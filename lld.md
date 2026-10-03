# Low-Level Design (LLD)
## Agentic Statement of Values (SOV) Intelligence & Cleansing System

**Document Version:** 1.3.0 (updated 2026-10-04; adds 1-click reject drop, Change Target ChromaDB feedback, and Mapping Accuracy KPI)  
**Target Architecture:** LangGraph State Machine, Pydantic V2, Pandera, OpenPyXL, RapidFuzz, Sentence-Transformers, ChromaDB  

---

## 1. Class & Data Contract Specifications

The system is typed with Pydantic V2. Each agent node takes a deep copy of the shared `SOVState`, writes only its own fields and returns the new state. Inside the LangGraph graph the state travels as a JSON-mode dict (`model_dump(mode="json")`), so checkpoints contain only plain values.

### 1.1 State Machine Container (`SOVState`, `app/schemas/state_models.py`)

```python
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
    VALIDATING = "validating"      # export written, validation failed
    COMPLETE = "complete"          # export written, validation passed
    ERROR = "error"

class SOVState(BaseModel):
    file_meta: Optional[FileMeta] = None
    # Agent 1
    sheet_manifest: Optional[SheetManifest] = None
    header_row: int = 0                       # header row of the primary sheet (0-indexed)
    primary_sheet_name: Optional[str] = None
    data_sheets: List[str] = []               # every PRIMARY sheet, merged into the output
    # Agent 2
    mappings: Optional[MappingResult] = None
    # Agent 3
    quality_report: Optional[QualityReport] = None
    recommendations: List[Recommendation] = []
    # Human decisions
    decisions: List[HumanDecision] = []
    # Human decisions on unclaimed (unmapped) source columns:
    # keys = source column name, values = TARGET_FIELDS name OR "__rejected__"
    unclaimed_decisions: Dict[str, str] = {}
    # Agent 4
    output_path: Optional[str] = None
    audit_log_path: Optional[str] = None
    validation_passed: bool = False
    validation_errors: List[str] = []
    # Orchestration
    stage: WorkflowStage = WorkflowStage.INIT
    error_message: Optional[str] = None
    audit_log: List[AuditEntry] = []
    session_id: str = ""
    re_reason_feedback: Optional[str] = None  # reviewer notes passed to Agent 3

    model_config = {"use_enum_values": True}
```

### 1.2 Sheet Intelligence Schemas

```python
class SheetClassification(str, Enum):
    PRIMARY = "Primary"        # SOV location data (all PRIMARY sheets are merged)
    SECONDARY = "Secondary"    # Some SOV signal, not used as data
    REJECT = "Reject"          # Cover pages, disclaimers, empty tabs

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
    header_row: int
    confidence: float
    reasoning: List[str]
    profile: SheetProfile
    issues: List[str] = []
```

### 1.3 Mapping & Recommendation Schemas

```python
class MappingMethod(str, Enum):
    MEMORY = "memory"
    EXACT = "exact"
    FUZZY = "fuzzy"
    SEMANTIC = "semantic"
    LLM = "llm"
    UNRESOLVED = "unresolved"

class ColumnMapping(BaseModel):
    source_column: str
    target: Optional[str]              # None if unmapped
    confidence: float
    method: MappingMethod
    rationale: str
    evidence: List[str] = []           # includes the reasons for any vetoed candidates
    review_required: bool = False      # confidence < HIGH_CONFIDENCE_THRESHOLD
    value_profile_fit: float = 0.0
    name_similarity: float = 0.0
    method_agreement: float = 0.0

class RecommendationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"            # rejected mapping with no alternative: a human decides
    SKIPPED = "skipped"                # defined, not currently assigned

class Recommendation(BaseModel):
    id: str                            # MAP-XXXXXXXX (mapping) / REC-XXXXXXXX (data quality)
    action_type: ActionType            # COLUMN_MAPPING | STANDARDISATION | DATA_CORRECTION | FLAG_FOR_REVIEW
    source_column: str
    target_column: str
    operation: str                     # Whitelisted function name
    before_example: str
    after_example: str
    rationale: str
    confidence: float
    uncertainty: str = ""
    affected_rows: int = 0
    affected_row_indices: List[int] = []
    status: RecommendationStatus = RecommendationStatus.PENDING
    rejection_note: str = ""
    re_reason_count: int = 0           # incremented on each rejection
    feedback_processed: bool = False   # True once Agent 3 re-reasoned on rejection_note
    issue_id: Optional[str] = None
    review_required: bool = False
```

