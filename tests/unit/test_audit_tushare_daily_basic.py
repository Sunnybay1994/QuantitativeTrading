from __future__ import annotations

import hashlib
import json
import sqlite3
import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.data.audit_tushare_daily_basic import audit_tushare_daily_basic
from quant.data.daily_basic_repository import (
    TushareDailyBasicQuery,
    TushareDailyBasicReadError,
    read_tushare_daily_basic,
)
from quant.data.publish_tushare_daily_basic import (
    TushareDailyBasicPublishError,
    publish_tushare_daily_basic_snapshot,
    verify_tushare_daily_basic_snapshot,
)


def _frame(*, symbol: str = "000001.SZ", trade_date: str = "20260814") -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts_code": [symbol],
            "trade_date": [trade_date],
            "close": [10.0],
            "turnover_rate": [1.0],
            "turnover_rate_f": [1.2],
            "volume_ratio": [None],
            "pe": [-10.0],
            "pe_ttm": [-9.0],
            "pb": [1.0],
            "ps": [2.0],
            "ps_ttm": [1.9],
            "dv_ratio": [None],
            "dv_ttm": [1.0],
            "total_share": [1000.0],
            "float_share": [800.0],
            "free_share": [700.0],
            "total_mv": [10_000.0],
            "circ_mv": [8_000.0],
        }
    )


def _add_raw(
    root: Path,
    *,
    request_id: str,
    frame: pl.DataFrame,
    trade_date: str,
) -> tuple[str, int]:
    request_root = (
        root / "raw" / "tushare" / "daily_basic" / f"request={request_id}"
    )
    request_root.mkdir(parents=True)
    parquet = request_root / "data.parquet"
    frame.write_parquet(parquet)
    payload = parquet.read_bytes()
    checksum = hashlib.sha256(payload).hexdigest()
    metadata = {
        "checksum_sha256": checksum,
        "columns": frame.columns,
        "fetched_at": "2026-08-15T00:00:00+00:00",
        "parameters": {"trade_date": trade_date},
        "request_id": request_id,
        "rows": frame.height,
        "schema_version": "request-raw-v1",
        "size_bytes": len(payload),
        "snapshot_id": request_id,
        "source": "tushare",
        "table": "daily_basic",
    }
    (request_root / "metadata.json").write_text(
        json.dumps(metadata, separators=(",", ":")), encoding="utf-8"
    )
    return checksum, frame.height


def _root(tmp_path: Path, *, pending: bool = False) -> Path:
    root = tmp_path / "data"
    ledger = root / "run_state" / "tushare_bulk" / "state.sqlite"
    ledger.parent.mkdir(parents=True)
    request_id = "1" * 64
    checksum, rows = _add_raw(
        root,
        request_id=request_id,
        frame=_frame(),
        trade_date="20260814",
    )
    with sqlite3.connect(ledger) as connection:
        connection.execute(
            "CREATE TABLE requests(request_id TEXT PRIMARY KEY, catalog_sha256 TEXT, "
            "dataset TEXT, api_name TEXT, parameters_json TEXT, max_rows INTEGER, "
            "status TEXT, attempts INTEGER, rows INTEGER, checksum_sha256 TEXT, "
            "error_code TEXT, updated_at TEXT)"
        )
        connection.execute(
            "INSERT INTO requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                request_id,
                "a" * 64,
                "daily_basic",
                "daily_basic",
                json.dumps({"trade_date": "20260814"}, separators=(",", ":")),
                6000,
                "COMPLETE",
                1,
                rows,
                checksum,
                None,
                "2026-08-15T00:00:00+00:00",
            ),
        )
        if pending:
            connection.execute(
                "INSERT INTO requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "2" * 64,
                    "a" * 64,
                    "daily_basic",
                    "daily_basic",
                    json.dumps(
                        {"trade_date": "20260815"}, separators=(",", ":")
                    ),
                    6000,
                    "PENDING",
                    0,
                    0,
                    None,
                    None,
                    "2026-08-15T00:00:00+00:00",
                ),
            )
    return root


def _replace_complete_frame(root: Path, frame: pl.DataFrame) -> Path:
    parquet = next(
        (root / "raw" / "tushare" / "daily_basic").glob("*/data.parquet")
    )
    frame.write_parquet(parquet)
    metadata_path = parquet.parent / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload = parquet.read_bytes()
    metadata["checksum_sha256"] = hashlib.sha256(payload).hexdigest()
    metadata["size_bytes"] = len(payload)
    metadata["rows"] = frame.height
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    ledger = root / "run_state" / "tushare_bulk" / "state.sqlite"
    with sqlite3.connect(ledger) as connection:
        connection.execute(
            "UPDATE requests SET checksum_sha256 = ?, rows = ?",
            (metadata["checksum_sha256"], frame.height),
        )
    return parquet


def test_partial_ledger_is_collecting_and_read_only(tmp_path: Path) -> None:
    root = _root(tmp_path, pending=True)
    before = sorted(path.relative_to(root) for path in root.rglob("*"))
    result = audit_tushare_daily_basic(data_root=root, verify_bytes=True)
    assert result["status"] == "COLLECTING"
    assert result["ledger"]["status_counts"] == {"COMPLETE": 1, "PENDING": 1}
    assert result["quality"]["eligible_rows"] == 1
    assert result["blocking_issues"] == []
    assert sorted(path.relative_to(root) for path in root.rglob("*")) == before


