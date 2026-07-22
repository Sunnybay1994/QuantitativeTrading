"""M1-X2: BarQuery universe window coverage unit tests."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.data.eligibility import EligibilityHistoryError
from quant.data.query import (
    AuditedBarWindow,
    BarQuery,
    BarWindowCoverage,
    BarWindowQueryError,
)


def _membership(
    path: Path,
    rows: list[tuple[str, str, dt.date, dt.date | None]],
    *,
    reverse: bool = False,
) -> Path:
    ordered = list(reversed(rows)) if reverse else rows
    frame = pl.DataFrame(
        {
            "universe": [row[0] for row in ordered],
            "symbol": [row[1] for row in ordered],
            "effective_from": [row[2] for row in ordered],
            "effective_to": [row[3] for row in ordered],
        },
        schema={
            "universe": pl.String,
            "symbol": pl.String,
            "effective_from": pl.Date,
            "effective_to": pl.Date,
        },
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)
    return path


def _write_day(
    root: Path,
    trade_date: dt.date,
    rows: list[tuple[str, str, float]],
) -> None:
    frame = pl.DataFrame(
        {
            "symbol": [row[0] for row in rows],
            "trade_date": [trade_date] * len(rows),
            "source": [row[1] for row in rows],
            "close": [row[2] for row in rows],
        }
    )
    out = root / f"date={trade_date.isoformat()}" / "data.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(out)


def _dates(n: int, end: dt.date) -> list[dt.date]:
    return [end - dt.timedelta(days=offset) for offset in range(n - 1, -1, -1)]


def test_coverage_short_missing_and_legacy_compat(tmp_path: Path) -> None:
    membership = _membership(
        tmp_path / "membership.parquet",
        [
            ("SH_CONNECT", "00700.HK", dt.date(2026, 1, 1), None),
            ("SH_CONNECT", "00001.HK", dt.date(2026, 1, 1), None),
            ("SH_CONNECT", "00388.HK", dt.date(2026, 1, 1), None),
        ],
    )
    bar_root = tmp_path / "bar_1d"
    as_of = dt.date(2026, 3, 10)
    full_days = set(_dates(60, as_of))
    short_days = set(_dates(59, as_of))
    for day in sorted(full_days):
        rows: list[tuple[str, str, float]] = [("00700.HK", "tushare", 1.0)]
        if day in short_days:
            rows.append(("00001.HK", "tushare", 2.0))
        _write_day(bar_root, day, rows)

    query = BarQuery(bar_root)
    legacy = query.recent_for_universe(
        membership_path=membership,
        universe="SH_CONNECT",
        as_of=as_of,
        source="tushare",
        observations=60,
    )
    audited = query.recent_for_universe_audited(
        membership_path=membership,
        universe="SH_CONNECT",
        as_of=as_of,
        source="tushare",
        observations=60,
    )
    assert isinstance(audited, AuditedBarWindow)
    assert isinstance(audited.coverage, BarWindowCoverage)
    assert audited.coverage.eligible_symbol_count == 3
    assert audited.coverage.returned_symbol_count == 2
    assert audited.coverage.missing_symbols == ("00388.HK",)
    assert audited.coverage.short_symbol_counts == (("00001.HK", 59),)
    assert audited.coverage.min_observations == 0
    assert audited.coverage.max_observations == 60
    assert audited.coverage.is_full_window is False
    assert set(audited.frame.get_column("symbol").unique().to_list()) == {
        "00001.HK",
        "00700.HK",
    }
    assert legacy.height == audited.frame.height
    assert legacy.select(sorted(legacy.columns)).sort(
        ["symbol", "trade_date"]
    ).equals(
        audited.frame.select(sorted(audited.frame.columns)).sort(
            ["symbol", "trade_date"]
        )
    )


def test_no_bar_files_keeps_eligible_and_all_missing(tmp_path: Path) -> None:
    membership = _membership(
        tmp_path / "membership.parquet",
        [
            ("SH_CONNECT", "00700.HK", dt.date(2026, 1, 1), None),
            ("SH_CONNECT", "00001.HK", dt.date(2026, 1, 1), None),
            ("SH_CONNECT", "00388.HK", dt.date(2026, 1, 1), None),
        ],
    )
    audited = BarQuery(tmp_path / "bar_1d").recent_for_universe_audited(
        membership_path=membership,
        universe="SH_CONNECT",
        as_of=dt.date(2026, 3, 10),
        source="tushare",
        observations=60,
    )
    assert audited.frame.height == 0
    assert audited.coverage.eligible_symbol_count == 3
    assert audited.coverage.returned_symbol_count == 0
    assert audited.coverage.missing_symbols == ("00001.HK", "00388.HK", "00700.HK")
    assert audited.coverage.short_symbol_counts == ()
    assert audited.coverage.min_observations == 0
    assert audited.coverage.max_observations == 0


def test_duplicate_symbol_date_source_fails_closed(tmp_path: Path) -> None:
    membership = _membership(
        tmp_path / "membership.parquet",
        [("SH_CONNECT", "00700.HK", dt.date(2026, 1, 1), None)],
    )
    bar_root = tmp_path / "bar_1d"
    day = dt.date(2026, 3, 10)
    _write_day(
        bar_root,
        day,
        [("00700.HK", "tushare", 1.0), ("00700.HK", "tushare", 1.1)],
    )
    with pytest.raises(BarWindowQueryError, match="BAR_WINDOW_DUPLICATE_KEY"):
        BarQuery(bar_root).recent_for_universe_audited(
            membership_path=membership,
            universe="SH_CONNECT",
            as_of=day,
            source="tushare",
            observations=60,
        )


def test_other_source_and_future_rows_excluded(tmp_path: Path) -> None:
    membership = _membership(
        tmp_path / "membership.parquet",
        [("SH_CONNECT", "00700.HK", dt.date(2026, 1, 1), None)],
    )
    bar_root = tmp_path / "bar_1d"
    as_of = dt.date(2026, 3, 10)
    _write_day(
        bar_root,
        as_of,
        [("00700.HK", "tushare", 1.0), ("00700.HK", "other", 9.0)],
    )
    _write_day(
        bar_root,
        as_of + dt.timedelta(days=1),
        [("00700.HK", "tushare", 2.0)],
    )
    audited = BarQuery(bar_root).recent_for_universe_audited(
        membership_path=membership,
        universe="SH_CONNECT",
        as_of=as_of,
        source="tushare",
        observations=60,
    )
    assert audited.frame.height == 1
    assert audited.frame.get_column("close").to_list() == [1.0]
    assert audited.coverage.returned_symbol_count == 1
    assert audited.coverage.max_observations == 1

    _write_day(
        bar_root,
        as_of - dt.timedelta(days=1),
        [("00700.HK", "tushare", 0.5), ("00700.HK", "tushare", 0.6)],
    )
    with pytest.raises(BarWindowQueryError, match="BAR_WINDOW_DUPLICATE_KEY"):
        BarQuery(bar_root).recent_for_universe_audited(
            membership_path=membership,
            universe="SH_CONNECT",
            as_of=as_of,
            source="tushare",
            observations=60,
        )


def test_membership_and_bar_order_do_not_change_result(tmp_path: Path) -> None:
    rows = [
        ("SH_CONNECT", "00388.HK", dt.date(2026, 1, 1), None),
        ("SH_CONNECT", "00700.HK", dt.date(2026, 1, 1), None),
        ("SH_CONNECT", "00001.HK", dt.date(2026, 1, 1), None),
    ]
    membership_a = _membership(tmp_path / "a.parquet", rows)
    membership_b = _membership(tmp_path / "b.parquet", rows, reverse=True)
    as_of = dt.date(2026, 3, 10)
    bar_root_a = tmp_path / "bars_a"
    bar_root_b = tmp_path / "bars_b"
    for day in _dates(3, as_of):
        _write_day(
            bar_root_a,
            day,
            [
                ("00001.HK", "tushare", 1.0),
                ("00388.HK", "tushare", 2.0),
                ("00700.HK", "tushare", 3.0),
            ],
        )
        _write_day(
            bar_root_b,
            day,
            [
                ("00700.HK", "tushare", 3.0),
                ("00001.HK", "tushare", 1.0),
                ("00388.HK", "tushare", 2.0),
            ],
        )
    left = BarQuery(bar_root_a).recent_for_universe_audited(
        membership_path=membership_a,
        universe="SH_CONNECT",
        as_of=as_of,
        source="tushare",
        observations=3,
    )
    right = BarQuery(bar_root_b).recent_for_universe_audited(
        membership_path=membership_b,
        universe="SH_CONNECT",
        as_of=as_of,
        source="tushare",
        observations=3,
    )
    assert left.coverage == right.coverage
    assert left.frame.select(["symbol", "trade_date", "source", "close"]).equals(
        right.frame.select(["symbol", "trade_date", "source", "close"])
    )


def test_pre_baseline_as_of_fails_closed(tmp_path: Path) -> None:
    membership = _membership(
        tmp_path / "membership.parquet",
        [("SH_CONNECT", "00700.HK", dt.date(2026, 1, 10), None)],
    )
    bar_root = tmp_path / "bar_1d"
    _write_day(
        bar_root,
        dt.date(2026, 1, 9),
        [("00700.HK", "tushare", 1.0)],
    )
    with pytest.raises(EligibilityHistoryError):
        BarQuery(bar_root).recent_for_universe_audited(
            membership_path=membership,
            universe="SH_CONNECT",
            as_of=dt.date(2026, 1, 9),
            source="tushare",
            observations=60,
        )


def test_missing_membership_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        BarQuery(tmp_path / "bar_1d").recent_for_universe_audited(
            membership_path=tmp_path / "missing.parquet",
            universe="SH_CONNECT",
            as_of=dt.date(2026, 3, 10),
            source="tushare",
            observations=60,
        )


def test_observations_rejects_bool_and_float(tmp_path: Path) -> None:
    membership = _membership(
        tmp_path / "membership.parquet",
        [("SH_CONNECT", "00700.HK", dt.date(2026, 1, 1), None)],
    )
    query = BarQuery(tmp_path / "bar_1d")
    with pytest.raises(BarWindowQueryError, match="BAR_WINDOW_INPUT_INVALID"):
        query.recent_for_universe_audited(
            membership_path=membership,
            universe="SH_CONNECT",
            as_of=dt.date(2026, 3, 10),
            source="tushare",
            observations=True,  # type: ignore[arg-type]
        )
    with pytest.raises(BarWindowQueryError, match="BAR_WINDOW_INPUT_INVALID"):
        query.recent_for_universe_audited(
            membership_path=membership,
            universe="SH_CONNECT",
            as_of=dt.date(2026, 3, 10),
            source="tushare",
            observations=60.0,  # type: ignore[arg-type]
        )


def _coverage_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "universe": "SH_CONNECT",
        "as_of": dt.date(2026, 7, 18),
        "source": "tushare",
        "requested_observations": 2,
        "eligible_symbol_count": 1,
        "returned_symbol_count": 1,
        "missing_symbols": (),
        "short_symbol_counts": (),
        "min_observations": 2,
        "max_observations": 2,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "overrides",
    [
        # min/max exceed requested; is_full_window would otherwise be True
        {
            "requested_observations": 2,
            "eligible_symbol_count": 1,
            "returned_symbol_count": 1,
            "missing_symbols": (),
            "short_symbol_counts": (),
            "min_observations": 3,
            "max_observations": 3,
        },
        # no missing/short but min/max below requested
        {
            "requested_observations": 60,
            "eligible_symbol_count": 1,
            "returned_symbol_count": 1,
            "missing_symbols": (),
            "short_symbol_counts": (),
            "min_observations": 59,
            "max_observations": 59,
        },
        # returned=0 but missing does not cover all eligible
        {
            "requested_observations": 60,
            "eligible_symbol_count": 3,
            "returned_symbol_count": 0,
            "missing_symbols": ("00001.HK", "00388.HK"),
            "short_symbol_counts": (),
            "min_observations": 0,
            "max_observations": 0,
        },
        # full+short coexist but max equals short count instead of requested
        {
            "requested_observations": 60,
            "eligible_symbol_count": 2,
            "returned_symbol_count": 2,
            "missing_symbols": (),
            "short_symbol_counts": (("00001.HK", 59),),
            "min_observations": 59,
            "max_observations": 59,
        },
        # max exceeds requested with missing present
        {
            "requested_observations": 2,
            "eligible_symbol_count": 2,
            "returned_symbol_count": 1,
            "missing_symbols": ("00388.HK",),
            "short_symbol_counts": (),
            "min_observations": 0,
            "max_observations": 3,
        },
        # len(short) > returned
        {
            "requested_observations": 60,
            "eligible_symbol_count": 1,
            "returned_symbol_count": 1,
            "missing_symbols": (),
            "short_symbol_counts": (("00001.HK", 1), ("00700.HK", 2)),
            "min_observations": 1,
            "max_observations": 2,
        },
        # missing non-empty but min != 0
        {
            "requested_observations": 60,
            "eligible_symbol_count": 2,
            "returned_symbol_count": 1,
            "missing_symbols": ("00388.HK",),
            "short_symbol_counts": (),
            "min_observations": 60,
            "max_observations": 60,
        },
    ],
    ids=[
        "min_max_exceed_requested",
        "full_claimed_but_short_minmax",
        "returned_zero_incomplete_missing",
        "full_plus_short_max_is_short",
        "max_gt_requested_with_missing",
        "short_len_gt_returned",
        "missing_nonzero_min",
    ],
)
def test_bar_window_coverage_rejects_inconsistent_manual_construction(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(BarWindowQueryError, match="BAR_WINDOW_INPUT_INVALID"):
        BarWindowCoverage(**_coverage_kwargs(**overrides))  # type: ignore[arg-type]


def test_bar_window_coverage_accepts_consistent_full_and_short_mix() -> None:
    coverage = BarWindowCoverage(
        **_coverage_kwargs(  # type: ignore[arg-type]
            requested_observations=60,
            eligible_symbol_count=2,
            returned_symbol_count=2,
            missing_symbols=(),
            short_symbol_counts=(("00001.HK", 59),),
            min_observations=59,
            max_observations=60,
        )
    )
    assert coverage.is_full_window is False
    assert coverage.max_observations == 60


@pytest.mark.parametrize(
    ("field", "bad_symbol"),
    [
        ("missing_symbols", ""),
        ("missing_symbols", "not-a-symbol"),
        ("missing_symbols", "00700.US"),
        ("missing_symbols", "700.HK"),
        ("short_symbol_counts", ""),
        ("short_symbol_counts", "not-a-symbol"),
        ("short_symbol_counts", "00700.US"),
        ("short_symbol_counts", "600000.XX"),
    ],
    ids=[
        "missing_empty",
        "missing_non_canonical",
        "missing_wrong_suffix",
        "missing_too_short",
        "short_empty",
        "short_non_canonical",
        "short_wrong_suffix",
        "short_bad_market",
    ],
)
def test_bar_window_coverage_rejects_non_canonical_symbols(
    field: str,
    bad_symbol: str,
) -> None:
    if field == "missing_symbols":
        overrides: dict[str, object] = {
            "requested_observations": 2,
            "eligible_symbol_count": 1,
            "returned_symbol_count": 0,
            "missing_symbols": (bad_symbol,),
            "short_symbol_counts": (),
            "min_observations": 0,
            "max_observations": 0,
        }
    else:
        overrides = {
            "requested_observations": 2,
            "eligible_symbol_count": 1,
            "returned_symbol_count": 1,
            "missing_symbols": (),
            "short_symbol_counts": ((bad_symbol, 1),),
            "min_observations": 1,
            "max_observations": 1,
        }
    with pytest.raises(BarWindowQueryError, match="BAR_WINDOW_INPUT_INVALID"):
        BarWindowCoverage(**_coverage_kwargs(**overrides))  # type: ignore[arg-type]


def test_bar_window_coverage_accepts_canonical_a_and_h_symbols() -> None:
    coverage = BarWindowCoverage(
        **_coverage_kwargs(  # type: ignore[arg-type]
            requested_observations=2,
            eligible_symbol_count=3,
            returned_symbol_count=2,
            missing_symbols=("600000.SH",),
            short_symbol_counts=(("00700.HK", 1),),
            min_observations=0,
            max_observations=2,
        )
    )
    assert coverage.missing_symbols == ("600000.SH",)
    assert coverage.short_symbol_counts == (("00700.HK", 1),)
    assert coverage.is_full_window is False


def _bar_frame(
    rows: list[tuple[str, dt.date, str]],
    *,
    schema_overrides: dict[str, pl.DataType] | None = None,
) -> pl.DataFrame:
    schema: dict[str, pl.DataType] = {
        "symbol": pl.String,
        "trade_date": pl.Date,
        "source": pl.String,
    }
    if schema_overrides:
        schema.update(schema_overrides)
    return pl.DataFrame(
        {
            "symbol": [row[0] for row in rows],
            "trade_date": [row[1] for row in rows],
            "source": [row[2] for row in rows],
        },
        schema=schema,
    )


def test_audited_bar_window_rejects_full_coverage_with_empty_frame() -> None:
    coverage = BarWindowCoverage(**_coverage_kwargs())  # type: ignore[arg-type]
    assert coverage.is_full_window is True
    with pytest.raises(BarWindowQueryError, match="BAR_WINDOW_INPUT_INVALID"):
        AuditedBarWindow(frame=pl.DataFrame(), coverage=coverage)


def test_audited_bar_window_rejects_missing_required_columns() -> None:
    coverage = BarWindowCoverage(**_coverage_kwargs())  # type: ignore[arg-type]
    frame = pl.DataFrame(
        {
            "symbol": ["00700.HK", "00700.HK"],
            "trade_date": [dt.date(2026, 7, 17), dt.date(2026, 7, 18)],
        },
        schema={"symbol": pl.String, "trade_date": pl.Date},
    )
    with pytest.raises(BarWindowQueryError, match="BAR_WINDOW_INPUT_INVALID"):
        AuditedBarWindow(frame=frame, coverage=coverage)


def test_audited_bar_window_rejects_wrong_dtype_without_cast() -> None:
    coverage = BarWindowCoverage(**_coverage_kwargs())  # type: ignore[arg-type]
    frame = _bar_frame(
        [
            ("00700.HK", dt.date(2026, 7, 17), "tushare"),
            ("00700.HK", dt.date(2026, 7, 18), "tushare"),
        ],
        schema_overrides={"trade_date": pl.Datetime("us")},
    )
    with pytest.raises(BarWindowQueryError, match="BAR_WINDOW_INPUT_INVALID"):
        AuditedBarWindow(frame=frame, coverage=coverage)


def test_audited_bar_window_rejects_unsorted_payload() -> None:
    coverage = BarWindowCoverage(**_coverage_kwargs())  # type: ignore[arg-type]
    frame = _bar_frame(
        [
            ("00700.HK", dt.date(2026, 7, 18), "tushare"),
            ("00700.HK", dt.date(2026, 7, 17), "tushare"),
        ]
    )
    with pytest.raises(BarWindowQueryError, match="BAR_WINDOW_INPUT_INVALID"):
        AuditedBarWindow(frame=frame, coverage=coverage)


def test_audited_bar_window_rejects_duplicate_key_rows() -> None:
    coverage = BarWindowCoverage(**_coverage_kwargs())  # type: ignore[arg-type]
    frame = _bar_frame(
        [
            ("00700.HK", dt.date(2026, 7, 17), "tushare"),
            ("00700.HK", dt.date(2026, 7, 17), "tushare"),
        ]
    )
    with pytest.raises(BarWindowQueryError, match="BAR_WINDOW_INPUT_INVALID"):
        AuditedBarWindow(frame=frame, coverage=coverage)


def test_audited_bar_window_rejects_future_or_foreign_source_rows() -> None:
    coverage = BarWindowCoverage(**_coverage_kwargs())  # type: ignore[arg-type]
    future = _bar_frame(
        [
            ("00700.HK", dt.date(2026, 7, 17), "tushare"),
            ("00700.HK", dt.date(2026, 7, 19), "tushare"),
        ]
    )
    foreign = _bar_frame(
        [
            ("00700.HK", dt.date(2026, 7, 17), "tushare"),
            ("00700.HK", dt.date(2026, 7, 18), "other"),
        ]
    )
    with pytest.raises(BarWindowQueryError, match="BAR_WINDOW_INPUT_INVALID"):
        AuditedBarWindow(frame=future, coverage=coverage)
    with pytest.raises(BarWindowQueryError, match="BAR_WINDOW_INPUT_INVALID"):
        AuditedBarWindow(frame=foreign, coverage=coverage)


def test_audited_bar_window_rejects_short_symbol_identity_mismatch() -> None:
    coverage = BarWindowCoverage(
        **_coverage_kwargs(  # type: ignore[arg-type]
            requested_observations=2,
            eligible_symbol_count=1,
            returned_symbol_count=1,
            missing_symbols=(),
            short_symbol_counts=(("00001.HK", 1),),
            min_observations=1,
            max_observations=1,
        )
    )
    frame = _bar_frame([("00700.HK", dt.date(2026, 7, 18), "tushare")])
    with pytest.raises(BarWindowQueryError, match="BAR_WINDOW_INPUT_INVALID"):
        AuditedBarWindow(frame=frame, coverage=coverage)


def test_audited_bar_window_rejects_forged_returned_count() -> None:
    coverage = BarWindowCoverage(
        **_coverage_kwargs(  # type: ignore[arg-type]
            requested_observations=2,
            eligible_symbol_count=3,
            returned_symbol_count=3,
            missing_symbols=(),
            short_symbol_counts=(("00001.HK", 1),),
            min_observations=1,
            max_observations=2,
        )
    )
    frame = _bar_frame(
        [
            ("00001.HK", dt.date(2026, 7, 18), "tushare"),
            ("00700.HK", dt.date(2026, 7, 17), "tushare"),
            ("00700.HK", dt.date(2026, 7, 18), "tushare"),
        ]
    )
    with pytest.raises(BarWindowQueryError, match="BAR_WINDOW_INPUT_INVALID"):
        AuditedBarWindow(frame=frame, coverage=coverage)


def test_audited_bar_window_accepts_consistent_full_window_frame() -> None:
    coverage = BarWindowCoverage(**_coverage_kwargs())  # type: ignore[arg-type]
    frame = _bar_frame(
        [
            ("00700.HK", dt.date(2026, 7, 17), "tushare"),
            ("00700.HK", dt.date(2026, 7, 18), "tushare"),
        ]
    )
    audited = AuditedBarWindow(frame=frame, coverage=coverage)
    assert audited.coverage.is_full_window is True
    assert audited.frame.height == 2


def test_audited_bar_window_accepts_empty_and_all_missing_bindings() -> None:
    empty = BarWindowCoverage(
        **_coverage_kwargs(  # type: ignore[arg-type]
            requested_observations=2,
            eligible_symbol_count=0,
            returned_symbol_count=0,
            missing_symbols=(),
            short_symbol_counts=(),
            min_observations=0,
            max_observations=0,
        )
    )
    all_missing = BarWindowCoverage(
        **_coverage_kwargs(  # type: ignore[arg-type]
            requested_observations=2,
            eligible_symbol_count=1,
            returned_symbol_count=0,
            missing_symbols=("00700.HK",),
            short_symbol_counts=(),
            min_observations=0,
            max_observations=0,
        )
    )
    assert AuditedBarWindow(frame=pl.DataFrame(), coverage=empty).frame.height == 0
    assert (
        AuditedBarWindow(frame=pl.DataFrame(), coverage=all_missing).frame.height == 0
    )
