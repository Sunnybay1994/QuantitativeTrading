"""Fixed morning VWAP-reversion design screen; no account or latency claims."""

import argparse
import datetime as dt
import json
import math
import tomllib
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import polars as pl

from quant.data.intraday_bars import validate_bars
from quant.data.intraday_research_inputs import read_etf_minutes
from quant.research.cost_map import round_trip_cost

TZ = ZoneInfo("Asia/Shanghai")


def morning_signal(bars: pl.DataFrame, *, day: dt.date, maximum_z: float) -> dict[str, Any]:
    """This function never uses observations after the morning decision time."""
    decision = dt.datetime.combine(day, dt.time(10, 30), TZ)
    morning = bars.filter((pl.col("trade_date") == day) & (pl.col("bar_end") <= decision)).sort("bar_start")
    valid = (morning.height == 12 and morning["bar_start"].to_list() == [
        dt.datetime.combine(day, dt.time(9, 30), TZ) + dt.timedelta(minutes=5 * i) for i in range(12)
    ])
    result: dict[str, Any] = {"trade_date": day, "decision_at": decision, "morning_vwap": None,
              "morning_std": None, "signal_close": None, "z": None, "signal": False}
    volume = cast(float, morning["volume"].sum())
    if not valid or volume <= 0:
        return result
    vwap = cast(float, morning["amount"].sum()) / volume
    std = cast(float | None, morning["close"].std(ddof=1))
    close = float(morning["close"][-1])
    z = (close - vwap) / std if std is not None and std > 0 else None
    result.update(morning_vwap=vwap, morning_std=std, signal_close=close, z=z,
                  signal=z is not None and math.isfinite(z) and z <= maximum_z)
    return result


def summarize(trades: pl.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    gross = cast(float | None, trades["gross_return"].mean())
    cost = cast(float | None, trades["estimated_cost_1x"].mean())
    ratio = gross / cost if gross is not None and cost else None
    passed = (trades.height >= config["screen"]["minimum_signals"] and ratio is not None
              and ratio >= config["screen"]["minimum_gross_to_cost"])
    return {"signals": trades.height, "mean_gross_return": gross, "mean_cost_1x": cost,
            "gross_to_cost": ratio, "conclusion": "RESEARCH_ONLY" if passed else "REJECTED",
            "estimated_net_means": {f"{m:g}x": trades[f"estimated_net_{m:g}x"].mean()
                                    for m in config["costs"]["cost_multipliers"]}}


def screen(bars: pl.DataFrame, config: dict[str, Any]) -> tuple[pl.DataFrame, dict[str, Any]]:
    research = config["research"]
    bars = validate_bars(bars.filter(pl.col("trade_date").is_between(
        research["design_start"], research["design_end"])))
    if bars.is_empty() or bars["symbol"].n_unique() != 1 or set(bars["source"]) != {"baostock"}:
        raise ValueError("B34 requires one symbol of BaoStock bars")
    rows = []
    grid = list(range(570, 690, 5)) + list(range(780, 900, 5))
    for (day,), frame in bars.group_by("trade_date"):
        frame = frame.sort("bar_start")
        starts = frame["bar_start"].to_list()
        if (frame.height != 48 or not frame["session_complete"].all()
            or [t.hour * 60 + t.minute for t in starts] != grid
            or any(t.second or t.microsecond for t in starts)
            or any(b - a != dt.timedelta(minutes=5) for a, b in zip(starts, frame["bar_end"]))):
            continue
        signal = morning_signal(frame, day=day, maximum_z=config["signal"]["maximum_z"])
        entry, exit_bar = frame.row(13, named=True), frame.row(47, named=True)
        if entry["volume"] <= 0 or exit_bar["volume"] <= 0:
            continue
        gross = exit_bar["open"] / entry["open"] - 1
        cost = round_trip_cost(entry["open"], config["costs"])["round_trip_fraction"]
        rows.append({"symbol": frame["symbol"][0], **signal, "entry_time": entry["bar_start"],
                     "exit_time": exit_bar["bar_start"], "entry_price": entry["open"],
                     "exit_price": exit_bar["open"], "gross_return": gross, "estimated_cost_1x": cost,
                     **{f"estimated_net_{m:g}x": gross - m * cost for m in config["costs"]["cost_multipliers"]}})
    if not rows:
        raise ValueError("No complete B34 sessions")
    trades = pl.DataFrame(rows, infer_schema_length=None).sort("trade_date")
    result = summarize(trades.filter(pl.col("signal")), config)
    baseline = summarize(trades, config)
    baseline.pop("conclusion")
    return trades, {"symbol": bars["symbol"][0], "complete_days": trades.height,
                    "unconditional_baseline": baseline, **result}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()
    payload = args.config.read_bytes()
    config = tomllib.loads(payload.decode("utf-8-sig"))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "config.toml").write_bytes(payload)
    summaries = []
    for symbol in config["research"]["symbols"]:
        bars = read_etf_minutes(args.data_root, symbol, "5m", "baostock")
        trades, summary = screen(bars, config)
        trades.write_parquet(args.output / f"{symbol}_sessions.parquet")
        summaries.append(summary)
    result = {"hypothesis_id": config["research"]["hypothesis_id"], "design_only": True, "summary": summaries}
    (args.output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
