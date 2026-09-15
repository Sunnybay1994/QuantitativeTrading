"""B29: reconstruct B23 trade paths using actual Southbound execution constraints."""

import argparse
import bisect
import datetime as dt
import json
import math
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.hk_connect_calendar import read_hk_connect_calendar
from quant.data.hk_connect_eligibility import read_eligibility_intervals
from quant.data.hk_intraday_research_inputs import read_hk_design_inputs
from quant.research.hk_momentum_design_screen import holding_return


def buy_routes_on(
    intervals: pl.DataFrame,
    symbols: list[str],
    date: dt.date,
) -> dict[str, tuple[str, ...]]:
    active = intervals.filter(
        pl.col("valid_from") <= date,
        pl.col("valid_to") >= date,
        pl.col("symbol").is_in(symbols),
    )
    if (
        active.height != 2 * len(symbols)
        or active.select("symbol", "route").unique().height != active.height
        or active["buy_eligible"].null_count()
        or set(active["route"]) != {"SH_CONNECT", "SZ_CONNECT"}
    ):
        raise ValueError(f"Unknown or conflicting route eligibility: {date}")
    return {
        symbol: tuple(
            route
            for route in ("SH_CONNECT", "SZ_CONNECT")
            if active.filter((pl.col("symbol") == symbol) & (pl.col("route") == route))[
                "buy_eligible"
            ].item()
        )
        for symbol in symbols
    }


