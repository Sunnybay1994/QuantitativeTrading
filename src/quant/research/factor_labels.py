"""Point-in-time next-open labels for cross-sectional factor research."""

from __future__ import annotations

import datetime as dt

import polars as pl

from quant.domain import Bar1dSchema


def build_next_open_factor_labels(
    *,
    factor_values: pl.DataFrame,
    bars: pl.DataFrame,
    sessions: tuple[dt.date, ...],
    horizons: tuple[int, ...] = (1, 5, 20),
) -> pl.DataFrame:
    """Attach open(t+1+h)/open(t+1)-1 without skipping missing sessions."""
    if (
        not isinstance(factor_values, pl.DataFrame)
        or factor_values.is_empty()
        or "symbol" not in factor_values.columns
        or "trade_date" not in factor_values.columns
        or type(sessions) is not tuple
        or not sessions
        or sessions != tuple(sorted(set(sessions)))
        or any(type(value) is not dt.date for value in sessions)
        or type(horizons) is not tuple
        or not horizons
        or horizons != tuple(sorted(set(horizons)))
        or any(type(value) is not int or value <= 0 for value in horizons)
    ):
        raise ValueError("invalid next-open label inputs")
    if factor_values.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("factor values contain duplicate symbol-date keys")
    clean_bars = Bar1dSchema.validate(bars).sort("symbol", "trade_date", "source")
    if clean_bars.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("label bars must have one source per symbol-date")
    calendar_rows: list[dict[str, object]] = []
    for index, as_of in enumerate(sessions):
        row: dict[str, object] = {"trade_date": as_of}
        for horizon in horizons:
            entry = index + 1
            exit_ = entry + horizon
            row[f"execution_date_{horizon}"] = sessions[entry] if entry < len(sessions) else None
            row[f"exit_date_{horizon}"] = sessions[exit_] if exit_ < len(sessions) else None
        calendar_rows.append(row)
    calendar = pl.DataFrame(calendar_rows, schema_overrides={
        name: pl.Date for name in calendar_rows[0]
    })
    opens = clean_bars.select(
        "symbol",
        "trade_date",
        (pl.col("open") * pl.col("adj_factor")).alias("adjusted_open"),
    )
    result = factor_values.join(calendar, on="trade_date", how="left")
    for horizon in horizons:
        entry_date = f"execution_date_{horizon}"
        exit_date = f"exit_date_{horizon}"
        entry_open = f"entry_open_{horizon}"
        exit_open = f"exit_open_{horizon}"
        result = result.join(
            opens.rename({"trade_date": entry_date, "adjusted_open": entry_open}),
            on=["symbol", entry_date],
            how="left",
        ).join(
            opens.rename({"trade_date": exit_date, "adjusted_open": exit_open}),
            on=["symbol", exit_date],
            how="left",
        )
        result = result.with_columns(
            (pl.col(exit_open) / pl.col(entry_open) - 1.0).alias(f"label_{horizon}")
        )
    return result.sort("trade_date", "symbol")


def build_next_rebalance_open_labels(
    *,
    factor_values: pl.DataFrame,
    bars: pl.DataFrame,
    sessions: tuple[dt.date, ...],
) -> pl.DataFrame:
    """Attach a non-overlapping open-to-next-rebalance-open return label.

    The current signal is executed at the next exchange-session open.  Its
    holding period ends at the next signal's execution open, so sparse monthly
    signals neither double-count overlapping 20-session returns nor invent a
    return for gaps between calendar months.
    """
    if (
        not isinstance(factor_values, pl.DataFrame)
        or factor_values.is_empty()
        or "symbol" not in factor_values.columns
        or "trade_date" not in factor_values.columns
        or factor_values.schema["trade_date"] != pl.Date
        or type(sessions) is not tuple
        or not sessions
        or sessions != tuple(sorted(set(sessions)))
        or any(type(value) is not dt.date for value in sessions)
    ):
        raise ValueError("invalid next-rebalance label inputs")
    if factor_values.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("factor values contain duplicate symbol-date keys")
    signal_dates = tuple(factor_values.get_column("trade_date").unique().sort().to_list())
    session_index = {value: index for index, value in enumerate(sessions)}
    if any(value not in session_index for value in signal_dates):
        raise ValueError("signal date is not an exchange session")

    calendar_rows: list[dict[str, object]] = []
    for index, as_of in enumerate(signal_dates):
        entry_index = session_index[as_of] + 1
        next_signal = signal_dates[index + 1] if index + 1 < len(signal_dates) else None
        exit_index = session_index[next_signal] + 1 if next_signal is not None else None
        calendar_rows.append(
            {
                "trade_date": as_of,
                "execution_date_rebalance": (
                    sessions[entry_index] if entry_index < len(sessions) else None
                ),
                "exit_date_rebalance": (
                    sessions[exit_index]
                    if exit_index is not None and exit_index < len(sessions)
                    else None
                ),
            }
        )

    clean_bars = Bar1dSchema.validate(bars).sort("symbol", "trade_date", "source")
    if clean_bars.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("label bars must have one source per symbol-date")
    opens = clean_bars.select(
        "symbol",
        "trade_date",
        (pl.col("open") * pl.col("adj_factor")).alias("adjusted_open"),
    )
    return (
        factor_values.join(pl.DataFrame(calendar_rows, schema={
            "trade_date": pl.Date, "execution_date_rebalance": pl.Date,
            "exit_date_rebalance": pl.Date,
        }), on="trade_date", how="left")
        .join(
            opens.rename(
                {
                    "trade_date": "execution_date_rebalance",
                    "adjusted_open": "entry_open_rebalance",
                }
            ),
            on=["symbol", "execution_date_rebalance"],
            how="left",
        )
        .join(
            opens.rename(
                {
                    "trade_date": "exit_date_rebalance",
                    "adjusted_open": "exit_open_rebalance",
                }
            ),
            on=["symbol", "exit_date_rebalance"],
            how="left",
        )
        .with_columns(
            (pl.col("exit_open_rebalance") / pl.col("entry_open_rebalance") - 1.0).alias(
                "label_rebalance"
            )
        )
        .sort("trade_date", "symbol")
    )


__all__ = ["build_next_open_factor_labels", "build_next_rebalance_open_labels"]
