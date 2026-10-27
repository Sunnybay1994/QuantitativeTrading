"""Unit tests for post-close Futu K_1M whole-market backfill."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data import post_close_k1m as mod
from quant.data.intraday_bars import TZ


def _bar(time_key: str, code: str = "SH.510300", **overrides):
    row = dict(
        code=code,
        time_key=time_key,
        open=1.0,
        high=1.1,
        low=0.9,
        close=1.05,
        volume=100.0,
        turnover=105.0,
    )
    row.update(overrides)
    return row


def test_normalize_maps_end_labels_and_skips_auction():
    rows = [
        _bar("2026-10-19 09:30:00"),  # auction end label — skip
        _bar("2026-10-19 09:31:00"),
        _bar("2026-10-19 14:59:00"),
        _bar("2026-10-19 15:00:00"),
        _bar("2026-10-20 09:31:00"),  # past end — skip
    ]
    frame, rejected = mod.normalize(rows, "510300.SH", dt.date(2026, 10, 19))
    assert rejected == 0
    assert frame.height == 3
    assert set(frame["source"].to_list()) == {"futu_realtime"}
    assert frame["bar_end"].dt.strftime("%H:%M").to_list() == ["09:31", "14:59", "15:00"]
    assert frame["bar_start"][0] == dt.datetime(2026, 10, 19, 9, 30, tzinfo=TZ)
    assert frame["session_complete"].to_list() == [False, False, False]


def test_coverage_counts_complete_partial_and_missing(tmp_path: Path):
    day = tmp_path / "date=2026-10-27"
    day.mkdir()
    (day / "a.json").write_text(json.dumps({
        "market": "cn", "ok": True, "session_bars": 240, "expected_bars": 240}), encoding="utf-8")
    (day / "b.json").write_text(json.dumps({
        "market": "cn", "ok": True, "session_bars": 10, "expected_bars": 240}), encoding="utf-8")
    (day / "c.json").write_text(json.dumps({
        "market": "hk", "ok": False, "session_bars": 0, "expected_bars": 330}), encoding="utf-8")
    summary = mod.write_coverage(tmp_path)
    text = (tmp_path / "coverage.md").read_text(encoding="utf-8")
    assert "240" in text and "330" in text
    cn = next(row for row in summary["rows"] if row["market"] == "cn")
    assert (cn["expected"], cn["complete"], cn["partial"], cn["missing"]) == (2, 1, 1, 0)
    hk = next(row for row in summary["rows"] if row["market"] == "hk")
    assert hk["missing"] == 1 and hk["complete_rate"] == 0


def test_normalize_rejects_bad_ohlc():
    rows = [_bar("2026-10-19 09:31:00", high=0.5, low=0.9)]
    frame, rejected = mod.normalize(rows, "510300.SH", dt.date(2026, 10, 19))
    assert frame.is_empty()
    assert rejected == 1


def test_normalize_hk_session_minutes():
    rows = [
        _bar("2026-10-16 09:30:00", code="HK.00700"),
        _bar("2026-10-16 09:31:00", code="HK.00700"),
        _bar("2026-10-16 12:00:00", code="HK.00700"),
        _bar("2026-10-16 13:01:00", code="HK.00700"),
        _bar("2026-10-16 16:00:00", code="HK.00700"),
        _bar("2026-10-16 15:00:00", code="HK.00700"),  # valid HK afternoon
    ]
    frame, rejected = mod.normalize(rows, "00700.HK", dt.date(2026, 10, 16))
    assert rejected == 0
    assert frame.height == 5
    assert frame["bar_end"].dt.strftime("%H:%M").to_list() == [
        "09:31",
        "12:00",
        "13:01",
        "15:00",
        "16:00",
    ]


def test_normalize_us_session_minutes_et_wall_clock():
    rows = [
        _bar("2026-10-16 09:30:00", code="US.AAPL"),
        _bar("2026-10-16 09:31:00", code="US.AAPL"),
        _bar("2026-10-16 16:00:00", code="US.AAPL"),
    ]
    frame, rejected = mod.normalize(rows, "AAPL.US", dt.date(2026, 10, 16))
    assert rejected == 0
    assert frame.height == 2


def test_load_universe_filters_bj(tmp_path: Path):
    path = tmp_path / "universe.json"
    path.write_text(
        json.dumps(
            {
                "captured_at": dt.datetime.now(TZ).isoformat(),
                "members": [
                    {"symbol": "510300.SH", "name": "ETF"},
                    {"symbol": "000001.SZ", "name": "PA"},
                    {"symbol": "920001.BJ", "name": "BJ"},
                ],
            }
        ),
        encoding="utf-8",
    )
    symbols = mod.load_universe(
        {"universe_path": str(path), "data_root": str(tmp_path), "markets": ["cn"]}
    )
    assert symbols == ["000001.SZ", "510300.SH"]


def test_load_universe_hk_ah_priority(tmp_path: Path):
    snap = tmp_path / "clean/connect_snapshot/route=SH_CONNECT/date=2026-09-09"
    snap.mkdir(parents=True)
    pl.DataFrame(
        {
            "route": ["SH_CONNECT"] * 3,
            "snapshot_date": [dt.date(2026, 9, 9)] * 3,
            "symbol": ["00001.HK", "00700.HK", "02318.HK"],
            "name_cn": ["a", "b", "c"],
            "name_en": ["a", "b", "c"],
            "security_type": ["STOCK"] * 3,
            "buy_eligible": [True, True, True],
            "source": ["sse"] * 3,
        }
    ).write_parquet(snap / "data.parquet")
    ah = tmp_path / "ah.toml"
    ah.write_text(
        '''
[[pairs]]
a_symbol = "601318.SH"
h_symbol = "02318.HK"
name = "平安"
''',
        encoding="utf-8",
    )
    symbols = mod.load_universe(
        {
            "data_root": str(tmp_path),
            "markets": ["hk"],
            "ah_dual_list": str(ah),
            "include_hsi": False,
        }
    )
    assert symbols[0] == "02318.HK"
    assert set(symbols) == {"00001.HK", "00700.HK", "02318.HK"}


def test_load_universe_us_from_config(tmp_path: Path):
    us = tmp_path / "us.toml"
    us.write_text(
        '''
[[members]]
symbol = "AAPL.US"
name = "Apple"
[[members]]
symbol = "SPY.US"
name = "SPY"
''',
        encoding="utf-8",
    )
    symbols = mod.load_universe(
        {"data_root": str(tmp_path), "markets": ["us"], "us_universe_path": str(us)}
    )
    assert symbols == ["AAPL.US", "SPY.US"]


def test_parse_markets_and_ready():
    assert mod.parse_markets("hk,us") == ["hk", "us"]
    noon = dt.datetime(2026, 10, 19, 12, 0, tzinfo=TZ)
    ok, detail = mod.market_ready("cn", noon, force=False)
    assert ok is False
    ok, _ = mod.market_ready("us", noon, force=False)
    assert ok is True
    late = dt.datetime(2026, 10, 19, 16, 10, tzinfo=TZ)
    assert mod.market_ready("hk", late, force=False)[0] is True


def test_run_idle_before_close(tmp_path: Path, monkeypatch):
    config = tmp_path / "cfg.toml"
    config.write_text(
        f'''
auto_trade = false
data_root = "{tmp_path.as_posix()}"
output = "{(tmp_path / "out").as_posix()}"
universe_path = "{(tmp_path / "missing.json").as_posix()}"
markets = ["cn"]
host = "127.0.0.1"
port = 11111
quota_reserve = 5
k1m_rotate_seconds = 65
''',
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "phase", lambda now: "trading")
    result = mod.run(config, force=False, markets=["cn"])
    assert result["status"] == "idle"
    assert "post-close" in result["reason"]


def test_run_one_batch_with_fake_client(tmp_path: Path, monkeypatch):
    root = tmp_path / "data"
    out = tmp_path / "out"
    uni = tmp_path / "universe.json"
    uni.write_text(
        json.dumps(
            {
                "captured_at": dt.datetime.now(TZ).isoformat(),
                "members": [
                    {"symbol": "510300.SH", "name": "ETF"},
                    {"symbol": "000001.SZ", "name": "PA"},
                ],
            }
        ),
        encoding="utf-8",
    )
    config = tmp_path / "cfg.toml"
    config.write_text(
        f'''
auto_trade = false
data_root = "{root.as_posix()}"
output = "{out.as_posix()}"
universe_path = "{uni.as_posix()}"
markets = ["cn"]
host = "127.0.0.1"
port = 11111
quota_reserve = 0
k1m_rotate_seconds = 60
request_spacing_seconds = 0
''',
        encoding="utf-8",
    )

    class FakeClient:
        def __init__(self, *a, **k):
            self.subscribed = []

        def state(self):
            return {"qot_logined": "true", "timestamp": str(dt.datetime.now(TZ).timestamp())}

        def quota(self):
            return {"total_used": 0, "remain": 2, "own_used": 0}

        def subscribe_k1m(self, symbols, reserve=None):
            self.subscribed = list(symbols)
            return {"remain": 0, "own_used": len(symbols)}

        def unsubscribe_k1m(self, symbols):
            self.subscribed = []
            return {"remain": 2, "own_used": 0}

        def bars(self, symbol):
            market = symbol.split(".")[1]
            code = symbol.split(".")[0]
            return [
                dict(
                    code=f"{market}.{code}",
                    time_key="2026-10-19 09:31:00",
                    open=1.0,
                    high=1.1,
                    low=0.9,
                    close=1.0,
                    volume=10.0,
                    turnover=10.0,
                ),
                dict(
                    code=f"{market}.{code}",
                    time_key="2026-10-19 15:00:00",
                    open=1.0,
                    high=1.2,
                    low=0.95,
                    close=1.1,
                    volume=20.0,
                    turnover=22.0,
                ),
            ]

        def close(self):
            pass

    monkeypatch.setattr(mod, "FutuRealtime", FakeClient)
    monkeypatch.setattr(mod, "phase", lambda now: "closed")
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    import quant.data.refresh as refresh_mod
    monkeypatch.setattr(refresh_mod, "latest_session", lambda **k: dt.date(2026, 10, 19))

    result = mod.run(config, force=True, max_batches=1, skip_complete=False, markets=["cn"])
    assert result["status"] in ("complete", "partial", "batch_budget_reached")
    assert result["ok"] == 2
    assert result["failed"] == 0
    assert result["batches"] == 1
    clean = root / "clean/bar_intraday/freq=1m/source=futu_realtime/symbol=510300.SH/data.parquet"
    assert clean.exists()
    frame = pl.read_parquet(clean)
    assert frame.height == 2
    assert (out / "status.json").exists()


def test_unknown_stock_error_parse():
    exc = RuntimeError("未知股票 158036")
    assert mod.is_unknown_stock_error(exc)
    assert mod.unknown_codes_from_error(exc) == {"158036"}
    assert mod.match_symbols_by_codes(["158036.SZ", "000001.SZ"], {"158036"}) == ["158036.SZ"]
    us = RuntimeError("未知股票 AAPL")
    assert mod.unknown_codes_from_error(us) == {"AAPL"}


def test_subscribe_k1m_resilient_filters_named_unknown():
    class Fake:
        def __init__(self):
            self.calls = []

        def subscribe_k1m(self, symbols, reserve=None):
            self.calls.append(list(symbols))
            if any(s.startswith("158036") for s in symbols):
                raise RuntimeError("未知股票 158036")
            return {"remain": 10}

    client = Fake()
    accepted, rejected = mod.subscribe_k1m_resilient(
        client, ["000001.SZ", "158036.SZ", "000002.SZ"], reserve=5
    )
    assert accepted == ["000001.SZ", "000002.SZ"]
    assert [r["symbol"] for r in rejected] == ["158036.SZ"]
    assert rejected[0]["unsupported"] is True
    assert client.calls[0] == ["000001.SZ", "158036.SZ", "000002.SZ"]
    assert client.calls[1] == ["000001.SZ", "000002.SZ"]


def test_subscribe_k1m_resilient_bisects_when_code_missing():
    class Fake:
        def __init__(self):
            self.calls = []

        def subscribe_k1m(self, symbols, reserve=None):
            self.calls.append(list(symbols))
            if "BAD.SZ" in symbols:
                raise RuntimeError("未知股票")
            return {"remain": 10}

    client = Fake()
    accepted, rejected = mod.subscribe_k1m_resilient(
        client, ["000001.SZ", "BAD.SZ", "000002.SZ"], reserve=5
    )
    assert set(accepted) == {"000001.SZ", "000002.SZ"}
    assert [r["symbol"] for r in rejected] == ["BAD.SZ"]
