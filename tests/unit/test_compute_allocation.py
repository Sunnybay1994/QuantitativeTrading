import datetime as dt
import json
from pathlib import Path

import pytest

from quant.research import compute_allocation as allocation


def fixture(tmp_path):
    old={'id':'ngp_old','expr':'adj_close','family':'nightly_price_volume','direction':1,'source_ref':'frozen/search.json'}
    path=tmp_path/'allocation.toml'
    path.write_text('auto_trade=false\ngp_weekday=5\nmaximum_gp_batches_per_week=1\n'
        'monthly_three_models=false\nweekly_candidate_generation=false\n'
        'registered_candidates=["registered"]\n[ngp_backlog]\nngp_old="'+allocation.definition_hash(old)+'"\n')
    spec=allocation.apply({'queue':str(tmp_path/'queue'),'output_root':str(tmp_path/'nightly'),
        'scheduler_day':'2026-11-05'},path)
    return spec,old,path


def write_definition(path,row):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(f'{key}={json.dumps(value)}\n' for key,value in row.items()),encoding='utf-8')


def test_saturday_claim_allows_one_new_batch_each_week_and_resumes_same_batch(tmp_path):
    spec,_,_=fixture(tmp_path)
    first,second=tmp_path/'first/N2',tmp_path/'second/N2'
    assert not allocation.gp_permission(spec,first,claim=True)['allowed']
    assert not (tmp_path/'nightly/gp_weekly').exists()
    spec['scheduler_day']='2026-11-07'
    assert allocation.gp_permission(spec,first,claim=True)['allowed']
    assert allocation.gp_permission(spec,first,claim=True)['allowed']
    assert not allocation.gp_permission(spec,second,claim=True)['allowed']
    spec['scheduler_day']='2026-11-14'
    assert allocation.gp_permission(spec,second,claim=True)['allowed']
    assert len(list((tmp_path/'nightly/gp_weekly').glob('*.json')))==2
    first.mkdir(parents=True)
    (first/'search_checkpoint.json').write_text('{"population":"preserved"}')
    spec['scheduler_day']='2026-11-09'
    assert allocation.gp_permission(spec,first)['resume_existing']


def test_only_preregistered_members_and_exact_original_backlog_are_eligible(tmp_path):
    spec,old,_=fixture(tmp_path)
    assert allocation.allowed(old,spec)
    assert allocation.allowed({**old,'id':'registered'},spec)
    assert not allocation.allowed({**old,'id':'ngp_new'},spec)
    assert not allocation.allowed({**old,'id':'intel_new','family':'preregistered_label'},spec)
    with pytest.raises(ValueError,match='Frozen C1 backlog'):
        allocation.allowed({**old,'direction':-1},spec)


def test_ingest_leaves_unregistered_other_session_file_untouched(tmp_path):
    from quant.research.nightly_steps import ingest
    spec,old,_=fixture(tmp_path)
    queue=Path(spec['queue'])
    write_definition(queue/'old.toml',old)
    write_definition(queue/'new.toml',{**old,'id':'intel_new'})
    original=(queue/'new.toml').read_bytes()
    run=tmp_path/'run';run.mkdir()
    result=ingest(spec,run)
    assert result['queued_candidates']==1
    assert (queue/'new.toml').read_bytes()==original
    assert [p.stem for p in (run/'candidates').glob('*.toml')]==['ngp_old']


def test_completed_rejected_gp_never_returns_from_cached_n2_library(tmp_path):
    from quant.research.nightly_steps import preserve_gp_candidates
    spec,old,_=fixture(tmp_path)
    run=tmp_path/'run';(run/'N2/library').mkdir(parents=True)
    write_definition(run/'N2/library/old.toml',old)
    write_definition(run/'N2/library/new.toml',{**old,'id':'ngp_new'})
    assert preserve_gp_candidates(spec,run,{})==1
    processing=Path(spec['queue'])/'processing'
    assert [p.name for p in processing.glob('*.toml')]==['old.toml']
    completed=processing/'completed/2026-11-05_ngp_old.toml'
    write_definition(completed,old)
    (processing/'old.toml').unlink()
    assert preserve_gp_candidates(spec,run,{})==0
    assert not list(processing.glob('*.toml'))
    assert not allocation.may_enqueue(old,spec)


