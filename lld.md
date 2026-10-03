# Low-Level Design (LLD)
## Agentic Statement of Values (SOV) Intelligence & Cleansing System

**Document Version:** 1.0.0  
**Target Architecture:** LangGraph State Machine, Pydantic V2, Pandera, OpenPyXL, RapidFuzz, Sentence-Transformers, ChromaDB  

---

## 1. Class & Data Contract Specifications

The system is strictly typed using Pydantic V2 and Pandera. Data moves across agent nodes inside an immutable, deeply copyable state container (`SOVState`).

### 1.1 State Machine Container (`SOVState`)

```python
class WorkflowStage(str, Enum):
    INITIALIZED = "initialized"
    DISCOVERING = "discovering"
    MAPPING = "mapping"
    QUALITY_CHECKING = "quality_checking"
    REVIEWING = "reviewing"
    TRANSFORMING = "transforming"
    VALIDATING = "validating"
    COMPLETE = "complete"
    ERROR = "error"

class SOVState(BaseModel):
    session_id: str
    stage: WorkflowStage = WorkflowStage.INITIALIZED
    file_meta: Optional[FileMetadata] = None
    sheet_manifest: Optional[SheetManifest] = None
    primary_sheet_name: Optional[str] = None
    header_row: int = 0
    mappings: Optional[MappingResult] = None
    quality_report: Optional[QualityReport] = None
    recommendations: List[Recommendation] = Field(default_factory=list)
    audit_log: List[AuditEntry] = Field(default_factory=list)
    output_path: Optional[str] = None
    audit_log_path: Optional[str] = None
    validation_passed: bool = False
    validation_errors: List[str] = Field(default_factory=list)
    quality_score: float = 0.0
    error_message: Optional[str] = None
```

### 1.2 Sheet Intelligence Schemas

```python
class SheetClassification(str, Enum):
    PRIMARY = "primary"        # Active SOV table containing insured risks
    SECONDARY = "secondary"    # Additional location data, notes, or subsidiary schedule
    REJECT = "reject"          # Cover pages, pivot summaries, charts, empty tabs

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

class SheetDiscoveryResult(BaseModel):
    sheet_name: str
    classification: SheetClassification
    header_row: int
    confidence: float
    reasoning: List[str]
    profile: SheetProfile
    issues: List[str]
```

### 1.3 Mapping & Recommendation Schemas

```python
class MappingMethod(str, Enum):
    EXACT = "exact"
    FUZZY = "fuzzy"
    SEMANTIC = "semantic"
    MEMORY = "memory"
    LLM = "llm"
    UNRESOLVED = "unresolved"

class ColumnMapping(BaseModel):
    source_column: str
    target: Optional[str]
    confidence: float
    method: MappingMethod
    rationale: str
    evidence: List[str]
    review_required: bool
    value_profile_fit: float
    name_similarity: float
    method_agreement: float

class Recommendation(BaseModel):
    id: str                            # e.g., REC-A4F12B89
    action_type: ActionType            # COLUMN_MAPPING | STANDARDISATION | DATA_CORRECTION | FLAG_FOR_REVIEW
    source_column: str
    target_column: str
    operation: str                     # Whitelisted function name
    before_example: Optional[str]
    after_example: Optional[str]
    rationale: str
    confidence: float
    uncertainty: str = ""
    affected_rows: int = 0
    affected_row_indices: List[int] = Field(default_factory=list)
    status: RecommendationStatus = RecommendationStatus.PENDING # PENDING | APPROVED | REJECTED | OVERRIDDEN
    issue_id: Optional[str] = None
    review_required: bool = False
```

---

## 2. Module & Agent Detailed Specifications

### 2.1 Agent 1: Sheet Intelligence & Discovery (`app.agents.sheet_discovery`)

#### Responsibilities:
1. Load all workbook worksheets with `openpyxl`.
2. Detect and unmerge merged ranges (`openpyxl.worksheet.worksheet.Worksheet.merged_cells`), forward-filling categorical headers across merged spans.
3. Strip leading title banners, empty preamble rows, and company disclaimers.
4. Scan the first $M = 30$ rows to locate the optimal header row index.
5. Compute composite structural confidence and classify each sheet.

