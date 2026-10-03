"""
Pandera schema validation for the final Cleaned_SOV output.
"""

from __future__ import annotations

import logging
from typing import List, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

TARGET_COLUMN_ORDER = [
    "Reference",
    "Address",
    "City",
    "State",
    "Zip",
    "County",
    "Country",
    "Building Value",
    "Contents",
    "BI",
    "Occupancy",
    "Construction",
    "Storeys",
    "Number of Buildings",
    "Year Built",
    "Fire Sprinklers (Y/N)",
    "Other",
]


def validate_output_schema(df: pd.DataFrame) -> Tuple[bool, List[str]]:
    """
    Validate the final cleaned DataFrame against the 17-field SOV schema.
    Returns (passed, list_of_errors).
    """
    errors = []

    # 1. Exactly 17 columns
    if len(df.columns) != 17:
        errors.append(
            f"Expected 17 columns, got {len(df.columns)}: {list(df.columns)}"
        )

    # 2. Exact column names
    actual = list(df.columns)
    if actual != TARGET_COLUMN_ORDER:
        missing = [c for c in TARGET_COLUMN_ORDER if c not in actual]
        extra = [c for c in actual if c not in TARGET_COLUMN_ORDER]
        wrong_order = actual != TARGET_COLUMN_ORDER
        if missing:
            errors.append(f"Missing columns: {missing}")
        if extra:
            errors.append(f"Extra columns: {extra}")
        if wrong_order and not missing and not extra:
            errors.append(f"Columns in wrong order. Expected: {TARGET_COLUMN_ORDER}")

    if errors:
        return False, errors

    # 3. Pandera validation (soft — won't fail on null values per design)
    try:
        import pandera.pandas as pa

        schema = pa.DataFrameSchema(
            columns={
                col: pa.Column(nullable=True, required=True)
                for col in TARGET_COLUMN_ORDER
            },
            strict=True,
            ordered=True,
        )
        schema.validate(df, lazy=True)
        logger.info("Pandera validation passed.")

    except Exception as e:
        errors.append(f"Pandera validation error: {e}")

    # 4. No merged cells (checked structurally — always True for DataFrame)
    # DataFrame output to xlsx never has merged cells unless explicitly added.

    # 5. Check for extra columns one more time
    if set(df.columns) != set(TARGET_COLUMN_ORDER):
        errors.append(f"Column set mismatch: {set(df.columns)} vs {set(TARGET_COLUMN_ORDER)}")

    passed = len(errors) == 0
    return passed, errors


def enforce_column_order(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure DataFrame has exactly 17 columns in the exact target order.
    Missing columns are added as null. Extra columns are dropped.
    """
    # Add missing columns as null
    for col in TARGET_COLUMN_ORDER:
        if col not in df.columns:
            df[col] = pd.NA

    # Drop extra columns
    df = df[[c for c in TARGET_COLUMN_ORDER if c in df.columns]]

    # Ensure exact order
    df = df[TARGET_COLUMN_ORDER]

    return df
