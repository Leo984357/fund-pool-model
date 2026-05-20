# -*- coding: utf-8 -*-
"""
run_daily_fund.py
基金池 → （可选抓取）→ 读库 → 因子 → 打分 → 选3 → 配权 → 入库 + 导出CSV
只依赖 src/ 下模块；其余文件不要动。
"""
from __future__ import annotations
import os, sys, sqlite3
from datetime import date
from pathlib import Path
import pandas as pd
# 在 run_daily_fund.py 顶部 imports 附近加入
import os
try:
    from src.backfill_portfolio import backfill as backfill_portfolio
except Exception:
    backfill_portfolio = None

# 计算项目根 & 注入 src
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# 配置与模块
import src.config as CFG
from src.data_loader_fund import load_nav, to_returns, make_equal_benchmark
from src.feature_engineering_fund import compute_factors
from src.scoring_model import score_funds
from src.optimizer import build_and_save_portfolio

# 可选抓取：若你本地有并行抓取模块则调用，否则跳过
try:
    from src.parallel_fetch import fetch_and_save_nav_batch  # 不存在则走 except
except Exception:
    fetch_and_save_nav_batch = None

# ---------------- 工具 ----------------
def _norm_code(x) -> str:
    s = str(x).strip()
    d = "".join(ch for ch in s if ch.isdigit())
    if len(d) in (5, 6):
        return d.zfill(6)
    return s

def _resolve_universe_csv() -> Path | None:
    """
    多路径回退：
      1) CFG.UNIVERSE_CSV（若存在）
      2) <ROOT>/data/universe_fund_effective.csv
      3) <ROOT>/data/universe_fund.csv
    都没有则返回 None（改从DB抽取）
    """
    cands = []
    if getattr(CFG, "UNIVERSE_CSV", None):
        cands.append(Path(CFG.UNIVERSE_CSV))
    cands += [ROOT / "data" / "universe_fund_effective.csv",
              ROOT / "data" / "universe_fund.csv"]
    for p in cands:
        if p and p.exists():
            return p
    return None

def _detect_nav_table(conn: sqlite3.Connection) -> tuple[str, str] | tuple[None, None]:
    """自动识别净值表及基金代码列（简化探测，仅用于兜底抽池）"""
    pref = ["fund_nav_daily", "fund_data_raw", "fund_nav_raw", "fund_nav", "fund_price"]
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    order = pref + [t for t in tables if t not in pref]
    def cols(t): return [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')]
    FUND_COLS = ["fund_code", "code", "基金代码", "基金代码(6位)", "证券代码"]
    DATE_COLS = ["date","trade_date","pricedate","净值日期","交易日期","日期"]
    NAV_COLS  = ["nav","单位净值","净值","unit_nav","nav_unit","累计净值","复权单位净值","单位净值(元)"]
    for t in order:
        if t not in tables: continue
        cs = cols(t)
        f = next((c for c in FUND_COLS if c in cs), None)
        d = next((c for c in DATE_COLS if c in cs), None)
        n = next((c for c in NAV_COLS  if c in cs), None)
        if f and d and n:
            return t, f
    return None, None

def _load_universe(limit: int) -> list[str]:
    """优先 CSV；没有则从 DB 抽取最近存在净值的基金代码"""
    csv_path = _resolve_universe_csv()
    if csv_path is not None:
        df = pd.read_csv(csv_path)
        col = "fund_code" if "fund_code" in df.columns else df.columns[0]
        codes = df[col].astype(str).map(_norm_code).dropna().tolist()
        print(f"[UNIVERSE] 来自 CSV: {csv_path}")
        return codes[:limit]
    # 兜底：DB 抽取
    if not Path(CFG.DB_PATH).exists():
        raise FileNotFoundError("未找到基金池CSV，且数据库不存在，无法构建基金池。")
    with sqlite3.connect(CFG.DB_PATH) as con:
        t, fcol = _detect_nav_table(con)
        if not t:
            raise FileNotFoundError("未找到基金池CSV，且库内无法识别净值表。")
        df = pd.read_sql_query(f'SELECT DISTINCT "{fcol}" AS fund_code FROM "{t}"', con)
    codes = df["fund_code"].astype(str).map(_norm_code).dropna().unique().tolist()
    print(f"[UNIVERSE] 来自 DB: 表 {t}（抽取 {len(codes)} 条，取前 {limit}）")
    return codes[:limit]

def today_ymd() -> str:
    return date.today().isoformat()

# ---------------- 主流程 ----------------
def main():
    # 目录准备
    Path(CFG.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    # 强约束：基金池≤10，组合=3（从 config/环境变量读，之后再钳制）
    uni_limit = min(int(getattr(CFG, "UNIVERSE_LIMIT", 1000)), 1000)
    print(f"[STEP 0] 运行日：{today_ymd()}")
    print(f"[STEP 1] 准备基金池（上限={uni_limit}）")

    codes = _load_universe(uni_limit)
    print(f"[UNIVERSE] 实际数量：{len(codes)} → {codes[:min(5,len(codes))]} ...")

    # 可选抓取：存在抓取模块才执行，不存在则直接从库读
    if fetch_and_save_nav_batch is not None:
        workers = int(os.getenv("PARALLEL_WORKERS", str(max(8, os.cpu_count() or 8))))
        print(f"[STEP 1.5] 抓取净值（workers={workers}, since={CFG.SINCE_DATE}）")
        try:
            fetch_and_save_nav_batch(codes, since=CFG.SINCE_DATE, max_workers=workers)
        except Exception as e:
            print(f"[WARN] 抓取失败（将直接从库读取）：{e}")

    # ====== STEP 2) 从库读取净值→日收益 ======
    print("[STEP 2] 从库读取净值→日收益")
    df_nav = load_nav(codes, getattr(CFG, "SINCE_DATE", "2018-01-01"))
    df_ret = to_returns(df_nav)
    bench  = make_equal_benchmark(df_ret)

    # ====== STEP 3) 计算因子 ======
    print("[STEP 3] 计算因子")
    df_fac = compute_factors(df_ret, bench=bench, window=int(getattr(CFG, "WINDOW_DAYS", 126)))

    # ====== STEP 4) 打分 ======
    print("[STEP 4] 打分")
    df_scores = score_funds(df_fac)
    if df_scores is not None and not df_scores.empty:
        scores_file = Path(CFG.OUTPUT_DIR) / f"scores_{today_ymd()}.csv"
        try:
            df_scores.to_csv(scores_file, index=False, encoding="utf-8")
            print(f"[导出] {scores_file}")
        except Exception as e:
            print(f"[WARN] 导出 scores 失败：{e}")
    else:
        print("[WARN] 打分为空")

    # ====== STEP 5) 构建组合（必做） ======
    print("[STEP 5] 构建组合并入库+导出")
    df_port = build_and_save_portfolio(df_scores, df_ret, date_str=today_ymd())
    if df_port is None or df_port.empty:
        print("[WARN] 组合为空（请检查打分/历史长度/数据入库）")
    print("====== 全流程完成 ======")

    # ==== 新增：历史回填（方案B） ====
    try:
        backfill_days = int(os.getenv("FUND_BACKFILL_DAYS", "0"))
    except Exception:
        backfill_days = 0

    if backfill_days > 0 and backfill_portfolio is not None:
        print(f"[BACKFILL] 开始回填最近 {backfill_days} 个交易日的组合到 portfolio_results ...")
        backfill_portfolio(n_days=backfill_days, verbose=True)
        print(f"[BACKFILL] 回填完成。")


if __name__ == "__main__":
    main()
