"""Six annual profitability measures and the fixed rank-based quality aggregate."""

import polars as pl

from quant.factors.annual_cash_profitability import compute_annual_cash_profitability

COMPONENTS = ('gpoa', 'roe', 'roa', 'cfoa', 'gmar', 'low_accruals')


def annual_profitability_components(income: pl.DataFrame, cash: pl.DataFrame,
                                     balance: pl.DataFrame, anchors: pl.DataFrame) -> pl.DataFrame:
    """All components use the same anchor period, with independent missing inputs."""
    key = ['symbol', 'end_date']
    base = anchors.join(income.select(*key, 'n_income'), on=key, how='left', validate='1:1')
    values = compute_annual_cash_profitability(base, cash, balance).join(
        income.select(*key, 'n_income_attr_p', 'revenue', 'oper_cost'), on=key, how='left', validate='1:1'
    ).join(balance.select(*key, 'total_hldr_eqy_exc_min_int'), on=key, how='left', validate='1:1')

    def ratio(numerator: pl.Expr, denominator: str) -> pl.Expr:
        return pl.when(numerator.is_finite() & pl.col(denominator).is_finite()
                       & (pl.col(denominator) > 0)).then(numerator / pl.col(denominator)).otherwise(None)

    gross = pl.when(pl.col('revenue').is_finite() & (pl.col('revenue') >= 0)
                    & pl.col('oper_cost').is_finite() & (pl.col('oper_cost') >= 0)).then(
                        pl.col('revenue') - pl.col('oper_cost')).otherwise(None)
    values = values.with_columns(
        ratio(gross, 'total_assets').alias('gpoa'),
        ratio(pl.col('n_income_attr_p'), 'total_hldr_eqy_exc_min_int').alias('roe'),
        ratio(pl.col('n_income'), 'total_assets').alias('roa'),
        pl.col('pit_annual_cash_profitability').alias('cfoa'),
        ratio(gross, 'revenue').alias('gmar'),
        ratio(pl.col('depr_fa_coga_dpba') - pl.col('working_capital')
              + pl.col('prior_working_capital'), 'total_assets').alias('low_accruals'))
    return values.with_columns(pl.when(pl.col(c).is_finite()).then(pl.col(c)).otherwise(None).alias(c)
                               for c in COMPONENTS)


def _rank_zscore(frame: pl.DataFrame, column: str) -> pl.Series:
    ranks = frame[column].rank(method='average')
    deviation = ranks.std(ddof=0)
    if deviation is None or deviation == 0:
        return ranks * 0
    return (ranks - ranks.mean()) / deviation


def rank_annual_profitability(frame: pl.DataFrame) -> pl.DataFrame:
    """Average available component rank z-scores, then rank-standardize the aggregate."""
    work = frame.with_columns(pl.when(pl.col(c).is_finite()).then(pl.col(c)).otherwise(None).alias(c)
                              for c in COMPONENTS)
    for component in COMPONENTS:
        work = work.with_columns(_rank_zscore(work, component).alias('z_' + component))
    work = work.with_columns(
        pl.sum_horizontal(pl.col(c).is_not_null().cast(pl.Int32) for c in COMPONENTS).alias('valid_components'),
        pl.mean_horizontal('z_' + c for c in COMPONENTS).alias('mean_component_rank_zscore'))
    return work.with_columns(_rank_zscore(work, 'mean_component_rank_zscore').alias('pit_annual_profitability'))
