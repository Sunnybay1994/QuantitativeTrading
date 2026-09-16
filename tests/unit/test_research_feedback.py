import json

import polars as pl

from quant.research.research_feedback import build, summarize


def test_missing_benchmark_is_independent_of_prediction_failure():
    result = summarize([
        {'factor': 'a', 'statistical_pass': True, 'return_benchmarks_complete': False},
        {'factor': 'b', 'statistical_pass': False, 'return_benchmarks_complete': True,
         'statistical_failures': ['hac_t']},
    ])
    assert result['statistical_pass'] == 1
    assert result['statistical_failure_counts'] == {'hac_t': 1}
    assert result['benchmark_incomplete'] == [{'factor': 'a', 'variant': None}]


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