---

## 2. Module & Agent Detailed Specifications

### 2.0 Workbook Ingestion (`app.processing.workbook`)

1. **Parse once:** `_parse_workbook(path, mtime)` loads the workbook with `openpyxl.load_workbook(data_only=True)` and converts every sheet to a DataFrame. It is `lru_cache`d per (resolved path, modification time), so the agents share one parse.
2. **Unmerge (fill down):** for each merged range the top-left value is written into the first column of every row of the range. Horizontal spans (banners such as "2023 - 2024 Values", footnotes merged across `B:AB`) are therefore *not* copied into other columns.
3. **Extract (`extract_data_frame`):** the header row becomes the column names (line breaks collapsed to spaces, blank names → `_col_{i}`, duplicates suffixed ` (1)`, ` (2)` …). Then these rows are dropped: completely blank rows; rows containing a cell equal to `total`, `grand total`, `subtotal`, `sum` or `footer`; note rows (exactly one non-empty cell, and it is non-numeric text); whitespace-only rows.
4. **Multi-sheet load (`load_source_data(state)`):** every sheet in `state.data_sheets` is extracted with its own header row and the frames are concatenated (columns aligned by name). `DataFrame.attrs["column_sheets"]` records which sheet(s) each column came from.
5. **`rename_and_coalesce(df, pairs)`:** renames source columns to targets; when several sources map to one target (one per sheet) they are combined into one column, earlier (higher-confidence) pairs winning where both have a value.

### 2.1 Agent 1: Sheet Intelligence & Discovery (`app.agents.sheet_discovery`)

#### Responsibilities:
1. Load all worksheets (`load_workbook_sheets`) and the unmerged view of each.
2. Scan the first $M = 30$ rows to locate the header row (`_find_best_header`).
3. Compute a composite structural score and classify each sheet.
4. Pick the best PRIMARY sheet as `primary_sheet_name`; set `data_sheets` = that sheet followed by every other PRIMARY sheet.

#### Algorithmic Formulation:
For candidate header row $i \in [0, \min(30, N_{\text{rows}}))$:

$$\text{TextRatio}(i) = \frac{\sum_{c \in \text{non-null}} \mathbb{I}[c \text{ is text and not numeric}]}{|\text{non-null}|}$$

$$\text{HeaderMatch}(i) = \frac{\sum_{c \in \text{non-null}} \mathbb{I}[\text{norm}(c) \in \text{SynonymSet}]}{\max(|\text{non-null}|, 1)}$$

$$\text{FillRatio}(i) = \frac{|\text{non-null}|}{\max(|\text{row}|, 1)}$$

$$\text{DataBelow}(i) = \frac{\sum_{v \in \text{row}_{i+1}} \mathbb{I}[v \text{ is numeric}]}{\max(|\text{row}_{i+1}|, 1)}$$

$$\text{Score}_{\text{header}}(i) = 0.40 \cdot \text{HeaderMatch}(i) + 0.20 \cdot \text{TextRatio}(i) + 0.20 \cdot \text{FillRatio}(i) + 0.20 \cdot \text{DataBelow}(i)$$

Sheet Composite Score:
$$\text{Score}_{\text{sheet}} = 0.35 \cdot S_{\text{header}} + 0.25 \cdot D_{\text{density}} + 0.20 \cdot C_{\text{type}} + 0.20 \cdot V_{\text{rows}}$$

