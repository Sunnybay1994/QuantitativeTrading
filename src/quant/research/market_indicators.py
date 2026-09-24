"""Observable market dimensions, with explicit populations and past-only scaling."""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd
import polars as pl


def stock_features(bars: pl.DataFrame, basic: pl.DataFrame,
                   sessions: list[dt.date]) -> pl.DataFrame:
    """No present-day constituents; no return across a missing exchange session."""
    keys = ['symbol', 'trade_date']
    for frame in (bars, basic):
        if frame.select(keys).is_duplicated().any():
            raise ValueError('Duplicate stock/date input')
    if sessions != sorted(set(sessions)):
        raise ValueError('Ordered unique exchange sessions required')
    calendar = pl.DataFrame({'trade_date': sessions, 'session': range(len(sessions))})
    selected = bars.filter(pl.col('symbol').str.contains(r'^(60|68|00|30)\d{4}\.(SH|SZ)$'))
    p = selected.join(basic.select(*keys, 'turnover_rate', 'circulating_market_value'),
                      on=keys, how='left', validate='1:1').join(calendar, on='trade_date', how='inner')
    p = p.sort('symbol', 'trade_date').with_columns(
        (pl.col('close') * pl.col('adj_factor')).alias('adj_close'),
        ((pl.col('close') > 0) & pl.col('close').is_finite()
         & (pl.col('amount') > 0) & pl.col('amount').is_finite()
         & (pl.col('volume') > 0) & pl.col('volume').is_finite()
         & (pl.col('high') >= pl.col('close')) & (pl.col('low') <= pl.col('close'))
         & pl.col('high').is_finite() & pl.col('low').is_finite()
         & (pl.col('low') > 0) & (pl.col('adj_factor') > 0)
         & pl.col('adj_factor').is_finite()).fill_null(False).alias('valid'))
    p = p.with_columns(
        pl.when(pl.col('valid')).then(pl.col('adj_close')).alias('adj_close'),
        pl.when(pl.col('valid')).then(pl.col('amount')).alias('valid_amount'))
    p = p.with_columns(
        pl.when((pl.col('session') - pl.col('session').shift(1).over('symbol') == 1)
                & pl.col('valid') & pl.col('valid').shift(1).over('symbol'))
        .then(pl.col('adj_close') / pl.col('adj_close').shift(1).over('symbol') - 1).alias('return'),
        pl.col('adj_close').rolling_mean(20, min_samples=20).over('symbol').alias('ma20'),
        pl.col('valid_amount').shift(1).rolling_mean(20, min_samples=20).over('symbol').alias('past_amount20'),
        (pl.col('session') - pl.col('session').shift(19).over('symbol') == 19).alias('continuous20'),
        (pl.col('session') - pl.col('session').shift(20).over('symbol') == 20).alias('continuous21'),
        pl.when(pl.col('valid') & (pl.col('high') > pl.col('low')))
        .then(2 * (pl.col('close') - pl.col('low')) / (pl.col('high') - pl.col('low')) - 1)
        .alias('close_location'))
    p = p.with_columns((pl.col('return').abs() / (pl.col('valid_amount') / 1e6))
                       .rolling_mean(20, min_samples=20).over('symbol').alias('amihud20'))
    return p.with_columns(
        pl.when(pl.col('continuous20')).then(pl.col('ma20')).alias('ma20'),
        pl.when(pl.col('continuous21')).then(pl.col('past_amount20')).alias('past_amount20'),
        pl.when(pl.col('continuous20') & pl.col('ma20').is_not_null())
        .then((pl.col('adj_close') >= pl.col('ma20')).cast(pl.Float64)).alias('above_ma20'),
        pl.when(pl.col('continuous21')).then(pl.col('amihud20')).alias('amihud20'),
        pl.when(pl.col('continuous21')).then(pl.col('valid_amount') / pl.col('past_amount20'))
        .alias('amount_ratio20'),
        pl.when(pl.col('turnover_rate').is_finite() & (pl.col('turnover_rate') >= 0)
                & pl.col('valid')).then(pl.col('turnover_rate') / 100).alias('turnover_fraction'))


