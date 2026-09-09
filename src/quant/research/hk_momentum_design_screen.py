"""Fixed multi-day HK momentum: gross-edge design screen before an account study."""

import argparse
import datetime as dt
import json
import math
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.hk_intraday_research_inputs import read_hk_design_inputs


def holding_return(first: float, last: float, start: dt.date, end: dt.date, events: list[dict[str, Any]]) -> float:
    units, cash = 1., 0.
    for event in events:
        if event["split"] != 1.:
            raise ValueError("Split price basis has not been verified")
        if start < event["date"] <= end:
            cash += units * event["cash"]
            units *= event["split"]
    return (units * last + cash) / first - 1


def screen(bars: pl.DataFrame, sessions: tuple[dt.date, ...], actions: dict[str, list[dict[str, Any]]],
           config: dict[str, Any]) -> tuple[pl.DataFrame, dict[str, Any]]:
    spec, definition = config["research"], config["signal"]
    if (definition["lookback_sessions"] != 20 or definition["top_k"] != 3
        or definition["hold_full_sessions"] != 5 or definition["signal_bar_start"] != "13:30"
        or definition["entry_bar_start"] != "14:30" or definition["positive_only"] is not True
        or definition["missing_signal_pool"] != "skip_cycle" or definition["missing_execution_quote"] != "fail"):
        raise ValueError("Unsupported HK design configuration")
    symbols = sorted(actions)
    if set(bars["symbol"]) != set(symbols):
        raise ValueError("Incomplete HK observation pool")
    selected = bars.filter(pl.col("trade_date") <= spec["design_end"]).with_columns(
        pl.col("bar_start").dt.strftime("%H:%M").alias("time"))
    selected = selected.filter(pl.col("time").is_in(["13:30", "14:30"]))
    if selected.select("symbol", "trade_date", "time").is_duplicated().any():
        raise ValueError("Duplicate HK design quotes")
    quotes = {(r["symbol"], r["trade_date"], r["time"]): r for r in selected.iter_rows(named=True)}
    def quote(symbol: str, date: dt.date, time: str) -> dict[str, Any] | None:
        row = quotes.get((symbol, date, time))
        if row is None or row["volume"] <= 0 or any(not math.isfinite(row[k]) or row[k] <= 0 for k in ("open", "close")):
            return None
        return row
    first_index = next(i for i, day in enumerate(sessions) if day >= spec["design_start"])
    rows, cycles, missing_signal_cycles, cash_cycles = [], 0, 0, 0
    for entry_index in range(first_index, len(sessions) - 5, 5):
        entry, exit_day = sessions[entry_index], sessions[entry_index + 5]
        if exit_day > spec["design_end"]:
            break
        if entry_index < 21:
            continue
        cycles += 1
        signal, reference = sessions[entry_index - 1], sessions[entry_index - 21]
        ranked = []
        for symbol in symbols:
            now, prior = quote(symbol, signal, "13:30"), quote(symbol, reference, "13:30")
            if now is None or prior is None:
                break
            score = holding_return(prior["close"], now["close"], reference, signal, actions[symbol])
            if score > 0:
                ranked.append((score, symbol))
        else:
            chosen = sorted(ranked, key=lambda r: (-r[0], r[1]))[:3]
            if not chosen:
                cash_cycles += 1
            for score, symbol in chosen:
                opening, closing = quote(symbol, entry, "14:30"), quote(symbol, exit_day, "14:30")
                if opening is None or closing is None:
                    raise ValueError(f"Selected execution quote unavailable: {symbol} {entry} {exit_day}")
                gross = holding_return(opening["open"], closing["open"], entry, exit_day, actions[symbol])
                cost = config["costs"]["round_trip_fraction"]
                rows.append({"symbol": symbol, "signal_date": signal, "reference_date": reference,
                    "entry_date": entry, "exit_date": exit_day, "score": score,
                    "entry_price": opening["open"], "exit_price": closing["open"], "gross_return": gross,
                    **{f"estimated_net_{m:g}x": gross - m * cost for m in config["costs"]["cost_multipliers"]}})
            continue
        missing_signal_cycles += 1
    trades = pl.DataFrame(rows)
    mean = sum(r["gross_return"] for r in rows) / len(rows) if rows else None
    ratio = mean / config["costs"]["round_trip_fraction"] if mean is not None else None
    passed = len(rows) >= config["screen"]["minimum_trades"] and ratio is not None and ratio >= config["screen"]["minimum_gross_to_cost"]
    return trades, {"hypothesis_id": spec["hypothesis_id"], "symbols": len(symbols), "cycles": cycles,
        "missing_signal_cycles": missing_signal_cycles, "cash_cycles": cash_cycles, "trades": len(rows),
        "mean_gross_return": mean, "gross_to_cost": ratio,
        "estimated_net_means": {f"{m:g}x": (sum(r[f"estimated_net_{m:g}x"] for r in rows) / len(rows) if rows else None)
                                for m in config["costs"]["cost_multipliers"]},
        "conclusion": "RESEARCH_ONLY" if passed else "REJECTED"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()
    payload = args.config.read_bytes()
    config = tomllib.loads(payload.decode("utf-8"))
    bars, sessions, actions = read_hk_design_inputs(args.data_root, Path(config["research"]["pool_config"]))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "config.toml").write_bytes(payload)
    trades, summary = screen(bars, sessions, actions, config)
    trades.write_parquet(args.output / "trades.parquet")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
