import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from scipy.stats import skew

from quant.factors.expressions import evaluate_expressions,required_history


def panel(values,symbol='A'):
    return pl.DataFrame({'symbol':[symbol]*len(values),
        'trade_date':[dt.date(2020,1,1)+dt.timedelta(days=i) for i in range(len(values))],
        'x':values})


def test_corrected_skew_matches_unbiased_local_reference_and_respects_bounds():
    x=np.random.default_rng(51).lognormal(size=500)
    result=evaluate_expressions(panel(x),{'s':'ts_skew(x,5)'},window_skew=True)['s']
    expected=skew(np.lib.stride_tricks.sliding_window_view(x,5),axis=1,bias=False)
    np.testing.assert_allclose(result.to_numpy()[4:],expected,rtol=1e-12,atol=1e-12)
    assert result.head(4).null_count()==4
    assert result.abs().max()<=np.sqrt(5)+1e-12


def test_old_prefix_and_extreme_scales_cannot_change_the_current_finite_window():
    x=[1e18,-1e18]+[1e-20*(i%7) for i in range(150)]
    p=panel(x)
    expr='ts_skew(ts_product(ts_rsquare(x,5),5),5)'
    # Use a plain skew too: near-zero windows used to suffer accumulated noise.
    expressions={'s':'ts_skew(x,5)','nested':expr}
    full=evaluate_expressions(p,expressions,window_skew=True)
    short=evaluate_expressions(p.slice(20),expressions,window_skew=True)
    for name,expression in expressions.items():
        warm=required_history(expression)
        np.testing.assert_allclose(full[name].to_numpy()[20+warm:],short[name].to_numpy()[warm:],
            equal_nan=True,rtol=0,atol=0)
    scaled=evaluate_expressions(panel([v*1e100 for v in x]),{'s':'ts_skew(x,5)'},window_skew=True)
    np.testing.assert_allclose(full['s'].to_numpy()[10:],scaled['s'].to_numpy()[10:],equal_nan=True,atol=1e-12)


def test_constant_missing_and_symbol_boundary_windows_are_not_filled():
    a=panel([1.,1.,1.,1.,1.,None,1.,2.,4.,8.])
    b=panel([9.,10.,12.,15.,20.],symbol='B')
    values=evaluate_expressions(pl.concat([a,b]),{'s':'ts_skew(x,5)'},window_skew=True)['s']
    assert values[:10].null_count()==10
    assert values[10:14].null_count()==4
    assert values[14]==pytest.approx(skew([9.,10.,12.,15.,20.],bias=False))


def test_legacy_default_is_unchanged_and_stable_path_is_explicit():
    p=panel([float(i%7) for i in range(90)])
    default=evaluate_expressions(p,{'s':'ts_skew(x,5)'})
    legacy=evaluate_expressions(p,{'s':'ts_skew(x,5)'},window_skew=False)
    assert default.equals(legacy)


def test_training_correction_preserves_old_n2_values_and_labels_its_actual_basis(tmp_path):
    from quant.research.gp_skew_repair import repaired_training
    source=tmp_path/'batch/day/N2/search.json';source.parent.mkdir(parents=True)
    source.write_text('{}')
    rng=np.random.default_rng(42)
    sample=pl.from_dicts([{'symbol':str(i),'trade_date':dt.date(2020,1,1)+dt.timedelta(days=d),
        'gp_x':float(rng.lognormal())} for i in range(120) for d in range(70)])
    sample.write_parquet(source.parent/'daily_sample.parquet')
    calculated=evaluate_expressions(sample,{'candidate':'ts_skew(gp_x,5)'},window_skew=True)
    rows=calculated.filter(pl.col('trade_date').dt.day()==20)
    original=rows.with_columns((pl.col('candidate')+5).alias('candidate'),pl.lit('ngp_x').alias('factor'))
    original.write_parquet(source.parent/'training_candidate_values.parquet')
    before=(source.parent/'training_candidate_values.parquet').read_bytes()
    labels=rows.select('symbol','trade_date').with_columns(pl.col('symbol').cast(pl.Float64).alias('label'))
    spec={'candidates':['ngp_x'],'sources':{str(source.parent/'daily_sample.parquet'):'verified_by_load'},
        'directions':{'ngp_x':1},'artifact_root':str(tmp_path/'repair')}
    plans={'ngp_x':{'source':source,'terminal':'ts_skew(gp_x,5)'}}
    corrected,receipt=repaired_training(spec,source=source,training=original,labels=labels,plans=plans)
    assert (source.parent/'training_candidate_values.parquet').read_bytes()==before
    assert corrected.drop('factor').equals(rows)
    assert not receipt['original_vs_corrected'][0]['passed']
    assert receipt['frozen_search_fitness_retained'] and not receipt['candidate_reselection']
    assert 'not original N2 reproduction' in receipt['basis']
    repeated,_=repaired_training(spec,source=source,training=original,labels=labels,plans=plans)
    assert repeated.equals(corrected)


def test_repair_request_rejects_changed_frozen_source(tmp_path):
    from quant.research.gp_skew_repair import load
    source=tmp_path/'source.json';source.write_text('original')
    config=tmp_path/'repair.toml'
    config.write_text('auto_trade=false\nversion="window_local_skew_v2"\n[sources]\n'+
        json.dumps(str(source))+'='+json.dumps(hashlib.sha256(source.read_bytes()).hexdigest()))
    assert load(config)
    source.write_text('changed')
    with pytest.raises(ValueError,match='Frozen skew-repair source changed'):
        load(config)


def test_original_panels_are_archived_before_replacement_and_backup_cannot_drift(tmp_path):
    from quant.research.gp_skew_repair import archive_panels
    data=tmp_path/'data';source=data/'factors/ngp_x/year=2020/data.parquet'
    source.parent.mkdir(parents=True);source.write_bytes(b'old derived bytes')
    spec={'candidates':['ngp_x'],'artifact_root':str(tmp_path/'repair')}
    first=archive_panels(spec,data_root=data)
    source.write_bytes(b'new corrected derived bytes')
    assert archive_panels(spec,data_root=data)==first
    saved=Path(next(iter(first['archived_sha256'])))
    assert saved.read_bytes()==b'old derived bytes'
    saved.write_bytes(b'tampered')
    with pytest.raises(ValueError,match='backup changed'):
        archive_panels(spec,data_root=data)
