"""Testy filtrowania ekranu głównego."""

import pandas as pd

from pm.pages.home import (
    UNCATEGORIZED,
    category_color,
    default_date_range,
    filter_transactions,
    month_category_amounts,
    normalize_range,
    ordered_categories,
)
from pm.schema import COL_CATEGORY, COL_CREDIT, COL_DATE, COL_DEBIT, INTERNAL_CATEGORY


def _frame() -> pd.DataFrame:
    rows = [
        ("2026-01-10", "Jedzenie", 40, 0),
        ("2026-01-20", "Dochody", 0, 1000),
        ("2026-02-05", "Jedzenie", 15, 0),
        ("2026-03-01", "Transport", 70, 0),
        ("2026-01-15", INTERNAL_CATEGORY, 500, 0),
        ("2026-02-11", "", 8, 0),
        ("2025-06-01", "Jedzenie", 9, 0),
    ]
    return pd.DataFrame(
        {
            COL_DATE: pd.to_datetime([row[0] for row in rows]),
            COL_CATEGORY: [row[1] for row in rows],
            COL_DEBIT: [row[2] for row in rows],
            COL_CREDIT: [row[3] for row in rows],
        }
    )


def test_filter_keeps_selected_categories_and_inclusive_dates():
    from pm.pages.home import _prepare

    prepared = _prepare(_frame())
    filtered = filter_transactions(prepared, "2026-01-10", "2026-02-11", ["Jedzenie", UNCATEGORIZED])
    assert set(filtered["_kategoria"]) == {"Jedzenie", UNCATEGORIZED}
    assert len(filtered) == 3
    assert INTERNAL_CATEGORY not in set(prepared["_kategoria"])


def test_monthly_amounts_split_categories_and_sign():
    from pm.pages.home import _prepare

    prepared = _prepare(_frame())
    filtered = filter_transactions(prepared, "2026-01-01", "2026-02-28", ["Jedzenie", "Dochody"])
    periods, series, balance = month_category_amounts(filtered, "2026-01-01", "2026-02-28", ["Dochody", "Jedzenie"])
    assert periods[:2] == ["2026-01", "2026-02"]
    assert series["Jedzenie"][0] == -40
    assert series["Dochody"][0] == 1000
    assert series["Jedzenie"][1] == -15
    assert balance[0] == 960


def test_date_helpers_and_stable_colors():
    start, end = default_date_range("2024-01-01", "2026-10-25")
    assert end.isoformat() == "2026-10-25"
    assert start.isoformat() == "2025-11-01"
    assert normalize_range(("2026-05-02", "2026-01-01"), "2026-01-01", "2026-05-02") == ("2026-01-01", "2026-05-02")
    names = ordered_categories(["Jedzenie", "", UNCATEGORIZED, "Dochody", "Jedzenie"])
    assert names == ["Dochody", "Jedzenie", UNCATEGORIZED]
    assert category_color("Dochody", names) != category_color("Jedzenie", names)


def test_table_uses_chart_filters_and_clicked_month():
    from pm.pages.home import _prepare, months_from_points, transaction_table
    from pm.schema import COL_RECIPIENT, COL_SUBCATEGORY, COL_TITLE

    frame = _frame()
    frame[COL_TITLE] = ["Biedronka", "Pensja", "Lidl", "Orlen", "Przelew", "Apteka", "Sklep"]
    frame[COL_RECIPIENT] = ["Sklep", "Firma", "Sklep", "Stacja", "Ja", "Apteka", "Sklep"]
    frame[COL_SUBCATEGORY] = ["Spożywcze", "Wynagrodzenie", "", "Benzyna", "", "Leki", ""]
    prepared = _prepare(frame)
    filtered = filter_transactions(prepared, "2026-01-01", "2026-03-31", ["Jedzenie", "Dochody", UNCATEGORIZED])
    everything = transaction_table(filtered)
    assert list(everything["Kategoria"]) == [UNCATEGORIZED, "Jedzenie", "Dochody", "Jedzenie"]
    assert list(everything["Podkategoria"]) == ["Leki", "", "Wynagrodzenie", "Spożywcze"]
    january = transaction_table(filtered, ("2026-01",))
    assert list(january["Tytuł"]) == ["Pensja", "Biedronka"]
    assert list(january["Odbiorca"]) == ["Firma", "Sklep"]
    assert january["Uznania"].sum() == 1000
    assert months_from_points([{"customdata": "2026-02", "x": "luty 2026"}, {"x": "2026-01-01"}]) == ("2026-02", "2026-01")
