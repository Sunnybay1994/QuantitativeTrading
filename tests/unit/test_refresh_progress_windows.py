import json
from pathlib import Path

import pytest

from quant.data.refresh_progress import RefreshProgress


@pytest.mark.parametrize('when', ['before_action', 'after_action'])
def test_windows_reader_conflict_retries_without_repeating_data_step(tmp_path,monkeypatch,when):
    target=tmp_path/'refresh_progress.json'
    original=Path.replace
    failures=[]
    calls=[]
    def replace(path,destination):
        selected = when == 'before_action' or json.loads(path.read_text(encoding='utf-8'))['status'] == 'complete'
        if destination==target and selected and len(failures)<3:
            failures.append(path)
            raise PermissionError('Windows reader holds destination')
        return original(path,destination)
    monkeypatch.setattr(Path,'replace',replace)
    monkeypatch.setattr('quant.data.realtime_store.time.sleep',lambda seconds:None)
    progress=RefreshProgress(target)
    result=progress.run('financials',lambda:calls.append('once') or {'rows':5})
    assert result=={'rows':5} and calls==['once']
    assert len(failures)==3
    assert json.loads(target.read_text(encoding='utf-8'))['stages']['financials']=='complete'
    assert not list(tmp_path.glob('*.tmp'))


def test_real_data_failure_still_propagates_after_progress_retries(tmp_path,monkeypatch):
    monkeypatch.setattr('quant.data.realtime_store.time.sleep',lambda seconds:None)
    progress=RefreshProgress(tmp_path/'progress.json')
    def fail():
        raise ValueError('real input failure')
    with pytest.raises(ValueError,match='real input failure'):
        progress.run('financials',fail)
    saved=json.loads(progress.path.read_text(encoding='utf-8'))
    assert saved['status']=='failed' and saved['error_type']=='ValueError'