#### Algorithmic Formulation:
For candidate header row $i \in [0, \min(30, N_{\text{rows}})]$:

$$\text{TextRatio}(i) = \frac{\sum_{c \in \text{non-null}} \mathbb{I}[c \text{ is text and not numeric}]}{|\text{non-null}|}$$

$$\text{HeaderMatch}(i) = \frac{\sum_{c \in \text{non-null}} \mathbb{I}[\text{norm}(c) \in \text{SynonymSet}]}{\max(|\text{non-null}|, 1)}$$

$$\text{DataBelow}(i) = \frac{\sum_{v \in \text{row}_{i+1}} \mathbb{I}[v \text{ is numeric}]}{\max(|\text{row}_{i+1}|, 1)}$$

$$\text{Score}_{\text{header}}(i) = 0.40 \cdot \text{HeaderMatch}(i) + 0.20 \cdot \text{TextRatio}(i) + 0.20 \cdot \text{FillRatio}(i) + 0.20 \cdot \text{DataBelow}(i)$$

Sheet Composite Score:
$$\text{Score}_{\text{sheet}} = 0.35 \cdot S_{\text{header}} + 0.25 \cdot D_{\text{density}} + 0.20 \cdot C_{\text{type}} + 0.20 \cdot V_{\text{rows}}$$

Where:
- $S_{\text{header}} = \min\left(1.0, \frac{\text{synonym\_matches}}{17} \times 3.0\right)$
- $D_{\text{density}} = \text{non-null cell ratio}$
- $C_{\text{type}} = \text{fraction of columns exhibiting homogeneous types (} >80\% \text{ numeric or } >80\% \text{ string)}$
- $V_{\text{rows}} = \min(1.0, \frac{\text{rows below header}}{100})$

Classification Logic:
- If $\text{Score}_{\text{sheet}} \ge 0.45$ and $\text{matches} \ge 3 \implies \mathbf{PRIMARY}$
- Else if $\text{Score}_{\text{sheet}} \ge 0.25$ or $\text{matches} \ge 1 \implies \mathbf{SECONDARY}$
- Else $\implies \mathbf{REJECT}$

---

### 2.2 Agent 2: Schema Mapping Agent (`app.agents.schema_mapping`)

#### Multi-Tier Cascade Architecture:

```
Source Column String & Series
            │
            ▼
┌─────────────────────────┐  Hit
│ Stage 0: Vector Memory  ├──────► Conf = min(0.99, match_conf * 1.1)
└───────────┬─────────────┘
            │ Miss
            ▼
┌─────────────────────────┐  Hit
│ Stage 1: Exact Synonym  ├──────► Conf = 0.97
└───────────┬─────────────┘
            │ Miss
            ▼
┌─────────────────────────┐
│ Stage 2: RapidFuzz      │ Token Sort Ratio (cutoff = 78%)
└───────────┬─────────────┘
            │
┌───────────▼─────────────┐
│ Stage 3: BGE Embeddings │ Dense Cosine Sim (cutoff = 0.75)
└───────────┬─────────────┘
            │
            ├─► Both Agree ──► High Confidence Consensus
            ├─► Disagree   ──► Take higher score (agreement = 0.60)
            ▼
┌─────────────────────────┐  Ambiguous / Low Signal (< 0.50)
│ Stage 4: LLM Gateway    ├──────► Structured JSON decision (Mistral/Groq)
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│ Hungarian Assignment    │ 1:1 Target Constraint Resolution
└─────────────────────────┘
```

#### Confidence Calibration Formula:
For a candidate mapping to canonical field $T$:

$$\text{Confidence} = 0.45 \cdot S_{\text{name}} + 0.35 \cdot V_{\text{profile}} + 0.20 \cdot A_{\text{method}}$$

