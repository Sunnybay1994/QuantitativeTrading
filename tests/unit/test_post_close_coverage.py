import datetime as dt
import json

import pytest

from quant.data.post_close_coverage import save_universe, write_coverage

DAY = dt.date(2026, 10, 28)


def receipt(root, symbol, *, bars=240, ok=True, **extra):
    folder = root / f"date={DAY}"
    folder.mkdir(exist_ok=True)
    (folder / f"{symbol}.json").write_text(json.dumps({
        "symbol": symbol, "market": "cn", "as_of": str(DAY), "ok": ok,
        "session_bars": bars, "expected_bars": 240, **extra,
    }), encoding="utf-8")


def test_unattempted_symbols_stay_in_denominator_and_rerun_cannot_shrink(tmp_path):
    symbols = ["000001.SZ", "000002.SZ", "600000.SH"]
    save_universe(tmp_path, {"cn": DAY}, symbols, dict.fromkeys(symbols, 240))
    receipt(tmp_path, symbols[0])
    row = write_coverage(tmp_path)["rows"][0]
    assert (row["expected"], row["complete"], row["missing"]) == (3, 1, 2)
    assert row["complete_rate"] == pytest.approx(1 / 3)
    assert row["denominator_verified"]
    save_universe(tmp_path, {"cn": DAY}, symbols[:1], {symbols[0]: 240})
    assert write_coverage(tmp_path)["rows"][0] == row


def test_legacy_success_cannot_verify_full_universe(tmp_path):
    receipt(tmp_path, "000001.SZ")
    row = write_coverage(tmp_path)["rows"][0]
    assert row["complete_rate"] == 1
    assert not row["denominator_verified"]
    assert row["denominator_basis"] == "receipts_only"


def test_snapshot_without_any_receipts_is_zero_coverage(tmp_path):
    save_universe(tmp_path, {"cn": DAY}, ["000001.SZ"], {"000001.SZ": 240})
    row = write_coverage(tmp_path)["rows"][0]
    assert row["expected"] == row["missing"] == 1
    assert row["complete"] == row["partial"] == row["complete_rate"] == 0


def test_cache_skip_counts_but_stale_date_and_failed_bars_do_not(tmp_path):
    symbols = ["000001.SZ", "000002.SZ", "600000.SH"]
    save_universe(tmp_path, {"cn": DAY}, symbols, dict.fromkeys(symbols, 240))
    receipt(tmp_path, symbols[0], ok=None, market=None, skipped=True)
    receipt(tmp_path, symbols[1], as_of="2026-10-27")
    receipt(tmp_path, symbols[2], ok=False)
    row = write_coverage(tmp_path)["rows"][0]
    assert (row["complete"], row["partial"], row["missing"]) == (1, 1, 1)


def test_probe_limit_freezes_full_pool_before_provider_connection(tmp_path, monkeypatch):
    from quant.data import post_close_k1m as mod

    symbols = ["000001.SZ", "600000.SH"]
    config = tmp_path / "config.toml"
    out = tmp_path / "out"
    config.write_text(f'auto_trade=false\ndata_root="{tmp_path.as_posix()}"\n'
                      f'output="{out.as_posix()}"\nk1m_rotate_seconds=65\n', encoding="utf-8")
    monkeypatch.setattr(mod, "load_universe", lambda *a, **kw: symbols)
    monkeypatch.setattr(mod, "latest_market_session", lambda *a, **kw: DAY)
    monkeypatch.setattr(mod, "expected_bars_for", lambda *a, **kw: 240)
    def no_provider(*a, **kw):
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr(mod, "FutuRealtime", no_provider)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        mod.run(config, force=True, markets=["cn"], limit=1)
    row = json.loads((out / "coverage.json").read_text())["rows"][0]
    assert row["expected"] == row["missing"] == 2


def test_doctor_does_not_accept_legacy_hundred_percent(tmp_path):
    from zoneinfo import ZoneInfo

    from quant.reporting.doctor import collect, render_markdown

    output = tmp_path / "artifacts/post_close_k1m"
    output.mkdir(parents=True)
    receipt(output, "000001.SZ")
    write_coverage(output)
    report = collect(root=tmp_path, tasks=[], now=dt.datetime(2026, 10, 29, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert "coverage: cn 2026-10-28 full universe unverified" in report["red"]
    assert "receipts_only" in render_markdown(report)
