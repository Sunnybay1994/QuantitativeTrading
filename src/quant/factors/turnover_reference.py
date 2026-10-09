"""Daily-turnover adjusted-price reference family, with fixed calendar windows.

Grinblatt-Han motivates survival weights; Riley-Summers-Duxbury uses daily
turnover. Local windows remain 260/52 calendar weeks with one completed week
excluded, not the latter paper's 1260-day implementation. Vendor adjustment
includes dividend reinvestment, so this is NOT actual holder/tax cost basis.
Current shares set each day's turnover denominator without inferring cohorts
created or cancelled by capital changes. No missing-price or suspension fill.
"""
import bisect
import datetime as dt

import numpy as np
import polars as pl

NAMES = ('turnover_reference_gain_260w_skip1w',
         'turnover_reference_gain_x_turnover_260w_skip1w')
CONTROLS = ('turnover_reference_equal_price_gain_260w',
            'turnover_reference_mean_turnover_52w',
            'turnover_reference_long_return_156w_skip52w')
WINDOW_WEEKS = 260
INTERACTION_WEEKS = 52
SCHEMA = {
    'symbol': pl.String, 'trade_date': pl.Date,
    **dict.fromkeys(NAMES + CONTROLS, pl.Float64),
    'window_start': pl.Date, 'cutoff_date': pl.Date,
    'expected_sessions': pl.Int64, 'valid_sessions': pl.Int64,
    'reference_price_at_cutoff_basis': pl.Float64,
    'weight_mass': pl.Float64, 'share_change_sessions': pl.Int64,
    'adjustment_change_sessions': pl.Int64, 'status': pl.String,
}


def _dates(values: tuple[dt.date, ...], name: str) -> None:
    if not values or any(type(x) is not dt.date for x in values):
        raise ValueError(f'{name} must contain dates')
    if values != tuple(sorted(set(values))):
        raise ValueError(f'{name} must be unique and increasing')


def _validate(frame: pl.DataFrame, numeric: list[str]) -> None:
    keys = ['symbol', 'trade_date']
    if not set(keys + numeric) <= set(frame.columns):
        raise ValueError('Missing daily columns')
    if frame.schema['trade_date'] != pl.Date or frame.schema['symbol'] != pl.String:
        raise ValueError('Require Date trade_date and String symbol')
    if frame.select(pl.any_horizontal(pl.col(c).is_null() for c in keys).any()).item():
        raise ValueError('Missing daily keys')
    if frame.filter(pl.col('symbol') == '').height or frame.select(keys).is_duplicated().any():
        raise ValueError('Duplicate or empty daily keys')
    if any(not frame.schema[c].is_numeric() for c in numeric):
        raise ValueError('Daily values must be numeric')


def formation_dates(signal: dt.date) -> tuple[dt.date, dt.date, dt.date]:
    """Return first Monday, final Friday, and 52-week interaction first Monday."""
    latest_friday = signal - dt.timedelta(days=(signal.weekday() - 4) % 7)
    last_friday = latest_friday - dt.timedelta(weeks=1)
    start = last_friday - dt.timedelta(weeks=WINDOW_WEEKS - 1, days=4)
    interaction_start = last_friday - dt.timedelta(weeks=INTERACTION_WEEKS - 1, days=4)
    return start, last_friday, interaction_start


