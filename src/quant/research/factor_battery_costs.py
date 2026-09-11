"""Year-bounded executable D10 portfolios using the shared daily account."""
import argparse
import copy
import datetime as dt
import json
import time
import tomllib
from pathlib import Path

import polars as pl

from quant.data.factor_battery_inputs import read_battery_execution
from quant.data.factor_panels import available_sessions
from quant.data.stock_execution_inputs import stock_session_states
from quant.research.classic_monthly_baseline import replay
from quant.research.factor_battery_groups import assign_groups
from quant.research.run_s1_walk_forward import metrics


def top_group_targets(scores: pl.DataFrame, *, variant: str, sessions: tuple[dt.date, ...],
                      end: dt.date, settings: dict, name: str) -> pl.DataFrame:
    """Fix membership at signal close and schedule only the next exchange open.

    After inception, a missing top group targets cash using a zero-weight
    eligible security to submit a liquidation batch to the shared account.
    """
    next_session = dict(zip(sessions, sessions[1:]))
    grouped = assign_groups(scores, score=variant, groups=settings["groups"],
                            minimum_symbols=settings["minimum_symbols"])
    top = grouped.filter(pl.col("group") == settings["groups"])
    first = top["trade_date"].min()
    schema = {"as_of": pl.Date, "execution_date": pl.Date, "symbol": pl.String,
              "strategy": pl.String, "strategy_version": pl.String, "weight": pl.Float64}
    if first is None:
        return pl.DataFrame(schema=schema)
    members = {key[0]: frame["symbol"].to_list()
               for key, frame in top.partition_by("trade_date", as_dict=True).items()}
    rows = []
    for (signal,), frame in scores.sort("trade_date", "symbol").partition_by("trade_date", as_dict=True).items():
        execution = next_session.get(signal)
        if signal < first or execution is None or execution > end:
            continue
        selected = members.get(signal, [])
        weights = [(symbol, 1/len(selected)) for symbol in selected] if selected else [(frame["symbol"][0], 0.)]
        rows.extend({"as_of": signal, "execution_date": execution, "symbol": symbol,
                     "strategy": name, "strategy_version": "1", "weight": weight}
                    for symbol, weight in weights)
    return pl.DataFrame(rows, schema=schema).sort("execution_date", "symbol")


