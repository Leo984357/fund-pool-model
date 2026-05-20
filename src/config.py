# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Any

# -----------------------------
# 路径根：src/ 的上一级
# -----------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 小工具
def _getenv_int(key: str, default: int) -> int:
    v = os.getenv(key, None)
    if v is None or str(v).strip() == "":
        return int(default)
    try:
        return int(v)
    except Exception:
        raise ValueError(f"ENV {key} 应为整数，当前值={v!r}")

def _getenv_float(key: str, default: float) -> float:
    v = os.getenv(key, None)
    if v is None or str(v).strip() == "":
        return float(default)
    try:
        return float(v)
    except Exception:
        raise ValueError(f"ENV {key} 应为浮点数，当前值={v!r}")

def _getenv_bool(key: str, default: bool) -> bool:
    v = os.getenv(key, None)
    if v is None or str(v).strip() == "":
        return bool(int(default))
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    # 兼容旧逻辑：用 0/1
    try:
        return bool(int(s))
    except Exception:
        raise ValueError(f"ENV {key} 应为布尔(0/1/true/false)，当前值={v!r}")

def _getenv_str(key: str, default: str) -> str:
    v = os.getenv(key, None)
    return default if v is None or str(v).strip() == "" else str(v)

# -------------------------------------------------
# 配置数据结构（保持对外变量名不变，同时提供对象化访问）
# -------------------------------------------------
@dataclass
class _Config:
    # 目录与路径（可被环境变量覆盖）
    DATA_DIR: Path = field(default_factory=lambda: Path(_getenv_str("FUND_DATA_DIR", str(PROJECT_ROOT / "data"))))
    DB_PATH: Path = field(default_factory=lambda: Path(_getenv_str("FUND_DB_PATH", str(PROJECT_ROOT / "db" / "fund_db.sqlite"))))
    OUTPUT_DIR: Path = field(default_factory=lambda: Path(_getenv_str("FUND_OUTPUT_DIR", str(PROJECT_ROOT / "output"))))
    UNIVERSE_CSV: str = _getenv_str("FUND_UNIVERSE_CSV", str(Path(_getenv_str("FUND_DATA_DIR", str(PROJECT_ROOT / "data"))) / "universe_fund.csv"))

    # 业务参数（既能 GUI 传入也能环境变量覆盖）
    UNIVERSE_LIMIT: int = _getenv_int("FUND_UNIVERSE_LIMIT", int(os.getenv("UNIVERSE_LIMIT", 100)))
    TOP_N_FUNDS: int = _getenv_int("FUND_TOP_N_FUNDS", int(os.getenv("FUND_TOP_N_FUNDS", 3)))
    WINDOW_DAYS: int = _getenv_int("FUND_WINDOW_DAYS", int(os.getenv("FUND_WINDOW_DAYS", 252)))
    SINCE_DATE: str = _getenv_str("FUND_SINCE_DATE", os.getenv("FUND_SINCE_DATE", "2022-01-01"))
    MIN_HISTORY_DAYS: int = _getenv_int("FUND_MIN_HISTORY_DAYS", int(os.getenv("FUND_MIN_HISTORY_DAYS", 60)))
    PURE_SHARPE_ONLY: bool = _getenv_bool("FUND_PURE_SHARPE_ONLY", bool(int(os.getenv("FUND_PURE_SHARPE_ONLY", "0"))))

    # 运行参数（补充完整性；保持默认不影响旧代码）
    PARALLEL_WORKERS: int = _getenv_int("PARALLEL_WORKERS", int(os.getenv("PARALLEL_WORKERS", 10)))
    WEIGHT_SCHEME: str = _getenv_str("FUND_WEIGHT_SCHEME", os.getenv("FUND_WEIGHT_SCHEME", "weight_risk_parity")).strip()

    # 表名（让 backtest/dao 更稳健）
    NAV_TABLE: str = _getenv_str("FUND_NAV_TABLE", "fund_nav_daily")
    PORTFOLIO_TABLE: str = _getenv_str("FUND_PORTFOLIO_TABLE", "portfolio_results")

    # 因子权重（与你的原始默认一致；允许通过 ENV 单独覆盖每个 key）
    FACTOR_WEIGHTS: Dict[str, float] = field(default_factory=lambda: {
        "ann_return": _getenv_float("FACTOR_ann_return", 0.35),
        "ann_vol":    _getenv_float("FACTOR_ann_vol",   -0.15),
        "down_vol":   _getenv_float("FACTOR_down_vol",  -0.10),
        "mdd":        _getenv_float("FACTOR_mdd",       -0.10),
        "sharpe":     _getenv_float("FACTOR_sharpe",     0.35),
        "ir":         _getenv_float("FACTOR_ir",         0.15),
    })

    # ---------- 校验 ----------
    def validate(self) -> None:
        # 目录存在性（不存在则创建）
        for p in [self.DATA_DIR, self.OUTPUT_DIR, self.DB_PATH.parent]:
            Path(p).mkdir(parents=True, exist_ok=True)

        if self.TOP_N_FUNDS <= 0:
            raise ValueError("TOP_N_FUNDS 必须 > 0")
        if self.UNIVERSE_LIMIT <= 0:
            raise ValueError("UNIVERSE_LIMIT 必须 > 0")
        if self.WINDOW_DAYS <= 0:
            raise ValueError("WINDOW_DAYS 必须 > 0")
        if self.MIN_HISTORY_DAYS < 1:
            raise ValueError("MIN_HISTORY_DAYS 必须 >= 1")
        if self.PARALLEL_WORKERS <= 0:
            raise ValueError("PARALLEL_WORKERS 必须 > 0")
        if not self.WEIGHT_SCHEME:
            raise ValueError("WEIGHT_SCHEME 不可为空（例：'weight_risk_parity'/'weight_equal'/'weight_mixed'）")

    # ---------- 供 GUI 使用：以字典更新 ----------
    def update_from_gui(self, kv: Dict[str, Any]) -> None:
        """
        GUI 将参数以字典传进来（字符串/数字都行），这里统一落地并校验。
        仅更新存在的字段；未知键将被忽略（保证向后兼容）。
        """
        for k, v in (kv or {}).items():
            if not hasattr(self, k):
                continue
            cur = getattr(self, k)
            # 做轻量的类型吸收
            try:
                if isinstance(cur, bool):
                    v = bool(int(v)) if isinstance(v, str) else bool(v)
                elif isinstance(cur, int):
                    v = int(v)
                elif isinstance(cur, float):
                    v = float(v)
                elif isinstance(cur, Path):
                    v = Path(str(v))
                elif isinstance(cur, dict) and isinstance(v, dict):
                    cur.update(v)  # 合并因子权重
                    v = cur
                else:
                    v = type(cur)(v) if not isinstance(v, type(cur)) else v
            except Exception:
                # 类型不匹配时，保持原值并给出友好提示
                raise ValueError(f"GUI 传入的 {k} 值类型不匹配：当前字段类型={type(cur).__name__}, 输入={v!r}")
            setattr(self, k, v)
        self.validate()

    # ---------- 导出摘要，供日志/GUI 显示 ----------
    def summary_lines(self) -> list[str]:
        d = asdict(self)
        # 将 Path 转成 str 以便展示
        for k in ["DATA_DIR", "DB_PATH", "OUTPUT_DIR"]:
            d[k] = str(d[k])
        lines = []
        for k in [
            "SINCE_DATE", "UNIVERSE_CSV", "PARALLEL_WORKERS",
            "UNIVERSE_LIMIT", "TOP_N_FUNDS", "WINDOW_DAYS",
            "MIN_HISTORY_DAYS", "PURE_SHARPE_ONLY", "WEIGHT_SCHEME",
            "NAV_TABLE", "PORTFOLIO_TABLE",
            "DATA_DIR", "DB_PATH", "OUTPUT_DIR"
        ]:
            lines.append(f"[ENV] {k}={d[k]}")
        return lines

