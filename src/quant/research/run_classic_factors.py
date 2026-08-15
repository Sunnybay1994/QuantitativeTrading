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
    TushareBulkFundBarQuery,
    TushareBulkStockBarQuery,
    read_tushare_bulk_clean_fund_bars,
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
from quant.factors.classic_fourth_batch import (
    FOURTH_BATCH_FACTOR_NAMES,
    FOURTH_BATCH_FACTOR_SPECS,
    compute_fourth_batch_daily_factors,
)
from quant.factors.classic_fifth_batch import (
    FIFTH_BATCH_FACTOR_NAMES,
    FIFTH_BATCH_FACTOR_SPECS,
    compute_fifth_batch_daily_factors,
)
from quant.factors.classic_market_risk import (
    DOWNSIDE_BETA_FACTOR_NAMES,
    DOWNSIDE_BETA_FACTOR_SPECS,
    MARKET_RISK_CONTROL_NAMES,
    compute_classic_market_risk_factors,
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

_CODE_PATHS: tuple[str, ...] = (
    "src/quant/data/clean_snapshot_repository.py",
    "src/quant/factors/classic.py",
    "src/quant/factors/classic_second_batch.py",
    "src/quant/factors/classic_third_batch.py",
    "src/quant/research/classic_factor_evaluation.py",
    "src/quant/research/factor_labels.py",
    "src/quant/research/lightweight_run.py",
    "src/quant/research/run_classic_factors.py",
)
_MARKET_RISK_CODE_PATHS: tuple[str, ...] = _CODE_PATHS + (
    "src/quant/factors/classic_market_risk.py",
)
_FOURTH_BATCH_CODE_PATHS: tuple[str, ...] = _CODE_PATHS + (
    "src/quant/factors/classic_fourth_batch.py",
)
_FIFTH_BATCH_CODE_PATHS: tuple[str, ...] = _FOURTH_BATCH_CODE_PATHS + (
    "src/quant/factors/classic_fifth_batch.py",
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
    include_fund_input = False
    code_paths: tuple[str, ...] = _CODE_PATHS
    fixed_direction: int | None = None
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
    elif factor_names == FOURTH_BATCH_FACTOR_NAMES:
        second_batch_values = compute_second_batch_daily_factors(bars)
        third_batch_values = compute_third_batch_daily_factors(bars)
        fourth_batch_values = compute_fourth_batch_daily_factors(
            bars,
            sessions=sessions,
        )
        factor_values = (
            first_batch_values.join(
                second_batch_values.select(
                    "symbol", "trade_date", *SECOND_BATCH_FACTOR_NAMES
                ),
                on=["symbol", "trade_date"],
                how="inner",
                validate="1:1",
            )
            .join(
                third_batch_values.select(
                    "symbol", "trade_date", *THIRD_BATCH_FACTOR_NAMES
                ),
                on=["symbol", "trade_date"],
                how="inner",
                validate="1:1",
            )
            .join(
                fourth_batch_values,
                on=["symbol", "trade_date"],
                how="left",
                validate="1:1",
            )
        )
        factor_specs = FOURTH_BATCH_FACTOR_SPECS
        code_paths = _FOURTH_BATCH_CODE_PATHS
    elif factor_names == FIFTH_BATCH_FACTOR_NAMES:
        second_batch_values = compute_second_batch_daily_factors(bars)
        third_batch_values = compute_third_batch_daily_factors(bars)
        fourth_batch_values = compute_fourth_batch_daily_factors(
            bars,
            sessions=sessions,
        )
        fifth_batch_values = compute_fifth_batch_daily_factors(
            bars,
            sessions=sessions,
        )
        factor_values = (
            first_batch_values.join(
                second_batch_values.select(
                    "symbol", "trade_date", *SECOND_BATCH_FACTOR_NAMES
                ),
                on=["symbol", "trade_date"],
                how="inner",
                validate="1:1",
            )
            .join(
                third_batch_values.select(
                    "symbol", "trade_date", *THIRD_BATCH_FACTOR_NAMES
                ),
                on=["symbol", "trade_date"],
                how="inner",
                validate="1:1",
            )
            .join(
                fourth_batch_values,
                on=["symbol", "trade_date"],
                how="left",
                validate="1:1",
            )
            .join(
                fifth_batch_values,
                on=["symbol", "trade_date"],
                how="left",
                validate="1:1",
            )
        )
        factor_specs = FIFTH_BATCH_FACTOR_SPECS
        code_paths = _FIFTH_BATCH_CODE_PATHS
        fixed_direction = cast(int, config["max_lottery"]["expected_direction"])
    elif factor_names == DOWNSIDE_BETA_FACTOR_NAMES:
        market_risk = cast(Mapping[str, Any], config["market_risk"])
        benchmark_symbol = cast(str, market_risk["benchmark"])
        benchmark_bars = read_tushare_bulk_clean_fund_bars(
            data_root=data_root,
            query=TushareBulkFundBarQuery(
                snapshot_id=snapshot_id,
                start_date=cast(dt.date, data["warmup_start"]),
                end_date=cast(dt.date, data["research_end"]),
                symbols=(benchmark_symbol,),
                threads=args.threads,
            ),
        )
        market_risk_values = compute_classic_market_risk_factors(
            bars,
            benchmark_bars,
            sessions=sessions,
            benchmark_symbol=benchmark_symbol,
            window_sessions=cast(int, market_risk["window_sessions"]),
            minimum_down_market_observations=cast(
                int, market_risk["minimum_down_market_observations"]
            ),
            annualization_sessions=cast(int, market_risk["annualization_sessions"]),
            minimum_market_variance=float(market_risk["minimum_market_variance"]),
        )
        factor_values = first_batch_values.join(
            market_risk_values,
            on=["symbol", "trade_date"],
            how="left",
            validate="1:1",
        )
        factor_specs = DOWNSIDE_BETA_FACTOR_SPECS
        include_fund_input = True
        code_paths = _MARKET_RISK_CODE_PATHS
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
        fixed_direction=fixed_direction,
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
    if factor_names == DOWNSIDE_BETA_FACTOR_NAMES:
        coverage_config = cast(Mapping[str, Any], config["coverage"])
        market_risk_config = cast(Mapping[str, Any], config["market_risk"])
        coverage_daily, coverage_summary = evaluate_factor_coverage(
            panel,
            factors=factor_names,
            start_date=cast(dt.date, data["research_start"]),
            end_date=cast(dt.date, data["research_end"]),
            folds=folds,
            rebalance_every_sessions=cast(
                int, portfolio_config["rebalance_every_sessions"]
            ),
            minimum_rebalance_symbols=cast(
                int, coverage_config["minimum_rebalance_symbols"]
            ),
            minimum_median_coverage=float(
                coverage_config["minimum_median_coverage"]
            ),
        )
        schedule_alignment = evaluate_rebalance_schedule_alignment(
            panel,
            cast(pl.DataFrame, results["targets"]),
            factors=factor_names,
            folds=folds,
            rebalance_every_sessions=cast(
                int, portfolio_config["rebalance_every_sessions"]
            ),
        )
        summary = apply_market_risk_admission_gates(
            summary,
            fold_metrics=cast(pl.DataFrame, results["fold_metrics"]),
            redundancy_summary=cast(pl.DataFrame, results["redundancy_summary"]),
            coverage_summary=coverage_summary,
            schedule_alignment=schedule_alignment,
            expected_direction=cast(int, market_risk_config["expected_direction"]),
            maximum_median_absolute_rank_correlation=float(
                factor_config["maximum_median_absolute_rank_correlation"]
            ),
        )
        results["factor_coverage_daily"] = coverage_daily
        results["factor_coverage_summary"] = coverage_summary
        results["rebalance_schedule_alignment"] = schedule_alignment
    if factor_names == FOURTH_BATCH_FACTOR_NAMES:
        coverage_config = cast(Mapping[str, Any], config["coverage"])
        coverage_daily, coverage_summary = evaluate_factor_coverage(
            panel,
            factors=factor_names,
            start_date=cast(dt.date, data["research_start"]),
            end_date=cast(dt.date, data["research_end"]),
            folds=folds,
            rebalance_every_sessions=cast(
                int, portfolio_config["rebalance_every_sessions"]
            ),
            minimum_rebalance_symbols=cast(
                int, coverage_config["minimum_rebalance_symbols"]
            ),
            minimum_median_coverage=float(
                coverage_config["minimum_median_coverage"]
            ),
        )
        schedule_alignment = evaluate_rebalance_schedule_alignment(
            panel,
            cast(pl.DataFrame, results["targets"]),
            factors=factor_names,
            folds=folds,
            rebalance_every_sessions=cast(
                int, portfolio_config["rebalance_every_sessions"]
            ),
        )
        summary = apply_fourth_batch_admission_gates(
            summary,
            redundancy_summary=cast(pl.DataFrame, results["redundancy_summary"]),
            coverage_summary=coverage_summary,
            schedule_alignment=schedule_alignment,
            maximum_median_absolute_rank_correlation=float(
                factor_config["maximum_median_absolute_rank_correlation"]
            ),
        )
        results["factor_coverage_daily"] = coverage_daily
        results["factor_coverage_summary"] = coverage_summary
        results["rebalance_schedule_alignment"] = schedule_alignment
    if factor_names == FIFTH_BATCH_FACTOR_NAMES:
        coverage_config = cast(Mapping[str, Any], config["coverage"])
        lottery_config = cast(Mapping[str, Any], config["max_lottery"])
        coverage_daily, coverage_summary = evaluate_factor_coverage(
            panel,
            factors=factor_names,
            start_date=cast(dt.date, data["research_start"]),
            end_date=cast(dt.date, data["research_end"]),
            folds=folds,
            rebalance_every_sessions=cast(
                int, portfolio_config["rebalance_every_sessions"]
            ),
            minimum_rebalance_symbols=cast(
                int, coverage_config["minimum_rebalance_symbols"]
            ),
            minimum_median_coverage=float(
                coverage_config["minimum_median_coverage"]
            ),
        )
        schedule_alignment = evaluate_rebalance_schedule_alignment(
            panel,
            cast(pl.DataFrame, results["targets"]),
            factors=factor_names,
            folds=folds,
            rebalance_every_sessions=cast(
                int, portfolio_config["rebalance_every_sessions"]
            ),
        )
        summary = apply_fifth_batch_admission_gates(
            summary,
            fold_metrics=cast(pl.DataFrame, results["fold_metrics"]),
            redundancy_summary=cast(pl.DataFrame, results["redundancy_summary"]),
            coverage_summary=coverage_summary,
            schedule_alignment=schedule_alignment,
            expected_direction=cast(int, lottery_config["expected_direction"]),
            maximum_median_absolute_rank_correlation=float(
                factor_config["maximum_median_absolute_rank_correlation"]
            ),
        )
        results["factor_coverage_daily"] = coverage_daily
        results["factor_coverage_summary"] = coverage_summary
        results["rebalance_schedule_alignment"] = schedule_alignment
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
    if "factor_coverage_daily" in results:
        outputs["factor_coverage_daily.parquet"] = _parquet(
            cast(pl.DataFrame, results["factor_coverage_daily"])
        )
        outputs["factor_coverage_summary.parquet"] = _parquet(
            cast(pl.DataFrame, results["factor_coverage_summary"])
        )
        outputs["rebalance_schedule_alignment.parquet"] = _parquet(
            cast(pl.DataFrame, results["rebalance_schedule_alignment"])
        )
    input_digests: tuple[ResearchInputDigestV1, ...] = (
        ResearchInputDigestV1(
            name="tushare-stock-bars",
            rows=snapshot.stock_rows,
            min_date=cast(dt.date, data["warmup_start"]),
            max_date=cast(dt.date, data["research_end"]),
            content_sha256=snapshot.manifest_sha256,
        ),
    )
    if include_fund_input:
        input_digests = (
            ResearchInputDigestV1(
                name="tushare-fund-bars",
                rows=snapshot.fund_rows,
                min_date=cast(dt.date, data["warmup_start"]),
                max_date=cast(dt.date, data["research_end"]),
                content_sha256=snapshot.manifest_sha256,
            ),
            *input_digests,
        )
    aggregate_metrics: list[tuple[str, float | int]] = [
        (
            "best_mean_test_rank_ic",
            cast(float, summary.get_column("mean_test_rank_ic").max()),
        ),
        ("candidate_symbols", len(candidates)),
        ("factor_count", len(factor_names)),
        ("passing_factor_count", passing.height),
        (
            "redundancy_eligible_count",
            cast(int, summary.get_column("combination_eligible").sum())
            if "combination_eligible" in summary.columns
            else 0,
        ),
    ]
    if "coverage_passed" in summary.columns:
        aggregate_metrics.append(
            (
                "coverage_eligible_count",
                cast(int, summary.get_column("coverage_passed").sum()),
            )
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
        code_sha256=compute_code_sha256(
            project_root=project_root, relative_paths=code_paths
        ),
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
        inputs=input_digests,
        outputs=(),
        aggregate_metrics=tuple(sorted(aggregate_metrics)),
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
    fixed_direction: int | None = None,
) -> dict[str, pl.DataFrame]:
    """Evaluate untouched tests after validation or a pre-registered direction."""
    if fixed_direction is not None and (
        type(fixed_direction) is not int or fixed_direction not in {-1, 1}
    ):
        raise ValueError("invalid fixed factor direction")
    daily_frames: list[pl.DataFrame] = []
    group_frames: list[pl.DataFrame] = []
    metric_rows: list[dict[str, object]] = []
    target_frames: list[pl.DataFrame] = []
    nav_frames: list[pl.DataFrame] = []
    for fold in folds:
        for factor in factors:
            raw_validation_daily, raw_validation_groups, raw_validation_metrics = (
                evaluate_factor_period(
                    panel,
                    factor=factor,
                    horizon=20,
                    start_date=fold.validation_start,
                    end_date=fold.validation_end,
                    minimum_symbols=minimum_symbols,
                    groups=groups,
                    newey_west_lag=ic_newey_west_lag,
                )
            )
            validation_observed_direction = (
                1 if raw_validation_metrics["rank_ic_mean"] >= 0 else -1
            )
            direction = (
                validation_observed_direction
                if fixed_direction is None
                else fixed_direction
            )
            if direction == 1:
                validation_daily = raw_validation_daily
                validation_groups = raw_validation_groups
                validation_metrics = raw_validation_metrics
            else:
                validation_daily, validation_groups, validation_metrics = (
                    evaluate_factor_period(
                        panel,
                        factor=factor,
                        horizon=20,
                        start_date=fold.validation_start,
                        end_date=fold.validation_end,
                        minimum_symbols=minimum_symbols,
                        groups=groups,
                        direction=direction,
                        newey_west_lag=ic_newey_west_lag,
                    )
                )
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
                metric_row: dict[str, object] = {
                    "factor": factor,
                    "fold": fold.fold,
                    "direction": direction,
                    "cost_multiplier": float(multiplier),
                    "validation_rank_ic": abs(
                        float(validation_metrics["rank_ic_mean"])
                    ),
                    "test_rank_ic": float(test20_metrics["rank_ic_mean"]),
                    "test_ic_dates": int(test20_metrics["dates"]),
                    **portfolio_metrics,
                }
                if fixed_direction is not None:
                    metric_row["validation_observed_direction"] = (
                        validation_observed_direction
                    )
                metric_rows.append(metric_row)
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


def evaluate_factor_coverage(
    panel: pl.DataFrame,
    *,
    factors: tuple[str, ...],
    start_date: dt.date,
    end_date: dt.date,
    folds: tuple[ResearchFoldV1, ...],
    rebalance_every_sessions: int,
    minimum_rebalance_symbols: int,
    minimum_median_coverage: float,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Measure all-date and pre-registered rebalance-date factor coverage."""
    if (
        not isinstance(panel, pl.DataFrame)
        or panel.is_empty()
        or type(factors) is not tuple
        or not factors
        or any(type(name) is not str or name not in panel.columns for name in factors)
        or type(start_date) is not dt.date
        or type(end_date) is not dt.date
        or end_date < start_date
        or type(folds) is not tuple
        or not folds
        or any(type(fold) is not ResearchFoldV1 for fold in folds)
        or type(rebalance_every_sessions) is not int
        or rebalance_every_sessions <= 0
        or type(minimum_rebalance_symbols) is not int
        or minimum_rebalance_symbols < 2
        or type(minimum_median_coverage) is not float
        or not math.isfinite(minimum_median_coverage)
        or not 0 < minimum_median_coverage <= 1
        or "exit_date_20" not in panel.columns
    ):
        raise ValueError("invalid factor coverage request")
    research = panel.filter(
        pl.col("trade_date").is_between(start_date, end_date, closed="both")
    )
    if research.is_empty():
        raise ValueError("factor coverage research window is empty")
    scheduled_dates = tuple(
        date
        for fold in folds
        for date in _scheduled_rebalance_dates(
            research,
            fold=fold,
            rebalance_every_sessions=rebalance_every_sessions,
        )
    )
    daily_frames: list[pl.DataFrame] = []
    summary_rows: list[dict[str, object]] = []
    for factor in factors:
        valid = pl.col(factor).is_not_null() & pl.col(factor).is_finite()
        daily = (
            research.group_by("trade_date")
            .agg(
                pl.len().alias("eligible_rows"),
                valid.fill_null(False).sum().alias("valid_rows"),
            )
            .with_columns(
                (pl.col("valid_rows") / pl.col("eligible_rows")).alias("coverage"),
                pl.lit(factor).alias("factor"),
                pl.col("trade_date")
                .is_in(scheduled_dates)
                .alias("scheduled_rebalance"),
            )
            .select(
                "factor",
                "trade_date",
                "eligible_rows",
                "valid_rows",
                "coverage",
                "scheduled_rebalance",
            )
            .sort("factor", "trade_date")
        )
        scheduled = daily.filter(pl.col("scheduled_rebalance"))
        minimum_valid_rows = (
            cast(int, scheduled.get_column("valid_rows").min())
            if not scheduled.is_empty()
            else 0
        )
        median_coverage = cast(float, daily.get_column("coverage").median())
        summary_rows.append(
            {
                "factor": factor,
                "dates": daily.height,
                "scheduled_rebalance_dates": len(scheduled_dates),
                "minimum_rebalance_valid_rows": minimum_valid_rows,
                "median_coverage": median_coverage,
                "coverage_passed": minimum_valid_rows >= minimum_rebalance_symbols
                and median_coverage >= minimum_median_coverage,
            }
        )
        daily_frames.append(daily)
    return (
        pl.concat(daily_frames).sort("factor", "trade_date"),
        pl.DataFrame(summary_rows).sort("factor"),
    )


def evaluate_rebalance_schedule_alignment(
    panel: pl.DataFrame,
    targets: pl.DataFrame,
    *,
    factors: tuple[str, ...],
    folds: tuple[ResearchFoldV1, ...],
    rebalance_every_sessions: int,
) -> pl.DataFrame:
    """Compare emitted target dates with the factor-independent frozen schedule."""
    if (
        not isinstance(panel, pl.DataFrame)
        or panel.is_empty()
        or "trade_date" not in panel.columns
        or "exit_date_20" not in panel.columns
        or not isinstance(targets, pl.DataFrame)
        or targets.is_empty()
        or not {"as_of", "factor", "fold"}.issubset(targets.columns)
        or type(factors) is not tuple
        or not factors
        or any(type(name) is not str for name in factors)
        or type(folds) is not tuple
        or not folds
        or any(type(fold) is not ResearchFoldV1 for fold in folds)
        or type(rebalance_every_sessions) is not int
        or rebalance_every_sessions <= 0
    ):
        raise ValueError("invalid rebalance schedule alignment request")
    rows: list[dict[str, object]] = []
    for factor in factors:
        for fold in folds:
            expected = _scheduled_rebalance_dates(
                panel,
                fold=fold,
                rebalance_every_sessions=rebalance_every_sessions,
            )
            actual = tuple(
                targets.filter(
                    (pl.col("factor") == factor) & (pl.col("fold") == fold.fold)
                )
                .get_column("as_of")
                .unique()
                .sort()
                .to_list()
            )
            expected_set = set(expected)
            actual_set = set(actual)
            missing_dates = tuple(sorted(expected_set - actual_set))
            unexpected_dates = tuple(sorted(actual_set - expected_set))
            rows.append(
                {
                    "factor": factor,
                    "fold": fold.fold,
                    "expected_rebalance_dates": len(expected),
                    "actual_rebalance_dates": len(actual),
                    "missing_rebalance_dates": len(missing_dates),
                    "unexpected_rebalance_dates": len(unexpected_dates),
                    "missing_dates": missing_dates,
                    "unexpected_dates": unexpected_dates,
                    "schedule_aligned": actual == expected,
                }
            )
    return pl.DataFrame(rows).sort("factor", "fold")


def apply_market_risk_admission_gates(
    summary: pl.DataFrame,
    *,
    fold_metrics: pl.DataFrame,
    redundancy_summary: pl.DataFrame,
    coverage_summary: pl.DataFrame,
    schedule_alignment: pl.DataFrame,
    expected_direction: int,
    maximum_median_absolute_rank_correlation: float,
) -> pl.DataFrame:
    """Apply expected-direction, coverage, and redundancy gates to market risk."""
    if (
        not isinstance(summary, pl.DataFrame)
        or summary.is_empty()
        or not isinstance(fold_metrics, pl.DataFrame)
        or fold_metrics.is_empty()
        or not isinstance(redundancy_summary, pl.DataFrame)
        or redundancy_summary.is_empty()
        or not isinstance(coverage_summary, pl.DataFrame)
        or coverage_summary.is_empty()
        or not isinstance(schedule_alignment, pl.DataFrame)
        or schedule_alignment.is_empty()
        or expected_direction not in {-1, 1}
        or type(maximum_median_absolute_rank_correlation) is not float
        or not 0 < maximum_median_absolute_rank_correlation < 1
    ):
        raise ValueError("invalid market-risk admission gate request")
    directions = (
        fold_metrics.filter(pl.col("cost_multiplier") == 1.0)
        .group_by("factor")
        .agg(
            pl.col("direction").n_unique().alias("observed_direction_count"),
            pl.col("direction").first().alias("observed_direction"),
        )
    )
    redundancy = redundancy_summary.group_by("factor_a").agg(
        pl.col("median_abs_rank_corr").max().alias("max_median_abs_rank_corr")
    )
    schedule = schedule_alignment.group_by("factor").agg(
        pl.col("schedule_aligned").all().alias("schedule_alignment_passed")
    )
    drop_columns = [
        column
        for column in ("max_median_abs_rank_corr", "combination_eligible")
        if column in summary.columns
    ]
    summary_base = summary.drop(drop_columns) if drop_columns else summary
    joined = (
        summary_base
        .join(directions, on="factor", how="left", validate="1:1")
        .join(
            redundancy,
            left_on="factor",
            right_on="factor_a",
            how="left",
            validate="1:1",
        )
        .join(coverage_summary, on="factor", how="left", validate="1:1")
        .join(schedule, on="factor", how="left", validate="1:1")
        .with_columns(
            pl.lit(expected_direction).alias("expected_direction"),
            (
                (pl.col("observed_direction_count") == 1)
                & (pl.col("observed_direction") == expected_direction)
            ).alias("expected_direction_passed"),
            (
                pl.col("max_median_abs_rank_corr").is_not_null()
                & (
                    pl.col("max_median_abs_rank_corr")
                    < maximum_median_absolute_rank_correlation
                )
            ).alias("redundancy_passed"),
        )
        .with_columns(pl.col("redundancy_passed").alias("combination_eligible"))
        .with_columns(
            pl.when(
                (pl.col("research_status") == "RESEARCH_ONLY")
                & pl.col("expected_direction_passed")
                & pl.col("redundancy_passed")
                & pl.col("coverage_passed")
                & pl.col("schedule_alignment_passed")
            )
            .then(pl.lit("RESEARCH_ONLY"))
            .otherwise(pl.lit("REJECTED"))
            .alias("research_status")
        )
    )
    return joined.sort("factor")


def apply_fourth_batch_admission_gates(
    summary: pl.DataFrame,
    *,
    redundancy_summary: pl.DataFrame,
    coverage_summary: pl.DataFrame,
    schedule_alignment: pl.DataFrame,
    maximum_median_absolute_rank_correlation: float,
) -> pl.DataFrame:
    """Fail closed on coverage, redundancy and target-schedule alignment."""
    if (
        not isinstance(summary, pl.DataFrame)
        or summary.is_empty()
        or not isinstance(redundancy_summary, pl.DataFrame)
        or redundancy_summary.is_empty()
        or not isinstance(coverage_summary, pl.DataFrame)
        or coverage_summary.is_empty()
        or not isinstance(schedule_alignment, pl.DataFrame)
        or schedule_alignment.is_empty()
        or type(maximum_median_absolute_rank_correlation) is not float
        or not 0 < maximum_median_absolute_rank_correlation < 1
    ):
        raise ValueError("invalid fourth-batch admission gate request")
    redundancy = redundancy_summary.group_by("factor_a").agg(
        pl.col("median_abs_rank_corr").max().alias("max_median_abs_rank_corr")
    )
    schedule = schedule_alignment.group_by("factor").agg(
        pl.col("schedule_aligned").all().alias("schedule_alignment_passed")
    )
    drop_columns = [
        column
        for column in ("max_median_abs_rank_corr", "combination_eligible")
        if column in summary.columns
    ]
    summary_base = summary.drop(drop_columns) if drop_columns else summary
    return (
        summary_base.join(
            redundancy,
            left_on="factor",
            right_on="factor_a",
            how="left",
            validate="1:1",
        )
        .join(coverage_summary, on="factor", how="left", validate="1:1")
        .join(schedule, on="factor", how="left", validate="1:1")
        .with_columns(
            (
                pl.col("max_median_abs_rank_corr").is_not_null()
                & (
                    pl.col("max_median_abs_rank_corr")
                    < maximum_median_absolute_rank_correlation
                )
            ).alias("redundancy_passed")
        )
        .with_columns(pl.col("redundancy_passed").alias("combination_eligible"))
        .with_columns(
            pl.when(
                (pl.col("research_status") == "RESEARCH_ONLY")
                & pl.col("redundancy_passed")
                & pl.col("coverage_passed")
                & pl.col("schedule_alignment_passed")
            )
            .then(pl.lit("RESEARCH_ONLY"))
            .otherwise(pl.lit("REJECTED"))
            .alias("research_status")
        )
        .sort("factor")
    )


def apply_fifth_batch_admission_gates(
    summary: pl.DataFrame,
    *,
    fold_metrics: pl.DataFrame,
    redundancy_summary: pl.DataFrame,
    coverage_summary: pl.DataFrame,
    schedule_alignment: pl.DataFrame,
    expected_direction: int,
    maximum_median_absolute_rank_correlation: float,
) -> pl.DataFrame:
    """Apply fixed-direction, coverage, redundancy and schedule gates to MAX."""
    if (
        not isinstance(summary, pl.DataFrame)
        or summary.is_empty()
        or not isinstance(fold_metrics, pl.DataFrame)
        or fold_metrics.is_empty()
        or not {
            "factor",
            "cost_multiplier",
            "direction",
            "validation_observed_direction",
        }.issubset(fold_metrics.columns)
        or not isinstance(redundancy_summary, pl.DataFrame)
        or redundancy_summary.is_empty()
        or not isinstance(coverage_summary, pl.DataFrame)
        or coverage_summary.is_empty()
        or not isinstance(schedule_alignment, pl.DataFrame)
        or schedule_alignment.is_empty()
        or expected_direction not in {-1, 1}
        or type(maximum_median_absolute_rank_correlation) is not float
        or not 0 < maximum_median_absolute_rank_correlation < 1
    ):
        raise ValueError("invalid fifth-batch admission gate request")
    directions = (
        fold_metrics.filter(pl.col("cost_multiplier") == 1.0)
        .group_by("factor")
        .agg(
            pl.col("direction").n_unique().alias("selected_direction_count"),
            pl.col("direction").first().alias("selected_direction"),
            (
                pl.col("validation_observed_direction") == expected_direction
            ).all().alias("validation_direction_passed"),
        )
    )
    redundancy = redundancy_summary.group_by("factor_a").agg(
        pl.col("median_abs_rank_corr").max().alias("max_median_abs_rank_corr")
    )
    schedule = schedule_alignment.group_by("factor").agg(
        pl.col("schedule_aligned").all().alias("schedule_alignment_passed")
    )
    drop_columns = [
        column
        for column in ("max_median_abs_rank_corr", "combination_eligible")
        if column in summary.columns
    ]
    summary_base = summary.drop(drop_columns) if drop_columns else summary
    return (
        summary_base.join(directions, on="factor", how="left", validate="1:1")
        .join(
            redundancy,
            left_on="factor",
            right_on="factor_a",
            how="left",
            validate="1:1",
        )
        .join(coverage_summary, on="factor", how="left", validate="1:1")
        .join(schedule, on="factor", how="left", validate="1:1")
        .with_columns(
            pl.lit(expected_direction).alias("expected_direction"),
            (
                (pl.col("selected_direction_count") == 1)
                & (pl.col("selected_direction") == expected_direction)
            ).alias("fixed_direction_passed"),
            (
                pl.col("max_median_abs_rank_corr").is_not_null()
                & (
                    pl.col("max_median_abs_rank_corr")
                    < maximum_median_absolute_rank_correlation
                )
            ).alias("redundancy_passed"),
        )
        .with_columns(pl.col("redundancy_passed").alias("combination_eligible"))
        .with_columns(
            pl.when(
                (pl.col("research_status") == "RESEARCH_ONLY")
                & pl.col("fixed_direction_passed")
                & pl.col("validation_direction_passed")
                & pl.col("redundancy_passed")
                & pl.col("coverage_passed")
                & pl.col("schedule_alignment_passed")
            )
            .then(pl.lit("RESEARCH_ONLY"))
            .otherwise(pl.lit("REJECTED"))
            .alias("research_status")
        )
        .sort("factor")
    )


def _scheduled_rebalance_dates(
    panel: pl.DataFrame,
    *,
    fold: ResearchFoldV1,
    rebalance_every_sessions: int,
) -> tuple[dt.date, ...]:
    return tuple(
        panel.filter(
            pl.col("trade_date").is_between(
                fold.test_start, fold.test_end, closed="both"
            )
            & (pl.col("exit_date_20") <= fold.test_end)
        )
        .get_column("trade_date")
        .unique()
        .sort()
        .to_list()[::rebalance_every_sessions]
    )


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
    market_risk = cast(Mapping[str, Any], config.get("market_risk", {}))
    max_lottery = cast(Mapping[str, Any], config.get("max_lottery", {}))
    coverage = cast(Mapping[str, Any], config.get("coverage", {}))
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
    fourth_batch = (
        names == FOURTH_BATCH_FACTOR_NAMES
        and factor_config.get("catalog") == "alpha158_fourth_batch_v1"
        and tuple(cast(list[str], factor_config["redundancy_reference_names"]))
        == CLASSIC_FACTOR_NAMES + SECOND_BATCH_FACTOR_NAMES + THIRD_BATCH_FACTOR_NAMES
        and float(factor_config["maximum_median_absolute_rank_correlation"]) == 0.80
        and coverage.get("minimum_rebalance_symbols") == 100
        and float(coverage.get("minimum_median_coverage", 0.0)) == 0.80
    )
    downside_beta = (
        names == DOWNSIDE_BETA_FACTOR_NAMES
        and factor_config.get("catalog") == "downside_beta_60_vs_510300_v1"
        and tuple(cast(list[str], factor_config["redundancy_reference_names"]))
        == CLASSIC_FACTOR_NAMES + MARKET_RISK_CONTROL_NAMES
        and float(factor_config["maximum_median_absolute_rank_correlation"]) == 0.80
        and market_risk.get("benchmark") == "510300.SH"
        and market_risk.get("window_sessions") == 60
        and market_risk.get("minimum_down_market_observations") == 15
        and market_risk.get("annualization_sessions") == 252
        and float(market_risk.get("minimum_market_variance", 0.0)) == 1e-12
        and market_risk.get("expected_direction") == -1
        and coverage.get("minimum_rebalance_symbols") == 100
        and float(coverage.get("minimum_median_coverage", 0.0)) == 0.80
    )
    fifth_batch = (
        names == FIFTH_BATCH_FACTOR_NAMES
        and factor_config.get("catalog") == "max_lottery_fifth_batch_v1"
        and tuple(cast(list[str], factor_config["redundancy_reference_names"]))
        == CLASSIC_FACTOR_NAMES
        + SECOND_BATCH_FACTOR_NAMES
        + THIRD_BATCH_FACTOR_NAMES
        + FOURTH_BATCH_FACTOR_NAMES
        + ("liquidity_20",)
        and float(factor_config["maximum_median_absolute_rank_correlation"]) == 0.80
        and max_lottery.get("window_sessions") == 20
        and max_lottery.get("return_type") == "simple_adjusted_close"
        and max_lottery.get("expected_direction") == -1
        and max_lottery.get("trial_budget") == 1
        and coverage.get("minimum_rebalance_symbols") == 100
        and float(coverage.get("minimum_median_coverage", 0.0)) == 0.80
    )
    if (
        not (
            first_batch
            or second_batch
            or third_batch
            or fourth_batch
            or downside_beta
            or fifth_batch
        )
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
    caveats = [
        "The 2019 liquid universe is PIT at its freeze date but is not an "
        "evolving historical constituent universe.",
        "Historical ST flags, industry membership and authoritative suspension "
        "facts are unavailable in this snapshot.",
        "Missing exact next-session opens produce null labels and are never forward-filled.",
        "The non-overlapping 20-session portfolio is a factor diagnostic, not "
        "the formal A-share account replay.",
        "Minimum commission uses one million CNY; order-book impact and capacity "
        "are not estimated.",
        "Minute, L2 and fundamental factors are not approximated with daily bars.",
        "No result from this run may exceed RESEARCH_ONLY without separate forward "
        "and market-event admission evidence.",
    ]
    if "market_risk" in config:
        caveats.extend(
            [
                "The registered negative direction is a defensive low-beta/BAB-style "
                "hypothesis, not a claim that the classic downside-risk premium "
                "predicts a negative return relation.",
                "Downside-beta evidence is mixed in the literature; direction, "
                "coverage, redundancy and exact rebalance-schedule gates are "
                "therefore fail-closed.",
            ]
        )
    if cast(Mapping[str, Any], config["factors"]).get("catalog") == (
        "alpha158_fourth_batch_v1"
    ):
        caveats.extend(
            [
                "RESI20, IMXD20 and VSUMD20 have no pre-registered permanent "
                "cross-sectional sign; each fold freezes its sign on validation only.",
                "Missing exchange-session observations invalidate rolling windows; "
                "coverage, redundancy and exact rebalance-schedule gates are fail-closed.",
            ]
        )
    if cast(Mapping[str, Any], config["factors"]).get("catalog") == (
        "max_lottery_fifth_batch_v1"
    ):
        caveats.extend(
            [
                "MAX is the greatest signed daily adjusted-close return over twenty "
                "sessions, not absolute return and not Qlib Alpha158 Max(high,20)/close.",
                "The economic direction is pre-registered at -1; validation may reject "
                "that direction but cannot reverse the tested portfolio.",
                "A historical pass would still require daily-basic size and turnover "
                "controls before forward observation.",
            ]
        )
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
        "factor_coverage_summary": (
            results["factor_coverage_summary"].to_dicts()
            if "factor_coverage_summary" in results
            else []
        ),
        "rebalance_schedule_alignment": (
            results["rebalance_schedule_alignment"].to_dicts()
            if "rebalance_schedule_alignment" in results
            else []
        ),
        "market_risk": config.get("market_risk", {}),
        "max_lottery": config.get("max_lottery", {}),
        "timing": {
            "signal": "close of as_of session",
            "execution": "next exchange session open",
            "label": "adjusted open(t+1+h)/adjusted open(t+1)-1",
        },
        "caveats": caveats,
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
