"""Fixed five-session cross-sectional ETF reversal, with no data IO."""

import datetime as dt
from dataclasses import dataclass

import polars as pl

from quant.strategies.base import Strategy


@dataclass(frozen=True)
class WeeklyEtfReversalStrategy(Strategy):
    candidates: tuple[str, ...]
    lookback_sessions: int = 5
    top_k: int = 3
    name: str = "weekly_etf_reversal"
    version: str = "v1"

    def __post_init__(self) -> None:
        if (not self.candidates or len(set(self.candidates)) != len(self.candidates)
            or type(self.lookback_sessions) is not int or self.lookback_sessions < 1
            or type(self.top_k) is not int or not 1 <= self.top_k <= len(self.candidates)):
            raise ValueError("Invalid weekly reversal configuration")

    def target_weights(self, as_of: dt.date, data: pl.DataFrame) -> pl.DataFrame:
        available = data.filter(pl.col("symbol").is_in(self.candidates) & (pl.col("trade_date") <= as_of))
        dates = sorted(available["trade_date"].unique().to_list())[-self.lookback_sessions - 1:]
        if len(dates) != self.lookback_sessions + 1 or dates[-1] != as_of:
            raise ValueError("Incomplete weekly price history")
        scores = {}
        for symbol in self.candidates:
            frame = available.filter((pl.col("symbol") == symbol) & pl.col("trade_date").is_in(dates)).sort("trade_date")
            if frame["trade_date"].to_list() != dates:
                raise ValueError(f"Incomplete or duplicate weekly prices: {symbol}")
            values = frame["adjusted_close"]
            if values.null_count() or not values.is_finite().all() or (values <= 0).any():
                raise ValueError("Weekly prices must be positive and finite")
            scores[symbol] = float(values[-1] / values[0] - 1)
        selected = sorted(scores, key=lambda symbol: (scores[symbol], symbol))[:self.top_k]
        return pl.DataFrame({"as_of": [as_of] * len(self.candidates), "symbol": self.candidates,
            "strategy": [self.name] * len(self.candidates), "strategy_version": [self.version] * len(self.candidates),
            "weight": [1 / self.top_k if s in selected else 0. for s in self.candidates]})
