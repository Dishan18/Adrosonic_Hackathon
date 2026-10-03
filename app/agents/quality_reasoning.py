"""
Agent 3: Data Quality and Reasoning Agent.

Part A: Deterministic quality detection
Part B: LLM reasoning/explanation and recommendation generation

The LLM never modifies data; it only explains, recommends, and selects
from the whitelist of transformations.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from app.schemas.state_models import (
    ActionType,
    QualityIssue,
    QualityReport,
    Recommendation,
    RecommendationStatus,
    Severity,
    SOVState,
    WorkflowStage,
)
from app.schemas.target_schema import (
    MONETARY_FIELDS,
    TARGET_FIELDS,
    VALID_SPRINKLER_CODES,
    US_STATE_ABBREVS,
    INTEGER_FIELDS,
    STRING_FIELDS,
)
from app.processing.workbook import unmerge_and_forward_fill, extract_data_frame
from app.processing.transformations import (
    WHITELISTED_OPERATIONS,
    suggest_operation_for_target,
)

logger = logging.getLogger(__name__)
CURRENT_YEAR = datetime.now().year


# ---------------------------------------------------------------------------
# Part A: Deterministic quality detection rules
# ---------------------------------------------------------------------------

def _get_mapped_df(state: SOVState) -> Optional[pd.DataFrame]:
    """Load and rename DataFrame according to current approved mappings."""
    if state.file_meta is None or state.mappings is None:
        return None

    path = state.file_meta.temp_path
    sheet = state.primary_sheet_name or ""
    header_row = state.header_row

    df = unmerge_and_forward_fill(path, sheet)
    if df.empty:
        return None

    data_df = extract_data_frame(df, header_row)

    # Rename according to mappings
    rename_map = {
        m.source_column: m.target
        for m in state.mappings.mappings
        if m.target is not None and m.source_column in data_df.columns
    }
    data_df = data_df.rename(columns=rename_map)
    return data_df


def detect_quality_issues(
    data_df: pd.DataFrame,
    mappings,
) -> List[QualityIssue]:
    """
    Run all deterministic quality rules against the mapped DataFrame.
    Returns a list of QualityIssue objects.
    """
    issues: List[QualityIssue] = []
    issue_counter = [0]

    def new_id():
        issue_counter[0] += 1
        return f"QI-{issue_counter[0]:04d}"

    # --- 1. Completeness ---
    for field in TARGET_FIELDS:
        if field not in data_df.columns:
            continue
        col = data_df[field]
        null_count = col.isna().sum() + (col == "").sum()
        total = len(col)
        if total == 0:
            continue
        null_pct = null_count / total * 100

        if null_pct > 50:
            severity = Severity.HIGH
        elif null_pct > 20:
            severity = Severity.MEDIUM
        elif null_pct > 5:
            severity = Severity.LOW
        else:
            continue

        issues.append(QualityIssue(
            issue_id=new_id(),
            issue_type="completeness",
            severity=severity,
            affected_field=field,
            affected_rows=[],
            affected_row_count=int(null_count),
            evidence=f"{field}: {null_count}/{total} ({null_pct:.1f}%) values are null/empty.",
            before_example="<null>",
            suggested_operation="flag_for_review",
            confidence=1.0,
        ))

    # --- 2. Monetary field validation ---
    for field in MONETARY_FIELDS:
        if field not in data_df.columns:
            continue
        col = data_df[field].dropna()
        if len(col) == 0:
            continue

        # Detect currency symbols
        has_currency = col.astype(str).str.contains(r"[\$,]", regex=True)
        currency_count = int(has_currency.sum())
        if currency_count > 0:
            sample = col[has_currency].astype(str).iloc[0]
            issues.append(QualityIssue(
                issue_id=new_id(),
                issue_type="format",
                severity=Severity.MEDIUM,
                affected_field=field,
                affected_rows=[],
                affected_row_count=currency_count,
                evidence=f"{field}: {currency_count} rows contain currency symbols/commas.",
                before_example=sample,
                suggested_operation="strip_currency",
                confidence=0.98,
            ))

        # Detect negative values
        def parse_monetary(v):
            try:
                return float(str(v).replace("$", "").replace(",", "").strip())
            except Exception:
                return None

        parsed = col.apply(parse_monetary)
        neg_rows = list(parsed[parsed < 0].index)
        if neg_rows:
            sample_neg = str(col.iloc[neg_rows[0]])
            issues.append(QualityIssue(
                issue_id=new_id(),
                issue_type="logical_error",
                severity=Severity.HIGH,
                affected_field=field,
                affected_rows=neg_rows[:50],
                affected_row_count=len(neg_rows),
                evidence=f"{field}: {len(neg_rows)} rows have negative monetary values.",
                before_example=sample_neg,
                suggested_operation="flag_for_review",
                confidence=1.0,
            ))

    # --- 3. Year Built validation ---
    if "Year Built" in data_df.columns:
        col = data_df["Year Built"].dropna()
        bad_rows = []
        for idx, v in col.items():
            try:
                yr = int(float(str(v).replace(",", "")))
                if yr > CURRENT_YEAR or yr < 1700:
                    bad_rows.append(idx)
            except Exception:
                bad_rows.append(idx)

        if bad_rows:
            sample = str(data_df["Year Built"].iloc[bad_rows[0]])
            issues.append(QualityIssue(
                issue_id=new_id(),
                issue_type="logical_error",
                severity=Severity.HIGH,
                affected_field="Year Built",
                affected_rows=bad_rows[:50],
                affected_row_count=len(bad_rows),
                evidence=f"Year Built: {len(bad_rows)} rows have invalid years (expected 1700–{CURRENT_YEAR}).",
                before_example=sample,
                suggested_operation="to_year_int",
                confidence=1.0,
            ))

    # --- 4. Storeys validation ---
    if "Storeys" in data_df.columns:
        col = data_df["Storeys"].dropna()
        bad_rows = []
        for idx, v in col.items():
            try:
                s = float(str(v).replace(",", ""))
                if s < 1:
                    bad_rows.append(idx)
            except Exception:
                bad_rows.append(idx)

        if bad_rows:
            sample = str(data_df["Storeys"].iloc[bad_rows[0]])
            issues.append(QualityIssue(
                issue_id=new_id(),
                issue_type="logical_error",
                severity=Severity.MEDIUM,
                affected_field="Storeys",
                affected_rows=bad_rows[:50],
                affected_row_count=len(bad_rows),
                evidence=f"Storeys: {len(bad_rows)} rows have values < 1.",
                before_example=sample,
                suggested_operation="flag_for_review",
                confidence=0.95,
            ))

    # --- 5. Number of Buildings ---
    if "Number of Buildings" in data_df.columns:
        col = data_df["Number of Buildings"].dropna()
        bad_rows = []
        for idx, v in col.items():
            try:
                n = float(str(v).replace(",", ""))
                if n < 1:
                    bad_rows.append(idx)
            except Exception:
                pass

        if bad_rows:
            issues.append(QualityIssue(
                issue_id=new_id(),
                issue_type="logical_error",
                severity=Severity.MEDIUM,
                affected_field="Number of Buildings",
                affected_rows=bad_rows[:50],
                affected_row_count=len(bad_rows),
                evidence=f"Number of Buildings: {len(bad_rows)} rows have values < 1.",
                before_example=str(data_df["Number of Buildings"].iloc[bad_rows[0]]),
                suggested_operation="flag_for_review",
                confidence=0.95,
            ))

    # --- 6. Fire Sprinklers validation ---
    if "Fire Sprinklers (Y/N)" in data_df.columns:
        col = data_df["Fire Sprinklers (Y/N)"].dropna()
        bad_vals = col[~col.astype(str).str.strip().str.upper().isin(VALID_SPRINKLER_CODES)]
        if len(bad_vals) > 0:
            sample = str(bad_vals.iloc[0])
            # Group by unique bad values
            unique_bad = bad_vals.astype(str).str.strip().unique()
            issues.append(QualityIssue(
                issue_id=new_id(),
                issue_type="format",
                severity=Severity.MEDIUM,
                affected_field="Fire Sprinklers (Y/N)",
                affected_rows=list(bad_vals.index[:50]),
                affected_row_count=len(bad_vals),
                evidence=(
                    f"Fire Sprinklers (Y/N): {len(bad_vals)} rows have non-standard codes: "
                    f"{', '.join(unique_bad[:5])}."
                ),
                before_example=sample,
                suggested_operation="normalize_sprinkler_code",
                confidence=0.95,
            ))

    # --- 7. State validation ---
    if "State" in data_df.columns:
        col = data_df["State"].dropna()
        bad_states = col[~col.astype(str).str.strip().str.upper().isin(US_STATE_ABBREVS)]
        if len(bad_states) > 0:
            # Distinguish full state names from garbage
            unique_bad = bad_states.astype(str).str.strip().unique()
            sample = str(bad_states.iloc[0])
            issues.append(QualityIssue(
                issue_id=new_id(),
                issue_type="format",
                severity=Severity.MEDIUM,
                affected_field="State",
                affected_rows=list(bad_states.index[:50]),
                affected_row_count=len(bad_states),
                evidence=f"State: {len(bad_states)} rows have non-standard values: {', '.join(str(x) for x in unique_bad[:5])}.",
                before_example=sample,
                suggested_operation="state_to_abbrev",
                confidence=0.90,
            ))

    # --- 8. Duplicate Reference IDs ---
    if "Reference" in data_df.columns:
        col = data_df["Reference"].dropna()
        dupes = col[col.duplicated(keep=False)]
        if len(dupes) > 0:
            dup_vals = dupes.unique()[:5]
            issues.append(QualityIssue(
                issue_id=new_id(),
                issue_type="duplicate",
                severity=Severity.HIGH,
                affected_field="Reference",
                affected_rows=list(dupes.index[:50]),
                affected_row_count=len(dupes),
                evidence=f"Reference: {len(dupes)} rows have duplicate IDs: {', '.join(str(v) for v in dup_vals)}.",
                before_example=str(dupes.iloc[0]),
                suggested_operation="flag_for_review",
                confidence=1.0,
            ))

    # --- 9. Zip validation ---
    if "Zip" in data_df.columns:
        col = data_df["Zip"].dropna()
        bad_zip = []
        for idx, v in col.items():
            s = str(v).strip().replace(",", "")
            digits = re.sub(r"\D", "", s.split(".")[0])
            if len(digits) != 5:
                bad_zip.append(idx)

        if bad_zip:
            sample = str(data_df["Zip"].iloc[bad_zip[0]])
            issues.append(QualityIssue(
                issue_id=new_id(),
                issue_type="format",
                severity=Severity.LOW,
                affected_field="Zip",
                affected_rows=bad_zip[:50],
                affected_row_count=len(bad_zip),
                evidence=f"Zip: {len(bad_zip)} rows have non-5-digit ZIP codes.",
                before_example=sample,
                suggested_operation="to_zip",
                confidence=0.90,
            ))

    # --- 10. Integer fields non-integer values ---
    for field in INTEGER_FIELDS:
        if field not in data_df.columns:
            continue
        col = data_df[field].dropna()
        non_int = []
        for idx, v in col.items():
            s = str(v).strip().replace(",", "")
            try:
                f = float(s)
                if f != int(f):
                    non_int.append(idx)
            except Exception:
                non_int.append(idx)

        if non_int:
            issues.append(QualityIssue(
                issue_id=new_id(),
                issue_type="type_error",
                severity=Severity.LOW,
                affected_field=field,
                affected_rows=non_int[:50],
                affected_row_count=len(non_int),
                evidence=f"{field}: {len(non_int)} rows have non-integer values.",
                before_example=str(data_df[field].iloc[non_int[0]]),
                suggested_operation="to_int",
                confidence=0.95,
            ))

    return issues


def compute_completeness(data_df: pd.DataFrame) -> Dict[str, float]:
    """Return per-field non-null percentage."""
    result = {}
    for field in TARGET_FIELDS:
        if field in data_df.columns:
            total = len(data_df)
            if total == 0:
                result[field] = 0.0
            else:
                non_null = data_df[field].notna().sum()
                result[field] = round(non_null / total * 100, 2)
        else:
            result[field] = 0.0
    return result


def compute_quality_score(
    issues: List[QualityIssue],
    completeness: Dict[str, float],
    mappings,
) -> float:
    """
    Aggregate SOV quality score from:
    - mapping confidence
    - completeness
    - anomaly count/severity
    """
    # Mapping score
    if mappings and mappings.mappings:
        mapped = [m for m in mappings.mappings if m.target is not None]
        mapping_score = sum(m.confidence for m in mapped) / max(len(TARGET_FIELDS), 1)
    else:
        mapping_score = 0.0

    # Completeness score
    if completeness:
        comp_score = sum(v for v in completeness.values() if v > 0) / (len(TARGET_FIELDS) * 100)
    else:
        comp_score = 0.0

    # Anomaly penalty
    severity_weights = {Severity.HIGH: 0.15, Severity.MEDIUM: 0.05, Severity.LOW: 0.02, Severity.INFO: 0.0}
    penalty = sum(severity_weights.get(i.severity, 0) for i in issues)
    anomaly_score = max(0.0, 1.0 - penalty)

    # Weighted composite
    score = (
        0.35 * mapping_score
        + 0.30 * comp_score
        + 0.35 * anomaly_score
    )
    return round(min(1.0, max(0.0, score)) * 100, 1)  # 0–100


# ---------------------------------------------------------------------------
# Part B: LLM reasoning and recommendation generation
# ---------------------------------------------------------------------------

def _generate_recommendation_from_issue(
    issue: QualityIssue,
    data_df: pd.DataFrame,
) -> Recommendation:
    """Create a Recommendation from a QualityIssue (deterministic base)."""
    # Determine source/target columns
    source_col = issue.affected_field
    target_col = issue.affected_field

    # Map issue to action type
    if issue.issue_type == "completeness":
        action = ActionType.FLAG_FOR_REVIEW
    elif issue.issue_type in ("format", "type_error"):
        action = ActionType.STANDARDISATION
    elif issue.issue_type == "logical_error":
        if issue.suggested_operation == "flag_for_review":
            action = ActionType.FLAG_FOR_REVIEW
        else:
            action = ActionType.DATA_CORRECTION
    elif issue.issue_type == "duplicate":
        action = ActionType.FLAG_FOR_REVIEW
    else:
        action = ActionType.FLAG_FOR_REVIEW

    # Compute after_example
    if issue.suggested_operation != "flag_for_review" and issue.before_example:
        from app.processing.transformations import apply_transformation
        try:
            after = apply_transformation(issue.suggested_operation, issue.before_example)
            after_example = str(after) if after is not None else issue.before_example
        except Exception:
            after_example = issue.before_example
    else:
        after_example = "[flagged — no transformation applied]"

    return Recommendation(
        id=f"REC-{uuid.uuid4().hex[:8].upper()}",
        action_type=action,
        source_column=source_col,
        target_column=target_col,
        operation=issue.suggested_operation,
        before_example=issue.before_example,
        after_example=after_example,
        rationale=issue.evidence,
        confidence=issue.confidence,
        uncertainty="",
        affected_rows=issue.affected_row_count,
        affected_row_indices=issue.affected_rows,
        status=RecommendationStatus.PENDING,
        issue_id=issue.issue_id,
        review_required=issue.confidence < 0.90 or issue.severity in (Severity.HIGH, Severity.MEDIUM),
    )


def _llm_explain_issues(
    issues: List[QualityIssue],
    recommendations: List[Recommendation],
    feedback: Optional[str] = None,
) -> List[Recommendation]:
    """
    Use LLM to enhance recommendations with explanations and uncertainty.
    Groups issues by type to avoid per-row LLM calls.
    Returns enriched recommendations.
    """
    try:
        from app.services.llm.gateway import get_llm
        from app.config import config

        llm = get_llm()
        if not llm.available:
            logger.info("LLM not available — using deterministic recommendations only.")
            return recommendations

        # Group issues for batch explanation (avoid per-row calls)
        issue_summary = "\n".join(
            f"- [{i.severity.upper()}] {i.issue_type} in '{i.affected_field}': {i.evidence}"
            for i in issues[:15]  # Cap to prevent huge prompts
        )

        rec_summary = "\n".join(
            f"- REC {r.id}: {r.action_type.value} on '{r.source_column}' — operation: {r.operation}"
            for r in recommendations[:15]
        )

        feedback_section = f"\nReviewer feedback: {feedback}\n" if feedback else ""

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert SOV (Statement of Values) data quality analyst. "
                    "Your role: explain data quality issues, assess business impact, "
                    "and confirm or refine recommended transformations. "
                    "You may ONLY select operations from this whitelist: "
                    f"{', '.join(sorted(WHITELISTED_OPERATIONS))}. "
                    "NEVER invent missing values. NEVER modify data directly. "
                    "Be concise and precise."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"SOV Quality Issues Detected:\n{issue_summary}\n\n"
                    f"Current Recommendations:\n{rec_summary}\n"
                    f"{feedback_section}\n"
                    "For each recommendation, provide: "
                    "1. A clear business-impact explanation. "
                    "2. Confirmation or correction of the suggested operation (must be from whitelist). "
                    "3. Uncertainty assessment. "
                    "Return a JSON array: [{id, rationale, operation, uncertainty, confidence}]"
                ),
            },
        ]

        raw = llm.complete(messages)
        if raw:
            # Parse and enrich recommendations
            try:
                text = raw.strip()
                if "```" in text:
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]

                import json
                enrichments = json.loads(text)
                if isinstance(enrichments, list):
                    enrichment_map = {e.get("id"): e for e in enrichments if e.get("id")}
                    for rec in recommendations:
                        if rec.id in enrichment_map:
                            e = enrichment_map[rec.id]
                            op = e.get("operation", rec.operation)
                            # Validate operation is whitelisted
                            if op not in WHITELISTED_OPERATIONS:
                                op = rec.operation
                            recommendations[recommendations.index(rec)] = rec.model_copy(update={
                                "rationale": e.get("rationale", rec.rationale),
                                "operation": op,
                                "uncertainty": e.get("uncertainty", rec.uncertainty),
                                "confidence": float(e.get("confidence", rec.confidence)),
                            })
            except Exception as e:
                logger.warning("LLM enrichment parse failed: %s", e)

        return recommendations

    except Exception as e:
        logger.warning("LLM reasoning failed: %s", e)
        return recommendations


# ---------------------------------------------------------------------------
# Also generate column mapping recommendations
# ---------------------------------------------------------------------------

def _generate_mapping_recommendations(state: SOVState) -> List[Recommendation]:
    """Create COLUMN_MAPPING recommendations for each mapped column."""
    recs = []
    if state.mappings is None:
        return recs

    for m in state.mappings.mappings:
        if m.target is None:
            continue
        recs.append(Recommendation(
            id=f"MAP-{uuid.uuid4().hex[:8].upper()}",
            action_type=ActionType.COLUMN_MAPPING,
            source_column=m.source_column,
            target_column=m.target,
            operation="trim_whitespace",  # Default for column rename
            before_example=f"Column: '{m.source_column}'",
            after_example=f"Renamed to: '{m.target}'",
            rationale=(
                f"Map '{m.source_column}' → '{m.target}' "
                f"(method={m.method}, confidence={m.confidence:.2f}). "
                f"{'; '.join(m.evidence[:2])}"
            ),
            confidence=m.confidence,
            uncertainty="" if m.confidence >= 0.90 else f"Confidence {m.confidence:.0%} — review recommended.",
            affected_rows=0,
            status=RecommendationStatus.PENDING,
            review_required=m.review_required or m.confidence < 0.90,
        ))

    return recs


# ---------------------------------------------------------------------------
# Agent 3 node function
# ---------------------------------------------------------------------------

def run_quality_reasoning(state: SOVState) -> SOVState:
    """
    LangGraph node: Agent 3 — Data Quality & Reasoning.
    Reads: state.file_meta, state.mappings, state.sheet_manifest
    Writes: state.quality_report, state.recommendations
    """
    logger.info("Agent 3: Data Quality & Reasoning starting.")
    state = state.model_copy(deep=True)
    state.stage = WorkflowStage.ASSESSING

    if state.mappings is None:
        state.error_message = "No mappings available for quality assessment."
        state.stage = WorkflowStage.ERROR
        return state

    # Load mapped DataFrame
    data_df = _get_mapped_df(state)
    if data_df is None or data_df.empty:
        state.error_message = "Could not load data for quality assessment."
        state.stage = WorkflowStage.ERROR
        return state

    logger.info("Assessing quality on %d rows × %d cols.", len(data_df), len(data_df.columns))

    # Part A: Deterministic detection
    issues = detect_quality_issues(data_df, state.mappings)
    completeness = compute_completeness(data_df)
    quality_score = compute_quality_score(issues, completeness, state.mappings)

    logger.info("Detected %d quality issues. Score: %.1f/100.", len(issues), quality_score)

    quality_report = QualityReport(
        issues=issues,
        completeness_by_field=completeness,
        overall_quality_score=quality_score,
        total_rows=len(data_df),
        issue_summary=f"{len(issues)} issues detected across {len(set(i.affected_field for i in issues))} fields.",
    )

    # Generate recommendations from issues
    data_quality_recs = [
        _generate_recommendation_from_issue(issue, data_df)
        for issue in issues
    ]

    # Generate column mapping recommendations
    mapping_recs = _generate_mapping_recommendations(state)

    all_recs = mapping_recs + data_quality_recs

    # Part B: LLM enrichment (batch, not per-row)
    feedback = state.re_reason_feedback
    all_recs = _llm_explain_issues(issues, all_recs, feedback=feedback)

    state.quality_report = quality_report
    state.recommendations = all_recs
    state.stage = WorkflowStage.ASSESSED
    state.re_reason_feedback = None  # Clear after use

    logger.info(
        "Agent 3 complete. %d recommendations generated. Quality score: %.1f/100.",
        len(all_recs), quality_score,
    )
    return state
