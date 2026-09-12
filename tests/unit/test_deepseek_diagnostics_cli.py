from pathlib import Path
import sys

import pytest

from quant.research import deepseek_diagnostics as module


@pytest.mark.parametrize('options', [
    ['--assessment', 'a.json', 'b.json', 'c.json'],
    ['--assessment', 'a.json', '--assessment', 'b.json', '--assessment', 'c.json'],
])
def test_cli_retains_every_model_assessment(monkeypatch, options):
    seen = []

    def diagnose(**kwargs):
        seen.extend(kwargs['assessments'])
        assert kwargs['cache_path'] == Path('artifacts/research/p7_deepseek_cache.sqlite')
        return {'result': 'dry_run', 'fact_count': 3, 'usd_bound_including_retries': .01}

    monkeypatch.setattr(module, 'run_diagnosis', diagnose)
    monkeypatch.setattr(sys, 'argv', ['diagnosis', '--scorecard', 'score.parquet',
                                    '--output', 'new', *options])
    module.main()
    assert seen == [Path('a.json'), Path('b.json'), Path('c.json')]


@pytest.mark.parametrize('state', ['success', 'budget_exhausted', 'deferred_off_peak', 'retryable', 'unknown'])
def test_diagnostic_live_exit_reports_unsuccessful_requests(monkeypatch, state):
    monkeypatch.setattr(module, 'run_diagnosis', lambda **kwargs: {
        'result': state, 'fact_count': 3, 'usd_bound_including_retries': .01})
    monkeypatch.setattr(sys, 'argv', ['diagnosis', '--scorecard', 'score.parquet',
                                    '--output', 'new', '--execute'])
    if state == 'success':
        module.main()
    else:
        with pytest.raises(SystemExit) as error:
            module.main()
        assert error.value.code == 1
