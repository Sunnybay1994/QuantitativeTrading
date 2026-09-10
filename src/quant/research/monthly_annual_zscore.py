"""Monthly financial safety using the latest known annual income period."""

import datetime as dt
from typing import Any

import polars as pl

from quant.data.financial_pit import select_financial_revisions_as_of
from quant.factors.annual_zscore import compute_annual_zscore
from quant.research.pit_quality_research import PITQualitySignalResult


def validate_annual_zscore(config: dict[str, Any]) -> None:
    """Reject configurations that disagree with the implemented fixed hypothesis."""
    expected = {
        'formula': '(1.2 * working_capital + 1.4 * retained_earnings + 3.3 * ebit + 0.6 * total_market_value + revenue) / total_assets',
        'working_capital': 'total_cur_assets - total_cur_liab',
        'retained_earnings': 'surplus_rese + undistr_porfit',
        'market_value': 'exact_signal_date_clean_total_market_value_yuan',
        'maximum_age_months': 18,
        'latest_annual_period': 'latest_known_income_period_no_fallback',
        'missing_component': 'exclude_symbol',
        'valid_values': 'all_finite_positive_assets_and_market_value_nonnegative_current_assets_current_liabilities_and_revenue',
    }
    if (any(config.get('annual_zscore', {}).get(k) != v for k, v in expected.items())
        or config['factors']['names'] != ['pit_annual_zscore']
        or config['factors']['directions'] != [1]):
        raise ValueError('Annual Z-score requires the frozen QMJ appendix mapping and positive direction')


def build_monthly_annual_zscore(
    *, income_history: pl.DataFrame, balance_history: pl.DataFrame, daily_basic: pl.DataFrame,
    signal_dates: tuple[dt.date, ...], candidate_symbols: tuple[str, ...],
) -> PITQualitySignalResult:
    """Missing or conflicting latest reports remain null; never reuse an older period."""
    fields = {'income': ['ebit', 'revenue'],
              'balancesheet': ['total_assets', 'total_cur_assets', 'total_cur_liab',
                               'surplus_rese', 'undistr_porfit']}
    structural = ['symbol', 'end_date', 'ann_date', 'f_ann_date', 'available_date',
                  'report_type', 'comp_type', 'update_flag']
    histories = {table: history.filter((pl.col('end_date').dt.month() == 12)
                 & (pl.col('end_date').dt.day() == 31)
                 & (pl.col('report_type') == '1') & (pl.col('comp_type') == '1'))
                 .select(*structural, *fields[table]) for table, history in
                 [('income', income_history), ('balancesheet', balance_history)]}
    frames, eligibility, quarantines = [], [], []
    name = 'pit_annual_zscore'
    keys = ['symbol', 'end_date']
    for date in signal_dates:
        anchors = histories['income'].filter(pl.col('available_date') < date).group_by('symbol').agg(
            pl.col('end_date').max())
        selected = {table: select_financial_revisions_as_of(histories[table], dataset=table, as_of=date)
                    for table in ('income', 'balancesheet')}
        cross = pl.DataFrame({'symbol': candidate_symbols}).join(anchors, on='symbol', how='left')
        for table, selection in selected.items():
            cross = cross.join(selection.selected.select(*keys, *fields[table]),
                               on=keys, how='left', validate='m:1')
            quarantines.append(selection.quarantined.with_columns(pl.lit(date).alias('as_of'),
                                                                 pl.lit(table).alias('dataset')))
        cross = compute_annual_zscore(cross.with_columns(pl.lit(date).alias('trade_date')),
                                     daily_basic.filter(pl.col('trade_date') == date))
        cross = cross.with_columns(
            pl.when(pl.col('end_date') >= pl.lit(date).dt.offset_by('-18mo'))
            .then(pl.col(name)).otherwise(None).alias(name),
            pl.col('end_date').alias('financial_period_end'))
        frames.append(cross.drop('end_date'))
        eligibility.append(cross.select(pl.col('trade_date').alias('as_of'), 'symbol', 'financial_period_end',
            pl.lit(name).alias('factor'),
            pl.when(pl.col(name).is_finite().fill_null(False)).then(pl.lit('VALID'))
            .otherwise(pl.lit('MISSING_INVALID_OR_STALE_ANNUAL_OR_MARKET_VALUE')).alias('status')))
    return PITQualitySignalResult(factors=pl.concat(frames).sort('trade_date', 'symbol'),
        eligibility=pl.concat(eligibility), quarantined=pl.concat(quarantines, how='diagonal_relaxed'))
