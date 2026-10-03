"""
Agentic SOV Intelligence System — Minimalist Enterprise UI
Clean, Apple-inspired minimal interface for SOV data cleansing, mapping, and audit.
"""

from __future__ import annotations

import io
import logging
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional, List

import pandas as pd
import streamlit as st

# Make app importable from root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.schemas.state_models import (
    ActionType,
    Recommendation,
    RecommendationStatus,
    SOVState,
    WorkflowStage,
)
from app.schemas.target_schema import TARGET_FIELDS
from app.processing.transformations import WHITELISTED_OPERATIONS
from app.orchestration.state import create_initial_state
from app.config import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Page configuration & Global Styles
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Agentic SOV Intelligence System",
    layout="wide",
    initial_sidebar_state="collapsed",
)

APPLE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Inter", "Segoe UI", Roboto, sans-serif !important;
    color: #1d1d1f;
    background-color: #fbfbfd;
}

/* Hide default streamlit decor */
header[data-testid="stHeader"] {
    background: transparent !important;
}
footer {
    display: none !important;
}
#MainMenu {
    display: none !important;
}
.stDeployButton {
    display: none !important;
}
[data-testid="stToolbar"] {
    display: none !important;
}
[data-testid="stDecoration"] {
    display: none !important;
}

/* Page container */
.main .block-container {
    max-width: 1080px;
    padding-top: 2rem;
    padding-bottom: 4rem;
}

/* Header typography */
.header-container {
    margin-bottom: 24px;
}
.header-title {
    font-size: 26px;
    font-weight: 600;
    letter-spacing: -0.025em;
    color: #1d1d1f;
    margin: 0 0 4px 0;
}
.header-subtitle {
    font-size: 14px;
    font-weight: 400;
    color: #86868b;
    margin: 0;
    line-height: 1.4;
}

/* Horizontal Step Indicator */
.stepper-wrap {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 12px;
    padding: 12px 24px;
    margin-bottom: 24px;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}
.stepper-item {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    font-weight: 500;
    color: #86868b;
}
.stepper-item.active {
    color: #1d1d1f;
    font-weight: 600;
}
.stepper-item.completed {
    color: #1d1d1f;
}
.stepper-point {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #d2d2d7;
}
.stepper-item.active .stepper-point {
    background: #0071e3;
    box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.15);
}
.stepper-item.completed .stepper-point {
    background: #34c759;
}
.stepper-line {
    flex: 1;
    height: 1px;
    background: #e5e5ea;
    margin: 0 16px;
}

/* Minimal Surface Cards */
.surface-card {
    background: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 12px;
    padding: 18px 22px;
    margin-bottom: 16px;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}
.surface-title {
    font-size: 14px;
    font-weight: 600;
    color: #1d1d1f;
    margin-bottom: 4px;
}
.surface-desc {
    font-size: 12px;
    color: #86868b;
    margin-bottom: 12px;
}

/* Metric Pill */
.stat-pill {
    background: #f5f5f7;
    border: 1px solid #e5e5ea;
    border-radius: 10px;
    padding: 10px 16px;
    min-width: 110px;
}
.stat-pill-val {
    font-size: 17px;
    font-weight: 600;
    color: #1d1d1f;
}
.stat-pill-lbl {
    font-size: 11px;
    font-weight: 500;
    color: #86868b;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-top: 2px;
}

/* Badges */
.badge {
    display: inline-block;
    font-size: 11px;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 6px;
    letter-spacing: 0.02em;
    text-transform: uppercase;
}
.badge-green {
    background: #f0fdf4;
    color: #15803d;
    border: 1px solid #bbf7d0;
}
.badge-amber {
    background: #fffbeb;
    color: #b45309;
    border: 1px solid #fde68a;
}
.badge-red {
    background: #fef2f2;
    color: #b91c1c;
    border: 1px solid #fecaca;
}
.badge-neutral {
    background: #f5f5f7;
    color: #636366;
    border: 1px solid #e5e5ea;
}
.badge-blue {
    background: #eff6ff;
    color: #1d4ed8;
    border: 1px solid #bfdbfe;
}

