"""A4 SUE family kernel unit tests."""
import datetime as dt
import math

import polars as pl

from quant.factors.sue_family import apply_time_decay, compute_rsue8, compute_sue_mad8, decay_scalar


def test_decay_scalar():
    assert abs(decay_scalar(1.0, 0, 20) - 1.0) < 1e-12
    assert abs(decay_scalar(1.0, 20, 20) - math.exp(-1.0)) < 1e-12


def test_apply_time_decay_columns():
    frame = pl.DataFrame({
        "symbol": ["000001.SZ", "000002.SZ"],
        "pit_sue8": [1.0, 2.0],
        "available_date": [dt.date(2024, 1, 10), None],
        "financial_period_end": [dt.date(2023, 12, 31), dt.date(2023, 12, 31)],
    })
    out = apply_time_decay(frame, signal_date=dt.date(2024, 1, 31), taus=(20, 40))
    assert out["sue_decay_tau20"][0] == decay_scalar(1.0, 21, 20)
    assert out["sue_decay_tau40"][0] == decay_scalar(1.0, 21, 40)
    assert out["sue_decay_tau20"][1] is None


def _income_chain(symbol: str = "000001.SZ") -> pl.DataFrame:
    # 12 consecutive quarters of cumulative then differenced by _single_quarters.
    rows = []
    value = 10.0
    rev = 100.0
    for year in (2021, 2022, 2023):
        for q, month in enumerate((3, 6, 9, 12), start=1):
            end = dt.date(year, month, 28 if month != 3 else 31)
            if month == 3:
                end = dt.date(year, 3, 31)
            elif month == 6:
                end = dt.date(year, 6, 30)
            elif month == 9:
                end = dt.date(year, 9, 30)
            else:
                end = dt.date(year, 12, 31)
            # cumulative within year for single-quarter extraction
            if q == 1:
                cum_income, cum_rev = value, rev
            else:
                cum_income += value
                cum_rev += rev
            value += 1.0
            rev += 2.0
            rows.append({
                "symbol": symbol,
                "report_type": "1",
                "comp_type": "1",
                "end_date": end,
                "n_income_attr_p": cum_income,
                "revenue": cum_rev,
                "available_date": end + dt.timedelta(days=30),
                "ann_date": end + dt.timedelta(days=30),
                "f_ann_date": end + dt.timedelta(days=30),
                "update_flag": "0",
                "source": "test",
            })
    return pl.DataFrame(rows)


def test_mad_and_rsue_produce_columns():
    income = _income_chain()
    mad = compute_sue_mad8(income)
    assert "sue_mad8" in mad.columns
    rsue = compute_rsue8(income)
    assert "rsue8" in rsue.columns
