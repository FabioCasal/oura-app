"""
Saved queries against oura.db. Add your own as new functions and register
them in QUERIES, then run:

    python analysis.py                  # run everything
    python analysis.py sleep_vs_readiness   # run just one
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


def sleep_score_trend():
    return q("SELECT day, score AS sleep_score FROM daily_sleep ORDER BY day")


def sleep_vs_readiness():
    return q("""
        SELECT s.day, s.score AS sleep_score, r.score AS readiness_score
        FROM daily_sleep s JOIN daily_readiness r ON s.day = r.day
        ORDER BY s.day
    """)


def resting_hr_and_hrv_trend():
    return q("""
        SELECT day, lowest_heart_rate, average_hrv
        FROM sleep_periods
        WHERE type = 'long_sleep'
        ORDER BY day
    """)


def steps_vs_sleep_score():
    return q("""
        SELECT a.day, a.steps, s.score AS sleep_score
        FROM daily_activity a JOIN daily_sleep s ON a.day = s.day
        ORDER BY a.day
    """)


def sleep_stage_minutes():
    return q("""
        SELECT day,
               deep_sleep_duration / 60.0 AS deep_min,
               rem_sleep_duration / 60.0 AS rem_min,
               light_sleep_duration / 60.0 AS light_min,
               awake_time / 60.0 AS awake_min
        FROM sleep_periods
        WHERE type = 'long_sleep'
        ORDER BY day
    """)


def workout_impact_on_next_day_readiness():
    return q("""
        SELECT w.day, w.activity, w.intensity, w.calories,
               r.score AS next_day_readiness
        FROM workouts w
        JOIN daily_readiness r ON r.day = date(w.day, '+1 day')
        ORDER BY w.day
    """)


def best_and_worst_sleep_nights():
    best = q("SELECT day, score FROM daily_sleep ORDER BY score DESC LIMIT 3")
    worst = q("SELECT day, score FROM daily_sleep ORDER BY score ASC LIMIT 3")
    best["kind"] = "best"
    worst["kind"] = "worst"
    return pd.concat([best, worst], ignore_index=True)


QUERIES = {
    "sleep_score_trend": sleep_score_trend,
    "sleep_vs_readiness": sleep_vs_readiness,
    "resting_hr_and_hrv_trend": resting_hr_and_hrv_trend,
    "steps_vs_sleep_score": steps_vs_sleep_score,
    "sleep_stage_minutes": sleep_stage_minutes,
    "workout_impact_on_next_day_readiness": workout_impact_on_next_day_readiness,
    "best_and_worst_sleep_nights": best_and_worst_sleep_nights,
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
