import os, sqlite3
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "db", "fund_db.sqlite")

DDL = [
    # 兼容历史（可保留）
    """CREATE TABLE IF NOT EXISTS fund_nav(
           fund_code TEXT, date TEXT, nav REAL, nav_accum REAL, nav_adj REAL,
           PRIMARY KEY (fund_code, date)
       )""",
    """CREATE TABLE IF NOT EXISTS index_nav(
           index_code TEXT, date TEXT, close REAL,
           PRIMARY KEY (index_code, date)
       )""",
    # 新增：股票日线（核心）
    """CREATE TABLE IF NOT EXISTS stock_daily(
           ts_code TEXT, date TEXT, close REAL, pct_chg REAL,
           PRIMARY KEY (ts_code, date)
       )""",
    # 组合输出（字段沿用，code 里放股票 ts_code）
    """CREATE TABLE IF NOT EXISTS portfolio_results(
           date                TEXT,
           fund_code           TEXT,   
           weight_equal        REAL,
           weight_risk_parity  REAL,
           weight_mixed        REAL,
           score               REAL,
           rank                INTEGER,
           PRIMARY KEY (date, fund_code)
       )"""
]

if __name__ == "__main__":
    os.makedirs(os.path.join(BASE_DIR, "db"), exist_ok=True)
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    for sql in DDL: cur.execute(sql)
    conn.commit(); conn.close()
    print(f"✅ DB initialized at {DB_PATH}")
