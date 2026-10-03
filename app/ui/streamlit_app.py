"""
Agentic SOV Intelligence System — Minimalist Enterprise UI
Clean, Apple-inspired interface with calm typography, human-readable review descriptions,
and smooth, flicker-free interactions.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any

import pandas as pd
import streamlit as st

# Make app importable from workspace root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.schemas.state_models import (
    ActionType,
    Recommendation,
    RecommendationStatus,
    SOVState,
    WorkflowStage,
)
from app.schemas.target_schema import TARGET_FIELDS
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
/* 1. Global Reset & Universal Light Palette */
html, body, [class*="css"], .stApp, [data-testid="stAppViewContainer"], .main {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Inter", "Segoe UI", Roboto, sans-serif !important;
    color: #1A1A1A !important;
    background-color: #F8F9FA !important;
}

/* 2. Hide Streamlit Decor */
header[data-testid="stHeader"] {
    background-color: #F8F9FA !important;
}
footer, #MainMenu, .stDeployButton, [data-testid="stToolbar"], [data-testid="stDecoration"] {
    display: none !important;
}

/* 3. Centered Layout Container */
.main .block-container {
    max-width: 1040px !important;
    padding-top: 1.8rem !important;
    padding-bottom: 4rem !important;
    background-color: #F8F9FA !important;
}

/* 4. Minimal Header */
.header-box {
    margin-bottom: 20px;
}
.header-box h1 {
    font-size: 25px !important;
    font-weight: 600 !important;
    letter-spacing: -0.02em !important;
    color: #111827 !important;
    margin: 0 0 4px 0 !important;
}
.header-box p {
    font-size: 14px !important;
    color: #6B7280 !important;
    margin: 0 !important;
    line-height: 1.4 !important;
}

/* 5. Stepper Bar */
.stepper-wrap {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #FFFFFF !important;
    border: 1px solid #E5E7EB !important;
    border-radius: 10px !important;
    padding: 12px 20px !important;
    margin-bottom: 20px !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02) !important;
}
.stepper-item {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 13px;
    font-weight: 500;
    color: #6B7280;
}
.stepper-item.active {
    color: #111827;
    font-weight: 600;
}
.stepper-item.completed {
    color: #111827;
}
.stepper-point {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #D1D5DB;
}
.stepper-item.active .stepper-point {
    background: #0071E3;
    box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.15);
}
.stepper-item.completed .stepper-point {
    background: #10B981;
}
.stepper-line {
    flex: 1;
    height: 1px;
    background: #E5E7EB;
    margin: 0 14px;
}

/* 6. Cards & Containers */
.surface-card {
    background: #FFFFFF !important;
    border: 1px solid #E5E7EB !important;
    border-radius: 10px !important;
    padding: 18px 20px !important;
    margin-bottom: 12px !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02) !important;
}
.surface-card:hover {
    border-color: #D1D5DB !important;
}

/* 7. Metric Counter Pills */
.stat-pill {
    background: #FFFFFF !important;
    border: 1px solid #E5E7EB !important;
    border-radius: 8px !important;
    padding: 10px 14px !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02) !important;
}
.stat-pill-val {
    font-size: 18px;
    font-weight: 600;
    color: #111827;
}
.stat-pill-lbl {
    font-size: 11px;
    font-weight: 500;
    color: #6B7280;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-top: 2px;
}

/* 8. Neutral Badges */
.badge {
    display: inline-block;
    font-size: 11px;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 5px;
    letter-spacing: 0.02em;
    text-transform: uppercase;
}
.badge-green {
    background: #ECFDF5;
    color: #047857;
    border: 1px solid #A7F3D0;
}
.badge-amber {
    background: #FFFBEB;
    color: #B45309;
    border: 1px solid #FDE68A;
}
.badge-red {
    background: #FEF2F2;
    color: #B91C1C;
    border: 1px solid #FECACA;
}
.badge-neutral {
    background: #F3F4F6;
    color: #4B5563;
    border: 1px solid #E5E7EB;
}
.badge-blue {
    background: #EFF6FF;
    color: #1D4ED8;
    border: 1px solid #BFDBFE;
}

/* 9. Clean Buttons */
div.stButton > button {
    border-radius: 7px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    padding: 5px 13px !important;
    border: 1px solid #D1D5DB !important;
    background-color: #FFFFFF !important;
    color: #374151 !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03) !important;
    transition: all 0.1s ease !important;
}
div.stButton > button:hover {
    background-color: #F9FAFB !important;
    border-color: #9CA3AF !important;
    color: #111827 !important;
}
div.stButton > button[kind="primary"] {
    background-color: #0071E3 !important;
    color: #FFFFFF !important;
    border: 1px solid #0071E3 !important;
}
div.stButton > button[kind="primary"]:hover {
    background-color: #0077ED !important;
    border-color: #0077ED !important;
}

/* 10. Apple Segmented Control Tabs & Navigation */
div[data-testid="stSegmentedControl"] {
    background: #E5E7EB !important;
    border: 1px solid #D1D5DB !important;
    border-radius: 8px !important;
    padding: 3px !important;
    gap: 3px !important;
    margin-bottom: 20px !important;
    display: flex !important;
    width: 100% !important;
}
div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] {
    display: flex !important;
    width: 100% !important;
    gap: 3px !important;
}
div[data-testid="stSegmentedControl"] button {
    flex: 1 !important;
    border-radius: 6px !important;
    padding: 6px 14px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    color: #4B5563 !important;
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
    transition: all 0.1s ease !important;
    text-align: center !important;
}
div[data-testid="stSegmentedControl"] button:hover {
    color: #111827 !important;
    background: rgba(255, 255, 255, 0.4) !important;
}
div[data-testid="stSegmentedControl"] button[aria-checked="true"],
div[data-testid="stSegmentedControl"] button[data-checked="true"] {
    background: #FFFFFF !important;
    color: #111827 !important;
    font-weight: 600 !important;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08) !important;
}

.stTabs [data-baseweb="tab-list"] {
    background: #E5E7EB !important;
    border: 1px solid #D1D5DB !important;
    border-radius: 8px !important;
    padding: 3px !important;
    gap: 3px !important;
    margin-bottom: 18px !important;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 6px !important;
    padding: 5px 14px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    color: #4B5563 !important;
    border: none !important;
    background: transparent !important;
}
.stTabs [aria-selected="true"] {
    background: #FFFFFF !important;
    color: #111827 !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08) !important;
    font-weight: 600 !important;
}
.stTabs [data-baseweb="tab-border"], .stTabs [data-baseweb="tab-highlight"] {
    display: none !important;
}

/* 11. DataFrame Table Container */
div[data-testid="stDataFrame"] {
    border: 1px solid #E5E7EB !important;
    border-radius: 8px !important;
    overflow: hidden !important;
    background: #FFFFFF !important;
}

/* 12. File Uploader */
div[data-testid="stFileUploader"] {
    background: #FFFFFF !important;
    border: 1px dashed #D1D5DB !important;
    border-radius: 10px !important;
    padding: 14px !important;
}
div[data-testid="stFileUploader"]:hover {
    border-color: #0071E3 !important;
}
</style>
"""

