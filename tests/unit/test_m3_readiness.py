"""D1 / L0A: M3 就绪审计（含基准 BenchmarkBar1dSchema 契约）。"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.domain import BenchmarkBar1dSchema
from quant.research.m3.readiness import ReadinessIssue, audit_m3_readiness

FIXTURE_ROOT = Path("tests/fixtures/m3")
BENCHMARK = "H00300.CSI"


def _read(name: str) -> pl.DataFrame:
    return pl.read_csv(FIXTURE_ROOT / name, try_parse_dates=True)


def _base_config(**overrides: object) -> dict:
    config: dict = {
        "data": {
            "universe": "CSI300_PIT",
            "benchmark": BENCHMARK,
            "source": "fixture",
            "start_date": dt.date(2026, 1, 5),
            "end_date": dt.date(2026, 1, 20),
            "minimum_train_sessions": 5,
            "minimum_cross_section_symbols": 2,
        },
        "labels": {"horizons_sessions": [5, 10]},
        "walk_forward": {"embargo_sessions": 10},
        "runtime": {"qlib": {"supported_python": ">=3.8,<3.13"}},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and key in config and isinstance(config[key], dict):
            nested = dict(config[key])
            nested.update(value)
            config[key] = nested
        else:
            config[key] = value
    return config


def _instruments() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"],
            "market": ["SZ", "SZ", "SZ", "SZ"],
            "name": ["a", "b", "c", "d"],
            "instrument_type": ["STOCK", "STOCK", "STOCK", "STOCK"],
            "currency": ["CNY"] * 4,
            "list_date": [dt.date(2020, 1, 1)] * 4,
            "delist_date": [None] * 4,
            "board_lot": [100] * 4,
            "status": ["LISTED"] * 4,
        }
    )


def _benchmark_bars(**overrides: object) -> pl.DataFrame:
    frame = _read("benchmark_bars_total_return.csv")
    for key, value in overrides.items():
        frame = frame.with_columns(pl.lit(value).alias(str(key)))
    return BenchmarkBar1dSchema.validate(frame)


def _audit(**kwargs: object) -> list[ReadinessIssue]:
    params = {
        "bars": _read("bars.csv"),
        "instruments": _instruments(),
        "membership": _read("membership.csv"),
        "calendars": _read("calendar.csv"),
        "benchmark_bars": _benchmark_bars(),
        "config": _base_config(),
    }
    params.update(kwargs)
    return audit_m3_readiness(**params)  # type: ignore[arg-type]


def _codes(issues: list[ReadinessIssue]) -> set[str]:
    return {item.code for item in issues if item.severity == "ERROR"}


def _benchmark_codes(issues: list[ReadinessIssue]) -> set[str]:
    return {
        item.code
        for item in issues
        if item.severity == "ERROR" and item.code.startswith("BENCHMARK_")
    }


def test_fixture_data_surfaces_python_or_qlib_runtime_errors() -> None:
    issues = _audit()
    codes = _codes(issues)
    assert "PYTHON_UNSUPPORTED" in codes or "QLIB_NOT_IMPORTABLE" in codes
    assert issues == sorted(issues, key=lambda i: (i.severity, i.code, i.message))


def test_l0a_valid_benchmark_schema_has_no_benchmark_errors() -> None:
    """完全通过 BenchmarkBar1dSchema、不含股票专属列的表不得出现 benchmark 类错误。"""
    bench = _benchmark_bars()
    assert set(bench.columns) == {
        "benchmark",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "source",
        "source_snapshot_id",
    }
    assert "symbol" not in bench.columns
    assert "volume" not in bench.columns
    assert "adj_factor" not in bench.columns
    # 日历与配置区间仅覆盖基准已有交易日，隔离字段契约与覆盖检查
    dates = bench.get_column("trade_date").to_list()
    calendars = pl.DataFrame(
        {
            "market": ["SH"] * len(dates),
            "date": dates,
            "is_open": [True] * len(dates),
            "is_connect_open": [False] * len(dates),
            "is_half_day": [False] * len(dates),
        }
    )
    codes = _benchmark_codes(
        _audit(
            benchmark_bars=bench,
            calendars=calendars,
            config=_base_config(
                data={
                    "universe": "CSI300_PIT",
                    "benchmark": BENCHMARK,
                    "source": "fixture",
                    "start_date": min(dates),
                    "end_date": max(dates),
                    "minimum_train_sessions": 1,
                    "minimum_cross_section_symbols": 1,
                }
            ),
        )
    )
    assert codes == set()


def test_missing_pit_membership_rejected() -> None:
    membership = _read("membership.csv").filter(pl.col("universe") != "CSI300_PIT")
    assert "PIT_MEMBERSHIP_MISSING" in _codes(_audit(membership=membership))


def test_missing_benchmark_rejected() -> None:
    empty = _benchmark_bars().clear()
    assert "BENCHMARK_EMPTY" in _codes(_audit(benchmark_bars=empty))
    assert "DATA_SOURCE_MISSING" not in _codes(_audit(benchmark_bars=empty))


def test_short_history_rejected() -> None:
    codes = _codes(
        _audit(
            config=_base_config(
                data={
                    "universe": "CSI300_PIT",
                    "benchmark": BENCHMARK,
                    "source": "fixture",
                    "start_date": dt.date(2026, 1, 5),
                    "end_date": dt.date(2026, 1, 20),
                    "minimum_train_sessions": 1000,
                    "minimum_cross_section_symbols": 2,
                }
            )
        )
    )
    assert "HISTORY_TOO_SHORT" in codes


def test_small_cross_section_rejected() -> None:
    codes = _codes(
        _audit(
            config=_base_config(
                data={
                    "universe": "CSI300_PIT",
                    "benchmark": BENCHMARK,
                    "source": "fixture",
                    "start_date": dt.date(2026, 1, 5),
                    "end_date": dt.date(2026, 1, 20),
                    "minimum_train_sessions": 1,
                    "minimum_cross_section_symbols": 100,
                }
            )
        )
    )
    assert "CROSS_SECTION_TOO_SMALL" in codes


def test_missing_factor_rejected() -> None:
    bars = _read("bars.csv").drop("adj_factor")
    assert "BARS_MISSING_FIELDS" in _codes(_audit(bars=bars))


def test_non_positive_factor_rejected() -> None:
    bars = _read("bars.csv").with_columns(pl.lit(0.0).alias("adj_factor"))
    assert "FACTOR_NON_POSITIVE" in _codes(_audit(bars=bars))


def test_embargo_smaller_than_max_horizon_rejected() -> None:
    assert "EMBARGO_TOO_SMALL" in _codes(
        _audit(config=_base_config(walk_forward={"embargo_sessions": 5}))
    )


def test_issue_sort_order_is_severity_code_message() -> None:
    issues = [
        ReadinessIssue("B", "WARNING", "z"),
        ReadinessIssue("A", "ERROR", "b"),
        ReadinessIssue("A", "ERROR", "a"),
    ]
    assert sorted(issues, key=lambda i: (i.severity, i.code, i.message)) == [
        ReadinessIssue("A", "ERROR", "a"),
        ReadinessIssue("A", "ERROR", "b"),
        ReadinessIssue("B", "WARNING", "z"),
    ]


def test_r1_daily_cross_section_uses_minimum_not_maximum() -> None:
    """两个开市日截面 2/1、阈值 2，必须报 CROSS_SECTION_TOO_SMALL。"""
    calendars = pl.DataFrame(
        {
            "market": ["SH", "SH"],
            "date": [dt.date(2026, 1, 5), dt.date(2026, 1, 6)],
            "is_open": [True, True],
            "is_connect_open": [False, False],
            "is_half_day": [False, False],
        }
    )
    membership = pl.DataFrame(
        {
            "universe": ["CSI300_PIT"] * 2,
            "symbol": ["000001.SZ", "000002.SZ"],
            "effective_from": [dt.date(2026, 1, 5)] * 2,
            "effective_to": [None, None],
        }
    )
    bars = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ", "000001.SZ"],
            "trade_date": [
                dt.date(2026, 1, 5),
                dt.date(2026, 1, 5),
                dt.date(2026, 1, 6),
            ],
            "open": [10.0, 20.0, 10.0],
            "high": [11.0, 21.0, 11.0],
            "low": [9.0, 19.0, 9.0],
            "close": [10.5, 20.5, 10.5],
            "volume": [100.0, 100.0, 100.0],
            "amount": [1000.0, 2000.0, 1000.0],
            "adj_factor": [1.0, 1.0, 1.0],
            "source": ["fixture"] * 3,
        }
    )
    bench = pl.DataFrame(
        {
            "benchmark": [BENCHMARK, BENCHMARK],
            "trade_date": [dt.date(2026, 1, 5), dt.date(2026, 1, 6)],
            "open": [100.0, 100.0],
            "high": [101.0, 101.0],
            "low": [99.0, 99.0],
            "close": [100.5, 100.5],
            "source": ["fixture"] * 2,
            "source_snapshot_id": ["snap", "snap"],
        }
    )
    issues = _audit(
        bars=bars,
        membership=membership,
        calendars=calendars,
        benchmark_bars=bench,
        config=_base_config(
            data={
                "universe": "CSI300_PIT",
                "benchmark": BENCHMARK,
                "source": "fixture",
                "start_date": dt.date(2026, 1, 5),
                "end_date": dt.date(2026, 1, 6),
                "minimum_train_sessions": 1,
                "minimum_cross_section_symbols": 2,
            }
        ),
    )
    cross = [i for i in issues if i.code == "CROSS_SECTION_TOO_SMALL"]
    assert cross
    assert "最小值 1" in cross[0].message
    assert "阈值 2" in cross[0].message
    assert "受影响日数 1" in cross[0].message


def test_r1_trainable_sessions_not_raw_calendar_height() -> None:
    """日历 756 日但可训练 session 仅 10，必须 HISTORY_TOO_SHORT。"""
    dates = [dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(756)]
    calendars = pl.DataFrame(
        {
            "market": ["SH"] * 756,
            "date": dates,
            "is_open": [True] * 756,
            "is_connect_open": [False] * 756,
            "is_half_day": [False] * 756,
        }
    )
    trade_days = dates[:10]
    symbols = [f"{i:06d}.SZ" for i in range(1, 3)]
    membership = pl.DataFrame(
        {
            "universe": ["CSI300_PIT"] * 2,
            "symbol": symbols,
            "effective_from": [dates[0]] * 2,
            "effective_to": [None, None],
        }
    )
    bar_rows = []
    for day in trade_days:
        for symbol in symbols:
            bar_rows.append(
                {
                    "symbol": symbol,
                    "trade_date": day,
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.5,
                    "volume": 100.0,
                    "amount": 1000.0,
                    "adj_factor": 1.0,
                    "source": "fixture",
                }
            )
    bars = pl.DataFrame(bar_rows)
    bench = pl.DataFrame(
        {
            "benchmark": [BENCHMARK] * 10,
            "trade_date": trade_days,
            "open": [100.0] * 10,
            "high": [101.0] * 10,
            "low": [99.0] * 10,
            "close": [100.5] * 10,
            "source": ["fixture"] * 10,
            "source_snapshot_id": ["snap"] * 10,
        }
    )
    issues = _audit(
        bars=bars,
        membership=membership,
        calendars=calendars,
        benchmark_bars=bench,
        instruments=pl.DataFrame(
            {
                "symbol": symbols,
                "market": ["SZ", "SZ"],
                "name": ["a", "b"],
                "instrument_type": ["STOCK", "STOCK"],
                "currency": ["CNY"] * 2,
                "list_date": [dates[0]] * 2,
                "delist_date": [None] * 2,
                "board_lot": [100] * 2,
                "status": ["LISTED"] * 2,
            }
        ),
        config=_base_config(
            data={
                "universe": "CSI300_PIT",
                "benchmark": BENCHMARK,
                "source": "fixture",
                "start_date": dates[0],
                "end_date": dates[-1],
                "minimum_train_sessions": 756,
                "minimum_cross_section_symbols": 2,
            }
        ),
    )
    hist = [i for i in issues if i.code == "HISTORY_TOO_SHORT"]
    assert hist
    assert "可训练 session 仅 10" in hist[0].message


def test_r1_history_outside_config_range_does_not_count() -> None:
    """配置区间外大量日历不得补足区间内不足历史。"""
    calendars = pl.DataFrame(
        {
            "market": ["SH"] * 3,
            "date": [dt.date(2025, 1, 2), dt.date(2026, 1, 5), dt.date(2026, 1, 6)],
            "is_open": [True, True, True],
            "is_connect_open": [False, False, False],
            "is_half_day": [False, False, False],
        }
    )
    membership = pl.DataFrame(
        {
            "universe": ["CSI300_PIT"],
            "symbol": ["000001.SZ"],
            "effective_from": [dt.date(2025, 1, 2)],
            "effective_to": [None],
        }
    )
    bars = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "trade_date": [
                dt.date(2025, 1, 2),
                dt.date(2026, 1, 5),
                dt.date(2026, 1, 6),
            ],
            "open": [10.0] * 3,
            "high": [11.0] * 3,
            "low": [9.0] * 3,
            "close": [10.5] * 3,
            "volume": [100.0] * 3,
            "amount": [1000.0] * 3,
            "adj_factor": [1.0] * 3,
            "source": ["fixture"] * 3,
        }
    )
    bench = pl.DataFrame(
        {
            "benchmark": [BENCHMARK] * 3,
            "trade_date": [
                dt.date(2025, 1, 2),
                dt.date(2026, 1, 5),
                dt.date(2026, 1, 6),
            ],
            "open": [100.0] * 3,
            "high": [101.0] * 3,
            "low": [99.0] * 3,
            "close": [100.5] * 3,
            "source": ["fixture"] * 3,
            "source_snapshot_id": ["snap"] * 3,
        }
    )
    issues = _audit(
        bars=bars,
        membership=membership,
        calendars=calendars,
        benchmark_bars=bench,
        config=_base_config(
            data={
                "universe": "CSI300_PIT",
                "benchmark": BENCHMARK,
                "source": "fixture",
                "start_date": dt.date(2026, 1, 5),
                "end_date": dt.date(2026, 1, 6),
                "minimum_train_sessions": 3,
                "minimum_cross_section_symbols": 1,
            }
        ),
    )
    assert "HISTORY_TOO_SHORT" in _codes(issues)


def test_f1_requires_data_source() -> None:
    config = _base_config()
    del config["data"]["source"]
    assert "CONFIG_INVALID" in _codes(_audit(config=config))
    config2 = _base_config(data={"source": ""})
    assert "CONFIG_INVALID" in _codes(_audit(config=config2))


def test_f1_missing_requested_source() -> None:
    assert "DATA_SOURCE_MISSING" in _codes(
        _audit(config=_base_config(data={"source": "tushare"}))
    )


def test_f1_cross_source_same_key_not_duplicate() -> None:
    base = _read("bars.csv").filter(pl.col("symbol") == "000001.SZ").head(1)
    other = base.with_columns(
        (pl.col("close") + 1.0).alias("close"),
        pl.lit("other").alias("source"),
    )
    bars = pl.concat([_read("bars.csv"), other])
    codes = _codes(_audit(bars=bars))
    assert "BARS_DUPLICATE_KEYS" not in codes


def test_f1_duplicate_within_selected_source() -> None:
    row = _read("bars.csv").head(1)
    bars = pl.concat([_read("bars.csv"), row])
    assert "BARS_DUPLICATE_KEYS" in _codes(_audit(bars=bars))


def test_f3_non_finite_emits_error_and_excludes_coverage() -> None:
    bars = _read("bars.csv").with_columns(
        pl.when(
            (pl.col("symbol") == "000001.SZ")
            & (pl.col("trade_date") == dt.date(2026, 1, 5))
        )
        .then(pl.lit(float("nan")))
        .otherwise(pl.col("close"))
        .alias("close")
    )
    codes = _codes(_audit(bars=bars))
    assert "BARS_NON_FINITE" in codes


def test_r1_pit_member_without_bars_rejected() -> None:
    membership = pl.DataFrame(
        {
            "universe": ["CSI300_PIT", "CSI300_PIT"],
            "symbol": ["000001.SZ", "000099.SZ"],
            "effective_from": [dt.date(2026, 1, 5), dt.date(2026, 1, 5)],
            "effective_to": [None, None],
        }
    )
    issues = _audit(membership=membership)
    pit = [i for i in issues if i.code == "PIT_BAR_COVERAGE_EMPTY"]
    assert any("000099.SZ" in i.message for i in pit)


def test_r1_missing_fields_return_issues_without_raising() -> None:
    bars = _read("bars.csv").drop("symbol")
    membership = _read("membership.csv").drop("universe")
    calendars = _read("calendar.csv").drop("date")
    assert "BARS_MISSING_FIELDS" in _codes(_audit(bars=bars))
    assert "MEMBERSHIP_MISSING_FIELDS" in _codes(_audit(membership=membership))
    assert "CALENDAR_MISSING_FIELDS" in _codes(_audit(calendars=calendars))


def test_l0a_duplicate_benchmark_keys_rejected() -> None:
    """重复 (benchmark, trade_date, source) 由生产 Schema 唯一性 fail-closed。"""
    row = _benchmark_bars().head(1)
    bench = pl.concat([_benchmark_bars(), row])
    codes = _codes(_audit(benchmark_bars=bench))
    # Schema-first：唯一性检查在 duplicate helper 之前，稳定报 BENCHMARK_INVALID
    assert "BENCHMARK_INVALID" in codes


def test_l0a_null_nan_inf_zero_negative_ohlc_rejected() -> None:
    cases = [
        pl.lit(None).cast(pl.Float64),
        pl.lit(float("nan")),
        pl.lit(float("inf")),
        pl.lit(0.0),
        pl.lit(-1.0),
    ]
    for bad in cases:
        bench = _benchmark_bars().with_columns(bad.alias("close"))
        assert "BENCHMARK_INVALID" in _codes(_audit(benchmark_bars=bench))


def test_l0a_ohlc_order_violations_rejected() -> None:
    low_gt_open = _benchmark_bars().with_columns(
        (pl.col("open") + 1.0).alias("low")
    )
    close_gt_high = _benchmark_bars().with_columns(
        (pl.col("high") + 1.0).alias("close")
    )
    assert "BENCHMARK_INVALID" in _codes(_audit(benchmark_bars=low_gt_open))
    assert "BENCHMARK_INVALID" in _codes(_audit(benchmark_bars=close_gt_high))


def test_l0a_mixed_benchmark_or_source_strictly_selected() -> None:
    base = _benchmark_bars()
    mixed_bench = pl.concat(
        [
            base,
            base.with_columns(pl.lit("000300.SH").alias("benchmark")),
        ]
    )
    assert "BENCHMARK_SYMBOL_MISMATCH" in _codes(_audit(benchmark_bars=mixed_bench))

    other_source = pl.concat(
        [
            base,
            base.with_columns(
                pl.lit("other").alias("source"),
                pl.lit("000300.SH").alias("benchmark"),
            ),
        ]
    )
    # 未选中 source 不参与；选中 source 内无混入时不应 mismatch
    assert "BENCHMARK_SYMBOL_MISMATCH" not in _codes(
        _audit(benchmark_bars=other_source)
    )


def test_l0a_price_index_config_rejected() -> None:
    assert "BENCHMARK_SYMBOL_MISMATCH" in _codes(
        _audit(config=_base_config(data={"benchmark": "000300.SH"}))
    )


def test_l0a_dense_coverage_uses_benchmark_column_only() -> None:
    """dense coverage 只从 benchmark 列取日期，不回退股票 helper。"""
    calendars = pl.DataFrame(
        {
            "market": ["SH", "SH"],
            "date": [dt.date(2026, 1, 5), dt.date(2026, 1, 6)],
            "is_open": [True, True],
            "is_connect_open": [False, False],
            "is_half_day": [False, False],
        }
    )
    membership = pl.DataFrame(
        {
            "universe": ["CSI300_PIT"],
            "symbol": ["000001.SZ"],
            "effective_from": [dt.date(2026, 1, 5)],
            "effective_to": [None],
        }
    )
    bars = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ"],
            "trade_date": [dt.date(2026, 1, 5), dt.date(2026, 1, 6)],
            "open": [10.0, 10.0],
            "high": [11.0, 11.0],
            "low": [9.0, 9.0],
            "close": [10.5, 10.5],
            "volume": [100.0, 100.0],
            "amount": [1000.0, 1000.0],
            "adj_factor": [1.0, 1.0],
            "source": ["fixture"] * 2,
        }
    )
    # 仅覆盖一日基准；不得靠股票列冒充第二日
    bench = pl.DataFrame(
        {
            "benchmark": [BENCHMARK],
            "trade_date": [dt.date(2026, 1, 5)],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "source": ["fixture"],
            "source_snapshot_id": ["snap"],
        }
    )
    codes = _codes(
        _audit(
            bars=bars,
            membership=membership,
            calendars=calendars,
            benchmark_bars=bench,
            config=_base_config(
                data={
                    "universe": "CSI300_PIT",
                    "benchmark": BENCHMARK,
                    "source": "fixture",
                    "start_date": dt.date(2026, 1, 5),
                    "end_date": dt.date(2026, 1, 6),
                    "minimum_train_sessions": 1,
                    "minimum_cross_section_symbols": 1,
                }
            ),
        )
    )
    assert "BENCHMARK_DATE_COVERAGE" in codes


def test_extra_column_and_date_coverage_both_reported() -> None:
    """超集列 + 故意缺日：BENCHMARK_INVALID 与 BENCHMARK_DATE_COVERAGE 须同时报告。"""
    calendars = pl.DataFrame(
        {
            "market": ["SH", "SH"],
            "date": [dt.date(2026, 1, 5), dt.date(2026, 1, 6)],
            "is_open": [True, True],
            "is_connect_open": [False, False],
            "is_half_day": [False, False],
        }
    )
    membership = pl.DataFrame(
        {
            "universe": ["CSI300_PIT"],
            "symbol": ["000001.SZ"],
            "effective_from": [dt.date(2026, 1, 5)],
            "effective_to": [None],
        }
    )
    bars = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ"],
            "trade_date": [dt.date(2026, 1, 5), dt.date(2026, 1, 6)],
            "open": [10.0, 10.0],
            "high": [11.0, 11.0],
            "low": [9.0, 9.0],
            "close": [10.5, 10.5],
            "volume": [100.0, 100.0],
            "amount": [1000.0, 1000.0],
            "adj_factor": [1.0, 1.0],
            "source": ["fixture"] * 2,
        }
    )
    bench = pl.DataFrame(
        {
            "benchmark": [BENCHMARK],
            "trade_date": [dt.date(2026, 1, 5)],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "source": ["fixture"],
            "source_snapshot_id": ["snap"],
            "extra_flag": [1],
        }
    )
    issues = _audit(
        bars=bars,
        membership=membership,
        calendars=calendars,
        benchmark_bars=bench,
        config=_base_config(
            data={
                "universe": "CSI300_PIT",
                "benchmark": BENCHMARK,
                "source": "fixture",
                "start_date": dt.date(2026, 1, 5),
                "end_date": dt.date(2026, 1, 6),
                "minimum_train_sessions": 1,
                "minimum_cross_section_symbols": 1,
            }
        ),
    )
    codes = _codes(issues)
    assert "BENCHMARK_INVALID" in codes
    assert "BENCHMARK_DATE_COVERAGE" in codes
    assert all(isinstance(item, ReadinessIssue) for item in issues)


def test_l0a_missing_benchmark_fields() -> None:
    bench = _benchmark_bars().drop("source_snapshot_id")
    assert "BENCHMARK_MISSING_FIELDS" in _codes(_audit(benchmark_bars=bench))


def test_p1a_stock_superset_columns_rejected() -> None:
    """股票专属四列作为 Schema superset → BENCHMARK_INVALID。"""
    bench = _benchmark_bars().with_columns(
        pl.lit("000300.SH").alias("symbol"),
        pl.lit(1.0).alias("volume"),
        pl.lit(1.0).alias("amount"),
        pl.lit(1.0).alias("adj_factor"),
    )
    codes = _codes(_audit(benchmark_bars=bench))
    assert "BENCHMARK_INVALID" in codes
    assert "BENCHMARK_MISSING_FIELDS" not in codes


def test_p1a_unknown_extra_column_rejected() -> None:
    bench = _benchmark_bars().with_columns(pl.lit(1).alias("extra_flag"))
    assert "BENCHMARK_INVALID" in _codes(_audit(benchmark_bars=bench))


def test_p1a_exact_columns_bad_dtype_rejected() -> None:
    """精确列名但 dtype 无法按 Schema 合法转换时拒绝。"""
    bench = _benchmark_bars().with_columns(pl.lit("not-a-float").alias("open"))
    assert set(bench.columns) == set(_benchmark_bars().columns)
    assert "BENCHMARK_INVALID" in _codes(_audit(benchmark_bars=bench))


def test_p1a_exact_legal_benchmark_still_ok() -> None:
    """精确合法 BenchmarkBar1dSchema 保持无 benchmark 结构错误。"""
    bench = _benchmark_bars()
    assert set(bench.columns) == {
        "benchmark",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "source",
        "source_snapshot_id",
    }
    dates = bench.get_column("trade_date").to_list()
    calendars = pl.DataFrame(
        {
            "market": ["SH"] * len(dates),
            "date": dates,
            "is_open": [True] * len(dates),
            "is_connect_open": [False] * len(dates),
            "is_half_day": [False] * len(dates),
        }
    )
    membership = pl.DataFrame(
        {
            "universe": ["CSI300_PIT"],
            "symbol": ["000001.SZ"],
            "effective_from": [min(dates)],
            "effective_to": [None],
        }
    )
    bars = pl.DataFrame(
        {
            "symbol": ["000001.SZ"] * len(dates),
            "trade_date": dates,
            "open": [10.0] * len(dates),
            "high": [11.0] * len(dates),
            "low": [9.0] * len(dates),
            "close": [10.5] * len(dates),
            "volume": [100.0] * len(dates),
            "amount": [1000.0] * len(dates),
            "adj_factor": [1.0] * len(dates),
            "source": ["fixture"] * len(dates),
        }
    )
    codes = _benchmark_codes(
        _audit(
            bars=bars,
            membership=membership,
            calendars=calendars,
            benchmark_bars=bench,
            config=_base_config(
                data={
                    "universe": "CSI300_PIT",
                    "benchmark": BENCHMARK,
                    "source": "fixture",
                    "start_date": min(dates),
                    "end_date": max(dates),
                    "minimum_train_sessions": 1,
                    "minimum_cross_section_symbols": 1,
                }
            ),
        )
    )
    assert codes == set()


def test_p1a_missing_fields_no_secondary_exception() -> None:
    """缺列只报缺字段语义，不因随后访问缺列抛二次异常。"""
    bench = _benchmark_bars().drop("close")
    issues = _audit(benchmark_bars=bench)
    assert "BENCHMARK_MISSING_FIELDS" in _codes(issues)
    assert all(isinstance(item, ReadinessIssue) for item in issues)


def test_p1a_schema_exception_surfaces_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    """注入含路径/token 的 Schema 异常时，公开 issue 与异常面不泄露原文。"""
    import traceback

    import quant.research.m3.readiness as readiness

    secret = "/abs/path/secret token=abcd1234 traceback=leak"

    class _BoomSchema:
        @staticmethod
        def validate(_frame: pl.DataFrame) -> pl.DataFrame:
            raise ValueError(secret)

    monkeypatch.setattr(readiness, "BenchmarkBar1dSchema", _BoomSchema)
    try:
        issues = _audit()
    except Exception as exc:  # pragma: no cover - must not raise
        surfaces = [
            str(exc),
            repr(exc),
            str(exc.__cause__),
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        ]
        for text in surfaces:
            assert "/abs/path" not in text
            assert "token=" not in text
            assert "abcd1234" not in text
        raise AssertionError("audit_m3_readiness must not raise on Schema failure") from exc

    invalid = [i for i in issues if i.code == "BENCHMARK_INVALID"]
    assert invalid
    for item in invalid:
        assert "/abs/path" not in item.message
        assert "token=" not in item.message
        assert "traceback=" not in item.message
        assert "abcd1234" not in item.message
        assert secret not in item.message


# --- P1-C: Schema before source/benchmark Polars expressions ---


def _raw_benchmark_bars() -> pl.DataFrame:
    """合法精确八列，但不预先 Schema.validate（便于注入坏 dtype）。"""
    return _read("benchmark_bars_total_return.csv").select(
        [
            "benchmark",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "source",
            "source_snapshot_id",
        ]
    )


def test_p1c_exact_source_list_string_no_raise() -> None:
    """exact columns，source=List[String]：不抛异常，BENCHMARK_INVALID。"""
    base = _raw_benchmark_bars()
    bench = base.with_columns(
        pl.Series(
            "source",
            [["fixture"]] * base.height,
            dtype=pl.List(pl.String),
        )
    )
    assert set(bench.columns) == set(base.columns)
    issues = _audit(benchmark_bars=bench)
    assert "BENCHMARK_INVALID" in _codes(issues)
    assert all(isinstance(item, ReadinessIssue) for item in issues)


def test_p1c_exact_benchmark_list_string_no_raise() -> None:
    """exact columns，benchmark=List[String]：不抛异常，BENCHMARK_INVALID。"""
    base = _raw_benchmark_bars()
    bench = base.with_columns(
        pl.Series(
            "benchmark",
            [[BENCHMARK]] * base.height,
            dtype=pl.List(pl.String),
        )
    )
    issues = _audit(benchmark_bars=bench)
    assert "BENCHMARK_INVALID" in _codes(issues)
    assert all(isinstance(item, ReadinessIssue) for item in issues)


def test_p1c_exact_source_int32_no_raise() -> None:
    """exact columns，source=Int32：不抛；coercion 后与配置不匹配则按 source 语义报告。"""
    base = _raw_benchmark_bars()
    bench = base.with_columns(pl.lit(1).cast(pl.Int32).alias("source"))
    issues = _audit(benchmark_bars=bench)
    codes = _codes(issues)
    assert all(isinstance(item, ReadinessIssue) for item in issues)
    # 当前 Schema coerce Int32→"1"，与配置 source=fixture 不匹配
    assert "DATA_SOURCE_MISSING" in codes or "BENCHMARK_INVALID" in codes


def test_p1c_exact_benchmark_int32_no_raise() -> None:
    """exact columns，benchmark=Int32：不抛，按 Schema/identity 语义 fail-closed。"""
    base = _raw_benchmark_bars()
    bench = base.with_columns(pl.lit(1).cast(pl.Int32).alias("benchmark"))
    issues = _audit(benchmark_bars=bench)
    codes = _codes(issues)
    assert all(isinstance(item, ReadinessIssue) for item in issues)
    assert "BENCHMARK_INVALID" in codes or "BENCHMARK_SYMBOL_MISMATCH" in codes


def test_p1c_extra_column_plus_non_coercible_source_no_raise() -> None:
    """extra 未知列 + source 不可 coercion：不抛，至少 BENCHMARK_INVALID。"""
    base = _raw_benchmark_bars()
    bench = base.with_columns(
        pl.Series(
            "source",
            [["fixture"]] * base.height,
            dtype=pl.List(pl.String),
        ),
        pl.lit(1).alias("vendor_tag"),
    )
    issues = _audit(benchmark_bars=bench)
    assert "BENCHMARK_INVALID" in _codes(issues)
    assert all(isinstance(item, ReadinessIssue) for item in issues)


def test_p1c_extra_plus_valid_projection_and_missing_day() -> None:
    """extra + 合法 required 投影 + 缺交易日：同时 BENCHMARK_INVALID 与 DATE_COVERAGE。"""
    calendars = pl.DataFrame(
        {
            "market": ["SH", "SH"],
            "date": [dt.date(2026, 1, 5), dt.date(2026, 1, 6)],
            "is_open": [True, True],
            "is_connect_open": [False, False],
            "is_half_day": [False, False],
        }
    )
    membership = pl.DataFrame(
        {
            "universe": ["CSI300_PIT"],
            "symbol": ["000001.SZ"],
            "effective_from": [dt.date(2026, 1, 5)],
            "effective_to": [None],
        }
    )
    bars = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ"],
            "trade_date": [dt.date(2026, 1, 5), dt.date(2026, 1, 6)],
            "open": [10.0, 10.0],
            "high": [11.0, 11.0],
            "low": [9.0, 9.0],
            "close": [10.5, 10.5],
            "volume": [100.0, 100.0],
            "amount": [1000.0, 1000.0],
            "adj_factor": [1.0, 1.0],
            "source": ["fixture"] * 2,
        }
    )
    bench = pl.DataFrame(
        {
            "benchmark": [BENCHMARK],
            "trade_date": [dt.date(2026, 1, 5)],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "source": ["fixture"],
            "source_snapshot_id": ["snap"],
            "extra_flag": [1],
        }
    )
    codes = _codes(
        _audit(
            bars=bars,
            membership=membership,
            calendars=calendars,
            benchmark_bars=bench,
            config=_base_config(
                data={
                    "universe": "CSI300_PIT",
                    "benchmark": BENCHMARK,
                    "source": "fixture",
                    "start_date": dt.date(2026, 1, 5),
                    "end_date": dt.date(2026, 1, 6),
                    "minimum_train_sessions": 1,
                    "minimum_cross_section_symbols": 1,
                }
            ),
        )
    )
    assert "BENCHMARK_INVALID" in codes
    assert "BENCHMARK_DATE_COVERAGE" in codes


def test_p1c_consumes_schema_return_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    """可 coercion 输入必须证明下游消费 Schema 返回 frame，而非原 frame。"""
    import quant.research.m3.readiness as readiness

    base = _raw_benchmark_bars()
    # 原 frame source=Int32，直接 filter 会抛；返回 frame 使用规范 String
    tainted = base.with_columns(pl.lit(1).cast(pl.Int32).alias("source"))
    legal_return = base.with_columns(pl.lit("fixture").alias("source"))

    class _ReturnSchema:
        @staticmethod
        def validate(frame: pl.DataFrame) -> pl.DataFrame:
            assert frame["source"].dtype == pl.Int32
            return legal_return

    monkeypatch.setattr(readiness, "BenchmarkBar1dSchema", _ReturnSchema)

    dates = legal_return.get_column("trade_date").to_list()
    calendars = pl.DataFrame(
        {
            "market": ["SH"] * len(dates),
            "date": dates,
            "is_open": [True] * len(dates),
            "is_connect_open": [False] * len(dates),
            "is_half_day": [False] * len(dates),
        }
    )
    membership = pl.DataFrame(
        {
            "universe": ["CSI300_PIT"],
            "symbol": ["000001.SZ"],
            "effective_from": [min(dates)],
            "effective_to": [None],
        }
    )
    bars = pl.DataFrame(
        {
            "symbol": ["000001.SZ"] * len(dates),
            "trade_date": dates,
            "open": [10.0] * len(dates),
            "high": [11.0] * len(dates),
            "low": [9.0] * len(dates),
            "close": [10.5] * len(dates),
            "volume": [100.0] * len(dates),
            "amount": [1000.0] * len(dates),
            "adj_factor": [1.0] * len(dates),
            "source": ["fixture"] * len(dates),
        }
    )
    codes = _benchmark_codes(
        _audit(
            bars=bars,
            membership=membership,
            calendars=calendars,
            benchmark_bars=tainted,
            config=_base_config(
                data={
                    "universe": "CSI300_PIT",
                    "benchmark": BENCHMARK,
                    "source": "fixture",
                    "start_date": min(dates),
                    "end_date": max(dates),
                    "minimum_train_sessions": 1,
                    "minimum_cross_section_symbols": 1,
                }
            ),
        )
    )
    # 若误用原 Int32 frame，会在 source filter 抛异常；能跑完且无 benchmark 结构错误即证明消费返回值
    assert codes == set()


def test_p1c_schema_exception_four_surfaces_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Schema 异常含绝对路径/token 时，issue / cause / repr / traceback 四观察面不泄露。"""
    import traceback

    import quant.research.m3.readiness as readiness

    secret = "/home/leak/secret.token value=tok_LIVE_9f3a"

    class _BoomSchema:
        @staticmethod
        def validate(_frame: pl.DataFrame) -> pl.DataFrame:
            raise RuntimeError(secret)

    monkeypatch.setattr(readiness, "BenchmarkBar1dSchema", _BoomSchema)
    raised: BaseException | None = None
    try:
        issues = _audit(benchmark_bars=_raw_benchmark_bars())
    except BaseException as exc:  # pragma: no cover
        raised = exc
        issues = []

    if raised is not None:
        surfaces = [
            str(raised),
            repr(raised),
            str(getattr(raised, "__cause__", None)),
            "".join(
                traceback.format_exception(type(raised), raised, raised.__traceback__)
            ),
        ]
        for text in surfaces:
            assert "/home/leak" not in text
            assert "tok_LIVE_9f3a" not in text
            assert secret not in text
        raise AssertionError("must not raise") from raised

    for item in issues:
        assert "/home/leak" not in item.message
        assert "tok_LIVE_9f3a" not in item.message
        assert secret not in item.message
    assert "BENCHMARK_INVALID" in _codes(issues)
