"""B20 daily forward observation and order references; never connects to a broker."""

import argparse
import copy
import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.refresh import SHANGHAI, completed_date, latest_session
from quant.data.refresh_cross_asset_forward import refresh_cross_asset_forward
from quant.execution.paper_ledger import run as run_ledger
from quant.research.monthly_etf import admission_checks
from quant.research.run_s1_walk_forward import metrics


def account_config_text(config: dict[str, Any], comparison: str, multiplier: float) -> str:
    """Generate only the account fields needed by the existing ledger."""
    costs = copy.deepcopy(config["costs"])
    for model in costs.values():
        for key in ("commission_rate", "commission_min", "slippage", "slippage_per_share"):
            if key in model:
                model[key] *= multiplier
    tables = {
        "paper": {"name": "b20_inverse_volatility" if comparison == "strategy" else "b20_equal_weight",
                  "start_date": config["forward"]["start_date"], "auto_trade": False,
                  "sell_only": False, "initial_cash": config["portfolio"]["initial_cash"]},
        "data": config["data"], "universe": config["universe"],
        "strategy": {"kind": "inverse_volatility" if comparison == "strategy" else "equal_weight",
                     "lookback_sessions": config["strategy"]["lookback_sessions"]},
        **{f"costs.{kind}": model for kind, model in costs.items()},
    }
    lines = []
    for label, values in tables.items():
        lines.append(f"[{label}]")
        for key, value in values.items():
            rendered = value.isoformat() if isinstance(value, dt.date) else json.dumps(value)
            lines.append(f"{key} = {rendered}")
        lines.append("")
    return "\n".join(lines)


def assess_forward(results: list[dict[str, Any]], config: dict[str, Any], end: dt.date,
                   controls_changed: bool = False) -> dict[str, Any]:
    """Do not make an interim admission decision."""
    if end < config["forward"]["assessment_date"]:
        return {"assessment_due": str(config["forward"]["assessment_date"]), "conclusion": None}
    sufficient = (len(results) == 6 and all(r["sessions"] >= config["forward"]["minimum_sessions"] for r in results))
    checks = admission_checks(results, config["admission"]) if sufficient else {}
    passed = sufficient and not controls_changed and all(checks.values())
    return {"assessment_due": str(config["forward"]["assessment_date"]),
            "conclusion": "PAPER_CANDIDATE" if passed else "REJECTED",
            "sufficient_observations": sufficient, "controls_changed": controls_changed, "checks": checks}


def run(*, config_path: Path, data_root: Path, output: Path, end: dt.date,
        refresh_data: bool = True) -> dict[str, Any]:
    text = config_path.read_text(encoding="utf-8")
    config = tomllib.loads(text)
    if (config["forward"]["auto_trade"] is not False
        or config["forward"]["assessment"] != "once_at_fixed_endpoint"
        or config["portfolio"]["cost_multipliers"] != [.5, 1., 2.]
        or config["universe"]["symbols"] != ["510300.SH", "511010.SH", "518880.SH"]):
        raise ValueError("Unsupported B20 forward configuration")
    end = min(end, config["forward"]["assessment_date"])
    if end < config["forward"]["start_date"] - dt.timedelta(days=1):
        raise ValueError("B20 observation begins with the first pre-trade signal")
    output.mkdir(parents=True, exist_ok=True)
    frozen = output / "experiment.toml"
    if frozen.exists() and frozen.read_text(encoding="utf-8") != text:
        raise ValueError("Forward experiment changed; use a new observation directory")
    if not frozen.exists():
        frozen.write_text(text, encoding="utf-8")
    if refresh_data:
        refresh_cross_asset_forward(data_root=data_root, end=end)
    results, series, accounts = [], [], []
    changed_controls = False
    for multiplier in config["portfolio"]["cost_multipliers"]:
        for comparison in ("strategy", "s0"):
            folder = output / f"cost_{multiplier:g}" / comparison
            folder.mkdir(parents=True, exist_ok=True)
            account_config = folder / "account.toml"
            account_text = account_config_text(config, comparison, multiplier)
            if account_config.exists() and account_config.read_text(encoding="utf-8") != account_text:
                raise ValueError("Forward account changed")
            if not account_config.exists():
                account_config.write_text(account_text, encoding="utf-8")
            accounts.append({"comparison": comparison, "cost_multiplier": multiplier,
                             **run_ledger(config_path=account_config, data_root=data_root, output=folder, end=end)})
            snapshots = sorted(p for p in folder.glob("????-??-??/state.json") if p.parent.name <= str(end))
            states = [json.loads(p.read_text(encoding="utf-8")) for p in snapshots]
            changed_controls |= any(not s["trading_enabled"] or s["sell_only"] for s in states)
            nav = pl.read_csv(folder / str(end) / "nav.csv")
            if nav.is_empty():
                continue
            fills = [pl.read_csv(p.parent / "fills.csv") for p in snapshots if (p.parent / "fills.csv").exists()]
            trades = pl.concat(fills, how="diagonal_relaxed") if fills else pl.DataFrame(schema={"notional": pl.Float64})
            trades = trades.with_columns(pl.col("notional").cast(pl.Float64))
            scores = metrics(nav, trades, initial_cash=config["portfolio"]["initial_cash"])
            results.append({"fold": 1, "comparison": comparison, "cost_multiplier": multiplier,
                            "test_start": str(config["forward"]["start_date"]), "sessions": nav.height, **scores})
            series.append(nav.with_columns(pl.lit(comparison).alias("comparison"),
                                          pl.lit(multiplier).alias("cost_multiplier")))
    summary = {"as_of": str(end), "start": str(config["forward"]["start_date"]),
               "historical_conclusion": config["forward"]["historical_conclusion"],
               "accounts": accounts, "results": results,
               **assess_forward(results, config, end, changed_controls)}
    daily = output / str(end)
    daily.mkdir(exist_ok=True)
    if series:
        pl.concat(series, how="diagonal_relaxed").write_csv(daily / "nav.csv")
    (daily / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/research/b20_three_asset_forward_20260909.toml"))
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/forward/b20"))
    parser.add_argument("--to", default="today")
    args = parser.parse_args()
    end = latest_session(data_root=args.data_root, through=completed_date(args.to, dt.datetime.now(SHANGHAI)))
    result = run(config_path=args.config, data_root=args.data_root, output=args.output, end=end)
    print(json.dumps({k: v for k, v in result.items() if k not in {"accounts", "results"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
