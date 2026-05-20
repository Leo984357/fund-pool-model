# -*- coding: utf-8 -*-
"""
RunStrategyWorker.py — GUI参数→ENV→真实管线→回测→artifacts

主要职责：
1) 把 GUI 的参数设置成环境变量（含 FUND_BACKFILL_DAYS）
2) 调用 run_daily_fund.main()（零实参，完全按 ENV 运行）
3) 回测：
   - 优先用 src.backtest_quick_fund.backtest_from_db(weight_col)
   - 若返回空或过短，回读 output/backtest_fund_nav.csv
   - 若仍为空，用“静态持仓”兜底（以最新权重 × 历史NAV 合成）
4) 导出 artifacts：收益曲线（csv/png）、当日权重、交易清单（再平衡diff）、参数json
5) 计算指标并回传
"""

from __future__ import annotations
from PySide6.QtCore import QThread, Signal

import os
import sys
import json
import hashlib
import importlib
import sqlite3
import datetime as dt
from typing import Dict, Any, Optional, Tuple

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

# --- utils: normalize rank from any type to int ---
def _normalize_rank_col(df):
    """
    Ensure df['rank'] is integer (handles bytes/blob/str/float),
    then sort ascending by rank.
    """
    if 'rank' not in df.columns:
        return df

    import pandas as pd

    def _to_int(v):
        # bytes / bytearray / memoryview -> little-endian unsigned int
        if isinstance(v, (bytes, bytearray, memoryview)):
            try:
                return int.from_bytes(v, byteorder='little', signed=False)
            except Exception:
                return None
        # 其他类型：尽量转成 int
        try:
            # 先把类似 '6.0' 的字符串变成 float，再取 int
            if isinstance(v, str):
                v = v.strip()
                # 常见 "b'...'" 字符串误入，做一次解包
                if v.startswith("b'") and v.endswith("'"):
                    v = v[2:-1].encode('latin1')
                    return int.from_bytes(v, 'little', signed=False)
            f = float(v)
            return int(f)
        except Exception:
            return None

    df = df.copy()
    df['rank'] = df['rank'].map(_to_int)
    # 如果有缺失，兜底用 score 的倒序重排生成 rank
    if df['rank'].isna().any() and 'score' in df.columns:
        df = df.sort_values('score', ascending=False)
        df['rank'] = range(1, len(df) + 1)

    # 强制 int 并升序
    df['rank'] = df['rank'].astype(int)
    df = df.sort_values('rank', ascending=True, kind='mergesort').reset_index(drop=True)
    return df

