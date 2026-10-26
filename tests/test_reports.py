"""Testy udziału wydatków w raportach."""

import pandas as pd

from pm.pages.reports import amount_slices, chosen_label, expense_slices, matching_transactions, month_span
from pm.schema import COL_CATEGORY, COL_CREDIT, COL_DATE, COL_DEBIT, COL_SUBCATEGORY


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            COL_DATE: pd.to_datetime(["2026-01-10", "2026-01-20", "2026-02-05", "2026-02-11"]),
            COL_CATEGORY: ["Jedzenie", "Jedzenie", "Transport", "Jedzenie"],
            COL_SUBCATEGORY: ["Spożywcze", "", "Benzyna", "Spożywcze"],
            COL_DEBIT: [100, 50, 100, 300],
        }
    )


def test_shares_are_spending_percent_and_monthly_average():
    slices = expense_slices(_frame(), by_subcategory=False, months=month_span("2026-01-01", "2026-02-28"))
    assert month_span("2026-01-01", "2026-02-28") == 2
    by_name = slices.set_index("Etykieta")
    assert by_name.loc["Jedzenie", "Suma"] == 450
    assert by_name.loc["Jedzenie", "Średnio miesięcznie"] == 225
    assert round(by_name.loc["Jedzenie", "Procent"], 2) == 81.82
    assert by_name.loc["Transport", "Średnio miesięcznie"] == 50


def test_subcategory_split_keeps_category_name():
    slices = expense_slices(_frame(), by_subcategory=True, months=2)
    labels = set(slices["Etykieta"])
    assert labels == {"Jedzenie / Spożywcze", "Jedzenie / Bez podkategorii", "Transport / Benzyna"}
    food = slices.set_index("Etykieta").loc["Jedzenie / Spożywcze", "Suma"]
    assert food == 400


def test_income_slices_use_credits():
    frame = _frame()
    frame[COL_CREDIT] = [0, 1000, 0, 200]
    slices = amount_slices(frame, COL_CREDIT, by_subcategory=True, months=2)
    by_name = slices.set_index("Etykieta")
    assert by_name.loc["Jedzenie / Bez podkategorii", "Suma"] == 1000
    assert by_name.loc["Jedzenie / Spożywcze", "Suma"] == 200
    assert "Transport / Benzyna" not in by_name.index


def test_matching_transactions_follow_the_slice_and_amount():
    matched = matching_transactions(_frame(), "Jedzenie", by_subcategory=False, amount_column=COL_DEBIT)
    assert list(matched[COL_DEBIT]) == [300, 100, 50]
    split = matching_transactions(_frame(), "Jedzenie / Spożywcze", by_subcategory=True, amount_column=COL_DEBIT)
    assert list(split[COL_DEBIT]) == [300, 100]


def test_latest_click_chooses_the_label():
    state = chosen_label({}, "", "")
    state = chosen_label(state, "Jedzenie", "")
    assert state["label"] == "Jedzenie"
    state = chosen_label(state, "Jedzenie", "Transport")
    assert state["label"] == "Transport"
    state = chosen_label(state, "Domowe", "Transport")
    assert state["label"] == "Domowe"
