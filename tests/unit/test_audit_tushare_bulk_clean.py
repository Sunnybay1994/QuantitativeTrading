from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path

import polars as pl
import pytest

from quant.data.audit_tushare_bulk_clean import (
    audit_tushare_bulk_clean_admission,
    main,
)


def _request(
    root: Path, *, dataset: str, request_id: str, frame: pl.DataFrame
) -> tuple[str, int, int]:
    directory = root / "raw" / "tushare" / dataset / f"request={request_id}"
    directory.mkdir(parents=True)
    data = directory / "data.parquet"
    frame.write_parquet(data)
    raw = data.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
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
        "size_bytes": len(raw),
    }
    (directory / "metadata.json").write_text(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    return checksum, frame.height, len(raw)


def _root(
    tmp_path: Path, *, bad: bool = False, fund_factor_date: str = "20260813"
) -> Path:
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
        for index, (dataset, frame) in enumerate(
            (
                (
                    "daily",
                    pl.DataFrame(
                        {
                            "ts_code": ["600001.SH"],
                            "trade_date": ["20260813"],
                            "open": [11.0],
                            "high": [10.0 if bad else 12.0],
                            "low": [9.0],
                            "close": [10.0],
                            "vol": [100.0],
                            "amount": [1000.0],
                        }
                    ),
                ),
                (
                    "adj_factor",
                    pl.DataFrame(
                        {
                            "ts_code": ["600001.SH"],
                            "trade_date": ["20260813"],
                            "adj_factor": [2.0],
                        }
                    ),
                ),
                (
                    "fund_daily",
                    pl.DataFrame(
                        {
                            "ts_code": ["510300.SH"],
                            "trade_date": [fund_factor_date],
                            "open": [4.0],
                            "high": [4.1],
                            "low": [3.9],
                            "close": [4.0],
                            "vol": [100.0],
                            "amount": [400.0],
                        }
                    ),
                ),
                (
                    "fund_adj",
                    pl.DataFrame(
                        {
                            "ts_code": ["510300.SH"],
                            "trade_date": ["20260813"],
                            "adj_factor": [1.5],
                        }
                    ),
                ),
            ),
            1,
        ):
            request_id = f"{index:064x}"
            checksum, rows, _ = _request(
                root, dataset=dataset, request_id=request_id, frame=frame
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


def test_ready_fixture_is_deterministic_and_does_not_write(tmp_path: Path) -> None:
    root = _root(tmp_path)
    before = sorted(path.relative_to(root) for path in root.rglob("*"))
    first = audit_tushare_bulk_clean_admission(data_root=root)
    second = audit_tushare_bulk_clean_admission(data_root=root)
    assert first == second
    assert first["status"] == "READY"
    assert first["request_count"] == 4
    assert first["blocking_issues"] == []
    assert first["scoped_clean_plan"]["status"] == "READY"
    assert first["scoped_clean_plan"]["stock_bar_1d"]["eligible_rows"] == 1
    assert first["scoped_clean_plan"]["fund_bar_1d"]["eligible_rows"] == 1
    assert sorted(path.relative_to(root) for path in root.rglob("*")) == before


def test_ohlc_anomaly_blocks_clean_admission(tmp_path: Path) -> None:
    result = audit_tushare_bulk_clean_admission(data_root=_root(tmp_path, bad=True))
    assert result["status"] == "BLOCKED"
    assert {item["code"] for item in result["blocking_issues"]} == {
        "DAILY_OHLC_RELATION_INVALID"
    }
    assert result["scoped_clean_plan"]["stock_bar_1d"]["reasons"] == {
        "OHLC_RELATION_INVALID": 1
    }


def test_byte_or_directory_closure_drift_fails_closed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    path = next((root / "raw" / "tushare" / "daily").glob("*/data.parquet"))
    path.write_bytes(path.read_bytes() + b"drift")
    with pytest.raises(ValueError, match="^TUSHARE_BULK_CLEAN_AUDIT_INVALID$"):
        audit_tushare_bulk_clean_admission(data_root=root)

    root = _root(tmp_path / "other")
    (root / "raw" / "tushare" / "daily" / f"request={'f' * 64}").mkdir()
    with pytest.raises(ValueError, match="^TUSHARE_BULK_CLEAN_AUDIT_INVALID$"):
        audit_tushare_bulk_clean_admission(data_root=root)


def test_scoped_plan_classifies_missing_fund_factor_once(tmp_path: Path) -> None:
    result = audit_tushare_bulk_clean_admission(
        data_root=_root(tmp_path, fund_factor_date="20260812")
    )
    assert result["status"] == "BLOCKED"
    assert result["scoped_clean_plan"]["fund_bar_1d"] == {
        "source_rows": 1,
        "classified_rows": 1,
        "eligible_rows": 0,
        "quarantined_rows": 1,
        "reasons": {"ADJ_FACTOR_MISSING": 1},
    }

def test_cli_writes_once_and_returns_blocked_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path, bad=True)
    output = tmp_path / "audit.json"
    assert main(["--data-root", str(root), "--output", str(output)]) == 3
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "BLOCKED"
    assert json.loads(capsys.readouterr().out) == result
    with pytest.raises(
        ValueError, match="^TUSHARE_BULK_CLEAN_AUDIT_OUTPUT_INVALID$"
    ):
        main(["--data-root", str(root), "--output", str(output)])
