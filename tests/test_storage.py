"""Testy zapisu bazy Excel i pełnej ścieżki importu."""

from io import BytesIO

import pandas as pd

from pm.categorizer import annotate_rows
from pm.importer import analyze_sheet, extract_transactions, read_sheet, read_workbook, split_new_and_duplicate
from pm.schema import COL_CATEGORY, COL_ID, SHEET_CATEGORIES, SHEET_KEYWORDS, SHEET_TRANSACTIONS
from pm.seed import seed_frames
from pm.storage import load_db, save_db


def test_roundtrip_creates_seed_categories(tmp_path):
    path = tmp_path / "baza.xlsx"
    save_db(
        {
            SHEET_TRANSACTIONS: seed_frames()["transactions"],
            SHEET_CATEGORIES: seed_frames()["categories"],
            SHEET_KEYWORDS: seed_frames()["keywords"],
            "Konta": seed_frames()["accounts"],
        },
        path,
    )
    loaded = load_db(path)
    names = loaded[SHEET_CATEGORIES][COL_CATEGORY].tolist()
    assert "Jedzenie" in names
    assert "Wewnętrzne" in names
    keywords = loaded[SHEET_KEYWORDS]
    assert (keywords["Słowo kluczowe"] == "Biedronka").any()
    fallback = keywords[(keywords[COL_CATEGORY] == "Dochody") & (keywords["Słowo kluczowe"] == "")]
    assert len(fallback) == 1
    assert loaded[SHEET_TRANSACTIONS].empty


def test_excel_import_is_categorized_and_deduplicated(tmp_path):
    frame = pd.DataFrame(
        [
            ["Data operacji", "Opis", "Kwota", "Waluta"],
            ["2024-01-10", "Lidl zakupy", -40, "PLN"],
            ["2024-01-11", "Allegro Biedronka", -30, "PLN"],
            ["2024-01-10", "Lidl zakupy", -40, "PLN"],
        ]
    )
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Wyciąg")
    workbook = read_workbook(buffer.getvalue(), "mbank.xlsx")
    raw = read_sheet(workbook, "Wyciąg")
    preview = analyze_sheet(raw)
    rows = extract_transactions(raw, preview.header_row, preview.columns, preview.mapping, "mbank.xlsx", "mBank")
    kept, duplicates = split_new_and_duplicate(rows, set())
    assert len(duplicates) == 1
    seeded = seed_frames()
    classes = annotate_rows(kept, seeded["keywords"], seeded["accounts"])
    by_title = {row["Tytuł"]: row for row in kept}
    assert by_title["Lidl zakupy"][COL_CATEGORY] == "Jedzenie"
    assert classes[by_title["Allegro Biedronka"][COL_ID]].status == "konflikt"

    path = tmp_path / "baza.xlsx"
    db = {
        SHEET_TRANSACTIONS: pd.DataFrame(kept),
        SHEET_CATEGORIES: seeded["categories"],
        SHEET_KEYWORDS: seeded["keywords"],
        "Konta": seeded["accounts"],
    }
    save_db(db, path)
    loaded = load_db(path)
    assert len(loaded[SHEET_TRANSACTIONS]) == 2
    again = extract_transactions(raw, preview.header_row, preview.columns, preview.mapping, "mbank.xlsx", "mBank")
    fresh, duplicates_again = split_new_and_duplicate(again, set())
    from pm.importer import keys_from_frame

    fresh, duplicates_again = split_new_and_duplicate(again, keys_from_frame(loaded[SHEET_TRANSACTIONS]))
    assert fresh == []
    assert len(duplicates_again) == 3
