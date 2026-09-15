import datetime as dt
from pathlib import Path


from quant.data import shadow_slippage_inputs as reader
from tests.unit.test_shadow_slippage import DAY, inputs


def test_local_minute_partition_and_daily_reader_only(tmp_path, monkeypatch):
    args = inputs()
    folder = tmp_path/'clean/bar_intraday/freq=5m/source=baostock/symbol=000001.SZ'
    folder.mkdir(parents=True)
    args['minutes'].write_parquet(folder/'data.parquet')
    calls = []
    def daily(**kwargs):
        calls.append(kwargs)
        return args['daily']
    monkeypatch.setattr(reader, 'read_stock_data', daily)
    daily_frame, minute, errors = reader.read_inputs(orders=args['orders'], known_through=DAY,
        data_root=tmp_path, refresh_config=Path('fixture'))
    assert not errors and minute.height == 6 and daily_frame.height == 1
    assert calls[0]['end'] == DAY


def test_future_orders_do_not_read_any_market_inputs(tmp_path, monkeypatch):
    args = inputs()
    monkeypatch.setattr(reader, 'read_stock_data', lambda **kw: (_ for _ in ()).throw(AssertionError('future read')))
    daily, minute, errors = reader.read_inputs(orders=args['orders'], known_through=dt.date(2026, 9, 11),
        data_root=tmp_path, refresh_config=Path('fixture'))
    assert daily.is_empty() and minute.is_empty() and not errors


def test_etf_snapshot_is_explicit_and_missing_minutes_are_reported(tmp_path, monkeypatch):
    import polars as pl
    args = inputs()
    args['orders'] = args['orders'].with_columns(pl.lit('etf').alias('asset_type'))
    calls = []
    def read(data_root, snapshot):
        calls.append(snapshot)
        return {'bars': args['daily']}
    monkeypatch.setattr(reader, 'read_cross_asset_etfs', read)
    daily, minute, errors = reader.read_inputs(orders=args['orders'], known_through=DAY,
        data_root=tmp_path, refresh_config=Path('fixture'), etf_snapshot='frozen_b20')
    assert calls == ['frozen_b20'] and daily.height == 1 and minute.is_empty()
    assert errors[0]['input'] == 'minute'
