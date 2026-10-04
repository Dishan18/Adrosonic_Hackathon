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
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

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
    state: Optional["SOVState"] = None,
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

    # Explicitly drop any source column whose mapping recommendation was rejected by the reviewer
    if state and getattr(state, "recommendations", None):
        for rec in state.recommendations:
            if rec.action_type == ActionType.COLUMN_MAPPING and rec.status == RecommendationStatus.REJECTED:
                src_col = rec.source_column
                dropped = False
                for c_name in [src_col, f"_unmapped_{src_col}"]:
                    if c_name in df.columns:
                        df = df.drop(columns=[c_name])
                        dropped = True
                if dropped:
                    logger.info("Rejected column '%s' — dropped from output.", src_col)
                    audit_entries.append(create_audit_entry(
                        source_column=src_col,
                        target_column="",
                        transformation_applied="column_rejected_dropped",
                        before_value=f"Column '{src_col}'",
                        after_value="Dropped (rejected by reviewer)",
                        confidence=1.0,
                        approved_by="human",
                        recommendation_id=None,
                    ))

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

    # Step 3: Handle unclaimed column decisions (manual assign / reject from human review).
    # Group assignments by target field first so that multiple source columns assigned to the
    # same target are always space-merged, whether or not that target was already populated.
    unclaimed = getattr(state, "unclaimed_decisions", {}) or {}

    if unclaimed:
        # Build target → [source_cols] groups (preserve insertion order)
        from collections import defaultdict
        assign_groups: dict = defaultdict(list)
        reject_cols: list = []

        for src_col, decision in unclaimed.items():
            if decision == "__rejected__":
                reject_cols.append(src_col)
            elif decision:  # non-empty target name
                assign_groups[decision].append(src_col)

        # Drop rejected columns
        for src_col in reject_cols:
            if src_col in df.columns:
                df = df.drop(columns=[src_col])
                logger.info("Unclaimed column '%s' rejected — dropped.", src_col)
                audit_entries.append(create_audit_entry(
                    source_column=src_col,
                    target_column="",
                    transformation_applied="unclaimed_reject",
                    before_value=f"Column '{src_col}'",
                    after_value="Dropped (rejected by reviewer)",
                    confidence=1.0,
                    approved_by="human",
                    recommendation_id=None,
                ))

        # Process each target group
        for tgt_field, src_cols in assign_groups.items():
            # Filter to columns that still exist
            src_cols = [c for c in src_cols if c in df.columns]
            if not src_cols:
                continue

            def _safe_str(s: pd.Series) -> pd.Series:
                """Convert to str, but keep NaN as actual NaN (not the string 'nan')."""
                return s.where(s.isna(), s.astype(str))

            def _merge_series(left: pd.Series, right: pd.Series) -> pd.Series:
                """Space-concatenate two series, ignoring NaN on either side."""
                l_str = _safe_str(left)
                r_str = _safe_str(right)
                result = pd.Series(index=left.index, dtype=object)
                both_valid   = l_str.notna() & r_str.notna()
                only_left    = l_str.notna() & r_str.isna()
                only_right   = l_str.isna()  & r_str.notna()
                result[both_valid]  = l_str[both_valid] + " " + r_str[both_valid]
                result[only_left]   = l_str[only_left]
                result[only_right]  = r_str[only_right]
                return result

            # Base: use existing target column if already populated, else use first source col
            if tgt_field in df.columns:
                accumulator = df[tgt_field].copy()
                for src_col in src_cols:
                    accumulator = _merge_series(accumulator, df[src_col])
                    df = df.drop(columns=[src_col])
                df[tgt_field] = accumulator
                logger.info(
                    "Unclaimed column(s) %s merged into existing target '%s'.", src_cols, tgt_field
                )
            else:
                # Target did not exist: first source becomes the base via rename
                first_src = src_cols[0]
                df = df.rename(columns={first_src: tgt_field})
                accumulator = df[tgt_field].copy()
                for src_col in src_cols[1:]:
                    accumulator = _merge_series(accumulator, df[src_col])
                    df = df.drop(columns=[src_col])
                df[tgt_field] = accumulator
                logger.info(
                    "Unclaimed column(s) %s assigned/merged into new target '%s'.", src_cols, tgt_field
                )

            audit_entries.append(create_audit_entry(
                source_column=", ".join(assign_groups[tgt_field]),
                target_column=tgt_field,
                transformation_applied="unclaimed_manual_assign",
                before_value=f"Unmapped column(s): {', '.join(assign_groups[tgt_field])}",
                after_value=f"Merged into '{tgt_field}' (space-separated)",
                confidence=1.0,
                approved_by="human",
                recommendation_id=None,
            ))

    return df, audit_entries


