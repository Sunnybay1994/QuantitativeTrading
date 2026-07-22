"""多数据源日线交叉校验。"""

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import polars as pl


@dataclass(frozen=True)
class CloseComparisonReport:
    """两个 clean bar_1d 数据源的收盘价差异。"""

    generated_at: str
    primary_source: str
    reference_source: str
    compared_rows: int
    primary_only_rows: int
    reference_only_rows: int
    tolerance: float
    above_tolerance_rows: int
    mean_abs_relative_diff: float | None
    max_abs_relative_diff: float | None


def compare_closes(
    primary: pl.DataFrame,
    reference: pl.DataFrame,
    *,
    tolerance: float = 0.005,
) -> CloseComparisonReport:
    """按 symbol/trade_date 对齐并计算绝对相对价差。"""
    if tolerance < 0:
        raise ValueError("tolerance 不得为负")
    required = {"symbol", "trade_date", "close", "source"}
    for name, frame in (("primary", primary), ("reference", reference)):
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"{name} 缺少字段: {', '.join(missing)}")
    primary_source = _single_source(primary, "primary")
    reference_source = _single_source(reference, "reference")
    key = ["symbol", "trade_date"]
    left = primary.select(*key, pl.col("close").alias("primary_close"))
    right = reference.select(*key, pl.col("close").alias("reference_close"))
    joined = left.join(right, on=key, how="inner").with_columns(
        ((pl.col("primary_close") / pl.col("reference_close")) - 1.0)
        .abs()
        .alias("abs_relative_diff")
    )
    primary_only = left.join(right.select(*key), on=key, how="anti").height
    reference_only = right.join(left.select(*key), on=key, how="anti").height
    diffs = joined.get_column("abs_relative_diff") if joined.height else None
    return CloseComparisonReport(
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        primary_source=primary_source,
        reference_source=reference_source,
        compared_rows=joined.height,
        primary_only_rows=primary_only,
        reference_only_rows=reference_only,
        tolerance=tolerance,
        above_tolerance_rows=joined.filter(pl.col("abs_relative_diff") > tolerance).height,
        mean_abs_relative_diff=_as_float(diffs.mean()) if diffs is not None else None,
        max_abs_relative_diff=_as_float(diffs.max()) if diffs is not None else None,
    )


def write_comparison_report(report: CloseComparisonReport, path: Path) -> None:
    """写入跨源校验 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")


def _single_source(frame: pl.DataFrame, name: str) -> str:
    sources = frame.get_column("source").unique().to_list()
    if len(sources) != 1:
        raise ValueError(f"{name} 必须且只能包含一个 source，实际为: {sources}")
    return str(sources[0])


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)
