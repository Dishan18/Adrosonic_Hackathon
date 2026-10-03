"""
Audit logger: generates audit trail for all applied transformations.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

import pandas as pd

from app.schemas.state_models import AuditEntry, SOVState

logger = logging.getLogger(__name__)


def create_audit_entry(
    source_column: str,
    target_column: str,
    transformation_applied: str,
    before_value: Any,
    after_value: Any,
    confidence: float,
    approved_by: str = "human",
    recommendation_id: Optional[str] = None,
    row_index: Optional[int] = None,
) -> AuditEntry:
    return AuditEntry(
        entry_id=f"AUD-{uuid.uuid4().hex[:8].upper()}",
        source_column=source_column,
        target_column=target_column,
        transformation_applied=transformation_applied,
        before_value=before_value,
        after_value=after_value,
        confidence=confidence,
        approved_by=approved_by,
        timestamp=datetime.now().isoformat(),
        recommendation_id=recommendation_id,
        row_index=row_index,
    )


def export_audit_log_xlsx(entries: List[AuditEntry], output_path: str) -> str:
    """Export audit log to Excel file."""
    rows = []
    for e in entries:
        rows.append({
            "Entry ID": e.entry_id,
            "Source Column": e.source_column,
            "Target Column": e.target_column,
            "Transformation Applied": e.transformation_applied,
            "Before Value": str(e.before_value) if e.before_value is not None else "",
            "After Value": str(e.after_value) if e.after_value is not None else "",
            "Confidence": e.confidence,
            "Approved By": e.approved_by,
            "Timestamp": e.timestamp,
            "Recommendation ID": e.recommendation_id or "",
            "Row Index": e.row_index if e.row_index is not None else "",
        })

    if not rows:
        rows = [{"Entry ID": "No transformations applied", "Source Column": "", "Target Column": "",
                 "Transformation Applied": "", "Before Value": "", "After Value": "",
                 "Confidence": "", "Approved By": "", "Timestamp": datetime.now().isoformat(),
                 "Recommendation ID": "", "Row Index": ""}]

    df = pd.DataFrame(rows)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output_path, index=False, engine="openpyxl")
    logger.info("Audit log exported: %s (%d entries)", output_path, len(entries))
    return output_path


def export_audit_log_json(entries: List[AuditEntry], output_path: str) -> str:
    """Export audit log to JSON file."""
    import json
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    data = [e.model_dump() for e in entries]
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info("Audit log (JSON) exported: %s", output_path)
    return output_path
