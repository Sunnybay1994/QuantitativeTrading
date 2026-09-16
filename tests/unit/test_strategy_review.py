from quant.reporting.strategy_review import classify, tags
from quant.reporting.daily_attention import attention

POLICY = {'minimum_years': 5., 'strong_excess': .05, 'strong_sharpe': 1.5,
          'soft_checks': ['drawdown', 'turnover', 'stress_windows'],
          'required_checks': ['net_excess', 'double_cost_positive', 'sharpe', 'active_evidence']}


def test_retain_strong_strategy_without_promoting_trading():
    row = {'conclusion': 'REJECTED', 'variant': 'budgeted', 'start': '2019-01-02',
           'end': '2026-08-31', 'excess_1x': .08, 'sharpe_1x': .96, 'measurement': 'holding_window'}
    checks = {k: True for k in POLICY['required_checks']} | {'drawdown': False}
    assert classify(row, {'checks': checks}, POLICY)['review_conclusion'] == 'RESEARCH_ONLY'
    for bad in ('double_cost_positive', 'portfolio_constraints_verified', 'unknown_failure'):
        assert not classify(row, {'checks': checks | {bad: False}}, POLICY)['retained']
    assert not classify(row | {'start': '2024-01-01'}, {'checks': checks}, POLICY)['retained']
    assert not classify(row | {'variant': 'factor/raw'}, {'checks': checks}, POLICY)['retained']
    assert row['conclusion'] == 'REJECTED'


def test_feature_neutralization_does_not_become_neutral_portfolio():
    result = tags({}, 'factor/size_industry_neutral', {})
    assert 'Top组多头回测' in result
    assert '信号中性化≠市场中性' in result
    assert '数据频率待核对' in result


def test_daily_complete_can_have_data_maintenance_without_trade_action():
    daily = {'status': 'complete', 'requires_review': True, 'stages': {'forward_tracking': {
        'status': 'complete', 'result': {'requires_review': True, 'shadow': {
            'missing_horizons': 54, 'observed_horizons': 410, 'errors': []}}}}}
    result = attention(daily)
    assert len(result) == 1
    assert '54' in result[0]['reason']
    assert '无需操作或下单' in result[0]['action']


def test_unexplained_review_flag_is_not_hidden():
    assert attention({'requires_review': True})
    assert attention({'requires_review': False, 'stages': {}}) == []
