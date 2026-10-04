# Agentic SOV Intelligence System

> **AI proposes. Code verifies. Humans approve. Everything is audited.**

An end-to-end agentic pipeline for cleansing and standardising chaotic Statement of Values (SOV) insurance data into an exact 17-field schema, with full human-in-the-loop control and a comprehensive audit trail.

---

## Architecture

```
Upload SOV File
      │
      ▼
┌─────────────────────────────────────────┐
│  Agent 1: Sheet Intelligence & Discovery│  ← Ranks sheets, finds header rows,
│  (LangGraph Node: discover_sheets)      │    unmerges cells; every PRIMARY
└─────────────────────────────────────────┘    sheet becomes a data sheet
      │
      ▼
┌─────────────────────────────────────────┐
│  Agent 2: Schema Mapping Agent          │  ← Cascade: Memory→Exact→Fuzzy+Semantic→LLM
│  (LangGraph Node: map_schema)           │    value-profile veto, confidence-ordered
└─────────────────────────────────────────┘    1:1 assignment (per sheet)
      │
      ▼
┌─────────────────────────────────────────┐
│  Agent 3: Data Quality & Reasoning      │  ← Deterministic rules + LLM
│  (LangGraph Node: assess_quality)       │    explanation (masked values only)
└─────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────┐
│  Human Review (HITL)                    │  ← Approve / 1-Click Reject / Change Target
│  (LangGraph interrupt before            │    1-Click Reject drops column (audited)
│   human_review, checkpointed)           │    Change Target stores feedback in ChromaDB
│                                         │    Live Mapping Accuracy KPI display
└─────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────┐
│  Agent 4: Controlled Transformation     │  ← Only whitelisted ops
│  (LangGraph Node: transform_export)     │    LLM never touches data
└─────────────────────────────────────────┘
      │
      ▼
 Cleaned_SOV.xlsx (17 fields, validated)
 Audit_Log.xlsx (full transformation trail)
```

**Review, rejection & feedback:** Clicking **Reject** on a column mapping immediately drops that column from the output without prompt friction (audited in `Audit_Log.xlsx`). Clicking **Change Target** allows manually assigning the column to another target standard field, storing this human correction into ChromaDB persistent vector memory (`method="human_feedback"`). A real-time **Mapping Accuracy KPI** (`approved_predicted / total_predicted * 100`) is displayed in the top action bar.

**Deliverables:** every run writes `outputs/Cleaned_SOV.xlsx` and `outputs/Audit_Log.xlsx` (the required names; overwritten by the latest run) plus timestamped copies `Cleaned_SOV_<session>_<time>.xlsx` / `Audit_Log_<session>_<time>.xlsx` as history. The UI also offers the column mappings as `Schema_Mapping.json`.

The Streamlit UI runs Agents 1-3 through the compiled LangGraph `StateGraph`, which pauses (checkpointed) before the `human_review` node. **Apply Approved Transformations** writes the reviewed state back into that checkpoint and resumes the graph into `transform_export`. If no resumable checkpoint exists (for example after an app restart), the UI calls the same Agent 4 node directly.

### Four Agents (Non-negotiable)

| Agent | Role | Key Tech |
|-------|------|----------|
| 1 | Sheet Discovery & Intelligence | openpyxl, pandas, heuristic scoring |
| 2 | Schema Mapping (cascade) | RapidFuzz, sentence-transformers, ChromaDB, LLM |
| 3 | Data Quality & Reasoning | Deterministic rules + LLM explanation |
| 4 | Controlled Transformation | Whitelist registry, Pandera + type validation |

### Exact 17-Field Output Schema

| Field | Type |
|-------|------|
| Reference | String |
| Address | String |
| City | String |
| State | String |
| Zip | Integer (exported with Excel format `00000`, so 802 displays as 00802) |
| County | String |
| Country | String |
| Building Value | Float |
| Contents | Float |
| BI | Float |
| Occupancy | String |
| Construction | String |
| Storeys | Integer |
| Number of Buildings | Integer |
| Year Built | Integer |
| Fire Sprinklers (Y/N) | String |
| Other | Float |

### Multi-sheet workbooks

