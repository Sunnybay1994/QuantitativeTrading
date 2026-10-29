import datetime as dt
import json

import polars as pl
import pytest

from quant.research.q10_matched_comparison import COSTS, common_window, compare_histories
from quant.research.factor_battery_cost_report import REQUIRED_BENCHMARKS
from quant.research.q10_sizing import _q10_2x_and_mdd


def test_unified_cli_forwards_saved_comparison_arguments(monkeypatch):
    from quant import cli
    seen=[]
    monkeypatch.setattr(cli,'_delegate',lambda module,args:seen.append((module,args)) or 0)
    args=['--compare-saved','saved-run','--receipt','new-receipt']
    assert cli.main(['research','q10-sizing',*args]) == 0
    assert seen == [('quant.research.q10_sizing',args)]


def histories():
    dates=[dt.date(2020,1,day) for day in (2,3,6,7)]
    a=pl.DataFrame({'date':dates,'unit_nav':[1.,2.,2.2,2.4],'market_value':[0.,1.,1.,0.]})
    b=pl.DataFrame({'date':dates,'unit_nav':[1.,1.,1.1,1.2],'market_value':[0.,0.,1.,0.]})
    return {cost:(a,b) for cost in COSTS}


def test_common_window_keeps_prior_wealth_and_subsequent_cash():
    source=histories()
    index=source[1.][1].select('date','unit_nav')
    result=compare_histories(source,{name:index for name in REQUIRED_BENCHMARKS})
    assert result['start']=='2020-01-06'
    assert result['sessions']==2
    for row in result['rows']:
        assert row['treatment']['starting_unit_nav']==2.
        assert row['treatment']['total_return']==pytest.approx(.2)
        assert row['q10']['total_return']==pytest.approx(.2)
        assert row['vs_q10_excess_pp']==pytest.approx(0.)


def test_missing_session_not_silently_intersected():
    source=histories()
    a,b=source[2.]
    source[2.]=(a.filter(pl.col('date')!=dt.date(2020,1,6)),b)
    with pytest.raises(ValueError,match='dates differ'):
        common_window(source)


def test_all_costs_and_holding_evidence_required():
    source=histories()
    source.pop(.5)
    with pytest.raises(ValueError,match='three cost'):
        common_window(source)
    source=histories()
    a,b=source[2.]
    source[2.]=(a.with_columns(pl.lit(0.).alias('market_value')),b)
    with pytest.raises(ValueError,match='holding evidence'):
        common_window(source)


def test_fixed_assessment_cannot_be_borrowed_for_different_window(tmp_path):
    payload={'rows':[{'variant':'budgeted','cost_multiplier':2.,
        'first_date':'2019-01-02','last_date':'2026-08-31'}]}
    (tmp_path/'assessment.json').write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='dates differ'):
        _q10_2x_and_mdd(tmp_path,start=dt.date(2017,2,3),end=dt.date(2026,8,31))


@pytest.mark.parametrize('different_anchor', [False, True])
def test_saved_nav_loader_keeps_anchors_and_never_changes_source_bytes(tmp_path,monkeypatch,different_anchor):
    import hashlib
    from quant.research.q10_matched_comparison import compare_saved
    from quant.data import equal_weight_index
    source = histories()
    treatment, control = tmp_path/'treatment',tmp_path/'control'
    for root,index in [(treatment,0),(control,1)]:
        root.mkdir(); (root/'summary.json').write_text('{}')
        for cost in COSTS:
            frame = source[cost][index]
            if different_anchor and index == 1:
                frame = frame.filter(pl.col('date') != dt.date(2020,1,3))
            folder=root/'budgeted'/f'cost_{cost:g}'/'2020'; folder.mkdir(parents=True)
            frame.write_parquet(folder/'nav.parquet')
            pl.DataFrame(schema={'date':pl.Date}).write_parquet(folder/'trades.parquet')
    before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob('*.parquet')}
    queries=[]
    def indexes(**kwargs):
        queries.append((kwargs['start'],kwargs['end']))
        return {name:source[1.][1].select('date','unit_nav') for name in REQUIRED_BENCHMARKS}
    monkeypatch.setattr(equal_weight_index,'load_return_benchmarks',indexes)
    if different_anchor:
        with pytest.raises(ValueError,match='anchor dates differ'):
            compare_saved(treatment,control,end=dt.date(2020,1,7),benchmark_config=tmp_path/'unused',data_root=tmp_path)
        assert not queries
    else:
        result=compare_saved(treatment,control,end=dt.date(2020,1,7),benchmark_config=tmp_path/'unused',data_root=tmp_path)
        assert queries == [(dt.date(2020,1,3),dt.date(2020,1,7))]
        assert result['start']=='2020-01-06' and result['sessions']==2
        assert all(row['vs_q10_excess_pp']==pytest.approx(0.) for row in result['rows'])
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==h for p,h in before.items())


