#!/usr/bin/env python3
"""Download presidential election results by state and party.

This script downloads the MIT Election Lab / Harvard Dataverse state-level
presidential returns dataset (1976-2024), normalizes it to Census-compatible
state identifiers, and writes analysis-ready CSVs for downstream joins.

Primary source:
- https://electionlab.mit.edu/data
- https://doi.org/10.7910/DVN/42MVDX
- Dataverse file: 1976-2024-president.csv

Outputs:
- presidential_results_raw.csv: candidate-level state returns
- presidential_results_by_party.csv: state-year-party aggregation suitable for
  joining to Census demographics and partisan measures
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, List, Optional, Tuple
import urllib.parse
import urllib.request

DATASET_DOI = "doi:10.7910/DVN/42MVDX"
FILE_ID = 13887042
USER_AGENT = "partisan-predictor/0.1 (presidential results downloader)"
SOURCE_URL_TEMPLATE = "https://dataverse.harvard.edu/api/access/datafile/{file_id}"

# 50 states + DC, aligned with the Census downloader.
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download presidential election results by state and party")
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        help="Optional explicit list of election years to keep (default: all years in the dataset)",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=1976,
        help="First election year to keep when --years is not provided",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2024,
        help="Last election year to keep when --years is not provided",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("data") / "elections",
        help="Output directory for CSV files",
    )
    parser.add_argument(
        "--guestbook-name",
        default=os.environ.get("DATAVERSE_GUESTBOOK_NAME", "partisan-predictor"),
        help="Guestbook name sent to Dataverse when requesting a signed download URL",
    )
    parser.add_argument(
        "--guestbook-email",
        default=os.environ.get("DATAVERSE_GUESTBOOK_EMAIL", "local@example.com"),
        help="Guestbook email sent to Dataverse when requesting a signed download URL",
    )
    parser.add_argument(
        "--guestbook-institution",
        default=os.environ.get("DATAVERSE_GUESTBOOK_INSTITUTION", "partisan-predictor"),
        help="Guestbook institution sent to Dataverse when requesting a signed download URL",
    )
    parser.add_argument(
        "--guestbook-position",
        default=os.environ.get("DATAVERSE_GUESTBOOK_POSITION", "analysis"),
        help="Guestbook position sent to Dataverse when requesting a signed download URL",
    )
    parser.add_argument(
        "--dataset-doi",
        default=DATASET_DOI,
        help="Dataverse persistent identifier for citation metadata",
    )
    parser.add_argument(
        "--file-id",
        type=int,
        default=FILE_ID,
        help="Dataverse file ID for the presidential state CSV",
    )
    return parser.parse_args()


def http_get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def request_signed_url(
    file_id: int,
    guestbook_name: str,
    guestbook_email: str,
    guestbook_institution: str,
    guestbook_position: str,
) -> str:
    payload = {
        "guestbookResponse": {
            "name": guestbook_name,
            "email": guestbook_email,
            "institution": guestbook_institution,
            "position": guestbook_position,
        }
    }
    url = f"{SOURCE_URL_TEMPLATE.format(file_id=file_id)}?signed=true"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        body = json.loads(response.read().decode("utf-8"))

    signed_url = body.get("data", {}).get("signedUrl")
    if not signed_url:
        raise RuntimeError("Dataverse did not return a signed download URL")
    return signed_url


def normalize_state_fips(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    try:
        return f"{int(float(value)):02d}"
    except ValueError:
        return value.zfill(2)


def normalized_state_name(value: str) -> str:
    value = (value or "").strip().lower()
    if not value:
        return ""
    return " ".join(part.capitalize() for part in value.split())


def normalize_party(value: str) -> str:
    value = (value or "").strip()
    return value if value else "OTHER"


def parse_int(value: str) -> Optional[int]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def pct(votes: int, total: int) -> Optional[float]:
    if total <= 0:
        return None
    return round((votes / total) * 100, 2)


def parse_csv_rows(csv_text: str) -> List[Dict[str, str]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    return [row for row in reader if row]


def keep_year(year: int, years: Optional[Iterable[int]], start_year: int, end_year: int) -> bool:
    if years is not None:
        return year in set(years)
    return start_year <= year <= end_year


def aggregate_by_state_party(rows: List[Dict[str, str]]) -> List[Dict[str, object]]:
    grouped: DefaultDict[
        Tuple[int, str, str, str, str, str],
        Dict[str, object],
    ] = defaultdict(lambda: {"votes": 0, "totalvotes": 0})

    for row in rows:
        year = parse_int(row.get("year", ""))
        if year is None:
            continue

        state_fips = normalize_state_fips(row.get("state_fips", ""))
        state_abbr = (row.get("state_po", "") or "").strip().upper()
        state_name = normalized_state_name(row.get("state", ""))
        party_detailed = normalize_party(row.get("party_detailed", ""))
        party_simplified = normalize_party(row.get("party_simplified", ""))
        candidate = (row.get("candidate", "") or "").strip()
        writein = (row.get("writein", "") or "").strip().lower() in {"true", "t", "1", "yes"}
        votes = parse_int(row.get("candidatevotes", "")) or 0
        totalvotes = parse_int(row.get("totalvotes", "")) or 0

        key = (year, state_fips, state_abbr, state_name, party_detailed, party_simplified)
        grouped[key]["votes"] = int(grouped[key]["votes"]) + votes
        grouped[key]["totalvotes"] = max(int(grouped[key]["totalvotes"]), totalvotes)
        grouped[key]["candidate_examples"] = grouped[key].get("candidate_examples", [])
        if candidate and len(grouped[key]["candidate_examples"]) < 3:
            grouped[key]["candidate_examples"].append(candidate)
        grouped[key]["writein_count"] = int(grouped[key].get("writein_count", 0)) + int(writein)

    aggregated: List[Dict[str, object]] = []
    year_state_totals: Dict[Tuple[int, str], Dict[str, int]] = defaultdict(lambda: {"democrat": 0, "republican": 0, "total": 0})

    for key, value in grouped.items():
        year, state_fips, state_abbr, state_name, party_detailed, party_simplified = key
        votes = int(value["votes"])
        totalvotes = int(value["totalvotes"])
        party_norm = party_simplified.upper()

        if party_norm == "DEMOCRAT":
            year_state_totals[(year, state_fips)]["democrat"] += votes
        elif party_norm == "REPUBLICAN":
            year_state_totals[(year, state_fips)]["republican"] += votes
        year_state_totals[(year, state_fips)]["total"] = max(year_state_totals[(year, state_fips)]["total"], totalvotes)

        aggregated.append(
            {
                "year": year,
                "state_fips": state_fips,
                "state_abbr": state_abbr,
                "state_name": state_name,
                "party_detailed": party_detailed,
                "party_simplified": party_simplified,
                "votes": votes,
                "total_votes": totalvotes,
                "vote_pct": pct(votes, totalvotes),
                "vote_share_of_total": (votes / totalvotes) if totalvotes else None,
                "candidate_examples": "; ".join(value.get("candidate_examples", [])),
                "writein_count": int(value.get("writein_count", 0)),
            }
        )

    for row in aggregated:
        year = int(row["year"])
        state_fips = str(row["state_fips"])
        totals = year_state_totals[(year, state_fips)]
        two_party_total = totals["democrat"] + totals["republican"]
        row["democratic_votes_state"] = totals["democrat"]
        row["republican_votes_state"] = totals["republican"]
        row["two_party_total_votes"] = two_party_total
        if row["party_simplified"].upper() in {"DEMOCRAT", "REPUBLICAN"} and two_party_total:
            row["two_party_vote_share"] = row["votes"] / two_party_total
            row["two_party_vote_pct"] = round((row["votes"] / two_party_total) * 100, 2)
        else:
            row["two_party_vote_share"] = None
            row["two_party_vote_pct"] = None

    aggregated.sort(key=lambda r: (int(r["year"]), str(r["state_fips"]), str(r["party_simplified"]), str(r["party_detailed"])))
    return aggregated


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()

    years = sorted(set(args.years)) if args.years else None
    if years is None and args.end_year < args.start_year:
        raise ValueError("--end-year must be >= --start-year")

    args.outdir.mkdir(parents=True, exist_ok=True)

    print("Requesting Dataverse signed download URL...")
    signed_url = request_signed_url(
        args.file_id,
        args.guestbook_name,
        args.guestbook_email,
        args.guestbook_institution,
        args.guestbook_position,
    )

    print("Downloading presidential results CSV...")
    csv_text = http_get_text(signed_url)
    rows = parse_csv_rows(csv_text)
    if not rows:
        print("No rows were downloaded from Dataverse.")
        return 1

    raw_rows: List[Dict[str, object]] = []
    for row in rows:
        year = parse_int(row.get("year", ""))
        if year is None:
            continue
        if not keep_year(year, years, args.start_year, args.end_year):
            continue

        candidatevotes = parse_int(row.get("candidatevotes", ""))
        totalvotes = parse_int(row.get("totalvotes", ""))

        raw_rows.append(
            {
                "year": year,
                "state_fips": normalize_state_fips(row.get("state_fips", "")),
                "state_abbr": (row.get("state_po", "") or "").strip().upper(),
                "state_name": normalized_state_name(row.get("state", "")),
                "office": (row.get("office", "") or "").strip(),
                "candidate": (row.get("candidate", "") or "").strip(),
                "party_detailed": normalize_party(row.get("party_detailed", "")),
                "party_simplified": normalize_party(row.get("party_simplified", "")),
                "writein": (row.get("writein", "") or "").strip().lower() in {"true", "t", "1", "yes"},
                "candidatevotes": candidatevotes,
                "totalvotes": totalvotes,
                "vote_pct": pct(candidatevotes or 0, totalvotes or 0),
                "version": parse_int(row.get("version", "")),
                "notes": (row.get("notes", "") or "").strip(),
            }
        )

    if not raw_rows:
        print("No rows matched the requested year range.")
        return 1

    raw_rows.sort(key=lambda r: (int(r["year"]), str(r["state_fips"]), str(r["party_simplified"]), str(r["candidate"])))
    party_rows = aggregate_by_state_party([{
        "year": str(r["year"]),
        "state": str(r["state_name"]).upper(),
        "state_po": str(r["state_abbr"]),
        "state_fips": str(r["state_fips"]),
        "office": str(r["office"]),
        "candidate": str(r["candidate"]),
        "party_detailed": str(r["party_detailed"]),
        "party_simplified": str(r["party_simplified"]),
        "writein": str(r["writein"]),
        "candidatevotes": str(r["candidatevotes"]),
        "totalvotes": str(r["totalvotes"]),
        "version": str(r["version"]) if r["version"] is not None else "",
        "notes": str(r["notes"]),
    } for r in raw_rows])

    raw_path = args.outdir / "presidential_results_raw.csv"
    party_path = args.outdir / "presidential_results_by_party.csv"
    meta_path = args.outdir / "presidential_results_source.json"

    write_csv(raw_path, raw_rows)
    write_csv(party_path, party_rows)

    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "dataset_doi": args.dataset_doi,
                "file_id": args.file_id,
                "source_url": SOURCE_URL_TEMPLATE.format(file_id=args.file_id),
                "downloaded_rows": len(raw_rows),
                "party_rows": len(party_rows),
                "years": years if years is not None else [args.start_year, args.end_year],
            },
            f,
            indent=2,
        )

    print(f"Wrote raw file: {raw_path}")
    print(f"Wrote party-level file: {party_path}")
    print(f"Wrote source metadata: {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
