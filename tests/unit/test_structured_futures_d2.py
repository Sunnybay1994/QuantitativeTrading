import datetime as dt

import polars as pl
import pytest

from quant.data.structured_futures import capture
from quant.reporting.structured_futures import market_facts
from tests.unit.test_structured_incremental import setup, Client


def quotes():
    return pl.DataFrame({'ts_code': ['IF2611.CFX', 'IC2611.CFX', 'IM2611.CFX', 'T2611.CFX'],
        'trade_date': ['20261106']*4, 'close': [4000., 5000., 6000., 100.],
        'settle': [4000., 5000., 6000., 100.], 'vol': [1.]*4, 'oi': [1.]*4})


def test_futures_are_monthly_quotes_not_fabricated_basis(tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.setattr('quant.data.structured_incremental._yield_check', lambda *a: None)
    record = capture(data_root=tmp_path, as_of=dt.date(2026, 11, 6), output=tmp_path/'probe',
                     connector=Client(lambda *a: quotes()))
    assert record['rows'] == 3 and record['consumer'] == 'monthly_market_panel_only'
    # This fixture uses root/data convention expected by the reporting module.
    market = tmp_path/'market'
    market.mkdir()
    import shutil
    shutil.copytree(tmp_path/'clean/fut_daily', market/'data/clean/fut_daily')
    report = market_facts('2026-11', root=market,
        known_at=dt.datetime(2026, 11, 10, tzinfo=dt.timezone.utc))
    assert report['status'] == 'observed_quotes'
    assert report['basis_status'].startswith('unknown')
    assert len(report['rows']) == 3
    assert market_facts('2026-11',root=market,known_at=dt.datetime(2026,11,10,
        tzinfo=dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=8))))==report
    early = market_facts('2026-11', root=market,
        known_at=dt.datetime(2026, 11, 8, tzinfo=dt.timezone.utc))
    assert early['status'] == 'no_observed_rows_in_month'


def test_futures_scope_and_duplicates_fail_closed(tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.setattr('quant.data.structured_incremental._yield_check', lambda *a: None)
    with pytest.raises(ValueError, match='unique daily contracts'):
        capture(data_root=tmp_path, as_of=dt.date(2026, 11, 6), output=tmp_path/'bad',
                connector=Client(lambda *a: quotes().head(1)))
