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


def _aggregate_redundancy_by_factor(
    summary: pl.DataFrame,
    redundancy_summary: pl.DataFrame,
) -> pl.DataFrame:
    """Aggregate validated redundancy incidents for every summary candidate.

    The redundancy evaluator emits unordered factor pairs.  Summary candidates
    therefore receive incidents from either endpoint, while reference-only
    endpoints remain absent from the returned candidate-keyed frame.
    """
    required_summary_columns = {"factor", "research_status"}
    required_redundancy_columns = {
        "factor_a",
        "factor_b",
        "median_abs_rank_corr",
    }
    if (
        not isinstance(summary, pl.DataFrame)
        or summary.is_empty()
        or not required_summary_columns.issubset(summary.columns)
        or not isinstance(redundancy_summary, pl.DataFrame)
        or redundancy_summary.is_empty()
        or not required_redundancy_columns.issubset(redundancy_summary.columns)
    ):
        raise ValueError("invalid classic redundancy aggregation request")

    for column in ("factor", "research_status"):
        if summary.schema[column] != pl.String:
            raise ValueError("classic summary string contract is invalid")
        values = summary.get_column(column).to_list()
        if any(type(value) is not str or not value for value in values):
            raise ValueError("classic summary string contract is invalid")
    statuses = cast(list[str], summary.get_column("research_status").to_list())
    if not set(statuses) <= {"RESEARCH_ONLY", "REJECTED"}:
        raise ValueError("classic summary status contract is invalid")
    for column in ("factor_a", "factor_b"):
        if redundancy_summary.schema[column] != pl.String:
            raise ValueError("classic redundancy endpoint contract is invalid")
        values = redundancy_summary.get_column(column).to_list()
        if any(type(value) is not str or not value for value in values):
            raise ValueError("classic redundancy endpoint contract is invalid")

    summary_factors = cast(list[str], summary.get_column("factor").to_list())
    if len(summary_factors) != len(set(summary_factors)):
        raise ValueError("classic summary factors are not unique")
    candidate_set = set(summary_factors)
    seen_pairs: set[tuple[str, str]] = set()
    maximum_by_factor: dict[str, int | float | Decimal] = {}
    for row in redundancy_summary.iter_rows(named=True):
        factor_a = cast(str, row["factor_a"])
        factor_b = cast(str, row["factor_b"])
        if factor_a == factor_b:
            raise ValueError("classic redundancy pair endpoints are not distinct")
        correlation = row["median_abs_rank_corr"]
        if isinstance(correlation, bool):
            raise ValueError("classic redundancy correlation contract is invalid")
        if not isinstance(correlation, (int, float, Decimal)):
            raise ValueError("classic redundancy correlation contract is invalid")
        numeric_correlation = cast(int | float | Decimal, correlation)
        try:
            finite = math.isfinite(float(numeric_correlation))
        except (OverflowError, TypeError, ValueError):
            finite = False
        if not finite:
            raise ValueError("classic redundancy correlation contract is invalid")
        if numeric_correlation < 0 or numeric_correlation > 1:
            raise ValueError("classic redundancy correlation must be between 0 and 1")

        pair: tuple[str, str] = (
            min(factor_a, factor_b),
            max(factor_a, factor_b),
        )
        if pair in seen_pairs:
            raise ValueError("classic redundancy pairs are not unique")
        seen_pairs.add(pair)
        for factor in (factor_a, factor_b):
            if factor in candidate_set:
                previous = maximum_by_factor.get(factor)
                if previous is None or float(numeric_correlation) > float(previous):
                    maximum_by_factor[factor] = numeric_correlation

    return pl.DataFrame(
        {
            "factor": summary_factors,
            "max_median_abs_rank_corr": [
                maximum_by_factor.get(factor) for factor in summary_factors
            ],
        },
        schema={
            "factor": pl.String,
            "max_median_abs_rank_corr": redundancy_summary.schema[
                "median_abs_rank_corr"
            ],
        },
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
            holding_outcomes = panel.select(
                pl.col("trade_date").alias("as_of"),
                "symbol",
                pl.col(portfolio_return_column).alias("holding_return"),
            )
            for multiplier in cost_multipliers:
                nav, portfolio_metrics = simulate_diagnostic_factor_portfolio(
                    targets=targets,
                    periods=periods,
                    holding_outcomes=holding_outcomes,
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
    redundancy = _aggregate_redundancy_by_factor(summary, redundancy_summary)
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
        .join(
            directions,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            redundancy,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            coverage_summary,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            schedule,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
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
    redundancy = _aggregate_redundancy_by_factor(summary, redundancy_summary)
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
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            coverage_summary,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            schedule,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
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


def _planned_test_signal_dates(
    panel: pl.DataFrame, *, fold: ResearchFoldV1, horizon: int
) -> tuple[dt.date, ...] | None:
    exit_date_column = f"exit_date_{horizon}"
    if (
        exit_date_column not in panel.columns
        or "trade_date" not in panel.columns
        or panel.is_empty()
    ):
        return None
    window = panel.filter(
        pl.col("trade_date").is_between(
            fold.test_start, fold.test_end, closed="both"
        )
    )
    if window.is_empty():
        return None
    date_plan = (
        window.group_by("trade_date")
        .agg(
            pl.len().alias("_rows"),
            pl.col(exit_date_column).null_count().alias("_exit_nulls"),
            pl.col(exit_date_column).drop_nulls().n_unique().alias("_exit_values"),
            pl.col(exit_date_column).drop_nulls().first().alias("_exit_date"),
        )
        .sort("trade_date")
    )
    dates: list[dt.date] = []
    boundary_started = False
    for row in date_plan.iter_rows(named=True):
        trade_date = row["trade_date"]
        row_count = row["_rows"]
        null_count = row["_exit_nulls"]
        value_count = row["_exit_values"]
        planned_exit = row["_exit_date"]
        if (
            type(trade_date) is not dt.date
            or type(row_count) is not int
            or type(null_count) is not int
            or type(value_count) is not int
            or null_count not in {0, row_count}
            or value_count > 1
        ):
            return None
        is_boundary = null_count == row_count or (
            planned_exit is not None and planned_exit > fold.test_end
        )
        if is_boundary:
            boundary_started = True
            continue
        if (
            boundary_started
            or planned_exit is None
            or type(planned_exit) is not dt.date
            or planned_exit < trade_date
        ):
            return None
        dates.append(trade_date)
    return tuple(dates) if dates else None


def _primary_monotonicity_row(
    *,
    factor: str,
    fold: int,
    signal_dates: int,
    means: Mapping[int, float] | None,
    invalid_reason: str | None,
    expected_direction: int,
) -> dict[str, object]:
    values: tuple[float | None, float | None, float | None, float | None, float | None]
    if means is None:
        values = (None, None, None, None, None)
        comparisons = (False, False, False, False)
    else:
        values = cast(
            tuple[float | None, float | None, float | None, float | None, float | None],
            tuple(means.get(group) for group in range(1, 6)),
        )
        comparison_values: list[bool] = []
        for index in range(4):
            left = values[index]
            right = values[index + 1]
            comparison_values.append(
                left <= right if left is not None and right is not None else False
            )
        comparisons = cast(
            tuple[bool, bool, bool, bool], tuple(comparison_values)
        )
    return {
        "factor": factor,
        "fold": fold,
        "period": "test",
        "horizon": 20,
        "expected_direction": expected_direction,
        "signal_dates": signal_dates,
        "group_1_mean_return": values[0],
        "group_2_mean_return": values[1],
        "group_3_mean_return": values[2],
        "group_4_mean_return": values[3],
        "group_5_mean_return": values[4],
        "group_1_le_group_2": comparisons[0],
        "group_2_le_group_3": comparisons[1],
        "group_3_le_group_4": comparisons[2],
        "group_4_le_group_5": comparisons[3],
        "monotonicity_passed": invalid_reason is None and all(comparisons),
        "invalid_reason": invalid_reason,
    }


def evaluate_primary_group_monotonicity(
    group_returns: pl.DataFrame,
    *,
    panel: pl.DataFrame,
    factor: str,
    folds: tuple[ResearchFoldV1, ...],
    minimum_symbols: int,
    expected_direction: int,
) -> pl.DataFrame:
    """Validate and aggregate the frozen MAX test horizon-20 five-group gate."""
    required_columns = {
        "factor",
        "fold",
        "period",
        "horizon",
        "direction",
        "trade_date",
        "group",
        "n_symbols",
        "mean_return",
        "factor_count",
        "paired_count",
        "coverage_numerator",
        "coverage_denominator",
        "coverage_status",
    }
    if (
        not isinstance(group_returns, pl.DataFrame)
        or not isinstance(panel, pl.DataFrame)
        or type(factor) is not str
        or not factor
        or type(folds) is not tuple
        or len(folds) != 3
        or any(type(item) is not ResearchFoldV1 for item in folds)
        or tuple(item.fold for item in folds) != (1, 2, 3)
        or type(minimum_symbols) is not int
        or minimum_symbols < 2
        or expected_direction != -1
        or not required_columns.issubset(group_returns.columns)
    ):
        raise ValueError("invalid primary group monotonicity request")

    valid_rows: list[dict[str, object]] = []
    result_rows: list[dict[str, object]] = []
    for fold in folds:
        expected_dates = _planned_test_signal_dates(panel, fold=fold, horizon=20)
        planned_dates = () if expected_dates is None else expected_dates
        selected = group_returns.filter(
            (pl.col("factor") == factor)
            & (pl.col("fold") == fold.fold)
            & (pl.col("period") == "test")
            & (pl.col("horizon") == 20)
        )
        actual_rows = selected.to_dicts()
        invalid_reason: str | None = None
        if expected_dates is None:
            invalid_reason = "missing_planned_test_dates"
        elif any(type(row.get("trade_date")) is not dt.date for row in actual_rows):
            invalid_reason = "test_signal_date_grid_mismatch"
        elif (
            tuple(
                sorted({cast(dt.date, row["trade_date"]) for row in actual_rows})
            )
            != planned_dates
        ):
            invalid_reason = "test_signal_date_grid_mismatch"
        elif any(type(row.get("group")) is not int for row in actual_rows):
            invalid_reason = "group_label_type_mismatch"
        elif {row.get("group") for row in actual_rows} != set(range(1, 6)):
            invalid_reason = "test_group_grid_mismatch"
        else:
            key_counts: dict[tuple[object, object], int] = {}
            for row in actual_rows:
                key = (row.get("trade_date"), row.get("group"))
                key_counts[key] = key_counts.get(key, 0) + 1
            if any(count != 1 for count in key_counts.values()):
                invalid_reason = "duplicate_test_group_row"
            elif len(actual_rows) != len(planned_dates) * 5:
                invalid_reason = "test_group_grid_mismatch"

        date_totals: dict[object, dict[str, int]] = {}
        means_by_group: dict[int, list[float]] = {group: [] for group in range(1, 6)}
        if invalid_reason is None:
            for row in actual_rows:
                if (
                    row.get("direction") != expected_direction
                    or row.get("coverage_status") != "PASS"
                ):
                    invalid_reason = "coverage_or_direction_failed"
                    break
                count_values = (
                    row.get("n_symbols"),
                    row.get("factor_count"),
                    row.get("paired_count"),
                    row.get("coverage_numerator"),
                    row.get("coverage_denominator"),
                )
                mean_return = row.get("mean_return")
                if any(type(value) is not int for value in count_values) or (
                    type(mean_return) not in {int, float}
                    or isinstance(mean_return, bool)
                    or not math.isfinite(float(cast(int | float, mean_return)))
                ):
                    invalid_reason = "non_finite_or_invalid_group_value"
                    break
                if (
                    int(row["n_symbols"]) <= 0
                    or int(row["factor_count"]) <= 0
                    or int(row["paired_count"]) <= 0
                    or int(row["coverage_numerator"]) != int(row["paired_count"])
                    or int(row["coverage_denominator"]) != int(row["factor_count"])
                ):
                    invalid_reason = "group_coverage_incomplete"
                    break
                date = row.get("trade_date")
                if date not in date_totals:
                    date_totals[date] = {
                        "n_symbols": 0,
                        "factor_count": 0,
                        "paired_count": 0,
                    }
                date_totals[date]["n_symbols"] += int(row["n_symbols"])
                date_totals[date]["factor_count"] += int(row["factor_count"])
                date_totals[date]["paired_count"] += int(row["paired_count"])
                means_by_group[int(row["group"])].append(
                    float(cast(int | float, mean_return))
                )
            if invalid_reason is None and any(
                totals["n_symbols"] < minimum_symbols
                or totals["factor_count"] < minimum_symbols
                or totals["paired_count"] < minimum_symbols
                for totals in date_totals.values()
            ):
                invalid_reason = "minimum_symbol_contract_failed"
            if invalid_reason is None and any(
                len(values) != len(planned_dates)
                or not all(math.isfinite(value) for value in values)
                for values in means_by_group.values()
            ):
                invalid_reason = "non_finite_or_missing_group_return"

        if invalid_reason is None:
            means = {
                group: sum(values) / len(values)
                for group, values in means_by_group.items()
            }
            fold_rows = [
                row
                for row in actual_rows
                if row.get("trade_date") in set(planned_dates)
            ]
            valid_rows.extend(fold_rows)
        else:
            means = None
        result_rows.append(
            _primary_monotonicity_row(
                factor=factor,
                fold=fold.fold,
                signal_dates=0 if expected_dates is None else len(expected_dates),
                means=means,
                invalid_reason=invalid_reason,
                expected_direction=expected_direction,
            )
        )

    pooled_invalid_reason: str | None = None
    pooled_means: Mapping[int, float] | None = None
    if any(row["invalid_reason"] is not None for row in result_rows):
        pooled_invalid_reason = "fold_monotonicity_input_invalid"
    else:
        pooled_signal_keys = {
            (row.get("fold"), row.get("trade_date")) for row in valid_rows
        }
        pooled_dates = [date for _, date in pooled_signal_keys]
        if len(set(pooled_dates)) != len(pooled_signal_keys):
            pooled_invalid_reason = "pooled_signal_date_duplicate"
        else:
            pooled_values: dict[int, list[float]] = {group: [] for group in range(1, 6)}
            for row in valid_rows:
                group = row.get("group")
                if type(group) is not int or group not in pooled_values:
                    pooled_invalid_reason = "pooled_group_grid_mismatch"
                    break
                value = row.get("mean_return")
                if (
                    type(value) not in {int, float}
                    or isinstance(value, bool)
                    or not math.isfinite(float(cast(int | float, value)))
                ):
                    pooled_invalid_reason = "pooled_non_finite_group_return"
                    break
                pooled_values[group].append(float(cast(int | float, value)))
            if pooled_invalid_reason is None:
                pooled_means = {
                    group: sum(values) / len(values)
                    for group, values in pooled_values.items()
                }
    result_rows.append(
        _primary_monotonicity_row(
            factor=factor,
            fold=0,
            signal_dates=len(valid_rows) // 5 if pooled_invalid_reason is None else 0,
            means=pooled_means,
            invalid_reason=pooled_invalid_reason,
            expected_direction=expected_direction,
        )
    )
    return pl.DataFrame(result_rows).sort("fold")


def apply_fifth_batch_admission_gates(
    summary: pl.DataFrame,
    *,
    fold_metrics: pl.DataFrame,
    redundancy_summary: pl.DataFrame,
    coverage_summary: pl.DataFrame,
    schedule_alignment: pl.DataFrame,
    expected_direction: int,
    maximum_median_absolute_rank_correlation: float,
    primary_group_monotonicity: pl.DataFrame,
) -> pl.DataFrame:
    """Apply fixed-direction, coverage, redundancy and schedule gates to MAX."""
    monotonicity_columns = {
        "factor",
        "fold",
        "period",
        "horizon",
        "expected_direction",
        "monotonicity_passed",
    }
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
        or not isinstance(primary_group_monotonicity, pl.DataFrame)
        or primary_group_monotonicity.is_empty()
        or not monotonicity_columns.issubset(primary_group_monotonicity.columns)
        or expected_direction not in {-1, 1}
        or expected_direction != -1
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
    redundancy = _aggregate_redundancy_by_factor(summary, redundancy_summary)
    schedule = schedule_alignment.group_by("factor").agg(
        pl.col("schedule_aligned").all().alias("schedule_alignment_passed")
    )
    monotonicity_rows: list[dict[str, object]] = []
    for factor in summary.get_column("factor").to_list():
        one = primary_group_monotonicity.filter(
            (pl.col("factor") == factor)
            & (pl.col("period") == "test")
            & (pl.col("horizon") == 20)
            & (pl.col("expected_direction") == expected_direction)
        )
        fold_rows = one.filter(pl.col("fold") > 0)
        pooled_rows = one.filter(pl.col("fold") == 0)
        fold_ids = tuple(sorted(fold_rows.get_column("fold").to_list()))
        fold_passed = sum(
            bool(value) for value in fold_rows.get_column("monotonicity_passed").to_list()
        )
        pooled_passed = (
            pooled_rows.height == 1
            and bool(pooled_rows.get_column("monotonicity_passed").item())
        )
        monotonicity_rows.append(
            {
                "factor": factor,
                "primary_monotonicity_fold_count": fold_rows.height,
                "primary_monotonicity_passed_folds": fold_passed,
                "primary_monotonicity_required_folds": 2,
                "primary_monotonicity_pooled_passed": pooled_passed,
                "primary_monotonicity_passed": (
                    fold_ids == (1, 2, 3)
                    and fold_passed >= 2
                    and pooled_passed
                ),
            }
        )
    monotonicity = pl.DataFrame(monotonicity_rows)
    drop_columns = [
        column
        for column in ("max_median_abs_rank_corr", "combination_eligible")
        if column in summary.columns
    ]
    summary_base = summary.drop(drop_columns) if drop_columns else summary
    return (
        summary_base.join(
            directions,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            redundancy,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            coverage_summary,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            schedule,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            monotonicity,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
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
                & pl.col("primary_monotonicity_passed")
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


def _normalize_main_config_payload(payload: bytes) -> str:
    if type(payload) is not bytes:
        raise ValueError("invalid classic config payload")
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError("classic config payload has a leading BOM")
    if b"\x00" in payload:
        raise ValueError("classic config payload contains NUL")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("classic config payload is not valid UTF-8") from None
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _cost_periods(project_root: Path, portfolio: Mapping[str, Any]) -> tuple[AShareCostPeriod, ...]:
    return _cost_schedule_binding(project_root, portfolio)[0]


def _cost_schedule_binding(
    project_root: Path, portfolio: Mapping[str, Any]
) -> tuple[tuple[AShareCostPeriod, ...], str]:
    relative_path = portfolio.get("cost_config_relative_path")
    if type(relative_path) is not str or not relative_path:
        raise ValueError("invalid A-share cost schedule")
    path = _inside(project_root, Path(relative_path))
    return _cost_schedule_binding_from_payload(path.read_bytes())


def _cost_schedule_binding_from_payload(
    payload: bytes,
) -> tuple[tuple[AShareCostPeriod, ...], str]:
    if type(payload) is not bytes:
        raise ValueError("invalid A-share cost schedule")
    try:
        config = tomllib.loads(payload.decode("utf-8"), parse_float=Decimal)
        costs = config["costs"]
        if type(costs) is not dict or frozenset(costs) != _COST_SECTION_KEYS:
            raise ValueError
        if (
            type(costs["schedule_version"]) is not str
            or not costs["schedule_version"]
            or type(costs["stamp_tax_source"]) is not str
            or not costs["stamp_tax_source"]
            or type(costs["transfer_fee_source"]) is not str
            or not costs["transfer_fee_source"]
            or type(costs["scaled_components"]) is not list
            or tuple(costs["scaled_components"]) != _COST_SCALED_COMPONENTS
            or type(costs["a_share_periods"]) is not list
            or not costs["a_share_periods"]
        ):
            raise ValueError

        periods: list[AShareCostPeriod] = []
        canonical_periods: list[dict[str, str | None]] = []
        for row in costs["a_share_periods"]:
            if (
                type(row) is not dict
                or not _COST_PERIOD_REQUIRED_KEYS <= frozenset(row)
                or not frozenset(row) <= _COST_PERIOD_KEYS
                or type(row["effective_from"]) is not dt.date
                or (
                    "effective_to" in row
                    and type(row["effective_to"]) is not dt.date
                )
            ):
                raise ValueError
            decimals = {
                name: _cost_decimal(row[name]) for name in _COST_DECIMAL_FIELDS
            }
            period = AShareCostPeriod(
                effective_from=row["effective_from"],
                effective_to=row.get("effective_to"),
                commission_rate=decimals["commission_rate"],
                commission_min=decimals["commission_min"],
                stamp_tax_sell=decimals["stamp_tax_sell"],
                transfer_fee=decimals["transfer_fee"],
                slippage=decimals["slippage"],
            )
            periods.append(period)
            canonical_periods.append(
                {
                    "effective_from": period.effective_from.isoformat(),
                    "effective_to": (
                        None
                        if period.effective_to is None
                        else period.effective_to.isoformat()
                    ),
                    **{
                        name: _cost_decimal_text(decimals[name])
                        for name in _COST_DECIMAL_FIELDS
                    },
                }
            )
        for current, following in zip(periods, periods[1:], strict=False):
            if (
                current.effective_to is None
                or current.effective_to.toordinal() + 1
                != following.effective_from.toordinal()
            ):
                raise ValueError

        semantic_payload = {
            "schema_version": "m2-a-share-cost-semantic-v1",
            "schedule_version": costs["schedule_version"],
            "sources": {
                "stamp_tax": costs["stamp_tax_source"],
                "transfer_fee": costs["transfer_fee_source"],
            },
            "scaled_components": list(_COST_SCALED_COMPONENTS),
            "periods": canonical_periods,
        }
    except (KeyError, TypeError, UnicodeDecodeError, ValueError, tomllib.TOMLDecodeError):
        raise ValueError("invalid A-share cost schedule") from None
    semantic_sha256 = hashlib.sha256(canonical_json_bytes(semantic_payload)).hexdigest()
    return tuple(periods), semantic_sha256


def _cost_decimal(value: object) -> Decimal:
    if type(value) is int:
        result = Decimal(cast(int, value))
    elif type(value) is Decimal:
        result = cast(Decimal, value)
    else:
        raise ValueError
    if not result.is_finite() or result < 0:
        raise ValueError
    return result


def _cost_decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _cost_schedule_input_digest(
    periods: tuple[AShareCostPeriod, ...], semantic_sha256: str
) -> ResearchInputDigestV1:
    return ResearchInputDigestV1(
        name="a-share-cost-schedule",
        rows=len(periods),
        min_date=None,
        max_date=None,
        content_sha256=semantic_sha256,
    )


def _build_input_digests(
    market_input_digests: tuple[ResearchInputDigestV1, ...],
    *,
    fifth_batch: bool,
    cost_periods: tuple[AShareCostPeriod, ...] | None,
    cost_semantic_sha256: str | None,
    sixth_batch: bool = False,
) -> tuple[ResearchInputDigestV1, ...]:
    if not fifth_batch and not sixth_batch:
        return market_input_digests
    if cost_periods is None or cost_semantic_sha256 is None:
        raise ValueError(
            "missing frozen MAX cost identity"
            if fifth_batch
            else "missing frozen sixth-batch cost identity"
        )
    return (
        _cost_schedule_input_digest(cost_periods, cost_semantic_sha256),
        *market_input_digests,
    )


def _is_lower_hex64(value: object) -> bool:
    return (
        type(value) is str
        and len(cast(str, value)) == 64
        and all(character in "0123456789abcdef" for character in cast(str, value))
    )


def _is_exact_int(value: object, expected: int) -> bool:
    return type(value) is int and value == expected


def _is_exact_float(value: object, expected: float) -> bool:
    if type(value) is int:
        try:
            numeric_value = float(value)
        except OverflowError:
            return False
    elif type(value) is float:
        numeric_value = value
    else:
        return False
    return math.isfinite(numeric_value) and numeric_value == expected


def _is_non_empty_string(value: object) -> bool:
    return type(value) is str and bool(value)


def _has_exact_keys(value: object, keys: frozenset[str]) -> bool:
    return isinstance(value, Mapping) and frozenset(value) == keys


def _is_exact_sixth_fold(value: object, expected: Mapping[str, dt.date]) -> bool:
    if not _has_exact_keys(value, frozenset(expected)):
        return False
    row = cast(Mapping[str, object], value)
    return all(
        type(row[key]) is dt.date and row[key] == expected[key]
        for key in expected
    )


def _validate_sixth_batch_config(
    config: Mapping[str, Any], *, threads: int
) -> None:
    required_sections = frozenset(
        {
            "research",
            "data",
            "universe",
            "factors",
            "alpha101_sixth_batch",
            "coverage",
            "portfolio",
            "admission",
            "walk_forward",
        }
    )
    valid = False
    try:
        if not _has_exact_keys(config, required_sections):
            raise ValueError
        research = cast(Mapping[str, Any], config["research"])
        data = cast(Mapping[str, Any], config["data"])
        universe = cast(Mapping[str, Any], config["universe"])
        factors = cast(Mapping[str, Any], config["factors"])
        sixth = cast(Mapping[str, Any], config["alpha101_sixth_batch"])
        coverage = cast(Mapping[str, Any], config["coverage"])
        portfolio = cast(Mapping[str, Any], config["portfolio"])
        admission = cast(Mapping[str, Any], config["admission"])
        walk_forward = cast(Mapping[str, Any], config["walk_forward"])
        expected_research_keys = frozenset(
            {"hypothesis_id", "hypothesis", "strategy_name", "strategy_version", "random_seed"}
        )
        expected_data_keys = frozenset(
            {"snapshot_id", "warmup_start", "research_start", "research_end"}
        )
        expected_universe_keys = frozenset(
            {"freeze_start", "freeze_end", "top_n", "minimum_observations", "minimum_average_amount"}
        )
        expected_factor_keys = frozenset(
            {
                "catalog",
                "names",
                "redundancy_reference_names",
                "horizons",
                "minimum_history_rows",
                "minimum_daily_symbols",
                "groups",
                "maximum_median_absolute_rank_correlation",
            }
        )
        expected_coverage_keys = frozenset(
            {"minimum_rebalance_symbols", "minimum_median_coverage"}
        )
        expected_portfolio_keys = frozenset(
            {
                "selection_horizon_sessions",
                "rebalance_every_sessions",
                "top_k",
                "initial_cash",
                "cost_multipliers",
                "cost_config_relative_path",
                "cost_schedule_semantic_sha256",
            }
        )
        expected_admission_keys = frozenset(
            {
                "minimum_mean_test_rank_ic",
                "minimum_positive_test_folds",
                "require_direction_consistency",
                "require_positive_2x_cost_return",
            }
        )
        if not all(
            (
                _has_exact_keys(research, expected_research_keys),
                _has_exact_keys(data, expected_data_keys),
                _has_exact_keys(universe, expected_universe_keys),
                _has_exact_keys(factors, expected_factor_keys),
                _has_exact_keys(sixth, _SIXTH_BATCH_SECTION_KEYS),
                _has_exact_keys(coverage, expected_coverage_keys),
                _has_exact_keys(portfolio, expected_portfolio_keys),
                _has_exact_keys(admission, expected_admission_keys),
                _has_exact_keys(walk_forward, frozenset({"folds"})),
            )
        ):
            raise ValueError

        folds = walk_forward["folds"]
        valid = (
            _is_non_empty_string(research["hypothesis_id"])
            and research["hypothesis_id"] == _SIXTH_BATCH_HYPOTHESIS_ID
            and _is_non_empty_string(research["hypothesis"])
            and _is_non_empty_string(research["strategy_name"])
            and _is_non_empty_string(research["strategy_version"])
            and type(research["random_seed"]) is int
            and data["snapshot_id"] == _SIXTH_BATCH_SNAPSHOT_ID
            and type(data["warmup_start"]) is dt.date
            and data["warmup_start"] == dt.date(2019, 1, 1)
            and type(data["research_start"]) is dt.date
            and data["research_start"] == dt.date(2020, 1, 1)
            and type(data["research_end"]) is dt.date
            and data["research_end"] == dt.date(2026, 8, 13)
            and _is_exact_sixth_universe(universe)
            and factors["catalog"] == _SIXTH_BATCH_CATALOG
            and type(factors["names"]) is list
            and tuple(factors["names"]) == SIXTH_BATCH_FACTOR_NAMES
            and type(factors["redundancy_reference_names"]) is list
            and tuple(factors["redundancy_reference_names"])
            == _SIXTH_BATCH_REFERENCE_NAMES
            and type(factors["horizons"]) is list
            and all(type(value) is int for value in factors["horizons"])
            and tuple(factors["horizons"]) == (1, 5, 20)
            and _is_exact_int(factors["minimum_history_rows"], 120)
            and _is_exact_int(factors["minimum_daily_symbols"], 100)
            and _is_exact_int(factors["groups"], 5)
            and _is_exact_float(
                factors["maximum_median_absolute_rank_correlation"], 0.80
            )
            and sixth["schema_version"] == "m2-alpha101-sixth-batch-v1"
            and sixth["hypothesis_id"] == _SIXTH_BATCH_HYPOTHESIS_ID
            and type(sixth["factors"]) is list
            and tuple(sixth["factors"]) == SIXTH_BATCH_FACTOR_NAMES
            and _is_exact_int(sixth["correlation_window_sessions"], 10)
            and _is_exact_int(sixth["delta_lag_sessions"], 1)
            and sixth["alpha041_price_basis"] == "raw_cny_per_share"
            and sixth["alpha041_vwap_formula"] == "amount_div_volume"
            and sixth["direction_policy"] == "validation_only_per_fold"
            and _is_exact_int(sixth["trial_budget"], 3)
            and _is_exact_int(sixth["trial_delta"], 3)
            and _is_exact_int(sixth["attempt_ordinal"], 1)
            and _is_exact_int(coverage["minimum_rebalance_symbols"], 100)
            and _is_exact_float(coverage["minimum_median_coverage"], 0.80)
            and _is_exact_int(portfolio["selection_horizon_sessions"], 20)
            and _is_exact_int(portfolio["rebalance_every_sessions"], 20)
            and _is_exact_int(portfolio["top_k"], 50)
            and _is_exact_float(portfolio["initial_cash"], 1_000_000.0)
            and type(portfolio["cost_multipliers"]) is list
            and tuple(
                _is_exact_float(value, expected)
                for value, expected in zip(
                    portfolio["cost_multipliers"], (0.5, 1.0, 2.0), strict=False
                )
            )
            == (True, True, True)
            and len(portfolio["cost_multipliers"]) == 3
            and portfolio["cost_config_relative_path"]
            == "configs/research/m3_qlib_example.toml"
            and portfolio["cost_schedule_semantic_sha256"]
            == _SIXTH_BATCH_COST_SEMANTIC_SHA256
            and _is_exact_float(admission["minimum_mean_test_rank_ic"], 0.01)
            and _is_exact_int(admission["minimum_positive_test_folds"], 2)
            and admission["require_direction_consistency"] is True
            and admission["require_positive_2x_cost_return"] is True
            and type(folds) is list
            and len(folds) == 3
            and all(
                _is_exact_sixth_fold(value, expected)
                for value, expected in zip(
                    folds, _SIXTH_BATCH_FROZEN_FOLDS, strict=True
                )
            )
            and type(threads) is int
            and 1 <= threads <= 2
        )
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        valid = False
    if not valid:
        raise ValueError("invalid classic-factor config")


def _is_exact_sixth_universe(universe: Mapping[str, Any]) -> bool:
    return (
        type(universe["freeze_start"]) is dt.date
        and universe["freeze_start"] == dt.date(2019, 1, 1)
        and type(universe["freeze_end"]) is dt.date
        and universe["freeze_end"] == dt.date(2019, 12, 31)
        and _is_exact_int(universe["top_n"], 800)
        and _is_exact_int(universe["minimum_observations"], 120)
        and _is_exact_float(universe["minimum_average_amount"], 20_000_000.0)
    )


def _validate_config(config: Mapping[str, Any], *, threads: int) -> None:
    sixth_factors = config.get("factors") if isinstance(config, Mapping) else None
    if (
        isinstance(sixth_factors, Mapping)
        and type(sixth_factors.get("names")) is list
        and tuple(sixth_factors["names"]) == SIXTH_BATCH_FACTOR_NAMES
    ):
        _validate_sixth_batch_config(config, threads=threads)
        return
    factor_config = cast(Mapping[str, Any], config["factors"])
    market_risk = cast(Mapping[str, Any], config.get("market_risk", {}))
    max_lottery = cast(Mapping[str, Any], config.get("max_lottery", {}))
    coverage = cast(Mapping[str, Any], config.get("coverage", {}))
    portfolio = cast(Mapping[str, Any], config["portfolio"])
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
        and max_lottery.get("trial_delta") == 0
        and coverage.get("minimum_rebalance_symbols") == 100
        and float(coverage.get("minimum_median_coverage", 0.0)) == 0.80
        and _is_lower_hex64(portfolio.get("cost_schedule_semantic_sha256"))
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
        or tuple(float(value) for value in portfolio["cost_multipliers"])
        != (0.5, 1.0, 2.0)
        or portfolio["selection_horizon_sessions"] != 20
        or type(threads) is not int
        or not 1 <= threads <= (2 if fifth_batch else 4)
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
                "This primary MAX gate does not close PIT symmetric redundancy coverage, "
                "audit-v4, R3 or any trading Gate.",
            ]
        )
    if cast(Mapping[str, Any], config["factors"]).get("catalog") == (
        _SIXTH_BATCH_CATALOG
    ):
        caveats.extend(
            [
                "Alpha101 #006 and #012 use adjusted open/close with raw volume; "
                "Alpha101 #041 intentionally remains raw CNY/share versus amount/volume.",
                "The three price-volume candidates are one frozen trial family; "
                "directions are selected on validation only and no candidate may be substituted.",
                "Strict exchange-session gaps, non-positive factor-specific denominators, "
                "redundancy, coverage, schedule and two-times-cost gates are fail-closed.",
            ]
        )
    report: dict[str, object] = {
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
        "primary_group_monotonicity": (
            results["primary_group_monotonicity"].to_dicts()
            if "primary_group_monotonicity" in results
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
    factor_catalog = cast(Mapping[str, Any], config["factors"]).get("catalog")
    if factor_catalog == _SIXTH_BATCH_CATALOG:
        report["alpha101_sixth_batch"] = config["alpha101_sixth_batch"]
    if factor_catalog in (
        "max_lottery_fifth_batch_v1",
        _SIXTH_BATCH_CATALOG,
    ):
        expected_cost_semantic_sha256 = cast(
            Mapping[str, Any], config["portfolio"]
        ).get("cost_schedule_semantic_sha256")
        if expected_cost_semantic_sha256 is not None:
            report["cost_schedule_semantic_sha256"] = expected_cost_semantic_sha256
    return report


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
