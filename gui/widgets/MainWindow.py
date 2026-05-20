# -*- coding: utf-8 -*-
"""
MainWindow.py — GUI（加入 Top-N / window_days / universe_limit / weight_scheme）
"""
from gui.widgets.RunTable import df_fix_topn, set_table_from_df

import sys
import os
import ast
import pandas as pd
import numpy as np
from gui.utils_format import normalize_topn_for_gui
import os
from typing import Dict, Any, List
from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextEdit, QLineEdit, QSpinBox, QFileDialog, QTabWidget,
    QTableView, QMessageBox, QDoubleSpinBox, QGroupBox, QFormLayout, QCheckBox, QComboBox
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib import image as mpimg
import pandas as pd

from gui.workers.RunStrategyWorker import RunStrategyWorker
from gui.workers.UniverseWorker import UniverseWorker


class MainWindow(QMainWindow):
    def _normalize_rank_col(self, df):
        """把 rank 规范为整数，并按 rank 升序稳定排序。兼容 bytes/字符串字节表示。"""
        if 'rank' not in df.columns:
            return df

        def _to_int(v):
            # bytes / bytearray / memoryview -> 按小端无符号整型解析
            if isinstance(v, (bytes, bytearray, memoryview)):
                try:
                    return int.from_bytes(bytes(v), byteorder='little', signed=False)
                except Exception:
                    return None

            # "b'\\x03\\x00'" 这样的字符串 -> 还原成 bytes 再转 int
            if isinstance(v, str):
                s = v.strip()
                if (s.startswith("b'") and s.endswith("'")) or (s.startswith('b"') and s.endswith('"')):
                    try:
                        b = ast.literal_eval(s)  # -> bytes
                        return int.from_bytes(b, byteorder='little', signed=False)
                    except Exception:
                        pass
                # 普通字符串尝试转成数值
                try:
                    return int(float(s))
                except Exception:
                    return None

            # 其他常见数值类型
            try:
                return int(v)
            except Exception:
                try:
                    return int(float(v))
                except Exception:
                    return None

        df = df.copy()
        df['rank'] = df['rank'].map(_to_int)

        # 若仍有缺失，且有 score 列：按 score 降序生成 1..N 的 rank（兜底）
        if df['rank'].isna().any():
            if 'score' in df.columns:
                df = df.sort_values('score', ascending=False).reset_index(drop=True)
                df['rank'] = list(range(1, len(df) + 1))
            else:
                # 没有 score 的话，把缺失填很大，起码不会排到前面
                df['rank'] = df['rank'].fillna(10 ** 9)

        df['rank'] = df['rank'].astype(int)
        # 稳定排序，避免同 rank 行的其他列抖动
        df = df.sort_values('rank', ascending=True, kind='mergesort').reset_index(drop=True)
        return df

    def _update_topn_table(self, df_topn):
        """
        df_topn 是 worker 传上来的原始 DataFrame（可能是全量）。
        这里在“显示层”统一做：
          1) rank 转 int、fund_code/date 规范化；
          2) 按 rank 或 score 排序；
          3) 按 GUI 的 Top-N 控件值裁剪 head(n)；
        """
        n = int(self.spin_topn.value())  # 这里就是你界面左上的 Top-N 控件

        df_topn = normalize_topn_for_gui(df_topn)

        if "rank" in df_topn.columns and df_topn["rank"].notna().any():
            # 有 rank：按 rank 升序稳定排序
            df_topn = df_topn.sort_values(["rank", "score"], ascending=[True, False], kind="stable")
        elif "score" in df_topn.columns:
            # 没 rank：按 score 降序
            df_topn = df_topn.sort_values("score", ascending=False, kind="stable")

        df_topn = df_topn.head(n).reset_index(drop=True)

        # 然后再喂给你的表格模型（沿用你原来封装）
        # 1) 先修正/截断（确保 Top-N 生效，rank/score 数值排序）
        df_topn = df_fix_topn(df_topn, int(self.spin_topn.value()) if hasattr(self, "spin_topn") else None)

        # 2) 填表：DisplayRole 显示，UserRole 数值排序
        set_table_from_df(self.tableTopN, df_topn, numeric_cols=("rank", "score", "weight"))
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Fund Pool Model - GUI")
        self.resize(1180, 780)

        central = QWidget(self); self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # 顶部：基础参数
        row1 = QHBoxLayout()
        self.edit_since = QLineEdit("2022-01-01")
        self.edit_universe = QLineEdit("data/universe_fund.csv")
        self.btn_browse = QPushButton("浏览基金池CSV"); self.btn_browse.clicked.connect(self.on_browse_universe_csv)
        self.spin_workers = QSpinBox(); self.spin_workers.setRange(1, 64); self.spin_workers.setValue(10)
        row1.addWidget(QLabel("起始日期:")); row1.addWidget(self.edit_since)
        row1.addWidget(QLabel("基金池:")); row1.addWidget(self.edit_universe); row1.addWidget(self.btn_browse)
        row1.addWidget(QLabel("并行workers:")); row1.addWidget(self.spin_workers)
        root.addLayout(row1)

        # 顶部：策略参数（新增）
        row2 = QHBoxLayout()
        self.spin_topn = QSpinBox(); self.spin_topn.setRange(1, 50); self.spin_topn.setValue(10)
        self.spin_window = QSpinBox(); self.spin_window.setRange(30, 1260); self.spin_window.setValue(252)
        self.spin_univ_cap = QSpinBox(); self.spin_univ_cap.setRange(1, 1000); self.spin_univ_cap.setValue(100)
        self.cmb_weight = QComboBox(); self.cmb_weight.addItems(["weight_mixed","weight_risk_parity","weight_equal"])
        row2.addWidget(QLabel("Top-N:")); row2.addWidget(self.spin_topn)
        row2.addWidget(QLabel("窗口天数:")); row2.addWidget(self.spin_window)
        row2.addWidget(QLabel("基金池上限:")); row2.addWidget(self.spin_univ_cap)
        row2.addWidget(QLabel("权重方案:")); row2.addWidget(self.cmb_weight)
        root.addLayout(row2)

        # 控制按钮/进度
        ctrl = QHBoxLayout()
        self.btn_start = QPushButton("开始"); self.btn_stop = QPushButton("停止"); self.btn_stop.setEnabled(False)
        self.btn_start.clicked.connect(self.on_start); self.btn_stop.clicked.connect(self.on_stop)
        ctrl.addWidget(self.btn_start); ctrl.addWidget(self.btn_stop)
        root.addLayout(ctrl)
        self.progress = QProgressBar(); self.progress.setRange(0, 100); root.addWidget(self.progress)

        # 日志 + Tabs
        self.log = QTextEdit(); self.log.setReadOnly(True)
        self.tabs = QTabWidget(); root.addWidget(self.tabs, stretch=1)

        tab_monitor = QWidget(); v0 = QVBoxLayout(tab_monitor)
        v0.addWidget(QLabel("运行日志")); v0.addWidget(self.log, stretch=1)
        self.lbl_summary = QLabel("结果摘要：-"); v0.addWidget(self.lbl_summary)
        self.tabs.addTab(tab_monitor, "监控台")

        tab_overview = QWidget(); v1 = QVBoxLayout(tab_overview)
        self.fig = Figure(figsize=(5,3)); self.ax = self.fig.add_subplot(111); self.canvas = FigureCanvas(self.fig)
        v1.addWidget(self.canvas, stretch=1)
        self.tabs.addTab(tab_overview, "结果总览")

        tab_port = QWidget(); v2 = QVBoxLayout(tab_port)
        v2.addWidget(QLabel("当期权重（Top-N）")); self.tbl_weights = QTableView(); v2.addWidget(self.tbl_weights)
        v2.addWidget(QLabel("交易清单")); self.tbl_trades = QTableView(); v2.addWidget(self.tbl_trades, stretch=1)
        self.tabs.addTab(tab_port, "组合与交易")

        # 基金池页（保持你已有 K / lookback / 权重参数等）
        tab_univ = QWidget(); v3 = QVBoxLayout(tab_univ)
        box = QGroupBox("基金池参数"); form = QFormLayout(box)
        self.spin_pool_size = QSpinBox(); self.spin_pool_size.setRange(5, 2000); self.spin_pool_size.setValue(100)
        self.spin_lookback  = QSpinBox(); self.spin_lookback.setRange(60, 1260); self.spin_lookback.setValue(252)
        self.dsb_min_cover = QDoubleSpinBox(); self._init_dsb(self.dsb_min_cover, 0.85, 0, 1, 0.01, 2)
        self.dsb_min_aum   = QDoubleSpinBox(); self._init_dsb(self.dsb_min_aum,   5e7, 0, 1e12, 1e6, 0)
        self.dsb_max_fee   = QDoubleSpinBox(); self._init_dsb(self.dsb_max_fee,  0.015, 0, 0.1, 0.001, 3)
        self.sb_min_age_days = QSpinBox(); self.sb_min_age_days.setRange(0, 5000); self.sb_min_age_days.setValue(365)
        self.dsb_w_cover  = QDoubleSpinBox(); self._init_dsb(self.dsb_w_cover, 0.40, -5, 5, 0.05, 3)
        self.dsb_w_sgrowth= QDoubleSpinBox(); self._init_dsb(self.dsb_w_sgrowth, 0.30, -5, 5, 0.05, 3)
        self.dsb_w_fee    = QDoubleSpinBox(); self._init_dsb(self.dsb_w_fee, 0.20, -5, 5, 0.05, 3)
        self.dsb_w_repair = QDoubleSpinBox(); self._init_dsb(self.dsb_w_repair, 0.10, -5, 5, 0.05, 3)
        self.chk_eq_active = QCheckBox("主动权益"); self.chk_eq_active.setChecked(True)
        self.chk_index     = QCheckBox("被动指数"); self.chk_index.setChecked(True)
        self.chk_sector_etf= QCheckBox("行业ETF"); self.chk_sector_etf.setChecked(True)
        self.chk_bond      = QCheckBox("债券");     self.chk_bond.setChecked(True)

        form.addRow("初步大小 K：", self.spin_pool_size)
        form.addRow("回看天数 N：", self.spin_lookback)
        form.addRow("最小覆盖率：", self.dsb_min_cover)
        form.addRow("最小规模（元）：", self.dsb_min_aum)
        form.addRow("最大费率：", self.dsb_max_fee)
        form.addRow("最小存续天数：", self.sb_min_age_days)
        form.addRow(QLabel("—— 预筛权重 ——"))
        form.addRow("w_cover：",  self.dsb_w_cover); form.addRow("w_sgrowth：", self.dsb_w_sgrowth)
        form.addRow("w_fee：",    self.dsb_w_fee);   form.addRow("w_repair：", self.dsb_w_repair)
        cats_row = QHBoxLayout()
        for w in (self.chk_eq_active, self.chk_index, self.chk_sector_etf, self.chk_bond): cats_row.addWidget(w)
        wrap = QWidget(); wrap.setLayout(cats_row)
        form.addRow("基金类型：", wrap); v3.addWidget(box)
        from gui.view_from_output import hook_output_rendering
        hook_output_rendering(self)

        ops = QHBoxLayout()
        self.btn_gen_univ = QPushButton("生成基金池"); self.btn_export_univ = QPushButton("导出预览为CSV"); self.btn_export_univ.setEnabled(False)
        ops.addWidget(self.btn_gen_univ); ops.addWidget(self.btn_export_univ); v3.addLayout(ops)
        self.tbl_univ = QTableView(); v3.addWidget(self.tbl_univ, stretch=1)
        self.tabs.addTab(tab_univ, "基金池")

        tab_src = QWidget(); v4 = QVBoxLayout(tab_src)
        self.lbl_runid = QLabel("RunID: -"); self.btn_open_art = QPushButton("打开产出目录"); self.btn_open_art.clicked.connect(self.open_artifacts)
        v4.addWidget(self.lbl_runid); v4.addWidget(self.btn_open_art); v4.addStretch(1)
        self.tabs.addTab(tab_src, "溯源与导出")

        # 绑定
        self.btn_gen_univ.clicked.connect(self.on_generate_universe)
        self.btn_export_univ.clicked.connect(self.on_export_universe)

        self.worker = None; self.univ_worker = None
        self._univ_cache: List[Dict[str, Any]] = []; self._last_art_dir = None
        self.append_log("建议先在【基金池】页生成最新 universe_fund.csv，再点击【开始】。")

    # ---- utils ui ----
    def _init_dsb(self, w: QDoubleSpinBox, val, mi, ma, step, dec):
        w.setRange(mi, ma); w.setSingleStep(step); w.setDecimals(dec); w.setValue(val)
    def append_log(self, msg: str): self.log.append(msg)

    # ---- browse csv ----
    def on_browse_universe_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择基金池CSV", "data", "CSV Files (*.csv)")
        if path: self.edit_universe.setText(path)

    # ---- start/stop ----
    def on_start(self):
        if self.worker and self.worker.isRunning(): return
        params = {
            "since": self.edit_since.text().strip(),
            "universe_csv": self.edit_universe.text().strip(),
            "workers": int(self.spin_workers.value()),
            # 新增：联动到真实管线
            "top_n": int(self.spin_topn.value()),
            "window_days": int(self.spin_window.value()),
            "universe_limit": int(self.spin_univ_cap.value()),
            "weight_scheme": self.cmb_weight.currentText(),
        }
        self.worker = RunStrategyWorker(params)
        if hasattr(self.worker, "stage"):     self.worker.stage.connect(self.on_stage)
        if hasattr(self.worker, "artifacts"): self.worker.artifacts.connect(self.on_artifacts)
        if hasattr(self.worker, "done"):      self.worker.done.connect(self.on_done)
        if hasattr(self.worker, "failed"):    self.worker.failed.connect(self.on_failed)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.log.connect(self.append_log)

        self.btn_start.setEnabled(False); self.btn_stop.setEnabled(True)
        self.append_log("启动任务..."); self.worker.start()

    def on_stop(self):
        if self.worker and self.worker.isRunning():
            if hasattr(self.worker, "stop"): self.worker.stop()
            self.append_log("已发送停止信号。")
        self.btn_start.setEnabled(True); self.btn_stop.setEnabled(False)

    # ---- slots ----
    def on_stage(self, name: str, pct: int):
        self.append_log(f"[STAGE] {name} -> {pct}%"); self.progress.setValue(int(pct))

    def on_artifacts(self, d: Dict[str, Any]):
        self.lbl_runid.setText(f"RunID: {d.get('run_id','-')}")
        self._last_art_dir = os.path.join("gui","artifacts", d.get("run_id","-"))
        # 表
        self._try_load_table(d.get("weights_csv"), self.tbl_weights)
        self._try_load_table(d.get("trades_csv"), self.tbl_trades)
        # 图
        self.ax.clear(); drew = False
        eq_csv, eq_png = d.get("equity_curve_csv"), d.get("equity_curve_png")
        if eq_csv and os.path.exists(eq_csv):
            df = pd.read_csv(eq_csv)
            x = pd.to_datetime(df.iloc[:,0], errors="coerce")
            y = pd.to_numeric(df.iloc[:,1], errors="coerce")
            self.ax.plot(x, y); self.ax.set_title("Equity Curve"); self.ax.grid(True, alpha=0.3); drew=True
        if (not drew) and eq_png and os.path.exists(eq_png):
            img = mpimg.imread(eq_png); self.ax.imshow(img); self.ax.axis("off"); drew=True
        if not drew:
            self.ax.text(0.5,0.5,"没有可绘制的收益曲线",ha="center",va="center",transform=self.ax.transAxes)
        self.canvas.draw_idle()

    def on_done(self, metrics: Dict[str, Any]):
        self.btn_start.setEnabled(True); self.btn_stop.setEnabled(False)
        txt = f"结果摘要：CAGR={metrics.get('cagr',0):.2%} | Sharpe={metrics.get('sharpe',0):.2f} | MaxDD={metrics.get('max_drawdown',0):.2%} | Vol={metrics.get('vol',0):.2%}"
        self.lbl_summary.setText(txt); self.append_log(txt)

    def on_failed(self, msg: str):
        self.btn_start.setEnabled(True); self.btn_stop.setEnabled(False)
        self.append_log("[ERROR]\n"+str(msg))
        try: QMessageBox.critical(self, "运行失败", str(msg))
        except Exception: pass

    # ---- 基金池 ----
    def on_generate_universe(self):
        if self.univ_worker and self.univ_worker.isRunning(): return
        params = {
            "pool_size": self.spin_pool_size.value(),
            "lookback_days": self.spin_lookback.value(),
            "filters": {
                "min_cover": self.dsb_min_cover.value(),
                "min_aum":   self.dsb_min_aum.value(),
                "max_fee":   self.dsb_max_fee.value(),
                "min_age_days": self.sb_min_age_days.value(),
                "allow_cat": self._allowed_categories()
            },
            "score_weights": {
                "cover": self.dsb_w_cover.value(),
                "sgrowth": self.dsb_w_sgrowth.value(),
                "fee": self.dsb_w_fee.value(),
                "repair": self.dsb_w_repair.value(),
            }
        }
        output_csv = self.edit_universe.text().strip() or "data/universe_fund.csv"
        self.univ_worker = UniverseWorker(params, output_csv=output_csv)
        self.univ_worker.stage.connect(lambda n,p:(self.append_log(f"[UNIV] {n} {p}%"), self.progress.setValue(p)))
        self.univ_worker.log.connect(lambda s:self.append_log("[UNIV] "+s))
        self.univ_worker.preview.connect(self.render_universe_table)
        self.univ_worker.saved.connect(self.on_universe_saved)
        self.univ_worker.failed.connect(lambda e: QMessageBox.critical(self, "基金池失败", e))
        self.univ_worker.start()

    def render_universe_table(self, rows: List[Dict[str, Any]]):
        self._univ_cache = rows or []; self.btn_export_univ.setEnabled(bool(self._univ_cache))
        model = QStandardItemModel(self)
        if not rows: self.tbl_univ.setModel(model); return
        cols = list(rows[0].keys()); model.setHorizontalHeaderLabels(cols)
        for r in rows: model.appendRow([QStandardItem(str(r.get(c,""))) for c in cols])
        self.tbl_univ.setModel(model)

    def on_universe_saved(self, p: str):
        self.append_log(f"[UNIV] 基金池已保存：{p}"); QMessageBox.information(self, "基金池完成", f"已写入：{p}")

    def on_export_universe(self):
        if not self._univ_cache: return
        path, _ = QFileDialog.getSaveFileName(self, "导出基金池预览为CSV", "universe_preview.csv", "CSV Files (*.csv)")
        if not path: return
        pd.DataFrame(self._univ_cache).to_csv(path, index=False, encoding="utf-8-sig")
        QMessageBox.information(self, "已导出", f"已导出到：{path}")

    def open_artifacts(self):
        if not self._last_art_dir:
            QMessageBox.information(self,"提示","当前没有产出目录"); return
        d = self._last_art_dir if os.path.isabs(self._last_art_dir) else os.path.join(os.getcwd(), self._last_art_dir)
        if not os.path.isdir(d):
            QMessageBox.information(self,"提示","目录不存在"); return
        if sys.platform.startswith("win"): os.startfile(d)
        elif sys.platform == "darwin": os.system(f'open "{d}"')
        else: os.system(f'xdg-open "{d}"')

    # helpers
    def _normalize_rank_col(self, df: pd.DataFrame) -> pd.DataFrame:
        """将 rank 列规范为 int，并按 rank 升序稳定排序。
           同时兼容 bytes / 字符串字节表现形式 b'\\x03\\x00' 等。
        """
        if 'rank' not in df.columns:
            return df

        def _to_int(v):
            # 1) bytes / bytearray / memoryview → int（按小端无符号解释）
            if isinstance(v, (bytes, bytearray, memoryview)):
                try:
                    return int.from_bytes(bytes(v), byteorder='little', signed=False)
                except Exception:
                    return None

            # 2) 字符串形如 "b'\\x03\\x00'" → 先还原成 bytes 再转 int
            if isinstance(v, str):
                s = v.strip()
                # 可能是 "b'\\x03\\x00'" 或 "b\"\\x03\\x00\""
                if (s.startswith("b'") and s.endswith("'")) or (s.startswith('b"') and s.endswith('"')):
                    try:
                        b = ast.literal_eval(s)  # -> bytes
                        return int.from_bytes(b, byteorder='little', signed=False)
                    except Exception:
                        pass
                # 其它字符串尝试走数值解析
                try:
                    return int(float(s))
                except Exception:
                    return None

            # 3) 常规可转数值类型
            try:
                return int(v)
            except Exception:
                try:
                    return int(float(v))
                except Exception:
                    return None

        df = df.copy()
        df['rank'] = df['rank'].map(_to_int)

        # 若仍有缺失，回退方案：若存在 score 列，则按 score 降序重排并生成 1..N 的 rank
        if df['rank'].isna().any():
            if 'score' in df.columns:
                df = df.sort_values('score', ascending=False).reset_index(drop=True)
                df['rank'] = np.arange(1, len(df) + 1, dtype=int)
            else:
                # 无 score 就把缺失填到很大数，避免跑到前面
                df['rank'] = df['rank'].fillna(10 ** 9)

        df['rank'] = df['rank'].astype(int)
        # 稳定排序，防止同 rank 的其它列抖动
        df = df.sort_values('rank', ascending=True, kind='mergesort').reset_index(drop=True)
        return df

    def _init_table(self, df: pd.DataFrame, view):
        """
        把 pandas.DataFrame 填充到 QTableView。
        额外处理：若存在 rank 列，先做规范化并按 rank 升序稳定排序。
        """
        if df is None:
            return

        # ------- 兼容 rank 列的 bytes/字符串字节表示，并按 rank 升序 -------
        if 'rank' in df.columns:
            def _to_int(v):
                # bytes / bytearray / memoryview -> 小端无符号整形
                if isinstance(v, (bytes, bytearray, memoryview)):
                    try:
                        return int.from_bytes(bytes(v), byteorder='little', signed=False)
                    except Exception:
                        return None
                # 形如 "b'\\x06\\x00'" 的字符串
                if isinstance(v, str):
                    s = v.strip()
                    if (s.startswith("b'") and s.endswith("'")) or (s.startswith('b"') and s.endswith('"')):
                        try:
                            b = ast.literal_eval(s)  # -> bytes
                            return int.from_bytes(b, byteorder='little', signed=False)
                        except Exception:
                            pass
                    try:
                        return int(float(s))
                    except Exception:
                        return None
                # 其他数值类型
                try:
                    return int(v)
                except Exception:
                    try:
                        return int(float(v))
                    except Exception:
                        return None

            df = df.copy()
            df['rank'] = df['rank'].map(_to_int)

            # 若仍有缺失，且存在 score，则按 score 降序赋 1..N 做兜底
            if df['rank'].isna().any():
                if 'score' in df.columns:
                    df = df.sort_values('score', ascending=False).reset_index(drop=True)
                    df['rank'] = list(range(1, len(df) + 1))
                else:
                    df['rank'] = df['rank'].fillna(10 ** 9)

            df['rank'] = df['rank'].astype(int)
            # 稳定排序，避免相同 rank 的行乱序
            df = df.sort_values('rank', ascending=True, kind='mergesort').reset_index(drop=True)
        # ------------------------------------------------------------------

        # ------- DataFrame -> QStandardItemModel -------
        model = QStandardItemModel()
        cols = [str(c) for c in df.columns]
        model.setColumnCount(len(cols))
        model.setHorizontalHeaderLabels(cols)

        for r in range(len(df)):
            row_items = []
            for c, col in enumerate(df.columns):
                val = df.iat[r, c]
                if pd.isna(val):
                    text = ""
                elif isinstance(val, float):
                    text = f"{val:.9g}"  # 紧凑显示
                else:
                    text = str(val)
                it = QStandardItem(text)
                it.setEditable(False)
                if isinstance(val, (int, float)) and not pd.isna(val):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    it.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                row_items.append(it)
            model.appendRow(row_items)

        view.setModel(model)
        view.setSortingEnabled(True)
        try:
            view.resizeColumnsToContents()
            view.horizontalHeader().setStretchLastSection(True)
        except Exception:
            pass

    def _try_load_table(self, csv_path: str | None, view):
        if not csv_path:
            return
        try:
            if not os.path.exists(csv_path):
                self.append_log(f"[WARN] 文件不存在：{csv_path}")
                return
            # 保留 rank 为 object，避免 pandas 先行强制转换
            try:
                df = pd.read_csv(csv_path, dtype={'rank': 'object'})
            except UnicodeDecodeError:
                df = pd.read_csv(csv_path, dtype={'rank': 'object'}, encoding='gbk')

            self._init_table(df, view)
            self.append_log(f"[INFO] 加载表格成功：{csv_path}（{len(df)} 行）")
        except Exception as e:
            self.append_log(f"[WARN] 加载表格失败：{csv_path} -> {e}")

    def _allowed_categories(self) -> List[str]:
        L=[];
        if self.chk_eq_active.isChecked(): L.append("主动权益")
        if self.chk_index.isChecked():     L.append("被动指数")
        if self.chk_sector_etf.isChecked():L.append("行业ETF")
        if self.chk_bond.isChecked():      L.append("债券")
        return L