# ---------------------------------------------------------------------------
# Session state initialization
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
    if "nav_tab" not in st.session_state:
        st.session_state.nav_tab = "Review"
    if "graph_thread_id" not in st.session_state:
        st.session_state.graph_thread_id = None
    if "unclaimed_decisions" not in st.session_state:
        st.session_state.unclaimed_decisions = {}


# ---------------------------------------------------------------------------
# Human-Readable Description Generator
# ---------------------------------------------------------------------------

def describe_recommendation(rec: Recommendation) -> Dict[str, str]:
    """
    Produce crystal-clear, plain-English explanations of what the reviewer is approving.
    Translates raw regex/internals into intuitive insurance data decisions.
    """
    op = rec.operation or ""
    action = rec.action_type
    src = rec.source_column
    tgt = rec.target_column

    if action == ActionType.COLUMN_MAPPING or op in ("column_rename", "trim_whitespace", ""):
        title = f"Map column '{src}' &rarr; '{tgt}'"
        summary = f"Assigns input column '{src}' to standard target field '{tgt}'."
        if rec.confidence >= 0.95:
            reason = f"Exact match: '{src}' is a recognized synonym for '{tgt}' in commercial property SOVs."
        elif rec.confidence >= 0.85:
            reason = f"High similarity: Column header and sample values match expected patterns for '{tgt}'."
        else:
            reason = f"Moderate similarity match: Please verify that '{src}' represents '{tgt}'."
        impact = f"In the finalized dataset, this column will be renamed to '{tgt}'."

    elif op == "strip_currency":
        title = f"Clean currency format in '{tgt}'"
        summary = "Removes currency symbols ($) and commas to store values as pure numeric floats."
        reason = f"Found currency symbols in {rec.affected_rows} row(s) for monetary field '{tgt}'."
        impact = "Converts formatted strings (e.g. '$1,500,000') into pure decimal numbers (1500000.0) required for underwriting models."

    elif op == "normalize_sprinkler_code":
        title = f"Standardize sprinkler indicators in '{tgt}'"
        summary = "Converts informal fire protection text to canonical insurance codes (Y, N, Y13, Y13R)."
        reason = f"Detected {rec.affected_rows} non-standard sprinkler value(s) in '{src}'."
        impact = "Replaces informal entries (e.g. 'Yes', 'No') with standardized codes."

    elif op in ("state_to_abbrev", "normalize_state"):
        title = f"Standardize US state code in '{tgt}'"
        summary = "Converts full state names or lowercase entries into standard 2-letter postal abbreviations."
        reason = f"Detected non-abbreviated state name in {rec.affected_rows} row(s)."
        impact = "Standardizes values to 2-letter ISO state codes (e.g. 'California' &rarr; 'CA')."

    elif op == "to_year_int":
        title = f"Standardize construction year in '{tgt}'"
        summary = "Converts year values to clean 4-digit integers."
        reason = f"Detected non-integer or decimal year formatting in {rec.affected_rows} row(s)."
        impact = "Ensures Year Built is stored as a valid integer year."

    elif op == "to_float":
        title = f"Format '{tgt}' as numeric float"
        summary = "Ensures numerical consistency for property exposure amounts."
        reason = f"Detected string-encoded numbers in {rec.affected_rows} row(s)."
        impact = "Casts text representations into standard floating point numbers."

    elif op == "to_int":
        title = f"Format '{tgt}' as integer"
        summary = "Ensures values in this column are clean whole numbers."
        reason = f"Detected float or string representations in {rec.affected_rows} row(s)."
        impact = "Stores whole-number values as integers. Fractional values (e.g. 1.5) are left unchanged for review, never truncated."

    elif op == "flag_for_review":
        title = f"Review data quality flag on '{tgt}'"
        summary = f"Flagged finding: {rec.affected_rows} row(s) have data quality concerns (such as missing values or out-of-range figures)."
        reason = rec.rationale if rec.rationale else f"Potential irregularity detected in '{tgt}'."
        impact = "No automated data alteration is made. Approving confirms reviewer awareness; rejecting dismisses this alert."

    else:
        title = f"Apply {op.replace('_', ' ').title()} to '{tgt}'"
        summary = f"Executes whitelisted transformation '{op}' on column '{tgt}'."
        reason = rec.rationale
        impact = f"Updates {rec.affected_rows} row(s) deterministically."

    return {
        "title": title,
        "summary": summary,
        "reason": reason,
        "impact": impact,
    }


# ---------------------------------------------------------------------------
# Header & Workflow Stepper
# ---------------------------------------------------------------------------