class RunStrategyWorker(QThread):
    # 事件信号
    progress = Signal(int)
    log = Signal(str)
    stage = Signal(str, int)
    artifacts = Signal(dict)
    done = Signal(dict)
    failed = Signal(str)

    # -----------------------------
    # 生命周期
    # -----------------------------
    def __init__(self, params: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.params = params or {}
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_id = f"run_{ts}_{hashlib.md5(json.dumps(self.params, sort_keys=True).encode()).hexdigest()[:8]}"
        self.project_root = self._guess_project_root()
        self.art_dir = os.path.join(self.project_root, "gui", "artifacts", self.run_id)
        os.makedirs(self.art_dir, exist_ok=True)
        self._stop = False

    def stop(self):
        self._stop = True

    # -----------------------------
    # 线程入口
    # -----------------------------
    def run(self):
        try:
            self._emit_stage("prepare", 5, "[STEP 0] 初始化任务")
            self._apply_env()

            # 在调用主流程前，检查基金池 CSV 的真实行数与样例
            csv_path = os.getenv("FUND_UNIVERSE_CSV", "")
            try:
                dfu = pd.read_csv(csv_path, dtype={"fund_code": str})
                dfu["fund_code"] = dfu["fund_code"].astype(str).str.zfill(6)
                self.log.emit(f"[CHECK] 基金池CSV实际行数={len(dfu)}，样例={dfu['fund_code'].head(5).tolist()}")
            except Exception as e:
                self.log.emit(f"[CHECK][WARN] 无法读取基金池CSV：{csv_path} -> {e}")

            # 调用真实管线
            self._emit_stage("pipeline", 25, "[STEP 1] 调用 run_daily_fund.main()（零参数，按环境变量运行）")
            self._call_run_daily()
            if self._stop:
                return

            # 回测
            self._emit_stage("backtest", 70, "[STEP 2] 回测并生成收益曲线")
            eq_csv, eq_png = self._gen_equity_curve()

            # 导出权重与交易diff
            self._emit_stage("harvest", 85, "[STEP 3] 导出权重与交易清单（换仓差异）")
            weights_csv, trades_csv = self._export_weights_and_trades()

            # 汇总产物
            payload = {
                "run_id": self.run_id,
                "equity_curve_csv": eq_csv,
                "equity_curve_png": eq_png,
                "weights_csv": weights_csv,
                "trades_csv": trades_csv,
                "params_json": self._dump_params_json(),
            }
            self.artifacts.emit(payload)

            # 计算指标
            metrics = self._metrics_from_equity(eq_csv)

            self._emit_stage("done", 100, "[DONE] 任务完成")
            self.done.emit({"run_id": self.run_id, **metrics})

        except Exception as e:
            self.failed.emit(str(e))

    # -----------------------------
    # 环境变量
    # -----------------------------
    def _apply_env(self):
        """把 GUI 参数打到 ENV，后续管线统一按 ENV 读取。"""
        def ap(p):
            return os.path.abspath(os.path.join(self.project_root, p)) if p and not os.path.isabs(p) else p

        p = self.params
        env = {
            "FUND_SINCE_DATE":     p.get("since", "2022-01-01"),
            "FUND_UNIVERSE_CSV":   ap(p.get("universe_csv", "data/universe_fund.csv")),
            "PARALLEL_WORKERS":    str(p.get("workers", max(8, os.cpu_count() or 8))),
            "FUND_TOP_N_FUNDS":    str(p.get("top_n", 3)),
            "FUND_WINDOW_DAYS":    str(p.get("window_days", 252)),
            "FUND_UNIVERSE_LIMIT": str(p.get("universe_limit", 10)),
            "FUND_WEIGHT_SCHEME":  p.get("weight_scheme", "weight_mixed"),
            "FUND_DB_PATH":        ap(os.path.join("db", "fund_db.sqlite")),
            "FUND_OUTPUT_DIR":     ap("output"),
            # 方案B：历史回填天数（默认 252；你也可以从 GUI 传自定义值）
            "FUND_BACKFILL_DAYS":  str(p.get("backfill_days", 252)),
        }
        for k, v in env.items():
            os.environ[k] = str(v)
            self.log.emit(f"[ENV] {k}={v}")

    
    # -----------------------------
    # 调用主流程
    # -----------------------------

    def _call_run_daily(self):
        # 热重载，避免 IDE 反复运行时缓存旧模块
        for name in list(sys.modules.keys()):
            if name.startswith("src.") or name in ("src", "run_daily_fund"):
                sys.modules.pop(name, None)
        sys.path.insert(0, self.project_root)
        m = importlib.import_module("run_daily_fund")
        if not hasattr(m, "main"):
            raise RuntimeError("run_daily_fund.main 未找到")
        self.log.emit(">>> 执行 run_daily_fund.main()")
        m.main()  # 零参数，完全按 ENV 运行
        self.log.emit("<<< 结束 run_daily_fund.main()")

    # -----------------------------
    # 回测（返回 equity csv/png）
    # -----------------------------
    def _gen_equity_curve(self) -> Tuple[str, str]:
        # 重新导入回测模块
        for name in list(sys.modules.keys()):
            if name.startswith("src.") or name == "src":
                sys.modules.pop(name, None)
        sys.path.insert(0, self.project_root)

        weight_col = os.getenv("FUND_WEIGHT_SCHEME", "weight_mixed")
        self.log.emit(f"[BT] 使用权重列：{weight_col}")

        df_nav = None
        # 1) 优先：函数返回
        try:
            bqf = importlib.import_module("src.backtest_quick_fund")
            df_nav = bqf.backtest_from_db(weight_col=weight_col)
        except Exception as e:
            self.log.emit(f"[BT][WARN] backtest_from_db 异常：{e}")

        # 2) 若空：回读 output/backtest_fund_nav.csv
        if df_nav is None or df_nav.empty:
            out_dir = os.getenv("FUND_OUTPUT_DIR", os.path.join(self.project_root, "output"))
            out_dir = out_dir if os.path.isabs(out_dir) else os.path.join(self.project_root, out_dir)
            csv_path = os.path.join(out_dir, "backtest_fund_nav.csv")
            if os.path.exists(csv_path):
                try:
                    tmp = pd.read_csv(csv_path)
                    cols = {c.lower(): c for c in tmp.columns}
                    date_col = cols.get("date") or list(tmp.columns)[0]
                    nav_col = cols.get("nav") or list(tmp.columns)[1]
                    df_nav = tmp[[date_col, nav_col]].rename(columns={date_col: "date", nav_col: "nav"})
                    self.log.emit(f"[BT] 回读导出的曲线：{csv_path} rows={len(df_nav)}")
                except Exception as e:
                    self.log.emit(f"[BT][WARN] 读取导出曲线失败：{e}")

        # 3) 若仍空：静态持仓兜底
        if df_nav is None or df_nav.empty or (len(df_nav) < 2):
            self.log.emit("[BT][WARN] backtest_from_db 结果不足，启用“静态持仓”兜底。")
            df_nav = self._equity_from_static_weights(weight_col)
            if df_nav is None or df_nav.empty:
                raise RuntimeError("无法生成收益曲线：backtest 与兜底都为空。")

        # 统一落盘到 artifacts
        df = df_nav.copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date")
        eq_csv = os.path.join(self.art_dir, "equity_curve.csv")
        df.rename(columns={"date": "date", "nav": "equity"}).to_csv(eq_csv, index=False, encoding="utf-8-sig")

        fig = Figure(figsize=(6, 2.6), dpi=160)
        ax = fig.add_subplot(111)
        ax.plot(df["date"], df["equity"])
        ax.set_title("Equity Curve")
        ax.grid(True, alpha=0.3)
        eq_png = os.path.join(self.art_dir, "equity_curve.png")
        fig.savefig(eq_png, bbox_inches="tight")

        return eq_csv, eq_png

    # 兜底：按“最新权重 × 历史NAV”合成静态曲线
    def _equity_from_static_weights(self, weight_col: str) -> Optional[pd.DataFrame]:
        db_path = os.getenv("FUND_DB_PATH", os.path.join(self.project_root, "db", "fund_db.sqlite"))
        if not os.path.isabs(db_path):
            db_path = os.path.join(self.project_root, db_path)
        if not os.path.exists(db_path):
            self.log.emit(f"[BT][ERR] DB 不存在：{db_path}")
            return None

        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        try:
            dts = pd.read_sql_query("SELECT DISTINCT date FROM portfolio_results ORDER BY date DESC LIMIT 1", con)
            if dts.empty:
                return None
            d_last = dts["date"].iloc[0]
            w = pd.read_sql_query(
                f"SELECT fund_code, {weight_col} AS weight FROM portfolio_results WHERE date=?",
                con,
                params=[d_last],
            )
            if w.empty:
                return None

            w["weight"] = pd.to_numeric(w["weight"], errors="coerce").fillna(0.0)
            w = w.loc[w["weight"] != 0.0].set_index("fund_code")["weight"]

            nav = pd.read_sql_query("SELECT fund_code AS code, date, nav FROM fund_nav_daily", con)
            if nav.empty:
                return None
            nav["date"] = pd.to_datetime(nav["date"], errors="coerce")
            nav = nav.dropna(subset=["date", "nav"])
            nav["code"] = nav["code"].astype(str).str.zfill(6)
            nav = nav.loc[nav["code"].isin(w.index)]
            if nav.empty:
                return None

            nav = nav.sort_values(["code", "date"])
            nav["nav"] = pd.to_numeric(nav["nav"], errors="coerce")
            nav = nav.dropna()
            nav["norm"] = nav.groupby("code")["nav"].transform(lambda s: s / (s.iloc[0] if len(s) > 0 else 1.0))

            nav = nav.join(w.rename("weight"), on="code")
            nav["contrib"] = nav["norm"] * nav["weight"]
            df = (
                nav.groupby("date")["contrib"]
                .sum()
                .reset_index()
                .rename(columns={"contrib": "nav"})
            )
            if not df.empty:
                base = df["nav"].iloc[0]
                if base != 0:
                    df["nav"] = df["nav"] / base
            return df
        finally:
            con.close()

    # -----------------------------
    # 导出权重与交易（再平衡差异）
    # -----------------------------
    def _export_weights_and_trades(self) -> Tuple[Optional[str], Optional[str]]:
        db_path = os.getenv("FUND_DB_PATH", os.path.join(self.project_root, "db", "fund_db.sqlite"))
        if not os.path.isabs(db_path):
            db_path = os.path.join(self.project_root, db_path)
        if not os.path.exists(db_path):
            self.log.emit(f"[WARN] 数据库不存在：{db_path}")
            return None, None

        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        try:
            dates = pd.read_sql_query(
                "SELECT DISTINCT date FROM portfolio_results ORDER BY date DESC LIMIT 2", con
            )
            if dates.empty:
                return None, None
            last_date = dates["date"].iloc[0]
            prev_date = dates["date"].iloc[1] if len(dates) > 1 else None

            weight_col = os.getenv("FUND_WEIGHT_SCHEME", "weight_mixed")
            df_last = pd.read_sql_query(
                f"""
                SELECT date,fund_code,{weight_col} AS weight, score, rank
                FROM portfolio_results
                WHERE date=?
                ORDER BY weight DESC
                """,
                con,
                params=[last_date],
            )
            weights_csv = os.path.join(self.art_dir, "weights.csv")
            df_last.to_csv(weights_csv, index=False, encoding="utf-8-sig")

            trades_csv = None
            if prev_date is not None:
                df_prev = pd.read_sql_query(
                    f"SELECT fund_code,{weight_col} AS weight FROM portfolio_results WHERE date=?",
                    con,
                    params=[prev_date],
                )
                m = (
                    df_last.set_index("fund_code")["weight"]
                    .rename("w1")
                    .to_frame()
                    .join(df_prev.set_index("fund_code")["weight"].rename("w0"), how="outer")
                    .fillna(0.0)
                )
                m["delta"] = m["w1"] - m["w0"]
                m = m.loc[m["delta"].abs() > 1e-8].sort_values("delta", ascending=False)
                out = m.reset_index().rename(columns={"index": "fund_code"})
                out["date"] = last_date
                out["action"] = out["delta"].apply(lambda x: "BUY" if x > 0 else "SELL")
                trades_csv = os.path.join(self.art_dir, "trades.csv")
                out[["date", "fund_code", "action", "delta"]].to_csv(trades_csv, index=False, encoding="utf-8-sig")

            return weights_csv, trades_csv
        finally:
            con.close()

    # -----------------------------
    # 指标
    # -----------------------------
    def _metrics_from_equity(self, eq_csv: str) -> Dict[str, float]:
        try:
            df = pd.read_csv(eq_csv)
            equity = pd.to_numeric(df.iloc[:, 1], errors="coerce").dropna()
            if len(equity) < 3:
                return {"cagr": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "vol": 0.0}
            rets = equity.pct_change().dropna()
            vol = float(rets.std() * np.sqrt(252))
            sharpe = float((rets.mean() * 252) / (vol + 1e-12))
            cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (252 / len(equity)) - 1)
            mdd = float((equity / equity.cummax() - 1).min())
            return {"cagr": cagr, "sharpe": sharpe, "max_drawdown": mdd, "vol": vol}
        except Exception:
            return {"cagr": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "vol": 0.0}

    # -----------------------------
    # 工具函数
    # -----------------------------
    def _dump_params_json(self) -> str:
        path = os.path.join(self.art_dir, "params.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"run_id": self.run_id, **self.params}, f, ensure_ascii=False, indent=2)
        return path

    def _guess_project_root(self) -> str:
        here = os.path.abspath(os.path.dirname(__file__))
        return os.path.abspath(os.path.join(here, "..", ".."))

    def _emit_stage(self, name: str, pct: int, msg: str):
        try:
            self.stage.emit(name, int(pct))
            self.progress.emit(int(pct))
            self.log.emit(msg)
        except Exception:
            pass
