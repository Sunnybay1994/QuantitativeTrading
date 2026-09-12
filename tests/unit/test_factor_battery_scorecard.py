import polars as pl
import pytest
import json

from quant.research.factor_battery_scorecard import assemble_scorecard
from quant.research.factor_battery_cost_report import MEASUREMENT


def fixture():
    settings = {'primary_variant': 'raw', 'portfolio': {'cost_multipliers': [.5, 1., 2.]},
                'admission': {'minimum_top_net_excess_all_market_ew': 0.,
                              'maximum_absolute_rank_correlation_with_better': .7}}
    screen = pl.DataFrame({'factor': ['a', 'b', 'c', 'd', 'e'], 'variant': ['raw']*5,
                           'icir': [.9, .8, .7, .6, .1], 'statistical_pass': [True]*4+[False]})
    correlations = pl.DataFrame({'factor': ['a', 'b', 'c', 'd', 'e'], 'variant': ['raw']*5,
        'higher_max_absolute_rank_correlation': [None, .2, .7, .3, .2]})
    reports = []
    for factor, excess in (('a', 0.), ('b', .01), ('c', .02)):
        reports.append({'measurement': MEASUREMENT, 'return_indexes_complete': True, 'rows': [{'factor': factor, 'variant': 'raw', 'cost_multiplier': multiplier,
            'holding_evidence': True, 'cagr': -.1 if multiplier == 2 else .1, 'sharpe': .4, 'max_drawdown': -.3,
            'annualized_one_way_turnover': 1., 'mean_invested_fraction': .8} for multiplier in (.5, 1., 2.)],
            'benchmark_comparisons': [{'variant': 'raw', 'cost_multiplier': cost,
                'benchmark': name, 'net_cagr_excess': excess}
                for cost in (1., .5, 2.) for name in ['all_market_equal_weight', 'csi800_equal_weight', '510300_total_return_reference']]})
    return screen, reports, correlations, settings


def test_admission_requires_positive_excess_and_complete_cost_evidence():
    screen, reports, correlations, settings = fixture()
    result = assemble_scorecard(screen, cost_reports=reports, correlations=correlations, settings=settings)
    assert result['factor_admitted'].to_list() == [False, True, False, None, False]
    assert result['conclusion'].to_list() == ['RESEARCH_ONLY']*4+['REJECTED']
    # A negative 2x CAGR is reported, not a new post-hoc admission condition.
    reports[1]['rows'].pop()
    missing = assemble_scorecard(screen, cost_reports=reports, correlations=correlations, settings=settings)
    assert missing.filter(pl.col('factor') == 'b')['factor_admitted'].item() is None


def test_missing_correlations_and_etf_excess_cannot_substitute_for_admission_inputs():
    screen, reports, correlations, settings = fixture()
    result = assemble_scorecard(screen, cost_reports=reports, correlations=None, settings=settings)
    assert result.filter(pl.col('factor') == 'b')['factor_admitted'].item() is None
    reports[1]['benchmark_comparisons'][0]['benchmark'] = '510300_total_return_reference'
    result = assemble_scorecard(screen, cost_reports=reports, correlations=correlations, settings=settings)
    assert result.filter(pl.col('factor') == 'b')['factor_admitted'].item() is None
    with pytest.raises(ValueError, match='complete correlation'):
        assemble_scorecard(screen, cost_reports=reports, correlations=correlations.head(1), settings=settings)


def test_highest_primary_factor_has_no_higher_peer_to_wait_for():
    screen, reports, _, settings = fixture()
    reports[0]['benchmark_comparisons'][0]['net_cagr_excess'] = .01
    result = assemble_scorecard(screen, cost_reports=reports, correlations=None, settings=settings)
    assert result.filter(pl.col('factor') == 'a')['factor_admitted'].item() is True
    assert result.filter(pl.col('factor') == 'b')['factor_admitted'].item() is None


@pytest.mark.parametrize('rank,rho,admitted', [(2, .9, False), (2, None, None), (0, None, True)])
def test_text_subset_leader_is_not_exempt_from_higher_external_peers(rank, rho, admitted):
    screen, reports, correlations, settings = fixture()
    reports[0]['benchmark_comparisons'][0]['net_cagr_excess'] = .01
    # The evaluated subset contains only a, but its ranking includes the old library.
    correlations = correlations.head(1).with_columns(
        pl.lit(rank).alias('comparison_primary_rank'),
        pl.lit(rho, dtype=pl.Float64).alias('higher_max_absolute_rank_correlation'))
    result = assemble_scorecard(screen.head(1), cost_reports=reports[:1],
                                correlations=correlations, settings=settings)
    assert result['factor_admitted'].item() is admitted


