from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from ._exceptions import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _env_str(key: str, default: str) -> str:
    v = os.getenv(key)
    return default if v is None or v.strip() == "" else v.strip()


def _env_int(key: str, default: int) -> int:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    try:
        return int(v)
    except ValueError:
        raise ConfigError(f"ENV {key} must be an integer, got {v!r}")


def _env_float(key: str, default: float) -> float:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    try:
        return float(v)
    except ValueError:
        raise ConfigError(f"ENV {key} must be a float, got {v!r}")


def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


_DEFAULT_FACTOR_WEIGHTS: Dict[str, float] = {
    "ann_return": 0.35, "ann_vol": -0.15, "down_vol": -0.10,
    "mdd": -0.10, "sharpe": 0.35, "ir": 0.15,
}


@dataclass
class Config:
    # Paths
    data_dir: Path = Path(_env_str("FUND_DATA_DIR", str(PROJECT_ROOT / "data")))
    db_path: Path = Path(_env_str("FUND_DB_PATH", str(PROJECT_ROOT / "db" / "fund_db.sqlite")))
    output_dir: Path = Path(_env_str("FUND_OUTPUT_DIR", str(PROJECT_ROOT / "output")))
    universe_csv: str = ""

    def __post_init__(self):
        if not self.universe_csv:
            self.universe_csv = str(self.data_dir / "universe_fund.csv")

    # Business parameters
    universe_limit: int = _env_int("FUND_UNIVERSE_LIMIT", 100)
    top_n_funds: int = _env_int("FUND_TOP_N_FUNDS", 3)
    window_days: int = _env_int("FUND_WINDOW_DAYS", 252)
    since_date: str = _env_str("FUND_SINCE_DATE", "2022-01-01")
    min_history_days: int = _env_int("FUND_MIN_HISTORY_DAYS", 60)
    pure_sharpe_only: bool = _env_bool("FUND_PURE_SHARPE_ONLY", False)

    # Runtime
    parallel_workers: int = _env_int("PARALLEL_WORKERS", 10)
    weight_scheme: str = _env_str("FUND_WEIGHT_SCHEME", "weight_risk_parity")

    # Table names
    nav_table: str = _env_str("FUND_NAV_TABLE", "fund_nav_daily")
    portfolio_table: str = _env_str("FUND_PORTFOLIO_TABLE", "portfolio_results")

    # Factor weights
    factor_weights: Dict[str, float] = field(default_factory=lambda: {
        k: _env_float(f"FW_{k}", v) for k, v in _DEFAULT_FACTOR_WEIGHTS.items()
    })

    def validate(self):
        if not self.db_path.parent.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def summary(self) -> str:
        lines = [
            f"Config:",
            f"  db={self.db_path}",
            f"  output={self.output_dir}",
            f"  universe_limit={self.universe_limit}",
            f"  since={self.since_date}",
            f"  window={self.window_days}d",
            f"  top_n={self.top_n_funds}",
            f"  weight={self.weight_scheme}",
            f"  workers={self.parallel_workers}",
        ]
        return "\n".join(lines)
