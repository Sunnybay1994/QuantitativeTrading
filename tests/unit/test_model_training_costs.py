import json
import datetime as dt

import polars as pl
import pytest

from quant.research.model_training_costs import prefix_cost_report


def fixture():
    dates = [dt.date(2020, 1, day) for day in (2, 3, 6)]
    nav = pl.DataFrame({'date': dates, 'equity': [100., 110., 200.], 'unit_nav': [1., 1.1, 2.],
                       'market_value': [50., 55., 100.], 'cumulative_fees': [0., 1., 10.]})
    trades = pl.DataFrame({'date': dates, 'notional': [100., 50., 1000.]})
    baseline = pl.DataFrame({'date': dates, 'unit_nav': [1., 1.05, 10.]})
    return dates, nav, trades, baseline


def test_future_nav_trades_and_benchmark_do_not_affect_prefix():
    dates, nav, trades, baseline = fixture()
    kwargs = dict(factor='a', cutoff=dates[1], initial_cash=100.)
    original = prefix_cost_report(histories={('raw', 1.): (nav, trades)},
        benchmarks={('all_market_equal_weight', None): baseline}, **kwargs)
    future = pl.col('date') > dates[1]
    nav = nav.with_columns([pl.when(future).then(999.).otherwise(pl.col(name)).alias(name)
                           for name in ('equity', 'unit_nav', 'market_value', 'cumulative_fees')])
    trades = trades.with_columns(pl.when(future).then(99999.).otherwise(pl.col('notional')).alias('notional'))
    baseline = baseline.with_columns(pl.when(future).then(.01).otherwise(pl.col('unit_nav')).alias('unit_nav'))
    changed = prefix_cost_report(histories={('raw', 1.): (nav, trades)},
        benchmarks={('all_market_equal_weight', None): baseline}, **kwargs)
    assert original == changed
    row = original['rows'][0]
    assert row['last_date'] == str(dates[1])
    assert row['ending_equity'] == 110.
    assert row['gross_traded_notional'] == 150.
    assert row['cumulative_fees'] == 1.
    assert next(row for row in original['benchmark_comparisons'] if row['benchmark'] == 'all_market_equal_weight')['net_cagr_excess'] > 0


def test_pre_inception_has_no_cost_evidence_and_missing_refit_is_rejected():
    dates, nav, trades, baseline = fixture()
    histories = {('raw', 1.): (nav, trades)}
    kwargs = dict(factor='a', initial_cash=100.)
    assert prefix_cost_report(histories=histories, benchmarks={}, cutoff=dt.date(2019, 12, 31),
                              **kwargs)['rows'] == []
    with pytest.raises(ValueError, match='Cost history is missing'):
        prefix_cost_report(histories=histories, benchmarks={}, cutoff=dt.date(2020, 1, 7), **kwargs)
    result = prefix_cost_report(histories=histories, benchmarks={('all_market_equal_weight', None): baseline.head(1)},
                           cutoff=dates[1], **kwargs)
    assert all(row['comparison_status'] == 'unavailable' for row in result['benchmark_comparisons'])


def test_costed_account_benchmark_is_rejected():
    dates, nav, trades, baseline = fixture()
    with pytest.raises(ValueError, match='Costed account'):
        prefix_cost_report(factor='a', histories={('raw', 1.): (nav, trades)},
            benchmarks={('all_market_equal_weight', 2.): baseline}, cutoff=dates[-1], initial_cash=100.)


def test_initial_cash_removed_prefix_keeps_entry_fee_and_later_cash():
    dates, nav, trades, baseline = fixture()
    nav = nav.with_columns(pl.Series('market_value', [0., 50., 0.]),
                           pl.Series('unit_nav', [1., .99, .99]), pl.Series('equity', [100., 99., 99.]))
    trades = trades.filter(pl.col('date') == dates[1])
    result = prefix_cost_report(factor='a', histories={('raw', 1.): (nav, trades)},
        benchmarks={('all_market_equal_weight', None): baseline}, cutoff=dates[-1], initial_cash=100.)
    row = result['rows'][0]
    assert row['first_date'] == str(dates[1]) and row['sessions'] == 2
    assert row['total_return'] == pytest.approx(-.01) and row['cash_sessions_after_entry'] == 1
    assert row['annualized_one_way_turnover'] == pytest.approx(50/100/2*252/2)


def test_benchmark_missing_first_holding_day_cannot_shrink_prefix():
    dates, nav, trades, baseline = fixture()
    result = prefix_cost_report(factor='a', histories={('raw', 1.): (nav, trades)},
            benchmarks={('all_market_equal_weight', None): baseline.slice(1)}, cutoff=dates[-1], initial_cash=100.)
    row = next(r for r in result['benchmark_comparisons'] if r['benchmark'] == 'all_market_equal_weight')
    assert row['net_cagr_excess'] is None and 'no shrinking' in row['error']


def test_zero_holding_prefix_cannot_supply_cost_excess():
    dates, nav, trades, baseline = fixture()
    nav = nav.with_columns(pl.lit(0.).alias('market_value'), pl.lit(1.).alias('unit_nav'))
    result = prefix_cost_report(factor='a', histories={('raw', 1.): (nav, trades.head(0))},
        benchmarks={('all_market_equal_weight', None): baseline}, cutoff=dates[-1], initial_cash=100.)
    assert result['rows'][0]['holding_evidence'] is False
    assert result['rows'][0]['cagr'] is None and result['benchmark_comparisons'] == []



