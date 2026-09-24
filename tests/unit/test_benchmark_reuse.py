import copy
import datetime as dt
import json

import polars as pl
import pytest

from quant.research import benchmark_reuse as reuse


def setup_context(tmp_path):
    paths = ['clean/stock_execution/fixture/'+name+'.parquet'
             for name in ('instruments', 'limits', 'suspensions', 'dividends')]
    paths += ['clean/trade_calendar/market='+market+'/data.parquet' for market in ('SH', 'SZ')]
    paths += ['clean/tushare_bulk/snapshots/base/bar_1d/asset=stock/year=2020/data.parquet',
              'clean/factor_benchmarks/base/members.parquet']
    for name in paths:
        path = tmp_path/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture content')
    config = tmp_path/'refresh.toml'
    config.write_text('stock_snapshot="base"')
    settings = {'data': {'refresh_config': str(config), 'csi800_snapshot': 'base'},
                'run': {'as_of': dt.date(2020, 12, 31)}, 'costs': {'commission': .001}}
    return {'settings': settings, 'plans': {'b': ('benchmark', pl.DataFrame({'weight': [1.]}))},
            'sessions': (dt.date(2020, 12, 31),), 'data_root': tmp_path, 'snapshot': 'fixture'}


@pytest.mark.parametrize('change', ['price', 'limit', 'calendar', 'cost', 'target', 'member', 'increment'])
def test_content_identity_invalidates_each_material_input(tmp_path, change):
    kwargs = setup_context(tmp_path)
    before = reuse.key(reuse.context(**kwargs))
    locations = {'price': 'clean/tushare_bulk/snapshots/base/bar_1d/asset=stock/year=2020/data.parquet',
                 'limit': 'clean/stock_execution/fixture/limits.parquet',
                 'calendar': 'clean/trade_calendar/market=SH/data.parquet',
                 'member': 'clean/factor_benchmarks/base/members.parquet'}
    if change in locations:
        (tmp_path/locations[change]).write_bytes(b'different input')
    elif change == 'cost':
        kwargs['settings']['costs']['commission'] = .002
    elif change == 'target':
        kwargs['plans']['b'] = ('benchmark', pl.DataFrame({'weight': [.5]}))
    else:
        folder = tmp_path/'clean/tushare_incremental/date=2020-12-30'
        folder.mkdir(parents=True)
        (folder/'bar_1d.parquet').write_bytes(b'new increment')
    assert reuse.key(reuse.context(**kwargs)) != before


def test_complete_cost_history_reuses_bytes_and_corruption_misses(tmp_path, monkeypatch):
    from tests.unit.test_factor_cost_checkpoint import setup_run
    from quant.research.factor_battery_costs import run_cost_plans
    _, _, kwargs = setup_run(monkeypatch, tmp_path/'source')
    result = run_cost_plans(**kwargs)
    context = {'version': 1, 'fixture': 'actual account replay'}
    root = tmp_path/'cache'
    reuse.publish(root, context, kwargs['output'], kwargs['plans'], kwargs['settings'])
    copy_path = tmp_path/'copy'
    assert reuse.lookup(root, context, copy_path)['rows'] == result['rows']
    for original in kwargs['output'].rglob('*.parquet'):
        assert original.read_bytes() == (copy_path/original.relative_to(kwargs['output'])).read_bytes()
    receipt = json.loads((copy_path/'benchmark_reuse.json').read_text())
    assert receipt['reused'] and receipt['saved_variant_cost_replays'] == 3
    partial = copy.deepcopy(result)
    partial['rows'] = partial['rows'][:1]
    (kwargs['output']/'summary.json').write_text(json.dumps(partial))
    assert reuse.lookup(root, context, tmp_path/'another') is None
    with pytest.raises(ValueError, match='Incomplete benchmark'):
        reuse.publish(root, context, kwargs['output'], kwargs['plans'], kwargs['settings'])


def test_partial_run_is_never_available(tmp_path):
    (tmp_path/'cache').mkdir()
    assert reuse.lookup(tmp_path/'cache', {'cutoff': '2026-08-31'}, tmp_path/'output') is None
    assert not (tmp_path/'output').exists()


def test_independent_b16_edit_does_not_invalidate_but_engine_edit_does(tmp_path, monkeypatch):
    kwargs=setup_context(tmp_path)
    before=reuse.context(**kwargs)
    original=reuse.digest
    def unrelated(path):
        if path.name in ('b16_forward.py','etf_quote_paper.py','market_clock_baseline.py'):
            return 'changed-independent-code'
        return original(path)
    monkeypatch.setattr(reuse,'digest',unrelated)
    assert reuse.context(**kwargs)==before
    def engine(path):
        return 'changed-fill-engine' if path.name=='daily_simulator.py' else original(path)
    monkeypatch.setattr(reuse,'digest',engine)
    assert reuse.context(**kwargs)!=before


@pytest.mark.parametrize('change',['none','data','targets','sessions','settings','engine','original_manifest'])
def test_scoped_migration_keeps_original_and_refuses_material_change(tmp_path,change):
    current={'version':2,'settings':{'cost':1},'sessions':['2026-09-01'],
             'targets':{'a':'frozen'},'files':{'data':'abc','engine':'def'}}
    old={**copy.deepcopy(current),'version':1}
    old['files']['b16_forward.py']='old-independent'
    path=tmp_path/'benchmark_inputs.json';path.write_text(json.dumps(old))
    before=path.read_bytes()
    with pytest.raises(ValueError,match='receipt'):
        reuse.require_compatible_resume(path,current)
    (tmp_path/'benchmark_scope_compatibility.json').write_text(json.dumps(dict(
        original_manifest_sha256=reuse.digest(path),compatible_context_key=reuse.key(current),
        all_retained_data_settings_sessions_targets_equal=True)))
    if change in ('data','engine'):current['files'][change]='changed'
    elif change=='targets':current['targets']['a']='changed'
    elif change=='sessions':current['sessions'].append('2026-09-02')
    elif change=='settings':current['settings']['cost']=2
    elif change=='original_manifest':path.write_text(json.dumps({**old,'version':0}))
    if change=='none':reuse.require_compatible_resume(path,current)
    else:
        with pytest.raises(ValueError,match='receipt'):reuse.require_compatible_resume(path,current)
    if change!='original_manifest':assert path.read_bytes()==before


def test_new_dependency_on_excluded_module_refuses_scope(tmp_path,monkeypatch):
    from pathlib import Path
    root=Path(reuse.__file__).resolve().parents[1]
    monkeypatch.setattr(reuse,'stock_replay_sources',lambda _:{root/'execution/b16_forward.py'})
    with pytest.raises(ValueError,match='became a stock replay dependency'):
        reuse.context(**setup_context(tmp_path))


@pytest.mark.parametrize('contents', ['{interrupted publication', '{"context":{"fixture":1}}'])
def test_broken_cache_index_is_a_miss_not_a_research_failure(tmp_path, contents):
    root = tmp_path/'cache'
    root.mkdir()
    context = {'fixture': 1}
    (root/f'{reuse.key(context)}.json').write_text(contents)
    assert reuse.lookup(root, context, tmp_path/'new') is None
    assert not (tmp_path/'new').exists()
