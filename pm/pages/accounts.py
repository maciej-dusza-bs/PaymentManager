"""Konta użytkownika służą do rozpoznawania przelewów wewnętrznych."""

from __future__ import annotations

import streamlit as st

from pm.schema import ACCOUNT_COLUMNS, COL_ACCOUNT_NAME, COL_ACCOUNT_NUMBER, SHEET_ACCOUNTS
from pm.storage import StorageError, load_db, save_db


def render() -> None:
    st.header("Konta użytkownika")
    st.caption("Jeśli tytuł lub odbiorca zawiera numer albo nazwę konta z tej listy, transakcja dostaje kategorię „Wewnętrzne”.")
    db = load_db()
    accounts = db[SHEET_ACCOUNTS]
    if accounts.empty:
        accounts = accounts.reindex(columns=ACCOUNT_COLUMNS)
    edited = st.data_editor(
        accounts,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key="accounts_editor",
        column_config={
            COL_ACCOUNT_NAME: st.column_config.TextColumn("Nazwa", required=True),
            COL_ACCOUNT_NUMBER: st.column_config.TextColumn("Numer konta"),
        },
    )
    if st.button("Zapisz", type="primary"):
        db[SHEET_ACCOUNTS] = edited
        try:
            save_db(db)
        except StorageError as exc:
            st.error(str(exc))
            return
        st.success("Zapisano konta.")
