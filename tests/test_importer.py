"""Testy wczytywania wyciągów."""

import pandas as pd

from pm.importer import (
    analyze_sheet,
    extract_transactions,
    guess_bank,
    parse_amount,
    parse_date,
    split_new_and_duplicate,
)
from pm.schema import COL_CREDIT, COL_CURRENCY, COL_DATE, COL_DEBIT, COL_TITLE


def _statement() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["Wyciąg mBank", None, None, None],
            ["Data operacji", "Opis transakcji", "Kwota", "Waluta"],
            ["01.02.2024", "Biedronka zakupy", "-12,50", "PLN"],
            ["02.02.2024", "Wynagrodzenie", "5 000,00", "PLN"],
            ["01.02.2024", "Biedronka zakupy", "-12,50", "PLN"],
        ]
    )


def test_parse_amount_and_date():
    assert parse_amount("1 234,56") == 1234.56
    assert parse_amount("1.234,56") == 1234.56
    assert parse_amount("-10,50") == -10.5
    assert parse_date("01.02.2024") == pd.Timestamp("2024-02-01")
    assert parse_date("2024-03-05") == pd.Timestamp("2024-03-05")


def test_header_mapping_signed_amount_and_dedup():
    raw = _statement()
    preview = analyze_sheet(raw)
    assert preview.header_row == 1
    assert preview.mapping[COL_DATE] == "Data operacji"
    assert preview.mapping["Kwota"] == "Kwota"
    assert preview.mapping[COL_DEBIT] is None
    rows = extract_transactions(
        raw,
        preview.header_row,
        preview.columns,
        preview.mapping,
        filename="wyciag_mbank.xlsx",
        bank="mBank",
    )
    assert len(rows) == 3
    assert rows[0][COL_DEBIT] == 12.5
    assert rows[0][COL_CREDIT] == 0
    assert rows[1][COL_CREDIT] == 5000
    kept, duplicates = split_new_and_duplicate(rows, set())
    assert len(kept) == 2
    assert len(duplicates) == 1
    assert guess_bank("wyciag_mbank.xlsx", raw) == "mBank"


def test_prefers_transaction_date_and_first_currency_column():
    raw = pd.DataFrame(
        [
            ["Lista transakcji", None, None, None, None],
            [None, None, None, None, None],
            ["Data transakcji", "Data księgowania", "Tytuł", "Kwota transakcji (waluta rachunku)", "Waluta"],
            ["2025-12-23", "2025-12-25", "Zakupy", "-94,00", "PLN"],
        ]
    )
    # druga kolumna Waluta jest pusta i nie powinna wygrać
    raw.loc[2, 5] = "Waluta"
    raw.loc[3, 5] = None
    preview = analyze_sheet(raw)
    assert preview.header_row == 2
    assert preview.mapping[COL_DATE] == "Data transakcji"
    assert preview.mapping["Kwota"] == "Kwota transakcji (waluta rachunku)"
    assert preview.mapping[COL_CURRENCY] == "Waluta"
    rows = extract_transactions(raw, preview.header_row, preview.columns, preview.mapping, "ing.xlsx", "ING")
    assert rows[0][COL_DATE] == pd.Timestamp("2025-12-23")
    assert rows[0][COL_DEBIT] == 94
    assert rows[0][COL_CURRENCY] == "PLN"


def test_zero_amount_is_invalid():
    from pm.importer import is_zero_amount

    assert is_zero_amount({COL_DEBIT: 0, COL_CREDIT: 0})
    assert is_zero_amount({COL_DEBIT: 0.0, COL_CREDIT: 0.0})
    assert not is_zero_amount({COL_DEBIT: 0, COL_CREDIT: 10})
    assert not is_zero_amount({COL_DEBIT: 1.5, COL_CREDIT: 0})


def test_bank_name_does_not_match_inside_another_word():
    raw = pd.DataFrame([["Booking date", "Amount"], ["2024-01-01", 10]])
    assert guess_bank("statement.xlsx", raw) == ""


def test_messy_cells_are_imported_without_error():
    raw = pd.DataFrame(
        [
            ["Nagłówek banku", None, {"opis": "wyciąg"}],
            ["Data operacji", "Opis transakcji", "Kwota"],
            ["01.02.2024", ["Biedronka", "zakupy"], "-12,50 PLN"],
            ["nie-data", "stopka", "razem"],
            [None, None, None],
            ["2024-03-01 00:00:00", "Wynagrodzenie", "5 000,00"],
        ]
    )
    preview = analyze_sheet(raw)
    rows = extract_transactions(raw, preview.header_row, preview.columns, preview.mapping, "bank.xlsx", "mBank")
    assert rows
    assert rows[0][COL_TITLE] == "Biedronka zakupy"
    assert rows[0][COL_DEBIT] == 12.5
    kept, duplicates = split_new_and_duplicate(["zły wiersz", *rows, rows[0]], set())
    assert len(duplicates) == 1
    assert all(isinstance(row, dict) for row in kept)


def test_separate_debit_and_credit_columns():
    raw = pd.DataFrame(
        [
            ["Data księgowania", "Tytuł", "Odbiorca", "Obciążenia", "Uznania", "Waluta"],
            ["2024-05-01", "Orlen", "Stacja", "200,00", None, "PLN"],
        ]
    )
    preview = analyze_sheet(raw)
    assert preview.mapping[COL_DEBIT] == "Obciążenia"
    assert preview.mapping[COL_CREDIT] == "Uznania"
    assert preview.mapping["Kwota"] is None
    rows = extract_transactions(raw, preview.header_row, preview.columns, preview.mapping, "pko.xlsx", "PKO BP")
    assert rows[0][COL_DEBIT] == 200
    assert rows[0][COL_TITLE] == "Orlen"
