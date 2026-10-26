"""Kategorie, słowa kluczowe i ponowne przeliczenie historii."""

from __future__ import annotations

import streamlit as st

from pm.categorizer import classify_row, unresolved_ids
from pm.schema import (
    COL_CATEGORY,
    COL_ID,
    COL_SOURCE,
    COL_SUBCATEGORY,
    SHEET_ACCOUNTS,
    SHEET_CATEGORIES,
    SHEET_KEYWORDS,
    SHEET_TRANSACTIONS,
    SOURCE_AUTO,
    SOURCE_MANUAL,
    STATUS_ASSIGNED,
)
from pm.storage import StorageError, load_db, save_db
from pm.ui import RULES_SAVED, render_manual_resolution, render_rules_editor, rules_overview


def _apply_reclass(queue: list[str]) -> list[str]:
    db = load_db()
    frame = db[SHEET_TRANSACTIONS]
    classes: dict = {}
    still: list[str] = []
    for row_id in queue:
        matches = frame.index[frame[COL_ID].astype(str) == row_id].tolist()
        if not matches:
            continue
        index = matches[0]
        record = frame.loc[index].to_dict()
        if str(record.get(COL_SOURCE) or "") == SOURCE_MANUAL:
            continue
        classification = classify_row(record, db[SHEET_KEYWORDS], db[SHEET_ACCOUNTS])
        classes[row_id] = classification
        if classification.status == STATUS_ASSIGNED:
            frame.at[index, COL_CATEGORY] = classification.category or ""
            frame.at[index, COL_SUBCATEGORY] = classification.subcategory or ""
            frame.at[index, COL_SOURCE] = SOURCE_AUTO
        else:
            still.append(row_id)
    db[SHEET_TRANSACTIONS] = frame
    save_db(db)
    stored = st.session_state.setdefault("recalc_classes", {})
    stored.update(classes)
    return unresolved_ids(still, classes)


def render() -> None:
    st.header("Kategorie")
    if st.session_state.pop(RULES_SAVED, False) and st.session_state.get("recalc_queue"):
        try:
            st.session_state["recalc_queue"] = _apply_reclass(list(st.session_state["recalc_queue"]))
        except StorageError as exc:
            st.error(str(exc))
        else:
            st.rerun()

    queue = st.session_state.get("recalc_queue") or []
    if queue:
        _render_queue(queue)
        return

    db = load_db()
    st.dataframe(rules_overview(db[SHEET_CATEGORIES], db[SHEET_KEYWORDS]), hide_index=True, width="stretch")
    st.divider()
    render_rules_editor("categories")
    st.divider()
    st.caption("Przeliczenie używa zapisanych reguł. Najpierw kliknij „Zapisz reguły”, jeśli coś zmieniałeś.")
    overwrite = st.checkbox("Nadpisz również ręcznie przypisane kategorie", key="recalc_overwrite")
    if st.button("Przelicz historię", type="primary"):
        _recalculate(overwrite)


def _recalculate(overwrite: bool) -> None:
    from pm.categorizer import recategorize

    db = load_db()
    updated, stats = recategorize(db[SHEET_TRANSACTIONS], db[SHEET_KEYWORDS], db[SHEET_ACCOUNTS], overwrite)
    db[SHEET_TRANSACTIONS] = updated
    try:
        save_db(db)
    except StorageError as exc:
        st.error(str(exc))
        return
    st.session_state["recalc_classes"] = {}
    st.session_state["recalc_queue"] = stats.conflict_ids
    st.success(
        f"Zmieniono {stats.changed}, wyczyszczono {stats.cleared}, "
        f"pominięto ręcznych {stats.skipped_manual}, konflikty: {stats.conflicts}."
    )
    if stats.conflict_ids:
        st.rerun()


def _render_queue(queue: list[str]) -> None:
    st.subheader("Rozstrzygnij konflikty")
    st.caption(f"Zostało {len(queue)}. Dotychczasowa kategoria zostaje, dopóki jej nie zmienisz.")
    db = load_db()
    frame = db[SHEET_TRANSACTIONS]
    row_id = queue[0]
    matches = frame.index[frame[COL_ID].astype(str) == row_id].tolist()
    if not matches:
        st.session_state["recalc_queue"] = queue[1:]
        st.rerun()
    record = frame.loc[matches[0]].to_dict()
    classes = st.session_state.setdefault("recalc_classes", {})
    classification = classes.get(row_id) or classify_row(record, db[SHEET_KEYWORDS], db[SHEET_ACCOUNTS])
    classes[row_id] = classification
    decision = render_manual_resolution(record, classification, f"recalc_{row_id}")
    if decision:
        for key, value in decision.items():
            frame.at[matches[0], key] = value
        db[SHEET_TRANSACTIONS] = frame
        try:
            save_db(db)
        except StorageError as exc:
            st.error(str(exc))
            return
        st.session_state["recalc_queue"] = queue[1:]
        st.rerun()
