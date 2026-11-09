"""Synthetic wiring evidence only: none of these fixtures certifies real 96-month coverage."""
import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl
import pytest

from quant.factors import compute
from quant.research import nightly_steps as steps
from quant.research import sue_preliminary_pipeline as pipeline
from quant.research import sue_preliminary_r5_inputs as inputs
from quant.research.sue_preliminary_s4 import normalize
from tests.unit.test_sue_preliminary_r5 import income_chain, native


@pytest.fixture
def frozen(tmp_path):
    config=tmp_path/'preregistered.toml'
    config.write_bytes(pipeline.CONFIG.read_bytes())
    chain=income_chain()
    point=chain.tail(1)['n_income_attr_p'].item()
    chain=chain.head(-1).with_columns(
        pl.col('n_income_attr_p').alias('n_income'),
        (pl.col('end_date')+dt.timedelta(days=60)).alias('available_date'),
        (pl.col('end_date')+dt.timedelta(days=60)).alias('ann_date'),
        (pl.col('end_date')+dt.timedelta(days=60)).alias('f_ann_date'),
        pl.lit('1').alias('update_flag'),pl.lit('fixture').alias('source'))
    chain.write_parquet(tmp_path/'income.parquet')
    observations=normalize(native(ann_date='20260103',end_date='20251231',
        parent_net_profit_min_10000cny=point/10000,parent_net_profit_max_10000cny=point/10000,
        observed_at=dt.datetime(2026,1,5,tzinfo=dt.UTC),available_at=dt.datetime(2026,1,5,tzinfo=dt.UTC)), 'forecast')
    observations.write_parquet(tmp_path/'observations.parquet')
    receipt=tmp_path/'qualification.json'
    row=dict(status='QUALIFIED_INPUTS',observed_at='2026-11-08T16:00:00+00:00',
        registered_at=tomllib.loads(config.read_text())['registered_at'],config=str(config),
        config_sha256=inputs.sha(config),finite_signal_months=96,
        source_data_root=str(tmp_path/'source'),income=str(tmp_path/'income.parquet'),
        observations=str(tmp_path/'observations.parquet'),
        files={str(p):inputs.sha(p) for p in (config,tmp_path/'income.parquet',tmp_path/'observations.parquet')})
    receipt.write_text(json.dumps(row))
    return receipt


def definition(receipt):
    return dict(id=inputs.IDENTIFIER,expr=inputs.IDENTIFIER,family=inputs.FAMILY,direction=1,
                source_ref=inputs.PREFIX+inputs.sha(receipt)+':'+str(receipt.resolve()))


def write_definition(path,row):
    path.write_text(''.join(f'{k}={json.dumps(v)}\n' for k,v in row.items()))


def test_compute_explicit_input_and_strict_time_adapter(frozen,tmp_path):
    panel=pl.DataFrame(dict(symbol=['600000.SH']*2,trade_date=[dt.date(2026,1,5),dt.date(2026,1,30)]))
    args=dict(expressions=(inputs.IDENTIFIER,),data_root=tmp_path,refresh_config=Path('unused'),
              read_start=dt.date(2026,1,5),read_end=dt.date(2026,1,30),sessions=())
    with pytest.raises(ValueError,match='opt-in'):
        compute.attach_expression_inputs(panel,panel,**args)
    result=compute.attach_expression_inputs(panel,panel,r5_input_receipt=frozen,**args)
    assert result[inputs.IDENTIFIER][0] is None
    assert result[inputs.IDENTIFIER][1] is not None
    library=tmp_path/'candidates';library.mkdir()
    write_definition(library/'r5.toml',definition(frozen))
    with pytest.raises(ValueError,match='original factor panels'):
        compute.run(data_root=tmp_path/'source',refresh_config=Path('unused'),library=library,
            selected='all',start=dt.date(2010,1,1),end=dt.date(2026,10,30),artifact_root=tmp_path,
            r5_input_receipt=frozen)


def test_receipt_hash_registration_and_definition_cannot_be_rebound(frozen):
    row=definition(frozen)
    inputs.definition_receipt(row,{'r5_input_receipt':str(frozen)})
    with pytest.raises(ValueError,match='opt-in'):
        inputs.definition_receipt(row,{})
    row['source_ref']=row['source_ref'].replace(inputs.sha(frozen),'0'*64)
    with pytest.raises(ValueError,match='SHA'):
        inputs.definition_receipt(row,{'r5_input_receipt':str(frozen)})
    saved=json.loads(frozen.read_text());saved['observed_at']='2026-11-01T00:00:00+00:00'
    frozen.write_text(json.dumps(saved))
    with pytest.raises(ValueError,match='post-registration'):
        inputs.load_receipt(frozen)


