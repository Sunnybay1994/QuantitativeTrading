import copy
import datetime as dt
from pathlib import Path
import statistics
import tomllib

import polars as pl
import pytest

from quant.research.monthly_alpha101_006 import build_monthly_alpha101_006, validate_alpha101_006


def test_adapter_matches_scalar_formula_on_completed_month_ends():
    dates=tuple(dt.date(2024,1,1)+dt.timedelta(days=i) for i in range(70))
    bars=pl.DataFrame([dict(symbol='600001.SH',trade_date=day,open=10.+(i*7%13)/2,
        high=20.,low=8.,close=11.,volume=100.+(i*3%11)*10,amount=2000.,adj_factor=1.,source='fixture')
        for i,day in enumerate(dates)])
    result=build_monthly_alpha101_006(bars,sessions=dates,start=dates[0],end=dates[-1])
    assert result['trade_date'].to_list()==[dt.date(2024,1,31),dt.date(2024,2,29)]
    for row in result.to_dicts():
        history=bars.filter(pl.col('trade_date')<=row['trade_date']).tail(10)
        expected=-statistics.correlation(history['open'].to_list(),history['volume'].to_list())
        assert row['alpha101_006']==pytest.approx(expected,abs=1e-12)


def test_fixed_config_and_no_self_redundancy():
    config=tomllib.loads(Path('configs/research/b78_alpha101_006_20260910.toml').read_text())
    prior=tomllib.loads(Path('configs/research/b74_alpha101_055_20260910.toml').read_text())
    for section in ('data','universe','costs','walk_forward','portfolio'):
        assert config[section]==prior[section]
    validate_alpha101_006(config)
    for section,key,value in [('alpha101_006','correlation_sessions',12),('factors','directions',[-1]),
        ('admission','redundancy_references',['alpha101_006']),('portfolio','retention_rank',75)]:
        changed=copy.deepcopy(config)
        changed[section][key]=value
        with pytest.raises(ValueError):
            validate_alpha101_006(changed)


def test_composition_preserves_factor_and_requires_matched_positive_increment():
    config=tomllib.loads(Path('configs/research/b79_alpha101_006_composite_20260910.toml').read_text())
    prior=tomllib.loads(Path('configs/research/b78_alpha101_006_20260910.toml').read_text())
    for section in ('alpha101_006','data','universe','costs','walk_forward','portfolio'):
        assert config[section]==prior[section]
    validate_alpha101_006(config)
    for section,key,value in [('factors','directions',[-1,-1,-1,1]),
        ('alpha101_006_composition','eligibility','three_factor_only'),
        ('alpha101_006_composition','weights','equal_rank'),('admission','comparison','510300'),
        ('admission','require_positive_paired_1x_compounded_increment',False),
        ('admission','minimum_mean_test_rank_ic',.03),('portfolio','retention_rank',75)]:
        changed=copy.deepcopy(config)
        changed[section][key]=value
        with pytest.raises(ValueError):
            validate_alpha101_006(changed)


def test_buffer_changes_only_retention_and_requires_lower_turnover():
    config=tomllib.loads(Path('configs/research/b80_alpha101_006_buffer75_20260910.toml').read_text())
    prior=tomllib.loads(Path('configs/research/b79_alpha101_006_composite_20260910.toml').read_text())
    for section in ('alpha101_006','data','universe','costs','walk_forward','factors','composite'):
        assert config[section]==prior[section]
    assert {k:v for k,v in config['portfolio'].items() if k!='retention_rank'}==prior['portfolio']
    validate_alpha101_006(config)
    for section,key,value in [('portfolio','retention_rank',100),
        ('portfolio','execution_months',[1,3,5,7,9,11]),
        ('alpha101_006_buffer','retention_rule','actual_holdings'),
        ('admission','require_lower_turnover_every_fold',False),('admission','comparison','three_factor')]:
        changed=copy.deepcopy(config)
        changed[section][key]=value
        with pytest.raises(ValueError):
            validate_alpha101_006(changed)
    changed=copy.deepcopy(config)
    changed['alpha101_006_composition']=prior['alpha101_006_composition']
    with pytest.raises(ValueError):
        validate_alpha101_006(changed)
