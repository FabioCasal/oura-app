"""
Ingest Oura data at the highest granularity the API exposes, normalized into
a SQLite database (oura.db) instead of raw JSON blobs.

Granularity by source:
  - heartrate_raw:        one row per raw HR reading (~every few min, denser
                           during workouts) from the /heartrate endpoint,
                           across the whole day, not just sleep.
  - sleep_hr_series /
    sleep_hrv_series:     one row per 5-minute HR/HRV sample, decoded from
                           the embedded time-series objects on each sleep
                           period.
  - sleep_phase_series:   one row per 30-second sleep-stage sample, decoded
                           from `sleep_phase_30_sec` (finer than the 5-min
                           summary string). Codes: 1=deep 2=light 3=rem
                           4=awake (per Oura's sleep model; verify against
                           https://cloud.ouraring.com/v2/docs if precision
                           matters).
  - sleep_movement_series: one row per 30-second movement sample, decoded
                           from `movement_30_sec`. Codes: 1=no motion
                           2=restless 3=tossing and turning 4=active
                           (same caveat as above).
  - daily_* tables:       one row per day, as the API returns (this is the
                           API's native resolution for these metrics).
  - sleep_periods:        one row per sleep period (naps count separately
                           from the main sleep period).
  - workouts:              one row per logged workout.

Re-running is idempotent: rows are upserted by their natural key, and each
period's exploded series is fully replaced on re-ingest.

Usage:
    python ingest.py [days_back]
"""

import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from oura_client import fetch, get_headers

DB_PATH = Path(__file__).parent / "oura.db"

DAYS_BACK = int(sys.argv[1]) if len(sys.argv) > 1 else 90
START_DATE = date.today() - timedelta(days=DAYS_BACK)
END_DATE = date.today()

