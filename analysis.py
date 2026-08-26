"""
Saved queries against oura.db. Add your own as new functions and register
them in QUERIES, then run:

    python analysis.py                  # run everything
    python analysis.py bedtimes         # run just one
    python analysis.py daily_sleep daily_readiness   # or a few
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).parent / "oura.db"


def q(sql: str) -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(sql, conn)
    conn.close()
    return df


# --- one query per table: every column, so you can see the full shape of
# the data available (skips the raw JSON blob columns and the huge
# per-sample series tables, which are better explored with query.py) ---

def personal_info():
    return q("SELECT * FROM personal_info")


def ring_configuration():
    return q("SELECT * FROM ring_configuration")


def daily_sleep():
    return q("SELECT id, day, score, timestamp, contributors_json FROM daily_sleep ORDER BY day")


def daily_readiness():
    return q("""
        SELECT id, day, score, timestamp, temperature_deviation,
               temperature_trend_deviation, contributors_json
        FROM daily_readiness ORDER BY day
    """)


def daily_activity():
    return q("""
        SELECT id, day, score, timestamp, steps, active_calories, total_calories,
               target_calories, equivalent_walking_distance, high_activity_time,
               medium_activity_time, low_activity_time, sedentary_time, resting_time,
               non_wear_time, inactivity_alerts, meters_to_target, target_meters,
               average_met_minutes
        FROM daily_activity ORDER BY day
    """)


def daily_spo2():
    return q("SELECT id, day, spo2_percentage_avg, breathing_disturbance_index FROM daily_spo2 ORDER BY day")


def daily_stress():
    return q("SELECT id, day, stress_high, recovery_high, day_summary FROM daily_stress ORDER BY day")


def daily_resilience():
    return q("SELECT id, day, level, contributors_json FROM daily_resilience ORDER BY day")


def daily_cardiovascular_age():
    return q("SELECT id, day, vascular_age, pulse_wave_velocity FROM daily_cardiovascular_age ORDER BY day")


def sleep_time():
    return q("SELECT id, day, status, optimal_bedtime_json, recommendation FROM sleep_time ORDER BY day")


def sleep_periods():
    return q("""
        SELECT id, day, period, type, bedtime_start, bedtime_end, timezone_offset,
               total_sleep_duration, time_in_bed, awake_time, deep_sleep_duration,
               light_sleep_duration, rem_sleep_duration, latency, efficiency,
               restless_periods, average_breath, average_heart_rate, average_hrv,
               lowest_heart_rate, sleep_score_delta, readiness_score_delta,
               sleep_algorithm_version, sleep_analysis_reason, low_battery_alert, ring_id
        FROM sleep_periods ORDER BY day, period
    """)


def workouts():
    return q("""
        SELECT id, day, activity, calories, distance, intensity, label, source,
               start_datetime, end_datetime
        FROM workouts ORDER BY day
    """)


# --- the one you asked for: what time you actually went to sleep each night ---

def bedtimes():
    """Bedtime/wake time for each night's main sleep (excludes naps)."""
    return q("""
        SELECT day,
               substr(bedtime_start, 12, 8) AS bedtime,
               substr(bedtime_end, 12, 8) AS wake_time,
               ROUND(total_sleep_duration / 3600.0, 2) AS hours_slept,
               ROUND(latency / 60.0, 1) AS minutes_to_fall_asleep
        FROM sleep_periods
        WHERE type = 'long_sleep'
        ORDER BY day
    """)


QUERIES = {
    "personal_info": personal_info,
    "ring_configuration": ring_configuration,
    "daily_sleep": daily_sleep,
    "daily_readiness": daily_readiness,
    "daily_activity": daily_activity,
    "daily_spo2": daily_spo2,
    "daily_stress": daily_stress,
    "daily_resilience": daily_resilience,
    "daily_cardiovascular_age": daily_cardiovascular_age,
    "sleep_time": sleep_time,
    "sleep_periods": sleep_periods,
    "workouts": workouts,
    "bedtimes": bedtimes,
}


def main():
    names = sys.argv[1:] or list(QUERIES.keys())
    for name in names:
        if name not in QUERIES:
            print(f"Unknown query: {name}. Available: {list(QUERIES.keys())}")
            continue
        print(f"\n=== {name} ===")
        print(QUERIES[name]().to_string(index=False))


if __name__ == "__main__":
    main()
