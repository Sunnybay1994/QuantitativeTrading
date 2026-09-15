import hashlib
import json

import polars as pl
import pytest

from quant.research.check_text_calibration import check_calibration


def fixture(tmp_path):
    run = tmp_path/'run'
    run.mkdir()
    (run/'run.json').write_text(json.dumps({'dry_run': False, 'prompt_version': 'frozen'}))
    rows = [{'input_id': name, 'reason_text': 'current reason', 'result': state,
             'text_operating_pressure': score, 'operating_pressure_status': status}
            for name, state, score, status in [('ok','success',0,'scored'),
                ('wrong','success',2,'scored'),('failed','retryable',None,'retryable')]]
    pl.from_dicts(rows).write_parquet(run/'scores.parquet')
    expected = {'prompt_version':'frozen','origin':'test fixture','scope':'partial',
        'cases':[{'input_id':name,'reason_sha256':hashlib.sha256(b'current reason').hexdigest(),
                  'checks':{'operating_pressure':[{'status':'scored','score':0}]},
                  'reference_excerpt':'current reason','rationale':'only current period'}
                 for name in ('ok','wrong','failed','missing')]}
    checks = tmp_path/'checks.json'
    checks.write_text(json.dumps(expected))
    return run, checks


def test_wrong_semantics_and_unfinished_calls_are_distinct(tmp_path):
    run, checks = fixture(tmp_path)
    result = check_calibration(run=run, checks=checks, output=tmp_path/'report')
    assert (result['passed'],result['failed'],result['ungraded']) == (1,1,2)
    assert result['observed_pass_fraction'] == result['completion_fraction'] == .5
    assert result['rows'][-1]['result'] == 'missing_record'


@pytest.mark.parametrize('change',['dry','version','reason'])
def test_incompatible_results_rejected(tmp_path, change):
    run, checks = fixture(tmp_path)
    if change == 'reason':
        values = pl.read_parquet(run/'scores.parquet').with_columns(pl.lit('changed').alias('reason_text'))
        values.write_parquet(run/'scores.parquet')
    else:
        (run/'run.json').write_text(json.dumps({'dry_run':change=='dry',
                                               'prompt_version':'other' if change=='version' else 'frozen'}))
    with pytest.raises(ValueError):
        check_calibration(run=run, checks=checks, output=tmp_path/'report')
    assert not (tmp_path/'report').exists()