SCHEMA = """
CREATE TABLE IF NOT EXISTS personal_info (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    age INTEGER, biological_sex TEXT, email TEXT, height REAL, weight REAL
);

CREATE TABLE IF NOT EXISTS ring_configuration (
    id TEXT PRIMARY KEY, color TEXT, design TEXT, firmware_version TEXT,
    hardware_type TEXT, set_up_at TEXT, size INTEGER
);

CREATE TABLE IF NOT EXISTS daily_sleep (
    id TEXT PRIMARY KEY, day TEXT, score INTEGER, timestamp TEXT, contributors_json TEXT
);
CREATE TABLE IF NOT EXISTS daily_readiness (
    id TEXT PRIMARY KEY, day TEXT, score INTEGER, timestamp TEXT,
    temperature_deviation REAL, temperature_trend_deviation REAL, contributors_json TEXT
);
CREATE TABLE IF NOT EXISTS daily_activity (
    id TEXT PRIMARY KEY, day TEXT, score INTEGER, timestamp TEXT, steps INTEGER,
    active_calories INTEGER, total_calories INTEGER, target_calories INTEGER,
    equivalent_walking_distance INTEGER, high_activity_time INTEGER,
    medium_activity_time INTEGER, low_activity_time INTEGER, sedentary_time INTEGER,
    resting_time INTEGER, non_wear_time INTEGER, inactivity_alerts INTEGER,
    meters_to_target INTEGER, target_meters INTEGER, average_met_minutes REAL,
    raw_json TEXT
);
CREATE TABLE IF NOT EXISTS daily_spo2 (
    id TEXT PRIMARY KEY, day TEXT, spo2_percentage_avg REAL, breathing_disturbance_index REAL
);
CREATE TABLE IF NOT EXISTS daily_stress (
    id TEXT PRIMARY KEY, day TEXT, stress_high INTEGER, recovery_high INTEGER, day_summary TEXT
);
CREATE TABLE IF NOT EXISTS daily_resilience (
    id TEXT PRIMARY KEY, day TEXT, level TEXT, contributors_json TEXT
);
CREATE TABLE IF NOT EXISTS daily_cardiovascular_age (
    id TEXT PRIMARY KEY, day TEXT, vascular_age INTEGER, pulse_wave_velocity REAL
);
CREATE TABLE IF NOT EXISTS sleep_time (
    id TEXT PRIMARY KEY, day TEXT, status TEXT, optimal_bedtime_json TEXT, recommendation TEXT
);

CREATE TABLE IF NOT EXISTS sleep_periods (
    id TEXT PRIMARY KEY, day TEXT, period INTEGER, type TEXT,
    bedtime_start TEXT, bedtime_end TEXT, timezone_offset TEXT,
    total_sleep_duration INTEGER, time_in_bed INTEGER, awake_time INTEGER,
    deep_sleep_duration INTEGER, light_sleep_duration INTEGER, rem_sleep_duration INTEGER,
    latency INTEGER, efficiency INTEGER, restless_periods INTEGER,
    average_breath REAL, average_heart_rate REAL, average_hrv REAL, lowest_heart_rate INTEGER,
    sleep_score_delta INTEGER, readiness_score_delta INTEGER,
    sleep_algorithm_version TEXT, sleep_analysis_reason TEXT,
    low_battery_alert INTEGER, ring_id TEXT
);

CREATE TABLE IF NOT EXISTS sleep_hr_series (
    period_id TEXT, seq INTEGER, timestamp TEXT, bpm REAL,
    PRIMARY KEY (period_id, seq)
);
CREATE TABLE IF NOT EXISTS sleep_hrv_series (
    period_id TEXT, seq INTEGER, timestamp TEXT, hrv_ms REAL,
    PRIMARY KEY (period_id, seq)
);
CREATE TABLE IF NOT EXISTS sleep_phase_series (
    period_id TEXT, seq INTEGER, timestamp TEXT, phase_code INTEGER, phase_label TEXT,
    PRIMARY KEY (period_id, seq)
);
CREATE TABLE IF NOT EXISTS sleep_movement_series (
    period_id TEXT, seq INTEGER, timestamp TEXT, movement_code INTEGER, movement_label TEXT,
    PRIMARY KEY (period_id, seq)
);

CREATE TABLE IF NOT EXISTS workouts (
    id TEXT PRIMARY KEY, day TEXT, activity TEXT, calories REAL, distance REAL,
    intensity TEXT, label TEXT, source TEXT, start_datetime TEXT, end_datetime TEXT
);

CREATE TABLE IF NOT EXISTS heartrate_raw (
    timestamp TEXT, bpm REAL, source TEXT,
    PRIMARY KEY (timestamp, source)
);

CREATE INDEX IF NOT EXISTS idx_hr_series_ts ON sleep_hr_series(timestamp);
CREATE INDEX IF NOT EXISTS idx_hrv_series_ts ON sleep_hrv_series(timestamp);
CREATE INDEX IF NOT EXISTS idx_phase_series_ts ON sleep_phase_series(timestamp);
CREATE INDEX IF NOT EXISTS idx_movement_series_ts ON sleep_movement_series(timestamp);
CREATE INDEX IF NOT EXISTS idx_heartrate_raw_ts ON heartrate_raw(timestamp);
"""

PHASE_LABELS = {1: "deep", 2: "light", 3: "rem", 4: "awake"}
MOVEMENT_LABELS = {1: "no_motion", 2: "restless", 3: "tossing_and_turning", 4: "active"}


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def add_seconds(dt: datetime, seconds: float) -> str:
    return (dt + timedelta(seconds=seconds)).isoformat()


def upsert(conn, table: str, row: dict):
    cols = list(row.keys())
    placeholders = ", ".join("?" for _ in cols)
    col_list = ", ".join(cols)
    sql = f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})"
    conn.execute(sql, [row[c] for c in cols])


def ingest_daily_generic(conn, table: str, records, field_map: dict, extra_json_field=None):
    """field_map: destination_col -> source_key (or None to use same name)."""
    if not records:
        return 0
    n = 0
    for r in records:
        row = {}
        for dest, src in field_map.items():
            val = r.get(src if src else dest)
            row[dest] = val
        if extra_json_field:
            row[extra_json_field] = json.dumps(r.get(extra_json_field.replace("_json", "")))
        upsert(conn, table, row)
        n += 1
    return n


