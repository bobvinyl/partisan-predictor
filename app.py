from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
CENSUS_PATH = ROOT / "data" / "census" / "state_demographics_wide.csv"
PVI_PATH = ROOT / "data" / "elections" / "state_partisanship_pvi.csv"

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

    census = census[["year", "state_name", "state_abbr", "population_total"]].copy()
    census["state"] = census["state_name"].str.replace("District Of Columbia", "District of Columbia", regex=False)

    pvi = pvi.copy()
    pvi["state"] = pvi["state"].str.replace("District Of Columbia", "District of Columbia", regex=False)

    df = census.merge(pvi, on=["year", "state"], how="left")
    df["population_total"] = pd.to_numeric(df["population_total"], errors="coerce")
    df["state_partisanship"] = pd.to_numeric(df["state_partisanship"], errors="coerce")
    df["pvi"] = pd.to_numeric(df["pvi"], errors="coerce")
    return df


def state_chart(df: pd.DataFrame, state: str) -> alt.LayerChart:
    state_df = df[df["state"] == state].sort_values("year").copy()
    years = state_df["year"].tolist()

    population_df = state_df[["year", "population_total"]].dropna(subset=["population_total"])
    partisan_df = state_df[["year", "state_partisanship", "pvi"]].melt(
        id_vars=["year"],
        value_vars=["state_partisanship", "pvi"],
        var_name="metric",
        value_name="value",
    )
    partisan_df = partisan_df.dropna(subset=["value"]).copy()
    partisan_df["metric"] = partisan_df["metric"].replace(
        {"state_partisanship": "State partisanship", "pvi": "PVI"}
    )
    partisanship_df = partisan_df[partisan_df["metric"] == "State partisanship"].copy()
    pvi_df = partisan_df[partisan_df["metric"] == "PVI"].copy()
    partisanship_neutral_df = partisanship_df[partisanship_df["value"].between(-5, 5, inclusive="both")].copy()
    partisanship_non_neutral_df = partisanship_df[~partisanship_df["value"].between(-5, 5, inclusive="both")].copy()
    partisanship_neutral_df["marker"] = "S"

    line_chart = (
        alt.Chart(population_df)
        .mark_line(point=True, strokeWidth=4, color=POPULATION_COLOR)
        .encode(
            x=alt.X("year:O", sort=years, title=None),
            y=alt.Y(
                "population_total:Q",
                title="Population",
                axis=alt.Axis(titleColor=POPULATION_COLOR, labelColor=POPULATION_COLOR, tickColor=POPULATION_COLOR),
                scale=alt.Scale(zero=False),
            ),
            tooltip=[
                alt.Tooltip("year:O", title="Year"),
                alt.Tooltip("population_total:Q", title="Population", format=",.0f"),
            ],
        )
        .properties(height=420)
    )

    partisan_base = alt.Chart(partisan_df).encode(
        x=alt.X("year:O", sort=years, title="Year"),
        y=alt.Y(
            "value:Q",
            title="State partisanship / PVI",
            axis=alt.Axis(titleColor=SIGN_POSITIVE, labelColor=SIGN_POSITIVE, tickColor=SIGN_POSITIVE),
            scale=alt.Scale(zero=False),
        ),
        tooltip=[
            alt.Tooltip("year:O", title="Year"),
            alt.Tooltip("metric:N", title="Metric"),
            alt.Tooltip("value:Q", title="Value", format=".2f"),
        ],
    )

    partisan_lines = partisan_base.mark_line(strokeWidth=3).encode(
        color=alt.Color(
            "metric:N",
            scale=alt.Scale(
                domain=["State partisanship", "PVI"],
                range=[SIGN_POSITIVE, SIGN_NEGATIVE],
            ),
            legend=alt.Legend(title="Metric"),
        )
    )

    partisanship_points = (
        alt.Chart(partisanship_non_neutral_df)
        .mark_point(size=70, filled=True, color=SIGN_POSITIVE)
        .encode(
            x=alt.X("year:O", sort=years, title="Year"),
            y=alt.Y(
                "value:Q",
                title="State partisanship / PVI",
                axis=alt.Axis(titleColor=SIGN_POSITIVE, labelColor=SIGN_POSITIVE, tickColor=SIGN_POSITIVE),
                scale=alt.Scale(zero=False),
            ),
            tooltip=[
                alt.Tooltip("year:O", title="Year"),
                alt.Tooltip("metric:N", title="Metric"),
                alt.Tooltip("value:Q", title="Value", format=".2f"),
            ],
        )
        .properties(height=420)
    )

    partisanship_s_markers = (
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
            y=alt.Y(
                "value:Q",
                title="State partisanship / PVI",
                axis=alt.Axis(titleColor=SIGN_POSITIVE, labelColor=SIGN_POSITIVE, tickColor=SIGN_POSITIVE),
                scale=alt.Scale(zero=False),
            ),
            tooltip=[
                alt.Tooltip("year:O", title="Year"),
                alt.Tooltip("metric:N", title="Metric"),
                alt.Tooltip("value:Q", title="Value", format=".2f"),
            ],
        )
        .properties(height=420)
    )

    pvi_points = (
        alt.Chart(pvi_df)
        .mark_point(size=70, filled=True, color=SIGN_NEGATIVE)
        .encode(
            x=alt.X("year:O", sort=years, title="Year"),
            y=alt.Y(
                "value:Q",
                title="State partisanship / PVI",
                axis=alt.Axis(titleColor=SIGN_POSITIVE, labelColor=SIGN_POSITIVE, tickColor=SIGN_POSITIVE),
                scale=alt.Scale(zero=False),
            ),
            tooltip=[
                alt.Tooltip("year:O", title="Year"),
                alt.Tooltip("metric:N", title="Metric"),
                alt.Tooltip("value:Q", title="Value", format=".2f"),
            ],
        )
        .properties(height=420)
    )

    partisan_chart = alt.layer(
        partisan_lines,
        partisanship_points,
        partisanship_s_markers,
        pvi_points,
    )

    chart = alt.layer(
        partisan_chart,
        line_chart,
    ).resolve_scale(y="independent").properties(title=state)
    chart = chart.configure_view(stroke=None)
    return chart


@st.cache_data(show_spinner=False)
def available_state_names(df: pd.DataFrame) -> list[str]:
    ordered = [state for state in STATE_ORDER if state in set(df["state"])]
    remaining = sorted(set(df["state"]) - set(ordered))
    return ordered + remaining


st.set_page_config(page_title="Partisan Predictor", layout="wide")
st.title("Partisan Predictor")
st.write(
    "Select one or more states and a year range to compare population, state partisanship, and PVI. "
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

        st.altair_chart(state_chart(filtered, state), use_container_width=True)
        if state_df["state_partisanship"].notna().any():
            st.markdown(
                f"**Latest observed values** for {state}: "
                f"Population {state_df.iloc[-1]['population_total']:,.0f}, "
                f"State partisanship {state_df['state_partisanship'].dropna().iloc[-1]:.2f}, "
                f"PVI {state_df['pvi'].dropna().iloc[-1]:.2f}."
            )
        else:
            st.markdown(
                f"**Latest observed values** for {state}: population only in this date range; "
                "partisanship and PVI are not available for the selected years."
            )
