"""不复权行情与累计后复权因子的组合。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

import polars as pl

from quant.domain import AdjustmentFactorSchema, Bar1dSchema

CoverageReason = Literal["missing_symbol", "no_baseline_on_or_before_first_bar"]


@dataclass(frozen=True, slots=True)
class AdjustmentFactorCoverageIssue:
    """单个证券的复权因子首日基线覆盖问题；字段脱敏，不含路径或凭据。"""

    symbol: str
    reason: CoverageReason
    first_trade_date: dt.date
    earliest_effective_date: dt.date | None


class AdjustmentFactorCoverageError(ValueError):
    """显式复权路径下因子覆盖不足；fail-closed，禁止静默把空因子当 1。"""

    def __init__(self, issues: tuple[AdjustmentFactorCoverageIssue, ...]) -> None:
        if not issues:
            raise ValueError("AdjustmentFactorCoverageError 需要至少一条 issue")
        ordered = tuple(sorted(issues, key=lambda item: item.symbol))
        if issues != ordered:
            issues = ordered
        self.issues = issues
        symbols = ", ".join(item.symbol for item in self.issues)
        detail = "; ".join(
            (
                f"{item.symbol}:{item.reason}"
                f"(first_trade_date={item.first_trade_date.isoformat()}"
                f", earliest_effective_date="
                f"{item.earliest_effective_date.isoformat() if item.earliest_effective_date else 'None'}"
                f")"
            )
            for item in self.issues
        )
        super().__init__(f"复权因子首日基线覆盖失败，拒绝发布: [{symbols}]; {detail}")


def apply_adjustment_factors(
    bars: pl.DataFrame, factors: pl.DataFrame
) -> pl.DataFrame:
    """按证券和生效日期 as-of 匹配因子，只更新 bar_1d.adj_factor。

    对每个已返回 bar 的证券做全局 coverage preflight：须存在
    ``effective_date <= min(trade_date)`` 的累计因子。任一证券失败则整体抛出
    ``AdjustmentFactorCoverageError``，不返回部分结果，不回退 bar 原 adj_factor。
    """
    validated_bars = Bar1dSchema.validate(bars)
    validated_factors = AdjustmentFactorSchema.validate(factors)
    if validated_bars.is_empty():
        return validated_bars

    _assert_first_day_baseline_coverage(validated_bars, validated_factors)

    columns = validated_bars.columns
    matched: list[pl.DataFrame] = []
    for symbol in validated_bars.get_column("symbol").unique().sort().to_list():
        symbol_bars = validated_bars.filter(pl.col("symbol") == symbol).sort("trade_date")
        symbol_factors = (
            validated_factors.filter(pl.col("symbol") == symbol)
            .select(
                "effective_date",
                pl.col("adj_factor").alias("_matched_adj_factor"),
            )
            .sort("effective_date")
        )
        matched.append(
            symbol_bars.join_asof(
                symbol_factors,
                left_on="trade_date",
                right_on="effective_date",
                strategy="backward",
            )
            .with_columns(pl.col("_matched_adj_factor").alias("adj_factor"))
            .select(columns)
        )
    return pl.concat(matched, how="vertical").sort(["symbol", "trade_date"])


def _assert_first_day_baseline_coverage(
    bars: pl.DataFrame, factors: pl.DataFrame
) -> None:
    """全局 preflight：任一 bar 证券缺少首日及以前基线则整体失败。"""
    issues: list[AdjustmentFactorCoverageIssue] = []
    bar_symbols = bars.get_column("symbol").unique().sort().to_list()
    for symbol in bar_symbols:
        symbol_bars = bars.filter(pl.col("symbol") == symbol)
        first_trade_date = symbol_bars.get_column("trade_date").min()
        assert isinstance(first_trade_date, dt.date)
        symbol_factors = factors.filter(pl.col("symbol") == symbol)
        if symbol_factors.is_empty():
            issues.append(
                AdjustmentFactorCoverageIssue(
                    symbol=symbol,
                    reason="missing_symbol",
                    first_trade_date=first_trade_date,
                    earliest_effective_date=None,
                )
            )
            continue
        earliest_effective_date = symbol_factors.get_column("effective_date").min()
        assert isinstance(earliest_effective_date, dt.date)
        if earliest_effective_date > first_trade_date:
            issues.append(
                AdjustmentFactorCoverageIssue(
                    symbol=symbol,
                    reason="no_baseline_on_or_before_first_bar",
                    first_trade_date=first_trade_date,
                    earliest_effective_date=earliest_effective_date,
                )
            )
    if issues:
        raise AdjustmentFactorCoverageError(tuple(issues))
