"""Monthly point-in-time annual cash profitability without stale-period fallback."""

import datetime as dt

import polars as pl

from quant.data.financial_pit import select_financial_revisions_as_of
from quant.factors.annual_cash_profitability import compute_annual_cash_profitability
from quant.research.pit_quality_research import PITQualitySignalResult


def build_monthly_annual_cash_profitability(
    *, income_history: pl.DataFrame, cash_history: pl.DataFrame, balance_history: pl.DataFrame,
    signal_dates: tuple[dt.date, ...], candidate_symbols: tuple[str, ...],
) -> PITQualitySignalResult:
    """Keep the latest known annual income period even when selection quarantines it."""
    fields = {'income': ['n_income'],
              'cashflow': ['depr_fa_coga_dpba', 'c_pay_acq_const_fiolta'],
              'balancesheet': ['total_assets', 'total_cur_assets', 'total_cur_liab',
                               'money_cap', 'st_borr', 'taxes_payable']}
    structural = ['symbol', 'end_date', 'ann_date', 'f_ann_date', 'available_date',
                  'report_type', 'comp_type', 'update_flag']
    histories = {table: history.filter((pl.col('end_date').dt.month() == 12)
                 & (pl.col('report_type') == '1') & (pl.col('comp_type') == '1'))
                 .select(*structural, *fields[table]) for table, history in
                 [('income', income_history), ('cashflow', cash_history), ('balancesheet', balance_history)]}
    frames, eligibility, quarantines = [], [], []
    name = 'pit_annual_cash_profitability'
    for date in signal_dates:
        latest = histories['income'].filter(pl.col('available_date') < date).group_by('symbol').agg(
            pl.col('end_date').max())
        selected = {table: select_financial_revisions_as_of(histories[table], dataset=table, as_of=date)
                    for table in ('income', 'cashflow', 'balancesheet')}
        values = compute_annual_cash_profitability(selected['income'].selected,
                  selected['cashflow'].selected, selected['balancesheet'].selected)
        cross = pl.DataFrame({'symbol': candidate_symbols}).join(latest, on='symbol', how='left').join(
            values, on=['symbol', 'end_date'], how='left')
        for table, selection in selected.items():
            quarantines.append(selection.quarantined.with_columns(pl.lit(date).alias('as_of'),
                                                                 pl.lit(table).alias('dataset')))
        cross = cross.with_columns(
            pl.when(pl.col('end_date') < pl.lit(date).dt.offset_by('-18mo'))
            .then(None).otherwise(pl.col(name)).alias(name)
        ).with_columns(pl.col('end_date').alias('financial_period_end'), pl.lit(date).alias('trade_date'),
            pl.when(pl.col(name).is_finite().fill_null(False)).then(pl.lit('VALID'))
            .otherwise(pl.lit('MISSING_INVALID_OR_STALE_ANNUAL')).alias('status'))
        frames.append(cross.drop('status', 'end_date'))
        eligibility.append(cross.select(pl.col('trade_date').alias('as_of'), 'symbol', 'financial_period_end',
                                        pl.lit(name).alias('factor'), 'status'))
    return PITQualitySignalResult(factors=pl.concat(frames).sort('trade_date', 'symbol'),
        eligibility=pl.concat(eligibility), quarantined=pl.concat(quarantines, how='diagonal_relaxed'))