def ingest_sleep(conn, records):
    if not records:
        return 0, 0, 0, 0, 0
    n_periods = n_hr = n_hrv = n_phase = n_move = 0
    for r in records:
        period_id = r["id"]
        bedtime_start = parse_dt(r["bedtime_start"])

        upsert(conn, "sleep_periods", {
            "id": period_id, "day": r.get("day"), "period": r.get("period"), "type": r.get("type"),
            "bedtime_start": r.get("bedtime_start"), "bedtime_end": r.get("bedtime_end"),
            "timezone_offset": r["bedtime_start"][-6:] if r.get("bedtime_start") else None,
            "total_sleep_duration": r.get("total_sleep_duration"), "time_in_bed": r.get("time_in_bed"),
            "awake_time": r.get("awake_time"), "deep_sleep_duration": r.get("deep_sleep_duration"),
            "light_sleep_duration": r.get("light_sleep_duration"), "rem_sleep_duration": r.get("rem_sleep_duration"),
            "latency": r.get("latency"), "efficiency": r.get("efficiency"),
            "restless_periods": r.get("restless_periods"), "average_breath": r.get("average_breath"),
            "average_heart_rate": r.get("average_heart_rate"), "average_hrv": r.get("average_hrv"),
            "lowest_heart_rate": r.get("lowest_heart_rate"), "sleep_score_delta": r.get("sleep_score_delta"),
            "readiness_score_delta": r.get("readiness_score_delta"),
            "sleep_algorithm_version": r.get("sleep_algorithm_version"),
            "sleep_analysis_reason": r.get("sleep_analysis_reason"),
            "low_battery_alert": int(bool(r.get("low_battery_alert"))), "ring_id": r.get("ring_id"),
        })
        n_periods += 1

        conn.execute("DELETE FROM sleep_hr_series WHERE period_id = ?", (period_id,))
        conn.execute("DELETE FROM sleep_hrv_series WHERE period_id = ?", (period_id,))
        conn.execute("DELETE FROM sleep_phase_series WHERE period_id = ?", (period_id,))
        conn.execute("DELETE FROM sleep_movement_series WHERE period_id = ?", (period_id,))

        hr = r.get("heart_rate") or {}
        base = parse_dt(hr["timestamp"]) if hr.get("timestamp") else bedtime_start
        interval = hr.get("interval") or 300.0
        for i, bpm in enumerate(hr.get("items") or []):
            if bpm is None:
                continue
            upsert(conn, "sleep_hr_series", {
                "period_id": period_id, "seq": i, "timestamp": add_seconds(base, i * interval), "bpm": bpm,
            })
            n_hr += 1

        hrv = r.get("hrv") or {}
        base = parse_dt(hrv["timestamp"]) if hrv.get("timestamp") else bedtime_start
        interval = hrv.get("interval") or 300.0
        for i, val in enumerate(hrv.get("items") or []):
            if val is None:
                continue
            upsert(conn, "sleep_hrv_series", {
                "period_id": period_id, "seq": i, "timestamp": add_seconds(base, i * interval), "hrv_ms": val,
            })
            n_hrv += 1

        phase_str = r.get("sleep_phase_30_sec") or ""
        for i, ch in enumerate(phase_str):
            code = int(ch)
            upsert(conn, "sleep_phase_series", {
                "period_id": period_id, "seq": i, "timestamp": add_seconds(bedtime_start, i * 30),
                "phase_code": code, "phase_label": PHASE_LABELS.get(code, "unknown"),
            })
            n_phase += 1

        move_str = r.get("movement_30_sec") or ""
        for i, ch in enumerate(move_str):
            code = int(ch)
            upsert(conn, "sleep_movement_series", {
                "period_id": period_id, "seq": i, "timestamp": add_seconds(bedtime_start, i * 30),
                "movement_code": code, "movement_label": MOVEMENT_LABELS.get(code, "unknown"),
            })
            n_move += 1

    return n_periods, n_hr, n_hrv, n_phase, n_move


def ingest_heartrate_raw(conn, records):
    if not records:
        return 0
    for r in records:
        upsert(conn, "heartrate_raw", {
            "timestamp": r.get("timestamp"), "bpm": r.get("bpm"), "source": r.get("source"),
        })
    return len(records)


def ingest_workouts(conn, records):
    if not records:
        return 0
    for r in records:
        upsert(conn, "workouts", {
            "id": r["id"], "day": r.get("day"), "activity": r.get("activity"),
            "calories": r.get("calories"), "distance": r.get("distance"), "intensity": r.get("intensity"),
            "label": r.get("label"), "source": r.get("source"),
            "start_datetime": r.get("start_datetime"), "end_datetime": r.get("end_datetime"),
        })
    return len(records)


