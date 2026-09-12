import datetime as dt
import json

import pytest

from quant.research import monthly_market_brief as module


@pytest.mark.parametrize('known,expected_read', [(dt.date(2026, 7, 30), False), (dt.date(2026, 7, 31), True)])
def test_outcomes_read_only_after_maturity_with_explicit_snapshot(tmp_path, monkeypatch, known, expected_read):
    issue = tmp_path/'issue'
    (issue/'brief').mkdir(parents=True)
    (issue/'brief/brief.json').write_text(json.dumps({'target_date': '2026-07-31',
        'status': 'success', 'dry_run': False}))
    calls = []
    def reader(**kwargs):
        calls.append(kwargs)
        assert kwargs['inputs'] == issue/'inputs'
        assert kwargs['config'] == tmp_path/'extended.toml'
        kwargs['output'].mkdir(parents=True)
        (kwargs['output']/'realized.json').write_text('{}')
    def scorer(**kwargs):
        assert kwargs['brief'] == issue/'brief'
        assert (kwargs['outcomes'] is not None) == expected_read
        if kwargs['outcomes'] is not None:
            assert kwargs['outcomes'].is_file()
        return {'status': 'scored' if expected_read else 'pending'}
    monkeypatch.setattr('quant.data.monthly_brief_inputs.realized', reader)
    monkeypatch.setattr(module, 'score', scorer)
    result = module.score_issue(issue=issue, output=tmp_path/'out', known_through=known,
                                benchmark_config=tmp_path/'extended.toml')
    assert bool(calls) == expected_read
    assert result['status'] == ('scored' if expected_read else 'pending')


def test_existing_issue_refused_before_any_preparation(tmp_path, monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError('Must not read or overwrite an existing issue')
    monkeypatch.setattr('quant.data.monthly_brief_inputs.prepare', forbidden)
    with pytest.raises(FileExistsError):
        module.run_issue(benchmark_config=tmp_path/'config.toml', output=tmp_path,
                         as_of=dt.date(2026, 6, 30), target_date=dt.date(2026, 7, 31))
