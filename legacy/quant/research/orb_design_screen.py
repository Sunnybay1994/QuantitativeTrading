"""Training-sample gross-edge screen for the fixed gold ETF ORB hypothesis."""

import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import Any, cast

import polars as pl

from quant.data.intraday_bars import validate_bars
from quant.data.intraday_research_inputs import read_etf_minutes
from quant.research.cost_map import round_trip_cost


def screen_orb(bars: pl.DataFrame, config: dict[str, Any]) -> tuple[pl.DataFrame, dict[str, Any]]:
    expected_signal = {"opening_range_end": "10:00", "last_signal_time": "14:30",
        "comparison": "close_strictly_above_opening_range_high", "entry": "next_bar_open",
        "exit": "14:55_bar_open", "maximum_round_trips_per_day": 1,
        "minimum_holding_bars": 1, "required_bars": 48}
    if config["signal"] != expected_signal:
        raise ValueError("Unsupported ORB design configuration")
    research = config["research"]
    selected = validate_bars(bars.filter(pl.col("trade_date").is_between(
        research["design_start"], research["design_end"])))
    if selected.is_empty() or selected["symbol"].n_unique() != 1:
        raise ValueError("ORB screen requires one nonempty symbol")
    expected_minutes = list(range(570, 690, 5)) + list(range(780, 900, 5))
    rows = []
    valid_days = 0
    for (day,), frame in selected.group_by("trade_date", maintain_order=True):
        frame = frame.sort("bar_start")
        starts = frame["bar_start"].to_list()
        if (frame.height != 48 or not frame["session_complete"].all()
            or [t.hour * 60 + t.minute for t in starts] != expected_minutes
            or any(t.second or t.microsecond for t in starts)
            or any(b - a != dt.timedelta(minutes=5) for a, b in zip(starts, frame["bar_end"]))):
            continue
        valid_days += 1
        candles = frame.to_dicts()
        opening_high = max(bar["high"] for bar in candles[:6])
        exit_bar = candles[-1]
        for index in range(6, 47):
            signal = candles[index]
            if signal["bar_end"].time() > dt.time(14, 30):
                break
            if signal["close"] <= opening_high:
                continue
            entry = candles[index + 1]
            if entry["bar_start"] >= exit_bar["bar_start"]:
                continue
            if entry["volume"] <= 0 or exit_bar["volume"] <= 0:
                break
            price = entry["open"]
            gross = exit_bar["open"] / price - 1
            cost = round_trip_cost(price, config["costs"])["round_trip_fraction"]
            rows.append({"symbol": signal["symbol"], "trade_date": day,
                "signal_time": signal["bar_end"], "entry_time": entry["bar_start"],
                "exit_time": exit_bar["bar_start"], "opening_high": opening_high,
                "signal_close": signal["close"], "entry_price": price, "exit_price": exit_bar["open"],
                "gross_return": gross, "estimated_cost_1x": cost,
                **{f"estimated_net_{m:g}x": gross - m * cost for m in config["costs"]["cost_multipliers"]}})
            break
    trades = pl.DataFrame(rows)
    gross_mean = cast(float, trades["gross_return"].mean()) if rows else None
    cost_mean = cast(float, trades["estimated_cost_1x"].mean()) if rows else None
    ratio = gross_mean / cost_mean if cost_mean and gross_mean is not None else None
    passed = bool(len(rows) >= config["screen"]["minimum_signals"]
                  and ratio is not None and ratio >= config["screen"]["minimum_gross_to_cost"])
    summary = {"symbol": selected["symbol"][0], "available_days": selected["trade_date"].n_unique(),
        "valid_days": valid_days, "signals": len(rows), "mean_gross_return": gross_mean,
        "mean_estimated_cost_1x": cost_mean, "gross_to_cost": ratio,
        "estimated_net_means": {f"{m:g}x": trades[f"estimated_net_{m:g}x"].mean() if rows else None
                                for m in config["costs"]["cost_multipliers"]},
        "conclusion": "RESEARCH_ONLY" if passed else "REJECTED"}
    return trades, summary


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
    summaries = []
    for symbol in config["research"]["symbols"]:
        bars = read_etf_minutes(args.data_root, symbol, "5m", "baostock")
        trades, summary = screen_orb(bars, config)
        trades.write_parquet(args.output / f"{symbol}_signals.parquet")
        summaries.append(summary)
    result = {"hypothesis_id": config["research"]["hypothesis_id"], "design_only": True,
              "summary": summaries}
    (args.output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
