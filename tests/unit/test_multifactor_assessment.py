import copy
import datetime as dt
import tomllib
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from quant.reporting.cycle_stress import path_statistics
from quant.reporting.multifactor_assessment import assess_model, calendar_years, underwater_calendar, holding_metrics
from quant.reporting.multifactor_models import render_model_report


def fixture():
    model = tomllib.loads(Path('configs/models/p4_annual_walk_forward_20260911.toml').read_text(encoding='utf-8'))
    model['walk_forward'].update(test_start=dt.date(2020, 1, 1), test_end=dt.date(2024, 12, 31))
    dates = [dt.date(2020, 1, 1)+dt.timedelta(days=i) for i in range(1827)
             if (dt.date(2020, 1, 1)+dt.timedelta(days=i)).weekday() < 5]
    values = np.cumprod(1+.0007+.0001*np.sin(np.arange(len(dates))))
    nav = pl.DataFrame({'date': dates, 'unit_nav': values, 'market_value': values*100, 'equity': values*100})
    # ETF wins the first year, but CSI800 wins the full period.
    etf_returns = np.array([.0005 if d.year == 2020 else 0. for d in dates])
    benchmarks = {
        '510300_total_return_reference': pl.DataFrame({'date': dates, 'unit_nav': np.cumprod(1+etf_returns)}),
        'csi800_equal_weight': pl.DataFrame({'date': dates, 'unit_nav': np.cumprod(np.full(len(dates), 1.0002))}),
        'all_market_equal_weight': pl.DataFrame({'date': dates, 'unit_nav': [1.]*len(dates)})}
    risk = path_statistics(nav, start=model['walk_forward']['test_start'], end=model['walk_forward']['test_end'])
    one = {**risk, 'annualized_one_way_turnover': 4.}
    windows = tomllib.loads(Path(model['admission']['stress_windows_config']).read_text(encoding='utf-8'))[
        'cycle_validation']['stress_windows']
    return nav, one, benchmarks, model, windows


def test_calendar_underwater_uses_anniversaries_including_recovery_and_leap_day():
    assert calendar_years(dt.date(2020, 2, 29), dt.date(2023, 2, 28)) == 3.
    start = dt.date(2020, 1, 1)
    nav = pl.DataFrame({'date': [dt.date(2020, 1, 2), dt.date(2023, 1, 1)], 'unit_nav': [.9, 1.]})
    result = underwater_calendar(nav, start=start)
    assert result['years'] == 3. and result['recovered'] is True
    later = nav.with_columns(pl.Series('date', [dt.date(2020, 1, 2), dt.date(2023, 1, 2)]))
    assert underwater_calendar(later, start=start)['years'] > 3.
    with pytest.raises(ValueError, match='ordered unique'):
        underwater_calendar(nav.reverse(), start=start)


def test_full_period_strongest_benchmark_is_fixed_for_annual_and_stress():
    nav, one, benchmarks, model, windows = fixture()
    result = assess_model(nav=nav, one=one, two=one, benchmarks=benchmarks, model=model, windows=windows)
    assert result['strongest_benchmark'] == 'csi800_equal_weight'
    assert result['conclusion'] == 'PAPER_CANDIDATE'
    assert all(result['checks'].values())
    first = result['annual'][0]
    expected = path_statistics(benchmarks['csi800_equal_weight'], start=dt.date(2020, 1, 1), end=dt.date(2020, 12, 31))
    assert first['benchmark_return'] == expected['total_return']
    assert len(result['annual']) == 5 and len(result['stress']) == 4


def test_zero_double_cost_return_and_short_active_history_cannot_pass():
    nav, one, benchmarks, model, windows = fixture()
    failed = assess_model(nav=nav, one=one, two={**one, 'cagr': 0.}, benchmarks=benchmarks, model=model, windows=windows)
    assert failed['conclusion'] == 'REJECTED' and not failed['checks']['double_cost_positive']
    nav = nav.with_columns(pl.when(pl.col('date') < dt.date(2024, 1, 1)).then(0.).otherwise(
        pl.col('market_value')).alias('market_value'))
    revised = {**one, **path_statistics(nav, start=dt.date(2024, 1, 1), end=model['walk_forward']['test_end'])}
    short = assess_model(nav=nav, one=revised, two=one, benchmarks=benchmarks, model=model, windows=windows)
    assert short['conclusion'] == 'RESEARCH_ONLY' and not short['checks']['active_evidence']


def test_missing_session_and_duplicate_stress_window_are_not_accepted():
    nav, one, benchmarks, model, windows = fixture()
    broken = {**benchmarks, 'csi800_equal_weight': benchmarks['csi800_equal_weight'].slice(1)}
    with pytest.raises(ValueError, match='session grids'):
        assess_model(nav=nav, one=one, two=one, benchmarks=broken, model=model, windows=windows)
    with pytest.raises(ValueError, match='distinct'):
        assess_model(nav=nav, one=one, two=one, benchmarks=benchmarks, model=model, windows=[windows[0]]*4)


def test_sensitivity_cannot_replace_failed_primary_in_report():
    nav, one, benchmarks, model, windows = fixture()
    passed = assess_model(nav=nav, one=one, two=one, benchmarks=benchmarks, model=model, windows=windows)
    failed = copy.deepcopy(passed)
    failed.update(conclusion='REJECTED', checks={**failed['checks'], 'turnover': False})
    report = render_model_report('equal_z', rows=[], assessment={'primary': failed, 'sensitivity': passed}, model=model)
    assert report.startswith('# equal_z：REJECTED')
    assert 'Top100仅作敏感性报告' in report
    assert 'turnover' in report


