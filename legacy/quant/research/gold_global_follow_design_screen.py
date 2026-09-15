"""B33 completed international gold daily signal, intraday design-cost screen."""

import argparse
import datetime as dt
import json
import math
import tomllib
from pathlib import Path
from typing import Any, cast

import polars as pl

from quant.data.intraday_bars import TZ, validate_bars
from quant.data.intraday_research_inputs import read_etf_daily, read_etf_minutes
from quant.research.cost_map import round_trip_cost


def select_gold_references(reference: pl.DataFrame, dates: list[dt.date]) -> pl.DataFrame:
    """Select the last completed reference strictly before each China open."""
    if (reference.schema.get("reference_date") != pl.Date
        or reference.schema.get("available_at") != pl.Datetime("us", "UTC")):
        raise ValueError("GC requires Date reference_date and UTC available_at")
    if reference.select("reference_date", "available_at").null_count().sum_horizontal().item():
        raise ValueError("Missing GC reference date or availability")
    if reference["reference_date"].is_duplicated().any():
        raise ValueError("Duplicate GC reference date")
    ordered = reference.sort("available_at", "reference_date")
    records: list[dict[str, Any]] = []
    for day in sorted(set(dates)):
        cutoff = dt.datetime.combine(day, dt.time(9, 30), TZ).astimezone(dt.UTC)
        known = ordered.filter(pl.col("available_at") < cutoff)
        row = known.row(-1, named=True) if known.height else None
        age = (day - row["reference_date"]).days if row else None
        value = row["reference_return"] if row else None
        price = row["close"] if row else None
        valid = (row is not None and age is not None and 0 <= age <= 4
                 and price is not None and math.isfinite(price) and price > 0
                 and value is not None and math.isfinite(value))
        records.append({"trade_date": day, "decision_at": cutoff,
                        "reference_date": row["reference_date"] if row else None,
                        "available_at": row["available_at"] if row else None,
                        "reference_return": value, "reference_age_days": age,
                        "valid_reference": valid, "signal": bool(valid and value is not None and value >= .005)})
    return pl.DataFrame(records, schema={"trade_date": pl.Date,
        "decision_at": pl.Datetime("us", "UTC"), "reference_date": pl.Date,
        "available_at": pl.Datetime("us", "UTC"), "reference_return": pl.Float64,
        "reference_age_days": pl.Int64, "valid_reference": pl.Boolean, "signal": pl.Boolean})


def _summarize(trades: pl.DataFrame, settings: dict[str, Any], multipliers: list[float]) -> dict[str, Any]:
    gross = cast(float, trades["gross_return"].mean()) if trades.height else None
    cost = cast(float, trades["estimated_cost_1x"].mean()) if trades.height else None
    ratio = gross / cost if gross is not None and cost else None
    passed = (trades.height >= settings["minimum_signals"] and ratio is not None
              and ratio >= settings["minimum_gross_to_cost"])
    return {"signals": trades.height, "mean_gross_return": gross,
            "mean_estimated_cost_1x": cost, "gross_to_cost": ratio,
            "estimated_net_means": {f"{m:g}x": trades[f"estimated_net_{m:g}x"].mean()
                                    if trades.height else None for m in multipliers},
            "conclusion": "RESEARCH_ONLY" if passed else "REJECTED"}


