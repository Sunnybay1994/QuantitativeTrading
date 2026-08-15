"""Run the frozen M2 classic daily-factor research roadmap."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import math
import tomllib
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import polars as pl

from quant.data import (
    TushareBulkStockBarQuery,
    read_tushare_bulk_clean_stock_bars,
)
from quant.data.publish_tushare_bulk_clean import verify_tushare_bulk_clean_snapshot
from quant.factors import (
    CLASSIC_FACTOR_NAMES,
    CLASSIC_FACTOR_SPECS,
    SECOND_BATCH_FACTOR_NAMES,
    SECOND_BATCH_FACTOR_SPECS,
    THIRD_BATCH_FACTOR_NAMES,
    THIRD_BATCH_FACTOR_SPECS,
    compute_classic_daily_factors,
    compute_second_batch_daily_factors,
    compute_third_batch_daily_factors,
)
from quant.research.classic_factor_evaluation import (
    build_diagnostic_factor_targets,
    evaluate_factor_period,
    evaluate_factor_redundancy,
    simulate_diagnostic_factor_portfolio,
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
from quant.settings import resolve_data_root

_CODE_PATHS = (
    "src/quant/data/clean_snapshot_repository.py",
    "src/quant/factors/classic.py",
    "src/quant/factors/classic_second_batch.py",
    "src/quant/factors/classic_third_batch.py",
    "src/quant/research/classic_factor_evaluation.py",
    "src/quant/research/factor_labels.py",
    "src/quant/research/lightweight_run.py",
    "src/quant/research/run_classic_factors.py",
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 M2 经典日频因子研究")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/research/m2_classic_daily_factors.toml"),
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
    universe_config = cast(Mapping[str, Any], config["universe"])
    factor_config = cast(Mapping[str, Any], config["factors"])
    portfolio_config = cast(Mapping[str, Any], config["portfolio"])
    snapshot_id = cast(str, data["snapshot_id"])
    snapshot = verify_tushare_bulk_clean_snapshot(data_root=data_root, snapshot_id=snapshot_id)
    freeze_bars = read_tushare_bulk_clean_stock_bars(
        data_root=data_root,
        query=TushareBulkStockBarQuery(
            snapshot_id=snapshot_id,
            start_date=cast(dt.date, universe_config["freeze_start"]),
            end_date=cast(dt.date, universe_config["freeze_end"]),
            threads=args.threads,
        ),
    )
    candidates = select_frozen_liquid_universe(
        freeze_bars,
        top_n=cast(int, universe_config["top_n"]),
        minimum_observations=cast(int, universe_config["minimum_observations"]),
        minimum_average_amount=float(universe_config["minimum_average_amount"]),
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
    factor_names = tuple(cast(list[str], factor_config["names"]))
    first_batch_values = compute_classic_daily_factors(bars)
    if factor_names == SECOND_BATCH_FACTOR_NAMES:
        second_batch_values = compute_second_batch_daily_factors(bars)
        factor_values = first_batch_values.join(
            second_batch_values.select("symbol", "trade_date", *SECOND_BATCH_FACTOR_NAMES),
            on=["symbol", "trade_date"],
            how="inner",
            validate="1:1",
        )
        factor_specs = SECOND_BATCH_FACTOR_SPECS
    elif factor_names == THIRD_BATCH_FACTOR_NAMES:
        third_batch_values = compute_third_batch_daily_factors(bars)
        second_batch_values = compute_second_batch_daily_factors(bars)
        factor_values = first_batch_values.join(
            second_batch_values.select("symbol", "trade_date", *SECOND_BATCH_FACTOR_NAMES),
            on=["symbol", "trade_date"],
            how="inner",
            validate="1:1",
        ).join(
            third_batch_values.select("symbol", "trade_date", *THIRD_BATCH_FACTOR_NAMES),
            on=["symbol", "trade_date"],
            how="inner",
            validate="1:1",
        )
        factor_specs = THIRD_BATCH_FACTOR_SPECS
    else:
        factor_values = first_batch_values
        factor_specs = CLASSIC_FACTOR_SPECS
    panel = build_next_open_factor_labels(
        factor_values=factor_values,
        bars=bars,
        sessions=sessions,
        horizons=tuple(cast(list[int], factor_config["horizons"])),
    ).filter(
        (pl.col("trade_date") >= cast(dt.date, data["research_start"]))
        & (pl.col("history_rows") >= cast(int, factor_config["minimum_history_rows"]))
        & (pl.col("liquidity_20") >= float(universe_config["minimum_average_amount"]))
    )
    folds = _folds(config)
    cost_periods = _cost_periods(project_root, portfolio_config)
    results = evaluate_walk_forward(
        panel=panel,
        factors=factor_names,
        horizons=tuple(cast(list[int], factor_config["horizons"])),
        folds=folds,
        minimum_symbols=cast(int, factor_config["minimum_daily_symbols"]),
        groups=cast(int, factor_config["groups"]),
        top_k=cast(int, portfolio_config["top_k"]),
        rebalance_every=cast(int, portfolio_config["rebalance_every_sessions"]),
        initial_cash=Decimal(str(portfolio_config["initial_cash"])),
        cost_multipliers=tuple(
            Decimal(str(value)) for value in portfolio_config["cost_multipliers"]
        ),
        costs=cost_periods,
        strategy_name=cast(str, config["research"]["strategy_name"]),
        strategy_version=cast(str, config["research"]["strategy_version"]),
    )
    summary = summarize_factors(
        cast(pl.DataFrame, results["fold_metrics"]),
        factors=factor_names,
        admission=cast(Mapping[str, Any], config["admission"]),
    )
    reference_names = tuple(cast(list[str], factor_config.get("redundancy_reference_names", [])))
    if reference_names:
        redundancy_daily, redundancy_summary = evaluate_factor_redundancy(
            panel,
            factors=factor_names,
            reference_factors=reference_names,
            start_date=cast(dt.date, data["research_start"]),
            end_date=cast(dt.date, data["research_end"]),
            minimum_symbols=cast(int, factor_config["minimum_daily_symbols"]),
        )
        threshold = float(factor_config["maximum_median_absolute_rank_correlation"])
        redundancy_by_factor = redundancy_summary.group_by("factor_a").agg(
            pl.col("median_abs_rank_corr").max().alias("max_median_abs_rank_corr")
        )
        summary = summary.join(
            redundancy_by_factor,
            left_on="factor",
            right_on="factor_a",
            how="left",
            validate="1:1",
        ).with_columns(
            (
                pl.col("max_median_abs_rank_corr").is_not_null()
                & (pl.col("max_median_abs_rank_corr") < threshold)
            ).alias("combination_eligible")
        )
        results["redundancy_daily"] = redundancy_daily
        results["redundancy_summary"] = redundancy_summary
    passing = summary.filter(pl.col("research_status") == "RESEARCH_ONLY")
    conclusion = "RESEARCH_ONLY" if passing.height else "REJECTED"
    report = _report(
        config=config,
        snapshot_id=snapshot.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        candidates=candidates,
        panel=panel,
        results=results,
        summary=summary,
        conclusion=conclusion,
    )
    outputs = {
        "daily_ic.parquet": _parquet(cast(pl.DataFrame, results["daily_ic"])),
        "factor_catalog.json": canonical_json_bytes(
            [
                {
                    "aliases": list(spec.aliases),
                    "mechanism": spec.mechanism,
                    "name": spec.name,
                    "source": spec.source,
                }
                for spec in factor_specs
            ]
        ),
        "factor_summary.parquet": _parquet(summary),
        "fold_metrics.parquet": _parquet(cast(pl.DataFrame, results["fold_metrics"])),
        "group_returns.parquet": _parquet(cast(pl.DataFrame, results["group_returns"])),
        "portfolio_nav.parquet": _parquet(cast(pl.DataFrame, results["portfolio_nav"])),
        "report.json": canonical_json_bytes(report),
        "targets.parquet": _parquet(cast(pl.DataFrame, results["targets"])),
    }
    if "redundancy_daily" in results:
        outputs["redundancy_daily.parquet"] = _parquet(
            cast(pl.DataFrame, results["redundancy_daily"])
        )
        outputs["redundancy_summary.parquet"] = _parquet(
            cast(pl.DataFrame, results["redundancy_summary"])
        )
    run = LightweightResearchRunV1(
        schema_version="lightweight-research-run-v1",
        run_id="",
        hypothesis_id=cast(str, config["research"]["hypothesis_id"]),
        hypothesis=cast(str, config["research"]["hypothesis"]),
        strategy_name=cast(str, config["research"]["strategy_name"]),
        strategy_version=cast(str, config["research"]["strategy_version"]),
        conclusion=cast(Any, conclusion),
        random_seed=cast(int, config["research"]["random_seed"]),
        config_relative_path=config_path.relative_to(project_root).as_posix(),
        config_sha256=hashlib.sha256(config_payload).hexdigest(),
        code_sha256=compute_code_sha256(project_root=project_root, relative_paths=_CODE_PATHS),
        universe_name="tushare-2019-liquid-top800",
        universe_frozen_as_of=cast(dt.date, universe_config["freeze_end"]),
        candidate_symbols=candidates,
        data_start=cast(dt.date, data["research_start"]),
        data_end=cast(dt.date, data["research_end"]),
        signal_timing="close",
        execution_timing="next_session_open",
        valuation_timing="close",
        folds=folds,
        cost_multipliers=tuple(float(value) for value in portfolio_config["cost_multipliers"]),
        selection_metric="walk_forward_rank_ic",
        inputs=(
            ResearchInputDigestV1(
                name="tushare-stock-bars",
                rows=snapshot.stock_rows,
                min_date=cast(dt.date, data["warmup_start"]),
                max_date=cast(dt.date, data["research_end"]),
                content_sha256=snapshot.manifest_sha256,
            ),
        ),
        outputs=(),
        aggregate_metrics=(
            (
                "best_mean_test_rank_ic",
                cast(float, summary.get_column("mean_test_rank_ic").max()),
            ),
            ("candidate_symbols", len(candidates)),
            ("factor_count", len(factor_names)),
            ("passing_factor_count", passing.height),
            (
                "redundancy_eligible_count",
                cast(
                    int,
                    summary.get_column("combination_eligible").sum(),
                )
                if "combination_eligible" in summary.columns
                else 0,
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
                "passing_factors": passing.get_column("factor").to_list(),
                "reused": reused,
                "root": str(root),
                "run_id": complete.run_id,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def select_frozen_liquid_universe(
    bars: pl.DataFrame,
    *,
    top_n: int,
    minimum_observations: int,
    minimum_average_amount: float,
) -> tuple[str, ...]:
    """Freeze a universe using only data available in the pre-research window."""
    if (
        type(top_n) is not int
        or top_n <= 0
        or type(minimum_observations) is not int
        or minimum_observations <= 0
        or not math.isfinite(minimum_average_amount)
        or minimum_average_amount <= 0
    ):
        raise ValueError("invalid frozen-universe request")
    ranked = (
        bars.group_by("symbol")
        .agg(
            pl.len().alias("observations"),
            pl.col("amount").mean().alias("average_amount"),
        )
        .filter(
            (pl.col("observations") >= minimum_observations)
            & (pl.col("average_amount") >= minimum_average_amount)
        )
        .sort("average_amount", "symbol", descending=[True, False])
        .head(top_n)
    )
    if ranked.height != top_n:
        raise ValueError("not enough securities for frozen universe")
    return tuple(sorted(ranked.get_column("symbol").to_list()))


def evaluate_walk_forward(
    *,
    panel: pl.DataFrame,
    factors: tuple[str, ...],
    horizons: tuple[int, ...],
    folds: tuple[ResearchFoldV1, ...],
    minimum_symbols: int,
    groups: int,
    top_k: int,
    rebalance_every: int,
    initial_cash: Decimal,
    cost_multipliers: tuple[Decimal, ...],
    costs: tuple[AShareCostPeriod, ...],
    strategy_name: str,
    strategy_version: str,
    portfolio_return_column: str = "label_20",
    portfolio_execution_date_column: str = "execution_date_20",
    portfolio_exit_date_column: str = "exit_date_20",
    portfolio_annualization_periods: float = 252.0 / 20.0,
    ic_newey_west_lag: int | None = None,
) -> dict[str, pl.DataFrame]:
    """Select direction on validation, then evaluate untouched test periods."""
    daily_frames: list[pl.DataFrame] = []
    group_frames: list[pl.DataFrame] = []
    metric_rows: list[dict[str, object]] = []
    target_frames: list[pl.DataFrame] = []
    nav_frames: list[pl.DataFrame] = []
    for fold in folds:
        for factor in factors:
            validation_daily, validation_groups, validation_metrics = evaluate_factor_period(
                panel,
                factor=factor,
                horizon=20,
                start_date=fold.validation_start,
                end_date=fold.validation_end,
                minimum_symbols=minimum_symbols,
                groups=groups,
                newey_west_lag=ic_newey_west_lag,
            )
            direction = 1 if validation_metrics["rank_ic_mean"] >= 0 else -1
            daily_frames.append(
                _with_evaluation_identity(
                    validation_daily,
                    fold=fold.fold,
                    period="validation",
                    factor=factor,
                    horizon=20,
                    direction=direction,
                )
            )
            group_frames.append(
                _with_evaluation_identity(
                    validation_groups,
                    fold=fold.fold,
                    period="validation",
                    factor=factor,
                    horizon=20,
                    direction=direction,
                )
            )
            test20_metrics: dict[str, float | int] | None = None
            for horizon in horizons:
                test_daily, test_groups, test_metrics = evaluate_factor_period(
                    panel,
                    factor=factor,
                    horizon=horizon,
                    start_date=fold.test_start,
                    end_date=fold.test_end,
                    minimum_symbols=minimum_symbols,
                    groups=groups,
                    direction=direction,
                    newey_west_lag=ic_newey_west_lag,
                )
                daily_frames.append(
                    _with_evaluation_identity(
                        test_daily,
                        fold=fold.fold,
                        period="test",
                        factor=factor,
                        horizon=horizon,
                        direction=direction,
                    )
                )
                group_frames.append(
                    _with_evaluation_identity(
                        test_groups,
                        fold=fold.fold,
                        period="test",
                        factor=factor,
                        horizon=horizon,
                        direction=direction,
                    )
                )
                if horizon == 20:
                    test20_metrics = test_metrics
            if test20_metrics is None:
                raise ValueError("test horizon 20 is missing")
            targets, periods = build_diagnostic_factor_targets(
                panel,
                factor=factor,
                direction=direction,
                fold=fold.fold,
                test_start=fold.test_start,
                test_end=fold.test_end,
                top_k=top_k,
                rebalance_every_sessions=rebalance_every,
                minimum_symbols=minimum_symbols,
                strategy_name=strategy_name,
                strategy_version=strategy_version,
                return_column=portfolio_return_column,
                execution_date_column=portfolio_execution_date_column,
                exit_date_column=portfolio_exit_date_column,
            )
            target_frames.append(targets)
            for multiplier in cost_multipliers:
                nav, portfolio_metrics = simulate_diagnostic_factor_portfolio(
                    targets=targets,
                    periods=periods,
                    costs=costs,
                    multiplier=multiplier,
                    initial_cash=initial_cash,
                    annualization_periods=portfolio_annualization_periods,
                )
                nav_frames.append(
                    nav.with_columns(
                        pl.lit(factor).alias("factor"),
                        pl.lit(fold.fold).alias("fold"),
                        pl.lit(float(multiplier)).alias("cost_multiplier"),
                    )
                )
                metric_rows.append(
                    {
                        "factor": factor,
                        "fold": fold.fold,
                        "direction": direction,
                        "cost_multiplier": float(multiplier),
                        "validation_rank_ic": abs(float(validation_metrics["rank_ic_mean"])),
                        "test_rank_ic": float(test20_metrics["rank_ic_mean"]),
                        "test_ic_dates": int(test20_metrics["dates"]),
                        **portfolio_metrics,
                    }
                )
    return {
        "daily_ic": pl.concat(daily_frames).sort(
            "fold", "period", "factor", "horizon", "trade_date"
        ),
        "group_returns": pl.concat(group_frames).sort(
            "fold", "period", "factor", "horizon", "trade_date", "group"
        ),
        "fold_metrics": pl.DataFrame(metric_rows).sort("factor", "fold", "cost_multiplier"),
        "targets": pl.concat(target_frames).sort("as_of", "strategy", "symbol"),
        "portfolio_nav": pl.concat(nav_frames).sort("factor", "fold", "cost_multiplier", "as_of"),
    }


def summarize_factors(
    metrics: pl.DataFrame,
    *,
    factors: tuple[str, ...],
    admission: Mapping[str, Any],
) -> pl.DataFrame:
    """Apply pre-registered research thresholds without PAPER promotion."""
    rows: list[dict[str, object]] = []
    for factor in factors:
        one = metrics.filter((pl.col("factor") == factor) & (pl.col("cost_multiplier") == 1.0))
        two = metrics.filter((pl.col("factor") == factor) & (pl.col("cost_multiplier") == 2.0))
        test_ics = [float(value) for value in one.get_column("test_rank_ic")]
        directions = [int(value) for value in one.get_column("direction")]
        mean_ic = sum(test_ics) / len(test_ics)
        positive_folds = sum(value > 0 for value in test_ics)
        direction_consistent = len(set(directions)) == 1
        one_x_return = (
            math.prod(1.0 + float(value) for value in one.get_column("total_return")) - 1.0
        )
        two_x_return = (
            math.prod(1.0 + float(value) for value in two.get_column("total_return")) - 1.0
        )
        passed = (
            mean_ic >= float(admission["minimum_mean_test_rank_ic"])
            and positive_folds >= cast(int, admission["minimum_positive_test_folds"])
            and (direction_consistent or not cast(bool, admission["require_direction_consistency"]))
            and (two_x_return > 0 or not cast(bool, admission["require_positive_2x_cost_return"]))
        )
        rows.append(
            {
                "factor": factor,
                "mean_test_rank_ic": mean_ic,
                "positive_test_folds": positive_folds,
                "direction_consistent": direction_consistent,
                "one_x_chained_return": one_x_return,
                "two_x_chained_return": two_x_return,
                "research_status": "RESEARCH_ONLY" if passed else "REJECTED",
            }
        )
    return pl.DataFrame(rows).sort("factor")


def _with_evaluation_identity(
    frame: pl.DataFrame,
    *,
    fold: int,
    period: str,
    factor: str,
    horizon: int,
    direction: int,
) -> pl.DataFrame:
    return frame.with_columns(
        pl.lit(fold).alias("fold"),
        pl.lit(period).alias("period"),
        pl.lit(factor).alias("factor"),
        pl.lit(horizon).alias("horizon"),
        pl.lit(direction).alias("direction"),
    )


def _folds(config: Mapping[str, Any]) -> tuple[ResearchFoldV1, ...]:
    rows = cast(list[Mapping[str, Any]], config["walk_forward"]["folds"])
    return tuple(ResearchFoldV1(fold=index, **dict(row)) for index, row in enumerate(rows, 1))


def _cost_periods(project_root: Path, portfolio: Mapping[str, Any]) -> tuple[AShareCostPeriod, ...]:
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
    factor_config = cast(Mapping[str, Any], config["factors"])
    names = tuple(cast(list[str], factor_config["names"]))
    first_batch = names == CLASSIC_FACTOR_NAMES and "catalog" not in factor_config
    second_batch = (
        names == SECOND_BATCH_FACTOR_NAMES
        and factor_config.get("catalog") == "alpha158_second_batch_v1"
        and tuple(cast(list[str], factor_config["redundancy_reference_names"]))
        == CLASSIC_FACTOR_NAMES
        and float(factor_config["maximum_median_absolute_rank_correlation"]) == 0.80
    )
    third_batch = (
        names == THIRD_BATCH_FACTOR_NAMES
        and factor_config.get("catalog") == "alpha158_third_batch_v1"
        and tuple(cast(list[str], factor_config["redundancy_reference_names"]))
        == CLASSIC_FACTOR_NAMES + SECOND_BATCH_FACTOR_NAMES
        and float(factor_config["maximum_median_absolute_rank_correlation"]) == 0.80
    )
    if (
        not (first_batch or second_batch or third_batch)
        or tuple(cast(list[int], config["factors"]["horizons"])) != (1, 5, 20)
        or tuple(float(value) for value in config["portfolio"]["cost_multipliers"])
        != (0.5, 1.0, 2.0)
        or config["portfolio"]["selection_horizon_sessions"] != 20
        or type(threads) is not int
        or not 1 <= threads <= 4
    ):
        raise ValueError("invalid classic-factor config")


def _report(
    *,
    config: Mapping[str, Any],
    snapshot_id: str,
    snapshot_manifest_sha256: str,
    candidates: tuple[str, ...],
    panel: pl.DataFrame,
    results: Mapping[str, pl.DataFrame],
    summary: pl.DataFrame,
    conclusion: str,
) -> dict[str, object]:
    return {
        "schema_version": "m2-classic-factor-report-v1",
        "conclusion": conclusion,
        "hypothesis": config["research"]["hypothesis"],
        "snapshot_id": snapshot_id,
        "snapshot_manifest_sha256": snapshot_manifest_sha256,
        "candidate_symbol_count": len(candidates),
        "panel_rows": panel.height,
        "daily_ic_rows": results["daily_ic"].height,
        "target_rows": results["targets"].height,
        "factor_summary": summary.to_dicts(),
        "redundancy_summary": (
            results["redundancy_summary"].to_dicts() if "redundancy_summary" in results else []
        ),
        "timing": {
            "signal": "close of as_of session",
            "execution": "next exchange session open",
            "label": "adjusted open(t+1+h)/adjusted open(t+1)-1",
        },
        "caveats": [
            "The 2019 liquid universe is PIT at its freeze date but is not an evolving historical constituent universe.",
            "Historical ST flags, industry membership and authoritative suspension facts are unavailable in this snapshot.",
            "Missing exact next-session opens produce null labels and are never forward-filled.",
            "The non-overlapping 20-session portfolio is a factor diagnostic, not the formal A-share account replay.",
            "Minimum commission uses one million CNY; order-book impact and capacity are not estimated.",
            "Minute, L2 and fundamental factors are not approximated with daily bars.",
            "No result from this run may exceed RESEARCH_ONLY without separate forward and market-event admission evidence.",
        ],
    }


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
