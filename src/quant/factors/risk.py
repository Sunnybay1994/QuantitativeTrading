"""Price-only risk factors used by lightweight ETF research."""

import datetime as dt
import math

import polars as pl

from quant.domain import FactorValueSchema, ResearchPrice1dSchema


def compute_realized_volatility_factors_from_prices(
    prices: pl.DataFrame,
    *,
    as_of: dt.date,
    source: str | None,
    adjustment_method: str | None = None,
    windows: tuple[int, ...] = (60,),
    annualization_sessions: int = 252,
    factor_version: str = "risk_v1",
) -> pl.DataFrame:
    """Compute annualized sample volatility from PIT log returns.

    ``annualized_realized_volatility_N`` uses exactly the latest ``N`` log
    returns ending at ``as_of``. A stale symbol or insufficient history emits a
    null value instead of carrying a prior risk estimate forward.
    """
    if source == "":
        raise ValueError("source 不能是空字符串")
    if not windows or any(window < 2 for window in windows):
        raise ValueError("windows 必须是至少为 2 的正整数")
    if annualization_sessions <= 0:
        raise ValueError("annualization_sessions 必须是正整数")

    clean = ResearchPrice1dSchema.validate(prices).filter(
        pl.col("trade_date") <= as_of
    )
    if source is not None:
        clean = clean.filter(pl.col("source") == source)
    if adjustment_method is not None:
        clean = clean.filter(pl.col("adjustment_method") == adjustment_method)

    rows: list[dict[str, object]] = []
    for symbol_frame in clean.partition_by("symbol", maintain_order=True):
        ordered = symbol_frame.sort("trade_date")
        symbol = ordered.item(0, "symbol")
        dates = ordered.get_column("trade_date").to_list()
        adjusted = ordered.get_column("adjusted_close").to_list()
        is_current = bool(dates) and dates[-1] == as_of
        for window in windows:
            value = (
                _annualized_log_return_volatility(
                    adjusted[-window - 1 :], annualization_sessions
                )
                if is_current and len(adjusted) > window
                else None
            )
            rows.append({
                "as_of": as_of,
                "symbol": symbol,
                "factor": f"annualized_realized_volatility_{window}",
                "value": value,
                "factor_version": factor_version,
            })
    if not rows:
        return pl.DataFrame(
            schema={
                "as_of": pl.Date,
                "symbol": pl.String,
                "factor": pl.String,
                "value": pl.Float64,
                "factor_version": pl.String,
            }
        )
    return FactorValueSchema.validate(pl.DataFrame(rows))


def _annualized_log_return_volatility(
    prices: list[float], annualization_sessions: int
) -> float:
    returns = [
        math.log(current / previous)
        for previous, current in zip(prices[:-1], prices[1:], strict=True)
    ]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return math.sqrt(variance * annualization_sessions)
