"""数据质量报告与 bar_1d 准入门禁。"""

import datetime as dt
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import pandera.errors
import polars as pl

from quant.domain import Bar1dSchema


@dataclass(frozen=True)
class BarQualityReport:
    """一次 bar_1d 批次的最小质量证据。"""

    generated_at: str
    rows: int
    null_cells: int
    missing_rate: float
    missing_rate_limit: float
    missing_observations: int
    duplicate_keys: int
    invalid_ohlc_rows: int
    extreme_return_rows: int
    extreme_return_threshold: float
    schema_error: str | None = None

    @property
    def passed(self) -> bool:
        return (
            self.missing_rate <= self.missing_rate_limit
            and self.missing_observations == 0
            and self.duplicate_keys == 0
            and self.invalid_ohlc_rows == 0
            and self.schema_error is None
        )


class QualityGateError(ValueError):
    """批次未通过数据质量门禁。"""

    def __init__(self, report: BarQualityReport) -> None:
        super().__init__(f"bar_1d 质量门禁失败: {asdict(report)}")
        self.report = report


def validate_bars(
    frame: pl.DataFrame,
    *,
    expected_dates: set[dt.date] | None = None,
    expected_symbols: set[str] | None = None,
    missing_rate_limit: float = 0.0,
    extreme_return_threshold: float = 0.30,
) -> BarQualityReport:
    """生成质量报告并执行 Schema；失败时抛出携带报告的异常。"""
    if not 0.0 <= missing_rate_limit <= 1.0:
        raise ValueError("missing_rate_limit 必须在 [0, 1] 内")
    if extreme_return_threshold <= 0:
        raise ValueError("extreme_return_threshold 必须大于 0")
    duplicate_keys = 0
    invalid_ohlc_rows = 0
    extreme_return_rows = 0
    missing_observations = 0
    key = ["symbol", "trade_date", "source"]
    if set(key).issubset(frame.columns):
        duplicate_keys = frame.height - frame.unique(subset=key).height
    price_columns = {"open", "high", "low", "close"}
    if price_columns.issubset(frame.columns):
        invalid_ohlc_rows = frame.filter(
            (pl.col("high") < pl.col("low"))
            | (pl.col("high") < pl.col("open"))
            | (pl.col("high") < pl.col("close"))
            | (pl.col("low") > pl.col("open"))
            | (pl.col("low") > pl.col("close"))
        ).height
    if {"symbol", "trade_date", "close"}.issubset(frame.columns):
        quality_price = (
            pl.col("close") * pl.col("adj_factor")
            if "adj_factor" in frame.columns
            else pl.col("close")
        )
        extreme_return_rows = (
            frame.sort(["symbol", "trade_date"])
            .with_columns(
                quality_price.pct_change().over("symbol").abs().alias("_abs_return")
            )
            .filter(pl.col("_abs_return") > extreme_return_threshold)
            .height
        )
        if expected_dates is not None:
            expected = len(expected_dates)
            observed = frame.group_by("symbol").agg(
                pl.col("trade_date").filter(pl.col("trade_date").is_in(expected_dates)).n_unique()
            )
            observed_by_symbol = dict(
                zip(
                    observed.get_column("symbol").to_list(),
                    observed.get_column("trade_date").to_list(),
                    strict=True,
                )
            )
            symbols = expected_symbols or set(observed_by_symbol)
            missing_observations = sum(
                max(expected - int(observed_by_symbol.get(symbol, 0)), 0)
                for symbol in symbols
            )
    null_cells = sum(frame.null_count().row(0)) if frame.width else 0
    total_cells = frame.height * frame.width
    report = BarQualityReport(
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        rows=frame.height,
        null_cells=null_cells,
        missing_rate=null_cells / total_cells if total_cells else 0.0,
        missing_rate_limit=missing_rate_limit,
        missing_observations=missing_observations,
        duplicate_keys=duplicate_keys,
        invalid_ohlc_rows=invalid_ohlc_rows,
        extreme_return_rows=extreme_return_rows,
        extreme_return_threshold=extreme_return_threshold,
    )
    try:
        Bar1dSchema.validate(frame)
    except pandera.errors.SchemaError as exc:
        report = replace(report, schema_error=str(exc))
    if not report.passed:
        raise QualityGateError(report)
    return report


def write_quality_report(report: BarQualityReport, path: Path) -> None:
    """把质量结果写为可审计 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({**asdict(report), "passed": report.passed}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
