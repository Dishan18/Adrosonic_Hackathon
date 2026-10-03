"""
Quality scoring service: aggregate SOV quality score.
"""

from __future__ import annotations

from typing import Dict, Optional

from app.schemas.state_models import QualityReport, MappingResult, Severity


def compute_sov_quality_score(
    quality_report: Optional[QualityReport],
    mappings: Optional[MappingResult],
) -> float:
    """
    Compute a 0–100 aggregate SOV quality score.
    Factors: mapping confidence, completeness, anomaly severity.
    """
    if quality_report is None and mappings is None:
        return 0.0

    # --- Mapping score (0-1) ---
    if mappings and mappings.mappings:
        from app.schemas.target_schema import TARGET_FIELDS
        mapped = [m for m in mappings.mappings if m.target is not None]
        coverage = len(mapped) / len(TARGET_FIELDS)
        avg_conf = sum(m.confidence for m in mapped) / max(len(mapped), 1)
        mapping_score = coverage * avg_conf
    else:
        mapping_score = 0.0

    # --- Completeness score (0-1) ---
    if quality_report and quality_report.completeness_by_field:
        values = list(quality_report.completeness_by_field.values())
        completeness_score = sum(v / 100 for v in values) / max(len(values), 1)
    else:
        completeness_score = 0.5  # Unknown

    # --- Anomaly score (0-1) ---
    if quality_report:
        weights = {Severity.HIGH: 0.20, Severity.MEDIUM: 0.08, Severity.LOW: 0.02}
        penalty = sum(weights.get(i.severity, 0) for i in quality_report.issues)
        anomaly_score = max(0.0, 1.0 - penalty)
    else:
        anomaly_score = 1.0

    # Weighted composite
    score = (
        0.35 * mapping_score
        + 0.30 * completeness_score
        + 0.35 * anomaly_score
    )
    return round(score * 100, 1)


def score_summary(score: float) -> Dict:
    """Return a human-readable summary for a quality score."""
    if score >= 80:
        grade = "A"
        label = "Excellent"
        color = "#00C851"
    elif score >= 65:
        grade = "B"
        label = "Good"
        color = "#33b5e5"
    elif score >= 50:
        grade = "C"
        label = "Fair"
        color = "#ffbb33"
    elif score >= 35:
        grade = "D"
        label = "Poor"
        color = "#ff8800"
    else:
        grade = "F"
        label = "Critical"
        color = "#ff4444"

    return {"score": score, "grade": grade, "label": label, "color": color}
