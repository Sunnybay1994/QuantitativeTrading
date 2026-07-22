"""质量指标和跨源价差报告测试。"""

import datetime as dt

import polars as pl
import pytest

from quant.data.comparison import compare_closes
from quant.data.quality import QualityGateError, validate_bars


def clean_bars(source: str, closes: list[float]) -> pl.DataFrame:
    dates = [dt.date(2026, 7, 8), dt.date(2026, 7, 9), dt.date(2026, 7, 10)]
    return pl.DataFrame(
        {
            "symbol": ["000001.SZ"] * len(closes),
            "trade_date": dates[: len(closes)],
            "open": closes,
            "high": [value * 1.01 for value in closes],
            "low": [value * 0.99 for value in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
            "amount": [value * 1000 for value in closes],
            "adj_factor": [1.0] * len(closes),
            "source": [source] * len(closes),
        }
    )


def test_quality_reports_missing_observation_and_extreme_return():
    frame = clean_bars("akshare", [10.0, 15.0])
    expected = {
        dt.date(2026, 7, 8),
        dt.date(2026, 7, 9),
        dt.date(2026, 7, 10),
    }

    with pytest.raises(QualityGateError) as error:
        validate_bars(frame, expected_dates=expected, extreme_return_threshold=0.30)

    assert error.value.report.missing_observations == 1
    assert error.value.report.extreme_return_rows == 1
    assert error.value.report.missing_rate == 0.0


def test_close_comparison_reports_price_differences_and_unmatched_rows():
    primary = clean_bars("akshare", [10.0, 10.1, 10.2])
    reference = clean_bars("baostock", [10.0, 10.2])

    report = compare_closes(primary, reference, tolerance=0.005)

    assert report.compared_rows == 2
    assert report.primary_only_rows == 1
    assert report.reference_only_rows == 0
    assert report.above_tolerance_rows == 1
    assert report.max_abs_relative_diff is not None


def test_quality_detects_symbol_with_no_rows():
    frame = clean_bars("akshare", [10.0])

    with pytest.raises(QualityGateError) as error:
        validate_bars(
            frame,
            expected_dates={dt.date(2026, 7, 8)},
            expected_symbols={"000001.SZ", "600000.SH"},
        )

    assert error.value.report.missing_observations == 1


def test_extreme_return_uses_adjusted_price():
    frame = clean_bars("baostock", [10.0, 8.0]).with_columns(
        pl.Series("adj_factor", [1.0, 1.25])
    )

    report = validate_bars(frame, extreme_return_threshold=0.10)

    assert report.extreme_return_rows == 0
