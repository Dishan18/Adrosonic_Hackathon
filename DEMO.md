# Live Demo Guide: Agentic SOV Intelligence System

Team **Cache Me If You Can** · Adrosonic Build · Problem Statement 3

A 10-minute walkthrough covering the 7 demo stages of the challenge brief (section 11), using two of the provided test SOVs:

| Part | File | Why this file | Stages |
|------|------|---------------|--------|
| A (≈2 min) | `SOV_K4T9.xlsx` | 7-sheet workbook, header on row 6, a **semantic** match (`Location Name → City`) | 1, 2 |
| B (≈8 min) | `SOV_Q8B3.xlsx` | 8 sheets (3 hidden), 3 location sheets merged, all three recommendation types | 1, 3, 4, 5, 6, 7 |

Every value under "You should see" was recorded in a rehearsal on 2026-10-03 in **deterministic mode** with a **fresh memory store**. With an LLM switched on, rationale texts get richer and a few confidences can be lower, so counts may shift slightly.

---

## 1. One-time setup

```powershell
cd D:\Adrosonic
pip install -r requirements.txt
copy .env.template .env        # skip if .env already exists
```

Optional, only to show LLM explanations (adds latency, not needed for any stage):

```powershell
ollama serve                   # separate terminal
ollama pull mistral
```

## 2. Pre-flight check (5 minutes before)

```powershell
python -m pytest tests/ -q     # expect: 92 passed
python benchmark.py            # expect: Overall: ALL TARGETS MET
```

Close `outputs\Cleaned_SOV.xlsx` and `outputs\Audit_Log.xlsx` if they are open in Excel (the app overwrites them).

## 3. Start the app for the demo

