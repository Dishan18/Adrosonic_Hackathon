# High-Level Design (HLD)
## Agentic Statement of Values (SOV) Intelligence & Cleansing System

**Document Version:** 1.3.0 (updated 2026-10-04; adds 1-click reject drop, Change Target ChromaDB feedback, and Mapping Accuracy KPI)  
**Target Environment:** Local workstation or private cloud (Streamlit, LangGraph, Ollama/Groq/Gemini, ChromaDB)  
**System Classification:** Commercial insurance data transformation engine with human-in-the-loop control  

---

## 1. Executive Summary & Problem Context

In commercial property insurance underwriting, a **Statement of Values (SOV)** is the foundational spreadsheet submitted by insurance brokers detailing physical assets, geocodes, construction attributes, and monetary exposures (Building Value, Contents, Business Interruption). 

### The Industry Challenge
- **Severe Inconsistency:** Broker spreadsheets arrive in unpredictable Excel layouts, featuring multi-row merged headers, title banners, unstructured notes, mixed formatting, currency strings (`$1,250,000`), ZIP codes that lost their leading zeros, non-standard state representations, conflicting column names, and locations split across several tabs.
- **Underwriter Bottleneck:** Risk engineers and underwriting assistants spend hours manually reformatting, sanitizing, and mapping incoming SOVs into the carrier's canonical exposure schema.
- **The Generative AI Dilemma:** Traditional LLM "black-box" approaches can hallucinate numbers, drop rows, or invent values, which leads to mispriced risk.

### The Solution: Agentic SOV Intelligence System
This system runs **four specialized agents** under a LangGraph state machine (Agent 4 includes the validation and export step). It guarantees:
1. **No Data Fabrication:** LLMs reason, suggest, and explain; only whitelisted, deterministic Python routines ever change cell data. Merged banners and footnotes are never copied into data cells.
2. **Schema Compliance:** Output always contains the exact 17 canonical fields in order (Pandera), and numeric fields are checked for type conformance; non-conformant values are reported, not hidden.
3. **Human-in-the-Loop (HITL) Governance:** Every recommendation carries a confidence score and rationale; anything below 90% must be decided individually by a reviewer before export.
4. **Episodic Vector Memory:** Human-approved mappings persist in ChromaDB and are reused for future files, subject to the same value checks as any other match.

---

## 2. Architectural Principles & Guardrails

```
┌────────────────────────────────────────────────────────────────────────┐
│                        CORE ARCHITECTURAL PILLARS                      │
├──────────────────┬──────────────────┬─────────────────┬────────────────┤
│ 1. Deterministic │ 2. Human-in-the- │ 3. Dual-Brain   │ 4. Verifiable  │
│    Execution     │    Loop (HITL)   │    Intelligence │    Auditability│
│ All data changes │ ≥90% confidence: │ Names AND values│ Every applied  │
│ use whitelisted  │ one-click bulk   │ must agree;     │ operation and  │
│ pure functions;  │ approval; <90%:  │ LLM reserved    │ rename logged  │
│ no LLM synthesis │ individual review│ for ambiguity   │ to Audit_Log   │
└──────────────────┴──────────────────┴─────────────────┴────────────────┘
```

1. **Deterministic Execution Sandbox:** The LLM never modifies spreadsheet rows or generates values. It explains issues, resolves genuinely ambiguous column mappings, and may only choose operations from a static whitelist.
2. **Confidence-Gated Autonomy:** Every recommendation is scored between `0.0` and `1.0`. **Approve All High-Confidence** approves pending items at or above $\tau_{high} = 0.90$ (`HIGH_CONFIDENCE_THRESHOLD`). The fallback **Approve All Remaining** button covers only items that do not require review; review-required items are always decided one by one.
3. **Dual-Brain Hybrid Resolution:** Deterministic stages (approved memory → normalized exact synonym → RapidFuzz + BGE semantic candidates) resolve most mappings. Every candidate is cross-checked against the column's actual values, and a candidate the values contradict is vetoed. The LLM Gateway (Ollama, Groq or Gemini) is called only for columns that remain unresolved.
4. **Strict Output Invariance:** Irrespective of the input layout (single-sheet, multi-tab, merged headers), every exported sheet contains exactly 17 ordered columns. When a workbook has multiple PRIMARY data sheets, each sheet is processed with strict isolation and exported as an independent deliverable (`Cleaned_SOV_<sheet>.xlsx` + `Audit_Log_<sheet>.xlsx`), with `Cleaned_SOV.xlsx` preserved as an explicit primary deliverable alias.