def screen_global_follow(
    bars: pl.DataFrame, daily: pl.DataFrame, reference: pl.DataFrame, config: dict[str, Any],
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, Any]]:
    """Compare fixed long continuation trades with unconditional intraday holds."""
    expected = {"reference_symbol": "GC=F", "reference_frequency": "1d",
        "reference_selection": "latest_available_at_strictly_before_09:30_Asia/Shanghai",
        "reference_return_threshold": .005, "maximum_reference_age_calendar_days": 4,
        "reference_age": "china_trade_date_minus_reference_date",
        "missing_reference_return": "no_signal_no_fallback", "weekends": "no_synthetic_rows",
        "entry": "09:35_bar_open", "exit": "14:55_bar_open", "direction": "long_only",
        "required_bars": 48, "maximum_round_trips_per_day": 1,
        "baseline": "every_complete_session_same_entry_exit_ignoring_reference"}
    if config["signal"] != expected:
        raise ValueError("B33 signal parameters are fixed before design returns")
    research = config["research"]
    selected = validate_bars(bars.filter(pl.col("trade_date").is_between(
        research["design_start"], research["design_end"])))
    if selected.is_empty() or selected["symbol"].n_unique() != 1:
        raise ValueError("B33 requires one nonempty symbol")
    if set(selected["source"]) != {"baostock"}:
        raise ValueError("B33 requires BaoStock 5-minute bars")
    symbol = selected["symbol"][0]
    daily_symbol = daily.filter(pl.col("symbol") == symbol) if "symbol" in daily.columns else daily
    dates = daily_symbol.filter(pl.col("trade_date").is_between(
        research["design_start"], research["design_end"]))["trade_date"].unique().sort().to_list()
    if not set(selected["trade_date"]).issubset(dates):
        raise ValueError("Minute session absent from daily reference")
    signals = select_gold_references(reference, dates)
    by_date = {r["trade_date"]: r for r in signals.to_dicts()}
    grid = list(range(570, 690, 5)) + list(range(780, 900, 5))
    rows: list[dict[str, Any]] = []
    valid_days = 0
    for (day,), frame in selected.group_by("trade_date"):
        frame = frame.sort("bar_start")
        starts = frame["bar_start"].to_list()
        if (frame.height != 48 or not frame["session_complete"].all()
            or [t.hour * 60 + t.minute for t in starts] != grid
            or any(t.second or t.microsecond for t in starts)
            or any(b - a != dt.timedelta(minutes=5) for a, b in zip(starts, frame["bar_end"]))):
            continue
        valid_days += 1
        entry, exit_bar = frame.row(1, named=True), frame.row(47, named=True)
        if entry["volume"] <= 0 or exit_bar["volume"] <= 0:
            continue
        gross = exit_bar["open"] / entry["open"] - 1
        cost = round_trip_cost(entry["open"], config["costs"])["round_trip_fraction"]
        rows.append({"symbol": symbol, **by_date[day], "entry_time": entry["bar_start"],
            "exit_time": exit_bar["bar_start"], "entry_price": entry["open"],
            "exit_price": exit_bar["open"], "gross_return": gross, "estimated_cost_1x": cost,
            **{f"estimated_net_{m:g}x": gross - m * cost for m in config["costs"]["cost_multipliers"]}})
    trades = pl.DataFrame(rows).sort("trade_date") if rows else pl.DataFrame()
    conditional = trades.filter(pl.col("signal")) if rows else trades
    stats = _summarize(conditional, config["screen"], config["costs"]["cost_multipliers"])
    baseline = _summarize(trades, config["screen"], config["costs"]["cost_multipliers"])
    baseline.pop("conclusion")
    return trades, signals, {"symbol": symbol, "daily_reference_sessions": len(dates),
        "complete_48bar_days": valid_days, "known_positive_reference_days": signals.filter(pl.col("signal")).height,
        "unconditional_baseline": baseline, **stats}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()
    # Data module owns the clean parquet read; no live provider call occurs here.
    from quant.data.gold_reference import RELATIVE_PATH, read_gold_reference

    payload = args.config.read_bytes()
    config = tomllib.loads(payload.decode("utf-8-sig"))
    reference = read_gold_reference(args.data_root)
    daily = read_etf_daily(args.data_root)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "config.toml").write_bytes(payload)
    summaries = []
    for symbol in config["research"]["symbols"]:
        bars = read_etf_minutes(args.data_root, symbol, "5m", "baostock")
        trades, signals, summary = screen_global_follow(bars, daily, reference, config)
        trades.write_parquet(args.output / f"{symbol}_sessions.parquet")
        signals.write_parquet(args.output / f"{symbol}_reference_selection.parquet")
        summaries.append(summary)
    result = {"hypothesis_id": config["research"]["hypothesis_id"], "design_only": True,
              "reference_input": str(args.data_root / RELATIVE_PATH), "summary": summaries}
    (args.output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
