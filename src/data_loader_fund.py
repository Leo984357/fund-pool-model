# -*- coding: utf-8 -*-
from __future__ import annotations
import sqlite3
from typing import List, Optional, Tuple
import pandas as pd

# ======================= 配置 =======================
try:
    from . import config as CFG
    DB_PATH = CFG.DB_PATH
    MIN_HISTORY_DAYS = int(getattr(CFG, "MIN_HISTORY_DAYS", 60))
except Exception:
    DB_PATH, MIN_HISTORY_DAYS = None, 60

# 列名同义词 & 表优先级
FUND_COLS  = ["fund_code", "code", "基金代码", "基金代码(6位)", "证券代码"]
DATE_COLS  = ["date", "trade_date", "pricedate", "净值日期", "交易日期", "日期"]
NAV_COLS   = ["nav", "单位净值", "净值", "nav_unit", "unit_nav", "单位净值(元)", "复权单位净值", "累计净值"]
PREFERRED_TABLES = ["fund_nav_daily", "fund_data_raw", "fund_nav_raw", "fund_nav", "fund_price"]

# ======================= DB 基础 =======================
def _connect() -> sqlite3.Connection:
    if DB_PATH is None:
        raise RuntimeError("config.DB_PATH 未设置")
    return sqlite3.connect(DB_PATH)

def _list_tables(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [r[0] for r in cur.fetchall()]

def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    cur = conn.execute(f'PRAGMA table_info("{table}")')
    return [r[1] for r in cur.fetchall()]

def _pick_first(cols: list[str], cands: list[str]) -> Optional[str]:
    for c in cands:
        if c in cols:
            return c
    return None

def _detect_nav_source(conn: sqlite3.Connection) -> Tuple[str, str, str, str]:
    """自动识别净值表与列：返回 (table, fund_col, date_col, nav_col)"""
    tables = _list_tables(conn)
    order = PREFERRED_TABLES + [t for t in tables if t not in PREFERRED_TABLES]
    for t in order:
        if t not in tables:
            continue
        cols = _table_columns(conn, t)
        f = _pick_first(cols, FUND_COLS)
        d = _pick_first(cols, DATE_COLS)
        n = _pick_first(cols, NAV_COLS)
        if f and d and n:
            print(f"[DB] 选中净值表: {t} (code={f}, date={d}, nav={n})")
            return t, f, d, n
    raise RuntimeError(f"未找到包含净值数据的表；现有表：{tables}")

# ======================= 规范化 =======================
def _norm_code(x) -> str:
    """读取侧的代码规范化：妥善处理 '1.0' → '000001'"""
    s = str(x).strip()
    if s == "":
        return s
    try:
        if s.replace(".", "", 1).isdigit() and s.count(".") <= 1:
            v = int(float(s))
            return str(v).zfill(6)
    except Exception:
        pass
    digits = "".join(ch for ch in s if ch.isdigit())
    if digits:
        v = int(digits)
        return str(v).zfill(6) if v < 10**6 else digits
    return s

# ======================= 对外接口 =======================
def load_nav(codes: List[str], since: str = "2018-01-01") -> pd.DataFrame:
    """
    从 SQLite 读取净值 → DataFrame[fund_code,date,nav]
    三重兜底：IN过滤→按日期全表→起点前移365天；最后按历史天数过滤（空集放宽至1天）
    """
    if not codes:
        return pd.DataFrame(columns=["fund_code", "date", "nav"])

    codes = [str(c).strip() for c in codes]
    valid_codes = {_norm_code(c) for c in codes}
    # 有的库里可能是去零/纯数字，额外准备一种“无前导零”的等价集合
    codes_intlike = {str(int(c)) for c in valid_codes if c.isdigit()}

    with _connect() as conn:
        t, fcol, dcol, ncol = _detect_nav_source(conn)

        # ① IN 查询（考虑规范化/去零两种写法）
        code_bag = list(valid_codes | codes_intlike | set(codes))
        placeholders = ",".join(["?"] * len(code_bag))
        sql1 = (
            f'SELECT "{fcol}" AS fund_code, "{dcol}" AS date, "{ncol}" AS nav '
            f'FROM "{t}" WHERE "{dcol}" >= ? AND "{fcol}" IN ({placeholders})'
        )
        df = pd.read_sql_query(sql1, conn, params=[since] + code_bag)

        # ② 若空：按日期全表，再在 Pandas 中过滤
        if df.empty:
            print("[DB] IN 查询为空，改为按日期全表读取后在 Pandas 过滤…")
            sql2 = (
                f'SELECT "{fcol}" AS fund_code, "{dcol}" AS date, "{ncol}" AS nav '
                f'FROM "{t}" WHERE "{dcol}" >= ?'
            )
            df = pd.read_sql_query(sql2, conn, params=[since])

        # ③ 仍空：起点前移 365 天再读
        if df.empty:
            print("[DB] 仍为空，since 前移 365 天再取…")
            sql3 = (
                f'SELECT "{fcol}" AS fund_code, "{dcol}" AS date, "{ncol}" AS nav '
                f'FROM "{t}" WHERE DATE("{dcol}") >= DATE(?, "-365 day")'
            )
            df = pd.read_sql_query(sql3, conn, params=[since])

    if df.empty:
        print("[DB] 净值读取仍为空：请确认历史净值已入库。")
        return df

    # 规范 + 去重 + 排序
    df["fund_code"] = df["fund_code"].map(_norm_code)
    df["date"] = pd.to_datetime(df["date"])
    df = (
        df[df["fund_code"].isin(valid_codes)]
          .drop_duplicates(subset=["fund_code", "date"])
          .sort_values(["fund_code", "date"])
          .reset_index(drop=True)
    )

    # 历史长度门槛（稳定性）；空集时放宽到 1 天（仅本次）
    lens = df.groupby("fund_code")["date"].nunique()
    keep = lens[lens >= MIN_HISTORY_DAYS].index.tolist()
    if len(keep) == 0:
        print(f"[DB] 注意：历史<{MIN_HISTORY_DAYS} 天导致空集，本次放宽至 1 天。")
        keep = lens[lens >= 1].index.tolist()

    df = df[df["fund_code"].isin(keep)].reset_index(drop=True)
    print(f"[DB] 净值样本：基金数={len(keep)}，记录数={len(df)}（since={since}）")
    return df

def to_returns(df_nav: pd.DataFrame) -> pd.DataFrame:
    """将净值转为日收益：ret_t = nav_t / nav_{t-1} - 1"""
    if df_nav is None or df_nav.empty:
        return pd.DataFrame(columns=["fund_code", "date", "ret"])
    df = df_nav.sort_values(["fund_code", "date"]).copy()
    df["ret"] = df.groupby("fund_code")["nav"].pct_change()
    df = df.dropna(subset=["ret"])
    return df[["fund_code", "date", "ret"]].reset_index(drop=True)

def make_equal_benchmark(df_ret: pd.DataFrame) -> pd.Series:
    """等权基准（同日平均收益）"""
    if df_ret is None or df_ret.empty:
        return pd.Series(dtype=float, name="bench_ret")
    s = df_ret.groupby("date")["ret"].mean().rename("bench_ret")
    s.index = pd.to_datetime(s.index)
    return s