Every sheet that Agent 1 classifies as **Primary** is an independent data sheet. The pipeline preserves strict sheet isolation throughout the entire workflow:
- **Sheet Discovery (Agent 1):** Scans and classifies all tabs, identifying every PRIMARY sheet and isolating its distinct header row.
- **Isolated Per-Sheet Mapping & Quality (Agents 2 & 3):** Rather than concatenating tabs into a single DataFrame, each PRIMARY sheet is evaluated in its own context. Schema mappings, value-profile vetoes, and data quality checks run independently per sheet, preventing cross-sheet header collisions and data contamination.
- **Review & Approval Gate (HITL):** The Streamlit UI provides intuitive Sheet Selectors allowing underwriters to inspect recommendations, data quality metrics, and unclaimed columns either per-sheet or across all sheets.
- **Separate Outputs (Agent 4):** Each PRIMARY sheet is transformed and exported as its own validated 17-column Excel deliverable: `Cleaned_SOV_<sheet>.xlsx` accompanied by `Audit_Log_<sheet>.xlsx`. For example, in `SOV_Q8B3.xlsx`, the system produces:
  - `Cleaned_SOV_23-24_Values.xlsx` (834 rows) + `Audit_Log_23-24_Values.xlsx`
  - `Cleaned_SOV_Deleted_Locations.xlsx` (69 rows) + `Audit_Log_Deleted_Locations.xlsx`
  - `Cleaned_SOV_Insured_Elsewhere.xlsx` (87 rows) + `Audit_Log_Insured_Elsewhere.xlsx`
- **Single-Deliverable Compatibility:** For backward compatibility with automated evaluation harnesses and single-file workflows, `Cleaned_SOV.xlsx` and `Audit_Log.xlsx` are also exported matching the selected primary sheet deliverable (never a concatenated or corrupted dataset).


---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Orchestration | LangGraph 1.2 (StateGraph + HITL interrupt) |
| State | Pydantic v2 `SOVState` |
| LLM | Provider set by `LLM_PROVIDER` (`ollama`, `groq` or `gemini`), with fallback to the other configured providers |
| Embeddings | sentence-transformers `bge-small-en-v1.5` |
| Vector memory | ChromaDB (persistent) |
| Fuzzy matching | RapidFuzz |
| Data | pandas + openpyxl |
| Validation | Pandera + numeric type-conformance checks |
| UI | Streamlit |
| Checkpointing | SQLite (`langgraph-checkpoint-sqlite`), in-memory fallback |
| Testing | pytest |

---

## Installation

```bash
# 1. Clone / enter the repo
cd d:\Adrosonic

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and configure environment
copy .env.template .env
# Edit .env to choose LLM_PROVIDER and add the matching API key (or configure Ollama)
```

---

## Environment Variables

| Variable | Default in code | Description |
|----------|-----------------|-------------|
| `LLM_PROVIDER` | `ollama` (`.env.template` sets `groq`) | `ollama`, `groq` or `gemini`; `none` / `off` switches the LLM off (deterministic-only mode, even if API keys are set) |
| `GROQ_API_KEY` | *(empty)* | Groq API key |
| `GROQ_MODEL` | `openai/gpt-oss-20b` | Groq model (other Groq models are tried if it fails) |
| `GEMINI_API_KEY` | *(empty)* | Gemini API key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint. Ollama is used only when `LLM_PROVIDER=ollama` or this variable is set explicitly |
| `OLLAMA_MODEL` | `mistral` | Ollama model |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | HuggingFace embedding model |
| `CHROMA_PERSIST_DIR` | `./chroma_db` | Mapping memory store |
| `CHROMA_COLLECTION` | `sov_mappings` | Mapping memory collection |
| `CHECKPOINT_DB` | `./checkpoints.sqlite` | LangGraph checkpoint database |
| `OUTPUT_DIR` | `./outputs` | Exported files |
| `UPLOAD_DIR` | `./uploads` | Uploaded files |
| `HIGH_CONFIDENCE_THRESHOLD` | `0.90` | Below this, a recommendation requires individual review |
| `FUZZY_THRESHOLD` | `0.75` | RapidFuzz score threshold |
| `SEMANTIC_THRESHOLD` | `0.70` | Semantic similarity threshold (was 0.60; at 0.60 unrelated headers such as `SW` or `Dept` matched fields) |
| `MAX_REREASON_ATTEMPTS` | `2` | A rejection with a note triggers re-reasoning (alternative or escalation) while the recommendation's rejection count is below this value; after that the rejection simply stands |
| `LLM_SAMPLE_ROWS` | `5` | Masked sample values sent to the LLM per column |