Where:
- $S_{\text{header}} = \min\left(1.0, \frac{\text{synonym\_matches}}{17} \times 3.0\right)$
- $D_{\text{density}} = \text{non-null cell ratio}$
- $C_{\text{type}} = \text{fraction of columns (first 200 data rows) that are} >80\% \text{ numeric or} <20\% \text{ numeric}$
- $V_{\text{rows}} = \min(1.0, \frac{\text{rows below header}}{100})$

Classification Logic:
- If $\text{Score}_{\text{sheet}} \ge 0.45$ and $\text{matches} \ge 3 \implies \mathbf{PRIMARY}$
- Else if $\text{Score}_{\text{sheet}} \ge 0.25$ or $\text{matches} \ge 1 \implies \mathbf{SECONDARY}$
- Else $\implies \mathbf{REJECT}$

Hidden sheets are scored like any other sheet.

---

### 2.2 Agent 2: Schema Mapping Agent (`app.agents.schema_mapping`)

#### Per-column cascade (`map_column`):

```
Source Column Name & Values  ──►  value profile (profile_column)
            │
            ▼
┌─────────────────────────┐  hit, values agree
│ Stage 0: Vector Memory  ├──────► name_sim = min(stored_conf, 0.99), agreement 1.0, ×1.10 boost
└───────────┬─────────────┘
            │ miss / vetoed
            ▼
┌─────────────────────────┐  hit, values agree
│ Stage 1: Exact Synonym  ├──────► name_sim = 0.97, agreement 1.0
└───────────┬─────────────┘
            │ miss / vetoed
            ▼
┌─────────────────────────┐
│ Stage 2: RapidFuzz      │ token_sort_ratio ≥ FUZZY_THRESHOLD×100 (75); top 5 distinct targets
├─────────────────────────┤
│ Stage 3: BGE Embeddings │ cosine ≥ SEMANTIC_THRESHOLD (0.70); top 5 distinct targets
└───────────┬─────────────┘
            │ every candidate target: veto check, then confidence; best ≥ 0.50 wins
            ▼
┌─────────────────────────┐  still unresolved (pass 2 only)
│ Stage 4: LLM Gateway    ├──────► structured JSON decision among fields with value fit > 0.35
└─────────────────────────┘
```

