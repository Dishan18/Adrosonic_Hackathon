"""
Workbook ingestion utilities.
Handles .xlsx, .csv, multi-sheet workbooks, merged cells, malformed input.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv"}
MAX_HEADER_SEARCH_ROWS = 30


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_workbook_sheets(path: str) -> Dict[str, pd.DataFrame]:
    """
    Load all sheets from an Excel file or a single CSV.
    Returns {sheet_name: DataFrame} with original (unprocessed) data.
    Raises a user-readable ValueError on unsupported/malformed files.
    """
    p = Path(path)
    ext = p.suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. Please upload .xlsx or .csv files."
        )

    if ext == ".csv":
        return _load_csv(path)
    else:
        return _load_excel(path)


def _load_csv(path: str) -> Dict[str, pd.DataFrame]:
    try:
        # Try common encodings
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                df = pd.read_csv(path, encoding=enc, dtype=str, keep_default_na=False)
                # Replace empty strings with NaN
                df = df.replace("", pd.NA)
                logger.info("Loaded CSV: %d rows × %d cols (enc=%s)", len(df), len(df.columns), enc)
                return {"Sheet1": df}
            except UnicodeDecodeError:
                continue
        raise ValueError("Unable to decode CSV — unknown encoding.")
    except Exception as e:
        if "Unable to decode" in str(e):
            raise
        raise ValueError(f"Failed to read CSV: {e}") from e


def _load_excel(path: str) -> Dict[str, pd.DataFrame]:
    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
        sheets: Dict[str, pd.DataFrame] = {}

        for name in xl.sheet_names:
            try:
                df = xl.parse(
                    name,
                    header=None,   # We'll detect headers ourselves
                    dtype=str,
                    keep_default_na=False,
                )
                df = df.replace("", pd.NA)
                sheets[name] = df
                logger.info(
                    "Sheet '%s': %d rows × %d cols", name, len(df), len(df.columns)
                )
            except Exception as e:
                logger.warning("Skipping sheet '%s': %s", name, e)

        if not sheets:
            raise ValueError("Excel file contains no readable sheets.")

        return sheets
    except Exception as e:
        if "no readable sheets" in str(e):
            raise
        raise ValueError(f"Failed to read Excel file: {e}") from e


@lru_cache(maxsize=4)
def _parse_workbook(path: str, mtime: float) -> Dict[str, Tuple[pd.DataFrame, Tuple[str, ...], Optional[bool]]]:
    """
    Parse every sheet once with openpyxl: unmerge, fill, and convert to a
    DataFrame. Cached per (path, mtime) because each agent re-reads the
    workbook, and a multi-sheet file was otherwise loaded 2× per sheet in
    discovery alone. Returns {sheet: (df, merged_ranges, is_active)}.
    """
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    parsed = {}
    for ws in wb.worksheets:
        # Unmerge: fill merged regions DOWN the first column only.
        # Vertical merges (e.g. one Loc # spanning several building rows) carry
        # a real value for every row. Horizontal merges are banners/notes
        # ("2023 - 2024 Values", footnotes spanning B:AB); copying them across
        # columns fabricates data in unrelated fields, so they stay in the
        # top-left cell only.
        merged_ranges = list(ws.merged_cells.ranges)
        merged_names = tuple(str(r) for r in merged_ranges)
        for merged in merged_ranges:
            top_left_value = ws.cell(merged.min_row, merged.min_col).value
            ws.unmerge_cells(str(merged))
            for r in range(merged.min_row, merged.max_row + 1):
                ws.cell(r, merged.min_col).value = top_left_value

        # Convert to DataFrame
        data = [list(row) for row in ws.iter_rows(values_only=True)]
        df = pd.DataFrame(data)
        df = df.replace("", pd.NA)
        df = df.where(pd.notna(df), other=pd.NA)
        parsed[ws.title] = (df, merged_names, ws is wb.active)
    return parsed


def _parsed_workbook(path: str):
    return _parse_workbook(str(Path(path).resolve()), Path(path).stat().st_mtime)


def unmerge_and_forward_fill(path: str, sheet_name: str) -> pd.DataFrame:
    """
    Load a sheet with openpyxl, unmerge cells, forward-fill merged regions,
    then return as DataFrame.
    """
    try:
        parsed = _parsed_workbook(path)
        if sheet_name in parsed:
            df = parsed[sheet_name][0]
        else:
            # For CSV there's only one sheet
            df = next(v[0] for v in parsed.values() if v[2])
        return df.copy()

    except Exception as e:
        logger.warning("unmerge_and_forward_fill failed for '%s': %s — using plain load", sheet_name, e)
        try:
            df = pd.read_excel(path, sheet_name=sheet_name, header=None, dtype=str, engine="openpyxl")
            df = df.replace("", pd.NA)
            return df
        except Exception:
            return pd.DataFrame()


def detect_header_row(df: pd.DataFrame, max_rows: int = MAX_HEADER_SEARCH_ROWS) -> int:
    """
    Heuristic: scan first `max_rows` rows for the most likely header row.
    Returns 0-indexed row index.
    """
    from app.schemas.target_schema import TARGET_SYNONYMS, TARGET_FIELDS

    all_synonyms: set = set()
    for synonyms in TARGET_SYNONYMS.values():
        for s in synonyms:
            all_synonyms.add(s.lower())
    for f in TARGET_FIELDS:
        all_synonyms.add(f.lower())

    best_row = 0
    best_score = -1.0
    n = min(max_rows, len(df))

    for i in range(n):
        row = df.iloc[i]
        non_null = row.dropna()
        if len(non_null) == 0:
            continue

        # Score: text ratio + synonym matches
        text_count = sum(1 for v in non_null if isinstance(v, str) and not _looks_numeric(str(v)))
        text_ratio = text_count / len(non_null) if len(non_null) > 0 else 0

        synonym_matches = 0
        for v in non_null:
            if isinstance(v, str):
                norm = re.sub(r"[\s_\-\.#]", " ", v.lower()).strip()
                if norm in all_synonyms:
                    synonym_matches += 1

        fill_ratio = len(non_null) / len(row) if len(row) > 0 else 0

        # Check data below is not all text (to verify it's a real header)
        data_below_score = 0.0
        if i + 1 < len(df):
            below_row = df.iloc[i + 1].dropna()
            numeric_below = sum(1 for v in below_row if _looks_numeric(str(v)))
            data_below_score = numeric_below / len(below_row) if len(below_row) > 0 else 0

        score = (
            0.35 * (synonym_matches / max(len(non_null), 1))
            + 0.25 * text_ratio
            + 0.20 * fill_ratio
            + 0.20 * data_below_score
        )

        if score > best_score:
            best_score = score
            best_row = i

    return best_row


def extract_data_frame(
    df: pd.DataFrame,
    header_row: int,
) -> pd.DataFrame:
    """
    Given a raw DataFrame and the header row index,
    return a clean DataFrame with proper column names and data rows only.
    """
    if header_row >= len(df):
        return df

    # Use header row as column names, cleaning and deduplicating
    headers = df.iloc[header_row]
    data = df.iloc[header_row + 1:].copy()

    cleaned_headers = []
    for i, h in enumerate(headers):
        if pd.isna(h):
            cleaned_headers.append(f"_col_{i}")
        else:
            val = re.sub(r"[\r\n\t]+", " ", str(h)).strip()
            if not val or val.lower() == "nan" or val.lower().startswith("unnamed:"):
                cleaned_headers.append(f"_col_{i}")
            else:
                cleaned_headers.append(val)

    # Ensure strictly unique column names
    seen: Dict[str, int] = {}
    unique_cols = []
    for col in cleaned_headers:
        if col in seen:
            seen[col] += 1
            unique_cols.append(f"{col} ({seen[col]})")
        else:
            seen[col] = 0
            unique_cols.append(col)

    data.columns = unique_cols
    data = data.reset_index(drop=True)

    # Drop completely blank rows
    data = data.dropna(how="all")

    # Drop obvious total/footer rows (rows where first col contains "total", "grand total", etc.)
    def is_total_row(row: pd.Series) -> bool:
        for v in row:
            if isinstance(v, str) and re.match(r"^(total|grand total|subtotal|sum|footer)$", v.strip().lower()):
                return True
        return False

    mask = data.apply(is_total_row, axis=1)
    if mask.any():
        logger.info("Dropping %d total/footer rows", mask.sum())
        data = data[~mask]

    # Drop note/footnote rows: a single free-text cell and nothing else
    # (e.g. "*Building values include fixed machinery & equipment"), and rows
    # whose cells hold only whitespace.
    # A genuine location row always carries more than one populated field.
    def is_note_row(row: pd.Series) -> bool:
        non_null = [v for v in row if not pd.isna(v) and str(v).strip() != ""]
        if not non_null:
            return True  # whitespace-only row
        if len(non_null) != 1:
            return False
        v = non_null[0]
        return isinstance(v, str) and not _looks_numeric(v)

    if len(data) > 0:
        note_mask = data.apply(is_note_row, axis=1)
        if note_mask.any():
            logger.info("Dropping %d note/footnote rows", note_mask.sum())
            data = data[~note_mask]

    data = data.reset_index(drop=True)
    return data


def _looks_numeric(s: str) -> bool:
    """Quick check: does this string look like a number?"""
    s = s.strip().replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        float(s)
        return True
    except ValueError:
        return False


def get_merged_cell_info(path: str, sheet_name: str) -> List[str]:
    """Return list of merged cell range strings for a sheet."""
    try:
        if Path(path).suffix.lower() != ".xlsx":
            return []
        parsed = _parsed_workbook(path)
        if sheet_name not in parsed:
            return []
        return list(parsed[sheet_name][1])
    except Exception:
        return []


def profile_dataframe(df: pd.DataFrame) -> Dict:
    """Compute structural metrics for a DataFrame."""
    if df.empty:
        return {"row_count": 0, "col_count": 0, "non_null_ratio": 0.0,
                "text_density": 0.0, "numeric_density": 0.0}

    total_cells = df.size
    non_null_cells = df.notna().sum().sum()
    non_null_ratio = non_null_cells / total_cells if total_cells > 0 else 0.0

    text_count = 0
    numeric_count = 0
    for col in df.columns:
        for val in df[col].dropna():
            s = str(val).strip()
            if _looks_numeric(s):
                numeric_count += 1
            elif s:
                text_count += 1

    total_data = text_count + numeric_count
    text_density = text_count / total_data if total_data > 0 else 0.0
    numeric_density = numeric_count / total_data if total_data > 0 else 0.0

    blank_rows = int(df.isna().all(axis=1).sum())

    return {
        "row_count": len(df),
        "col_count": len(df.columns),
        "non_null_ratio": round(non_null_ratio, 4),
        "text_density": round(text_density, 4),
        "numeric_density": round(numeric_density, 4),
        "blank_row_count": blank_rows,
    }


def load_single_sheet_data(path: str, sheet_name: str, header_row: int = 0) -> pd.DataFrame:
    """
    Extract an isolated sheet's data as a DataFrame using unmerge_and_forward_fill
    and its designated header row.
    """
    df = unmerge_and_forward_fill(path, sheet_name)
    if df.empty:
        df = load_workbook_sheets(path).get(sheet_name, pd.DataFrame())
    if df.empty:
        return pd.DataFrame()
    data = extract_data_frame(df, header_row)
    if not data.empty:
        data.attrs["column_sheets"] = {col: [sheet_name] for col in data.columns}
    return data


def load_source_data(state) -> pd.DataFrame:
    """
    Load the SOV data rows for a pipeline state as a DataFrame.
    When a sheet is processed independently (or in single-sheet workbooks),
    this extracts only that sheet's data without concatenation.
    """
    if state.file_meta is None:
        return pd.DataFrame()
    path = state.file_meta.temp_path

    header_rows = {}
    if state.sheet_manifest is not None:
        header_rows = {s.sheet_name: s.header_row for s in state.sheet_manifest.sheets}
    primary = state.primary_sheet_name or ""
    names = list(state.data_sheets) or [primary]
    specs = [(n, state.header_row if n == primary else header_rows.get(n, 0)) for n in names if n]

    frames = []
    column_sheets: Dict[str, List[str]] = {}
    for name, header_row in specs:
        data = load_single_sheet_data(path, name, header_row)
        if not data.empty:
            frames.append(data)
            for col in data.columns:
                column_sheets.setdefault(col, []).append(name)

    if not frames:
        return pd.DataFrame()
    combined = frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True, sort=False)
    combined.attrs["column_sheets"] = column_sheets
    return combined


def rename_and_coalesce(df: pd.DataFrame, pairs: List[Tuple[str, str]]) -> pd.DataFrame:
    """
    Rename source columns to targets, combining several sources that map to
    the same target (one per sheet, so their rows never overlap) into one
    column. `pairs` is in priority order: where two sources both have a value
    in a row, the earlier pair wins.
    """
    by_target: Dict[str, List[str]] = {}
    for src, tgt in pairs:
        if src in df.columns:
            by_target.setdefault(tgt, []).append(src)

    sources = {s for srcs in by_target.values() for s in srcs}
    out = df[[c for c in df.columns if c not in sources]].copy()
    for tgt, srcs in by_target.items():
        series = df[srcs[0]]
        for s in srcs[1:]:
            series = series.where(series.notna(), df[s])
        out[tgt] = series
    out.attrs = dict(df.attrs)
    return out
