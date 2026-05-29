class FundPoolError(Exception):
    """Base exception for fund-pool-model."""


class ConfigError(FundPoolError):
    """Configuration validation error."""


class DataError(FundPoolError):
    """Data access or integrity error."""


class UniverseError(FundPoolError):
    """Fund universe loading error."""


class FetchError(FundPoolError):
    """External data fetch error."""


class BacktestError(FundPoolError):
    """Backtesting error."""
