import copy
import datetime as dt
import json
import math
import statistics
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.research.pead_account_report import (
    benchmark_comparisons,
    build_report,
    stress_metrics,
    window_metrics,
    write_report,
)


DATES = [dt.date(2024, 1, day) for day in (2, 3, 4, 5, 8, 9)]
RULES = tomllib.loads(Path('configs/models/q1d_causal48_return_benchmark_20260912.toml').read_text(encoding='utf-8'))['admission']


def account(levels=None):
    levels = levels or [1., 1., .99, 1.01, 1.005, 1.005]
    exposure = [0., 0., 80., 80., 0., 0.]
    nav = pl.DataFrame({'date': DATES, 'unit_nav': levels,
        'equity': [value * 100 for value in levels], 'market_value': exposure,
        'cash': [value * 100 - amount for value, amount in zip(levels, exposure)],
        'cumulative_fees': [0., 0., .2, .2, .4, .4]})
    trades = pl.DataFrame({'date': [DATES[2], DATES[4]], 'symbol': ['000001.SZ'] * 2,
        'side': ['BUY', 'SELL'], 'notional': [80., 80.], 'suspension_coverage_complete': [False, True]})
    positions = pl.DataFrame({'date': DATES[2:4], 'symbol': ['000001.SZ'] * 2,
        'quantity': [1, 1], 'market_value': [80., 80.]})
    return {'nav': nav, 'trades': trades, 'positions': positions,
        'rejections': pl.DataFrame(schema={'date': pl.Date, 'reason': pl.String})}


def inputs():
    accounts = {(name, cost): account() for name in ('pead40', 'all_events') for cost in (.5, 1., 2.)}
    benchmarks = {'510300_total_return_reference': pl.DataFrame({'date': DATES, 'unit_nav': [1., 1., .98, 1.02, 1., 1.]})}
    return accounts, benchmarks


def report(accounts=None, benchmarks=None, **kwargs):
    if accounts is None:
        accounts, benchmarks = inputs()
    return build_report(accounts, benchmarks or {}, initial_cash=100., stress_windows=[],
        admission_rules=RULES, **kwargs)


def test_holding_window_preserves_entry_loss_and_cash_tail_with_arithmetic_sharpe():
    frames = account()
    result = window_metrics(frames['nav'], frames['trades'], start=DATES[2], end=DATES[-1], initial_cash=100.)
    returns = [-.01, 1.01 / .99 - 1, 1.005 / 1.01 - 1, 0.]
    expected = statistics.mean(returns) / statistics.stdev(returns) * math.sqrt(252)
    assert result['sharpe_rf0'] == pytest.approx(expected)
    assert result['sharpe_rf2'] == pytest.approx(
        (statistics.mean(returns) - (1.02 ** (1 / 252) - 1)) / statistics.stdev(returns) * math.sqrt(252))
    assert result['max_drawdown'] == pytest.approx(-.01)
    assert result['total_return'] == pytest.approx(.005)
    assert result['sessions'] == 4 and result['cash_sessions'] == 2
    assert result['fees'] == .4 and result['trade_count'] == 2
    assert result['annualized_one_way_turnover_252'] == pytest.approx((80 / 200 + 80 / 202) * 252 / 4)


def test_benchmark_listing_later_exposes_partial_coverage_and_never_fills_prefix():
    frames = account()
    benchmark = pl.DataFrame({'date': DATES[3:], 'unit_nav': [1.01, 1.02, 1.03]})
    row = benchmark_comparisons(frames['nav'], {'etf': benchmark}, start=DATES[2], end=DATES[-1])[0]
    assert row['comparison_status'] == 'partial_coverage'
    assert row['omitted_sessions'] == 1
    assert row['first_date'] == str(DATES[3])
    assert row['benchmark_risk']['total_return'] == pytest.approx(.03)
    assert row['strategy_cagr'] == pytest.approx((1.005 / .99) ** (252 / 3) - 1)


def test_internal_missing_benchmark_date_must_not_shrink_or_bridge():
    frames = account()
    benchmark = pl.DataFrame({'date': [DATES[2], DATES[4], DATES[5]], 'unit_nav': [1., 1.01, 1.02]})
    row = benchmark_comparisons(frames['nav'], {'eq': benchmark}, start=DATES[2], end=DATES[-1])[0]
    assert row['comparison_status'] == 'unavailable'
    assert row['net_cagr_excess'] is None
    assert 'missing holding-window sessions' in row['error']


