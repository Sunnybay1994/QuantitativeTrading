"""Identify required size and industry controls without imputing exposures."""
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