def test_copied_configuration_cannot_backdate_actual_registration(frozen):
    row=json.loads(frozen.read_text())
    config=Path(row['config'])
    config.write_text(config.read_text().replace('2026-11-08T23:05:11+08:00','2010-01-01T00:00:00+08:00'))
    row['config_sha256']=inputs.sha(config)
    row['registered_at']='2010-01-01T00:00:00+08:00'
    row['files'][str(config)]=inputs.sha(config)
    frozen.write_text(json.dumps(row))
    with pytest.raises(ValueError,match='no backdated registration'):
        inputs.load_receipt(frozen)


@pytest.mark.parametrize('value',[None,float('inf'),float('-inf'),float('nan')])
def test_present_but_nonfinite_control_cannot_pass(value):
    panel=pl.DataFrame({c:[float(i)] for i,c in enumerate(inputs.CONTROLS)}).with_columns(
        pl.lit(value,dtype=pl.Float64).alias(inputs.CONTROLS[-1]))
    result=inputs.check_controls(panel,lambda *a:pytest.fail('Empty control reached statistics'))
    assert not result['passed'] and result['reason']=='r5_frozen_controls_nonfinite'


def test_one_control_is_not_the_frozen_ten():
    result=inputs.check_controls(pl.DataFrame({inputs.CONTROLS[0]:[1.]}),lambda *a:pytest.fail('Partial controls accepted'))
    assert not result['passed'] and len(result['missing'])==9


@pytest.mark.parametrize('value',[float('nan'),float('inf'),float('-inf'),None,2.49,2.5])
def test_nw_t_must_be_finite_and_use_all_ten(value):
    seen=[]
    def evaluate(panel,candidate,controls,direction):
        seen.append(controls)
        return dict(months=96,newey_west_t=value)
    panel=pl.DataFrame({c:[float(i)] for i,c in enumerate(inputs.CONTROLS)})
    result=inputs.check_controls(panel,evaluate)
    assert seen==[list(inputs.CONTROLS)]
    assert result['passed'] is (value==2.5)


def test_current_unqualified_inputs_never_enqueue_or_run_battery(tmp_path,monkeypatch):
    from quant.research.sue_preliminary_audit import run as real_audit
    def audit(**kw):
        data=tmp_path/'source'
        folder=data/'clean/trade_calendar/market=SH';folder.mkdir(parents=True)
        pl.DataFrame(dict(date=[dt.date(2026,9,30),dt.date(2026,10,30),dt.date(2026,11,30)],
                          is_open=[True]*3)).write_parquet(folder/'data.parquet')
        kw['data_root']=data
        return real_audit(**kw)
    monkeypatch.setattr(pipeline.audit,'run',audit)
    monkeypatch.setattr(steps,'ingest',lambda *a:pytest.fail('Unqualified data entered queue'))
    result=pipeline.run(output=tmp_path/'result',execute=True)
    assert result['status']=='SAMPLE_INSUFFICIENT' and result['finite_signal_months']==0
    assert not result['enqueued'] and not result['completed_battery']
    assert result['formal_months'] is result['incremental_nw_t'] is result['admission'] is None
    assert not (tmp_path/'result/queue').exists()


