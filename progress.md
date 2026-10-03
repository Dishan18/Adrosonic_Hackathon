# Project Progress: Agentic SOV Cleansing & Intelligence System

**Status:** ✅ Production-Ready, Fully Tested  
**Last Updated:** 2026-10-03  
**System Architecture:** CacheMeIfYouCan (PS3) — Agentic SOV Cleansing & Intelligence System.

---

## 1. Project Overview & Architecture

Statement of Values (SOV) files in commercial property insurance are notoriously heterogeneous, messy, and non-standard. The system converts raw multi-tab spreadsheets into clean, validated, standardized 17-column datasets with an immutable audit trail and Human-In-The-Loop (HITL) approval.

### Four Core Agents:
1. **Agent 1: Sheet Discovery & Intelligence (`app.agents.sheet_discovery`)**
   - Automatically inspects all sheets in uploaded `.xlsx`/`.xls`/`.csv` files.
   - Computes tabular density, header candidate scores, unmerges cells safely, and extracts primary data.
   - Samples up to 200 rows for type consistency scoring (fast on 5000+ row files).
2. **Agent 2: Schema Mapping Agent (`app.agents.schema_mapping`)**
   - Multi-stage cascading column mapping:
     1. Vector Memory Retrieval (ChromaDB historical matches)
     2. Exact / Alias matching against insurance synonyms
     3. Fuzzy string matching (RapidFuzz token sort/set ratio)
     4. Semantic embedding similarity (`bge-small-en-v1.5`)
     5. LLM fallback (Ollama mistral / Groq gpt-oss-20b)
   - Value profiling (numeric, currency, year, zip, storey, sprinkler detection).
   - Composite confidence score calculation with strict 1-to-1 target constraint.
   - DataFrame→Series deduplication guards throughout cascade.
3. **Agent 3: Data Quality & Reasoning (`app.agents.quality_reasoning`)**
   - Deterministic rule engine for format, logical, completeness, and anomaly issues.
   - Sprinkler code validation, negative monetary detection, year range check (1700-present), storeys > 0.
   - LLM-assisted root-cause reasoning and actionable recommendations with confidence and uncertainty flags.
4. **Agent 4: Controlled Transformation & Export (`app.agents.transformation`)**
   - Strict whitelist execution engine (LLM never executes arbitrary code on real data).
   - Supported operations: `strip_currency`, `to_year_int`, `state_to_abbrev`, `normalize_sprinkler_code`, `to_float`, `to_int`, `to_zip`, `trim_whitespace`, `flag_for_review`, etc.
   - Exact 17-column schema enforcement and Pandera validation.
   - Export to formatted Excel: `Cleaned_SOV.xlsx` + `Audit_Log.xlsx`.
   - Pre-rename collision avoidance prevents duplicate column name creation.

---

## 2. Implementation Checklist & Status

- [x] **Project Scaffolding & Dependencies** (`requirements.txt`, `.env.template`)
- [x] **Target Schema & Validation** (`app/schemas/target_schema.py`, exact 17 fields, Pandera schema)
- [x] **State Models** (`app/schemas/state_models.py`, Pydantic v2 `SOVState`, `ColumnMapping`, `Recommendation`, `AuditEntry`)
- [x] **Agent 1: Sheet Discovery** (`app/agents/sheet_discovery.py`, openpyxl merged cell handling, header row detection)
- [x] **Profiling & Similarity** (`app/processing/profiling.py`, column profiling, pattern matching, profile fit scoring)
- [x] **Agent 2: Schema Mapping** (`app/agents/schema_mapping.py`, 4-stage cascade, memory boost, 1-to-1 constraint)
- [x] **Vector Memory Service** (`app/services/memory_service.py`, ChromaDB + persistent storage)
- [x] **Agent 3: Quality Reasoning** (`app/agents/quality_reasoning.py`, deterministic rules + LLM reasoning)
- [x] **Transformations Whitelist** (`app/processing/transformations.py`, pure functions, null preservation)
- [x] **Agent 4: Transformation & Export** (`app/agents/transformation.py`, audit trail logging, Excel generation)
- [x] **Audit Engine** (`app/audit/audit_logger.py`, structured change tracking, before/after records)
- [x] **LangGraph Orchestrator** (`app/orchestration/graph.py`, StateGraph, interrupt gate before transformation, checkpoints)
- [x] **Streamlit UI** (`app/ui/streamlit_app.py`, Apple-styled minimal UI: Upload → Review → Final Output tabs)
- [x] **Benchmark Suite** (`benchmark.py`, evaluations against sample files and ground truth)
- [x] **Automated Tests** (`tests/test_sov_system.py`, 75 tests, comprehensive coverage across all agents and edge cases)

---

## 3. Key Technical Decisions & Fixes Applied

### Session 1: Initial Build
1. **Pydantic v2 Compatibility**: Replaced deprecated `class Config:` with `model_config = ConfigDict(use_enum_values=True)`. Added `review_required` attribute to `Recommendation` model.
2. **Deterministic Rules & Anomaly Detection**: Exact detection for non-standard sprinkler codes (`Y`, `N`, `Y13`, `Y(13R)`). Robust numeric ZIP handling for both string and float/integer loaded representations.
3. **HITL Review Thresholds**: Mappings and recommendations below 90% confidence trigger mandatory human review. Export locked until all recommendations are reviewed and approved.

