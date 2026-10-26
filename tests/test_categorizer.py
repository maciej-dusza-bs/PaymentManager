"""Testy kategoryzacji."""

from pm.categorizer import annotate_rows, classify_transaction, recategorize
from pm.schema import (
    COL_CATEGORY,
    COL_CREDIT,
    COL_DEBIT,
    COL_ID,
    COL_RECIPIENT,
    COL_SOURCE,
    COL_SUBCATEGORY,
    COL_TITLE,
    INTERNAL_CATEGORY,
    SOURCE_MANUAL,
    STATUS_ASSIGNED,
    STATUS_CONFLICT,
    STATUS_NONE,
)
from pm.seed import seed_frames


def _rules():
    frames = seed_frames()
    return frames["keywords"], frames["accounts"]


def test_grocery_within_limit():
    keywords, accounts = _rules()
    result = classify_transaction("Zakupy Biedronka", "", 80, 0, keywords, accounts)
    assert result.status == STATUS_ASSIGNED
    assert result.category == "Jedzenie"
    assert result.subcategory == ""


def test_grocery_above_limit_is_unassigned():
    keywords, accounts = _rules()
    result = classify_transaction("Biedronka", "", 800, 0, keywords, accounts)
    assert result.status == STATUS_NONE


def test_several_keywords_same_category_are_not_a_conflict():
    keywords, accounts = _rules()
    result = classify_transaction("Lidl warzywa", "", 40, 0, keywords, accounts)
    assert result.status == STATUS_ASSIGNED
    assert result.category == "Jedzenie"
    assert result.subcategory == ""


def test_two_categories_are_a_conflict():
    keywords, accounts = _rules()
    result = classify_transaction("Allegro i Biedronka", "sklep", 100, 0, keywords, accounts)
    assert result.status == STATUS_CONFLICT
    assert {hit.category for hit in result.hits} == {"Domowe", "Jedzenie"}


def test_keyword_matches_whole_word_in_title_or_recipient():
    import pandas as pd

    from pm.schema import COL_AMOUNT_MAX, COL_AMOUNT_MIN

    keywords, accounts = _rules()
    extra = keywords.iloc[:1].copy()
    extra[COL_CATEGORY] = "Restauracje"
    extra["Słowo kluczowe"] = "kebab"
    extra[COL_AMOUNT_MIN] = 0
    extra[COL_AMOUNT_MAX] = 600
    keywords = pd.concat([keywords, extra], ignore_index=True)
    glued = classify_transaction("Płatność", "kebabBistro", 35, 0, keywords, accounts)
    folded = classify_transaction("KEBÁB na mieście", "", 35, 0, keywords, accounts)
    in_recipient = classify_transaction("Płatność kartą", "Kebab", 35, 0, keywords, accounts)
    assert glued.status == STATUS_NONE
    assert folded.status == STATUS_ASSIGNED
    assert folded.category == "Restauracje"
    assert in_recipient.status == STATUS_ASSIGNED
    assert in_recipient.category == "Restauracje"


def test_income_keyword_beats_fallback():
    keywords, accounts = _rules()
    result = classify_transaction("Wynagrodzenie PORR", "", 0, 8000, keywords, accounts)
    assert result.status == STATUS_ASSIGNED
    assert result.category == "Dochody"
    assert result.subcategory == ""


def test_any_credit_falls_back_to_income():
    keywords, accounts = _rules()
    result = classify_transaction("Wpływ nieznany", "", 0, 15, keywords, accounts)
    assert result.status == STATUS_ASSIGNED
    assert result.category == "Dochody"
    assert result.subcategory == ""


def test_unknown_debit_stays_empty():
    keywords, accounts = _rules()
    result = classify_transaction("Sklep XYZ", "", 15, 0, keywords, accounts)
    assert result.status == STATUS_NONE


def test_internal_phrase_wins_over_keywords():
    keywords, accounts = _rules()
    result = classify_transaction("Przelew wewnętrzny Biedronka", "", 40, 0, keywords, accounts)
    assert result.status == STATUS_ASSIGNED
    assert result.category == INTERNAL_CATEGORY


