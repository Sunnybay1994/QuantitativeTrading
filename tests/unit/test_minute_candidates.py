import datetime as dt
from pathlib import Path
import tomllib

from quant.research.minute_candidates import generate
from quant.research.intraday_afternoon import signal


def test_battery_is_bounded_frozen_and_keeps_three_costs(tmp_path):
    spec = Path('configs/research/minute_search_v1.toml')
    paths = generate(spec, tmp_path)
    assert len(paths) == 4
    before = [p.read_bytes() for p in paths]
    assert generate(spec, tmp_path) == paths
    assert [p.read_bytes() for p in paths] == before
    for path in paths:
        cfg = tomllib.loads(path.read_text(encoding='utf-8'))
        assert cfg['cost_multipliers'] == [.5, 1., 2.]
        assert cfg['execution_model'] == 'next_5m_worst'
        assert cfg['auto_trade'] is False


def test_breakout_uses_completed_opening_range_only():
    start = dt.datetime(2026, 9, 22, 9, 30)
    rows = [dict(bar_end=start+dt.timedelta(minutes=5*(i+1)),
                 high=11, close=10, amount=1000, volume=100) for i in range(12)]
    rows[-1]['close'] = 12
    at = start+dt.timedelta(hours=1)
    assert signal(rows, at, 'opening_range_breakout')
    assert signal(rows+[dict(bar_end=at+dt.timedelta(minutes=5), high=1000)],
                  at, 'opening_range_breakout')
    rows[0]['high'] = 13
    assert not signal(rows, at, 'opening_range_breakout')


def test_reclaim_requires_crossing_not_merely_above_vwap():
    at = dt.datetime(2026, 9, 22, 13, 30)
    rows = [dict(bar_end=at-dt.timedelta(minutes=5), close=9, volume=100, amount=1000),
            dict(bar_end=at, close=11, volume=100, amount=1000)]
    assert signal(rows, at, 'vwap_reclaim')
    rows[0]['close'] = 11
    assert not signal(rows, at, 'vwap_reclaim')