def test_n1_n3_n4_binding_and_original_battery_call(frozen,tmp_path,monkeypatch):
    from quant.data import nightly_genetic_inputs, monthly_open_inputs
    from quant.reporting import experiment_registry
    from quant.research import run_factor_pipeline, gp_context_alignment
    run=tmp_path/'run';run.mkdir()
    for name in ('N3','N4'):(run/name).mkdir()
    queue=tmp_path/'queue';queue.mkdir()
    write_definition(queue/'r5.toml',definition(frozen))
    library=tmp_path/'library';library.mkdir()
    write_definition(library/'reference.toml',dict(id='pit_sue8_context_v2',expr='adj_close',family='price',direction=1,source_ref='fixture'))
    reference=tmp_path/'reference';reference.mkdir()
    (reference/'battery.toml').write_text('[run]\nas_of=2026-10-30\n')
    refcard=tmp_path/'reference.parquet'
    pl.DataFrame(dict(factor=['pit_sue8_context_v2'],variant=['raw'],factor_admitted=[True])).write_parquet(refcard)
    settings=dict(r5_input_receipt=str(frozen),r5_reference_data_root=str(tmp_path/'source'),
        queue=str(queue),library=str(library),batch_root=str(tmp_path/'batches'),data_root=str(tmp_path/'isolated'),
        refresh_config='configs/data/refresh.toml',as_of=dt.date(2026,10,30),history_start=dt.date(2010,1,1),
        training_end=dt.date(2025,12,31),battery_config='configs/factors/battery.toml',workers=1,
        reference_statistics=str(reference),reference_scorecard=str(refcard),rejected_root=str(tmp_path/'rejected'),
        execution_snapshot='fixture',return_benchmark_config='configs/data/q10_forward_return_benchmarks_v1.toml',
        compute_allocation={'registered_candidates':['sue_prelim']})
    assert steps.ingest(settings,run)['queued_candidates']==1
    unrelated=Path(settings['batch_root'])/'old_unfinished/library';unrelated.mkdir(parents=True)
    write_definition(unrelated/'other.toml',dict(id='other',expr='adj_close',family='price',direction=1,source_ref='old'))
    monkeypatch.setattr(monthly_open_inputs,'evaluation_source_identity',lambda settings:b'fixture')
    monkeypatch.setattr(nightly_genetic_inputs,'require_execution_coverage',lambda *a:None)
    calls=[]
    def compute_call(**kw):
        assert kw['r5_input_receipt']==frozen
        assert [d.id for d in steps.load_library(kw['library'])]==[inputs.IDENTIFIER]
        calls.append('compute')
    monkeypatch.setattr(compute,'run',compute_call)
    monkeypatch.setattr(gp_context_alignment,'verify_new_gp_values',lambda *a,**kw:None)
    def battery(**kw):
        assert kw['config']==Path('configs/factors/battery.toml')
        spec=tomllib.loads(kw['config'].read_text())
        assert spec['variants']==['raw','size_industry_neutral']
        assert spec['portfolio']['cost_multipliers']==[.5,1.,2.]
        assert 'existing_runs' not in kw
        folder=kw['output']/'statistics/factors'/inputs.IDENTIFIER;folder.mkdir(parents=True)
        pl.DataFrame(dict(symbol=['600000.SH'],trade_date=[dt.date(2026,10,30)],raw=[1.],
                          size_industry_neutral=[1.])).write_parquet(folder/'monthly_scores.parquet')
        card=kw['output']/'scorecard.parquet'
        pl.DataFrame(dict(factor=[inputs.IDENTIFIER]*2,variant=spec['variants'],factor_admitted=[False]*2)).write_parquet(card)
        calls.append('existing battery; cost engines mocked')
        return dict(cost_failures=[],scorecard_path=str(card))
    monkeypatch.setattr(run_factor_pipeline,'run_pipeline',battery)
    monkeypatch.setattr(experiment_registry,'register_run',lambda *a:None)
    result=steps.evaluate(settings,run)
    assert Path(result['batch'])!=unrelated.parent
    (run/'N3/result.json').write_text(json.dumps(result))
    keys=pl.DataFrame(dict(symbol=['600000.SH'],trade_date=[dt.date(2026,10,30)]))
    monkeypatch.setattr(nightly_genetic_inputs,'admitted_controls',lambda *a:(keys,['pit_sue8_context_v2']))
    def panel(**kw):
        assert set(inputs.CONTROLS)<=set(kw['factors'])
        assert kw['data_root']==tmp_path/'source'
        return keys.with_columns(pl.lit(dt.date(2026,10,30)).alias('label_exit_date'),pl.lit(.1).alias('label'),
                                *[pl.lit(1.).alias(c) for c in inputs.CONTROLS])
    monkeypatch.setattr(nightly_genetic_inputs,'read_raw_monthly',panel)
    monkeypatch.setattr(steps,'maximum_correlation',lambda *a:0.)
    card=Path(result['scorecard'])
    original_card=card.read_bytes()
    pl.read_parquet(card).with_columns(pl.lit('other_completed').alias('factor')).write_parquet(card)
    with pytest.raises(ValueError,match='not another completed result'):
        steps.admit(settings,run)
    card.write_bytes(original_card)
    admitted=steps.admit(settings,run)
    assert admitted['admitted']==0 and admitted['rejected']==1
    assert calls==['compute','existing battery; cost engines mocked']
    score=pl.read_parquet(run/'N4/admission_scorecard.parquet').row(0,named=True)
    assert len(score['family_controls']['controls_used'])==10


def test_n4_cannot_use_completed_other_batch_for_r5(frozen,tmp_path):
    run=tmp_path/'run/N3';run.mkdir(parents=True)
    batch=tmp_path/'other';batch.mkdir()
    (batch/'settings.json').write_text(json.dumps(dict(as_of='2026-10-30',training_end='2025-12-31',history_start='2010-01-01')))
    (run/'result.json').write_text(json.dumps(dict(evaluated=1,batch=str(batch))))
    with pytest.raises(ValueError,match='Another completed batch'):
        steps.admit({'r5_input_receipt':str(frozen)},run.parent)


