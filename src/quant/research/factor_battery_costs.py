"""Year-bounded executable D10 portfolios using the shared daily account."""
import argparse
import copy
import datetime as dt
import json
import time
import tomllib
from pathlib import Path
from typing import Callable

import polars as pl

from quant.data.factor_battery_inputs import read_battery_execution
from quant.data.factor_panels import available_sessions
from quant.data.stock_execution_inputs import stock_session_states
from quant.research.classic_monthly_baseline import replay
from quant.research.factor_battery_groups import assign_groups
from quant.research.factor_cost_checkpoint import prepare_resume, read_year, save_year
from quant.research.run_s1_walk_forward import metrics


def cost_metrics(nav: pl.DataFrame, trades: pl.DataFrame, *, initial_cash: float) -> dict:
    """Normalize turnover by prior-session equity and expose invested fractions."""
    if (nav.is_empty() or nav['date'].null_count() or not nav['date'].is_sorted()
            or nav['date'].n_unique() != nav.height):
        raise ValueError('Cost metrics require ordered unique NAV dates')
    denominators = nav.select('date', pl.col('equity').shift(1).fill_null(initial_cash).alias('prior_equity'))
    if not denominators['prior_equity'].is_finite().all() or (denominators['prior_equity'] <= 0).any():
        raise ValueError('Cost metrics require positive prior equity')
    if trades.filter(~pl.col('date').is_in(nav['date'].implode())).height:
        raise ValueError('Trade dates are outside NAV history')
    amounts = trades.group_by('date').agg(pl.col('notional').sum())
    daily = denominators.join(amounts, on='date', how='left').with_columns(pl.col('notional').fill_null(0.))
    result = metrics(nav, trades, initial_cash=initial_cash)
    result['annualized_turnover_on_initial_cash'] = result['annualized_one_way_turnover']
    result['annualized_one_way_turnover'] = daily.select(
        (pl.col('notional')/(2*pl.col('prior_equity'))).sum()).item()*252/nav.height
    result['mean_invested_fraction'] = nav.select((pl.col('market_value')/pl.col('equity')).mean()).item()
    result['ending_invested_fraction'] = nav['market_value'][-1]/nav['equity'][-1]
    return result


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
    rows: list[dict] = []
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
                     execution_snapshot: str, factor: str, resume: bool = False) -> dict:
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
    config_bytes = (statistics / "battery.toml").read_bytes() + (
        f'\n[cost_replay]\nfactor = {json.dumps(factor)}\n'
        f'execution_snapshot = {json.dumps(execution_snapshot)}\n'
        'empty_top_group = "cash_after_first_valid_group"\n').encode("utf-8")
    if resume:
        if (output / "battery.toml").read_bytes() != config_bytes:
            raise ValueError("Resume cost settings changed")
    else:
        output.mkdir(parents=True, exist_ok=False)
        (output / "battery.toml").write_bytes(config_bytes)
    return run_cost_plans(settings=settings, plans=plans, sessions=sessions, output=output,
                          data_root=data_root, execution_snapshot=execution_snapshot, factor=factor, resume=resume)