def aggregate_daily(panel: pl.DataFrame, minimum_stocks: int,
                    minimum_coverage: float) -> pl.DataFrame:
    """Coverage denominator = names observed in preceding 20 sessions or today.

    This is an observed active universe, not a verified listing/suspension census.
    Missing rows are never silently called suspended or assigned zero returns.
    """
    daily = panel.group_by('trade_date').agg(
        pl.col('symbol').n_unique().alias('observed_stocks'),
        pl.col('valid').sum().alias('valid_stocks'),
        pl.col('return').count().alias('return_stocks'),
        pl.col('above_ma20').count().alias('breadth_stocks'),
        pl.col('amihud20').count().alias('impact_stocks'),
        pl.col('turnover_fraction').count().alias('turnover_stocks'),
        pl.col('close_location').count().alias('location_stocks'),
        pl.col('valid_amount').sum().alias('amount_cny'),
        pl.col('amount_ratio20').median().alias('activity_ratio20'),
        pl.col('turnover_fraction').median().alias('turnover_median'),
        pl.col('amihud20').median().alias('amihud_median20_per_million'),
        pl.col('amihud20').mean().alias('amihud_mean20_per_million'),
        pl.col('above_ma20').mean().alias('breadth20'),
        ((pl.col('return') > 0).sum().cast(pl.Float64) - (pl.col('return') < 0).sum().cast(pl.Float64))
        .truediv(pl.col('return').count()).alias('advance_decline_balance'),
        pl.col('close_location').median().alias('close_location_median'),
        pl.col('return').std(ddof=1).alias('cross_section_dispersion'),
        (pl.col('valid_amount').top_k(20).sum() / pl.col('valid_amount').sum()).alias('top20_amount_share'),
    ).sort('trade_date')
    # O(rows), avoids a symbol x date grid and future universe membership.
    last_seen, denominators = {}, {}
    for rows in panel.select('session', 'trade_date', 'symbol').sort('session').partition_by('session'):
        seq = rows['session'][0]
        last_seen = {s: v for s, v in last_seen.items() if v >= seq - 20}
        last_seen.update(dict.fromkeys(rows['symbol'].to_list(), seq))
        denominators[rows['trade_date'][0]] = len(last_seen)
    daily = daily.with_columns(pl.col('trade_date').replace_strict(denominators)
                              .cast(pl.Int64).alias('reference_stocks'))
    daily = daily.with_columns((pl.col('valid_stocks') / pl.col('reference_stocks')).alias('coverage'))
    masks = {
        'advance_decline_balance': 'return_stocks', 'breadth20': 'breadth_stocks',
        'amihud_median20_per_million': 'impact_stocks', 'amihud_mean20_per_million': 'impact_stocks',
        'turnover_median': 'turnover_stocks', 'close_location_median': 'location_stocks',
        'cross_section_dispersion': 'return_stocks',
    }
    for metric, count in masks.items():
        daily = daily.with_columns(pl.when((pl.col(count) >= minimum_stocks)
            & (pl.col(count) / pl.col('reference_stocks') >= minimum_coverage))
            .then(pl.col(metric)).otherwise(None).alias(metric))
    return daily.with_columns(((pl.col('valid_stocks') >= minimum_stocks)
        & (pl.col('coverage') >= minimum_coverage)).alias('coverage_ok'))


def prior_percentiles(values: pd.Series, window: int, minimum: int) -> pd.Series:
    """Midrank vs finite observations in strictly preceding calendar rows."""
    if not 1 <= minimum <= window:
        raise ValueError('Invalid normalization window')
    x = values.to_numpy(dtype=float)
    result = np.full(len(x), np.nan)
    for i, value in enumerate(x):
        past = x[max(0, i - window):i]
        past = past[np.isfinite(past)]
        if np.isfinite(value) and len(past) >= minimum:
            result[i] = 100 * ((past < value).sum() + .5 * (past == value).sum()) / len(past)
    return pd.Series(result, index=values.index)


