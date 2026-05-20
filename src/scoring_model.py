from __future__ import annotations
import numpy as np
import pandas as pd
from typing import List

# 兼容读取你的 config；不存在则落到默认
try:
    from . import config as CFG
    FACTOR_WEIGHTS = getattr(CFG, "FACTOR_WEIGHTS", {
        "ann_return": 0.35, "ann_vol": -0.15, "down_vol": -0.10,
        "mdd": -0.10, "sharpe": 0.35, "ir": 0.15
    })
    PURE_SHARPE_ONLY = getattr(CFG, "PURE_SHARPE_ONLY", False)
except Exception:
    FACTOR_WEIGHTS = {
        "ann_return": 0.35, "ann_vol": -0.15, "down_vol": -0.10,
        "mdd": -0.10, "sharpe": 0.35, "ir": 0.15
    }
    PURE_SHARPE_ONLY = False

def _winsor(s: pd.Series, p: float = 0.01) -> pd.Series:
    if s.notna().sum() < 5:
        return s
    lo, hi = s.quantile(p), s.quantile(1-p)
    return s.clip(lower=lo, upper=hi)

def _z_mad(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    med = x.median()
    mad = (x - med).abs().median()
    if not np.isfinite(mad) or mad == 0:
        sd = x.std(ddof=0)
        return (x - x.mean()) / sd if (np.isfinite(sd) and sd != 0) else (x - x.mean())
    return (x - med) / (1.4826 * mad)

def score_funds(df_fac: pd.DataFrame) -> pd.DataFrame:
    """
    输入：因子表（compute_factors 输出）
    输出：DataFrame[fund_code, score, rank, ...因子列]
    —— 接口名称与返回列保持不变（至少包含 fund_code/score/rank）
    """
    if df_fac is None or df_fac.empty:
        return pd.DataFrame(columns=["fund_code","score","rank"])
    df = df_fac.copy()

    cols = [c for c in FACTOR_WEIGHTS.keys() if c in df.columns]
    if PURE_SHARPE_ONLY and "sharpe" in df.columns:
        cols = ["sharpe"]
    if not cols:
        return pd.DataFrame(columns=["fund_code","score","rank"])

    use_cols: List[str] = []
    for c in cols:
        s = pd.to_numeric(df[c], errors="coerce")
        if s.notna().sum() <= 1 or s.nunique(dropna=True) <= 1:
            continue
        df[c] = _winsor(s)
        df[c] = _z_mad(df[c])
        use_cols.append(c)
    if not use_cols:
        return pd.DataFrame(columns=["fund_code","score","rank"])

    df["score"] = 0.0
    wsum = 0.0
    for c in use_cols:
        w = float(FACTOR_WEIGHTS.get(c, 0))
        if w == 0:
            continue
        df["score"] = df["score"] + w * df[c]
        wsum += abs(w)
    if wsum > 0:
        df["score"] = df["score"] / wsum   # 归一到[-1,1]附近

    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["rank"] = np.arange(1, len(df) + 1)
    return df[["fund_code","score","rank"] + use_cols]
