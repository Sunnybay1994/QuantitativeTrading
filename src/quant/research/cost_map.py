"""Compare ETF tick/commission costs and quality-filtered session statistics."""

import argparse
import datetime as dt
import json
import math
import tomllib
from pathlib import Path
from typing import Any, cast

import polars as pl

from quant.data.intraday_research_inputs import read_etf_daily, read_etf_minutes


def round_trip_cost(price: float, settings: dict[str, Any], multiplier: float = 1.0) -> dict[str, float]:
    if price <= 0 or not math.isfinite(price):
        raise ValueError("Price must be positive and finite")
    quantity = math.floor(settings["order_budget"] / (price * settings["board_lot"])) * settings["board_lot"]
    if quantity <= 0:
        raise ValueError("Order budget cannot purchase one board lot")
    notional = quantity * price
    commission = 2 * max(settings["commission_min"], notional * settings["commission_rate"])
    execution = 2 * quantity * settings["tick_size"] * settings["slippage_ticks_per_side"]
    return {"quantity": float(quantity), "notional": notional,
            "commission_fraction": commission / notional * multiplier,
            "execution_fraction": execution / notional * multiplier,
            "round_trip_fraction": (commission + execution) / notional * multiplier}


def compute_cost_map(daily: pl.DataFrame, members: list[dict[str, Any]], config: dict[str, Any]) -> pl.DataFrame:
    end, statistics, costs = config["research"]["as_of"], config["statistics"], config["costs"]
    last_dates = daily.filter(pl.col("trade_date") <= end)["trade_date"].unique().sort().tail(statistics["lookback_sessions"])
    rows = []
    for member in members:
        frame = daily.filter((pl.col("symbol") == member["symbol"]) & pl.col("trade_date").is_in(last_dates.implode())).sort("trade_date")
        if frame.height < statistics["minimum_valid_daily_rows"] or frame["trade_date"].max() != end:
            raise ValueError(f"Insufficient cost-map daily data for {member['symbol']}")
        price = float(frame["close"][-1])
        sigma = cast(float, frame["return"].std(ddof=1))
        estimate = round_trip_cost(price, costs)
        tick_fraction = costs["tick_size"] / price
        tick_ratio, full_ratio = sigma / (2 * tick_fraction), sigma / estimate["round_trip_fraction"]
        row = {"symbol": member["symbol"], "name": member["name"], "category": member["t0_category"],
               "date": str(end), "price": price, "one_tick_fraction": tick_fraction,
               "spread_fraction_assumption": costs["spread_ticks_assumption"] * tick_fraction,
               "daily_volatility": sigma, "average_daily_amount": frame["amount"].mean(),
               "sessions": frame.height, "traded_sessions": frame.filter(pl.col("volume") > 0).height,
               "tick_only_ratio": tick_ratio, "full_cost_ratio": full_ratio,
               "eligible_for_5m_research": tick_ratio >= config["screen"]["minimum_tick_ratio_for_5m"]
                   and sigma >= config["screen"]["minimum_daily_volatility_for_5m"], **estimate}
        for multiplier in costs["cost_multipliers"]:
            row[f"round_trip_cost_{multiplier:g}x"] = round_trip_cost(price, costs, multiplier)["round_trip_fraction"]
        rows.append(row)
    return pl.DataFrame(rows).sort("full_cost_ratio", descending=True)


def overnight_decomposition(daily: pl.DataFrame, start: dt.date, end: dt.date) -> pl.DataFrame:
    frame = daily.sort("symbol", "trade_date").with_columns(pl.col("close").shift(1).over("symbol").alias("_prior_close"))
    # Exclude ex-right/reference changes: this is a price decomposition, not a dividend ledger.
    frame = frame.filter(pl.col("trade_date").is_between(start, end) & (pl.col("volume") > 0)
        & (pl.col("open") > 0) & ((pl.col("pre_close") - pl.col("_prior_close")).abs() <= 1e-8))
    frame = frame.with_columns((pl.col("open") / pl.col("_prior_close")).log().alias("overnight_log_return"),
        (pl.col("close") / pl.col("open")).log().alias("intraday_log_return"))
    return frame.group_by("symbol").agg(pl.len().alias("days"),
        pl.col("overnight_log_return").mean(), pl.col("intraday_log_return").mean(),
        pl.col("overnight_log_return").std().alias("overnight_std"),
        pl.col("intraday_log_return").std().alias("intraday_std"),
        pl.corr("overnight_log_return", "intraday_log_return").alias("overnight_intraday_corr"),
    ).sort("symbol")


