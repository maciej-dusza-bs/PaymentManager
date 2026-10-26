"""Wczytywanie wyciągów Excel: arkusz, nagłówki, kwoty, deduplikacja."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO

import pandas as pd

from pm.schema import (
    COL_BANK,
    COL_CREDIT,
    COL_CURRENCY,
    COL_DATE,
    COL_DEBIT,
    COL_FILE,
    COL_ID,
    COL_RECIPIENT,
    COL_TITLE,
    COL_UPLOADED,
    SIGNED_AMOUNT_FIELD,
    TARGET_FIELDS,
    TX_COLUMNS,
)
from pm.textutil import contains_term, fold

SYNONYMS: dict[str, list[str]] = {
    COL_DATE: [
        "data transakcji",
        "data operacji",
        "data ksiegowania",
        "data waluty",
        "booking date",
        "transaction date",
        "data",
    ],
    COL_TITLE: [
        "tytul operacji",
        "tytul transakcji",
        "opis transakcji",
        "opis operacji",
        "szczegoly transakcji",
        "tytul",
        "opis",
        "description",
        "title",
    ],
    COL_RECIPIENT: [
        "nadawca/odbiorca",
        "nazwa odbiorcy",
        "nazwa nadawcy",
        "nazwa kontrahenta",
        "odbiorca",
        "nadawca",
        "kontrahent",
        "beneficiary",
    ],
    COL_DEBIT: [
        "kwota obciazenia",
        "obciazenia",
        "obciazenie",
        "wydatki",
        "debit",
        "winien",
    ],
    COL_CREDIT: [
        "kwota uznania",
        "uznania",
        "uznanie",
        "wplywy",
        "credit",
        "ma",
    ],
    SIGNED_AMOUNT_FIELD: [
        "kwota transakcji",
        "kwota operacji",
        "kwota",
        "amount",
        "wartosc",
    ],
    COL_CURRENCY: ["waluta", "currency"],
}

BANKS: list[tuple[str, list[str]]] = [
    ("mBank", ["mbank"]),
    ("PKO BP", ["pko"]),
    ("ING", ["ing bank", "ing"]),
    ("Santander", ["santander"]),
    ("Millennium", ["millennium", "1160 2202"]),
    ("Pekao", ["pekao"]),
    ("BNP Paribas", ["bnp", "bgz"]),
    ("Alior", ["alior"]),
    ("Credit Agricole", ["agricole"]),
    ("Nest Bank", ["nest bank", "nest"]),
    ("Revolut", ["revolut"]),
    ("VeloBank", ["velobank", "velo"]),
    ("Citi Handlowy", ["handlowy", "citi"]),
]


@dataclass
class SheetPreview:
    header_row: int
    columns: list[str]
    mapping: dict[str, str | None]
    raw: pd.DataFrame = field(repr=False)


def read_workbook(data: bytes, filename: str) -> pd.ExcelFile:
    engine = "xlrd" if filename.lower().endswith(".xls") and not filename.lower().endswith(".xlsx") else "openpyxl"
    return pd.ExcelFile(BytesIO(data), engine=engine)


def read_sheet(workbook: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(workbook, sheet_name=sheet_name, header=None, dtype=object)


def _cell_match(cell: str) -> tuple[str, int, int] | None:
    """Zwraca pole, długość dopasowanego synonimu i jego pozycję na liście (mniejsza = lepsza)."""
    folded = fold(cell)
    if not folded:
        return None
    best_field = None
    best_key = None
    for field_name, synonyms in SYNONYMS.items():
        for priority, synonym in enumerate(synonyms):
            exact = folded == synonym
            contained = len(synonym) >= 5 and synonym in folded
            if not (exact or contained):
                continue
            key = (len(synonym), -priority)
            if best_key is None or key > best_key:
                best_key = key
                best_field = (field_name, len(synonym), priority)
    return best_field


def _cell_field(cell: str) -> str | None:
    match = _cell_match(cell)
    return None if match is None else match[0]


def find_header_row(raw: pd.DataFrame, scan: int = 40) -> int:
    limit = min(scan, len(raw))
    best_row = 0
    best_score = -1
    for index in range(limit):
        fields = set()
        for value in raw.iloc[index].tolist():
            plain = unwrap_cell(value)
            found = _cell_field("" if _missing(plain) else str(plain))
            if found:
                fields.add(found)
        has_date = COL_DATE in fields
        has_amount = bool(fields & {COL_DEBIT, COL_CREDIT, SIGNED_AMOUNT_FIELD})
        score = len(fields) + (2 if has_date and has_amount else 0)
        if score > best_score:
            best_score = score
            best_row = index
    return best_row


def _column_names(raw: pd.DataFrame, header_row: int) -> list[str]:
    names: list[str] = []
    seen: dict[str, int] = {}
    for offset, value in enumerate(raw.iloc[header_row].tolist()):
        plain = unwrap_cell(value)
        if _missing(plain) or str(plain).strip() == "":
            label = f"Kolumna {offset + 1}"
        else:
            label = str(plain).strip()
        count = seen.get(label, 0) + 1
        seen[label] = count
        names.append(label if count == 1 else f"{label} ({count})")
    return names


def detect_mapping(raw: pd.DataFrame, header_row: int) -> dict[str, str | None]:
    names = _column_names(raw, header_row)
    mapping: dict[str, str | None] = {field: None for field in TARGET_FIELDS}
    mapping[SIGNED_AMOUNT_FIELD] = None
    used: set[int] = set()
    ranked: list[tuple[tuple[int, int, int], int, str]] = []
    for index, name in enumerate(names):
        original = str(unwrap_cell(raw.iloc[header_row, index])) if index < raw.shape[1] else name
        match = _cell_match(original)
        if match:
            field_name, synonym_length, priority = match
            ranked.append(((-priority, synonym_length, -index), index, field_name))
    ranked.sort(reverse=True)
    for _, index, field_name in ranked:
        if mapping.get(field_name) is None and index not in used:
            mapping[field_name] = names[index]
            used.add(index)
    if mapping[COL_DEBIT] or mapping[COL_CREDIT]:
        mapping[SIGNED_AMOUNT_FIELD] = None
    return mapping


def analyze_sheet(raw: pd.DataFrame) -> SheetPreview:
    if raw is None or raw.empty:
        return SheetPreview(0, [], {field: None for field in TARGET_FIELDS + [SIGNED_AMOUNT_FIELD]}, raw)
    header_row = find_header_row(raw)
    columns = _column_names(raw, header_row)
    return SheetPreview(header_row, columns, detect_mapping(raw, header_row), raw)


def header_columns(raw: pd.DataFrame, header_row: int) -> list[str]:
    if raw is None or raw.empty:
        return []
    row = min(max(int(header_row), 0), len(raw) - 1)
    return _column_names(raw, row)


def guess_bank(filename: str, raw: pd.DataFrame | None = None) -> str:
    parts = [filename.replace("_", " ").replace("-", " ")]
    if raw is not None and not raw.empty:
        for value in raw.head(15).to_numpy().ravel().tolist():
            if value is None or (isinstance(value, float) and pd.isna(value)):
                continue
            parts.append(str(value))
    blob = " ".join(parts)
    for label, needles in BANKS:
        if any(contains_term(blob, needle) for needle in needles):
            return label
    return ""


def _missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, dict, bytes)):
        return False
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    if isinstance(missing, bool):
        return missing
    return False


def unwrap_cell(value):
    """Sprowadza komórkę Excela do liczby, daty albo tekstu."""
    if isinstance(value, (list, tuple)):
        parts = [unwrap_cell(item) for item in value if not _missing(item)]
        parts = [item for item in parts if item is not None and str(item).strip() != ""]
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0]
        return " ".join(str(item) for item in parts)
    if isinstance(value, dict):
        return unwrap_cell(" ".join(str(item) for item in value.values()))
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (str, datetime, pd.Timestamp)):
        return value
    if hasattr(value, "tolist"):
        try:
            listed = value.tolist()
        except Exception:
            return value
        if listed is not value and isinstance(listed, (list, tuple, dict)):
            return unwrap_cell(listed)
        return listed
    return value


def parse_amount(value) -> float:
    value = unwrap_cell(value)
    if _missing(value) or isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none"}:
        return 0.0
    text = text.replace("\xa0", " ").replace("zł", "").replace("pln", "").replace("PLN", "")
    text = text.replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    text = re.sub(r"[^0-9.\-]", "", text)
    if text in {"", "-", ".", "-."}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_date(value):
    value = unwrap_cell(value)
    if _missing(value):
        return pd.NaT
    if isinstance(value, datetime):
        try:
            return pd.Timestamp(value.date())
        except (TypeError, ValueError):
            return pd.NaT
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return pd.NaT
        return pd.Timestamp(value.date())
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return pd.NaT
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%y"):
        try:
            return pd.Timestamp(datetime.strptime(text[:10], fmt).date())
        except ValueError:
            continue
    parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return pd.NaT
    return pd.Timestamp(parsed.date())


def _as_money(value) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = parse_amount(value)
    if number != number:
        return 0.0
    return number


def transaction_key(date, debit, credit, title: str, recipient: str = "") -> tuple:
    name = fold(title) or fold(recipient)
    when = ""
    if not _missing(date):
        try:
            stamp = pd.Timestamp(date)
            if not pd.isna(stamp):
                when = stamp.strftime("%Y-%m-%d")
        except (TypeError, ValueError, OverflowError):
            when = ""
    return (when, round(_as_money(debit), 2), round(_as_money(credit), 2), name)


def _column_index(columns: list[str], selected: str | None) -> int | None:
    if not selected:
        return None
    try:
        return columns.index(selected)
    except ValueError:
        return None


def mapped_preview(
    raw: pd.DataFrame,
    header_row: int,
    columns: list[str],
    mapping: dict[str, str | None],
    negative_is_debit: bool = True,
    limit: int = 10,
) -> pd.DataFrame:
    rows = extract_transactions(
        raw,
        header_row,
        columns,
        mapping,
        filename="",
        bank="",
        negative_is_debit=negative_is_debit,
    )
    visible = [COL_DATE, COL_TITLE, COL_RECIPIENT, COL_DEBIT, COL_CREDIT, COL_CURRENCY]
    if not rows:
        return pd.DataFrame(columns=visible)
    frame = pd.DataFrame(rows)
    return frame[visible].head(limit).reset_index(drop=True)


def extract_transactions(
    raw: pd.DataFrame,
    header_row: int,
    columns: list[str],
    mapping: dict[str, str | None],
    filename: str,
    bank: str,
    negative_is_debit: bool = True,
    uploaded_at: datetime | None = None,
) -> list[dict]:
    indexes = {field: _column_index(columns, mapping.get(field)) for field in list(TARGET_FIELDS) + [SIGNED_AMOUNT_FIELD]}
    stamp = pd.Timestamp(uploaded_at or datetime.now())
    body = raw.iloc[header_row + 1 :]
    rows: list[dict] = []
    for _, series in body.iterrows():
        values = series.tolist()

        def cell(field: str):
            index = indexes.get(field)
            if not isinstance(index, int) or isinstance(index, bool) or index >= len(values):
                return None
            value = unwrap_cell(values[index])
            if _missing(value):
                return None
            return value

        date = parse_date(cell(COL_DATE))
        title = "" if cell(COL_TITLE) is None else str(cell(COL_TITLE)).strip()
        recipient = "" if cell(COL_RECIPIENT) is None else str(cell(COL_RECIPIENT)).strip()
        currency = "" if cell(COL_CURRENCY) is None else str(cell(COL_CURRENCY)).strip() or "PLN"
        if not currency:
            currency = "PLN"

        debit = parse_amount(cell(COL_DEBIT)) if indexes.get(COL_DEBIT) is not None else 0.0
        credit = parse_amount(cell(COL_CREDIT)) if indexes.get(COL_CREDIT) is not None else 0.0
        if indexes.get(SIGNED_AMOUNT_FIELD) is not None and indexes.get(COL_DEBIT) is None and indexes.get(COL_CREDIT) is None:
            signed = parse_amount(cell(SIGNED_AMOUNT_FIELD))
            if negative_is_debit:
                if signed < 0:
                    debit, credit = abs(signed), 0.0
                elif signed > 0:
                    debit, credit = 0.0, signed
            else:
                if signed > 0:
                    debit, credit = signed, 0.0
                elif signed < 0:
                    debit, credit = 0.0, abs(signed)
        try:
            debit = abs(float(debit))
            credit = abs(float(credit))
        except (TypeError, ValueError):
            debit, credit = 0.0, 0.0
        if pd.isna(date) and debit == 0 and credit == 0 and not title and not recipient:
            continue
        if pd.isna(date):
            continue
        row = {column: "" for column in TX_COLUMNS}
        row.update(
            {
                COL_ID: str(uuid.uuid4()),
                COL_FILE: filename,
                COL_UPLOADED: stamp,
                COL_BANK: bank,
                COL_DATE: date,
                COL_TITLE: title,
                COL_RECIPIENT: recipient,
                COL_DEBIT: round(debit, 2),
                COL_CREDIT: round(credit, 2),
                COL_CURRENCY: currency,
            }
        )
        rows.append(row)
    return rows


def is_zero_amount(row: dict) -> bool:
    try:
        debit = abs(float(row.get(COL_DEBIT) or 0))
        credit = abs(float(row.get(COL_CREDIT) or 0))
    except (TypeError, ValueError):
        return True
    return round(debit, 2) == 0 and round(credit, 2) == 0


def split_new_and_duplicate(rows: list[dict], existing_keys: set[tuple]) -> tuple[list[dict], list[dict]]:
    kept: list[dict] = []
    duplicates: list[dict] = []
    seen = set(existing_keys)
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            key = transaction_key(
                row.get(COL_DATE),
                row.get(COL_DEBIT),
                row.get(COL_CREDIT),
                str(row.get(COL_TITLE) or ""),
                str(row.get(COL_RECIPIENT) or ""),
            )
        except Exception:
            continue
        if key in seen:
            duplicates.append(row)
            continue
        seen.add(key)
        kept.append(row)
    return kept, duplicates


def keys_from_frame(frame: pd.DataFrame) -> set[tuple]:
    if frame is None or frame.empty:
        return set()
    keys = set()
    for _, row in frame.iterrows():
        keys.add(
            transaction_key(
                row.get(COL_DATE),
                row.get(COL_DEBIT),
                row.get(COL_CREDIT),
                str(row.get(COL_TITLE) or ""),
                str(row.get(COL_RECIPIENT) or ""),
            )
        )
    return keys
