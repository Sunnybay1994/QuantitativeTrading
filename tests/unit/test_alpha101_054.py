import copy
import datetime as dt
from pathlib import Path
import tomllib

import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.factors.alpha101_054 import compute_alpha101_054
from quant.research.monthly_alpha101_054 import validate_alpha101_054

DATES = tuple(dt.date(2024, 1, i) for i in range(1, 5))


def sample():
    return pl.DataFrame(dict(symbol=['600001.SH']*4, trade_date=DATES, open=[10.,11.,9.,10.],
        high=[12.]*4, low=[8.]*4, close=[11.,9.,8.,12.], volume=[100.]*4))


def test_original_power_formula_scale_and_future():
    bars=sample()
    actual=compute_alpha101_054(bars,sessions=DATES)
    for row,value in zip(bars.to_dicts(),actual['alpha101_054'],strict=True):
        assert value==pytest.approx(-(row['low']-row['close'])*row['open']**5/
                                   ((row['low']-row['high'])*row['close']**5))
    scaled=bars.with_columns(pl.col(k)*1e70 for k in ('open','high','low','close'))
    assert_frame_equal(actual,compute_alpha101_054(scaled,sessions=DATES))
    assert_frame_equal(actual.head(3),compute_alpha101_054(bars.head(3),sessions=DATES[:3]))


@pytest.mark.parametrize('column,value',[('high',8.),('close',13.),('open',7.),('low',None),
    ('volume',0.),('close',float('inf'))])
def test_invalid_bar_and_missing_session_are_null(column,value):
    bad=sample().with_columns(pl.when(pl.col('trade_date')==DATES[1]).then(pl.lit(value))
        .otherwise(pl.col(column)).alias(column))
    assert compute_alpha101_054(bad,sessions=DATES)['alpha101_054'][1] is None
    missing=compute_alpha101_054(sample().filter(pl.col('trade_date')!=DATES[1]),sessions=DATES)
    assert missing['alpha101_054'][1] is None
    assert missing['alpha101_054'][2] is not None


def test_config_fixed_and_duplicates_rejected():
    config=tomllib.loads(Path('configs/research/b73_alpha101_054_20260910.toml').read_text())
    validate_alpha101_054(config)
    for section,key,value in [('alpha101_054','power',4),('factors','directions',[-1]),
                              ('portfolio','retention_rank',75)]:
        changed=copy.deepcopy(config)
        changed[section][key]=value
        with pytest.raises(ValueError):
            validate_alpha101_054(changed)
    with pytest.raises(ValueError,match='Duplicate'):
        compute_alpha101_054(pl.concat([sample(),sample().head(1)]),sessions=DATES)