def render_header():
    st.markdown(
        """
        <div class="header-box">
            <h1>Agentic SOV Intelligence System</h1>
            <p>Deterministic transformation, cascading schema mapping, and human approval for commercial property SOVs.</p>
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
                f"<div style='font-size:13px;color:#111827;padding-top:6px;'>"
                f"Selected: <strong>{uploaded.name}</strong> "
                f"<span style='color:#6B7280;'>({ext.upper()}, {size_kb:.1f} KB)</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='font-size:13px;color:#6B7280;padding-top:6px;'>"
                "Supports multi-sheet workbooks, merged headers, and non-standard layouts (.xlsx, .xls, .csv)"
                "</div>",
                unsafe_allow_html=True,
            )

    with col_btn:
        if uploaded is not None:
            btn_box = st.empty()
            if btn_box.button("Run Pipeline", type="primary", key="btn_run_pipeline"):
                btn_box.empty()
                _show_pipeline_animation_and_run(uploaded)
                st.session_state.target_nav_tab = "Review"
                st.rerun()
        else:
            st.button("Run Pipeline", disabled=True, key="btn_run_pipeline_disabled")


_PIPELINE_ANIM_CSS = """
<style>
@keyframes agent-pulse {
    0%   { opacity: 0.35; transform: scale(0.97); }
    50%  { opacity: 1;    transform: scale(1.01); }
    100% { opacity: 0.35; transform: scale(0.97); }
}
@keyframes dot-bounce {
    0%, 80%, 100% { transform: translateY(0);   opacity: 0.4; }
    40%            { transform: translateY(-6px); opacity: 1;   }
}
@keyframes bar-slide {
    0%   { width: 0%;   }
    100% { width: 100%; }
}
.pipeline-overlay {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 14px;
    padding: 28px 32px 24px;
    margin: 18px 0 12px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.07);
    text-align: center;
}
.pipeline-title {
    font-size: 16px;
    font-weight: 600;
    color: #111827;
    margin-bottom: 4px;
    letter-spacing: -0.01em;
}
.pipeline-sub {
    font-size: 13px;
    color: #6B7280;
    margin-bottom: 22px;
}
.pipeline-bar-track {
    width: 100%;
    height: 4px;
    background: #F3F4F6;
    border-radius: 2px;
    overflow: hidden;
    margin-bottom: 24px;
}
.pipeline-bar-fill {
    height: 4px;
    background: linear-gradient(90deg, #0071E3 0%, #34D399 100%);
    border-radius: 2px;
    animation: bar-slide 12s ease-in-out forwards;
}
.pipeline-steps {
    display: flex;
    justify-content: center;
    gap: 14px;
    flex-wrap: wrap;
}
.pipeline-step {
    display: flex;
    align-items: center;
    gap: 7px;
    background: #F9FAFB;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12px;
    font-weight: 500;
    color: #4B5563;
    animation: agent-pulse 2.2s ease-in-out infinite;
}
.pipeline-step:nth-child(1) { animation-delay: 0.0s; }
.pipeline-step:nth-child(2) { animation-delay: 0.5s; }
.pipeline-step:nth-child(3) { animation-delay: 1.0s; }
.pipeline-step:nth-child(4) { animation-delay: 1.5s; }
.pipeline-step-dot {
    width: 7px; height: 7px;
    border-radius: 50%;
    background: #0071E3;
    flex-shrink: 0;
}
.pipeline-dots {
    display: flex;
    justify-content: center;
    gap: 6px;
    margin-top: 20px;
}
.pipeline-dots span {
    width: 7px; height: 7px;
    border-radius: 50%;
    background: #0071E3;
    display: inline-block;
    animation: dot-bounce 1.4s ease-in-out infinite;
}
.pipeline-dots span:nth-child(2) { animation-delay: 0.2s; }
.pipeline-dots span:nth-child(3) { animation-delay: 0.4s; }
</style>
"""

_PIPELINE_ANIM_HTML = """
<div class="pipeline-overlay">
    <div class="pipeline-title">Agents Working on Your Data</div>
    <div class="pipeline-sub">Running multi-stage intelligence cascade — this usually takes 10–30 seconds</div>
    <div class="pipeline-bar-track"><div class="pipeline-bar-fill"></div></div>
    <div class="pipeline-steps">
        <div class="pipeline-step">
            <div class="pipeline-step-dot"></div>Agent 1 · Sheet Discovery
        </div>
        <div class="pipeline-step">
            <div class="pipeline-step-dot" style="background:#8B5CF6;"></div>Agent 2 · Schema Mapping
        </div>
        <div class="pipeline-step">
            <div class="pipeline-step-dot" style="background:#F59E0B;"></div>Agent 3 · Quality Assessment
        </div>
        <div class="pipeline-step">
            <div class="pipeline-step-dot" style="background:#10B981;"></div>Human Review Ready
        </div>
    </div>
    <div class="pipeline-dots">
        <span></span><span></span><span></span>
    </div>
</div>
"""


def _show_pipeline_animation_and_run(uploaded_file):
    """Show animated agent progress card, run the pipeline, then clear the card."""
    anim_slot = st.empty()
    anim_slot.markdown(_PIPELINE_ANIM_CSS + _PIPELINE_ANIM_HTML, unsafe_allow_html=True)
    try:
        _run_pipeline(uploaded_file)
    finally:
        anim_slot.empty()


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
        # Agents 1–3 run through the LangGraph StateGraph, which pauses
        # (checkpointed) before the human_review node. A fresh thread per run
        # keeps a re-run from resuming an older pipeline.
        from app.orchestration.graph import run_pipeline_to_review

        thread_id = f"{session_id}-{uuid.uuid4().hex[:8]}"
        state = run_pipeline_to_review(state, thread_id=thread_id)
        if state.stage == WorkflowStage.ERROR:
            if state.sheet_manifest is None:
                st.error(f"Sheet discovery error: {state.error_message}")
            elif state.mappings is None:
                st.error(f"Schema mapping error: {state.error_message}")
            else:
                st.error(f"Quality assessment error: {state.error_message}")
            return

        st.session_state.graph_thread_id = thread_id
        state.stage = WorkflowStage.HUMAN_REVIEW

    except Exception as e:
        st.error(f"Pipeline execution failure: {e}")
        logger.exception("Pipeline error")
        return

    st.session_state.sov_state = state
    st.session_state.pipeline_ran = True
    st.session_state.review_complete = False
    st.session_state.transformed = False


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

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

    # Calculate mapping accuracy: predicted_columns_approved / total columns predicted * 100
    col_mapping_recs = [r for r in recs if r.action_type == ActionType.COLUMN_MAPPING]
    total_cols_predicted = len(col_mapping_recs)
    predicted_cols_approved = len([r for r in col_mapping_recs if r.status == RecommendationStatus.APPROVED])
    accuracy_pct = (predicted_cols_approved / total_cols_predicted * 100.0) if total_cols_predicted > 0 else 0.0

    # Action Bar: Approval & Transformation Controls + Accuracy KPI
    col_actions, col_accuracy, col_apply = st.columns([1.3, 0.9, 1.2])

    high_conf_pending = [r for r in pending if r.confidence >= config.HIGH_CONFIDENCE_THRESHOLD]

    with col_actions:
        if high_conf_pending:
            btn_h_box = st.empty()
            if btn_h_box.button(f"Approve All High-Confidence ({len(high_conf_pending)} items >=90%)", key="approve_high_btn"):
                btn_h_box.button("Approving High-Confidence...", disabled=True, key="appr_high_busy")
                for r in high_conf_pending:
                    _approve_recommendation(state, r.id)
                st.session_state.sov_state = state
                st.rerun()
        else:
            # Bulk approval never covers review-required items: low-confidence
            # recommendations must be decided one by one.
            optional_pending = [r for r in pending if not r.review_required]
            if optional_pending:
                btn_rem_box = st.empty()
                if btn_rem_box.button(f"Approve All Remaining ({len(optional_pending)} items)", key="approve_remaining_btn"):
                    btn_rem_box.button("Approving Remaining...", disabled=True, key="appr_rem_busy")
                    for r in optional_pending:
                        _approve_recommendation(state, r.id)
                    st.session_state.sov_state = state
                    st.rerun()
            elif pending:
                st.button(
                    f"Review Remaining Individually ({len(pending)} items)",
                    disabled=True,
                    key="approve_remaining_locked",
                )
            else:
                st.button(f"All High-Confidence Approved ({len(approved)} Approved)", disabled=True, key="approve_high_locked")

    with col_accuracy:
        st.markdown(
            f"""
            <div style="background:#FFFFFF;border:1px solid #E5E7EB;border-radius:8px;padding:6px 12px;text-align:center;box-shadow:0 1px 2px rgba(0,0,0,0.02);min-height:54px;display:flex;flex-direction:column;justify-content:center;">
                <div style="font-size:11px;font-weight:600;color:#6B7280;text-transform:uppercase;letter-spacing:0.04em;">Mapping Accuracy</div>
                <div style="font-size:18px;font-weight:700;color:#0071E3;line-height:1.2;">{accuracy_pct:.1f}%</div>
                <div style="font-size:10.5px;color:#9CA3AF;">{predicted_cols_approved} of {total_cols_predicted} approved</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_apply:
        if still_pending_required:
            st.button(
                f"Apply Approved Transformations ({len(still_pending_required)} Required Pending)",
                disabled=True,
                key="btn_apply_disabled_top",
            )
        else:
            btn_apply_box = st.empty()
            if btn_apply_box.button("Apply Approved Transformations", type="primary", key="btn_apply_transformations_top"):
                btn_apply_box.button("Applying Transformations...", disabled=True, key="btn_apply_active_top")
                with st.spinner("Applying approved transformations and generating audited deliverables..."):
                    state.unclaimed_decisions = st.session_state.get("unclaimed_decisions", {})
                    _run_transformation(state)
                st.session_state.transformed = True
                st.session_state.target_nav_tab = "Final Output"
                st.rerun()

    # Informational status banner
    if still_pending_required:
        st.markdown(
            f"<div style='font-size:13px;color:#B45309;background:#FFFBEB;border:1px solid #FDE68A;padding:8px 12px;border-radius:7px;margin-top:6px;'>"
            f"Export locked: {len(still_pending_required)} required review decision(s) pending."
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div style='font-size:13px;color:#047857;background:#ECFDF5;border:1px solid #A7F3D0;padding:8px 12px;border-radius:7px;margin-top:6px;'>"
            f"All required decisions complete. Ready for transformation."
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    # Grouped review sections
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
                _render_recommendation_card(state, rec)

    # Apply approved transformations also available at bottom when unlocked
    if not still_pending_required:
        st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
        btn_apply_bottom_box = st.empty()
        if btn_apply_bottom_box.button("Apply Approved Transformations", type="primary", key="btn_apply_transformations_bottom"):
            btn_apply_bottom_box.button("Applying Transformations...", disabled=True, key="btn_apply_active_bottom")
            with st.spinner("Applying approved transformations and generating audited deliverables..."):
                state.unclaimed_decisions = st.session_state.get("unclaimed_decisions", {})
                _run_transformation(state)
            st.session_state.transformed = True
            st.session_state.target_nav_tab = "Final Output"
            st.rerun()

    # Unclaimed columns section — rendered below everything else in the Review tab
    render_unclaimed_section(state)


def _render_recommendation_card(state: SOVState, rec: Recommendation):
    details = describe_recommendation(rec)
    if rec.status == RecommendationStatus.ESCALATED:
        details["impact"] = "Not applied. Escalated to a human reviewer: the column stays unmapped unless a target is assigned."
    elif rec.status == RecommendationStatus.REJECTED:
        details["impact"] = "Not applied: rejected by the reviewer."

    # Badges
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
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;">
                <div>
                    <span style="font-family:monospace;font-size:11px;color:#6B7280;margin-right:6px;">{rec.id}</span>
                    <strong style="font-size:14px;color:#111827;">{details['title']}</strong>
                </div>
                <div style="display:flex;gap:6px;align-items:center;">
                    <span class="badge {conf_cls}">Confidence {conf_pct}</span>
                    <span class="badge {status_cls}">{rec.status.upper()}</span>
                </div>
            </div>
            <div style="font-size:13px;color:#374151;margin-bottom:6px;line-height:1.4;">
                {details['summary']}
            </div>
            <div style="font-size:12px;color:#6B7280;margin-bottom:8px;line-height:1.4;">
                <strong>Why:</strong> {details['reason']}
            </div>
            <div style="font-size:12px;color:#6B7280;margin-bottom:10px;line-height:1.4;">
                <strong>Impact:</strong> {details['impact']}
            </div>
        """,
        unsafe_allow_html=True,
    )

    if rec.before_example or rec.after_example:
        st.markdown(
            f"""
            <div style="background:#F9FAFB;border:1px solid #E5E7EB;border-radius:6px;padding:6px 12px;font-size:12px;color:#374151;margin-bottom:10px;">
                <span style="color:#6B7280;">Before:</span> <code>{rec.before_example or 'None'}</code>
                <span style="margin:0 8px;color:#9CA3AF;">→</span>
                <span style="color:#6B7280;">After:</span> <code>{rec.after_example or 'None'}</code>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if rec.uncertainty:
        st.markdown(
            f"<div style='font-size:12px;color:#B45309;margin-bottom:8px;'>Note: {rec.uncertainty}</div>",
            unsafe_allow_html=True,
        )

    # Action Toolbar
    col_appr, col_rej, col_edit, col_space = st.columns([1, 1, 1, 3])

    if rec.status == RecommendationStatus.PENDING:
        with col_appr:
            if st.button("Approve", key=f"app_{rec.id}"):
                _approve_recommendation(state, rec.id)
                st.session_state.sov_state = state
                st.rerun()

        with col_rej:
            if st.button("Reject", key=f"rej_{rec.id}"):
                _reject_recommendation(state, rec.id, note="")
                st.session_state.sov_state = state
                st.rerun()

        with col_edit:
            if st.button("Change Target", key=f"edit_{rec.id}"):
                st.session_state[f"show_edit_{rec.id}"] = not st.session_state.get(f"show_edit_{rec.id}", False)
                st.rerun()

    elif rec.status == RecommendationStatus.APPROVED:
        with col_appr:
            st.markdown("<span style='font-size:12px;color:#047857;font-weight:500;'>Approved</span>", unsafe_allow_html=True)
        with col_rej:
            if st.button("Revert to Pending", key=f"revert_{rec.id}"):
                _revert_recommendation(state, rec.id)
                st.session_state.sov_state = state
                st.rerun()

    elif rec.status == RecommendationStatus.REJECTED:
        with col_appr:
            if st.button("Re-Approve", key=f"reapp_{rec.id}"):
                _approve_recommendation(state, rec.id)
                st.session_state.sov_state = state
                st.rerun()
        with col_rej:
            rej_label = "Rejected (Column will be dropped)" if rec.action_type == ActionType.COLUMN_MAPPING else "Rejected"
            st.markdown(f"<span style='font-size:12px;color:#B91C1C;font-weight:500;'>{rej_label}</span>", unsafe_allow_html=True)

    elif rec.status == RecommendationStatus.ESCALATED:
        with col_appr:
            st.markdown("<span style='font-size:12px;color:#6D28D9;font-weight:500;'>Escalated to human</span>", unsafe_allow_html=True)
        if rec.action_type == ActionType.COLUMN_MAPPING:
            with col_edit:
                if st.button("Assign Target", key=f"edit_{rec.id}"):
                    st.session_state[f"show_edit_{rec.id}"] = not st.session_state.get(f"show_edit_{rec.id}", False)
                    st.rerun()

    # Expandable edit target field (saves as human feedback to ChromaDB)
    if st.session_state.get(f"show_edit_{rec.id}"):
        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
        current_target = rec.target_column if rec.target_column in TARGET_FIELDS else TARGET_FIELDS[0]
        target_idx = TARGET_FIELDS.index(current_target) if current_target in TARGET_FIELDS else 0
        new_target = st.selectbox("Assign to Standard Field (Stores as feedback in ChromaDB)", TARGET_FIELDS, index=target_idx, key=f"sel_target_{rec.id}")
        ce1, ce2, _ = st.columns([1.2, 1, 3])
        with ce1:
            if st.button("Save & Assign Target", key=f"save_edit_{rec.id}"):
                _edit_and_approve_recommendation(state, rec.id, new_target)
                st.session_state[f"show_edit_{rec.id}"] = False
                st.session_state.sov_state = state
                st.rerun()
        with ce2:
            if st.button("Cancel", key=f"canc_edit_{rec.id}"):
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


def _revert_recommendation(state: SOVState, rec_id: str):
    for i, rec in enumerate(state.recommendations):
        if rec.id == rec_id:
            state.recommendations[i] = rec.model_copy(
                update={"status": RecommendationStatus.PENDING}
            )
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
                    "uncertainty": "User manually assigned target (saved as human feedback).",
                    "confidence": 1.0,
                }
            )
            # Sync internal state.mappings if available
            if state.mappings and getattr(state.mappings, "mappings", None):
                for m in state.mappings.mappings:
                    if m.source_column == rec.source_column:
                        m.target = new_target
                        m.confidence = 1.0
                        m.rationale = f"Manually assigned by reviewer to '{new_target}' (feedback)."
                        break
            if rec.action_type == ActionType.COLUMN_MAPPING:
                try:
                    from app.services.memory.chroma_store import store_approved_mapping
                    store_approved_mapping(
                        source_column=rec.source_column,
                        target_field=new_target,
                        confidence=1.0,
                        method="human_feedback",
                    )
                except Exception as e:
                    logger.warning("Memory store error: %s", e)
            break