def test_complete_supported_fixture_is_ready(tmp_path: Path) -> None:
    result = audit_tushare_daily_basic(data_root=_root(tmp_path))
    assert result["status"] == "READY"
    assert result["raw_closure"]["complete_request_count"] == 1
    assert result["raw_closure"]["catalog_sha256s"] == ["a" * 64]
    assert len(result["raw_closure"]["request_set_sha256"]) == 64
    assert result["quality"]["raw_rows"] == 1
    assert result["quality"]["duplicate_keys"] == 0
    assert result["clean_scope"] == {
        "supported_markets": ["SH", "SZ"],
        "eligible_rows": 1,
        "quarantined_rows": 0,
        "quarantine_reasons": {},
        "raw_share_and_market_value_multiplier": 10_000,
        "raw_close_is_not_bar_authority": True,
    }


def test_parameter_date_drift_blocks_and_byte_drift_fails_closed(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    parquet = _replace_complete_frame(root, _frame(trade_date="20260813"))
    result = audit_tushare_daily_basic(data_root=root, verify_bytes=True)
    assert result["status"] == "BLOCKED"
    assert {issue["code"] for issue in result["blocking_issues"]} == {
        "PARAMETER_DATE_MISMATCH"
    }

    parquet.write_bytes(parquet.read_bytes() + b"drift")
    with pytest.raises(ValueError, match="^TUSHARE_DAILY_BASIC_AUDIT_INVALID$"):
        audit_tushare_daily_basic(data_root=root, verify_bytes=True)


def test_per_request_row_count_drift_cannot_cancel_out(tmp_path: Path) -> None:
    root = _root(tmp_path)
    first_metadata_path = next(
        (root / "raw" / "tushare" / "daily_basic").glob("*/metadata.json")
    )
    first_metadata = json.loads(first_metadata_path.read_text(encoding="utf-8"))
    first_metadata["rows"] = 2
    first_metadata_path.write_text(
        json.dumps(first_metadata, separators=(",", ":")), encoding="utf-8"
    )

    second_id = "2" * 64
    second_frame = pl.concat(
        [_frame(symbol="000002.SZ"), _frame(symbol="000003.SZ")]
    )
    second_checksum, _ = _add_raw(
        root,
        request_id=second_id,
        frame=second_frame,
        trade_date="20260814",
    )
    second_metadata_path = (
        root
        / "raw"
        / "tushare"
        / "daily_basic"
        / f"request={second_id}"
        / "metadata.json"
    )
    second_metadata = json.loads(second_metadata_path.read_text(encoding="utf-8"))
    second_metadata["rows"] = 1
    second_metadata_path.write_text(
        json.dumps(second_metadata, separators=(",", ":")), encoding="utf-8"
    )

    ledger = root / "run_state" / "tushare_bulk" / "state.sqlite"
    with sqlite3.connect(ledger) as connection:
        connection.execute(
            "UPDATE requests SET rows = 2 WHERE request_id = ?", ("1" * 64,)
        )
        connection.execute(
            "INSERT INTO requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                second_id,
                "a" * 64,
                "daily_basic",
                "daily_basic",
                json.dumps({"trade_date": "20260814"}, separators=(",", ":")),
                6000,
                "COMPLETE",
                1,
                1,
                second_checksum,
                None,
                "2026-08-15T00:00:00+00:00",
            ),
        )

    result = audit_tushare_daily_basic(data_root=root, verify_bytes=True)
    assert result["ledger"]["complete_rows"] == result["quality"]["raw_rows"] == 3
    assert result["quality"]["row_count_mismatch"] == 2
    assert result["status"] == "BLOCKED"
    assert result["blocking_issues"] == [
        {"code": "LEDGER_RAW_ROW_COUNT_MISMATCH", "count": 2}
    ]


def test_publish_verify_reuse_and_tamper_detection(tmp_path: Path) -> None:
    root = _root(tmp_path)
    first = publish_tushare_daily_basic_snapshot(data_root=root, threads=1)
    assert first.rows == 1
    assert first.quarantine_rows == 0
    assert first.reused is False
    assert (first.root / "year=2026" / "data.parquet").is_file()
    clean = pl.read_parquet(first.root / "year=2026" / "data.parquet")
    assert clean.row(0, named=True)["total_shares"] == 10_000_000.0

    second = publish_tushare_daily_basic_snapshot(data_root=root, threads=1)
    assert second.snapshot_id == first.snapshot_id
    assert second.manifest_sha256 == first.manifest_sha256
    assert second.reused is True
    verified = verify_tushare_daily_basic_snapshot(
        data_root=root, snapshot_id=first.snapshot_id
    )
    assert verified.reused is True

    path = first.root / "year=2026" / "data.parquet"
    path.write_bytes(path.read_bytes() + b"drift")
    with pytest.raises(
        TushareDailyBasicPublishError,
        match="^TUSHARE_DAILY_BASIC_PUBLISH_INVALID$",
    ):
        verify_tushare_daily_basic_snapshot(
            data_root=root, snapshot_id=first.snapshot_id
        )


