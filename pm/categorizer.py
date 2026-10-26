"""Kategoryzacja transakcji na podstawie słów kluczowych i zasad kwot."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from pm.schema import (
    AMOUNT_ANY,
    AMOUNT_CREDIT,
    AMOUNT_DEBIT,
    COL_ACCOUNT_NAME,
    COL_ACCOUNT_NUMBER,
    COL_AMOUNT_MAX,
    COL_AMOUNT_MIN,
    COL_AMOUNT_TYPE,
    COL_CATEGORY,
    COL_CREDIT,
    COL_DEBIT,
    COL_ID,
    COL_KEYWORD,
    COL_RECIPIENT,
    COL_SOURCE,
    COL_SUBCATEGORY,
    COL_TITLE,
    INTERNAL_CATEGORY,
    SOURCE_AUTO,
    SOURCE_MANUAL,
    STATUS_ASSIGNED,
    STATUS_CONFLICT,
    STATUS_NONE,
)
from pm.textutil import contains_term, digits_only, fold

_INTERNAL_PHRASE = "wewnetrzn"


@dataclass
class RuleHit:
    category: str
    keyword: str
    subcategory: str
    amount_type: str
    amount_min: float | None
    amount_max: float | None

    def label(self) -> str:
        return describe_rule(self.amount_type, self.amount_min, self.amount_max, fallback=not self.keyword)


@dataclass
class Classification:
    status: str
    category: str | None = None
    subcategory: str | None = None
    hits: list[RuleHit] = field(default_factory=list)


@dataclass
class RecalcStats:
    changed: int = 0
    conflicts: int = 0
    cleared: int = 0
    skipped_manual: int = 0
    conflict_ids: list[str] = field(default_factory=list)


def describe_rule(amount_type: str, amount_min, amount_max, fallback: bool = False) -> str:
    lo = _num(amount_min)
    hi = _num(amount_max)
    typ = (amount_type or AMOUNT_ANY).strip().lower()
    if fallback and typ == AMOUNT_CREDIT and lo is None and hi is None:
        return "Dowolny wpływ na konto"
    if typ == AMOUNT_DEBIT and lo is None and hi is None:
        return "Dowolne obciążenie"
    if typ == AMOUNT_CREDIT and lo is None and hi is None:
        return "Dowolny wpływ na konto"
    if typ == AMOUNT_ANY and lo is None and hi is None:
        return "Dowolna kwota"
    names = {
        AMOUNT_DEBIT: "Obciążenie",
        AMOUNT_CREDIT: "Uznanie",
        AMOUNT_ANY: "Kwota",
    }
    name = names.get(typ, typ)
    if lo is not None and hi is not None:
        return f"{name} od {_fmt(lo)} do {_fmt(hi)} zł"
    if lo is not None:
        return f"{name} od {_fmt(lo)} zł"
    if hi is not None:
        return f"{name} do {_fmt(hi)} zł"
    return name


def _fmt(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}"


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _money(value) -> float:
    number = _num(value)
    return 0.0 if number is None else number


def _text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _keyword_rows(keywords: pd.DataFrame) -> list[dict]:
    if keywords is None or keywords.empty:
        return []
    rows = []
    for _, row in keywords.iterrows():
        category = str(row.get(COL_CATEGORY) or "").strip()
        if not category:
            continue
        rows.append(
            {
                "category": category,
                "keyword": _text(row.get(COL_KEYWORD)),
                "subcategory": _text(row.get(COL_SUBCATEGORY)),
                "amount_type": str(row.get(COL_AMOUNT_TYPE) or AMOUNT_ANY).strip().lower(),
                "amount_min": _num(row.get(COL_AMOUNT_MIN)),
                "amount_max": _num(row.get(COL_AMOUNT_MAX)),
            }
        )
    return rows


def _amount_matches(rule: dict, debit: float, credit: float) -> bool:
    typ = rule["amount_type"] or AMOUNT_ANY
    if typ == AMOUNT_DEBIT:
        if debit <= 0:
            return False
        value = debit
    elif typ == AMOUNT_CREDIT:
        if credit <= 0:
            return False
        value = credit
    else:
        value = debit if debit > 0 else credit
        if value <= 0:
            return False
    lo = rule["amount_min"]
    hi = rule["amount_max"]
    if lo is not None and value < lo - 1e-6:
        return False
    if hi is not None and value > hi + 1e-6:
        return False
    return True


def _accounts(accounts: pd.DataFrame) -> list[tuple[str, str]]:
    if accounts is None or accounts.empty:
        return []
    found = []
    for _, row in accounts.iterrows():
        name = str(row.get(COL_ACCOUNT_NAME) or "").strip()
        number = digits_only(row.get(COL_ACCOUNT_NUMBER))
        if name or len(number) >= 6:
            found.append((name, number))
    return found


def _internal_match(title: str, recipient: str, accounts: pd.DataFrame) -> str | None:
    blob = f"{title} {recipient}"
    if _INTERNAL_PHRASE in fold(blob):
        return "Między kontami"
    compact = digits_only(blob)
    folded_blob = fold(blob)
    for name, number in _accounts(accounts):
        if len(number) >= 6 and number in compact:
            return f"Konto: {name}" if name else "Konto własne"
        if len(fold(name)) >= 4 and contains_term(folded_blob, name):
            return f"Konto: {name}"
    return None


def _hit_from(rule: dict) -> RuleHit:
    return RuleHit(
        category=rule["category"],
        keyword=rule["keyword"],
        subcategory=str(rule.get("subcategory") or "").strip(),
        amount_type=rule["amount_type"],
        amount_min=rule["amount_min"],
        amount_max=rule["amount_max"],
    )


def _shared_subcategory(hits: list[RuleHit]) -> str | None:
    """Jedna podkategoria albo pusty tekst. None, gdy reguły wskazują różne podkategorie."""
    found: list[str] = []
    for hit in hits:
        text = (hit.subcategory or "").strip()
        if text and text not in found:
            found.append(text)
    if len(found) > 1:
        return None
    return found[0] if found else ""


def classify_transaction(
    title: str,
    recipient: str,
    debit,
    credit,
    keywords: pd.DataFrame,
    accounts: pd.DataFrame | None = None,
) -> Classification:
    debit_v = _money(debit)
    credit_v = _money(credit)
    internal = _internal_match(str(title or ""), str(recipient or ""), accounts if accounts is not None else pd.DataFrame())
    if internal:
        return Classification(status=STATUS_ASSIGNED, category=INTERNAL_CATEGORY, subcategory=internal, hits=[])

    rules = _keyword_rows(keywords)
    haystack = f"{title or ''} {recipient or ''}"
    keyword_hits = [
        rule
        for rule in rules
        if rule["keyword"] and contains_term(haystack, rule["keyword"]) and _amount_matches(rule, debit_v, credit_v)
    ]
    if keyword_hits:
        hits = [_hit_from(rule) for rule in keyword_hits]
        categories = {hit.category for hit in hits}
        subcategory = _shared_subcategory(hits)
        if len(categories) == 1 and subcategory is not None:
            return Classification(
                status=STATUS_ASSIGNED,
                category=next(iter(categories)),
                subcategory=subcategory,
                hits=hits,
            )
        return Classification(status=STATUS_CONFLICT, hits=hits)

    fallback_hits = [
        rule for rule in rules if not rule["keyword"] and _amount_matches(rule, debit_v, credit_v)
    ]
    if not fallback_hits:
        return Classification(status=STATUS_NONE)
    categories = {rule["category"] for rule in fallback_hits}
    hits = [_hit_from(rule) for rule in fallback_hits]
    subcategory = _shared_subcategory(hits)
    if len(categories) == 1 and subcategory is not None:
        return Classification(status=STATUS_ASSIGNED, category=next(iter(categories)), subcategory=subcategory, hits=hits)
    return Classification(status=STATUS_CONFLICT, hits=hits)


def classify_row(row: dict, keywords: pd.DataFrame, accounts: pd.DataFrame) -> Classification:
    if not isinstance(row, dict):
        return Classification(status=STATUS_NONE)
    return classify_transaction(
        row.get(COL_TITLE, ""),
        row.get(COL_RECIPIENT, ""),
        row.get(COL_DEBIT, 0),
        row.get(COL_CREDIT, 0),
        keywords,
        accounts,
    )


def apply_classification(row: dict, classification: Classification, overwrite_manual: bool) -> str:
    """Aktualizuje wiersz. Zwraca: changed, same, conflict, cleared, skipped."""
    manual = str(row.get(COL_SOURCE) or "") == SOURCE_MANUAL
    if manual and not overwrite_manual:
        return "skipped"

    if classification.status == STATUS_ASSIGNED:
        new_cat = classification.category or ""
        new_sub = classification.subcategory or ""
        changed = (str(row.get(COL_CATEGORY) or "") != new_cat) or (str(row.get(COL_SUBCATEGORY) or "") != new_sub)
        row[COL_CATEGORY] = new_cat
        row[COL_SUBCATEGORY] = new_sub
        row[COL_SOURCE] = SOURCE_AUTO
        return "changed" if changed else "same"

    if classification.status == STATUS_CONFLICT:
        return "conflict"

    had_category = bool(str(row.get(COL_CATEGORY) or "").strip())
    if had_category and (not manual or overwrite_manual):
        row[COL_CATEGORY] = ""
        row[COL_SUBCATEGORY] = ""
        row[COL_SOURCE] = SOURCE_AUTO
        return "cleared"
    return "same"


def annotate_rows(
    rows: list[dict],
    keywords: pd.DataFrame,
    accounts: pd.DataFrame,
    only_ids: set[str] | None = None,
) -> dict[str, Classification]:
    """Nadaje kategorie wierszom. Pomija ręcznie przypisane. Zwraca klasyfikacje przetworzonych wierszy."""
    found: dict[str, Classification] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get(COL_ID) or "")
        if only_ids is not None and row_id not in only_ids:
            continue
        if str(row.get(COL_SOURCE) or "") == SOURCE_MANUAL:
            continue
        classification = classify_row(row, keywords, accounts)
        found[row_id] = classification
        if classification.status == STATUS_ASSIGNED:
            row[COL_CATEGORY] = classification.category or ""
            row[COL_SUBCATEGORY] = classification.subcategory or ""
            row[COL_SOURCE] = SOURCE_AUTO
        else:
            row[COL_CATEGORY] = ""
            row[COL_SUBCATEGORY] = ""
            row[COL_SOURCE] = ""
    return found


def unresolved_ids(ids: list[str], classes: dict[str, Classification]) -> list[str]:
    conflicts: list[str] = []
    missing: list[str] = []
    for row_id in ids:
        classification = classes.get(row_id)
        if classification is None:
            continue
        if classification.status == STATUS_CONFLICT:
            conflicts.append(row_id)
        elif classification.status == STATUS_NONE:
            missing.append(row_id)
    return conflicts + missing


def recategorize(
    transactions: pd.DataFrame,
    keywords: pd.DataFrame,
    accounts: pd.DataFrame,
    overwrite_manual: bool = False,
) -> tuple[pd.DataFrame, RecalcStats]:
    stats = RecalcStats()
    if transactions is None or transactions.empty:
        return transactions.copy() if transactions is not None else pd.DataFrame(), stats

    updated = transactions.copy()
    for idx, row in updated.iterrows():
        record = row.to_dict()
        if str(record.get(COL_SOURCE) or "") == SOURCE_MANUAL and not overwrite_manual:
            stats.skipped_manual += 1
            continue
        classification = classify_row(record, keywords, accounts)
        outcome = apply_classification(record, classification, overwrite_manual)
        for key, value in record.items():
            updated.at[idx, key] = value
        if outcome == "changed":
            stats.changed += 1
        elif outcome == "cleared":
            stats.cleared += 1
        elif outcome == "conflict":
            stats.conflicts += 1
            stats.conflict_ids.append(str(record.get(COL_ID)))
        elif outcome == "skipped":
            stats.skipped_manual += 1
    return updated, stats
