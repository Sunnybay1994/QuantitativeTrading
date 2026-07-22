"""L0 / D3: forward relative labels with eligible_keys and diagnostics."""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import polars as pl
import pytest

from quant.domain import BenchmarkBar1dSchema, ForwardReturnLabelSchema
from quant.research.m3.labels import LabelBuildResult, compute_forward_relative_labels

FIXTURE_ROOT = Path("tests/fixtures/m3")
BENCHMARK = "H00300.CSI"
LABEL_VERSION = "next_open_to_h_close_relative_v1"


def _read(name: str) -> pl.DataFrame:
    return pl.read_csv(FIXTURE_ROOT / name, try_parse_dates=True)


def _benchmark_bars(**overrides: object) -> pl.DataFrame:
    """Build a BenchmarkBar1d frame; defaults mirror the total-return fixture OHLC."""
    rows = [
        {
            "benchmark": BENCHMARK,
            "trade_date": dt.date(2026, 1, 5),
            "open": 99.5,
            "high": 100.5,
            "low": 99.0,
            "close": 100.0,
            "source": "fixture",
            "source_snapshot_id": "snap_fixture",
        },
        {
            "benchmark": BENCHMARK,
            "trade_date": dt.date(2026, 1, 6),
            "open": 100.0,
            "high": 101.0,
            "low": 99.5,
            "close": 100.5,
            "source": "fixture",
            "source_snapshot_id": "snap_fixture",
        },
        {
            "benchmark": BENCHMARK,
            "trade_date": dt.date(2026, 1, 12),
            "open": 104.5,
            "high": 105.5,
            "low": 104.0,
            "close": 105.0,
            "source": "fixture",
            "source_snapshot_id": "snap_fixture",
        },
        {
            "benchmark": BENCHMARK,
            "trade_date": dt.date(2026, 1, 19),
            "open": 109.5,
            "high": 110.5,
            "low": 109.0,
            "close": 110.0,
            "source": "fixture",
            "source_snapshot_id": "snap_fixture",
        },
    ]
    if overrides:
        rows = [{**row, **overrides} for row in rows]
    return BenchmarkBar1dSchema.validate(pl.DataFrame(rows))


def _eligible(*pairs: tuple[dt.date, str]) -> pl.DataFrame:
    return pl.DataFrame(
        {"as_of": [p[0] for p in pairs], "symbol": [p[1] for p in pairs]}
    )


def _golden_eligible() -> pl.DataFrame:
    as_of = dt.date(2026, 1, 5)
    return _eligible(
        (as_of, "000001.SZ"),
        (as_of, "000002.SZ"),
        (as_of, "000003.SZ"),
    )


def _build(
    *,
    bars: pl.DataFrame | None = None,
    benchmark_bars: pl.DataFrame | None = None,
    eligible_keys: pl.DataFrame | None = None,
    calendars: pl.DataFrame | None = None,
    horizons: list[int] | None = None,
    benchmark: str = BENCHMARK,
    label_version: str = LABEL_VERSION,
) -> LabelBuildResult:
    return compute_forward_relative_labels(
        bars=_read("bars.csv") if bars is None else bars,
        benchmark_bars=(
            _read("benchmark_bars_total_return.csv")
            if benchmark_bars is None
            else benchmark_bars
        ),
        eligible_keys=_golden_eligible() if eligible_keys is None else eligible_keys,
        calendars=_read("calendar.csv") if calendars is None else calendars,
        horizons=[5, 10] if horizons is None else horizons,
        benchmark=benchmark,
        label_version=label_version,
    )


def _assert_conservation(result: LabelBuildResult, eligible_keys: pl.DataFrame, horizons: list[int]) -> None:
    expected = eligible_keys.height * len(horizons)
    diag_sum = int(result.diagnostics.get_column("sample_count").sum() or 0)
    assert result.labels.height + diag_sum == expected


def test_labels_match_golden_fixture() -> None:
    result = _build()
    expected = _read("expected_labels.csv")
    ForwardReturnLabelSchema.validate(result.labels)
    got = result.labels.sort(["as_of", "horizon_sessions", "symbol"])
    exp = expected.sort(["as_of", "horizon_sessions", "symbol"])
    key_cols = [
        "as_of",
        "symbol",
        "benchmark",
        "horizon_sessions",
        "return_start_date",
        "return_end_date",
        "available_as_of",
        "label_version",
    ]
    assert got.select(key_cols).equals(exp.select(key_cols))
    for col in ("raw_return", "benchmark_return", "relative_return"):
        for left, right in zip(
            got.get_column(col).to_list(), exp.get_column(col).to_list(), strict=True
        ):
            assert left == pytest.approx(right, abs=1e-10)
    _assert_conservation(result, _golden_eligible(), [5, 10])
    assert result.diagnostics.is_empty()


