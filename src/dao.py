# -*- coding: utf-8 -*-
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Iterable, Sequence
import pandas as pd

# ======================= 配置 / 连接 =======================
try:
    from . import config as CFG
    DB_PATH = Path(getattr(CFG, "DB_PATH"))
except Exception:
    DB_PATH = Path(__file__).resolve().parents[1] / "db" / "fund_db.sqlite"

def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    # 基础性能参数（对并发抓取友好）
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA temp_store=MEMORY;")
    return con

# ======================= 工具 =======================
# 判定“像基金代码”的列名集合
CODE_LIKE = {"fund_code", "code", "基金代码", "基金代码(6位)", "证券代码"}

def _norm_code_str(x):
    """
    标准化基金代码为 6 位字符串。
    支持: int, float('1.0'), '000001', 'F000001' 等。
    """
    if x is None:
        return None
    s = str(x).strip()
    if s == "":
        return s
    # 先处理 1.0 / 29.0 这类
    try:
        if s.replace(".", "", 1).isdigit() and s.count(".") <= 1:
            v = int(float(s))
            return str(v).zfill(6)
    except Exception:
        pass
    # 常规：抽取所有数字
    digits = "".join(ch for ch in s if ch.isdigit())
    if digits:
        v = int(digits)
        return str(v).zfill(6) if v < 10**6 else digits
    return s

def _infer_sql_type(colname: str, s: pd.Series) -> str:
    """根据列名/数据类型推断 SQLite 列类型；代码列一律 TEXT。"""
    if colname in CODE_LIKE:
        return "TEXT"
    if pd.api.types.is_integer_dtype(s):
        return "INTEGER"
    if pd.api.types.is_float_dtype(s):
        return "REAL"
    if pd.api.types.is_bool_dtype(s):
        return "INTEGER"
    return "TEXT"

def _ensure_table_and_index(con: sqlite3.Connection, table: str, df: pd.DataFrame, pk_cols: Sequence[str]) -> None:
    """不存在则建表，并为 pk_cols 建唯一索引（供 ON CONFLICT 使用）"""
    cols = list(df.columns)
    col_defs = []
    for c in cols:
        t = _infer_sql_type(c, df[c])
        col_defs.append(f'"{c}" {t}')
    sql_create = f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(col_defs)})'
    con.execute(sql_create)

    if pk_cols:
        idx = f'idx_{table}_' + "_".join(pk_cols)
        cols_expr = ", ".join(f'"{c}"' for c in pk_cols)
        try:
            con.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS "{idx}" ON "{table}" ({cols_expr})')
        except sqlite3.OperationalError as e:
            print(f'[DAO][WARN] 创建唯一索引失败：{e}')

def _chunk_iter(it: Iterable, n: int):
    buf = []
    for x in it:
        buf.append(x)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf

# ======================= 公共 UPSERT =======================
def upsert_df(table: str, df: pd.DataFrame, pk_cols: Sequence[str]) -> int:
    """
    将 df upsert 到 SQLite 的 `table` 中；pk_cols 为唯一键列。
    返回受影响行数（插入+更新）。
    """
    if df is None or df.empty:
        return 0

    df = df.copy()

    # 先把所有“像代码”的列标准化为 6 位字符串（写库永远是 TEXT '000001' 形态）
    for c in df.columns:
        if c in CODE_LIKE:
            df[c] = df[c].map(_norm_code_str)

    cols = list(df.columns)
    pk_cols = list(pk_cols)
    non_pk = [c for c in cols if c not in pk_cols]

    with _connect() as con:
        print(f"[DAO] DB 路径：{DB_PATH.resolve()}")
        _ensure_table_and_index(con, table, df, pk_cols)

        col_expr      = ", ".join(f'"{c}"' for c in cols)
        placeholders  = ", ".join(["?"] * len(cols))
        pk_expr       = ", ".join(f'"{c}"' for c in pk_cols)
        update_assign = ", ".join(f'"{c}"=excluded."{c}"' for c in non_pk) if non_pk else ""

        # ① 首选：ON CONFLICT DO UPDATE（需要唯一索引）
        if non_pk:
            on_conflict_sql = (
                f'INSERT INTO "{table}" ({col_expr}) VALUES ({placeholders}) '
                f'ON CONFLICT({pk_expr}) DO UPDATE SET {update_assign}'
            )
        else:
            on_conflict_sql = f'INSERT OR IGNORE INTO "{table}" ({col_expr}) VALUES ({placeholders})'

        # ② 兜底：REPLACE INTO（极端情况下）
        replace_sql = f'REPLACE INTO "{table}" ({col_expr}) VALUES ({placeholders})'

        def _iter_rows():
            for i in range(len(df)):
                yield tuple(df.iloc[i][cols].tolist())

        affected = 0
        try:
            before = con.total_changes
            for chunk in _chunk_iter(_iter_rows(), 800):
                con.executemany(on_conflict_sql, chunk)
            affected = con.total_changes - before
        except sqlite3.OperationalError as e:
            print(f"[DAO][WARN] ON CONFLICT 失败，使用 REPLACE INTO 兜底：{e}")
            before = con.total_changes
            for chunk in _chunk_iter(_iter_rows(), 800):
                con.executemany(replace_sql, chunk)
            affected = con.total_changes - before

        return int(affected)

# ======================= 便捷封装 =======================
def upsert_nav(df_nav: pd.DataFrame, table: str = "fund_nav_daily") -> int:
    """期望列：fund_code, date, nav；唯一键：(fund_code, date)"""
    need = {"fund_code", "date", "nav"}
    if not need.issubset(set(df_nav.columns)):
        raise ValueError(f"[DAO] upsert_nav 需要列 {need}，收到 {set(df_nav.columns)}")
    return upsert_df(table, df_nav[["fund_code", "date", "nav"]], pk_cols=("fund_code", "date"))

def upsert_portfolio(df_port: pd.DataFrame, table: str = "portfolio_results") -> int:
    """唯一键：(date, fund_code)"""
    if "date" not in df_port.columns or "fund_code" not in df_port.columns:
        raise ValueError("[DAO] upsert_portfolio 需要列 ['date','fund_code']")
    return upsert_df(table, df_port, pk_cols=("date", "fund_code"))
