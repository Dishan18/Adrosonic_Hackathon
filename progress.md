# Project Progress: Agentic SOV Cleansing & Intelligence System

**Status:** ✅ Audited against four real broker SOVs; demo requirements (brief pp. 13–16) covered; 92/92 tests passing  
**Last Updated:** 2026-10-03  
**System Architecture:** CacheMeIfYouCan (PS3) — Agentic SOV Cleansing & Intelligence System.

---

## 1. Project Overview & Architecture

Statement of Values (SOV) files in commercial property insurance are notoriously heterogeneous, messy, and non-standard. The system converts raw multi-tab spreadsheets into clean, validated, standardized 17-column datasets with an audit trail and Human-In-The-Loop (HITL) approval.

### Four Core Agents:
1. **Agent 1: Sheet Discovery & Intelligence (`app.agents.sheet_discovery`)**
   - Inspects all sheets in uploaded `.xlsx`/`.csv` files.
   - Computes tabular density and header candidate scores; unmerges cells (fill down only) and extracts data.
   - Samples up to 200 rows for type consistency scoring (fast on 5000+ row files).
   - Every sheet classified PRIMARY is a data sheet; all of them are merged into one output.
2. **Agent 2: Schema Mapping Agent (`app.agents.schema_mapping`)**
   - Multi-stage cascading column mapping:
     1. Vector Memory Retrieval (ChromaDB, human-approved mappings)
     2. Exact / Alias matching against insurance synonyms
     3. Fuzzy string matching (RapidFuzz token sort ratio, top-5 candidates)
     4. Semantic embedding similarity (`bge-small-en-v1.5`, top-5 candidates)
     5. LLM fallback (Ollama / Groq / Gemini) for still-unresolved columns
   - Value profiling (numeric, currency, year, zip, storey, sprinkler detection); candidates whose values contradict the field are vetoed.
   - Composite confidence score; targets claimed strongest-column-first, 1-to-1 within each sheet.
3. **Agent 3: Data Quality & Reasoning (`app.agents.quality_reasoning`)**
   - Deterministic rule engine (12 checks) for format, logical, completeness, and anomaly issues.
   - LLM-assisted explanations from counts and masked examples; the LLM can never raise a confidence.
   - Re-reasoning after a rejection: alternative mapping or escalation to a human; every other decision kept.
4. **Agent 4: Controlled Transformation & Export (`app.agents.transformation`)**
   - Strict whitelist execution engine (LLM never executes arbitrary code on real data).
   - Supported operations: `strip_currency`, `to_float`, `to_int`, `to_str`, `to_year_int`, `to_zip`, `state_to_abbrev`, `normalize_sprinkler_code`, `trim_whitespace`, `normalize_spaces`, `normalize_date`, `flag_for_review`.
   - Exact 17-column schema enforcement, Pandera validation and numeric type checks.
   - Export to Excel: `Cleaned_SOV.xlsx` (Zip formatted `00000`) + `Audit_Log.xlsx`.

---

## 2. Implementation Checklist & Status

- [x] **Project Scaffolding & Dependencies** (`requirements.txt`, `.env.template`)
- [x] **Target Schema & Validation** (`app/schemas/target_schema.py`, exact 17 fields; `app/processing/validation.py`, Pandera + type checks)
- [x] **State Models** (`app/schemas/state_models.py`, Pydantic v2 `SOVState`, `ColumnMapping`, `Recommendation`, `AuditEntry`)
- [x] **Agent 1: Sheet Discovery** (`app/agents/sheet_discovery.py`, merged-cell handling, header row detection, data sheets)
- [x] **Workbook Ingestion** (`app/processing/workbook.py`, cached parsing, note/footer filtering, multi-sheet merge)
- [x] **Profiling & Similarity** (`app/processing/profiling.py`, column profiling, profile fit scoring)
- [x] **Agent 2: Schema Mapping** (`app/agents/schema_mapping.py`, cascade, value-profile veto, confidence-ordered 1:1 assignment)
- [x] **Vector Memory Service** (`app/services/memory/chroma_store.py`, ChromaDB + persistent storage)
- [x] **Agent 3: Quality Reasoning** (`app/agents/quality_reasoning.py`, deterministic rules + LLM reasoning)
- [x] **Quality Score** (`app/services/scoring/quality_score.py`, single formula used by Agent 3 and the UI)
- [x] **Transformations Whitelist** (`app/processing/transformations.py`, pure functions, null preservation)
- [x] **Agent 4: Transformation & Export** (`app/agents/transformation.py`, audit trail logging, Excel generation)
- [x] **Audit Engine** (`app/audit/logger.py`, structured change tracking, before/after records)
- [x] **LangGraph Orchestrator** (`app/orchestration/graph.py`, StateGraph, interrupt before human review, SQLite checkpoints, working resume)
- [x] **LLM Gateway & Masking** (`app/services/llm/gateway.py`, `app/services/llm/masking.py`)
- [x] **Streamlit UI** (`app/ui/streamlit_app.py`, Upload → Review → Final Output; runs through the LangGraph graph)
- [x] **Benchmark Suite** (`benchmark.py`, evaluations against the synthetic samples; labels inline)
- [x] **Automated Tests** (`tests/test_sov_system.py`, 92 tests; `tests/conftest.py` isolates persistent stores)

---

## 3. Key Technical Decisions & Fixes Applied

### Session 1: Initial Build
1. **Pydantic v2 Compatibility**: Replaced deprecated `class Config:` with `model_config`. Added `review_required` attribute to `Recommendation` model.
2. **Deterministic Rules & Anomaly Detection**: Detection for non-standard sprinkler codes (`Y`, `N`, `Y13`, `Y(13R)`). Numeric ZIP handling for both string and float/integer loaded representations.
3. **HITL Review Thresholds**: Mappings and recommendations below 90% confidence trigger mandatory human review. Export locked until all review-required recommendations are decided.

### Session 2: UI Redesign (Apple/iOS Aesthetic)
- Minimal, Apple/iOS inspired UI — clean white/light-gray background, system fonts, strong whitespace hierarchy.
- Smooth tab navigation with `st.segmented_control`.
- Button loading states: "Running Pipeline...", "Applying Transformations..." with lock/unlock flow.
- Top action bar for review controls (Approve All High-Confidence, Apply Approved Transformations).

### Session 3: Production File Bug Fixes (2026-10-03)
1. **Duplicate Column Header Fix (`workbook.py`, `profiling.py`, `schema_mapping.py`)**: `SOV_B4ID.xlsx` row 11 had 3 columns named `'2024 - Increase 10%'`; added deduplication in `extract_data_frame()` and `isinstance(series, pd.DataFrame)` guards.
2. **17-Column Output Collision Fix (`transformation.py`, `validation.py`)**: source column `'Other'` collided with target `'Other'`; `enforce_column_order()` now always builds exactly 17 columns.
3. **`normalize_sprinkler_code` Integer Safety (`transformations.py`)**: wrapped in try/except; element-level fallback in `apply_transformation_to_series()`.
4. **Local Ollama LLM Integration (`gateway.py`, `config.py`, `.env`)**: primary provider switched to local Ollama (`mistral`); provider routing with fallback; Ollama `format=json` for structured output.

> The Session 3 end-to-end check only confirmed that each file produced 17 columns and passed the (then column-only) validation. The Session 4 audit found that the content of three of the four outputs was wrong; see below.

### Session 4: Real-File Audit (2026-10-03)
Running the four broker files end to end and inspecting the output values showed:

| File | Defect found |
|------|--------------|
| SOV_B4ID | Building numbers (`Bldg.`) mapped to Building Value and building values to Number of Buildings; merged footnote rows copied into every column, so `to_zip`/`to_year_int` produced values from note text (Zip "20182", Year Built 2018) |
| SOV_K4T9 | Reference = "Client A" for every row (`Account Name`), Country = longitude; `Location ID` and `Country Name` left unmapped |
| SOV_Q8B3 | Building codes (`hou-1`) as Building Value, real `2023 Building Value` unmapped, Storeys = square footage; sprinkler transform applied without an audit entry |
| SOV_H6D2 | Footnote row output as a location |

