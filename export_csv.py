"""
Export every table in oura.db to its own CSV file under csv/.

Usage:
    python export_csv.py
"""

import csv
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "oura.db"
CSV_DIR = Path(__file__).parent / "csv"


def main():
    CSV_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()]

    for table in tables:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        out_path = CSV_DIR / f"{table}.csv"
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if rows:
                writer.writerow(rows[0].keys())
                writer.writerows(rows)
            else:
                cols = [d[1] for d in conn.execute(f"PRAGMA table_info({table})").fetchall()]
                writer.writerow(cols)
        print(f"{table:28s} {len(rows)} rows -> {out_path.name}")

    conn.close()
    print(f"\nSaved {len(tables)} CSV files to {CSV_DIR}")


if __name__ == "__main__":
    main()
