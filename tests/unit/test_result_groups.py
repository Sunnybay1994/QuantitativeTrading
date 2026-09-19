import datetime as dt
import hashlib
import json
import os

import polars as pl
import pytest

from quant.reporting.result_groups import annotate


def saved_nav(path, *, values=(1., 1.1), dates=None):
    frame = pl.DataFrame({'date': dates or [dt.date(2025, 1, 2), dt.date(2025, 1, 3)],
                          'unit_nav': values, 'equity': [100., 110.],
                          'cash': [0., 0.], 'market_value': [100., 110.]})
    frame.write_parquet(path)
    return frame


def digest(path):
    from quant.reporting.result_groups import _digest
    stat = path.stat()
    return _digest(str(path), stat.st_size, stat.st_mtime_ns, stat.st_dev, stat.st_ino)


def test_identical_files_reuse_only_validated_digest(tmp_path, monkeypatch):
    from quant.reporting import result_groups
    first, second = tmp_path/'a.parquet', tmp_path/'b.parquet'
    frame = saved_nav(first)
    second.write_bytes(first.read_bytes())
    result_groups._CONTENT_DIGESTS.clear()
    calls = []
    original = pl.read_parquet

    def read(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(pl, 'read_parquet', read)
    expected = hashlib.sha256(frame.write_json().encode()).hexdigest()
    assert digest(first) == digest(second) == expected
    assert len(calls) == 1


@pytest.mark.parametrize('values', [(1., None), (1., float('nan')), (1., float('inf'))])
def test_invalid_histories_are_never_added_to_content_cache(tmp_path, values):
    from quant.reporting import result_groups
    path = tmp_path/'invalid.parquet'
    saved_nav(path, values=values)
    content = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='Invalid account history'):
        digest(path)
    assert content not in result_groups._CONTENT_DIGESTS


def test_content_reuse_preserves_semantic_order_and_changed_nav(tmp_path):
    first, reversed_path, changed = (tmp_path/name for name in ('a.parquet', 'reversed.parquet', 'changed.parquet'))
    frame = saved_nav(first)
    frame.reverse().write_parquet(reversed_path)
    saved_nav(changed, values=(1., 1.2))
    assert digest(first) == digest(reversed_path)
    assert digest(first) != digest(changed)


@pytest.mark.parametrize('empty', [False, True])
def test_duplicate_dates_and_empty_nav_remain_invalid(tmp_path, empty):
    path = tmp_path/'invalid_dates.parquet'
    frame = saved_nav(path, dates=[dt.date(2025, 1, 2)]*2)
    if empty:
        frame.head(0).write_parquet(path)
    with pytest.raises(ValueError, match='Incomplete account history'):
        digest(path)


def test_digest_content_cache_is_bounded(tmp_path, monkeypatch):
    from quant.reporting import result_groups
    monkeypatch.setattr(result_groups, '_CONTENT_LIMIT', 2)
    result_groups._CONTENT_DIGESTS.clear()
    for index in range(3):
        path = tmp_path/f'{index}.parquet'
        saved_nav(path, values=(1., 1.1+index))
        digest(path)
    assert len(result_groups._CONTENT_DIGESTS) == 2


def group_rows(root):
    rows = []
    for name in ('a', 'b'):
        run = root/'artifacts'/name
        for cost in ('0.5', '1', '2'):
            folder = run/'control'/f'cost_{cost}'/'2025'
            folder.mkdir(parents=True)
            saved_nav(folder/'nav.parquet')
        evidence = run/'periods_1x'/hashlib.sha256(b'control').hexdigest()[:16]
        evidence.mkdir(parents=True)
        (evidence/'sources.json').write_text(json.dumps({'nav': [str(run/'control/cost_1/2025/nav.parquet')]}))
        rows.append({'variant': 'control', 'report_path': str(run/'report.md'),
                     'cagr_1x': 0., 'sharpe_1x': 0., 'mdd_1x': -.1, 'turnover_1x': 1.})
    return rows


def test_persistent_annotations_survive_empty_process_caches(tmp_path, monkeypatch):
    from quant.reporting import result_groups
    rows = group_rows(tmp_path)
    expected = result_groups.cached_annotations(rows, tmp_path)
    result_groups._digest.cache_clear()
    result_groups._CONTENT_DIGESTS.clear()

    def unexpected(*args, **kwargs):
        raise AssertionError('Source validation should be reused only after dependency checks')

    monkeypatch.setattr(result_groups, 'annotate', unexpected)
    assert result_groups.cached_annotations([dict(row) for row in rows], tmp_path) == expected


