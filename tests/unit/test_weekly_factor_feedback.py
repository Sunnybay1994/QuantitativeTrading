import json

import polars as pl

from quant.research.weekly_factor_feedback import update


def test_pending_is_not_zero_correlation_and_measured_fraction_uses_real_rows(tmp_path):
    root = tmp_path/'weekly'
    week = root/'2026-09-14'
    week.mkdir(parents=True)
    config = tmp_path/'weekly.toml'
    config.write_text(f'output_root = "{root.as_posix()}"')
    (week/'summary.json').write_text(json.dumps({'completed': True, 'queued_ids': ['a', 'b']}))
    runs = tmp_path/'continuous'
    update(config, runs)
    result = json.loads((week/'evaluation_feedback.json').read_text())
    assert result['maxcorr_lt_0_6_fraction'] is None
    assert result['evaluation_status'] == 'pending'
    n4 = runs/'batch_000001'/'2026-09-15'/'N4'
    n4.mkdir(parents=True)
    pl.DataFrame({'factor': ['a', 'b', 'unrelated'], 'maximum_rank_correlation': [.2, .8, .1]}).write_parquet(
        n4/'admission_scorecard.parquet')
    update(config, runs)
    result = json.loads((week/'evaluation_feedback.json').read_text())
    assert result['maxcorr_lt_0_6_fraction'] == .5
    assert result['evaluation_status'] == 'complete'
    assert result['evaluated_count'] == 2