def test_annual_driver_uses_refit_end_and_distinguishes_training_threshold(tmp_path, monkeypatch):
    from quant.research import model_training_costs as module
    from quant.research.factor_battery_cost_report import REQUIRED_BENCHMARKS
    dates, nav, trades, baseline = fixture()
    prefix, benchmark, run = [tmp_path/name for name in ('prefix', 'legacy', 'cost')]
    config = '''primary_variant = "raw"
[admission]
minimum_months = 96
minimum_top_net_excess_all_market_ew = 0.0
maximum_absolute_rank_correlation_with_better = 0.7
[portfolio]
initial_cash = 100.0
cost_multipliers = [0.5, 1.0, 2.0]
[costs]
[universe]
[data]
[run]
as_of = 2020-01-06
'''
    for folder in (prefix, benchmark, run):
        folder.mkdir()
        (folder/'battery.toml').write_text(config)
    (prefix/'model.toml').write_text('[selection]')
    (benchmark/'summary.json').write_text(json.dumps({'execution_snapshot': 'fixture'}))
    (run/'summary.json').write_text(json.dumps({'rows': [{'variant': 'raw', 'cost_multiplier': c} for c in (.5,1.,2.)]}))
    pl.DataFrame({'test_year': [2020,2021], 'refit_close': dates[1:], 'factor': ['a','a'],
        'variant': ['raw','raw'], 'icir': [.5,.5], 'statistical_pass': [True,True]}).write_parquet(prefix/'annual_statistical_screen.parquet')
    measurement = tmp_path/'return.toml'
    measurement.write_text('[benchmarks]')
    monkeypatch.setattr(module, 'existing_cost_factor', lambda *args, **kwargs: 'a')
    def load(folder, *args):
        assert folder == run  # Legacy account paths are validation only.
        return nav, trades
    monkeypatch.setattr(module, 'load_cost_history', load)
    calls = []
    def indexes(**kwargs):
        calls.append(kwargs)
        return {name: baseline.filter(pl.col('date') <= kwargs['end']) for name in REQUIRED_BENCHMARKS}
    monkeypatch.setattr(module, 'return_indexes', indexes)
    args = dict(prefix=prefix, output=tmp_path/'report', cost_runs=[run], cost_root=tmp_path/'empty',
                benchmarks=benchmark, data_root=tmp_path, return_benchmark_config=measurement)
    result = module.run_cost_prefixes(**args)
    assert [call['end'] for call in calls] == [dates[1]]*3+[dates[2]]*3
    assert result['training_minimum_months'] == result['final_battery_minimum_months'] == 96
    table = pl.read_parquet(args['output']/'annual_cost_metrics.parquet')
    assert table.filter(pl.col('test_year') == 2020)['ending_equity'].to_list() == [110.]*3
    assert table.height == 6
    from polars.testing import assert_frame_equal
    original_loader = module.load_cost_history
    monkeypatch.setattr(module, 'load_cost_history', lambda *args: pytest.fail('Unchanged completed histories must be reused'))
    reused = module.run_cost_prefixes(**{**args, 'output': tmp_path/'reused', 'previous_costs': args['output']})
    assert reused['reused_cost_factors'] == ['a']
    for file in ('annual_cost_metrics.parquet', 'annual_benchmark_comparisons.parquet', 'annual_cost_screen.parquet'):
        assert_frame_equal(pl.read_parquet(args['output']/file), pl.read_parquet(tmp_path/'reused'/file))
    measurement.write_text('[benchmarks]\nequal_weight_snapshot="changed"\n')
    with pytest.raises(ValueError, match='unchanged model and benchmark'):
        module.run_cost_prefixes(**{**args, 'output': tmp_path/'changed_returns', 'previous_costs': args['output']})
    measurement.write_text('[benchmarks]')
    import shutil
    replacement = tmp_path/'replacement'
    shutil.copytree(run, replacement)
    reads = []
    def replaced_history(folder, *unused):
        reads.append(folder)
        return nav, trades
    monkeypatch.setattr(module, 'load_cost_history', replaced_history)
    replaced = module.run_cost_prefixes(**{**args, 'output': tmp_path/'replaced',
        'cost_runs': [replacement], 'previous_costs': args['output']})
    assert replaced['reused_cost_factors'] == [] and reads == [replacement]*3
    late = tmp_path/'late_inception'
    shutil.copytree(run, late)
    late_summary = json.loads((late/'summary.json').read_text())
    for row in late_summary['rows']:
        row['first_date'] = str(dates[-1])
    (late/'summary.json').write_text(json.dumps(late_summary))
    monkeypatch.setattr(module, 'load_cost_history', lambda *args: (nav.tail(1), trades.filter(pl.col('date') == dates[-1])))
    late_args = {**args, 'cost_runs': [late], 'output': tmp_path/'late_report'}
    module.run_cost_prefixes(**late_args)
    monkeypatch.setattr(module, 'load_cost_history', lambda *args: pytest.fail('Late inception cache must also be reusable'))
    late_reuse = module.run_cost_prefixes(**{**late_args, 'output': tmp_path/'late_reused',
                                            'previous_costs': late_args['output']})
    assert late_reuse['reused_cost_factors'] == ['a']
    assert_frame_equal(pl.read_parquet(late_args['output']/'annual_cost_screen.parquet'),
                       pl.read_parquet(tmp_path/'late_reused'/'annual_cost_screen.parquet'))
    monkeypatch.setattr(module, 'load_cost_history', original_loader)
    (prefix/'model.toml').write_text('[selection]\nminimum_known_months = 48\n')
    changed = module.run_cost_prefixes(**{**args, 'output': tmp_path/'training48'})
    assert changed['training_minimum_months'] == 48 and changed['final_battery_minimum_months'] == 96
    (prefix/'summary.json').write_text(json.dumps({'training_minimum_months': 96}))
    with pytest.raises(ValueError, match='prefix threshold'):
        module.run_cost_prefixes(**{**args, 'output': tmp_path/'mixed'})