def test_live_limits_apply_to_old_frozen_run_without_rewriting_its_request(tmp_path,monkeypatch):
    from quant.research import nightly,nightly_steps
    from quant.factors import library
    spec,_,policy=fixture(tmp_path)
    frozen=tmp_path/'run/2026-10-31/config.toml';frozen.parent.mkdir(parents=True)
    frozen.write_text('output_root='+json.dumps(str(tmp_path/'nightly'))+'\nlibrary="unused"\n'
        'weekday_hours=6\nweekend_hours=20\nminimum_free_gb=0\n')
    original=frozen.read_bytes()
    monkeypatch.setattr(library,'load_library',lambda _:[])
    monkeypatch.setattr(nightly_steps,'resolve_settings',lambda settings,_:settings)
    monkeypatch.setattr(nightly,'digest',lambda *_:None)
    monkeypatch.setattr(nightly,'work_order',lambda *_:('N2',))
    monkeypatch.setattr(nightly.subprocess,'Popen',lambda *_a,**_k:pytest.fail('Thursday started a new GP'))
    result=nightly.execute(frozen,run_path=frozen.parent,now=dt.datetime(2026,11,5,9),allocation_config=policy)
    assert result['steps']['N2']['result']['skipped']
    assert not result['steps']['N2']['result']['evaluated']
    assert not (frozen.parent/'N2/result.json').exists()
    assert frozen.read_bytes()==original


def test_monthly_disables_all_three_predictors_but_preserves_admission_controls(tmp_path,monkeypatch):
    from quant.research import nightly_monthly as monthly
    from quant.data import nightly_genetic_inputs
    from quant.factors import compute
    from quant.research import run_factor_pipeline,q10_plus_admitted
    from quant.reporting import experiment_registry
    spec,_,_=fixture(tmp_path)
    output=tmp_path/'2026-11';output.mkdir()
    calls=[]
    monkeypatch.setattr(monthly,'_freeze',lambda *_:{'as_of':'2026-10-30','data_root':str(tmp_path),
        'execution_snapshot':'fixed','history_start':'2010-01-01','workers':1})
    monkeypatch.setattr(nightly_genetic_inputs,'require_execution_coverage',lambda *_:None)
    monkeypatch.setattr(compute,'run',lambda **_:calls.append('compute_controls'))
    monkeypatch.setattr(run_factor_pipeline,'run_pipeline',lambda **_:{'cost_failures':[],
        'pending_external_runs':[],'scorecard_path':'reference_scorecard'})
    monkeypatch.setattr(experiment_registry,'register_run',lambda _:calls.append('register_controls'))
    monkeypatch.setattr(monthly,'_predict',lambda *_:pytest.fail('Disabled models predicted'))
    monkeypatch.setattr(monthly,'_constructions',lambda *_:pytest.fail('Disabled models replayed'))
    monkeypatch.setattr(q10_plus_admitted,'run_for_month',lambda **_:{'conclusions':{'budgeted':'REJECTED'}})
    result=monthly._run_month(spec,output)
    assert result['disabled_methods']==['equal_z','positive_mean_ic','lightgbm']
    assert list(result['methods'])==['q10_plus_admitted']
    assert calls==['compute_controls','register_controls']
    assert '关闭不是模型检验通过' in (output/'report.md').read_text(encoding='utf-8')


def test_dispatch_passes_live_limits_and_never_calls_generic_weekly_generator(tmp_path,monkeypatch):
    from quant.research import continuous_mining,weekly_factor_candidates
    spec,old,policy=fixture(tmp_path)
    write_definition(Path(spec['queue'])/'processing/ngp_old.toml',old)
    config=tmp_path/'nightly.toml'
    config.write_text('compute_allocation_config='+json.dumps(str(policy))+'\n'
        'queue='+json.dumps(spec['queue'])+'\noutput_root='+json.dumps(spec['output_root'])+'\n'
        'weekly_candidates_config="should_not_run.toml"\n[genetic]\nseed=1\n')
    monkeypatch.setattr(weekly_factor_candidates,'run',lambda *_a,**_k:pytest.fail('C1 replenished generic candidates'))
    observed=[]
    def execute(frozen,**kwargs):
        observed.append(kwargs['allocation_config'])
        return {'steps':{step:{'ok':True} for step in ('N1','N2','N3','N4','N5')}}
    monkeypatch.setattr(continuous_mining.nightly,'execute',execute)
    result=continuous_mining.dispatch(config,tmp_path/'continuous',now=dt.datetime(2026,11,5,9))
    assert result['state']=='completed'
    assert result['weekly_candidates']['state']=='disabled_by_C1'
    assert observed==[policy]


def test_nightly_search_cannot_replenish_new_gp_even_after_a_real_search(tmp_path,monkeypatch):
    from quant.research import run_genetic_factor_search,nightly_gp
    spec,old,_=fixture(tmp_path)
    spec['scheduler_day']='2026-11-07'
    output=tmp_path/'run/2026-11-07/N2';(output/'library').mkdir(parents=True)
    write_definition(output/'library/new.toml',{**old,'id':'ngp_new'})
    monkeypatch.setattr(nightly_gp,'run',lambda *_:{'candidates':1})
    result=run_genetic_factor_search.run_nightly(spec,output)
    assert result['candidates']==1 # Search output is retained, not relabelled as a battery result.
    assert not list((Path(spec['queue'])/'processing').glob('*.toml'))
