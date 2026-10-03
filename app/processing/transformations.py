"""
Deterministic transformation registry (whitelist).
ONLY operations defined here may be applied to data.
The LLM can ONLY select from this whitelist.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from app.schemas.target_schema import US_STATE_ABBREVS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Individual transformation functions
# ---------------------------------------------------------------------------

def strip_currency(value: Any) -> Any:
    """Remove currency symbols and commas. Return NaN if not numeric."""
    if pd.isna(value) or value is None:
        return value
    s = str(value).strip()
    s = s.replace("$", "").replace(",", "").replace("(", "-").replace(")", "")
    s = s.strip()
    if s == "" or s == "-":
        return pd.NA
    try:
        return float(s)
    except ValueError:
        return pd.NA


def to_float(value: Any) -> Any:
    """Convert to float. Preserve NaN."""
    if pd.isna(value) or value is None:
        return value
    s = str(value).strip().replace(",", "").replace("$", "")
    if s == "":
        return pd.NA
    try:
        return float(s)
    except ValueError:
        return pd.NA


def to_int(value: Any) -> Any:
    """Convert to integer. Preserve NaN."""
    if pd.isna(value) or value is None:
        return value
    s = str(value).strip().replace(",", "")
    if s == "":
        return pd.NA
    try:
        return int(float(s))
    except (ValueError, OverflowError):
        return pd.NA


def to_str(value: Any) -> Any:
    """Convert to string. Preserve NaN."""
    if pd.isna(value) or value is None:
        return pd.NA
    s = str(value).strip()
    return s if s else pd.NA


def trim_whitespace(value: Any) -> Any:
    """Trim leading/trailing whitespace."""
    if pd.isna(value) or value is None:
        return value
    return str(value).strip()


def normalize_spaces(value: Any) -> Any:
    """Normalize multiple spaces to single space."""
    if pd.isna(value) or value is None:
        return value
    return re.sub(r"\s+", " ", str(value).strip())


def state_to_abbrev(value: Any) -> Any:
    """Convert state name to 2-letter abbreviation, or leave as-is if already valid."""
    if pd.isna(value) or value is None:
        return value
    s = str(value).strip()
    if s.upper() in US_STATE_ABBREVS:
        return s.upper()

    # Full state name lookup
    STATE_MAP = {
        "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
        "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
        "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
        "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
        "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
        "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
        "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
        "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
        "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
        "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
        "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
        "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
        "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
    }
    abbrev = STATE_MAP.get(s.lower())
    return abbrev if abbrev else s  # Return original if no match


def normalize_sprinkler_code(value: Any) -> Any:
    """Normalize sprinkler codes to canonical form."""
    if pd.isna(value) or value is None:
        return value
    s = str(value).strip()
    mapping = {
        "yes": "Y", "true": "Y", "1": "Y",
        "no": "N", "false": "N", "0": "N",
        "y 13": "Y13", "y13r": "Y(13R)", "y (13r)": "Y(13R)",
    }
    upper = s.upper()
    if upper in {"Y", "N", "Y13", "Y(13R)"}:
        return upper
    normalized = mapping.get(s.lower(), s)
    return normalized


def normalize_date(value: Any) -> Any:
    """Try to parse and normalize date-like strings to YYYY-MM-DD."""
    if pd.isna(value) or value is None:
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value  # Return original if parsing fails


def to_year_int(value: Any) -> Any:
    """Extract 4-digit year from various formats."""
    if pd.isna(value) or value is None:
        return value
    s = str(value).strip()
    # Direct 4-digit year
    m = re.search(r"\b(1[7-9]\d{2}|20[0-2]\d)\b", s)
    if m:
        return int(m.group(1))
    return pd.NA


def to_zip(value: Any) -> Any:
    """Extract/normalize 5-digit ZIP code."""
    if pd.isna(value) or value is None:
        return value
    s = str(value).strip()
    # Handle ZIP+4
    s = s.split("-")[0].split(".")[0]
    # Strip leading/trailing whitespace and non-digits
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 5:
        zip5 = digits[:5]
        try:
            return int(zip5)
        except ValueError:
            return pd.NA
    return pd.NA


def flag_for_review(value: Any) -> Any:
    """Identity transformation — value flagged but not changed."""
    return value


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

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

WHITELISTED_OPERATIONS = set(TRANSFORMATION_REGISTRY.keys())


def apply_transformation(operation: str, value: Any) -> Any:
    """
    Apply a named transformation from the whitelist.
    Raises ValueError if operation is not whitelisted.
    """
    if operation not in TRANSFORMATION_REGISTRY:
        raise ValueError(
            f"Operation '{operation}' is not in the transformation whitelist. "
            f"Allowed: {sorted(WHITELISTED_OPERATIONS)}"
        )
    try:
        return TRANSFORMATION_REGISTRY[operation](value)
    except Exception as e:
        logger.warning("Transformation '%s' failed on value '%s': %s", operation, value, e)
        return value  # Return original on error


def apply_transformation_to_series(operation: str, series: pd.Series) -> pd.Series:
    """Apply a whitelisted transformation to an entire Series."""
    if operation not in TRANSFORMATION_REGISTRY:
        raise ValueError(f"Operation '{operation}' is not whitelisted.")
    fn = TRANSFORMATION_REGISTRY[operation]
    return series.apply(fn)


def suggest_operation_for_target(target_field: str, source_col_sample: pd.Series) -> str:
    """
    Suggest the most appropriate transformation operation for a target field,
    based on the target's expected type.
    """
    from app.schemas.target_schema import MONETARY_FIELDS, INTEGER_FIELDS, STRING_FIELDS

    if target_field in MONETARY_FIELDS:
        # Check if currency symbols present
        sample = source_col_sample.dropna().astype(str)
        has_currency = any(re.search(r"[\$,]", v) for v in sample)
        return "strip_currency" if has_currency else "to_float"

    elif target_field == "Year Built":
        return "to_year_int"

    elif target_field == "Zip":
        return "to_zip"

    elif target_field == "State":
        return "state_to_abbrev"

    elif target_field == "Fire Sprinklers (Y/N)":
        return "normalize_sprinkler_code"

    elif target_field in INTEGER_FIELDS:
        return "to_int"

    elif target_field in STRING_FIELDS:
        return "trim_whitespace"

    return "trim_whitespace"
