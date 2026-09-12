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
        return {'result': 'dry_run', 'fact_count': 3, 'usd_bound_including_retries': .01}

    monkeypatch.setattr(module, 'run_diagnosis', diagnose)
    monkeypatch.setattr(sys, 'argv', ['diagnosis', '--scorecard', 'score.parquet',
                                    '--output', 'new', *options])
    module.main()
    assert seen == [Path('a.json'), Path('b.json'), Path('c.json')]
