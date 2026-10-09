import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.research import pead_event_inputs as runner


def test_progress_reader_lock_does_not_abort_research(tmp_path, monkeypatch):
    original = Path.replace
    attempts = []
    monkeypatch.setattr(runner.time, 'sleep', lambda seconds: None)

    def locked(path, destination):
        attempts.append(destination)
        raise PermissionError('Windows reader lock')

    monkeypatch.setattr(Path, 'replace', locked)
    assert runner._write_progress(tmp_path, {'year': 2020}) is False
    assert len(attempts) == 5
    monkeypatch.setattr(Path, 'replace', original)
    assert runner._write_progress(tmp_path, {'year': 2021}) is True
    assert json.loads((tmp_path/'progress.json').read_text()) == {'year': 2021}


def fixture_inputs(tmp_path, monkeypatch):
    manifest = tmp_path/'manifest.json'
    manifest.write_text('{}')
    source = tmp_path/'source.py'
    source.write_text('original')
    monkeypatch.setattr(runner, '_code_files', lambda: {'source.py': source})
    return dict(output=tmp_path, history=pl.DataFrame({'symbol': ['departed']}),
        start=dt.date(2020, 1, 1), end=dt.date(2021, 12, 31), manifest=manifest,
        progress=lambda record: None), source


def test_interrupted_year_resumes_without_recomputing_completed_year(tmp_path, monkeypatch):
    kwargs, _ = fixture_inputs(tmp_path, monkeypatch)
    calls = []
    interrupted = True

    def builder(history, start, end, progress):
        assert history['symbol'].to_list() == ['departed']
        calls.append(start.year)
        if start.year == 2021 and interrupted:
            raise RuntimeError('interrupt')
        return pl.DataFrame({'announcement_date': [start], 'symbol': ['departed']})

    with pytest.raises(RuntimeError, match='interrupt'):
        runner._event_checkpoints(**kwargs, builder=builder)
    assert (tmp_path/'years/2020/summary.json').exists()
    assert not (tmp_path/'years/2021').exists()
    interrupted = False
    result = runner._event_checkpoints(**kwargs, builder=builder)
    assert calls == [2020, 2021, 2021]
    assert result.height == 2


@pytest.mark.parametrize('change', ['input', 'code', 'checkpoint'])
def test_resume_refuses_changed_identity(tmp_path, monkeypatch, change):
    kwargs, source = fixture_inputs(tmp_path, monkeypatch)

    def builder(history, start, end, progress):
        return pl.DataFrame({'announcement_date': [start], 'symbol': ['departed']})

    runner._event_checkpoints(**kwargs, builder=builder)
    if change == 'input':
        kwargs['manifest'].write_text('{"changed":true}')
    elif change == 'code':
        source.write_text('changed')
    else:
        path = tmp_path/'years/2020/summary.json'
        record = json.loads(path.read_text())
        record['sha256'] = 'invalid'
        path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='checkpoint'):
        runner._event_checkpoints(**kwargs, builder=builder)