---

## 3. High-Level Component & System Topology

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                 PRESENTATION TIER                                       │
│    Streamlit UI (sheet selector, review cards, bulk approval, before/after, downloads)  │
└───────────────────────────────────────────┬─────────────────────────────────────────────┘
                                            │ Excel / CSV upload
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                  LANGGRAPH ORCHESTRATION ENGINE (SQLite checkpoints)                    │
│                                                                                         │
│  [ Agent 1: Discovery ]   ──►  [ Agent 2: Schema Mapping ] ──► [ Agent 3: Quality ]     │
│   - Unmerge (fill down)         - Memory (ChromaDB)             - Completeness index    │
│   - Header row detection        - Normalized exact match        - Anomaly detection     │
│   - Sheet scoring/ranking       - RapidFuzz + BGE candidates    - Whitelist suggestions │
│   - Primary sheet isolation     - Value-profile veto            - Masked LLM reasoning  │
│                                 - Per-sheet 1:1 mapping         │                       │
│                                 - LLM fallback                  │                       │
└───────────────────────────────────────────┬─────────────────────────────────────────────┘
                                            │ interrupt_before = human_review
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                         HUMAN-IN-THE-LOOP APPROVAL GATE                                 │
│  Sheet Filter: inspect cards and unclaimed columns per sheet or across all sheets       │
│  Approve / 1-Click Reject (drops column) / Change Target (ChromaDB feedback); KPI Card  │
│  Unclaimed Columns: manually assign to any target field (space-merged) or reject (drop) │
└───────────────────────────────────────────┬─────────────────────────────────────────────┘
                                            │ reviewed state written to checkpoint, resume
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                     AGENT 4: CONTROLLED TRANSFORMATION & EXPORT                         │
│   - Approved renames only; rejected columns explicitly dropped and audited              │
│   - Whitelist-only series operations, audited before write-back                         │
│   - 17-column enforcement, Pandera + numeric type-conformance validation                │
│   - Cleaned_SOV_<sheet>.xlsx & Audit_Log_<sheet>.xlsx (and Cleaned_SOV.xlsx alias)      │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### External Services & Backing Stores
- **LLM Gateway:** One client for `ollama` (default model `mistral`), `groq` (default `openai/gpt-oss-20b`, other Groq models tried on failure) and `gemini` (default `gemini-2.5-flash`). The provider in `LLM_PROVIDER` is tried first, then the other configured providers: Groq/Gemini need an API key; Ollama must be the chosen provider or have `OLLAMA_BASE_URL` set explicitly. If none answers, the pipeline continues deterministically.
- **Dense Embedding Model:** Singleton `sentence-transformers` model `BAAI/bge-small-en-v1.5` (384 dimensions). Corpus embeddings are computed once per process; per-header candidate lists are cached.
- **Episodic Vector Store:** Local persistent `chromadb` collection `sov_mappings` holding human-approved mappings. Chroma embeds these documents with its own default embedding function (independent of the BGE model above).
- **Checkpoint Store:** `langgraph-checkpoint-sqlite` (`CHECKPOINT_DB`); an in-memory checkpointer is used if SQLite is unavailable, because the HITL interrupt requires one.

---

## 4. End-to-End Pipeline & Stage Descriptions

