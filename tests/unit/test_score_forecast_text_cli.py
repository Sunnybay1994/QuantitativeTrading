import json
import sys

import pytest

from quant.research import score_forecast_text as module


@pytest.mark.parametrize('state,execute,code', [
    ('success', True, 0), ('dry_run', False, 0), ('unknown', True, 1),
    ('budget_exhausted', True, 1), ('deferred_off_peak', True, 1),
    ('retryable', True, 1), ('failed', True, 1),
])
def test_scoring_cli_keeps_partial_results_but_signals_unfinished_requests(monkeypatch, capsys, state, execute, code):
    summary = {'success': 2, 'missing_text': 3, 'same_day_conflict': 1,
               'input_too_long': 1, 'not_selected': 5}
    summary[state] = summary.get(state, 0) + 1
    monkeypatch.setattr(module, 'run_batch', lambda **kwargs: {
        'plan': {}, 'summary': summary, 'deferred_until': [], 'requests_this_run': 0})
    monkeypatch.setattr(sys, 'argv', ['score', '--input', 'source', '--output', 'new']
                        + (['--execute'] if execute else []))
    if code:
        with pytest.raises(SystemExit) as error:
            module.main()
        assert error.value.code == code
    else:
        module.main()
    assert json.loads(capsys.readouterr().out)['summary'] == summary