def test_96_point_months_do_not_replace_96_finite_formula_months(frozen,tmp_path,monkeypatch):
    saved=json.loads(frozen.read_text())
    data=tmp_path/'data';source=data/'clean/tushare_financials/fixture';source.mkdir(parents=True)
    (source/'income.parquet').write_bytes(Path(saved['income']).read_bytes())
    refresh=tmp_path/'refresh.toml';refresh.write_text('financial_snapshot="fixture"\n')
    def point_audit(**kw):
        out=kw['output'];out.mkdir()
        (out/'observations.parquet').write_bytes(Path(saved['observations']).read_bytes())
        dates=[dt.date(y,m,28) for y in range(2010,2018) for m in range(1,13)]
        pl.DataFrame(dict(signal_date=dates)).write_parquet(out/'monthly_input_coverage.parquet')
        return dict(months_with_100_basis_verified_points=96,status='EXISTING_PIPELINE_REQUIRED')
    monkeypatch.setattr(pipeline.audit,'run',point_audit)
    result=pipeline.qualify(config=pipeline.CONFIG,data_root=data,refresh_config=refresh,
        output=tmp_path/'qualification',known_at=dt.datetime(2026,11,8,16,tzinfo=dt.UTC))
    assert result['finite_signal_months']==0 and result['status']=='SAMPLE_INSUFFICIENT'
    assert not result['enqueued']


def test_event_cache_matches_direct_builder_and_carries_invalid_revision_null(frozen,monkeypatch):
    saved=json.loads(frozen.read_text())
    path=Path(saved['observations']);history=pl.read_parquet(path)
    revision=history.with_columns(pl.lit('revision').alias('source_row_id'),
        pl.lit(dt.datetime(2026,1,20,tzinfo=dt.UTC)).alias('available_at'),
        pl.lit(dt.datetime(2026,1,20,tzinfo=dt.UTC)).alias('observed_at'),
        pl.lit('parent_profit_basis_unverified').alias('input_reason'))
    history=pl.concat([history,revision]);history.write_parquet(path)
    saved['files'][str(path)]=inputs.sha(path);frozen.write_text(json.dumps(saved))
    days=[dt.date(2026,1,d) for d in range(5,31)]
    panel=pl.DataFrame(dict(symbol=['600000.SH']*len(days),trade_date=days))
    real=inputs.build_monthly_s4
    seen=[]
    def build(**kw):
        seen.extend(kw['signal_dates'])
        return real(**kw)
    monkeypatch.setattr(inputs,'build_monthly_s4',build)
    result=inputs.attach(panel,frozen)
    expected=real(income_history=pl.read_parquet(saved['income']),preliminary_history=history,
        signal_dates=tuple(days),candidate_symbols=('600000.SH',)).factors
    assert result[inputs.IDENTIFIER].equals(expected['sue_prelim'])
    assert len(seen)==3
    assert result.filter(pl.col('trade_date')>=dt.date(2026,1,21))[inputs.IDENTIFIER].null_count()==10


def test_diagnostics_use_this_batch_and_preserve_missing_january(tmp_path):
    folder=tmp_path/'evaluation/statistics/factors'/inputs.IDENTIFIER;folder.mkdir(parents=True)
    pl.DataFrame(dict(variant=['size_industry_neutral']*2,
        trade_date=[dt.date(2020,2,28),dt.date(2020,3,31)],rank_ic=[.1,.2])).write_parquet(folder/'monthly_ic.parquet')
    card=tmp_path/'n4.parquet'
    pl.from_dicts([dict(factor=inputs.IDENTIFIER,factor_admitted=False,family_controls=dict(
        incremental=dict(months=2,newey_west_t=1.5),sue_rank_correlation=.4))]).write_parquet(card)
    result=inputs.diagnostics(tmp_path,card)
    assert result['formal_months']==2 and result['incremental_nw_t']==1.5
    assert result['sue_rank_correlation']==.4 and result['january_ic'] is None
    pl.DataFrame(dict(factor=['other'],factor_admitted=[True])).write_parquet(card)
    with pytest.raises(ValueError,match='own unique'):
        inputs.diagnostics(tmp_path,card)


def test_isolated_data_namespace_shares_clean_but_never_old_factor_panels(tmp_path):
    source=tmp_path/'source';(source/'clean').mkdir(parents=True)
    (source/'clean/capture').write_bytes(b'unchanged existing capture')
    target=tmp_path/'isolated'
    pipeline.isolated_inputs(source,target)
    assert (target/'clean/capture').read_bytes()==b'unchanged existing capture'
    (target/'factors'/inputs.IDENTIFIER).mkdir(parents=True)
    assert not (source/'factors').exists()
