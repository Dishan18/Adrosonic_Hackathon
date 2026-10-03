"""
Agent 4: Controlled Transformation Agent.

Runs ONLY after human approval.
Applies only approved transformations from the whitelist.
Produces:
  - Cleaned_SOV.xlsx (exactly 17 columns)
  - Audit_Log.xlsx (full transformation audit trail)

The LLM NEVER touches this agent. Pure deterministic code.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd

from app.schemas.state_models import (
    ActionType,
    AuditEntry,
    Recommendation,
    RecommendationStatus,
    SOVState,
    WorkflowStage,
)
from app.schemas.target_schema import TARGET_FIELDS
from app.processing.workbook import load_source_data, rename_and_coalesce
from app.processing.transformations import (
    WHITELISTED_OPERATIONS,
    apply_transformation_to_series,
)
from app.processing.validation import (
    enforce_column_order,
    validate_output_schema,
    TARGET_COLUMN_ORDER,
)
from app.audit.logger import create_audit_entry, export_audit_log_xlsx
from app.config import config

logger = logging.getLogger(__name__)


def _load_source_df(state: SOVState) -> Optional[pd.DataFrame]:
    """Load and extract all data sheets as one clean DataFrame."""
    if state.file_meta is None:
        return None
    return load_source_data(state)


def _apply_approved_transformations(
    source_df: pd.DataFrame,
    approved_recs: List[Recommendation],
) -> tuple[pd.DataFrame, List[AuditEntry]]:
    """
    Apply only approved transformations from the whitelist.
    Returns (transformed_df, audit_entries).

    THIS FUNCTION MUST NEVER:
    - fabricate missing values
    - apply unapproved operations
    - modify the original source_df
    """
    df = source_df.copy()
    audit_entries: List[AuditEntry] = []

    # Step 1: Apply column renames (from COLUMN_MAPPING recommendations).
    # Strongest approval first. A target can be claimed once per sheet: an
    # edited target may collide with another approved mapping, while columns
    # from different merged sheets may legitimately share a target.
    column_sheets = df.attrs.get("column_sheets", {})

    def sheets_of(col: str) -> set:
        return set(column_sheets.get(col, ["_single_"]))

    approved_mappings = sorted(
        (r for r in approved_recs
         if r.action_type == ActionType.COLUMN_MAPPING and r.status == RecommendationStatus.APPROVED),
        key=lambda r: -r.confidence,
    )
    pairs = []
    mapped_sources = set()
    claimed: dict = {}
    for rec in approved_mappings:
        src = rec.source_column
        tgt = rec.target_column
        if src not in df.columns or src in mapped_sources:
            continue
        if claimed.get(tgt, set()) & sheets_of(src):
            logger.warning(
                "Approved mapping '%s' → '%s' skipped: target already claimed by another approved mapping.",
                src, tgt,
            )
            continue
        claimed.setdefault(tgt, set()).update(sheets_of(src))
        mapped_sources.add(src)
        pairs.append((src, tgt))
        if src != tgt:
            audit_entries.append(create_audit_entry(
                source_column=src,
                target_column=tgt,
                transformation_applied="column_rename",
                before_value=f"Column '{src}'",
                after_value=f"Column '{tgt}'",
                confidence=rec.confidence,
                approved_by="human",
                recommendation_id=rec.id,
            ))

    # A source column that merely happens to carry a target name (e.g. "State",
    # "Other") must not reach the output unless its own mapping was approved —
    # otherwise rejected or unreviewed data leaks into Cleaned_SOV.
    stray = {
        c: f"_unmapped_{c}" for c in df.columns
        if c in TARGET_FIELDS and c not in mapped_sources
    }
    if stray:
        df = df.rename(columns=stray)
    if pairs:
        df = rename_and_coalesce(df, pairs)
        logger.info("Mapped columns: %s", pairs)

    # Step 2: Apply data transformations (STANDARDISATION / DATA_CORRECTION)
    for rec in approved_recs:
        if rec.action_type in (ActionType.STANDARDISATION, ActionType.DATA_CORRECTION):
            if rec.status != RecommendationStatus.APPROVED:
                continue

            target_col = rec.target_column
            operation = rec.operation

            if target_col not in df.columns:
                logger.warning("Target column '%s' not in DataFrame — skipping.", target_col)
                continue

            # Ensure single series if duplicate column exists with target_col name
            target_data = df[target_col]
            if isinstance(target_data, pd.DataFrame):
                best_idx = 0
                best_cnt = -1
                for i in range(target_data.shape[1]):
                    cnt = target_data.iloc[:, i].notna().sum()
                    if cnt > best_cnt:
                        best_cnt = cnt
                        best_idx = i
                other_cols = [c for c in df.columns if c != target_col]
                chosen_series = target_data.iloc[:, best_idx]
                df = df.loc[:, other_cols].copy()
                df[target_col] = chosen_series

            if operation not in WHITELISTED_OPERATIONS:
                logger.error(
                    "Operation '%s' not in whitelist — REFUSING to apply. Rec: %s",
                    operation, rec.id,
                )
                continue

            if operation == "flag_for_review":
                # No-op transformation
                continue

            try:
                # Snapshot before
                before_series = df[target_col].copy()
                if isinstance(before_series, pd.DataFrame):
                    before_series = before_series.iloc[:, 0]

                # Apply transformation (object dtype: mixed int/str/float
                # values must not be coerced by pandas' arrow-backed str dtype)
                before_obj = before_series.astype(object)
                after_series = apply_transformation_to_series(operation, before_obj).astype(object)

                # Count changed rows BEFORE writing back, so a failure here can
                # never leave an applied-but-unaudited change in the output.
                def _same(a, b) -> bool:
                    if pd.isna(a) and pd.isna(b):
                        return True
                    if pd.isna(a) or pd.isna(b):
                        return False
                    return a == b

                changed = [not _same(a, b) for a, b in zip(after_series, before_obj)]
                n_changed = int(sum(changed))

                # Summarize in one audit entry per recommendation, sampling a
                # row that actually changed
                first = changed.index(True) if n_changed else 0
                before_sample = str(before_obj.iloc[first]) if len(before_obj) > 0 else ""
                after_sample = str(after_series.iloc[first]) if len(after_series) > 0 else ""

                df[target_col] = after_series

                audit_entries.append(create_audit_entry(
                    source_column=rec.source_column,
                    target_column=target_col,
                    transformation_applied=operation,
                    before_value=f"{before_sample} (sample; {n_changed} rows changed)",
                    after_value=after_sample,
                    confidence=rec.confidence,
                    approved_by="human",
                    recommendation_id=rec.id,
                ))

                logger.info(
                    "Applied '%s' to '%s': %d rows changed.", operation, target_col, n_changed
                )

            except Exception as e:
                logger.error(
                    "Failed to apply '%s' to '%s': %s", operation, target_col, e
                )

    return df, audit_entries


def run_transformation(state: SOVState) -> SOVState:
    """
    LangGraph node: Agent 4 — Controlled Transformation.
    Reads: state (all previous stages)
    Writes: state.output_path, state.audit_log_path, state.validation_passed, state.audit_log
    """
    logger.info("Agent 4: Controlled Transformation starting.")
    state = state.model_copy(deep=True)
    state.stage = WorkflowStage.TRANSFORMING

    # Safety check: ensure all low-confidence recs have decisions
    if state.mappings is None:
        state.error_message = "No mappings available for transformation."
        state.stage = WorkflowStage.ERROR
        return state

    # Get only approved recommendations
    approved_recs = [
        r for r in state.recommendations
        if r.status == RecommendationStatus.APPROVED
    ]

    logger.info("Applying %d approved recommendations.", len(approved_recs))

    # Load source data
    source_df = _load_source_df(state)
    if source_df is None or source_df.empty:
        state.error_message = "Could not load source data for transformation."
        state.stage = WorkflowStage.ERROR
        return state

    # Apply transformations
    transformed_df, audit_entries = _apply_approved_transformations(source_df, approved_recs)

    # Enforce 17-column schema
    final_df = enforce_column_order(transformed_df)

    # Validate output
    passed, validation_errors = validate_output_schema(final_df)

    if not passed:
        logger.error("Output validation failed: %s", validation_errors)
        state.validation_passed = False
        state.validation_errors = validation_errors
        state.stage = WorkflowStage.VALIDATING
        # Still save audit log but not the cleaned SOV
    else:
        logger.info("Output validation passed.")
        state.validation_passed = True
        state.validation_errors = []

    # Export Cleaned_SOV.xlsx
    output_dir = Path(config.OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    session = state.session_id or "default"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    cleaned_path = str(output_dir / f"Cleaned_SOV_{session}_{ts}.xlsx")
    audit_path = str(output_dir / f"Audit_Log_{session}_{ts}.xlsx")

    # Convert to object dtype to preserve nulls cleanly
    for col in final_df.columns:
        final_df[col] = final_df[col].where(final_df[col].notna(), other=None)

    try:
        with pd.ExcelWriter(cleaned_path, engine="openpyxl") as writer:
            final_df.to_excel(writer, sheet_name="Cleaned_SOV", index=False)
            # Zip is an integer field; show leading zeros (802 → 00802)
            ws = writer.sheets["Cleaned_SOV"]
            zip_col = TARGET_COLUMN_ORDER.index("Zip") + 1
            for (cell,) in ws.iter_rows(min_row=2, min_col=zip_col, max_col=zip_col):
                if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
                    cell.number_format = "00000"
        logger.info("Cleaned_SOV.xlsx saved: %s", cleaned_path)
    except Exception as e:
        state.error_message = f"Failed to write Cleaned_SOV.xlsx: {e}"
        state.stage = WorkflowStage.ERROR
        return state

    # Export Audit_Log.xlsx
    try:
        export_audit_log_xlsx(audit_entries, audit_path)
    except Exception as e:
        logger.error("Audit log export failed: %s", e)

    # Schema conformance of the written file: no merged cells
    try:
        import openpyxl
        merged = len(openpyxl.load_workbook(cleaned_path)["Cleaned_SOV"].merged_cells.ranges)
        if merged:
            passed = False
            validation_errors.append(f"Cleaned_SOV.xlsx contains {merged} merged cell range(s).")
            state.validation_passed = False
            state.validation_errors = validation_errors
    except Exception as e:
        logger.warning("Merged-cell check on output failed: %s", e)

    # Required deliverable names (Cleaned_SOV.xlsx / Audit_Log.xlsx) next to the
    # timestamped copies, which are kept as history
    import shutil
    for src, name in ((cleaned_path, "Cleaned_SOV.xlsx"), (audit_path, "Audit_Log.xlsx")):
        try:
            if Path(src).exists():
                shutil.copyfile(src, output_dir / name)
        except Exception as e:  # e.g. the previous copy is open in Excel
            logger.warning("Could not write %s: %s", name, e)

    state.output_path = cleaned_path
    state.audit_log_path = audit_path
    state.audit_log = audit_entries
    state.stage = WorkflowStage.COMPLETE if passed else WorkflowStage.VALIDATING

    logger.info(
        "Agent 4 complete. Output: %s | Validation: %s",
        cleaned_path, "PASSED" if passed else "FAILED",
    )
    return state


def generate_preview_df(
    state: SOVState,
    approved_recs: Optional[List[Recommendation]] = None,
) -> pd.DataFrame:
    """
    Generate a preview DataFrame with proposed transformations applied.
    Does NOT write to disk. Used by the UI for before/after preview.
    """
    source_df = _load_source_df(state)
    if source_df is None or source_df.empty:
        return pd.DataFrame()

    recs = approved_recs or [
        r for r in state.recommendations
        if r.status == RecommendationStatus.APPROVED
    ]

    preview_df, _ = _apply_approved_transformations(source_df, recs)
    return enforce_column_order(preview_df)