/* Buttons */
div.stButton > button {
    border-radius: 8px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    padding: 6px 14px !important;
    border: 1px solid #d2d2d7 !important;
    background-color: #ffffff !important;
    color: #1d1d1f !important;
    transition: all 0.12s ease-in-out !important;
}
div.stButton > button:hover {
    background-color: #f5f5f7 !important;
    border-color: #bcbcc0 !important;
}
div.stButton > button[kind="primary"] {
    background-color: #0071e3 !important;
    color: #ffffff !important;
    border: 1px solid #0071e3 !important;
}
div.stButton > button[kind="primary"]:hover {
    background-color: #0077ed !important;
    border-color: #0077ed !important;
}

/* Apple-style segmented tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px !important;
    background: #f5f5f7 !important;
    padding: 4px !important;
    border-radius: 10px !important;
    border: 1px solid #e5e5ea !important;
    margin-bottom: 20px !important;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 7px !important;
    padding: 6px 14px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    color: #636366 !important;
    border: none !important;
    background: transparent !important;
}
.stTabs [aria-selected="true"] {
    background: #ffffff !important;
    color: #1d1d1f !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.06) !important;
    font-weight: 600 !important;
}
.stTabs [data-baseweb="tab-border"] {
    display: none !important;
}

/* Table styling */
div[data-testid="stDataFrame"] {
    border: 1px solid #e5e5ea !important;
    border-radius: 10px !important;
    overflow: hidden !important;
    background: #ffffff !important;
}

/* File Uploader */
div[data-testid="stFileUploader"] {
    background: #ffffff;
    border: 1px dashed #d2d2d7;
    border-radius: 12px;
    padding: 16px;
}
div[data-testid="stFileUploader"]:hover {
    border-color: #0071e3;
}