def score_states(daily: pl.DataFrame, benchmark: pl.DataFrame,
                 sessions: list[dt.date], settings: dict) -> pl.DataFrame:
    """Descriptive EOD features; output includes separate next-session eligibility."""
    if daily['trade_date'].is_duplicated().any() or benchmark['date'].is_duplicated().any():
        raise ValueError('Duplicate daily indicator or benchmark date')
    p = daily.to_pandas().set_index('trade_date').reindex(pd.to_datetime(sessions))
    p.index.name = 'trade_date'
    b = benchmark.to_pandas().set_index('date')['unit_nav'].reindex(p.index)
    p['benchmark_return'] = b.pct_change(fill_method=None)
    p['benchmark_vol20'] = p['benchmark_return'].rolling(20, min_periods=20).std() * np.sqrt(252)
    ma60, ma200 = b.rolling(60).mean(), b.rolling(200).mean()
    p['benchmark_return60'] = b / b.shift(60) - 1
    p['benchmark_ma200_distance'] = b / ma200 - 1
    valid = b.notna() & ma200.notna() & ma60.notna()
    p['trend'] = np.select([valid & (b > ma200) & (ma60 > ma200),
                            valid & (b < ma200) & (ma60 < ma200), valid],
                           ['up', 'down', 'mixed'], default='unknown')
    components = ['turnover_median', 'amihud_median20_per_million', 'advance_decline_balance',
                  'breadth20', 'close_location_median', 'benchmark_vol20']
    for name in components:
        p[name + '_percentile'] = prior_percentiles(p[name], settings['normalization_window'],
                                                   settings['minimum_history'])
    # All components required. Do not silently change weights when a source is absent.
    p['liquidity_score'] = (p['turnover_median_percentile'] + 100
                             - p['amihud_median20_per_million_percentile']) / 2
    p['sentiment_proxy_score'] = (p['advance_decline_balance_percentile']
        + p['breadth20_percentile'] + p['close_location_median_percentile']) / 3
    p['volatility_percentile'] = p['benchmark_vol20_percentile']
    low, high = settings['low_percentile'], settings['high_percentile']
    for metric, label in [('liquidity_score', 'liquidity'), ('sentiment_proxy_score', 'sentiment'),
                          ('volatility_percentile', 'volatility')]:
        p[label + '_state'] = np.select([p[metric] <= low, p[metric] >= high, p[metric].notna()],
                                        ['low', 'high', 'middle'], default='unknown')
    ready = p['coverage_ok'].eq(True) & p[['liquidity_score', 'sentiment_proxy_score',
                                          'volatility_percentile']].notna().all(axis=1) & valid
    stress = (p['volatility_percentile'] >= high) & ((p['liquidity_score'] <= low)
                                                    | (p['sentiment_proxy_score'] <= low))
    p['market_state'] = np.select([ready & stress,
        ready & (p['trend'] == 'up') & (p['breadth20'] > .5),
        ready & (p['trend'] == 'down') & (p['breadth20'] < .5), ready],
        ['stress', 'trend_up', 'trend_down', 'mixed'], default='unknown')
    p['effective_date'] = pd.Series(p.index, index=p.index).shift(-1)
    p['timing'] = 'historical_close_reconstruction_not_arrival_proof'
    return pl.from_pandas(p.reset_index()).with_columns(pl.col('trade_date').cast(pl.Date),
                                                       pl.col('effective_date').cast(pl.Date))


