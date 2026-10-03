"""
Pydantic state models for the Agentic SOV Intelligence System.
These are the shared typed state objects passed between LangGraph nodes.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class WorkflowStage(str, Enum):
    INIT = "init"
    DISCOVERING = "discovering"
    DISCOVERED = "discovered"
    MAPPING = "mapping"
    MAPPED = "mapped"
    ASSESSING = "assessing"
    ASSESSED = "assessed"
    HUMAN_REVIEW = "human_review"
    TRANSFORMING = "transforming"
    VALIDATING = "validating"
    COMPLETE = "complete"
    ERROR = "error"


class SheetClassification(str, Enum):
    PRIMARY = "Primary"
    SECONDARY = "Secondary"
    REJECT = "Reject"


class MappingMethod(str, Enum):
    MEMORY = "memory"
    EXACT = "exact"
    FUZZY = "fuzzy"
    SEMANTIC = "semantic"
    LLM = "llm"
    UNRESOLVED = "unresolved"


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ActionType(str, Enum):
    COLUMN_MAPPING = "column_mapping"
    DATA_CORRECTION = "data_correction"
    STANDARDISATION = "standardisation"
    FLAG_FOR_REVIEW = "flag_for_review"


class RecommendationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    SKIPPED = "skipped"


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"


# ---------------------------------------------------------------------------
# File metadata
# ---------------------------------------------------------------------------

class FileMeta(BaseModel):
    original_filename: str
    file_type: str  # "xlsx" or "csv"
    temp_path: str
    upload_timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    file_size_bytes: int = 0
    session_id: str = ""


# ---------------------------------------------------------------------------
# Sheet discovery / Agent 1
# ---------------------------------------------------------------------------

class MergedCellInfo(BaseModel):
    sheet_name: str
    ranges: List[str] = Field(default_factory=list)


class SheetProfile(BaseModel):
    sheet_name: str
    row_count: int
    col_count: int
    non_null_ratio: float
    text_density: float
    numeric_density: float
    header_likeness: float
    candidate_field_matches: int
    data_continuity: float
    merged_cell_count: int
    typed_data_consistency: float
    blank_row_count: int
    total_row_count: int
    metadata_row_count: int
    score: float = 0.0


class SheetDiscoveryResult(BaseModel):
    sheet_name: str
    classification: SheetClassification
    header_row: int  # 0-indexed
    confidence: float
    reasoning: List[str]
    profile: SheetProfile
    issues: List[str] = Field(default_factory=list)


class SheetManifest(BaseModel):
    sheets: List[SheetDiscoveryResult]
    primary_sheet: Optional[str] = None
    header_row: int = 0  # 0-indexed row in primary sheet

    @property
    def primary(self) -> Optional[SheetDiscoveryResult]:
        for s in self.sheets:
            if s.sheet_name == self.primary_sheet:
                return s
        return None


# ---------------------------------------------------------------------------
# Schema mapping / Agent 2
# ---------------------------------------------------------------------------

class ColumnMapping(BaseModel):
    source_column: str
    target: Optional[str]  # None if unmapped
    confidence: float
    method: MappingMethod
    rationale: str
    evidence: List[str] = Field(default_factory=list)
    review_required: bool = False
    value_profile_fit: float = 0.0
    name_similarity: float = 0.0
    method_agreement: float = 0.0


class MappingResult(BaseModel):
    mappings: List[ColumnMapping]
    unmapped_source_columns: List[str] = Field(default_factory=list)
    unmapped_target_fields: List[str] = Field(default_factory=list)
    overall_mapping_confidence: float = 0.0


# ---------------------------------------------------------------------------
# Data quality / Agent 3
# ---------------------------------------------------------------------------

class QualityIssue(BaseModel):
    issue_id: str
    issue_type: str
    severity: Severity
    affected_field: str
    affected_rows: List[int] = Field(default_factory=list)
    affected_row_count: int = 0
    evidence: str
    before_example: str
    suggested_operation: str
    confidence: float = 1.0


class QualityReport(BaseModel):
    issues: List[QualityIssue] = Field(default_factory=list)
    completeness_by_field: Dict[str, float] = Field(default_factory=dict)
    overall_quality_score: float = 0.0
    total_rows: int = 0
    issue_summary: str = ""


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

class Recommendation(BaseModel):
    id: str
    action_type: ActionType
    source_column: str
    target_column: str
    operation: str  # Must be in whitelist
    before_example: str
    after_example: str
    rationale: str
    confidence: float
    uncertainty: str = ""
    affected_rows: int = 0
    affected_row_indices: List[int] = Field(default_factory=list)
    status: RecommendationStatus = RecommendationStatus.PENDING
    rejection_note: str = ""
    re_reason_count: int = 0
    feedback_processed: bool = False  # True once Agent 3 has re-reasoned on rejection_note
    issue_id: Optional[str] = None
    review_required: bool = False  # True when confidence < HIGH_CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# Human decisions
# ---------------------------------------------------------------------------

class HumanDecision(BaseModel):
    recommendation_id: str
    decision: ReviewDecision
    note: str = ""
    edited_operation: Optional[str] = None
    reviewer_id: str = "human"
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# ---------------------------------------------------------------------------
# Audit log entry
# ---------------------------------------------------------------------------

class AuditEntry(BaseModel):
    entry_id: str
    source_column: str
    target_column: str
    transformation_applied: str
    before_value: Any
    after_value: Any
    confidence: float
    approved_by: str
    timestamp: str
    recommendation_id: Optional[str] = None
    row_index: Optional[int] = None


# ---------------------------------------------------------------------------
# Master SOV State (passed through LangGraph)
# ---------------------------------------------------------------------------

class SOVState(BaseModel):
    """
    Shared typed state object for the entire LangGraph pipeline.
    Each agent reads from earlier fields and writes to its own fields only.
    """

    # --- Input ---
    file_meta: Optional[FileMeta] = None

    # --- Agent 1 outputs ---
    sheet_manifest: Optional[SheetManifest] = None
    header_row: int = 0  # confirmed header row (0-indexed)
    primary_sheet_name: Optional[str] = None
    data_sheets: List[str] = Field(default_factory=list)  # all sheets merged into the output

    # --- Agent 2 outputs ---
    mappings: Optional[MappingResult] = None

    # --- Agent 3 outputs ---
    quality_report: Optional[QualityReport] = None
    recommendations: List[Recommendation] = Field(default_factory=list)

    # --- Human decisions ---
    decisions: List[HumanDecision] = Field(default_factory=list)

    # --- Agent 4 outputs ---
    output_path: Optional[str] = None
    audit_log_path: Optional[str] = None
    validation_passed: bool = False
    validation_errors: List[str] = Field(default_factory=list)

    # --- Orchestration ---
    stage: WorkflowStage = WorkflowStage.INIT
    error_message: Optional[str] = None
    audit_log: List[AuditEntry] = Field(default_factory=list)
    session_id: str = ""

    # --- Re-reasoning ---
    re_reason_feedback: Optional[str] = None

    model_config = {"use_enum_values": True}
