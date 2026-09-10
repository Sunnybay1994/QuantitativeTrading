import copy
import datetime as dt
import math
from pathlib import Path
import tomllib

import polars as pl
import pytest

from quant.research.monthly_alpha101_041 import build_monthly_alpha101_041, validate_alpha101_041


def sample():
    dates=tuple(dt.date(2024,1,1)+dt.timedelta(days=i) for i in range(70))
    bars=pl.DataFrame([dict(symbol='600001.SH',trade_date=day,open=11.,high=20.,low=8.,
        close=10.+(i*3%7),volume=100.+(i*3%11)*10,amount=2000.,adj_factor=1.+(i%3)*.1,source='fixture')
        for i,day in enumerate(dates)])
    return dates,bars


def test_month_ends_match_raw_scalar_formula_and_ignore_adjustment():
    dates,bars=sample()
    result=build_monthly_alpha101_041(bars,sessions=dates,start=dates[0],end=dates[-1])
    assert result['trade_date'].to_list()==[dt.date(2024,1,31),dt.date(2024,2,29)]
    for row in result.to_dicts():
        raw=bars.filter(pl.col('trade_date')==row['trade_date']).row(0,named=True)
        assert row['alpha101_041']==pytest.approx(math.sqrt(raw['high']*raw['low'])-raw['amount']/raw['volume'],abs=1e-12)
    changed=bars.with_columns((pl.col('adj_factor')*100).alias('adj_factor'))
    actual=build_monthly_alpha101_041(changed,sessions=dates,start=dates[0],end=dates[-1])
    assert actual['alpha101_041'].to_list()==result['alpha101_041'].to_list()


def test_day_local_factor_survives_previous_gap_but_nulls_zero_current_volume():
    dates,bars=sample()
    baseline=build_monthly_alpha101_041(bars,sessions=dates,start=dates[0],end=dates[-1])
    gap=bars.filter(pl.col('trade_date')!=dt.date(2024,1,30))
    result=build_monthly_alpha101_041(gap,sessions=dates,start=dates[0],end=dates[-1])
    assert result['alpha101_041'].to_list()==baseline['alpha101_041'].to_list()
    zero=bars.with_columns(pl.when(pl.col('trade_date')==dt.date(2024,1,31)).then(0.).otherwise(pl.col('volume')).alias('volume'))
    result=build_monthly_alpha101_041(zero,sessions=dates,start=dates[0],end=dates[-1])
    assert result['alpha101_041'].to_list()==[None,baseline['alpha101_041'][1]]


def test_fixed_config_preserves_baseline_and_reference_twelve():
    config=tomllib.loads(Path('configs/research/b85_alpha101_041_20260910.toml').read_text())
    prior=tomllib.loads(Path('configs/research/b82_alpha101_012_20260910.toml').read_text())
    for section in ('data','universe','costs','walk_forward','portfolio'):
        assert config[section]==prior[section]
    assert config['admission']['redundancy_references']==prior['admission']['redundancy_references']+['alpha101_012']
    validate_alpha101_041(config)
    for section,key,value in [('alpha101_041','adjustment','adj_factor'),('alpha101_041','vwap','close'),
        ('factors','directions',[-1]),('admission','redundancy_references',['alpha101_041']),
        ('portfolio','retention_rank',75)]:
        changed=copy.deepcopy(config)
        changed[section][key]=value
        with pytest.raises(ValueError):
            validate_alpha101_041(changed)


def test_composition_freezes_cohort_directions_and_paired_admission():
    config=tomllib.loads(Path('configs/research/b86_alpha101_041_composite_20260910.toml').read_text())
    prior=tomllib.loads(Path('configs/research/b85_alpha101_041_20260910.toml').read_text())
    for section in ('data','universe','costs','walk_forward','portfolio','alpha101_041'):
        assert config[section]==prior[section]
    validate_alpha101_041(config)
    for section,key,value in [('alpha101_041_composition','eligibility','separate_pools'),
        ('alpha101_041_composition','weights','optimized'),('factors','directions',[-1,1,-1,-1]),
        ('admission','comparison','510300'),('admission','require_positive_paired_1x_compounded_increment',False)]:
        changed=copy.deepcopy(config)
        changed[section][key]=value
        with pytest.raises(ValueError):
            validate_alpha101_041(changed)




def test_buffer_changes_only_retention_and_requires_lower_turnover():
    config=tomllib.loads(Path('configs/research/b87_alpha101_041_buffer75_20260910.toml').read_text())
    prior=tomllib.loads(Path('configs/research/b86_alpha101_041_composite_20260910.toml').read_text())
    for section in ('alpha101_041','data','universe','costs','walk_forward','factors','composite'):
        assert config[section]==prior[section]
    assert {k:v for k,v in config['portfolio'].items() if k!='retention_rank'}==prior['portfolio']
    validate_alpha101_041(config)
    for section,key,value in [('portfolio','retention_rank',100),
        ('portfolio','execution_months',[1,3,5,7,9,11]),
        ('alpha101_041_buffer','retention_rule','actual_holdings'),
        ('admission','require_lower_turnover_every_fold',False),('admission','comparison','three_factor')]:
        changed=copy.deepcopy(config)
        changed[section][key]=value
        with pytest.raises(ValueError):
            validate_alpha101_041(changed)
    changed=copy.deepcopy(config)
    changed['alpha101_041_composition']=prior['alpha101_041_composition']
    with pytest.raises(ValueError):
        validate_alpha101_041(changed)