def screen(
    bars: pl.DataFrame,
    hk_sessions: tuple[dt.date, ...],
    actions: dict[str, list[dict[str, Any]]],
    calendar: pl.DataFrame,
    intervals: pl.DataFrame,
    config: dict[str, Any],
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, Any]]:
    spec, signal, execution = config["research"], config["signal"], config["execution"]
    if (
        signal["lookback_sessions"] != 20
        or signal["top_k"] != 3
        or signal["positive_only"] is not True
        or signal["signal_bar_start"] != "13:30"
        or signal["entry_bar_start"] != "14:30"
        or execution["hold_executable_sessions"] != 5
        or execution["cycle_stride"] != 5
        or config["costs"]["round_trip_fraction"] != 0.004
        or config["costs"]["cost_multipliers"] != [0.5, 1.0, 2.0]
        or config["screen"]["maximum_conclusion"] != "RESEARCH_ONLY"
    ):
        raise ValueError("Unsupported B29 frozen parameters")
    start, end = spec["design_start"], spec["design_end"]
    days = calendar.filter(pl.col("date").is_between(start, end))
    if (
        days.height != (end - start).days + 1
        or days["date"].n_unique() != days.height
        or days["can_execute_1430"].null_count()
    ):
        raise ValueError("Incomplete Southbound calendar")
    execution_days = tuple(days.filter("can_execute_1430")["date"].sort().to_list())
    if tuple(sorted(set(hk_sessions))) != hk_sessions:
        raise ValueError("HK signal sessions must be unique and sorted")
    if not set(execution_days).issubset(hk_sessions):
        raise ValueError("Executable Southbound date is not a complete HK session")
    symbols = sorted(actions)
    if set(bars["symbol"]) != set(symbols):
        raise ValueError("Incomplete HK observation pool")
    selected = (
        bars.filter(pl.col("trade_date") <= end)
        .with_columns(pl.col("bar_start").dt.strftime("%H:%M").alias("time"))
        .filter(pl.col("time").is_in(["13:30", "14:30"]))
    )
    if selected.select("symbol", "trade_date", "time").is_duplicated().any():
        raise ValueError("Duplicate HK design quotes")
    quotes = {
        (row["symbol"], row["trade_date"], row["time"]): row
        for row in selected.iter_rows(named=True)
    }

    def quote(symbol: str, date: dt.date, time: str) -> dict[str, Any] | None:
        row = quotes.get((symbol, date, time))
        if row is None or any(
            row.get(key) is None or not math.isfinite(row[key]) or row[key] <= 0
            for key in ("open", "close", "volume")
        ):
            return None
        return row

    trade_rows: list[dict[str, Any]] = []
    cycle_rows: list[dict[str, Any]] = []
    cost, multipliers = config["costs"]["round_trip_fraction"], config["costs"]["cost_multipliers"]
    for entry_index in range(0, len(execution_days) - 5, 5):
        entry, exit_day = execution_days[entry_index], execution_days[entry_index + 5]
        signal_index = bisect.bisect_left(hk_sessions, entry) - 1
        if signal_index < 20:
            raise ValueError(f"Insufficient pre-entry HK signal history: {entry}")
        signal_date, reference = hk_sessions[signal_index], hk_sessions[signal_index - 20]
        routes = buy_routes_on(intervals, symbols, entry)
        exit_routes = buy_routes_on(intervals, symbols, exit_day)
        ranked, missing = [], []
        for symbol in symbols:
            now, prior = quote(symbol, signal_date, "13:30"), quote(symbol, reference, "13:30")
            if now is None or prior is None:
                missing.append(symbol)
                continue
            score = holding_return(
                prior["close"], now["close"], reference, signal_date, actions[symbol]
            )
            if score > 0 and routes[symbol]:
                ranked.append((score, symbol))
        chosen = [] if missing else sorted(ranked, key=lambda item: (-item[0], item[1]))[:3]
        cycle_id = len(cycle_rows)
        cycle_gross = 0.0
        for score, symbol in chosen:
            opening, closing = quote(symbol, entry, "14:30"), quote(symbol, exit_day, "14:30")
            if opening is None or closing is None:
                raise ValueError(
                    f"Selected execution quote unavailable: {symbol} {entry} {exit_day}"
                )
            gross = holding_return(
                opening["open"], closing["open"], entry, exit_day, actions[symbol]
            )
            route = routes[symbol][0]
            # A buy-list removal does not forbid sale of shares already held.
            # Keep the acquisition route, including when the other route is eligible.
            trade_rows.append(
                {
                    "cycle_id": cycle_id,
                    "symbol": symbol,
                    "signal_date": signal_date,
                    "reference_date": reference,
                    "entry_date": entry,
                    "exit_date": exit_day,
                    "entry_route": route,
                    "exit_route": route,
                    "entry_buy_eligible": True,
                    "exit_route_buy_eligible": route in exit_routes[symbol],
                    "exit_sell_only": route not in exit_routes[symbol],
                    "hold_executable_sessions": 5,
                    "calendar_holding_days": (exit_day - entry).days,
                    "score": score,
                    "entry_price": opening["open"],
                    "exit_price": closing["open"],
                    "slot_weight": 1 / 3,
                    "gross_return": gross,
                    **{f"estimated_net_{m:g}x": gross - m * cost for m in multipliers},
                }
            )
            cycle_gross += gross / 3
        cycle_rows.append(
            {
                "cycle_id": cycle_id,
                "signal_date": signal_date,
                "reference_date": reference,
                "entry_date": entry,
                "exit_date": exit_day,
                "eligible_buy_names": sum(bool(value) for value in routes.values()),
                "positive_eligible_names": len(ranked) if not missing else None,
                "selected_names": len(chosen),
                "cash_slots": 3 - len(chosen),
                "missing_signal_symbols": ",".join(missing),
                "cycle_gross_return": cycle_gross,
                **{
                    f"cycle_estimated_net_{m:g}x": cycle_gross - len(chosen) / 3 * m * cost
                    for m in multipliers
                },
            }
        )
    if not cycle_rows:
        raise ValueError("No complete design cycles")
    trades = (
        pl.DataFrame(trade_rows)
        if trade_rows
        else pl.DataFrame(
            schema={
                "cycle_id": pl.Int64,
                "symbol": pl.String,
                "entry_date": pl.Date,
                "exit_date": pl.Date,
                "gross_return": pl.Float64,
            }
        )
    )
    mean = sum(row["gross_return"] for row in trade_rows) / len(trade_rows) if trade_rows else None
    ratio = mean / cost if mean is not None else None
    passed = (
        len(trade_rows) >= config["screen"]["minimum_trades"]
        and ratio is not None
        and ratio >= config["screen"]["minimum_gross_to_cost"]
    )
    summary = {
        "hypothesis_id": spec["hypothesis_id"],
        "study_kind": spec["study_kind"],
        "design_start": str(start),
        "design_end": str(end),
        "symbols": len(symbols),
        "execution_sessions": len(execution_days),
        "cycles": len(cycle_rows),
        "missing_signal_cycles": sum(bool(row["missing_signal_symbols"]) for row in cycle_rows),
        "cash_cycles": sum(row["selected_names"] == 0 for row in cycle_rows),
        "underfilled_nonempty_cycles": sum(0 < row["selected_names"] < 3 for row in cycle_rows),
        "trades": len(trade_rows),
        "sell_only_exits": sum(row["exit_sell_only"] for row in trade_rows),
        "mean_gross_return": mean,
        "gross_to_cost": ratio,
        "estimated_net_means": {
            f"{m:g}x": mean - m * cost if mean is not None else None for m in multipliers
        },
        "fixed_slot_mean_cycle_gross": sum(row["cycle_gross_return"] for row in cycle_rows)
        / len(cycle_rows),
        "fixed_slot_mean_cycle_net": {
            f"{m:g}x": sum(row[f"cycle_estimated_net_{m:g}x"] for row in cycle_rows)
            / len(cycle_rows)
            for m in multipliers
        },
        "conclusion": "RESEARCH_ONLY" if passed else "REJECTED",
        "limitation": spec["pool_limitation"],
    }
    return trades, pl.DataFrame(cycle_rows), summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()
    payload = args.config.read_bytes()
    config = tomllib.loads(payload.decode("utf-8"))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "config.toml").write_bytes(payload)
    try:
        bars, sessions, actions = read_hk_design_inputs(
            args.data_root, Path(config["research"]["pool_config"])
        )
        calendar = read_hk_connect_calendar(
            args.data_root, config["execution"]["calendar_snapshot"]
        )
        intervals = read_eligibility_intervals(
            args.data_root, config["execution"]["eligibility_snapshot"]
        )
        trades, cycles, summary = screen(bars, sessions, actions, calendar, intervals, config)
        trades.write_parquet(args.output / "trades.parquet")
        trades.write_csv(args.output / "trades.csv")
        cycles.write_csv(args.output / "cycles.csv")
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    except Exception as error:
        (args.output / "error.json").write_text(
            json.dumps(
                {
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "hypothesis_id": config["research"]["hypothesis_id"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        raise
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
