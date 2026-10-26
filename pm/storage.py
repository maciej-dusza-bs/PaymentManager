"""Odczyt i zapis bazy w pliku Excel, z kopią zapasową."""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from pm.schema import (
    ACCOUNT_COLUMNS,
    CATEGORY_COLUMNS,
    COL_ACCOUNT_NAME,
    COL_ACCOUNT_NUMBER,
    COL_AMOUNT_MAX,
    COL_AMOUNT_MIN,
    COL_AMOUNT_TYPE,
    COL_CATEGORY,
    COL_CREDIT,
    COL_DATE,
    COL_DEBIT,
    COL_ID,
    COL_KEYWORD,
    COL_NOTE,
    COL_SUBCATEGORY,
    COL_UPLOADED,
    INTERNAL_CATEGORY,
    KEYWORD_COLUMNS,
    SHEET_ACCOUNTS,
    SHEET_CATEGORIES,
    SHEET_KEYWORDS,
    SHEET_TRANSACTIONS,
    TX_COLUMNS,
)
from pm.seed import CATEGORIES, seed_frames

BACKUP_KEEP = 30


class StorageError(Exception):
    pass


def data_path() -> Path:
    override = os.environ.get("PM_DATA_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "data" / "baza.xlsx"


def _backup_dir(path: Path) -> Path:
    return path.parent / "backup"


def _coerce_transactions(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty and (df is None or len(df.columns) == 0):
        return pd.DataFrame(columns=TX_COLUMNS)
    frame = df.copy()
    for column in TX_COLUMNS:
        if column not in frame.columns:
            frame[column] = "" if column not in (COL_DEBIT, COL_CREDIT, COL_DATE, COL_UPLOADED) else pd.NA
    frame = frame[TX_COLUMNS]
    for column in (COL_DEBIT, COL_CREDIT):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    frame[COL_DATE] = pd.to_datetime(frame[COL_DATE], errors="coerce")
    frame[COL_UPLOADED] = pd.to_datetime(frame[COL_UPLOADED], errors="coerce")
    text_cols = [c for c in TX_COLUMNS if c not in (COL_DEBIT, COL_CREDIT, COL_DATE, COL_UPLOADED)]
    for column in text_cols:
        frame[column] = frame[column].fillna("").astype(str).replace({"nan": ""})
    return frame


def _coerce_categories(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or len(getattr(df, "columns", [])) == 0:
        frame = pd.DataFrame(columns=CATEGORY_COLUMNS)
    else:
        frame = df.copy()
        for column in CATEGORY_COLUMNS:
            if column not in frame.columns:
                frame[column] = ""
        frame = frame[CATEGORY_COLUMNS]
        frame[COL_CATEGORY] = frame[COL_CATEGORY].fillna("").astype(str).str.strip()
        frame[COL_NOTE] = frame[COL_NOTE].fillna("").astype(str)
        frame = frame[frame[COL_CATEGORY] != ""]
    names = set(frame[COL_CATEGORY].tolist())
    if INTERNAL_CATEGORY not in names:
        desc = next((item[1] for item in CATEGORIES if item[0] == INTERNAL_CATEGORY), "")
        extra = pd.DataFrame([{COL_CATEGORY: INTERNAL_CATEGORY, COL_NOTE: desc}])
        frame = pd.concat([frame, extra], ignore_index=True)
    return frame.reset_index(drop=True)


def _coerce_keywords(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or len(getattr(df, "columns", [])) == 0:
        return pd.DataFrame(columns=KEYWORD_COLUMNS)
    frame = df.copy()
    for column in KEYWORD_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame = frame[KEYWORD_COLUMNS]
    frame[COL_CATEGORY] = frame[COL_CATEGORY].fillna("").astype(str).str.strip()
    frame[COL_SUBCATEGORY] = frame[COL_SUBCATEGORY].fillna("").astype(str).str.strip().replace({"nan": ""})
    frame[COL_KEYWORD] = frame[COL_KEYWORD].fillna("").astype(str).replace({"nan": ""})
    frame[COL_AMOUNT_TYPE] = frame[COL_AMOUNT_TYPE].fillna("dowolny").astype(str).str.strip().str.lower()
    frame[COL_AMOUNT_MIN] = pd.to_numeric(frame[COL_AMOUNT_MIN], errors="coerce")
    frame[COL_AMOUNT_MAX] = pd.to_numeric(frame[COL_AMOUNT_MAX], errors="coerce")
    frame[COL_ID] = frame[COL_ID].fillna("").astype(str).replace({"nan": ""})
    frame = frame[frame[COL_CATEGORY] != ""]
    return frame.reset_index(drop=True)


def _coerce_accounts(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or len(getattr(df, "columns", [])) == 0:
        return pd.DataFrame(columns=ACCOUNT_COLUMNS)
    frame = df.copy()
    for column in ACCOUNT_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    frame = frame[ACCOUNT_COLUMNS]
    frame[COL_ACCOUNT_NAME] = frame[COL_ACCOUNT_NAME].fillna("").astype(str).str.strip()
    frame[COL_ACCOUNT_NUMBER] = frame[COL_ACCOUNT_NUMBER].fillna("").astype(str).str.strip()
    frame = frame[(frame[COL_ACCOUNT_NAME] != "") | (frame[COL_ACCOUNT_NUMBER] != "")]
    return frame.reset_index(drop=True)


def empty_db() -> dict[str, pd.DataFrame]:
    seeded = seed_frames()
    return {
        SHEET_TRANSACTIONS: _coerce_transactions(seeded["transactions"]),
        SHEET_CATEGORIES: _coerce_categories(seeded["categories"]),
        SHEET_KEYWORDS: _coerce_keywords(seeded["keywords"]),
        SHEET_ACCOUNTS: _coerce_accounts(seeded["accounts"]),
    }


def load_db(path: Path | None = None) -> dict[str, pd.DataFrame]:
    path = path or data_path()
    if not path.exists():
        db = empty_db()
        save_db(db, path)
        return db
    sheets = pd.read_excel(path, sheet_name=None, engine="openpyxl")
    return {
        SHEET_TRANSACTIONS: _coerce_transactions(sheets.get(SHEET_TRANSACTIONS, pd.DataFrame())),
        SHEET_CATEGORIES: _coerce_categories(sheets.get(SHEET_CATEGORIES, pd.DataFrame())),
        SHEET_KEYWORDS: _coerce_keywords(sheets.get(SHEET_KEYWORDS, pd.DataFrame())),
        SHEET_ACCOUNTS: _coerce_accounts(sheets.get(SHEET_ACCOUNTS, pd.DataFrame())),
    }


def _prune_backups(directory: Path) -> None:
    files = sorted(directory.glob("baza_*.xlsx"), key=lambda item: item.stat().st_mtime, reverse=True)
    for old in files[BACKUP_KEEP:]:
        old.unlink(missing_ok=True)


def save_db(db: dict[str, pd.DataFrame], path: Path | None = None) -> None:
    path = path or data_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = _backup_dir(path)
        backup.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, backup / f"baza_{stamp}.xlsx")
        _prune_backups(backup)

    ordered = {
        SHEET_TRANSACTIONS: _coerce_transactions(db[SHEET_TRANSACTIONS]),
        SHEET_CATEGORIES: _coerce_categories(db[SHEET_CATEGORIES]),
        SHEET_KEYWORDS: _coerce_keywords(db[SHEET_KEYWORDS]),
        SHEET_ACCOUNTS: _coerce_accounts(db[SHEET_ACCOUNTS]),
    }
    temporary = path.with_suffix(".tmp.xlsx")
    try:
        with pd.ExcelWriter(temporary, engine="openpyxl") as writer:
            for name, frame in ordered.items():
                frame.to_excel(writer, sheet_name=name, index=False)
        os.replace(temporary, path)
    except PermissionError as exc:
        temporary.unlink(missing_ok=True)
        raise StorageError(
            "Nie mogę zapisać bazy. Zamknij plik baza.xlsx, jeśli jest otwarty w Excelu, i spróbuj ponownie."
        ) from exc
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
