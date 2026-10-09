import datetime as dt

import numpy as np
import polars as pl

from quant.research.industry_information_coverage import residual_available
from quant.research.nightly_steps import incremental_statistics


def sample():
    rng=np.random.default_rng(701)
    return pl.DataFrame({'symbol':[f'{i:06d}.SZ' for i in range(150)],
        'trade_date':[dt.date(2025,12,31)]*150,'candidate':rng.normal(size=150),
        'label':rng.normal(size=150),'control':rng.normal(size=150)})


def test_availability_matches_original_incremental_month_acceptance():
    frame=sample()
    n,available=residual_available(frame,['control'])
    result=incremental_statistics(frame,'candidate',['control'],1)
    assert n==150 and available and result['months']==1


def test_constant_or_exactly_controlled_candidate_has_no_projectable_month():
    frame=sample()
    for value in (pl.lit(1.),pl.col('control')):
        actual=frame.with_columns(value.alias('candidate'))
        assert residual_available(actual,['control'])==(150,False)
        assert incremental_statistics(actual,'candidate',['control'],1)['months']==0


def test_missing_control_or_target_does_not_count_a_month():
    frame=sample().with_row_index()
    for column in ('label','control'):
        actual=frame.with_columns(pl.when(pl.col('index')<51).then(None).otherwise(pl.col(column)).alias(column))
        assert residual_available(actual,['control'])==(99,False)
        assert incremental_statistics(actual,'candidate',['control'],1)['months']==0
