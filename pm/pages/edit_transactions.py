"""Prosta edycja zapisanych transakcji."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from pm.schema import (
    COL_CATEGORY,
    COL_DATE,
    COL_ID,
    COL_NOTE,
    COL_SOURCE,
    COL_SUBCATEGORY,
    COL_TITLE,
    SHEET_CATEGORIES,
    SHEET_TRANSACTIONS,
    SOURCE_MANUAL,
    TX_COLUMNS,
)
from pm.storage import StorageError, load_db, save_db


def render() -> None:
    st.header("Edytuj transakcje")
    st.caption("Zmiana kategorii tutaj nie zmienia reguł. Historia trzyma przypisanie, które zapiszesz.")
    db = load_db()
    transactions = db[SHEET_TRANSACTIONS]
    if transactions.empty:
        st.info("Brak transakcji.")
        return

    categories = [""] + db[SHEET_CATEGORIES][COL_CATEGORY].tolist()
    names = ["Wszystkie"] + sorted({str(name) for name in transactions[COL_CATEGORY].tolist() if str(name).strip()})
    picked = st.selectbox("Kategoria", names)
    dated = transactions[transactions[COL_DATE].notna()]
    if dated.empty:
        start = end = pd.Timestamp.today().date()
    else:
        start = dated[COL_DATE].min().date()
        end = dated[COL_DATE].max().date()
    chosen = st.date_input("Zakres dat", value=(start, end))
    view = transactions.copy()
    if isinstance(chosen, (tuple, list)) and len(chosen) == 2:
        lo, hi = chosen
        mask = view[COL_DATE].dt.date.between(lo, hi) | view[COL_DATE].isna()
        view = view[mask]
    if picked != "Wszystkie":
        view = view[view[COL_CATEGORY] == picked]
    if view.empty:
        st.info("Brak transakcji dla tego filtra.")
        return

    shown = view.copy()
    shown[COL_DATE] = pd.to_datetime(shown[COL_DATE], errors="coerce").dt.strftime("%Y-%m-%d")
    edited = st.data_editor(
        shown,
        hide_index=True,
        width="stretch",
        num_rows="fixed",
        key="edit_tx",
        column_config={
            COL_ID: st.column_config.TextColumn("ID", disabled=True),
            COL_CATEGORY: st.column_config.SelectboxColumn("Kategoria", options=categories),
            COL_DATE: st.column_config.TextColumn("Data Transakcji", disabled=True),
        },
    )
    if st.button("Zapisz", type="primary"):
        by_id = {str(row[COL_ID]): row for row in edited.to_dict("records")}
        updated = transactions.copy()
        for index, row in updated.iterrows():
            edit = by_id.get(str(row[COL_ID]))
            if not edit:
                continue
            for column in TX_COLUMNS:
                if column in (COL_ID, COL_DATE):
                    continue
                updated.at[index, column] = edit.get(column, row[column])
            if str(edit.get(COL_CATEGORY) or "") != str(row.get(COL_CATEGORY) or "") or str(edit.get(COL_SUBCATEGORY) or "") != str(row.get(COL_SUBCATEGORY) or "") or str(edit.get(COL_NOTE) or "") != str(row.get(COL_NOTE) or "") or str(edit.get(COL_TITLE) or "") != str(row.get(COL_TITLE) or ""):
                updated.at[index, COL_SOURCE] = SOURCE_MANUAL
        db[SHEET_TRANSACTIONS] = updated
        try:
            save_db(db)
        except StorageError as exc:
            st.error(str(exc))
            return
        st.success("Zapisano zmiany.")
