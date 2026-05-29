#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src._config import Config
from src.pipeline.daily import run_daily


def main():
    config = Config()
    result = run_daily(config)

    print(f"\nPipeline result: {result.run_date}")
    print(f"  universe: {len(result.universe)} funds")
    print(f"  scores:   {len(result.df_scores) if result.df_scores is not None else 0}")
    print(f"  portfolio: {len(result.df_portfolio) if result.df_portfolio is not None else 0}")
    print(f"  risks:    {result.risk_warnings or 'none'}")
    if result.score_path:
        print(f"  score_path: {result.score_path}")
    if result.portfolio_path:
        print(f"  portfolio_path: {result.portfolio_path}")
    if result.report_path:
        print(f"  report_path: {result.report_path}")


if __name__ == "__main__":
    main()