Stage 0 uses `get_exact_memory_mapping`: Chroma query, similarity $= 1 - d/2$ (Chroma's default L2 distance), hit if similarity $> 0.85$.

#### Confidence Calibration Formula:
For a candidate mapping to canonical field $T$:

$$\text{Confidence} = 0.45 \cdot S_{\text{name}} + 0.35 \cdot V_{\text{profile}} + 0.20 \cdot A_{\text{method}}$$

Where:
- $S_{\text{name}}$: exact $0.97$; fuzzy $0.92 \times \frac{\text{ratio}}{100}$; semantic $0.90 \times \cos(\vec{q}, \vec{d})$; LLM $0.85 \times \text{conf}_{\text{llm}}$; memory $\min(\text{stored conf}, 0.99)$. A target found by both fuzzy and semantic uses the average.
- $V_{\text{profile}}$: Value-Profile Fit from `score_value_profile_fit(profile, T)` (section 2.2.1). An **empty** column scores a neutral $0.5$ here, so a correctly named but empty column is not out-ranked by weak matches.
- $A_{\text{method}}$: $1.0$ for memory, exact, or fuzzy+semantic agreement; $0.7$ for a target found by only one of fuzzy/semantic, and for LLM.
- Memory Boost: $\text{Confidence} \leftarrow \min(0.99, \text{Confidence} \times 1.10)$.
- `review_required = Confidence < HIGH_CONFIDENCE_THRESHOLD (0.90)`; LLM mappings always require review.

#### 2.2.1 Value-Profile Fit and Veto

| Target | Fit |
|--------|-----|
| Building Value, Contents, BI, Other | $0.6 \cdot \text{monetary} + 0.4 \cdot \text{numeric}$; halved if any value is negative (monetary = numeric with $|v| \ge 100$) |
| Year Built | year ratio (1700 … current year + 1); $+0.3$ if > 80% numeric and min/max in range |
| Zip | $z = \max(\text{zip5}, 0.6 \cdot \text{zip3–4})$; $z$ if $z > 0.5$, else $z \cdot (1 - \min(0.5, \text{monetary}))$. 3–4 digit integers are ZIPs that lost leading zeros |
| State | ratio of US state/territory codes (dots and spaces ignored: `V.I.` → `VI`) |
| Fire Sprinklers (Y/N) | $\min(1, \text{sprinkler codes} + 0.3 \cdot \text{Y/N})$ |
| Storeys, Number of Buildings | integer 1–200 ratio, $+0.2$ if > 80% numeric |
| Reference | $0.2$ if > 80% numeric with fractions (coordinates, amounts); else $0.5 + 0.5 \cdot \text{unique ratio}$ |
| Address | address-pattern ratio; at least $0.3$ for text columns (< 20% numeric) |
| City, County, Country | $0$ if > 80% numeric; else $0.7 \cdot (1-\text{numeric}) + 0.3 \cdot (1-\text{monetary})$ |
| Occupancy, Construction | $0.7 \cdot (1-\text{numeric}) + 0.3 \cdot (1-\text{monetary})$ (numeric codes allowed) |

**Veto:** a candidate (memory, exact, fuzzy, semantic or LLM) is rejected when the column has data and $V_{\text{profile}} < 0.25$ (`MIN_PROFILE_FIT`). Examples from real files: building numbers 1–6 as `Building Value`, $ amounts as `Number of Buildings`, longitudes as `Country`. The reason is kept in `evidence`.

#### 1:1 Target Uniqueness (`run_schema_mapping`)
1. **Pass 1:** score every named column independently (no LLM).
2. **Pass 2:** repeatedly commit the pending column with the highest current confidence. If its target is already claimed by a column from an overlapping sheet, re-score it with that target excluded and put it back in the queue at its new confidence. A column still unresolved at its turn gets the LLM stage.
3. Targets are unique **per sheet**: columns that come from different merged sheets (never sharing a row) may claim the same target.
4. `_apply_hungarian_assignment` is kept as a final safety net: if two columns from the same sheet still share a target, the lower-confidence one is demoted to `UNRESOLVED` with the reason in `rationale`.

---

### 2.3 Agent 3: Quality Reasoning & Auditing (`app.agents.quality_reasoning`)

#### Deterministic Rule Matrix:

| Check # | Target Field | Failure Condition | Suggested Whitelist Op | Severity |
|---------|--------------|-------------------|------------------------|----------|
| 1 | All mapped fields | Missingness $> 50\%$ / $> 20\%$ / $> 5\%$ | `flag_for_review` | High / Med / Low |
| 2 | Monetary Fields | Value contains `$` or `,` | `strip_currency` | Medium |
| 3 | Monetary Fields | Value $< 0$ (incl. accounting `(1,000)`) | `flag_for_review` | High |
| 4 | Monetary Fields | Non-numeric text (`TBD`, `Included in Bldg`) | `flag_for_review` | Medium |
| 5 | `Year Built` | Not a year, or $< 1700$ or $> \text{Year}_{\text{current}}$ | `to_year_int` | High |
| 6 | `Storeys` | Non-numeric, or $< 1$ | `flag_for_review` | Medium |
| 7 | `Number of Buildings` | Count $< 1$ | `flag_for_review` | Medium |
| 8 | `Fire Sprinklers (Y/N)` | Code not in `{"Y", "N", "Y13", "Y(13R)"}` | `normalize_sprinkler_code` | Medium |
| 9 | `State` | Not in `US_STATE_ABBREVS` | `state_to_abbrev` | Medium |
| 10 | `Reference` | Duplicated identifier rows | `flag_for_review` | High |
| 11 | `Zip` | Not 5 digits | `to_zip` | Low |
| 12 | Integer fields | Non-integer values | `to_int` | Low |

Each issue becomes a recommendation with `review_required = confidence < 0.90 or severity ∈ {High, Medium}`. Mapping recommendations (`MAP-…`, operation `trim_whitespace`) are generated for every mapped column.

#### Re-reasoning on rejected items (`_rereason_rejected_mappings`, `_apply_rereason_outcomes`)
Runs first when a recommendation is `REJECTED` with a note, `feedback_processed` is false and `re_reason_count < MAX_REREASON_ATTEMPTS`:
- **Column mapping:** `map_column` (Agent 2's cascade) is called for that source column with the rejected target and every target used by another column excluded. An alternative updates `state.mappings` and the same recommendation returns as `PENDING`, `review_required`, with the rejected target and the reviewer's note in `uncertainty` / `rationale`. No alternative: the mapping becomes `UNRESOLVED` and the item is `ESCALATED` ("Assign Target" in the UI).
- **Data fix:** stays `REJECTED`; `uncertainty` records that the change was withdrawn and the values stay as in the source.
- All handled items get `feedback_processed = True`, so neither the UI nor the graph re-reasons on them again.

#### Carry-over (`_carry_over_decisions`)
When Agent 3 runs again (a rejection with a note), regenerated recommendations keep the previous ID, status, rejection note, re-reason count and `feedback_processed` flag. Matching key: `(action_type, source_column)` for mappings (so an edited target survives); `(action_type, source_column, target_column, operation, issue_type)` otherwise. Same-key items are matched in order, never collapsed. The re-reasoning note is carried for processed items, and escalated items (or a target the human assigned to one) are kept even though their column is no longer mapped.

#### LLM enrichment (`_llm_explain_issues`)
- Prompt contains, per issue: severity, type, field, affected-row count, suggested operation and **one masked example** (`app.services.llm.masking.mask_value`). Raw evidence strings are not sent.
- The LLM may rewrite `rationale` / `uncertainty` and pick a whitelisted `operation` for data-quality recommendations. It cannot change the operation of a column mapping, and it can lower but never raise `confidence`; `review_required` is recomputed so it can only become stricter.

#### Composite Quality Score (`app.services.scoring.quality_score.compute_sov_quality_score`)
Agent 3 stores this value in `QualityReport.overall_quality_score`; the UI shows the same number.

$$\text{QualityScore} = 100 \times \left( 0.35 \cdot Q_{\text{mapping}} + 0.30 \cdot Q_{\text{completeness}} + 0.35 \cdot Q_{\text{anomalies}} \right)$$

Where:
- $Q_{\text{mapping}} = \frac{|\text{mapped}|}{17} \times \overline{\text{Confidence}}_{\text{mapped}}$
- $Q_{\text{completeness}} = \frac{1}{17}\sum_{f \in \text{targets}} \frac{\text{Non-Null-Pct}(f)}{100}$ (unmapped fields count as 0)
- $Q_{\text{anomalies}} = \max\left(0.0, 1.0 - \sum_{i \in \text{issues}} w_{\text{severity}}(i)\right)$, $w_{\text{High}} = 0.20, w_{\text{Med}} = 0.08, w_{\text{Low}} = 0.02$.

---

### 2.4 Agent 4: Controlled Transformation (`app.agents.transformation`)

#### Execution Invariant:
Only operations present in `WHITELISTED_OPERATIONS` are applied. A non-whitelisted operation is logged as an error and skipped; nothing is evaluated dynamically.

#### The Whitelisted Registry:
```python
TRANSFORMATION_REGISTRY: Dict[str, Callable] = {
    "strip_currency": strip_currency,      # "$1,000" → 1000.0; non-numeric → NA
    "to_float": to_float,
    "to_int": to_int,                      # "2.0" → 2; 1.5 stays 1.5 (never truncated)
    "to_str": to_str,
    "to_year_int": to_year_int,            # first 1700–2029 year in the text, else NA
    "to_zip": to_zip,                      # first 5 digits; 3–4 digit ZIPs kept (802)
    "state_to_abbrev": state_to_abbrev,    # names, "V.I." → "VI", US territories
    "normalize_sprinkler_code": normalize_sprinkler_code,
    "trim_whitespace": trim_whitespace,
    "normalize_spaces": normalize_spaces,
    "normalize_date": normalize_date,
    "flag_for_review": flag_for_review,    # identity
}
```

#### Rename, Collision Resolution & Mutation:
1. **Renames:** approved `COLUMN_MAPPING` recommendations, highest confidence first. A target can be claimed once per sheet; a later approved mapping to an already claimed target (e.g. after "Change Target") is skipped with a warning.
2. **Strays:** any other source column whose name equals a target field (e.g. a rejected or unreviewed `State`) is renamed to `_unmapped_{name}` so it cannot reach the output.
3. **Coalesce:** `rename_and_coalesce` combines per-sheet sources of one target.
4. **Operations:** approved `STANDARDISATION` / `DATA_CORRECTION` recommendations run on their target column as `object` dtype. The changed-row count and a before/after sample (first changed row) are computed **before** the result is written back, so a change can never be applied without its audit entry.
5. **Duplicate-name slices:** if `df[col]` yields a DataFrame, the slice with the most non-null values is kept.

---

### 2.5 Validation & Export (`app.processing.validation`, end of Agent 4)

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

1. **Ordering & Padding (`enforce_column_order`):** missing canonical columns are added empty; extra columns are dropped.
2. **Validation (`validate_output_schema`):** exactly 17 columns, exact names and order, the Pandera schema above, and **type conformance**: every non-null value of `Building Value`, `Contents`, `BI`, `Other` must be numeric, and of `Zip`, `Storeys`, `Number of Buildings`, `Year Built` integral. Each failure is reported as e.g. `Storeys: 1 non-integer value(s), e.g. 1.5`.
3. **Serialization:** `Cleaned_SOV_{session}_{timestamp}.xlsx` via openpyxl, copied to `Cleaned_SOV.xlsx` (and the audit log to `Audit_Log.xlsx`) in `OUTPUT_DIR`; the written file is re-opened and any merged cell range is a validation error; numeric `Zip` cells get number format `00000`. Files are written even when validation fails (stage `VALIDATING`), so the reviewer can see the problems.
4. **Audit Register:** `Audit_Log_{session}_{timestamp}.xlsx`.

---

## 3. Storage & Service Layer

### 3.1 Episodic Vector Memory (`app.services.memory.chroma_store`)
- **Backend:** embedded ChromaDB in `CHROMA_PERSIST_DIR` (default `./chroma_db`).
- **Collection:** `CHROMA_COLLECTION` (default `sov_mappings`), embedded with Chroma's default embedding function.
- **Documents:** `"{source_column} -> {target_field}"`, ID `map_{normalized_source}_{target}`; metadata `source_column`, `normalized_source`, `target_field`, `confidence`, `method` (`human_approved` / `human_edited`), `approved_by`, `timestamp`.
- **Writes:** only when a reviewer approves or edits a column mapping in the UI.
- **Reads:** similarity $= 1 - d/2$; results $> 0.5$ returned, $> 0.85$ used by Stage 0. Empty collections are skipped, and results are cached per (header, collection size), so a new approval invalidates the cache.

### 3.2 Dense Embedding Encoder (`app.services.embeddings.encoder`)
- **Model:** `EMBEDDING_MODEL` (default `BAAI/bge-small-en-v1.5`), 384 dimensions, normalized embeddings.
- **Caching:** the model is a process singleton; the corpus embeddings are computed once; fuzzy and semantic candidate lists are `lru_cache`d per header string.

### 3.3 LLM Gateway (`app.services.llm.gateway`) and Masking (`app.services.llm.masking`)
- **Abstraction:** `LLMGateway.complete()` and `complete_structured()` (Pydantic-validated JSON with retries).
- **Off switch:** `LLM_PROVIDER` = `none` / `off` / `disabled` makes `is_llm_available()` false and `complete()` return `None`.
- **Provider order:** `LLM_PROVIDER` first, then the others. Groq and Gemini are tried only with an API key; Ollama only when `LLM_PROVIDER=ollama` or `OLLAMA_BASE_URL` is set explicitly (`Config.OLLAMA_CONFIGURED`).
- **Safe Heuristic Mode:** if every provider fails, `complete()` returns `None` and the agents keep their deterministic results.
- **Masking:** `mask_value` replaces digits with `9`, e-mail addresses with `<email>`, and truncates to 32 characters.

### 3.4 Orchestration (`app.orchestration.graph`)
- **Nodes:** `discover_sheets → map_schema → assess_quality → human_review → transform_export`, plus `re_reason` and `error`. Every conditional edge has an explicit path map.
- **Routing after review:** unprocessed rejection notes (count below `MAX_REREASON_ATTEMPTS`) → `re_reason` (which marks them `feedback_processed`) → `human_review`; review-required items still pending → `human_review` (pause again); otherwise → `transform_export`.
- **Checkpointing:** compiled once per process with `interrupt_before=["human_review"]` and a `SqliteSaver` (in-memory fallback).
- **API:** `run_pipeline_to_review(state, thread_id)` runs to the pause. `resume_pipeline_after_review(state, thread_id)` writes the reviewed state into the checkpoint (`update_state`) and continues with `invoke(None)`. The UI uses a fresh `thread_id` per pipeline run.

---

## 4. Test Strategy & Verification

The system is guarded by 92 tests in `tests/test_sov_system.py`; `tests/conftest.py` redirects ChromaDB, outputs, uploads and checkpoints to a temporary directory.
- **Unit Tests:** ingestion, header detection, sheet ranking, exact/fuzzy mapping, confidence, value profiling, anomaly rules, every whitelisted transformation, null preservation, schema validation, masking, LLM-provider gating.
- **Integration Tests:** end-to-end runs on the synthetic samples; the LangGraph run → pause → reject/re-reason → resume → export cycle; audit logging; malformed input.
- **Real-file regressions:** synthetic workbooks reproducing defects found in the broker files (merged footnotes, first-come mapping, value-profile veto, multi-sheet merge, rejected same-name columns, zero-stripped ZIPs, flags sharing a field). The four broker files themselves are not part of the automated suite; they are verified manually (see `README.md`, "Verified on Real SOVs").

---

## 5. Unclaimed Columns Feature

### 5.1 Overview

Agent 2 places every source column that could not be matched to a target field in `MappingResult.unmapped_source_columns`. These columns are **never** written to `Cleaned_SOV.xlsx` by default (they are dropped by `enforce_column_order`). The **Unclaimed Columns** review section gives the human reviewer a deterministic way to handle them before transformation.

### 5.2 Review UI (`app/ui/streamlit_app.py` → `render_unclaimed_section`)

Rendered at the **bottom of the Review tab**, below the four standard expanders, only when `state.mappings.unmapped_source_columns` is non-empty. For each unclaimed column the section shows:

- **Column name** in monospace
- **Sample values** from the raw source DataFrame (up to 4, best-effort)
- **Visual status badge** — red border = rejected, green = assigned, neutral = no decision
- **Controls row:** selectbox (17 target fields + blank placeholder) + **Assign** button + **Reject**/**Undo** button

Decisions are stored in `st.session_state["unclaimed_decisions"]` (a `Dict[str, str]`):

| Value | Meaning |
|-------|---------|
| `"__rejected__"` | Drop column — never reaches the output |
| A `TARGET_FIELDS` name | Manually assign to that target field |
| *(absent)* | No action — column is silently dropped by `enforce_column_order` |

Decisions are flushed into `state.unclaimed_decisions` immediately before `_run_transformation` is called (both Apply button sites). The `unclaimed_decisions` dict is cleared on session reset.

### 5.3 Transformation Logic (`app/agents/transformation.py` → `_apply_approved_transformations`, Step 3)

Runs **after** all approved recommendation transforms, **before** `enforce_column_order`.

**Grouping:** all manual assignments are first grouped by target field. This ensures that two or more source columns assigned to the same target are always space-merged, whether that target was pre-populated by an approved recommendation or was entirely absent.

**Reject path:**
```
for src_col in reject_cols:
    df.drop(columns=[src_col])   # removed; logged to audit trail as "unclaimed_reject"
```

**Assign path (per target group):**
```
if target already in df.columns:
    # Always merge — target was pre-populated
    for src_col in src_cols:
        accumulator = safe_space_concat(df[target], df[src_col])
        df.drop(src_col)
    df[target] = accumulator

else:
    # Target was empty
    df.rename(src_cols[0] → target)      # first source becomes the base
    for src_col in src_cols[1:]:         # additional sources: merge in
        accumulator = safe_space_concat(df[target], df[src_col])
        df.drop(src_col)
    df[target] = accumulator
```

**NaN-safe concatenation (`_merge_series`):**
- Both non-null → `left + " " + right`
- Only left non-null → `left`
- Only right non-null → `right`
- Both null → null

Every accept/assign operation appends an `AuditEntry` with `transformation_applied = "unclaimed_manual_assign"` or `"unclaimed_reject"`.

---

## 6. Pipeline Animation

When the **Run Pipeline** button is clicked, `_show_pipeline_animation_and_run()` is called. It:

1. Renders a full-width animated card via `st.empty().markdown(...)` with:
   - A gradient progress bar (`@keyframes bar-slide`, 12-second fill)
   - Four pulsing agent-step pills (`@keyframes agent-pulse`, staggered delays)
   - Three bouncing loading dots (`@keyframes dot-bounce`)
2. Calls `_run_pipeline(uploaded_file)` synchronously inside a `try/finally`
3. Clears the placeholder unconditionally in `finally` — so the card disappears whether the pipeline succeeded or failed

No additional threads or async code is introduced; Streamlit's synchronous rendering model is preserved.

---

## 7. Review Actions, Feedback Persistence & Mapping Accuracy KPI

### 7.1 Single-Click Column Rejection & Deterministic Drop
When a reviewer clicks **Reject** on any column mapping recommendation:
1. The status transitions immediately to `RecommendationStatus.REJECTED` with zero modal prompts or required feedback notes.
2. In `app/agents/transformation.py` (`_apply_approved_transformations`), every source column belonging to a rejected column mapping recommendation is explicitly dropped from the DataFrame:
   ```python
   for rec in state.recommendations:
       if rec.action_type == ActionType.COLUMN_MAPPING and rec.status == RecommendationStatus.REJECTED:
           if rec.source_column in df.columns:
               df = df.drop(columns=[rec.source_column])
   ```
3. An audit record is logged to `Audit_Log.xlsx` with `transformation_applied="column_rejected_dropped"` and `after_value="Dropped (rejected by reviewer)"`, with `recommendation_id=None` so it does not count as an applied transformation.

### 7.2 Change Target & ChromaDB Active Feedback
When a reviewer uses **Change Target** to manually assign a column to another standard field:
1. `rec.target_column` is updated to the newly selected target field, with `confidence = 1.0` and status `APPROVED`.
2. The internal `state.mappings.mappings` entry for that column is kept synchronized.
3. The human correction is stored into ChromaDB persistent vector memory:
   ```python
   store_approved_mapping(
       source_column=rec.source_column,
       target_field=new_target,
       confidence=1.0,
       method="human_feedback",
       reviewer_id="human",
   )
   ```
4. On future SOV uploads, Stage 0 Vector Memory recalls this human-verified mapping first.

### 7.3 Real-Time Mapping Accuracy KPI
The Review tab renders a top action bar metric card beside the bulk approval button:
$$\text{Mapping Accuracy (\%)} = \frac{\text{predicted\_columns\_approved}}{\text{total\_columns\_predicted}} \times 100$$
- $\text{total\_columns\_predicted}$: Number of recommendations with `action_type == ActionType.COLUMN_MAPPING`.
- $\text{predicted\_columns\_approved}$: Count of those recommendations with status `APPROVED`.
- Dynamically updates as the underwriter approves, rejects, or edits mappings.