def run_factor_costs(*, statistics: Path, output: Path, data_root: Path,
                     execution_snapshot: str, factor: str) -> dict:
    """Replay both frozen variants and all cost multipliers without annual resets."""
    settings = tomllib.loads((statistics / "battery.toml").read_text(encoding="utf-8"))
    end = settings["run"]["as_of"]
    if not isinstance(end, dt.date) or Path(factor).name != factor or factor in (".", ".."):
        raise ValueError("Invalid cost replay selection")
    folder = statistics / "factors" / factor
    if not (folder / "statistics.json").is_file():
        raise ValueError("Finish factor statistics before executable costs")
    scores = pl.read_parquet(folder / "monthly_scores.parquet")
    sessions = available_sessions(data_root, end)
    plans = {}
    for variant in settings["variants"]:
        name = f"battery_{factor}_{variant}"
        targets = top_group_targets(scores, variant=variant, sessions=sessions, end=end,
                                    settings=settings, name=name)
        if not targets.is_empty():
            plans[variant] = (name, targets)
    if not plans:
        raise ValueError("Factor has no executable top-group observations")
    output.mkdir(parents=True, exist_ok=False)
    (output / "battery.toml").write_bytes((statistics / "battery.toml").read_bytes() + (
        f'\n[cost_replay]\nfactor = {json.dumps(factor)}\n'
        f'execution_snapshot = {json.dumps(execution_snapshot)}\n'
        'empty_top_group = "cash_after_first_valid_group"\n').encode("utf-8"))
    for variant, (_, targets) in plans.items():
        targets.write_parquet(output / f"targets_{variant}.parquet")
    accounts = {(variant, multiplier): {} for variant in plans
                for multiplier in settings["portfolio"]["cost_multipliers"]}
    pieces = {key: [] for key in accounts}
    first = min(targets["execution_date"].min() for _, targets in plans.values())
    began = time.perf_counter()
    for year in range(first.year, end.year+1):
        low, high = max(first, dt.date(year, 1, 1)), min(end, dt.date(year, 12, 31))
        annual_targets = {variant: targets.filter(pl.col("execution_date").is_between(low, high))
                          for variant, (_, targets) in plans.items()}
        symbols = set().union(*(set(frame["symbol"]) for frame in annual_targets.values()),
                              *(set(account.get("holdings", {})) for account in accounts.values()))
        # Preserve receivable-only names and record-date events for holdings
        # even when a later year's factor never selects them again.
        for account in accounts.values():
            symbols.update(row["symbol"] for row in account.get("receivables", []))
            symbols.update(key.split("|", 1)[0] for key, value in
                           account.get("share_distribution_entitlements", {}).items() if value["quantity"])
        if not symbols:
            continue
        inputs = read_battery_execution(data_root=data_root,
            refresh_config=Path(settings["data"]["refresh_config"]), snapshot=execution_snapshot,
            start=low, end=high, symbols=sorted(symbols), include_all_dividends=True)
        dividends = inputs["dividends"].with_columns((pl.col("div_cash") * (
            1-settings["portfolio"]["stock_dividend_withholding"])).alias("div_cash"))
        active_sessions = [date for date in sessions if low <= date <= high]
        execution_dates = sorted(set().union(*(set(frame["execution_date"]) for frame in annual_targets.values())))
        for multiplier in settings["portfolio"]["cost_multipliers"]:
            scenario = copy.deepcopy(settings)
            for cost in scenario["costs"].values():
                for field in ("commission_rate", "commission_min", "slippage"):
                    cost[field] *= multiplier
            states = stock_session_states(bars=inputs["bars"], limits=inputs["limits"],
                suspensions=inputs["suspensions"], sessions=active_sessions, symbols=sorted(symbols),
                execution_dates=execution_dates, slippage=scenario["costs"]["a_share"]["slippage"])
            for variant, (name, targets) in plans.items():
                inception = targets["execution_date"].min()
                dates = [date for date in active_sessions if date >= inception]
                if not dates:
                    continue
                chunk = replay(bars=inputs["bars"], calendar=inputs["calendar"],
                    instruments=inputs["instruments"], targets=annual_targets[variant], dividends=dividends,
                    market_states=states, config=scenario, sessions=dates, name=name, validate_once=True,
                    account_state=accounts[(variant, multiplier)])
                parts = output / variant / f"cost_{multiplier:g}" / str(year)
                parts.mkdir(parents=True)
                for kind, frame in zip(("nav", "trades", "rejections"), chunk):
                    frame.write_parquet(parts / f"{kind}.parquet")
                pieces[(variant, multiplier)].append(chunk)
                print(json.dumps({"factor": factor, "year": year, "variant": variant,
                    "multiplier": multiplier, "sessions": len(dates),
                    "elapsed_seconds": round(time.perf_counter()-began, 2)}), flush=True)
    rows = []
    for (variant, multiplier), chunks in pieces.items():
        if not chunks:
            continue
        nav, trades, rejects = [pl.concat([chunk[index] for chunk in chunks], how="vertical_relaxed")
                                for index in range(3)]
        rows.append({"factor": factor, "variant": variant, "cost_multiplier": multiplier,
                     "first_date": str(nav["date"].min()), "last_date": str(nav["date"].max()),
                     **metrics(nav, trades, initial_cash=settings["portfolio"]["initial_cash"]),
                     "rejected_orders": rejects.height, "delisting_writeoff": nav["delisting_writeoff"].sum()})
    result = {"factor": factor, "execution_snapshot": execution_snapshot,
              "empty_top_group": "cash_after_first_valid_group", "rows": rows,
              "seconds": time.perf_counter()-began}
    (output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--statistics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--execution-snapshot", required=True)
    parser.add_argument("--factor", required=True)
    args = parser.parse_args()
    print(json.dumps(run_factor_costs(statistics=args.statistics, output=args.output,
        data_root=args.data_root, execution_snapshot=args.execution_snapshot, factor=args.factor)), flush=True)


if __name__ == "__main__":
    main()
