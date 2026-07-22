"""ETF 趋势轮动使用的可复现价量因子。"""

import datetime as dt
import math

import polars as pl

from quant.domain import Bar1dSchema, FactorValueSchema, ResearchPrice1dSchema


def compute_trend_factors(
    bars: pl.DataFrame,
    *,
    as_of: dt.date,
    source: str,
    momentum_windows: tuple[int, ...] = (20, 60, 120),
    regression_window: int = 60,
    factor_version: str = "trend_v1",
) -> pl.DataFrame:
    """由截至 as_of 的复权收盘价计算动量和年化斜率×R²。

    ``momentum_N`` 使用当前复权收盘价相对 N 个交易观测前的收益；回归因子
    使用最近 N 个观测的对数价格。证券在 ``as_of`` 没有行情时所有值为 null，
    防止停牌或缺数证券沿用陈旧信号。
    """
    if not source:
        raise ValueError("source 不能为空")
    if not momentum_windows or any(window <= 0 for window in momentum_windows):
        raise ValueError("momentum_windows 必须是正整数")
    if regression_window < 2:
        raise ValueError("regression_window 至少为 2")

    clean = Bar1dSchema.validate(bars).filter(
        (pl.col("source") == source) & (pl.col("trade_date") <= as_of)
    )
    prices = clean.select(
        "symbol",
        "trade_date",
        (pl.col("close") * pl.col("adj_factor")).alias("adjusted_close"),
        pl.lit("CUMULATIVE_FACTOR").alias("adjustment_method"),
        "source",
    )
    return compute_trend_factors_from_prices(
        prices,
        as_of=as_of,
        source=source,
        adjustment_method="CUMULATIVE_FACTOR",
        momentum_windows=momentum_windows,
        regression_window=regression_window,
        factor_version=factor_version,
    )


def compute_trend_factors_from_prices(
    prices: pl.DataFrame,
    *,
    as_of: dt.date,
    source: str | None,
    adjustment_method: str | None = None,
    momentum_windows: tuple[int, ...] = (20, 60, 120),
    regression_window: int = 60,
    factor_version: str = "trend_v1",
) -> pl.DataFrame:
    """由研究专用调整收盘价计算趋势因子。"""
    if source == "":
        raise ValueError("source 不能是空字符串")
    if not momentum_windows or any(window <= 0 for window in momentum_windows):
        raise ValueError("momentum_windows 必须是正整数")
    if regression_window < 2:
        raise ValueError("regression_window 至少为 2")
    clean = ResearchPrice1dSchema.validate(prices).filter(pl.col("trade_date") <= as_of)
    if source is not None:
        clean = clean.filter(pl.col("source") == source)
    if adjustment_method is not None:
        clean = clean.filter(pl.col("adjustment_method") == adjustment_method)
    factor_names = [f"momentum_{window}" for window in momentum_windows]
    regression_name = f"regression_slope_r2_{regression_window}"
    rows: list[dict[str, object]] = []
    for symbol_frame in clean.partition_by("symbol", maintain_order=True):
        ordered = symbol_frame.sort("trade_date")
        symbol = ordered.item(0, "symbol")
        dates = ordered.get_column("trade_date").to_list()
        adjusted = ordered.get_column("adjusted_close").to_list()
        is_current = bool(dates) and dates[-1] == as_of
        values: dict[str, float | None] = {}
        for window, name in zip(momentum_windows, factor_names, strict=True):
            values[name] = (
                adjusted[-1] / adjusted[-window - 1] - 1.0
                if is_current and len(adjusted) > window
                else None
            )
        values[regression_name] = (
            _annualized_log_slope_r2(adjusted[-regression_window:])
            if is_current and len(adjusted) >= regression_window
            else None
        )
        rows.extend(
            {
                "as_of": as_of,
                "symbol": symbol,
                "factor": factor,
                "value": value,
                "factor_version": factor_version,
            }
            for factor, value in values.items()
        )
    if not rows:
        return _empty_factor_frame()
    return FactorValueSchema.validate(pl.DataFrame(rows))


def _annualized_log_slope_r2(prices: list[float]) -> float:
    logs = [math.log(price) for price in prices]
    count = len(logs)
    x_mean = (count - 1) / 2
    y_mean = sum(logs) / count
    denominator = sum((index - x_mean) ** 2 for index in range(count))
    slope = sum(
        (index - x_mean) * (value - y_mean) for index, value in enumerate(logs)
    ) / denominator
    intercept = y_mean - slope * x_mean
    total = sum((value - y_mean) ** 2 for value in logs)
    residual = sum(
        (value - (intercept + slope * index)) ** 2
        for index, value in enumerate(logs)
    )
    r_squared = 0.0 if total <= 1e-24 else max(0.0, min(1.0, 1 - residual / total))
    return math.expm1(slope * 252) * r_squared


def _empty_factor_frame() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "as_of": pl.Date,
            "symbol": pl.String,
            "factor": pl.String,
            "value": pl.Float64,
            "factor_version": pl.String,
        }
    )