def _run_rereason(state: SOVState):
    from app.agents.quality_reasoning import run_quality_reasoning
    try:
        handled = {
            r.id for r in state.recommendations
            if r.status == RecommendationStatus.REJECTED and r.rejection_note and not r.feedback_processed
        }
        new_state = run_quality_reasoning(state)
        # Feedback consumed here, so the graph does not re-reason on it again
        state.recommendations = [
            r.model_copy(update={"feedback_processed": True}) if r.id in handled else r
            for r in new_state.recommendations
        ]
        state.quality_report = new_state.quality_report
        state.stage = WorkflowStage.HUMAN_REVIEW
        st.session_state.sov_state = state
    except Exception as e:
        st.error(f"Re-reasoning failed: {e}")


# ---------------------------------------------------------------------------
# Unclaimed Columns Section
# ---------------------------------------------------------------------------

def render_unclaimed_section(state: SOVState):
    """Render the 'Unclaimed Source Columns' section at the bottom of the Review tab."""
    if state.mappings is None:
        return

    unclaimed_cols = state.mappings.unmapped_source_columns
    if not unclaimed_cols:
        return

    from app.agents.transformation import _load_source_df

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

    with st.expander(f"Unclaimed Source Columns ({len(unclaimed_cols)})", expanded=False):
        st.markdown(
            "<div style='font-size:13px;color:#6B7280;margin-bottom:12px;'>"
            "These source columns were not mapped to any of the 17 standard fields by the agents. "
            "Manually assign each column to a target field, or reject it to exclude it from the output."
            "</div>",
            unsafe_allow_html=True,
        )

        # Load a sample of source data for preview (best-effort)
        source_df = None
        try:
            source_df = _load_source_df(state)
        except Exception:
            pass

        decisions: Dict[str, str] = st.session_state.get("unclaimed_decisions", {})

        for col in unclaimed_cols:
            current = decisions.get(col, "")

            # Determine card border color based on current decision
            if current == "__rejected__":
                border_color = "#FECACA"  # red
                status_label = "<span style='color:#B91C1C;font-size:11px;font-weight:600;'>REJECTED</span>"
            elif current:
                border_color = "#A7F3D0"  # green
                status_label = f"<span style='color:#047857;font-size:11px;font-weight:600;'>ASSIGNED → {current}</span>"
            else:
                border_color = "#E5E7EB"  # neutral
                status_label = "<span style='color:#6B7280;font-size:11px;'>No action</span>"

            st.markdown(
                f"""
                <div style="background:#FFFFFF;border:1px solid {border_color};border-radius:10px;
                            padding:14px 16px;margin-bottom:10px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                        <strong style="font-size:14px;color:#111827;font-family:monospace;">{col}</strong>
                        {status_label}
                    </div>
                """,
                unsafe_allow_html=True,
            )

            # Sample values preview
            if source_df is not None and col in source_df.columns:
                samples = source_df[col].dropna().astype(str).head(4).tolist()
                if samples:
                    sample_str = " · ".join(f"<code>{s[:30]}</code>" for s in samples)
                    st.markdown(
                        f"<div style='font-size:12px;color:#6B7280;margin-bottom:10px;'>"
                        f"Sample values: {sample_str}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

            st.markdown("</div>", unsafe_allow_html=True)

            # Controls row
            col_sel, col_assign_btn, col_rej_btn, _ = st.columns([3, 1, 1, 2])

            with col_sel:
                # Build options: blank placeholder + all 17 target fields
                options = [""] + list(TARGET_FIELDS)
                current_idx = options.index(current) if current in options else 0
                chosen = st.selectbox(
                    "Assign to",
                    options=options,
                    index=current_idx,
                    key=f"uncl_sel_{col}",
                    label_visibility="collapsed",
                    format_func=lambda x: "— Select target field —" if x == "" else x,
                )

            with col_assign_btn:
                if st.button("Assign", key=f"uncl_assign_{col}", disabled=(not chosen)):
                    decisions[col] = chosen
                    st.session_state.unclaimed_decisions = decisions
                    st.rerun()

            with col_rej_btn:
                if current == "__rejected__":
                    if st.button("Undo", key=f"uncl_undo_{col}"):
                        decisions.pop(col, None)
                        st.session_state.unclaimed_decisions = decisions
                        st.rerun()
                else:
                    if st.button("Reject", key=f"uncl_rej_{col}"):
                        decisions[col] = "__rejected__"
                        st.session_state.unclaimed_decisions = decisions
                        st.rerun()


def _run_transformation(state: SOVState):
    from app.agents.transformation import run_transformation
    from app.orchestration.graph import resume_pipeline_after_review
    with st.spinner("Executing transformations…"):
        try:
            final_state = None
            thread_id = st.session_state.get("graph_thread_id")
            if thread_id:
                # Resume the paused graph: human_review → transform_export
                try:
                    final_state = resume_pipeline_after_review(state, thread_id=thread_id)
                    if final_state.stage not in (WorkflowStage.COMPLETE, WorkflowStage.VALIDATING, WorkflowStage.ERROR):
                        logger.warning("Graph stopped at '%s' — running Agent 4 directly.", final_state.stage)
                        final_state = None
                except Exception as e:
                    logger.warning("Graph resume failed (%s) — running Agent 4 directly.", e)
                    final_state = None
            if final_state is None:
                # No resumable checkpoint (e.g. app restarted): same Agent 4 node, called directly
                final_state = run_transformation(state)
            st.session_state.sov_state = final_state
            st.session_state.transformed = True
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

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

    if result.unmapped_target_fields:
        unmapped_str = ", ".join(result.unmapped_target_fields)
        st.markdown(
            f"<div style='font-size:12px;color:#B45309;background:#FFFBEB;border:1px solid #FDE68A;padding:8px 12px;border-radius:6px;margin-bottom:12px;'>"
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
    st.dataframe(df, width="stretch", hide_index=True)

    # Machine-readable mapping output (source → target, confidence, method, evidence)
    mapping_json = result.model_dump(mode="json")
    with st.expander("Mapping JSON output", expanded=False):
        semantic = [m.source_column for m in result.mappings if m.method == "semantic"]
        if semantic:
            st.caption("Semantic (embedding) matches: " + ", ".join(semantic))
        st.json(mapping_json, expanded=3)
    import json as _json
    st.download_button(
        label="Download mapping JSON",
        data=_json.dumps(mapping_json, indent=2),
        file_name="Schema_Mapping.json",
        mime="application/json",
        key="dl_mapping_json",
    )


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
            <div class="surface-card" style="margin-bottom:14px;">
                <div style="font-size:13px;color:#111827;">
                    <strong>Primary Sheet:</strong> <code>{primary.sheet_name}</code>
                    <span style="margin:0 8px;color:#9CA3AF;">|</span>
                    <span>Header Row: {primary.header_row} (0-indexed)</span>
                    <span style="margin:0 8px;color:#9CA3AF;">|</span>
                    <span>Confidence: {primary.confidence:.1%}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if len(state.data_sheets) > 1:
        st.caption(
            f"{len(state.data_sheets)} data sheets merged into one output: "
            + ", ".join(state.data_sheets)
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

    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    if primary and primary.reasoning:
        with st.expander("Discovery Reasoning Details", expanded=False):
            for r in primary.reasoning:
                st.markdown(f"<div style='font-size:13px;color:#4B5563;'>• {r}</div>", unsafe_allow_html=True)


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

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

    # Per-field completeness (share of rows with a value, per target field)
    if qr.completeness_by_field:
        mapped_targets = {m.target for m in (state.mappings.mappings if state.mappings else []) if m.target}
        with st.expander(f"Per-field completeness ({qr.total_rows} rows)", expanded=True):
            comp_rows = [
                {
                    "Target Field": field,
                    "Completeness": pct / 100.0,
                    "Status": "Mapped" if field in mapped_targets else "No source column",
                }
                for field, pct in qr.completeness_by_field.items()
            ]
            st.dataframe(
                pd.DataFrame(comp_rows),
                width="stretch",
                hide_index=True,
                column_config={
                    "Completeness": st.column_config.ProgressColumn(
                        "Completeness", format="percent", min_value=0.0, max_value=1.0,
                    ),
                },
            )

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
        st.dataframe(pd.DataFrame(issue_rows), width="stretch", hide_index=True)
    else:
        st.markdown("<div style='font-size:13px;color:#047857;padding:8px 0;'>No data quality issues detected.</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Section 6: Data Preview (Before & After)
# ---------------------------------------------------------------------------

def _display_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Display-only copy: mixed-type raw columns (1980 and "1980's") as text, so Arrow can render them."""
    out = df.copy()
    for col in out.columns:
        values = out[col].dropna()
        if out[col].dtype == object and values.map(type).nunique() > 1:
            out[col] = out[col].map(lambda v: v if pd.isna(v) else str(v))
    return out


def render_preview_section(state: SOVState):
    from app.agents.transformation import _load_source_df, generate_preview_df

    source_df = _load_source_df(state)
    approved = [r for r in state.recommendations if r.status == RecommendationStatus.APPROVED]
    preview_df = generate_preview_df(state, approved) if approved else pd.DataFrame()

    col_before, col_after = st.columns(2)

    with col_before:
        st.markdown("<strong style='font-size:13px;color:#111827;'>Raw Source Data</strong>", unsafe_allow_html=True)
        if source_df is not None and not source_df.empty:
            st.dataframe(_display_safe(source_df.head(15)), width="stretch")
        else:
            st.caption("Source data not loaded.")

    with col_after:
        st.markdown("<strong style='font-size:13px;color:#111827;'>Transformed Output (17 Standard Fields)</strong>", unsafe_allow_html=True)
        if not preview_df.empty:
            st.dataframe(_display_safe(preview_df.head(15)), width="stretch")
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
                f"<div style='font-size:13px;color:#B45309;background:#FFFBEB;border:1px solid #FDE68A;padding:12px 16px;border-radius:8px;'>"
                f"Export locked. Please complete the {len(still_pending_required)} required review decision(s) in the Review section."
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='font-size:13px;color:#4B5563;background:#F3F4F6;border:1px solid #E5E7EB;padding:12px 16px;border-radius:8px;'>"
                "Review complete. Click 'Apply Approved Transformations' in the Review section to build deliverables."
                "</div>",
                unsafe_allow_html=True,
            )
        return

    # Validation banner
    if state.validation_passed:
        st.markdown(
            f"""
            <div style="background:#ECFDF5;border:1px solid #A7F3D0;border-radius:8px;padding:12px 16px;margin-bottom:18px;">
                <div style="font-size:14px;font-weight:600;color:#047857;margin-bottom:2px;">
                    Validation Passed: Exact 17-Column Schema
                </div>
                <div style="font-size:12px;color:#065F46;">
                    Output data strictly adheres to target column types and order without fabricated missing values.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div style="background:#FEF2F2;border:1px solid #FECACA;border-radius:8px;padding:12px 16px;margin-bottom:18px;">
                <div style="font-size:14px;font-weight:600;color:#B91C1C;margin-bottom:2px;">
                    Validation Warning
                </div>
                <div style="font-size:12px;color:#991B1B;">
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
            )

    if state.output_path and Path(state.output_path).exists():
        _render_schema_conformance(state.output_path)

    # Audit Trail summary
    if state.audit_log:
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        with st.expander(f"Audit Trail ({len(state.audit_log)} logged entries)", expanded=True):
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
            st.dataframe(pd.DataFrame(audit_rows), width="stretch", hide_index=True)


def _render_schema_conformance(output_path: str):
    """Show the written Cleaned_SOV.xlsx: headers, field types, merged cells, first rows."""
    import openpyxl
    from app.processing.validation import TARGET_COLUMN_ORDER
    from app.schemas.target_schema import TARGET_DTYPES

    ws = openpyxl.load_workbook(output_path, read_only=False)["Cleaned_SOV"]
    headers = [c.value for c in ws[1]]
    merged = len(ws.merged_cells.ranges)
    cleaned = pd.read_excel(output_path, sheet_name="Cleaned_SOV")

    def conforms(col: str) -> str:
        expected = TARGET_DTYPES[col]
        values = cleaned[col].dropna()
        if values.empty:
            return "Empty"
        if expected == "str":
            return "OK"
        nums = pd.to_numeric(values, errors="coerce")
        if nums.isna().any():
            return f"{int(nums.isna().sum())} non-numeric"
        if expected == "int" and not (nums == nums.round()).all():
            return f"{int((nums != nums.round()).sum())} non-integer"
        return "OK"

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        ok = headers == TARGET_COLUMN_ORDER
        st.markdown(
            f"<div class='stat-pill'><div class='stat-pill-val'>{len(headers)} {'✓' if ok else '✗'}</div>"
            f"<div class='stat-pill-lbl'>Columns, exact names & order</div></div>",
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"<div class='stat-pill'><div class='stat-pill-val'>{merged} {'✓' if merged == 0 else '✗'}</div>"
            f"<div class='stat-pill-lbl'>Merged cell ranges</div></div>",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f"<div class='stat-pill'><div class='stat-pill-val'>{len(cleaned)}</div>"
            f"<div class='stat-pill-lbl'>Data rows</div></div>",
            unsafe_allow_html=True,
        )

    with st.expander("Schema conformance (headers & data types)", expanded=True):
        st.dataframe(
            pd.DataFrame([
                {
                    "#": i,
                    "Header in file": h,
                    "Expected": TARGET_COLUMN_ORDER[i - 1] if i <= len(TARGET_COLUMN_ORDER) else "",
                    "Expected type": TARGET_DTYPES.get(h, ""),
                    "Values": conforms(h) if h in TARGET_DTYPES else "",
                }
                for i, h in enumerate(headers, 1)
            ]),
            width="stretch",
            hide_index=True,
        )

    with st.expander("Cleaned output (first 20 rows)", expanded=True):
        st.dataframe(cleaned.head(20), width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Sidebar (Minimal Controls)
# ---------------------------------------------------------------------------

def render_sidebar(state: Optional[SOVState]):
    with st.sidebar:
        st.markdown("<strong style='font-size:14px;color:#111827;'>System Configuration</strong>", unsafe_allow_html=True)
        st.caption("Enterprise SOV Cleansing & Validation")

        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

        llm_avail = config.is_llm_available()
        status_text = f"{config.LLM_PROVIDER.upper()} Active" if llm_avail else "Deterministic Mode"
        badge_cls = "badge-green" if llm_avail else "badge-neutral"

        st.markdown(
            f"""
            <div style="background:#FFFFFF;border:1px solid #E5E7EB;border-radius:8px;padding:10px 12px;margin-bottom:12px;">
                <div style="font-size:11px;color:#6B7280;text-transform:uppercase;margin-bottom:4px;">LLM Gateway</div>
                <span class="badge {badge_cls}">{status_text}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if state and state.file_meta:
            st.markdown(
                f"""
                <div style="background:#FFFFFF;border:1px solid #E5E7EB;border-radius:8px;padding:10px 12px;margin-bottom:12px;font-size:12px;color:#111827;">
                    <div style="font-size:11px;color:#6B7280;text-transform:uppercase;margin-bottom:4px;">Active Session</div>
                    <div><strong>File:</strong> {state.file_meta.original_filename}</div>
                    <div><strong>Sheet:</strong> {state.primary_sheet_name or 'None'}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        if st.button("Reset Session", key="btn_reset_session"):
            st.session_state.sov_state = None
            st.session_state.pipeline_ran = False
            st.session_state.review_complete = False
            st.session_state.transformed = False
            st.session_state.unclaimed_decisions = {}
            st.session_state.target_nav_tab = "Review"
            st.session_state.nav_tab = "Review"
            st.session_state.session_id = uuid.uuid4().hex[:12]
            st.rerun()


# ---------------------------------------------------------------------------
# Main App Structure
# ---------------------------------------------------------------------------

def main():
    st.markdown(APPLE_CSS, unsafe_allow_html=True)
    if "target_nav_tab" in st.session_state:
        st.session_state.nav_tab = st.session_state.pop("target_nav_tab")
    init_session()
    state: Optional[SOVState] = st.session_state.sov_state

    render_header()
    render_stepper(state)
    render_upload_section()
    render_sidebar(state)

    if state and st.session_state.pipeline_ran:
        st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

        tab_labels = [
            "Review",
            "Data Preview",
            "Schema Mapping",
            "Sheet Detection",
            "Data Quality",
            "Final Output",
        ]
        current_tab = st.segmented_control(
            "Workflow Navigation",
            options=tab_labels,
            key="nav_tab",
            label_visibility="collapsed",
        )
        active = current_tab or st.session_state.get("nav_tab", "Review")

        if active == "Review":
            render_review_section(state)
        elif active == "Data Preview":
            render_preview_section(state)
        elif active == "Schema Mapping":
            render_mapping_section(state)
        elif active == "Sheet Detection":
            render_discovery_section(state)
        elif active == "Data Quality":
            render_quality_section(state)
        elif active == "Final Output":
            render_export_section(state)


if __name__ == "__main__":
    main()
