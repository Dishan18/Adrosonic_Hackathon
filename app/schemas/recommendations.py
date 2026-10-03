"""
Recommendation schema models used by Agent 3 and the HITL review.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.state_models import ActionType, RecommendationStatus


class LLMSingleRecommendation(BaseModel):
    """A single recommendation produced by the LLM."""

    issue_id: str
    action_type: ActionType
    source_column: str
    target_column: str
    operation: str  # Must be in whitelist
    before_example: str
    after_example: str
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty: str = ""
    affected_rows: int = 0


class LLMRecommendationOutput(BaseModel):
    """Structured output expected from LLM reasoning calls."""

    recommendations: List[LLMSingleRecommendation] = Field(default_factory=list)
    overall_assessment: str = ""
    business_impact: str = ""
    uncertainty_notes: str = ""


class MappingDecision(BaseModel):
    """LLM structured output for a single column mapping decision."""

    source_column: str
    target_field: Optional[str] = None  # Must be one of TARGET_FIELDS or null
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""
    evidence: List[str] = Field(default_factory=list)
    requires_review: bool = False


class LLMMappingResponse(BaseModel):
    """LLM structured output for batch mapping."""

    mappings: List[MappingDecision] = Field(default_factory=list)
