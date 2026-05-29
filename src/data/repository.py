from __future__ import annotations
from pathlib import Path
from typing import Iterable, Sequence
import pandas as pd
import sqlite3

from .._config import Config
from ..common.utils import norm_code, log
from .connection import get_connection, ensure_table, table_columns

CODE_LIKE = {"fund_code", "code"}
FUND_COLS = ["fund_code", "code", "基金代码", "基金代码(6位)", "证券代码"]
DATE_COLS = ["date", "trade_date", "pricedate", "净值日期", "交易日期", "日期"]
NAV_COLS = ["nav", "单位净值", "净值", "unit_nav", "nav_unit", "单位净值(元)", "复权单位净值", "累计净值"]
PREFERRED_TABLES = ["fund_nav_daily", "fund_data_raw", "fund_nav_raw", "fund_nav", "fund_price"]


def _infer_sql_type(colname: str, s: pd.Series) -> str:
    if colname in CODE_LIKE:
        return "TEXT"
    if pd.api.types.is_integer_dtype(s):
        return "INTEGER"
    if pd.api.types.is_float_dtype(s):
        return "REAL"
    if pd.api.types.is_bool_dtype(s):
        return "INTEGER"
    return "TEXT"


def _chunk_iter(it: Iterable, n: int):
    buf = []
    for x in it:
        buf.append(x)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf


def _pick_first(cols: list[str], candidates: list[str]):
    for c in candidates:
        if c in cols:
            return c
    return None


def _detect_nav_source(conn: sqlite3.Connection) -> tuple[str, str, str, str]:
    from .connection import list_tables, table_columns
    tables = list_tables(conn)
    order = PREFERRED_TABLES + [t for t in tables if t not in PREFERRED_TABLES]
    for t in order:
        if t not in tables:
            continue
        cols = table_columns(conn, t)
        f = _pick_first(cols, FUND_COLS)
        d = _pick_first(cols, DATE_COLS)
        n = _pick_first(cols, NAV_COLS)
        if f and d and n:
            return t, f, d, n
    raise RuntimeError(f"No NAV table found; available: {tables}")