### Session 2: UI Redesign (Apple/iOS Aesthetic)
- Minimal, premium Apple/iOS inspired UI — clean white/light-gray background, system fonts, strong whitespace hierarchy.
- Smooth, non-glitchy tab navigation with `st.segmented_control`.
- Button loading states: "Running Pipeline...", "Applying Transformations..." with lock/unlock flow.
- Top action bar for review controls (Approve All High-Confidence, Apply Approved Transformations).

### Session 3: Production File Bug Fixes (2026-10-03)
1. **Duplicate Column Header Fix (`workbook.py`, `profiling.py`, `schema_mapping.py`)**:
   - `SOV_B4ID.xlsx` row 11 had 3 columns named `'2024 - Increase 10%'`. Pandas returned a `pd.DataFrame` instead of `pd.Series` when slicing, causing `AttributeError`.
   - Added: deduplication in `extract_data_frame()` + `isinstance(series, pd.DataFrame)` guards throughout.
2. **17-Column Output Collision Fix (`transformation.py`, `validation.py`)**:
   - Source column `'Other'` collided with target `'Other'` after renaming, producing 18 columns and failing Pandera.
   - Added: pre-rename collision avoidance + rebuilt `enforce_column_order()` to always produce exactly 17 columns from a fresh DataFrame.
3. **`normalize_sprinkler_code` Integer Safety (`transformations.py`)**:
   - Integer sprinkler codes in `SOV_Q8B3.xlsx` caused `Expected bytes, got 'int'` error.
   - Wrapped in try/except; added element-level fallback in `apply_transformation_to_series()`.
4. **Local Ollama LLM Integration (`gateway.py`, `config.py`, `.env`)**:
   - Groq free-tier 8,000 TPM limit exhausted on large files.
   - Switched primary provider to local Ollama (`mistral:latest`, 4.4 GB, running on `localhost:11434`).
   - Provider routing: `ollama → groq → gemini` fallback chain.
   - Ollama `format=json` mode for structured output; regex JSON extraction as parse fallback.

---

## 4. Test Suite & Benchmark Verification

### Pytest Coverage (`tests/test_sov_system.py`)
- **Total Tests:** 75
- **Passed:** 75 (100%)
- **Failed:** 0
- **Duration:** ~404s (6m 44s) — includes Ollama LLM inference

### Production File E2E Verification
| File | Size | Sheet | Header Row | Mapped | Validation | Result |
|:-----|:-----|:------|:-----------|:-------|:-----------|:-------|
| `SOV_B4ID.xlsx` | 9.6 KB | `SOV` | 11 | 17/17 | 17 cols, Pandera ✅ | **PASSED** |
| `SOV_H6D2.xlsx` | 34.1 KB | `SOV` | 6 | 17/17 | 17 cols, Pandera ✅ | **PASSED** |
| `SOV_K4T9.xlsx` | 41.3 KB | `Locations` | 5 | 11/17 | 17 cols, Pandera ✅ | **PASSED** |
| `SOV_Q8B3.xlsx` | 1.9 MB | `23-24 Values` | 0 | 15/17 | 17 cols, Pandera ✅ | **PASSED** |

### Benchmark Suite Evaluation (`benchmark.py`)
| Metric | Achieved | Target Requirement | Status |
|:---|:---:|:---:|:---:|
| **Mapping Accuracy** | **100.00%** | ≥ 74.0% | ✅ **PASS** |
| **Anomaly Recall** | **91.67%** | ≥ 90.0% | ✅ **PASS** |
| **Transformation Correctness** | **100.00%** | ≥ 95.0% | ✅ **PASS** |
| **Explainability Coverage** | **100.00%** | 100.0% | ✅ **PASS** |
| **Audit Completeness** | **100.00%** | 100.0% | ✅ **PASS** |

---

## 5. LLM Provider Configuration

| Provider | Model | Status | Notes |
|:---------|:------|:-------|:------|
| **Ollama (Local)** | `mistral:latest` (4.4 GB) | ✅ Primary | No rate limits, fully offline |
| **Groq** | `openai/gpt-oss-20b` | ✅ Fallback | 8K TPM free tier |
| **Gemini** | `gemini-3.6-flash` | ✅ Fallback | via REST API |

Ollama must be running before starting the app: `ollama serve`

---

## 6. Frontend Interactive Workflow

### User Flow
```
Upload File → Click "Run Pipeline" (locked while running)
    → Automatic redirect to Review tab
    → Review recommendations (approve/deny individually or bulk)
    → "Apply Approved Transformations" appears when all required reviews done
    → Click Apply (locked while running)
    → Automatic redirect to Final Output tab
    → Download Cleaned_SOV.xlsx and Audit_Log.xlsx
```

### Key UI Features
1. **Run Pipeline button**: locks immediately with "Running Pipeline..." feedback
2. **Approve All High-Confidence**: bulk-approves ≥90% confidence recommendations
3. **Apply Approved Transformations**: only unlocks when all review_required=True items are decided
4. **Final Output tab**: download links for both output files + validation status badge

---

## 7. Running the System

```bash
# 1. Start Ollama (required for LLM)
ollama serve

# 2. Activate virtual environment (if using one)
# 3. Start the Streamlit app
streamlit run app/ui/streamlit_app.py --server.port 8501

# 4. Open browser: http://localhost:8501

# 5. Run tests
pytest tests/test_sov_system.py -v
```
