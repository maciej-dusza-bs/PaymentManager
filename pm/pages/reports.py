"""Raporty: udział wydatków i dochodów. Przelewy wewnętrzne są pomijane."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.colors import qualitative

from pm.schema import (
    COL_CATEGORY,
    COL_CREDIT,
    COL_DATE,
    COL_DEBIT,
    COL_RECIPIENT,
    COL_SUBCATEGORY,
    COL_TITLE,
    INTERNAL_CATEGORY,
    SHEET_TRANSACTIONS,
)
from pm.storage import load_db

UNCATEGORIZED = "Bez kategorii"
NO_SUBCATEGORY = "Bez podkategorii"
DETAIL_COLUMNS = ["Data", "Kategoria", "Podkategoria", "Tytuł", "Odbiorca", "Obciążenia", "Uznania"]


def _pln(value: float) -> str:
    formatted = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return f"{formatted} zł"


def _label(value, empty: str) -> str:
    if value is None:
        return empty
    try:
        if pd.isna(value):
            return empty
    except TypeError:
        pass
    text = str(value).strip()
    return text if text and text.lower() != "nan" else empty


def month_span(start, end) -> int:
    periods = pd.period_range(start=pd.Timestamp(start), end=pd.Timestamp(end), freq="M")
    return max(int(periods.size), 1)


def _chosen_bounds(chosen, fallback_start, fallback_end):
    if isinstance(chosen, (tuple, list)):
        if len(chosen) >= 2 and chosen[0] is not None and chosen[1] is not None:
            start, end = chosen[0], chosen[1]
            if start > end:
                start, end = end, start
            return start, end
        if len(chosen) == 1 and chosen[0] is not None:
            return chosen[0], chosen[0]
    elif chosen is not None:
        return chosen, chosen
    return fallback_start, fallback_end


def _text_column(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame.columns:
        return pd.Series([""] * len(frame), index=frame.index, dtype="object")
    return frame[name].fillna("").astype(str).replace({"nan": ""})


def _slice_labels(frame: pd.DataFrame, by_subcategory: bool) -> pd.Series:
    category = frame[COL_CATEGORY].map(lambda value: _label(value, UNCATEGORIZED))
    if not by_subcategory:
        return category
    subcategory = _text_column(frame, COL_SUBCATEGORY).map(lambda value: _label(value, NO_SUBCATEGORY))
    return category + " / " + subcategory


def amount_slices(frame: pd.DataFrame, amount_column: str, by_subcategory: bool, months: int) -> pd.DataFrame:
    columns = ["Etykieta", "Suma", "Średnio miesięcznie", "Procent"]
    if frame is None or frame.empty or months < 1 or amount_column not in frame.columns:
        return pd.DataFrame(columns=columns)
    work = frame.copy()
    work["_kwota"] = pd.to_numeric(work[amount_column], errors="coerce").fillna(0.0)
    work = work[work["_kwota"] > 0]
    if work.empty:
        return pd.DataFrame(columns=columns)
    grouped = work.assign(_etykieta=_slice_labels(work, by_subcategory)).groupby("_etykieta", as_index=False)["_kwota"].sum()
    total = float(grouped["_kwota"].sum())
    grouped = grouped.rename(columns={"_etykieta": "Etykieta", "_kwota": "Suma"})
    grouped["Średnio miesięcznie"] = grouped["Suma"] / months
    grouped["Procent"] = grouped["Suma"] / total * 100 if total else 0.0
    return grouped.sort_values("Suma", ascending=False).reset_index(drop=True)


def expense_slices(frame: pd.DataFrame, by_subcategory: bool, months: int) -> pd.DataFrame:
    return amount_slices(frame, COL_DEBIT, by_subcategory, months)


def matching_transactions(frame: pd.DataFrame, label: str, by_subcategory: bool, amount_column: str) -> pd.DataFrame:
    if frame is None or frame.empty or not label or amount_column not in frame.columns:
        return frame.iloc[0:0].copy() if frame is not None else pd.DataFrame()
    work = frame.copy()
    work["_kwota"] = pd.to_numeric(work[amount_column], errors="coerce").fillna(0.0)
    work = work[(work["_kwota"] > 0) & (_slice_labels(work, by_subcategory) == label)]
    if work.empty:
        return work
    return work.sort_values("_kwota", ascending=False)


def transaction_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)
    dates = frame[COL_DATE] if COL_DATE in frame.columns else pd.Series([pd.NaT] * len(frame), index=frame.index)
    return pd.DataFrame(
        {
            "Data": pd.to_datetime(dates, errors="coerce").dt.normalize().to_list(),
            "Kategoria": frame[COL_CATEGORY].map(lambda value: _label(value, "")).tolist() if COL_CATEGORY in frame.columns else "",
            "Podkategoria": _text_column(frame, COL_SUBCATEGORY).tolist(),
            "Tytuł": _text_column(frame, COL_TITLE).tolist(),
            "Odbiorca": _text_column(frame, COL_RECIPIENT).tolist(),
            "Obciążenia": pd.to_numeric(frame[COL_DEBIT], errors="coerce").fillna(0.0).tolist() if COL_DEBIT in frame.columns else 0.0,
            "Uznania": pd.to_numeric(frame[COL_CREDIT], errors="coerce").fillna(0.0).tolist() if COL_CREDIT in frame.columns else 0.0,
        }
    )


def label_from_points(points) -> str:
    for point in points or []:
        if not isinstance(point, dict):
            continue
        custom = point.get("customdata")
        if isinstance(custom, (list, tuple)) and len(custom) > 1 and str(custom[1]).strip():
            return str(custom[1]).strip()
        label = point.get("label")
        if label:
            return str(label).strip()
    return ""


def label_from_rows(rows, labels: list[str]) -> str:
    if not rows:
        return ""
    index = rows[0]
    if not isinstance(index, int) or index < 0 or index >= len(labels):
        return ""
    return labels[index]


def chosen_label(previous: dict | None, pie_label: str, row_label: str) -> dict:
    previous = previous or {}
    label = str(previous.get("label") or "")
    if pie_label and pie_label != previous.get("pie", ""):
        label = pie_label
    elif row_label and row_label != previous.get("row", ""):
        label = row_label
    elif not label:
        label = pie_label or row_label
    return {"pie": pie_label, "row": row_label, "label": label}


def _pie(slices: pd.DataFrame, title: str) -> go.Figure:
    labels = slices["Etykieta"].tolist()
    figure = go.Figure(
        go.Pie(
            labels=labels,
            values=slices["Suma"].tolist(),
            customdata=[[_pln(amount), label] for amount, label in zip(slices["Średnio miesięcznie"], labels)],
            texttemplate="%{label}<br>%{percent:.1%}<br>%{customdata[0]}",
            hovertemplate="%{label}<br>Udział: %{percent:.1%}<br>Średnio miesięcznie: %{customdata[0]}<extra></extra>",
            sort=False,
            direction="clockwise",
            marker={"colors": [qualitative.Dark24[index % len(qualitative.Dark24)] for index in range(len(labels))]},
        )
    )
    figure.update_layout(
        title=title,
        margin={"t": 60, "b": 20},
        height=620,
        legend={"orientation": "h", "y": -0.15},
    )
    return figure


def _selection_points(event) -> list:
    selection = getattr(event, "selection", None)
    if not selection:
        return []
    points = selection["points"] if "points" in selection else []
    return list(points or [])


def _selection_rows(event) -> list:
    selection = getattr(event, "selection", None)
    if not selection:
        return []
    rows = selection["rows"] if "rows" in selection else []
    return list(rows or [])


def _share_table(slices: pd.DataFrame, key: str):
    return st.dataframe(
        slices,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=key,
        column_config={
            "Etykieta": st.column_config.TextColumn("Etykieta"),
            "Suma": st.column_config.NumberColumn("Suma", format="%.2f"),
            "Średnio miesięcznie": st.column_config.NumberColumn("Średnio miesięcznie", format="%.2f"),
            "Procent": st.column_config.NumberColumn("Procent", format="%.1f"),
        },
    )


def _render_share(
    view: pd.DataFrame,
    months: int,
    amount_column: str,
    heading: str,
    chart_title: str,
    empty_text: str,
    split_default: bool,
    key: str,
) -> None:
    st.subheader(heading)
    by_subcategory = st.checkbox(
        "Podziel na podkategorie",
        value=split_default,
        key=f"{key}_split",
        help="Każdy wycinek to kategoria i jej podkategoria.",
    )
    slices = amount_slices(view, amount_column, by_subcategory, months)
    if slices.empty:
        st.info(empty_text)
        return
    chart = st.plotly_chart(
        _pie(slices, chart_title),
        width="stretch",
        on_select="rerun",
        selection_mode="points",
        key=f"{key}_pie",
    )
    st.caption(
        f"Procent to udział w tym okresie. Kwota przy wycinku to średnia miesięczna ({months} mies.). "
        "Kliknij wycinek albo wiersz tabeli, aby zobaczyć transakcje."
    )
    table = _share_table(slices, f"{key}_table")
    labels = slices["Etykieta"].tolist()
    state = chosen_label(
        st.session_state.get(f"{key}_pick"),
        label_from_points(_selection_points(chart)),
        label_from_rows(_selection_rows(table), labels),
    )
    st.session_state[f"{key}_pick"] = state
    label = state["label"] if state["label"] in labels else ""
    if not label:
        return
    matched = matching_transactions(view, label, by_subcategory, amount_column)
    st.markdown(f"**Transakcje: {label}**")
    st.dataframe(
        transaction_rows(matched),
        hide_index=True,
        width="stretch",
        column_config={
            "Data": st.column_config.DateColumn("Data", format="DD.MM.YYYY"),
            "Obciążenia": st.column_config.NumberColumn("Obciążenia", format="%.2f"),
            "Uznania": st.column_config.NumberColumn("Uznania", format="%.2f"),
        },
    )


def render() -> None:
    st.header("Raporty")
    transactions = load_db()[SHEET_TRANSACTIONS]
    if not transactions.empty:
        category = transactions[COL_CATEGORY].fillna("").astype(str).str.strip()
        transactions = transactions[category != INTERNAL_CATEGORY]
    if transactions.empty:
        st.info("Brak transakcji do raportu.")
        return

    dated = transactions[transactions[COL_DATE].notna()]
    data_start = dated[COL_DATE].min().date() if not dated.empty else pd.Timestamp.today().date()
    data_end = dated[COL_DATE].max().date() if not dated.empty else data_start
    chosen = st.date_input("Okres", value=(data_start, data_end), format="DD.MM.YYYY")
    start, end = _chosen_bounds(chosen, data_start, data_end)
    view = transactions[transactions[COL_DATE].notna()].copy()
    view = view[view[COL_DATE].dt.date.between(start, end)]
    if view.empty:
        st.info("Brak transakcji w wybranym okresie.")
        return

    months = month_span(start, end)
    _render_share(
        view,
        months,
        COL_DEBIT,
        "Wydatki",
        "Średni udział wydatków",
        "Brak wydatków w wybranym okresie.",
        False,
        "report_expenses",
    )
    _render_share(
        view,
        months,
        COL_CREDIT,
        "Dochody",
        "Średni udział dochodów",
        "Brak dochodów w wybranym okresie.",
        True,
        "report_income",
    )
    st.caption("Przelewy wewnętrzne nie wchodzą do raportu.")
