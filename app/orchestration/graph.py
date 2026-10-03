"""
LangGraph StateGraph orchestration for the Agentic SOV Intelligence System.

Graph:
  discover_sheets → map_schema → assess_quality → human_review → transform_export

Human rejection routes back to assess_quality for re-reasoning.
SQLite checkpointing enables pause/resume.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional

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
    # mode="json" stores enums as plain strings, so checkpoints never contain
    # application classes (LangGraph's msgpack serializer refuses those).
    return state.model_dump(mode="json")


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
    LangGraph pauses before this node and waits for human input.
    The caller resumes the graph after writing decisions into the state
    (see resume_pipeline_after_review).
    """
    s = _dict_to_state(state)
    s.stage = WorkflowStage.HUMAN_REVIEW
    return _state_to_dict(s)


def node_transform(state: Dict) -> Dict:
    s = _dict_to_state(state)
    result = run_transformation(s)
    return _state_to_dict(result)


def _rejections_awaiting_rereason(s: SOVState) -> List[Recommendation]:
    return [
        r for r in s.recommendations
        if r.status == RecommendationStatus.REJECTED
        and r.rejection_note
        and not r.feedback_processed
        and r.re_reason_count < config.MAX_REREASON_ATTEMPTS
    ]


def node_re_reason(state: Dict) -> Dict:
    """Re-reason node: called when reviewer rejects a recommendation with a note."""
    s = _dict_to_state(state)
    pending = _rejections_awaiting_rereason(s)
    s.re_reason_feedback = "\n".join(
        f"Recommendation {r.id} ({r.operation} on '{r.target_column}') rejected: {r.rejection_note}"
        for r in pending
    ) or None
    s.stage = WorkflowStage.ASSESSING
    result = run_quality_reasoning(s)

    # Mark the feedback as consumed so routing does not loop back here.
    handled = {r.id for r in pending}
    result.recommendations = [
        r.model_copy(update={"feedback_processed": True}) if r.id in handled else r
        for r in result.recommendations
    ]
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
) -> Literal["transform_export", "re_reason", "human_review", "error"]:
    """
    Route after human review:
    - If there are rejected recs with unprocessed feedback → re_reason
    - If all review-required recs are decided → transform_export
    - Otherwise stay at human_review (interrupt again)
    """
    s = _dict_to_state(state)
    if s.stage == WorkflowStage.ERROR:
        return "error"

    if _rejections_awaiting_rereason(s):
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

# Compiled graphs are cached: an in-memory checkpointer only survives between
# run and resume if the same compiled graph is reused.
_COMPILED: Dict[bool, Any] = {}


def _make_checkpointer():
    """SQLite checkpointer when available; in-memory otherwise (interrupts need one)."""
    try:
        import sqlite3
        from langgraph.checkpoint.sqlite import SqliteSaver

        conn = sqlite3.connect(config.CHECKPOINT_DB, check_same_thread=False)
        logger.info("Graph checkpointing: SQLite (%s).", config.CHECKPOINT_DB)
        return SqliteSaver(conn)
    except Exception as e:
        from langgraph.checkpoint.memory import InMemorySaver

        logger.warning("SQLite checkpointing unavailable (%s) — using in-memory checkpoints.", e)
        return InMemorySaver()


def build_graph(use_checkpointing: bool = True):
    """
    Build and compile the LangGraph StateGraph.
    Returns a compiled graph (cached per checkpointing mode).
    """
    if use_checkpointing in _COMPILED:
        return _COMPILED[use_checkpointing]

    try:
        from langgraph.graph import StateGraph, END
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

    # Edges (explicit path maps: every value a router can return must be listed)
    graph.add_conditional_edges(
        "discover_sheets", route_after_discovery,
        {"map_schema": "map_schema", "error": "error"},
    )
    graph.add_conditional_edges(
        "map_schema", route_after_mapping,
        {"assess_quality": "assess_quality", "error": "error"},
    )
    graph.add_conditional_edges(
        "assess_quality", route_after_assessment,
        {"human_review": "human_review", "error": "error"},
    )
    graph.add_conditional_edges(
        "human_review", route_after_human_review,
        {
            "transform_export": "transform_export",
            "re_reason": "re_reason",
            "human_review": "human_review",
            "error": "error",
        },
    )
    graph.add_conditional_edges(
        "re_reason", route_after_rereason,
        {"human_review": "human_review", "error": "error"},
    )
    graph.add_edge("transform_export", END)
    graph.add_edge("error", END)

    # Interrupt at human_review for HITL. An interrupt requires a checkpointer,
    # so one is always attached; use_checkpointing selects SQLite persistence.
    if use_checkpointing:
        checkpointer = _make_checkpointer()
    else:
        from langgraph.checkpoint.memory import InMemorySaver
        checkpointer = InMemorySaver()

    compiled = graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"],
    )
    _COMPILED[use_checkpointing] = compiled
    return compiled


# ---------------------------------------------------------------------------
# Simple synchronous runner (for UI / tests / CLI)
# ---------------------------------------------------------------------------

def run_pipeline_to_review(
    initial_state: SOVState,
    thread_id: str = "default",
) -> SOVState:
    """
    Run the pipeline from start through assess_quality, stopping before
    human_review. Use a fresh thread_id per pipeline run.
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
    Resume the paused pipeline after human review decisions have been applied
    to state. Writes the reviewed state into the thread's checkpoint, then
    continues from the interrupt (passing new input instead would restart the
    graph from discovery). Returns the state at the next stop: the completed
    export, or human_review again if required decisions are still pending.
    """
    graph = build_graph(use_checkpointing=True)
    config_dict = {"configurable": {"thread_id": thread_id}}

    if not graph.get_state(config_dict).next:
        raise RuntimeError(
            f"No paused pipeline found for thread '{thread_id}'. "
            "Run run_pipeline_to_review first."
        )

    graph.update_state(config_dict, _state_to_dict(state_with_decisions))
    result = graph.invoke(None, config=config_dict)
    return _dict_to_state(result)