def compute_turnover_reference(
    bars: pl.DataFrame, basic: pl.DataFrame, *,
    sessions: tuple[dt.date, ...], signal_dates: tuple[dt.date, ...],
) -> pl.DataFrame:
    """Compute both fixed signals and matched controls, preserving null states.

    Caller supplies the complete exchange calendar and completed month ends.
    Each stock/date in bars is a single raw OHLC observation; volume and
    total_shares must both be shares. Explicit zero-volume rows may carry a
    zero hazard; absent rows are unknown even if later weight becomes zero.
    Post-cutoff observations only validate current-quote availability. They do
    not enter the reference, comparison price, interaction or matched controls.
    """
    _dates(sessions, 'sessions'); _dates(signal_dates, 'signal_dates')
    if len({(d.year, d.month) for d in signal_dates}) != len(signal_dates):
        raise ValueError('Only one signal date per month')
    month_ends = {(d.year, d.month): d for d in sessions}
    if any(month_ends.get((d.year, d.month)) != d for d in signal_dates):
        raise ValueError('Signal dates must be supplied-calendar month ends')
    _validate(bars, ['close', 'adj_factor', 'volume'])
    _validate(basic, ['total_shares'])
    calendar_set = set(sessions)
    if not set(bars['trade_date']) <= calendar_set or not set(basic['trade_date']) <= calendar_set:
        raise ValueError('Observation outside exchange calendar')
    if bars.is_empty():
        return pl.DataFrame(schema=SCHEMA)
    keys = ['symbol', 'trade_date']
    observed = bars.select(*keys, 'close', 'adj_factor', 'volume').join(
        basic.select(*keys, 'total_shares'), on=keys, how='left', validate='1:1').sort(keys)
    locations = {d: i for i, d in enumerate(sessions)}
    anchors = []
    for signal in signal_dates:
        start, end, interaction_start = formation_dates(signal)
        anchors.append((signal, start, bisect.bisect_left(sessions, start),
                        bisect.bisect_right(sessions, end), bisect.bisect_left(sessions, interaction_start),
                        bisect.bisect_right(sessions, end-dt.timedelta(weeks=156))-1,
                        bisect.bisect_right(sessions, end-dt.timedelta(weeks=52))-1))
    rows = []
    for (symbol,), group in observed.group_by('symbol', maintain_order=True):
        close, adj, volume, shares = [np.full(len(sessions), np.nan) for _ in range(4)]
        index = np.asarray([locations[d] for d in group['trade_date']], dtype=int)
        for name, array in [('close', close), ('adj_factor', adj), ('volume', volume), ('total_shares', shares)]:
            array[index] = group[name].cast(pl.Float64).to_numpy()
        with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
            hazard = volume / shares
        valid = (np.isfinite(close) & (close > 0) & np.isfinite(adj) & (adj > 0)
                 & np.isfinite(volume) & (volume >= 0) & np.isfinite(shares) & (shares > 0)
                 & np.isfinite(hazard) & (hazard >= 0) & (hazard <= 1))
        for signal, start, left, right, interaction_left, long_start, long_end in anchors:
            row = dict.fromkeys(SCHEMA)
            row.update(symbol=symbol, trade_date=signal, window_start=start,
                       cutoff_date=sessions[right-1] if right else None,
                       expected_sessions=max(0, right-left),
                       valid_sessions=int(valid[left:right].sum()), status='valid')
            if sessions[0] > start or right <= left:
                row['status'] = 'insufficient_calendar_history'
            elif not valid[locations[signal]] or volume[locations[signal]] <= 0:
                row['status'] = 'invalid_current_quote'
            elif not valid[left:right].all():
                row['status'] = 'incomplete_or_invalid_window'
            else:
                h = hazard[left:right]
                survival = np.r_[1., np.cumprod(1. - h[:0:-1])]
                weights = h[::-1] * survival
                mass = float(weights.sum())
                row['weight_mass'] = mass
                row['share_change_sessions'] = int(np.count_nonzero(np.diff(shares[left:right])))
                row['adjustment_change_sessions'] = int(np.count_nonzero(np.diff(adj[left:right])))
                if mass <= 0:
                    row['status'] = 'zero_turnover_mass'
                else:
                    # Ratios use the cutoff's adjustment basis, never a future factor.
                    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
                        price_ratio = (close[left:right] / close[right-1]) * (adj[left:right] / adj[right-1])
                        reference_ratio = float(np.dot(weights, price_ratio[::-1]) / mass)
                        reference = reference_ratio * close[right-1]
                        gain = 1. - reference_ratio
                        mean_h = float(hazard[interaction_left:right].mean())
                        interaction = gain * mean_h
                        equal_gain = 1. - float(price_ratio.mean())
                        long_return = (close[long_end]/close[long_start])*(adj[long_end]/adj[long_start])-1.
                    values = [reference, gain, mean_h, interaction, equal_gain, long_return]
                    if not all(np.isfinite(v) for v in values) or reference <= 0:
                        row['status'] = 'nonfinite_result'
                    else:
                        row.update({NAMES[0]: gain, NAMES[1]: interaction,
                                    CONTROLS[0]: equal_gain, CONTROLS[1]: mean_h,
                                    CONTROLS[2]: float(long_return),
                                    'reference_price_at_cutoff_basis': reference})
            rows.append(row)
    return pl.DataFrame(rows, schema=SCHEMA).sort(keys)
