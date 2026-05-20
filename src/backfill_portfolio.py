# -*- coding: utf-8 -*-
from __future__ import annotations

import sqlite3
from pathlib import Path
import pandas as pd
from .config import C

def _read_sql(conn, sql: str) -> pd.DataFrame:
    return pd.read_sql(sql, conn, parse_dates=["date"])

def _export_backtest_curve(df: pd.DataFrame, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "backtest_fund_nav.csv"
    df.to_csv(path, index=False)
    print(f"[OK] 导出回测曲线：{path}")
    return path

def backfill_equity_from_latest_weights(
    db_path: str | Path = None,
    nav_table: str | None = None,
    portfolio_table: str | None = None,
    weight_col: str | None = None,
    days: int | None = None,
    out_dir: str | Path | None = None,
) -> pd.DataFrame:
    """
    读取最近一段时间（days）的权重与 NAV，按“静态持仓（最近一次权重）”兜底生成等价的净值曲线：
      - 若历史样本不足，仍可产出一条可视化的 equity 以供 GUI 展示；
      - 该函数不写回 DB，仅生成曲线文件便于审阅。
    返回 DataFrame(['date','equity'])
    """
    db_path = Path(db_path or C.DB_PATH)
    nav_table = nav_table or C.NAV_TABLE
    portfolio_table = portfolio_table or C.PORTFOLIO_TABLE
    weight_col = weight_col or C.WEIGHT_SCHEME
    days = days or C.WINDOW_DAYS
    out_dir = Path(out_dir or C.OUTPUT_DIR)

    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在：{db_path}")

    with sqlite3.connect(db_path) as conn:
        # 取最近 days 的交易日 NAV
        sql_nav = f"""
        SELECT date, fund_code, nav
        FROM {nav_table}
        WHERE date >= date((SELECT max(date) FROM {nav_table}), '-{days} day')
        """
        nav = _read_sql(conn, sql_nav).sort_values("date")
        if nav.empty:
            raise ValueError(f"{nav_table} 最近 {days} 日无净值数据。")

        px = nav.pivot_table(index="date", columns="fund_code", values="nav", aggfunc="last").sort_index()

        # 拿最近一次的组合权重（按 weight_col），作为静态持仓
        sql_w = f"""
        SELECT date, fund_code, {weight_col} AS weight
        FROM {portfolio_table}
        WHERE date = (SELECT max(date) FROM {portfolio_table})
        """
        w_last = _read_sql(conn, sql_w)
        if w_last.empty:
            # 若权重也没有，直接给一个均匀权重，对所有基金平均分配
            codes = list(px.columns)
            if not codes:
                raise ValueError("无基金列可用于静态持仓。")
            w_vec = pd.Series(1.0 / len(codes), index=codes, name="weight")
        else:
            w_vec = w_last.set_index("fund_code")["weight"]
            # 只保留 NAV 中存在的基金列
            w_vec = w_vec.reindex(px.columns).fillna(0.0)
            s = w_vec.abs().sum()
            w_vec = w_vec / (s if s != 0 else 1.0)

        # 计算日收益（新版接口，去掉 deprecated 警告）
        rets = px.pct_change(fill_method=None).fillna(0.0)

        # 静态持仓：整个区间都用同一组权重
        port_ret = (rets * w_vec.reindex(rets.columns).fillna(0.0)).sum(axis=1)
        equity = (1.0 + port_ret).cumprod()

        df_curve = pd.DataFrame({"date": equity.index, "equity": equity.values})
        _export_backtest_curve(df_curve, out_dir)
        return df_curve

def main() -> None:
    print("[BACKFILL] 使用静态持仓兜底，生成最近窗口的净值曲线 ...")
    try:
        _ = backfill_equity_from_latest_weights(
            db_path=C.DB_PATH,
            nav_table=C.NAV_TABLE,
            portfolio_table=C.PORTFOLIO_TABLE,
            weight_col=C.WEIGHT_SCHEME,
            days=C.WINDOW_DAYS,
            out_dir=C.OUTPUT_DIR,
        )
        print("[BACKFILL] done.")
    except Exception as e:
        print("[BACKFILL][ERROR]", repr(e))
