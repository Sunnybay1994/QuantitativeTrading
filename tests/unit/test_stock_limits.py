import datetime as dt
import json

import polars as pl
import pytest

from quant.data import stock_limits
from quant.data.storage import RawStore

DAY = dt.date(2026, 9, 24)
LATE = dt.datetime(2026, 9, 28, 7, tzinfo=dt.timezone.utc)


def keys():
    return pl.DataFrame({'symbol': ['600001.SH', '000001.SZ'], 'trade_date': [DAY, DAY]})


def raw():
    return keys().rename({'symbol': 'ts_code'}).with_columns(
        pl.col('trade_date').dt.strftime('%Y%m%d'), pl.lit(11.0).alias('up_limit'),
        pl.lit(9.0).alias('down_limit'))


def save(root, frame=None, day=DAY):
    return RawStore(root/'raw').write(source='tushare', table='stk_limit',
        frame=raw() if frame is None else frame, parameters={'trade_date': day.strftime('%Y%m%d')},
        fetched_at=LATE)


def test_late_receipt_reused_without_backdating_or_network(tmp_path, monkeypatch):
    snapshot = save(tmp_path)
    before = snapshot.metadata_path.read_bytes(), snapshot.data_path.read_bytes()
    monkeypatch.setattr(stock_limits, 'read_stock_data', lambda **kw: keys())
    monkeypatch.setattr(stock_limits, 'TushareConnector', lambda **kw: pytest.fail('Do not refetch complete data'))
    result = stock_limits.refresh_stock_limits(data_root=tmp_path, config=tmp_path/'unused', end=DAY)
    assert result['new_rows'] == 0 and result['required_keys'] == 2
    assert result['fetched_at'] == LATE.isoformat()
    assert 'date=2026-09-28' in result['source'] and result['as_of'] == str(DAY)
    assert before == (snapshot.metadata_path.read_bytes(), snapshot.data_path.read_bytes())
    assert stock_limits.read_saved_limits(tmp_path, LATE.date(), keys().with_columns(
        pl.lit(LATE.date()).alias('trade_date'))) is None


@pytest.mark.parametrize('problem', ['date', 'duplicate', 'null', 'nan', 'reversed', 'hash', 'time'])
def test_invalid_saved_input_fails_closed(tmp_path, problem):
    frame = raw()
    if problem == 'date':
        frame = frame.with_columns(pl.lit('20260925').alias('trade_date'))
    elif problem == 'duplicate':
        frame = pl.concat([frame, frame.head(1)])
    elif problem in ('null', 'nan'):
        frame = frame.with_columns(pl.lit(None if problem == 'null' else float('nan'),
            dtype=pl.Float64).alias('up_limit'))
    elif problem == 'reversed':
        frame = frame.with_columns(pl.lit(8.0).alias('up_limit'))
    snapshot = save(tmp_path, frame)
    if problem in ('hash', 'time'):
        receipt = json.loads(snapshot.metadata_path.read_text())
        receipt['checksum_sha256' if problem == 'hash' else 'fetched_at'] = (
            '0' * 64 if problem == 'hash' else '2026-09-28T07:00:00')
        snapshot.metadata_path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        stock_limits.read_saved_limits(tmp_path, DAY, keys())


def test_partial_raw_is_not_complete_and_producer_fetches_once(tmp_path, monkeypatch):
    old = save(tmp_path, raw().head(1))
    calls = []

    class Connector:
        def query_raw(self, api, **params):
            calls.append((api, params))
            return raw()

    monkeypatch.setattr(stock_limits, 'TushareConnector', lambda **kw: Connector())
    monkeypatch.setattr(stock_limits, 'read_stock_data', lambda **kw: keys())
    result = stock_limits.refresh_stock_limits(data_root=tmp_path, config=tmp_path/'unused', end=DAY)
    assert result['new_rows'] == 2 and old.data_path.is_file()
    assert calls == [('stk_limit', {'trade_date': '20260924'})]
    again = stock_limits.refresh_stock_limits(data_root=tmp_path, config=tmp_path/'unused', end=DAY)
    assert again['new_rows'] == 0 and len(calls) == 1
