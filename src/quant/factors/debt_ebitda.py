"""Annual provider-reported interest-bearing debt relative to positive EBITDA."""

import polars as pl


def compute_debt_ebitda(frame: pl.DataFrame) -> pl.DataFrame:
    """Zero debt is valid; nonpositive earnings cannot masquerade as low leverage."""
    ratio = pl.col('interestdebt') / pl.col('ebitda')
    return frame.with_columns(pl.when(pl.col('interestdebt').is_finite() & (pl.col('interestdebt') >= 0)
        & pl.col('ebitda').is_finite() & (pl.col('ebitda') > 0) & ratio.is_finite())
        .then(ratio).otherwise(None).alias('pit_annual_debt_ebitda'))
