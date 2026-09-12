"""Versioned SUE values gated by the latest disclosed company/report context."""

import datetime as dt

import polars as pl

from quant.data.sue_input_quality import diagnose_sue_report_context
from quant.research.monthly_sue import build_monthly_sue
from quant.research.pit_quality_research import PITQualitySignalResult

NAME = 'pit_sue8_context_v2'
_FACTOR_SCHEMA = {'symbol': pl.String, 'trade_date': pl.Date,
                  'financial_period_end': pl.Date, NAME: pl.Float64}
_ELIGIBILITY_SCHEMA = {'as_of': pl.Date, 'symbol': pl.String, 'financial_period_end': pl.Date,
    'factor': pl.String, 'status': pl.String, 'reason': pl.String, 'legacy_status': pl.String,
    'legacy_factor_value': pl.Float64, 'latest_report_end': pl.Date,
    'latest_available_date': pl.Date, 'latest_comp_type': pl.String,
    'latest_comp_types': pl.String, 'report_context': pl.String,
    'period_matches_context': pl.Boolean, 'suppressed_legacy_value': pl.Boolean}


def build_monthly_sue_context_v2(
    *, income_history: pl.DataFrame, signal_dates: tuple[dt.date, ...],
    candidate_symbols: tuple[str, ...],
) -> PITQualitySignalResult:
    """Reuse the original formula/announcement chain; suppress unsupported old anchors.

    The latest type-1 report is chosen before filtering company type, using
    available_date strictly before each signal. Economic revision conflicts and
    the original SUE numerical computation remain owned by build_monthly_sue.
    """
    if (type(signal_dates) is not tuple or any(type(date) is not dt.date for date in signal_dates)
            or len(signal_dates) != len(set(signal_dates))
            or type(candidate_symbols) is not tuple or len(candidate_symbols) != len(set(candidate_symbols))
            or any(not isinstance(symbol, str) or not symbol for symbol in candidate_symbols)):
        raise ValueError('Require unique signal dates and candidate symbols')
    if not signal_dates or not candidate_symbols:
        quarantined = income_history.head(0).with_columns(
            pl.lit(None, dtype=pl.String).alias('quarantine_reason'),
            pl.lit(None, dtype=pl.Date).alias('as_of'))
        return PITQualitySignalResult(factors=pl.DataFrame(schema=_FACTOR_SCHEMA),
            eligibility=pl.DataFrame(schema=_ELIGIBILITY_SCHEMA), quarantined=quarantined)
    factors, eligibility, quarantines = [], [], []
    for date in signal_dates:
        pool = pl.DataFrame({'symbol': candidate_symbols}, schema={'symbol': pl.String}).with_columns(
            pl.lit(date).alias('trade_date'))
        context = diagnose_sue_report_context(pool=pool, income_history=income_history,
            factor_values=pool.with_columns(pl.lit(None, dtype=pl.Float64).alias('value')), as_of=date)
        # Pass the untouched history to retain all original economic fields and
        # conflict evidence. The original function calls compute_sue8 internally.
        original = build_monthly_sue(income_history=income_history, signal_dates=(date,),
                                     candidate_symbols=candidate_symbols)
        original_status = original.eligibility.select('symbol', pl.col('status').alias('legacy_status'))
        cross = (original.factors.rename({'pit_sue8': 'legacy_factor_value'})
            .join(original_status, on='symbol', how='left', validate='1:1')
            .join(context.drop('factor_value', 'unexpected_factor_value'),
                  on=['symbol', 'trade_date'], how='left', validate='1:1')
            .with_columns((pl.col('financial_period_end') == pl.col('latest_report_end'))
                          .fill_null(False).alias('period_matches_context')))
        cross = cross.with_columns(
            pl.when(pl.col('report_context') != 'industrial')
            .then(pl.concat_str(pl.lit('CONTEXT_'), pl.col('report_context').str.to_uppercase()))
            .when(pl.col('legacy_status') == 'QUARANTINED').then(pl.lit('QUARANTINED'))
            .when(~pl.col('period_matches_context')).then(pl.lit('CONTEXT_PERIOD_MISMATCH'))
            .otherwise(pl.col('legacy_status')).alias('status'),
        ).with_columns(
            pl.when(pl.col('status') == 'VALID').then(pl.col('legacy_factor_value'))
            .otherwise(None).cast(pl.Float64).alias(NAME),
            pl.when(pl.col('status') == 'VALID').then(pl.lit('CURRENT_INDUSTRIAL_REPORT'))
            .when(pl.col('status') == 'QUARANTINED').then(pl.lit('ORIGINAL_REVISION_CONFLICT'))
            .when(pl.col('status') == 'CONTEXT_PERIOD_MISMATCH')
            .then(pl.lit('LATEST_REPORT_DIFFERS_FROM_COMPUTED_FINANCIAL_PERIOD'))
            .when(pl.col('status') == 'MISSING_OR_ZERO_VARIANCE')
            .then(pl.lit('ORIGINAL_SUE_MISSING_OR_ZERO_VARIANCE'))
            .otherwise(pl.concat_str(pl.lit('LATEST_REPORT_CONTEXT_'), pl.col('report_context').str.to_uppercase()))
            .alias('reason'),
            (pl.col('legacy_factor_value').is_finite().fill_null(False) & (pl.col('status') != 'VALID'))
            .alias('suppressed_legacy_value'),
        )
        factors.append(cross.select(*_FACTOR_SCHEMA))
        eligibility.append(cross.with_columns(pl.col('trade_date').alias('as_of'), pl.lit(NAME).alias('factor'))
                           .select(*_ELIGIBILITY_SCHEMA))
        quarantines.append(original.quarantined)
    return PITQualitySignalResult(factors=pl.concat(factors).sort('trade_date', 'symbol'),
        eligibility=pl.concat(eligibility).sort('as_of', 'symbol'),
        quarantined=pl.concat(quarantines, how='diagonal_relaxed'))
