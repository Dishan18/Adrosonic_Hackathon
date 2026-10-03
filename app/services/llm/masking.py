"""
Data minimisation for LLM prompts.

Only headers, target definitions, counts and masked sample values leave the
process. Masking keeps the *shape* of a value (which is what mapping needs:
"9999" looks like a year, "$9,999,999" like an amount, "Masonry" like a
construction class) while removing the actual figures, identifiers and
contact details.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List

MAX_MASKED_LENGTH = 32

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def mask_value(value: Any) -> str:
    """
    Mask a single cell value:
      - every digit becomes '9'  ("75219" → "99999", "$1,500,000" → "$9,999,999")
      - e-mail addresses become "<email>"
      - long values are truncated to MAX_MASKED_LENGTH characters
    """
    s = str(value).strip()
    s = _EMAIL.sub("<email>", s)
    s = re.sub(r"\d", "9", s)
    if len(s) > MAX_MASKED_LENGTH:
        s = s[:MAX_MASKED_LENGTH] + "…"
    return s


def mask_values(values: Iterable[Any]) -> List[str]:
    return [mask_value(v) for v in values]