def aggregate_five_minute_bars(bars: pl.DataFrame) -> pl.DataFrame:
    """Aggregate complete sessions into the same five trading intervals as Yahoo."""
    complete = bars.group_by("trade_date").agg(pl.len().alias("n"),
        pl.col("bar_start").n_unique().alias("unique_n"), pl.col("session_complete").all()).filter(
            (pl.col("n") == 48) & (pl.col("unique_n") == 48) & pl.col("session_complete"))
    selected = bars.join(complete.select("trade_date"), on="trade_date").sort("bar_start")
    minute = pl.col("bar_start").dt.hour().cast(pl.Int32) * 60 + pl.col("bar_start").dt.minute()
    selected = selected.with_columns(pl.when(minute < 630).then(570).when(minute < 690).then(630)
        .when(minute < 810).then(780).when(minute < 870).then(810).otherwise(870).alias("_minute"))
    return selected.group_by("symbol", "trade_date", "_minute").agg(
        pl.col("bar_start").first(), pl.col("open").first(), pl.col("close").last(),
        pl.col("high").max(), pl.col("low").min(), pl.col("volume").sum(),
        pl.col("session_complete").all()).drop("_minute").sort("bar_start")


def hourly_profile(bars: pl.DataFrame, daily: pl.DataFrame, settings: dict[str, Any]) -> tuple[pl.DataFrame, dict[str, Any]]:
    symbol = bars["symbol"][0]
    stats = bars.group_by("trade_date").agg(pl.col("high").max(), pl.col("low").min(),
        pl.col("volume").sum(), pl.col("session_complete").all(), pl.len().alias("bars"))
    check = stats.join(daily.filter(pl.col("symbol") == symbol), on="trade_date", suffix="_daily").with_columns(
        (pl.col("volume") / pl.col("volume_daily").replace(0, None)).alias("volume_ratio"))
    valid = check.filter(pl.col("session_complete") & (pl.col("bars") == 5)
        & (pl.col("high") <= pl.col("high_daily") + settings["price_tolerance"])
        & (pl.col("low") >= pl.col("low_daily") - settings["price_tolerance"])
        & ((pl.col("volume_ratio") - 1).abs() <= settings["hourly_max_daily_volume_deviation"]))
    selected = bars.join(valid.select("trade_date"), on="trade_date", how="inner").with_columns(
        pl.col("bar_start").dt.strftime("%H:%M").alias("interval"),
        (pl.col("volume") / pl.col("volume").sum().over("trade_date")).alias("volume_share"),
        (pl.col("close") / pl.col("open")).log().pow(2).alias("squared_log_return"),
    ).with_columns(pl.when(pl.col("interval").is_in(["12:30", "13:00", "14:30"]))
                   .then(30.0).otherwise(60.0).alias("trading_minutes"))
    profile = selected.group_by("interval").agg(pl.len().alias("days"),
        pl.col("volume_share").mean(),
        (pl.col("volume_share") * 240 / pl.col("trading_minutes")).mean().alias("volume_rate_vs_daily_average"),
        (pl.col("squared_log_return") / pl.col("trading_minutes")).mean().alias("variance_per_trading_minute"),
    ).with_columns(pl.lit(symbol).alias("symbol")).sort("interval")
    return profile, {"symbol": symbol, "available_days": stats.height, "valid_days": valid.height,
                     "excluded_days": stats.height - valid.height}


