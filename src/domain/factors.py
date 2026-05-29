from __future__ import annotations
import numpy as np
import pandas as pd
from math import sqrt
from .._config import Config

TRADING_DAYS = 252
_REQUIRED = ["fund_code", "ann_return", "ann_vol", "down_vol", "sharpe", "ir", "mdd"]


def _mdd_from_returns(r: pd.Series) -> float:
    if r is None or r.empty:
        return np.nan
    wealth = (1.0 + r.fillna(0)).cumprod()
    peak = wealth.cummax()
    dd = wealth / peak - 1.0
    return float(dd.min()) if len(dd) else np.nan


def compute_factors(df_ret: pd.DataFrame, bench: pd.Series | None = None, window: int = 126) -> pd.DataFrame:
    if df_ret is None or df_ret.empty:
        return pd.DataFrame(columns=_REQUIRED)

    df = df_ret.copy()
    df["date"] = pd.to_datetime(df["date"])

    if bench is not None:
        b = bench.copy()
        b.index = pd.to_datetime(b.index)
        df = df.merge(b.rename("bench_ret"), left_on="date", right_index=True, how="left")
    else:
        df["bench_ret"] = np.nan

    df["excess"] = df["ret"] - df["bench_ret"]

    rows = []
    for code, g in df.groupby("fund_code", sort=False):
        g = g.sort_values("date")
        if len(g) < max(30, int(window * 0.5)):
            continue
        ww = g.tail(window)
        r = ww["ret"].astype(float)
        ex = ww["excess"].astype(float)

        mu = r.mean()
        sd = r.std(ddof=0)
        down = r[r < 0].std(ddof=0)
        sharpe = (mu / sd * sqrt(TRADING_DAYS)) if (sd and sd > 0) else np.nan
        ex_sd = ex.std(ddof=0)
        ir = (ex.mean() / ex_sd * sqrt(TRADING_DAYS)) if (ex_sd and ex_sd > 0) else np.nan

        rows.append({
            "fund_code": code,
            "ann_return": float(mu * TRADING_DAYS) if np.isfinite(mu) else np.nan,
            "ann_vol": float(sd * sqrt(TRADING_DAYS)) if np.isfinite(sd) else np.nan,
            "down_vol": float(down * sqrt(TRADING_DAYS)) if np.isfinite(down) else np.nan,
            "sharpe": float(sharpe) if np.isfinite(sharpe) else np.nan,
            "ir": float(ir) if np.isfinite(ir) else np.nan,
            "mdd": float(_mdd_from_returns(r)),
        })

    if not rows:
        return pd.DataFrame(columns=_REQUIRED)
    return pd.DataFrame(rows, columns=_REQUIRED)


def adapt_factor_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    mapping = {
        "annual_return": "ann_return",
        "annual_vol": "ann_vol",
        "downside_vol": "down_vol",
        "max_drawdown": "mdd",
        "information_ratio": "ir",
    }
    out = df.copy()
    for old, new in mapping.items():
        if old in out.columns and new not in out.columns:
            out = out.rename(columns={old: new})
    return out
