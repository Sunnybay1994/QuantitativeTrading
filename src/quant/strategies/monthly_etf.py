"""Fixed monthly SMA timing and skip-month relative momentum for ETF research."""

import datetime as dt
from dataclasses import dataclass
from typing import Literal

import polars as pl

from quant.strategies.base import Strategy


@dataclass(frozen=True)
class MonthlyEtfStrategy(Strategy):
    """Consume completed month-end total-return prices, without doing IO."""

    candidates: tuple[str, ...]
    kind: Literal["sma", "relative_momentum"]
    lookback_months: int
    skip_months: int = 0
    top_k: int = 3
    name: str = "monthly_etf"
    version: str = "v1"

    def __post_init__(self) -> None:
        if not self.candidates or len(set(self.candidates)) != len(self.candidates):
            raise ValueError("Monthly strategy needs distinct candidates")
        if self.lookback_months < 2 or not 0 <= self.skip_months < self.lookback_months:
            raise ValueError("Invalid monthly lookback or skip")
        if self.kind not in {"sma", "relative_momentum"} or not 1 <= self.top_k <= len(self.candidates):
            raise ValueError("Invalid monthly strategy or selection count")
        if self.kind == "sma" and self.skip_months:
            raise ValueError("SMA uses the current completed month")

    def target_weights(self, as_of: dt.date, data: pl.DataFrame) -> pl.DataFrame:
        """Each SMA sleeve keeps its fixed pool weight or cash; momentum takes Top-K."""
        available = data.filter(pl.col("trade_date") <= as_of).sort("trade_date", "symbol")
        needed = self.lookback_months if self.kind == "sma" else self.lookback_months + 1
        last_date = available["trade_date"].max()
        scores = {}
        for symbol in self.candidates:
            frame = available.filter(pl.col("symbol") == symbol).tail(needed)
            months = [d.year * 12 + d.month for d in frame["trade_date"]]
            if (frame.height != needed or frame["trade_date"].max() != last_date
                or any(b - a != 1 for a, b in zip(months, months[1:]))):
                raise ValueError(f"Incomplete monthly price history: {symbol} {as_of}")
            values = frame["adjusted_close"]
            if values.null_count() or not values.is_finite().all() or (values <= 0).any():
                raise ValueError("Monthly prices must be positive and finite")
            if self.kind == "sma":
                scores[symbol] = float(values[-1] / values.mean() - 1)
            else:
                scores[symbol] = float(values[-1 - self.skip_months] / values[0] - 1)
        if self.kind == "sma":
            weights = {s: 1 / len(self.candidates) if scores[s] > 0 else 0. for s in self.candidates}
        else:
            selected = sorted(scores, key=lambda s: (-scores[s], s))[:self.top_k]
            weights = {s: 1 / self.top_k if s in selected else 0. for s in self.candidates}
        return pl.DataFrame({"as_of": [as_of] * len(weights), "strategy": [self.name] * len(weights),
            "strategy_version": [self.version] * len(weights), "symbol": list(weights), "weight": list(weights.values())})
