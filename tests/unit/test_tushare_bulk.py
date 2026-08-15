from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data.tushare_bulk import (
    build_request_plan,
    load_catalog,
    probe_permissions,
    write_run_document,
)


class _Client:
    def query(self, api_name: str, **params: str) -> object:
        del params
        if api_name == "denied":
            raise RuntimeError("2002: 没有权限")
        if api_name == "limited":
            raise RuntimeError("每分钟访问频率超过限制")
        if api_name == "empty":
            return pl.DataFrame()
        return pl.DataFrame({"value": [1]})


def _catalog(path: Path) -> Path:
    path.write_text(
        """
[meta]
schema_version = "tushare-bulk-catalog-v1"
catalog_version = "test-v1"
source_url = "https://example.invalid"
captured_on = 2026-08-14

[[datasets]]
name = "daily"
api_name = "daily"
category = "stock"
priority = "core"
probe_mode = "query"
probe_params = { ts_code = "000001.SZ" }
request_unit = "per_symbol"
inventory = "stock"
history_start = 2026-01-01
max_rows = 6000
chunk_days = 3000
partition = "year"
overlap_days = 5

[[datasets]]
name = "empty"
api_name = "empty"
category = "stock"
priority = "extended"
probe_mode = "query"
probe_params = {}
request_unit = "once"
inventory = "none"
history_start = ""
max_rows = 6000
chunk_days = 3000
partition = "snapshot"
overlap_days = 0

[[datasets]]
name = "denied"
api_name = "denied"
category = "stock"
priority = "archive"
probe_mode = "query"
probe_params = {}
request_unit = "once"
inventory = "none"
history_start = ""
max_rows = 6000
chunk_days = 3000
partition = "snapshot"
overlap_days = 0

[[datasets]]
name = "limited"
api_name = "limited"
category = "stock"
priority = "archive"
probe_mode = "query"
probe_params = {}
request_unit = "once"
inventory = "none"
history_start = ""
max_rows = 6000
chunk_days = 3000
partition = "snapshot"
overlap_days = 0
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path


def _shared_data(root: Path) -> None:
    instrument = root / "clean" / "instrument" / "market=SH"
    calendar = root / "clean" / "trade_calendar" / "market=SH"
    instrument.mkdir(parents=True)
    calendar.mkdir(parents=True)
    pl.DataFrame({
        "symbol": ["600000.SH", "510300.SH"],
        "market": ["SH", "SH"],
        "instrument_type": ["STOCK", "ETF"],
    }).write_parquet(instrument / "data.parquet")
    pl.DataFrame({
        "date": [dt.date(2026, 1, 2), dt.date(2026, 1, 3)],
        "is_open": [True, False],
    }).write_parquet(calendar / "data.parquet")


def test_probe_classifies_without_persisting_hostile_messages(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path / "catalog.toml"))
    report = probe_permissions(
        catalog=catalog,
        client=_Client(),
        requests_per_minute=120,
        now=dt.datetime(2026, 8, 14, tzinfo=dt.timezone.utc),
        sleeper=lambda _: None,
    )
    statuses = {row["dataset"]: row["status"] for row in report["results"]}
    assert statuses == {
        "daily": "ACCESSIBLE",
        "empty": "EMPTY_BUT_VALID",
        "denied": "PERMISSION_DENIED",
        "limited": "RATE_LIMITED",
    }
    assert "没有权限" not in json.dumps(report, ensure_ascii=False)


def test_plan_uses_shared_inventory_and_keeps_download_disabled(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path / "catalog.toml"))
    report = probe_permissions(
        catalog=catalog,
        client=_Client(),
        now=dt.datetime(2026, 8, 14, tzinfo=dt.timezone.utc),
        sleeper=lambda _: None,
    )
    data_root = tmp_path / "shared"
    data_root.mkdir()
    _shared_data(data_root)
    plan = build_request_plan(
        catalog=catalog,
        permission_report=report,
        data_root=data_root,
        as_of=dt.date(2026, 8, 14),
        now=dt.datetime(2026, 8, 14, tzinfo=dt.timezone.utc),
    )
    daily = plan["datasets"][0]
    assert daily["estimated_requests"] == 1
    assert plan["summary"]["historical_download_authorized"] is False
    assert plan["summary"]["unresolved_datasets"] == 3


def test_probe_retries_only_named_datasets_and_preserves_base_rows(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path / "catalog.toml"))
    base = probe_permissions(
        catalog=catalog,
        client=_Client(),
        now=dt.datetime(2026, 8, 14, tzinfo=dt.timezone.utc),
        sleeper=lambda _: None,
    )
    retried = probe_permissions(
        catalog=catalog,
        client=_Client(),
        dataset_names=frozenset({"daily"}),
        base_report=base,
        now=dt.datetime(2026, 8, 14, 1, tzinfo=dt.timezone.utc),
        sleeper=lambda _: None,
    )
    assert retried["query_count"] == 1
    assert retried["results"][1:] == base["results"][1:]


def test_report_is_immutable_and_duplicate_catalog_names_fail(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    path = write_run_document(data_root=data_root, kind="permission", value={"ok": True})
    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True}
    duplicate = _catalog(tmp_path / "duplicate.toml")
    payload = duplicate.read_text(encoding="utf-8")
    duplicate.write_text(payload.replace('name = "empty"', 'name = "daily"'), encoding="utf-8")
    with pytest.raises(ValueError, match="TUSHARE_CATALOG_INVALID"):
        load_catalog(duplicate)


def test_catalog_identity_is_stable_across_lf_and_crlf(tmp_path: Path) -> None:
    lf_path = _catalog(tmp_path / "lf.toml")
    lf_path.write_bytes(lf_path.read_bytes().replace(b"\r\n", b"\n"))
    crlf_path = tmp_path / "crlf.toml"
    crlf_path.write_bytes(lf_path.read_bytes().replace(b"\n", b"\r\n"))
    assert load_catalog(lf_path) == load_catalog(crlf_path)


def test_versioned_catalog_covers_all_supported_market_categories() -> None:
    catalog = load_catalog(Path("configs/data/tushare_bulk_v1.toml"))
    assert len(catalog.datasets) >= 60
    assert {item.category for item in catalog.datasets} == {
        "bond",
        "finance",
        "fund",
        "future",
        "fx",
        "hk",
        "index",
        "macro",
        "option",
        "stock",
    }
    assert {item.priority for item in catalog.datasets} == {"core", "extended", "archive"}


def test_versioned_catalog_keeps_finance_fallback_bounded_and_vip_manual() -> None:
    catalog = load_catalog(Path("configs/data/tushare_bulk_v1.toml"))
    assert catalog.version == "2026-08-15-v2"
    by_name = {item.name: item for item in catalog.datasets}

    for name in ("income", "balancesheet", "cashflow", "fina_indicator"):
        spec = by_name[name]
        assert spec.request_unit == "per_symbol"
        assert spec.inventory == "stock"
        assert spec.history_start == dt.date(1990, 1, 1)
        assert spec.chunk_days == 1825
    assert by_name["fina_indicator"].max_rows == 100

    for name in (
        "income_vip",
        "balancesheet_vip",
        "cashflow_vip",
        "fina_indicator_vip",
    ):
        spec = by_name[name]
        assert spec.probe_mode == "query"
        assert spec.probe_params == {"period": "20231231"}
        assert spec.request_unit == "manual"
        assert spec.inventory == "none"
