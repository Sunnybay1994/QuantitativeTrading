"""Identify required size and industry controls without imputing exposures."""
from pathlib import Path

import polars as pl


def neutralization_control_status(frame: pl.DataFrame) -> pl.DataFrame:
    """Preserve rows and mark controls used by the existing cross-section OLS.

    A finite positive market value and a nonempty industry string are required.
    These are control availability flags, not factor-value missingness flags.
    """
    required = {'total_market_value', 'industry_l1'}
    if not required <= set(frame.columns):
        raise ValueError('Neutralization needs total_market_value and industry_l1')
    if frame.schema['industry_l1'] not in (pl.String, pl.Null):
        raise ValueError('Industry controls must be strings')
    return frame.with_columns(
        (~pl.col('total_market_value').is_finite().fill_null(False)
         | (pl.col('total_market_value') <= 0).fill_null(False)).alias('size_missing'),
        (pl.col('industry_l1').is_null()
         | (pl.col('industry_l1').cast(pl.String) == '').fill_null(False)).alias('industry_missing'),
    ).with_columns((~pl.col('size_missing') & ~pl.col('industry_missing')).alias('controls_valid'))


def apply_recovered_market_values(*, universe: pl.DataFrame, recovery_path: Path) -> pl.DataFrame:
    """Overlay the 21 verified same-day recoveries in memory, preserving evidence.

    Pass the complete multi-date frozen universe. Existing positive finite market
    values and unknown keys are rejected; no input file or frame is modified.
    """
    keys = ['symbol', 'trade_date']
    required = {*keys, 'total_market_value'}
    if not required <= set(universe.columns):
        raise ValueError('Frozen universe is missing market-value keys or values')
    if (universe.select(keys).is_duplicated().any()
            or universe.select(pl.any_horizontal(pl.col(keys).is_null()).any()).item()):
        raise ValueError('Frozen universe needs unique non-null keys')
    recovery = pl.read_parquet(recovery_path)
    fields = {'symbol', 'as_of', 'total_market_value', 'recovery_status', 'source_date',
              'raw_path', 'evidence_reason', 'market_value_unit', 'normalization_pass',
              'mv_reconciliation_pass', 'close_match', 'fallback_used'}
    if not fields <= set(recovery.columns) or recovery.height != 21:
        raise ValueError('Require the complete 21-row verified market-value recovery table')
    recovery = recovery.rename({'as_of': 'trade_date'})
    if (recovery.select(keys).is_duplicated().any()
            or recovery.select(pl.any_horizontal(pl.col(keys).is_null()).any()).item()):
        raise ValueError('Recovery needs unique non-null keys')
    valid = ((pl.col('recovery_status') == 'recovered_same_day_raw')
             & (pl.col('source_date') == pl.col('trade_date'))
             & (pl.col('market_value_unit') == 'CNY')
             & pl.col('total_market_value').is_finite() & (pl.col('total_market_value') > 0)
             & pl.col('normalization_pass') & pl.col('mv_reconciliation_pass')
             & pl.col('close_match') & ~pl.col('fallback_used')
             & (pl.col('raw_path').str.len_chars() > 0) & (pl.col('evidence_reason').str.len_chars() > 0))
    if recovery.filter(~valid.fill_null(False)).height:
        raise ValueError('Recovery lacks positive CNY values or verified same-day evidence')
    if recovery.join(universe.select(keys), on=keys, how='anti').height:
        raise ValueError('Recovery contains unknown frozen-universe keys')
    existing = recovery.select(keys).join(universe.select(*keys, 'total_market_value'), on=keys, validate='1:1')
    if existing.filter(pl.col('total_market_value').is_finite().fill_null(False)
                       & (pl.col('total_market_value') > 0)).height:
        raise ValueError('Recovery would overwrite an existing valid market value')
    additions = recovery.select(*keys, pl.col('total_market_value').alias('_recovered_market_value'),
        pl.col('recovery_status').alias('market_value_recovery_status'),
        pl.col('source_date').alias('market_value_source_date'),
        pl.col('raw_path').alias('market_value_raw_path'),
        pl.col('evidence_reason').alias('market_value_evidence_reason'))
    added_columns = set(additions.columns) - set(keys)
    if added_columns & set(universe.columns) or 'market_value_recovered' in universe.columns:
        raise ValueError('Recovery diagnostic columns already exist')
    result = universe.join(additions, on=keys, how='left', validate='1:1', maintain_order='left').with_columns(
        pl.col('_recovered_market_value').is_not_null().alias('market_value_recovered'),
        pl.coalesce('_recovered_market_value', 'total_market_value').alias('total_market_value'),
    ).drop('_recovered_market_value')
    if {'size_missing', 'industry_missing', 'controls_valid'} & set(universe.columns):
        result = neutralization_control_status(result)
    return result