def run_cost_plans(*, settings: dict, plans: dict, sessions: tuple[dt.date, ...], output: Path,
                   data_root: Path, execution_snapshot: str, factor: str,
                   start: dt.date | None = None,
                   turnover_budgets: dict[str, float] | None = None, resume: bool = False,
                   target_constraints: Callable[[pl.DataFrame, dict], tuple[pl.DataFrame, dict]] | None = None) -> dict:
    """Replay factor and equal-weight benchmark plans through the same account."""
    if (target_constraints is not None) != ('target_constraints_config' in settings):
        raise ValueError('Constraint hook requires its explicit replay configuration')
    end = settings['run']['as_of']
    if not plans or (start is None and any(targets.is_empty() for _, targets in plans.values())):
        raise ValueError('Cost replay requires nonempty target plans')
    if start is not None and (start > end or any(
            targets.filter(~pl.col('execution_date').is_between(start, end)).height for _, targets in plans.values())):
        raise ValueError('Invalid explicit cost replay range')
    prepare_resume(output=output, settings=settings, plans=plans, sessions=sessions,
        data_root=data_root, snapshot=execution_snapshot, factor=factor, start=start,
        turnover_budgets=turnover_budgets, resume=resume)
    accounts: dict[tuple[str, float], dict] = {(variant, multiplier): {} for variant in plans
                for multiplier in settings["portfolio"]["cost_multipliers"]}
    pieces: dict[tuple[str, float], list[tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]]] = {
        key: [] for key in accounts}
    first = start if start is not None else min(targets["execution_date"].min() for _, targets in plans.values())
    began = time.perf_counter()
    unfinished = set()
    for year in range(first.year, end.year+1):
        low, high = max(first, dt.date(year, 1, 1)), min(end, dt.date(year, 12, 31))
        active_sessions = [date for date in sessions if low <= date <= high]
        pending = set()
        for key in accounts:
            variant, multiplier = key
            inception = start if start is not None else plans[variant][1]["execution_date"].min()
            dates = [date for date in active_sessions if date >= inception]
            if not dates:
                continue
            folder = output / variant / f"cost_{multiplier:g}" / str(year)
            if resume and folder.exists():
                if target_constraints is not None and not (folder/'constraints.json').is_file():
                    raise ValueError('Constraint checkpoint lacks its saved diagnostics')
                if key in unfinished:
                    raise ValueError("Checkpoint years contain a gap; retain partial output")
                accounts[key], chunk = read_year(folder, dates=dates, previous=accounts[key])
                pieces[key].append(chunk)
            else:
                unfinished.add(key)
                pending.add(key)
        if not pending:
            continue
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
            symbols.update(key.split("|", 1)[0] for key, value in
                           account.get("share_reduction_entitlements", {}).items() if value)
        # A cash-only year still advances the account and its exchange calendar.
        inputs = read_battery_execution(data_root=data_root,
            refresh_config=Path(settings["data"]["refresh_config"]), snapshot=execution_snapshot,
            start=low, end=high, symbols=sorted(symbols), include_all_dividends=True)
        dividends = inputs["dividends"].with_columns((pl.col("div_cash") * (
            1-settings["portfolio"]["stock_dividend_withholding"])).alias("div_cash"))
        execution_dates = sorted(set().union(*(set(frame["execution_date"]) for frame in annual_targets.values())))
        for multiplier in settings["portfolio"]["cost_multipliers"]:
            if not any(key[1] == multiplier for key in pending):
                continue
            scenario = copy.deepcopy(settings)
            for cost in scenario["costs"].values():
                for field in ("commission_rate", "commission_min", "slippage"):
                    cost[field] *= multiplier
            states = stock_session_states(bars=inputs["bars"], limits=inputs["limits"],
                suspensions=inputs["suspensions"], sessions=active_sessions, symbols=sorted(symbols),
                execution_dates=execution_dates, slippage=scenario["costs"]["a_share"]["slippage"])
            for variant, (name, targets) in plans.items():
                if (variant, multiplier) not in pending:
                    continue
                inception = start if start is not None else targets["execution_date"].min()
                dates = [date for date in active_sessions if date >= inception]
                if not dates:
                    continue
                target_records: list[dict] = []
                constraint_records: list[dict] = []
                constraint_diagnostics: list[dict] = []
                try:
                    chunk = replay(bars=inputs["bars"], calendar=inputs["calendar"],
                        instruments=inputs["instruments"], targets=annual_targets[variant], dividends=dividends,
                        market_states=states, config=scenario, sessions=dates, name=name, validate_once=True,
                        account_state=accounts[(variant, multiplier)],
                        target_turnover_budget=(turnover_budgets or {}).get(variant),
                        target_records=target_records, target_constraints=target_constraints,
                        constraint_records=constraint_records, constraint_diagnostics=constraint_diagnostics)
                except ValueError as exc:
                    if target_constraints is not None:
                        failures = output/variant/f'cost_{multiplier:g}'
                        failures.mkdir(parents=True, exist_ok=True)
                        path = failures/f'constraints_failure_{year}_{time.time_ns()}.json'
                        path.write_text(json.dumps({'year': year, 'reason': str(exc),
                            'diagnostics': constraint_diagnostics,
                            'resume': 'Restart unfinished year from last completed annual checkpoint'},
                            indent=2, default=str), encoding='utf-8')
                        if constraint_records:
                            pl.from_dicts(constraint_records).write_parquet(path.with_suffix('.parquet'))
                    raise
                parts = output / variant / f"cost_{multiplier:g}" / str(year)
                save_year(parts, account=accounts[(variant, multiplier)], chunks=chunk,
                          target_records=target_records)
                if target_constraints is not None:
                    (parts/'constraints.json').write_text(json.dumps(constraint_diagnostics,
                        indent=2, default=str), encoding='utf-8')
                    if constraint_records:
                        pl.from_dicts(constraint_records).write_parquet(parts/'constraint_targets.parquet')
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
                     **cost_metrics(nav, trades, initial_cash=settings["portfolio"]["initial_cash"]),
                     "rejected_orders": rejects.height, "delisting_writeoff": nav["delisting_writeoff"].sum()})
    result = {"factor": factor, "execution_snapshot": execution_snapshot,
              "empty_top_group": "cash_on_full_calendar" if start is not None else "cash_after_first_valid_group", "rows": rows,
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
    parser.add_argument("--resume", action="store_true", help="Resume this interrupted output from complete annual accounts")
    args = parser.parse_args()
    print(json.dumps(run_factor_costs(statistics=args.statistics, output=args.output,
        data_root=args.data_root, execution_snapshot=args.execution_snapshot, factor=args.factor,
        resume=args.resume)), flush=True)


if __name__ == "__main__":
    main()