def realtime_snapshot(quotes: list[dict], reference: pl.DataFrame, *,
                      now: dt.datetime, settings: dict) -> dict:
    """Point-in-time breadth/activity only; no daily Amihud from partial-day totals.

    Normalized quotes may contain prev_close (exchange ex-rights reference),
    bid/ask, and past_same_time_amount. Missing fields stay unavailable.
    """
    if now.tzinfo is None:
        raise ValueError('Timezone-aware now required')
    ref = {r['symbol']: r for r in reference.iter_rows(named=True)}
    if len(ref) != reference.height or not ref:
        raise ValueError('Require unique nonempty fixed prior-session reference')
    latest, rejected = {}, {}
    for q in quotes:
        symbol = q.get('symbol')
        reason = None
        try:
            provider, received = (q[k] if isinstance(q[k], dt.datetime) else
                                  dt.datetime.fromisoformat(q[k]) for k in ('provider_time', 'received_at'))
            if provider.tzinfo is None or received.tzinfo is None:
                raise ValueError('Naive timestamp')
            if provider > now or received > now or provider > received + dt.timedelta(seconds=2):
                reason = 'future_or_inconsistent_time'
            elif provider.astimezone(now.tzinfo).date() != now.date():
                reason = 'different_session'
            elif (now - provider).total_seconds() > settings['quote_max_age_seconds']:
                reason = 'stale'
            elif symbol not in ref:
                reason = 'outside_prior_reference'
            elif q.get('suspension', False):
                reason = 'suspended'
            elif any(not math.isfinite(float(q[k])) or float(q[k]) <= 0
                     for k in ('last_price', 'amount', 'volume')):
                reason = 'invalid_price_volume_amount'
            if reason is None and (symbol not in latest or received > latest[symbol][0]):
                latest[symbol] = (received, q)
        except (KeyError, ValueError, TypeError):
            reason = 'invalid_quote'
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
    fresh = [x[1] for x in latest.values()]
    reference_date = reference['trade_date'].max() if 'trade_date' in reference.columns else None
    price_returns, spreads, time_ratios, breadth = [], [], [], []
    for q in fresh:
        def positive(key):
            try:
                v = float(q.get(key))
                return v if math.isfinite(v) and v > 0 else None
            except (TypeError, ValueError):
                return None
        previous = positive('prev_close')
        if previous:
            price_returns.append(float(q['last_price']) / previous - 1)
            prior = ref[q['symbol']]
            if (prior.get('ma20') and prior.get('adj_close') and
                    (reference_date is None or prior['trade_date'] == reference_date)):
                adjusted_now = prior['adj_close'] * float(q['last_price']) / previous
                breadth.append(float(adjusted_now >= prior['ma20']))
        bid, ask = positive('bid'), positive('ask')
        if bid and ask and bid <= ask:
            spreads.append(1e4 * (ask - bid) / ((ask + bid) / 2))
        baseline = positive('past_same_time_amount')
        if baseline:
            try:
                baseline_end = dt.date.fromisoformat(str(q['baseline_end_date']))
                clock = q['baseline_clock']
                if baseline_end < now.date() and clock == provider_clock(q):
                    time_ratios.append(float(q['amount']) / baseline)
            except (KeyError, ValueError, TypeError):
                pass
    coverage = len(fresh) / len(ref)
    ready = coverage >= settings['minimum_coverage'] and len(fresh) >= settings['minimum_stocks']
    enough_returns = len(price_returns) >= settings['minimum_stocks'] and len(price_returns) / len(ref) >= settings['minimum_coverage']
    def sufficient(values):
        return len(values) >= settings['minimum_stocks'] and len(values) / len(ref) >= settings['minimum_coverage']
    return dict(as_of=now.isoformat(), mode='intraday_provisional', auto_trade=False,
        reference_stocks=len(ref), fresh_stocks=len(fresh), coverage=coverage,
        coverage_ok=ready, rejected=rejected,
        observed_cumulative_amount_cny=sum(float(q['amount']) for q in fresh) if fresh else None,
        advance_decline_balance=(sum(np.sign(price_returns)) / len(price_returns)) if enough_returns else None,
        return_reference_stocks=len(price_returns), spread_stocks=len(spreads),
        breadth_reference_stocks=len(breadth),
        above_prior_ma20_fraction=float(np.mean(breadth)) if sufficient(breadth) else None,
        median_spread_bps=float(np.median(spreads)) if sufficient(spreads) else None,
        same_time_amount_stocks=len(time_ratios),
        same_time_amount_ratio=float(np.median(time_ratios)) if sufficient(time_ratios) else None,
        market_state='unknown', liquidity_score=None, sentiment_proxy_score=None,
        classification_status='not_implemented',
        component_input_status='ready' if ready and enough_returns and sufficient(spreads)
            and sufficient(breadth) and sufficient(time_ratios) else 'incomplete',
        missing_components=[name for name,ok in [('fresh_coverage',ready),('returns',enough_returns),
            ('spread',sufficient(spreads)),('breadth',sufficient(breadth)),('same_clock_amount',sufficient(time_ratios))] if not ok],
        reason='Intraday classification mapping is not implemented; continuous component availability is reported separately. EOD states remain separate.',
        interpretation='Missing quotes are not flat returns; observed amount is not full-market turnover.')


def provider_clock(quote: dict) -> str:
    value = quote['provider_time']
    value = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value)
    return value.astimezone(dt.timezone(dt.timedelta(hours=8))).strftime('%H:%M')


def conditional_returns(states: pl.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    """Lagged descriptive slices, never a stitched strategy or selection rule."""
    if returns.index.has_duplicates:
        raise ValueError('Duplicate return dates')
    s = states.select('effective_date', 'market_state').drop_nulls('effective_date').to_pandas()
    s = s.set_index('effective_date')['market_state']
    rows = []
    for name in returns:
        p = pd.concat([returns[name].rename('return'), s], axis=1, join='inner').dropna()
        for (year, state), part in p.groupby([p.index.year, 'market_state']):
            rows.append(dict(strategy=name, year=int(year), state=state, sessions=len(part),
                months=part.index.to_period('M').nunique(), mean_daily_bps=1e4 * part['return'].mean(),
                positive_day_fraction=(part['return'] > 0).mean()))
    return pd.DataFrame(rows)