def main():
    headers = get_headers()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    print(f"Ingesting Oura data from {START_DATE} to {END_DATE} into {DB_PATH}\n")

    def f(endpoint, date_mode):
        return fetch(endpoint, date_mode, START_DATE, END_DATE, headers)

    info = f("personal_info", False)
    if isinstance(info, dict):
        upsert(conn, "personal_info", {"id": 1, **{k: info.get(k) for k in ["age", "biological_sex", "email", "height", "weight"]}})
        print("personal_info            1 record")

    ring = f("ring_configuration", False)
    if ring:
        for r in ring:
            upsert(conn, "ring_configuration", {k: r.get(k) for k in ["id", "color", "design", "firmware_version", "hardware_type", "set_up_at", "size"]})
        print(f"ring_configuration       {len(ring)} record(s)")

    n = ingest_daily_generic(conn, "daily_sleep", f("daily_sleep", True),
        {"id": "id", "day": "day", "score": "score", "timestamp": "timestamp"}, "contributors_json")
    print(f"daily_sleep              {n} records")

    n = ingest_daily_generic(conn, "daily_readiness", f("daily_readiness", True),
        {"id": "id", "day": "day", "score": "score", "timestamp": "timestamp",
         "temperature_deviation": "temperature_deviation", "temperature_trend_deviation": "temperature_trend_deviation"},
        "contributors_json")
    print(f"daily_readiness          {n} records")

    activity_records = f("daily_activity", True)
    if activity_records:
        for r in activity_records:
            row = {k: r.get(k) for k in [
                "id", "day", "score", "timestamp", "steps", "active_calories", "total_calories",
                "target_calories", "equivalent_walking_distance", "high_activity_time",
                "medium_activity_time", "low_activity_time", "sedentary_time", "resting_time",
                "non_wear_time", "inactivity_alerts", "meters_to_target", "target_meters", "average_met_minutes",
            ]}
            row["raw_json"] = json.dumps(r)
            upsert(conn, "daily_activity", row)
    print(f"daily_activity           {len(activity_records or [])} records")

    spo2_records = f("daily_spo2", True)
    if spo2_records:
        for r in spo2_records:
            upsert(conn, "daily_spo2", {
                "id": r["id"], "day": r.get("day"),
                "spo2_percentage_avg": (r.get("spo2_percentage") or {}).get("average"),
                "breathing_disturbance_index": r.get("breathing_disturbance_index"),
            })
    print(f"daily_spo2               {len(spo2_records or [])} records")

    n = ingest_daily_generic(conn, "daily_stress", f("daily_stress", True),
        {"id": "id", "day": "day", "stress_high": "stress_high", "recovery_high": "recovery_high", "day_summary": "day_summary"})
    print(f"daily_stress             {n} records")

    n = ingest_daily_generic(conn, "daily_resilience", f("daily_resilience", True),
        {"id": "id", "day": "day", "level": "level"}, "contributors_json")
    print(f"daily_resilience         {n} records")

    n = ingest_daily_generic(conn, "daily_cardiovascular_age", f("daily_cardiovascular_age", True),
        {"id": "id", "day": "day", "vascular_age": "vascular_age", "pulse_wave_velocity": "pulse_wave_velocity"})
    print(f"daily_cardiovascular_age {n} records")

    sleep_time_records = f("sleep_time", True)
    if sleep_time_records:
        for r in sleep_time_records:
            upsert(conn, "sleep_time", {
                "id": r["id"], "day": r.get("day"), "status": r.get("status"),
                "optimal_bedtime_json": json.dumps(r.get("optimal_bedtime")), "recommendation": r.get("recommendation"),
            })
    print(f"sleep_time               {len(sleep_time_records or [])} records")

    n_periods, n_hr, n_hrv, n_phase, n_move = ingest_sleep(conn, f("sleep", True))
    print(f"sleep_periods            {n_periods} periods")
    print(f"  sleep_hr_series          {n_hr} samples (5-min resolution)")
    print(f"  sleep_hrv_series         {n_hrv} samples (5-min resolution)")
    print(f"  sleep_phase_series       {n_phase} samples (30-sec resolution)")
    print(f"  sleep_movement_series    {n_move} samples (30-sec resolution)")

    n = ingest_workouts(conn, f("workout", True))
    print(f"workouts                 {n} records")

    n = ingest_heartrate_raw(conn, f("heartrate", "datetime"))
    print(f"heartrate_raw            {n} readings")

    conn.commit()
    conn.close()
    print(f"\nDone. Database at {DB_PATH}")


if __name__ == "__main__":
    main()