---

## LLM Setup

### Option A: Groq (cloud)

1. Get an API key at [console.groq.com](https://console.groq.com)
2. Set `LLM_PROVIDER=groq` and `GROQ_API_KEY=your_key` in `.env`

### Option B: Ollama (fully local)

```bash
# Install Ollama from https://ollama.ai
ollama pull mistral

# Set in .env:
# LLM_PROVIDER=ollama
# OLLAMA_BASE_URL=http://localhost:11434
# OLLAMA_MODEL=mistral
```

### Provider fallback

The provider in `LLM_PROVIDER` is tried first, then the others that are configured: Groq and Gemini need an API key, and Ollama needs to be the chosen provider or have `OLLAMA_BASE_URL` set explicitly. For a fully local setup, use `LLM_PROVIDER=ollama` and leave `GROQ_API_KEY` and `GEMINI_API_KEY` empty; otherwise a failed Ollama call falls back to the cloud provider.

> The system works in **deterministic-only mode** if no LLM is available, or when `LLM_PROVIDER=none`.
> LLM features (enriched explanations, ambiguous mapping resolution) are skipped gracefully.

---

## Run the Application

```bash
# Start the Streamlit UI
streamlit run app/ui/streamlit_app.py

# The app opens at: http://localhost:8501
```

---

## Run Tests

```bash
# Full test suite (92 tests)
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ -v --cov=app --cov-report=html

# Specific test class
python -m pytest tests/test_sov_system.py::TestSchemaValidation -v
```

`tests/conftest.py` points ChromaDB, outputs, uploads and checkpoints at a temporary directory, so test runs never write "approved" mappings into the real `chroma_db/`.

---

## Run Benchmark

```bash
python benchmark.py
```

Outputs per-sample and aggregate scores (on the synthetic samples in `data/samples/`; labels are defined in `benchmark.py`) for:
- Mapping Accuracy (target: ≥74%)
- Anomaly Recall (target: ≥90%)
- Transformation Correctness (target: ≥95%)
- Explainability Coverage (target: 100%)
- Audit Completeness (target: 100%)

The report is written to `outputs/benchmark_report.json`.

---

## Demo Flow (10-minute walkthrough)

1. **Upload** `data/samples/sample2_messy.xlsx` in the Upload tab
2. Click **Run Pipeline**
3. **Sheet Discovery**: sheet rankings, detected header row, merged-cell info, merged data sheets
4. **Schema Mapping**: column mappings with confidence scores
5. **Quality Report**: issues such as currency symbols, a negative value, a duplicate reference
6. **Human Review**:
   - Click **Approve All High-Confidence** for recommendations at ≥90% confidence
   - Approve each remaining review-required recommendation individually (bulk "Approve All Remaining" covers only items that do not require review)
   - Reject `strip_currency` with note: *"These are already clean floats"*
   - Agent 3 re-reasons with that feedback (the fix is withdrawn and the card says why); the other decisions are kept
   - Reject a column mapping with a note: Agent 3 proposes an alternative target or escalates the item to a human (**Assign Target**)
7. Click **Apply Approved Transformations**
   - If any source columns were not mapped, scroll down in the Review tab to **Unclaimed Source Columns**
   - Assign each to a target field (values are space-merged if multiple columns share a target) or click **Reject** to drop the column from the output
8. **Final Output** tab: schema conformance panel (17 headers in order, types per field, 0 merged cells), cleaned rows, audit trail; download `Cleaned_SOV.xlsx` and `Audit_Log.xlsx`
9. Verify schema: exactly 17 columns in exact order

The full 10-minute evaluator demo (two real files, commands and script) is in [`DEMO.md`](DEMO.md).

---

## Project Structure

```
d:\Adrosonic\
├── app/
│   ├── agents/
│   │   ├── sheet_discovery.py     # Agent 1
│   │   ├── schema_mapping.py      # Agent 2
│   │   ├── quality_reasoning.py   # Agent 3
│   │   └── transformation.py      # Agent 4
│   ├── orchestration/
│   │   ├── graph.py               # LangGraph StateGraph (run / pause / resume)
│   │   └── state.py               # State initialization
│   ├── services/
│   │   ├── llm/gateway.py         # LLM gateway (Ollama / Groq / Gemini)
│   │   ├── llm/masking.py         # Value masking for LLM prompts
│   │   ├── embeddings/encoder.py  # Sentence-transformer embeddings
│   │   ├── memory/chroma_store.py # ChromaDB vector memory
│   │   └── scoring/quality_score.py  # The single quality-score formula
│   ├── schemas/
│   │   ├── state_models.py        # Pydantic SOVState + all models
│   │   ├── target_schema.py       # 17-field schema definitions + synonyms
│   │   └── recommendations.py     # LLM output schemas
│   ├── processing/
│   │   ├── workbook.py            # Excel/CSV loading, unmerging, multi-sheet merge
│   │   ├── profiling.py           # Value profiling
│   │   ├── transformations.py     # Whitelisted transformation registry
│   │   └── validation.py          # Pandera + type validation
│   ├── audit/logger.py            # Audit trail generation
│   ├── ui/streamlit_app.py        # Streamlit HITL interface
│   └── config.py                  # Environment config
├── tests/
│   ├── conftest.py                # Isolates persistent stores during tests
│   └── test_sov_system.py         # pytest suite (92 tests)
├── data/
│   └── samples/                   # Synthetic test SOV files
├── benchmark.py                   # Scoring harness (labels inline)
├── requirements.txt
├── .env.template
└── progress.md
```

---

## Security Model

- **Data minimisation**: the LLM receives headers, field definitions, counts and **masked** sample values: every digit becomes `9` (`2345 Reagan Street` → `9999 Reagan Street`, `$1,500,000` → `$9,999,999`), e-mail addresses become `<email>`, values are cut to 32 characters. Words are kept because mapping depends on them (`Masonry`, `Warehouse`), so text such as company or street names is still sent.
- **No API keys in code**: all secrets via `.env` (`.gitignore`d)
- **LLM never modifies data**: only deterministic code applies transformations. The LLM may refine explanations and pick a whitelisted operation for data-quality recommendations; it can lower but never raise a confidence, and cannot attach operations to column mappings.
- **Uploads persist**: uploaded files are stored in `UPLOAD_DIR` as `<session_id>.<ext>` and are not deleted automatically (Agent 4 re-reads them after review). Clear the folder according to your retention policy.
- **Whitelist-only transformations**: the LLM cannot inject arbitrary code

---

## Verified on Real SOVs

The four broker files `SOV_B4ID.xlsx`, `SOV_H6D2.xlsx`, `SOV_K4T9.xlsx` and `SOV_Q8B3.xlsx` were run end to end (LLM off, empty memory):

| File | Data sheets | Output rows | Hand-labelled columns mapped correctly |
|------|-------------|-------------|----------------------------------------|
| SOV_B4ID | SOV | 15 | 15 / 15 |
| SOV_H6D2 | SOV | 19 | 15 / 15 |
| SOV_K4T9 | Locations | 34 | 12 / 12 |
| SOV_Q8B3 | 23-24 Values (834), Deleted Locations (69), Insured Elsewhere (87) | 834, 69, 87 (separate exports) | 13 / 13 |

With every recommendation approved, validation still reports real problems in the source data instead of passing silently: `Storeys` 1.5 in B4ID (fractions are not truncated) and `Contents` "Included in Bldg" in Q8B3.

---

## Design Constraints (Non-Negotiable)

1. Four distinct agents
2. Shared typed Pydantic `SOVState`
3. LLM never directly edits data
4. Deterministic code performs transformations
5. Human approval required before Agent 4
6. Missing data is never fabricated (merged banners/footnotes are not copied into data cells; fractional integers are not truncated)
7. Exactly 17 target columns
8. Exact field names and ordering
9. Full audit trail
10. Low-confidence recommendations require individual review
11. Rejection feedback triggers re-reasoning: an alternative is proposed, or the item is escalated to a human (bounded by `MAX_REREASON_ATTEMPTS`)
12. No hardcoded API keys
13. Malformed files fail gracefully
14. Export locked until review complete
15. Unclaimed source columns are surfaced in the Review tab: each can be manually assigned to a target field (space-merged if shared) or rejected (dropped before export)
16. Review tab features 1-click column rejection (dropped from output), Change Target with persistent ChromaDB human feedback, and real-time Mapping Accuracy KPI
