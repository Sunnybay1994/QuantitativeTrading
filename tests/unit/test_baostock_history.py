import datetime as dt

from quant.data.baostock_history import pending
from quant.data.market_universe import listing


def test_only_verified_current_checkpoint_is_skipped():
    now = dt.datetime.now(dt.timezone.utc)
    end = dt.date(2026, 9, 22)
    assert not pending({'status': 'captured', 'through': str(end)}, end, now)
    assert pending({'status': 'captured', 'through': '2026-09-21'}, end, now)
    assert pending({'status': 'empty', 'through': str(end)}, end, now)
    assert not pending({'status': 'error', 'retry_after': (now+dt.timedelta(days=1)).isoformat()}, end, now)
    assert pending({'status': 'partial', 'retry_after': (now-dt.timedelta(days=1)).isoformat()}, end, now)


def test_listing_does_not_truncate_history_to_research_start():
    assert listing({'list_date': '19910403'}) == dt.date(1991, 4, 3)
    assert listing({}) == dt.date(1990, 12, 19)


def test_universe_keeps_historical_names_and_ignores_research_pool(tmp_path, monkeypatch):
    import polars as pl
    from quant.data import market_universe, recent_minutes
    monkeypatch.chdir(tmp_path)
    config = tmp_path/'configs/data'
    config.mkdir(parents=True)
    (config/'refresh.toml').write_text('stock_snapshot = "test"')
    folder = tmp_path/'clean/tushare_bulk/snapshots/test/bar_1d/asset=stock/year=2020'
    folder.mkdir(parents=True)
    pl.DataFrame({'symbol': ['600001.SH'], 'trade_date': [dt.date(2020, 1, 2)]}).write_parquet(folder/'data.parquet')
    monkeypatch.setattr(recent_minutes, 'universe', lambda *args: [
        {'symbol': '688999.SH', 'list_date': '20210901', 'asset': 'stock'},
        {'symbol': '920001.BJ', 'list_date': '20210901', 'asset': 'stock'}])
    from quant.data.connectors.public_market import PublicMarket
    monkeypatch.setattr(PublicMarket, 'fetch', lambda *args: [
        {'code': 'sh.600001', 'code_name': 'old', 'ipoDate': '19990101', 'outDate': '2020-01-03'}])
    assert {m['symbol'] for m in market_universe.bao_members(tmp_path)} == {'600001.SH', '688999.SH'}


def test_source_outage_stops_after_five_errors_and_preserves_retry_queue(tmp_path, monkeypatch):
    import polars as pl
    from quant.data import baostock_history as history, refresh, refresh_stocks
    monkeypatch.setattr(history, 'bao_members', lambda root: [
        {'symbol': f'{i:06d}.SZ', 'list_date': '20260101'} for i in range(10)])
    monkeypatch.setattr(refresh, 'latest_session', lambda **kwargs: dt.date(2026, 9, 23))
    monkeypatch.setattr(refresh_stocks, 'read_stock_data', lambda **kwargs: pl.DataFrame(
        schema={'symbol': pl.String, 'trade_date': pl.Date, 'volume': pl.Float64}))
    def unavailable(*args):
        raise ConnectionError('source unavailable')
    monkeypatch.setattr(history, 'capture', unavailable)
    monkeypatch.setattr(history.time, 'sleep', lambda seconds: None)
    result = history.run(root=tmp_path/'data', output=tmp_path/'out')
    assert result['pause_reason'] == 'consecutive_source_errors'
    assert result['requests'] == result['errors'] == 5
    checkpoints = list((tmp_path/'out/checkpoints').glob('*/*.json'))
    assert len(checkpoints) == 5
    import json
    for path in checkpoints:
        saved = json.loads(path.read_text())
        assert saved['status'] == 'error' and saved['retry_after']
