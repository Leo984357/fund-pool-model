from __future__ import annotations
from pathlib import Path

from .._config import Config
from .._types import PipelineResult
from ..common.utils import today_ymd, log
from ..data.repository import Repository
from ..data.fetcher import Fetcher
from ..data.pool import UniversePool
from ..domain.factors import compute_factors, adapt_factor_columns
from ..domain.scoring import score_funds
from ..domain.optimizer import build_portfolio
from ..domain.risk import check_risk
from ..reporting.report import generate_report


def run_daily(config: Config) -> PipelineResult:
    config.validate()
    run_date = today_ymd()
    log(f"=== Daily Pipeline: {run_date} ===")
    print(config.summary())

    repo = Repository(config)
    fetcher = Fetcher(config, repo)
    pool = UniversePool(config)

    log("[STEP 1] Loading universe...")
    universe = pool.load()
    log(f"  -> {len(universe)} funds")

    log("[STEP 2] Fetching NAV data...")
    fetcher.fetch_and_save_batch(universe, since=config.since_date, max_workers=config.parallel_workers)

    log("[STEP 3] Reading NAV from DB...")
    df_nav = repo.load_nav(universe, since=config.since_date)
    df_ret = repo.to_returns(df_nav)
    bench = repo.make_equal_benchmark(df_ret)

    log("[STEP 4] Computing factors...")
    df_factors = compute_factors(df_ret, bench=bench, window=config.window_days)
    df_factors = adapt_factor_columns(df_factors)

    log("[STEP 5] Scoring...")
    df_scores = score_funds(df_factors, factor_weights=config.factor_weights, pure_sharpe_only=config.pure_sharpe_only)
    score_path = None
    if df_scores is not None and not df_scores.empty:
        score_path = Path(config.output_dir) / f"scores_{run_date}.csv"
        df_scores.to_csv(score_path, index=False, encoding="utf-8")
        log(f"  scores saved: {score_path}")

    log("[STEP 6] Risk checks...")
    risk_warnings = check_risk(df_scores)
    for w in risk_warnings:
        log(f"  [RISK] {w}")

    log("[STEP 7] Building portfolio...")
    df_portfolio = build_portfolio(df_scores, df_ret, run_date,
                                   top_n=config.top_n_funds,
                                   window_days=config.window_days)
    portfolio_path = None
    if df_portfolio is not None and not df_portfolio.empty:
        repo.upsert_portfolio(df_portfolio)
        portfolio_path = Path(config.output_dir) / f"portfolio_fund_{run_date}.csv"
        df_portfolio.to_csv(portfolio_path, index=False, encoding="utf-8")
        log(f"  portfolio saved: {portfolio_path}")

    log("[STEP 8] Generating report...")
    report_path = Path(config.output_dir) / "report.html"
    generate_report(run_date, df_scores, df_portfolio, None, Path(config.output_dir))

    log("=== Pipeline complete ===")
    return PipelineResult(
        run_date=run_date,
        universe=universe,
        df_nav=df_nav,
        df_ret=df_ret,
        df_factors=df_factors,
        df_scores=df_scores,
        df_portfolio=df_portfolio,
        risk_warnings=risk_warnings,
        score_path=score_path,
        portfolio_path=portfolio_path,
        report_path=report_path,
    )
