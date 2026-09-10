import datetime as dt
import math

import polars as pl
import pytest

from quant.factors.annual_profitability import COMPONENTS, annual_profitability_components, rank_annual_profitability
from quant.research.monthly_annual_profitability import build_monthly_annual_profitability


def statements() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    keys = {'symbol': ['000001.SZ'] * 2, 'end_date': [dt.date(2021, 12, 31), dt.date(2022, 12, 31)]}
    income = pl.DataFrame(keys | {'n_income': [20., 20.], 'n_income_attr_p': [16., 16.],
                                  'revenue': [100., 100.], 'oper_cost': [70., 70.]})
    cash = pl.DataFrame(keys | {'depr_fa_coga_dpba': [5., 5.], 'c_pay_acq_const_fiolta': [3., 3.]})
    balance = pl.DataFrame(keys | {'total_assets': [100., 100.], 'total_hldr_eqy_exc_min_int': [80., 80.],
        'total_cur_assets': [60., 70.], 'total_cur_liab': [20., 20.], 'money_cap': [15., 15.],
        'st_borr': [3., 3.], 'taxes_payable': [2., 2.]})
    return income, cash, balance, income.select('symbol', 'end_date').tail(1)


def test_six_local_formulas_and_missing_capex() -> None:
    income, cash, balance, anchor = statements()
    values = annual_profitability_components(income, cash, balance, anchor)
    assert values.select(COMPONENTS).row(0) == pytest.approx((.3, .2, .2, .12, .3, -.05))
    cash = cash.with_columns(pl.lit(None, dtype=pl.Float64).alias('c_pay_acq_const_fiolta'))
    ranked = rank_annual_profitability(annual_profitability_components(income, cash, balance, anchor))
    assert ranked['cfoa'].item() is None
    assert ranked['low_accruals'].item() == pytest.approx(-.05)
    assert ranked['valid_components'].item() == 5


def test_available_mean_ties_and_all_missing() -> None:
    frame = pl.DataFrame({'gpoa': [1., 2., 3., None], 'roe': [None, 2., 1., None],
                          **{c: [None] * 4 for c in COMPONENTS[2:]}})
    result = rank_annual_profitability(frame)
    assert result['valid_components'].to_list() == [1, 2, 2, 0]
    assert result['pit_annual_profitability'].to_list()[:3] == pytest.approx([-math.sqrt(1.5), math.sqrt(1.5), 0.])
    assert result['pit_annual_profitability'][3] is None
    tied = frame.with_columns(pl.Series('gpoa', [1., 1., 3., None]),
                              pl.lit(None, dtype=pl.Float64).alias('roe'))
    assert rank_annual_profitability(tied)['pit_annual_profitability'].to_list()[:3] == pytest.approx(
        [-1 / math.sqrt(2), -1 / math.sqrt(2), math.sqrt(2)])
    constant = frame.with_columns(pl.lit(1.).alias('gpoa'), pl.lit(None, dtype=pl.Float64).alias('roe'))
    assert rank_annual_profitability(constant)['pit_annual_profitability'].to_list() == [0.] * 4


@pytest.mark.parametrize('field,expected', [('total_assets', 2), ('total_hldr_eqy_exc_min_int', 5), ('st_borr', 4)])
def test_invalid_denominator_and_missing_working_capital_are_component_specific(field: str, expected: int) -> None:
    income, cash, balance, anchor = statements()
    balance = balance.with_columns(pl.lit(None if field == 'st_borr' else 0., dtype=pl.Float64).alias(field))
    result = rank_annual_profitability(annual_profitability_components(income, cash, balance, anchor))
    assert result['valid_components'].item() == expected


def test_announcement_latest_conflict_and_expiry() -> None:
    income, cash, balance, _ = statements()
    def dated(frame):
        return frame.with_columns((pl.col('end_date').dt.offset_by('3mo')).alias('available_date')).with_columns(
            pl.col('available_date').alias('ann_date'), pl.col('available_date').alias('f_ann_date'),
            pl.lit('1').alias('report_type'), pl.lit('1').alias('comp_type'), pl.lit('0').alias('update_flag'))
    income, cash, balance = [dated(f) for f in (income, cash, balance)]
    income = pl.concat([income, income.tail(1).with_columns(pl.lit(21.).alias('n_income'))])
    def run(date):
        return build_monthly_annual_profitability(income_history=income, cash_history=cash,
            balance_history=balance, signal_dates=(date,), candidate_symbols=('000001.SZ',)).factors
    same_day = run(dt.date(2023, 3, 31))
    assert same_day['financial_period_end'].item() == dt.date(2021, 12, 31)
    after = run(dt.date(2023, 4, 1))
    assert after['financial_period_end'].item() == dt.date(2022, 12, 31)
    assert after['gpoa'].item() is None and after['cfoa'].item() is None
    assert after['valid_components'].item() == 1
    assert after['low_accruals'].item() == pytest.approx(-.05)
    expired = run(dt.date(2024, 7, 1))
    assert expired['valid_components'].item() == 0
    assert expired['pit_annual_profitability'].item() is None
