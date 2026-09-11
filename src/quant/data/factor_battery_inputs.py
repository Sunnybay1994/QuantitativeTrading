"""Read a bounded year of battery controls, tradability and monthly labels."""
import bisect
import datetime as dt
from pathlib import Path

import polars as pl

from quant.data.factor_panels import available_sessions, read_factor_inputs, read_factor_industry
from quant.data.refresh_stocks import read_stock_data
from quant.data.stock_paper_inputs import read_stock_paper_calendar
from quant.research.factor_battery_universe import prepare_battery_universe
from quant.research.factor_labels import build_next_rebalance_open_labels


def read_battery_execution(*, data_root: Path, refresh_config: Path, snapshot: str,
                           start: dt.date, end: dt.date, symbols: list[str]) -> dict[str, pl.DataFrame]:
    """Read the published execution inputs for one bounded replay."""
    if start > end or not symbols or Path(snapshot).name != snapshot or snapshot in (".", ".."):
        raise ValueError("Invalid battery execution selection")
    folder = data_root / "clean/stock_execution" / snapshot
    result = {name: pl.read_parquet(folder / f"{name}.parquet").filter(pl.col("symbol").is_in(symbols))
              for name in ("instruments", "dividends", "limits", "suspensions")}
    if set(result["instruments"]["symbol"]) != set(symbols):
        raise ValueError("Missing battery execution instruments")
    calendar = read_stock_paper_calendar(data_root)
    previous = calendar.filter(pl.col("is_open") & (pl.col("date") < start))["date"].max()
    read_start = previous if isinstance(previous, dt.date) else start
    result["bars"] = read_stock_data(data_root=data_root, config=refresh_config, table="bar_1d",
                                    start=read_start, end=end).filter(pl.col("symbol").is_in(symbols))
    result["calendar"] = calendar.filter(pl.col("date").is_between(read_start, end))
    for name in ("limits", "suspensions"):
        result[name] = result[name].filter(pl.col("trade_date").is_between(start, end))
    # Keep pre-start record dates for delayed corporate actions; the account
    # requires an actual earlier holdings snapshot rather than inventing one.
    result["dividends"] = result["dividends"].filter(
        (pl.col("ex_date") >= start) & (pl.col("record_date") <= end))
    return result


def read_battery_symbols(data_root: Path, *, start: dt.date, end: dt.date) -> list[str]:
    """Use all historical panel members, including subsequently delisted stocks."""
    paths = [data_root / f"factors/forward_returns/year={year}/data.parquet"
             for year in range(start.year, end.year+1)]
    return (pl.scan_parquet(paths).filter(pl.col("trade_date").is_between(start,end))
        .select("ts_code").unique().sort("ts_code").collect()["ts_code"].to_list())


def read_battery_factor_year(data_root: Path, *, factor: str, year: int,
                             known_through: dt.date) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Mask labels beyond the battery cutoff even if the stored panel is newer."""
    values = pl.read_parquet(data_root / "factors" / factor / f"year={year}/data.parquet").rename(
        {"ts_code": "symbol"}).filter(pl.col("trade_date") <= known_through)
    labels = pl.read_parquet(data_root / f"factors/forward_returns/year={year}/data.parquet").rename(
        {"ts_code": "symbol"}).filter(pl.col("trade_date") <= known_through)
    sessions = available_sessions(data_root, known_through)
    expressions = []
    for horizon in (1,5,10,20,60):
        cutoff = sessions[-horizon-2] if len(sessions) >= horizon+2 else dt.date.min
        expressions.append(pl.when(pl.col("trade_date") <= cutoff).then(pl.col(f"label_{horizon}"))
                           .otherwise(None).alias(f"label_{horizon}"))
    return values, labels.with_columns(expressions)


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
