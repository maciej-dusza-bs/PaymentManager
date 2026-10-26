"""Payment Manager — lokalna aplikacja do analizy wydatków i przychodów."""

from __future__ import annotations

import streamlit as st

from pm.pages import accounts, add_transactions, categories, edit_transactions, export, home, reports

st.set_page_config(page_title="Payment Manager", layout="wide")

PAGES = [
    ("Ekran główny", "home", home),
    ("Raporty", "reports", reports),
    ("Dodaj transakcje", "add", add_transactions),
    ("Edytuj transakcje", "edit", edit_transactions),
    ("Konta użytkownika", "accounts", accounts),
    ("Kategorie", "categories", categories),
    ("Export historii", "export", export),
]

if "page" not in st.session_state:
    st.session_state.page = "home"

with st.sidebar:
    st.title("Payment Manager")
    st.caption("Wydatki i przychody")
    for label, key, _module in PAGES:
        if st.button(label, key=f"nav_{key}", width="stretch", type="primary" if st.session_state.page == key else "secondary"):
            st.session_state.page = key
            st.rerun()

for _label, key, module in PAGES:
    if st.session_state.page == key:
        module.render()
        break