Fixes:
1. **Merged cells** filled down the first column only; note, footnote and whitespace-only rows dropped.
2. **Mapping**: candidates vetoed when the column's values contradict the field; targets claimed strongest-first instead of left to right; ambiguous synonyms ("Bldg", "Buildings") removed and real-file synonyms added.
3. **Agent 4**: unapproved/rejected columns that already carry a target name no longer leak into the output; transformations are audited before they are written back (pandas 3 mixed-type crash).
4. **Agent 3**: re-reasoning keeps prior decisions; LLM cannot raise confidence or attach operations to mappings; non-numeric monetary values detected; negative-value sample bug fixed.
5. **Validation**: numeric type conformance added (it previously checked column names only).
6. **Multi-sheet**: every PRIMARY sheet merged into one output (per-sheet 1:1 mapping, columns coalesced).
7. **Performance**: workbook parsed once per file instead of once per sheet and per agent (Q8B3 discovery 60–126 s → 6–15 s, depending on machine load); empty mapping memory no longer queried.
8. **Tests**: isolated from the real `chroma_db/` (test runs had written "approved" mappings such as `SW → Reference`).

### Session 5: Follow-up Fixes (2026-10-03)
1. **Mapping memory**: the polluted store was moved to `chroma_db_backup_20261003/` (git-ignored); a fresh store is created on first use.
2. **Semantic threshold**: default and `.env` raised from 0.60 to 0.70.
3. **Bulk approval**: "Approve All Remaining" now covers only items that do not require review.
4. **Zip / Storeys**: ZIPs that lost leading zeros (802) are kept and exported with format `00000`; `to_int` no longer truncates fractions (1.5 stays 1.5 and is reported by validation).
5. **LangGraph**: the UI now runs through the graph; `resume_pipeline_after_review` actually resumes (it previously restarted at discovery); the "still pending" route no longer crashes; re-reasoning receives the rejection notes; checkpoints store plain JSON values; `langgraph-checkpoint-sqlite` added to `requirements.txt`.
6. **Quality score**: one formula (`compute_sov_quality_score`) for the stored report, the benchmark and the UI.
7. **LLM data minimisation**: sample values and issue examples are masked (digits → `9`, e-mails removed, truncated).
8. **Ollama fallback**: used only when it is the provider or `OLLAMA_BASE_URL` is set explicitly.

### Session 6: Demo Readiness (2026-10-03)
Checked against the challenge brief (constraints C-01–C-07, success metrics, 7 demo stages):
1. **Re-reasoning / escalation (stage 5):** a rejected mapping gets the next-best target from Agent 2's cascade or is escalated to a human ("Assign Target"); a rejected fix is withdrawn with an explanation. Deterministic, so it works without an LLM.
2. **Mapping JSON (stage 2):** Schema Mapping tab shows the mapping JSON (confidence, method, evidence) and offers `Schema_Mapping.json`.
3. **Per-field completeness (stage 3):** Data Quality tab shows completeness for all 17 fields.
4. **Cleaned output, audit log, schema conformance (stages 6–7):** Final Output tab shows header order, per-field type check, merged-cell count (0), the first cleaned rows and the audit trail.
5. **C-07 file names:** `outputs/Cleaned_SOV.xlsx` and `outputs/Audit_Log.xlsx` are written on every run.
6. **Value profile:** a column of 4-digit years no longer fits monetary fields.
7. **End-to-end time:** 15–22 s per real file from a cold start (target < 60 s).
8. **Deterministic mode:** `LLM_PROVIDER=none` switches the LLM off even when API keys are set in `.env`.
9. **Demo script:** `DEMO.md`; final deck: `CacheMeIfYouCan_PS3_Final.pptx`.

