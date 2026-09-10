"""Monthly earnings stability from point-in-time quarterly parent ROE."""

import datetime as dt

import polars as pl

from quant.data.financial_pit import select_financial_revisions_as_of
from quant.data.quarterly_parent_income import select_quarterly_parent_income
from quant.factors.quarterly_roe_stability import compute_quarterly_roe_stability
from quant.research.pit_quality_research import PITQualitySignalResult


def build_monthly_quarterly_roe_stability(
    *, income_history: pl.DataFrame, balance_history: pl.DataFrame,
    signal_dates: tuple[dt.date, ...], candidate_symbols: tuple[str, ...],
) -> PITQualitySignalResult:
    """Anchor on the latest known income period and require a recent report."""
    structural = ['symbol', 'end_date', 'ann_date', 'f_ann_date', 'available_date',
                  'report_type', 'comp_type', 'update_flag']
    balance_history = balance_history.select(*structural, 'total_hldr_eqy_exc_min_int').filter(
        (pl.col('report_type') == '1') & (pl.col('comp_type') == '1'))
    income_history = income_history.filter((pl.col('report_type') == '1') & (pl.col('comp_type') == '1'))
    frames, eligibility, quarantines = [], [], []
    name = 'pit_quarterly_roe_volatility'
    for date in signal_dates:
        anchors = income_history.filter(pl.col('available_date') < date).group_by('symbol').agg(
            pl.col('end_date').max())
        quarters, income_quarantine = select_quarterly_parent_income(income_history, as_of=date)
        balance = select_financial_revisions_as_of(balance_history, dataset='balancesheet', as_of=date)
        values = compute_quarterly_roe_stability(quarters, balance.selected, anchors)
        cross = pl.DataFrame({'symbol': candidate_symbols}).join(values, on='symbol', how='left').with_columns(
            pl.when(pl.col('end_date') >= pl.lit(date).dt.offset_by('-6mo'))
            .then(pl.col(name)).otherwise(None).alias(name)
        ).with_columns(pl.col('end_date').alias('financial_period_end'), pl.lit(date).alias('trade_date'),
            pl.when(pl.col(name).is_finite().fill_null(False)).then(pl.lit('VALID'))
            .otherwise(pl.lit('MISSING_INVALID_OR_STALE_QUARTERS')).alias('status'))
        frames.append(cross.drop('end_date', 'status'))
        eligibility.append(cross.select(pl.col('trade_date').alias('as_of'), 'symbol', 'financial_period_end',
                                        pl.lit(name).alias('factor'), 'status'))
        for dataset, quarantine in [('income', income_quarantine), ('balancesheet', balance.quarantined)]:
            quarantines.append(quarantine.with_columns(pl.lit(date).alias('as_of'),
                                                        pl.lit(dataset).alias('dataset')))
    return PITQualitySignalResult(factors=pl.concat(frames).sort('trade_date', 'symbol'),
        eligibility=pl.concat(eligibility), quarantined=pl.concat(quarantines, how='diagonal_relaxed'))
