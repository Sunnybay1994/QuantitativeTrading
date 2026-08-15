from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path

import polars as pl
import pytest

import quant.data.clean_snapshot_repository as repository
from quant.data.clean_snapshot_repository import (
    TushareBulkCleanReadError,
    TushareBulkFundBarQuery,
    TushareBulkStockBarQuery,
    read_tushare_bulk_clean_fund_bars,
    read_tushare_bulk_clean_stock_bars,
)
from quant.data.publish_tushare_bulk_clean import publish_tushare_bulk_clean_snapshot


def _raw_frame(dataset: str) -> pl.DataFrame:
    if dataset == "daily":
        return pl.DataFrame(
            {
                "ts_code": ["600002.SH", "600001.SH", "600001.SH"],
                "trade_date": ["20250813", "20250814", "20250813"],
                "open": [20.0, 11.0, 10.0],
                "high": [21.0, 12.0, 11.0],
                "low": [19.0, 10.0, 9.0],
                "close": [20.5, 11.5, 10.5],
                "vol": [200.0, 110.0, 100.0],
                "amount": [4000.0, 1210.0, 1000.0],
            }
        )
    if dataset == "adj_factor":
        return pl.DataFrame(
            {
                "ts_code": ["600001.SH", "600002.SH", "600001.SH"],
                "trade_date": ["20250813", "20250813", "20250814"],
                "adj_factor": [2.0, 1.0, 2.0],
            }
        )
    if dataset == "fund_daily":
        return pl.DataFrame(
            {
                "ts_code": ["510300.SH"],
                "trade_date": ["20250813"],
                "open": [4.0],
                "high": [4.1],
                "low": [3.9],
                "close": [4.0],
                "vol": [100.0],
                "amount": [400.0],
            }
        )
    if dataset == "fund_adj":
        return pl.DataFrame(
            {
                "ts_code": ["510300.SH"],
                "trade_date": ["20250813"],
                "adj_factor": [1.0],
            }
        )
    raise AssertionError(dataset)


def _data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    ledger = root / "run_state" / "tushare_bulk" / "state.sqlite"
    ledger.parent.mkdir(parents=True)
    with sqlite3.connect(ledger) as connection:
        connection.execute(
            "CREATE TABLE requests(request_id TEXT PRIMARY KEY, catalog_sha256 TEXT, "
            "dataset TEXT, api_name TEXT, parameters_json TEXT, max_rows INTEGER, "
            "status TEXT, attempts INTEGER, rows INTEGER, checksum_sha256 TEXT, "
            "error_code TEXT, updated_at TEXT)"
        )
        for index, dataset in enumerate(
            ("daily", "adj_factor", "fund_daily", "fund_adj"), 1
        ):
            request_id = f"{index:064x}"
            directory = root / "raw" / "tushare" / dataset / f"request={request_id}"
            directory.mkdir(parents=True)
            frame = _raw_frame(dataset)
            path = directory / "data.parquet"
            frame.write_parquet(path)
            payload = path.read_bytes()
            checksum = hashlib.sha256(payload).hexdigest()
            metadata = {
                "schema_version": "request-raw-v1",
                "snapshot_id": request_id,
                "source": "tushare",
                "table": dataset,
                "request_id": request_id,
                "fetched_at": dt.datetime(2026, 8, 14, tzinfo=dt.UTC).isoformat(),
                "parameters": {"fixture": dataset},
                "rows": frame.height,
                "columns": frame.columns,
                "checksum_sha256": checksum,
                "size_bytes": len(payload),
            }
            (directory / "metadata.json").write_text(
                json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            connection.execute(
                "INSERT INTO requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    request_id,
                    "a" * 64,
                    dataset,
                    dataset,
                    json.dumps({"fixture": dataset}, separators=(",", ":")),
                    100,
                    "COMPLETE",
                    1,
                    frame.height,
                    checksum,
                    None,
                    "2026-08-14T00:00:00+00:00",
                ),
            )
    return root