def test_suspended_missing_entry_price_is_dropped() -> None:
    eligible = _eligible(
        (dt.date(2026, 1, 5), "000001.SZ"),
        (dt.date(2026, 1, 5), "000004.SZ"),
    )
    result = _build(eligible_keys=eligible, horizons=[5])
    assert "000004.SZ" not in result.labels.get_column("symbol").unique().to_list()
    diag = result.diagnostics.filter(pl.col("reason") == "ASSET_ENTRY_BAR_MISSING")
    assert diag.height == 1
    assert diag.item(0, "sample_count") == 1
    _assert_conservation(result, eligible, [5])


def test_duplicate_bars_rejected() -> None:
    bars = pl.concat([_read("bars.csv"), _read("bars.csv").head(1)])
    with pytest.raises(ValueError, match="重复"):
        _build(bars=bars, horizons=[5])


def test_duplicate_benchmark_bars_rejected() -> None:
    base = _read("benchmark_bars_total_return.csv")
    dup = base.head(1).with_columns(pl.lit("other_source").alias("source"))
    bench = pl.concat([base, dup])
    with pytest.raises(ValueError, match="重复"):
        _build(benchmark_bars=bench, horizons=[5])


def test_tail_without_full_horizon_omitted() -> None:
    eligible = _eligible((dt.date(2026, 1, 16), "000001.SZ"))
    result = _build(eligible_keys=eligible, horizons=[10])
    assert result.labels.is_empty()
    assert result.diagnostics.item(0, "reason") == "TAIL_INCOMPLETE"
    _assert_conservation(result, eligible, [10])


def test_cross_holiday_uses_session_offset_not_calendar_days() -> None:
    result = _build(horizons=[5])
    row = result.labels.filter(
        (pl.col("symbol") == "000001.SZ") & (pl.col("horizon_sessions") == 5)
    ).row(0, named=True)
    assert row["return_end_date"].isoformat() == "2026-01-12"
    assert row["relative_return"] == pytest.approx(0.05, abs=1e-10)


def test_corporate_action_adj_factor_hand_calc() -> None:
    """entry open=100 factor=1; exit close=50 factor=2 → raw_return=0 not -0.5."""
    as_of = dt.date(2026, 1, 5)
    entry = dt.date(2026, 1, 6)
    exit_date = dt.date(2026, 1, 12)
    bars = pl.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "trade_date": entry,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1.0,
                "amount": 1.0,
                "adj_factor": 1.0,
                "source": "fixture",
            },
            {
                "symbol": "000001.SZ",
                "trade_date": exit_date,
                "open": 50.0,
                "high": 51.0,
                "low": 49.0,
                "close": 50.0,
                "volume": 1.0,
                "amount": 1.0,
                "adj_factor": 2.0,
                "source": "fixture",
            },
        ]
    )
    result = _build(
        bars=bars,
        eligible_keys=_eligible((as_of, "000001.SZ")),
        horizons=[5],
    )
    assert result.labels.height == 1
    assert result.labels.item(0, "raw_return") == pytest.approx(0.0, abs=1e-12)
    assert result.labels.item(0, "raw_return") != pytest.approx(-0.5, abs=1e-6)


