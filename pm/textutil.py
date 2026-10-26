"""Normalizacja tekstu do porównań bez wielkości liter i polskich znaków."""

from __future__ import annotations

import re
import unicodedata

_PL = str.maketrans("ąćęłńóśźż", "acelnoszz")


def fold(value) -> str:
    if value is None:
        return ""
    try:
        if value != value:  # NaN
            return ""
    except Exception:
        pass
    text = str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().translate(_PL)
    text = text.replace("ł", "l")
    return re.sub(r"\s+", " ", text).strip()


def digits_only(value) -> str:
    return re.sub(r"\D", "", fold(value))


def contains_term(haystack: str, term: str) -> bool:
    """Dopasowanie całego słowa lub frazy, nie fragmentu dłuższego wyrazu."""
    folded_term = fold(term)
    if not folded_term:
        return False
    try:
        pattern = r"(?<!\w)" + re.escape(folded_term) + r"(?!\w)"
        return re.search(pattern, fold(haystack)) is not None
    except (TypeError, re.error):
        return False
