"""Read a bounded year of battery controls, tradability and monthly labels."""
import bisect
import datetime as dt
from pathlib import Path

import polars as pl

from quant.data.factor_panels import available_sessions, read_factor_inputs, read_factor_industry
from quant.research.factor_battery_universe import prepare_battery_universe
from quant.research.factor_labels import build_next_rebalance_open_labels


def read_battery_year(*, data_root: Path, refresh_config: Path, limits_snapshot: str,
                      start: dt.date, end: dt.date, known_through: dt.date,
                      minimum_listing_days: int = 120, amount_window_sessions: int = 20,
                      amount_exclude_bottom_fraction: float = .2) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Read controls only through signal dates; later prices supply labels alone."""
    if start.year != end.year or start > end or end > known_through:
        raise ValueError("Battery inputs require a single year bounded by known prices")
    sessions = available_sessions(data_root, known_through)
    targets = tuple(day for day in sessions if start <= day <= end)
    if not targets:
        raise ValueError("No battery sessions in requested year")
    # Include the next month's last signal and its execution open for December labels.
    future = end.replace(day=1) + dt.timedelta(days=70)
    read_end = min(future, known_through)
    first = bisect.bisect_left(sessions, targets[0])
    read_start = sessions[max(0, first-amount_window_sessions+1)]
    panel, bars = read_factor_inputs(data_root, refresh_config, read_start, read_end, sessions)
    instruments = pl.concat([pl.read_parquet(data_root / f"clean/instrument/market={market}/data.parquet")
                             for market in ("SH", "SZ")])
    names = pl.read_parquet(data_root / "clean/stock_name_history/data.parquet")
    limits = pl.read_parquet(data_root / "clean/factor_execution" / limits_snapshot
                            / f"year={start.year}/limits.parquet")
    universe = prepare_battery_universe(bars.filter(pl.col("trade_date") <= end),
        instruments, names, limits, sessions=sessions, minimum_listing_days=minimum_listing_days,
        amount_window_sessions=amount_window_sessions,
        amount_exclude_bottom_fraction=amount_exclude_bottom_fraction)
    universe = universe.filter(pl.col("trade_date").is_between(start, end))
    controls = read_factor_industry(data_root, panel.filter(pl.col("trade_date").is_between(start, end)))
    controls = controls.select("symbol", "trade_date", "total_market_value", "industry_l1")
    universe = universe.join(controls, on=["symbol", "trade_date"], how="left", validate="1:1")
    # Determine completed month ends from the complete exchange calendar, not
    # from observed symbols or the last date present in a particular factor.
    calendar = available_sessions(data_root, known_through + dt.timedelta(days=40))
    month_ends = {previous for previous, following in zip(calendar, calendar[1:])
                  if (previous.year, previous.month) != (following.year, following.month)}
    monthly_keys = panel.filter(pl.col("trade_date").is_in(month_ends)).select("symbol", "trade_date")
    if monthly_keys.is_empty():
        monthly = pl.DataFrame(schema={"symbol": pl.String, "trade_date": pl.Date,
            "execution_date_rebalance": pl.Date, "exit_date_rebalance": pl.Date,
            "label_rebalance": pl.Float64})
    else:
        monthly = build_next_rebalance_open_labels(factor_values=monthly_keys, bars=bars, sessions=sessions)
        monthly = monthly.filter(pl.col("trade_date").is_between(start,end)).select(
            "symbol", "trade_date", "execution_date_rebalance", "exit_date_rebalance", "label_rebalance")
    return universe, monthly
