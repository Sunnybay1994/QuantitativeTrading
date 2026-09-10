"""QMJ appendix Z-score with explicit annual Chinese statement mappings."""

import polars as pl


def compute_annual_zscore(financial: pl.DataFrame, daily_basic: pl.DataFrame) -> pl.DataFrame:
    """All money inputs are yuan, including clean total_market_value; use exact dates."""
    keys = ['symbol', 'trade_date']
    values = financial.join(daily_basic.select(*keys, 'total_market_value'),
                            on=keys, how='left', validate='1:1').with_columns(
        (pl.col('total_cur_assets') - pl.col('total_cur_liab')).alias('working_capital'),
        (pl.col('surplus_rese') + pl.col('undistr_porfit')).alias('retained_earnings'))
    required = ['total_assets', 'total_cur_assets', 'total_cur_liab', 'surplus_rese',
                'undistr_porfit', 'ebit', 'revenue', 'total_market_value']
    valid = (pl.all_horizontal(pl.col(c).is_finite() for c in required)
             & (pl.col('total_assets') > 0) & (pl.col('total_market_value') > 0)
             & (pl.col('total_cur_assets') >= 0) & (pl.col('total_cur_liab') >= 0)
             & (pl.col('revenue') >= 0))
    score = (1.2 * pl.col('working_capital') + 1.4 * pl.col('retained_earnings')
             + 3.3 * pl.col('ebit') + .6 * pl.col('total_market_value') + pl.col('revenue')
             ) / pl.col('total_assets')
    return values.with_columns(pl.when(valid & score.is_finite()).then(score)
                               .otherwise(None).alias('pit_annual_zscore'))
