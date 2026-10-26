"""Ekran główny: wykres według kategorii oraz filtry dat i kategorii."""

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
_PALETTE = qualitative.Dark24


def _without_internal(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame[frame[COL_CATEGORY].fillna("").astype(str).str.strip() != INTERNAL_CATEGORY].copy()


def _pln(value: float) -> str:
    formatted = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return f"{formatted} zł"


def category_label(value) -> str:
    if value is None:
        return UNCATEGORIZED
    try:
        if pd.isna(value):
            return UNCATEGORIZED
    except TypeError:
        pass
    text = str(value).strip()
    return text or UNCATEGORIZED


def ordered_categories(names: list[str]) -> list[str]:
    regular = sorted({name for name in names if name and name != UNCATEGORIZED})
    if UNCATEGORIZED in names:
        regular.append(UNCATEGORIZED)
    return regular


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    data = _without_internal(frame)
    if data.empty:
        return data
    data["_kategoria"] = data[COL_CATEGORY].map(category_label)
    data["_uznania"] = pd.to_numeric(data[COL_CREDIT], errors="coerce").fillna(0.0)
    data["_obciazenia"] = pd.to_numeric(data[COL_DEBIT], errors="coerce").fillna(0.0)
    data["_netto"] = data["_uznania"] - data["_obciazenia"]
    return data


def default_date_range(data_min, data_max) -> tuple:
    end = pd.Timestamp(data_max).normalize()
    start = (end.to_period("M") - 11).to_timestamp().normalize()
    clipped = max(start, pd.Timestamp(data_min).normalize())
    return clipped.date(), end.date()


def normalize_range(value, fallback_start, fallback_end):
    if isinstance(value, (tuple, list)):
        if len(value) >= 2 and value[0] is not None and value[1] is not None:
            start, end = value[0], value[1]
        elif len(value) == 1 and value[0] is not None:
            start = end = value[0]
        else:
            return fallback_start, fallback_end
    elif value is None:
        return fallback_start, fallback_end
    else:
        start = end = value
    if start > end:
        start, end = end, start
    return start, end


def filter_transactions(frame: pd.DataFrame, start, end, categories: list[str]) -> pd.DataFrame:
    if frame.empty or not categories:
        return frame.iloc[0:0].copy()
    chosen = set(categories)
    mask = frame["_kategoria"].isin(chosen)
    dated = frame[COL_DATE].notna()
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    mask = mask & dated & (frame[COL_DATE] >= start_ts) & (frame[COL_DATE] <= end_ts)
    return frame.loc[mask].copy()


def month_category_amounts(
    frame: pd.DataFrame, start, end, categories: list[str]
) -> tuple[list[str], dict[str, list[float]], list[float]]:
    periods = [str(period) for period in pd.period_range(start=pd.Timestamp(start), end=pd.Timestamp(end), freq="M")]
    series = {category: [0.0] * len(periods) for category in categories}
    if frame.empty or not periods:
        return periods, series, [0.0] * len(periods)
    work = frame[frame[COL_DATE].notna()].copy()
    work["Miesiąc"] = work[COL_DATE].dt.to_period("M").astype(str)
    grouped = work.groupby(["Miesiąc", "_kategoria"])["_netto"].sum()
    for index, period in enumerate(periods):
        for category in categories:
            series[category][index] = float(grouped.get((period, category), 0.0))
    balance = [sum(series[category][index] for category in categories) for index in range(len(periods))]
    return periods, series, balance


_MONTH_NAMES = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)
TABLE_COLUMNS = ["Data", "Kategoria", "Podkategoria", "Tytuł", "Odbiorca", "Obciążenia", "Uznania"]


def month_key(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) >= 7 and text[4] == "-" and text[:4].isdigit() and text[5:7].isdigit():
        month = int(text[5:7])
        if 1 <= month <= 12:
            return text[:7]
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return ""
    return str(parsed.to_period("M"))


def months_from_points(points) -> tuple[str, ...]:
    found: list[str] = []
    for point in points or []:
        if not isinstance(point, dict):
            continue
        custom = point.get("customdata")
        raw = custom[0] if isinstance(custom, (list, tuple)) and custom else custom
        if raw in (None, ""):
            raw = point.get("x")
        key = month_key(raw)
        if key and key not in found:
            found.append(key)
    return tuple(found)


def month_label(period: str) -> str:
    key = month_key(period)
    if not key:
        return str(period)
    year, month = key.split("-")
    return f"{_MONTH_NAMES[int(month) - 1]} {year}"


def _text_column(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame.columns:
        return pd.Series([""] * len(frame), index=frame.index, dtype="object")
    return frame[name].fillna("").astype(str).replace({"nan": ""})


def transaction_table(frame: pd.DataFrame, months: tuple[str, ...] = ()) -> pd.DataFrame:
    empty = pd.DataFrame(columns=TABLE_COLUMNS)
    if frame.empty:
        return empty
    view = frame
    if months:
        keys = frame[COL_DATE].dt.to_period("M").astype(str)
        view = frame.loc[keys.isin(months)]
    if view.empty:
        return empty
    view = view.sort_values([COL_DATE, COL_TITLE] if COL_TITLE in view.columns else [COL_DATE], ascending=False)
    return pd.DataFrame(
        {
            "Data": view[COL_DATE].dt.normalize().to_list(),
            "Kategoria": view["_kategoria"].tolist(),
            "Podkategoria": _text_column(view, COL_SUBCATEGORY).tolist(),
            "Tytuł": _text_column(view, COL_TITLE).tolist(),
            "Odbiorca": _text_column(view, COL_RECIPIENT).tolist(),
            "Obciążenia": view["_obciazenia"].tolist(),
            "Uznania": view["_uznania"].tolist(),
        }
    )


def category_color(name: str, names: list[str]) -> str:
    index = names.index(name) if name in names else 0
    return _PALETTE[index % len(_PALETTE)]


def _figure(periods: list[str], series: dict[str, list[float]], balance: list[float], palette_names: list[str]) -> go.Figure:
    figure = go.Figure()
    labels = [month_label(period) for period in periods]
    for category, values in series.items():
        figure.add_bar(
            name=category,
            x=labels,
            y=values,
            customdata=periods,
            marker_color=category_color(category, palette_names),
        )
    figure.add_scatter(
        name="Saldo miesiąca",
        x=labels,
        y=balance,
        customdata=periods,
        mode="lines+markers",
        yaxis="y2",
        line_color="#1d3557",
    )
    figure.update_layout(
        barmode="relative",
        title="Przychody i wydatki według kategorii",
        yaxis_title="Kwota",
        yaxis2={"overlaying": "y", "side": "right", "title": "Saldo", "showgrid": False},
        legend={"orientation": "h", "y": -0.25},
        margin={"t": 60, "b": 80},
        height=560,
        xaxis={"type": "category"},
    )
    return figure


def render() -> None:
    st.header("Podsumowanie")
    prepared = _prepare(load_db()[SHEET_TRANSACTIONS])
    if prepared.empty:
        st.info("Brak transakcji. Dodaj wyciąg w menu „Dodaj transakcje”.")
        return

    labels = ordered_categories(prepared["_kategoria"].tolist())
    dated = prepared[prepared[COL_DATE].notna()]
    if dated.empty:
        st.info("Transakcje nie mają dat, więc nie da się ich nanieść na wykres.")
        return
    data_min = dated[COL_DATE].min().date()
    data_max = dated[COL_DATE].max().date()
    default_start, default_end = default_date_range(data_min, data_max)

    left, right = st.columns([1, 2])
    with left:
        picked = st.date_input(
            "Daty",
            value=(default_start, default_end),
            min_value=data_min,
            max_value=data_max,
            format="DD.MM.YYYY",
            help="Początek i koniec zakresu. Oba dni są wliczane.",
        )
    with right:
        selected = st.multiselect(
            "Kategorie",
            options=labels,
            default=labels,
            placeholder="Wybierz kategorie",
            help="Można zaznaczyć kilka kategorii naraz.",
        )

    start, end = normalize_range(picked, default_start, default_end)
    if not selected:
        st.info("Wybierz co najmniej jedną kategorię.")
        return

    filtered = filter_transactions(prepared, start, end, selected)
    periods, series, balance = month_category_amounts(filtered, start, end, selected)
    nonce = int(st.session_state.get("home_chart_nonce", 0))
    event = st.plotly_chart(
        _figure(periods, series, balance, labels),
        width="stretch",
        on_select="rerun",
        selection_mode="points",
        key=f"home_chart_{nonce}",
    )
    chosen_months = tuple(month for month in months_from_points(getattr(event, "selection", {}).get("points", [])) if month in periods)
    st.caption(
        "Słupek w górę to uznania, w dół obciążenia. Kolor oznacza kategorię. "
        "Kliknij miesiąc, aby zawęzić listę transakcji. Przelewy wewnętrzne nie wchodzą do podsumowania."
    )
    if chosen_months:
        names = ", ".join(month_label(month) for month in chosen_months)
        st.caption(f"Lista transakcji: {names}.")
        if st.button("Pokaż wszystkie miesiące z wykresu"):
            st.session_state.home_chart_nonce = nonce + 1
            st.rerun()

    table = transaction_table(filtered, chosen_months)
    st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        column_config={
            "Data": st.column_config.DateColumn("Data", format="DD.MM.YYYY"),
            "Obciążenia": st.column_config.NumberColumn("Obciążenia", format="%.2f"),
            "Uznania": st.column_config.NumberColumn("Uznania", format="%.2f"),
        },
    )
    if table.empty:
        st.info("Brak transakcji w wybranym zakresie.")

    st.subheader("Wybrany zakres")
    total_in = float(filtered["_uznania"].sum()) if not filtered.empty else 0.0
    total_out = float(filtered["_obciazenia"].sum()) if not filtered.empty else 0.0
    first, second, third, fourth = st.columns(4)
    first.metric("Przychody", _pln(total_in))
    second.metric("Wydatki", _pln(total_out))
    third.metric("Saldo", _pln(total_in - total_out))
    fourth.metric("Transakcje", f"{len(filtered)}")
