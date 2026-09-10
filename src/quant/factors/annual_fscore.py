"""Nine binary annual financial signals under the fixed local accounting mapping."""

import polars as pl

COMPONENTS = ('positive_roa', 'positive_cfo', 'improving_roa', 'cash_above_income',
    'lower_leverage', 'improving_liquidity', 'no_common_equity_issue',
    'improving_gross_margin', 'improving_asset_turnover')
FIELDS = {'income': ('n_income', 'revenue', 'oper_cost'), 'cashflow': ('n_cashflow_act',),
    'balancesheet': ('total_assets', 'total_cur_assets', 'total_cur_liab', 'lt_borr', 'bond_payable')}


def annual_fscore_components(income: pl.DataFrame, cash: pl.DataFrame, balance: pl.DataFrame,
                            anchors: pl.DataFrame, issuance: pl.DataFrame) -> pl.DataFrame:
    """Use one annual anchor and exact prior-year periods, never substitute missing fields."""
    key = ['symbol', 'end_date']
    values = anchors.join(income.select(*key, *FIELDS['income']), on=key, how='left', validate='1:1')
    for table, frame in [('cashflow', cash), ('balancesheet', balance)]:
        values = values.join(frame.select(*key, *FIELDS[table]), on=key, how='left', validate='1:1')
    for table, frame in [('income', income), ('balancesheet', balance)]:
        prior = frame.select('symbol', pl.col('end_date').dt.offset_by('1y'),
            *[pl.col(c).alias('prior_' + c) for c in FIELDS[table]])
        values = values.join(prior, on=key, how='left', validate='1:1')
    values = values.join(balance.select('symbol', pl.col('end_date').dt.offset_by('2y'),
        pl.col('total_assets').alias('two_year_prior_assets')), on=key, how='left', validate='1:1')
    values = values.join(issuance, on='symbol', how='left', validate='1:1')

    def positive(column: str) -> pl.Expr:
        return pl.col(column).is_finite() & (pl.col(column) > 0)

    def ratio(numerator: pl.Expr, denominator: pl.Expr) -> pl.Expr:
        return pl.when(numerator.is_finite() & denominator.is_finite() & (denominator > 0)).then(
            numerator / denominator).otherwise(None)

    def average_assets(first: str, second: str) -> pl.Expr:
        return pl.when(positive(first) & positive(second)).then((pl.col(first) + pl.col(second)) / 2)

    def debt(prefix: str) -> pl.Expr:
        a, b = pl.col(prefix + 'lt_borr'), pl.col(prefix + 'bond_payable')
        return pl.when(a.is_finite() & b.is_finite() & (a >= 0) & (b >= 0)).then(a + b)

    def margin(prefix: str) -> pl.Expr:
        revenue, cost = pl.col(prefix + 'revenue'), pl.col(prefix + 'oper_cost')
        return pl.when(positive(prefix + 'revenue') & cost.is_finite() & (cost >= 0)).then((revenue - cost) / revenue)

    def liquidity(prefix: str) -> pl.Expr:
        assets, liabilities = pl.col(prefix + 'total_cur_assets'), pl.col(prefix + 'total_cur_liab')
        return pl.when(assets.is_finite() & (assets >= 0) & positive(prefix + 'total_cur_liab')).then(assets / liabilities)

    values = values.with_columns(
        ratio(pl.col('n_income'), pl.col('prior_total_assets')).alias('roa'),
        ratio(pl.col('prior_n_income'), pl.col('two_year_prior_assets')).alias('prior_roa'),
        ratio(pl.col('n_cashflow_act'), pl.col('prior_total_assets')).alias('cfo'),
        ratio(debt(''), average_assets('total_assets', 'prior_total_assets')).alias('leverage'),
        ratio(debt('prior_'), average_assets('prior_total_assets', 'two_year_prior_assets')).alias('prior_leverage'),
        liquidity('').alias('liquidity'), liquidity('prior_').alias('prior_liquidity'),
        margin('').alias('gross_margin'), margin('prior_').alias('prior_gross_margin'),
        pl.when(positive('revenue')).then(ratio(pl.col('revenue'), pl.col('prior_total_assets'))).alias('asset_turnover'),
        pl.when(positive('prior_revenue')).then(ratio(pl.col('prior_revenue'), pl.col('two_year_prior_assets'))).alias('prior_asset_turnover'))

    def binary(test: pl.Expr, *columns: str) -> pl.Expr:
        return pl.when(pl.all_horizontal(pl.col(c).is_finite() for c in columns)).then(test.cast(pl.Int8)).otherwise(None)

    values = values.with_columns(
        binary(pl.col('roa') > 0, 'roa').alias('positive_roa'),
        binary(pl.col('cfo') > 0, 'cfo').alias('positive_cfo'),
        binary(pl.col('roa') > pl.col('prior_roa'), 'roa', 'prior_roa').alias('improving_roa'),
        binary(pl.col('cfo') > pl.col('roa'), 'cfo', 'roa').alias('cash_above_income'),
        binary(pl.col('leverage') < pl.col('prior_leverage'), 'leverage', 'prior_leverage').alias('lower_leverage'),
        binary(pl.col('liquidity') > pl.col('prior_liquidity'), 'liquidity', 'prior_liquidity').alias('improving_liquidity'),
        binary(pl.col('gross_margin') > pl.col('prior_gross_margin'), 'gross_margin', 'prior_gross_margin').alias('improving_gross_margin'),
        binary(pl.col('asset_turnover') > pl.col('prior_asset_turnover'), 'asset_turnover', 'prior_asset_turnover').alias('improving_asset_turnover'),
        pl.when(pl.col('no_common_equity_issue').is_in([0, 1])).then(pl.col('no_common_equity_issue')).otherwise(None).alias('no_common_equity_issue'))
    values = values.with_columns(pl.sum_horizontal(pl.col(c).is_not_null().cast(pl.Int8) for c in COMPONENTS).alias('valid_components'))
    return values.with_columns(pl.when(pl.col('valid_components') == 9).then(
        pl.sum_horizontal(COMPONENTS).cast(pl.Float64)).otherwise(None).alias('pit_annual_fscore'))
