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