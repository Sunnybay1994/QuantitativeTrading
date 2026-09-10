"""Annual local cash profitability using fixed Tushare statement mappings."""

import polars as pl

WC_FIELDS = ('total_cur_assets', 'total_cur_liab', 'money_cap', 'st_borr', 'taxes_payable')


def compute_annual_cash_profitability(income: pl.DataFrame, cash: pl.DataFrame,
                                      balance: pl.DataFrame) -> pl.DataFrame:
    """Match annual statements and prior-year working capital; never fill missing debt."""
    keys = ['symbol', 'end_date']
    for frame in (income, cash, balance):
        if frame.select(pl.struct(keys).is_duplicated().any()).item():
            raise ValueError('Duplicate annual period')
        if frame.filter(pl.col('end_date').dt.month() != 12).height:
            raise ValueError('Annual statements required')
    wc = (pl.col('total_cur_assets') - pl.col('total_cur_liab') - pl.col('money_cap')
          + pl.col('st_borr') + pl.col('taxes_payable'))
    b = balance.with_columns(wc.alias('working_capital'))
    prior = b.select('symbol', pl.col('end_date').dt.offset_by('1y'),
                     pl.col('working_capital').alias('prior_working_capital'))
    values = income.select(*keys, 'n_income').join(
        cash.select(*keys, 'depr_fa_coga_dpba', 'c_pay_acq_const_fiolta'), on=keys, how='left'
    ).join(b.select(*keys, 'total_assets', 'working_capital'), on=keys, how='left').join(
        prior, on=keys, how='left')
    required = ['n_income', 'depr_fa_coga_dpba', 'c_pay_acq_const_fiolta',
                'total_assets', 'working_capital', 'prior_working_capital']
    return values.with_columns(
        pl.when(pl.all_horizontal(pl.col(f).is_finite() for f in required)
                & (pl.col('total_assets') > 0))
        .then((pl.col('n_income') + pl.col('depr_fa_coga_dpba')
               - pl.col('working_capital') + pl.col('prior_working_capital')
               - pl.col('c_pay_acq_const_fiolta')) / pl.col('total_assets'))
        .otherwise(None).alias('pit_annual_cash_profitability'))
