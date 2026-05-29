from __future__ import annotations
import numpy as np
import pandas as pd


def _robust_inverse_vol(df_ret: pd.DataFrame, top_codes: list[str],
                        lookback_max: int = 60, lookback_min: int = 20) -> pd.Series:
    if df_ret is None or df_ret.empty or not top_codes:
        return pd.Series(dtype=float)
    sub = df_ret[df_ret["fund_code"].isin(top_codes)].copy()
    cnt = sub.groupby("fund_code")["date"].nunique()
    if cnt.empty:
        return pd.Series(dtype=float)
    L = int(min(lookback_max, max(lookback_min, cnt.median())))
    recent = sub.sort_values("date").groupby("fund_code").tail(L)
    vol = recent.groupby("fund_code")["ret"].std(ddof=0)
    eps = 1e-8
    vol = (vol + eps).replace(0, np.nan)
    iv = 1.0 / vol
    if iv.notna().sum() == 0:
        return pd.Series(dtype=float)
    w = iv / iv.sum()
    return w.reindex(top_codes).fillna(0.0)


def build_portfolio(df_scores: pd.DataFrame, df_ret: pd.DataFrame,
                    date_str: str, top_n: int = 3,
                    window_days: int = 60) -> pd.DataFrame:
    cols = ["date", "fund_code", "weight_equal", "weight_risk_parity", "weight_mixed", "score", "rank"]
    if df_scores is None or df_scores.empty:
        return pd.DataFrame(columns=cols)

    top = df_scores.sort_values("score", ascending=False).head(top_n)["fund_code"].astype(str).tolist()
    n = len(top)
    if n == 0:
        return pd.DataFrame(columns=cols)

    w_eq = pd.Series(1.0 / n, index=top, name="w_eq")
    w_iv = _robust_inverse_vol(df_ret, top, lookback_max=window_days, lookback_min=20)
    if w_iv.sum() <= 0 or w_iv.isna().all():
        w_iv = w_eq.copy()
    else:
        w_iv = w_iv / w_iv.sum()
    w_mix = 0.5 * w_eq.add(w_iv, fill_value=0.0)

    out = pd.DataFrame({
        "date": date_str,
        "fund_code": top,
        "weight_equal": w_eq.values,
        "weight_risk_parity": w_iv.values,
        "weight_mixed": w_mix.values,
    })
    if {"fund_code", "score", "rank"}.issubset(df_scores.columns):
        out = out.merge(df_scores[["fund_code", "score", "rank"]], on="fund_code", how="left")
    return out
