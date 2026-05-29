from __future__ import annotations
from .._config import Config
from ..common.utils import log
from ..data.repository import Repository
from ..data.fetcher import Fetcher
from ..data.pool import UniversePool


def run_incremental(config: Config, lookback_days: int = 5):
    config.validate()
    repo = Repository(config)
    fetcher = Fetcher(config, repo)
    pool = UniversePool(config)

    universe = pool.load()
    log(f"[INCREMENTAL] universe: {len(universe)} funds")

    rows = fetcher.fetch_incremental(universe, fallback_since=config.since_date, lookback_days=lookback_days)
    log(f"[INCREMENTAL] done, {rows} rows written")
    return rows
