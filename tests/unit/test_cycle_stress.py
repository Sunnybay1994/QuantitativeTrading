import datetime as dt
import json

import polars as pl
import pytest

from quant.reporting.cycle_stress import benchmark_regimes, path_statistics


def test_initial_loss_recovery_and_calendar_slice_keep_previous_wealth():
    dates = [dt.date(2020, 1, 2) + dt.timedelta(days=i) for i in range(6)]
    nav = pl.DataFrame({'date': dates, 'unit_nav': [.8, .9, 1., 1.2, 1.08, 1.3]})
    full = path_statistics(nav, start=dates[0], end=dates[-1])
    assert full['max_drawdown'] == pytest.approx(-.2)
    assert full['worst_day'] == pytest.approx(-.2)
    assert full['max_drawdown_recovery_date'] == dates[2]
    assert full['longest_underwater_sessions'] == 2
    assert full['max_drawdown_peak_is_initial_capital']
    assert full['worst_5_sessions'] == pytest.approx(.08)
    assert full['expected_shortfall_95'] == pytest.approx(-.2)
    window = path_statistics(nav, start=dates[4], end=dates[5])
    assert window['starting_unit_nav'] == 1.2
    assert window['total_return'] == pytest.approx(1.3/1.2-1)
    assert window['worst_day'] == pytest.approx(-.1)


def test_unrecovered_loss_and_bad_paths():
    dates = [dt.date(2020, 1, i) for i in (2, 3, 6)]
    nav = pl.DataFrame({'date': dates, 'unit_nav': [1.1, .8, .9]})
    result = path_statistics(nav, start=dates[0], end=dates[-1])
    assert result['unrecovered_at_end']
    assert result['max_drawdown_recovery_date'] is None
    assert result['max_drawdown_peak_date'] == dates[0]
    with pytest.raises(ValueError):
        path_statistics(pl.concat([nav, nav.head(1)]), start=dates[0], end=dates[-1])


def test_regime_uses_previous_close_and_keeps_future_prices_out():
    start = dt.date(2019, 1, 1)
    bars = pl.DataFrame({'trade_date': [start+dt.timedelta(days=i) for i in range(225)],
                         'close': [100.+i for i in range(224)]+[1.]})
    regimes = benchmark_regimes(bars)
    assert regimes['regime'][-1] == 'bull'
    assert regimes['regime'][-1] == benchmark_regimes(bars.with_columns(
        pl.when(pl.col('trade_date') == bars['trade_date'][-1]).then(10000.).otherwise(pl.col('close')).alias('close')))['regime'][-1]


@pytest.mark.parametrize('paired', ['three_factor', 'cv20_monthly_buffered'])
def test_export_uses_registered_pair_and_requires_every_cost_case(tmp_path, monkeypatch, paired):
    import quant.reporting.cycle_stress as reporting
    run = tmp_path / 'run'
    run.mkdir()
    comparisons = ['top50', paired, '510300']
    config = tmp_path / 'config.toml'
    config.write_text('[research]\nhypothesis_id="fixture"\n[data]\nwarmup_start=2019-01-01\n'
        '[[walk_forward.folds]]\ntest_start=2020-01-02\ntest_end=2020-01-06\n'
        f'[cycle_validation]\ncomparisons={json.dumps(comparisons)}\n'
        '[[cycle_validation.stress_windows]]\nname="shock"\nstart=2020-01-03\nend=2020-01-06\n', encoding='utf-8')
    dates = [dt.date(2020, 1, day) for day in (2, 3, 6)]
    nav = pl.DataFrame({'date': dates, 'unit_nav': [.99, 1.01, 1.02], 'delisting_writeoff': [0., 0., 0.]})
    metrics = path_statistics(nav, start=dates[0], end=dates[-1])
    rows, frames = [], []
    for comparison in comparisons:
        for multiplier in (.5, 1., 2.):
            rows.append(dict(fold=1, comparison=comparison, cost_multiplier=multiplier,
                annualized_one_way_turnover=1., **metrics))
            frames.append(nav.with_columns(pl.lit(1).alias('fold'), pl.lit(comparison).alias('comparison'),
                pl.lit(multiplier).alias('cost_multiplier')))
    pl.concat(frames).write_parquet(run / 'nav.parquet')
    empty = pl.DataFrame(schema={'date': pl.Date, 'fold': pl.Int32, 'comparison': pl.String,
        'cost_multiplier': pl.Float64, 'side': pl.String, 'reason': pl.String})
    for name in ('trades', 'rejections'):
        empty.write_parquet(run / f'{name}.parquet')
    report = dict(hypothesis_id='fixture', conclusion='RESEARCH_ONLY', results=rows, factor_diagnostics=[])
    (run / 'report.json').write_text(json.dumps(report, default=str), encoding='utf-8')
    market = pl.DataFrame({'trade_date': [dt.date(2019, 1, 1)+dt.timedelta(days=i) for i in range(400)],
        'close': [100.+i for i in range(400)]})
    monkeypatch.setattr(reporting, 'read_etf_research_inputs', lambda *a: (market, None, None, None))
    result = reporting.analyze(run=run, config=config, data_root=tmp_path, output=tmp_path / 'analysis')
    assert {r['comparison'] for r in result['total']} == set(comparisons)
    assert len(result['total']) == len(result['stress_windows']) == 9
    assert pl.read_parquet(tmp_path / 'analysis/continuous_nav_with_regimes.parquet').height == 27
    report['results'] = rows[:-1]
    (run / 'report.json').write_text(json.dumps(report, default=str), encoding='utf-8')
    with pytest.raises(ValueError, match='all configured'):
        reporting.analyze(run=run, config=config, data_root=tmp_path, output=tmp_path / 'incomplete')