def test_bounded_read_is_filtered_sorted_and_deterministic(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    snapshot = publish_tushare_bulk_clean_snapshot(data_root=root, threads=1)
    query = TushareBulkStockBarQuery(
        snapshot_id=snapshot.snapshot_id,
        start_date=dt.date(2025, 8, 13),
        end_date=dt.date(2025, 8, 14),
        symbols=("600001.SH",),
        threads=1,
    )
    first = read_tushare_bulk_clean_stock_bars(data_root=root, query=query)
    second = read_tushare_bulk_clean_stock_bars(data_root=root, query=query)
    assert first.equals(second)
    assert first.select("symbol", "trade_date").rows() == [
        ("600001.SH", dt.date(2025, 8, 13)),
        ("600001.SH", dt.date(2025, 8, 14)),
    ]
    assert first.get_column("volume").to_list() == [10_000.0, 11_000.0]


def test_bounded_fund_read_uses_only_fund_partitions(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    snapshot = publish_tushare_bulk_clean_snapshot(data_root=root, threads=1)
    query = TushareBulkFundBarQuery(
        snapshot_id=snapshot.snapshot_id,
        start_date=dt.date(2025, 8, 13),
        end_date=dt.date(2025, 8, 13),
        symbols=("510300.SH",),
        threads=1,
    )

    frame = read_tushare_bulk_clean_fund_bars(data_root=root, query=query)

    assert frame.select("symbol", "trade_date", "close").rows() == [
        ("510300.SH", dt.date(2025, 8, 13), 4.0)
    ]


def test_query_contract_and_empty_range_fail_closed(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    snapshot = publish_tushare_bulk_clean_snapshot(data_root=root, threads=1)
    invalid = (
        {"start_date": dt.date(2025, 8, 15), "end_date": dt.date(2025, 8, 14)},
        {"symbols": ("600002.SH", "600001.SH")},
        {"symbols": ("600001.SH", "600001.SH")},
        {"threads": 5},
    )
    base = {
        "snapshot_id": snapshot.snapshot_id,
        "start_date": dt.date(2025, 8, 13),
        "end_date": dt.date(2025, 8, 14),
        "threads": 1,
    }
    for change in invalid:
        with pytest.raises(TushareBulkCleanReadError):
            TushareBulkStockBarQuery(**(base | change))  # type: ignore[arg-type]
    empty = TushareBulkStockBarQuery(
        snapshot_id=snapshot.snapshot_id,
        start_date=dt.date(2024, 1, 1),
        end_date=dt.date(2024, 1, 2),
        threads=1,
    )
    with pytest.raises(TushareBulkCleanReadError) as captured:
        read_tushare_bulk_clean_stock_bars(data_root=root, query=empty)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_missing_or_mid_read_changed_partition_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _data_root(tmp_path)
    snapshot = publish_tushare_bulk_clean_snapshot(data_root=root, threads=1)
    query = TushareBulkStockBarQuery(
        snapshot_id=snapshot.snapshot_id,
        start_date=dt.date(2025, 8, 13),
        end_date=dt.date(2025, 8, 14),
        threads=1,
    )
    original = repository._query_parquet

    def changed(*, paths: tuple[Path, ...], query: TushareBulkStockBarQuery) -> pl.DataFrame:
        frame = original(paths=paths, query=query)
        paths[0].write_bytes(paths[0].read_bytes() + b"drift")
        return frame

    monkeypatch.setattr(repository, "_query_parquet", changed)
    with pytest.raises(TushareBulkCleanReadError) as captured:
        read_tushare_bulk_clean_stock_bars(data_root=root, query=query)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None

    other_root = _data_root(tmp_path / "other")
    other = publish_tushare_bulk_clean_snapshot(data_root=other_root, threads=1)
    next((other.root / "bar_1d" / "asset=stock").rglob("data.parquet")).unlink()
    with pytest.raises(TushareBulkCleanReadError):
        read_tushare_bulk_clean_stock_bars(
            data_root=other_root,
            query=TushareBulkStockBarQuery(
                snapshot_id=other.snapshot_id,
                start_date=dt.date(2025, 8, 13),
                end_date=dt.date(2025, 8, 14),
                threads=1,
            ),
        )
