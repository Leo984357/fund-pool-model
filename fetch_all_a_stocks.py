#!/usr/bin/env python3
"""
全量拉取 A 股日线 (2015-01-01 ~ 2025-12-31)
使用 Tushare Pro HTTP API（直连，绕过有问题的 proxy 连接池）。
支持断点续传。
"""
import os
import sys
import time
import json
import sqlite3
from datetime import datetime

import requests
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db", "ashare_daily.sqlite")
STOCK_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db", "stock_list.csv")
TOKEN = "218920c4902a9cb098fd0a5422510dbabc9b69b73e33032cbd8fe35d"
API_URL = "http://api.waditu.com/dataapi"
START_DATE = "20150101"
END_DATE = "20251231"
SLEEP = 0.35
MAX_RETRIES = 3


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def new_session():
    s = requests.Session()
    s.trust_env = False
    return s


def tushare_api(api_name, **kwargs):
    last_err = None
    for attempt in range(MAX_RETRIES):
        session = new_session()
        try:
            payload = {
                "api_name": api_name,
                "token": TOKEN,
                "params": kwargs,
                "fields": "",
            }
            r = session.post(f"{API_URL}/{api_name}", json=payload, timeout=60)
            result = r.json()
            if result["code"] != 0:
                raise Exception(result["msg"])
            data = result["data"]
            if not data or not data.get("items"):
                return pd.DataFrame()
            return pd.DataFrame(data["items"], columns=data["fields"])
        except Exception as e:
            last_err = e
            wait = min(2 ** attempt * SLEEP, 120)
            if attempt < MAX_RETRIES - 1:
                time.sleep(wait)
        finally:
            session.close()
    raise last_err


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_daily (
            ts_code TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            vol REAL,
            amount REAL,
            pct_chg REAL,
            change REAL,
            PRIMARY KEY (ts_code, date)
        )
    """)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.commit()
    conn.close()
    log(f"DB: {DB_PATH}")


def get_fetched_codes():
    if not os.path.exists(DB_PATH):
        return set()
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql("SELECT DISTINCT ts_code FROM stock_daily", conn)
        conn.close()
        return set(df["ts_code"].tolist())
    except Exception:
        return set()


def get_stock_list():
    if os.path.exists(STOCK_CACHE):
        log("Loading stock list from cache...")
        df = pd.read_csv(STOCK_CACHE)
        log(f"Loaded {len(df)} stocks from cache")
        return df
    log("Fetching stock list from Tushare...")
    df = tushare_api("stock_basic")
    df.to_csv(STOCK_CACHE, index=False)
    log(f"Saved {len(df)} stocks to cache")
    return df


def fetch_one_stock(code):
    try:
        df = tushare_api("daily", ts_code=code, start_date=START_DATE, end_date=END_DATE)
        if df is None or df.empty:
            return None
        df = df.rename(columns={"trade_date": "date"})
        df["ts_code"] = code
        df["date"] = df["date"].astype(str)
        needed = ["ts_code", "date", "open", "high", "low", "close", "vol", "amount", "pct_chg", "change"]
        for c in needed:
            if c not in df.columns:
                df[c] = None
        return df[needed]
    except Exception as e:
        return None


def main():
    init_db()

    stocks = get_stock_list()
    total = len(stocks)
    log(f"Total A-share stocks: {total}")

    fetched = get_fetched_codes()
    if fetched:
        log(f"Already fetched: {len(fetched)} stocks (resuming)")

    conn = sqlite3.connect(DB_PATH)
    total_rows = 0
    skipped = 0
    errors = 0
    t0 = time.time()

    for i, (_, row) in enumerate(stocks.iterrows()):
        code = row["ts_code"]
        name = row.get("name", "")

        if code in fetched:
            skipped += 1
            continue

        df = fetch_one_stock(code)
        if df is not None and not df.empty:
            df.to_sql("stock_daily", conn, if_exists="append", index=False, method="multi", chunksize=500)
            total_rows += len(df)
            conn.commit()
        else:
            errors += 1

        elapsed = time.time() - t0
        done = i + 1
        rate = done / elapsed if elapsed > 0 else 0
        pct = done / total * 100
        eta = (total - done) / rate if rate > 0 else 0
        nrows = len(df) if df is not None else 0
        log(f"[{done}/{total}] {pct:.1f}% {code} {name}: {nrows} rows "
            f"(total={total_rows}, err={errors}, {rate:.1f} stocks/s, eta={eta/60:.1f}min)")

        time.sleep(SLEEP)

    conn.close()
    elapsed = time.time() - t0
    log(f"\nDone! {total_rows} rows from {total - skipped - errors} stocks in {elapsed/60:.1f}min")
    log(f"Skipped: {skipped} already-fetched, Errors: {errors}")


if __name__ == "__main__":
    main()
