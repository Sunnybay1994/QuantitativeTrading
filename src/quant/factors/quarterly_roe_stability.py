"""Dispersion of quarterly parent ROE in a fixed sixty-calendar-quarter window."""

import polars as pl


def compute_quarterly_roe_stability(quarters: pl.DataFrame, balance: pl.DataFrame,
                                     anchors: pl.DataFrame) -> pl.DataFrame:
    """Missing quarters reduce the count; they never expand the window."""
    key = ['symbol', 'end_date']
    for frame in (quarters, balance):
        if frame.select(pl.struct(key).is_duplicated().any()).item():
            raise ValueError('Duplicate quarterly period')
    q = quarters.join(balance.select(*key, 'total_hldr_eqy_exc_min_int'), on=key, how='left').join(
        anchors.select('symbol', pl.col('end_date').alias('anchor_period')), on='symbol', how='inner')
    def index(col: str) -> pl.Expr:
        return pl.col(col).dt.year() * 4 + pl.col(col).dt.quarter()
    q = q.filter((index('end_date') <= index('anchor_period'))
                 & (index('end_date') > index('anchor_period') - 60)).with_columns(
        pl.when(pl.col('single_parent_income').is_finite()
                & pl.col('total_hldr_eqy_exc_min_int').is_finite()
                & (pl.col('total_hldr_eqy_exc_min_int') > 0))
        .then(pl.col('single_parent_income') / pl.col('total_hldr_eqy_exc_min_int'))
        .otherwise(None).alias('quarter_roe')).with_columns(
        pl.when(pl.col('quarter_roe').is_finite()).then(pl.col('quarter_roe')).otherwise(None).alias('quarter_roe'))
    summary = q.group_by('symbol').agg(pl.col('quarter_roe').count().alias('valid_quarters'),
                                      pl.col('quarter_roe').std(ddof=1).alias('pit_quarterly_roe_volatility'))
    return anchors.join(summary, on='symbol', how='left').with_columns(
        pl.col('valid_quarters').fill_null(0),
        pl.when(pl.col('valid_quarters') >= 12).then(pl.col('pit_quarterly_roe_volatility'))
        .otherwise(None).alias('pit_quarterly_roe_volatility'))
