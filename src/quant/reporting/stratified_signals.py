"""Past-only strata and cross-sectional diagnostics for existing saved scores."""
import datetime as dt
import math

import polars as pl

from quant.reporting.cycle_stress import benchmark_regimes
from quant.research.factor_battery_statistics import monthly_ic_summary, rank_ic_by_date


def assign_strata(controls: pl.DataFrame, *, quantiles: list[float], minimum_months: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    if len(quantiles) != 2 or not 0 < quantiles[0] < quantiles[1] < 1:
        raise ValueError('Require two increasing internal quantiles')
    if controls.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate control keys')
    panel = controls.with_columns((pl.col('trade_date').dt.year()
        + (pl.col('trade_date').dt.month() == 12).cast(pl.Int32)).alias('diagnostic_year'))
    monthly_amount = controls.filter(pl.col('eligible') & pl.col('amount20').is_finite()
        & (pl.col('amount20') > 0)).group_by('trade_date').agg(pl.col('amount20').median().alias('market_amount20'))
    rows = []
    for year in sorted(panel['diagnostic_year'].unique()):
        past = controls.filter(pl.col('eligible') & (pl.col('trade_date').dt.year() < year))
        row = {'diagnostic_year': year, 'last_training_date': past['trade_date'].max(),
               'training_months': past['trade_date'].n_unique()}
        for field in ('amount20', 'total_market_value'):
            valid = past.filter(pl.col(field).is_finite() & (pl.col(field) > 0))
            values = valid[field] if valid['trade_date'].n_unique() >= minimum_months else pl.Series([], dtype=pl.Float64)
            for index, quantile in enumerate(quantiles):
                row[f'{field}_q{index+1}'] = values.quantile(quantile, interpolation='linear') if len(values) else None
        past_market = monthly_amount.filter(pl.col('trade_date').dt.year() < year)
        row['market_amount_threshold'] = past_market['market_amount20'].median() if past_market.height >= minimum_months else None
        rows.append(row)
    thresholds = pl.from_dicts(rows, infer_schema_length=None)
    panel = panel.join(thresholds, on='diagnostic_year', how='left', validate='m:1').join(
        monthly_amount, on='trade_date', how='left', validate='m:1')
    for field, label in [('amount20', 'liquidity'), ('total_market_value', 'size')]:
        panel = panel.with_columns(pl.when(~pl.col(field).is_finite().fill_null(False)
            | (pl.col(field) <= 0) | pl.col(f'{field}_q1').is_null()).then(pl.lit('unknown'))
            .when(pl.col(field) <= pl.col(f'{field}_q1')).then(pl.lit('low'))
            .when(pl.col(field) <= pl.col(f'{field}_q2')).then(pl.lit('middle'))
            .otherwise(pl.lit('high')).alias(label))
    panel = panel.with_columns(pl.col('industry_l1').fill_null('unknown').alias('industry'),
        pl.when(pl.col('market_amount_threshold').is_null() | pl.col('market_amount20').is_null())
        .then(pl.lit('unknown')).when(pl.col('market_amount20') <= pl.col('market_amount_threshold'))
        .then(pl.lit('low')).otherwise(pl.lit('high')).alias('market_liquidity'))
    return panel, thresholds


def market_states(prices: pl.DataFrame) -> pl.DataFrame:
    """Daily states for realized returns; every input ends at the preceding close."""
    prices = prices.sort('date')
    if prices['date'].is_duplicated().any() or prices.filter(~pl.col('unit_nav').is_finite() | (pl.col('unit_nav') <= 0)).height:
        raise ValueError('Require unique positive benchmark prices')
    regimes = benchmark_regimes(prices.rename({'date': 'trade_date', 'unit_nav': 'close'}))
    observed = prices.with_columns(pl.col('unit_nav').pct_change().rolling_std(20).alias('vol20'))
    # Estimate each year's threshold strictly from completed earlier years.
    thresholds = []
    for year in sorted(prices['date'].dt.year().unique()):
        past = observed.filter(pl.col('date').dt.year() < year)['vol20'].drop_nulls()
        thresholds.append({'year': year, 'volatility_threshold': past.median() if len(past) >= 20 else None})
    daily = observed.with_columns(pl.col('date').dt.year().alias('year'),
        pl.col('date').shift(1).alias('signal_date'), pl.col('vol20').shift(1).alias('prior_vol20')).join(
        pl.from_dicts(thresholds, infer_schema_length=None), on='year', how='left', validate='m:1').join(
        regimes, on='date', how='left', validate='1:1')
    return daily.sort('date').with_columns(pl.when(pl.int_range(pl.len()) < 220).then(pl.lit('unknown'))
        .otherwise(pl.col('regime').fill_null('unknown')).alias('trend'),
        pl.when(pl.col('prior_vol20').is_null() | pl.col('volatility_threshold').is_null()).then(pl.lit('unknown'))
        .when(pl.col('prior_vol20') <= pl.col('volatility_threshold')).then(pl.lit('low'))
        .otherwise(pl.lit('high')).alias('volatility')).select(
            'date', 'signal_date', 'trend', 'volatility', 'prior_vol20', 'volatility_threshold')


def signal_diagnostics(scores: pl.DataFrame, controls: pl.DataFrame, labels: pl.DataFrame,
                       states: pl.DataFrame, *, name: str, end: dt.date, settings: dict) -> tuple[pl.DataFrame, pl.DataFrame]:
    if scores.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate diagnostic score keys')
    scores = scores.filter((pl.col('trade_date') <= end) & pl.col('score').is_finite())
    panel = scores.join(controls.select('symbol', 'trade_date', 'liquidity', 'size', 'industry', 'market_liquidity'),
        on=['symbol', 'trade_date'], how='left', validate='1:1').join(
        states.select(pl.col('signal_date').alias('trade_date'), 'trend', 'volatility').drop_nulls('trade_date'),
        on='trade_date', how='left', validate='m:1').join(labels, on=['symbol', 'trade_date'], how='left', validate='1:1')
    panel = panel.with_columns(pl.when(pl.col('trade_date') <= settings['training_end'])
        .then(pl.lit('development')).otherwise(pl.lit('later')).alias('period'))
    panel = panel.with_columns(pl.when(pl.col('period') == 'development').then(pl.lit(settings['training_end']))
        .otherwise(pl.lit(end)).alias('label_cutoff'))
    panel = panel.with_columns(pl.when(pl.col('exit_date_rebalance') <= pl.col('label_cutoff'))
        .then(pl.col('label_rebalance')).otherwise(None).alias('label'))
    monthly_frames, summaries = [], []
    for dimension in ('all', 'liquidity', 'size', 'industry', 'trend', 'volatility', 'market_liquidity'):
        data = panel.with_columns((pl.lit('all') if dimension == 'all' else pl.col(dimension).fill_null('unknown')).alias('stratum'))
        for (period, stratum), cohort in data.partition_by(['period', 'stratum'], as_dict=True).items():
            ic = rank_ic_by_date(cohort, score='score', label='label', minimum_symbols=settings['minimum_symbols'],
                minimum_paired_coverage=settings['minimum_paired_coverage'])
            # Top decile is fixed before observing which labels are available.
            ranked = cohort.with_columns((pl.col('score').rank('average').over('trade_date')
                / pl.len().over('trade_date')).alias('score_percentile'))
            top = ranked.filter(pl.col('score_percentile') > .9).group_by('trade_date').agg(
                pl.len().alias('top_count'), pl.col('label').is_finite().sum().alias('top_paired'),
                pl.col('label').filter(pl.col('label').is_finite()).mean().alias('top_mean_gross_return'))
            means = cohort.group_by('trade_date').agg(pl.col('label').filter(pl.col('label').is_finite()).mean().alias('cohort_mean_gross_return'))
            ic = ic.join(top, on='trade_date', how='left', validate='1:1').join(means, on='trade_date', validate='1:1')
            ic = ic.with_columns(pl.when(pl.col('rank_ic').is_not_null()
                & (pl.col('top_paired') / pl.col('top_count') >= settings['minimum_paired_coverage']))
                .then(pl.col('top_mean_gross_return') - pl.col('cohort_mean_gross_return')).otherwise(None).alias('top_gross_excess'))
            ic = ic.sort('trade_date')
            stats = monthly_ic_summary(ic['trade_date'].to_list(), ic['rank_ic'].to_list(), lag=settings['monthly_newey_west_lag'])
            info = {'series': name, 'period': period, 'dimension': dimension, 'stratum': stratum}
            summaries.append({**info, **stats, 'signal_months': ic.height, 'median_signal_count': ic['signal_count'].median(),
                'median_paired_coverage': ic['paired_coverage'].median(), 'mean_top_gross_excess': ic['top_gross_excess'].mean()})
            monthly_frames.append(ic.with_columns(*[pl.lit(value).alias(key) for key, value in info.items()]))
    return pl.concat(monthly_frames, how='diagonal_relaxed'), pl.from_dicts(summaries, infer_schema_length=None)


def conditional_returns(daily: pl.DataFrame, dimension: str) -> list[dict]:
    rows = []
    for (state,), frame in daily.partition_by(dimension, as_dict=True).items():
        returns = frame['daily_return']
        if not returns.is_finite().all() or (returns <= -1).any():
            raise ValueError('Invalid realized portfolio returns')
        benchmark = frame['benchmark_daily_return'] if 'benchmark_daily_return' in frame.columns else None
        if benchmark is not None and (benchmark.null_count() or not benchmark.is_finite().all() or (benchmark <= -1).any()):
            raise ValueError('Missing or invalid realized benchmark returns')
        rows.append({'dimension': dimension, 'state': state, 'sessions': frame.height,
            'mean_daily_return': returns.mean(), 'negative_day_fraction': (returns < 0).mean(),
            'log_return_contribution': sum(math.log1p(value) for value in returns),
            'mean_benchmark_daily_return': benchmark.mean() if benchmark is not None else None,
            'mean_daily_excess': (returns-benchmark).mean() if benchmark is not None else None,
            'log_relative_return_contribution': sum(math.log1p(a)-math.log1p(b)
                for a, b in zip(returns, benchmark, strict=True)) if benchmark is not None else None,
            'one_way_turnover_sum': frame['one_way_turnover'].sum(), 'fees': frame['fee'].sum(),
            'slippage_cost': frame['slippage_cost'].sum()})
    return rows
