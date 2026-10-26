"""Pobranie historii transakcji do pliku Excel."""

from __future__ import annotations

from io import BytesIO

import pandas as pd
import streamlit as st

from pm.schema import SHEET_TRANSACTIONS
from pm.storage import load_db


def render() -> None:
    st.header("Export historii")
    transactions = load_db()[SHEET_TRANSACTIONS]
    st.write(f"Transakcji w bazie: {len(transactions)}.")
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        transactions.to_excel(writer, index=False, sheet_name=SHEET_TRANSACTIONS)
    st.download_button(
        "Pobierz historię (Excel)",
        data=buffer.getvalue(),
        file_name="historia_transakcji.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )
