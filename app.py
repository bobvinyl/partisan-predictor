from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
CENSUS_PATH = ROOT / "data" / "census" / "state_demographics_wide.csv"
PVI_PATH = ROOT / "data" / "elections" / "state_partisanship_pvi.csv"
PARTY_RESULTS_PATH = ROOT / "data" / "elections" / "presidential_results_by_party.csv"

STATE_ORDER = [
    "Alabama",
    "Alaska",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "District Of Columbia",
    "Florida",
    "Georgia",
    "Hawaii",
    "Idaho",
    "Illinois",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "Nevada",
    "New Hampshire",
    "New Jersey",
    "New Mexico",
    "New York",
    "North Carolina",
    "North Dakota",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "Pennsylvania",
    "Rhode Island",
    "South Carolina",
    "South Dakota",
    "Tennessee",
    "Texas",
    "Utah",
    "Vermont",
    "Virginia",
    "Washington",
    "West Virginia",
    "Wisconsin",
    "Wyoming",
]

SIGN_POSITIVE = "#1f5cff"
SIGN_NEGATIVE = "#d62728"
LINE_COLOR = "#111827"
POPULATION_COLOR = "#7c3aed"


@st.cache_data(show_spinner=False)
def load_data() -> pd.DataFrame:
    census = pd.read_csv(CENSUS_PATH)
    pvi = pd.read_csv(PVI_PATH)
    party = pd.read_csv(PARTY_RESULTS_PATH)

    census = census[
        ["year", "state_name", "state_abbr", "population_total", "population_density_per_sq_mile"]
    ].copy()
    census["state"] = census["state_name"].str.replace("District Of Columbia", "District of Columbia", regex=False)

    pvi = pvi.copy()
    pvi["state"] = pvi["state"].str.replace("District Of Columbia", "District of Columbia", regex=False)

    party = party[["year", "state_name", "state_abbr", "electoral_votes"]].copy()
    party["state"] = party["state_name"].str.replace("District Of Columbia", "District of Columbia", regex=False)
    electoral_votes = party.groupby(["year", "state"], as_index=False)["electoral_votes"].max()

    df = census.merge(pvi, on=["year", "state"], how="left")
    df = df.merge(electoral_votes, on=["year", "state"], how="left")
    df["population_total"] = pd.to_numeric(df["population_total"], errors="coerce")
    df["population_density_per_sq_mile"] = pd.to_numeric(df["population_density_per_sq_mile"], errors="coerce")
    df["state_partisanship"] = pd.to_numeric(df["state_partisanship"], errors="coerce")
    df["pvi"] = pd.to_numeric(df["pvi"], errors="coerce")
    df["electoral_votes"] = pd.to_numeric(df["electoral_votes"], errors="coerce")
    return df


def state_chart(
    df: pd.DataFrame,
    state: str,
    population_mode: str,
    show_state_partisanship: bool,
    show_pvi: bool,
) -> alt.LayerChart:
    state_df = df[df["state"] == state].sort_values("year").copy()
    years = state_df["year"].tolist()

    if population_mode == "Population":
        population_field = "population_total"
        population_axis_title = "Population"
        population_tooltip_title = "Population"
        population_format = ",.0f"
    else:
        population_field = "population_density_per_sq_mile"
        population_axis_title = "Population density (per sq mile)"
        population_tooltip_title = "Population density"
        population_format = ",.2f"

    population_df = state_df[["year", population_field]].dropna(subset=[population_field])

    partisanship_df = state_df[["year", "state_partisanship"]].dropna(subset=["state_partisanship"]).copy()
    partisanship_df["metric"] = "State partisanship"
    partisanship_df["value"] = partisanship_df["state_partisanship"]

    pvi_df = state_df[["year", "pvi"]].dropna(subset=["pvi"]).copy()
    pvi_df["metric"] = "PVI"
    pvi_df["value"] = pvi_df["pvi"]

    partisanship_neutral_df = partisanship_df[partisanship_df["value"].between(-5, 5, inclusive="both")].copy()
    partisanship_non_neutral_df = partisanship_df[~partisanship_df["value"].between(-5, 5, inclusive="both")].copy()

    line_chart = (
        alt.Chart(population_df)
        .mark_line(point=True, strokeWidth=4, color=POPULATION_COLOR)
        .encode(
            x=alt.X("year:O", sort=years, title=None),
            y=alt.Y(
                f"{population_field}:Q",
                title=population_axis_title,
                axis=alt.Axis(titleColor=POPULATION_COLOR, labelColor=POPULATION_COLOR, tickColor=POPULATION_COLOR),
                scale=alt.Scale(zero=False),
            ),
            tooltip=[
                alt.Tooltip("year:O", title="Year"),
                alt.Tooltip(f"{population_field}:Q", title=population_tooltip_title, format=population_format),
            ],
        )
        .properties(height=420)
    )

    partisan_layers: list[alt.Chart] = []
    partisan_y = alt.Y(
        "value:Q",
        title="State partisanship / PVI",
        axis=alt.Axis(titleColor=SIGN_POSITIVE, labelColor=SIGN_POSITIVE, tickColor=SIGN_POSITIVE),
        scale=alt.Scale(zero=False),
    )
    zero_line = (
        alt.Chart(pd.DataFrame({"value": [0.0]}))
        .mark_rule(color="#6b7280", strokeDash=[4, 4])
        .encode(y=partisan_y)
        .properties(height=420)
    )

    if show_state_partisanship:
        partisan_layers.append(
            alt.Chart(partisanship_df)
            .mark_line(strokeWidth=3, color=SIGN_POSITIVE)
            .encode(
                x=alt.X("year:O", sort=years, title="Year"),
                y=partisan_y,
                tooltip=[
                    alt.Tooltip("year:O", title="Year"),
                    alt.Tooltip("metric:N", title="Metric"),
                    alt.Tooltip("value:Q", title="Value", format=".2f"),
                ],
            )
            .properties(height=420)
        )
        partisan_layers.append(
            alt.Chart(partisanship_non_neutral_df)
            .mark_point(size=70, filled=True, color=SIGN_POSITIVE)
            .encode(
                x=alt.X("year:O", sort=years, title="Year"),
                y=partisan_y,
                tooltip=[
                    alt.Tooltip("year:O", title="Year"),
                    alt.Tooltip("metric:N", title="Metric"),
                    alt.Tooltip("value:Q", title="Value", format=".2f"),
                ],
            )
            .properties(height=420)
        )
        partisan_layers.append(
            alt.Chart(partisanship_neutral_df)
            .mark_text(
                text="S",
                fontSize=16,
                fontWeight="bold",
                color=SIGN_POSITIVE,
                baseline="middle",
                align="center",
            )
            .encode(
                x=alt.X("year:O", sort=years, title="Year"),
                y=partisan_y,
                tooltip=[
                    alt.Tooltip("year:O", title="Year"),
                    alt.Tooltip("metric:N", title="Metric"),
                    alt.Tooltip("value:Q", title="Value", format=".2f"),
                ],
            )
            .properties(height=420)
        )

    if show_pvi:
        partisan_layers.append(
            alt.Chart(pvi_df)
            .mark_line(strokeWidth=3, color=SIGN_NEGATIVE)
            .encode(
                x=alt.X("year:O", sort=years, title="Year"),
                y=partisan_y,
                tooltip=[
                    alt.Tooltip("year:O", title="Year"),
                    alt.Tooltip("metric:N", title="Metric"),
                    alt.Tooltip("value:Q", title="Value", format=".2f"),
                ],
            )
            .properties(height=420)
        )
        partisan_layers.append(
            alt.Chart(pvi_df)
            .mark_point(size=70, filled=True, color=SIGN_NEGATIVE)
            .encode(
                x=alt.X("year:O", sort=years, title="Year"),
                y=partisan_y,
                tooltip=[
                    alt.Tooltip("year:O", title="Year"),
                    alt.Tooltip("metric:N", title="Metric"),
                    alt.Tooltip("value:Q", title="Value", format=".2f"),
                ],
            )
            .properties(height=420)
        )

    if partisan_layers:
        partisan_chart = alt.layer(zero_line, *partisan_layers)
        chart = alt.layer(partisan_chart, line_chart).resolve_scale(y="independent").properties(title=state)
    else:
        chart = line_chart.properties(title=state)

    chart = chart.configure_view(stroke=None)
    return chart


def yearly_scatter_chart(df: pd.DataFrame, year: int) -> alt.Chart:
    year_df = (
        df[df["year"] == year][
            ["state", "state_abbr", "year", "population_density_per_sq_mile", "state_partisanship", "pvi"]
        ]
        .query("state != 'District of Columbia'")
        .dropna(subset=["population_density_per_sq_mile", "state_partisanship"])
        .copy()
    )

    chart = (
        alt.Chart(year_df)
        .mark_circle(size=95, opacity=0.85)
        .encode(
            x=alt.X("population_density_per_sq_mile:Q", title="Population density (per sq mile)"),
            y=alt.Y("state_partisanship:Q", title="State partisanship"),
            color=alt.Color("state_abbr:N", title="State"),
            tooltip=[
                alt.Tooltip("state:N", title="State"),
                alt.Tooltip("year:O", title="Year"),
                alt.Tooltip("population_density_per_sq_mile:Q", title="Population density", format=",.2f"),
                alt.Tooltip("state_partisanship:Q", title="State partisanship", format=".2f"),
                alt.Tooltip("pvi:Q", title="PVI", format=".2f"),
            ],
        )
        .properties(height=300, title=f"{year}: Population density vs state partisanship")
        .configure_view(stroke=None)
    )
    return chart


def _binary_treemap_layout(items: List[Dict[str, float]], x: float, y: float, w: float, h: float) -> List[Dict[str, float]]:
    if not items:
        return []
    if len(items) == 1:
        out = dict(items[0])
        out.update({"x0": x, "x1": x + w, "y0": y, "y1": y + h})
        return [out]

    total = sum(item["value"] for item in items)
    running = 0.0
    split_index = 0
    for idx, item in enumerate(items):
        running += item["value"]
        if running >= total / 2:
            split_index = idx + 1
            break

    left = items[:split_index]
    right = items[split_index:]
    left_total = sum(item["value"] for item in left)

    if w >= h:
        left_w = w * (left_total / total)
        return _binary_treemap_layout(left, x, y, left_w, h) + _binary_treemap_layout(right, x + left_w, y, w - left_w, h)

    left_h = h * (left_total / total)
    return _binary_treemap_layout(left, x, y, w, left_h) + _binary_treemap_layout(right, x, y + left_h, w, h - left_h)


def yearly_treemap_chart(df: pd.DataFrame, year: int) -> alt.LayerChart:
    year_df = (
        df[df["year"] == year][["state", "state_abbr", "year", "electoral_votes", "state_partisanship"]]
        .dropna(subset=["electoral_votes", "state_partisanship"])
        .copy()
    )
    year_df = year_df[year_df["electoral_votes"] > 0]
    year_df = year_df.sort_values("electoral_votes", ascending=False)

    items = [
        {
            "state": str(row["state"]),
            "state_abbr": str(row["state_abbr"]),
            "year": int(row["year"]),
            "electoral_votes": float(row["electoral_votes"]),
            "state_partisanship": float(row["state_partisanship"]),
            "value": float(row["electoral_votes"]),
        }
        for _, row in year_df.iterrows()
    ]
    layout = _binary_treemap_layout(items, 0.0, 0.0, 100.0, 60.0)
    layout_df = pd.DataFrame(layout)
    layout_df["label_x"] = (layout_df["x0"] + layout_df["x1"]) / 2
    layout_df["label_y"] = (layout_df["y0"] + layout_df["y1"]) / 2

    base = alt.Chart(layout_df)
    rect = base.mark_rect(stroke="white", strokeWidth=1).encode(
        x=alt.X("x0:Q", axis=None),
        x2="x1:Q",
        y=alt.Y("y0:Q", axis=None),
        y2="y1:Q",
        color=alt.Color(
            "state_partisanship:Q",
            title="State partisanship",
            scale=alt.Scale(domainMid=0, range=[SIGN_NEGATIVE, "#f8fafc", SIGN_POSITIVE]),
        ),
        tooltip=[
            alt.Tooltip("state:N", title="State"),
            alt.Tooltip("year:O", title="Year"),
            alt.Tooltip("electoral_votes:Q", title="Electoral votes", format=".0f"),
            alt.Tooltip("state_partisanship:Q", title="State partisanship", format=".2f"),
        ],
    )

    labels = base.mark_text(fontSize=10, color="#111827").encode(
        x=alt.X("label_x:Q", axis=None),
        y=alt.Y("label_y:Q", axis=None),
        text="state_abbr:N",
    )

    return alt.layer(rect, labels).properties(
        height=360,
        title=f"{year}: Electoral votes treemap (color = state partisanship)",
    ).configure_view(stroke=None)


def swing_state_counts_chart(df: pd.DataFrame) -> alt.Chart:
    counts = (
        df.groupby("year", as_index=False)["is_swing"]
        .sum()
        .rename(columns={"is_swing": "swing_state_count"})
    )

    chart = (
        alt.Chart(counts)
        .mark_bar(color="#0f766e")
        .encode(
            x=alt.X("year:O", title="Year"),
            y=alt.Y("swing_state_count:Q", title="Swing states"),
            tooltip=[
                alt.Tooltip("year:O", title="Year"),
                alt.Tooltip("swing_state_count:Q", title="Swing states", format=".0f"),
            ],
        )
        .properties(height=180, title="Swing state count by year")
        .configure_view(stroke=None)
    )
    return chart


def swing_state_heatmap(df: pd.DataFrame) -> alt.LayerChart:
    states_sorted = [state.replace("District Of Columbia", "District of Columbia") for state in STATE_ORDER]
    year_values = sorted(df["year"].dropna().astype(int).unique().tolist())
    chart_height = max(900, len(states_sorted) * 22)

    base = alt.Chart(df).encode(
        x=alt.X("year:O", sort=year_values, title="Year"),
        y=alt.Y(
            "state:N",
            sort=states_sorted,
            title="State",
            axis=alt.Axis(labelOverlap=False, labelLimit=220),
        ),
        tooltip=[
            alt.Tooltip("state:N", title="State"),
            alt.Tooltip("year:O", title="Year"),
            alt.Tooltip("state_partisanship:Q", title="State partisanship", format=".2f"),
            alt.Tooltip("is_swing:N", title="Swing"),
        ],
    )

    heatmap = base.mark_rect().encode(
        color=alt.Color(
            "state_partisanship:Q",
            title="State partisanship",
            scale=alt.Scale(domainMid=0, range=[SIGN_NEGATIVE, "#f8fafc", SIGN_POSITIVE]),
        )
    )

    swing_markers = (
        alt.Chart(df[df["is_swing"] == True])
        .mark_text(text="S", color="#111827", fontWeight="bold", fontSize=12)
        .encode(
            x=alt.X("year:O", sort=year_values, title="Year"),
            y=alt.Y("state:N", sort=states_sorted, title="State"),
        )
    )

    chart = (
        alt.layer(heatmap, swing_markers)
        .properties(height=chart_height, title="Swing states by year (S = -5 to 5 state partisanship)")
        .configure_view(stroke=None)
    )
    return chart


@st.cache_data(show_spinner=False)
def available_state_names(df: pd.DataFrame) -> list[str]:
    ordered = [state for state in STATE_ORDER if state in set(df["state"])]
    remaining = sorted(set(df["state"]) - set(ordered))
    return ordered + remaining


st.set_page_config(page_title="Partisan Predictor", layout="wide")
st.title("Partisan Predictor")
st.write(
    "Select one or more states and a year range to compare population or population density, "
    "with optional state partisanship and PVI overlays. "
    "Positive values are blue and negative values are red."
)

df = load_data()
state_names = available_state_names(df)

left, right = st.columns([1, 2])
with left:
    selected_states = st.multiselect(
        "States",
        options=state_names,
        default=["Pennsylvania"],
    )
    year_range = st.slider(
        "Year range",
        min_value=1976,
        max_value=2024,
        value=(1976, 2024),
        step=1,
    )
    population_mode = st.radio(
        "Population metric",
        options=["Population", "Population density"],
        index=1,
        horizontal=True,
    )
    show_state_partisanship = st.checkbox("Graph state partisanship", value=True)
    show_pvi = st.checkbox("Graph PVI", value=True)

filtered = df[(df["year"] >= year_range[0]) & (df["year"] <= year_range[1])]

if not selected_states:
    st.info("Choose one or more states to render the charts.")
else:
    selected_years = filtered["year"].nunique()
    st.caption(f"Showing {selected_years} year(s) across {len(selected_states)} state(s).")

    for state in selected_states:
        state_df = filtered[filtered["state"] == state]
        if state_df.empty:
            st.warning(f"No data available for {state} in the selected range.")
            continue

        st.altair_chart(
            state_chart(filtered, state, population_mode, show_state_partisanship, show_pvi),
            use_container_width=True,
        )

        population_value = (
            state_df.iloc[-1]["population_total"]
            if population_mode == "Population"
            else state_df.iloc[-1]["population_density_per_sq_mile"]
        )
        population_label = "Population" if population_mode == "Population" else "Population density"
        population_value_text = f"{population_value:,.0f}" if population_mode == "Population" else f"{population_value:,.2f}"

        details = [f"{population_label} {population_value_text}"]
        if show_state_partisanship and state_df["state_partisanship"].notna().any():
            details.append(f"State partisanship {state_df['state_partisanship'].dropna().iloc[-1]:.2f}")
        if show_pvi and state_df["pvi"].notna().any():
            details.append(f"PVI {state_df['pvi'].dropna().iloc[-1]:.2f}")

        st.markdown(f"**Latest observed values** for {state}: " + ", ".join(details) + ".")

    st.subheader("Population Density vs State Partisanship by Year")
    scatter_source = filtered[filtered["state"] != "District of Columbia"].copy()
    scatter_years = sorted(scatter_source["year"].dropna().astype(int).unique().tolist())

    for year in scatter_years:
        year_points = scatter_source[
            (scatter_source["year"] == year)
            & scatter_source["population_density_per_sq_mile"].notna()
            & scatter_source["state_partisanship"].notna()
        ]
        if year_points.empty:
            continue
        st.altair_chart(yearly_scatter_chart(scatter_source, year), use_container_width=True)

    st.subheader("Swing States by Year")
    swing_source = (
        filtered[
            filtered["state_partisanship"].notna()
        ][["state", "year", "state_partisanship"]]
        .copy()
    )
    swing_source["is_swing"] = swing_source["state_partisanship"].between(-5, 5, inclusive="both")

    if swing_source.empty:
        st.info("No state partisanship data available to calculate swing states in this range.")
    else:
        st.altair_chart(swing_state_counts_chart(swing_source), use_container_width=True)
        st.altair_chart(swing_state_heatmap(swing_source), use_container_width=True)

    st.subheader("Electoral Vote Treemap by Year")
    treemap_source = filtered[filtered["electoral_votes"].notna() & filtered["state_partisanship"].notna()].copy()
    treemap_years = sorted(treemap_source["year"].dropna().astype(int).unique().tolist())

    for year in treemap_years:
        year_rows = treemap_source[treemap_source["year"] == year]
        if year_rows.empty:
            continue
        st.altair_chart(yearly_treemap_chart(treemap_source, year), use_container_width=True)
