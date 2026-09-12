import datetime as dt
import json

import polars as pl
import pytest

from quant.research.factor_battery_cost_report import compare_nav
from quant.research.factor_battery_costs import cost_metrics
from quant.data.factor_benchmarks import read_etf_total_return
from quant.research import factor_battery_cost_report as reporting


def test_comparison_includes_first_common_day_return():
    dates = [dt.date(2020, 1, day) for day in (2, 3, 6)]
    strategy = pl.DataFrame({'date': dates[1:], 'unit_nav': [.9, 1.1]})
    benchmark = pl.DataFrame({'date': dates, 'unit_nav': [2., 2.2, 2.4]})
    result = compare_nav(strategy, benchmark)
    assert result['sessions'] == 2
    assert result['relative_total_return'] == pytest.approx(1.1/1.2-1)
    assert result['net_cagr_excess'] < 0
    assert compare_nav(strategy, strategy)['net_cagr_excess'] == 0.


def test_comparison_does_not_silently_drop_missing_sessions():
    dates = [dt.date(2020, 1, day) for day in (2, 3, 6)]
    strategy = pl.DataFrame({'date': dates, 'unit_nav': [1., 1.1, 1.2]})
    with pytest.raises(ValueError, match='different session grid'):
        compare_nav(strategy, strategy.filter(pl.col('date') != dates[1]))


@pytest.mark.parametrize('dates', [[], [dt.date(2020, 1, 3), dt.date(2020, 1, 2)],
    [dt.date(2020, 1, 2)] * 2, [None, dt.date(2020, 1, 2)]])
def test_date_checks_reject_empty_unordered_duplicate_and_null_sessions(dates):
    nav = pl.DataFrame({'date': dates, 'unit_nav': [1.] * len(dates)},
                       schema={'date': pl.Date, 'unit_nav': pl.Float64})
    with pytest.raises(ValueError, match='ordered'):
        compare_nav(nav, nav)
    with pytest.raises(ValueError, match='ordered'):
        cost_metrics(nav, pl.DataFrame(), initial_cash=100.)


def test_etf_reference_preserves_first_observed_return_and_cuts_future(tmp_path):
    folder = tmp_path/'clean/factor_benchmarks/fixture'
    folder.mkdir(parents=True)
    dates = [dt.date(2020, 1, day) for day in (2, 3, 6)]
    pl.DataFrame({'symbol': ['510300.SH']*3, 'trade_date': dates,
                  'adjusted_close': [2., 2.2, 9.]}).write_parquet(folder/'prices.parquet')
    result = read_etf_total_return(data_root=tmp_path, snapshot='fixture', end=dates[1])
    assert result['date'].to_list() == [dates[1]]
    assert result['unit_nav'].to_list() == [1.1]
    with pytest.raises(ValueError, match='Invalid ETF'):
        read_etf_total_return(data_root=tmp_path, snapshot='../fixture', end=dates[1])


def test_reporting_ignores_preserved_unfinished_year_directories(tmp_path):
    (tmp_path/'summary.json').write_text('{}')
    folder = tmp_path/'raw/cost_1/2020'
    folder.mkdir(parents=True)
    nav = pl.DataFrame({'date': [dt.date(2020,12,31)], 'unit_nav': [1.]})
    nav.write_parquet(folder/'nav.parquet')
    pl.DataFrame({'date': [], 'notional': []}).write_parquet(folder/'trades.parquet')
    partial = folder.parent/'.2020-unfinished-fixture'
    partial.mkdir()
    (partial/'nav.parquet').write_text('incomplete preserved write')
    actual, _ = reporting.load_cost_history(tmp_path, 'raw', 1., dt.date(2020,12,31))
    assert actual.equals(nav)
    assert (partial/'nav.parquet').read_text() == 'incomplete preserved write'
    (folder/'nav.parquet').unlink()
    with pytest.raises(FileNotFoundError):
        reporting.load_cost_history(tmp_path, 'raw', 1., dt.date(2020,12,31))


