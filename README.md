# partisan-predictor

## Census Demographic Data Download

Use the downloader script to pull state-level Census ACS profile demographics by year.

Script location:
- `scripts/download_census_demographics.py`

Output files:
- `data/census/state_demographics_wide.csv` (one row per year + state)
- `data/census/state_demographics_long.csv` (tidy metric-value format)
- `data/census/metric_variable_map.json` (metric-to-Census-variable mapping used)

Included metrics (counts):
- total population
- adult population (18+)
- male and female population
- education: bachelor's degree or higher (age 25+)
- race: white alone, black alone, asian alone
- ethnicity: hispanic/latino and not hispanic/latino

### Run

```bash
python scripts/download_census_demographics.py --start-year 2010 --end-year 2025 --api-key YOUR_CENSUS_API_KEY
```

Optional flags:
- `--years 2012 2016 2020 2024` to use specific years
- `--api-key YOUR_CENSUS_API_KEY` (required for downloads)
- `--api-key-file census.key` to read key from a local file
- `--outdir data/census` to change output location

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

The raw output includes a rounded `vote_pct` column (candidate share of total votes in that state-year).

The party-level CSV includes `year`, `state_fips`, `state_abbr`, and `state_name`, so it can be joined directly to the Census outputs. It also includes:
- `vote_pct` (party share of all votes in that state-year)
- `two_party_vote_pct` (party share of Democrat + Republican votes only)

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