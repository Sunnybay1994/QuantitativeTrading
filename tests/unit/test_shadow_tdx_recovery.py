import datetime as dt
import struct

import polars as pl
import pytest

from quant.data.shadow_tdx_recovery import recover, validate_day
from quant.data.tdx_intraday import decode_minute_payload
from quant.data.intraday_bars import SCHEMA

DAY = dt.date(2026, 9, 10)


def fixture(tmp_path):
    encoded = (DAY.year-2004)*2048+DAY.month*100+DAY.day
    payload = b''.join(struct.pack('<Hhfffffii', encoded, m, 10., 10., 10., 10., 1000., 100, 0)
                       for m in [*range(571, 691), *range(781, 901)])
    p = tmp_path/'tdx/sh/minline/sh510300.lc1'
    p.parent.mkdir(parents=True)
    p.write_bytes(payload)
    _, bars, _ = decode_minute_payload(payload, symbol='510300.SH', frequency='1m')
    bars = bars.select(list(SCHEMA))
    reference = bars.with_columns(pl.lit(None, dtype=pl.Float64).alias('amount'), pl.lit('yahoo').alias('source'))
    orders = pl.DataFrame({'symbol': ['510300.SH'], 'asset_type': ['etf'], 'execution_date': [DAY]})
    return orders, bars, reference


def test_recovery_snapshot_and_future_boundary(tmp_path):
    orders, bars, reference = fixture(tmp_path)
    result, audit = recover(orders=orders, minutes=reference, known_through=DAY,
                           tdx_root=tmp_path/'tdx', output=tmp_path/'out')
    assert result.equals(bars.head(30)) and audit[0]['status'] == 'recovered'
    assert len(list((tmp_path/'out/raw_tdx').glob('*.lc1'))) == 1
    again, _ = recover(orders=orders, minutes=reference, known_through=DAY,
                       tdx_root=tmp_path/'tdx', output=tmp_path/'out')
    assert again.equals(result)
    future, audit = recover(orders=orders, minutes=reference, known_through=DAY-dt.timedelta(days=1),
                           tdx_root=tmp_path/'tdx', output=tmp_path/'future')
    assert future.equals(reference) and not audit and not (tmp_path/'future').exists()


def test_reject_incorrect_units_price_and_coverage(tmp_path):
    _, bars, reference = fixture(tmp_path)
    for invalid in (bars.head(239), bars.with_columns(pl.col('volume')*100)):
        with pytest.raises(ValueError):
            validate_day(invalid, reference)
    for invalid in (reference.head(191), reference.with_columns(pl.col('close')+.01),
                    reference.with_columns(pl.lit(float('nan')).alias('close'))):
        with pytest.raises(ValueError):
            validate_day(bars, invalid)


def test_missing_file_preserves_missing_amount(tmp_path):
    orders, _, reference = fixture(tmp_path)
    result, audit = recover(orders=orders, minutes=reference, known_through=DAY,
                           tdx_root=tmp_path/'missing', output=tmp_path/'out')
    assert result.equals(reference) and audit[0]['status'] == 'unavailable'


def test_late_bad_turnover_does_not_certify_whole_day(tmp_path):
    orders, _, reference = fixture(tmp_path)
    path = tmp_path/'tdx/sh/minline/sh510300.lc1'
    payload = bytearray(path.read_bytes())
    struct.pack_into('<f', payload, 90*32+20, 2000.)
    path.write_bytes(payload)
    result, audit = recover(orders=orders, minutes=reference, known_through=DAY,
                           tdx_root=tmp_path/'tdx', output=tmp_path/'out')
    assert result.height == 30
    assert audit[0]['whole_day_validation']['status'] == 'failed'
    assert all(row['status'] == 'passed' for row in audit[0]['windows'])


def test_bad_turnover_inside_window_keeps_larger_horizons_missing(tmp_path):
    orders, _, reference = fixture(tmp_path)
    path = tmp_path/'tdx/sh/minline/sh510300.lc1'
    payload = bytearray(path.read_bytes())
    struct.pack_into('<f', payload, 10*32+20, 2000.)
    path.write_bytes(payload)
    result, audit = recover(orders=orders, minutes=reference, known_through=DAY,
                           tdx_root=tmp_path/'tdx', output=tmp_path/'out')
    assert result.height == 5
    assert [r['status'] for r in audit[0]['windows']] == ['passed', 'failed', 'failed']
    from quant.execution.shadow_slippage import _vwap
    assert _vwap(result, DAY, 5)[0] == 10.
    assert _vwap(result, DAY, 15)[0] is None