def test_benchmark_cache_is_shared_only_within_explicit_reporting_scope(tmp_path, monkeypatch):
    run, benchmarks = tmp_path/'factor', tmp_path/'benchmarks'
    config = '[portfolio]\ninitial_cash=100.0\n[costs]\n[universe]\n[run]\nas_of=2020-12-31\n'
    for folder in (run, benchmarks):
        folder.mkdir()
        (folder/'battery.toml').write_text(config)
    (run/'summary.json').write_text(json.dumps({'execution_snapshot': 'same', 'rows': [
        {'factor': 'a', 'variant': variant, 'cost_multiplier': 1.} for variant in ('raw', 'neutral')]}))
    (benchmarks/'summary.json').write_text(json.dumps({'execution_snapshot': 'same', 'rows': [
        {'variant': variant, 'cost_multiplier': 1.} for variant in ('market', 'csi800')]}))
    calls = []
    index_calls = []
    nav = pl.DataFrame({'date': [dt.date(2020,12,30),dt.date(2020,12,31)], 'unit_nav': [1.,1.01],
        'equity': [100.,101.], 'market_value': [90.,90.], 'cumulative_fees': [0.,0.]})
    def load(folder, variant, multiplier, end):
        calls.append(folder)
        return nav, pl.DataFrame(schema={'date': pl.Date, 'notional': pl.Float64})
    monkeypatch.setattr(reporting, 'load_cost_history', load)
    def indexes(**kwargs):
        index_calls.append(kwargs)
        return {name: nav.select('date','unit_nav') for name in kwargs['names']}
    monkeypatch.setattr('quant.data.equal_weight_index.load_return_benchmarks', indexes)
    config_path = tmp_path/'return.toml'
    config_path.write_text('[benchmarks]')
    args = dict(run=run, benchmarks=benchmarks, return_benchmark_config=config_path)
    cache = {}
    first = reporting.collect_cost_report(**args, benchmark_cache=cache)
    second = reporting.collect_cost_report(**args, benchmark_cache=cache)
    assert first == second and len(index_calls) == 3
    assert calls.count(benchmarks) == 0  # Legacy account is checked, never read as a benchmark NAV.
    reporting.collect_cost_report(**args)
    assert len(index_calls) == 6
    absent = reporting.collect_cost_report(run=run, benchmarks=benchmarks)
    assert all(row['comparison_status'] == 'unavailable' for row in absent['benchmark_comparisons'])
    assert not absent['return_indexes_complete']


@pytest.mark.parametrize('missing', ['first', 'last', 'middle'])
def test_holding_comparison_never_shrinks_index_window(missing):
    dates = [dt.date(2020, 1, day) for day in (2, 3, 6)]
    nav = pl.DataFrame({'date': dates, 'unit_nav': [.99, 1.1, 1.2]})
    index = nav.filter(pl.col('date') != dates[{'first': 0, 'middle': 1, 'last': 2}[missing]])
    with pytest.raises(ValueError, match='no shrinking'):
        reporting.compare_holding_index(nav, index, start=dates[0], end=dates[-1])


def test_holding_metrics_keep_entry_fee_and_prior_equity():
    dates = [dt.date(2020, 1, day) for day in (2, 3, 6)]
    nav = pl.DataFrame({'date': dates, 'unit_nav': [1., .99, .98], 'equity': [100., 99., 98.],
        'market_value': [0., 90., 0.], 'cumulative_fees': [0., 1., 2.]})
    trades = pl.DataFrame({'date': dates[1:], 'notional': [90., 88.]})
    result = reporting.holding_cost_metrics(nav, trades, initial_cash=100.)
    assert result['total_return'] == pytest.approx(-.02)
    assert result['sessions'] == 2 and result['initial_cash_period']['sessions'] == 1
    assert result['annualized_one_way_turnover'] == pytest.approx((90/100+88/99)/2*252/2)


def test_optional_etf_coverage_is_separate_for_raw_and_neutral(tmp_path, monkeypatch):
    run = tmp_path/'cost'
    run.mkdir()
    (run/'battery.toml').write_text('[portfolio]\ninitial_cash=100.0\n[run]\nas_of=2020-01-03\n')
    (run/'summary.json').write_text(json.dumps({'rows': [
        {'factor': 'a', 'variant': v, 'cost_multiplier': 1.} for v in ('raw','neutral')]}))
    config = tmp_path/'return.toml'
    config.write_text('[benchmarks]')
    dates = [dt.date(2020,1,2), dt.date(2020,1,3)]
    def load(folder, variant, *args):
        return pl.DataFrame({'date': dates, 'unit_nav': [1.,1.02], 'equity': [100.,102.],
            'market_value': [90. if variant == 'raw' else 0.,90.], 'cumulative_fees': [0.,0.]}), \
            pl.DataFrame(schema={'date': pl.Date, 'notional': pl.Float64})
    def indexes(**kw):
        name = kw['names'][0]
        if name == '510300' and kw['start'] == dates[0]:
            raise ValueError('ETF coverage starts later')
        grid = [d for d in dates if d >= kw['start']]
        return {name: pl.DataFrame({'date': grid, 'unit_nav': [1.]*len(grid)})}
    monkeypatch.setattr(reporting, 'load_cost_history', load)
    monkeypatch.setattr('quant.data.equal_weight_index.load_return_benchmarks', indexes)
    result = reporting.collect_cost_report(run=run, return_benchmark_config=config)
    rows = {(r['variant'],r['benchmark']):r for r in result['benchmark_comparisons']}
    assert rows['raw','510300_total_return_reference']['comparison_status'] == 'unavailable'
    assert rows['neutral','510300_total_return_reference']['comparison_status'] == 'complete'
    assert rows['raw','all_market_equal_weight']['net_cagr_excess'] > 0
    assert len(result['rows']) == 2
