from __future__ import annotations
from pathlib import Path
import sqlite3
import pandas as pd

from .._config import Config
from .._exceptions import BacktestError


def backfill_equity(config: Config, days: int | None = None, weight_col: str | None = None) -> pd.DataFrame:
    days = days or config.window_days
    weight_col = weight_col or config.weight_scheme
    db_path = config.db_path
    nav_table = config.nav_table
    portfolio_table = config.portfolio_table
    out_dir = config.output_dir

    if not db_path.exists():
        raise BacktestError(f"DB not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        nav = pd.read_sql(
            f"""
            SELECT date, fund_code, nav FROM {nav_table}
            WHERE date >= date((SELECT max(date) FROM {nav_table}), '-{days} day')
            """,
            conn, parse_dates=["date"],
        ).sort_values("date")
        if nav.empty:
            raise BacktestError(f"No NAV in last {days} days")

        px = nav.pivot_table(index="date", columns="fund_code", values="nav", aggfunc="last").sort_index()

        sql_w = f"""
        SELECT date, fund_code, {weight_col} AS weight
        FROM {portfolio_table}
        WHERE date = (SELECT max(date) FROM {portfolio_table})
        """
        w_last = pd.read_sql(sql_w, conn, parse_dates=["date"])
        if w_last.empty:
            codes = list(px.columns)
            if not codes:
                raise BacktestError("No funds available")
            w_vec = pd.Series(1.0 / len(codes), index=codes, name="weight")
        else:
            w_vec = w_last.set_index("fund_code")["weight"]
            w_vec = w_vec.reindex(px.columns).fillna(0.0)
            s = w_vec.abs().sum()
            w_vec = w_vec / (s if s != 0 else 1.0)

        rets = px.pct_change(fill_method=None).fillna(0.0)
        port_ret = (rets * w_vec.reindex(rets.columns).fillna(0.0)).sum(axis=1)
        equity = (1.0 + port_ret).cumprod()

        df_curve = pd.DataFrame({"date": equity.index, "equity": equity.values})
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "backtest_fund_nav.csv"
        df_curve.to_csv(out_path, index=False)
        print(f"[BACKFILL] saved: {out_path}")
        return df_curve
