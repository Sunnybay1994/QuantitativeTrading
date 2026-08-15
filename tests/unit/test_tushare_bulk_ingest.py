from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import polars as pl

from quant.data.tushare_bulk import load_catalog, probe_permissions
from quant.data.tushare_bulk_ingest import ledger_summary, prepare_requests, run_requests


class _Client:
    def query(self, api_name: str, **params: str) -> object:
        del api_name, params
        return pl.DataFrame({"trade_date": ["20260102"]})


class _Connector:
    def __init__(self, rows: int = 1) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict[str, str]]] = []

    def query_raw(self, api_name: str, **params: str) -> pl.DataFrame:
        self.calls.append((api_name, params))
        return pl.DataFrame({"value": list(range(self.rows))})


def _catalog(path: Path, *, max_rows: int = 6000) -> Path:
    path.write_text(
        f'''datasets = [
  {{ name = "daily", api_name = "daily", category = "stock", priority = "core", probe_mode = "query", probe_params = {{ ts_code = "000001.SZ", start_date = "20260101", end_date = "20260102" }}, request_unit = "per_trade_date", inventory = "none", history_start = 2026-01-01, max_rows = {max_rows}, chunk_days = 1, partition = "year", overlap_days = 5 }},
]
[meta]
schema_version = "tushare-bulk-catalog-v1"
catalog_version = "test-v1"
source_url = "https://example.invalid"
captured_on = 2026-08-14
''',
        encoding="utf-8",
    )
    return path


def _data_root(path: Path) -> Path:
    calendar = path / "clean" / "trade_calendar" / "market=SH"
    calendar.mkdir(parents=True)
    pl.DataFrame({
        "date": [dt.date(2026, 1, 2), dt.date(2026, 1, 3)],
        "is_open": [True, False],
    }).write_parquet(calendar / "data.parquet")
    return path


def _per_symbol_catalog(path: Path) -> Path:
    path.write_text(
        '''datasets = [
  { name = "income", api_name = "income", category = "finance", priority = "core", probe_mode = "query", probe_params = { ts_code = "000001.SZ", period = "20231231" }, request_unit = "per_symbol", inventory = "stock", history_start = 2026-01-01, max_rows = 6000, chunk_days = 2, partition = "report_year", overlap_days = 500 },
]
[meta]
schema_version = "tushare-bulk-catalog-v1"
catalog_version = "test-v1"
source_url = "https://example.invalid"
captured_on = 2026-08-14
''',
        encoding="utf-8",
    )
    return path


def _stock_inventory(root: Path) -> None:
    target = root / "clean" / "instrument" / "market=SH"
    target.mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": ["600001.SH", "600002.SH"],
            "market": ["SH", "SH"],
            "instrument_type": ["STOCK", "STOCK"],
        }
    ).write_parquet(target / "data.parquet")


def test_prepare_and_run_write_deterministic_raw_and_resume(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path / "catalog.toml"))
    report = probe_permissions(
        catalog=catalog,
        client=_Client(),
        now=dt.datetime(2026, 8, 14, tzinfo=dt.timezone.utc),
        sleeper=lambda _: None,
    )
    root = _data_root(tmp_path / "data")
    ledger = root / "run_state" / "state.sqlite"
    prepared = prepare_requests(
        catalog=catalog,
        permission_report=report,
        data_root=root,
        ledger_path=ledger,
        datasets=frozenset({"daily"}),
        start=dt.date(2026, 1, 1),
        end=dt.date(2026, 1, 3),
    )
    assert prepared == {"planned": 1, "inserted": 1, "existing": 0}
    connector = _Connector()
    assert run_requests(
        connector=connector,
        data_root=root,
        ledger_path=ledger,
        max_requests=2,
        requests_per_minute=100,
        sleeper=lambda _: None,
    ) == {"completed": 1, "retryable": 0, "failed": 0}
    assert ledger_summary(ledger) == {"COMPLETE": 1}
    assert len(list((root / "raw" / "tushare" / "daily").rglob("data.parquet"))) == 1
    assert not connector.calls[0][1].keys() & {"ts_code", "start_date", "end_date"}
    with sqlite3.connect(ledger) as conn:
        conn.execute("UPDATE requests SET status='PENDING'")
        conn.commit()
    recovered = _Connector()
    assert run_requests(
        connector=recovered,
        data_root=root,
        ledger_path=ledger,
        max_requests=1,
        requests_per_minute=100,
        sleeper=lambda _: None,
    )["completed"] == 1
    assert recovered.calls == []


def test_row_cap_fails_closed_without_writing_raw(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path / "catalog.toml", max_rows=1))
    report = probe_permissions(
        catalog=catalog,
        client=_Client(),
        now=dt.datetime(2026, 8, 14, tzinfo=dt.timezone.utc),
        sleeper=lambda _: None,
    )
    root = _data_root(tmp_path / "data")
    ledger = root / "state.sqlite"
    prepare_requests(
        catalog=catalog,
        permission_report=report,
        data_root=root,
        ledger_path=ledger,
        datasets=frozenset({"daily"}),
        start=dt.date(2026, 1, 1),
        end=dt.date(2026, 1, 3),
    )
    result = run_requests(
        connector=_Connector(rows=1),
        data_root=root,
        ledger_path=ledger,
        max_requests=1,
        requests_per_minute=100,
        sleeper=lambda _: None,
    )
    assert result == {"completed": 0, "retryable": 0, "failed": 1}
    assert ledger_summary(ledger) == {"SPLIT_REQUIRED": 1}
    assert len(list((root / "raw").rglob("data.parquet"))) == 1


def test_per_symbol_requests_match_planned_non_overlapping_time_chunks(
    tmp_path: Path,
) -> None:
    catalog = load_catalog(_per_symbol_catalog(tmp_path / "catalog.toml"))
    report = probe_permissions(
        catalog=catalog,
        client=_Client(),
        now=dt.datetime(2026, 8, 14, tzinfo=dt.timezone.utc),
        sleeper=lambda _: None,
    )
    root = tmp_path / "data"
    _stock_inventory(root)
    ledger = root / "run_state" / "state.sqlite"
    prepared = prepare_requests(
        catalog=catalog,
        permission_report=report,
        data_root=root,
        ledger_path=ledger,
        datasets=frozenset({"income"}),
        start=dt.date(2026, 1, 1),
        end=dt.date(2026, 1, 5),
    )
    assert prepared == {"planned": 6, "inserted": 6, "existing": 0}
    with sqlite3.connect(ledger) as conn:
        parameters = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT parameters_json FROM requests"
            )
        ]
    parameters.sort(key=lambda row: (row["ts_code"], row["start_date"]))
    assert parameters == [
        {
            "end_date": end,
            "start_date": start,
            "ts_code": symbol,
        }
        for symbol in ("600001.SH", "600002.SH")
        for start, end in (
            ("20260101", "20260102"),
            ("20260103", "20260104"),
            ("20260105", "20260105"),
        )
    ]
    assert all("period" not in row for row in parameters)