def test_snapshot_identity_binds_raw_data_and_metadata_bytes(tmp_path: Path) -> None:
    baseline_root = _root(tmp_path / "baseline")
    data_root = _root(tmp_path / "data-change")
    metadata_root = _root(tmp_path / "metadata-change")

    changed = _frame().with_columns(pl.lit(11.0).alias("pe_ttm"))
    _replace_complete_frame(data_root, changed)
    metadata_path = next(
        (metadata_root / "raw" / "tushare" / "daily_basic").glob(
            "*/metadata.json"
        )
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["fetched_at"] = "2026-08-15T01:00:00+00:00"
    metadata_path.write_text(
        json.dumps(metadata, separators=(",", ":")), encoding="utf-8"
    )

    audits = [
        audit_tushare_daily_basic(data_root=root, verify_bytes=True)
        for root in (baseline_root, data_root, metadata_root)
    ]
    assert {audit["status"] for audit in audits} == {"READY"}
    assert len({audit["raw_closure"]["request_set_sha256"] for audit in audits}) == 3

    snapshots = [
        publish_tushare_daily_basic_snapshot(data_root=root, threads=1)
        for root in (baseline_root, data_root, metadata_root)
    ]
    assert len({snapshot.snapshot_id for snapshot in snapshots}) == 3


def test_partial_input_cannot_create_clean_snapshot(tmp_path: Path) -> None:
    root = _root(tmp_path, pending=True)
    with pytest.raises(
        TushareDailyBasicPublishError,
        match="^TUSHARE_DAILY_BASIC_PUBLISH_INVALID$",
    ):
        publish_tushare_daily_basic_snapshot(data_root=root)
    assert not (root / "clean").exists()


def test_unsupported_market_is_preserved_only_in_quarantine(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _replace_complete_frame(root, _frame(symbol="920001.BJ"))
    audit = audit_tushare_daily_basic(data_root=root, verify_bytes=True)
    assert audit["status"] == "READY"
    assert audit["clean_scope"]["quarantine_reasons"] == {
        "UNSUPPORTED_MARKET": 1
    }
    snapshot = publish_tushare_daily_basic_snapshot(data_root=root, threads=1)
    assert snapshot.rows == 0
    assert snapshot.quarantine_rows == 1
    quarantine = pl.read_parquet(snapshot.root / "quarantine.parquet")
    assert quarantine.row(0) == ("920001.BJ", "20260814", "UNSUPPORTED_MARKET")


def test_observed_share_and_market_value_anomalies_are_quarantined(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    eligible = _frame(symbol="000001.SZ")
    bad_shares = _frame(symbol="000002.SZ").with_columns(
        pl.lit(1_100.0).alias("float_share")
    )
    bad_market_value = _frame(symbol="000003.SZ").with_columns(
        pl.lit(11_000.0).alias("circ_mv")
    )
    _replace_complete_frame(
        root,
        pl.concat([eligible, bad_shares, bad_market_value]),
    )

    audit = audit_tushare_daily_basic(data_root=root, verify_bytes=True)
    assert audit["status"] == "READY"
    assert audit["quality"]["eligible_rows"] == 1
    assert audit["clean_scope"]["quarantine_reasons"] == {
        "MARKET_VALUE_RELATION_INVALID": 1,
        "SHARE_RELATION_INVALID": 1,
    }

    snapshot = publish_tushare_daily_basic_snapshot(data_root=root, threads=1)
    assert snapshot.rows == 1
    assert snapshot.quarantine_rows == 2
    quarantine = pl.read_parquet(snapshot.root / "quarantine.parquet")
    assert quarantine.rows() == [
        ("000002.SZ", "20260814", "SHARE_RELATION_INVALID"),
        ("000003.SZ", "20260814", "MARKET_VALUE_RELATION_INVALID"),
    ]


def test_bounded_repository_reads_only_requested_dates_and_symbols(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    snapshot = publish_tushare_daily_basic_snapshot(data_root=root, threads=1)
    query = TushareDailyBasicQuery(
        snapshot_id=snapshot.snapshot_id,
        start_date=dt.date(2026, 8, 14),
        end_date=dt.date(2026, 8, 14),
        symbols=("000001.SZ",),
        threads=1,
    )
    first = read_tushare_daily_basic(data_root=root, query=query)
    second = read_tushare_daily_basic(data_root=root, query=query)
    assert first.equals(second)
    assert first.select("symbol", "trade_date").row(0) == (
        "000001.SZ",
        dt.date(2026, 8, 14),
    )

    with pytest.raises(
        TushareDailyBasicReadError,
        match="^TUSHARE_DAILY_BASIC_READ_INVALID$",
    ):
        TushareDailyBasicQuery(
            snapshot_id=snapshot.snapshot_id,
            start_date=dt.date(2026, 8, 14),
            end_date=dt.date(2026, 8, 14),
            symbols=("000001.SZ", "000001.SZ"),
        )
