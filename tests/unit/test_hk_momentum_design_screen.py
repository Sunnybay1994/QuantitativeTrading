import datetime as dt
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.data.intraday_bars import TZ
from quant.research.hk_momentum_design_screen import holding_return, screen


def fixture_inputs():
    sessions = tuple(dt.date(2023, 9, 1) + dt.timedelta(days=i) for i in range(50))
    cfg = tomllib.loads(Path('configs/research/b23_hk_momentum_design_20260909.toml').read_text())
    cfg['research'].update(design_start=sessions[25], design_end=sessions[40])
    rows = []
    for symbol in ('A', 'B', 'C', 'D'):
        for i, day in enumerate(sessions):
            for hour in (13, 14):
                price = 10. + i * .1
                rows.append(dict(symbol=symbol, trade_date=day,
                    bar_start=dt.datetime.combine(day, dt.time(hour, 30), TZ),
                    open=price, close=price, volume=100.))
    bars = pl.DataFrame(rows).with_columns(pl.col('bar_start').dt.convert_time_zone('Asia/Shanghai'))
    return bars, sessions, {s: [] for s in ('A', 'B', 'C', 'D')}, cfg


def test_fixed_cycles_past_signal_cost_and_missing_exit():
    bars, sessions, actions, cfg = fixture_inputs()
    trades, summary = screen(bars, sessions, actions, cfg)
    first = trades.row(0, named=True)
    assert first['signal_date'] == sessions[24]
    assert first['reference_date'] == sessions[4]
    assert first['entry_date'] == sessions[25]
    assert first['exit_date'] == sessions[30]
    assert first['gross_return'] == pytest.approx(13. / 12.5 - 1.)
    assert first['estimated_net_2x'] == pytest.approx(.032)
    assert trades['symbol'].to_list() == ['A', 'B', 'C'] * 3
    assert summary['trades'] == 9
    assert summary['conclusion'] == 'REJECTED'  # Fewer than the frozen 20 trades.
    future = bars.with_columns(pl.when(pl.col('trade_date') > sessions[40])
        .then(1000.).otherwise(pl.col('open')).alias('open'))
    assert screen(future, sessions, actions, cfg)[0].equals(trades)
    missing = bars.filter(~((pl.col('symbol') == 'A') & (pl.col('trade_date') == sessions[30])
        & (pl.col('bar_start').dt.hour() == 14)))
    with pytest.raises(ValueError, match='execution quote unavailable'):
        screen(missing, sessions, actions, cfg)
    missing_signal = bars.filter(~((pl.col('symbol') == 'D') & (pl.col('trade_date') == sessions[24])
        & (pl.col('bar_start').dt.hour() == 13)))
    assert screen(missing_signal, sessions, actions, cfg)[1]['missing_signal_cycles'] == 1


def test_cash_dividend_boundary_and_future_event():
    start, end = dt.date(2024, 1, 1), dt.date(2024, 1, 8)
    events = [{'date': start, 'cash': 9., 'split': 1.},
              {'date': end, 'cash': .5, 'split': 1.},
              {'date': dt.date(2024, 2, 1), 'cash': 99., 'split': 1.}]
    assert holding_return(10., 9.5, start, end, events) == pytest.approx(0.)
