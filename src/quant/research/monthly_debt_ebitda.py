"""Annual debt/EBITDA with strict announcement lag and income-period anchoring."""

import datetime as dt
from typing import Any

import polars as pl

from quant.data.financial_pit import select_financial_revisions_as_of
from quant.factors.debt_ebitda import compute_debt_ebitda
from quant.research.pit_quality_research import PITQualitySignalResult


def validate_debt_ebitda(config: dict[str, Any]) -> None:
    expected = {'formula': 'interestdebt / ebitda', 'source_table': 'fina_indicator',
        'maximum_age_months': 18, 'latest_annual_period': 'latest_known_industrial_income_period_no_fallback',
        'income_usage': 'period_and_company_type_only', 'missing_component': 'exclude_symbol',
        'valid_values': 'finite_nonnegative_debt_positive_ebitda'}
    if (any(config.get('debt_ebitda', {}).get(k) != v for k, v in expected.items())
        or config['factors']['names'] != ['pit_annual_debt_ebitda'] or config['factors']['directions'] != [-1]):
        raise ValueError('Debt/EBITDA requires the fixed annual provider mapping and negative direction')


def build_monthly_debt_ebitda(
    *, income_history: pl.DataFrame, indicator_history: pl.DataFrame,
    signal_dates: tuple[dt.date, ...], candidate_symbols: tuple[str, ...],
) -> PITQualitySignalResult:
    """Require the latest known industrial annual period, with no older indicator fallback."""
    annual = (pl.col('end_date').dt.month() == 12) & (pl.col('end_date').dt.day() == 31)
    income = income_history.filter(annual & (pl.col('report_type') == '1') & (pl.col('comp_type') == '1'))
    indicator = indicator_history.filter(annual).select('symbol', 'ann_date', 'available_date',
                                                        'end_date', 'interestdebt', 'ebitda')
    frames, eligibility, quarantines = [], [], []
    keys, name = ['symbol', 'end_date'], 'pit_annual_debt_ebitda'
    for date in signal_dates:
        anchors = income.filter(pl.col('available_date') < date).group_by('symbol').agg(pl.col('end_date').max())
        selected = select_financial_revisions_as_of(indicator, dataset='fina_indicator', as_of=date)
        cross = pl.DataFrame({'symbol': candidate_symbols}).join(anchors, on='symbol', how='left').join(
            selected.selected.select(*keys, 'interestdebt', 'ebitda'), on=keys, how='left', validate='m:1')
        cross = compute_debt_ebitda(cross).with_columns(
            pl.when(pl.col('end_date') >= pl.lit(date).dt.offset_by('-18mo'))
            .then(pl.col(name)).otherwise(None).alias(name),
            pl.col('end_date').alias('financial_period_end'), pl.lit(date).alias('trade_date'))
        frames.append(cross.drop('end_date'))
        eligibility.append(cross.select(pl.col('trade_date').alias('as_of'), 'symbol', 'financial_period_end',
            pl.lit(name).alias('factor'), pl.when(pl.col(name).is_finite().fill_null(False)).then(pl.lit('VALID'))
            .otherwise(pl.lit('MISSING_INVALID_OR_STALE_ANNUAL_DEBT_EBITDA')).alias('status')))
        quarantines.append(selected.quarantined.with_columns(pl.lit(date).alias('as_of'),
                                                            pl.lit('fina_indicator').alias('dataset')))
    return PITQualitySignalResult(factors=pl.concat(frames).sort('trade_date', 'symbol'),
        eligibility=pl.concat(eligibility), quarantined=pl.concat(quarantines, how='diagonal_relaxed'))
