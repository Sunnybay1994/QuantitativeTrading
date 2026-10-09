import importlib.util
from pathlib import Path

import pytest
import datetime as dt
import json
import tomllib


def helper():
    from quant.research import n4_correlation
    return n4_correlation


def test_n4_engine_is_only_frozen_for_a_new_batch(tmp_path,monkeypatch):
    from quant.research import continuous_mining as mining
    config=tmp_path/'nightly.toml'
    original='[genetic]\nseed=10\npopulation_size=200\ngenerations=30\nmax_depth=5\n'
    config.write_text(original)
    seen=[]
    def execute(path,**kw):
        seen.append(tomllib.loads(path.read_text()).get('n4_correlation_engine','legacy'))
        if len(seen)==1:
            raise KeyboardInterrupt
        result={'steps':{step:{'ok':True} for step in ['N1','N2','N3','N4','N5']}}
        (kw['run_path']/'summary.json').write_text(json.dumps(result))
        return result
    monkeypatch.setattr(mining.nightly,'execute',execute)
    with pytest.raises(KeyboardInterrupt):
        mining.dispatch(config,tmp_path/'continuous',now=dt.datetime(2026,10,5,9))
    config.write_text('n4_correlation_engine="pairwise_sorted_counts_v1"\n'+original)
    mining.dispatch(config,tmp_path/'continuous',now=dt.datetime(2026,10,5,10))
    mining.dispatch(config,tmp_path/'continuous',now=dt.datetime(2026,10,5,11))
    assert seen==['legacy','legacy','pairwise_sorted_counts_v1']


def test_unversioned_frozen_settings_call_legacy_only(monkeypatch):
    m, calls = helper(), []
    monkeypatch.setattr(m, 'maximum_correlation', lambda *args: pytest.fail('Old run entered new implementation'))
    def legacy(*args):
        calls.append(args)
        return .5123
    settings, frame, controls = {}, object(), ['a', 'b']
    assert m.admission_correlation(frame, 'candidate', controls,
        engine=settings.get('n4_correlation_engine', 'legacy'), legacy=legacy) == .5123
    assert calls == [(frame, 'candidate', controls)]


def test_only_explicit_new_version_calls_optimized(monkeypatch):
    m, calls = helper(), []
    def optimized(*args):
        calls.append(args)
        return .498
    monkeypatch.setattr(m, 'maximum_correlation', optimized)
    frame, controls = object(), ['a']
    assert m.admission_correlation(frame, 'candidate', controls,
        engine='pairwise_sorted_counts_v1', legacy=lambda *args: pytest.fail('New dispatch used legacy')) == .498
    assert calls == [(frame, 'candidate', controls)]


@pytest.mark.parametrize('engine', ['', 'new', None])
def test_unknown_version_never_falls_back_silently(monkeypatch, engine):
    m = helper()
    fail = lambda *args: pytest.fail('Unknown version started computation')
    monkeypatch.setattr(m, 'maximum_correlation', fail)
    with pytest.raises(ValueError, match='Unknown N4'):
        m.admission_correlation(None, 'candidate', [], engine=engine, legacy=fail)
