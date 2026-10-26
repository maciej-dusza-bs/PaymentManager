"""Kreator wczytywania wyciągów i kategoryzacji nowych transakcji."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from pm.categorizer import annotate_rows, unresolved_ids
from pm.importer import (
    SIGNED_AMOUNT_FIELD,
    detect_mapping,
    extract_transactions,
    guess_bank,
    header_columns,
    is_zero_amount,
    keys_from_frame,
    mapped_preview,
    read_sheet,
    read_workbook,
    split_new_and_duplicate,
    transaction_key,
)
from pm.schema import (
    COL_BANK,
    COL_CATEGORY,
    COL_CREDIT,
    COL_CURRENCY,
    COL_DATE,
    COL_DEBIT,
    COL_FILE,
    COL_ID,
    COL_NOTE,
    COL_RECIPIENT,
    COL_SOURCE,
    COL_SUBCATEGORY,
    COL_TITLE,
    SHEET_ACCOUNTS,
    SHEET_CATEGORIES,
    SHEET_KEYWORDS,
    SHEET_TRANSACTIONS,
    SOURCE_MANUAL,
    TARGET_FIELDS,
)
from pm.storage import StorageError, load_db, save_db
from pm.ui import RULES_SAVED, render_manual_resolution

FIELD_LABELS = {
    COL_DATE: "Data Transakcji",
    COL_TITLE: "Tytuł",
    COL_RECIPIENT: "Odbiorca",
    COL_DEBIT: "Obciążenia",
    COL_CREDIT: "Uznania",
    COL_CURRENCY: "Waluta",
    SIGNED_AMOUNT_FIELD: "Kwota ze znakiem",
}


def _fresh() -> dict:
    return {
        "step": "upload",
        "files": [],
        "index": 0,
        "sheet": None,
        "detect_nonce": 0,
        "rows": [],
        "classes": {},
        "queue": [],
        "duplicates": [],
        "invalid": [],
        "review_version": 0,
        "header_row": 0,
        "mapping": {},
        "columns": [],
        "bank": "",
        "_map_key": None,
        "notice": "",
    }


def _wizard() -> dict:
    if "import_wizard" not in st.session_state or st.session_state.import_wizard is None:
        st.session_state.import_wizard = _fresh()
    return st.session_state.import_wizard


def _known_keys(rows: list) -> set[tuple]:
    keys = keys_from_frame(load_db()[SHEET_TRANSACTIONS])
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            keys.add(transaction_key(row.get(COL_DATE), row.get(COL_DEBIT), row.get(COL_CREDIT), str(row.get(COL_TITLE) or ""), str(row.get(COL_RECIPIENT) or "")))
        except Exception:
            continue
    return keys


def _start_resolution(imp: dict) -> None:
    ids = [str(row.get(COL_ID)) for row in imp["rows"] if isinstance(row, dict) and row.get(COL_ID)]
    imp["queue"] = unresolved_ids(ids, imp["classes"] if isinstance(imp.get("classes"), dict) else {})
    imp["step"] = "resolve" if imp["queue"] else "review"


def _reclassify_queue(imp: dict) -> None:
    db = load_db()
    pending = set(imp["queue"])
    found = annotate_rows(imp["rows"], db[SHEET_KEYWORDS], db[SHEET_ACCOUNTS], pending)
    imp["classes"].update(found)
    imp["queue"] = unresolved_ids(list(imp["queue"]), imp["classes"])


def render() -> None:
    st.header("Dodaj transakcje")
    imp = _wizard()
    if st.button("Zacznij od nowa"):
        st.session_state.import_wizard = _fresh()
        st.rerun()
    if imp.get("notice"):
        st.success(imp["notice"])
    if imp["step"] == "upload":
        _render_upload(imp)
    elif imp["step"] == "file":
        _render_file(imp)
    elif imp["step"] == "resolve":
        _render_resolve(imp)
    else:
        _render_review(imp)


def _render_upload(imp: dict) -> None:
    st.write("Wskaż jeden lub wiele plików Excel z wyciągami.")
    uploaded = st.file_uploader(
        "Pliki wyciągów",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
        key="upload_statements",
    )
    if st.button("Wczytaj pliki", type="primary", disabled=not uploaded):
        imp["files"] = [{"name": item.name, "data": item.getvalue()} for item in uploaded]
        imp["index"] = 0
        imp["sheet"] = None
        imp["step"] = "file"
        imp["notice"] = ""
        st.rerun()


def _render_file(imp: dict) -> None:
    files = imp.get("files")
    index = imp.get("index", 0)
    if not isinstance(files, list) or not isinstance(index, int):
        st.error("Zapis kreatora jest nieczytelny. Zacznij import od nowa.")
        return
    if index >= len(files):
        _start_resolution(imp)
        st.rerun()
    current = files[index]
    if not isinstance(current, dict) or "data" not in current:
        st.error("Nie mogę odczytać wskazanego pliku. Wczytaj go ponownie.")
        return
    filename = str(current.get("name") or "wyciąg")
    st.subheader(f"Plik {index + 1} z {len(files)}: {filename}")
    try:
        workbook = read_workbook(current["data"], filename)
    except Exception as exc:
        st.error(f"Nie mogę odczytać pliku: {exc}")
        if st.button("Pomiń plik"):
            _advance(imp, "Pominięto plik, którego nie udało się odczytać.")
        return

    sheets = workbook.sheet_names
    if len(sheets) > 1 and not imp.get("sheet"):
        choice = st.radio("W pliku jest kilka arkuszy. Wybierz źródło transakcji.", sheets, key=f"sheet_{imp['index']}_{imp['detect_nonce']}")
        if st.button("Użyj tego arkusza", type="primary"):
            imp["sheet"] = choice
            st.rerun()
        return

    sheet = imp.get("sheet") or sheets[0]
    imp["sheet"] = sheet
    if len(sheets) == 1:
        st.caption(f"Arkusz: {sheet}")
    raw = read_sheet(workbook, sheet)
    state_key = f"{imp['index']}:{sheet}:{imp['detect_nonce']}"
    if imp.get("_map_key") != state_key:
        from pm.importer import analyze_sheet

        detected = analyze_sheet(raw)
        imp["_map_key"] = state_key
        imp["header_row"] = detected.header_row
        imp["columns"] = detected.columns
        imp["mapping"] = dict(detected.mapping)
        imp["bank"] = guess_bank(filename, raw)

    hr_key = f"hr_{state_key}"
    if hr_key not in st.session_state:
        st.session_state[hr_key] = int(imp["header_row"]) + 1
    header_excel = st.number_input(
        "Wiersz nagłówka (numer wiersza w Excelu)",
        min_value=1,
        max_value=max(len(raw), 1),
        step=1,
        key=hr_key,
    )
    if int(header_excel) - 1 != int(imp["header_row"]):
        imp["header_row"] = int(header_excel) - 1
        imp["columns"] = header_columns(raw, imp["header_row"])
        imp["mapping"] = detect_mapping(raw, imp["header_row"])
        st.rerun()

    st.write("Dopasowanie kolumn. Zostaw „(brak)”, jeśli kolumny nie ma w pliku.")
    options = ["(brak)"] + [str(name) for name in imp["columns"]]
    widget_key = f"{state_key}:{imp['header_row']}"
    left, right = st.columns(2)
    for field_index, field in enumerate(TARGET_FIELDS + [SIGNED_AMOUNT_FIELD]):
        chosen = imp["mapping"].get(field) or "(brak)"
        if chosen not in options:
            chosen = "(brak)"
        slot = left if field_index % 2 == 0 else right
        selected = slot.selectbox(
            FIELD_LABELS[field],
            options,
            index=options.index(chosen),
            key=f"map_{widget_key}_{field}",
        )
        imp["mapping"][field] = None if selected == "(brak)" else selected

    bank_key = f"bank_{state_key}"
    if bank_key not in st.session_state:
        st.session_state[bank_key] = imp.get("bank") or ""
    imp["bank"] = st.text_input("Bank", key=bank_key)
    negative_is_debit = st.checkbox("Ujemna kwota w kolumnie „Kwota ze znakiem” oznacza obciążenie", value=True, key=f"sign_{state_key}")

    st.markdown("**Podgląd rozpoznanych danych**")
    try:
        preview = mapped_preview(raw, int(imp["header_row"]), list(imp["columns"]), imp["mapping"], negative_is_debit)
    except Exception as exc:
        st.error(f"Nie mogę pokazać podglądu. Zmień wiersz nagłówka albo dopasowanie kolumn. ({exc})")
        preview = None
    if preview is not None:
        st.dataframe(preview, hide_index=True, width="stretch")

    accept, redetect, skip = st.columns(3)
    if accept.button("Akceptuj i wczytaj", type="primary"):
        try:
            _accept_file(imp, raw, filename, negative_is_debit)
        except Exception as exc:
            st.error(
                "Nie udało się wczytać tego pliku. Sprawdź wiersz nagłówka i przypisanie kolumn. "
                f"Jeśli układ jest niestandardowy, popraw go ręcznie. Szczegóły: {exc}"
            )
    if redetect.button("Wykryj nagłówki ponownie"):
        imp["detect_nonce"] += 1
        imp["_map_key"] = None
        st.rerun()
    if skip.button("Pomiń plik"):
        _advance(imp, f"Pominięto plik {filename}.")

    replacement = st.file_uploader("Wczytaj ten plik ponownie", type=["xlsx", "xls"], key=f"replace_{state_key}")
    if replacement is not None and st.button("Zastąp plik"):
        imp["files"][imp["index"]] = {"name": replacement.name, "data": replacement.getvalue()}
        imp["sheet"] = None
        imp["detect_nonce"] += 1
        imp["_map_key"] = None
        st.rerun()


def _accept_file(imp: dict, raw: pd.DataFrame, filename: str, negative_is_debit: bool) -> None:
    mapping = imp.get("mapping")
    columns = imp.get("columns")
    if not isinstance(mapping, dict) or not isinstance(columns, list):
        st.error("Brak dopasowania kolumn. Wykryj nagłówki ponownie.")
        return
    if not mapping.get(COL_DATE) or mapping.get(COL_DATE) == "(brak)":
        st.error("Wskaż kolumnę z datą transakcji.")
        return
    if not any(mapping.get(field) and mapping.get(field) != "(brak)" for field in (COL_DEBIT, COL_CREDIT, SIGNED_AMOUNT_FIELD)):
        st.error("Wskaż kolumnę obciążeń, uznań albo kwoty ze znakiem.")
        return
    try:
        header_row = int(imp.get("header_row") or 0)
    except (TypeError, ValueError):
        st.error("Numer wiersza nagłówka jest niepoprawny.")
        return
    extracted = extract_transactions(
        raw,
        header_row,
        [str(name) for name in columns],
        mapping,
        filename=filename,
        bank=str(imp.get("bank") or ""),
        negative_is_debit=negative_is_debit,
    )
    valid = [row for row in extracted if isinstance(row, dict) and not is_zero_amount(row)]
    invalid = [row for row in extracted if isinstance(row, dict) and is_zero_amount(row)]
    kept, duplicates = split_new_and_duplicate(valid, _known_keys(imp["rows"]))
    db = load_db()
    classes = annotate_rows(kept, db[SHEET_KEYWORDS], db[SHEET_ACCOUNTS])
    imp["rows"].extend(kept)
    imp.setdefault("duplicates", []).extend(duplicates)
    imp.setdefault("invalid", []).extend(invalid)
    imp["classes"].update(classes)
    _advance(
        imp,
        f"{filename}: nowych {len(kept)}, duplikatów {len(duplicates)}, błędnych (kwota 0) {len(invalid)}.",
    )


def _advance(imp: dict, notice: str) -> None:
    imp["notice"] = notice
    imp["index"] += 1
    imp["sheet"] = None
    imp["_map_key"] = None
    if imp["index"] >= len(imp["files"]):
        _start_resolution(imp)
    st.rerun()


def _render_resolve(imp: dict) -> None:
    if st.session_state.pop(RULES_SAVED, False):
        _reclassify_queue(imp)
        if not imp["queue"]:
            imp["step"] = "review"
        st.rerun()
    if not imp["queue"]:
        imp["step"] = "review"
        st.rerun()
    row_id = imp["queue"][0]
    row = next(item for item in imp["rows"] if item[COL_ID] == row_id)
    classification = imp["classes"].get(row_id)
    st.caption(f"Do rozstrzygnięcia: {len(imp['queue'])} (najpierw konflikty, potem brak kategorii).")
    decision = render_manual_resolution(row, classification, f"imp_{row_id}")
    if decision:
        row.update(decision)
        imp["queue"] = imp["queue"][1:]
        if not imp["queue"]:
            imp["step"] = "review"
        st.rerun()


def _render_review(imp: dict) -> None:
    st.subheader("Sprawdź nowe transakcje")
    duplicates = imp.setdefault("duplicates", [])
    invalid = imp.setdefault("invalid", [])
    st.write(f"Nowych: {len(imp['rows'])}. Duplikatów: {len(duplicates)}. Błędnych: {len(invalid)}.")
    if not imp["rows"] and not duplicates and not invalid:
        st.info("Żadna transakcja nie była nowa. Historia pozostała bez zmian.")
        if st.button("Wróć do ekranu głównego", type="primary"):
            st.session_state.import_wizard = _fresh()
            st.session_state.page = "home"
            st.rerun()
        return

    if imp["rows"]:
        edited = _render_new_rows(imp)
    else:
        edited = None
    _render_duplicates(imp)
    _render_invalid(imp)
    approve, cancel = st.columns(2)
    if imp["rows"] and approve.button("Zatwierdź", type="primary"):
        _commit(imp, edited)
    if cancel.button("Anuluj import"):
        st.session_state.import_wizard = _fresh()
        st.rerun()


def _fmt_tx(row: dict) -> str:
    when = row.get(COL_DATE)
    try:
        when = pd.Timestamp(when).strftime("%Y-%m-%d")
    except Exception:
        when = str(when or "—")
    title = str(row.get(COL_TITLE) or "—")
    recipient = str(row.get(COL_RECIPIENT) or "—")
    return f"{when} · {title} · {recipient} · obciążenie {row.get(COL_DEBIT)} · uznanie {row.get(COL_CREDIT)} {row.get(COL_CURRENCY) or ''}"


def _render_duplicates(imp: dict) -> None:
    duplicates = imp.get("duplicates") or []
    if not duplicates:
        return
    st.subheader("Zduplikowane transakcje")
    st.caption("Są już w historii albo powtarzają się w tym imporcie. Kliknij „Dodaj”, żeby mimo to zapisać kopię.")
    for row in list(duplicates):
        info, action = st.columns([5, 1])
        info.write(_fmt_tx(row))
        if action.button("Dodaj", key=f"add_dup_{row.get(COL_ID)}"):
            db = load_db()
            classes = annotate_rows([row], db[SHEET_KEYWORDS], db[SHEET_ACCOUNTS])
            imp["classes"].update(classes)
            imp["rows"].append(row)
            imp["duplicates"] = [item for item in duplicates if item.get(COL_ID) != row.get(COL_ID)]
            imp["review_version"] = imp.get("review_version", 0) + 1
            st.rerun()


def _render_invalid(imp: dict) -> None:
    invalid = imp.get("invalid") or []
    if not invalid:
        return
    st.subheader("Błędne transakcje")
    st.warning("Kwota wynosi 0. Te wiersze nie zostaną zapisane.")
    frame = pd.DataFrame(invalid)
    visible = [column for column in (COL_DATE, COL_TITLE, COL_RECIPIENT, COL_DEBIT, COL_CREDIT, COL_CURRENCY, COL_BANK, COL_FILE) if column in frame.columns]
    shown = frame[visible].copy()
    if COL_DATE in shown.columns:
        shown[COL_DATE] = pd.to_datetime(shown[COL_DATE], errors="coerce").dt.strftime("%Y-%m-%d")
    st.dataframe(shown, hide_index=True, width="stretch")


def _render_new_rows(imp: dict) -> pd.DataFrame:
    db = load_db()
    categories = [""] + db[SHEET_CATEGORIES][COL_CATEGORY].tolist()
    frame = pd.DataFrame(imp["rows"])
    visible = frame[
        [COL_DATE, COL_TITLE, COL_RECIPIENT, COL_DEBIT, COL_CREDIT, COL_CURRENCY, COL_BANK, COL_FILE, COL_CATEGORY, COL_SUBCATEGORY, COL_NOTE, COL_ID]
    ].copy()
    visible[COL_DATE] = pd.to_datetime(visible[COL_DATE], errors="coerce").dt.strftime("%Y-%m-%d")
    return st.data_editor(
        visible,
        hide_index=True,
        width="stretch",
        key=f"import_review_{imp.get('review_version', 0)}",
        column_config={
            COL_DATE: st.column_config.TextColumn("Data", disabled=True),
            COL_TITLE: st.column_config.TextColumn("Tytuł", disabled=True),
            COL_RECIPIENT: st.column_config.TextColumn("Odbiorca", disabled=True),
            COL_DEBIT: st.column_config.NumberColumn("Obciążenia", disabled=True),
            COL_CREDIT: st.column_config.NumberColumn("Uznania", disabled=True),
            COL_CURRENCY: st.column_config.TextColumn("Waluta", disabled=True),
            COL_BANK: st.column_config.TextColumn("Bank", disabled=True),
            COL_FILE: st.column_config.TextColumn("Plik", disabled=True),
            COL_CATEGORY: st.column_config.SelectboxColumn("Kategoria", options=categories),
            COL_SUBCATEGORY: st.column_config.TextColumn("Podkategoria"),
            COL_NOTE: st.column_config.TextColumn("Opis"),
            COL_ID: None,
        },
    )


def _commit(imp: dict, edited: pd.DataFrame) -> None:
    by_id = {str(row[COL_ID]): row for row in edited.to_dict("records")}
    for row in imp["rows"]:
        edit = by_id.get(str(row[COL_ID]))
        if not edit:
            continue
        changed = (
            str(edit.get(COL_CATEGORY) or "") != str(row.get(COL_CATEGORY) or "")
            or str(edit.get(COL_SUBCATEGORY) or "") != str(row.get(COL_SUBCATEGORY) or "")
        )
        row[COL_CATEGORY] = edit.get(COL_CATEGORY) or ""
        row[COL_SUBCATEGORY] = edit.get(COL_SUBCATEGORY) or ""
        row[COL_NOTE] = edit.get(COL_NOTE) or ""
        if changed:
            row[COL_SOURCE] = SOURCE_MANUAL
    db = load_db()
    fresh = pd.DataFrame(imp["rows"])
    db[SHEET_TRANSACTIONS] = pd.concat([db[SHEET_TRANSACTIONS], fresh], ignore_index=True)
    try:
        save_db(db)
    except StorageError as exc:
        st.error(str(exc))
        return
    st.session_state.import_wizard = _fresh()
    st.session_state.page = "home"
    st.rerun()
