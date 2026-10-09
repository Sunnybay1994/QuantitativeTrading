"""Realized monthly labels for saved forecasts, using the exchange calendar."""
import datetime as dt
from pathlib import Path

import numpy as np
import polars as pl

from quant.data.factor_panels import available_sessions
from quant.data.refresh_stocks import read_stock_data
from quant.research.factor_labels import build_next_rebalance_open_labels


def residual_labels(
    labels: pl.DataFrame,
    controls: pl.DataFrame,
    *,
    label_column: str = "label",
    control_columns: list[str],
    industry_column: str | None = "industry_l1",
    minimum_symbols: int = 50,
) -> pl.DataFrame:
    """Cross-sectional OLS residual of ``label`` on controls (+ industry dummies) each month.

    Used only as a GP search target (B1). Admission batteries keep the original label.
    """
    if labels.select("symbol", "trade_date").is_duplicated().any():
        raise ValueError("duplicate label keys")
    if controls.select("symbol", "trade_date").is_duplicated().any():
        raise ValueError("duplicate control keys")
    needed = ["symbol", "trade_date", *control_columns]
    if industry_column:
        needed.append(industry_column)
    missing = [c for c in needed if c not in controls.columns]
    if missing:
        raise ValueError(f"controls missing columns: {missing}")
    joined = labels.select("symbol", "trade_date", label_column).join(
        controls.select(needed), on=["symbol", "trade_date"], how="inner", validate="1:1"
    )
    frames = []
    for (day,), section in joined.partition_by("trade_date", as_dict=True).items():
        valid = section.filter(pl.col(label_column).is_finite())
        for col in control_columns:
            valid = valid.filter(pl.col(col).is_finite())
        if industry_column:
            valid = valid.filter(pl.col(industry_column).is_not_null())
        if valid.height < minimum_symbols:
            continue
        y = valid[label_column].to_numpy().astype(float)
        x_cols = [np.ones((valid.height, 1)), valid.select(control_columns).to_numpy().astype(float)]
        if industry_column:
            industries = valid[industry_column].to_list()
            levels = sorted(set(industries))
            for level in levels[1:]:
                x_cols.append(np.array([[1.0] if ind == level else [0.0] for ind in industries], dtype=float))
        x = np.concatenate(x_cols, axis=1)
        beta, *_ = np.linalg.lstsq(x, y, rcond=None)
        resid = y - x @ beta
        frames.append(valid.select("symbol", "trade_date").with_columns(pl.Series(label_column, resid)))
    if not frames:
        raise ValueError("no months produced residual labels")
    out = pl.concat(frames).sort("trade_date", "symbol")
    # Preserve extra label metadata columns when present.
    meta = [c for c in labels.columns if c not in ("symbol", "trade_date", label_column)]
    if meta:
        out = out.join(labels.select("symbol", "trade_date", *meta), on=["symbol", "trade_date"], how="left")
    return out


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
