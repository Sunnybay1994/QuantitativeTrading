import copy
import datetime as dt
from pathlib import Path
import tomllib

import polars as pl
import pytest

from quant.research.monthly_alpha101_012 import build_monthly_alpha101_012, validate_alpha101_012


def sample():
    dates=tuple(dt.date(2024,1,1)+dt.timedelta(days=i) for i in range(70))
    bars=pl.DataFrame([dict(symbol='600001.SH',trade_date=day,open=11.,high=20.,low=8.,
        close=10.+(i*3%7),volume=100.+(i*3%11)*10,amount=2000.,adj_factor=1.+(i%3)*.1,source='fixture')
        for i,day in enumerate(dates)])
    return dates,bars


def test_adapter_matches_scalar_formula_on_completed_month_ends():
    dates,bars=sample()
    result=build_monthly_alpha101_012(bars,sessions=dates,start=dates[0],end=dates[-1])
    assert result['trade_date'].to_list()==[dt.date(2024,1,31),dt.date(2024,2,29)]
    for row in result.to_dicts():
        first,last=bars.filter(pl.col('trade_date')<=row['trade_date']).tail(2).to_dicts()
        dv=last['volume']-first['volume']
        expected=-((dv>0)-(dv<0))*(last['close']*last['adj_factor']-first['close']*first['adj_factor'])
        assert row['alpha101_012']==pytest.approx(expected,abs=1e-12)


def test_missing_previous_session_is_null_but_unchanged_volume_is_zero():
    dates,bars=sample()
    gap=bars.filter(pl.col('trade_date')!=dt.date(2024,1,30))
    result=build_monthly_alpha101_012(gap,sessions=dates,start=dates[0],end=dates[-1])
    assert result.filter(pl.col('trade_date')==dt.date(2024,1,31))['alpha101_012'].item() is None
    constant=bars.with_columns(pl.lit(100.).alias('volume'))
    result=build_monthly_alpha101_012(constant,sessions=dates,start=dates[0],end=dates[-1])
    assert result['alpha101_012'].to_list()==[0.,0.]
    assert result['alpha101_006'].null_count()==2


def test_fixed_config_preserves_baseline_and_reference_six():
    config=tomllib.loads(Path('configs/research/b82_alpha101_012_20260910.toml').read_text())
    prior=tomllib.loads(Path('configs/research/b78_alpha101_006_20260910.toml').read_text())
    for section in ('data','universe','costs','walk_forward','portfolio'):
        assert config[section]==prior[section]
    assert config['admission']['redundancy_references']==prior['admission']['redundancy_references']+['alpha101_006']
    validate_alpha101_012(config)
    for section,key,value in [('alpha101_012','delta_sessions',2),('alpha101_012','price_change','return'),
        ('factors','directions',[-1]),('alpha101_012','unchanged_volume','null'),
        ('admission','redundancy_references',['alpha101_012']),('portfolio','retention_rank',75)]:
        changed=copy.deepcopy(config)
        changed[section][key]=value
        with pytest.raises(ValueError):
            validate_alpha101_012(changed)
