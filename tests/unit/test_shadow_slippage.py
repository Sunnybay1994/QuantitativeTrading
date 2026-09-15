import datetime as dt
import json

import polars as pl
import pytest

from quant.data.intraday_bars import SCHEMA
from quant.data.shadow_slippage_inputs import DAILY_SCHEMA
from quant.execution import shadow_slippage as shadow

DAY = dt.date(2026, 9, 14)


def inputs(side='BUY'):
    orders = pl.from_dicts([{'account': 'q10', 'asset_type': 'stock', 'as_of': dt.date(2026, 9, 11),
        'execution_date': DAY, 'symbol': '000001.SZ', 'side': side, 'quantity': 100, 'signal_price': 10.}], schema=shadow.ORDER_SCHEMA)
    daily = pl.DataFrame({'symbol': ['000001.SZ'], 'trade_date': [DAY], 'open': [10.1]}, schema=DAILY_SCHEMA)
    start = dt.datetime.combine(DAY, dt.time(9, 30), shadow.ZONE)
    minutes = pl.from_dicts([{'symbol': '000001.SZ', 'trade_date': DAY,
        'bar_start': start+dt.timedelta(minutes=5*i), 'bar_end': start+dt.timedelta(minutes=5*(i+1)),
        'open': 10., 'high': 11., 'low': 10., 'close': 10.2, 'volume': 100.,
        'amount': 1020., 'source': 'fixture'} for i in range(6)], schema=SCHEMA)
    return dict(orders=orders, daily=daily, minutes=minutes, known_through=DAY)


@pytest.mark.parametrize('side, sign', [('BUY', 1), ('SELL', -1)])
def test_price_only_directional_bps_and_complete_windows(side, sign):
    detail, monthly = shadow.calculate(**inputs(side))
    assert detail['status'].to_list() == ['observed']*4
    assert detail['slippage_bps'].to_list() == pytest.approx([100*sign, 200*sign, 200*sign, 200*sign])
    assert monthly['valid_samples'].sum() == 4
    assert detail['vs_open_bps'][1] == pytest.approx(sign*(10.2/10.1-1)*10000)


@pytest.mark.parametrize('damage', ['gap', 'duplicate', 'missing_amount'])
def test_incomplete_window_never_fills_zero(damage):
    args = inputs()
    if damage == 'gap':
        args['minutes'] = args['minutes'].filter(pl.col('bar_start').dt.minute() != 35)
    elif damage == 'duplicate':
        args['minutes'] = pl.concat([args['minutes'], args['minutes'].head(1)])
    else:
        args['minutes'] = args['minutes'].with_columns(pl.lit(None).cast(pl.Float64).alias('amount'))
    detail, monthly = shadow.calculate(**args)
    row = detail.filter(pl.col('horizon') == 'vwap_15m').row(0, named=True)
    assert row['status'] == 'missing' and row['slippage_bps'] is None and row['shadow_price'] is None
    assert monthly['missing_samples'].sum() > 0


def test_future_quotes_are_pending_even_if_supplied():
    args = inputs()
    args['known_through'] = dt.date(2026, 9, 11)
    detail, monthly = shadow.calculate(**args)
    assert detail['status'].to_list() == ['pending']*4
    assert detail['shadow_price'].null_count() == 4 and detail['open_price'].null_count() == 4
    assert monthly['pending_samples'].sum() == 4


def test_empty_existing_orders_write_headers_and_no_calibration(tmp_path):
    account = tmp_path/'account'
    account.mkdir()
    (account/'orders.csv').write_text('as_of,execution_date,symbol,side,quantity,reference_price\n')
    result = shadow.run(accounts=[{'account': 'b20', 'root': str(account), 'asset_type': 'etf'}],
        known_through=DAY, output=tmp_path/'out')
    assert result['status'] == 'no_samples' and not result['calibration_complete']
    assert pl.read_csv(tmp_path/'out/shadow_execution.csv').height == 0
    assert pl.read_csv(tmp_path/'out/slippage_monthly.csv').height == 0
    assert json.loads((tmp_path/'out/summary.json').read_text())['orders'] == 0


def test_b20_b32_q10_orders_ignore_fee_and_estimated_fill(tmp_path):
    accounts = []
    for name, asset in [('b20', 'etf'), ('b32', 'stock'), ('q10', 'stock')]:
        folder = tmp_path/name/'2026-09-11'
        folder.mkdir(parents=True)
        (folder/'orders.csv').write_text('as_of,execution_date,symbol,side,quantity,reference_price,estimated_fill_price,estimated_fee\n2026-09-11,2026-09-14,000001.SZ,BUY,100,10,999,10000\n')
        accounts.append({'account': name, 'root': str(folder.parent), 'asset_type': asset})
    orders, errors = shadow.read_orders(accounts, DAY)
    assert not errors and orders['signal_price'].to_list() == [10., 10., 10.]


def test_monthly_p90_and_missing_counts_are_per_account(tmp_path):
    args = inputs()
    second = args['orders'].with_columns(pl.lit('SELL').alias('side'))
    args['orders'] = pl.concat([args['orders'], second])
    detail, monthly = shadow.calculate(**args)
    row = monthly.filter(pl.col('horizon') == 'open').row(0, named=True)
    assert row['samples'] == 2 and row['median_bps'] == pytest.approx(0.)
    assert row['p90_bps'] == pytest.approx(80.)
