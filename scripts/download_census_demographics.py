#!/usr/bin/env python3
"""Download state-level Census demographics by year.

This script pulls selected metrics from the U.S. Census Bureau ACS 1-year profile API
and writes analysis-ready CSV files keyed by year and state. The outputs are structured
for downstream joins with political datasets like PVI or raw partisanship.

Data source:
- https://api.census.gov/data/{year}/acs/acs1/profile

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
) -> List[Dict[str, str]]:
    var_list = ["NAME", *variables]
    query_params = {
        "get": ",".join(var_list),
        "for": "state:*",
    }
    if api_key:
        query_params["key"] = api_key

    base = BASE_URL_TEMPLATE.format(year=year)
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


def parse_number(value: str) -> Optional[float]:
    if value in ("", None, "null", "N", "-", "(X)"):
        return None
    try:
        if "." in value:
            return float(value)
        return float(int(value))
    except (TypeError, ValueError):
        return None


def build_year(year: int, api_key: str, sleep_seconds: float) -> Tuple[List[Dict[str, object]], Dict[str, Dict[str, str]]]:
    group_cache: Dict[str, Dict[str, object]] = {}
    resolved: Dict[str, Dict[str, str]] = {}

    for metric in METRICS:
        if metric.group not in group_cache:
            group_cache[metric.group] = fetch_group_metadata(year, metric.group, api_key)
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

    raw_rows = fetch_state_data(year, query_var_ids, api_key)
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

    args.outdir.mkdir(parents=True, exist_ok=True)

    all_rows: List[Dict[str, object]] = []
    variable_map_by_year: Dict[int, Dict[str, Dict[str, str]]] = {}

    for year in years:
        print(f"Downloading Census profile data for {year}...")
        try:
            rows, resolved = build_year(year, api_key, args.sleep_seconds)
        except urllib.error.HTTPError as exc:
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

    metric_names = [m.metric for m in METRICS]
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