def test_account_replay_is_not_accepted_as_return_index():
    frames = account()
    row = benchmark_comparisons(frames['nav'], {'bad': frames['nav']}, start=DATES[2], end=DATES[-1])[0]
    assert row['comparison_status'] == 'unavailable'
    assert 'Account replay' in row['error']


def test_missing_pre_window_benchmark_anchor_cannot_bridge_a_return():
    frames = account()
    benchmark = pl.DataFrame({'date': [DATES[0], *DATES[2:]], 'unit_nav': [1., .99, 1.01, 1., 1.]})
    row = benchmark_comparisons(frames['nav'], {'eq': benchmark}, start=DATES[2], end=DATES[-1])[0]
    assert row['comparison_status'] == 'unavailable'
    assert 'anchor session differs' in row['error']


def test_cash_pressure_is_na_but_full_liquidation_day_still_counts():
    frames = account()
    rows = stress_metrics(frames['nav'], frames['trades'], {}, initial_cash=100., windows=[
        {'name': 'cash', 'start': DATES[0], 'end': DATES[1]},
        {'name': 'liquidation', 'start': DATES[4], 'end': DATES[4]},
        {'name': 'after', 'start': DATES[5], 'end': DATES[5]}])
    assert rows[0]['applicable'] is False and rows[0]['total_return'] is None
    assert rows[0]['reason'] == 'cash_only_window'
    assert rows[1]['applicable'] is True
    assert rows[1]['total_return'] == pytest.approx(1.005 / 1.01 - 1)
    assert rows[2]['applicable'] is False


def test_stress_outside_saved_history_cannot_be_truncated_into_success():
    frames = account()
    rows = stress_metrics(frames['nav'], frames['trades'], {}, initial_cash=100., windows=[
        {'name': 'future', 'start': DATES[4], 'end': DATES[-1] + dt.timedelta(days=1)}])
    assert rows[0]['applicable'] is False and rows[0]['reason'] == 'outside_account_history'


def test_six_accounts_full_and_holding_windows_and_pending_gates():
    result = report(expected_sessions=DATES)
    assert len(result['accounts']) == 6
    row = result['accounts'][0]
    assert row['full']['sessions'] == 6 and row['holding']['sessions'] == 4
    assert row['holding']['initial_cash_period']['sessions'] == 2
    assert row['calendar_turnover']['annual'][0]['partial_year'] is True
    assert row['positions']['maximum_names'] == 1
    assert row['suspension_execution_coverage']['covered_fills'] == 1
    assert row['suspension_execution_coverage']['unverified_fills'] == 1
    assert all(r['status'] == 'pending_benchmark_corporate_actions' for r in result['admission'])
    assert result['admission'][0]['checks']['net_excess'] is None
    assert result['admission'][0]['checks']['active_evidence'] is False
    assert result['development_decision']['status'] == 'STOP_FIXED_PORTFOLIO_HYPOTHESIS'
    assert all(row['differences']['cagr'] == 0 for row in result['paired'])
    assert result['auto_trade'] is False
    json.dumps(result, allow_nan=False)


def test_paired_metrics_use_common_later_start_and_actual_prior_capital():
    accounts, benchmarks = inputs()
    for cost in (.5, 1., 2.):
        frames = account([1., 1., 1., 1.01, 1.005, 1.005])
        frames['nav'] = frames['nav'].with_columns(
            pl.when(pl.col('date') == DATES[2]).then(0.).otherwise(pl.col('market_value')).alias('market_value'),
            pl.when(pl.col('date') == DATES[2]).then(pl.col('equity')).otherwise(pl.col('cash')).alias('cash'))
        frames['positions'] = frames['positions'].filter(pl.col('date') >= DATES[3])
        frames['trades'] = frames['trades'].with_columns(
            pl.when(pl.col('date') == DATES[2]).then(pl.lit(DATES[3])).otherwise(pl.col('date')).alias('date'))
        accounts['pead40', cost] = frames
    result = report(accounts, benchmarks)
    pair = result['paired'][0]
    assert pair['first_date'] == str(DATES[3])
    assert pair['treatment_metrics']['total_return'] == pytest.approx(.005)
    assert pair['control_metrics']['total_return'] == pytest.approx(1.005 / .99 - 1)