class Repository:
    def __init__(self, config: Config):
        self.config = config

    def _connect(self):
        return get_connection(self.config.db_path)

    # -------- upsert --------

    def upsert_df(self, table: str, df: pd.DataFrame, pk_cols: Sequence[str]) -> int:
        if df is None or df.empty:
            return 0
        df = df.copy()
        for c in df.columns:
            if c in CODE_LIKE:
                df[c] = df[c].map(norm_code)

        cols = list(df.columns)
        pk = list(pk_cols)
        non_pk = [c for c in cols if c not in pk]

        with self._connect() as con:
            col_defs = {c: _infer_sql_type(c, df[c]) for c in cols}
            ensure_table(con, table, col_defs, pk)

            col_expr = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join(["?"] * len(cols))
            pk_expr = ", ".join(f'"{c}"' for c in pk)
            update_assign = ", ".join(f'"{c}"=excluded."{c}"' for c in non_pk) if non_pk else ""

            if non_pk:
                sql = f'INSERT INTO "{table}" ({col_expr}) VALUES ({placeholders}) ON CONFLICT({pk_expr}) DO UPDATE SET {update_assign}'
            else:
                sql = f'INSERT OR IGNORE INTO "{table}" ({col_expr}) VALUES ({placeholders})'

            fallback_sql = f'REPLACE INTO "{table}" ({col_expr}) VALUES ({placeholders})'

            def _rows():
                for i in range(len(df)):
                    yield tuple(df.iloc[i][cols].tolist())

            affected = 0
            try:
                before = con.total_changes
                for chunk in _chunk_iter(_rows(), 800):
                    con.executemany(sql, chunk)
                affected = con.total_changes - before
            except sqlite3.OperationalError:
                before = con.total_changes
                for chunk in _chunk_iter(_rows(), 800):
                    con.executemany(fallback_sql, chunk)
                affected = con.total_changes - before
            return int(affected)

    def upsert_nav(self, df_nav: pd.DataFrame) -> int:
        need = {"fund_code", "date", "nav"}
        if not need.issubset(set(df_nav.columns)):
            raise ValueError(f"upsert_nav needs columns {need}, got {set(df_nav.columns)}")
        return self.upsert_df(self.config.nav_table, df_nav[["fund_code", "date", "nav"]], pk_cols=("fund_code", "date"))

    def upsert_portfolio(self, df_port: pd.DataFrame) -> int:
        if "date" not in df_port.columns or "fund_code" not in df_port.columns:
            raise ValueError("upsert_portfolio needs columns ['date','fund_code']")
        return self.upsert_df(self.config.portfolio_table, df_port, pk_cols=("date", "fund_code"))

    # -------- read NAV --------

    def load_nav(self, codes: list[str], since: str = "2018-01-01") -> pd.DataFrame:
        if not codes:
            return pd.DataFrame(columns=["fund_code", "date", "nav"])
        codes = [str(c).strip() for c in codes]
        valid_codes = {norm_code(c) for c in codes}
        codes_intlike = {str(int(c)) for c in valid_codes if c.isdigit()}

        with self._connect() as conn:
            t, fcol, dcol, ncol = _detect_nav_source(conn)

            code_bag = list(valid_codes | codes_intlike | set(codes))
            placeholders = ",".join(["?"] * len(code_bag))
            df = pd.read_sql_query(
                f'SELECT "{fcol}" AS fund_code, "{dcol}" AS date, "{ncol}" AS nav '
                f'FROM "{t}" WHERE "{dcol}" >= ? AND "{fcol}" IN ({placeholders})',
                conn, params=[since] + code_bag,
            )

            if df.empty:
                log("[DB] IN query empty, trying full table scan...")
                df = pd.read_sql_query(
                    f'SELECT "{fcol}" AS fund_code, "{dcol}" AS date, "{ncol}" AS nav '
                    f'FROM "{t}" WHERE "{dcol}" >= ?',
                    conn, params=[since],
                )

            if df.empty:
                log("[DB] Still empty, shifting since back 365 days...")
                df = pd.read_sql_query(
                    f'SELECT "{fcol}" AS fund_code, "{dcol}" AS date, "{ncol}" AS nav '
                    f'FROM "{t}" WHERE DATE("{dcol}") >= DATE(?, "-365 day")',
                    conn, params=[since],
                )

        if df.empty:
            log("[DB] No NAV data found.")
            return df

        df["fund_code"] = df["fund_code"].map(norm_code)
        df["date"] = pd.to_datetime(df["date"])
        df = (
            df[df["fund_code"].isin(valid_codes)]
            .drop_duplicates(subset=["fund_code", "date"])
            .sort_values(["fund_code", "date"])
            .reset_index(drop=True)
        )

        min_days = self.config.min_history_days
        lens = df.groupby("fund_code")["date"].nunique()
        keep = lens[lens >= min_days].index.tolist()
        if not keep:
            log(f"[DB] All funds have <{min_days} days, relaxing to 1 day.")
            keep = lens[lens >= 1].index.tolist()

        df = df[df["fund_code"].isin(keep)].reset_index(drop=True)
        log(f"[DB] NAV: funds={len(keep)}, rows={len(df)} since={since}")
        return df

    @staticmethod
    def to_returns(df_nav: pd.DataFrame) -> pd.DataFrame:
        if df_nav is None or df_nav.empty:
            return pd.DataFrame(columns=["fund_code", "date", "ret"])
        df = df_nav.sort_values(["fund_code", "date"]).copy()
        df["ret"] = df.groupby("fund_code")["nav"].pct_change()
        df = df.dropna(subset=["ret"])
        return df[["fund_code", "date", "ret"]].reset_index(drop=True)

    @staticmethod
    def make_equal_benchmark(df_ret: pd.DataFrame) -> pd.Series:
        if df_ret is None or df_ret.empty:
            return pd.Series(dtype=float, name="bench_ret")
        s = df_ret.groupby("date")["ret"].mean().rename("bench_ret")
        s.index = pd.to_datetime(s.index)
        return s

    def get_latest_nav_date(self) -> str | None:
        dbp = self.config.db_path
        if not dbp.exists():
            return None
        with self._connect() as conn:
            cur = conn.execute(f"SELECT MAX(date) FROM {self.config.nav_table}")
            row = cur.fetchone()
            return str(row[0]) if row and row[0] else None
