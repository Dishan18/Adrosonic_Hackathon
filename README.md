# 🏢 Agentic SOV Intelligence System

> **AI proposes. Code verifies. Humans approve. Everything is audited.**

An end-to-end agentic pipeline for cleansing and standardising chaotic Statement of Values (SOV) insurance data into an exact 17-field schema, with full human-in-the-loop control and a comprehensive audit trail.

---

## Architecture

```
Upload SOV File
      │
      ▼
┌─────────────────────────────────────────┐
│  Agent 1: Sheet Intelligence & Discovery│  ← Ranks sheets, finds headers
│  (LangGraph Node: discover_sheets)      │     unmerges cells
└─────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────┐
│  Agent 2: Schema Mapping Agent          │  ← 4-stage cascade:
│  (LangGraph Node: map_schema)           │    Memory→Exact→Fuzzy→Semantic→LLM
└─────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────┐
│  Agent 3: Data Quality & Reasoning      │  ← Deterministic rules + LLM
│  (LangGraph Node: assess_quality)       │    explanation & recommendations
└─────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────┐
│  Human Review (HITL)                    │  ← Approve / Reject / Edit
│  (LangGraph interrupt)                  │    Rejection → re-reasoning loop
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

### Four Agents (Non-negotiable)

| Agent | Role | Key Tech |
|-------|------|----------|
| 1 | Sheet Discovery & Intelligence | openpyxl, pandas, heuristic scoring |
| 2 | Schema Mapping (cascade) | RapidFuzz, sentence-transformers, ChromaDB, LLM |
| 3 | Data Quality & Reasoning | Deterministic rules + LLM explanation |
| 4 | Controlled Transformation | Whitelist registry, Pandera validation |

### Exact 17-Field Output Schema

| Field | Type |
|-------|------|
| Reference | String |
| Address | String |
| City | String |
| State | String |
| Zip | Integer |
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

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Orchestration | LangGraph 1.2 (StateGraph + HITL interrupt) |
| State | Pydantic v2 `SOVState` |
| LLM (primary) | Groq Llama 3.3 70B |
| LLM (fallback) | Ollama (local) |
| Embeddings | sentence-transformers `bge-small-en-v1.5` |
| Vector memory | ChromaDB (persistent) |
| Fuzzy matching | RapidFuzz |
| Data | pandas + openpyxl |
| Validation | Pandera |
| UI | Streamlit |
| Checkpointing | SQLite (via langgraph-checkpoint-sqlite) |
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
# Edit .env to add your GROQ_API_KEY (or configure Ollama)
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `groq` | `groq` or `ollama` |
| `GROQ_API_KEY` | *(empty)* | Your Groq API key |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | `llama3.2` | Ollama model |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | HuggingFace embedding model |
| `HIGH_CONFIDENCE_THRESHOLD` | `0.90` | Threshold for Approve All |
| `FUZZY_THRESHOLD` | `0.75` | RapidFuzz score threshold |
| `SEMANTIC_THRESHOLD` | `0.60` | Semantic similarity threshold |

---

## LLM Setup

### Option A: Groq (Recommended — free tier available)

1. Get a free API key at [console.groq.com](https://console.groq.com)
2. Set `LLM_PROVIDER=groq` and `GROQ_API_KEY=your_key` in `.env`

### Option B: Ollama (fully local)

```bash
# Install Ollama from https://ollama.ai
ollama pull llama3.2

# Set in .env:
# LLM_PROVIDER=ollama
# OLLAMA_BASE_URL=http://localhost:11434
# OLLAMA_MODEL=llama3.2
```

> The system works in **deterministic-only mode** if no LLM is configured.
> LLM features (enriched explanations, ambiguous mapping resolution) will be skipped gracefully.

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
# Full test suite
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ -v --cov=app --cov-report=html

# Specific test class
python -m pytest tests/test_sov_system.py::TestSchemaValidation -v
```

---

## Run Benchmark

```bash
python benchmark.py
```

Outputs per-sample and aggregate scores for:
- Mapping Accuracy (target: ≥74%)
- Anomaly Recall (target: ≥90%)
- Transformation Correctness (target: ≥95%)
- Explainability Coverage (target: 100%)
- Audit Completeness (target: 100%)

---

## Demo Flow (10-minute walkthrough)

1. **Upload** `data/samples/sample2_messy.xlsx` in the Upload tab
2. Click **Run Pipeline**
3. **Sheet Discovery** tab: see sheet rankings, header row at row 5, merged cell info
4. **Schema Mapping** tab: see 17 column mappings with confidence scores
5. **Quality Report** tab: see ≥3 issues (currency symbols, negative value, duplicate reference)
6. **Human Review** tab:
   - Click **Approve All** for high-confidence (≥90%) recommendations
   - Accept one column mapping recommendation manually
   - Reject `strip_currency` with note: *"These are already clean floats"*
   - See Agent 3 re-reason with that feedback
7. Click **Apply Approved Transformations**
8. **Export** tab: download `Cleaned_SOV.xlsx` and `Audit_Log.xlsx`
9. Verify schema: exactly 17 columns in exact order

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
│   │   ├── graph.py               # LangGraph StateGraph
│   │   └── state.py               # State initialization
│   ├── services/
│   │   ├── llm/gateway.py         # LLM gateway (Groq/Ollama)
│   │   ├── embeddings/encoder.py  # Sentence-transformer embeddings
│   │   ├── memory/chroma_store.py # ChromaDB vector memory
│   │   └── scoring/quality_score.py
│   ├── schemas/
│   │   ├── state_models.py        # Pydantic SOVState + all models
│   │   ├── target_schema.py       # 17-field schema definitions
│   │   └── recommendations.py     # LLM output schemas
│   ├── processing/
│   │   ├── workbook.py            # Excel/CSV loading, header detection
│   │   ├── profiling.py           # Value profiling
│   │   ├── transformations.py     # Whitelisted transformation registry
│   │   └── validation.py          # Pandera schema validation
│   ├── audit/logger.py            # Audit trail generation
│   ├── ui/streamlit_app.py        # Streamlit HITL interface
│   └── config.py                  # Environment config
├── tests/
│   └── test_sov_system.py         # Comprehensive pytest suite (75+ tests)
├── data/
│   ├── samples/                   # Test SOV files
│   └── ground_truth/              # Benchmark labels
├── benchmark.py                   # Scoring harness
├── requirements.txt
├── .env.template
└── progress.md
```

---

## Security Model

- **Data minimisation**: LLM receives only headers, definitions, and limited masked samples
- **No API keys in code**: All secrets via `.env` (`.gitignore`d)
- **LLM never modifies data**: Only deterministic code applies transformations
- **Per-session temp storage**: Uploaded files stored in `uploads/` and cleaned after use
- **Whitelist-only transformations**: LLM cannot inject arbitrary code

---

## Design Constraints (Non-Negotiable)

1. ✅ Four distinct agents
2. ✅ Shared typed Pydantic `SOVState`
3. ✅ LLM never directly edits data
4. ✅ Deterministic code performs transformations
5. ✅ Human approval required before Agent 4
6. ✅ Missing data is never fabricated
7. ✅ Exactly 17 target columns
8. ✅ Exact field names and ordering
9. ✅ Full audit trail
10. ✅ Low-confidence recommendations require review
11. ✅ Rejection feedback triggers re-reasoning or escalation
12. ✅ No hardcoded API keys
13. ✅ Malformed files fail gracefully
14. ✅ Export locked until review complete
