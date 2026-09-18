import json

import polars as pl

from quant.research.research_feedback import build, summarize, candidate_diagnostic


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