def test_missing_comparison_rank_cannot_silently_use_subset_ranking():
    screen, reports, correlations, settings = fixture()
    correlations = correlations.with_columns(pl.lit(None, dtype=pl.Int64).alias('comparison_primary_rank'))
    with pytest.raises(ValueError, match='comparison-pool'):
        assemble_scorecard(screen, cost_reports=reports, correlations=correlations, settings=settings)


@pytest.mark.parametrize('problem', [None, 'settings', 'missing', 'duplicate_factor'])
def test_refresh_retains_previous_runs_and_deduplicates_overlapping_paths(tmp_path, monkeypatch, problem):
    from quant.research import factor_battery_scorecard as module

    screen, reports, _, _ = fixture()
    folder, previous, costs = tmp_path/'screen', tmp_path/'previous', tmp_path/'costs'
    folder.mkdir()
    previous.mkdir()
    config = '''primary_variant = "raw"
[run]
as_of = "2026-08-31"
[portfolio]
cost_multipliers = [0.5, 1.0, 2.0]
[admission]
minimum_top_net_excess_all_market_ew = 0.0
maximum_absolute_rank_correlation_with_better = 0.7
'''
    (folder/'battery.toml').write_text(config)
    (previous/'battery.toml').write_text(config + ('\n# changed' if problem == 'settings' else ''))
    screen.write_parquet(folder/'statistical_screen.parquet')
    for factor in ['a', 'b']:
        path = costs/factor
        path.mkdir(parents=True)
        (path/'summary.json').write_text(json.dumps({'execution_snapshot': 'frozen'}))
    (previous/'summary.json').write_text(json.dumps({'cost_runs': [str(costs/'a')]}))
    if problem == 'missing':
        (costs/'a'/'summary.json').unlink()
    monkeypatch.setattr(module, 'existing_cost_factor',
                        lambda path, **kwargs: 'a' if problem == 'duplicate_factor' else path.name)
    calls = []

    def collect(*, run, **kwargs):
        calls.append(run.name)
        return reports[0 if run.name == 'a' else 1]

    monkeypatch.setattr(module, 'collect_cost_report', collect)
    args = dict(screen=folder, output=tmp_path/'new', cost_runs=[costs/'a'], cost_root=costs,
                benchmarks=None, redundancy=None, data_root=tmp_path, previous_scorecard=previous)
    if problem:
        with pytest.raises(ValueError):
            module.run_scorecard(**args)
        assert not (tmp_path/'new').exists()
    else:
        result = module.run_scorecard(**args)
        assert calls == ['a', 'b']
        assert result['cost_complete_rows'] == 2
        assert len(result['cost_runs']) == 2
        assert len(json.loads((previous/'summary.json').read_text())['cost_runs']) == 1



def test_legacy_positive_cost_flags_cannot_be_reused():
    screen, reports, correlations, settings = fixture()
    del reports[1]['measurement']
    result = assemble_scorecard(screen, cost_reports=reports, correlations=correlations, settings=settings)
    row = result.filter(pl.col('factor') == 'b').row(0, named=True)
    assert row['costs_complete'] is False and row['factor_admitted'] is None


def test_no_holdings_is_explicit_rejection_not_a_pass():
    screen, reports, correlations, settings = fixture()
    for row in reports[1]['rows']:
        row['holding_evidence'] = False
        row['cagr'] = None
    result = assemble_scorecard(screen, cost_reports=reports, correlations=correlations, settings=settings)
    assert result.filter(pl.col('factor') == 'b')['factor_admitted'].item() is False


def test_missing_optional_index_does_not_add_an_admission_condition():
    screen, reports, correlations, settings = fixture()
    reports[1]['benchmark_comparisons'] = [row for row in reports[1]['benchmark_comparisons']
                                           if row['benchmark'] != 'csi800_equal_weight']
    result = assemble_scorecard(screen, cost_reports=reports, correlations=correlations, settings=settings)
    assert result.filter(pl.col('factor') == 'b')['factor_admitted'].item() is True
