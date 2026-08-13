"""M2 买入持有/等权与 ETF 趋势轮动基线策略。"""

import datetime as dt
import math
from dataclasses import dataclass

import polars as pl

from quant.domain import FactorValueSchema, TargetWeightSchema
from quant.strategies.base import Strategy


@dataclass(frozen=True)
class EqualWeightStrategy(Strategy):
    """对冻结候选池输出等权目标；调仓频率由上游日程决定。"""

    candidates: tuple[str, ...]
    cash_buffer: float = 0.0
    name: str = "equal_weight"
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        _validate_parameters(self.candidates, self.cash_buffer)

    def target_weights(self, as_of: dt.date, data: pl.DataFrame) -> pl.DataFrame:
        """只选择 data 中当日 eligible 的冻结候选证券。"""
        if "symbol" not in data.columns:
            raise ValueError("等权策略输入必须包含 symbol")
        available = data
        if "eligible" in available.columns:
            available = available.filter(pl.col("eligible"))
        available_symbols = set(available.get_column("symbol").to_list())
        selected = [symbol for symbol in self.candidates if symbol in available_symbols]
        return _weights_frame(
            as_of=as_of,
            strategy=self.name,
            version=self.version,
            symbols=selected,
            invested_weight=1.0 - self.cash_buffer,
            zero_symbols=list(self.candidates),
        )


@dataclass(frozen=True)
class EtfTrendStrategy(Strategy):
    """正动量/正趋势过滤后，选择趋势分数最高的冻结 ETF。"""

    candidates: tuple[str, ...]
    top_k: int = 1
    cash_buffer: float = 0.0
    factor_version: str = "trend_v1"
    momentum_windows: tuple[int, ...] = (20, 60, 120)
    regression_window: int = 60
    name: str = "etf_trend"
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        _validate_parameters(self.candidates, self.cash_buffer)
        if self.top_k <= 0:
            raise ValueError("top_k 必须大于 0")

    def target_weights(self, as_of: dt.date, data: pl.DataFrame) -> pl.DataFrame:
        """消费长表 FactorValueSchema，绝对趋势不通过时保留现金。"""
        by_symbol = _factor_values(
            data, as_of=as_of, factor_version=self.factor_version
        )
        ranked = _rank_positive_trends(
            by_symbol=by_symbol,
            candidates=self.candidates,
            momentum_windows=self.momentum_windows,
            regression_window=self.regression_window,
        )
        selected = [symbol for symbol, _ in ranked[: self.top_k]]
        return _weights_frame(
            as_of=as_of,
            strategy=self.name,
            version=self.version,
            symbols=selected,
            invested_weight=1.0 - self.cash_buffer,
            zero_symbols=list(self.candidates),
        )


@dataclass(frozen=True)
class RegimeFilteredEtfTrendStrategy(Strategy):
    """仅在宽基准处于绝对正趋势时承担 ETF 趋势组合风险。"""

    candidates: tuple[str, ...]
    regime_symbol: str
    top_k: int = 1
    cash_buffer: float = 0.0
    factor_version: str = "trend_v1"
    momentum_windows: tuple[int, ...] = (20, 60, 120)
    regression_window: int = 60
    name: str = "etf_regime_trend"
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        _validate_parameters(self.candidates, self.cash_buffer)
        if self.regime_symbol not in self.candidates:
            raise ValueError("regime_symbol 必须属于冻结候选池")
        if self.top_k <= 0:
            raise ValueError("top_k 必须大于 0")

    def target_weights(self, as_of: dt.date, data: pl.DataFrame) -> pl.DataFrame:
        """市场状态不满足时输出全候选零权重，显式回到现金。"""
        by_symbol = _factor_values(
            data, as_of=as_of, factor_version=self.factor_version
        )
        regime = _rank_positive_trends(
            by_symbol=by_symbol,
            candidates=(self.regime_symbol,),
            momentum_windows=self.momentum_windows,
            regression_window=self.regression_window,
        )
        ranked = (
            _rank_positive_trends(
                by_symbol=by_symbol,
                candidates=self.candidates,
                momentum_windows=self.momentum_windows,
                regression_window=self.regression_window,
            )
            if regime
            else []
        )
        selected = [symbol for symbol, _ in ranked[: self.top_k]]
        return _weights_frame(
            as_of=as_of,
            strategy=self.name,
            version=self.version,
            symbols=selected,
            invested_weight=1.0 - self.cash_buffer,
            zero_symbols=list(self.candidates),
        )


