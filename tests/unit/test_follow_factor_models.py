import datetime as dt
import json
import shutil
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.research import follow_factor_models as follow

END = dt.date(2020,12,31)
TEMPLATE = Path('configs/models/p4_annual_walk_forward_20260911.toml')
MEASUREMENT = Path('configs/data/return_benchmarks_q1b_20260912.toml')


def fixture(tmp_path, monkeypatch, *, layout='statistics', missing_cost=False):
    root=tmp_path/'evaluation'
    statistics=root/layout
    statistics.mkdir(parents=True)
    battery='variants=["raw"]\n[run]\nas_of=2020-12-31\nselected="all"\n[portfolio]\ncost_multipliers=[0.5,1.0,2.0]\n'
    (statistics/'battery.toml').write_text(battery)
    (statistics/'summary.json').write_text(json.dumps({'as_of':str(END),'factors':2}))
    pl.DataFrame({'factor':['loser','winner'],'variant':['raw','raw']}).write_parquet(statistics/'statistics.parquet')
    for factor in ('loser','winner'):
        folder=statistics/'factors'/factor
        folder.mkdir(parents=True)
        for name in ('monthly_ic.parquet','monthly_groups.parquet','monthly_scores.parquet'):
            (folder/name).touch()
    for year in range(2014,2021):
        folder=statistics/'inputs'/str(year)
        folder.mkdir(parents=True)
        for name in ('universe.parquet','monthly_labels.parquet'):
            (folder/name).touch()
    benchmarks=root/'benchmarks'
    benchmarks.mkdir()
    (benchmarks/'summary.json').write_text('{"execution_snapshot":"fixture"}')
    for factor in ('loser','winner'):
        if missing_cost and factor=='loser':
            continue
        folder=root/'costs'/('attempt_001' if layout=='training' else '')/factor
        folder.mkdir(parents=True)
        (folder/'battery.toml').write_text(battery+f'\n[cost_replay]\nfactor="{factor}"\nexecution_snapshot="fixture"\n')
        (folder/'summary.json').write_text(json.dumps({'rows':[{'variant':'raw','cost_multiplier':c,'last_date':str(END)} for c in (.5,1.,2.)]}))
        for c in (.5,1.,2.):
            annual=folder/'raw'/f'cost_{c:g}'/'2020'
            annual.mkdir(parents=True)
            pl.DataFrame({'date':[END],'unit_nav':[1.]}).write_parquet(annual/'nav.parquet')
            pl.DataFrame({'date':[]},schema={'date':pl.Date}).write_parquet(annual/'trades.parquet')
    calls=[]
    monkeypatch.setattr(follow,'run_pipeline',lambda **kw: calls.append(kw) or {'model_results_ready':True})
    return dict(evaluation=root,model_config=TEMPLATE,measurement_config=MEASUREMENT,output=tmp_path/'models'),calls


@pytest.mark.parametrize('layout',['statistics','training'])
def test_all_factors_enter_prefix_and_template_thresholds_stay_fixed(tmp_path,monkeypatch,layout):
    kwargs,calls=fixture(tmp_path,monkeypatch,layout=layout)
    result=follow.follow_factor_models(**kwargs)
    assert result['candidate_factors']==['loser','winner']
    assert result['completed_cost_factors']==['loser','winner']
    assert result['model_results_ready'] and len(calls)==1
    model=tomllib.loads((kwargs['output']/'model.toml').read_text(encoding='utf-8'))
    original=tomllib.loads(TEMPLATE.read_text(encoding='utf-8'))
    assert model['selection']==original['selection'] and model['admission']==original['admission']
    assert model['walk_forward']['test_end']==END
    assert len(model['research']['cost_runs'])==2
    assert not list(Path(model['research']['cost_root']).iterdir())
    assert 'retrospective' in model['research']['historical_evidence']
    assert calls[0]['measurement_config'].read_bytes()==MEASUREMENT.read_bytes()


def test_missing_full_period_loser_cost_does_not_shrink_family(tmp_path,monkeypatch):
    kwargs,calls=fixture(tmp_path,monkeypatch,missing_cost=True)
    result=follow.follow_factor_models(**kwargs)
    assert not calls and not result['model_results_ready']
    assert result['candidate_factors']==['loser','winner']
    assert result['missing_inputs']==['costs:loser']
    assert (kwargs['output']/'model.toml').is_file()


def test_missing_statistical_file_stops_before_models(tmp_path,monkeypatch):
    kwargs,calls=fixture(tmp_path,monkeypatch)
    (kwargs['evaluation']/'statistics/factors/loser/monthly_scores.parquet').unlink()
    result=follow.follow_factor_models(**kwargs)
    assert not calls and 'statistics:loser/monthly_scores.parquet' in result['missing_inputs']


def test_duplicate_cost_factor_cannot_be_chosen_by_performance(tmp_path,monkeypatch):
    kwargs,_=fixture(tmp_path,monkeypatch)
    root=kwargs['evaluation']/'costs'
    shutil.copytree(root/'loser',root/'another_loser')
    with pytest.raises(ValueError,match='duplicate'):
        follow.follow_factor_models(**kwargs)


