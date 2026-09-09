"""Fixed inverse-volatility allocation from daily total-return prices."""

import datetime as dt
import math
from dataclasses import dataclass

import polars as pl

from quant.strategies.base import Strategy


@dataclass(frozen=True)
class InverseVolatilityStrategy(Strategy):
    candidates: tuple[str, ...]
    lookback_sessions: int = 60
    name: str = "inverse_volatility"
    version: str = "v1"

    def __post_init__(self) -> None:
        if (not self.candidates or len(set(self.candidates)) != len(self.candidates)
            or self.lookback_sessions < 2):
            raise ValueError("Invalid inverse-volatility configuration")

    def target_weights(self, as_of: dt.date, data: pl.DataFrame) -> pl.DataFrame:
        available = data.filter(pl.col("trade_date") <= as_of).sort("trade_date", "symbol")
        dates = available["trade_date"].unique().sort().tail(self.lookback_sessions + 1).to_list()
        inverse = {}
        for symbol in self.candidates:
            frame = available.filter(pl.col("symbol") == symbol).tail(self.lookback_sessions + 1)
            if len(dates) != self.lookback_sessions + 1 or frame["trade_date"].to_list() != dates:
                raise ValueError(f"Incomplete volatility history: {symbol}")
            prices = frame["adjusted_close"]
            if prices.null_count() or not prices.is_finite().all() or (prices <= 0).any():
                raise ValueError("Invalid volatility input prices")
            sigma = prices.pct_change().drop_nulls().std(ddof=1)
            if not isinstance(sigma, float) or not math.isfinite(sigma) or sigma <= 0:
                raise ValueError(f"Zero or unavailable volatility: {symbol}")
            inverse[symbol] = 1 / sigma
        total = sum(inverse.values())
        return pl.DataFrame({"as_of": [as_of] * len(inverse), "strategy": [self.name] * len(inverse),
            "strategy_version": [self.version] * len(inverse), "symbol": list(inverse),
            "weight": [value / total for value in inverse.values()]})
