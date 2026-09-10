import datetime as dt

import numpy as np
import polars as pl
import pytest

from quant.research.classic_factor_evaluation import newey_west_t_statistic
from quant.research.factor_battery_statistics import (
    benjamini_hochberg, monthly_ic_summary, preprocess_cross_section, rank_ic_by_date,
)


def test_neutralization_removes_size_and_industry_without_inventing_variance():
    rng = np.random.default_rng(7)
    size = rng.normal(20, 1, 300)
    industry = np.array(["a", "b", "c"]*100)
    y = .5*size + (industry=="b")*.8 + rng.normal(0,.2,300)
    result = preprocess_cross_section(y, size, industry, neutralize=True)
    assert np.mean(result) == pytest.approx(0, abs=1e-12)
    assert np.std(result) == pytest.approx(1)
    assert np.corrcoef(result,size)[0,1] == pytest.approx(0,abs=1e-12)
    for level in ("a","b","c"):
        assert result[industry==level].mean() == pytest.approx(0,abs=1e-12)
    constant = preprocess_cross_section(np.ones(300),size,industry,neutralize=True)
    assert np.isnan(constant).all()
    # Zero MAD in a sparse signal does not erase its nonzero observations.
    sparse = preprocess_cross_section(np.r_[np.zeros(290),np.ones(10)],size,industry,neutralize=False)
    assert np.isfinite(sparse).all() and np.std(sparse) == pytest.approx(1)


def test_rank_ic_counts_signal_cohort_before_missing_outcomes():
    day = dt.date(2020,1,31)
    frame = pl.DataFrame({"trade_date":[day]*5,"score":[1.,2.,2.,4.,5.],
        "label":[5.,4.,4.,2.,None]})
    row = rank_ic_by_date(frame,score="score",label="label",minimum_symbols=3,
        minimum_paired_coverage=.9).row(0,named=True)
    assert row["signal_count"]==5 and row["paired_count"]==4
    assert row["paired_coverage"]==pytest.approx(.8) and row["rank_ic"] is None
    row = rank_ic_by_date(frame,score="score",label="label",minimum_symbols=3,
        minimum_paired_coverage=.8).row(0,named=True)
    assert row["rank_ic"]==pytest.approx(-1)


def test_calendar_hac_preserves_missing_months_and_matches_contiguous_reference():
    dates = [dt.date(2020,m,1) for m in range(1,13)]
    values = [.03,.04,-.02,.06,.03,-.01,.09,.08,.03,-.02,.04,.07]
    summary = monthly_ic_summary(dates,values,lag=3)
    assert summary["newey_west_t"]==pytest.approx(newey_west_t_statistic(values,lag=3))
    sparse_dates = [dates[i] for i in (0,2,5,8,11)]
    sparse_values = [values[i] for i in (0,2,5,8,11)]
    sparse = monthly_ic_summary(sparse_dates,sparse_values,lag=1)
    centered = np.array(sparse_values)-np.mean(sparse_values)
    # No adjacent calendar observations: lag-one covariance is zero.
    expected = np.mean(sparse_values)/np.sqrt(np.sum(centered**2)/len(centered)**2)
    assert sparse["newey_west_t"]==pytest.approx(expected)
    assert sparse["qualified_years"]==0 and sparse["yearly_positive_fraction"] is None
    constant = monthly_ic_summary(dates,[.03]*12)
    assert constant["icir"] is None and constant["newey_west_t"] is None
    assert benjamini_hochberg([.01,.04,.03,None])==pytest.approx([.04,.053333333333,.053333333333,None])
    with pytest.raises(ValueError):
        benjamini_hochberg([float("nan")])