def test_own_account_number_is_internal():
    keywords, accounts = _rules()
    accounts.loc[len(accounts)] = ["Rachunek", "12 3456 7890 1234 5678 9012 3456"]
    result = classify_transaction("Przelew", "12345678901234567890123456", 200, 0, keywords, accounts)
    assert result.category == INTERNAL_CATEGORY


def test_recategorize_keeps_conflicts_and_manual_rows():
    keywords, accounts = _rules()
    from pm.schema import TX_COLUMNS
    import pandas as pd

    rows = pd.DataFrame(
        [
            {
                COL_ID: "1",
                COL_TITLE: "Allegro Biedronka",
                COL_RECIPIENT: "",
                COL_DEBIT: 50,
                COL_CREDIT: 0,
                COL_CATEGORY: "Domowe",
                COL_SUBCATEGORY: "",
                COL_SOURCE: "auto",
            },
            {
                COL_ID: "2",
                COL_TITLE: "Biedronka",
                COL_RECIPIENT: "",
                COL_DEBIT: 20,
                COL_CREDIT: 0,
                COL_CATEGORY: "Rozrywka",
                COL_SUBCATEGORY: "",
                COL_SOURCE: SOURCE_MANUAL,
            },
        ]
    )
    for column in TX_COLUMNS:
        if column not in rows.columns:
            rows[column] = ""
    updated, stats = recategorize(rows, keywords, accounts, overwrite_manual=False)
    conflict = updated[updated[COL_ID] == "1"].iloc[0]
    manual = updated[updated[COL_ID] == "2"].iloc[0]
    assert conflict[COL_CATEGORY] == "Domowe"
    assert stats.conflicts == 1
    assert stats.conflict_ids == ["1"]
    assert manual[COL_CATEGORY] == "Rozrywka"
    assert stats.skipped_manual == 1


def test_annotate_assigns_and_clears_conflict():
    keywords, accounts = _rules()
    rows = [
        {COL_ID: "a", COL_TITLE: "Lidl", COL_RECIPIENT: "", COL_DEBIT: 10, COL_CREDIT: 0, COL_SOURCE: ""},
        {COL_ID: "b", COL_TITLE: "Allegro Biedronka", COL_RECIPIENT: "", COL_DEBIT: 10, COL_CREDIT: 0, COL_SOURCE: ""},
    ]
    classes = annotate_rows(rows, keywords, accounts)
    assert rows[0][COL_CATEGORY] == "Jedzenie"
    assert classes["b"].status == STATUS_CONFLICT
    assert rows[1][COL_CATEGORY] == ""


def test_subcategory_comes_from_the_keyword_rule():
    import pandas as pd

    from pm.schema import COL_AMOUNT_MAX, COL_AMOUNT_MIN, COL_AMOUNT_TYPE, COL_KEYWORD

    keywords = pd.DataFrame(
        [
            {
                COL_ID: "1",
                COL_CATEGORY: "Jedzenie",
                COL_SUBCATEGORY: "Spożywcze",
                COL_KEYWORD: "Biedronka",
                COL_AMOUNT_TYPE: "obciążenie",
                COL_AMOUNT_MIN: 0,
                COL_AMOUNT_MAX: 500,
            },
            {
                COL_ID: "2",
                COL_CATEGORY: "Jedzenie",
                COL_SUBCATEGORY: "Napoje",
                COL_KEYWORD: "kawa",
                COL_AMOUNT_TYPE: "obciążenie",
                COL_AMOUNT_MIN: None,
                COL_AMOUNT_MAX: None,
            },
        ]
    )
    single = classify_transaction("Biedronka", "", 40, 0, keywords, pd.DataFrame())
    assert single.status == STATUS_ASSIGNED
    assert single.category == "Jedzenie"
    assert single.subcategory == "Spożywcze"
    clash = classify_transaction("Biedronka kawa", "", 40, 0, keywords, pd.DataFrame())
    assert clash.status == STATUS_CONFLICT
    assert {hit.subcategory for hit in clash.hits} == {"Spożywcze", "Napoje"}