Where:
- $S_{\text{name}}$: Name similarity from exact (1.0), fuzzy ($0.92 \times \frac{\text{ratio}}{100}$), semantic ($0.90 \times \cos(\vec{q}, \vec{d})$), or LLM ($0.85 \times \text{conf}_{\text{llm}}$).
- $V_{\text{profile}}$: Value-Profile Fit score ($0.0 \dots 1.0$) generated by `score_value_profile_fit(profile, T)`.
- $A_{\text{method}}$: Inter-stage agreement ($1.0$ if memory/exact or fuzzy+semantic agree; $0.8$ if single heuristic matches; $0.6$ on heuristic clash).
- Memory Boost: If from approved memory, $\text{Confidence} \leftarrow \min(0.99, \text{Confidence} \times 1.10)$.

#### 1:1 Target Uniqueness (Hungarian Assignment):
If multiple source columns $C_1, C_2, \dots C_k$ target the same canonical field $T$:
1. Select $C^* = \arg\max_i \text{Confidence}(C_i \to T)$.
2. Assign $C^* \to T$.
3. Demote all other $C_{j \ne *} \to \text{UNRESOLVED}$ with $\text{Confidence} = 0.0$ and clear explanation in rationale.

---

### 2.3 Agent 3: Quality Reasoning & Auditing (`app.agents.quality_reasoning`)

#### Deterministic Rule Matrix:

| Check # | Target Field | Failure Condition | Suggested Whitelist Op | Severity |
|---------|--------------|-------------------|------------------------|----------|
| 1 | All 17 Fields | Missingness $> 50\%$ / $> 20\%$ / $> 5\%$ | `flag_for_review` | High / Med / Low |
| 2 | Monetary Fields | Presence of `$`, `,`, `(`, `)` | `strip_currency` | Medium |
| 3 | Monetary Fields | Value $< 0.0$ | `flag_for_review` | High |
| 4 | `Year Built` | Year $< 1700$ or $> \text{Year}_{\text{current}}$ | `to_year_int` | High |
| 5 | `Storeys` | Floor count $< 1$ | `flag_for_review` | Medium |
| 6 | `Number of Buildings` | Count $< 1$ | `flag_for_review` | Medium |
| 7 | `Fire Sprinklers (Y/N)` | Code not in `{"Y", "N", "Y13", "Y(13R)"}` | `normalize_sprinkler_code` | Medium |
| 8 | `State` | String not in `US_STATE_ABBREVS` | `state_to_abbrev` | Medium |
| 9 | `Reference` | Duplicated identifier rows | `flag_for_review` | High |
| 10 | `Zip` | Non-5-digit postal values | `to_zip` | Low |

#### Composite Quality Score Formula:
$$\text{QualityScore} = 100 \times \left( 0.35 \cdot Q_{\text{mapping}} + 0.30 \cdot Q_{\text{completeness}} + 0.35 \cdot Q_{\text{anomalies}} \right)$$

Where:
- $Q_{\text{mapping}} = \frac{\sum_{m \in \text{mapped}} \text{Confidence}(m)}{17}$
- $Q_{\text{completeness}} = \frac{\sum_{f \in \text{targets}} \text{Non-Null-Pct}(f)}{17 \times 100}$
- $Q_{\text{anomalies}} = \max\left(0.0, 1.0 - \sum_{i \in \text{issues}} w_{\text{severity}}(i)\right)$
  - Weights: $w_{\text{High}} = 0.15, w_{\text{Med}} = 0.05, w_{\text{Low}} = 0.02, w_{\text{Info}} = 0.00$.

---

### 2.4 Agent 4: Controlled Transformation (`app.agents.transformation`)

#### Execution Invariant:
Only operations present in `WHITELISTED_OPERATIONS` can be invoked. Any dynamic code execution, arbitrary `eval()`, or unapproved prompt commands are blocked at runtime.

#### The Whitelisted Registry:
```python
TRANSFORMATION_REGISTRY: Dict[str, Callable] = {
    "strip_currency": strip_currency,
    "to_float": to_float,
    "to_int": to_int,
    "to_str": to_str,
    "to_year_int": to_year_int,
    "to_zip": to_zip,
    "state_to_abbrev": state_to_abbrev,
    "normalize_sprinkler_code": normalize_sprinkler_code,
    "trim_whitespace": trim_whitespace,
    "normalize_spaces": normalize_spaces,
    "normalize_date": normalize_date,
    "flag_for_review": flag_for_review,
}
```

