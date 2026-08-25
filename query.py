"""
Run any SQL query against oura.db and print the results as a table.

Usage:
    python query.py "SELECT day, score FROM daily_sleep ORDER BY day"
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "oura.db"


def main():
    if len(sys.argv) < 2:
        sys.exit('Usage: python query.py "SELECT ..."')
    sql = sys.argv[1]

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql).fetchall()
    conn.close()

    if not rows:
        print("(no rows)")
        return

    cols = rows[0].keys()
    widths = [max(len(c), max((len(str(r[c])) for r in rows), default=0)) for c in cols]

    def fmt_row(values):
        return " | ".join(str(v).ljust(w) for v, w in zip(values, widths))

    print(fmt_row(cols))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(fmt_row([r[c] for c in cols]))
    print(f"\n({len(rows)} rows)")


if __name__ == "__main__":
    main()
