"""Realized monthly labels for saved forecasts, using the exchange calendar."""
import datetime as dt
from pathlib import Path

import polars as pl

from quant.data.factor_panels import available_sessions
from quant.data.refresh_stocks import read_stock_data
from quant.research.factor_labels import build_next_rebalance_open_labels


def monthly_schedule(sessions: tuple[dt.date, ...], day: dt.date) -> tuple[dt.date, dt.date] | None:
    ends = [a for a, b in zip(sessions, sessions[1:]) if (a.year, a.month) != (b.year, b.month)]
    if day not in ends:
        return None
    following_month = (day.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    following = [d for d in ends if d.year == following_month.year and d.month == following_month.month]
    if not following:
        return None
    return sessions[sessions.index(day)+1], sessions[sessions.index(following[0])+1]


def read_forecast_labels(*, data_root: Path, refresh_config: Path, keys: pl.DataFrame,
                         known_through: dt.date) -> tuple[pl.DataFrame, tuple[dt.date, ...]]:
    sessions = available_sessions(data_root, known_through + dt.timedelta(days=100))
    schema = {'symbol': pl.String, 'trade_date': pl.Date, 'execution_date_rebalance': pl.Date,
              'exit_date_rebalance': pl.Date, 'label_rebalance': pl.Float64}
    frames = []
    for day in keys['trade_date'].unique().sort():
        schedule = monthly_schedule(sessions, day)
        if schedule is None or schedule[1] > known_through:
            continue
        entry, exit_day = schedule
        cohort = keys.filter(pl.col('trade_date') == day)
        next_signal = sessions[sessions.index(exit_day)-1]
        label_keys = pl.concat([cohort, cohort.with_columns(pl.lit(next_signal).alias('trade_date'))])
        bars = read_stock_data(data_root=data_root, config=refresh_config, table='bar_1d',
                               start=entry, end=exit_day).filter(pl.col('symbol').is_in(cohort['symbol'].to_list()))
        labels = build_next_rebalance_open_labels(factor_values=label_keys, bars=bars, sessions=sessions)
        frames.append(labels.filter(pl.col('trade_date') == day).select(list(schema)))
    return pl.concat(frames) if frames else pl.DataFrame(schema=schema), sessions