Run in one PowerShell window. The demo memory folder is separate from `chroma_db\`, so rehearsals never change the live run; the `Remove-Item` line clears **only** that demo folder.

```powershell
cd D:\Adrosonic
$env:LLM_PROVIDER = "none"                 # deterministic mode, predictable timing
$env:CHROMA_PERSIST_DIR = ".\chroma_demo"  # fresh mapping memory for the demo
Remove-Item -Recurse -Force .\chroma_demo -ErrorAction SilentlyContinue
python -m streamlit run app/ui/streamlit_app.py
```

The browser opens at <http://localhost:8501>. The sidebar should read **LLM GATEWAY · DETERMINISTIC MODE**.
To demo with the LLM instead, leave out the `LLM_PROVIDER` line (uses `.env`, Ollama by default).

Warm-up: upload any file and click **Run Pipeline** once before the evaluators join (the first run loads the embedding model, about 10–15 s). Then click **Reset Session** in the sidebar.

---

## 4. Run sheet (10 minutes)

### Part A: `SOV_K4T9.xlsx` (stages 1–2)

| Time | Stage | Do | You should see | Say (short script) |
|------|-------|----|----------------|--------------------|
| 0:00 | 1 | Drag `SOV_K4T9.xlsx` into the uploader → **Run Pipeline** | Animated card: "Agents Working on Your Data" with pulsing stage pills, finishes in ~5 s (warm) | "A real broker workbook: 7 tabs, a cover summary, a glossary, disclaimers, and the data starts on row 6." |
| 0:30 | 1 | Tab **Sheet Detection** | Primary sheet `Locations`, **Header Row 5 (0-indexed = Excel row 6)**, confidence 75.6%. Glossary, Original from Client A, Summary, YOY Comparison → Secondary; Confidentiality, Vendor Disclaimers → Reject | "Agent 1 scores every sheet on header vocabulary, density, type consistency and volume, picks the data sheet and finds the header row on its own." |
| 1:00 | 2 | Tab **Schema Mapping** | 11 / 18 mapped, average 86.6%. Row `Location Name → City`, **83.6%, method semantic**, review required | "Agent 2 runs a cascade: memory, exact synonyms, fuzzy, then embeddings. 'Location Name' shares no words with 'City'; the embedding model matched it, and the values (Mangualde, Sines…) agree." |
| 1:30 | 2 | Expand **Mapping JSON output** | Caption "Semantic (embedding) matches: Location Name, TIV". Entry 4: `"source_column": "Location Name", "target": "City", "confidence": 0.8359, "method": "semantic"` | "This is the machine-readable mapping, with confidence, method and evidence for every column; it downloads as `Schema_Mapping.json`." |

Optional (only if asked): the synthetic sample `data/samples/sample1_standard.xlsx` maps `Const Type → Construction` and `Other Insured Value → Other` semantically; `Bldg Repl Cost → Building Value` is a learned synonym there (exact tier).

### Part B: `SOV_Q8B3.xlsx` (stages 1, 3–7)

| Time | Stage | Do | You should see | Say (short script) |
|------|-------|----|----------------|--------------------|
| 2:00 | 1 | Remove K4T9 (✕) → drag `SOV_Q8B3.xlsx` → **Run Pipeline** | Finishes in about 10 s (990 rows) | "A harder file: 8 tabs, three of them hidden, and the locations are split across three tabs." |
| 2:20 | 1 | Tab **Sheet Detection** | Caption "3 data sheets merged into one output: 23-24 Values, Deleted Locations, Insured Elsewhere". Header row 0. Trailer, All Autos, Equipment (vehicle and equipment lists) → Secondary; Questions → Reject | "All three location tabs are merged into one 17-column output. The vehicle and equipment tabs are recognised as not-SOV." |
| 2:50 | 3 | Tab **Data Quality** | Score 44.7 / 100 (grade D), **15 issues**, 5 critical. **Per-field completeness** bars (e.g. Reference 44.55%, Address 99.19%, City 0% "No source column"). Issue table with types: completeness, type_error (Contents "Included in Bldg"), logical_error (Year Built "1989 / 2012"), format (sprinkler codes "Yes"), duplicate (Reference) | "Agent 3's checks are deterministic, so recall is measurable: completeness per field, type errors, logical violations, formats and duplicates." |
| 3:40 | 4 | Tab **Review** → expand groups | 30 recommendations. **Column mapping** `Map column 'Loc #' → 'Reference'` (83%). **Data correction** `Standardize construction year in 'Year Built'`: `1989 / 2012 → 1989`. **Standardisation** `Standardize sprinkler indicators in 'Fire Sprinklers (Y/N)'`: `Yes → Y` (95%) | "Every item has a plain-English why, an impact and a before/after. Nothing is applied yet." |
| 4:40 | 5 | On the sprinkler card click **Approve** | Card turns *Approved* | "Accepting one recommendation." |
| 5:00 | 5 | Card `Map column 'TOTAL' → 'Number of Buildings'` (60%) → **Reject** → type *"TOTAL is the total insured value, not a building count"* → **Confirm Reject** | Badge **ESCALATED**; note "Re-reasoned with reviewer feedback …: no alternative target fits this column. Escalated to a human reviewer…"; button **Assign Target** | "The agent re-reasons on the rejected item with my feedback. It looks for another target; none fits, so it escalates to a human instead of guessing. I could assign a target here; I'll leave the column out." |
| 6:00 | 5 | **Approve All High-Confidence (21 items ≥90%)** | Remaining review-required items stay pending | "Bulk approval only covers items at 90% or more; low-confidence items need a person." |
| 6:20 | 5 | Approve the 6 remaining cards one by one: `Loc #`, `Building`, `2023 Building Value`, `2023 Contents Value`, `Building Value`, `Contents Value` | Banner "All required decisions complete. Ready for transformation." | "Building Value and 2023 Building Value come from different tabs, so both may feed Building Value." |
| 6:40 | 5 | Scroll down: **Unclaimed Source Columns** expander | Shows unmapped source columns with sample values and **Assign / Reject** controls | "Any column left unmapped can be manually assigned to any of the 17 fields—merging with spaces if shared—or rejected to drop it cleanly." |
| 7:00 | 6 | **Apply Approved Transformations** | Opens **Final Output** after about 5 s | "Agent 4 applies only approved, whitelisted operations; the LLM never touches data." |
| 7:15 | 6 | Scroll: **Cleaned output** and **Audit Trail** (≈13 entries) | Audit rows such as `#Floor → Storeys column_rename` and `Year Built to_year_int · 1990 (sample; 374 rows changed)` | "Every rename and every operation is logged with before/after, confidence and who approved it." |
| 8:00 | 7 | Top of Final Output: pills and **Schema conformance** table | **17 ✓** columns, exact names & order · **0 ✓** merged cell ranges · 990 data rows · type check per field (Zip int OK, Building Value float OK, Contents "1 non-numeric") | "Exactly 17 fields, in order, typed, no merged cells." |
| 8:30 | 7 | Banner **Validation Warning: Contents: 1 non-numeric value, 'Included in Bldg'** | | "This is deliberate honesty: one cell says 'Included in Bldg'. We never invent a number, and we don't hide the problem." |
| 8:45 | 7 | **Download Cleaned_SOV.xlsx**, open it in Excel | Headers row 1, Zip shows `75219`; no merged cells | "Here is the deliverable, named exactly as required, with Audit_Log.xlsx next to it." |
| 9:30 | — | Wrap-up | | "AI proposes, code verifies, humans approve, everything is audited." |

