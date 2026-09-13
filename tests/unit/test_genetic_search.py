import datetime as dt
import random
from dataclasses import replace

import numpy as np
import polars as pl
import pytest

from quant.factors.expressions import ExpressionEngine
from quant.factors.genetic_search import GeneticSearchConfig, search_genetic


def panel():
    rows=[]
    for i,day in enumerate([dt.date(2020,1,31),dt.date(2020,2,29),dt.date(2020,3,31)]):
        for n in range(8):
            rows.append({'symbol':f's{n}','trade_date':day,'label_exit_date':day+dt.timedelta(days=1),
                         'x':float(n+1+i*1000),'y':float((n*3)%7), 'label':float(n+1-i*1000)})
    return pl.DataFrame(rows)


def config(**changes):
    cfg=GeneticSearchConfig(training_end=dt.date(2020,4,2),seed=74,population_size=10,
        generations=3,max_unique_evaluations=40,max_attempts=100,max_depth=3,
        minimum_symbols=5,minimum_months=3,candidate_count=40,
        crossover_probability=1.,mutation_probability=1.,random_baseline=True)
    return replace(cfg,**changes)


def test_reproducible_actual_evolution_budgets_random_control_and_rng_restore():
    before=random.getstate()
    result=search_genetic(panel(),{'x':'ret20','y':'vol20'},config())
    assert random.getstate()==before
    assert result==search_genetic(panel().reverse(),{'y':'vol20','x':'ret20'},config())
    assert any(t['generation']>0 and 'crossover' in t['operation'] and 'mutation' in t['operation'] for t in result['trials'])
    assert result['summary']['attempts']<=100 and result['summary']['unique_evaluations']<=40
    assert result['summary']['duplicate_attempts']>0
    assert result['random_baseline']['summary']['unique_evaluation_target']==result['summary']['unique_evaluations']
    for r in [result,result['random_baseline']]:
        assert len(r['trials'])==r['summary']['attempts']
        assert all(t['depth']<=3 for t in r['trials'] if t['status']=='evaluated')


def test_equal_month_cross_section_ic_not_flattened_and_direction():
    data=panel()
    assert np.corrcoef(data['x'],data['label'])[0,1]<-.99
    result=search_genetic(data,{'x':'ret20'},config())
    leaf=[t for t in result['trials'] if t['status']=='evaluated' and t['complexity']==1]
    assert leaf and leaf[0]['train']['mean_ic']==pytest.approx(1.)
    neg=[t for t in result['trials'] if t['status']=='evaluated' and t['tree']=='neg(ARG0)']
    assert neg and neg[0]['direction']==-1 and neg[0]['directed_mean_ic']==pytest.approx(1.)
    assert neg[0]['fitness']==pytest.approx(1.-2*config().complexity_penalty)


def test_dsl_export_reproduces_precomputed_arithmetic():
    data=panel()
    # Raw DSL is a different spelling of exactly the same terminal values.
    data=data.with_columns((pl.col('x')/2).alias('raw_x'),pl.col('y').alias('raw_y'))
    result=search_genetic(data,{'x':'raw_x * 2','y':'raw_y'},config())
    for candidate in result['candidates']:
        def values(expr):
            engine=ExpressionEngine(data)
            compiled=engine.compile(expr)
            return engine.frame.select(compiled.alias('out')).collect()['out'].to_numpy()
        assert np.allclose(values(candidate['expression']),values(candidate['terminal_expression']),equal_nan=True)


@pytest.mark.parametrize('kind',['future_signal','future_label','duplicate','daily_not_monthly','label_terminal'])
def test_rejects_leakage_or_ambiguous_training_boundary(kind):
    data=panel()
    terminals={'x':'ret20'}
    if kind=='future_signal':
        data=data.with_columns(pl.lit(dt.date(2021,1,1)).alias('trade_date'))
    elif kind=='future_label':
        data=data.with_columns(pl.lit(dt.date(2021,1,1)).alias('label_exit_date'))
    elif kind=='duplicate':
        data=pl.concat([data,data.head(1)])
    elif kind=='daily_not_monthly':
        extra=data.head(1).with_columns(pl.lit(dt.date(2020,1,30)).alias('trade_date'))
        data=pl.concat([data,extra])
    else:
        terminals={'x':'label * 2'}
    with pytest.raises(ValueError):
        search_genetic(data,terminals,config())


def test_all_invalid_and_attempt_budget_terminate_without_candidates():
    data=panel().with_columns(pl.lit(float('inf')).alias('x'))
    result=search_genetic(data,{'x':'ret20'},config(max_attempts=9,max_unique_evaluations=100))
    assert not result['candidates'] and len(result['trials'])==9
    assert result['summary']['invalid_attempts']>0
    assert all(t['status'] in ('invalid','duplicate') for t in result['trials'])


def test_depth_failures_recorded_and_unique_cap_counts_invalid_evaluations(monkeypatch):
    from deap import gp
    def overdeep(left, right):
        neg=gp.Primitive('neg',[object],object)
        return type(left)([neg,neg,*left]),right
    monkeypatch.setattr(gp,'cxOnePoint',overdeep)
    result=search_genetic(panel(),{'x':'ret20','y':'vol20'},config(max_depth=1,max_unique_evaluations=30,max_attempts=200,mutation_probability=0.))
    assert any(t.get('reason')=='maximum_tree_depth' for t in result['trials'])
    assert all(c['depth']<=1 for c in result['candidates'])
    capped=search_genetic(panel(),{'x':'ret20'},config(max_unique_evaluations=1,max_attempts=50))
    assert capped['summary']['unique_evaluations']==1
    assert len(capped['trials'])==1


def test_original_terminal_and_sign_equivalent_candidates_are_not_exported():
    result=search_genetic(panel(),{'x':'ret20'},config())
    assert result['summary']['valid_evaluations']>0
    assert not result['candidates']
    assert any(t.get('equivalent_to')=='x' for t in result['trials'])
