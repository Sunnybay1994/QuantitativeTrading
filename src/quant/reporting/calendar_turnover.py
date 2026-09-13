"""Calendar-year realized one-way turnover under the 2026-09-13 ruling."""
import datetime as dt

import polars as pl


def calendar_turnover(nav: pl.DataFrame, trades: pl.DataFrame) -> dict:
    """Half of gross fills divided by mean daily equity, without 252-day scaling.

    Include the first holding session and all subsequent cash sessions. Partial
    calendar years are explicitly marked and retained without extrapolation.
    """
    if (nav.is_empty() or nav['date'].n_unique() != nav.height
            or not nav['date'].is_sorted() or nav['equity'].null_count()
            or not nav['equity'].is_finite().all() or (nav['equity'] <= 0).any()):
        raise ValueError('Require ordered unique daily NAV and positive finite equity')
    if (trades['notional'].null_count() or not trades['notional'].is_finite().all()
            or (trades['notional'] < 0).any() or trades['date'].null_count()
            or trades.filter(~pl.col('date').is_in(nav['date'].implode())).height):
        raise ValueError('Require finite nonnegative fills on saved NAV dates')
    start = nav.filter(pl.col('market_value') > 0)['date'].min()
    if start is None:
        raise ValueError('No holding evidence')
    active = nav.filter(pl.col('date') >= start)
    years = active.with_columns(pl.col('date').dt.year().alias('year')).group_by('year').agg(
        pl.col('equity').mean().alias('mean_daily_equity'),
        pl.col('date').min().alias('first'), pl.col('date').max().alias('last'),
        pl.len().alias('sessions'))
    amounts = trades.filter(pl.col('date') >= start).with_columns(
        pl.col('date').dt.year().alias('year')).group_by('year').agg(
            (pl.col('notional').sum()/2).alias('one_way_notional'))
    annual = years.join(amounts, on='year', how='left').with_columns(
        pl.col('one_way_notional').fill_null(0.)).with_columns(
        (pl.col('one_way_notional')/pl.col('mean_daily_equity')).alias('turnover')).sort('year')
    rows = annual.to_dicts()
    for row in rows:
        # Session boundaries within a week of year boundaries include exchange holidays.
        row['partial_year'] = (row['first'] > dt.date(row['year'], 1, 7)
                               or row['last'] < dt.date(row['year'], 12, 24))
    return {'basis': 'calendar_year_half_gross_fills_over_mean_daily_equity',
            'annual': rows, 'median': annual['turnover'].median(),
            'maximum': annual['turnover'].max(), 'partial_years_extrapolated': False}


def turnover_passes(turnover: float, double_cost_excess: float) -> bool:
    return turnover <= 6. or (turnover <= 8. and double_cost_excess >= .05)