---

## 4. Test Suite & Benchmark Verification

### Pytest Coverage (`tests/test_sov_system.py`)
- **Total Tests:** 92
- **Passed:** 92 (100%)
- **Failed:** 0
- **Duration:** 17–34 s with the LLM disabled (`LLM_PROVIDER=none`), depending on machine load

### Real-File End-to-End Verification (LLM off, empty memory, all recommendations approved)
| File | Data sheets | Header row | Output rows | Hand-labelled columns correct | Validation |
|:-----|:------------|:-----------|:------------|:------------------------------|:-----------|
| `SOV_B4ID.xlsx` | `SOV` | 11 | 15 | 15/15 | Reports `Storeys` 1.5 (fraction kept, not truncated) |
| `SOV_H6D2.xlsx` | `SOV` | 6 | 19 | 15/15 | ✅ Passed |
| `SOV_K4T9.xlsx` | `Locations` | 5 | 34 | 12/12 | ✅ Passed |
| `SOV_Q8B3.xlsx` | `23-24 Values`, `Deleted Locations`, `Insured Elsewhere` | 0 | 990 | 13/13 | Reports `Contents` "Included in Bldg" |

### Benchmark Suite Evaluation (`benchmark.py`, synthetic samples)
| Metric | Achieved | Target Requirement | Status |
|:---|:---:|:---:|:---:|
| **Mapping Accuracy** | **100.00%** | ≥ 74.0% | ✅ **PASS** |
| **Anomaly Recall** | **100.00%** | ≥ 90.0% | ✅ **PASS** |
| **Transformation Correctness** | **100.00%** | ≥ 95.0% | ✅ **PASS** |
| **Explainability Coverage** | **100.00%** | 100.0% | ✅ **PASS** |
| **Audit Completeness** | **100.00%** | 100.0% | ✅ **PASS** |

---

## 5. LLM Provider Configuration

| Provider | Default model (code) | Used when | Notes |
|:---------|:---------------------|:----------|:------|
| **Ollama (Local)** | `mistral` | `LLM_PROVIDER=ollama`, or `OLLAMA_BASE_URL` set | No rate limits, fully offline |
| **Groq** | `openai/gpt-oss-20b` | `GROQ_API_KEY` set | Other Groq models tried if the configured one fails |
| **Gemini** | `gemini-2.5-flash` | `GEMINI_API_KEY` set | Via REST API |

The provider in `LLM_PROVIDER` is tried first. Ollama must be running before starting the app when it is used: `ollama serve`.

---

## 6. Frontend Interactive Workflow

### User Flow
```
Upload File → Click "Run Pipeline" (locked while running)
    → LangGraph runs Agents 1–3 and pauses before human review
    → Review recommendations (approve/reject/change target; bulk approval for ≥90% items)
    → "Apply Approved Transformations" appears when all review-required items are decided
    → Click Apply (locked while running) → graph resumes into Agent 4
    → Final Output tab: download Cleaned_SOV.xlsx and Audit_Log.xlsx
```

### Key UI Features
1. **Run Pipeline button**: locks immediately with "Running Pipeline..." feedback
2. **Approve All High-Confidence**: bulk-approves pending recommendations at ≥90% confidence
3. **Approve All Remaining**: shown when no ≥90% items are pending; covers only items that do not require review. Otherwise a disabled "Review Remaining Individually" button is shown
4. **Apply Approved Transformations**: unlocks only when all review_required=True items are decided
5. **Discovery section**: lists the data sheets merged into the output
6. **Final Output tab**: download links for both output files + validation status badge

---

## 7. Running the System

```bash
# 1. Start Ollama (when LLM_PROVIDER=ollama)
ollama serve

# 2. Activate virtual environment (if using one)
# 3. Start the Streamlit app
streamlit run app/ui/streamlit_app.py --server.port 8501

# 4. Open browser: http://localhost:8501

# 5. Run tests
pytest tests/test_sov_system.py -v
```
