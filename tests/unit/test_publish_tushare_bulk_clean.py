from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path

import polars as pl
import pytest

from quant.data.publish_tushare_bulk_clean import (
    TushareBulkCleanPublishError,
    main,
    publish_tushare_bulk_clean_snapshot,
    verify_tushare_bulk_clean_snapshot,
)


def _frame(dataset: str, *, all_eligible: bool = False) -> pl.DataFrame:
    if dataset == "daily":
        frame = pl.DataFrame(
            {
                "ts_code": ["600001.SH", "600002.SH", "920001.BJ"],
                "trade_date": ["20250813"] * 3,
                "open": [10.0, 10.0, 5.0],
                "high": [11.0, 9.0, 6.0],
                "low": [9.0, 8.0, 4.0],
                "close": [10.5, 8.5, 5.5],
                "vol": [100.0, 200.0, 300.0],
                "amount": [1000.0, 2000.0, 3000.0],
            }
        )
        return frame.head(1) if all_eligible else frame
    if dataset == "adj_factor":
        frame = pl.DataFrame(
            {
                "ts_code": ["600001.SH", "600002.SH", "920001.BJ"],
                "trade_date": ["20250813"] * 3,
                "adj_factor": [2.0, 2.0, 1.0],
            }
        )
        return frame.head(1) if all_eligible else frame
    if dataset == "fund_daily":
        frame = pl.DataFrame(
            {
                "ts_code": ["510300.SH", "159001.SZ"],
                "trade_date": ["20250813"] * 2,
                "open": [4.0, 2.0],
                "high": [4.1, 2.1],
                "low": [3.9, 1.9],
                "close": [4.0, 2.0],
                "vol": [100.0, 200.0],
                "amount": [400.0, 400.0],
            }
        )
        return frame.head(1) if all_eligible else frame
    if dataset == "fund_adj":
        return pl.DataFrame(
            {
                "ts_code": ["510300.SH"],
                "trade_date": ["20250813"],
                "adj_factor": [1.5],
            }
        )
    raise AssertionError(dataset)


def _raw_request(
    root: Path, *, dataset: str, request_id: str, all_eligible: bool
) -> tuple[str, int]:
    frame = _frame(dataset, all_eligible=all_eligible)
    directory = root / "raw" / "tushare" / dataset / f"request={request_id}"
    directory.mkdir(parents=True)
    data = directory / "data.parquet"
    frame.write_parquet(data)
    payload = data.read_bytes()
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
        json.dumps(metadata, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    return checksum, frame.height


def _data_root(tmp_path: Path, *, all_eligible: bool = False) -> Path:
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
            checksum, rows = _raw_request(
                root,
                dataset=dataset,
                request_id=request_id,
                all_eligible=all_eligible,
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
                    rows,
                    checksum,
                    None,
                    "2026-08-14T00:00:00+00:00",
                ),
            )
    return root


