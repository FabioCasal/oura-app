"""
Shared low-level Oura API v2 client: auth headers + paginated/chunked fetch.
Used by both fetch_oura.py (raw dump for inspection) and ingest.py
(normalized SQLite load).
"""

from datetime import date, timedelta

import requests

from oura_auth import get_access_token

BASE_URL = "https://api.ouraring.com/v2/usercollection"

# some endpoints reject ranges beyond N days and must be chunked
MAX_DAYS_PER_REQUEST = {"heartrate": 30}


def get_headers():
    return {"Authorization": f"Bearer {get_access_token()}"}


def fetch_range(endpoint: str, date_mode, start: date, end: date, headers: dict):
    params = {}
    if date_mode == "datetime":
        params = {
            "start_datetime": f"{start.isoformat()}T00:00:00-00:00",
            "end_datetime": f"{end.isoformat()}T23:59:59-00:00",
        }
    elif date_mode:
        params = {"start_date": start.isoformat(), "end_date": end.isoformat()}

    records = []
    next_token = None
    while True:
        if next_token:
            params["next_token"] = next_token
        resp = requests.get(f"{BASE_URL}/{endpoint}", headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"  [{endpoint}] HTTP {resp.status_code}: {resp.text[:200]}")
            return None
        payload = resp.json()
        if "data" in payload:
            records.extend(payload["data"])
            next_token = payload.get("next_token")
            if not next_token:
                break
        else:
            records = payload  # single-object endpoints like personal_info
            break
    return records


def fetch(endpoint: str, date_mode, start_date: date, end_date: date, headers: dict):
    max_chunk = MAX_DAYS_PER_REQUEST.get(endpoint)
    if not date_mode or not max_chunk:
        return fetch_range(endpoint, date_mode, start_date, end_date, headers)

    all_records = []
    chunk_start = start_date
    while chunk_start <= end_date:
        chunk_end = min(chunk_start + timedelta(days=max_chunk - 1), end_date)
        chunk = fetch_range(endpoint, date_mode, chunk_start, chunk_end, headers)
        if chunk is None:
            return None
        all_records.extend(chunk)
        chunk_start = chunk_end + timedelta(days=1)
    return all_records