---

## 5. Verify the deliverables from the command line (optional)

```powershell
python -c "import openpyxl; ws=openpyxl.load_workbook(r'outputs\Cleaned_SOV.xlsx')['Cleaned_SOV']; print([c.value for c in ws[1]]); print('merged cells:', len(ws.merged_cells.ranges), '| rows:', ws.max_row-1)"
```

Expected after Part B: the 17 headers in order, `merged cells: 0 | rows: 990`.

## 6. If something goes wrong

| Symptom | Fix |
|---------|-----|
| First run is slow | The embedding model is loading; do the warm-up run (section 3). |
| Numbers differ from this sheet | Memory from an earlier run: stop the app, rerun the commands in section 3 (they clear `chroma_demo`). |
| Sidebar shows an LLM provider instead of Deterministic Mode | `$env:LLM_PROVIDER = "none"` was not set in the window that started Streamlit. |
| "Could not write Cleaned_SOV.xlsx" in the log | The previous file is open in Excel. The timestamped copy `outputs\Cleaned_SOV_<session>_<time>.xlsx` is still written; close Excel and rerun Apply. |
| Browser lost the session | Click **Reset Session**, upload again; a run takes about 10 s. |

## 7. Quick answers for evaluator questions

| Question | Answer |
|----------|--------|
| C-01 auto-transformation? | Nothing changes until a person approves; review-required items cannot be bulk-approved; export is locked until every required decision is made. |
| C-02 hallucinated data? | Missing fields stay blank; merged banners/footnotes are never copied into data; fractions (1.5 storeys) are not truncated; non-numeric money is flagged, not invented. |
| C-03 schema? | Exactly 17 fields in order, enforced and validated (Pandera + type check), 0 merged cells. |
| C-04 four agents? | Discovery, Mapping, Quality & Reasoning, Transformation: separate LangGraph nodes sharing one typed `SOVState`, paused (checkpointed) before human review. |
| C-05 explanations? | Every mapping and recommendation carries a rationale string, shown on its card and in the JSON. |
| C-06 all samples? | All four broker files and the three synthetic samples run end to end without crashing (verified by hand; 92 automated tests cover the same code paths). |
| C-07 file names? | `outputs/Cleaned_SOV.xlsx` and `outputs/Audit_Log.xlsx`, plus timestamped history copies. |
| Mapping accuracy? | 55 / 55 hand-labelled columns on the 4 real files; 100% on the synthetic benchmark (target ≥ 74%, baseline 53%). |
| Anomaly recall? | 100% on the benchmark's planted anomalies (target ≥ 90%). |
| Speed? | 15–22 s per real file end to end from a cold start (target < 60 s); about 5–10 s once warm. |
| Data privacy? | Runs fully local with Ollama; LLM prompts get masked values only (digits → 9, e-mails removed); keys only in `.env`. |
| Innovation? | Vector memory of approved mappings, live workflow stepper, xlsx + csv input, iterative re-reasoning with escalation. |
