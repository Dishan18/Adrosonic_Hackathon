"""
State management utilities for the SOV pipeline.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.schemas.state_models import FileMeta, SOVState, WorkflowStage


def create_initial_state(
    file_path: str,
    original_filename: str,
    file_type: str,
    file_size_bytes: int = 0,
    session_id: str = "",
) -> SOVState:
    """Create a fresh SOV state for a new file upload."""
    if not session_id:
        session_id = uuid.uuid4().hex[:12]

    return SOVState(
        file_meta=FileMeta(
            original_filename=original_filename,
            file_type=file_type,
            temp_path=file_path,
            upload_timestamp=datetime.now().isoformat(),
            file_size_bytes=file_size_bytes,
            session_id=session_id,
        ),
        session_id=session_id,
        stage=WorkflowStage.INIT,
    )
