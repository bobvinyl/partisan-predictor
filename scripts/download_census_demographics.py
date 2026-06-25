#!/usr/bin/env python3
"""Download state-level Census demographics by year.

This script pulls selected metrics from U.S. Census API endpoints and writes
analysis-ready CSV files keyed by year and state. The outputs are structured for
downstream joins with political datasets like PVI or raw partisanship.

Data source:
- 2006+ (except 2020): https://api.census.gov/data/{year}/acs/acs1/profile
- 2020 fallback: https://api.census.gov/data/2020/acs/acs5/profile
- 2005 fallback: https://api.census.gov/data/2005/acs/acs1
- 2000 fallback: https://api.census.gov/data/2000/dec/sf1 and /dec/sf3

Example:
    python scripts/download_census_demographics.py --start-year 2010 --end-year 2025
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

BASE_URL_TEMPLATE = "https://api.census.gov/data/{year}/acs/acs1/profile"
USER_AGENT = "partisan-predictor/0.1 (demographics downloader)"
MIN_ACS1_PROFILE_YEAR = 2006
ACS5_PROFILE_2020_BASE_URL = "https://api.census.gov/data/2020/acs/acs5/profile"
ACS1_2005_BASE_URL = "https://api.census.gov/data/2005/acs/acs1"
DECENNIAL_2000_SF1_BASE_URL = "https://api.census.gov/data/2000/dec/sf1"
DECENNIAL_2000_SF3_BASE_URL = "https://api.census.gov/data/2000/dec/sf3"
PEP_1990_INT_CHARAGEGROUPS_BASE_URL = "https://api.census.gov/data/1990/pep/int_charagegroups"
APPORTIONMENT_HISTORY_CSV_URL = (
    "https://www2.census.gov/programs-surveys/decennial/2020/data/apportionment/apportionment.csv"
)

_STATE_LOOKUP_CACHE: Optional[Dict[str, str]] = None
_STATE_FIPS_NAME_CACHE: Optional[Dict[str, str]] = None
_APPORTIONMENT_ANCHOR_CACHE: Optional[Dict[int, Dict[str, float]]] = None

# State land area in square miles, used to derive population density from
# population totals for all supported years.
STATE_LAND_AREA_SQ_MILES: Dict[str, float] = {
    "01": 50645.33,
    "02": 570640.95,
    "04": 113594.08,
    "05": 52035.48,
    "06": 155779.22,
    "08": 103641.89,
    "09": 4842.36,
    "10": 1948.54,
    "11": 61.05,
    "12": 53624.76,
    "13": 57513.49,
    "15": 6422.63,
    "16": 82643.12,
    "17": 55518.93,
    "18": 35826.11,
    "19": 55857.13,
    "20": 81758.72,
    "21": 39486.34,
    "22": 43203.90,
    "23": 30842.92,
    "24": 9706.99,
    "25": 7800.06,
    "26": 56538.90,
    "27": 79626.74,
    "28": 46923.27,
    "29": 68741.52,
    "30": 145545.80,
    "31": 76824.17,
    "32": 109781.18,
    "33": 8952.65,
    "34": 7354.22,
    "35": 121298.15,
    "36": 47126.40,
    "37": 48617.91,
    "38": 69000.80,
    "39": 40860.69,
    "40": 68594.92,
    "41": 95988.01,
    "42": 44742.70,
    "44": 1033.81,
    "45": 30060.70,
    "46": 75811.00,
    "47": 41234.90,
    "48": 261231.71,
    "49": 82169.62,
    "50": 9216.66,
    "51": 39490.09,
    "53": 66455.52,
    "54": 24038.21,
    "55": 54157.80,
    "56": 97093.14,
}

# 50 states + DC. These are useful join keys for political datasets.
STATE_FIPS_TO_ABBR: Dict[str, str] = {
    "01": "AL",
    "02": "AK",
    "04": "AZ",
    "05": "AR",
    "06": "CA",
    "08": "CO",
    "09": "CT",
    "10": "DE",
    "11": "DC",
    "12": "FL",
    "13": "GA",
    "15": "HI",
    "16": "ID",
    "17": "IL",
    "18": "IN",
    "19": "IA",
    "20": "KS",
    "21": "KY",
    "22": "LA",
    "23": "ME",
    "24": "MD",
    "25": "MA",
    "26": "MI",
    "27": "MN",
    "28": "MS",
    "29": "MO",
    "30": "MT",
    "31": "NE",
    "32": "NV",
    "33": "NH",
    "34": "NJ",
    "35": "NM",
    "36": "NY",
    "37": "NC",
    "38": "ND",
    "39": "OH",
    "40": "OK",
    "41": "OR",
    "42": "PA",
    "44": "RI",
    "45": "SC",
    "46": "SD",
    "47": "TN",
    "48": "TX",
    "49": "UT",
    "50": "VT",
    "51": "VA",
    "53": "WA",
    "54": "WV",
    "55": "WI",
    "56": "WY",
}


@dataclass(frozen=True)
class MetricSpec:
    metric: str
    group: str
    required_tokens: Tuple[str, ...]
    preferred_ids: Tuple[str, ...] = ()


METRICS: Tuple[MetricSpec, ...] = (
    MetricSpec(
        metric="population_total",
        group="DP05",
        required_tokens=("estimate", "sex and age", "total population"),
        preferred_ids=("DP05_0001E",),
    ),
    MetricSpec(
        metric="population_adult_18_plus",
        group="DP05",
        required_tokens=("estimate", "sex and age", "total population", "18 years and over"),
        preferred_ids=("DP05_0024E",),
    ),
    MetricSpec(
        metric="population_male",
        group="DP05",
        required_tokens=("estimate", "sex and age", "total population", "male"),
        preferred_ids=("DP05_0002E",),
    ),
    MetricSpec(
        metric="population_female",
        group="DP05",
        required_tokens=("estimate", "sex and age", "total population", "female"),
        preferred_ids=("DP05_0003E",),
    ),
    MetricSpec(
        metric="education_bachelors_or_higher_25_plus",
        group="DP02",
        required_tokens=(
            "estimate",
            "educational attainment",
            "population 25 years and over",
            "bachelor",
            "or higher",
        ),
        preferred_ids=("DP02_0067E",),
    ),
    MetricSpec(
        metric="race_white_alone",
        group="DP05",
        required_tokens=("estimate", "race", "one race", "white"),
        preferred_ids=("DP05_0037E",),
    ),
    MetricSpec(
        metric="race_black_alone",
        group="DP05",
        required_tokens=("estimate", "race", "one race", "black"),
        preferred_ids=("DP05_0038E",),
    ),
    MetricSpec(
        metric="race_asian_alone",
        group="DP05",
        required_tokens=("estimate", "race", "one race", "asian"),
        preferred_ids=("DP05_0044E",),
    ),
    MetricSpec(
        metric="ethnicity_hispanic_or_latino",
        group="DP05",
        required_tokens=("estimate", "hispanic or latino", "of any race"),
        preferred_ids=("DP05_0071E",),
    ),
    MetricSpec(
        metric="ethnicity_not_hispanic_or_latino",
        group="DP05",
        required_tokens=("estimate", "not hispanic or latino"),
        preferred_ids=("DP05_0072E",),
    ),
)

DERIVED_METRICS: Tuple[str, ...] = ("population_density_per_sq_mile",)
ALL_METRIC_NAMES: Tuple[str, ...] = tuple(metric.metric for metric in METRICS) + DERIVED_METRICS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download Census demographics by year and state")
    parser.add_argument("--start-year", type=int, default=2010, help="First year (inclusive)")
    parser.add_argument("--end-year", type=int, default=2025, help="Last year (inclusive)")
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        help="Optional explicit list of years (overrides --start-year/--end-year)",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("data") / "census",
        help="Output directory for CSV and metadata files",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("CENSUS_API_KEY", ""),
        help="Census API key (or set CENSUS_API_KEY env var).",
    )
    parser.add_argument(
        "--api-key-file",
        type=Path,
        default=Path("census.key"),
        help="Path to file containing Census API key (first non-empty line)",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.25,
        help="Delay between API calls to reduce rate-limit risk",
    )
    return parser.parse_args()


def load_api_key(args: argparse.Namespace) -> str:
    if args.api_key:
        return args.api_key.strip()

    key_path: Path = args.api_key_file
    if key_path.exists() and key_path.is_file():
        for line in key_path.read_text(encoding="utf-8").splitlines():
            candidate = line.strip()
            if candidate:
                return candidate

    return ""


def http_get_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as response:
        raw = response.read()

    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        snippet = " ".join(text.split())[:220]
        if "Missing Key" in text:
            raise RuntimeError(
                "Census API key is required. Pass --api-key or set CENSUS_API_KEY."
            ) from exc
        raise RuntimeError(f"Census API returned non-JSON response: {snippet}") from exc


def fetch_group_metadata(year: int, group: str, api_key: str) -> Dict[str, object]:
    url = f"{BASE_URL_TEMPLATE.format(year=year)}/groups/{group}.json"
    if api_key:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}key={urllib.parse.quote(api_key)}"
    payload = http_get_json(url)
    if not isinstance(payload, dict) or "variables" not in payload:
        raise ValueError(f"Unexpected metadata format for year={year}, group={group}")
    return payload


def normalize_text(text: str) -> str:
    return " ".join(text.lower().replace("!", " ").split())


def normalize_state_name(text: str) -> str:
    return " ".join(
        text.lower()
        .replace(".", " ")
        .replace("-", " ")
        .replace("'", " ")
        .split()
    )


def get_state_name_to_fips(api_key: str) -> Dict[str, str]:
    global _STATE_LOOKUP_CACHE
    if _STATE_LOOKUP_CACHE is not None:
        return _STATE_LOOKUP_CACHE

    lookup: Dict[str, str] = {}
    for probe_year in (2024, 2023, 2022, 2021, 2019, 2010):
        try:
            rows = fetch_state_data(probe_year, [], api_key)
        except Exception:  # noqa: BLE001
            continue

        for row in rows:
            state_fips = row.get("state", "")
            state_name = row.get("NAME", "")
            if state_fips in STATE_FIPS_TO_ABBR and state_name:
                lookup[normalize_state_name(state_name)] = state_fips

        if lookup:
            _STATE_LOOKUP_CACHE = lookup
            return lookup

    raise RuntimeError("Unable to resolve state name lookup from Census API")


def get_state_fips_to_name(api_key: str) -> Dict[str, str]:
    global _STATE_FIPS_NAME_CACHE
    if _STATE_FIPS_NAME_CACHE is not None:
        return _STATE_FIPS_NAME_CACHE

    result: Dict[str, str] = {}
    for probe_year in (2024, 2023, 2022, 2021, 2019, 2010):
        try:
            rows = fetch_state_data(probe_year, [], api_key)
        except Exception:  # noqa: BLE001
            continue

        for row in rows:
            state_fips = row.get("state", "")
            state_name = row.get("NAME", "")
            if state_fips in STATE_FIPS_TO_ABBR and state_name:
                result[state_fips] = state_name

        if result:
            _STATE_FIPS_NAME_CACHE = result
            return result

    raise RuntimeError("Unable to resolve state FIPS->name lookup from Census API")


def empty_metric_map(label: str) -> Dict[str, Dict[str, str]]:
    metric_map: Dict[str, Dict[str, str]] = {}
    for metric in METRICS:
        if metric.metric == "population_total":
            metric_map[metric.metric] = {"id": label, "label": label}
        else:
            metric_map[metric.metric] = {"id": "", "label": "Unavailable for this source/year"}
    return metric_map


def add_population_density(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    for row in rows:
        state_fips = str(row.get("state_fips", ""))
        population_total = row.get("population_total")
        land_area_sq_miles = STATE_LAND_AREA_SQ_MILES.get(state_fips)

        if population_total is None or land_area_sq_miles in (None, 0):
            row["population_density_per_sq_mile"] = None
            continue

        row["population_density_per_sq_mile"] = float(population_total) / land_area_sq_miles

    return rows


def add_derived_metric_map(resolved: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    out = dict(resolved)
    out["population_density_per_sq_mile"] = {
        "id": "DERIVED_POPULATION_TOTAL_OVER_LAND_AREA",
        "label": "Derived as population_total divided by state land area in square miles",
    }
    return out


def finalize_year_output(
    rows: List[Dict[str, object]],
    resolved: Dict[str, Dict[str, str]],
    source_name: str,
) -> Tuple[List[Dict[str, object]], Dict[str, Dict[str, str]], str]:
    return add_population_density(rows), add_derived_metric_map(resolved), source_name


def build_population_only_rows(
    year: int,
    population_by_state_fips: Dict[str, float],
    api_key: str,
) -> List[Dict[str, object]]:
    name_by_fips = get_state_fips_to_name(api_key)
    metric_names = [m.metric for m in METRICS if m.metric != "population_total"]

    rows: List[Dict[str, object]] = []
    for state_fips in sorted(population_by_state_fips, key=int):
        if state_fips not in STATE_FIPS_TO_ABBR:
            continue

        state_name = name_by_fips.get(state_fips, "")

        rows.append(
            {
                "year": year,
                "state_fips": state_fips,
                "state_abbr": STATE_FIPS_TO_ABBR[state_fips],
                "state_name": state_name,
                "population_total": population_by_state_fips[state_fips],
                **{metric: None for metric in metric_names},
            }
        )

    return rows


def get_apportionment_anchor_populations(api_key: str) -> Dict[int, Dict[str, float]]:
    global _APPORTIONMENT_ANCHOR_CACHE
    if _APPORTIONMENT_ANCHOR_CACHE is not None:
        return _APPORTIONMENT_ANCHOR_CACHE

    raw = urllib.request.urlopen(APPORTIONMENT_HISTORY_CSV_URL, timeout=120).read().decode(
        "utf-8", errors="replace"
    )
    rows = csv.DictReader(raw.splitlines())

    name_to_fips = get_state_name_to_fips(api_key)
    anchors: Dict[int, Dict[str, float]] = {1970: {}, 1980: {}, 1990: {}}

    for row in rows:
        if row.get("Geography Type", "") != "State":
            continue

        try:
            year = int(row.get("Year", ""))
        except ValueError:
            continue
        if year not in anchors:
            continue

        name_norm = normalize_state_name(row.get("Name", ""))
        state_fips = name_to_fips.get(name_norm)
        if not state_fips:
            continue

        pop_text = row.get("Resident Population", "").replace(",", "").strip()
        if not pop_text:
            continue
        anchors[year][state_fips] = float(int(pop_text))

    _APPORTIONMENT_ANCHOR_CACHE = anchors
    return anchors


def build_year_pre1990_interpolated_population(
    year: int,
    api_key: str,
    sleep_seconds: float,
) -> Tuple[List[Dict[str, object]], Dict[str, Dict[str, str]]]:
    del sleep_seconds
    anchors = get_apportionment_anchor_populations(api_key)

    if year <= 1980:
        start_year, end_year = 1970, 1980
    else:
        start_year, end_year = 1980, 1990

    t = (year - start_year) / (end_year - start_year)
    start = anchors[start_year]
    end = anchors[end_year]

    pop_by_state: Dict[str, float] = {}
    for state_fips in sorted(set(start) & set(end), key=int):
        pop_by_state[state_fips] = start[state_fips] + (end[state_fips] - start[state_fips]) * t

    rows = build_population_only_rows(year, pop_by_state, api_key)
    source = f"Interpolated resident population between {start_year} and {end_year} decennial anchors"
    return rows, empty_metric_map(source)


def build_year_199x_pep_population(
    year: int,
    api_key: str,
    sleep_seconds: float,
) -> Tuple[List[Dict[str, object]], Dict[str, Dict[str, str]]]:
    year_code = str(year)[-2:]
    pop_by_state: Dict[str, float] = {}

    for state_fips in sorted(STATE_FIPS_TO_ABBR.keys(), key=int):
        query = {
            "get": "POP,YEAR,AGEGRP,HISP,RACE_SEX",
            "for": "county:*",
            "in": f"state:{state_fips}",
            "YEAR": year_code,
            "key": api_key,
        }
        url = f"{PEP_1990_INT_CHARAGEGROUPS_BASE_URL}?{urllib.parse.urlencode(query)}"
        payload = http_get_json(url)
        if not isinstance(payload, list) or len(payload) < 2:
            continue

        header = payload[0]
        if not isinstance(header, list):
            continue
        idx = {name: i for i, name in enumerate(header)}

        total = 0.0
        for raw_row in payload[1:]:
            if not isinstance(raw_row, list):
                continue
            agegrp = raw_row[idx.get("AGEGRP", -1)] if idx.get("AGEGRP", -1) >= 0 else ""
            hisp = raw_row[idx.get("HISP", -1)] if idx.get("HISP", -1) >= 0 else ""
            race_sex = raw_row[idx.get("RACE_SEX", -1)] if idx.get("RACE_SEX", -1) >= 0 else ""
            county_idx = idx.get("county", idx.get("COUNTY", -1))
            county = raw_row[county_idx] if county_idx >= 0 else ""
            # AGEGRP 00 + HISP 1 + RACE_SEX 01/02 gives male/female totals for all origins.
            # Exclude synthetic county 000 summary rows to avoid double counting.
            if agegrp != "00" or hisp != "1" or race_sex not in ("01", "02") or county == "000":
                continue

            value = parse_number(raw_row[idx.get("POP", -1)] if idx.get("POP", -1) >= 0 else "")
            if value is not None:
                total += value

        # PEP 1990 int_charagegroups stores counts in hundreds.
        pop_by_state[state_fips] = total * 100.0
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    rows = build_population_only_rows(year, pop_by_state, api_key)
    source = "1990 PEP county aggregation (total population only)"
    return rows, empty_metric_map(source)


def resolve_metric_var(
    metric: MetricSpec,
    group_variables: Dict[str, Dict[str, str]],
) -> Optional[Tuple[str, str]]:
    for preferred in metric.preferred_ids:
        if preferred in group_variables:
            return preferred, group_variables[preferred].get("label", "")

    best_match: Optional[Tuple[str, str]] = None
    for variable_id, details in group_variables.items():
        if not variable_id.endswith("E"):
            continue
        label = details.get("label", "")
        label_norm = normalize_text(label)
        if all(token in label_norm for token in metric.required_tokens):
            best_match = (variable_id, label)
            break

    return best_match


def fetch_state_data(
    year: int,
    variables: Iterable[str],
    api_key: str,
    base_url: Optional[str] = None,
) -> List[Dict[str, str]]:
    var_list = ["NAME", *variables]
    query_params = {
        "get": ",".join(var_list),
        "for": "state:*",
    }
    if api_key:
        query_params["key"] = api_key

    base = base_url or BASE_URL_TEMPLATE.format(year=year)
    url = f"{base}?{urllib.parse.urlencode(query_params)}"
    payload = http_get_json(url)
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"Unexpected data format for year={year}")

    headers = payload[0]
    if not isinstance(headers, list):
        raise ValueError(f"Unexpected header format for year={year}")

    rows: List[Dict[str, str]] = []
    for row in payload[1:]:
        if not isinstance(row, list):
            continue
        rows.append(dict(zip(headers, row)))

    return rows


def fetch_state_data_chunked(
    year: int,
    variables: Iterable[str],
    api_key: str,
    base_url: str,
    chunk_size: int = 45,
) -> List[Dict[str, str]]:
    var_list = list(dict.fromkeys(variables))
    if not var_list:
        return []

    merged_by_state: Dict[str, Dict[str, str]] = {}
    for i in range(0, len(var_list), chunk_size):
        chunk = var_list[i : i + chunk_size]
        rows = fetch_state_data(year, chunk, api_key, base_url=base_url)
        for row in rows:
            state_fips = row.get("state", "")
            if not state_fips:
                continue
            if state_fips not in merged_by_state:
                merged_by_state[state_fips] = {
                    "state": state_fips,
                    "NAME": row.get("NAME", ""),
                }
            merged_by_state[state_fips].update(row)

    merged_rows = list(merged_by_state.values())
    merged_rows.sort(key=lambda r: int(r["state"]))
    return merged_rows


def parse_number(value: str) -> Optional[float]:
    if value in ("", None, "null", "N", "-", "(X)"):
        return None
    try:
        if "." in value:
            return float(value)
        return float(int(value))
    except (TypeError, ValueError):
        return None


def sum_values(row: Dict[str, str], variable_ids: Iterable[str]) -> Optional[float]:
    values = [parse_number(row.get(var_id, "")) for var_id in variable_ids]
    numeric = [v for v in values if v is not None]
    if not numeric:
        return None
    return float(sum(numeric))


def build_year_profile(
    year: int,
    api_key: str,
    sleep_seconds: float,
    profile_base_url: Optional[str] = None,
) -> Tuple[List[Dict[str, object]], Dict[str, Dict[str, str]]]:
    group_cache: Dict[str, Dict[str, object]] = {}
    resolved: Dict[str, Dict[str, str]] = {}

    for metric in METRICS:
        if metric.group not in group_cache:
            base = profile_base_url or BASE_URL_TEMPLATE.format(year=year)
            metadata_url = f"{base}/groups/{metric.group}.json"
            if api_key:
                metadata_url = f"{metadata_url}?key={urllib.parse.quote(api_key)}"
            payload = http_get_json(metadata_url)
            if not isinstance(payload, dict) or "variables" not in payload:
                raise ValueError(f"Unexpected metadata format for year={year}, group={metric.group}")
            group_cache[metric.group] = payload
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        variables = group_cache[metric.group].get("variables", {})
        if not isinstance(variables, dict):
            raise ValueError(f"Bad variable metadata for group={metric.group} year={year}")

        match = resolve_metric_var(metric, variables)
        if match is None:
            resolved[metric.metric] = {"id": "", "label": ""}
        else:
            resolved[metric.metric] = {"id": match[0], "label": match[1]}

    query_var_ids = [v["id"] for v in resolved.values() if v["id"]]
    if not query_var_ids:
        return [], resolved

    raw_rows = fetch_state_data(year, query_var_ids, api_key, base_url=profile_base_url)
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)

    normalized_rows: List[Dict[str, object]] = []
    for row in raw_rows:
        state_fips = row.get("state", "")
        if state_fips not in STATE_FIPS_TO_ABBR:
            continue

        out_row: Dict[str, object] = {
            "year": year,
            "state_fips": state_fips,
            "state_abbr": STATE_FIPS_TO_ABBR[state_fips],
            "state_name": row.get("NAME", ""),
        }

        for metric_name, info in resolved.items():
            variable_id = info["id"]
            out_row[metric_name] = parse_number(row.get(variable_id, "")) if variable_id else None

        normalized_rows.append(out_row)

    normalized_rows.sort(key=lambda r: (int(r["state_fips"]), r["state_name"]))
    return normalized_rows, resolved


def build_year_2005_acs1(
    year: int,
    api_key: str,
    sleep_seconds: float,
) -> Tuple[List[Dict[str, object]], Dict[str, Dict[str, str]]]:
    del year  # Fixed endpoint for this builder.

    adult_vars = [
        *[f"B01001_{i:03d}E" for i in range(7, 26)],
        *[f"B01001_{i:03d}E" for i in range(31, 50)],
    ]
    bachelors_plus_vars = [
        "B15002_015E",
        "B15002_016E",
        "B15002_017E",
        "B15002_018E",
        "B15002_032E",
        "B15002_033E",
        "B15002_034E",
        "B15002_035E",
    ]

    var_ids = [
        "B01001_001E",
        "B01001_002E",
        "B01001_026E",
        "B02001_002E",
        "B02001_003E",
        "B02001_005E",
        "B03002_012E",
        "B03002_013E",
        *adult_vars,
        *bachelors_plus_vars,
    ]
    var_ids = sorted(set(var_ids))
    raw_rows = fetch_state_data_chunked(2005, var_ids, api_key, base_url=ACS1_2005_BASE_URL)
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)

    resolved = {
        "population_total": {"id": "B01001_001E", "label": "Estimate!!Total population"},
        "population_adult_18_plus": {
            "id": "SUM(" + ",".join(adult_vars) + ")",
            "label": "Derived from B01001 sex-by-age detailed table",
        },
        "population_male": {"id": "B01001_002E", "label": "Estimate!!Male"},
        "population_female": {"id": "B01001_026E", "label": "Estimate!!Female"},
        "education_bachelors_or_higher_25_plus": {
            "id": "SUM(" + ",".join(bachelors_plus_vars) + ")",
            "label": "Derived from B15002 educational attainment",
        },
        "race_white_alone": {"id": "B02001_002E", "label": "Estimate!!White alone"},
        "race_black_alone": {"id": "B02001_003E", "label": "Estimate!!Black or African American alone"},
        "race_asian_alone": {"id": "B02001_005E", "label": "Estimate!!Asian alone"},
        "ethnicity_hispanic_or_latino": {"id": "B03002_012E", "label": "Estimate!!Hispanic or Latino"},
        "ethnicity_not_hispanic_or_latino": {"id": "B03002_013E", "label": "Estimate!!Not Hispanic or Latino"},
    }

    normalized_rows: List[Dict[str, object]] = []
    for row in raw_rows:
        state_fips = row.get("state", "")
        if state_fips not in STATE_FIPS_TO_ABBR:
            continue

        normalized_rows.append(
            {
                "year": 2005,
                "state_fips": state_fips,
                "state_abbr": STATE_FIPS_TO_ABBR[state_fips],
                "state_name": row.get("NAME", ""),
                "population_total": parse_number(row.get("B01001_001E", "")),
                "population_adult_18_plus": sum_values(row, adult_vars),
                "population_male": parse_number(row.get("B01001_002E", "")),
                "population_female": parse_number(row.get("B01001_026E", "")),
                "education_bachelors_or_higher_25_plus": sum_values(row, bachelors_plus_vars),
                "race_white_alone": parse_number(row.get("B02001_002E", "")),
                "race_black_alone": parse_number(row.get("B02001_003E", "")),
                "race_asian_alone": parse_number(row.get("B02001_005E", "")),
                "ethnicity_hispanic_or_latino": parse_number(row.get("B03002_012E", "")),
                "ethnicity_not_hispanic_or_latino": parse_number(row.get("B03002_013E", "")),
            }
        )

    normalized_rows.sort(key=lambda r: (int(r["state_fips"]), r["state_name"]))
    return normalized_rows, resolved


def build_year_2000_decennial(
    year: int,
    api_key: str,
    sleep_seconds: float,
) -> Tuple[List[Dict[str, object]], Dict[str, Dict[str, str]]]:
    del year  # Fixed endpoint for this builder.

    sf1_adult_vars = [
        *[f"P012{i:03d}" for i in range(8, 26)],
        *[f"P012{i:03d}" for i in range(32, 50)],
    ]
    sf1_vars = [
        "P001001",
        "P012002",
        "P012026",
        "P003002",
        "P003003",
        "P003005",
        "P004002",
        "P004003",
        *sf1_adult_vars,
    ]
    sf1_rows = fetch_state_data(2000, sorted(set(sf1_vars)), api_key, base_url=DECENNIAL_2000_SF1_BASE_URL)
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)

    sf3_bachelors_plus_vars = [
        "P037015",
        "P037016",
        "P037017",
        "P037018",
        "P037032",
        "P037033",
        "P037034",
        "P037035",
    ]
    sf3_rows = fetch_state_data(2000, sf3_bachelors_plus_vars, api_key, base_url=DECENNIAL_2000_SF3_BASE_URL)
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)

    sf3_by_state = {row.get("state", ""): row for row in sf3_rows}

    resolved = {
        "population_total": {"id": "P001001", "label": "Total population (2000 SF1)"},
        "population_adult_18_plus": {
            "id": "SUM(" + ",".join(sf1_adult_vars) + ")",
            "label": "Derived from P012 sex-by-age table (2000 SF1)",
        },
        "population_male": {"id": "P012002", "label": "Total!!Male (2000 SF1)"},
        "population_female": {"id": "P012026", "label": "Total!!Female (2000 SF1)"},
        "education_bachelors_or_higher_25_plus": {
            "id": "SUM(" + ",".join(sf3_bachelors_plus_vars) + ")",
            "label": "Derived from P037 educational attainment (2000 SF3)",
        },
        "race_white_alone": {"id": "P003002", "label": "White alone (2000 SF1)"},
        "race_black_alone": {"id": "P003003", "label": "Black or African American alone (2000 SF1)"},
        "race_asian_alone": {"id": "P003005", "label": "Asian alone (2000 SF1)"},
        "ethnicity_hispanic_or_latino": {"id": "P004002", "label": "Hispanic or Latino (2000 SF1)"},
        "ethnicity_not_hispanic_or_latino": {"id": "P004003", "label": "Not Hispanic or Latino (2000 SF1)"},
    }

    normalized_rows: List[Dict[str, object]] = []
    for row in sf1_rows:
        state_fips = row.get("state", "")
        if state_fips not in STATE_FIPS_TO_ABBR:
            continue
        row_sf3 = sf3_by_state.get(state_fips, {})

        normalized_rows.append(
            {
                "year": 2000,
                "state_fips": state_fips,
                "state_abbr": STATE_FIPS_TO_ABBR[state_fips],
                "state_name": row.get("NAME", ""),
                "population_total": parse_number(row.get("P001001", "")),
                "population_adult_18_plus": sum_values(row, sf1_adult_vars),
                "population_male": parse_number(row.get("P012002", "")),
                "population_female": parse_number(row.get("P012026", "")),
                "education_bachelors_or_higher_25_plus": sum_values(row_sf3, sf3_bachelors_plus_vars),
                "race_white_alone": parse_number(row.get("P003002", "")),
                "race_black_alone": parse_number(row.get("P003003", "")),
                "race_asian_alone": parse_number(row.get("P003005", "")),
                "ethnicity_hispanic_or_latino": parse_number(row.get("P004002", "")),
                "ethnicity_not_hispanic_or_latino": parse_number(row.get("P004003", "")),
            }
        )

    normalized_rows.sort(key=lambda r: (int(r["state_fips"]), r["state_name"]))
    return normalized_rows, resolved


def interpolate_row_values(
    row_start: Dict[str, object],
    row_end: Dict[str, object],
    t: float,
    year: int,
) -> Dict[str, object]:
    out_row: Dict[str, object] = {
        "year": year,
        "state_fips": row_start["state_fips"],
        "state_abbr": row_start["state_abbr"],
        "state_name": row_start["state_name"],
    }

    metric_names = list(ALL_METRIC_NAMES)
    for metric in metric_names:
        start_val = row_start.get(metric)
        end_val = row_end.get(metric)
        if start_val is None or end_val is None:
            out_row[metric] = None
            continue
        out_row[metric] = float(start_val) + (float(end_val) - float(start_val)) * t

    return out_row


def build_year_2004_interpolated(
    year: int,
    api_key: str,
    sleep_seconds: float,
) -> Tuple[List[Dict[str, object]], Dict[str, Dict[str, str]]]:
    del year
    rows_2000, _ = build_year_2000_decennial(2000, api_key, sleep_seconds)
    rows_2005, _ = build_year_2005_acs1(2005, api_key, sleep_seconds)

    by_state_2000 = {row["state_fips"]: row for row in rows_2000}
    by_state_2005 = {row["state_fips"]: row for row in rows_2005}

    # 2004 is 4/5 of the way from 2000 to 2005.
    t = 4.0 / 5.0
    interpolated_rows: List[Dict[str, object]] = []
    for state_fips in sorted(set(by_state_2000) & set(by_state_2005), key=int):
        interpolated_rows.append(
            interpolate_row_values(by_state_2000[state_fips], by_state_2005[state_fips], t, 2004)
        )

    resolved = {
        metric.metric: {
            "id": "INTERPOLATED_2000_TO_2005",
            "label": "Linear interpolation between 2000 decennial and 2005 ACS detailed",
        }
        for metric in METRICS
    }
    return interpolated_rows, resolved


def build_year(
    year: int,
    api_key: str,
    sleep_seconds: float,
) -> Tuple[List[Dict[str, object]], Dict[str, Dict[str, str]], str]:
    if year in (1976, 1980, 1984, 1988):
        rows, resolved = build_year_pre1990_interpolated_population(year, api_key, sleep_seconds)
        return finalize_year_output(rows, resolved, "interpolated population (decennial anchors)")

    if year in (1992, 1996):
        rows, resolved = build_year_199x_pep_population(year, api_key, sleep_seconds)
        return finalize_year_output(rows, resolved, "1990 PEP county aggregation (population only)")

    if year == 2020:
        rows, resolved = build_year_profile(
            year,
            api_key,
            sleep_seconds,
            profile_base_url=ACS5_PROFILE_2020_BASE_URL,
        )
        return finalize_year_output(rows, resolved, "acs/acs5/profile")

    if year >= MIN_ACS1_PROFILE_YEAR:
        rows, resolved = build_year_profile(year, api_key, sleep_seconds)
        return finalize_year_output(rows, resolved, "acs/acs1/profile")

    if year == 2005:
        rows, resolved = build_year_2005_acs1(year, api_key, sleep_seconds)
        return finalize_year_output(rows, resolved, "acs/acs1 (detailed tables)")

    if year == 2004:
        rows, resolved = build_year_2004_interpolated(year, api_key, sleep_seconds)
        return finalize_year_output(rows, resolved, "interpolated (2000 decennial -> 2005 ACS detailed)")

    if year == 2000:
        rows, resolved = build_year_2000_decennial(year, api_key, sleep_seconds)
        return finalize_year_output(rows, resolved, "dec/sf1 + dec/sf3")

    raise ValueError(
        "No supported Census API fallback configured for this year. "
        "Supported years: 1976, 1980, 1984, 1988, 1992, 1996, 2000, 2004, 2005, and 2006+ "
        "(with 2020 routed to ACS5 profile)."
    )


def write_wide_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        return

    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_long_csv(path: Path, rows: List[Dict[str, object]], metric_names: Iterable[str]) -> None:
    fields = ["year", "state_fips", "state_abbr", "state_name", "metric", "value"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            for metric in metric_names:
                writer.writerow(
                    {
                        "year": row["year"],
                        "state_fips": row["state_fips"],
                        "state_abbr": row["state_abbr"],
                        "state_name": row["state_name"],
                        "metric": metric,
                        "value": row.get(metric),
                    }
                )


def main() -> int:
    args = parse_args()
    api_key = load_api_key(args)

    if not api_key:
        print("Census API key is required for data downloads.")
        print("Pass --api-key, set CENSUS_API_KEY, or place key in census.key.")
        return 2

    if args.years:
        years = sorted(set(args.years))
    else:
        if args.end_year < args.start_year:
            raise ValueError("--end-year must be >= --start-year")
        years = list(range(args.start_year, args.end_year + 1))

    filtered_years: List[int] = []
    unsupported_years: List[int] = []
    for year in years:
        if year in (1976, 1980, 1984, 1988, 1992, 1996, 2000, 2004, 2005) or year >= MIN_ACS1_PROFILE_YEAR:
            filtered_years.append(year)
        else:
            unsupported_years.append(year)

    if unsupported_years:
        print(
            "Skipping unsupported years for configured Census endpoint fallbacks: "
            + ", ".join(str(y) for y in unsupported_years)
        )
        print(
            "Supported years are 1976, 1980, 1984, 1988, 1992, 1996, 2000, 2004, 2005, and 2006+ "
            "(with 2020 routed to ACS 5-year profile)."
        )

    years = filtered_years
    if not years:
        print("No supported years requested after filtering. Nothing to download.")
        return 1

    args.outdir.mkdir(parents=True, exist_ok=True)

    all_rows: List[Dict[str, object]] = []
    variable_map_by_year: Dict[int, Dict[str, Dict[str, str]]] = {}

    for year in years:
        print(f"Downloading Census data for {year}...")
        try:
            rows, resolved, source_name = build_year(year, api_key, args.sleep_seconds)
            print(f"  Source: {source_name}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                print(
                    f"  Skipping {year}: Census endpoint not available (HTTP 404). "
                    "This can happen for unreleased years."
                )
            else:
                print(f"  Skipping {year}: HTTP {exc.code} from Census API")
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"  Skipping {year}: {exc}")
            continue

        if not rows:
            print(f"  No rows returned for {year}.")
            continue

        all_rows.extend(rows)
        variable_map_by_year[year] = resolved
        print(f"  Retrieved {len(rows)} state rows")

    if not all_rows:
        print("No data downloaded. Check year range and API availability.")
        return 1

    all_rows.sort(key=lambda r: (int(r["year"]), int(r["state_fips"])))

    wide_path = args.outdir / "state_demographics_wide.csv"
    long_path = args.outdir / "state_demographics_long.csv"
    map_path = args.outdir / "metric_variable_map.json"

    metric_names = list(ALL_METRIC_NAMES)
    write_wide_csv(wide_path, all_rows)
    write_long_csv(long_path, all_rows, metric_names)

    with map_path.open("w", encoding="utf-8") as f:
        json.dump(variable_map_by_year, f, indent=2)

    print(f"Wrote wide file: {wide_path}")
    print(f"Wrote long file: {long_path}")
    print(f"Wrote metric map: {map_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
