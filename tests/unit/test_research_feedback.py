import json

import polars as pl

from quant.research.research_feedback import (
    build, summarize, candidate_diagnostic, search_objective_components, search_selection_summary,
)


def test_missing_benchmark_is_independent_of_prediction_failure():
    result = summarize([
        {'factor': 'a', 'statistical_pass': True, 'return_benchmarks_complete': False},
        {'factor': 'b', 'statistical_pass': False, 'return_benchmarks_complete': True,
         'statistical_failures': ['hac_t']},
    ])
    assert result['statistical_pass'] == 1
    assert result['statistical_failure_counts'] == {'hac_t': 1}
    assert result['benchmark_incomplete'] == [{'factor': 'a', 'variant': None}]


def test_negative_search_direction_is_aligned_before_comparing_history():
    candidate = {'direction': -1, 'fitness_preprocessing': 'battery_raw_mad3_scale1.4826_v1',
                 'train': {'mean_ic': -.03, 'icir': -.4, 'newey_west_t': -3.}}
    row = {'factor': 'a', 'variant': 'raw', 'direction': -1, 'mean_ic': .01, 'cost_1_sharpe': .5}
    result = candidate_diagnostic(row, candidate, {'sample_symbols': 300})
    assert result['train_direction_adjusted']['mean_ic'] == .03
    assert abs(result['full_minus_training_mean_ic'] + .02) < 1e-12
    assert result['validation'] is None
    assert result['costs'] == {'cost_1_sharpe': .5}
    assert result['training_sample']['sample_symbols'] == 300
    assert candidate_diagnostic({**row, 'variant': 'size_industry_neutral'}, candidate, {})[
        'full_minus_training_mean_ic'] is None
    assert candidate_diagnostic(row, {}, {})['full_minus_training_mean_ic'] is None


def test_partial_battery_is_not_a_zero_pass_result(tmp_path):
    root = tmp_path/'runs'
    config = tmp_path/'policy.toml'
    config.write_text(f'continuous_root = "{root.as_posix()}"', encoding='utf-8')
    for index, ok in enumerate([True, False]):
        run = root/f'batch_{index:06d}'/'2026-09-16'
        run.mkdir(parents=True)
        score = run/'score.parquet'
        pl.DataFrame({'factor': ['x'], 'statistical_pass': [True]}).write_parquet(score)
        (run/'summary.json').write_text(json.dumps({'steps': {'N3': {
            'ok': ok, 'result': {'scorecard': str(score)}}}}), encoding='utf-8')
    result = build(config)
    assert len(result['completed_batteries']) == len(result['pending_batteries']) == 1
    assert result['completed_batteries'][0]['statistical_pass'] == 1
    assert result['completed_batteries'][0]['candidate_diagnostics'][0]['validation'] is None


def test_predictive_primary_is_distinct_from_descriptive_pooled_training():
    candidate = {'direction': -1, 'fitness_preprocessing': 'battery_raw_mad3_scale1.4826_v1',
                 'search_objective': 'predictive_priority_v2', 'train': {'mean_ic': -.2},
                 'selection_primary': .015, 'maximum_rank_correlation': .7,
                 'selection_eligible': True, 'selection_reasons': [],
                 'group_statistics': [{'group': 0, 'mean_ic': -.015}]}
    row = {'factor': 'a', 'variant': 'raw', 'direction': -1, 'mean_ic': .01}
    result = candidate_diagnostic(row, candidate, {'first_signal': '2020-01-31', 'last_signal': '2025-12-01'})
    assert result['search_selection']['selection_primary'] == .015
    assert result['train_direction_adjusted']['mean_ic'] == .2
    assert result['training_group_statistics'] == candidate['group_statistics']
    assert 'pooled' in result['training_comparison_basis']
    assert result['training_sample']['sample_first_signal'] == '2020-01-31'
    assert result['training_sample']['sample_last_signal'] == '2025-12-01'


