import datetime as dt
import json

import polars as pl
import pytest

from quant.reporting.forward_dashboard import read_account


def account(tmp_path):
    nav = []
    for day, equity, price, notional in [('2026-09-10', 990., 89., 900.), ('2026-09-11', 980., 88., 0.)]:
        folder = tmp_path/day
        folder.mkdir()
        nav.append({'date': day, 'unit_nav': equity/1000, 'equity': equity, 'cash': 100., 'market_value': equity-100})
        (folder/'state.json').write_text(json.dumps({'date': day, 'cash': 100,
            'holdings': {'example': {'quantity': 10, 'mark_price': price}}}))
        pl.from_dicts(nav).write_csv(folder/'nav.csv')
        pl.DataFrame({'date': [day], 'notional': [notional]}).write_csv(folder/'fills.csv')
    return {'root': str(tmp_path), 'account': 'example'}


def test_drawdown_includes_initial_cash_and_turnover_includes_entry(tmp_path):
    spec = account(tmp_path)
    row = read_account(spec, dt.date(2026, 9, 11))
    assert row['status'] == 'current'
    assert row['maximum_drawdown'] == pytest.approx(-.02)
    assert row['turnover'] == pytest.approx(450/985)
    assert row['cash_weight']+sum(r['weight'] for r in row['exposures']) == pytest.approx(1)
    earlier = read_account(spec, dt.date(2026, 9, 10))
    assert earlier['as_of'] == '2026-09-10'
    assert len(earlier['history']) == 1


def test_missing_fill_file_is_unknown_not_zero_and_stale_is_visible(tmp_path):
    spec = account(tmp_path)
    (tmp_path/'2026-09-11'/'fills.csv').unlink()
    row = read_account(spec, dt.date(2026, 9, 14))
    assert row['status'] == 'stale'
    assert row['turnover'] is None


def test_balance_mismatch_is_unavailable(tmp_path):
    spec = account(tmp_path)
    path = tmp_path/'2026-09-11'/'state.json'
    state = json.loads(path.read_text())
    state['cash'] = 200
    path.write_text(json.dumps(state))
    row = read_account(spec, dt.date(2026, 9, 11))
    assert row['status'] == 'unavailable'
    assert '不平' in row['error']
