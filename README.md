# partisan-predictor

## Census Demographic Data Download

Use the downloader script to pull state-level Census ACS profile demographics by year.

Script location:
- `scripts/download_census_demographics.py`

Output files:
- `data/census/state_demographics_wide.csv` (one row per year + state)
- `data/census/state_demographics_long.csv` (tidy metric-value format)
- `data/census/metric_variable_map.json` (metric-to-Census-variable mapping used)

Included metrics:
- total population
- population density per square mile
- adult population (18+)
- male and female population
- education: bachelor's degree or higher (age 25+)
- race: white alone, black alone, asian alone
- ethnicity: hispanic/latino and not hispanic/latino

`population_density_per_sq_mile` is derived for every supported year as `population_total / state land area` using a bundled state land-area reference table.

### Run

```bash
python scripts/download_census_demographics.py --start-year 2010 --end-year 2025 --api-key YOUR_CENSUS_API_KEY
```

Optional flags:
- `--years 2012 2016 2020 2024` to use specific years
- `--api-key YOUR_CENSUS_API_KEY` (required for downloads)
- `--api-key-file census.key` to read key from a local file
- `--outdir data/census` to change output location

Year-by-year method (presidential-election timeline):
- `2008, 2012, 2016, 2024`: ACS 1-year profile (`acs/acs1/profile`).
- `2020`: ACS 5-year profile fallback (`acs/acs5/profile`) because ACS 1-year profile is unavailable for 2020.
- `2005`: ACS 1-year detailed tables (`acs/acs1`) with derived metrics for adult population and bachelor's-or-higher.
- `2004`: linear interpolation between 2000 and 2005 values, computed per state and metric.
- `2000`: Decennial Census (`dec/sf1` + `dec/sf3`) with derived metrics from SF table components.
- `1992, 1996`: 1990 PEP county aggregation (`1990/pep/int_charagegroups`) for `population_total` only.
- `1976, 1980, 1984, 1988`: interpolated `population_total` between decennial resident-population anchors.
- For `1976, 1980, 1984, 1988, 1992, 1996`, non-population metrics are set to null.
- Future unreleased years may return 404 and are skipped.

Interpolation formulas used:
- `value_2004 = value_2000 + (4/5) * (value_2005 - value_2000)`
- Pre-1990 population years use linear interpolation between decennial anchors for the surrounding decades.

You can also set `CENSUS_API_KEY` in your environment.

If `--api-key` and `CENSUS_API_KEY` are both missing, the script will read from `census.key` in the repo root by default (first non-empty line).

These files are structured to join on `year` + `state_abbr` (or `state_fips`) for future PVI/raw-partisanship comparisons.

## Presidential Election Results Download

Use the presidential results downloader to pull MIT Election Lab state-level presidential returns from Dataverse and normalize them to the same state identifiers used by the Census data.

Script location:
- `scripts/download_presidential_results.py`

Output files:
- `data/elections/presidential_results_raw.csv` (candidate-level state returns)
- `data/elections/presidential_results_by_party.csv` (state-year-party aggregation)
- `data/elections/presidential_results_source.json` (source and row-count metadata)
- `data/elections/state_partisanship_pvi.csv` (derived state and national partisanship plus PVI)

Run:

```bash
python scripts/download_presidential_results.py
```

Optional flags:
- `--years 2000 2004 2008 2012 2016 2020 2024` to keep specific election years
- `--start-year 1976 --end-year 2024` to set a year range
- `--guestbook-name`, `--guestbook-email`, `--guestbook-institution`, `--guestbook-position` to override the Dataverse guestbook fields

The raw output includes:
- `vote_pct` (candidate share of total votes in that state-year)
- `electoral_votes` (state electoral votes for that election year, based on Census apportionment)
- `electoral_votes_won_state` (electoral votes awarded to that candidate in that state-year)
- `electoral_votes_won_election` (total electoral votes awarded to that candidate in that election year)

The party-level CSV includes `year`, `state_fips`, `state_abbr`, and `state_name`, so it can be joined directly to the Census outputs. It also includes:
- `vote_pct` (party share of all votes in that state-year)
- `two_party_vote_pct` (party share of Democrat + Republican votes only)
- `electoral_votes` (state electoral votes for that election year)
- `electoral_votes_won_state` (electoral votes awarded to that party in that state-year)
- `electoral_votes_won_election` (total electoral votes awarded to that party in that election year)

Maine and Nebraska split allocations are handled with explicit state-year overrides (recorded in `presidential_results_source.json`) because the MIT source file does not include district-level presidential results.

## State Partisanship and PVI Output

The derived file `data/elections/state_partisanship_pvi.csv` is built from `data/elections/presidential_results_by_party.csv` using two-party (Democrat/Republican) vote shares.

Columns:
- `year`
- `state`
- `national_partisanship`
- `state_partisanship`
- `pvi`

Definitions (all in percentage points, rounded to 2 decimals):
- `state_partisanship = state_dem_share - state_rep_share`
- `national_partisanship = national_dem_share - national_rep_share`
- `pvi = state_partisanship - national_partisanship`

Sign convention:
- Positive values indicate Democratic lean.
- Negative values indicate Republican lean.

## Citation

MIT Election Lab / Dataverse citation details used for the presidential dataset are saved in:
- [mit_election_presidential_citation.md](mit_election_presidential_citation.md)

## Streamlit App

Use the interactive app to compare population, state partisanship, and PVI by state.

Run:

```bash
streamlit run app.py
```

Dependencies used by the app:
- `streamlit`
- `pandas`
- `altair`

The app lets you select one or more states and a year range from 1976 to 2024. Each state view shows:
- population as a line chart
- state partisanship and PVI as clustered bars
- blue for positive values and red for negative values