def _replace_dataset(root: Path, *, dataset: str, frame: pl.DataFrame) -> None:
    directory = next((root / "raw" / "tushare" / dataset).glob("request=*"))
    data = directory / "data.parquet"
    frame.write_parquet(data)
    payload = data.read_bytes()
    checksum = hashlib.sha256(payload).hexdigest()
    metadata_path = directory / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update(
        {
            "rows": frame.height,
            "columns": frame.columns,
            "checksum_sha256": checksum,
            "size_bytes": len(payload),
        }
    )
    metadata_path.write_text(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    with sqlite3.connect(root / "run_state" / "tushare_bulk" / "state.sqlite") as connection:
        connection.execute(
            "UPDATE requests SET rows=?,checksum_sha256=? WHERE dataset=?",
            (frame.height, checksum, dataset),
        )


def test_publish_verify_and_reuse_scoped_snapshot(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    first = publish_tushare_bulk_clean_snapshot(data_root=root)
    assert first.reused is False
    assert (first.stock_rows, first.fund_rows, first.quarantine_rows) == (1, 1, 3)
    stock = pl.read_parquet(
        first.root / "bar_1d" / "asset=stock" / "year=2025" / "data.parquet"
    )
    assert stock.select("symbol", "volume", "amount", "adj_factor").row(0) == (
        "600001.SH",
        10000.0,
        1_000_000.0,
        2.0,
    )
    quarantine = pl.read_parquet(first.root / "quarantine.parquet")
    assert quarantine.select("asset", "symbol", "reason").rows() == [
        ("fund", "159001.SZ", "ADJ_FACTOR_MISSING"),
        ("stock", "600002.SH", "OHLC_RELATION_INVALID"),
        ("stock", "920001.BJ", "UNSUPPORTED_SYMBOL"),
    ]
    verified = verify_tushare_bulk_clean_snapshot(
        data_root=root, snapshot_id=first.snapshot_id
    )
    assert verified.reused is True
    assert verified.manifest_sha256 == first.manifest_sha256
    replay = publish_tushare_bulk_clean_snapshot(data_root=root)
    assert replay.reused is True
    assert replay == verified


def test_tamper_and_raw_drift_fail_closed(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    published = publish_tushare_bulk_clean_snapshot(data_root=root)
    quarantine = published.root / "quarantine.parquet"
    quarantine.write_bytes(quarantine.read_bytes() + b"drift")
    with pytest.raises(
        TushareBulkCleanPublishError,
        match="^TUSHARE_BULK_CLEAN_PUBLISH_INVALID$",
    ) as captured:
        verify_tushare_bulk_clean_snapshot(
            data_root=root, snapshot_id=published.snapshot_id
        )
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None

    other = _data_root(tmp_path / "other")
    raw = next((other / "raw" / "tushare" / "daily").glob("*/data.parquet"))
    raw.write_bytes(raw.read_bytes() + b"drift")
    with pytest.raises(TushareBulkCleanPublishError):
        publish_tushare_bulk_clean_snapshot(data_root=other)
    assert not (other / "clean").exists()


def test_fully_ready_input_publishes_empty_quarantine(tmp_path: Path) -> None:
    root = _data_root(tmp_path, all_eligible=True)
    published = publish_tushare_bulk_clean_snapshot(data_root=root)
    assert (published.stock_rows, published.fund_rows, published.quarantine_rows) == (
        1,
        1,
        0,
    )
    quarantine = pl.read_parquet(published.root / "quarantine.parquet")
    assert quarantine.is_empty()
    assert verify_tushare_bulk_clean_snapshot(
        data_root=root, snapshot_id=published.snapshot_id
    ).quarantine_rows == 0


def test_duplicate_factor_and_foreign_snapshot_fail_without_clobber(
    tmp_path: Path,
) -> None:
    root = _data_root(tmp_path)
    factor = _frame("adj_factor").head(1)
    _replace_dataset(
        root,
        dataset="adj_factor",
        frame=pl.concat([factor, factor], how="vertical"),
    )
    with pytest.raises(TushareBulkCleanPublishError):
        publish_tushare_bulk_clean_snapshot(data_root=root)
    assert not (root / "clean").exists()

    other = _data_root(tmp_path / "other")
    foreign = (
        other
        / "clean"
        / "tushare_bulk"
        / "snapshots"
        / ("f" * 64)
    )
    foreign.mkdir(parents=True)
    marker = foreign / "foreign.txt"
    marker.write_text("owned elsewhere", encoding="utf-8")
    with pytest.raises(TushareBulkCleanPublishError):
        publish_tushare_bulk_clean_snapshot(data_root=other)
    assert marker.read_text(encoding="utf-8") == "owned elsewhere"


def test_extra_or_missing_snapshot_file_is_rejected(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    published = publish_tushare_bulk_clean_snapshot(data_root=root)
    extra = published.root / "extra.txt"
    extra.write_text("extra", encoding="utf-8")
    with pytest.raises(TushareBulkCleanPublishError):
        verify_tushare_bulk_clean_snapshot(
            data_root=root, snapshot_id=published.snapshot_id
        )
    extra.unlink()
    partition = next((published.root / "bar_1d").rglob("data.parquet"))
    partition.unlink()
    with pytest.raises(TushareBulkCleanPublishError):
        verify_tushare_bulk_clean_snapshot(
            data_root=root, snapshot_id=published.snapshot_id
        )


def test_cli_and_invalid_threads(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _data_root(tmp_path)
    assert main(["--data-root", str(root), "--threads", "1"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["stock_rows"] == 1
    assert output["fund_rows"] == 1
    assert output["quarantine_rows"] == 3
    with pytest.raises(TushareBulkCleanPublishError):
        publish_tushare_bulk_clean_snapshot(data_root=root, threads=0)