def plot_map(costs: pl.DataFrame, profiles: pl.DataFrame, output: Path, symbols: list[str]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.titlelocation": "left"})
    fig, axes = plt.subplots(1, 2, figsize=(13, 7.5), gridspec_kw={"width_ratios": [1.2, 1]})
    left, right = axes
    ordered = costs.reverse()
    positions = np.arange(ordered.height)
    for row, y in zip(ordered.iter_rows(named=True), positions):
        left.plot([row["full_cost_ratio"], row["tick_only_ratio"]], [y, y], color="#C6C9CD", linewidth=1.2)
    left.scatter(ordered["tick_only_ratio"], positions, facecolors="white", edgecolors="#727980", label="Two ticks only", zorder=3)
    left.scatter(ordered["full_cost_ratio"], positions, color="#3568B0", label="Commission + two ticks", zorder=4)
    left.set_yticks(positions, ordered["symbol"].to_list())
    left.set_xlim(left=0)
    left.set_xlabel("Daily return volatility / round-trip cost")
    left.set_title("ETF cost comparison\n60 sessions through 8 Sep 2026; CNY 100k orders", fontsize=12, pad=17)
    left.grid(axis="x", color="#E7E9EC", linewidth=.7)
    left.legend(loc="lower right", fontsize=9, frameon=False)
    for index, (symbol, color) in enumerate(zip(symbols, ["#3568B0", "#C49A3A"], strict=True)):
        frame = profiles.filter(pl.col("symbol") == symbol).sort("interval")
        if frame.height != 5:
            continue
        right.bar(np.arange(5) + (index - .5) * .34, frame["volume_rate_vs_daily_average"], width=.32,
                  color=color, edgecolor="#33383E", linewidth=.5, label=f"{symbol} (n={frame['days'][0]})")
    right.set_xticks(np.arange(5), ["09:30\n60 min", "10:30\n60 min", "13:00\n30 min", "13:30\n60 min", "14:30\n30 min"])
    right.set_ylabel("Volume per minute / daily average")
    right.set_title("Gold ETF volume profile\nBaoStock 5-minute bars aggregated; Jan-Sep 2026", fontsize=12, pad=17)
    right.axhline(1, color="#535960", linewidth=1, linestyle="--")
    right.set_axisbelow(True)
    right.grid(axis="y", color="#E7E9EC", linewidth=.7)
    right.legend(loc="upper right", fontsize=9, frameon=False)
    fig.subplots_adjust(left=.09, right=.98, bottom=.13, top=.85, wspace=.35)
    fig.text(.09, .04, "Sources: Tushare daily and BaoStock 5-minute data. Spread is assumed; volatility is not expected trading profit.", fontsize=9, color="#535960")
    fig.savefig(output, dpi=170, facecolor="white")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/research/b5_cost_map_20260909.toml"))
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = tomllib.loads(args.config.read_text(encoding="utf-8"))
    members = tomllib.loads(Path(config["research"]["universe"]).read_text(encoding="utf-8"))["members"]
    daily = read_etf_daily(args.data_root)
    costs = compute_cost_map(daily, members, config)
    decomposition = overnight_decomposition(daily, config["statistics"]["profile_start"], config["research"]["as_of"])
    decomposition = decomposition.join(costs.select("symbol", "round_trip_fraction"), on="symbol").with_columns(
        (pl.col("overnight_log_return") / pl.col("round_trip_fraction")).alias("unconditional_overnight_profit_to_cost"))
    profiles, quality, bao_profiles, bao_quality = [], [], [], []
    for member in members:
        bars = read_etf_minutes(args.data_root, member["symbol"], "60m", "yahoo").filter(
            pl.col("trade_date").is_between(config["statistics"]["profile_start"], config["research"]["as_of"]))
        profile, row = hourly_profile(bars, daily, config["statistics"])
        profiles.append(profile)
        quality.append(row)
        bao = read_etf_minutes(args.data_root, member["symbol"], "5m", "baostock").filter(
            pl.col("trade_date").is_between(config["statistics"]["profile_start"], config["research"]["as_of"]))
        bao_profile, bao_row = hourly_profile(aggregate_five_minute_bars(bao), daily, config["statistics"])
        bao_profiles.append(bao_profile)
        bao_quality.append(bao_row)
    profile_frame = pl.concat(profiles)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, frame in (("cost_map", costs), ("overnight", decomposition),
                        ("hourly_profile", profile_frame), ("hourly_quality", pl.DataFrame(quality)),
                        ("baostock_profile", pl.concat(bao_profiles)), ("baostock_quality", pl.DataFrame(bao_quality))):
        frame.write_csv(args.output / f"{name}.csv")
    plot_map(costs, pl.concat(bao_profiles), args.output / "cost_and_profile.png", config["statistics"]["profile_symbols"])
    report = {"config": str(args.config), "analysis": "descriptive screening", "conclusion": "RESEARCH_ONLY",
              "as_of": str(config["research"]["as_of"]), "symbols": len(members),
              "five_minute_research_eligible": costs.filter(pl.col("eligible_for_5m_research"))["symbol"].to_list(),
              "hourly_quality": quality,
              "baostock_quality": bao_quality,
              "caveat": "Modeled spread and slippage need forward calibration; daily volatility is not expected profit.",
              "source_note": "Tushare daily costs; BaoStock 5-minute aggregation for plotted profiles. Yahoo hourly statistics retained for diagnosis only: daily checks do not establish correct intraday volume allocation.",
              "format_note": "One-page Markdown with static figures, as required by project instructions; technical scope/methods merged into definitions and evidence."}
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "config.toml").write_bytes(args.config.read_bytes())
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