def _clean_sheet_name(sheet_name: str) -> str:
    cleaned = re.sub(r'[^\w\-.]+', '_', sheet_name.strip())
    return cleaned.strip('_')


def _execute_transformation_on_state(
    state: SOVState,
    sheet_suffix: Optional[str] = None,
) -> SOVState:
    """
    Execute transformation and schema validation on a single sheet context.
    If sheet_suffix is provided, files are named Cleaned_SOV_{sheet_suffix}.xlsx.
    Otherwise, standard names Cleaned_SOV.xlsx are used.
    """
    state = state.model_copy(deep=True)
    state.stage = WorkflowStage.TRANSFORMING

    if state.mappings is None:
        state.error_message = "No mappings available for transformation."
        state.stage = WorkflowStage.ERROR
        return state

    approved_recs = [
        r for r in state.recommendations
        if r.status == RecommendationStatus.APPROVED
    ]
    logger.info("Applying %d approved recommendations for sheet '%s'.", len(approved_recs), sheet_suffix or "default")

    source_df = _load_source_df(state)
    if source_df is None or source_df.empty:
        state.error_message = "Could not load source data for transformation."
        state.stage = WorkflowStage.ERROR
        return state

    transformed_df, audit_entries = _apply_approved_transformations(source_df, approved_recs, state=state)
    final_df = enforce_column_order(transformed_df)
    passed, validation_errors = validate_output_schema(final_df)

    if not passed:
        logger.error("Output validation failed: %s", validation_errors)
        state.validation_passed = False
        state.validation_errors = validation_errors
        state.stage = WorkflowStage.VALIDATING
    else:
        logger.info("Output validation passed.")
        state.validation_passed = True
        state.validation_errors = []

    output_dir = Path(config.OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    session = state.session_id or "default"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    prefix = f"_{sheet_suffix}" if sheet_suffix else ""
    cleaned_path = str(output_dir / f"Cleaned_SOV{prefix}_{session}_{ts}.xlsx")
    audit_path = str(output_dir / f"Audit_Log{prefix}_{session}_{ts}.xlsx")
    deliverable_cleaned_name = f"Cleaned_SOV{prefix}.xlsx"
    deliverable_audit_name = f"Audit_Log{prefix}.xlsx"

    for col in final_df.columns:
        final_df[col] = final_df[col].where(final_df[col].notna(), other=None)

    try:
        with pd.ExcelWriter(cleaned_path, engine="openpyxl") as writer:
            final_df.to_excel(writer, sheet_name="Cleaned_SOV", index=False)
            ws = writer.sheets["Cleaned_SOV"]
            zip_col = TARGET_COLUMN_ORDER.index("Zip") + 1
            for (cell,) in ws.iter_rows(min_row=2, min_col=zip_col, max_col=zip_col):
                if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
                    cell.number_format = "00000"
        logger.info("%s saved: %s", deliverable_cleaned_name, cleaned_path)
    except Exception as e:
        state.error_message = f"Failed to write {deliverable_cleaned_name}: {e}"
        state.stage = WorkflowStage.ERROR
        return state

    try:
        export_audit_log_xlsx(audit_entries, audit_path)
    except Exception as e:
        logger.error("Audit log export failed: %s", e)

    try:
        import openpyxl
        merged = len(openpyxl.load_workbook(cleaned_path)["Cleaned_SOV"].merged_cells.ranges)
        if merged:
            passed = False
            validation_errors.append(f"{deliverable_cleaned_name} contains {merged} merged cell range(s).")
            state.validation_passed = False
            state.validation_errors = validation_errors
    except Exception as e:
        logger.warning("Merged-cell check on output failed: %s", e)

    import shutil
    deliverable_cleaned_path = output_dir / deliverable_cleaned_name
    deliverable_audit_path = output_dir / deliverable_audit_name
    for src, dst in ((cleaned_path, deliverable_cleaned_path), (audit_path, deliverable_audit_path)):
        try:
            if Path(src).exists():
                shutil.copyfile(src, dst)
        except Exception as e:
            logger.warning("Could not write %s: %s", dst.name, e)

    state.output_path = str(deliverable_cleaned_path)
    state.audit_log_path = str(deliverable_audit_path)
    state.audit_log = audit_entries
    state.stage = WorkflowStage.COMPLETE if passed else WorkflowStage.VALIDATING
    return state


def run_transformation(state: SOVState) -> SOVState:
    """
    LangGraph node: Agent 4 — Controlled Transformation.
    Reads: state (all previous stages)
    Writes: state.output_path, state.audit_log_path, state.output_paths, state.audit_log_paths,
            state.validation_passed, state.audit_log
    """
    logger.info("Agent 4: Controlled Transformation starting.")
    state = state.model_copy(deep=True)
    state.stage = WorkflowStage.TRANSFORMING

    # Multi-sheet case: each PRIMARY sheet is transformed independently
    if getattr(state, "sheet_states", None) and len(state.sheet_states) > 1:
        logger.info("Agent 4: Transforming %d sheets independently.", len(state.sheet_states))
        output_paths: Dict[str, str] = {}
        audit_log_paths: Dict[str, str] = {}
        all_audit_entries: List[AuditEntry] = []
        all_passed = True
        all_errors: List[str] = []

        rec_status_by_id = {r.id: r.status for r in state.recommendations}

        for sheet_name, sub_state in list(state.sheet_states.items()):
            if rec_status_by_id:
                sub_state.recommendations = [
                    r.model_copy(update={"status": rec_status_by_id.get(r.id, r.status)})
                    for r in sub_state.recommendations
                ]
            sub_state.unclaimed_decisions = state.unclaimed_decisions
            sub_state.file_meta = state.file_meta
            sub_state.sheet_manifest = state.sheet_manifest

            clean_suffix = _clean_sheet_name(sheet_name)
            transformed_sub = _execute_transformation_on_state(sub_state, sheet_suffix=clean_suffix)
            state.sheet_states[sheet_name] = transformed_sub

            if transformed_sub.output_path:
                output_paths[sheet_name] = transformed_sub.output_path
            if transformed_sub.audit_log_path:
                audit_log_paths[sheet_name] = transformed_sub.audit_log_path
            all_audit_entries.extend(transformed_sub.audit_log)
            if not transformed_sub.validation_passed:
                all_passed = False
                all_errors.extend([f"[{sheet_name}] {e}" for e in transformed_sub.validation_errors])

        primary_name = state.primary_sheet_name or next(iter(state.sheet_states))
        primary_sub = state.sheet_states[primary_name]

        # Explicit compatibility alias to the selected primary deliverable
        output_dir = Path(config.OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        import shutil
        if primary_sub.output_path and Path(primary_sub.output_path).exists():
            try:
                shutil.copyfile(primary_sub.output_path, output_dir / "Cleaned_SOV.xlsx")
            except Exception as e:
                logger.warning("Could not write Cleaned_SOV.xlsx alias: %s", e)
        if primary_sub.audit_log_path and Path(primary_sub.audit_log_path).exists():
            try:
                shutil.copyfile(primary_sub.audit_log_path, output_dir / "Audit_Log.xlsx")
            except Exception as e:
                logger.warning("Could not write Audit_Log.xlsx alias: %s", e)

        state.output_path = primary_sub.output_path
        state.audit_log_path = primary_sub.audit_log_path
        state.output_paths = output_paths
        state.audit_log_paths = audit_log_paths
        state.audit_log = all_audit_entries
        state.validation_passed = all_passed
        state.validation_errors = all_errors
        state.stage = WorkflowStage.COMPLETE if all_passed else WorkflowStage.VALIDATING

        logger.info(
            "Agent 4 multi-sheet complete (%d sheets). Primary: %s | Validation: %s",
            len(output_paths), state.output_path, "PASSED" if all_passed else "FAILED",
        )
        return state

    # Single-sheet case
    transformed = _execute_transformation_on_state(state, sheet_suffix=None)
    if transformed.output_path:
        transformed.output_paths = {transformed.primary_sheet_name or "Cleaned_SOV": transformed.output_path}
    if transformed.audit_log_path:
        transformed.audit_log_paths = {transformed.primary_sheet_name or "Cleaned_SOV": transformed.audit_log_path}
    return transformed


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
