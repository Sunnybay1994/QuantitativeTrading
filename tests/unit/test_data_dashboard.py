import datetime as dt
import json

import polars as pl
import pytest

from quant.reporting.data_inventory import DataInventory, files, profile, summarize
from quant.reporting.data_sync import sync


def write(path, symbol="000001.SZ", dates=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        dict(
            symbol=[symbol] * 2,
            trade_date=dates or [dt.date(2018, 9, 17), dt.date(2018, 12, 28)],
            source=["futu"] * 2,
        )
    ).write_parquet(path)


def test_profile_uses_actual_dates_and_symbol_counts(tmp_path):
    path = tmp_path / "data/clean/futu_minute/plan/symbol=000001.SZ/year=2018/data.parquet"
    write(path)
    row = profile(path, tmp_path)
    assert (row["first"], row["last"], row["frequency"]) == ("2018-09-17", "2018-12-28", "1m")
    assert row["symbols"] == ["000001.SZ"] and row["year"] == 2018


def test_year_presence_is_not_inferred_from_min_max_and_duplicate_sources(tmp_path):
    cfg = tmp_path / "configs/data/minute_history.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('end="2020-12-31"')
    bounds = tmp_path / "artifacts/minute_history/earliest_bounds.json"
    bounds.parent.mkdir(parents=True)
    bounds.write_text(json.dumps({"000001.SZ": {"first_date": "2018-09-17"}}))
    rows = []
    for year in (2018, 2020):
        path = tmp_path / f"data/clean/futu_minute/plan/symbol=000001.SZ/year={year}/data.parquet"
        write(path, dates=[dt.date(year, 1, 2), dt.date(year, 12, 28)])
        rows.append(profile(path, tmp_path))
    value = summarize(rows + rows, tmp_path)
    assert value["overview"][0]["symbols"] == 1
    stock = value["minute_symbols"][0]
    assert stock["missing_years"] == [2019] and not stock["plan_years_complete"]
    rows.append({**rows[0], "year": 2019})
    assert summarize(rows, tmp_path)["minute_symbols"][0]["plan_years_complete"]


def test_inventory_detects_file_revisions_and_reports_corrupt_files(tmp_path):
    path = tmp_path / "data/clean/futu_minute/plan/symbol=000001.SZ/year=2018/data.parquet"
    write(path)
    inv = DataInventory(tmp_path)
    inv._build()
    assert inv.payload["overview"][0]["first"] == "2018-09-17"
    write(path, dates=[dt.date(2018, 1, 2), dt.date(2018, 12, 28)])
    bad = path.with_name("bad.parquet")
    bad.write_bytes(b"not parquet")
    inv._build()
    assert inv.payload["overview"][0]["first"] == "2018-01-02"
    assert len(inv.payload["errors"]) == 1
    assert len(files(tmp_path)) == 2


def test_sync_allowlist_and_existing_task_routes(monkeypatch):
    from quant.reporting import data_sync

    calls = []
    monkeypatch.setattr(data_sync, "powershell", lambda script: calls.append(script) or [])
    with pytest.raises(ValueError):
        sync("recent'; Remove-Item")
    assert not calls
    sync("recent")
    assert "QuantitativeTrading-MinutesRecent" in calls[0]
    assert "IgnoreNew" in calls[0] and "-eq 'Running'" in calls[0]
    assert "ContinuousMining" not in calls[0]


def test_data_sync_reuses_local_origin_token_protection():
    from quant.reporting.mining_control import authorized

    headers = {
        "Host": "127.0.0.1:8768",
        "Origin": "http://127.0.0.1:8768",
        "X-Mining-Token": "token",
    }
    assert authorized(headers, "token", 8768)
    assert not authorized({**headers, "Origin": "https://attacker.example"}, "token", 8768)
    assert not authorized({**headers, "Content-Length": "100"}, "token", 8768)


def test_progress_snapshot_retries_transient_windows_reader_lock(tmp_path, monkeypatch):
    from pathlib import Path
    from quant.data import realtime_store

    original = Path.replace
    calls = []

    def locked_once(path, target):
        calls.append(target)
        if len(calls) == 1:
            raise PermissionError('reader briefly holds the snapshot')
        return original(path, target)

    monkeypatch.setattr(Path, 'replace', locked_once)
    monkeypatch.setattr(realtime_store.time, 'sleep', lambda seconds: None)
    target = tmp_path / 'status.json'
    target.write_text('{"status":"old"}')
    realtime_store.atomic_json(target, {'status': 'completed'})
    assert len(calls) == 2
    assert json.loads(target.read_text()) == {'status': 'completed'}
    assert not list(tmp_path.glob('*.tmp'))
