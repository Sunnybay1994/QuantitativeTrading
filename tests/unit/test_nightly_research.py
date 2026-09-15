import datetime as dt
import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from deap import gp

from quant.factors.expressions import _UNARY, _WINDOW, required_history
from quant.research.nightly import failed_streak
from quant.research.nightly_gp import expand_expression, maximum_correlation, primitive_set
from quant.research.nightly_steps import incremental_statistics, ingest
from quant.data.nightly_genetic_inputs import admitted_controls


def test_gp_family_selection_falls_back_and_rotates_without_lowering_coverage():
    from quant.research.nightly_gp import select_family
    groups = {'price_volume':['price'], 'financial':['pit'], 'minute':['minute'],
              'mixed':['price','pit','minute']}
    coverage = {'price':72, 'pit':72, 'minute':71}
    selection = select_family(groups, coverage, 2)
    assert selection['requested_family'] == 'minute'
    assert selection['family'] == 'mixed'
    assert selection['family_selection_reason'] == 'preferred_family_insufficient_history'
    assert {select_family(groups, coverage, seed)['family'] for seed in range(4)} == {
        'price_volume', 'financial', 'mixed'}
    unavailable = select_family(groups, dict.fromkeys(coverage,71), 2)
    assert unavailable['family_terminals_with_72_months'] == 0
    assert unavailable['family_selection_reason'] == 'no_family_has_required_history'


def test_gp_family_selection_preserves_checkpoint_family_and_favored_terminals():
    from quant.research.nightly_gp import select_family
    groups = {'price_volume':['price'], 'minute':['new_minute'], 'mixed':['price','new_minute']}
    coverage = {'price':72, 'new_minute':72, 'old_minute':71}
    frozen = {'family':'minute', 'favored_terminals':['old_minute']}
    selection = select_family(groups, coverage, 0, frozen)
    assert selection['family'] == 'minute'
    assert selection['favored_terminals'] == ['old_minute']
    assert selection['family_terminals_with_72_months'] == 0
    with pytest.raises(ValueError, match='changed or disappeared'):
        select_family(groups, {'price':72}, 0, frozen)


@pytest.mark.parametrize('symbols', [99, 100])
def test_gp_run_family_coverage_boundary(tmp_path: Path, monkeypatch, symbols: int):
    from quant.research import nightly_gp
    output = tmp_path/'2026-09-15'/'N2'
    output.mkdir(parents=True)
    library = tmp_path/'library'
    library.mkdir()
    (library/'x.toml').write_text('id="x"\nexpr="adj_close"\nfamily="price"\ndirection=1\nsource_ref="fixture"\n')
    rows = [{'symbol':str(i), 'trade_date':dt.date(year,month,15), 'gp_x':float(i)}
            for year in range(2010,2016) for month in range(1,13) for i in range(symbols)]
    frame = pl.from_dicts(rows)
    frame.write_parquet(output/'daily_sample.parquet')
    frame.select('symbol','trade_date').with_columns(pl.lit(.1).alias('label'),
        pl.lit(dt.date(2016,1,1)).alias('label_exit_date')).write_parquet(output/'monthly_sample.parquet')
    def fake_search(*args, **kwargs):
        assert symbols == 100, 'insufficient coverage must not reach GP search'
        assert kwargs['family'] == 'mixed'
        return []
    monkeypatch.setattr(nightly_gp, 'search', fake_search)
    settings = {'library':str(library), 'training_end':'2016-01-01',
                'genetic':{'seed':(2-dt.date(2026,9,15).toordinal()) % 4}}
    if symbols == 99:
        with pytest.raises(ValueError, match='72 months and 100 finite stocks'):
            nightly_gp.run(settings, output)
    else:
        assert nightly_gp.run(settings, output)['family'] == 'mixed'
    summary = json.loads((output/'input_summary.json').read_text())
    assert summary['requested_family'] == 'minute'
    assert summary['family_selection_reason'] == (
        'no_family_has_required_history' if symbols == 99 else 'preferred_family_insufficient_history')


def test_incremental_statistics_is_invariant_to_join_row_order():
    rng = np.random.default_rng(31)
    rows = []
    for month in range(1, 5):
        for symbol in range(120):
            candidate, control = rng.normal(size=2)
            rows.append({'trade_date': dt.date(2020, month, 28), 'symbol': str(symbol),
                         'candidate': candidate, 'control': control,
                         'label': .1*candidate+rng.normal()})
    frame = pl.from_dicts(rows)
    ordered = incremental_statistics(frame, 'candidate', ['control'], 1)
    shuffled = incremental_statistics(frame.sample(fraction=1, shuffle=True, seed=5),
                                      'candidate', ['control'], 1)
    assert ordered['months'] == shuffled['months'] == 4
    assert ordered['newey_west_t'] == pytest.approx(shuffled['newey_west_t'])


