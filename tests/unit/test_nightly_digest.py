from pathlib import Path

import pytest

from quant.research.nightly import digest


@pytest.mark.parametrize('state,expected', [
    ({'ok': False, 'error': 'Worker exceeded 221 seconds'}, '入库判定未完成'),
    ({'ok': True, 'result': {'skipped': True}}, '入库判定未完成'),
    ({'ok': True, 'result': {'admitted': 0, 'rejected': 20}}, '通过 0，拒绝 20'),
])
def test_digest_distinguishes_pending_admission(tmp_path: Path, monkeypatch, state, expected):
    monkeypatch.setattr('quant.factors.library.load_library', lambda path: [])
    run = tmp_path / '2026-09-15'
    run.mkdir()
    summary = {'library_before': 0, 'steps': {'N4': state}}
    digest({'library': str(tmp_path)}, run, summary, rewrite_leaderboard=False)
    for name in ('digest.md', 'report.md'):
        report = (run / name).read_text(encoding='utf-8')
        assert expected in report
        assert '通过 0，拒绝 0' not in report
