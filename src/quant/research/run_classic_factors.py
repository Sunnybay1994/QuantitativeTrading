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
from quant.factors.classic_sixth_batch import (
    SIXTH_BATCH_FACTOR_NAMES,
    SIXTH_BATCH_FACTOR_SPECS,
    compute_sixth_batch_daily_factors,
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
_SIXTH_BATCH_CODE_PATHS: tuple[str, ...] = _FIFTH_BATCH_CODE_PATHS + (
    "src/quant/factors/classic_sixth_batch.py",
)
_SIXTH_BATCH_CATALOG = "alpha101_price_volume_geometry_sixth_batch_v1"
_SIXTH_BATCH_HYPOTHESIS_ID = "m2-alpha101-price-volume-geometry-sixth-batch-v1"
_SIXTH_BATCH_SNAPSHOT_ID = (
    "b79a7b5e66dee0ae439c030078414157ca6c1f3b6ce7fbe5e36ff3910c1089d2"
)
_SIXTH_BATCH_COST_SEMANTIC_SHA256 = (
    "b2041d8495aa408de0bd264d6c03eb7e4d174e03f120289bc8471cbb5ea0a959"
)
_SIXTH_BATCH_REFERENCE_NAMES = (
    CLASSIC_FACTOR_NAMES
    + SECOND_BATCH_FACTOR_NAMES
    + THIRD_BATCH_FACTOR_NAMES
    + FOURTH_BATCH_FACTOR_NAMES
    + FIFTH_BATCH_FACTOR_NAMES
    + ("liquidity_20",)
)
_SIXTH_BATCH_SECTION_KEYS = frozenset(
    {
        "schema_version",
        "hypothesis_id",
        "factors",
        "correlation_window_sessions",
        "delta_lag_sessions",
        "alpha041_price_basis",
        "alpha041_vwap_formula",
        "direction_policy",
        "trial_budget",
        "trial_delta",
        "attempt_ordinal",
    }
)
_SIXTH_BATCH_FROZEN_FOLDS: tuple[dict[str, dt.date], ...] = (
    {
        "train_start": dt.date(2020, 1, 1),
        "train_end": dt.date(2020, 12, 31),
        "validation_start": dt.date(2021, 1, 1),
        "validation_end": dt.date(2021, 12, 31),
        "test_start": dt.date(2022, 1, 1),
        "test_end": dt.date(2022, 12, 31),
    },
    {
        "train_start": dt.date(2020, 1, 1),
        "train_end": dt.date(2022, 12, 31),
        "validation_start": dt.date(2023, 1, 1),
        "validation_end": dt.date(2023, 12, 31),
        "test_start": dt.date(2024, 1, 1),
        "test_end": dt.date(2024, 12, 31),
    },
    {
        "train_start": dt.date(2020, 1, 1),
        "train_end": dt.date(2024, 12, 31),
        "validation_start": dt.date(2025, 1, 1),
        "validation_end": dt.date(2025, 12, 31),
        "test_start": dt.date(2026, 1, 1),
        "test_end": dt.date(2026, 8, 13),
    },
)
_FROZEN_MAX_R15_CONFIG_SHA256 = (
    "baa384bbdcc1406fa53b6b7c689087ac03eeebf99db852f37ba9d03e40ca2c6e"
)
_COST_SECTION_KEYS = frozenset(
    {
        "schedule_version",
        "stamp_tax_source",
        "transfer_fee_source",
        "scaled_components",
        "a_share_periods",
    }
)
_COST_PERIOD_REQUIRED_KEYS = frozenset(
    {
        "effective_from",
        "commission_rate",
        "commission_min",
        "stamp_tax_sell",
        "transfer_fee",
        "slippage",
    }
)
_COST_PERIOD_KEYS = _COST_PERIOD_REQUIRED_KEYS | {"effective_to"}
_COST_DECIMAL_FIELDS = (
    "commission_rate",
    "commission_min",
    "stamp_tax_sell",
    "transfer_fee",
    "slippage",
)
_COST_SCALED_COMPONENTS = ("commission_rate", "commission_min", "slippage")


from quant.research.run_classic_factors_evaluate import (
    _aggregate_redundancy_by_factor,
    apply_fourth_batch_admission_gates,
    apply_fifth_batch_admission_gates,
    apply_market_risk_admission_gates,
    evaluate_factor_coverage,
    evaluate_primary_group_monotonicity,
    evaluate_rebalance_schedule_alignment,
    evaluate_walk_forward,
    select_frozen_liquid_universe,
    summarize_factors,
)
from quant.research.run_classic_factors_admission import (
    _build_input_digests,
    _cost_decimal,
    _cost_decimal_text,
    _cost_periods,
    _cost_schedule_binding,
    _cost_schedule_binding_from_payload,
    _cost_schedule_input_digest,
    _folds,
    _normalize_main_config_payload,
    _validate_config,
    _validate_sixth_batch_config,
)
from quant.research.run_classic_factors_report import _inside, _parquet, _report

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
    config_text = _normalize_main_config_payload(config_payload)
    config = cast(dict[str, Any], tomllib.loads(config_text))
    _validate_config(config, threads=args.threads)

    data = cast(Mapping[str, Any], config["data"])
    universe_config = cast(Mapping[str, Any], config["universe"])
    factor_config = cast(Mapping[str, Any], config["factors"])
    portfolio_config = cast(Mapping[str, Any], config["portfolio"])
    factor_names = tuple(cast(list[str], factor_config["names"]))
    fifth_batch = factor_names == FIFTH_BATCH_FACTOR_NAMES
    sixth_batch = factor_names == SIXTH_BATCH_FACTOR_NAMES
    config_sha256 = hashlib.sha256(
        config_text.encode("utf-8") if fifth_batch else config_payload
    ).hexdigest()
    cost_periods: tuple[AShareCostPeriod, ...] | None = None
    cost_semantic_sha256: str | None = None
    if fifth_batch or sixth_batch:
        if fifth_batch and config_sha256 != _FROZEN_MAX_R15_CONFIG_SHA256:
            raise ValueError("frozen MAX R15 config payload identity mismatch")
        cost_periods, cost_semantic_sha256 = _cost_schedule_binding(
            project_root, portfolio_config
        )
        expected_cost_semantic_sha256 = portfolio_config["cost_schedule_semantic_sha256"]
        if cost_semantic_sha256 != expected_cost_semantic_sha256:
            raise ValueError("classic cost schedule semantic identity mismatch")
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
    elif factor_names == SIXTH_BATCH_FACTOR_NAMES:
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
        sixth_batch_values = compute_sixth_batch_daily_factors(
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
            .join(
                sixth_batch_values,
                on=["symbol", "trade_date"],
                how="left",
                validate="1:1",
            )
        )
        factor_specs = SIXTH_BATCH_FACTOR_SPECS
        code_paths = _SIXTH_BATCH_CODE_PATHS
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
    if cost_periods is None:
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
        redundancy_by_factor = _aggregate_redundancy_by_factor(
            summary, redundancy_summary
        )
        summary = summary.join(
            redundancy_by_factor,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
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
    if factor_names in (FOURTH_BATCH_FACTOR_NAMES, SIXTH_BATCH_FACTOR_NAMES):
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
        primary_group_monotonicity = evaluate_primary_group_monotonicity(
            cast(pl.DataFrame, results["group_returns"]),
            panel=panel,
            factor=factor_names[0],
            folds=folds,
            minimum_symbols=cast(int, factor_config["minimum_daily_symbols"]),
            expected_direction=cast(int, lottery_config["expected_direction"]),
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
            primary_group_monotonicity=primary_group_monotonicity,
        )
        results["primary_group_monotonicity"] = primary_group_monotonicity
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
    if "primary_group_monotonicity" in results:
        outputs["primary_group_monotonicity.parquet"] = _parquet(
            cast(pl.DataFrame, results["primary_group_monotonicity"])
        )
    market_input_digests: tuple[ResearchInputDigestV1, ...] = (
        ResearchInputDigestV1(
            name="tushare-stock-bars",
            rows=snapshot.stock_rows,
            min_date=cast(dt.date, data["warmup_start"]),
            max_date=cast(dt.date, data["research_end"]),
            content_sha256=snapshot.manifest_sha256,
        ),
    )
    if include_fund_input:
        market_input_digests = (
            ResearchInputDigestV1(
                name="tushare-fund-bars",
                rows=snapshot.fund_rows,
                min_date=cast(dt.date, data["warmup_start"]),
                max_date=cast(dt.date, data["research_end"]),
                content_sha256=snapshot.manifest_sha256,
            ),
            *market_input_digests,
        )
    input_digests = _build_input_digests(
        market_input_digests,
        fifth_batch=fifth_batch,
        sixth_batch=sixth_batch,
        cost_periods=cost_periods,
        cost_semantic_sha256=cost_semantic_sha256,
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
    if "primary_monotonicity_passed" in summary.columns:
        aggregate_metrics.append(
            (
                "primary_monotonicity_passed_count",
                cast(int, summary.get_column("primary_monotonicity_passed").sum()),
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
        config_sha256=config_sha256,
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
if __name__ == "__main__":
    raise SystemExit(main())
