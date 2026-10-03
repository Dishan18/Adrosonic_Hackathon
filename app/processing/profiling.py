"""
Column value profiling for the schema mapping cascade.
Profiles each column's values to determine what target field they most likely represent.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from app.schemas.target_schema import (
    MONETARY_FIELDS,
    INTEGER_FIELDS,
    US_STATE_ABBREVS,
    VALID_SPRINKLER_CODES,
    TARGET_FIELDS,
)

logger = logging.getLogger(__name__)

CURRENT_YEAR = datetime.now().year


# ---------------------------------------------------------------------------
# Profile a single column
# ---------------------------------------------------------------------------

def profile_column(series: pd.Series | pd.DataFrame) -> Dict:
    """
    Compute value-profile metrics for a single pandas Series.
    Returns a dict of profile attributes used for value_profile_fit scoring.
    """
    if isinstance(series, pd.DataFrame):
        series = series.iloc[:, 0]
    clean = series.dropna().astype(str).str.strip()
    clean = clean[clean != ""]

    if len(clean) == 0:
        return {"empty": True}

    n = len(clean)
    profile = {"n": n, "empty": False}

    # Numeric analysis
    numerics = []
    for v in clean:
        num = _try_float(v)
        if num is not None:
            numerics.append(num)

    numeric_ratio = len(numerics) / n
    profile["numeric_ratio"] = numeric_ratio

    if numerics:
        profile["min"] = min(numerics)
        profile["max"] = max(numerics)
        profile["mean"] = sum(numerics) / len(numerics)
        profile["all_integers"] = all(float(x) == int(x) for x in numerics)
        profile["any_negative"] = any(x < 0 for x in numerics)
    else:
        profile["min"] = None
        profile["max"] = None
        profile["mean"] = None
        profile["all_integers"] = False
        profile["any_negative"] = False

    # String length analysis
    lengths = [len(v) for v in clean]
    profile["mean_length"] = sum(lengths) / len(lengths)
    profile["max_length"] = max(lengths)

    # Currency detection
    currency_count = sum(1 for v in clean if re.search(r"[\$,]", v))
    profile["currency_ratio"] = currency_count / n

    # Year-like detection (4-digit, 1700-current)
    year_count = sum(1 for v in clean if _is_year_like(v))
    profile["year_ratio"] = year_count / n

    # Zip-like detection (5-digit), handle both string and float/int representations
    zip_count = 0
    for v in clean:
        vs = v.strip()
        # Direct 5-digit string
        if re.match(r"^\d{5}(-\d{4})?$", vs):
            zip_count += 1
        # Float representation like "10001.0"
        elif re.match(r"^\d{5}\.0$", vs):
            zip_count += 1
        # Integer that's 5 digits in range 00000-99999
        elif re.match(r"^\d{5}$", re.sub(r"\.0$", "", vs)):
            zip_count += 1
    profile["zip_ratio"] = zip_count / n

    # 3–4 digit integers: ZIPs whose leading zeros Excel dropped (00802 → 802)
    short_zip_count = sum(1 for v in clean if re.match(r"^\d{3,4}$", re.sub(r"\.0$", "", v.strip())))
    profile["short_zip_ratio"] = short_zip_count / n

    # State-like detection (2-letter US state)
    # Tolerate dotted/spaced forms such as "V.I." or "N. Y."
    state_count = sum(1 for v in clean if re.sub(r"[\s.]", "", v).upper() in US_STATE_ABBREVS)
    profile["state_ratio"] = state_count / n

    # Sprinkler-like detection
    sprinkler_count = sum(
        1 for v in clean if _is_sprinkler_code(v)
    )
    profile["sprinkler_ratio"] = sprinkler_count / n

    # Y/N binary
    yn_count = sum(1 for v in clean if v.strip().upper() in {"Y", "N", "YES", "NO"})
    profile["yn_ratio"] = yn_count / n

    # Storey-like (small integer 1-100)
    storey_count = sum(
        1 for v in clean if _is_storey_like(v)
    )
    profile["storey_ratio"] = storey_count / n

    # Large monetary detection (>= 1000 with possible currency symbols)
    monetary_count = sum(
        1 for v in clean if _is_monetary_like(v)
    )
    profile["monetary_ratio"] = monetary_count / n

    # Unique ratio (Reference-like)
    unique_count = len(set(clean))
    profile["unique_ratio"] = unique_count / n

    # Address-like (contains digits + letters mixed, or keywords)
    addr_count = sum(1 for v in clean if _looks_like_address(v))
    profile["address_ratio"] = addr_count / n

    return profile


def score_value_profile_fit(profile: Dict, target_field: str) -> float:
    """
    Score how well a column's value profile fits a target field.
    Returns 0.0–1.0.
    """
    if profile.get("empty", False):
        return 0.0

    score = 0.0

    if target_field in MONETARY_FIELDS:
        # Expect large floats, possibly with currency symbols
        score += profile.get("monetary_ratio", 0.0) * 0.6
        score += profile.get("numeric_ratio", 0.0) * 0.4
        if profile.get("any_negative"):
            score *= 0.5
        # A column of 4-digit years (1990, 2005, …) is not an amount
        if profile.get("year_ratio", 0.0) >= 0.9:
            score *= 0.2

    elif target_field == "Year Built":
        score = profile.get("year_ratio", 0.0)
        # Bonus if numeric and in range
        if profile.get("numeric_ratio", 0) > 0.8 and profile.get("min") and profile.get("max"):
            if 1700 <= profile["min"] and profile["max"] <= CURRENT_YEAR + 1:
                score = min(1.0, score + 0.3)

    elif target_field == "Zip":
        # Short (zero-stripped) ZIPs are weaker evidence than 5-digit ones
        zip_ratio = max(profile.get("zip_ratio", 0.0), 0.6 * profile.get("short_zip_ratio", 0.0))
        # High zip_ratio trumps monetary detection (ZIPs are 5-digit numbers)
        if zip_ratio > 0.5:
            score = zip_ratio
        else:
            # Zip shouldn't be monetary when zip_ratio is low
            score = zip_ratio * (1 - min(0.5, profile.get("monetary_ratio", 0.0)))

    elif target_field == "State":
        score = profile.get("state_ratio", 0.0)

    elif target_field == "Fire Sprinklers (Y/N)":
        score = profile.get("sprinkler_ratio", 0.0)
        score += profile.get("yn_ratio", 0.0) * 0.3
        score = min(1.0, score)

    elif target_field == "Storeys":
        score = profile.get("storey_ratio", 0.0)
        # Small integers, not zip/year
        if profile.get("numeric_ratio", 0) > 0.8:
            score += 0.2
        score = min(1.0, score)

    elif target_field == "Number of Buildings":
        # Similar to Storeys but typically smaller
        score = profile.get("storey_ratio", 0.0)
        if profile.get("numeric_ratio", 0) > 0.8:
            score += 0.2
        score = min(1.0, score)

    elif target_field == "Reference":
        # Any value type can be an identifier (numeric Loc # values are common,
        # and repeats are legitimate when one location has several buildings),
        # so uniqueness only raises the score above a neutral floor.
        # Fractional numbers (coordinates, amounts) are not identifiers.
        if profile.get("numeric_ratio", 0.0) > 0.8 and not profile.get("all_integers", False):
            return 0.2
        score = 0.5 + 0.5 * profile.get("unique_ratio", 0.0)

    elif target_field == "Address":
        score = profile.get("address_ratio", 0.0)
        # Some SOVs carry only a locality in the address column; plain text is
        # weak evidence but not a contradiction.
        if profile.get("numeric_ratio", 0.0) < 0.2:
            score = max(score, 0.3)

    elif target_field in {"City", "County", "Country", "Occupancy", "Construction"}:
        # Text-dominant, not numeric. A purely numeric column (lat/long,
        # amounts, IDs) cannot be a place name. Occupancy/Construction may
        # legitimately be numeric codes, so they are not vetoed.
        if target_field in {"City", "County", "Country"} and profile.get("numeric_ratio", 0.0) > 0.8:
            return 0.0
        score = (1 - profile.get("numeric_ratio", 0.0)) * 0.7
        score += (1 - profile.get("monetary_ratio", 0.0)) * 0.3

    return round(min(1.0, max(0.0, score)), 4)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _try_float(s: str) -> Optional[float]:
    s = s.strip().replace(",", "").replace("$", "").replace("(", "-").replace(")", "")
    try:
        return float(s)
    except ValueError:
        return None


def _is_year_like(s: str) -> bool:
    s = s.strip()
    if re.match(r"^\d{4}$", s):
        y = int(s)
        return 1700 <= y <= CURRENT_YEAR + 1
    return False


def _is_storey_like(s: str) -> bool:
    try:
        v = float(s.strip().replace(",", ""))
        return 1 <= v <= 200 and float(v) == int(v)
    except Exception:
        return False


def _is_monetary_like(s: str) -> bool:
    s = s.strip().replace(",", "").replace("$", "")
    try:
        v = float(s)
        return abs(v) >= 100  # monetary values are typically >= $100
    except Exception:
        return False


def _is_sprinkler_code(s: str) -> bool:
    return s.strip().upper() in {
        "Y", "N", "YES", "NO", "Y13", "Y(13R)", "TRUE", "FALSE", "1", "0",
        "Y 13", "Y(13 R)", "SPRINKLERED", "NON-SPRINKLERED",
    }


def _looks_like_address(s: str) -> bool:
    """Heuristic: contains digits + words, or address keywords."""
    if re.search(r"\d+\s+\w+", s):
        return True
    keywords = {"street", "st", "ave", "avenue", "blvd", "boulevard", "rd", "road",
                "dr", "drive", "ln", "lane", "way", "place", "pl", "court", "ct"}
    tokens = set(re.split(r"\s+|,|\.", s.lower()))
    return bool(tokens & keywords)