def test_legacy_pooled_fitness_components_remain_unchanged():
    result = search_objective_components({'train': {'mean_ic': -.04},
        'maximum_rank_correlation': .2, 'fitness': -.061, 'complexity': 2})
    assert result['signal_component'] == .04
    assert result['correlation_penalty'] == .1
    assert abs(result['residual_complexity_penalty']-.001) < 1e-12
    assert result['correlation_role'] == 'scalar_fitness_penalty'


def test_objective_summaries_do_not_pool_distinct_primary_definitions():
    result = search_selection_summary([
        {'search_objective': 'predictive_priority_v2', 'selection_primary': .02,
         'train': {'mean_ic': .8}, 'maximum_rank_correlation': .9, 'selection_eligible': True},
        {'search_objective': 'cross_stock_min_ic_v1', 'worst_directional_mean_ic': -.01,
         'train': {'mean_ic': .7}, 'maximum_rank_correlation': .1, 'fitness': -.061}])
    assert result['predictive_priority_v2']['primary']['median'] == .02
    assert result['cross_stock_min_ic_v1']['primary']['median'] == -.01


def test_compact_feedback_keeps_new_search_primary_and_secondary(tmp_path):
    root = tmp_path/'runs'
    config = tmp_path/'policy.toml'
    config.write_text(f'continuous_root = "{root.as_posix()}"', encoding='utf-8')
    run = root/'batch_12'/'2026-09-20'
    (run/'N2').mkdir(parents=True)
    score = run/'score.parquet'
    pl.DataFrame({'factor': ['x'], 'variant': ['raw'], 'statistical_pass': [True]}).write_parquet(score)
    (run/'summary.json').write_text(json.dumps({'steps': {'N3': {'ok': True, 'result': {'scorecard': str(score)}}}}))
    candidate = {'factor_id': 'x', 'search_objective': 'predictive_priority_v2',
                 'selection_primary': .02, 'maximum_rank_correlation': .8, 'selection_eligible': True}
    (run/'N2/search.json').write_text(json.dumps({'candidates': [candidate], 'trials': [candidate]}))
    result = build(config)['completed_batteries'][0]
    # prompt_context retains this compact field when it drops candidate_diagnostics.
    summary = result['search_selection']['predictive_priority_v2']
    assert summary['primary']['median'] == .02
    assert summary['secondary_correlation']['median'] == .8
    assert summary['eligible'] == 1
    assert summary['correlation_role'] == 'secondary_within_registered_ic_band'


def test_prompt_only_diagnoses_recent_completed_and_preserves_full_report(tmp_path, monkeypatch):
    from quant.research.research_feedback import prompt_context
    from quant.research import search_sample_diagnostics
    root = tmp_path/'runs'
    output = tmp_path/'report'
    output.mkdir()
    saved = output/'feedback.json'
    saved.write_text('previous full report')
    config = tmp_path/'policy.toml'
    config.write_text(f'continuous_root = "{root.as_posix()}"\noutput_root = "{output.as_posix()}"')
    calls = []
    monkeypatch.setattr(search_sample_diagnostics, 'batch_diagnostics',
                        lambda run, statistics: calls.append(run.parent.name) or {})
    for index in range(1, 7):
        run = root/f'batch_{index:06d}'/'2026-10-04'
        run.mkdir(parents=True)
        score = run/'score.parquet'
        pl.DataFrame({'factor': [f'x{index}'], 'statistical_pass': [False]}).write_parquet(score)
        (run/'summary.json').write_text(json.dumps({'steps': {'N3': {
            'ok': index != 6, 'result': {'scorecard': str(score)}}}}))
    result = prompt_context(config)
    assert calls == ['batch_000003', 'batch_000004', 'batch_000005']
    assert len(result['pending_batteries']) == 1
    assert 'batch_000006' in result['pending_batteries'][0]['run']
    assert result['completed_comparison_scope'] == 'last_3_completed_batteries'
    assert saved.read_text() == 'previous full report'
    calls.clear()
    assert len(build(config)['completed_batteries']) == 5
    assert len(calls) == 5
