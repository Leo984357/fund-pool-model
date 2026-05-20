# -*- coding: utf-8 -*-
from __future__ import annotations
import numpy as np
import pandas as pd
from math import sqrt

TRADING_DAYS = 252
_REQUIRED = ["fund_code","ann_return","ann_vol","down_vol","sharpe","ir","mdd"]

def _mdd_from_returns(r: pd.Series) -> float:
    """由日收益估算窗口内最大回撤（基于累计净值曲线，返回负值）。"""
    if r is None or r.empty:
        return np.nan
    wealth = (1.0 + r.fillna(0)).cumprod()
    peak = wealth.cummax()
    dd = wealth / peak - 1.0
    return float(dd.min()) if len(dd) else np.nan

def _auto_equal_bench(df_ret: pd.DataFrame) -> pd.Series:
    """当未提供 bench 时，用等权平均日收益作为基准。"""
    if df_ret is None or df_ret.empty:
        return pd.Series(dtype=float, name="bench_ret")
    s = df_ret.groupby("date")["ret"].mean().rename("bench_ret")
    s.index = pd.to_datetime(s.index)
    return s

def _pick_bench_arg(args, kwargs, df_ret: pd.DataFrame) -> pd.Series:
    """
    兼容多种调用形态：
    - compute_factors(df_ret, bench, window=...)
    - compute_factors(df_ret, df_nav, bench, window=...)   ← 忽略 df_nav
    - compute_factors(df_ret, bench=..., window=...)
    如果都没给 bench，则退化为等权基准。
    """
    if "bench" in kwargs and isinstance(kwargs["bench"], pd.Series):
        return kwargs["bench"]

    # 从位置参数里找第一个 pd.Series 作为 bench（若传了 df_nav，则它通常是 DataFrame，会被自动跳过）
    for a in args:
        if isinstance(a, pd.Series):
            return a

    # 都没找到就用等权基准
    return _auto_equal_bench(df_ret)

def compute_factors(df_ret: pd.DataFrame, *args, window: int = 126, **kwargs) -> pd.DataFrame:
    """
    自适应签名版本：
    - 支持 compute_factors(df_ret, bench, window=...)
    - 支持 compute_factors(df_ret, df_nav, bench, window=...)
      （会自动忽略 df_nav，只用 bench）
    返回：
      DataFrame[fund_code, ann_return, ann_vol, down_vol, sharpe, ir, mdd]
    """
    if df_ret is None or df_ret.empty:
        return pd.DataFrame(columns=_REQUIRED)

    # 选出 bench（Series），忽略任何 DataFrame 类型的额外位置参数（如 df_nav）
    bench = _pick_bench_arg(args, kwargs, df_ret)

    df = df_ret.copy()
    df["date"] = pd.to_datetime(df["date"])

    if isinstance(bench, pd.Series):
        b = bench.copy()
        b.index = pd.to_datetime(b.index)
        df = df.merge(b.rename("bench_ret"), left_on="date", right_index=True, how="left")
    else:
        # 理论上不会走到这里，留作兜底
        df["bench_ret"] = np.nan

    df["excess"] = df["ret"] - df["bench_ret"]

    rows = []
    for code, g in df.groupby("fund_code", sort=False):
        g = g.sort_values("date")
        if len(g) < max(30, int(window*0.5)):
            continue
        ww = g.tail(window)
        r = ww["ret"].astype(float)
        ex = ww["excess"].astype(float)

        mu   = r.mean()
        sd   = r.std(ddof=0)
        down = r[r < 0].std(ddof=0)

        sharpe = (mu / sd * sqrt(TRADING_DAYS)) if (sd and sd > 0) else np.nan
        ex_sd  = ex.std(ddof=0)
        ir     = (ex.mean() / ex_sd * sqrt(TRADING_DAYS)) if (ex_sd and ex_sd > 0) else np.nan

        rows.append({
            "fund_code":  code,
            "ann_return": float(mu * TRADING_DAYS)                 if np.isfinite(mu)   else np.nan,
            "ann_vol":    float(sd * sqrt(TRADING_DAYS))           if np.isfinite(sd)   else np.nan,
            "down_vol":   float(down * sqrt(TRADING_DAYS))         if np.isfinite(down) else np.nan,
            "sharpe":     float(sharpe)                            if np.isfinite(sharpe) else np.nan,
            "ir":         float(ir)                                if np.isfinite(ir)     else np.nan,
            "mdd":        float(_mdd_from_returns(r)),
        })

    if not rows:
        return pd.DataFrame(columns=_REQUIRED)
    return pd.DataFrame(rows, columns=_REQUIRED)