def test_ingest_skips_published_candidate_but_rejects_changed_definition(tmp_path):
    queue = tmp_path/'queue'
    queue.mkdir()
    library = tmp_path/'library'
    (library/'auto').mkdir(parents=True)
    text = ('id="gp_known"\nexpr="delta(adj_close, 5)"\nfamily="price"\n'
            'direction=1\nsource_ref="fixture"\n')
    (library/'auto/gp_known.toml').write_text(text+'source="nightly_gp"\n')
    (queue/'gp_known.toml').write_text(text)
    run = tmp_path/'run'
    run.mkdir()
    settings = {'queue': str(queue), 'library': str(library)}
    assert ingest(settings, run)['queued_candidates'] == 0
    assert not list((run/'candidates').glob('*.toml'))
    (queue/'processing/gp_known.toml').write_text(text.replace('direction=1', 'direction=-1'))
    with pytest.raises(ValueError, match='Published candidate definition collision'):
        ingest(settings, run)


def test_dsl_grammar_contains_every_operator_and_daily_windows():
    pset=primitive_set(['adj_close','volume'])
    names={p.name for p in pset.primitives[object]}
    assert _UNARY<=names
    assert all(any(n.startswith(op+'_') for n in names) for op in _WINDOW-{'ts_quantile'})
    assert {'where','ind_neutralize','div','pow','gt','ge','lt','le','eq','ne'}<=names
    expression=gp.compile(gp.PrimitiveTree.from_string("ts_mean_20('adj_close')",pset),pset)
    assert expression=='ts_mean(adj_close,20)'
    assert required_history(expression)==19
    assert expand_expression('ts_mean(gp_x,20)',{'gp_x':'delta(adj_close,5)'})=='ts_mean(delta(adj_close, 5), 20)'


def test_maximum_correlation_reranks_common_support():
    frame=pl.DataFrame({'trade_date':[dt.date(2020,1,1)]*6,
        'score':[1.,2.,3.,4.,5.,6.],'control':[6.,None,4.,3.,None,1.]})
    assert np.isclose(maximum_correlation(frame,'score',['control'],minimum=4),1.)


def test_incremental_projection_removes_exact_copy():
    random=np.random.default_rng(7)
    rows=[]
    for year in range(2010,2019):
        for month in range(1,13):
            x=random.normal(size=120)
            y=x+random.normal(size=120)*.2
            for i in range(120):
                rows.append({'trade_date':dt.date(year,month,15),'symbol':str(i),
                             'candidate':float(x[i]),'control':float(x[i]),'label':float(y[i])})
    result=incremental_statistics(pl.from_dicts(rows),'candidate',['control'],1)
    # Numerically zero residual is not an independent admitted signal.
    assert result['mean_ic'] is None or abs(result['mean_ic'])<.1


def test_ingest_restarts_processing_without_duplicate_or_early_admission(tmp_path: Path):
    queue=tmp_path/'queue'
    queue.mkdir()
    (queue/'batch.toml').write_text('[[factors]]\nid="test_factor"\nexpr="delta(adj_close, 5)"\n'
        'family="price"\ndirection=1\nsource_ref="fixture"\n')
    run=tmp_path/'run'
    run.mkdir()
    settings={'queue':str(queue)}
    assert ingest(settings,run)['queued_candidates']==1
    assert ingest(settings,run)['queued_candidates']==1
    assert (queue/'processing'/'batch.toml').exists()
    assert len(list((run/'candidates').glob('*.toml')))==1


def test_three_distinct_real_runs_required_for_alert(tmp_path: Path):
    for day in ('2026-09-14','2026-09-15'):
        folder=tmp_path/day
        folder.mkdir()
        (folder/'summary.json').write_text(json.dumps({'steps':{'N2':{'ok':False}}}))
    assert failed_streak(tmp_path,dt.date(2026,9,15),'N2')==2
    folder=tmp_path/'2026-09-16'
    folder.mkdir()
    (folder/'summary.json').write_text(json.dumps({'steps':{'N2':{'ok':False}}}))
    assert failed_streak(tmp_path,dt.date(2026,9,16),'N2')==3


def test_admitted_controls_keep_neutral_variant_and_direction(tmp_path: Path):
    folder=tmp_path/'factors'/'test_factor'
    folder.mkdir(parents=True)
    (folder/'statistics.json').write_text(json.dumps({'statistics':[{'variant':'size_industry_neutral','mean_ic':.03}]}))
    pl.DataFrame({'symbol':['a','b'],'trade_date':[dt.date(2025,1,31)]*2,
                  'raw':[1.,2.],'size_industry_neutral':[-5.,7.]}).write_parquet(folder/'monthly_scores.parquet')
    card=pl.DataFrame({'factor':['test_factor'],'variant':['size_industry_neutral'],'mean_ic':[.03],'factor_admitted':[True]})
    frame,names=admitted_controls(tmp_path,card)
    assert len(names)==1
    assert frame[names[0]].to_list()==[-5.,7.]


