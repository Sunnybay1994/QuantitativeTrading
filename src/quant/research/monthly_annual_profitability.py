"""Point-in-time annual six-measure profitability scores for monthly research."""

import datetime as dt

import polars as pl

from quant.data.financial_pit import select_financial_revisions_as_of
from quant.factors.annual_profitability import (
    COMPONENTS, annual_profitability_components, rank_annual_profitability,
)
from quant.research.pit_quality_research import PITQualitySignalResult


def build_monthly_annual_profitability(
    *, income_history: pl.DataFrame, cash_history: pl.DataFrame, balance_history: pl.DataFrame,
    signal_dates: tuple[dt.date, ...], candidate_symbols: tuple[str, ...],
) -> PITQualitySignalResult:
    """Rank fresh financial candidates; later market filters do not change these scores."""
    fields = {'income': ['n_income', 'n_income_attr_p', 'revenue', 'oper_cost'],
              'cashflow': ['depr_fa_coga_dpba', 'c_pay_acq_const_fiolta'],
              'balancesheet': ['total_assets', 'total_hldr_eqy_exc_min_int', 'total_cur_assets',
                               'total_cur_liab', 'money_cap', 'st_borr', 'taxes_payable']}
    structural = ['symbol', 'end_date', 'ann_date', 'f_ann_date', 'available_date',
                  'report_type', 'comp_type', 'update_flag']
    histories = {table: history.filter((pl.col('end_date').dt.month() == 12)
                 & (pl.col('report_type') == '1') & (pl.col('comp_type') == '1'))
                 .select(*structural, *fields[table]) for table, history in
                 [('income', income_history), ('cashflow', cash_history), ('balancesheet', balance_history)]}
    frames, eligibility, quarantines = [], [], []
    for date in signal_dates:
        anchors = histories['income'].filter(pl.col('available_date') < date).group_by('symbol').agg(
            pl.col('end_date').max())
        selected = {table: select_financial_revisions_as_of(histories[table], dataset=table, as_of=date)
                    for table in ('income', 'cashflow', 'balancesheet')}
        values = annual_profitability_components(selected['income'].selected,
            selected['cashflow'].selected, selected['balancesheet'].selected, anchors)
        cross = pl.DataFrame({'symbol': candidate_symbols}).join(values, on='symbol', how='left').with_columns(
            pl.when(pl.col('end_date') >= pl.lit(date).dt.offset_by('-18mo'))
            .then(pl.col(c)).otherwise(None).alias(c) for c in COMPONENTS)
        cross = rank_annual_profitability(cross).with_columns(
            pl.col('end_date').alias('financial_period_end'), pl.lit(date).alias('trade_date'))
        frames.append(cross.drop('end_date'))
        eligibility.append(cross.select(pl.col('trade_date').alias('as_of'), 'symbol', 'financial_period_end',
            'valid_components', pl.lit('pit_annual_profitability').alias('factor'),
            pl.when(pl.col('pit_annual_profitability').is_finite().fill_null(False)).then(pl.lit('VALID'))
            .otherwise(pl.lit('MISSING_INVALID_OR_STALE_ANNUAL')).alias('status')))
        for table, selection in selected.items():
            quarantines.append(selection.quarantined.with_columns(pl.lit(date).alias('as_of'),
                                                                 pl.lit(table).alias('dataset')))
    return PITQualitySignalResult(factors=pl.concat(frames).sort('trade_date', 'symbol'),
        eligibility=pl.concat(eligibility), quarantined=pl.concat(quarantines, how='diagonal_relaxed'))