@dataclass(frozen=True)
class BreadthFilteredEtfTrendStrategy(Strategy):
    """仅在冻结候选池严格多数处于正动量时承担趋势组合风险。"""

    candidates: tuple[str, ...]
    top_k: int = 1
    cash_buffer: float = 0.0
    factor_version: str = "trend_v1"
    momentum_windows: tuple[int, ...] = (20, 60, 120)
    regression_window: int = 60
    breadth_window: int = 120
    name: str = "etf_breadth_regime_trend"
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        _validate_parameters(self.candidates, self.cash_buffer)
        if self.top_k <= 0:
            raise ValueError("top_k 必须大于 0")
        if self.breadth_window not in self.momentum_windows:
            raise ValueError("breadth_window 必须包含在 momentum_windows")

    def target_weights(self, as_of: dt.date, data: pl.DataFrame) -> pl.DataFrame:
        """宽度输入不完整或未达到严格多数时显式回到现金。"""
        by_symbol = _factor_values(
            data, as_of=as_of, factor_version=self.factor_version
        )
        breadth_name = f"momentum_{self.breadth_window}"
        breadth_values = [
            by_symbol.get(symbol, {}).get(breadth_name)
            for symbol in self.candidates
        ]
        risk_on = (
            all(value is not None for value in breadth_values)
            and sum(value > 0 for value in breadth_values if value is not None) * 2
            > len(self.candidates)
        )
        ranked = (
            _rank_positive_trends(
                by_symbol=by_symbol,
                candidates=self.candidates,
                momentum_windows=self.momentum_windows,
                regression_window=self.regression_window,
            )
            if risk_on
            else []
        )
        selected = [symbol for symbol, _ in ranked[: self.top_k]]
        return _weights_frame(
            as_of=as_of,
            strategy=self.name,
            version=self.version,
            symbols=selected,
            invested_weight=1.0 - self.cash_buffer,
            zero_symbols=list(self.candidates),
        )


@dataclass(frozen=True)
class RegimeFilteredEtfLowVolatilityStrategy(Strategy):
    """Select the lowest-volatility ETFs while the broad market trend is positive."""

    candidates: tuple[str, ...]
    regime_symbol: str
    top_k: int = 2
    cash_buffer: float = 0.0
    trend_factor_version: str = "trend_v1"
    risk_factor_version: str = "risk_v1"
    momentum_windows: tuple[int, ...] = (20, 60, 120)
    regression_window: int = 60
    volatility_window: int = 60
    name: str = "etf_regime_low_volatility"
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        _validate_parameters(self.candidates, self.cash_buffer)
        if self.regime_symbol not in self.candidates:
            raise ValueError("regime_symbol 必须属于冻结候选池")
        if self.top_k <= 0:
            raise ValueError("top_k 必须大于 0")
        if self.volatility_window < 2:
            raise ValueError("volatility_window 至少为 2")

    def target_weights(self, as_of: dt.date, data: pl.DataFrame) -> pl.DataFrame:
        """Fail closed on a negative regime or incomplete volatility input."""
        trends = _factor_values(
            data, as_of=as_of, factor_version=self.trend_factor_version
        )
        regime = _rank_positive_trends(
            by_symbol=trends,
            candidates=(self.regime_symbol,),
            momentum_windows=self.momentum_windows,
            regression_window=self.regression_window,
        )
        risks = _factor_values(
            data, as_of=as_of, factor_version=self.risk_factor_version
        )
        factor_name = f"annualized_realized_volatility_{self.volatility_window}"
        ranked = []
        if regime:
            for symbol in self.candidates:
                value = risks.get(symbol, {}).get(factor_name)
                if value is not None and math.isfinite(value) and value > 0:
                    ranked.append((symbol, value))
            ranked.sort(key=lambda item: (item[1], item[0]))
        selected = [symbol for symbol, _ in ranked[: self.top_k]]
        return _weights_frame(
            as_of=as_of,
            strategy=self.name,
            version=self.version,
            symbols=selected,
            invested_weight=1.0 - self.cash_buffer,
            zero_symbols=list(self.candidates),
        )


