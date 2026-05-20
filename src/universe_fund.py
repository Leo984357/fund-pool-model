# -*- coding: utf-8 -*-
"""
universe_fund.py  — 统一基金池入/出路径 & 上限参数
要点：
1) 统一从 src.config 读取 UNIVERSE_CSV（可被 FUND_UNIVERSE_CSV 覆盖），写入/读取同一路径
2) 上限优先级：入参 limit > 环境变量 FUND_UNIVERSE_LIMIT / UNIVERSE_LIMIT > config.UNIVERSE_LIMIT
3) 先读 CSV；不足从 DB 去重补齐；仍不足再尝试 AKShare；最终统一为 6 位数字、去重、截断
"""
from __future__ import annotations
import os, sqlite3
from pathlib import Path
from typing import List, Optional
import pandas as pd

# --- 配置与路径 ---
try:
    from .config import PROJECT_ROOT, DATA_DIR, UNIVERSE_CSV as CFG_UNIVERSE_CSV, UNIVERSE_LIMIT as CFG_UNIVERSE_LIMIT
except Exception:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    DATA_DIR = PROJECT_ROOT / "data"
    CFG_UNIVERSE_CSV = str(DATA_DIR / "universe_fund.csv")
    CFG_UNIVERSE_LIMIT = 100

try:
    from .utils import log
except Exception:
    def log(*a, **k): print(*a, **k)

# 统一：CSV 绝对路径（无论谁调用都落到同一处）
_UNIVERSE_CSV = Path(CFG_UNIVERSE_CSV) if CFG_UNIVERSE_CSV else (PROJECT_ROOT / "data" / "universe_fund.csv")
if not _UNIVERSE_CSV.is_absolute():
    _UNIVERSE_CSV = (PROJECT_ROOT / _UNIVERSE_CSV).resolve()

_DB_PATH = PROJECT_ROOT / "db" / "fund_db.sqlite"

# --- helpers ---
def _effective_limit(limit: Optional[int]) -> int:
    if limit is not None:
        return int(limit)
    # 兼容两种前缀
    env = os.getenv("FUND_UNIVERSE_LIMIT") or os.getenv("UNIVERSE_LIMIT")
    if env:
        try:
            return int(env)
        except:
            pass
    return int(CFG_UNIVERSE_LIMIT)

def _normalize_codes(obj) -> pd.DataFrame:
    """把任意 Series/DataFrame 提取成一列 fund_code（仅 6 位数字），去重。"""
    if obj is None:
        return pd.DataFrame(columns=["fund_code"])
    if isinstance(obj, pd.Series):
        s = obj.astype(str)
    elif isinstance(obj, pd.DataFrame):
        prefer = ["fund_code","代码","基金代码","symbol","code"]
        col = next((c for c in prefer if c in obj.columns), None)
        if col is None:
            for c in obj.columns:
                vals = obj[c].astype(str)
                if vals.str.contains(r"\d{6}", regex=True).any():
                    col = c; break
        if col is None:
            col = obj.columns[0]
        s = obj[col].astype(str)
    else:
        return pd.DataFrame(columns=["fund_code"])
    s = s.str.extract(r"(\d{6})", expand=False).dropna().map(lambda x: x.zfill(6))
    return pd.DataFrame({"fund_code": s}).drop_duplicates(subset=["fund_code"]).reset_index(drop=True)

def _read_csv_candidates() -> pd.DataFrame:
    try:
        if _UNIVERSE_CSV.exists():
            return _normalize_codes(pd.read_csv(_UNIVERSE_CSV, dtype=str))
    except Exception as e:
        log(f"[WARN] 读取 {_UNIVERSE_CSV} 失败：{e}")
    return pd.DataFrame(columns=["fund_code"])

def _read_db_codes() -> pd.DataFrame:
    if not _DB_PATH.exists():
        return pd.DataFrame(columns=["fund_code"])
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        df = pd.read_sql("SELECT DISTINCT fund_code FROM fund_nav_daily;", conn)
        conn.close()
        return _normalize_codes(df)
    except Exception as e:
        log(f"[INFO] 读取 DB 失败：{e}")
        return pd.DataFrame(columns=["fund_code"])

def _read_akshare_codes(max_rows: int = 2000) -> pd.DataFrame:
    try:
        import akshare as ak
        dfs = []
        for fn in ("fund_name_em", "fund_etf_fund_daily_em", "fund_lof_fund_daily_em"):
            if hasattr(ak, fn):
                try:
                    df = getattr(ak, fn)()
                    if isinstance(df, pd.DataFrame) and not df.empty:
                        dfs.append(df)
                except Exception as e:
                    log(f"[INFO] AK {fn} 拉取失败：{e}")
        if not dfs:
            return pd.DataFrame(columns=["fund_code"])
        return _normalize_codes(pd.concat(dfs, ignore_index=True)).head(max_rows)
    except Exception as e:
        log(f"[INFO] AKShare 不可用/失败，跳过补齐：{e}")
        return pd.DataFrame(columns=["fund_code"])

# --- main api ---
def load_universe_fund(limit: Optional[int] = None) -> List[str]:
    eff_limit = _effective_limit(limit)
    _UNIVERSE_CSV.parent.mkdir(parents=True, exist_ok=True)

    # 1) CSV
    base = _read_csv_candidates()
    base_cnt = int(base.shape[0])

    # 2) DB 补齐
    if base_cnt < eff_limit:
        db_df = _read_db_codes()
        if not db_df.empty:
            base = pd.concat([base, db_df], ignore_index=True).drop_duplicates()

    # 3) AKShare 补齐
    if base.shape[0] < eff_limit:
        ak_df = _read_akshare_codes(max_rows=eff_limit*2)
        if not ak_df.empty:
            base = pd.concat([base, ak_df], ignore_index=True).drop_duplicates()

    # 统一、截断
    base = _normalize_codes(base)
    codes = base["fund_code"].head(eff_limit).tolist()

    # 写回 CSV（持久化，同一条路径）
    pd.DataFrame({"fund_code": codes}).to_csv(_UNIVERSE_CSV, index=False, encoding="utf-8-sig")

    log(f"[UNIVERSE] 候选={base_cnt} → 返回={len(codes)}（上限={eff_limit}） 已写回：{_UNIVERSE_CSV.resolve()}")
    if len(codes) < eff_limit:
        log(f"[HINT] 候选不足，未到上限 {eff_limit}；请检查 AKShare/网络或手工补充 CSV")
    return codes
