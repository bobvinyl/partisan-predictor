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

    census = census[
        ["year", "state_name", "state_abbr", "population_total", "population_density_per_sq_mile"]
    ].copy()
    census["state"] = census["state_name"].str.replace("District Of Columbia", "District of Columbia", regex=False)

    pvi = pvi.copy()
    pvi["state"] = pvi["state"].str.replace("District Of Columbia", "District of Columbia", regex=False)

    df = census.merge(pvi, on=["year", "state"], how="left")
    df["population_total"] = pd.to_numeric(df["population_total"], errors="coerce")
    df["population_density_per_sq_mile"] = pd.to_numeric(df["population_density_per_sq_mile"], errors="coerce")
    df["state_partisanship"] = pd.to_numeric(df["state_partisanship"], errors="coerce")
    df["pvi"] = pd.to_numeric(df["pvi"], errors="coerce")
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
        partisan_chart = alt.layer(*partisan_layers)
        chart = alt.layer(partisan_chart, line_chart).resolve_scale(y="independent").properties(title=state)
    else:
        chart = line_chart.properties(title=state)

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
