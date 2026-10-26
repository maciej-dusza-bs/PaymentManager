"""Wspólne elementy interfejsu: edycja reguł i ręczne przypisanie kategorii."""

from __future__ import annotations

import uuid

import pandas as pd
import streamlit as st

from pm.categorizer import Classification, describe_rule
from pm.schema import (
    AMOUNT_TYPES,
    CATEGORY_COLUMNS,
    COL_AMOUNT_MAX,
    COL_AMOUNT_MIN,
    COL_AMOUNT_TYPE,
    COL_BANK,
    COL_CATEGORY,
    COL_CREDIT,
    COL_CURRENCY,
    COL_DATE,
    COL_DEBIT,
    COL_FILE,
    COL_ID,
    COL_KEYWORD,
    COL_NOTE,
    COL_RECIPIENT,
    COL_SOURCE,
    COL_SUBCATEGORY,
    COL_TITLE,
    INTERNAL_CATEGORY,
    KEYWORD_COLUMNS,
    SHEET_CATEGORIES,
    SHEET_KEYWORDS,
    SOURCE_MANUAL,
    STATUS_CONFLICT,
)
from pm.storage import StorageError, load_db, save_db

RULES_SAVED = "rules_just_saved"


def rules_overview(categories: pd.DataFrame, keywords: pd.DataFrame) -> pd.DataFrame:
    rules = keywords.copy()
    rules["Zasada kwoty"] = [
        describe_rule(typ, lo, hi, fallback=not str(word).strip())
        for typ, lo, hi, word in zip(
            rules[COL_AMOUNT_TYPE],
            rules[COL_AMOUNT_MIN],
            rules[COL_AMOUNT_MAX],
            rules[COL_KEYWORD],
        )
    ]
    merged = categories.merge(rules, on=COL_CATEGORY, how="left")
    view = merged[[COL_CATEGORY, COL_NOTE, COL_SUBCATEGORY, COL_KEYWORD, "Zasada kwoty"]].copy()
    view[COL_KEYWORD] = view[COL_KEYWORD].fillna("")
    view[COL_SUBCATEGORY] = view[COL_SUBCATEGORY].fillna("")
    view["Zasada kwoty"] = view["Zasada kwoty"].fillna("")
    view = view.rename(columns={COL_NOTE: "Opis", COL_SUBCATEGORY: "Podkategoria", COL_KEYWORD: "Słowo kluczowe"})
    return view