/* Form input refinement */
div[data-baseweb="input"] {
    border-radius: 8px !important;
}
div[data-baseweb="select"] {
    border-radius: 8px !important;
}
</style>
"""

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def init_session():
    if "sov_state" not in st.session_state:
        st.session_state.sov_state = None
    if "session_id" not in st.session_state:
        st.session_state.session_id = uuid.uuid4().hex[:12]
    if "pipeline_ran" not in st.session_state:
        st.session_state.pipeline_ran = False
    if "review_complete" not in st.session_state:
        st.session_state.review_complete = False
    if "transformed" not in st.session_state:
        st.session_state.transformed = False


# ---------------------------------------------------------------------------
# Header & Workflow Stepper
# ---------------------------------------------------------------------------

def render_header():
    st.markdown(
        """
        <div class="header-container">
            <h1 class="header-title">Agentic SOV Intelligence System</h1>
            <p class="header-subtitle">Deterministic transformation, cascading schema mapping, and human-in-the-loop review for commercial property SOVs.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_stepper(state: Optional[SOVState]):
    stages = [
        ("Discovery", WorkflowStage.DISCOVERED),
        ("Mapping", WorkflowStage.MAPPED),
        ("Quality", WorkflowStage.ASSESSED),
        ("Review", WorkflowStage.HUMAN_REVIEW),
        ("Transformation", WorkflowStage.COMPLETE),
    ]

    current_stage = state.stage if state else WorkflowStage.INIT
    stage_names = [s[1] for s in stages]

    # Map current state to an index 0..4
    stage_idx = -1
    if current_stage == WorkflowStage.DISCOVERED:
        stage_idx = 0
    elif current_stage == WorkflowStage.MAPPED:
        stage_idx = 1
    elif current_stage == WorkflowStage.ASSESSED:
        stage_idx = 2
    elif current_stage in (WorkflowStage.HUMAN_REVIEW, WorkflowStage.TRANSFORMING, WorkflowStage.VALIDATING):
        stage_idx = 3
    elif current_stage == WorkflowStage.COMPLETE:
        stage_idx = 4

    html = ['<div class="stepper-wrap">']
    for i, (label, stage_enum) in enumerate(stages):
        if i > 0:
            html.append('<div class="stepper-line"></div>')

        if stage_idx > i:
            cls = "stepper-item completed"
        elif stage_idx == i:
            cls = "stepper-item active"
        else:
            cls = "stepper-item"

        html.append(f'<div class="{cls}"><div class="stepper-point"></div><span>{label}</span></div>')

    html.append('</div>')
    st.markdown("".join(html), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Section 1: File Upload
# ---------------------------------------------------------------------------

def render_upload_section():
    with st.container():
        uploaded = st.file_uploader(
            "Select Statement of Values file",
            type=["xlsx", "xls", "csv"],
            key="file_uploader",
            label_visibility="collapsed",
        )

        col_info, col_btn = st.columns([3, 1])

        with col_info:
            if uploaded is not None:
                size_kb = uploaded.size / 1024
                ext = Path(uploaded.name).suffix.lower().lstrip(".")
                st.markdown(
                    f"<div style='font-size:13px;color:#1d1d1f;padding-top:6px;'>"
                    f"Selected: <strong>{uploaded.name}</strong> "
                    f"<span style='color:#86868b;'>({ext.upper()}, {size_kb:.1f} KB)</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    "<div style='font-size:13px;color:#86868b;padding-top:6px;'>"
                    "Supports multi-sheet workbooks, merged headers, and irregular layouts (.xlsx, .xls, .csv)"
                    "</div>",
                    unsafe_allow_html=True,
                )

        with col_btn:
            if uploaded is not None:
                if st.button("Run Pipeline", type="primary", use_container_width=True):
                    with st.spinner("Processing workbook through agent cascade…"):
                        _run_pipeline(uploaded)
            else:
                st.button("Run Pipeline", disabled=True, use_container_width=True)


def _run_pipeline(uploaded_file):
    ext = Path(uploaded_file.name).suffix.lower()
    upload_dir = Path(config.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    session_id = st.session_state.session_id
    temp_path = str(upload_dir / f"{session_id}{ext}")

    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getvalue())

    state = create_initial_state(
        file_path=temp_path,
        original_filename=uploaded_file.name,
        file_type=ext.lstrip("."),
        file_size_bytes=uploaded_file.size,
        session_id=session_id,
    )

    try:
        from app.agents.sheet_discovery import run_sheet_discovery
        from app.agents.schema_mapping import run_schema_mapping
        from app.agents.quality_reasoning import run_quality_reasoning

        state = run_sheet_discovery(state)
        if state.stage == WorkflowStage.ERROR:
            st.error(f"Sheet discovery error: {state.error_message}")
            return

        state = run_schema_mapping(state)
        if state.stage == WorkflowStage.ERROR:
            st.error(f"Schema mapping error: {state.error_message}")
            return

        state = run_quality_reasoning(state)
        if state.stage == WorkflowStage.ERROR:
            st.error(f"Quality assessment error: {state.error_message}")
            return

        state.stage = WorkflowStage.HUMAN_REVIEW

    except Exception as e:
        st.error(f"Pipeline execution failure: {e}")
        logger.exception("Pipeline error")
        return

    st.session_state.sov_state = state
    st.session_state.pipeline_ran = True
    st.session_state.review_complete = False
    st.session_state.transformed = False
    st.rerun()


# ---------------------------------------------------------------------------
# Section 2: Human Review (Primary Interaction Area)
# ---------------------------------------------------------------------------

def render_review_section(state: SOVState):
    if not state.recommendations:
        st.info("No recommendations generated for this dataset.")
        return

    recs = state.recommendations
    pending = [r for r in recs if r.status == RecommendationStatus.PENDING]
    approved = [r for r in recs if r.status == RecommendationStatus.APPROVED]
    rejected = [r for r in recs if r.status == RecommendationStatus.REJECTED]
    still_pending_required = [r for r in pending if r.review_required]

    # Metrics row
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f"<div class='stat-pill'><div class='stat-pill-val'>{len(recs)}</div><div class='stat-pill-lbl'>Total Proposed</div></div>",
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"<div class='stat-pill'><div class='stat-pill-val'>{len(pending)}</div><div class='stat-pill-lbl'>Pending Review</div></div>",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f"<div class='stat-pill'><div class='stat-pill-val'>{len(approved)}</div><div class='stat-pill-lbl'>Approved</div></div>",
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            f"<div class='stat-pill'><div class='stat-pill-val'>{len(rejected)}</div><div class='stat-pill-lbl'>Rejected</div></div>",
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    # Bulk actions & status alert
    col_actions, col_status = st.columns([1, 1])

    with col_actions:
        high_conf_pending = [r for r in pending if r.confidence >= config.HIGH_CONFIDENCE_THRESHOLD]
        if high_conf_pending:
            if st.button(f"Approve High-Confidence ({len(high_conf_pending)} items ≥90%)", key="approve_high_btn"):
                for r in high_conf_pending:
                    _approve_recommendation(state, r.id)
                st.rerun()

    with col_status:
        if still_pending_required:
            st.markdown(
                f"<div style='font-size:13px;color:#b45309;background:#fffbeb;border:1px solid #fde68a;padding:8px 12px;border-radius:8px;'>"
                f"Export locked: {len(still_pending_required)} required decision(s) pending."
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div style='font-size:13px;color:#15803d;background:#f0fdf4;border:1px solid #bbf7d0;padding:8px 12px;border-radius:8px;'>"
                f"All required decisions complete. Ready for transformation."
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    # Grouped review cards
    action_groups = [
        (ActionType.COLUMN_MAPPING, "Column Mappings"),
        (ActionType.STANDARDISATION, "Standardisation"),
        (ActionType.DATA_CORRECTION, "Data Corrections"),
        (ActionType.FLAG_FOR_REVIEW, "Flagged Items"),
    ]

    for action_type, label in action_groups:
        group_recs = [r for r in recs if r.action_type == action_type]
        if not group_recs:
            continue

        with st.expander(f"{label} ({len(group_recs)})", expanded=(action_type == ActionType.COLUMN_MAPPING)):
            for rec in group_recs:
                _render_recommendation_item(state, rec)

    # Transformation execution button once unlocked
    if not still_pending_required:
        st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
        if st.button("Apply Approved Transformations", type="primary", use_container_width=True):
            _run_transformation(state)


def _render_recommendation_item(state: SOVState, rec: Recommendation):
    # Status badges
    status_cls = {
        RecommendationStatus.PENDING: "badge-amber",
        RecommendationStatus.APPROVED: "badge-green",
        RecommendationStatus.REJECTED: "badge-red",
        RecommendationStatus.ESCALATED: "badge-neutral",
    }.get(rec.status, "badge-neutral")

    conf_pct = f"{rec.confidence:.0%}"
    conf_cls = "badge-green" if rec.confidence >= 0.90 else "badge-amber" if rec.confidence >= 0.70 else "badge-red"

    st.markdown(
        f"""
        <div class="surface-card">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <div>
                    <span style="font-family:monospace;font-size:12px;color:#86868b;margin-right:8px;">{rec.id}</span>
                    <strong style="font-size:14px;color:#1d1d1f;">{rec.source_column}</strong>
                    <span style="color:#86868b;margin:0 6px;">→</span>
                    <strong style="font-size:14px;color:#1d1d1f;">{rec.target_column}</strong>
                </div>
                <div style="display:flex;gap:6px;align-items:center;">
                    <span class="badge {conf_cls}">Conf {conf_pct}</span>
                    <span class="badge {status_cls}">{rec.status.upper()}</span>
                </div>
            </div>
            <div style="font-size:12px;color:#636366;margin-bottom:8px;">
                <span>Operation: <code>{rec.operation}</code></span>
                <span style="margin:0 8px;">|</span>
                <span>Affected rows: {rec.affected_rows}</span>
            </div>
            <div style="font-size:13px;color:#1d1d1f;margin-bottom:8px;line-height:1.4;">
                {rec.rationale}
            </div>
        """,
        unsafe_allow_html=True,
    )

    if rec.before_example or rec.after_example:
        st.markdown(
            f"""
            <div style="background:#f5f5f7;border-radius:8px;padding:6px 12px;font-size:12px;color:#1d1d1f;margin-bottom:10px;">
                <span style="color:#86868b;">Before:</span> <code>{rec.before_example or 'null'}</code>
                <span style="margin:0 8px;color:#86868b;">→</span>
                <span style="color:#86868b;">After:</span> <code>{rec.after_example or 'null'}</code>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if rec.uncertainty:
        st.markdown(
            f"<div style='font-size:12px;color:#b45309;margin-bottom:8px;'>Note: {rec.uncertainty}</div>",
            unsafe_allow_html=True,
        )

    # Controls
    if rec.status == RecommendationStatus.PENDING:
        col_appr, col_rej, col_edit = st.columns([1, 1, 1])

        with col_appr:
            if st.button("Approve", key=f"app_{rec.id}", use_container_width=True):
                _approve_recommendation(state, rec.id)
                st.rerun()

        with col_rej:
            if st.button("Reject", key=f"rej_{rec.id}", use_container_width=True):
                st.session_state[f"show_reject_{rec.id}"] = not st.session_state.get(f"show_reject_{rec.id}", False)

        with col_edit:
            if st.button("Edit", key=f"edit_{rec.id}", use_container_width=True):
                st.session_state[f"show_edit_{rec.id}"] = not st.session_state.get(f"show_edit_{rec.id}", False)

        # Inline rejection note
        if st.session_state.get(f"show_reject_{rec.id}"):
            rej_note = st.text_input("Rejection note (optional)", key=f"rnote_{rec.id}")
            c_r1, c_r2 = st.columns(2)
            with c_r1:
                if st.button("Confirm Rejection", key=f"conf_rej_{rec.id}", use_container_width=True):
                    _reject_recommendation(state, rec.id, rej_note)
                    st.session_state[f"show_reject_{rec.id}"] = False
                    st.rerun()
            with c_r2:
                if st.button("Cancel", key=f"canc_rej_{rec.id}", use_container_width=True):
                    st.session_state[f"show_reject_{rec.id}"] = False
                    st.rerun()

        # Inline edit
        if st.session_state.get(f"show_edit_{rec.id}"):
            st.markdown("<div style='font-size:12px;font-weight:600;margin-top:8px;'>Edit Target Mapping</div>", unsafe_allow_html=True)
            current_target = rec.target_column if rec.target_column in TARGET_FIELDS else TARGET_FIELDS[0]
            target_idx = TARGET_FIELDS.index(current_target) if current_target in TARGET_FIELDS else 0
            new_target = st.selectbox("Select Target Field", TARGET_FIELDS, index=target_idx, key=f"sel_target_{rec.id}")

            c_e1, c_e2 = st.columns(2)
            with c_e1:
                if st.button("Save & Approve", key=f"save_edit_{rec.id}", use_container_width=True):
                    _edit_and_approve_recommendation(state, rec.id, new_target)
                    st.session_state[f"show_edit_{rec.id}"] = False
                    st.rerun()
            with c_e2:
                if st.button("Cancel", key=f"canc_edit_{rec.id}", use_container_width=True):
                    st.session_state[f"show_edit_{rec.id}"] = False
                    st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def _approve_recommendation(state: SOVState, rec_id: str):
    for i, rec in enumerate(state.recommendations):
        if rec.id == rec_id:
            state.recommendations[i] = rec.model_copy(
                update={"status": RecommendationStatus.APPROVED}
            )
            if rec.action_type == ActionType.COLUMN_MAPPING:
                try:
                    from app.services.memory.chroma_store import store_approved_mapping
                    store_approved_mapping(
                        source_column=rec.source_column,
                        target_field=rec.target_column,
                        confidence=rec.confidence,
                        method="human_approved",
                    )
                except Exception as e:
                    logger.warning("Memory store failure: %s", e)
            break


def _reject_recommendation(state: SOVState, rec_id: str, note: str = ""):
    for i, rec in enumerate(state.recommendations):
        if rec.id == rec_id:
            new_count = rec.re_reason_count + 1
            state.recommendations[i] = rec.model_copy(
                update={
                    "status": RecommendationStatus.REJECTED,
                    "rejection_note": note,
                    "re_reason_count": new_count,
                }
            )
            if note and new_count < config.MAX_REREASON_ATTEMPTS:
                state.re_reason_feedback = f"Recommendation {rec_id} rejected: {note}"
                _run_rereason(state)
            break


def _edit_and_approve_recommendation(state: SOVState, rec_id: str, new_target: str):
    for i, rec in enumerate(state.recommendations):
        if rec.id == rec_id:
            state.recommendations[i] = rec.model_copy(
                update={
                    "target_column": new_target,
                    "status": RecommendationStatus.APPROVED,
                    "uncertainty": "User edited target mapping.",
                    "confidence": 1.0,
                }
            )
            if rec.action_type == ActionType.COLUMN_MAPPING:
                try:
                    from app.services.memory.chroma_store import store_approved_mapping
                    store_approved_mapping(
                        source_column=rec.source_column,
                        target_field=new_target,
                        confidence=1.0,
                        method="human_edited",
                    )
                except Exception as e:
                    logger.warning("Memory store error: %s", e)
            break


def _run_rereason(state: SOVState):
    from app.agents.quality_reasoning import run_quality_reasoning
    try:
        new_state = run_quality_reasoning(state)
        state.recommendations = new_state.recommendations
        state.quality_report = new_state.quality_report
        state.stage = WorkflowStage.HUMAN_REVIEW
        st.session_state.sov_state = state
    except Exception as e:
        st.error(f"Re-reasoning failed: {e}")


def _run_transformation(state: SOVState):
    from app.agents.transformation import run_transformation
    with st.spinner("Executing whitelisted transformations…"):
        try:
            final_state = run_transformation(state)
            st.session_state.sov_state = final_state
            st.session_state.transformed = True
            st.rerun()
        except Exception as e:
            st.error(f"Transformation execution error: {e}")
            logger.exception("Transformation error")


# ---------------------------------------------------------------------------
# Section 3: Schema Mapping
# ---------------------------------------------------------------------------

def render_mapping_section(state: SOVState):
    if state.mappings is None:
        st.info("Schema mapping data not available.")
        return

    result = state.mappings
    mapped = [m for m in result.mappings if m.target]
    high_conf = sum(1 for m in result.mappings if m.confidence >= 0.90)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            f"<div class='stat-pill'><div class='stat-pill-val'>{len(mapped)} / {len(result.mappings)}</div><div class='stat-pill-lbl'>Mapped Columns</div></div>",
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"<div class='stat-pill'><div class='stat-pill-val'>{result.overall_mapping_confidence:.1%}</div><div class='stat-pill-lbl'>Average Confidence</div></div>",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f"<div class='stat-pill'><div class='stat-pill-val'>{high_conf}</div><div class='stat-pill-lbl'>High Confidence (≥90%)</div></div>",
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    if result.unmapped_target_fields:
        unmapped_str = ", ".join(result.unmapped_target_fields)
        st.markdown(
            f"<div style='font-size:12px;color:#b45309;background:#fffbeb;border:1px solid #fde68a;padding:8px 12px;border-radius:8px;margin-bottom:12px;'>"
            f"Unmapped target fields: {unmapped_str}"
            f"</div>",
            unsafe_allow_html=True,
        )

    rows = []
    for m in result.mappings:
        rows.append({
            "Source Column": m.source_column,
            "Target Field": m.target or "Unmapped",
            "Confidence": f"{m.confidence:.1%}",
            "Method": m.method,
            "Review Required": "Yes" if m.review_required else "No",
            "Rationale": m.rationale,
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Section 4: Sheet Discovery
# ---------------------------------------------------------------------------

def render_discovery_section(state: SOVState):
    if state.sheet_manifest is None:
        st.info("Sheet manifest not available.")
        return

    manifest = state.sheet_manifest
    primary = manifest.primary

    if primary:
        st.markdown(
            f"""
            <div class="surface-card" style="margin-bottom:16px;">
                <div style="font-size:13px;color:#1d1d1f;">
                    <strong>Primary Sheet:</strong> <code>{primary.sheet_name}</code>
                    <span style="margin:0 8px;color:#86868b;">|</span>
                    <span>Header Row: {primary.header_row} (0-indexed)</span>
                    <span style="margin:0 8px;color:#86868b;">|</span>
                    <span>Confidence: {primary.confidence:.1%}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    rows = []
    for s in manifest.sheets:
        rows.append({
            "Sheet Name": s.sheet_name,
            "Classification": s.classification,
            "Confidence": f"{s.confidence:.1%}",
            "Header Row": s.header_row,
            "Data Rows": max(0, s.profile.row_count - s.header_row - 1),
            "Field Matches": s.profile.candidate_field_matches,
            "Non-null %": f"{s.profile.non_null_ratio:.0%}",
            "Merged Cells": s.profile.merged_cell_count,
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if primary and primary.reasoning:
        with st.expander("Discovery Reasoning Details", expanded=False):
            for r in primary.reasoning:
                st.markdown(f"<div style='font-size:13px;color:#636366;'>• {r}</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Section 5: Data Quality
# ---------------------------------------------------------------------------

def render_quality_section(state: SOVState):
    if state.quality_report is None:
        st.info("Quality report not available.")
        return

    qr = state.quality_report
    from app.services.scoring.quality_score import compute_sov_quality_score, score_summary
    score = compute_sov_quality_score(qr, state.mappings)
    summary = score_summary(score)
    critical_count = sum(1 for i in qr.issues if i.severity == "high")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f"<div class='stat-pill'><div class='stat-pill-val'>{score:.1f} / 100</div><div class='stat-pill-lbl'>Quality Score</div></div>",
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"<div class='stat-pill'><div class='stat-pill-val'>{summary['grade']}</div><div class='stat-pill-lbl'>Grade</div></div>",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f"<div class='stat-pill'><div class='stat-pill-val'>{len(qr.issues)}</div><div class='stat-pill-lbl'>Issues Detected</div></div>",
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            f"<div class='stat-pill'><div class='stat-pill-val'>{critical_count}</div><div class='stat-pill-lbl'>Critical Issues</div></div>",
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    if qr.issues:
        issue_rows = []
        for issue in qr.issues:
            issue_rows.append({
                "ID": issue.issue_id,
                "Severity": issue.severity.upper(),
                "Type": issue.issue_type,
                "Affected Field": issue.affected_field,
                "Affected Rows": issue.affected_row_count,
                "Evidence": issue.evidence,
                "Suggested Operation": issue.suggested_operation,
            })
        st.dataframe(pd.DataFrame(issue_rows), use_container_width=True, hide_index=True)
    else:
        st.markdown("<div style='font-size:13px;color:#15803d;padding:8px 0;'>No data quality issues detected.</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Section 6: Data Preview (Before & After)
# ---------------------------------------------------------------------------

def render_preview_section(state: SOVState):
    from app.agents.transformation import _load_source_df, generate_preview_df

    source_df = _load_source_df(state)
    approved = [r for r in state.recommendations if r.status == RecommendationStatus.APPROVED]
    preview_df = generate_preview_df(state, approved) if approved else pd.DataFrame()

    st.markdown("<div class='surface-title'>Data Transformation Preview</div>", unsafe_allow_html=True)
    st.markdown("<div class='surface-desc'>Comparison between raw extracted data and current approved transformation output.</div>", unsafe_allow_html=True)

    col_before, col_after = st.columns(2)

    with col_before:
        st.markdown("<strong style='font-size:13px;color:#1d1d1f;'>Raw Source Data</strong>", unsafe_allow_html=True)
        if source_df is not None and not source_df.empty:
            st.dataframe(source_df.head(15), use_container_width=True)
        else:
            st.caption("Source data not loaded.")

    with col_after:
        st.markdown("<strong style='font-size:13px;color:#1d1d1f;'>Transformed Output (17 Standard Fields)</strong>", unsafe_allow_html=True)
        if not preview_df.empty:
            st.dataframe(preview_df.head(15), use_container_width=True)
        else:
            st.caption("Approve recommendations in Human Review to generate preview.")


# ---------------------------------------------------------------------------
# Section 7: Final Output & Export
# ---------------------------------------------------------------------------

def render_export_section(state: SOVState):
    if not st.session_state.get("transformed"):
        still_pending_required = [
            r for r in state.recommendations
            if r.status == RecommendationStatus.PENDING and r.review_required
        ]
        if still_pending_required:
            st.markdown(
                f"<div style='font-size:13px;color:#b45309;background:#fffbeb;border:1px solid #fde68a;padding:12px 16px;border-radius:10px;'>"
                f"Export locked. Please complete the {len(still_pending_required)} required review decision(s) in the Review section."
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='font-size:13px;color:#636366;background:#f5f5f7;border:1px solid #e5e5ea;padding:12px 16px;border-radius:10px;'>"
                "Review complete. Click 'Apply Approved Transformations' in the Review section to build the final deliverables."
                "</div>",
                unsafe_allow_html=True,
            )
        return

    # Validation banner
    if state.validation_passed:
        st.markdown(
            f"""
            <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:14px 18px;margin-bottom:20px;">
                <div style="font-size:14px;font-weight:600;color:#15803d;margin-bottom:2px;">
                    Validation Passed: Exact 17-Column Schema
                </div>
                <div style="font-size:12px;color:#166534;">
                    Output data strictly adheres to target column types and order without fabricated missing values.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:14px 18px;margin-bottom:20px;">
                <div style="font-size:14px;font-weight:600;color:#b91c1c;margin-bottom:2px;">
                    Validation Warning
                </div>
                <div style="font-size:12px;color:#991b1b;">
                    {'; '.join(state.validation_errors)}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Downloads
    c1, c2 = st.columns(2)

    with c1:
        if state.output_path and Path(state.output_path).exists():
            with open(state.output_path, "rb") as f:
                data = f.read()
            st.download_button(
                label="Download Cleaned_SOV.xlsx",
                data=data,
                file_name="Cleaned_SOV.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_sov_btn",
                use_container_width=True,
            )

    with c2:
        if state.audit_log_path and Path(state.audit_log_path).exists():
            with open(state.audit_log_path, "rb") as f:
                audit_data = f.read()
            st.download_button(
                label="Download Audit_Log.xlsx",
                data=audit_data,
                file_name="Audit_Log.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_audit_btn",
                use_container_width=True,
            )

    # Audit Trail summary
    if state.audit_log:
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        with st.expander(f"Audit Trail ({len(state.audit_log)} logged entries)", expanded=False):
            audit_rows = []
            for entry in state.audit_log:
                audit_rows.append({
                    "Entry ID": entry.entry_id,
                    "Source Column": entry.source_column,
                    "Target Column": entry.target_column,
                    "Operation": entry.transformation_applied,
                    "Before Value": str(entry.before_value)[:50],
                    "After Value": str(entry.after_value)[:50],
                    "Confidence": f"{entry.confidence:.0%}",
                    "Approved By": entry.approved_by,
                    "Timestamp": entry.timestamp,
                })
            st.dataframe(pd.DataFrame(audit_rows), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Sidebar (Minimal Controls)
# ---------------------------------------------------------------------------

def render_sidebar(state: Optional[SOVState]):
    with st.sidebar:
        st.markdown("<strong style='font-size:14px;color:#1d1d1f;'>System Configuration</strong>", unsafe_allow_html=True)
        st.caption("Enterprise SOV Cleansing & Validation")

        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

        # Provider pill
        llm_avail = config.is_llm_available()
        status_text = f"{config.LLM_PROVIDER.upper()} Active" if llm_avail else "Deterministic Mode"
        badge_cls = "badge-green" if llm_avail else "badge-neutral"

        st.markdown(
            f"""
            <div style="background:#ffffff;border:1px solid #e5e5ea;border-radius:8px;padding:10px 12px;margin-bottom:12px;">
                <div style="font-size:11px;color:#86868b;text-transform:uppercase;margin-bottom:4px;">LLM Gateway</div>
                <span class="badge {badge_cls}">{status_text}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if state and state.file_meta:
            st.markdown(
                f"""
                <div style="background:#ffffff;border:1px solid #e5e5ea;border-radius:8px;padding:10px 12px;margin-bottom:12px;font-size:12px;color:#1d1d1f;">
                    <div style="font-size:11px;color:#86868b;text-transform:uppercase;margin-bottom:4px;">Active Session</div>
                    <div><strong>File:</strong> {state.file_meta.original_filename}</div>
                    <div><strong>Sheet:</strong> {state.primary_sheet_name or 'None'}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        if st.button("Reset Session", use_container_width=True):
            st.session_state.sov_state = None
            st.session_state.pipeline_ran = False
            st.session_state.review_complete = False
            st.session_state.transformed = False
            st.session_state.session_id = uuid.uuid4().hex[:12]
            st.rerun()


# ---------------------------------------------------------------------------
# Main App Structure
# ---------------------------------------------------------------------------

def main():
    st.markdown(APPLE_CSS, unsafe_allow_html=True)
    init_session()
    state: Optional[SOVState] = st.session_state.sov_state

    render_header()
    render_stepper(state)
    render_upload_section()
    render_sidebar(state)

    if state and st.session_state.pipeline_ran:
        st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

        tab_labels = [
            "Review",
            "Data Preview",
            "Schema Mapping",
            "Sheet Detection",
            "Data Quality",
            "Final Output",
        ]
        tabs = st.tabs(tab_labels)

        with tabs[0]:
            render_review_section(state)

        with tabs[1]:
            render_preview_section(state)

        with tabs[2]:
            render_mapping_section(state)

        with tabs[3]:
            render_discovery_section(state)

        with tabs[4]:
            render_quality_section(state)

        with tabs[5]:
            render_export_section(state)


if __name__ == "__main__":
    main()
