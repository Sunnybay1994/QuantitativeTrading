"""Annual PIT F-score for the frozen monthly factor experiment."""

import datetime as dt
from typing import Any

import polars as pl

from quant.data.financial_pit import select_financial_revisions_as_of
from quant.factors.annual_fscore import COMPONENTS, FIELDS, annual_fscore_components
from quant.factors.common_equity_issuance import ISSUANCE_CODES, NON_ISSUANCE_CODES, compute_no_common_equity_issue
from quant.research.pit_quality_research import PITQualitySignalResult


def validate_annual_fscore(config: dict[str, Any]) -> None:
    expected = {
        'components': list(COMPONENTS), 'aggregation': 'sum_all_nine_binary_signals', 'minimum_components': 9,
        'maximum_age_months': 18, 'latest_annual_period': 'latest_known_income_period_no_fallback',
        'net_income_mapping': 'n_income', 'roa_cfo_denominator': 'beginning_year_total_assets',
        'long_term_debt_mapping': 'lt_borr_plus_bond_payable_both_explicit_nonnegative',
        'leverage_denominator': 'average_beginning_end_year_total_assets',
        'liquidity': 'total_cur_assets_div_total_cur_liab', 'gross_margin': 'revenue_minus_oper_cost_div_revenue',
        'asset_turnover': 'revenue_div_beginning_year_total_assets', 'change_rule': 'strict_improvement',
        'issuance_window': 'anchor_fiscal_year',
        'issuance_availability': 'announcement_strictly_before_signal_and_event_in_completed_fiscal_year',
        'issuance_codes': sorted(ISSUANCE_CODES), 'non_issuance_codes': sorted(NON_ISSUANCE_CODES),
        'ambiguous_issuance': 'null_unless_explicit_issuance_already_proves_zero',
        'empty_or_unseen_event_history': 'null',
        'universe_adaptation': 'full_frozen_top800_without_high_book_to_market_screen',
        'missing_component': 'exclude_symbol',
    }
    if (any(config.get('annual_fscore', {}).get(k) != v for k, v in expected.items())
        or config['financials'].get('factor_family') != 'annual_fscore'
        or config['factors']['names'] != ['pit_annual_fscore'] or config['factors']['directions'] != [1]):
        raise ValueError('Unsupported annual F-score configuration')


def build_monthly_annual_fscore(
    *, income_history: pl.DataFrame, cash_history: pl.DataFrame, balance_history: pl.DataFrame,
    events: pl.DataFrame, event_coverage: pl.DataFrame,
    signal_dates: tuple[dt.date, ...], candidate_symbols: tuple[str, ...],
) -> PITQualitySignalResult:
    """Bind all nine signals to the latest annual period known before each signal."""
    structural = ['symbol', 'end_date', 'ann_date', 'f_ann_date', 'available_date',
                  'report_type', 'comp_type', 'update_flag']
    histories = {table: history.filter((pl.col('end_date').dt.month() == 12)
        & (pl.col('report_type') == '1') & (pl.col('comp_type') == '1')).select(*structural, *FIELDS[table])
        for table, history in [('income', income_history), ('cashflow', cash_history), ('balancesheet', balance_history)]}
    frames, eligibility, quarantines = [], [], []
    for date in signal_dates:
        anchors = histories['income'].filter(pl.col('available_date') < date).group_by('symbol').agg(pl.col('end_date').max())
        selected = {table: select_financial_revisions_as_of(histories[table], dataset=table, as_of=date)
                    for table in ('income', 'cashflow', 'balancesheet')}
        issuance = compute_no_common_equity_issue(events, event_coverage, anchors, as_of=date)
        values = annual_fscore_components(selected['income'].selected, selected['cashflow'].selected,
            selected['balancesheet'].selected, anchors, issuance)
        cross = pl.DataFrame({'symbol': candidate_symbols}).join(values, on='symbol', how='left').with_columns(
            pl.when(pl.col('end_date') >= pl.lit(date).dt.offset_by('-18mo'))
            .then(pl.col('pit_annual_fscore')).otherwise(None).alias('pit_annual_fscore'),
            pl.col('end_date').alias('financial_period_end'), pl.lit(date).alias('trade_date'))
        frames.append(cross.drop('end_date'))
        eligibility.append(cross.select(pl.col('trade_date').alias('as_of'), 'symbol', 'financial_period_end',
            'valid_components', 'issuance_status', pl.lit('pit_annual_fscore').alias('factor'),
            pl.when(pl.col('pit_annual_fscore').is_finite().fill_null(False)).then(pl.lit('VALID'))
            .otherwise(pl.lit('MISSING_INVALID_OR_STALE_ANNUAL')).alias('status')))
        for table, selection in selected.items():
            quarantines.append(selection.quarantined.with_columns(pl.lit(date).alias('as_of'), pl.lit(table).alias('dataset')))
    return PITQualitySignalResult(factors=pl.concat(frames).sort('trade_date', 'symbol'),
        eligibility=pl.concat(eligibility), quarantined=pl.concat(quarantines, how='diagonal_relaxed'))
