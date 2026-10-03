"""
Agent 1: Sheet Intelligence and Discovery Agent.

Inspects every worksheet, scores and ranks sheets, detects header rows,
repairs structural issues, and returns a SheetManifest.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd

from app.schemas.state_models import (
    SheetClassification,
    SheetDiscoveryResult,
    SheetManifest,
    SheetProfile,
    SOVState,
    WorkflowStage,
)
from app.schemas.target_schema import TARGET_FIELDS, TARGET_SYNONYMS
from app.processing.workbook import (
    load_workbook_sheets,
    unmerge_and_forward_fill,
    detect_header_row,
    extract_data_frame,
    profile_dataframe,
    get_merged_cell_info,
)

logger = logging.getLogger(__name__)

# Scoring weights from PDF2
WEIGHT_HEADER_MATCH = 0.35
WEIGHT_DATA_DENSITY = 0.25
WEIGHT_TYPE_CONSISTENCY = 0.20
WEIGHT_ROW_VOLUME = 0.20

# Pre-build synonym lookup set
_ALL_SYNONYMS: Optional[set] = None


def _get_synonym_set() -> set:
    global _ALL_SYNONYMS
    if _ALL_SYNONYMS is None:
        s = set()
        for field in TARGET_FIELDS:
            s.add(field.lower())
            s.add(re.sub(r"[\s_\-\.#\(\)/]", " ", field.lower()).strip())
        for synonyms in TARGET_SYNONYMS.values():
            for syn in synonyms:
                s.add(syn.lower())
                s.add(re.sub(r"[\s_\-\.#\(\)/]", " ", syn.lower()).strip())
        _ALL_SYNONYMS = s
    return _ALL_SYNONYMS


# ---------------------------------------------------------------------------
# Sheet scoring
# ---------------------------------------------------------------------------

def _score_header_row(row: pd.Series, df: pd.DataFrame, row_idx: int) -> Tuple[float, int]:
    """
    Score a candidate header row.
    Returns (score, synonym_match_count).
    """
    synonyms = _get_synonym_set()
    non_null = row.dropna()
    if len(non_null) == 0:
        return 0.0, 0

    # Text ratio
    text_count = sum(
        1 for v in non_null
        if isinstance(v, str) and not _looks_numeric(str(v))
    )
    text_ratio = text_count / len(non_null)

    # Synonym matches
    match_count = 0
    for v in non_null:
        if isinstance(v, str):
            norm = re.sub(r"[\s_\-\.#\(\)/]", " ", v.lower()).strip()
            if norm in synonyms or v.lower() in synonyms:
                match_count += 1

    header_match = match_count / max(len(non_null), 1)

    # Fill ratio
    fill_ratio = len(non_null) / max(len(row), 1)

    # Data below has numeric content?
    data_below = 0.0
    if row_idx + 1 < len(df):
        below = df.iloc[row_idx + 1].dropna()
        numeric_below = sum(1 for v in below if _looks_numeric(str(v)))
        data_below = numeric_below / max(len(below), 1)

    score = (
        0.4 * header_match
        + 0.2 * text_ratio
        + 0.2 * fill_ratio
        + 0.2 * data_below
    )

    return score, match_count


def _find_best_header(df: pd.DataFrame, max_rows: int = 30) -> Tuple[int, float, int]:
    """
    Scan up to max_rows for the best header row.
    Returns (row_idx, score, synonym_match_count).
    """
    best_idx = 0
    best_score = -1.0
    best_matches = 0

    for i in range(min(max_rows, len(df))):
        score, matches = _score_header_row(df.iloc[i], df, i)
        if score > best_score:
            best_score = score
            best_idx = i
            best_matches = matches

    return best_idx, best_score, best_matches


def _compute_type_consistency(df: pd.DataFrame, header_row: int) -> float:
    """
    Estimate typed-data consistency below the header row.
    Score = fraction of columns that have consistent data types.
    """
    if header_row + 1 >= len(df):
        return 0.0

    data = df.iloc[header_row + 1:].head(200)
    if len(data) == 0:
        return 0.0

    consistent_cols = 0
    for col in data.columns:
        col_series = data[col]
        if isinstance(col_series, pd.DataFrame):
            col_series = col_series.iloc[:, 0]
        col_data = col_series.dropna().astype(str).str.strip()
        if len(col_data) == 0:
            continue
        numeric_count = sum(1 for v in col_data if _looks_numeric(v))
        ratio = numeric_count / len(col_data)
        # Either mostly numeric or mostly text = consistent
        if ratio > 0.80 or ratio < 0.20:
            consistent_cols += 1

    return consistent_cols / max(len(data.columns), 1)


def _compute_data_continuity(df: pd.DataFrame, header_row: int) -> float:
    """
    Fraction of non-blank data rows below the header.
    """
    if header_row + 1 >= len(df):
        return 0.0
    data = df.iloc[header_row + 1:].head(200)
    non_blank = data.dropna(how="all")
    return len(non_blank) / max(len(data), 1)


def score_sheet(
    sheet_name: str,
    df: pd.DataFrame,
    path: str,
) -> SheetDiscoveryResult:
    """
    Score and classify a single sheet.
    """
    reasoning: List[str] = []
    issues: List[str] = []

    # Handle empty sheets
    if df is None or df.empty:
        profile = SheetProfile(
            sheet_name=sheet_name, row_count=0, col_count=0,
            non_null_ratio=0.0, text_density=0.0, numeric_density=0.0,
            header_likeness=0.0, candidate_field_matches=0, data_continuity=0.0,
            merged_cell_count=0, typed_data_consistency=0.0, blank_row_count=0,
            total_row_count=0, metadata_row_count=0,
        )
        return SheetDiscoveryResult(
            sheet_name=sheet_name,
            classification=SheetClassification.REJECT,
            header_row=0,
            confidence=0.0,
            reasoning=["Sheet is empty."],
            profile=profile,
            issues=["Empty sheet"],
        )

    # Unmerge and forward fill
    clean_df = unmerge_and_forward_fill(path, sheet_name)
    if clean_df.empty:
        clean_df = df

    # Get merged cell info
    merged = get_merged_cell_info(path, sheet_name)

    # Profile raw data
    raw_profile = profile_dataframe(clean_df)

    # Find best header
    header_row_idx, header_score, synonym_matches = _find_best_header(clean_df)

    # Compute structural metrics
    type_consistency = _compute_type_consistency(clean_df, header_row_idx)
    data_continuity = _compute_data_continuity(clean_df, header_row_idx)

    data_below_header = len(clean_df) - header_row_idx - 1
    row_volume_score = min(1.0, data_below_header / 100.0)  # normalize to 100 rows

    # Header match score
    header_match_score = min(1.0, synonym_matches / max(1, len(TARGET_FIELDS)) * 3)

    # Data density
    data_density = raw_profile.get("non_null_ratio", 0.0)

    # Composite score
    composite = (
        WEIGHT_HEADER_MATCH * header_match_score
        + WEIGHT_DATA_DENSITY * data_density
        + WEIGHT_TYPE_CONSISTENCY * type_consistency
        + WEIGHT_ROW_VOLUME * row_volume_score
    )

    # Classification
    if composite >= 0.45 and synonym_matches >= 3:
        classification = SheetClassification.PRIMARY
    elif composite >= 0.25 or synonym_matches >= 1:
        classification = SheetClassification.SECONDARY
    else:
        classification = SheetClassification.REJECT

    # Build reasoning
    reasoning.append(f"Header row detected at row {header_row_idx} (0-indexed).")
    reasoning.append(f"Synonym field matches: {synonym_matches} out of {len(TARGET_FIELDS)} target fields.")
    reasoning.append(f"Header match score: {header_match_score:.2f}, Data density: {data_density:.2f}.")
    reasoning.append(f"Type consistency: {type_consistency:.2f}, Data continuity: {data_continuity:.2f}.")
    reasoning.append(f"Data rows below header: {data_below_header}.")
    reasoning.append(f"Composite score: {composite:.3f} → {classification.value}.")

    if merged:
        reasoning.append(f"Merged cells detected ({len(merged)} ranges) — unmerged for processing.")

    if synonym_matches < 2:
        issues.append(f"Very few SOV field matches ({synonym_matches}) — may not be a SOV sheet.")

    if data_below_header < 5:
        issues.append("Fewer than 5 data rows below the detected header.")

    profile = SheetProfile(
        sheet_name=sheet_name,
        row_count=len(clean_df),
        col_count=len(clean_df.columns),
        non_null_ratio=raw_profile.get("non_null_ratio", 0.0),
        text_density=raw_profile.get("text_density", 0.0),
        numeric_density=raw_profile.get("numeric_density", 0.0),
        header_likeness=header_score,
        candidate_field_matches=synonym_matches,
        data_continuity=data_continuity,
        merged_cell_count=len(merged),
        typed_data_consistency=type_consistency,
        blank_row_count=raw_profile.get("blank_row_count", 0),
        total_row_count=len(clean_df),
        metadata_row_count=header_row_idx,
        score=composite,
    )

    return SheetDiscoveryResult(
        sheet_name=sheet_name,
        classification=classification,
        header_row=header_row_idx,
        confidence=round(composite, 4),
        reasoning=reasoning,
        profile=profile,
        issues=issues,
    )


# ---------------------------------------------------------------------------
# Agent 1 node function
# ---------------------------------------------------------------------------

def run_sheet_discovery(state: SOVState) -> SOVState:
    """
    LangGraph node: Agent 1 — Sheet Intelligence and Discovery.
    Reads: state.file_meta
    Writes: state.sheet_manifest, state.header_row, state.primary_sheet_name
    """
    logger.info("Agent 1: Sheet Discovery starting.")
    state = state.model_copy(deep=True)
    state.stage = WorkflowStage.DISCOVERING

    if state.file_meta is None:
        state.error_message = "No file metadata found. Please upload a file first."
        state.stage = WorkflowStage.ERROR
        return state

    path = state.file_meta.temp_path

    try:
        raw_sheets = load_workbook_sheets(path)
    except ValueError as e:
        state.error_message = str(e)
        state.stage = WorkflowStage.ERROR
        return state

    if not raw_sheets:
        state.error_message = "No readable sheets found in the uploaded file."
        state.stage = WorkflowStage.ERROR
        return state

    # Score each sheet
    results: List[SheetDiscoveryResult] = []
    for sheet_name, df in raw_sheets.items():
        logger.info("Scoring sheet: %s", sheet_name)
        result = score_sheet(sheet_name, df, path)
        results.append(result)
        logger.info(
            "  → %s (confidence=%.3f, header_row=%d)",
            result.classification, result.confidence, result.header_row,
        )

    # Sort: Primary first, then by confidence
    results.sort(key=lambda r: (
        0 if r.classification == SheetClassification.PRIMARY else
        1 if r.classification == SheetClassification.SECONDARY else 2,
        -r.confidence,
    ))

    # Select primary sheet
    primary = next(
        (r for r in results if r.classification == SheetClassification.PRIMARY),
        results[0] if results else None,
    )

    if primary is None:
        state.error_message = "Could not identify a primary SOV data sheet."
        state.stage = WorkflowStage.ERROR
        return state

    manifest = SheetManifest(
        sheets=results,
        primary_sheet=primary.sheet_name,
        header_row=primary.header_row,
    )

    state.sheet_manifest = manifest
    state.header_row = primary.header_row
    state.primary_sheet_name = primary.sheet_name
    # Every sheet classified Primary is SOV location data; they are merged into
    # one output. The best-scoring sheet comes first.
    state.data_sheets = [primary.sheet_name] + [
        r.sheet_name for r in results
        if r.classification == SheetClassification.PRIMARY and r.sheet_name != primary.sheet_name
    ]
    state.stage = WorkflowStage.DISCOVERED

    logger.info(
        "Agent 1 complete. Primary sheet: '%s', header row: %d, confidence: %.3f. Data sheets: %s",
        primary.sheet_name, primary.header_row, primary.confidence, state.data_sheets,
    )
    return state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _looks_numeric(s: str) -> bool:
    s = str(s).strip().replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        float(s)
        return True
    except ValueError:
        return False
