import datetime as dt
import json
from pathlib import Path
import tomllib
from types import SimpleNamespace

import pytest

from quant.research import continuous_mining as mining


@pytest.mark.parametrize('permanent',[False,True])
def test_publication_retries_only_directory_rename_and_keeps_frozen_recipe(tmp_path,monkeypatch,permanent):
    config=tmp_path/'nightly.toml'
    original='[genetic]\nseed=10\npopulation_size=200\ngenerations=30\nmax_depth=5\n'
    config.write_text(original)
    root=tmp_path/'continuous';batch=root/'batch_000001'
    observed=[];denials=[];pauses=[]
    rename=Path.rename
    def publish(source,target):
        if Path(target)==batch and (permanent or len(denials)<2):
            denials.append((source/'2026-10-04/config.toml').read_bytes())
            raise PermissionError('temporary Windows directory reader')
        return rename(source,target)
    def execute(path,**kwargs):
        observed.append(tomllib.loads(path.read_text())['genetic'])
        result={'steps':{step:{'ok':True} for step in ('N1','N2','N3','N4','N5')}}
        (kwargs['run_path']/'summary.json').write_text(json.dumps(result))
        return result
    monkeypatch.setattr(Path,'rename',publish)
    monkeypatch.setattr(mining,'time',SimpleNamespace(sleep=pauses.append))
    monkeypatch.setattr(mining.nightly,'execute',execute)
    if permanent:
        with pytest.raises(PermissionError):mining.dispatch(config,root,now=dt.datetime(2026,10,4,15))
        assert not batch.exists() and observed==[]
        assert (root/'batch_000001.2026-10-04.pending/2026-10-04/config.toml').is_file()
        assert len(denials)==11 and pauses==[.1]*10
    else:
        result=mining.dispatch(config,root,now=dt.datetime(2026,10,4,15))
        assert result['state']=='completed' and len(observed)==1
        assert observed[0]['seed']==11
        assert (observed[0]['population_size'],observed[0]['generations'],observed[0]['max_depth'])==(200,30,5)
        assert len(denials)==2 and pauses==[.1,.1]
        assert not list(root.glob('*.pending'))
    assert len(set(denials))==1 and config.read_text()==original


def test_publication_cannot_replace_existing_batch_or_escape_root(tmp_path):
    root=tmp_path/'continuous';root.mkdir()
    staging=root/'batch_000002.pending';staging.mkdir()
    batch=root/'batch_000002';batch.mkdir()
    marker=batch/'frozen.txt';marker.write_text('keep existing batch')
    with pytest.raises(FileExistsError):mining._publish_batch(staging,batch,root)
    assert marker.read_text()=='keep existing batch' and staging.is_dir()
    with pytest.raises(ValueError,match='escapes'):
        mining._publish_batch(staging,tmp_path/'outside',root)