```
Raw Workbook (.xlsx / .csv)
  │
  ├─► [Agent 1. Sheet Intelligence]
  │     Parses every worksheet once (cached per file + modification time).
  │     Merged ranges: the top-left value is filled DOWN the first column only;
  │     horizontal banners and footnotes are not copied across columns.
  │     Scores the first 30 rows per sheet for the header row; scores each sheet
  │     (header match, density, type consistency, volume) → PRIMARY / SECONDARY / REJECT.
  │     All PRIMARY sheets become independent data sheets (best-scoring is primary_sheet_name).
  │
  ├─► [Agent 2. Schema Mapping]
  │     Evaluates each PRIMARY sheet in its own isolated context (columns matched against sheet header).
  │     For each raw column:
  │       Stage 0: ChromaDB memory (human-approved mappings)
  │       Stage 1: normalized exact synonym lookup
  │       Stage 2+3: RapidFuzz and BGE candidates (top 5 targets each), scored jointly
  │       Stage 4: LLM, only for columns still unresolved
  │     Every candidate is scored 0.45·name + 0.35·value-fit + 0.20·agreement;
  │     candidates whose values contradict the field (fit < 0.25) are vetoed.
  │     Targets are claimed strongest-column-first and are unique per sheet.
  │
  ├─► [Agent 3. Quality Reasoning]
  │     Runs 12 deterministic checks on each mapped sheet view: completeness, currency
  │     symbols, negative amounts, non-numeric amounts, Year Built range, Storeys,
  │     building counts, sprinkler codes, state codes, duplicate references,
  │     ZIP format, non-integer integer fields.
  │     Computes the 0–100 Quality Score (one formula, shared with the UI) and maps each
  │     issue to a whitelisted operation. The LLM enriches explanations from counts and
  │     masked examples only.
  │
  ├─► [Human-in-the-Loop Review Gate]  (graph paused before human_review)
  │     Review cards: before → after example, confidence, rationale, and sheet identifier.
  │     Reviewer can filter by sheet or view all recommendations at once.
  │     A rejection with a note re-runs Agent 3 with that feedback: a rejected
  │     mapping gets the next-best target from the mapping cascade or is
  │     ESCALATED to a human (who can assign a target); a rejected fix is
  │     withdrawn with an explanation. Every other decision and ID is preserved.
  │
  └─► [Agent 4. Controlled Transformation, Validation & Export]
        Applies only APPROVED recommendations per sheet: column renames first, then whitelisted
        operations (`strip_currency`, `to_float`, `to_int`, `to_str`, `to_year_int`,
        `to_zip`, `state_to_abbrev`, `normalize_sprinkler_code`, `trim_whitespace`,
        `normalize_spaces`, `normalize_date`; `flag_for_review` changes nothing).
        Writes one audit entry per rename and per applied operation (sample before/after
        and the number of rows changed).
        After approved recommendations: applies unclaimed-column decisions per sheet — rejected columns
        are dropped; manually assigned columns are renamed or space-merged into their target
        (NaN-safe, grouping ensures consistent merge even when two sources share a target).
        Enforces the 17-column order, validates (Pandera + numeric types) and writes
        Cleaned_SOV_<sheet>.xlsx and Audit_Log_<sheet>.xlsx for each PRIMARY sheet,
        along with Cleaned_SOV.xlsx and Audit_Log.xlsx (exact names, plus timestamped copies).
        Re-opens each file to confirm 0 merged cells. A failed validation is shown to the reviewer;
        the files are still written so the problems can be inspected.
```

---

## 5. The Canonical 17-Field SOV Target Schema

Every processed workbook is aligned strictly to these 17 fields (synonyms are a selection from `TARGET_SYNONYMS` in `app/schemas/target_schema.py`):

