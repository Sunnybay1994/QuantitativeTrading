import json

import polars as pl
import pytest

from quant.data import gp_minute_snapshot as snapshot


def source(root, symbol='000001.SZ', provider='baostock', value=1.):
    path = root/f'clean/bar_intraday/freq=5m/source={provider}/symbol={symbol}/data.parquet'
    path.parent.mkdir(parents=True,exist_ok=True)
    pl.DataFrame({'value':[value]}).write_parquet(path)
    return path


@pytest.mark.parametrize('copy_fallback',[False,True])
def test_collector_replacement_and_new_symbols_cannot_change_frozen_reader(tmp_path,monkeypatch,copy_fallback):
    root, output = tmp_path/'live',tmp_path/'frozen'
    original = source(root)
    if copy_fallback:
        def no_link(*args): raise OSError('different volume')
        monkeypatch.setattr(snapshot.os,'link',no_link)
    frozen, paths = snapshot.freeze(root,output)
    pinned = frozen/original.relative_to(root)
    assert pl.read_parquet(pinned)['value'].item() == 1.
    marker = (output/'completed.json').read_bytes()
    replacement = original.with_suffix('.replacement.parquet')
    pl.DataFrame({'value':[2.]}).write_parquet(replacement); replacement.replace(original)
    source(root,symbol='000002.SZ',value=3.)
    source(root,provider='tdx',value=4.)
    again, again_paths = snapshot.freeze(root,output)
    assert frozen == again and paths == again_paths
    assert (output/'completed.json').read_bytes() == marker
    assert pl.read_parquet(pinned)['value'].item() == 1.
    assert len(list((output/'clean').rglob('data.parquet'))) == 1
    assert pl.read_parquet(original)['value'].item() == 2.


@pytest.mark.parametrize('change',['bytes','missing','added'])
def test_snapshot_damage_is_never_repaired_from_new_live_bytes(tmp_path,change):
    root, output = tmp_path/'live',tmp_path/'frozen'
    original = source(root)
    snapshot.freeze(root,output)
    pinned = output/original.relative_to(root)
    if change == 'bytes': pinned.write_bytes(b'broken')
    elif change == 'missing': pinned.unlink()
    else: source(output,symbol='000002.SZ')
    with pytest.raises(ValueError,match='Frozen GP minute source'):
        snapshot.freeze(root,output)


def test_initially_absent_sources_stay_absent(tmp_path):
    root, output = tmp_path/'live',tmp_path/'frozen'
    snapshot.freeze(root,output)
    source(root)
    _, paths = snapshot.freeze(root,output)
    assert paths == [output/'completed.json']
    assert json.loads(paths[0].read_text())['files'] == []


def test_interrupted_freeze_cannot_repin_uncopied_changed_source(tmp_path,monkeypatch):
    root, output = tmp_path/'live',tmp_path/'frozen'
    original = source(root)
    actual_hash = snapshot._hash
    monkeypatch.setattr(snapshot,'_hash',lambda p: (_ for _ in ()).throw(RuntimeError('interrupted')))
    with pytest.raises(RuntimeError): snapshot.freeze(root,output)
    pinned = output/original.relative_to(root)
    pinned.unlink()  # Simulate an interrupted copy without its target bytes.
    replacement = original.with_suffix('.next.parquet')
    pl.DataFrame({'value':[99.]}).write_parquet(replacement); replacement.replace(original)
    monkeypatch.setattr(snapshot,'_hash',actual_hash)
    with pytest.raises(ValueError,match='source changed'):
        snapshot.freeze(root,output)
    assert not (output/'completed.json').exists()