def test_invalid_entry_factor_diagnostics() -> None:
    bars = _read("bars.csv").with_columns(
        pl.when(
            (pl.col("symbol") == "000001.SZ")
            & (pl.col("trade_date") == dt.date(2026, 1, 6))
        )
        .then(pl.lit(float("nan")))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    eligible = _eligible((dt.date(2026, 1, 5), "000001.SZ"))
    result = _build(bars=bars, eligible_keys=eligible, horizons=[5])
    assert result.labels.is_empty()
    assert result.diagnostics.item(0, "reason") == "ASSET_ENTRY_FACTOR_INVALID"
    _assert_conservation(result, eligible, [5])


def test_invalid_exit_factor_diagnostics() -> None:
    bars = _read("bars.csv").with_columns(
        pl.when(
            (pl.col("symbol") == "000001.SZ")
            & (pl.col("trade_date") == dt.date(2026, 1, 12))
        )
        .then(pl.lit(0.0))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    eligible = _eligible((dt.date(2026, 1, 5), "000001.SZ"))
    result = _build(bars=bars, eligible_keys=eligible, horizons=[5])
    assert result.labels.is_empty()
    assert result.diagnostics.item(0, "reason") == "ASSET_EXIT_FACTOR_INVALID"
    _assert_conservation(result, eligible, [5])


def test_benchmark_ignores_stock_adj_factor() -> None:
    """Benchmark return uses raw index points only; stock factor changes raw_return."""
    bars = _read("bars.csv").with_columns(
        pl.when(
            (pl.col("symbol") == "000001.SZ")
            & (pl.col("trade_date") == dt.date(2026, 1, 12))
        )
        .then(pl.lit(2.0))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    result = _build(
        bars=bars,
        eligible_keys=_eligible((dt.date(2026, 1, 5), "000001.SZ")),
        horizons=[5],
    )
    row = result.labels.row(0, named=True)
    # unadjusted would be 11/10-1=0.1; with exit factor 2 → (11*2)/(10*1)-1=1.2
    assert row["raw_return"] == pytest.approx(1.2, abs=1e-12)
    assert row["benchmark_return"] == pytest.approx(0.05, abs=1e-12)


def test_benchmark_entry_and_exit_missing_diagnostics() -> None:
    eligible = _eligible((dt.date(2026, 1, 5), "000001.SZ"))
    missing_entry = _benchmark_bars().filter(pl.col("trade_date") != dt.date(2026, 1, 6))
    result_entry = _build(
        benchmark_bars=missing_entry, eligible_keys=eligible, horizons=[5]
    )
    assert result_entry.diagnostics.item(0, "reason") == "BENCHMARK_ENTRY_MISSING"

    missing_exit = _benchmark_bars().filter(pl.col("trade_date") != dt.date(2026, 1, 12))
    result_exit = _build(
        benchmark_bars=missing_exit, eligible_keys=eligible, horizons=[5]
    )
    assert result_exit.diagnostics.item(0, "reason") == "BENCHMARK_EXIT_MISSING"
    _assert_conservation(result_entry, eligible, [5])
    _assert_conservation(result_exit, eligible, [5])


def test_asset_exit_bar_missing_diagnostics() -> None:
    bars = _read("bars.csv").filter(
        ~(
            (pl.col("symbol") == "000001.SZ")
            & (pl.col("trade_date") == dt.date(2026, 1, 12))
        )
    )
    eligible = _eligible((dt.date(2026, 1, 5), "000001.SZ"))
    result = _build(bars=bars, eligible_keys=eligible, horizons=[5])
    assert result.diagnostics.item(0, "reason") == "ASSET_EXIT_BAR_MISSING"
    _assert_conservation(result, eligible, [5])


def test_diagnostics_conservation_across_reason_classes() -> None:
    """Each (eligible, horizon) lands in labels or exactly one first-hit reason."""
    as_of = dt.date(2026, 1, 5)
    eligible = _eligible(
        (as_of, "000001.SZ"),  # success for h=5; h=10 success too with full benches
        (as_of, "000004.SZ"),  # entry missing
        (dt.date(2026, 1, 16), "000001.SZ"),  # tail for h=10
    )
    bars = _read("bars.csv").with_columns(
        pl.when(
            (pl.col("symbol") == "000002.SZ")
            & (pl.col("trade_date") == dt.date(2026, 1, 6))
        )
        .then(pl.lit(-1.0))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    # Include an invalid-factor symbol only when present in eligible
    eligible = pl.concat(
        [eligible, _eligible((as_of, "000002.SZ"))]
    )
    result = _build(bars=bars, eligible_keys=eligible, horizons=[5, 10])
    reasons = set(result.diagnostics.get_column("reason").to_list())
    assert "ASSET_ENTRY_BAR_MISSING" in reasons
    assert "TAIL_INCOMPLETE" in reasons
    assert "ASSET_ENTRY_FACTOR_INVALID" in reasons
    _assert_conservation(result, eligible, [5, 10])
    # No overlapping assignment: every diag reason count is positive int
    assert result.diagnostics.filter(pl.col("sample_count") <= 0).is_empty()


def test_rejects_foreign_benchmark_in_frame() -> None:
    foreign = _benchmark_bars().with_columns(pl.lit("000300.SH").alias("benchmark"))
    with pytest.raises(ValueError, match="只含显式基准"):
        _build(benchmark_bars=foreign, horizons=[5])


def test_non_finite_returns_rejected_by_schema() -> None:
    with pytest.raises(Exception):
        ForwardReturnLabelSchema.validate(
            pl.DataFrame(
                [
                    {
                        "as_of": dt.date(2026, 1, 5),
                        "symbol": "000001.SZ",
                        "benchmark": BENCHMARK,
                        "horizon_sessions": 5,
                        "return_start_date": dt.date(2026, 1, 6),
                        "return_end_date": dt.date(2026, 1, 12),
                        "available_as_of": dt.date(2026, 1, 12),
                        "raw_return": math.nan,
                        "benchmark_return": 0.01,
                        "relative_return": math.nan,
                        "label_version": "v",
                    }
                ]
            )
        )
