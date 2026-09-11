import polars as pl
import pytest

from quant.research.factor_battery_scorecard import assemble_scorecard


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
        reports.append({'rows': [{'factor': factor, 'variant': 'raw', 'cost_multiplier': multiplier,
            'cagr': -.1 if multiplier == 2 else .1, 'sharpe': .4, 'max_drawdown': -.3,
            'annualized_one_way_turnover': 1., 'mean_invested_fraction': .8} for multiplier in (.5, 1., 2.)],
            'benchmark_comparisons': [{'variant': 'raw', 'cost_multiplier': 1.,
                'benchmark': 'all_market_equal_weight', 'net_cagr_excess': excess}]})
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
