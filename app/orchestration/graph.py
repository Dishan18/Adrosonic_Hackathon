"""
LangGraph StateGraph orchestration for the Agentic SOV Intelligence System.

Graph:
  discover_sheets → map_schema → assess_quality → human_review → transform_export

Human rejection routes back to assess_quality for re-reasoning.
SQLite checkpointing enables pause/resume.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from app.schemas.state_models import (
    Recommendation,
    RecommendationStatus,
    SOVState,
    WorkflowStage,
)
from app.agents.sheet_discovery import run_sheet_discovery
from app.agents.schema_mapping import run_schema_mapping
from app.agents.quality_reasoning import run_quality_reasoning
from app.agents.transformation import run_transformation
from app.config import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node wrappers (convert SOVState ↔ dict for LangGraph compatibility)
# ---------------------------------------------------------------------------

def _state_to_dict(state: SOVState) -> Dict:
    return state.model_dump()


def _dict_to_state(d: Dict) -> SOVState:
    return SOVState.model_validate(d)


def node_discover(state: Dict) -> Dict:
    s = _dict_to_state(state)
    result = run_sheet_discovery(s)
    return _state_to_dict(result)


def node_map_schema(state: Dict) -> Dict:
    s = _dict_to_state(state)
    result = run_schema_mapping(s)
    return _state_to_dict(result)


def node_assess_quality(state: Dict) -> Dict:
    s = _dict_to_state(state)
    result = run_quality_reasoning(s)
    return _state_to_dict(result)


def node_human_review(state: Dict) -> Dict:
    """
    HITL node: this is an interrupt point.
    LangGraph will pause here and wait for human input.
    The UI resumes the graph by supplying decisions.
    """
    # In headless mode (tests), auto-approve all high-confidence recs
    s = _dict_to_state(state)
    s.stage = WorkflowStage.HUMAN_REVIEW
    return _state_to_dict(s)


def node_transform(state: Dict) -> Dict:
    s = _dict_to_state(state)
    result = run_transformation(s)
    return _state_to_dict(result)


def node_re_reason(state: Dict) -> Dict:
    """Re-reason node: called when reviewer rejects a recommendation."""
    s = _dict_to_state(state)
    s.stage = WorkflowStage.ASSESSING
    result = run_quality_reasoning(s)
    return _state_to_dict(result)


# ---------------------------------------------------------------------------
# Edge routing
# ---------------------------------------------------------------------------

def route_after_discovery(state: Dict) -> Literal["map_schema", "error"]:
    s = _dict_to_state(state)
    if s.stage == WorkflowStage.ERROR:
        return "error"
    return "map_schema"


def route_after_mapping(state: Dict) -> Literal["assess_quality", "error"]:
    s = _dict_to_state(state)
    if s.stage == WorkflowStage.ERROR:
        return "error"
    return "assess_quality"


def route_after_assessment(state: Dict) -> Literal["human_review", "error"]:
    s = _dict_to_state(state)
    if s.stage == WorkflowStage.ERROR:
        return "error"
    return "human_review"


def route_after_human_review(
    state: Dict,
) -> Literal["transform_export", "re_reason", "error"]:
    """
    Route after human review:
    - If there are rejected recs with feedback → re_reason
    - If all low-confidence recs decided → transform_export
    - Otherwise stay at human_review (interrupt)
    """
    s = _dict_to_state(state)
    if s.stage == WorkflowStage.ERROR:
        return "error"

    # Check for rejected recs needing re-reasoning
    rejected_with_feedback = [
        r for r in s.recommendations
        if r.status == RecommendationStatus.REJECTED
        and r.rejection_note
        and r.re_reason_count < config.MAX_REREASON_ATTEMPTS
    ]

    if rejected_with_feedback:
        # Feed back the first rejection note
        return "re_reason"

    # Check if all blocking recs are decided
    pending_required = [
        r for r in s.recommendations
        if r.status == RecommendationStatus.PENDING
        and r.review_required
    ]

    if pending_required:
        return "human_review"  # Stay (interrupt again)

    return "transform_export"


def route_after_rereason(state: Dict) -> Literal["human_review", "error"]:
    s = _dict_to_state(state)
    if s.stage == WorkflowStage.ERROR:
        return "error"
    return "human_review"


def route_error(state: Dict) -> str:
    return "__end__"


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------

def build_graph(use_checkpointing: bool = True):
    """
    Build and compile the LangGraph StateGraph.
    Returns a compiled graph.
    """
    try:
        from langgraph.graph import StateGraph, END
        from langgraph.checkpoint.sqlite import SqliteSaver
        import sqlite3
    except ImportError as e:
        raise ImportError(f"LangGraph not installed: {e}") from e

    # Use TypedDict-compatible state (dict-based for LangGraph)
    graph = StateGraph(dict)

    # Add nodes
    graph.add_node("discover_sheets", node_discover)
    graph.add_node("map_schema", node_map_schema)
    graph.add_node("assess_quality", node_assess_quality)
    graph.add_node("human_review", node_human_review)
    graph.add_node("re_reason", node_re_reason)
    graph.add_node("transform_export", node_transform)
    graph.add_node("error", lambda s: s)

    # Entry point
    graph.set_entry_point("discover_sheets")

    # Edges
    graph.add_conditional_edges("discover_sheets", route_after_discovery)
    graph.add_conditional_edges("map_schema", route_after_mapping)
    graph.add_conditional_edges("assess_quality", route_after_assessment)
    graph.add_conditional_edges("human_review", route_after_human_review)
    graph.add_conditional_edges("re_reason", route_after_rereason)
    graph.add_edge("transform_export", END)
    graph.add_edge("error", END)

    # Interrupt at human_review for HITL
    graph.set_finish_point("transform_export")

    # Checkpointing
    if use_checkpointing:
        try:
            conn = sqlite3.connect(config.CHECKPOINT_DB, check_same_thread=False)
            checkpointer = SqliteSaver(conn)
            compiled = graph.compile(
                checkpointer=checkpointer,
                interrupt_before=["human_review"],
            )
            logger.info("Graph compiled with SQLite checkpointing.")
        except Exception as e:
            logger.warning("Checkpointing failed (%s) — compiling without.", e)
            compiled = graph.compile(interrupt_before=["human_review"])
    else:
        compiled = graph.compile(interrupt_before=["human_review"])

    return compiled


# ---------------------------------------------------------------------------
# Simple synchronous runner (for tests / CLI)
# ---------------------------------------------------------------------------

def run_pipeline_to_review(
    initial_state: SOVState,
    thread_id: str = "default",
) -> SOVState:
    """
    Run the pipeline from start through assess_quality, stopping at human_review.
    """
    graph = build_graph(use_checkpointing=True)
    config_dict = {"configurable": {"thread_id": thread_id}}

    result = graph.invoke(_state_to_dict(initial_state), config=config_dict)
    return _dict_to_state(result)


def resume_pipeline_after_review(
    state_with_decisions: SOVState,
    thread_id: str = "default",
) -> SOVState:
    """
    Resume the pipeline after human review decisions have been applied to state.
    """
    graph = build_graph(use_checkpointing=True)
    config_dict = {"configurable": {"thread_id": thread_id}}

    result = graph.invoke(_state_to_dict(state_with_decisions), config=config_dict)
    return _dict_to_state(result)