| # | Field Name | Expected Type | Core Domain Description | Example Broker Synonyms |
|---|------------|---------------|-------------------------|--------------------------|
| 1 | `Reference` | String | Unique location identifier | Loc #, Location ID, Item #, Site ID |
| 2 | `Address` | String | Street address of the insured property | Street, Street Address, Property Address |
| 3 | `City` | String | City where the property is located | City Name, Town, Municipality |
| 4 | `State` | String (2-letter) | US state / territory abbreviation | ST, State Code, Province |
| 5 | `Zip` | Integer | 5-digit US ZIP (exported with format `00000`) | Zip Code, Postal Code, Zip+4 |
| 6 | `County` | String | County where the property is located | Parish, Borough, District |
| 7 | `Country` | String | Country | Country Name, Country Code, Nation |
| 8 | `Building Value` | Float | Replacement cost of the building | Building, Building Values, Bldg Value, Building RCV |
| 9 | `Contents` | Float | Value of contents | Contents Value, BPP, Business Personal Property |
| 10 | `BI` | Float | Business Interruption value | Business Interruption, Time Element, Extra Expense |
| 11 | `Occupancy` | String | Occupancy class or use | Occ, Occupancy Class, Building Use |
| 12 | `Construction` | String | Construction type / class | Construction Type, ISO Construction |
| 13 | `Storeys` | Integer | Number of floors | Stories, # of Stories, Floors |
| 14 | `Number of Buildings` | Integer | Buildings at the location | # of Buildings, No of Bldgs, Num Bldgs |
| 15 | `Year Built` | Integer (YYYY) | Year of original construction | Yr Built, Year Constructed |
| 16 | `Fire Sprinklers (Y/N)` | String Code | Sprinkler presence (Y, N, Y13, Y(13R)) | Sprinklered, % Sprinklered, Sprinkler % |
| 17 | `Other` | Float | Other insured value not covered above | Other Value, Other TIV, Miscellaneous |

"Bldg" and "Buildings" are deliberately **not** synonyms: in real files "Bldg #" / "Bldg." is a building number and "Buildings" is often a value column.

---

## 6. Security, Compliance & Data Governance

1. **Local Deployment:** With `LLM_PROVIDER=ollama` and no Groq/Gemini keys set, no policy data leaves the machine at run time (the embedding models are downloaded once on first use).
2. **Data Minimisation:** LLM prompts contain headers, field definitions, counts and masked values: digits replaced by `9`, e-mail addresses replaced, values truncated to 32 characters. Words are kept, so names in text cells can still appear.
3. **Auditability & Traceability:** `Audit_Log.xlsx` records, per entry: Entry ID, Source Column, Target Column, Transformation Applied (`column_rename` or the operation), Before Value (sample and rows changed), After Value, Confidence, Approved By, Timestamp (local ISO-8601), Recommendation ID (`MAP-…` for mappings, `REC-…` for data-quality items), Row Index (blank for these per-operation summary entries).
4. **No Training On Policyholder Data:** The memory store is a local ChromaDB instance; nothing is sent to model training.
5. **Retention:** Uploaded files are kept in `UPLOAD_DIR` and outputs in `OUTPUT_DIR`; neither is deleted automatically.

---

## 7. Non-Functional Requirements & Measured Results

Measured on 2026-10-03 on a CPU-only Windows workstation, LLM disabled, empty memory store.

| Metric / Dimension | Design Target | Measured |
|--------------------|---------------|----------|
| **Mapping Accuracy (synthetic benchmark)** | ≥ 74% | 100% (`python benchmark.py`) |
| **Mapping Accuracy (4 real broker SOVs)** | — | 55 / 55 hand-labelled columns |
| **Anomaly Recall (synthetic benchmark)** | ≥ 90% | 100% |
| **Sheet discovery, 8-sheet / 2 MB workbook (SOV_Q8B3)** | — | 6–15 s depending on machine load (60–126 s before the parse cache) |
| **End-to-end pipeline, real SOVs (cold start, LLM off)** | < 60 s | 15–22 s per file (B4ID 16 s, H6D2 17 s, K4T9 15 s, Q8B3 22 s) |
| **Full test suite** | 0 failures | 93 passed in 17–34 s |
| **Failure Recovery** | No unhandled exceptions | Malformed files end in an ERROR stage with a readable message; LLM failures fall back to deterministic results |
| **Schema Strictness** | 17 ordered columns, typed numeric fields | 17 ordered columns always; type problems reported as validation errors |

The first run in a new process also loads the embedding model, which adds several seconds to mapping.