@dataclass(frozen=True)
class RegimeFilteredEtfRiskAdjustedMomentumStrategy(Strategy):
    """Rank positive-trend ETFs by fixed momentum per unit of realized risk."""

    candidates: tuple[str, ...]
    regime_symbol: str
    top_k: int = 2
    cash_buffer: float = 0.0
    trend_factor_version: str = "trend_v1"
    risk_factor_version: str = "risk_v1"
    momentum_windows: tuple[int, ...] = (20, 60, 120)
    regression_window: int = 60
    ranking_momentum_window: int = 120
    volatility_window: int = 60
    name: str = "etf_regime_risk_adjusted_momentum"
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        _validate_parameters(self.candidates, self.cash_buffer)
        if self.regime_symbol not in self.candidates:
            raise ValueError("regime_symbol 必须属于冻结候选池")
        if self.top_k <= 0:
            raise ValueError("top_k 必须大于 0")
        if self.ranking_momentum_window not in self.momentum_windows:
            raise ValueError("ranking_momentum_window 必须包含在 momentum_windows")
        if self.volatility_window < 2:
            raise ValueError("volatility_window 至少为 2")

    def target_weights(self, as_of: dt.date, data: pl.DataFrame) -> pl.DataFrame:
        """Fail closed unless the regime, positive-trend and risk inputs are complete."""
        trends = _factor_values(
            data, as_of=as_of, factor_version=self.trend_factor_version
        )
        regime = _rank_positive_trends(
            by_symbol=trends,
            candidates=(self.regime_symbol,),
            momentum_windows=self.momentum_windows,
            regression_window=self.regression_window,
        )
        eligible = {
            symbol
            for symbol, _ in _rank_positive_trends(
                by_symbol=trends,
                candidates=self.candidates,
                momentum_windows=self.momentum_windows,
                regression_window=self.regression_window,
            )
        }
        risks = _factor_values(
            data, as_of=as_of, factor_version=self.risk_factor_version
        )
        momentum_name = f"momentum_{self.ranking_momentum_window}"
        volatility_name = f"annualized_realized_volatility_{self.volatility_window}"
        ranked: list[tuple[str, float]] = []
        if regime:
            for symbol in self.candidates:
                momentum = trends.get(symbol, {}).get(momentum_name)
                volatility = risks.get(symbol, {}).get(volatility_name)
                if (
                    symbol in eligible
                    and momentum is not None
                    and volatility is not None
                    and math.isfinite(momentum)
                    and math.isfinite(volatility)
                    and volatility > 0
                ):
                    ranked.append((symbol, momentum / volatility))
            ranked.sort(key=lambda item: (-item[1], item[0]))
        selected = [symbol for symbol, _ in ranked[: self.top_k]]
        return _weights_frame(
            as_of=as_of,
            strategy=self.name,
            version=self.version,
            symbols=selected,
            invested_weight=1.0 - self.cash_buffer,
            zero_symbols=list(self.candidates),
        )


def _factor_values(
    data: pl.DataFrame, *, as_of: dt.date, factor_version: str
) -> dict[str, dict[str, float | None]]:
    factors = FactorValueSchema.validate(data).filter(
        (pl.col("as_of") == as_of)
        & (pl.col("factor_version") == factor_version)
    )
    by_symbol: dict[str, dict[str, float | None]] = {}
    for row in factors.iter_rows(named=True):
        by_symbol.setdefault(row["symbol"], {})[row["factor"]] = row["value"]
    return by_symbol


def _rank_positive_trends(
    *,
    by_symbol: dict[str, dict[str, float | None]],
    candidates: tuple[str, ...],
    momentum_windows: tuple[int, ...],
    regression_window: int,
) -> list[tuple[str, float]]:
    momentum_names = [f"momentum_{window}" for window in momentum_windows]
    score_name = f"regression_slope_r2_{regression_window}"
    ranked: list[tuple[str, float]] = []
    for symbol in candidates:
        values = by_symbol.get(symbol, {})
        momenta = [values.get(name) for name in momentum_names]
        score = values.get(score_name)
        if (
            score is not None
            and score > 0
            and all(value is not None and value > 0 for value in momenta)
        ):
            ranked.append((symbol, score))
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return ranked


def _validate_parameters(candidates: tuple[str, ...], cash_buffer: float) -> None:
    if not candidates or len(set(candidates)) != len(candidates):
        raise ValueError("candidates 必须非空且不能重复")
    if not 0 <= cash_buffer < 1:
        raise ValueError("cash_buffer 必须在 [0, 1) 范围内")


def _weights_frame(
    *,
    as_of: dt.date,
    strategy: str,
    version: str,
    symbols: list[str],
    invested_weight: float,
    zero_symbols: list[str],
) -> pl.DataFrame:
    if not symbols:
        symbols = zero_symbols
        invested_weight = 0.0
    weight = invested_weight / len(symbols)
    return TargetWeightSchema.validate(pl.DataFrame({
        "as_of": [as_of] * len(symbols),
        "strategy": [strategy] * len(symbols),
        "strategy_version": [version] * len(symbols),
        "symbol": symbols,
        "weight": [weight] * len(symbols),
    }))
