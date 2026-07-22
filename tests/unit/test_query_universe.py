"""M1-X2: query_universe CLI coverage and strict gate tests."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import polars as pl

from quant.data.query_universe import main


def _ensure_bar(
    bar_root: Path,
    day: dt.date,
    rows: list[tuple[str, str, float]],
) -> Path:
    out = bar_root / f"date={day.isoformat()}" / "data.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "symbol": [row[0] for row in rows],
            "trade_date": [day] * len(rows),
            "source": [row[1] for row in rows],
            "close": [row[2] for row in rows],
        }
    ).write_parquet(out)
    return out


def _write_membership(data_root: Path, symbols: list[str]) -> None:
    membership_dir = data_root / "clean" / "universe_membership" / "universe=SH_CONNECT"
    membership_dir.mkdir(parents=True)
    pl.DataFrame(
        {
            "universe": ["SH_CONNECT"] * len(symbols),
            "symbol": symbols,
            "effective_from": [dt.date(2026, 1, 1)] * len(symbols),
            "effective_to": [None] * len(symbols),
        },
        schema={
            "universe": pl.String,
            "symbol": pl.String,
            "effective_from": pl.Date,
            "effective_to": pl.Date,
        },
    ).write_parquet(membership_dir / "data.parquet")


def _write_hk_references(
    data_root: Path,
    *,
    calendar_rows: list[tuple[dt.date, bool]],
    instruments: list[tuple[str, str, dt.date, str]],
    official_types: dict[str, str] | None = None,
) -> None:
    calendar_path = data_root / "clean" / "trade_calendar" / "market=HK" / "data.parquet"
    calendar_path.parent.mkdir(parents=True)
    pl.DataFrame(
        {
            "market": ["HK"] * len(calendar_rows),
            "date": [day for day, _ in calendar_rows],
            "is_open": [is_open for _, is_open in calendar_rows],
            "is_connect_open": [is_open for _, is_open in calendar_rows],
            "is_half_day": [False] * len(calendar_rows),
        },
        schema={
            "market": pl.String,
            "date": pl.Date,
            "is_open": pl.Boolean,
            "is_connect_open": pl.Boolean,
            "is_half_day": pl.Boolean,
        },
    ).write_parquet(calendar_path)

    instrument_path = data_root / "clean" / "instrument" / "market=HK" / "data.parquet"
    instrument_path.parent.mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": [row[0] for row in instruments],
            "market": ["HK"] * len(instruments),
            "name": [f"name-{row[0]}" for row in instruments],
            "instrument_type": [row[1] for row in instruments],
            "currency": ["HKD"] * len(instruments),
            "list_date": [row[2] for row in instruments],
            "delist_date": [None] * len(instruments),
            "board_lot": [100] * len(instruments),
            "status": [row[3] for row in instruments],
        },
        schema={
            "symbol": pl.String,
            "market": pl.String,
            "name": pl.String,
            "instrument_type": pl.String,
            "currency": pl.String,
            "list_date": pl.Date,
            "delist_date": pl.Date,
            "board_lot": pl.Int64,
            "status": pl.String,
        },
    ).write_parquet(instrument_path)

    types = (
        official_types
        if official_types is not None
        else {row[0]: row[1] for row in instruments}
    )
    snapshot_path = (
        data_root
        / "clean"
        / "connect_snapshot"
        / "route=SH_CONNECT"
        / f"date={max(day for day, _ in calendar_rows).isoformat()}"
        / "data.parquet"
    )
    snapshot_path.parent.mkdir(parents=True)
    pl.DataFrame(
        {
            "route": ["SH_CONNECT"] * len(types),
            "snapshot_date": [max(day for day, _ in calendar_rows)] * len(types),
            "symbol": list(types),
            "name_cn": [f"name-{symbol}" for symbol in types],
            "name_en": [f"name-{symbol}" for symbol in types],
            "security_type": list(types.values()),
            "buy_eligible": [True] * len(types),
            "source": ["sse"] * len(types),
        },
        schema={
            "route": pl.String,
            "snapshot_date": pl.Date,
            "symbol": pl.String,
            "name_cn": pl.String,
            "name_en": pl.String,
            "security_type": pl.String,
            "buy_eligible": pl.Boolean,
            "source": pl.String,
        },
    ).write_parquet(snapshot_path)

    event_path = (
        data_root
        / "clean"
        / "connect_event"
        / "route=SH_CONNECT"
        / "data.parquet"
    )
    event_path.parent.mkdir(parents=True)
    pl.DataFrame(
        schema={
            "route": pl.String,
            "effective_date": pl.Date,
            "symbol": pl.String,
            "action": pl.String,
            "name_cn": pl.String,
            "name_en": pl.String,
            "security_type": pl.String,
            "published_date": pl.Date,
            "source": pl.String,
        }
    ).write_parquet(event_path)


def _small_calendar() -> list[tuple[dt.date, bool]]:
    return [
        (dt.date(2026, 3, 6), True),
        (dt.date(2026, 3, 7), False),
        (dt.date(2026, 3, 8), False),
        (dt.date(2026, 3, 9), True),
        (dt.date(2026, 3, 10), True),
    ]


def test_cli_report_mode_prints_coverage(tmp_path: Path, capsys) -> None:
    data_root = tmp_path / "data"
    _write_membership(data_root, ["00700.HK", "00001.HK", "00388.HK"])
    bar_root = data_root / "clean" / "bar_1d"
    as_of = dt.date(2026, 3, 10)
    full_days = {as_of - dt.timedelta(days=i) for i in range(60)}
    short_days = {as_of - dt.timedelta(days=i) for i in range(59)}
    for day in sorted(full_days):
        rows = [("00700.HK", "tushare", 1.0)]
        if day in short_days:
            rows.append(("00001.HK", "tushare", 2.0))
        _ensure_bar(bar_root, day, rows)

    code = main(
        [
            "--universe",
            "SH_CONNECT",
            "--as-of",
            as_of.isoformat(),
            "--source",
            "tushare",
            "--observations",
            "60",
            "--data-root",
            str(data_root),
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["eligible_symbol_count"] == 3
    assert payload["returned_symbol_count"] == 2
    assert payload["missing_symbols"] == ["00388.HK"]
    assert payload["short_symbol_counts"] == [["00001.HK", 59]]
    assert payload["is_full_window"] is False
    assert payload["output"] is None


def test_cli_require_full_window_fails_without_output(tmp_path: Path, capsys) -> None:
    data_root = tmp_path / "data"
    _write_membership(data_root, ["00700.HK", "00001.HK", "00388.HK"])
    bar_root = data_root / "clean" / "bar_1d"
    as_of = dt.date(2026, 3, 10)
    full_days = {as_of - dt.timedelta(days=i) for i in range(60)}
    short_days = {as_of - dt.timedelta(days=i) for i in range(59)}
    for day in sorted(full_days):
        rows = [("00700.HK", "tushare", 1.0)]
        if day in short_days:
            rows.append(("00001.HK", "tushare", 2.0))
        _ensure_bar(bar_root, day, rows)

    output = tmp_path / "out" / "window.parquet"
    code = main(
        [
            "--universe",
            "SH_CONNECT",
            "--as-of",
            as_of.isoformat(),
            "--source",
            "tushare",
            "--observations",
            "60",
            "--data-root",
            str(data_root),
            "--output",
            str(output),
            "--require-full-window",
        ]
    )
    assert code == 1
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["code"] == "BAR_WINDOW_INCOMPLETE"
    assert payload["missing_symbols"] == ["00388.HK"]
    assert payload["short_symbol_counts"] == [["00001.HK", 59]]
    assert not output.exists()
    assert not output.parent.exists()


def test_cli_writes_output_only_on_success(tmp_path: Path, capsys) -> None:
    data_root = tmp_path / "data"
    _write_membership(data_root, ["00700.HK"])
    bar_root = data_root / "clean" / "bar_1d"
    as_of = dt.date(2026, 3, 10)
    for day in (as_of - dt.timedelta(days=i) for i in range(2)):
        _ensure_bar(bar_root, day, [("00700.HK", "tushare", 1.0)])

    output = tmp_path / "artifacts" / "window.parquet"
    code = main(
        [
            "--universe",
            "SH_CONNECT",
            "--as-of",
            as_of.isoformat(),
            "--source",
            "tushare",
            "--observations",
            "2",
            "--data-root",
            str(data_root),
            "--output",
            str(output),
            "--require-full-window",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["is_full_window"] is True
    assert payload["output"] == output.as_posix()
    assert output.exists()
    assert "\\" not in payload["output"]


def test_cli_available_history_accepts_new_stock_complete_since_listing(
    tmp_path: Path, capsys
) -> None:
    data_root = tmp_path / "data"
    symbol = "00700.HK"
    _write_membership(data_root, [symbol])
    _write_hk_references(
        data_root,
        calendar_rows=_small_calendar(),
        instruments=[(symbol, "STOCK", dt.date(2026, 3, 9), "LISTED")],
    )
    bar_root = data_root / "clean" / "bar_1d"
    for day in (dt.date(2026, 3, 9), dt.date(2026, 3, 10)):
        _ensure_bar(bar_root, day, [(symbol, "tushare", 1.0)])

    output = tmp_path / "out" / "window.parquet"
    code = main(
        [
            "--universe",
            "SH_CONNECT",
            "--as-of",
            "2026-03-10",
            "--source",
            "tushare",
            "--observations",
            "3",
            "--data-root",
            str(data_root),
            "--output",
            str(output),
            "--require-available-history",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["is_full_window"] is False
    assert payload["available_history"] == {
        "eligible_symbol_count": 1,
        "required_stock_symbol_count": 1,
        "excluded_etf_symbols": [],
        "structurally_short_symbol_counts": [[symbol, 2]],
        "missing_session_counts": [],
        "unexpected_session_counts": [],
        "missing_session_total": 0,
        "unexpected_session_total": 0,
        "min_required_sessions": 2,
        "max_required_sessions": 2,
        "is_available_history_complete": True,
    }
    assert output.exists()


def test_cli_available_history_rejects_equal_count_with_wrong_date(tmp_path: Path, capsys) -> None:
    data_root = tmp_path / "data"
    symbol = "00700.HK"
    _write_membership(data_root, [symbol])
    _write_hk_references(
        data_root,
        calendar_rows=_small_calendar(),
        instruments=[(symbol, "STOCK", dt.date(2026, 3, 9), "LISTED")],
    )
    bar_root = data_root / "clean" / "bar_1d"
    _ensure_bar(bar_root, dt.date(2026, 3, 8), [(symbol, "tushare", 1.0)])
    _ensure_bar(bar_root, dt.date(2026, 3, 10), [(symbol, "tushare", 1.0)])
    output = tmp_path / "out" / "window.parquet"

    code = main(
        [
            "--universe",
            "SH_CONNECT",
            "--as-of",
            "2026-03-10",
            "--source",
            "tushare",
            "--observations",
            "3",
            "--data-root",
            str(data_root),
            "--output",
            str(output),
            "--require-available-history",
        ]
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["code"] == "BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE"
    assert payload["available_history"]["missing_session_counts"] == [[symbol, 1]]
    assert payload["available_history"]["unexpected_session_counts"] == [[symbol, 1]]
    assert not output.exists()
    assert not output.parent.exists()


def test_cli_available_history_excludes_only_proven_etf(tmp_path: Path, capsys) -> None:
    data_root = tmp_path / "data"
    symbol = "02800.HK"
    _write_membership(data_root, [symbol])
    _write_hk_references(
        data_root,
        calendar_rows=_small_calendar(),
        instruments=[(symbol, "ETF", dt.date(2020, 1, 1), "LISTED")],
    )

    code = main(
        [
            "--universe",
            "SH_CONNECT",
            "--as-of",
            "2026-03-10",
            "--source",
            "tushare",
            "--observations",
            "3",
            "--data-root",
            str(data_root),
            "--require-available-history",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["available_history"]["excluded_etf_symbols"] == [symbol]
    assert payload["available_history"]["required_stock_symbol_count"] == 0
    assert payload["available_history"]["is_available_history_complete"] is True


def test_cli_official_etf_does_not_require_instrument_row(tmp_path: Path, capsys) -> None:
    data_root = tmp_path / "data"
    symbol = "02800.HK"
    _write_membership(data_root, [symbol])
    _write_hk_references(
        data_root,
        calendar_rows=_small_calendar(),
        instruments=[],
        official_types={symbol: "ETF"},
    )

    code = main(
        [
            "--universe", "SH_CONNECT", "--as-of", "2026-03-10",
            "--source", "tushare", "--observations", "3",
            "--data-root", str(data_root), "--require-available-history",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["available_history"]["excluded_etf_symbols"] == [symbol]
    assert payload["available_history"]["required_stock_symbol_count"] == 0


def test_cli_official_etf_conflicting_stock_instrument_is_reference_invalid(
    tmp_path: Path, capsys
) -> None:
    data_root = tmp_path / "data"
    symbol = "02800.HK"
    _write_membership(data_root, [symbol])
    _write_hk_references(
        data_root,
        calendar_rows=_small_calendar(),
        instruments=[(symbol, "STOCK", dt.date(2020, 1, 1), "LISTED")],
        official_types={symbol: "ETF"},
    )

    code = main(
        [
            "--universe", "SH_CONNECT", "--as-of", "2026-03-10",
            "--source", "tushare", "--observations", "3",
            "--data-root", str(data_root), "--require-available-history",
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip() == "BAR_WINDOW_REFERENCE_INVALID"


def test_cli_other_official_type_falls_back_to_instrument(tmp_path: Path, capsys) -> None:
    data_root = tmp_path / "data"
    symbol = "02800.HK"
    _write_membership(data_root, [symbol])
    _write_hk_references(
        data_root,
        calendar_rows=_small_calendar(),
        instruments=[(symbol, "ETF", dt.date(2020, 1, 1), "LISTED")],
        official_types={symbol: "OTHER"},
    )

    code = main(
        [
            "--universe", "SH_CONNECT", "--as-of", "2026-03-10",
            "--source", "tushare", "--observations", "3",
            "--data-root", str(data_root), "--require-available-history",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["available_history"]["excluded_etf_symbols"] == [symbol]


def test_cli_cross_route_official_type_conflict_is_reference_invalid(
    tmp_path: Path, capsys
) -> None:
    data_root = tmp_path / "data"
    symbol = "02800.HK"
    _write_membership(data_root, [symbol])
    _write_hk_references(
        data_root,
        calendar_rows=_small_calendar(),
        instruments=[],
        official_types={symbol: "ETF"},
    )
    sh_path = next(
        (data_root / "clean" / "connect_snapshot" / "route=SH_CONNECT").rglob(
            "data.parquet"
        )
    )
    sz_path = (
        data_root
        / "clean"
        / "connect_snapshot"
        / "route=SZ_CONNECT"
        / "date=2026-03-10"
        / "data.parquet"
    )
    sz_path.parent.mkdir(parents=True)
    pl.read_parquet(sh_path).with_columns(
        pl.lit("SZ_CONNECT").alias("route"),
        pl.lit("STOCK").alias("security_type"),
        pl.lit("szse").alias("source"),
    ).write_parquet(sz_path)

    code = main(
        [
            "--universe", "SH_CONNECT", "--as-of", "2026-03-10",
            "--source", "tushare", "--observations", "3",
            "--data-root", str(data_root), "--require-available-history",
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip() == "BAR_WINDOW_REFERENCE_INVALID"


def test_cli_available_history_missing_instrument_is_reference_invalid(
    tmp_path: Path, capsys
) -> None:
    data_root = tmp_path / "data"
    _write_membership(data_root, ["02800.HK"])
    _write_hk_references(
        data_root,
        calendar_rows=_small_calendar(),
        instruments=[("00700.HK", "STOCK", dt.date(2020, 1, 1), "LISTED")],
        official_types={"02800.HK": "STOCK"},
    )

    code = main(
        [
            "--universe",
            "SH_CONNECT",
            "--as-of",
            "2026-03-10",
            "--source",
            "tushare",
            "--observations",
            "3",
            "--data-root",
            str(data_root),
            "--require-available-history",
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err.strip() == "BAR_WINDOW_REFERENCE_INVALID"


def test_cli_available_history_suspended_status_does_not_reduce_required_dates(
    tmp_path: Path, capsys
) -> None:
    data_root = tmp_path / "data"
    symbol = "00700.HK"
    _write_membership(data_root, [symbol])
    _write_hk_references(
        data_root,
        calendar_rows=_small_calendar(),
        instruments=[(symbol, "STOCK", dt.date(2026, 3, 6), "SUSPENDED")],
    )
    bar_root = data_root / "clean" / "bar_1d"
    for day in (dt.date(2026, 3, 6), dt.date(2026, 3, 10)):
        _ensure_bar(bar_root, day, [(symbol, "tushare", 1.0)])

    code = main(
        [
            "--universe",
            "SH_CONNECT",
            "--as-of",
            "2026-03-10",
            "--source",
            "tushare",
            "--observations",
            "3",
            "--data-root",
            str(data_root),
            "--require-available-history",
        ]
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["available_history"]["missing_session_counts"] == [[symbol, 1]]


def test_cli_available_history_rejects_calendar_natural_day_gap(tmp_path: Path, capsys) -> None:
    data_root = tmp_path / "data"
    symbol = "00700.HK"
    _write_membership(data_root, [symbol])
    calendar = [row for row in _small_calendar() if row[0] != dt.date(2026, 3, 7)]
    _write_hk_references(
        data_root,
        calendar_rows=calendar,
        instruments=[(symbol, "STOCK", dt.date(2026, 3, 6), "LISTED")],
    )

    code = main(
        [
            "--universe",
            "SH_CONNECT",
            "--as-of",
            "2026-03-10",
            "--source",
            "tushare",
            "--observations",
            "3",
            "--data-root",
            str(data_root),
            "--require-available-history",
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err.strip() == "BAR_WINDOW_REFERENCE_INVALID"


def test_cli_full_window_gate_keeps_priority_over_available_history(tmp_path: Path, capsys) -> None:
    data_root = tmp_path / "data"
    symbol = "00700.HK"
    _write_membership(data_root, [symbol])
    bar_root = data_root / "clean" / "bar_1d"
    for day in (dt.date(2026, 3, 9), dt.date(2026, 3, 10)):
        _ensure_bar(bar_root, day, [(symbol, "tushare", 1.0)])

    code = main(
        [
            "--universe",
            "SH_CONNECT",
            "--as-of",
            "2026-03-10",
            "--source",
            "tushare",
            "--observations",
            "3",
            "--data-root",
            str(data_root),
            "--require-full-window",
            "--require-available-history",
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert captured.err == ""
    assert json.loads(captured.out)["code"] == "BAR_WINDOW_INCOMPLETE"
