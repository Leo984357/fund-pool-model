# -*- coding: utf-8 -*-
from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path

# 配置
try:
    from . import config as CFG
    TOP_N_FUNDS = int(getattr(CFG, "TOP_N_FUNDS", 3))
    OUTPUT_DIR  = Path(getattr(CFG, "OUTPUT_DIR", Path(__file__).resolve().parents[1] / "output"))
    IV_LOOKBACK_MAX = int(getattr(CFG, "IV_LOOKBACK_MAX", 60))
    IV_LOOKBACK_MIN = int(getattr(CFG, "IV_LOOKBACK_MIN", 20))
except Exception:
    TOP_N_FUNDS, IV_LOOKBACK_MAX, IV_LOOKBACK_MIN = 3, 60, 20
    OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output"

from .dao import upsert_df  # 保持原接口

def _robust_inverse_vol(df_ret: pd.DataFrame, top_codes: list[str]) -> pd.Series:
    """稳健逆波动：窗口自适应 + epsilon 防零；不可用时退回等权"""
    if df_ret is None or df_ret.empty or not top_codes:
        return pd.Series(dtype=float)
    sub = df_ret[df_ret["fund_code"].isin(top_codes)].copy()
    cnt = sub.groupby("fund_code")["date"].nunique()
    if cnt.empty:
        return pd.Series(dtype=float)
    L = int(min(IV_LOOKBACK_MAX, max(IV_LOOKBACK_MIN, cnt.median())))
    recent = sub.sort_values("date").groupby("fund_code").tail(L)
    vol = recent.groupby("fund_code")["ret"].std(ddof=0)
    eps = 1e-8
    vol = (vol + eps).replace(0, np.nan)
    iv = 1.0 / vol
    if iv.notna().sum() == 0:
        return pd.Series(dtype=float)
    w = iv / iv.sum()
    return w.reindex(top_codes).fillna(0.0)

def build_and_save_portfolio(df_scores: pd.DataFrame,
                             df_ret: pd.DataFrame,
                             date_str: str) -> pd.DataFrame:
    """
    输出：
      [date,fund_code,weight_equal,weight_risk_parity,weight_mixed,score,rank]
    行为：
      1) upsert 至 SQLite: portfolio_results
      2) 导出 CSV: output/portfolio_fund_YYYY-MM-DD.csv
    """
    cols = ["date","fund_code","weight_equal","weight_risk_parity","weight_mixed","score","rank"]
    if df_scores is None or df_scores.empty:
        return pd.DataFrame(columns=cols)

    top = df_scores.sort_values("score", ascending=False).head(TOP_N_FUNDS)["fund_code"].astype(str).tolist()
    n = len(top)
    if n == 0:
        return pd.DataFrame(columns=cols)

    w_eq = pd.Series(1.0 / n, index=top, name="w_eq")
    w_iv = _robust_inverse_vol(df_ret, top)
    if (w_iv.sum() <= 0) or (w_iv.isna().all()):
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
    if {"fund_code","score","rank"}.issubset(df_scores.columns):
        out = out.merge(df_scores[["fund_code","score","rank"]], on="fund_code", how="left")

    # 入库 + 导出
    upsert_df("portfolio_results", out, pk_cols=["date","fund_code"])
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        outfile = OUTPUT_DIR / f"portfolio_fund_{date_str}.csv"
        out.to_csv(outfile, index=False, encoding="utf-8")
        print(f"[导出] {outfile}")
    except Exception as e:
        print(f"[WARN] 导出 CSV 失败：{e}")

    # 控制台摘要
    try:
        disp = out[["fund_code","weight_mixed","weight_risk_parity","weight_equal","score","rank"]]
        print("[组合] 当日持仓（按混合权重）")
        print(disp.sort_values("weight_mixed", ascending=False).to_string(index=False))
    except Exception:
        pass

    return out