def test_gp_resume_reuses_fitness_without_recalculating(tmp_path: Path,monkeypatch):
    from quant.research import nightly_gp
    pset=gp.PrimitiveSet('DAILY',0)
    pset.addTerminal('gp_x')
    pset.addTerminal('gp_y')
    pset.addPrimitive(lambda a,b:f'({a}+{b})',2,name='add')
    monkeypatch.setattr(nightly_gp,'primitive_set',lambda _:pset)
    rng=np.random.default_rng(13)
    rows=[]
    for year in range(2010,2014):
        for month in range(1,13):
            for i in range(100):
                x,y=rng.normal(size=2)
                rows.append({'symbol':str(i),'trade_date':dt.date(year,month,15),
                             'gp_x':float(x),'gp_y':float(y),'label':float(x+y)})
    frame=pl.from_dicts(rows)
    settings={'seed':7,'population_size':10,'generations':1,'max_depth':5,'complexity_penalty':.0005}
    mapping={'gp_x':'adj_close','gp_y':'volume'}
    winners=nightly_gp.search(frame.drop('label'),frame.select('symbol','trade_date','label'),mapping,settings,tmp_path,family='fixture')
    assert winners
    def forbidden(*args,**kwargs):
        raise AssertionError('completed fitness must come from checkpoint')
    monkeypatch.setattr(nightly_gp,'evaluate_expressions',forbidden)
    repeated=nightly_gp.search(frame.drop('label'),frame.select('symbol','trade_date','label'),mapping,settings,tmp_path,family='fixture')
    assert repeated==winners
    # Resume before the final generation also exercises DEAP mutation on restored
    # string terminals (their original return type is object, not inferred str).
    checkpoint=tmp_path/'search_checkpoint.json'
    saved=json.loads(checkpoint.read_text())
    saved['generation']=0
    checkpoint.write_text(json.dumps(saved))
    again=nightly_gp.search(frame.drop('label'),frame.select('symbol','trade_date','label'),mapping,settings,tmp_path,family='fixture')
    assert again==winners


def test_gp_training_scores_match_battery_and_reject_tiny_signal():
    from quant.research.factor_battery_evaluation import score_factor_sections
    from quant.research.nightly_gp import preprocess_training_scores

    rows = []
    for month, scale in ((1, 1.), (2, 1e-30)):
        for i in range(120):
            rows.append({'symbol':str(i), 'trade_date':dt.date(2020,month,15),
                         'candidate':scale * (1e4 if i == 119 else float(i)),
                         'label':float(i), 'eligible':True,
                         'total_market_value':1e8, 'industry_l1':'test'})
    frame = pl.from_dicts(rows)
    scored = preprocess_training_scores(frame)
    battery = score_factor_sections(universe=frame,
        values=frame.rename({'candidate':'value'}), direction=1,
        settings={'variants':['raw'], 'preprocessing':{'mad_multiplier':3., 'mad_normal_scale':1.4826}})
    np.testing.assert_allclose(scored['candidate'].to_numpy(), battery['raw'].to_numpy(), equal_nan=True)
    assert scored.filter(pl.col('trade_date') == dt.date(2020,2,15))['candidate'].null_count() == 120
    assert scored.filter(pl.col('trade_date') == dt.date(2020,1,15))['candidate'].null_count() == 0


def test_gp_rejects_legacy_fitness_cache_without_overwriting(tmp_path: Path):
    from quant.research.nightly_gp import search

    cache = tmp_path/'fitness_cache.json'
    original = json.dumps([{'terminal_expression':'gp_x', 'fitness':.1}])
    cache.write_text(original)
    frame = pl.DataFrame({'symbol':['a'], 'trade_date':[dt.date(2020,1,15)], 'gp_x':[1.]})
    labels = frame.select('symbol','trade_date').with_columns(pl.lit(1.).alias('label'))
    with pytest.raises(ValueError, match='use a new run directory'):
        search(frame, labels, {'gp_x':'adj_close'}, {'seed':1}, tmp_path, family='fixture')
    assert cache.read_text() == original


def test_gp_does_not_export_tiny_rank_predictive_candidate(tmp_path: Path, monkeypatch):
    from quant.research import nightly_gp

    pset = gp.PrimitiveSet('DAILY', 0)
    pset.addTerminal('gp_tiny')
    pset.addPrimitive(lambda a:f'(-{a})', 1, name='neg')
    monkeypatch.setattr(nightly_gp, 'primitive_set', lambda _:pset)
    frame = pl.from_dicts([
        {'symbol':str(i), 'trade_date':dt.date(year,month,15),
         'gp_tiny':float(i)*1e-30, 'label':float(i)}
        for year in range(2010,2014) for month in range(1,13) for i in range(120)])
    winners = nightly_gp.search(frame.drop('label'), frame.select('symbol','trade_date','label'),
        {'gp_tiny':'adj_close'}, {'seed':1, 'population_size':10, 'generations':0,
        'max_depth':5, 'complexity_penalty':.0005}, tmp_path, family='fixture')
    assert winners == []
    trials = json.loads((tmp_path/'search.json').read_text())['trials']
    assert trials and all(row['error'] == 'fewer than 48 valid training months' for row in trials)