def test_cost_advantage_reversal_stops_instead_of_promoting():
    accounts, benchmarks = inputs()
    for cost in (.5, 1.):
        accounts['pead40', cost] = account([1., 1., .999, 1.03, 1.03, 1.03])
    accounts['pead40', 2.] = account([1., 1., .98, .97, .96, .96])
    result = report(accounts, benchmarks)
    decision = result['development_decision']
    assert decision['checks']['higher_1x_cagr'] is True
    assert decision['checks']['higher_1x_rf2_sharpe'] is True
    assert decision['checks']['no_2x_cagr_reversal'] is False
    assert decision['status'] == 'STOP_FIXED_PORTFOLIO_HYPOTHESIS'


def test_positive_paired_difference_can_still_lose_money_and_is_never_admission():
    accounts, benchmarks = inputs()
    for cost in (.5, 1., 2.):
        accounts['pead40', cost] = account([1., 1., .99, 1.01, .995, .995])
        accounts['all_events', cost] = account([1., 1., .98, .96, .94, .94])
    result = report(accounts, benchmarks)
    decision = result['development_decision']
    assert decision['status'] == 'PAIRED_GAIN_PENDING_VALIDATION'
    assert decision['positive_difference_does_not_imply_absolute_profit_or_risk_gate_pass'] is True
    assert result['paired'][1]['treatment_metrics']['cagr'] < 0
    assert result['admission'][0]['checks']['double_cost_positive'] is False


@pytest.mark.parametrize('fault', ['missing_cost', 'missing_nav_day', 'missing_positions', 'bad_position_total', 'outside_trade'])
def test_incomplete_or_inconsistent_execution_evidence_is_rejected(fault):
    accounts, benchmarks = inputs()
    frames = accounts['pead40', 1.]
    if fault == 'missing_cost':
        del accounts['pead40', .5]
    elif fault == 'missing_nav_day':
        frames['nav'] = frames['nav'].filter(pl.col('date') != DATES[-1])
    elif fault == 'missing_positions':
        frames['positions'] = frames['positions'].clear()
    elif fault == 'bad_position_total':
        frames['positions'] = frames['positions'].with_columns(pl.lit(79.).alias('market_value'))
    else:
        frames['trades'] = frames['trades'].with_columns(pl.lit(dt.date(2030, 1, 1)).alias('date'))
    with pytest.raises(ValueError):
        report(accounts, benchmarks, expected_sessions=DATES)


def test_cash_only_accounts_are_unvalidated_with_no_phantom_holding_statistics():
    accounts, benchmarks = inputs()
    for frames in accounts.values():
        frames['nav'] = frames['nav'].with_columns(pl.lit(1.).alias('unit_nav'), pl.lit(100.).alias('equity'),
            pl.lit(100.).alias('cash'), pl.lit(0.).alias('market_value'), pl.lit(0.).alias('cumulative_fees'))
        frames['trades'] = frames['trades'].clear()
        frames['positions'] = frames['positions'].clear()
    result = report(accounts, benchmarks)
    assert result['accounts'][0]['holding']['cagr'] is None
    assert result['development_decision']['status'] == 'INSUFFICIENT_ACCOUNT_EVIDENCE'
    assert result['paired'][0]['comparison_status'] == 'unavailable'


def test_writes_machine_periods_without_mutating_source_frames(tmp_path):
    accounts, benchmarks = inputs()
    before = copy.deepcopy(accounts)
    output = tmp_path / 'report'
    result = write_report(output, accounts, benchmarks, initial_cash=100., stress_windows=[], admission_rules=RULES)
    assert (output / 'summary.json').is_file() and (output / 'report.md').is_file()
    assert (output / 'pead40_cost1' / 'periods' / 'monthly_2024.md').is_file()
    assert json.loads((output / 'summary.json').read_text(encoding='utf-8')) == result
    for key in accounts:
        for name in accounts[key]:
            assert accounts[key][name].equals(before[key][name])
    with pytest.raises(FileExistsError):
        write_report(output, accounts, benchmarks, initial_cash=100., stress_windows=[], admission_rules=RULES)