@pytest.mark.parametrize('change', ['nav', 'missing_nav', 'manifest', 'version', 'corrupt'])
def test_persistent_annotations_revalidate_changed_sources_and_invalid_cache(tmp_path, monkeypatch, change):
    from quant.reporting import result_groups
    rows = group_rows(tmp_path)
    result_groups.cached_annotations(rows, tmp_path)
    cache = tmp_path/'artifacts/reports/dashboard/result_groups.json'
    target = tmp_path/'artifacts/b/control/cost_2/2025/nav.parquet'
    if change == 'nav':
        saved_nav(target, values=(1., 1.3))
    elif change == 'missing_nav':
        target.unlink()
    elif change == 'manifest':
        next((tmp_path/'artifacts/b/periods_1x').glob('*/sources.json')).write_text('{"nav": []}')
    elif change == 'version':
        saved = json.loads(cache.read_text(encoding='utf-8'))
        saved['version'] = -1
        cache.write_text(json.dumps(saved), encoding='utf-8')
    else:
        cache.write_text('{"incomplete":', encoding='utf-8')
    original = result_groups.annotate
    calls = []

    def annotate(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(result_groups, 'annotate', annotate)
    result = result_groups.cached_annotations(rows, tmp_path)
    assert calls == [True]
    if change in ('missing_nav', 'manifest'):
        assert result[1]['result_group'] is None
    elif change == 'nav':
        assert result[1]['result_group'] != result[0]['result_group']


def test_registry_change_invalidates_persistent_annotations(tmp_path, monkeypatch):
    from quant.reporting import result_groups
    rows = group_rows(tmp_path)
    result_groups.cached_annotations(rows, tmp_path)
    rows[1]['cagr_1x'] = .1
    result = result_groups.cached_annotations(rows, tmp_path)
    assert all(row['result_group'] is None for row in result)


def test_same_size_and_mtime_replacement_invalidates_both_cache_layers(tmp_path):
    from quant.reporting import result_groups
    rows = group_rows(tmp_path)
    target = tmp_path/'artifacts/b/control/cost_2/2025/nav.parquet'
    frame = pl.read_parquet(target)
    frame.write_parquet(target, compression='uncompressed')
    result = result_groups.cached_annotations(rows, tmp_path)
    assert result[0]['result_group'] == result[1]['result_group']
    prior = target.stat()
    replacement = target.with_name('replacement.parquet')
    frame.with_columns(pl.Series('unit_nav', [1., 1.3])).write_parquet(
        replacement, compression='uncompressed')
    assert replacement.stat().st_size == prior.st_size
    os.utime(replacement, ns=(prior.st_atime_ns, prior.st_mtime_ns))
    replacement.replace(target)
    updated = target.stat()
    assert (updated.st_dev, updated.st_ino) != (prior.st_dev, prior.st_ino)
    assert (updated.st_size, updated.st_mtime_ns) == (prior.st_size, prior.st_mtime_ns)
    result = result_groups.cached_annotations(rows, tmp_path)
    assert result[0]['result_group'] != result[1]['result_group']


def test_optional_cache_write_failure_does_not_discard_verified_groups(tmp_path, monkeypatch):
    from quant.reporting import result_groups
    rows = group_rows(tmp_path)

    def fail(*args, **kwargs):
        raise OSError('Cache directory unavailable')

    monkeypatch.setattr(result_groups.tempfile, 'NamedTemporaryFile', fail)
    result = result_groups.cached_annotations(rows, tmp_path)
    assert result[0]['result_group'] == result[1]['result_group']
    assert result[0]['group_kind'] == '公共对照／相同净值'


def test_groups_require_all_cost_histories_and_preserve_conclusions(tmp_path):
    rows=[]
    for name,values in [('a',[1.1,1.0]),('b',[1.1,1.0]),('c',[1.2,1.0])]:
        run=tmp_path/'artifacts'/name
        for cost in ['0.5','1','2']:
            folder=run/'control'/('cost_'+cost)/'2025'
            folder.mkdir(parents=True)
            pl.DataFrame({'date':[dt.date(2025,1,2),dt.date(2025,1,3)],'unit_nav':values,
                'equity':[v*100 for v in values],'cash':[0.,0.],'market_value':[v*100 for v in values]}).write_parquet(folder/'nav.parquet')
        key=hashlib.sha256(b'control').hexdigest()[:16]
        evidence=run/'periods_1x'/key
        evidence.mkdir(parents=True)
        (evidence/'sources.json').write_text(json.dumps({'nav':[str(run/'control/cost_1/2025/nav.parquet')]}))
        rows.append(dict(variant='control',report_path=str(run/'report.md'),conclusion=name))
    rows.append(dict(variant='unknown',report_path=str(tmp_path/'missing/report.md'),conclusion='REJECTED'))
    for row in rows:
        row.update(cagr_1x=0.,sharpe_1x=0.,mdd_1x=-.1,turnover_1x=1.)
    result=annotate(rows,tmp_path)
    assert result[0]['result_group']==result[1]['result_group']
    assert result[2]['result_group']!=result[0]['result_group']
    assert result[3]['result_group'] is None
    assert [r['conclusion'] for r in result]==['a','b','c','REJECTED']
    assert result[0]['group_kind']=='公共对照／相同净值'
    (tmp_path/'artifacts/b/control/cost_2/2025/nav.parquet').unlink()
    assert annotate(rows,tmp_path)[1]['result_group'] is None
