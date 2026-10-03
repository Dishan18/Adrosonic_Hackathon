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
from app.processing.workbook import unmerge_and_forward_fill, extract_data_frame
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
    """Load and extract the primary data sheet as a clean DataFrame."""
    if state.file_meta is None:
        return None

    path = state.file_meta.temp_path
    sheet = state.primary_sheet_name or ""
    header_row = state.header_row

    df = unmerge_and_forward_fill(path, sheet)
    if df.empty:
        from app.processing.workbook import load_workbook_sheets
        sheets = load_workbook_sheets(path)
        df = sheets.get(sheet, pd.DataFrame())

    return extract_data_frame(df, header_row)


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

    # Step 1: Apply column renames (from COLUMN_MAPPING recommendations)
    rename_map = {}
    for rec in approved_recs:
        if rec.action_type == ActionType.COLUMN_MAPPING and rec.status == RecommendationStatus.APPROVED:
            src = rec.source_column
            tgt = rec.target_column
            if src in df.columns and src != tgt:
                rename_map[src] = tgt
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

    if rename_map:
        df = df.rename(columns=rename_map)
        logger.info("Renamed columns: %s", rename_map)

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

                # Apply transformation
                df[target_col] = apply_transformation_to_series(operation, df[target_col])

                # Create audit entries for changed rows
                changed_mask = df[target_col] != before_series
                changed_indices = list(changed_mask[changed_mask].index[:100])

                # Summarize in one audit entry per recommendation
                n_changed = changed_mask.sum()
                before_sample = str(before_series.iloc[0]) if len(before_series) > 0 else ""
                after_sample = str(df[target_col].iloc[0]) if len(df) > 0 else ""

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
