#!/usr/bin/env python3
"""
DB initialization and reset.
"""
from pathlib import Path
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "db" / "fund_db.sqlite"

DDL = [
    """CREATE TABLE IF NOT EXISTS fund_nav_daily(
        fund_code TEXT, date TEXT, nav REAL,
        PRIMARY KEY (fund_code, date)
    )""",
    """CREATE TABLE IF NOT EXISTS portfolio_results(
        date TEXT, fund_code TEXT,
        weight_equal REAL, weight_risk_parity REAL, weight_mixed REAL,
        score REAL, rank INTEGER,
        PRIMARY KEY (date, fund_code)
    )""",
]


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    for sql in DDL:
        conn.execute(sql)
    conn.commit()
    conn.close()
    print(f"DB initialized: {DB_PATH}")


def reset_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"DB removed: {DB_PATH}")
    init_db()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        reset_db()
    else:
        init_db()