def _frame(edited, columns: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame(edited).copy()
    for column in columns:
        if column not in frame.columns:
            frame[column] = ""
    return frame[columns]


def _merge(original: pd.DataFrame, edited: pd.DataFrame, column: str, filter_values: list[str] | None, show_all: bool) -> pd.DataFrame:
    if show_all or not filter_values:
        return edited.reset_index(drop=True)
    kept = original[~original[column].astype(str).isin(filter_values)].copy()
    return pd.concat([kept, edited], ignore_index=True)


def validate_rules(categories: pd.DataFrame, keywords: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    names = [str(name).strip() for name in categories[COL_CATEGORY].tolist()]
    names = [name for name in names if name]
    if len(names) != len(set(names)):
        errors.append("Nazwy kategorii muszą być unikalne.")
    if INTERNAL_CATEGORY not in names:
        errors.append("Kategoria „Wewnętrzne” jest wymagana i nie można jej usunąć.")
    known = set(names)
    for _, row in keywords.iterrows():
        category = str(row.get(COL_CATEGORY) or "").strip()
        word = str(row.get(COL_KEYWORD) or "").strip()
        label = word or "(reguła bez słowa kluczowego)"
        if not category:
            errors.append(f"Uzupełnij kategorię dla „{label}”.")
            continue
        if category not in known:
            errors.append(f"„{label}” wskazuje kategorię „{category}”, której nie ma na liście.")
        amount_type = str(row.get(COL_AMOUNT_TYPE) or "").strip().lower()
        if amount_type not in AMOUNT_TYPES:
            errors.append(f"Nieznany typ kwoty przy „{label}”.")
        lo = row.get(COL_AMOUNT_MIN)
        hi = row.get(COL_AMOUNT_MAX)
        if pd.notna(lo) and pd.notna(hi) and float(lo) > float(hi):
            errors.append(f"Kwota min jest większa od kwoty max przy „{label}”.")
    return errors


def _prepare(categories: pd.DataFrame, keywords: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    categories = _frame(categories, CATEGORY_COLUMNS)
    keywords = _frame(keywords, KEYWORD_COLUMNS)
    categories[COL_CATEGORY] = categories[COL_CATEGORY].fillna("").astype(str).str.strip()
    categories[COL_NOTE] = categories[COL_NOTE].fillna("").astype(str)
    categories = categories[categories[COL_CATEGORY] != ""]
    keywords[COL_CATEGORY] = keywords[COL_CATEGORY].fillna("").astype(str).str.strip()
    keywords[COL_SUBCATEGORY] = keywords[COL_SUBCATEGORY].fillna("").astype(str).str.strip()
    keywords[COL_KEYWORD] = keywords[COL_KEYWORD].fillna("").astype(str).str.strip()
    keywords[COL_AMOUNT_TYPE] = keywords[COL_AMOUNT_TYPE].fillna("dowolny").astype(str).str.strip().str.lower()
    keywords[COL_AMOUNT_MIN] = pd.to_numeric(keywords[COL_AMOUNT_MIN], errors="coerce")
    keywords[COL_AMOUNT_MAX] = pd.to_numeric(keywords[COL_AMOUNT_MAX], errors="coerce")
    keywords = keywords[keywords[COL_CATEGORY] != ""].copy()
    for index, row in keywords.iterrows():
        identifier = row[COL_ID]
        missing = identifier is None or (isinstance(identifier, float) and pd.isna(identifier))
        if missing or str(identifier).strip().lower() in {"", "none", "nan"}:
            keywords.at[index, COL_ID] = str(uuid.uuid4())
    return categories.reset_index(drop=True), keywords.reset_index(drop=True)


def render_rules_editor(prefix: str, highlight: list[str] | None = None) -> None:
    """Edycja kategorii i słów kluczowych. Po zapisie ustawia flagę RULES_SAVED i przeładowuje stronę."""
    db = load_db()
    categories = db[SHEET_CATEGORIES]
    keywords = db[SHEET_KEYWORDS]
    version = st.session_state.get(f"{prefix}_ver", 0)
    highlight = [name for name in (highlight or []) if name]
    show_all = True
    if highlight:
        st.caption("Widoczne są kategorie z tego konfliktu. Zapis nie usuwa pozostałych reguł.")
        show_all = st.checkbox("Pokaż wszystkie kategorie", value=False, key=f"{prefix}_all")
    filter_values = highlight if highlight and not show_all else None
    cat_view = categories if filter_values is None else categories[categories[COL_CATEGORY].isin(filter_values)]
    kw_view = keywords if filter_values is None else keywords[keywords[COL_CATEGORY].isin(filter_values)]
    if cat_view.empty:
        cat_view = pd.DataFrame(columns=CATEGORY_COLUMNS)
    if kw_view.empty:
        kw_view = pd.DataFrame(columns=KEYWORD_COLUMNS)

    st.markdown("**Kategorie**")
    edited_cats = st.data_editor(
        cat_view,
        num_rows="dynamic",
        hide_index=True,
        key=f"{prefix}_cats_{version}_{show_all}",
        column_config={
            COL_CATEGORY: st.column_config.TextColumn("Kategoria", required=True),
            COL_NOTE: st.column_config.TextColumn("Opis"),
        },
    )
    options = sorted(
        {
            str(name).strip()
            for name in list(categories[COL_CATEGORY]) + list(edited_cats.get(COL_CATEGORY, []))
            if str(name).strip()
        }
    )
    st.markdown("**Słowa kluczowe i zasady kwot**")
    st.caption("Puste słowo kluczowe to reguła zapasowa. Działa tylko wtedy, gdy nie pasuje żadne słowo.")
    edited_kw = st.data_editor(
        kw_view,
        num_rows="dynamic",
        hide_index=True,
        key=f"{prefix}_kw_{version}_{show_all}",
        column_config={
            COL_ID: st.column_config.TextColumn("ID", disabled=True),
            COL_CATEGORY: st.column_config.SelectboxColumn("Kategoria", options=options, required=True),
            COL_SUBCATEGORY: st.column_config.TextColumn("Podkategoria"),
            COL_KEYWORD: st.column_config.TextColumn("Słowo kluczowe"),
            COL_AMOUNT_TYPE: st.column_config.SelectboxColumn("Typ kwoty", options=AMOUNT_TYPES, required=True),
            COL_AMOUNT_MIN: st.column_config.NumberColumn("Kwota min", min_value=0.0, step=1.0),
            COL_AMOUNT_MAX: st.column_config.NumberColumn("Kwota max", min_value=0.0, step=1.0),
        },
    )
    if st.button("Zapisz reguły", key=f"{prefix}_save", type="primary"):
        merged_cats = _merge(_frame(categories, CATEGORY_COLUMNS), _frame(edited_cats, CATEGORY_COLUMNS), COL_CATEGORY, filter_values, filter_values is None)
        merged_kw = _merge(_frame(keywords, KEYWORD_COLUMNS), _frame(edited_kw, KEYWORD_COLUMNS), COL_CATEGORY, filter_values, filter_values is None)
        clean_cats, clean_kw = _prepare(merged_cats, merged_kw)
        errors = validate_rules(clean_cats, clean_kw)
        if errors:
            for error in errors:
                st.error(error)
            return
        db[SHEET_CATEGORIES] = clean_cats
        db[SHEET_KEYWORDS] = clean_kw
        try:
            save_db(db)
        except StorageError as exc:
            st.error(str(exc))
            return
        st.session_state[f"{prefix}_ver"] = version + 1
        st.session_state[RULES_SAVED] = True
        st.rerun()


def _fmt_date(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except Exception:
        return str(value)


def _money(txn: dict, column: str) -> str:
    currency = txn.get(COL_CURRENCY) or "PLN"
    try:
        amount = float(txn.get(column) or 0)
    except (TypeError, ValueError):
        amount = 0.0
    formatted = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
    return f"{formatted} {currency}"


def render_transaction_details(txn: dict) -> None:
    left, middle, right = st.columns(3)
    left.metric("Data transakcji", _fmt_date(txn.get(COL_DATE)))
    middle.metric("Obciążenie", _money(txn, COL_DEBIT))
    right.metric("Uznanie", _money(txn, COL_CREDIT))
    st.write(f"**Tytuł:** {txn.get(COL_TITLE) or '—'}")
    st.write(f"**Odbiorca:** {txn.get(COL_RECIPIENT) or '—'}")
    st.caption(f"Bank: {txn.get(COL_BANK) or '—'}  ·  Plik: {txn.get(COL_FILE) or '—'}  ·  Waluta: {txn.get(COL_CURRENCY) or 'PLN'}")


def _chosen_subcategory(hits, category: str) -> str:
    same = [hit for hit in hits if hit.category == category and (hit.subcategory or "").strip()]
    unique = list(dict.fromkeys(hit.subcategory.strip() for hit in same))
    return unique[0] if len(unique) == 1 else ""


def render_manual_resolution(txn: dict, classification: Classification, prefix: str) -> dict | None:
    """Zwraca uzupełniony wiersz, gdy użytkownik podejmie decyzję w tym przebiegu."""
    render_transaction_details(txn)
    hits = classification.hits
    choice = None
    subcategory = None

    if classification.status == STATUS_CONFLICT and hits:
        st.warning("Transakcja pasuje do kilku kategorii. Wybierz właściwą albo popraw listę reguł.")
        table = pd.DataFrame(
            [
                {
                    "Kategoria": hit.category,
                    "Podkategoria": hit.subcategory or "",
                    "Słowo kluczowe": hit.keyword or "(reguła zapasowa)",
                    "Zasada kwoty": hit.label(),
                }
                for hit in hits
            ]
        )
        st.dataframe(table, hide_index=True, width="stretch")
        categories = list(dict.fromkeys(hit.category for hit in hits))
        columns = st.columns(len(categories))
        for index, category in enumerate(categories):
            if columns[index].button(f"Wybierz: {category}", key=f"{prefix}_hit_{category}"):
                choice = category
                subcategory = _chosen_subcategory(hits, category)
    else:
        st.info("Nie udało się przypisać kategorii. Wskaż ją ręcznie albo dodaj słowo kluczowe.")

    db = load_db()
    all_categories = db[SHEET_CATEGORIES][COL_CATEGORY].tolist()
    note_key = f"{prefix}_note"
    if note_key not in st.session_state:
        st.session_state[note_key] = str(txn.get(COL_NOTE) or "")
    selected = st.selectbox("Inna kategoria", [""] + all_categories, key=f"{prefix}_sel")
    typed_sub = st.text_input("Podkategoria", key=f"{prefix}_sub")
    note = st.text_input("Opis", key=note_key)
    assign, leave = st.columns(2)
    if assign.button("Przypisz wybraną kategorię", key=f"{prefix}_assign"):
        if not selected:
            st.error("Wybierz kategorię z listy.")
        else:
            choice = selected
            subcategory = typed_sub
    if leave.button("Zostaw bez kategorii", key=f"{prefix}_leave"):
        updated = dict(txn)
        updated[COL_CATEGORY] = ""
        updated[COL_SUBCATEGORY] = ""
        updated[COL_NOTE] = note
        updated[COL_SOURCE] = SOURCE_MANUAL
        return updated

    highlight = list(dict.fromkeys(hit.category for hit in hits))
    with st.expander("Popraw kategorie i słowa kluczowe", expanded=classification.status == STATUS_CONFLICT):
        render_rules_editor(f"{prefix}_rules", highlight or None)

    if choice:
        updated = dict(txn)
        updated[COL_CATEGORY] = choice
        updated[COL_SUBCATEGORY] = subcategory if subcategory is not None else typed_sub
        updated[COL_NOTE] = note
        updated[COL_SOURCE] = SOURCE_MANUAL
        return updated
    return None
