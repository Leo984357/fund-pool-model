from __future__ import annotations
from pathlib import Path
import sqlite3
import pandas as pd

from .._config import Config
from .._exceptions import BacktestError


def run_backtest(config: Config, weight_col: str | None = None) -> pd.DataFrame:
    weight_col = weight_col or config.weight_scheme
    db_path = config.db_path
    nav_table = config.nav_table
    portfolio_table = config.portfolio_table
    since_date = config.since_date
    out_dir = config.output_dir

    if not db_path.exists():
        raise BacktestError(f"DB not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        sql_w = f"""
        SELECT date, fund_code, {weight_col} AS weight
        FROM {portfolio_table}
        WHERE date >= date('{since_date}')
        """
        w = pd.read_sql(sql_w, conn, parse_dates=["date"])
        if w.empty:
            raise BacktestError(f"No weights in {portfolio_table} since {since_date}")

        w = w.pivot_table(index="date", columns="fund_code", values="weight", aggfunc="last").sort_index()
        w = w.ffill().fillna(0.0)
        row_sum = w.abs().sum(axis=1)
        row_sum[row_sum == 0.0] = 1.0
        w = w.div(row_sum, axis=0)

        nav = pd.read_sql(f"SELECT date, fund_code, nav FROM {nav_table}", conn, parse_dates=["date"])
        if nav.empty:
            raise BacktestError(f"No NAV data in {nav_table}")

        px = nav.pivot_table(index="date", columns="fund_code", values="nav", aggfunc="last").sort_index()
        px = px.reindex(w.index.union(px.index)).sort_index()
        rets = px.pct_change(fill_method=None).reindex(w.index).fillna(0.0)

        port_ret = (w.shift(1).fillna(0.0) * rets).sum(axis=1)
        equity = (1.0 + port_ret).cumprod()
        df_equity = pd.DataFrame({"date": equity.index, "equity": equity.values})

        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "equity_curve.csv"
        df_equity.to_csv(out_path, index=False)
        print(f"[BACKTEST] saved: {out_path}")
        return df_equity
