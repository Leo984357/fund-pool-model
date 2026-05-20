# -*- coding: utf-8 -*-
"""
reset_db.py
用途：重置 Fund_pool_model 项目的 SQLite 数据库。
- 支持两种模式：
  1) 硬重置（hard）：备份旧库 -> 删除库文件 -> 重建空库与表结构
  2) 软清空（soft）：保留库文件与表结构，只清空业务表数据
- 设计目标：在 IDE 内直接运行，无需 shell；不依赖外网。

使用方式：
1. 将本文件放到项目根目录（与 run_daily_fund.py 同级）
2. 在 IDE 里运行此脚本（建议先看下方参数配置）

运行后：
- 硬重置会重新创建空表（含 WAL / busy_timeout 等 PRAGMA）
- 软清空仅删除数据，不改表定义
"""

import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

# ======================= 可配置参数 =======================
# 模式："hard" 或 "soft"
MODE = os.getenv("RESET_MODE", "hard").lower()  # 可在 IDE 环境变量里设 RESET_MODE=soft

# 数据库路径（相对项目根目录）
DB_PATH = Path("db") / "fund_db.sqlite"

# 需要清空/重建的业务表（按你的项目惯例）
TABLES = [
    "fund_nav_daily",
    "fund_nav_latest",
    "fund_info",
    "fund_holdings",
    "fund_allocation",
    "portfolio_results",
]

# =======================================================

SCHEMA_SQL = [
    # PRAGMA 建议在连接后设置，这里仅备份展示
]

CREATE_TABLES_SQL = [
    # 基金日净值（主键：fund_code+date）
    """
    CREATE TABLE IF NOT EXISTS fund_nav_daily (
        fund_code   TEXT NOT NULL,
        date        TEXT NOT NULL,
        nav         REAL,
        acc_nav     REAL,
        PRIMARY KEY (fund_code, date)
    );
    """,
    # 最近净值快照（每只基金一行）
    """
    CREATE TABLE IF NOT EXISTS fund_nav_latest (
        fund_code   TEXT PRIMARY KEY,
        date        TEXT,
        nav         REAL,
        acc_nav     REAL
    );
    """,
    # 基金基本信息
    """
    CREATE TABLE IF NOT EXISTS fund_info (
        fund_code       TEXT PRIMARY KEY,
        name            TEXT,
        type            TEXT,
        manager         TEXT,
        custodian       TEXT,
        inception_date  TEXT
    );
    """,
    # 基金持仓（季报/年报）
    """
    CREATE TABLE IF NOT EXISTS fund_holdings (
        fund_code   TEXT NOT NULL,
        report_date TEXT NOT NULL,
        stock_code  TEXT NOT NULL,
        weight      REAL,
        shares      REAL,
        market_value REAL,
        PRIMARY KEY (fund_code, report_date, stock_code)
    );
    """,
    # 资产配置
    """
    CREATE TABLE IF NOT EXISTS fund_allocation (
        fund_code   TEXT NOT NULL,
        report_date TEXT NOT NULL,
        equity      REAL,
        bond        REAL,
        cash        REAL,
        other       REAL,
        PRIMARY KEY (fund_code, report_date)
    );
    """,
    # 分红/拆分
    """
    CREATE TABLE IF NOT EXISTS fund_dividend (
        fund_code   TEXT NOT NULL,
        ex_date     TEXT NOT NULL,
        dividend    REAL,
        split_ratio REAL,
        PRIMARY KEY (fund_code, ex_date)
    );
    """,
    # 股票日线（若后续扩展用得到）
    """
    CREATE TABLE IF NOT EXISTS stock_daily (
        ts_code     TEXT NOT NULL,
        date        TEXT NOT NULL,
        close       REAL,
        pct_chg     REAL,
        PRIMARY KEY (ts_code, date)
    );
    """,
    # 组合结果（优化输出）
    """
    CREATE TABLE IF NOT EXISTS portfolio_results (
        date                TEXT NOT NULL,
        fund_code           TEXT NOT NULL,
        weight_equal        REAL,
        weight_risk_parity  REAL,
        weight_mixed        REAL,
        score               REAL,
        rank                INTEGER,
        PRIMARY KEY (date, fund_code)
    );
    """,
]

def ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)

def connect_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)  # autocommit
    cur = conn.cursor()
    # 基础 PRAGMA：提升并发与稳定性
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA synchronous=NORMAL;")
    cur.execute("PRAGMA busy_timeout=8000;")  # 8s
    cur.execute("PRAGMA temp_store=MEMORY;")
    cur.close()
    return conn

def create_schema(conn: sqlite3.Connection):
    cur = conn.cursor()
    for sql in CREATE_TABLES_SQL:
        cur.execute(sql)
    cur.close()

def backup_db(path: Path) -> Path:
    if not path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path.with_name(path.stem + f".bak_{ts}" + path.suffix)
    shutil.copy2(path, bak)
    return bak

def hard_reset(db_path: Path):
    print(f"[Reset] 硬重置：{db_path}")
    ensure_parent(db_path)
    bak = backup_db(db_path)
    if bak:
        print(f"[Reset] 备份已创建：{bak}")
    if db_path.exists():
        db_path.unlink()  # 删除库文件
        print(f"[Reset] 旧库已删除")
    # 重建空库与表
    conn = connect_db(db_path)
    try:
        create_schema(conn)
        print("[Reset] 表结构已创建完毕")
    finally:
        conn.close()

def soft_clear(db_path: Path):
    print(f"[Reset] 软清空：{db_path}")
    ensure_parent(db_path)
    conn = connect_db(db_path)
    try:
        cur = conn.cursor()
        for t in TABLES:
            try:
                cur.execute(f"DELETE FROM {t};")
                print(f"[Reset] 清空表：{t}")
            except Exception as e:
                print(f"[Warn] 清空 {t} 失败：{e}")
        cur.execute("VACUUM;")
        cur.close()
        print("[Reset] VACUUM 完成")
    finally:
        conn.close()

def post_check(db_path: Path):
    conn = connect_db(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
        tables = [r[0] for r in cur.fetchall()]
        print("[Check] 当前表：", tables)
        for t in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {t};")
                n = cur.fetchone()[0]
                print(f"[Check] {t}: {n} 行")
            except Exception as e:
                print(f"[Check] {t}: 计数失败 {e}")
        cur.close()
    finally:
        conn.close()

def main():
    root = Path(__file__).resolve().parent
    db_path = (root / DB_PATH).resolve()
    print(f"[Reset] 项目根：{root}")
    print(f"[Reset] 数据库：{db_path}")
    if MODE == "hard":
        hard_reset(db_path)
    elif MODE == "soft":
        soft_clear(db_path)
    else:
        raise SystemExit(f"未知模式：{MODE}，可选 hard/soft")

    print("[Reset] 完成，开始核查...")
    post_check(db_path)
    print("[Reset] 结束。下一步可运行 run_daily_fund.py 重建数据。")

if __name__ == "__main__":
    main()
