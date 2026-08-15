"""Run the pre-registered M2 three-factor composite research experiment."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import tomllib
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import polars as pl

from quant.data import (
    TushareBulkFundBarQuery,
    TushareBulkStockBarQuery,
    read_tushare_bulk_clean_fund_bars,
    read_tushare_bulk_clean_stock_bars,
)
from quant.data.publish_tushare_bulk_clean import verify_tushare_bulk_clean_snapshot
from quant.factors import CLASSIC_FACTOR_SPECS, compute_classic_daily_factors
from quant.research.classic_factor_composite import (
    COMPOSITE_COMPONENTS,
    COMPOSITE_NAME,
    evaluate_composite_walk_forward,
)
from quant.research.factor_labels import build_next_open_factor_labels
from quant.research.lightweight_run import (
    LightweightResearchRunV1,
    ResearchFoldV1,
    ResearchInputDigestV1,
    canonical_json_bytes,
    compute_code_sha256,
    publish_lightweight_research_run,
)
from quant.research.m3.contracts import AShareCostPeriod
from quant.research.run_classic_factors import (
    select_frozen_liquid_universe,
    summarize_factors,
)
from quant.settings import resolve_data_root

_CODE_PATHS = (
    "src/quant/data/clean_snapshot_repository.py",
    "src/quant/factors/classic.py",
    "src/quant/portfolio/selection.py",
    "src/quant/research/classic_factor_composite.py",
    "src/quant/research/classic_factor_evaluation.py",
    "src/quant/research/factor_labels.py",
    "src/quant/research/lightweight_run.py",
    "src/quant/research/run_classic_factor_composite.py",
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 M2 三因子等权 rank 组合研究")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/research/m2_classic_factor_composite.toml"),
    )
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args(argv)
    project_root = args.project_root.resolve(strict=True)
    config_path = _inside(project_root, args.config)
    artifact_root = _inside(project_root, args.artifact_root, strict=False)
    data_root = resolve_data_root(args.data_root, base=project_root)
    config_payload = config_path.read_bytes()
    with config_path.open("rb") as stream:
        config = cast(dict[str, Any], tomllib.load(stream))
    _validate_config(config, threads=args.threads)

    data = cast(Mapping[str, Any], config["data"])
    universe = cast(Mapping[str, Any], config["universe"])
    factors = cast(Mapping[str, Any], config["factors"])
    portfolio = cast(Mapping[str, Any], config["portfolio"])
    risk = cast(Mapping[str, Any], config["risk_control"])
    research = cast(Mapping[str, Any], config["research"])
    snapshot_id = cast(str, data["snapshot_id"])
    snapshot = verify_tushare_bulk_clean_snapshot(
        data_root=data_root, snapshot_id=snapshot_id
    )
    freeze_bars = read_tushare_bulk_clean_stock_bars(
        data_root=data_root,
        query=TushareBulkStockBarQuery(
            snapshot_id=snapshot_id,
            start_date=cast(dt.date, universe["freeze_start"]),
            end_date=cast(dt.date, universe["freeze_end"]),
            threads=args.threads,
        ),
    )
    candidates = select_frozen_liquid_universe(
        freeze_bars,
        top_n=cast(int, universe["top_n"]),
        minimum_observations=cast(int, universe["minimum_observations"]),
        minimum_average_amount=float(universe["minimum_average_amount"]),
    )
    bars = read_tushare_bulk_clean_stock_bars(
        data_root=data_root,
        query=TushareBulkStockBarQuery(
            snapshot_id=snapshot_id,
            start_date=cast(dt.date, data["warmup_start"]),
            end_date=cast(dt.date, data["research_end"]),
            symbols=candidates,
            threads=args.threads,
        ),
    )
    sessions = tuple(sorted(set(bars.get_column("trade_date").to_list())))
    factor_values = compute_classic_daily_factors(bars)
    panel = build_next_open_factor_labels(
        factor_values=factor_values,
        bars=bars,
        sessions=sessions,
        horizons=tuple(cast(list[int], factors["horizons"])),
    ).filter(
        (pl.col("trade_date") >= cast(dt.date, data["research_start"]))
        & (pl.col("history_rows") >= cast(int, factors["minimum_history_rows"]))
        & (pl.col("liquidity_20") >= float(universe["minimum_average_amount"]))
    )
    folds = _folds(config)
    cost_periods = _cost_periods(project_root, portfolio)
    risk_symbol = cast(str | None, risk.get("benchmark"))
    risk_prices: pl.DataFrame | None = None
    if risk_symbol is not None:
        fund_bars = read_tushare_bulk_clean_fund_bars(
            data_root=data_root,
            query=TushareBulkFundBarQuery(
                snapshot_id=snapshot_id,
                start_date=cast(dt.date, data["warmup_start"]),
                end_date=cast(dt.date, data["research_end"]),
                symbols=(risk_symbol,),
                threads=args.threads,
            ),
        )
        risk_prices = fund_bars.select(
            "symbol",
            "trade_date",
            (pl.col("close") * pl.col("adj_factor")).alias("adjusted_close"),
            pl.lit("CUMULATIVE_FACTOR").alias("adjustment_method"),
            "source",
        ).sort("symbol", "trade_date")
    results = evaluate_composite_walk_forward(
        panel=panel,
        components=COMPOSITE_COMPONENTS,
        composite_name=COMPOSITE_NAME,
        horizons=tuple(cast(list[int], factors["horizons"])),
        folds=folds,
        minimum_symbols=cast(int, factors["minimum_daily_symbols"]),
        groups=cast(int, factors["groups"]),
        top_k=cast(int, portfolio["top_k"]),
        rebalance_every=cast(int, portfolio["rebalance_every_sessions"]),
        initial_cash=Decimal(str(portfolio["initial_cash"])),
        cost_multipliers=tuple(
            Decimal(str(value)) for value in portfolio["cost_multipliers"]
        ),
        costs=cost_periods,
        strategy_name=cast(str, research["strategy_name"]),
        strategy_version=cast(str, research["strategy_version"]),
        lookback_observations=cast(int, risk["lookback_observations"]),
        annualized_target_volatility=float(risk["annualized_volatility"]),
        annualization_sessions=cast(int, risk["annualization_sessions"]),
        risk_prices=risk_prices,
        risk_symbol=risk_symbol,
    )
    summary = summarize_factors(
        results["fold_metrics"],
        factors=(COMPOSITE_NAME,),
        admission=cast(Mapping[str, Any], config["admission"]),
    )
    cash_period_fraction = cast(
        float,
        results["periods"].select(
            (pl.col("invested_weight") == 0).mean()
        ).item(),
    )
    if cast(bool, risk.get("require_zero_cash_period_fraction", False)) and (
        cash_period_fraction != 0.0
    ):
        summary = summary.with_columns(pl.lit("REJECTED").alias("research_status"))
    passing = summary.filter(pl.col("research_status") == "RESEARCH_ONLY")
    conclusion = "RESEARCH_ONLY" if passing.height else "REJECTED"
    report = _report(
        config=config,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        candidates=candidates,
        panel=panel,
        results=results,
        summary=summary,
        conclusion=conclusion,
    )
    catalog = [
        {
            "aliases": list(spec.aliases),
            "mechanism": spec.mechanism,
            "name": spec.name,
            "source": spec.source,
        }
        for spec in CLASSIC_FACTOR_SPECS
        if spec.name in COMPOSITE_COMPONENTS
    ]
    outputs = {
        "component_directions.parquet": _parquet(results["component_directions"]),
        "daily_ic.parquet": _parquet(results["daily_ic"]),
        "factor_catalog.json": canonical_json_bytes(catalog),
        "factor_summary.parquet": _parquet(summary),
        "fold_metrics.parquet": _parquet(results["fold_metrics"]),
        "group_returns.parquet": _parquet(results["group_returns"]),
        "periods.parquet": _parquet(results["periods"]),
        "portfolio_nav.parquet": _parquet(results["portfolio_nav"]),
        "report.json": canonical_json_bytes(report),
        "targets.parquet": _parquet(results["targets"]),
    }
    mean_exposure = cast(
        float, results["periods"].get_column("invested_weight").mean()
    )
    run = LightweightResearchRunV1(
        schema_version="lightweight-research-run-v1",
        run_id="",
        hypothesis_id=cast(str, research["hypothesis_id"]),
        hypothesis=cast(str, research["hypothesis"]),
        strategy_name=cast(str, research["strategy_name"]),
        strategy_version=cast(str, research["strategy_version"]),
        conclusion=cast(Any, conclusion),
        random_seed=cast(int, research["random_seed"]),
        config_relative_path=config_path.relative_to(project_root).as_posix(),
        config_sha256=hashlib.sha256(config_payload).hexdigest(),
        code_sha256=compute_code_sha256(
            project_root=project_root, relative_paths=_CODE_PATHS
        ),
        universe_name="tushare-2019-liquid-top800",
        universe_frozen_as_of=cast(dt.date, universe["freeze_end"]),
        candidate_symbols=candidates,
        data_start=cast(dt.date, data["research_start"]),
        data_end=cast(dt.date, data["research_end"]),
        signal_timing="close",
        execution_timing="next_session_open",
        valuation_timing="close",
        folds=folds,
        cost_multipliers=tuple(float(value) for value in portfolio["cost_multipliers"]),
        selection_metric="walk_forward_composite_rank_ic",
        inputs=_inputs(
            snapshot_manifest_sha256=snapshot.manifest_sha256,
            stock_rows=snapshot.stock_rows,
            fund_rows=snapshot.fund_rows,
            start=cast(dt.date, data["warmup_start"]),
            end=cast(dt.date, data["research_end"]),
            include_fund=risk_symbol is not None,
        ),
        outputs=(),
        aggregate_metrics=(
            ("candidate_symbols", len(candidates)),
            ("component_count", len(COMPOSITE_COMPONENTS)),
            ("mean_invested_weight", mean_exposure),
            (
                "mean_test_rank_ic",
                cast(float, summary.item(0, "mean_test_rank_ic")),
            ),
        ),
        caveats=tuple(cast(list[str], report["caveats"])),
    )
    root, complete, reused = publish_lightweight_research_run(
        artifact_root=artifact_root, run=run, output_payloads=outputs
    )
    print(
        json.dumps(
            {
                "conclusion": complete.conclusion,
                "mean_invested_weight": mean_exposure,
                "reused": reused,
                "root": str(root),
                "run_id": complete.run_id,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _folds(config: Mapping[str, Any]) -> tuple[ResearchFoldV1, ...]:
    rows = cast(list[Mapping[str, Any]], config["walk_forward"]["folds"])
    return tuple(
        ResearchFoldV1(fold=index, **dict(row)) for index, row in enumerate(rows, 1)
    )


def _cost_periods(
    project_root: Path, portfolio: Mapping[str, Any]
) -> tuple[AShareCostPeriod, ...]:
    path = _inside(project_root, Path(cast(str, portfolio["cost_config_relative_path"])))
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    rows = cast(list[Mapping[str, Any]], config["costs"]["a_share_periods"])
    return tuple(
        AShareCostPeriod(
            effective_from=cast(dt.date, row["effective_from"]),
            effective_to=cast(dt.date | None, row.get("effective_to")),
            commission_rate=Decimal(str(row["commission_rate"])),
            commission_min=Decimal(str(row["commission_min"])),
            stamp_tax_sell=Decimal(str(row["stamp_tax_sell"])),
            transfer_fee=Decimal(str(row["transfer_fee"])),
            slippage=Decimal(str(row["slippage"])),
        )
        for row in rows
    )


def _validate_config(config: Mapping[str, Any], *, threads: int) -> None:
    risk = cast(Mapping[str, Any], config["risk_control"])
    composite = cast(Mapping[str, Any], config["composite"])
    risk_method = risk.get("method")
    benchmark_valid = (
        risk_method == "unlevered_portfolio_volatility_target"
        and "benchmark" not in risk
        and not cast(bool, risk.get("require_zero_cash_period_fraction", False))
    ) or (
        risk_method == "unlevered_benchmark_volatility_target"
        and risk.get("benchmark") == "510300.SH"
        and risk.get("require_zero_cash_period_fraction") is True
    )
    if (
        tuple(cast(list[str], config["factors"]["names"])) != COMPOSITE_COMPONENTS
        or tuple(cast(list[int], config["factors"]["horizons"])) != (1, 5, 20)
        or composite["name"] != COMPOSITE_NAME
        or composite["method"]
        != "validation_directed_equal_weight_cross_sectional_average_rank"
        or not benchmark_valid
        or risk["lookback_observations"] != 60
        or float(risk["annualized_volatility"]) != 0.12
        or risk["annualization_sessions"] != 252
        or tuple(float(value) for value in config["portfolio"]["cost_multipliers"])
        != (0.5, 1.0, 2.0)
        or config["portfolio"]["selection_horizon_sessions"] != 20
        or type(threads) is not int
        or not 1 <= threads <= 4
    ):
        raise ValueError("invalid classic-factor composite config")


def _report(
    *,
    config: Mapping[str, Any],
    snapshot_manifest_sha256: str,
    candidates: tuple[str, ...],
    panel: pl.DataFrame,
    results: Mapping[str, pl.DataFrame],
    summary: pl.DataFrame,
    conclusion: str,
) -> dict[str, object]:
    return {
        "schema_version": "m2-classic-factor-composite-report-v1",
        "conclusion": conclusion,
        "hypothesis": config["research"]["hypothesis"],
        "snapshot_id": config["data"]["snapshot_id"],
        "snapshot_manifest_sha256": snapshot_manifest_sha256,
        "candidate_symbol_count": len(candidates),
        "panel_rows": panel.height,
        "component_directions": results["component_directions"].to_dicts(),
        "factor_summary": summary.to_dicts(),
        "mean_invested_weight": cast(
            float, results["periods"].get_column("invested_weight").mean()
        ),
        "cash_period_fraction": cast(
            float,
            results["periods"].select(
                (pl.col("invested_weight") == 0).mean()
            ).item(),
        ),
        "timing": {
            "signal": "close of as_of session",
            "execution": "next exchange session open",
            "label": "adjusted open(t+1+h)/adjusted open(t+1)-1",
        },
        "risk_control": {
            "method": config["risk_control"]["method"],
            "benchmark": config["risk_control"].get("benchmark"),
            "lookback_observations": 60,
            "annualized_volatility": 0.12,
            "annualization_sessions": 252,
        },
        "caveats": [
            "The components were chosen after observing the first-run test results, so this is not an independent final holdout.",
            "The 2019 liquid universe is PIT at its freeze date but is not an evolving historical constituent universe.",
            "Historical ST flags, industry membership and authoritative suspension facts are unavailable in this snapshot.",
            "Missing exact next-session opens produce null labels and are never forward-filled.",
            "The non-overlapping 20-session portfolio is a factor diagnostic, not the formal A-share account replay.",
            "The volatility target uses signal-date-known adjusted closes, only reduces exposure, and assigns zero return to cash.",
            "No result from this run may exceed RESEARCH_ONLY without a new frozen forward window and market-event admission evidence.",
        ],
    }


def _inputs(
    *,
    snapshot_manifest_sha256: str,
    stock_rows: int,
    fund_rows: int,
    start: dt.date,
    end: dt.date,
    include_fund: bool,
) -> tuple[ResearchInputDigestV1, ...]:
    rows: list[ResearchInputDigestV1] = []
    if include_fund:
        rows.append(
            ResearchInputDigestV1(
                name="tushare-fund-bars",
                rows=fund_rows,
                min_date=start,
                max_date=end,
                content_sha256=snapshot_manifest_sha256,
            )
        )
    rows.append(
        ResearchInputDigestV1(
            name="tushare-stock-bars",
            rows=stock_rows,
            min_date=start,
            max_date=end,
            content_sha256=snapshot_manifest_sha256,
        )
    )
    return tuple(rows)


def _parquet(frame: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.write_parquet(buffer, compression="zstd", statistics=True)
    return buffer.getvalue()


def _inside(root: Path, path: Path, *, strict: bool = True) -> Path:
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve(strict=strict)
    if resolved != root and root not in resolved.parents:
        raise ValueError("path escapes project root")
    return resolved


if __name__ == "__main__":
    raise SystemExit(main())
