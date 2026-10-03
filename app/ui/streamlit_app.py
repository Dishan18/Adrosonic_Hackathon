"""
Agentic SOV Intelligence System — Streamlit UI

Architecture:
  - Session state manages SOVState and workflow progression
  - Pipeline runs in stages via LangGraph
  - HITL review happens in the Human Review tab
  - Export locked until review complete
"""

from __future__ import annotations

import io
import logging
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

# Make app importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.schemas.state_models import (
    ActionType,
    Recommendation,
    RecommendationStatus,
    ReviewDecision,
    SOVState,
    WorkflowStage,
    HumanDecision,
)
from app.schemas.target_schema import TARGET_FIELDS
from app.orchestration.state import create_initial_state
from app.config import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="SOV Intelligence System",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

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


# ---------------------------------------------------------------------------
# Workflow stage indicator
# ---------------------------------------------------------------------------

def render_workflow_status(state: Optional[SOVState]):
    stages = [
        ("📂", "Upload", WorkflowStage.INIT),
        ("🔍", "Sheet Discovery", WorkflowStage.DISCOVERED),
        ("🗺️", "Schema Mapping", WorkflowStage.MAPPED),
        ("📊", "Quality & Reasoning", WorkflowStage.ASSESSED),
        ("👤", "Human Review", WorkflowStage.HUMAN_REVIEW),
        ("⚙️", "Transformation", WorkflowStage.TRANSFORMING),
        ("✅", "Complete", WorkflowStage.COMPLETE),
    ]

    current = state.stage if state else WorkflowStage.INIT
    stage_order = [s[2] for s in stages]

    try:
        current_idx = stage_order.index(current)
    except ValueError:
        current_idx = 0

    cols = st.columns(len(stages))
    for i, (icon, label, stage) in enumerate(stages):
        with cols[i]:
            if i < current_idx:
                st.markdown(f"<div style='text-align:center;color:#00C851;font-size:1.5em'>{icon}</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='text-align:center;font-size:0.75em;color:#00C851'>✓ {label}</div>", unsafe_allow_html=True)
            elif i == current_idx:
                st.markdown(f"<div style='text-align:center;color:#33b5e5;font-size:1.5em'>{icon}</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='text-align:center;font-size:0.75em;color:#33b5e5;font-weight:bold'>▶ {label}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div style='text-align:center;color:#888;font-size:1.5em'>{icon}</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='text-align:center;font-size:0.75em;color:#888'>{label}</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Tab: Upload
# ---------------------------------------------------------------------------

def render_upload_tab():
    st.header("📂 Upload SOV File")
    st.markdown(
        "Upload a **Statement of Values** file (.xlsx or .csv). "
        "Multi-sheet workbooks, merged cells, and non-standard headers are all supported."
    )

    uploaded = st.file_uploader(
        "Choose file",
        type=["xlsx", "xls", "csv"],
        key="file_uploader",
    )

    if uploaded is None:
        st.info("Please upload an SOV file to begin.")
        return

    if st.button("🚀 Run Pipeline", type="primary", key="run_pipeline_btn"):
        with st.spinner("Running AI pipeline…"):
            _run_pipeline(uploaded)


def _run_pipeline(uploaded_file):
    """Save upload, create state, run pipeline to human_review."""
    # Save to temp file
    ext = Path(uploaded_file.name).suffix.lower()
    upload_dir = Path(config.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    session_id = st.session_state.session_id
    temp_path = str(upload_dir / f"{session_id}{ext}")

    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getvalue())

    # Create initial state
    state = create_initial_state(
        file_path=temp_path,
        original_filename=uploaded_file.name,
        file_type=ext.lstrip("."),
        file_size_bytes=uploaded_file.size,
        session_id=session_id,
    )

    # Run agents 1-3 (stops before human_review)
    try:
        from app.agents.sheet_discovery import run_sheet_discovery
        from app.agents.schema_mapping import run_schema_mapping
        from app.agents.quality_reasoning import run_quality_reasoning

        state = run_sheet_discovery(state)
        if state.stage == WorkflowStage.ERROR:
            st.error(f"❌ Sheet Discovery failed: {state.error_message}")
            return

        state = run_schema_mapping(state)
        if state.stage == WorkflowStage.ERROR:
            st.error(f"❌ Schema Mapping failed: {state.error_message}")
            return

        state = run_quality_reasoning(state)
        if state.stage == WorkflowStage.ERROR:
            st.error(f"❌ Quality Assessment failed: {state.error_message}")
            return

        state.stage = WorkflowStage.HUMAN_REVIEW

    except Exception as e:
        st.error(f"❌ Pipeline error: {e}")
        logger.exception("Pipeline error")
        return

    st.session_state.sov_state = state
    st.session_state.pipeline_ran = True
    st.session_state.review_complete = False
    st.session_state.transformed = False
    st.success("✅ Pipeline complete. Review results in the tabs below.")
    st.rerun()


# ---------------------------------------------------------------------------
# Tab: Sheet Discovery
# ---------------------------------------------------------------------------

def render_discovery_tab(state: SOVState):
    st.header("🔍 Sheet Discovery & Intelligence")

    if state.sheet_manifest is None:
        st.warning("No sheet manifest available.")
        return

    manifest = state.sheet_manifest

    # Primary sheet info
    primary = manifest.primary
    if primary:
        st.success(
            f"**Primary Sheet:** `{primary.sheet_name}` | "
            f"Header Row: {primary.header_row} (0-indexed) | "
            f"Confidence: {primary.confidence:.1%}"
        )

    # All sheets table
    rows = []
    for s in manifest.sheets:
        rows.append({
            "Sheet": s.sheet_name,
            "Classification": s.classification,
            "Confidence": f"{s.confidence:.1%}",
            "Header Row": s.header_row,
            "Data Rows": s.profile.row_count - s.header_row - 1,
            "Field Matches": s.profile.candidate_field_matches,
            "Non-null %": f"{s.profile.non_null_ratio:.0%}",
            "Merged Cells": s.profile.merged_cell_count,
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)

    # Reasoning for primary
    if primary and primary.reasoning:
        with st.expander("📋 Discovery Reasoning", expanded=False):
            for reason in primary.reasoning:
                st.write(f"• {reason}")
            if primary.issues:
                st.warning("Issues: " + "; ".join(primary.issues))


# ---------------------------------------------------------------------------
# Tab: Schema Mapping
# ---------------------------------------------------------------------------

def render_mapping_tab(state: SOVState):
    st.header("🗺️ Schema Mapping")

    if state.mappings is None:
        st.warning("No mapping results available.")
        return

    result = state.mappings
    overall_conf = result.overall_mapping_confidence

    col1, col2, col3 = st.columns(3)
    with col1:
        mapped = [m for m in result.mappings if m.target]
        st.metric("Mapped Columns", f"{len(mapped)}/{len(result.mappings)}")
    with col2:
        st.metric("Overall Confidence", f"{overall_conf:.1%}")
    with col3:
        high_conf = sum(1 for m in result.mappings if m.confidence >= 0.90)
        st.metric("High Confidence (≥90%)", high_conf)

    if result.unmapped_target_fields:
        st.warning(f"Unmapped target fields: {', '.join(result.unmapped_target_fields)}")

    # Mapping table
    rows = []
    for m in result.mappings:
        rows.append({
            "Source Column": m.source_column,
            "Target Field": m.target or "⚠️ Unmapped",
            "Confidence": f"{m.confidence:.1%}",
            "Method": m.method,
            "Review Required": "⚠️ Yes" if m.review_required else "✓ No",
            "Rationale": m.rationale[:80] + "…" if len(m.rationale) > 80 else m.rationale,
        })

    df = pd.DataFrame(rows)
    # Color-code confidence
    st.dataframe(
        df,
        use_container_width=True,
        column_config={
            "Confidence": st.column_config.TextColumn("Confidence"),
            "Review Required": st.column_config.TextColumn("Review Required"),
        },
    )

    # Detail expander for each mapping
    with st.expander("🔍 Mapping Details", expanded=False):
        for m in result.mappings:
            with st.container():
                conf_color = "#00C851" if m.confidence >= 0.90 else "#ffbb33" if m.confidence >= 0.50 else "#ff4444"
                st.markdown(
                    f"**`{m.source_column}`** → **`{m.target or 'UNMAPPED'}`** "
                    f"<span style='color:{conf_color}'>{m.confidence:.1%}</span> [{m.method}]",
                    unsafe_allow_html=True,
                )
                if m.evidence:
                    for ev in m.evidence[:2]:
                        st.caption(ev)
                st.divider()


# ---------------------------------------------------------------------------
# Tab: Quality Report
# ---------------------------------------------------------------------------

def render_quality_tab(state: SOVState):
    st.header("📊 Data Quality Report")

    if state.quality_report is None:
        st.warning("No quality report available.")
        return

    qr = state.quality_report

    from app.services.scoring.quality_score import compute_sov_quality_score, score_summary
    score = compute_sov_quality_score(qr, state.mappings)
    summary = score_summary(score)

    # Score display
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("SOV Quality Score", f"{score:.1f}/100", delta=None)
    with col2:
        st.metric("Grade", summary["grade"])
    with col3:
        st.metric("Total Issues", len(qr.issues))
    with col4:
        high_issues = sum(1 for i in qr.issues if i.severity == "high")
        st.metric("Critical Issues", high_issues)

    # Completeness table
    if qr.completeness_by_field:
        with st.expander("📈 Field Completeness", expanded=True):
            comp_df = pd.DataFrame([
                {"Field": k, "Completeness %": f"{v:.1f}%"}
                for k, v in qr.completeness_by_field.items()
                if v > 0
            ])
            st.dataframe(comp_df, use_container_width=True)

    # Issues table
    if qr.issues:
        st.subheader(f"⚠️ {len(qr.issues)} Quality Issues Detected")
        issue_rows = []
        for issue in qr.issues:
            sev_icon = {"high": "🔴", "medium": "🟡", "low": "🟢", "info": "ℹ️"}.get(issue.severity, "")
            issue_rows.append({
                "ID": issue.issue_id,
                "Severity": f"{sev_icon} {issue.severity.upper()}",
                "Type": issue.issue_type,
                "Field": issue.affected_field,
                "Affected Rows": issue.affected_row_count,
                "Evidence": issue.evidence[:100],
                "Suggested Op": issue.suggested_operation,
            })
        st.dataframe(pd.DataFrame(issue_rows), use_container_width=True)
    else:
        st.success("✅ No quality issues detected!")


# ---------------------------------------------------------------------------
# Tab: Human Review
# ---------------------------------------------------------------------------

def render_review_tab(state: SOVState):
    st.header("👤 Human Review — Approve / Reject Recommendations")

    if not state.recommendations:
        st.info("No recommendations to review.")
        return

    recs = state.recommendations
    pending = [r for r in recs if r.status == RecommendationStatus.PENDING]
    approved = [r for r in recs if r.status == RecommendationStatus.APPROVED]
    rejected = [r for r in recs if r.status == RecommendationStatus.REJECTED]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total", len(recs))
    with col2:
        st.metric("Pending", len(pending))
    with col3:
        st.metric("Approved", len(approved))
    with col4:
        st.metric("Rejected", len(rejected))

    # Approve All (high confidence)
    high_conf_pending = [r for r in pending if r.confidence >= config.HIGH_CONFIDENCE_THRESHOLD]
    if high_conf_pending:
        if st.button(
            f"✅ Approve All High-Confidence ({len(high_conf_pending)} recommendations, ≥90%)",
            key="approve_all_btn",
        ):
            for rec in high_conf_pending:
                _approve_recommendation(state, rec.id)
            st.rerun()

    st.divider()

    # Review queue
    action_types = {
        ActionType.COLUMN_MAPPING: "🗺️ Column Mappings",
        ActionType.STANDARDISATION: "📐 Standardisation",
        ActionType.DATA_CORRECTION: "🔧 Data Corrections",
        ActionType.FLAG_FOR_REVIEW: "🚩 Flagged Items",
    }

    for action_type, label in action_types.items():
        type_recs = [r for r in recs if r.action_type == action_type]
        if not type_recs:
            continue

        with st.expander(f"{label} ({len(type_recs)})", expanded=(action_type == ActionType.COLUMN_MAPPING)):
            for rec in type_recs:
                _render_recommendation_card(state, rec)

    # Check if review complete
    still_pending_required = [
        r for r in state.recommendations
        if r.status == RecommendationStatus.PENDING and r.review_required
    ]

    if not still_pending_required:
        st.success("✅ All required recommendations have been decided!")
        if st.button("▶️ Apply Approved Transformations", type="primary", key="apply_btn"):
            _run_transformation(state)
    else:
        st.warning(
            f"⚠️ {len(still_pending_required)} required recommendations still pending. "
            "Export is locked until all are decided."
        )


def _render_recommendation_card(state: SOVState, rec: Recommendation):
    """Render a single recommendation with Approve/Reject/Edit controls."""
    status_colors = {
        RecommendationStatus.PENDING: "#888",
        RecommendationStatus.APPROVED: "#00C851",
        RecommendationStatus.REJECTED: "#ff4444",
        RecommendationStatus.ESCALATED: "#ff8800",
    }
    color = status_colors.get(rec.status, "#888")
    conf_pct = f"{rec.confidence:.0%}"

    with st.container():
        cols = st.columns([3, 1, 1, 1, 1])
        with cols[0]:
            st.markdown(
                f"**{rec.id}** — `{rec.source_column}` → `{rec.target_column}` "
                f"<span style='color:{color}'>● {rec.status.upper()}</span>",
                unsafe_allow_html=True,
            )
            st.caption(f"Op: `{rec.operation}` | Conf: {conf_pct} | Rows: {rec.affected_rows}")
            with st.expander("Details", expanded=False):
                st.write(f"**Rationale:** {rec.rationale}")
                if rec.before_example:
                    st.write(f"**Before:** `{rec.before_example}`")
                if rec.after_example:
                    st.write(f"**After:** `{rec.after_example}`")
                if rec.uncertainty:
                    st.warning(f"**Uncertainty:** {rec.uncertainty}")

        if rec.status == RecommendationStatus.PENDING:
            with cols[1]:
                if st.button("✅ Approve", key=f"approve_{rec.id}"):
                    _approve_recommendation(state, rec.id)
                    st.rerun()

            with cols[2]:
                if st.button("❌ Reject", key=f"reject_{rec.id}"):
                    st.session_state[f"show_reject_{rec.id}"] = True

            if st.session_state.get(f"show_reject_{rec.id}"):
                note = st.text_input(
                    f"Rejection note for {rec.id} (optional)",
                    key=f"note_{rec.id}",
                )
                col_confirm, col_cancel = st.columns(2)
                with col_confirm:
                    if st.button("Confirm Reject", key=f"confirm_reject_{rec.id}"):
                        _reject_recommendation(state, rec.id, note)
                        st.session_state[f"show_reject_{rec.id}"] = False
                        st.rerun()
                with col_cancel:
                    if st.button("Cancel", key=f"cancel_reject_{rec.id}"):
                        st.session_state[f"show_reject_{rec.id}"] = False
                        st.rerun()

        st.divider()


def _approve_recommendation(state: SOVState, rec_id: str):
    """Approve a recommendation in session state."""
    for i, rec in enumerate(state.recommendations):
        if rec.id == rec_id:
            state.recommendations[i] = rec.model_copy(
                update={"status": RecommendationStatus.APPROVED}
            )
            # Store approved mapping in ChromaDB if it's a column mapping
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
                    logger.warning("Failed to store mapping in memory: %s", e)
            break


def _reject_recommendation(state: SOVState, rec_id: str, note: str = ""):
    """Reject a recommendation and optionally trigger re-reasoning."""
    for i, rec in enumerate(state.recommendations):
        if rec.id == rec_id:
            new_count = rec.re_reason_count + 1
            new_status = (
                RecommendationStatus.REJECTED
                if new_count >= config.MAX_REREASON_ATTEMPTS
                else RecommendationStatus.REJECTED
            )
            state.recommendations[i] = rec.model_copy(
                update={
                    "status": new_status,
                    "rejection_note": note,
                    "re_reason_count": new_count,
                }
            )
            # Trigger re-reasoning if note provided and under limit
            if note and new_count < config.MAX_REREASON_ATTEMPTS:
                state.re_reason_feedback = f"Rec {rec_id} rejected: {note}"
                _run_rereason(state)
            break


def _run_rereason(state: SOVState):
    """Run Agent 3 again with feedback."""
    from app.agents.quality_reasoning import run_quality_reasoning
    try:
        new_state = run_quality_reasoning(state)
        # Merge new recommendations for the rejected item
        state.recommendations = new_state.recommendations
        state.quality_report = new_state.quality_report
        state.stage = WorkflowStage.HUMAN_REVIEW
        st.session_state.sov_state = state
    except Exception as e:
        st.error(f"Re-reasoning failed: {e}")


def _run_transformation(state: SOVState):
    """Run Agent 4 after all approvals."""
    from app.agents.transformation import run_transformation
    with st.spinner("⚙️ Applying approved transformations…"):
        try:
            final_state = run_transformation(state)
            st.session_state.sov_state = final_state
            st.session_state.transformed = True
            if final_state.validation_passed:
                st.success("✅ Transformation complete and validation passed!")
            else:
                st.error(f"Validation errors: {final_state.validation_errors}")
            st.rerun()
        except Exception as e:
            st.error(f"Transformation failed: {e}")
            logger.exception("Transformation error")


# ---------------------------------------------------------------------------
# Tab: Preview & Export
# ---------------------------------------------------------------------------

def render_export_tab(state: SOVState):
    st.header("📥 Preview & Export")

    if not st.session_state.get("transformed"):
        # Show before/after preview
        st.info("Complete the Human Review step and apply transformations to enable download.")

        if state.recommendations:
            approved = [r for r in state.recommendations if r.status == RecommendationStatus.APPROVED]
            if approved:
                st.subheader("Preview with Approved Transformations")
                try:
                    from app.agents.transformation import generate_preview_df
                    preview_df = generate_preview_df(state, approved)
                    if not preview_df.empty:
                        st.dataframe(preview_df.head(20), use_container_width=True)
                except Exception as e:
                    st.warning(f"Preview unavailable: {e}")
        return

    if not state.validation_passed:
        st.error("❌ Validation failed. Cannot export.")
        if state.validation_errors:
            for err in state.validation_errors:
                st.write(f"• {err}")
        return

    # Cleaned SOV download
    st.success("✅ Transformation and validation complete!")

    if state.output_path and Path(state.output_path).exists():
        with open(state.output_path, "rb") as f:
            data = f.read()
        st.download_button(
            label="⬇️ Download Cleaned_SOV.xlsx",
            data=data,
            file_name="Cleaned_SOV.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_sov_btn",
        )

        # Preview
        try:
            preview_df = pd.read_excel(state.output_path, sheet_name="Cleaned_SOV")
            st.subheader(f"Preview: {len(preview_df)} rows × {len(preview_df.columns)} columns")
            st.dataframe(preview_df.head(20), use_container_width=True)
            st.caption(f"Schema: {list(preview_df.columns)}")
        except Exception as e:
            st.warning(f"Preview error: {e}")
    else:
        st.warning("Output file not found.")

    # Audit log download
    if state.audit_log_path and Path(state.audit_log_path).exists():
        with open(state.audit_log_path, "rb") as f:
            audit_data = f.read()
        st.download_button(
            label="⬇️ Download Audit_Log.xlsx",
            data=audit_data,
            file_name="Audit_Log.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_audit_btn",
        )

    # Validation details
    with st.expander("🔍 Validation Report", expanded=False):
        st.write("**Status:** ✅ PASSED" if state.validation_passed else "**Status:** ❌ FAILED")
        st.write(f"**Columns:** {len(TARGET_FIELDS)} (exact 17-field SOV schema)")
        st.write(f"**Column Order:** {TARGET_FIELDS}")
        if state.validation_errors:
            for err in state.validation_errors:
                st.write(f"• ❌ {err}")

    # Audit log preview
    if state.audit_log:
        with st.expander(f"📋 Audit Log ({len(state.audit_log)} entries)", expanded=False):
            audit_rows = []
            for entry in state.audit_log:
                audit_rows.append({
                    "Entry ID": entry.entry_id,
                    "Source": entry.source_column,
                    "Target": entry.target_column,
                    "Operation": entry.transformation_applied,
                    "Before": str(entry.before_value)[:50],
                    "After": str(entry.after_value)[:50],
                    "Confidence": f"{entry.confidence:.0%}",
                    "Approved By": entry.approved_by,
                    "Time": entry.timestamp,
                })
            st.dataframe(pd.DataFrame(audit_rows), use_container_width=True)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar(state: Optional[SOVState]):
    with st.sidebar:
        st.title("🏢 SOV Intelligence")
        st.caption("Agentic SOV Cleansing System")

        if state:
            st.divider()
            st.subheader("📊 Status")
            st.write(f"**Stage:** {state.stage}")
            if state.file_meta:
                st.write(f"**File:** {state.file_meta.original_filename}")
            if state.primary_sheet_name:
                st.write(f"**Sheet:** {state.primary_sheet_name}")
            if state.quality_report:
                score = state.quality_report.overall_quality_score
                st.metric("Quality Score", f"{score:.1f}/100")

            st.divider()
            st.subheader("🤖 LLM Status")
            if config.is_llm_available():
                st.success(f"✅ {config.LLM_PROVIDER.upper()} ready")
            else:
                st.warning("⚠️ LLM not configured (deterministic mode)")
                st.caption("Set GROQ_API_KEY in .env to enable LLM features.")

        st.divider()
        st.caption("Design: AI proposes. Code verifies. Humans approve. Everything is audited.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    init_session()
    state: Optional[SOVState] = st.session_state.sov_state

    # Header
    st.title("🏢 Agentic SOV Intelligence System")
    st.caption(
        "Upload chaotic SOV files → AI-powered schema mapping → Human review → "
        "Audit-ready Cleaned_SOV.xlsx"
    )

    render_sidebar(state)

    # Workflow indicator
    st.divider()
    render_workflow_status(state)
    st.divider()

    # Tabs
    tab_labels = [
        "📂 Upload",
        "🔍 Sheet Discovery",
        "🗺️ Schema Mapping",
        "📊 Quality Report",
        "👤 Human Review",
        "📥 Export",
    ]

    tabs = st.tabs(tab_labels)

    with tabs[0]:
        render_upload_tab()

    with tabs[1]:
        if state and state.sheet_manifest:
            render_discovery_tab(state)
        elif st.session_state.pipeline_ran:
            st.warning("Sheet discovery data not available.")
        else:
            st.info("Upload a file to start.")

    with tabs[2]:
        if state and state.mappings:
            render_mapping_tab(state)
        elif st.session_state.pipeline_ran:
            st.warning("Mapping data not available.")
        else:
            st.info("Upload a file to start.")

    with tabs[3]:
        if state and state.quality_report:
            render_quality_tab(state)
        elif st.session_state.pipeline_ran:
            st.warning("Quality report not available.")
        else:
            st.info("Upload a file to start.")

    with tabs[4]:
        if state and state.recommendations:
            render_review_tab(state)
        elif st.session_state.pipeline_ran:
            st.info("No recommendations generated.")
        else:
            st.info("Upload a file to start.")

    with tabs[5]:
        if state:
            render_export_tab(state)
        else:
            st.info("Upload a file to start.")


if __name__ == "__main__":
    main()
