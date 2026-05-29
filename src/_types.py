from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import pandas as pd


@dataclass
class PipelineResult:
    run_date: str
    universe: list[str]
    df_nav: pd.DataFrame
    df_ret: pd.DataFrame
    df_factors: pd.DataFrame
    df_scores: pd.DataFrame
    df_portfolio: pd.DataFrame
    risk_warnings: list[str]
    score_path: Path | None = None
    portfolio_path: Path | None = None
    report_path: Path | None = None
