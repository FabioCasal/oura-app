"""
Classify a day as high-stress vs. good-recovery by comparing that day's
metrics against your own trailing baseline (not fixed thresholds -- normal
HRV/RHR varies a lot person to person).

Pulls: HRV, resting HR, sleep efficiency (from sleep_periods' long_sleep),
sleep score, readiness score, and stress/recovery time (from daily_stress).
Each is turned into a z-score against your history, oriented so positive =
more strain and negative = more recovery, then combined into one weighted
"Strain/Recovery Index" (SRI):

    HRV            25%   (autonomic marker, weighted highest)
    resting HR     20%   (autonomic marker)
    sleep score     15%
    readiness score 15%
    stress time      15%   (Oura's own stress_high, seconds)
    recovery time    10%   (Oura's own recovery_high, seconds)

Metrics with fewer than MIN_HISTORY days of comparison data are dropped and
the remaining weights are renormalized, so the summary still works early on
before much history has built up.

Usage:
    python daily_summary.py            # yesterday
    python daily_summary.py 2026-08-20 # a specific day (YYYY-MM-DD)
"""

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).parent / "oura.db"
MIN_HISTORY = 5

# (column in the merged frame, weight, sign -- +1 means "higher = more strain")
METRICS = [
    ("hrv", 0.25, -1),
    ("resting_hr", 0.20, +1),
    ("sleep_score", 0.15, -1),
    ("readiness_score", 0.15, -1),
    ("stress_seconds", 0.15, +1),
    ("recovery_seconds", 0.10, -1),
]

BUCKETS = [
    (-999, -1.0, "Excellent Recovery Day"),
    (-1.0, -0.3, "Good Recovery Day"),
    (-0.3, 0.3, "Neutral / Balanced Day"),
    (0.3, 1.0, "Elevated Strain Day"),
    (1.0, 999, "High Stress Day"),
]


def load_all_days() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT
            r.day,
            r.score AS readiness_score,
            r.temperature_deviation,
            s.score AS sleep_score,
            sp.average_hrv AS hrv,
            sp.lowest_heart_rate AS resting_hr,
            sp.efficiency AS sleep_efficiency,
            st.stress_high AS stress_seconds,
            st.recovery_high AS recovery_seconds,
            st.day_summary AS oura_stress_label
        FROM daily_readiness r
        LEFT JOIN daily_sleep s ON s.day = r.day
        LEFT JOIN sleep_periods sp ON sp.day = r.day AND sp.type = 'long_sleep'
        LEFT JOIN daily_stress st ON st.day = r.day
        ORDER BY r.day
    """, conn)
    conn.close()
    return df


def bucket_for(score: float) -> str:
    for lo, hi, label in BUCKETS:
        if lo <= score < hi:
            return label
    return "Neutral / Balanced Day"


def summarize(target_day: str):
    df = load_all_days()
    if target_day not in df["day"].values:
        available = ", ".join(df["day"].tail(5))
        sys.exit(f"No data for {target_day}. Most recent days available: {available}")

    today_row = df[df["day"] == target_day].iloc[0]
    history = df[df["day"] != target_day]

    contributions = []
    used_weight = 0.0
    for col, weight, sign in METRICS:
        hist_vals = history[col].dropna()
        today_val = today_row[col]
        if pd.isna(today_val) or len(hist_vals) < MIN_HISTORY:
            continue
        mean, std = hist_vals.mean(), hist_vals.std()
        if not std or pd.isna(std):
            continue
        z = sign * (today_val - mean) / std
        contributions.append({
            "metric": col, "value": today_val, "baseline_mean": mean,
            "z": z, "weight": weight,
        })
        used_weight += weight

    if not contributions:
        sys.exit(f"Not enough history yet to compare {target_day} against (need {MIN_HISTORY}+ prior days).")

    sri = sum(c["z"] * c["weight"] for c in contributions) / used_weight
    label = bucket_for(sri)

    contributions.sort(key=lambda c: abs(c["z"]), reverse=True)

    LABELS = {
        "hrv": ("HRV", "ms"), "resting_hr": ("resting heart rate", "bpm"),
        "sleep_score": ("sleep score", "pts"), "readiness_score": ("readiness score", "pts"),
        "stress_seconds": ("stress time", "min"), "recovery_seconds": ("recovery time", "min"),
    }

    print(f"\n=== {target_day}: {label} ===")
    print(f"Strain/Recovery Index: {sri:+.2f}  (negative = recovery, positive = strain)\n")

    for c in contributions:
        name, unit = LABELS[c["metric"]]
        val, mean = c["value"], c["baseline_mean"]
        if unit == "min":
            val, mean = val / 60, mean / 60
        direction = "above" if val >= mean else "below"
        pct = abs(val - mean) / mean * 100 if mean else 0
        flag = "  <-- biggest driver" if c is contributions[0] else ""
        print(f"  {name:20s} {val:7.1f} {unit:4s} vs {mean:7.1f} {unit} baseline "
              f"({pct:4.0f}% {direction}, z={c['z']:+.2f}){flag}")

    label_str = today_row["oura_stress_label"]
    if pd.notna(label_str):
        print(f"\nOura's own daily_stress label for this day: {label_str}")
    if pd.notna(today_row["temperature_deviation"]) and abs(today_row["temperature_deviation"]) >= 0.3:
        print(f"Note: body temperature was {today_row['temperature_deviation']:+.2f}°C off baseline "
              f"-- worth a look if you're feeling off (illness, cycle, alcohol, etc. can all cause this).")
    print()


def main():
    if len(sys.argv) > 1:
        target_day = sys.argv[1]
    else:
        target_day = (date.today() - timedelta(days=1)).isoformat()
    summarize(target_day)


if __name__ == "__main__":
    main()
