"""Pure target-selection transforms used between strategy scores and execution."""

import datetime as dt
import math
from collections.abc import Sequence

import polars as pl

from quant.domain import ResearchPrice1dSchema, TargetWeightSchema


def retain_ranked_target_selection(
    *,
    current_targets: pl.DataFrame,
    retention_candidates: pl.DataFrame,
    previous_symbols: Sequence[str],
    top_k: int,
) -> pl.DataFrame:
    """Retain prior targets while they remain in an explicit ranked candidate band.

    Both target frames must describe the same signal and strategy. ``current_targets``
    contains the ordinary Top-K selection, while ``retention_candidates`` contains
    the wider ranked band. Account positions and cash are deliberately absent.
    """
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
        raise ValueError("top_k 必须是正整数")
    if len(set(previous_symbols)) != len(previous_symbols):
        raise ValueError("previous_symbols 不能重复")

    current = TargetWeightSchema.validate(current_targets)
    candidates = TargetWeightSchema.validate(retention_candidates)
    _require_single_target_identity(current, label="current_targets")
    _require_single_target_identity(candidates, label="retention_candidates")
    if _target_identity(current) != _target_identity(candidates):
        raise ValueError("current_targets 与 retention_candidates 身份不一致")

    current_ranked = _positive_symbols(current)
    candidate_ranked = _positive_symbols(candidates)
    if not current_ranked:
        return current
    if not set(current_ranked).issubset(candidate_ranked):
        raise ValueError("普通 Top-K 目标必须属于保留候选带")

    previous = set(previous_symbols)
    selected = [symbol for symbol in candidate_ranked if symbol in previous][:top_k]
    for symbol in current_ranked:
        if symbol not in selected and len(selected) < top_k:
            selected.append(symbol)
    for symbol in candidate_ranked:
        if symbol not in selected and len(selected) < top_k:
            selected.append(symbol)

    invested_weight = float(current.get_column("weight").sum())
    row = current.row(0, named=True)
    weight = invested_weight / len(selected)
    return TargetWeightSchema.validate(pl.DataFrame({
        "as_of": [row["as_of"]] * len(selected),
        "strategy": [row["strategy"]] * len(selected),
        "strategy_version": [row["strategy_version"]] * len(selected),
        "symbol": selected,
        "weight": [weight] * len(selected),
    }))


def scale_target_weights_to_volatility(
    *,
    targets: pl.DataFrame,
    prices: pl.DataFrame,
    lookback_observations: int,
    annualized_target_volatility: float,
    annualization_sessions: int = 252,
) -> pl.DataFrame:
    """Scale positive target weights down to an unlevered volatility target.

    The selected symbols and their relative weights are unchanged.  Volatility is
    estimated from signal-date-available total-return prices on common observation
    dates.  Cash has zero return, so the estimate uses the absolute portfolio
    weights rather than renormalizing the invested sleeve to one.
    """
    if (
        not isinstance(lookback_observations, int)
        or isinstance(lookback_observations, bool)
        or lookback_observations < 2
    ):
        raise ValueError("lookback_observations 必须是至少为 2 的整数")
    if (
        not isinstance(annualization_sessions, int)
        or isinstance(annualization_sessions, bool)
        or annualization_sessions <= 0
    ):
        raise ValueError("annualization_sessions 必须是正整数")
    if (
        not isinstance(annualized_target_volatility, float)
        or not math.isfinite(annualized_target_volatility)
        or not 0 < annualized_target_volatility < 1
    ):
        raise ValueError("annualized_target_volatility 必须是 (0, 1) 内有限浮点数")

    current = TargetWeightSchema.validate(targets)
    _require_single_target_identity(current, label="targets")
    positive = current.filter(pl.col("weight") > 0)
    if positive.is_empty():
        return current

    history = ResearchPrice1dSchema.validate(prices)
    as_of = current.item(0, "as_of")
    if type(as_of) is not dt.date:
        raise ValueError("targets.as_of 必须是 date")
    weights = {
        row["symbol"]: float(row["weight"])
        for row in positive.select("symbol", "weight").iter_rows(named=True)
    }
    returns_by_symbol = {
        symbol: _trailing_returns(
            history=history,
            symbol=symbol,
            as_of=as_of,
            lookback_observations=lookback_observations,
        )
        for symbol in weights
    }
    common_dates = set.intersection(
        *(set(values) for values in returns_by_symbol.values())
    )
    ordered_dates = sorted(common_dates)
    if len(ordered_dates) < lookback_observations:
        return TargetWeightSchema.validate(
            current.with_columns(pl.lit(0.0).alias("weight"))
        )
    selected_dates = ordered_dates[-lookback_observations:]
    portfolio_returns = [
        sum(
            weights[symbol] * returns_by_symbol[symbol][date]
            for symbol in weights
        )
        for date in selected_dates
    ]
    mean = sum(portfolio_returns) / len(portfolio_returns)
    variance = sum((value - mean) ** 2 for value in portfolio_returns) / (
        len(portfolio_returns) - 1
    )
    realized = math.sqrt(variance * annualization_sessions)
    if not math.isfinite(realized):
        raise ValueError("波动率估计必须有限")
    scale = (
        1.0
        if realized <= annualized_target_volatility or realized == 0.0
        else annualized_target_volatility / realized
    )
    return TargetWeightSchema.validate(
        current.with_columns((pl.col("weight") * scale).alias("weight"))
    )


def _trailing_returns(
    *,
    history: pl.DataFrame,
    symbol: str,
    as_of: dt.date,
    lookback_observations: int,
) -> dict[dt.date, float]:
    observations = (
        history.filter(
            (pl.col("symbol") == symbol) & (pl.col("trade_date") <= as_of)
        )
        .sort("trade_date")
        .tail(lookback_observations + 1)
        .select("trade_date", "adjusted_close")
    )
    if observations.height < lookback_observations + 1:
        return {}
    dates = observations.get_column("trade_date").to_list()
    values = observations.get_column("adjusted_close").to_list()
    if dates[-1] != as_of:
        return {}
    return {
        dates[index]: values[index] / values[index - 1] - 1.0
        for index in range(1, len(dates))
    }


def _require_single_target_identity(frame: pl.DataFrame, *, label: str) -> None:
    if frame.is_empty():
        raise ValueError(f"{label} 不能为空")
    if frame.select("as_of", "strategy", "strategy_version").unique().height != 1:
        raise ValueError(f"{label} 必须只有一个目标身份")


def _target_identity(frame: pl.DataFrame) -> tuple[object, object, object]:
    row = frame.select("as_of", "strategy", "strategy_version").row(0)
    return row[0], row[1], row[2]


def _positive_symbols(frame: pl.DataFrame) -> list[str]:
    return frame.filter(pl.col("weight") > 0).get_column("symbol").to_list()
