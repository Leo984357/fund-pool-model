from __future__ import annotations
import sqlite3
from pathlib import Path
from contextlib import contextmanager


@contextmanager
def get_connection(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA temp_store=MEMORY;")
    try:
        yield con
    finally:
        con.commit()
        con.close()


def list_tables(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [r[0] for r in cur.fetchall()]


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    cur = conn.execute(f'PRAGMA table_info("{table}")')
    return [r[1] for r in cur.fetchall()]


def ensure_table(conn: sqlite3.Connection, table: str, col_defs: dict[str, str], pk_cols: list[str] = None):
    cols = ', '.join(f'"{k}" {v}' for k, v in col_defs.items())
    if pk_cols:
        pk = ', '.join(f'"{c}"' for c in pk_cols)
        cols += f', PRIMARY KEY ({pk})'
    conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({cols})')
