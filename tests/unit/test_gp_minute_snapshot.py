from pathlib import Path

import polars as pl
import pytest

from tests.unit.test_gp_minute_snapshot_files import source


def test_full_context_routes_expanded_minute_inputs_to_the_frozen_root(tmp_path,monkeypatch):
    import datetime as dt
    from quant.data.gp_context_inputs import FullMarketInputs
    from quant.factors import compute
    root, output = tmp_path/'live',tmp_path/'context'; output.mkdir()
    original = source(root)
    guard = FullMarketInputs.__new__(FullMarketInputs)
    guard.root, guard.output = root,output
    guard.sources_path = output/'source_manifest.json'; guard.sources,guard.stamps = {},{}
    guard.freeze_minutes,guard.minute_root = True,None
    guard.source_settings = {}; guard.mapping = {'gp_min':'ts_mean(minute_realized_vol,20)'}
    guard.sessions = (dt.date(2020,1,2),dt.date(2020,1,3)); guard.config = tmp_path/'refresh.toml'
    guard.metrics = {'expanded_context_reads':0}
    panel=pl.DataFrame({'symbol':['000001.SZ'],'trade_date':[guard.sessions[0]],'close':[10.]})
    guard._base = lambda *args: (panel,panel)
    guard.verify_sources = lambda: [guard.track(Path(name)) for name in guard.sources]
    seen=[]

    def attach(panel,bars,**kwargs):
        assert kwargs['data_root'] == root
        pinned = kwargs['minute_data_root']/original.relative_to(root)
        seen.append(pl.read_parquet(pinned)['value'].item())
        return panel

    monkeypatch.setattr(compute,'attach_expression_inputs',attach)
    guard.read('gp_min','ts_mean(minute_realized_vol,20)',*guard.sessions)
    next_file=original.with_suffix('.next.parquet')
    pl.DataFrame({'value':[99.]}).write_parquet(next_file); next_file.replace(original)
    guard.read('gp_min','ts_mean(minute_realized_vol,20)',*guard.sessions)
    assert seen == [1.,1.]
    assert not any(Path(name)==original.resolve() for name in guard.sources)
    assert any('minute_inputs' in name for name in guard.sources)


@pytest.mark.parametrize('message',[
    'Frozen GP minute source checksum changed: snapshot.parquet',
    'Frozen GP minute source inventory changed',
    'Frozen GP context source changed: legacy minute inputs lack a frozen snapshot',
])
def test_source_failures_abort_search_instead_of_becoming_low_fitness_trials(tmp_path,message):
    import datetime as dt
    from types import SimpleNamespace
    from quant.research import nightly_gp
    from quant.research.gp_full_context import VERSION
    panel=pl.DataFrame({'symbol':['000001.SZ'],'trade_date':[dt.date(2020,1,2)],'gp_a':[1.]})
    labels=panel.select('symbol','trade_date').with_columns(pl.lit(.01).alias('label'))

    def fail(expression): raise ValueError(message)

    evaluator=SimpleNamespace(identity='fixture',verify_sources=lambda:None,evaluate=fail)
    settings=dict(seed=7,population_size=2,generations=0,max_depth=5,complexity_penalty=.0005,
                  calculation_context=VERSION)
    with pytest.raises(ValueError,match='Frozen GP'):
        nightly_gp.search(panel,labels,{'gp_a':'adj_close'},settings,tmp_path,
                          family='fixture',context_evaluator=evaluator)
    assert not (tmp_path/'search_checkpoint.json').exists()
    assert not (tmp_path/'fitness_cache.json').exists()
