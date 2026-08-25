"""
Pull raw JSON from every Oura API v2 endpoint and save it under data/, plus
print a summary (date range, record count, fields) for quick inspection.

For actual analysis, use ingest.py instead, which decodes the embedded
high-resolution series (5-min HR/HRV, 30-sec movement/sleep-phase) into a
normalized SQLite database.

Usage:
    python fetch_oura.py [days_back]
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from oura_client import fetch, get_headers

DATA_DIR = Path(__file__).parent / "data"

DAYS_BACK = int(sys.argv[1]) if len(sys.argv) > 1 else 90
START_DATE = date.today() - timedelta(days=DAYS_BACK)
END_DATE = date.today()

# endpoint -> whether it takes start/end date params
ENDPOINTS = {
    "personal_info": False,
    "ring_configuration": False,
    "daily_sleep": True,
    "daily_readiness": True,
    "daily_activity": True,
    "daily_spo2": True,
    "daily_stress": True,
    "daily_resilience": True,
    "daily_cardiovascular_age": True,
    "sleep": True,
    "sleep_time": True,
    "session": True,
    "workout": True,
    "tag": True,
    "enhanced_tag": True,
    "rest_mode_period": True,
    "heartrate": "datetime",
}


def summarize(records):
    if records is None:
        return "FAILED"
    if isinstance(records, dict):
        return f"1 object, fields: {sorted(records.keys())}"
    if not records:
        return "0 records"
    fields = sorted(records[0].keys())
    dates = [r.get("day") or r.get("timestamp") or r.get("bedtime_start") for r in records]
    dates = [d for d in dates if d]
    date_range = f"{min(dates)} -> {max(dates)}" if dates else "n/a"
    return f"{len(records)} records, range {date_range}, fields: {fields}"


def main():
    DATA_DIR.mkdir(exist_ok=True)
    headers = get_headers()
    print(f"Fetching Oura data from {START_DATE} to {END_DATE}\n")
    summary_lines = []

    for endpoint, date_mode in ENDPOINTS.items():
        records = fetch(endpoint, date_mode, START_DATE, END_DATE, headers)
        out_path = DATA_DIR / f"{endpoint}.json"
        with open(out_path, "w") as f:
            json.dump(records, f, indent=2)
        line = f"{endpoint:28s} {summarize(records)}"
        print(line)
        summary_lines.append(line)

    with open(DATA_DIR / "_summary.txt", "w") as f:
        f.write("\n".join(summary_lines))

    print(f"\nSaved raw JSON + summary to {DATA_DIR}")


if __name__ == "__main__":
    main()