# -------------------------------------------------
# 单例配置：对外暴露原有“模块级变量”，保证旧代码不改也能用
# -------------------------------------------------
C = _Config()
C.validate()

# === 保持对外兼容的“旧变量名” ===
DATA_DIR = C.DATA_DIR
DB_PATH = C.DB_PATH
OUTPUT_DIR = C.OUTPUT_DIR
UNIVERSE_CSV = C.UNIVERSE_CSV

UNIVERSE_LIMIT = C.UNIVERSE_LIMIT
TOP_N_FUNDS = C.TOP_N_FUNDS
WINDOW_DAYS = C.WINDOW_DAYS
SINCE_DATE = C.SINCE_DATE
MIN_HISTORY_DAYS = C.MIN_HISTORY_DAYS
PURE_SHARPE_ONLY = C.PURE_SHARPE_ONLY

PARALLEL_WORKERS = C.PARALLEL_WORKERS
WEIGHT_SCHEME = C.WEIGHT_SCHEME

NAV_TABLE = C.NAV_TABLE
PORTFOLIO_TABLE = C.PORTFOLIO_TABLE

FACTOR_WEIGHTS = C.FACTOR_WEIGHTS

# 便捷方法：打印/记录摘要
def print_summary() -> None:
    for ln in C.summary_lines():
        print(ln)