def test_stress_return_win_does_not_hide_a_worse_window_drawdown():
    nav, one, benchmarks, model, windows = fixture()
    nav = nav.with_columns(pl.when(pl.col('date') == dt.date(2024, 1, 31)).then(
        pl.col('unit_nav')*.8).otherwise(pl.col('unit_nav')).alias('unit_nav'))
    revised = {**one, **path_statistics(nav, start=model['walk_forward']['test_start'], end=model['walk_forward']['test_end'])}
    result = assess_model(nav=nav, one=revised, two=revised, benchmarks=benchmarks, model=model, windows=windows)
    shock = next(row for row in result['stress'] if row['window'] == '2024_early_year_selloff')
    assert shock['model_return'] > shock['benchmark_return']
    assert shock['not_worse'] is False



def small_account():
    dates = [dt.date(2024, 1, i) for i in range(1, 7)]
    nav = pl.DataFrame({'date': dates, 'unit_nav': [1., 1., .99, 1.08, 1.07, 1.07],
                        'equity': [100., 100., 99., 108., 107., 107.],
                        'market_value': [0., 0., 90., 100., 0., 0.]})
    trades = pl.DataFrame({'date': [dates[2], dates[4]], 'notional': [90., 100.]})
    return nav, trades


def test_holding_window_entry_fee_cash_days_and_prior_equity_turnover():
    nav, trades = small_account()
    result = holding_metrics(nav, trades, initial_cash=100.)
    assert result['active_start'] == dt.date(2024, 1, 3)
    assert result['initial_cash_period']['sessions'] == 2
    assert result['sessions'] == 4 and result['cash_sessions_after_entry'] == 2
    assert result['total_return'] == pytest.approx(.07)
    assert result['max_drawdown'] == pytest.approx(-.01)
    assert result['cagr'] == pytest.approx(1.07**(252/4)-1)
    assert result['annualized_one_way_turnover'] == pytest.approx((90/100+100/108)/2*252/4)


def test_first_session_entry_does_not_drop_entry_cost():
    nav, trades = small_account()
    result = holding_metrics(nav.slice(2), trades, initial_cash=100.)
    assert result['initial_cash_period']['sessions'] == 0
    assert result['max_drawdown'] == pytest.approx(-.01)
    assert result['total_return'] == pytest.approx(.07)


def test_zero_holdings_has_no_fabricated_risk_or_active_period():
    nav, _, benchmarks, model, windows = fixture()
    nav = nav.with_columns(pl.lit(0.).alias('market_value'), pl.lit(1.).alias('unit_nav'))
    trades = pl.DataFrame(schema={'date': pl.Date, 'notional': pl.Float64})
    metrics = holding_metrics(nav, trades, initial_cash=100.)
    result = assess_model(nav=nav, one=metrics, two=metrics, benchmarks=benchmarks, model=model, windows=windows)
    assert metrics['cagr'] is None and metrics['sessions'] == 0
    assert result['conclusion'] == 'RESEARCH_ONLY' and result['risk'] is None
    assert result['active_start'] is None and result['stress_windows_not_worse'] == 0
    assert all(row['not_worse'] is None for row in result['stress'])


def test_cash_only_stress_not_passed_and_expanded_window_count_allowed():
    nav, one, benchmarks, model, windows = fixture()
    window = windows[-1]
    nav = nav.with_columns(pl.when(pl.col('date').is_between(
        window['start']-dt.timedelta(days=5), window['end'])).then(0.).otherwise(pl.col('market_value')).alias('market_value'))
    expanded = [*windows, {'name': 'extra', 'start': dt.date(2021, 1, 1), 'end': dt.date(2021, 2, 1)}]
    result = assess_model(nav=nav, one=one, two=one, benchmarks=benchmarks, model=model, windows=expanded)
    shock = next(row for row in result['stress'] if row['window'] == window['name'])
    assert not shock['applicable'] and shock['not_worse'] is None
    assert result['stress_windows_total'] == 5
    model['admission']['minimum_stress_windows_not_worse'] = 5
    result = assess_model(nav=nav, one=one, two=one, benchmarks=benchmarks, model=model, windows=expanded)
    assert not result['checks']['stress_windows']


def test_benchmark_measured_only_on_matching_holding_window():
    nav, _, benchmarks, model, windows = fixture()
    start = dt.date(2023, 1, 2)
    nav = nav.with_columns(pl.when(pl.col('date') < start).then(0.).otherwise(pl.col('market_value')).alias('market_value'))
    metrics = holding_metrics(nav, pl.DataFrame(schema={'date': pl.Date, 'notional': pl.Float64}), initial_cash=100.)
    result = assess_model(nav=nav, one=metrics, two=metrics, benchmarks=benchmarks, model=model, windows=windows)
    for row in result['benchmarks']:
        expected = path_statistics(benchmarks[row['benchmark']], start=start, end=model['walk_forward']['test_end'])
        assert row['total_return'] == expected['total_return'] and row['first'] == start


def test_account_benchmark_rejected():
    nav, one, benchmarks, model, windows = fixture()
    benchmarks['csi800_equal_weight'] = nav
    with pytest.raises(ValueError, match='not account'):
        assess_model(nav=nav, one=one, two=one, benchmarks=benchmarks, model=model, windows=windows)
