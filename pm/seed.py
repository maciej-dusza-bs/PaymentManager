"""Domyślne kategorie i słowa kluczowe przy pierwszym uruchomieniu."""

from __future__ import annotations

import uuid

import pandas as pd

from pm.schema import (
    ACCOUNT_COLUMNS,
    AMOUNT_ANY,
    AMOUNT_CREDIT,
    AMOUNT_DEBIT,
    CATEGORY_COLUMNS,
    COL_AMOUNT_MAX,
    COL_AMOUNT_MIN,
    COL_AMOUNT_TYPE,
    COL_CATEGORY,
    COL_ID,
    COL_KEYWORD,
    COL_NOTE,
    COL_SUBCATEGORY,
    INTERNAL_CATEGORY,
    KEYWORD_COLUMNS,
    TX_COLUMNS,
)

# (kategoria, opis)
CATEGORIES: list[tuple[str, str]] = [
    ("Opłaty stałe", "Abonamenty, komorne, opłaty stałe"),
    ("Koszty", "Koszty uzyskania przychodu do zwrotu"),
    ("Dochody", "Wszelkie przychody"),
    ("Podatki", "Obciążenia od odsetek, podatki, itp."),
    ("Wypłaty", "Wypłaty gotówkowe z bankomatów"),
    ("Jedzenie", "Zakupy spożywcze"),
    ("Restauracje", "Zamówienia jedzenia i jedzenie w restauracji"),
    ("Zdrowie", "Wizyty u lekarzy, zakup leków"),
    ("Domowe", "Jednorazowe zakupy do domu – meble, rzeczy do remontów, itp."),
    ("Yoshi", "Karma dla psa, weterynarz"),
    ("Rozrywka", "Wszelkie wydatki na rozrywkę"),
    ("Transport", "Paliwo i transport publiczny"),
    (INTERNAL_CATEGORY, "Przelewy między własnymi kontami"),
]

# (kategoria, słowo, typ kwoty, min, max). Puste słowo = reguła zapasowa.
KEYWORDS: list[tuple[str, str, str, float | None, float | None]] = [
    ("Opłaty stałe", "Komorne", AMOUNT_DEBIT, 0, 2000),
    ("Opłaty stałe", "e-on", AMOUNT_DEBIT, 0, 2000),
    ("Opłaty stałe", "plus", AMOUNT_DEBIT, 0, 2000),
    ("Opłaty stałe", "Netflix", AMOUNT_DEBIT, 0, 2000),
    ("Opłaty stałe", "Youtube", AMOUNT_DEBIT, 0, 2000),
    ("Dochody", "Pensja", AMOUNT_CREDIT, None, None),
    ("Dochody", "PORR", AMOUNT_CREDIT, None, None),
    ("Dochody", "Wynagrodzenie", AMOUNT_CREDIT, None, None),
    ("Dochody", "Odsetki", AMOUNT_CREDIT, None, None),
    ("Dochody", "", AMOUNT_CREDIT, None, None),
    ("Podatki", "Podatek", AMOUNT_ANY, None, None),
    ("Wypłaty", "Wypłata", AMOUNT_DEBIT, None, None),
    ("Wypłaty", "Bankomat", AMOUNT_DEBIT, None, None),
    ("Jedzenie", "Frisco", AMOUNT_DEBIT, 0, 500),
    ("Jedzenie", "Tesco", AMOUNT_DEBIT, 0, 500),
    ("Jedzenie", "Biedronka", AMOUNT_DEBIT, 0, 500),
    ("Jedzenie", "Lidl", AMOUNT_DEBIT, 0, 500),
    ("Jedzenie", "Spożywczy", AMOUNT_DEBIT, 0, 500),
    ("Jedzenie", "warzywa", AMOUNT_DEBIT, 0, 500),
    ("Restauracje", "Restauracja", AMOUNT_DEBIT, 0, 600),
    ("Restauracje", "obiad", AMOUNT_DEBIT, 0, 600),
    ("Restauracje", "pyszne", AMOUNT_DEBIT, 0, 600),
    ("Zdrowie", "Lekarz", AMOUNT_ANY, None, None),
    ("Zdrowie", "apteka", AMOUNT_ANY, None, None),
    ("Domowe", "Allegro", AMOUNT_ANY, None, None),
    ("Yoshi", "Weterynarz", AMOUNT_ANY, None, None),
    ("Yoshi", "karma", AMOUNT_ANY, None, None),
    ("Yoshi", "smaczki", AMOUNT_ANY, None, None),
    ("Rozrywka", "Empik", AMOUNT_ANY, None, None),
    ("Rozrywka", "kino", AMOUNT_ANY, None, None),
    ("Transport", "Benzyna", AMOUNT_ANY, None, None),
    ("Transport", "Orlen", AMOUNT_ANY, None, None),
    ("Transport", "Shell", AMOUNT_ANY, None, None),
    ("Transport", "Circle", AMOUNT_ANY, None, None),
    ("Transport", "ztm", AMOUNT_ANY, None, None),
    ("Transport", "jakdojade", AMOUNT_ANY, None, None),
]


def _blank(value: float | None) -> float | None:
    return None if value is None else float(value)


def seed_frames() -> dict[str, pd.DataFrame]:
    categories = pd.DataFrame(
        [{COL_CATEGORY: name, COL_NOTE: desc} for name, desc in CATEGORIES],
        columns=CATEGORY_COLUMNS,
    )
    keywords = pd.DataFrame(
        [
            {
                COL_ID: str(uuid.uuid4()),
                COL_CATEGORY: cat,
                COL_SUBCATEGORY: "",
                COL_KEYWORD: word,
                COL_AMOUNT_TYPE: typ,
                COL_AMOUNT_MIN: _blank(lo),
                COL_AMOUNT_MAX: _blank(hi),
            }
            for cat, word, typ, lo, hi in KEYWORDS
        ],
        columns=KEYWORD_COLUMNS,
    )
    accounts = pd.DataFrame(columns=ACCOUNT_COLUMNS)
    transactions = pd.DataFrame(columns=TX_COLUMNS)
    return {
        "categories": categories,
        "keywords": keywords,
        "accounts": accounts,
        "transactions": transactions,
    }

