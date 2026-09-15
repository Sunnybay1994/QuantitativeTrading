"""M1-X2: query_universe CLI coverage and strict gate tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import traceback
from pathlib import Path

import polars as pl
import pytest

from quant.data.hk_history_backfill import (
    HKHistoryBackfillError,
    build_hk_history_plan_v2,
    write_or_verify_plan,
)
from quant.data.query import BarQuery, BarWindowQueryError
from quant.data.query_universe import main
from tests.support.hk_history_v3 import (
    AS_OF,
    WINDOW_START,
    load_combined_evidence,
    publish_minimal_v3,
    write_seed,
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _write_no_trade_evidence(data_root: Path, *, symbol: str, trade_date: dt.date) -> Path:
    selector = "hkex/daily/synthetic.html"
    raw_path = data_root / "raw" / selector
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_payload = b"SYNTHETIC DAILY QUOTATIONS FIXTURE"
    raw_path.write_bytes(raw_payload)
    evidence: dict[str, object] = {
        "schema_version": "hk-no-trade-evidence-v1",
        "symbol": symbol,
        "trade_date": trade_date.isoformat(),
        "market": "HK",
        "reason": "NO_DAILY_TRADING_V1",
        "source": "HKEX_DAILY_QUOTATIONS",
        "source_record_id": "synthetic-fixture-record",
        "source_as_of": "2026-07-31T00:00:00+00:00",
        "raw_selector": selector,
        "raw_file_sha256": hashlib.sha256(raw_payload).hexdigest(),
        "raw_metadata_sha256": "0" * 64,
    }
    metadata = {
        "schema_version": "hk-no-trade-raw-metadata-v1",
        "source": evidence["source"],
        "source_record_id": evidence["source_record_id"],
        "source_as_of": evidence["source_as_of"],
        "raw_selector": selector,
        "raw_file_sha256": evidence["raw_file_sha256"],
    }
    metadata_payload = _canonical(metadata)
    raw_path.with_suffix(".json").write_bytes(metadata_payload)
    evidence["raw_metadata_sha256"] = hashlib.sha256(metadata_payload).hexdigest()
    evidence["evidence_sha256"] = hashlib.sha256(_canonical(evidence)).hexdigest()
    evidences = [evidence]
    payload = {
        "schema_version": "hk-no-trade-evidence-set-v1",
        "evidences": evidences,
        "evidence_set_sha256": hashlib.sha256(_canonical(evidences)).hexdigest(),
    }
    path = data_root / "clean" / "hk_no_trade_evidence" / "evidence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(payload))
    return raw_path


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
        official_types if official_types is not None else {row[0]: row[1] for row in instruments}
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

    event_path = data_root / "clean" / "connect_event" / "route=SH_CONNECT" / "data.parquet"
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
        "exempted_session_count": 0,
        "exemption_reason_counts": [],
        "no_trade_evidence_sha256": None,
        "min_required_sessions": 2,
        "max_required_sessions": 2,
        "is_available_history_complete": True,
    }
    assert output.exists()


def test_cli_available_history_uses_exact_verified_no_trade_projection(
    tmp_path: Path, capsys
) -> None:
    data_root = tmp_path / "data"
    symbol = "00700.HK"
    _write_membership(data_root, [symbol])
    _write_hk_references(
        data_root,
        calendar_rows=_small_calendar(),
        instruments=[(symbol, "STOCK", dt.date(2026, 3, 6), "LISTED")],
    )
    raw_path = _write_no_trade_evidence(data_root, symbol=symbol, trade_date=dt.date(2026, 3, 9))
    for day in (dt.date(2026, 3, 6), dt.date(2026, 3, 10)):
        _ensure_bar(data_root / "clean" / "bar_1d", day, [(symbol, "tushare", 1.0)])

    args = [
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
    assert main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["available_history"]["exempted_session_count"] == 1
    assert payload["available_history"]["exemption_reason_counts"] == [["NO_DAILY_TRADING_V1", 1]]
    assert payload["available_history"]["missing_session_total"] == 0

    _ensure_bar(
        data_root / "clean" / "bar_1d",
        dt.date(2026, 3, 9),
        [(symbol, "tushare", 1.0)],
    )
    assert main(args) == 1
    conflict = json.loads(capsys.readouterr().out)
    assert conflict["available_history"]["unexpected_session_total"] == 1

    raw_path.write_bytes(b"tampered")
    assert main(args) == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == "BAR_WINDOW_REFERENCE_INVALID"


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
        (data_root / "clean" / "connect_snapshot" / "route=SH_CONNECT").rglob("data.parquet")
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


def _july_calendar() -> list[tuple[dt.date, bool]]:
    return [(AS_OF, True)]


def _mixed_argv(
    fixture,
    *,
    extra: list[str] | None = None,
    output: Path | None = None,
    as_of: str | None = None,
    verification_as_of: str | None = None,
    plan: Path | None = None,
    journal: Path | None = None,
) -> list[str]:
    args = [
        "--universe",
        "SH_CONNECT",
        "--as-of",
        as_of or AS_OF.isoformat(),
        "--from-verified-hk-availability",
        "--plan",
        str(plan or fixture.plan_path),
        "--journal-root",
        str(journal or fixture.journal_root),
        "--verification-as-of",
        verification_as_of or fixture.verification_as_of.isoformat(),
        "--observations",
        "1",
        "--data-root",
        str(fixture.data_root),
        "--require-available-history",
    ]
    if output is not None:
        args.extend(["--output", str(output)])
    if extra:
        args.extend(extra)
    return args


def _prepare_mixed_refs(
    fixture,
    symbols: list[str],
    *,
    calendar_rows: list[tuple[dt.date, bool]] | None = None,
    instruments: list[tuple[str, str, dt.date, str]] | None = None,
    official_types: dict[str, str] | None = None,
) -> None:
    _write_membership(fixture.data_root, symbols)
    _write_hk_references(
        fixture.data_root,
        calendar_rows=calendar_rows or _july_calendar(),
        instruments=instruments or [(symbol, "STOCK", AS_OF, "LISTED") for symbol in symbols],
        official_types=official_types,
    )


def test_cli_mixed_conflicts_and_missing_required_flags(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "--universe",
            "SH_CONNECT",
            "--as-of",
            "2026-07-10",
            "--source",
            "tushare",
            "--from-verified-hk-availability",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip() == "BAR_WINDOW_INPUT_INVALID"

    code = main(
        [
            "--universe",
            "SH_CONNECT",
            "--as-of",
            "2026-07-10",
            "--from-verified-hk-availability",
            "--require-available-history",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip() == "BAR_WINDOW_INPUT_INVALID"


def test_cli_mixed_rejects_naive_non_utc_and_mismatched_as_of(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fixture = publish_minimal_v3(tmp_path, monkeypatch)
    _prepare_mixed_refs(fixture, ["00001.HK", "00002.HK", "02983.HK"])
    output = tmp_path / "out.parquet"
    for verification in (
        "2026-08-16T12:00:00",
        "2026-08-16T12:00:00+08:00",
        "not-a-datetime",
    ):
        code = main(_mixed_argv(fixture, output=output, verification_as_of=verification))
        captured = capsys.readouterr()
        assert code == 1
        assert captured.err.strip() == "BAR_WINDOW_INPUT_INVALID"
        assert not output.exists()
    code = main(_mixed_argv(fixture, output=output, as_of="2026-07-09"))
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip() == "BAR_WINDOW_INPUT_INVALID"
    assert not output.exists()
    code = main(_mixed_argv(fixture, extra=["--require-full-window"], output=output))
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip() == "BAR_WINDOW_INPUT_INVALID"
    assert not output.exists()


def test_cli_mixed_complete_and_ignores_evidence_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fixture = publish_minimal_v3(tmp_path, monkeypatch)
    symbols = ["00001.HK", "00002.HK", "02983.HK", "01065.HK"]
    _prepare_mixed_refs(fixture, symbols)
    evidence_path = fixture.data_root / "clean" / "hk_no_trade_evidence" / "evidence.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text("hostile-not-a-plan-evidence", encoding="utf-8")
    output = tmp_path / "out" / "window.parquet"
    code = main(_mixed_argv(fixture, output=output))
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["source"] == "verified-hk-availability-v1"
    assert payload["plan_sha256"] == fixture.plan.plan_sha256
    assert payload["publication_sha256"] == fixture.bundle.publication_sha256
    assert payload["verification_as_of"] == fixture.verification_as_of.isoformat()
    assert payload["available_history"]["is_available_history_complete"] is True
    assert ["hkex", 1] in payload["source_row_counts"]
    assert output.exists()


def test_cli_single_source_still_marks_02983_hkex_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fixture = publish_minimal_v3(tmp_path, monkeypatch)
    _prepare_mixed_refs(fixture, ["02983.HK"])
    code = main(
        [
            "--universe",
            "SH_CONNECT",
            "--as-of",
            AS_OF.isoformat(),
            "--source",
            "tushare",
            "--observations",
            "1",
            "--data-root",
            str(fixture.data_root),
            "--require-available-history",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    payload = json.loads(captured.out)
    assert payload["source"] == "tushare"
    assert payload["code"] == "BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE"
    assert payload["available_history"]["missing_session_total"] == 1


def test_cli_mixed_second_verify_drift_does_not_write_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fixture = publish_minimal_v3(tmp_path, monkeypatch)
    _prepare_mixed_refs(fixture, ["00001.HK", "00002.HK", "02983.HK"])
    output = tmp_path / "out.parquet"
    import quant.data.query_universe as query_universe

    real_verify = query_universe.verify_hk_bar_bundle

    def drift(*args: object, **kwargs: object) -> None:
        target = fixture.clean_root / f"date={AS_OF.isoformat()}" / "data.parquet"
        changed = pl.read_parquet(target).with_columns(pl.col("close") + 0.01)
        changed.write_parquet(target)
        real_verify(*args, **kwargs)

    monkeypatch.setattr(query_universe, "verify_hk_bar_bundle", drift)
    code = main(_mixed_argv(fixture, output=output))
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip() == "HK_BAR_VERIFY_FAILED"
    assert not output.exists()


def test_cli_mixed_hostile_errors_are_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fixture = publish_minimal_v3(tmp_path, monkeypatch)
    _prepare_mixed_refs(fixture, ["00001.HK"])
    import quant.data.query_universe as query_universe

    marker = r"C:\secret\hostile-token"

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError(marker)

    monkeypatch.setattr(query_universe, "load_verified_hk_bar_bundle", boom)
    code = main(_mixed_argv(fixture, output=tmp_path / "out.parquet"))
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip() == "BAR_WINDOW_REFERENCE_INVALID"
    assert marker not in captured.err
    assert marker not in captured.out

    def boom_value(*_args: object, **_kwargs: object) -> None:
        try:
            raise ValueError(marker)
        except ValueError as exc:
            wrapped = HKHistoryBackfillError("HK_BAR_VERIFY_FAILED")
            raise wrapped from exc

    monkeypatch.setattr(query_universe, "load_hk_history_plan", boom_value)
    code = main(_mixed_argv(fixture))
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip() == "HK_BAR_VERIFY_FAILED"
    assert marker not in captured.err
    assert marker not in "".join(
        traceback.format_exception(
            HKHistoryBackfillError, HKHistoryBackfillError("HK_BAR_VERIFY_FAILED"), None
        )
    )


def test_cli_mixed_ua001_plan_rejects_v2b_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fixture = publish_minimal_v3(tmp_path, monkeypatch)
    _prepare_mixed_refs(fixture, ["00001.HK"])
    ua_root = tmp_path / "ua-raw"
    seed, _seed_time = write_seed(ua_root, {"00001.HK": [AS_OF]})
    evidence = load_combined_evidence(ua_root, include_ua_m1_004=False)
    plan_001 = build_hk_history_plan_v2(
        expected_dates={
            "00001.HK": [AS_OF],
            "00002.HK": [AS_OF],
            "01065.HK": [dt.date(2026, 5, 5), AS_OF],
            "02983.HK": [AS_OF],
        },
        seed=seed,
        unresolved={"02983.HK": [AS_OF]},
        evidence=evidence,
        as_of=AS_OF,
        window_start=WINDOW_START,
    )
    plan_path = tmp_path / "plan-001.json"
    write_or_verify_plan(plan_path, plan_001)
    output = tmp_path / "out.parquet"
    code = main(_mixed_argv(fixture, plan=plan_path, output=output))
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip() in {
        "HK_HISTORY_FINALIZE_V3_INVALID",
        "HK_BAR_VERIFY_FAILED",
        "HK_HISTORY_PLAN_CONFLICT",
    }
    assert not output.exists()


def test_cli_mixed_no_trade_raw_tamper_fails_bundle_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fixture = publish_minimal_v3(tmp_path, monkeypatch)
    _prepare_mixed_refs(fixture, ["00001.HK"])
    raw_path = fixture.raw_root / "hkex" / "daily" / "d260710e.html"
    raw_path.write_bytes(raw_path.read_bytes() + b"TAMPER")
    output = tmp_path / "out.parquet"
    code = main(_mixed_argv(fixture, output=output))
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip() in {
        "HK_HISTORY_REFERENCE_INVALID",
        "HK_BAR_VERIFY_FAILED",
    }
    assert not output.exists()


def test_cli_mixed_stock_missing_instrument_and_etf_without_instrument(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fixture = publish_minimal_v3(tmp_path, monkeypatch)
    _write_membership(fixture.data_root, ["00001.HK"])
    _write_hk_references(
        fixture.data_root,
        calendar_rows=_july_calendar(),
        instruments=[],
        official_types={"00001.HK": "STOCK"},
    )
    code = main(_mixed_argv(fixture))
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip() == "BAR_WINDOW_REFERENCE_INVALID"

    fixture_etf = publish_minimal_v3(tmp_path / "etf", monkeypatch)
    _write_membership(fixture_etf.data_root, ["02800.HK"])
    _write_hk_references(
        fixture_etf.data_root,
        calendar_rows=_july_calendar(),
        instruments=[],
        official_types={"02800.HK": "ETF"},
    )
    code = main(_mixed_argv(fixture_etf))
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["available_history"]["excluded_etf_symbols"] == ["02800.HK"]


def test_cli_mixed_equal_count_wrong_date_and_exemption_unexpected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fixture = publish_minimal_v3(tmp_path, monkeypatch)
    _prepare_mixed_refs(
        fixture,
        ["00001.HK"],
        calendar_rows=[
            (dt.date(2026, 7, 8), False),
            (dt.date(2026, 7, 9), True),
            (AS_OF, True),
        ],
        instruments=[("00001.HK", "STOCK", dt.date(2026, 7, 9), "LISTED")],
    )
    extra_closed = fixture.clean_root / "date=2026-07-08" / "data.parquet"
    extra_closed.parent.mkdir(parents=True, exist_ok=True)
    pl.read_parquet(fixture.clean_root / f"date={AS_OF.isoformat()}" / "data.parquet").filter(
        pl.col("symbol") == "00001.HK"
    ).with_columns(pl.lit(dt.date(2026, 7, 8)).alias("trade_date")).write_parquet(extra_closed)
    code = main(_mixed_argv(fixture, extra=["--observations", "2"]))
    captured = capsys.readouterr()
    assert code == 1
    payload = json.loads(captured.out)
    assert payload["code"] == "BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE"
    assert payload["available_history"]["missing_session_total"] >= 1
    assert payload["available_history"]["unexpected_session_total"] >= 1

    fixture_ex = publish_minimal_v3(tmp_path / "exempt", monkeypatch)
    _prepare_mixed_refs(fixture_ex, ["01065.HK"])
    _append = fixture_ex.clean_root / f"date={AS_OF.isoformat()}" / "data.parquet"
    extra = (
        pl.read_parquet(_append)
        .filter(pl.col("symbol") == "00001.HK")
        .with_columns(pl.lit("01065.HK").alias("symbol"))
    )
    pl.concat([pl.read_parquet(_append), extra], how="vertical_relaxed").write_parquet(_append)
    code = main(_mixed_argv(fixture_ex))
    captured = capsys.readouterr()
    assert code == 1
    payload = json.loads(captured.out)
    assert payload["available_history"]["unexpected_session_total"] == 1


def test_cli_mixed_physical_duplicate_key_on_mapped_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fixture = publish_minimal_v3(tmp_path, monkeypatch)
    _prepare_mixed_refs(fixture, ["00001.HK"])
    output = tmp_path / "out.parquet"
    import quant.data.query_universe as query_universe

    real_load = query_universe.load_verified_hk_bar_bundle

    def load_then_duplicate(**kwargs: object):
        bundle = real_load(**kwargs)
        target = fixture.clean_root / f"date={AS_OF.isoformat()}" / "data.parquet"
        frame = pl.read_parquet(target)
        row = frame.filter(pl.col("symbol") == "00001.HK")
        pl.concat([frame, row], how="vertical_relaxed").write_parquet(target)
        return bundle

    monkeypatch.setattr(query_universe, "load_verified_hk_bar_bundle", load_then_duplicate)
    code = main(_mixed_argv(fixture, output=output))
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip() == "BAR_WINDOW_DUPLICATE_KEY"
    assert not output.exists()


def test_cli_mixed_ua_exemptions_0504_missing_and_exempt_day_unexpected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    may4 = dt.date(2026, 5, 4)
    may5 = dt.date(2026, 5, 5)
    fixture = publish_minimal_v3(
        tmp_path,
        monkeypatch,
        request_dates={
            "00002.HK": [AS_OF],
            "01065.HK": [may4, AS_OF],
        },
        extra_expected={"01065.HK": [may4, may5, AS_OF]},
        evidence_mode="ua-001",
    )
    open_days = {may4, may5, AS_OF}
    calendar_rows = []
    day = may4
    while day <= AS_OF:
        calendar_rows.append((day, day in open_days))
        day += dt.timedelta(days=1)
    _prepare_mixed_refs(
        fixture,
        ["01065.HK"],
        calendar_rows=calendar_rows,
        instruments=[("01065.HK", "STOCK", may4, "LISTED")],
    )
    args = _mixed_argv(fixture, extra=["--observations", "3"])
    assert main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["available_history"]["is_available_history_complete"] is True
    assert payload["available_history"]["exempted_session_count"] == 1

    import quant.data.query as query_mod

    query = query_mod.BarQuery(fixture.clean_root)
    membership = (
        fixture.data_root / "clean" / "universe_membership" / "universe=SH_CONNECT" / "data.parquet"
    )
    may4_path = fixture.clean_root / f"date={may4.isoformat()}" / "data.parquet"
    may4_path.unlink()
    audited = query.recent_for_universe_mixed_audited(
        membership_path=membership,
        universe="SH_CONNECT",
        as_of=AS_OF,
        observations=3,
        bundle=fixture.bundle,
        plan=fixture.plan,
    )
    available = query.audit_available_history_mixed(
        audited=audited,
        calendar_path=(
            fixture.data_root / "clean" / "trade_calendar" / "market=HK" / "data.parquet"
        ),
        instrument_path=(fixture.data_root / "clean" / "instrument" / "market=HK" / "data.parquet"),
        eligibility_snapshot_root=fixture.data_root / "clean" / "connect_snapshot",
        eligibility_event_root=fixture.data_root / "clean" / "connect_event",
        no_trade_evidences=fixture.plan.no_trade_evidence,
        no_trade_evidence_sha256=fixture.plan.no_trade_evidence_sha256,
    )
    assert available.available_history.missing_sessions
    extra = (
        pl.read_parquet(fixture.clean_root / f"date={AS_OF.isoformat()}" / "data.parquet")
        .filter(pl.col("symbol") == "01065.HK")
        .with_columns(pl.lit(may5).alias("trade_date"))
    )
    may5_path = fixture.clean_root / f"date={may5.isoformat()}" / "data.parquet"
    may5_path.parent.mkdir(parents=True, exist_ok=True)
    extra.write_parquet(may5_path)
    available_unexpected = query.audit_available_history_mixed(
        audited=audited,
        calendar_path=(
            fixture.data_root / "clean" / "trade_calendar" / "market=HK" / "data.parquet"
        ),
        instrument_path=(fixture.data_root / "clean" / "instrument" / "market=HK" / "data.parquet"),
        eligibility_snapshot_root=fixture.data_root / "clean" / "connect_snapshot",
        eligibility_event_root=fixture.data_root / "clean" / "connect_event",
        no_trade_evidences=fixture.plan.no_trade_evidence,
        no_trade_evidence_sha256=fixture.plan.no_trade_evidence_sha256,
    )
    assert available_unexpected.available_history.unexpected_sessions
    assert available_unexpected.available_history.missing_sessions


def _append_symbol_bar(
    clean_root: Path,
    *,
    symbol: str,
    trade_date: dt.date,
    template_symbol: str = "00001.HK",
) -> None:
    source = clean_root / f"date={AS_OF.isoformat()}" / "data.parquet"
    extra = (
        pl.read_parquet(source)
        .filter(pl.col("symbol") == template_symbol)
        .with_columns(
            pl.lit(symbol).alias("symbol"),
            pl.lit(trade_date).alias("trade_date"),
        )
    )
    target = clean_root / f"date={trade_date.isoformat()}" / "data.parquet"
    if target.exists():
        extra = pl.concat([pl.read_parquet(target), extra], how="vertical_relaxed")
    target.parent.mkdir(parents=True, exist_ok=True)
    extra.write_parquet(target)


def _mixed_ah_paths(fixture) -> dict[str, Path]:
    return {
        "calendar_path": (
            fixture.data_root / "clean" / "trade_calendar" / "market=HK" / "data.parquet"
        ),
        "instrument_path": (
            fixture.data_root / "clean" / "instrument" / "market=HK" / "data.parquet"
        ),
        "eligibility_snapshot_root": fixture.data_root / "clean" / "connect_snapshot",
        "eligibility_event_root": fixture.data_root / "clean" / "connect_event",
    }


def test_cli_mixed_unmapped_required_bar_does_not_complete_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    july9 = dt.date(2026, 7, 9)
    fixture = publish_minimal_v3(tmp_path, monkeypatch)
    _prepare_mixed_refs(
        fixture,
        ["00001.HK"],
        calendar_rows=[(july9, True), (AS_OF, True)],
        instruments=[("00001.HK", "STOCK", july9, "LISTED")],
    )
    _append_symbol_bar(fixture.clean_root, symbol="00001.HK", trade_date=july9)
    membership = (
        fixture.data_root / "clean" / "universe_membership" / "universe=SH_CONNECT" / "data.parquet"
    )
    audited = BarQuery(fixture.clean_root).recent_for_universe_mixed_audited(
        membership_path=membership,
        universe="SH_CONNECT",
        as_of=AS_OF,
        observations=2,
        bundle=fixture.bundle,
        plan=fixture.plan,
    )
    assert audited.frame.get_column("trade_date").to_list() == [AS_OF]
    available = BarQuery(fixture.clean_root).audit_available_history_mixed(
        audited=audited,
        **_mixed_ah_paths(fixture),
        no_trade_evidences=fixture.plan.no_trade_evidence,
        no_trade_evidence_sha256=fixture.plan.no_trade_evidence_sha256,
    )
    assert available.available_history.is_available_history_complete is False
    assert available.available_history.missing_sessions
    output = tmp_path / "out.parquet"
    code = main(_mixed_argv(fixture, extra=["--observations", "2"], output=output))
    captured = capsys.readouterr()
    assert code == 1
    payload = json.loads(captured.out)
    assert payload["code"] == "BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE"
    assert payload["available_history"]["missing_session_total"] >= 1
    assert payload["available_history"]["is_available_history_complete"] is False
    assert not output.exists()


def test_cli_mixed_member_outside_availability_does_not_complete_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fixture = publish_minimal_v3(tmp_path, monkeypatch)
    _prepare_mixed_refs(fixture, ["00001.HK", "09999.HK"])
    _append_symbol_bar(fixture.clean_root, symbol="09999.HK", trade_date=AS_OF)
    output = tmp_path / "out.parquet"
    code = main(_mixed_argv(fixture, output=output))
    captured = capsys.readouterr()
    assert code == 1
    payload = json.loads(captured.out)
    assert payload["code"] == "BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE"
    assert "09999.HK" in payload["missing_symbols"]
    assert payload["available_history"]["is_available_history_complete"] is False
    assert payload["available_history"]["missing_session_total"] >= 1
    assert not (
        payload["missing_symbols"] and payload["available_history"]["is_available_history_complete"]
    )
    assert not output.exists()


def test_mixed_ah_actual_polars_error_has_empty_exception_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fixture = publish_minimal_v3(tmp_path, monkeypatch)
    _prepare_mixed_refs(fixture, ["00001.HK"])
    membership = (
        fixture.data_root / "clean" / "universe_membership" / "universe=SH_CONNECT" / "data.parquet"
    )
    audited = BarQuery(fixture.clean_root).recent_for_universe_mixed_audited(
        membership_path=membership,
        universe="SH_CONNECT",
        as_of=AS_OF,
        observations=1,
        bundle=fixture.bundle,
        plan=fixture.plan,
    )
    marker = r"C:\secret\hostile-parquet-token"
    snapshot = next(
        (fixture.data_root / "clean" / "connect_snapshot").glob("route=*/date=*/data.parquet")
    )
    snapshot.write_bytes(b"NOT-A-PARQUET-FILE " + marker.encode("utf-8"))
    with pytest.raises(BarWindowQueryError, match="^BAR_WINDOW_REFERENCE_INVALID$") as caught:
        BarQuery(fixture.clean_root).audit_available_history_mixed(
            audited=audited,
            **_mixed_ah_paths(fixture),
            no_trade_evidences=fixture.plan.no_trade_evidence,
            no_trade_evidence_sha256=fixture.plan.no_trade_evidence_sha256,
        )
    exc = caught.value
    assert exc.__cause__ is None
    assert exc.__context__ is None
    assert marker not in repr(exc)
    assert marker not in "".join(traceback.format_exception(exc))
    output = tmp_path / "out.parquet"
    code = main(_mixed_argv(fixture, output=output))
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip() == "BAR_WINDOW_REFERENCE_INVALID"
    assert marker not in captured.err
    assert marker not in captured.out
    assert not output.exists()


def _assert_detached_reference_invalid(
    exc: BaseException, *, marker: str, leaks: tuple[str, ...]
) -> None:
    assert str(exc) == "BAR_WINDOW_REFERENCE_INVALID"
    assert exc.__cause__ is None
    assert exc.__context__ is None
    surfaces = (
        repr(exc),
        "".join(traceback.format_exception(exc)),
        repr(exc.__context__),
        repr(exc.__cause__),
    )
    for leak in (marker, *leaks):
        for surface in surfaces:
            assert leak not in surface


def test_mixed_ah_actual_calendar_parquet_error_has_empty_exception_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fixture = publish_minimal_v3(tmp_path, monkeypatch)
    _prepare_mixed_refs(fixture, ["00001.HK"])
    membership = (
        fixture.data_root / "clean" / "universe_membership" / "universe=SH_CONNECT" / "data.parquet"
    )
    audited = BarQuery(fixture.clean_root).recent_for_universe_mixed_audited(
        membership_path=membership,
        universe="SH_CONNECT",
        as_of=AS_OF,
        observations=1,
        bundle=fixture.bundle,
        plan=fixture.plan,
    )
    marker = r"C:\secret\hostile-calendar-token"
    calendar_path = fixture.data_root / "clean" / "trade_calendar" / "market=HK" / "data.parquet"
    calendar_path.write_bytes(b"NOT-A-PARQUET-FILE " + marker.encode("utf-8"))
    with pytest.raises(BarWindowQueryError, match="^BAR_WINDOW_REFERENCE_INVALID$") as caught:
        BarQuery(fixture.clean_root).audit_available_history_mixed(
            audited=audited,
            **_mixed_ah_paths(fixture),
            no_trade_evidences=fixture.plan.no_trade_evidence,
            no_trade_evidence_sha256=fixture.plan.no_trade_evidence_sha256,
        )
    _assert_detached_reference_invalid(
        caught.value,
        marker=marker,
        leaks=(str(calendar_path), calendar_path.as_posix(), "ComputeError", "PAR1"),
    )
    output = tmp_path / "out.parquet"
    code = main(_mixed_argv(fixture, output=output))
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip() == "BAR_WINDOW_REFERENCE_INVALID"
    assert marker not in captured.err
    assert marker not in captured.out
    assert str(calendar_path) not in captured.err
    assert str(calendar_path) not in captured.out
    assert not output.exists()


def test_mixed_actual_duckdb_bar_io_error_has_empty_exception_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fixture = publish_minimal_v3(tmp_path, monkeypatch)
    _prepare_mixed_refs(fixture, ["00001.HK"])
    membership = (
        fixture.data_root / "clean" / "universe_membership" / "universe=SH_CONNECT" / "data.parquet"
    )
    query = BarQuery(fixture.clean_root)
    audited = query.recent_for_universe_mixed_audited(
        membership_path=membership,
        universe="SH_CONNECT",
        as_of=AS_OF,
        observations=1,
        bundle=fixture.bundle,
        plan=fixture.plan,
    )
    marker = r"C:\secret\hostile-duckdb-token"
    bar_path = fixture.clean_root / f"date={AS_OF.isoformat()}" / "data.parquet"
    leaks = (
        str(bar_path),
        str(bar_path.resolve()),
        bar_path.as_posix(),
        "InvalidInputException",
        "bar_1d",
    )
    bar_path.write_bytes(b"NOT-A-PARQUET-FILE " + marker.encode("utf-8"))
    with pytest.raises(BarWindowQueryError, match="^BAR_WINDOW_REFERENCE_INVALID$") as physical:
        query.audit_available_history_mixed(
            audited=audited,
            **_mixed_ah_paths(fixture),
            no_trade_evidences=fixture.plan.no_trade_evidence,
            no_trade_evidence_sha256=fixture.plan.no_trade_evidence_sha256,
        )
    _assert_detached_reference_invalid(physical.value, marker=marker, leaks=leaks)
    with pytest.raises(BarWindowQueryError, match="^BAR_WINDOW_REFERENCE_INVALID$") as mapped:
        query.recent_for_universe_mixed_audited(
            membership_path=membership,
            universe="SH_CONNECT",
            as_of=AS_OF,
            observations=1,
            bundle=fixture.bundle,
            plan=fixture.plan,
        )
    _assert_detached_reference_invalid(mapped.value, marker=marker, leaks=leaks)
    output = tmp_path / "out.parquet"
    code = main(_mixed_argv(fixture, output=output))
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip() in {"HK_BAR_VERIFY_FAILED", "BAR_WINDOW_REFERENCE_INVALID"}
    assert marker not in captured.err
    assert marker not in captured.out
    assert str(bar_path) not in captured.err
    assert str(bar_path) not in captured.out
    assert not output.exists()
