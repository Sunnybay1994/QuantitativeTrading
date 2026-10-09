import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from quant.factors.gp_materialized import materialized_plans, evaluate_materialized
from quant.research.gp_expression_identity import VERSION as IDENTITY, canonical_expression
from quant.research.gp_full_context import VERSION, expand, scope_cross_sections


def fixture(tmp_path, terminal='ts_mean(gp_test, 2)'):
    source = tmp_path/'N2/search.json'
    source.parent.mkdir()
    mapping = {'gp_test': 'close / 2'}
    expression = canonical_expression(expand(scope_cross_sections(terminal), mapping), IDENTITY)
    row = {'factor_id':'candidate', 'terminal_expression':terminal, 'expression':expression,
           'direction':1, 'calculation_context':VERSION, 'expression_identity':IDENTITY}
    source.write_text(json.dumps({'candidates':[row]}))
    (source.parent/'terminal_mapping.json').write_text(json.dumps(mapping))
    definition = SimpleNamespace(id='candidate', expr=expression, direction=1, source_ref=str(source))
    root = tmp_path/'data'
    folder = root/'factors/test/year=2020'
    folder.mkdir(parents=True)
    (folder.parent/'definition.json').write_text(json.dumps({'expr':'close / 2'}))
    dates = [dt.date(2020,1,i) for i in range(1,5)]
    panel = pl.DataFrame({'symbol':['A']*4, 'trade_date':dates, 'close':[2.,4.,6.,8.], 'adj_close':[2.,4.,6.,8.]})
    # A published rounded terminal is an observed N2 input, not an invitation to
    # inline its formula using a different floating-point calculation path.
    pl.DataFrame({'ts_code':['A']*4, 'trade_date':dates, 'value':[1.,2.+1e-12,3.,4.]}).write_parquet(folder/'data.parquet')
    config=tmp_path/'refresh.toml'; config.write_text('')
    return definition, panel, root, config


def test_published_terminal_boundary_and_source_immutability(tmp_path):
    d,p,root,cfg=fixture(tmp_path)
    source=Path(d.source_ref)
    before=source.read_bytes()
    result=evaluate_materialized(p,materialized_plans([d]),data_root=root,refresh_config=cfg,artifact_root=tmp_path/'out')
    assert result['candidate'].to_list()==[None,1.5000000000005,2.5000000000005,3.5]
    assert source.read_bytes()==before
    values=root/'factors/test/year=2020/data.parquet'
    pl.read_parquet(values).with_columns((pl.col('value')+1).alias('value')).write_parquet(values)
    with pytest.raises(ValueError,match='source changed'):
        evaluate_materialized(p,materialized_plans([d]),data_root=root,refresh_config=cfg,artifact_root=tmp_path/'out')


def test_mapping_and_direction_must_match_frozen_formula(tmp_path):
    d,_,_,_=fixture(tmp_path)
    d.direction=-1
    with pytest.raises(ValueError,match='frozen definition'):
        materialized_plans([d])
    d.direction=1
    (Path(d.source_ref).parent/'terminal_mapping.json').write_text(json.dumps({'gp_test':'close / 3'}))
    with pytest.raises(ValueError,match='frozen definition'):
        materialized_plans([d])


def test_new_cross_sections_use_full_context_reader(tmp_path,monkeypatch):
    d,p,root,cfg=fixture(tmp_path,'rank(gp_test)')
    full=pl.DataFrame({'symbol':['A','B','C','D'], 'trade_date':[p['trade_date'][0]]*4,
                      'adj_close':[2.,1.,3.,None], 'gp_test':[2.,1.,3.,999.]})
    calls=[]
    class Reader:
        def __init__(self,**kwargs):
            pass
        def read(self,expression,expanded,low,high):
            calls.append(expression)
            return full,expression,'same N2 context'
        def verify_sources(self):
            pass
    monkeypatch.setattr('quant.factors.gp_materialized.FullMarketInputs',Reader)
    result=evaluate_materialized(p.head(1),materialized_plans([d]),data_root=root,refresh_config=cfg,artifact_root=tmp_path/'out')
    assert result['candidate'].item()==.5
    assert len(calls)==1 and 'where(adj_close > 0' in calls[0]
