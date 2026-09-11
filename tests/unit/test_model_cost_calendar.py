import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.research import factor_battery_costs as costs
from quant.research.classic_monthly_baseline import replay
from tests.unit.test_batched_daily_replay import replay_inputs
from tests.unit.test_paper_ledger import D1, D2, D3


@pytest.mark.parametrize('all_cash', [False, True])
def test_explicit_start_preserves_cash_sessions_using_the_same_account(tmp_path, monkeypatch, all_cash):
    inputs = replay_inputs()
    inputs['dividends'] = inputs['dividends'].head(0)
    targets = inputs['targets'].tail(1).with_columns(pl.lit(1.).alias('weight'))
    if all_cash:
        targets = targets.head(0)
    settings = {**inputs['config'], 'run': {'as_of': D3},
        'data': {'refresh_config': 'unused'},
        'portfolio': {**inputs['config']['portfolio'], 'cost_multipliers': [.5, 1., 2.],
                       'stock_dividend_withholding': .2}}

    def read(**kwargs):
        assert kwargs['start'] == D1
        empty = not kwargs['symbols']
        return {**{name: inputs[name].head(0) if empty else inputs[name]
                   for name in ('bars', 'instruments', 'dividends')},
                'calendar': inputs['calendar'], 'limits': pl.DataFrame(), 'suspensions': pl.DataFrame()}

    monkeypatch.setattr(costs, 'read_battery_execution', read)
    monkeypatch.setattr(costs, 'stock_session_states', lambda **kwargs: inputs['market_states'])
    result = costs.run_cost_plans(settings=settings, plans={'model': ('probe', targets)},
        sessions=(D1, D2, D3), output=tmp_path, data_root=tmp_path, execution_snapshot='fixture', factor='model', start=D1)
    assert len(result['rows']) == 3
    nav = pl.read_parquet(tmp_path/'model'/'cost_1'/'2026'/'nav.parquet')
    assert nav['date'].to_list() == [D1, D2, D3]
    assert nav['unit_nav'][:2].to_list() == [1., 1.]
    expected = replay(**{**inputs, 'targets': targets}, validate_once=True)
    assert_frame_equal(nav, expected[0])
    if all_cash:
        assert nav['unit_nav'].to_list() == [1., 1., 1.]
        assert all(row['trade_count'] == 0 for row in result['rows'])
