import datetime as dt

import polars as pl
import pytest

from quant.factors.annual_cash_profitability import compute_annual_cash_profitability
from quant.research.monthly_annual_cash_profitability import build_monthly_annual_cash_profitability


def histories() -> dict[str, pl.DataFrame]:
    out = {}
    for table in ('income', 'cashflow', 'balancesheet'):
        rows = []
        for year in (2021, 2022):
            values = {'n_income': 20.0} if table == 'income' else {
                'depr_fa_coga_dpba': 5.0, 'c_pay_acq_const_fiolta': 3.0} if table == 'cashflow' else {
                'total_assets': 100.0, 'total_cur_assets': 60.0 if year == 2021 else 70.0,
                'total_cur_liab': 20.0, 'money_cap': 15.0, 'st_borr': 3.0, 'taxes_payable': 2.0}
            rows.append({'symbol': '000001.SZ', 'end_date': dt.date(year, 12, 31),
                         'ann_date': dt.date(year + 1, 3, 1), 'f_ann_date': dt.date(year + 1, 3, 1),
                         'available_date': dt.date(year + 1, 3, 1), 'report_type': '1',
                         'comp_type': '1', 'update_flag': '0', **values})
        out[table] = pl.DataFrame(rows)
    return out


def build(h: dict[str, pl.DataFrame], date: dt.date = dt.date(2023, 3, 2)) -> pl.DataFrame:
    return build_monthly_annual_cash_profitability(income_history=h['income'], cash_history=h['cashflow'],
        balance_history=h['balancesheet'], signal_dates=(date,), candidate_symbols=('000001.SZ',)).factors


def test_formula_and_announcement_boundary() -> None:
    h = histories()
    result = build(h)
    assert result['pit_annual_cash_profitability'].item() == pytest.approx(.12)
    assert result['working_capital'].item() == 40
    assert result['prior_working_capital'].item() == 30
    assert build(h, dt.date(2023, 3, 1))['pit_annual_cash_profitability'].item() is None


@pytest.mark.parametrize('field', ['total_assets', 'total_cur_assets', 'total_cur_liab', 'money_cap',
                                   'st_borr', 'taxes_payable'])
def test_null_balance_inputs_remain_null(field: str) -> None:
    h = histories()
    h['balancesheet'] = h['balancesheet'].with_columns(pl.lit(None, dtype=pl.Float64).alias(field))
    assert build(h)['pit_annual_cash_profitability'].item() is None


@pytest.mark.parametrize('table,field', [('income', 'n_income'), ('cashflow', 'depr_fa_coga_dpba'),
                                       ('cashflow', 'c_pay_acq_const_fiolta'), ('balancesheet', 'st_borr')])
def test_latest_revision_conflict_does_not_fall_back(table: str, field: str) -> None:
    h = histories()
    duplicate = h[table].tail(1).with_columns((pl.col(field) + 1).alias(field))
    h[table] = pl.concat([h[table], duplicate])
    assert build(h)['pit_annual_cash_profitability'].item() is None


def test_missing_current_cash_and_age_and_negative_values() -> None:
    h = histories()
    assert build(h, dt.date(2024, 7, 1))['pit_annual_cash_profitability'].item() is None
    assert build(h, dt.date(2024, 6, 30))['pit_annual_cash_profitability'].item() == pytest.approx(.12)
    h['cashflow'] = h['cashflow'].head(1)
    assert build(h)['pit_annual_cash_profitability'].item() is None
    h = histories()
    h['income'] = h['income'].with_columns(pl.lit(-20.).alias('n_income'))
    assert build(h)['pit_annual_cash_profitability'].item() == pytest.approx(-.28)


def test_duplicate_annual_input_is_rejected() -> None:
    h = histories()
    with pytest.raises(ValueError, match='Duplicate'):
        compute_annual_cash_profitability(pl.concat([h['income'], h['income']]),
                                          h['cashflow'], h['balancesheet'])