def test_bad_measurement_and_pre_history_test_window_reject(tmp_path,monkeypatch):
    kwargs,_=fixture(tmp_path,monkeypatch)
    bad=tmp_path/'measurement.toml'
    bad.write_text('[account_benchmarks]\nname="cash-constrained"\n')
    with pytest.raises(ValueError,match='return-index'):
        follow.follow_factor_models(**{**kwargs,'measurement_config':bad})
    template=tmp_path/'template.toml'
    template.write_text(TEMPLATE.read_text(encoding='utf-8').replace('test_start = 2015-01-01','test_start = 2021-01-01'),encoding='utf-8')
    with pytest.raises(ValueError,match='ends before'):
        follow.follow_factor_models(**{**kwargs,'model_config':template})


def test_runtime_failure_preserves_bound_config_and_reason(tmp_path,monkeypatch):
    kwargs,_=fixture(tmp_path,monkeypatch)
    def fail(**kw):
        raise ValueError('annual evidence missing')
    monkeypatch.setattr(follow,'run_pipeline',fail)
    with pytest.raises(ValueError,match='annual evidence'):
        follow.follow_factor_models(**kwargs)
    saved=json.loads((kwargs['output']/'summary.json').read_text())
    assert saved['failure_reason']=='annual evidence missing'
    assert not saved['model_results_ready']
    assert (kwargs['output']/'report.md').is_file()


def test_search_optional_hook_runs_after_existing_batch(tmp_path,monkeypatch):
    from tests.unit.test_run_factor_search import fake_stages,CONFIG
    from quant.research import run_factor_search
    fake_stages(monkeypatch)
    calls=[]
    monkeypatch.setattr(follow,'follow_factor_models',lambda **kw: calls.append(kw) or {'model_results_ready':False})
    result=run_factor_search.run(config=CONFIG,output=tmp_path/'search',model_config=TEMPLATE,measurement_config=MEASUREMENT)
    assert result['models']['model_results_ready'] is False
    assert calls[0]['evaluation']==tmp_path/'search'
    assert calls[0]['model_config']==TEMPLATE

def test_raw_paper_result_is_diagnostic_only_for_adaptive_candidates(tmp_path,monkeypatch):
    kwargs,_=fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(follow,'run_pipeline',lambda **kw: {'model_results_ready':True,
        'conclusions':{'equal_z':'PAPER_CANDIDATE'}})
    result=follow.follow_factor_models(**kwargs)
    assert result['conclusion']=='RESEARCH_ONLY'
    assert result['promotion_allowed'] is False
    assert result['raw_model_conclusions']=={'equal_z':'PAPER_CANDIDATE'}


def test_genetic_evaluation_hook_uses_complete_evaluation_directory(tmp_path,monkeypatch):
    from quant.factors import compute
    from quant.research import run_factor_pipeline,run_genetic_factor_search
    root=tmp_path/'genetic'
    root.mkdir()
    content='[dates]\nstart=2010-01-01\ntest_end=2020-12-31\n[evaluation]\nrefresh_config="fixture"\nbattery_config="fixture"\nexecution_snapshot="fixture"\nworkers=1\nreturn_benchmark_config="fixture"\n'
    config=tmp_path/'config.toml'
    config.write_text(content)
    (root/'config.toml').write_text(content)
    monkeypatch.setattr(compute,'run',lambda **kw: {})
    monkeypatch.setattr(run_factor_pipeline,'run_pipeline',lambda **kw: {'scorecard':{'admitted_rows':0}})
    calls=[]
    monkeypatch.setattr(follow,'follow_factor_models',lambda **kw: calls.append(kw) or {'conclusion':'RESEARCH_ONLY'})
    result=run_genetic_factor_search.evaluate_selected(config=config,output=root,data_root=tmp_path,
        model_config=TEMPLATE,measurement_config=MEASUREMENT)
    assert result['models']['conclusion']=='RESEARCH_ONLY'
    assert calls[0]['evaluation']==root/'evaluation'
    assert calls[0]['model_config']==TEMPLATE

def test_duplicated_cost_scenario_is_not_complete(tmp_path,monkeypatch):
    kwargs,calls=fixture(tmp_path,monkeypatch)
    path=kwargs['evaluation']/'costs/loser/summary.json'
    saved=json.loads(path.read_text())
    saved['rows'].append(saved['rows'][0])
    path.write_text(json.dumps(saved))
    result=follow.follow_factor_models(**kwargs)
    assert not calls
    assert 'costs:loser:incomplete_variants_or_costs' in result['missing_inputs']


def test_statistical_summary_count_prevents_silent_factor_omission(tmp_path,monkeypatch):
    kwargs,_=fixture(tmp_path,monkeypatch)
    path=kwargs['evaluation']/'statistics/statistics.parquet'
    pl.read_parquet(path).filter(pl.col('factor')=='winner').write_parquet(path)
    with pytest.raises(ValueError,match='Incomplete statistical factor family'):
        follow.follow_factor_models(**kwargs)