#### Collision Resolution & Atomic Mutation:
1. **Column Renaming Phase:** If target column $T$ already exists in source DataFrame as an unmapped column, it is proactively renamed to `_orig_{T}` to prevent Pandas DataFrame column collision.
2. **Series Multi-Index Disambiguation:** When slicing `df[col]`, if a duplicated column name yields a sub-DataFrame instead of a Series, the pipeline calculates non-null counts across duplicate columns, keeps the most complete column, and drops redundant slices.
3. **Audit Log Generation:** For every applied transformation, row-level change detection calculates the exact number of modified cells and logs before/after samples to `AuditEntry`.

---

### 2.5 Agent 5: Validation & Export Engine (`app.processing.validation`)

#### Pandera Strict Contract Enforcement:
```python
TARGET_COLUMN_ORDER = [
    "Reference", "Address", "City", "State", "Zip", "County", "Country",
    "Building Value", "Contents", "BI", "Occupancy", "Construction",
    "Storeys", "Number of Buildings", "Year Built", "Fire Sprinklers (Y/N)", "Other"
]

schema = pa.DataFrameSchema(
    columns={col: pa.Column(nullable=True, required=True) for col in TARGET_COLUMN_ORDER},
    strict=True,
    ordered=True,
)
```

1. **Ordering & Padding:** Any missing canonical columns are instantiated as `None`. Any unrecognized extra columns are dropped.
2. **Serialization:** Writes finalized clean table to `Cleaned_SOV_{session}_{timestamp}.xlsx` using OpenPyXL with standard styles.
3. **Audit Register:** Writes formatted `Audit_Log_{session}_{timestamp}.xlsx` with full traceability metadata.

---

## 3. Storage & Service Layer

### 3.1 Episodic Vector Memory (`app.services.memory.chroma_store`)
- **Backend:** Embedded ChromaDB in `data/chroma_db/`.
- **Collection:** `sov_approved_mappings`.
- **Key Fields:** Document text (`source_column`), Metadata (`{"target_field": str, "confidence": float, "approved_at": str}`).
- **Similarity Threshold:** $\text{CosineDistance} < 0.20 \implies \text{Similarity} \ge 0.80$.

### 3.2 Dense Embedding Encoder (`app.services.embeddings.encoder`)
- **Model:** `sentence-transformers/all-MiniLM-L6-v2` or `BAAI/bge-small-en-v1.5`.
- **Vector Dimension:** 384 dimensions.
- **Optimization:** In-memory LRU cache (`@lru_cache(maxsize=1024)`) on embedding generation. Precomputes and caches corpus embeddings at startup.

### 3.3 LLM Gateway (`app.services.llm.gateway`)
- **Abstraction:** Unified `LLMGateway` supporting `complete()` and `complete_structured()`.
- **Multi-Provider Fallback Hierarchy:**
  1. Primary Provider: Configured in `.env` (`ollama` / `groq` / `gemini`).
  2. Fallback Provider: If primary provider experiences HTTP 429 (Rate Limit), Connection Refused, or Read Timeout, automatically switch to secondary provider.
  3. Safe Heuristic Mode: If all LLM providers fail, the pipeline falls back gracefully to deterministic fuzzy & value-profile scoring without raising an unhandled exception.

---

## 4. Test Strategy & Verification

The system is guarded by 75 regression tests in `tests/test_sov_system.py`:
- **Unit Tests:** Unmerging, forward fill, currency stripping, sprinkler normalization, state mapping, Pandera schema enforcement.
- **Integration Tests:** 4 end-to-end production broker SOVs (`SOV_B4ID.xlsx`, `SOV_H6D2.xlsx`, `SOV_K4T9.xlsx`, `SOV_Q8B3.xlsx`).
- **Regression Invariant:** Every test run must produce 100% Pandera validation compliance and 0 failed assertions.

---