@pytest.mark.parametrize('problem', ['none', 'missing_report', 'changed_nav'])
def test_saved_correction_preserves_measurements_and_conclusions(tmp_path,monkeypatch,problem):
    from quant.research import q10_matched_comparison as module
    root=tmp_path/'saved'
    folder=root/'M2'
    folder.mkdir(parents=True)
    (root/'config.toml').write_text('q10_control="unused"')
    assessment={'rows':[{'variant':'budgeted','last_date':'2020-01-07','cagr':.12}],
        'assessments':{'budgeted':{'vs_q10_2x_excess_pp':-9.,'conclusion':'RESEARCH_ONLY'}}}
    cell={'vs_q10_2x_excess_pp':-9.,'conclusion':'RESEARCH_ONLY','double_cost_excess':.1}
    (folder/'assessment.json').write_text(json.dumps(assessment))
    (folder/'cell_result.json').write_text(json.dumps(cell))
    (folder/'report.md').write_text('vs Q10 Δpp=-9. MDD2=-.2\nvs Q10 同窗 2× 超额差 = -9. pp',encoding='utf-8')
    (root/'summary.json').write_text(json.dumps({'members':[{'id':'M2',**cell}]}))
    old_comparison = folder/'matched_q10_comparison.json'
    old_comparison.write_text('{"original_comparison":true}')
    source=histories()
    result=compare_histories(source,{name:source[1.][1].select('date','unit_nav') for name in REQUIRED_BENCHMARKS})
    monkeypatch.setattr(module,'compare_saved',lambda *args,**kwargs:result)
    receipt=tmp_path/'receipt'
    if problem == 'missing_report':
        (folder/'report.md').unlink()
        before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
        with pytest.raises(ValueError,match='complete artifacts'):
            module.repair_saved(root,receipt=receipt,data_root=tmp_path)
        assert all(p.read_bytes()==data for p,data in before.items())
        assert not receipt.exists()
        return
    if problem == 'changed_nav':
        nav=folder/'budgeted/cost_1/2020/nav.parquet'; nav.parent.mkdir(parents=True)
        nav.write_bytes(b'original frozen NAV')
        before={p:p.read_bytes() for p in root.rglob('*') if p.is_file() and p!=nav}
        def changed(*args,**kwargs):
            nav.write_bytes(b'concurrent replacement')
            return result
        monkeypatch.setattr(module,'compare_saved',changed)
        with pytest.raises(ValueError,match='NAV changed during comparison'):
            module.repair_saved(root,receipt=receipt,data_root=tmp_path)
        assert all(p.read_bytes()==data for p,data in before.items())
        assert not receipt.exists()
        return
    module.repair_saved(root,receipt=receipt,data_root=tmp_path)
    after=json.loads((folder/'assessment.json').read_text())
    assert after['rows']==assessment['rows']
    assert after['assessments']['budgeted']['conclusion']=='RESEARCH_ONLY'
    assert json.loads((receipt/'before/M2/cell_result.json').read_text())==cell
    assert json.loads((receipt/'before/M2/matched_q10_comparison.json').read_text())=={'original_comparison':True}
    assert json.loads((folder/'cell_result.json').read_text())['double_cost_excess']==.1
    assert 'Δpp=0.0' in (folder/'report.md').read_text(encoding='utf-8')
    with pytest.raises(ValueError,match='new correction'):
        module.repair_saved(root,receipt=receipt,data_root=tmp_path)
