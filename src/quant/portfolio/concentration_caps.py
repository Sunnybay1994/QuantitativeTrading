"""One frozen, cash-preserving concentration policy for monthly targets."""
import math

import polars as pl


def cap_targets(targets: pl.DataFrame, industries: pl.DataFrame, *,
                cash_buffer: float, single_stock_weight: float,
                industry_weight: float) -> pl.DataFrame:
    """Join industry at signal date, only reduce weights, and retain zero rows."""
    if not (0 <= cash_buffer < 1 and 0 < single_stock_weight <= 1
            and 0 < industry_weight <= 1):
        raise ValueError('Invalid concentration limits')
    keys = ['as_of', 'symbol']
    if targets.select(keys).is_duplicated().any() or industries.select(keys).is_duplicated().any():
        raise ValueError('Duplicate signal security')
    if any(not math.isfinite(w) or w < 0 for w in targets['weight']):
        raise ValueError('Invalid target weight')
    if targets.group_by('as_of').agg(pl.col('weight').sum()).filter(pl.col('weight') > 1+1e-10).height:
        raise ValueError('Target weights exceed capital')
    joined = targets.join(industries.select(*keys, 'industry_l1'), on=keys, how='left')
    joined = joined.with_columns(pl.when(
        pl.col('industry_l1').is_null() | (pl.col('industry_l1').str.strip_chars() == '')
    ).then(0.).otherwise(pl.col('weight').clip(upper_bound=single_stock_weight)).alias('weight'))
    joined = joined.with_columns(pl.col('weight').sum().over('as_of', 'industry_l1').alias('_sector'))
    joined = joined.with_columns((pl.col('weight') * pl.when(pl.col('_sector') > industry_weight)
        .then(industry_weight/pl.col('_sector')).otherwise(1.)).alias('weight'))
    joined = joined.with_columns(pl.col('weight').sum().over('as_of').alias('_total'))
    return joined.with_columns((pl.col('weight') * pl.when(pl.col('_total') > 1-cash_buffer)
        .then((1-cash_buffer)/pl.col('_total')).otherwise(1.)).alias('weight')).select(targets.columns)
