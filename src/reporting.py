from __future__ import annotations
import datetime as dt
from pathlib import Path
import pandas as pd

def _metrics_from_returns(r: pd.Series) -> dict:
    if r is None or r.empty:
        return {}
    r = r.dropna()
    ann = r.mean()*252
    vol = r.std(ddof=0)*(252**0.5)
    sharpe = ann/vol if vol and vol>0 else float("nan")
    wealth = (1+r).cumprod()
    dd = wealth/wealth.cummax()-1
    mdd = dd.min() if len(dd) else float("nan")
    return {"ann_return":ann, "ann_vol":vol, "sharpe":sharpe, "mdd":mdd}

def generate_daily_report(date_str: str,
                          df_scores: pd.DataFrame,
                          df_port: pd.DataFrame,
                          port_nav: pd.Series | None,
                          out_dir: Path):
    """
    生成简易 HTML 报告：评分 TOP、组合权重、若提供 NAV 则附指标。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    html = [f"<h2>Daily Report - {date_str}</h2>"]
    if df_scores is not None and not df_scores.empty:
        html.append("<h3>Top Scores</h3>")
        html.append(df_scores.head(10).to_html(index=False))
    if df_port is not None and not df_port.empty:
        html.append("<h3>Portfolio Weights</h3>")
        html.append(df_port.to_html(index=False))
    if port_nav is not None and not port_nav.empty:
        ret = port_nav.pct_change().dropna()
        m = _metrics_from_returns(ret)
        html.append("<h3>Backtest Snapshot</h3>")
        html.append(pd.DataFrame([m]).to_html(index=False))
    (out_dir/"report.html").write_text("\n".join(html), encoding="utf-8")
