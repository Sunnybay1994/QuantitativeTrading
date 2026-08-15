"""Run the frozen M2 ``daily_basic`` value-proxy research study."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import tomllib
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import polars as pl

from quant.data import TushareBulkStockBarQuery, read_tushare_bulk_clean_stock_bars
from quant.data.daily_basic_repository import (
    TushareDailyBasicQuery,
    read_tushare_daily_basic,
)
from quant.data.publish_tushare_bulk_clean import verify_tushare_bulk_clean_snapshot
from quant.data.publish_tushare_daily_basic import verify_tushare_daily_basic_snapshot
from quant.factors import (
    AMIHUD_FACTOR_NAMES,
    CLASSIC_FACTOR_NAMES,
    DAILY_VALUE_FACTOR_NAMES,
    DAILY_VALUE_FACTOR_SPECS,
    LIQUIDITY_FACTOR_SPECS,
    TURNOVER_FACTOR_NAMES,
    compute_classic_daily_factors,
    compute_daily_value_factors,
    compute_monthly_amihud_illiquidity,
    compute_monthly_free_float_turnover_factors,
)
from quant.research.classic_factor_evaluation import evaluate_factor_redundancy
from quant.research.factor_labels import (
    build_next_open_factor_labels,
    build_next_rebalance_open_labels,
)
from quant.research.lightweight_run import (
    LightweightResearchRunV1,
    ResearchInputDigestV1,
    canonical_json_bytes,
    compute_code_sha256,
    publish_lightweight_research_run,
)
from quant.research.run_classic_factors import (
    _cost_periods,
    _folds,
    _inside,
    _parquet,
    evaluate_walk_forward,
    select_frozen_liquid_universe,
    summarize_factors,
)
from quant.research.pit_quality_research import monthly_signal_sessions
from quant.settings import resolve_data_root

_DAILY_VALUE_CATALOG = "tushare_daily_basic_value_proxy_v1"
_AMIHUD_CATALOG = "tushare_monthly_amihud_v1"
_TURNOVER_CATALOG = "tushare_monthly_free_float_turnover_v1"
_REFERENCE_FACTORS = CLASSIC_FACTOR_NAMES + ("log_total_market_value",)
_AMIHUD_REFERENCE_FACTORS = _REFERENCE_FACTORS + DAILY_VALUE_FACTOR_NAMES + TURNOVER_FACTOR_NAMES
_TURNOVER_REFERENCE_FACTORS = _REFERENCE_FACTORS + DAILY_VALUE_FACTOR_NAMES + AMIHUD_FACTOR_NAMES
_AMIHUD_EXPECTED_DIRECTIONS = {"amihud_illiquidity_monthly": 1}
_TURNOVER_EXPECTED_DIRECTIONS = {
    "free_float_turnover_level_monthly": -1,
    "free_float_turnover_abnormal_12m": -1,
}
_BASE_CODE_PATHS = (
    "src/quant/data/clean_snapshot_repository.py",
    "src/quant/data/daily_basic_repository.py",
    "src/quant/data/publish_tushare_daily_basic.py",
    "src/quant/factors/classic.py",
    "src/quant/factors/daily_value.py",
    "src/quant/research/classic_factor_evaluation.py",
    "src/quant/research/factor_labels.py",
    "src/quant/research/lightweight_run.py",
    "src/quant/research/run_classic_factors.py",
    "src/quant/research/run_daily_value_factors.py",
)
_LIQUIDITY_CODE_PATHS = _BASE_CODE_PATHS + (
    "src/quant/factors/liquidity.py",
    "src/quant/research/pit_quality_research.py",
)


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one immutable two-snapshot daily-value research run."""
    parser = argparse.ArgumentParser(
        description="运行 M2 daily_basic 价值代理因子研究"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/research/m2_daily_value_factors.toml"),
    )
    parser.add_argument("--daily-basic-snapshot-id", required=True)
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
    factor_names, factor_specs, reference_factors, monthly = _study_contract(config)
    bar_snapshot_id = cast(str, data["bar_snapshot_id"])
    bar_snapshot = verify_tushare_bulk_clean_snapshot(
        data_root=data_root, snapshot_id=bar_snapshot_id
    )
    daily_snapshot = verify_tushare_daily_basic_snapshot(
        data_root=data_root, snapshot_id=args.daily_basic_snapshot_id
    )

    freeze_bars = read_tushare_bulk_clean_stock_bars(
        data_root=data_root,
        query=TushareBulkStockBarQuery(
            snapshot_id=bar_snapshot_id,
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
            snapshot_id=bar_snapshot_id,
            start_date=cast(dt.date, data["warmup_start"]),
            end_date=cast(dt.date, data["research_end"]),
            symbols=candidates,
            threads=args.threads,
        ),
    )
    daily_basic = read_tushare_daily_basic(
        data_root=data_root,
        query=TushareDailyBasicQuery(
            snapshot_id=args.daily_basic_snapshot_id,
            start_date=cast(dt.date, data["warmup_start"]),
            end_date=cast(dt.date, data["research_end"]),
            symbols=candidates,
            threads=args.threads,
        ),
    )
    sessions = tuple(sorted(set(bars.get_column("trade_date").to_list())))
    if monthly:
        signal_dates = monthly_signal_sessions(
            sessions,
            start=cast(dt.date, data["warmup_start"]),
            end=cast(dt.date, data["research_end"]),
        )
        panel = build_monthly_liquidity_panel(
            daily_basic=daily_basic,
            bars=bars,
            sessions=sessions,
            signal_dates=signal_dates,
            candidate_symbols=candidates,
            horizons=tuple(cast(list[int], factors["horizons"])),
            minimum_valid_days=cast(int, factors["minimum_valid_days"]),
            turnover_history_months=cast(int, factors["turnover_history_months"]),
        )
    else:
        panel = build_daily_value_panel(
            daily_basic=daily_basic,
            bars=bars,
            sessions=sessions,
            horizons=tuple(cast(list[int], factors["horizons"])),
        )
    panel = panel.filter(
        (pl.col("trade_date") >= cast(dt.date, data["research_start"]))
        & (pl.col("history_rows") >= cast(int, factors["minimum_history_rows"]))
        & (pl.col("liquidity_20") >= float(universe["minimum_average_amount"]))
    )
    if panel.is_empty():
        raise ValueError("daily-value panel is empty")

    results = evaluate_walk_forward(
        panel=panel,
        factors=factor_names,
        horizons=tuple(cast(list[int], factors["horizons"])),
        folds=_folds(config),
        minimum_symbols=cast(
            int,
            factors[
                "minimum_signal_symbols" if monthly else "minimum_daily_symbols"
            ],
        ),
        groups=cast(int, factors["groups"]),
        top_k=cast(int, portfolio["top_k"]),
        rebalance_every=(
            cast(int, portfolio["rebalance_every_signals"])
            if monthly
            else cast(int, portfolio["rebalance_every_sessions"])
        ),
        initial_cash=Decimal(str(portfolio["initial_cash"])),
        cost_multipliers=tuple(
            Decimal(str(value)) for value in portfolio["cost_multipliers"]
        ),
        costs=_cost_periods(project_root, portfolio),
        strategy_name=cast(str, config["research"]["strategy_name"]),
        strategy_version=cast(str, config["research"]["strategy_version"]),
        portfolio_return_column=("label_rebalance" if monthly else "label_20"),
        portfolio_execution_date_column=(
            "execution_date_rebalance" if monthly else "execution_date_20"
        ),
        portfolio_exit_date_column=(
            "exit_date_rebalance" if monthly else "exit_date_20"
        ),
        portfolio_annualization_periods=(
            float(portfolio["annualization_periods"]) if monthly else 252.0 / 20.0
        ),
        ic_newey_west_lag=(cast(int, factors["ic_newey_west_lag"]) if monthly else None),
    )
    summary = summarize_factors(
        cast(pl.DataFrame, results["fold_metrics"]),
        factors=factor_names,
        admission=cast(Mapping[str, Any], config["admission"]),
    )
    if monthly:
        summary = apply_expected_direction_gate(
            summary,
            fold_metrics=cast(pl.DataFrame, results["fold_metrics"]),
            expected_directions=cast(
                Mapping[str, Any], factors["expected_directions"]
            ),
        )
    redundancy_daily, redundancy_summary = evaluate_factor_redundancy(
        panel,
        factors=factor_names,
        reference_factors=reference_factors,
        start_date=cast(dt.date, data["research_start"]),
        end_date=cast(dt.date, data["research_end"]),
        minimum_symbols=cast(
            int,
            factors[
                "minimum_signal_symbols" if monthly else "minimum_daily_symbols"
            ],
        ),
    )
    summary = apply_redundancy_gate(
        summary,
        redundancy_summary=redundancy_summary,
        maximum_median_absolute_rank_correlation=float(
            factors["maximum_median_absolute_rank_correlation"]
        ),
    )
    results["redundancy_daily"] = redundancy_daily
    results["redundancy_summary"] = redundancy_summary
    coverage = build_factor_coverage(panel, factors=factor_names)
    if monthly:
        summary = apply_coverage_gate(
            summary,
            coverage=coverage,
            minimum_signal_symbols=cast(int, factors["minimum_signal_symbols"]),
            minimum_median_coverage=float(factors["minimum_median_coverage"]),
        )
    passing = summary.filter(pl.col("research_status") == "RESEARCH_ONLY")
    conclusion = "RESEARCH_ONLY" if passing.height else "REJECTED"
    report = _report(
        config=config,
        bar_snapshot_id=bar_snapshot.snapshot_id,
        bar_manifest_sha256=bar_snapshot.manifest_sha256,
        daily_snapshot_id=daily_snapshot.snapshot_id,
        daily_manifest_sha256=daily_snapshot.manifest_sha256,
        candidates=candidates,
        panel=panel,
        results=results,
        summary=summary,
        conclusion=conclusion,
        monthly=monthly,
    )
    outputs = {
        "daily_ic.parquet": _parquet(cast(pl.DataFrame, results["daily_ic"])),
        (
            "monthly_signal_coverage.parquet"
            if monthly
            else "daily_value_coverage.parquet"
        ): _parquet(coverage),
        "factor_catalog.json": canonical_json_bytes(
            [
                {
                    "mechanism": spec.mechanism,
                    "missing_rule": spec.missing_rule,
                    "name": spec.name,
                    "source": spec.source,
                }
                for spec in factor_specs
            ]
        ),
        "factor_summary.parquet": _parquet(summary),
        "fold_metrics.parquet": _parquet(
            cast(pl.DataFrame, results["fold_metrics"])
        ),
        "group_returns.parquet": _parquet(
            cast(pl.DataFrame, results["group_returns"])
        ),
        "portfolio_nav.parquet": _parquet(
            cast(pl.DataFrame, results["portfolio_nav"])
        ),
        "redundancy_daily.parquet": _parquet(redundancy_daily),
        "redundancy_summary.parquet": _parquet(redundancy_summary),
        "report.json": canonical_json_bytes(report),
        "targets.parquet": _parquet(cast(pl.DataFrame, results["targets"])),
    }
    folds = _folds(config)
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
            project_root=project_root,
            relative_paths=_LIQUIDITY_CODE_PATHS if monthly else _BASE_CODE_PATHS,
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
        selection_metric=(
            "monthly_walk_forward_rank_ic_with_coverage_and_redundancy_gates"
            if monthly
            else "walk_forward_rank_ic_with_redundancy_gate"
        ),
        inputs=(
            ResearchInputDigestV1(
                name="tushare-daily-basic",
                rows=daily_snapshot.rows,
                min_date=cast(dt.date, data["warmup_start"]),
                max_date=cast(dt.date, data["research_end"]),
                content_sha256=daily_snapshot.manifest_sha256,
            ),
            ResearchInputDigestV1(
                name="tushare-stock-bars",
                rows=bar_snapshot.stock_rows,
                min_date=cast(dt.date, data["warmup_start"]),
                max_date=cast(dt.date, data["research_end"]),
                content_sha256=bar_snapshot.manifest_sha256,
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
            ("panel_rows", panel.height),
            ("passing_factor_count", passing.height),
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


def build_daily_value_panel(
    *,
    daily_basic: pl.DataFrame,
    bars: pl.DataFrame,
    sessions: tuple[dt.date, ...],
    horizons: tuple[int, ...] = (1, 5, 20),
) -> pl.DataFrame:
    """Join daily-value signals to bar-only controls and next-open labels."""
    daily_values = compute_daily_value_factors(daily_basic)
    if daily_values.select(
        pl.struct("symbol", "trade_date").is_duplicated().any()
    ).item():
        raise ValueError("daily-basic values contain duplicate symbol-date keys")
    bar_values = compute_classic_daily_factors(bars)
    factor_values = daily_values.select(
        "symbol",
        "trade_date",
        *DAILY_VALUE_FACTOR_NAMES,
        "log_total_market_value",
    ).join(
        bar_values.select(
            "symbol",
            "trade_date",
            "history_rows",
            "liquidity_20",
            *CLASSIC_FACTOR_NAMES,
        ),
        on=["symbol", "trade_date"],
        how="inner",
        validate="1:1",
    )
    if factor_values.is_empty():
        raise ValueError("daily-basic and bar snapshots do not overlap")
    return build_next_open_factor_labels(
        factor_values=factor_values,
        bars=bars,
        sessions=sessions,
        horizons=horizons,
    )


def build_monthly_liquidity_panel(
    *,
    daily_basic: pl.DataFrame,
    bars: pl.DataFrame,
    sessions: tuple[dt.date, ...],
    signal_dates: tuple[dt.date, ...],
    candidate_symbols: tuple[str, ...],
    horizons: tuple[int, ...] = (1, 5, 20),
    minimum_valid_days: int = 15,
    turnover_history_months: int = 12,
) -> pl.DataFrame:
    """Join monthly liquidity signals to controls and next-open labels."""
    amihud = compute_monthly_amihud_illiquidity(
        bars,
        sessions=sessions,
        signal_dates=signal_dates,
        candidate_symbols=candidate_symbols,
        minimum_valid_days=minimum_valid_days,
    )
    turnover = compute_monthly_free_float_turnover_factors(
        daily_basic,
        signal_dates=signal_dates,
        candidate_symbols=candidate_symbols,
        minimum_valid_days=minimum_valid_days,
        history_months=turnover_history_months,
    )
    daily_values = compute_daily_value_factors(daily_basic).filter(
        pl.col("trade_date").is_in(signal_dates)
    )
    bar_values = compute_classic_daily_factors(bars).filter(
        pl.col("trade_date").is_in(signal_dates)
    )
    factor_values = (
        amihud.join(
            turnover,
            on=["symbol", "trade_date"],
            how="inner",
            validate="1:1",
        )
        .join(
            daily_values.select(
                "symbol",
                "trade_date",
                *DAILY_VALUE_FACTOR_NAMES,
                "log_total_market_value",
            ),
            on=["symbol", "trade_date"],
            how="left",
            validate="1:1",
        )
        .join(
            bar_values.select(
                "symbol",
                "trade_date",
                "history_rows",
                "liquidity_20",
                *CLASSIC_FACTOR_NAMES,
            ),
            on=["symbol", "trade_date"],
            how="inner",
            validate="1:1",
        )
    )
    if factor_values.is_empty():
        raise ValueError("monthly liquidity and bar snapshots do not overlap")
    if tuple(
        factor_values.get_column("trade_date").unique().sort().to_list()
    ) != signal_dates:
        raise ValueError("monthly liquidity panel is missing a signal date")
    fixed_horizon = build_next_open_factor_labels(
        factor_values=factor_values,
        bars=bars,
        sessions=sessions,
        horizons=horizons,
    )
    return build_next_rebalance_open_labels(
        factor_values=fixed_horizon,
        bars=bars,
        sessions=sessions,
    )


def build_daily_value_coverage(panel: pl.DataFrame) -> pl.DataFrame:
    """Return deterministic per-date coverage for every pre-registered proxy."""
    return build_factor_coverage(panel, factors=DAILY_VALUE_FACTOR_NAMES)


def build_factor_coverage(
    panel: pl.DataFrame, *, factors: tuple[str, ...]
) -> pl.DataFrame:
    """Return deterministic per-signal coverage for the requested factors."""
    if not isinstance(panel, pl.DataFrame) or panel.is_empty():
        raise ValueError("factor coverage panel is empty")
    if (
        type(factors) is not tuple
        or not factors
        or len(factors) != len(set(factors))
        or any(name not in panel.columns for name in factors)
    ):
        raise ValueError("invalid factor coverage request")
    frames: list[pl.DataFrame] = []
    for factor in factors:
        frames.append(
            panel.group_by("trade_date")
            .agg(
                pl.len().alias("eligible_rows"),
                (
                    pl.col(factor).is_not_null() & pl.col(factor).is_finite()
                ).sum().alias("valid_rows"),
            )
            .with_columns(
                pl.lit(factor).alias("factor"),
                (pl.col("valid_rows") / pl.col("eligible_rows")).alias("coverage"),
            )
            .select("factor", "trade_date", "eligible_rows", "valid_rows", "coverage")
        )
    return pl.concat(frames).sort("factor", "trade_date")


def apply_coverage_gate(
    summary: pl.DataFrame,
    *,
    coverage: pl.DataFrame,
    minimum_signal_symbols: int,
    minimum_median_coverage: float,
) -> pl.DataFrame:
    """Reject factors that fail any signal-date or median coverage threshold."""
    if (
        not isinstance(summary, pl.DataFrame)
        or summary.is_empty()
        or not isinstance(coverage, pl.DataFrame)
        or coverage.is_empty()
        or type(minimum_signal_symbols) is not int
        or minimum_signal_symbols < 2
        or not 0 < minimum_median_coverage <= 1
    ):
        raise ValueError("invalid factor coverage gate")
    factor_names = tuple(summary.get_column("factor").to_list())
    required_columns = {
        "factor",
        "trade_date",
        "eligible_rows",
        "valid_rows",
        "coverage",
    }
    if not required_columns <= set(coverage.columns):
        raise ValueError("coverage factors do not match summary")
    signal_dates = coverage.get_column("trade_date").unique().to_list()
    if (
        coverage.select(
            pl.struct("factor", "trade_date").is_duplicated().any()
        ).item()
        or set(coverage.get_column("factor").unique().to_list())
        != set(factor_names)
        or coverage.height != len(factor_names) * len(signal_dates)
        or coverage.filter(
            (pl.col("eligible_rows") <= 0)
            | (pl.col("valid_rows") < 0)
            | (pl.col("valid_rows") > pl.col("eligible_rows"))
            | ~pl.col("coverage").is_finite()
            | ~pl.col("coverage").is_between(0.0, 1.0, closed="both")
            | (
                pl.col("coverage")
                != pl.col("valid_rows").cast(pl.Float64)
                / pl.col("eligible_rows").cast(pl.Float64)
            )
        ).height
        > 0
    ):
        raise ValueError("coverage factors do not match summary")
    coverage_summary = coverage.group_by("factor").agg(
        pl.col("valid_rows").min().alias("minimum_valid_rows"),
        pl.col("coverage").median().alias("median_coverage"),
    )
    return (
        summary.join(coverage_summary, on="factor", how="left", validate="1:1")
        .with_columns(
            (
                (pl.col("minimum_valid_rows") >= minimum_signal_symbols)
                & (pl.col("median_coverage") >= minimum_median_coverage)
            ).alias("coverage_passed")
        )
        .with_columns(
            pl.when(
                (pl.col("research_status") == "RESEARCH_ONLY")
                & pl.col("coverage_passed")
            )
            .then(pl.lit("RESEARCH_ONLY"))
            .otherwise(pl.lit("REJECTED"))
            .alias("research_status")
        )
        .sort("factor")
    )


def apply_expected_direction_gate(
    summary: pl.DataFrame,
    *,
    fold_metrics: pl.DataFrame,
    expected_directions: Mapping[str, Any],
) -> pl.DataFrame:
    """Reject factors whose validation-selected direction violates the prior."""
    if (
        not isinstance(summary, pl.DataFrame)
        or summary.is_empty()
        or not isinstance(fold_metrics, pl.DataFrame)
        or fold_metrics.is_empty()
        or not isinstance(expected_directions, Mapping)
    ):
        raise ValueError("invalid expected-direction gate")
    factor_names = tuple(summary.get_column("factor").to_list())
    if set(expected_directions) != set(factor_names) or any(
        type(expected_directions[name]) is not int
        or cast(int, expected_directions[name]) not in {-1, 1}
        for name in factor_names
    ):
        raise ValueError("expected directions do not match summary")
    observed = (
        fold_metrics.filter(pl.col("cost_multiplier") == 1.0)
        .group_by("factor")
        .agg(
            pl.col("direction").n_unique().alias("observed_direction_count"),
            pl.col("direction").first().alias("observed_direction"),
        )
    )
    expected = pl.DataFrame(
        {
            "factor": factor_names,
            "expected_direction": [
                cast(int, expected_directions[name]) for name in factor_names
            ],
        }
    )
    return (
        summary.join(observed, on="factor", how="left", validate="1:1")
        .join(expected, on="factor", how="left", validate="1:1")
        .with_columns(
            (
                (pl.col("observed_direction_count") == 1)
                & (pl.col("observed_direction") == pl.col("expected_direction"))
            ).alias("expected_direction_passed")
        )
        .with_columns(
            pl.when(
                (pl.col("research_status") == "RESEARCH_ONLY")
                & pl.col("expected_direction_passed")
            )
            .then(pl.lit("RESEARCH_ONLY"))
            .otherwise(pl.lit("REJECTED"))
            .alias("research_status")
        )
        .sort("factor")
    )


def apply_redundancy_gate(
    summary: pl.DataFrame,
    *,
    redundancy_summary: pl.DataFrame,
    maximum_median_absolute_rank_correlation: float,
) -> pl.DataFrame:
    """Reject otherwise passing factors that are near-duplicates of controls."""
    if (
        not isinstance(summary, pl.DataFrame)
        or summary.is_empty()
        or not isinstance(redundancy_summary, pl.DataFrame)
        or redundancy_summary.is_empty()
        or not 0 < maximum_median_absolute_rank_correlation < 1
    ):
        raise ValueError("invalid daily-value redundancy gate")
    candidate_factors = summary.get_column("factor").to_list()
    maxima = (
        pl.concat(
            [
                redundancy_summary.select(
                    pl.col("factor_a").alias("factor"),
                    "median_abs_rank_corr",
                ),
                redundancy_summary.filter(
                    pl.col("factor_b").is_in(candidate_factors)
                ).select(
                    pl.col("factor_b").alias("factor"),
                    "median_abs_rank_corr",
                ),
            ]
        )
        .group_by("factor")
        .agg(
            pl.col("median_abs_rank_corr")
            .max()
            .alias("max_median_abs_rank_corr")
        )
    )
    return (
        summary.join(
            maxima,
            on="factor",
            how="left",
            validate="1:1",
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
        .with_columns(
            pl.when(
                (pl.col("research_status") == "RESEARCH_ONLY")
                & pl.col("redundancy_passed")
            )
            .then(pl.lit("RESEARCH_ONLY"))
            .otherwise(pl.lit("REJECTED"))
            .alias("research_status")
        )
        .sort("factor")
    )


def _study_contract(
    config: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[Any, ...], tuple[str, ...], bool]:
    catalog = cast(str, cast(Mapping[str, Any], config["factors"])["catalog"])
    if catalog == _DAILY_VALUE_CATALOG:
        return (
            DAILY_VALUE_FACTOR_NAMES,
            DAILY_VALUE_FACTOR_SPECS,
            _REFERENCE_FACTORS,
            False,
        )
    if catalog == _AMIHUD_CATALOG:
        return (
            AMIHUD_FACTOR_NAMES,
            tuple(
                spec for spec in LIQUIDITY_FACTOR_SPECS if spec.name in AMIHUD_FACTOR_NAMES
            ),
            _AMIHUD_REFERENCE_FACTORS,
            True,
        )
    if catalog == _TURNOVER_CATALOG:
        return (
            TURNOVER_FACTOR_NAMES,
            tuple(
                spec
                for spec in LIQUIDITY_FACTOR_SPECS
                if spec.name in TURNOVER_FACTOR_NAMES
            ),
            _TURNOVER_REFERENCE_FACTORS,
            True,
        )
    raise ValueError("invalid daily-value-factor config")


def _validate_config(config: Mapping[str, Any], *, threads: int) -> None:
    try:
        data = cast(Mapping[str, Any], config["data"])
        factors = cast(Mapping[str, Any], config["factors"])
        portfolio = cast(Mapping[str, Any], config["portfolio"])
        factor_names, _, reference_names, monthly = _study_contract(config)
        common = (
            type(data["bar_snapshot_id"]) is str
            and len(cast(str, data["bar_snapshot_id"])) == 64
            and set(cast(str, data["bar_snapshot_id"]))
            <= set("0123456789abcdef")
            and tuple(cast(list[str], factors["names"])) == factor_names
            and tuple(cast(list[str], factors["redundancy_reference_names"]))
            == reference_names
            and float(factors["maximum_median_absolute_rank_correlation"]) == 0.80
            and tuple(cast(list[int], factors["horizons"])) == (1, 5, 20)
            and tuple(float(value) for value in portfolio["cost_multipliers"])
            == (0.5, 1.0, 2.0)
            and portfolio["selection_horizon_sessions"] == 20
            and type(threads) is int
        )
        if monthly:
            expected = (
                _AMIHUD_EXPECTED_DIRECTIONS
                if factors["catalog"] == _AMIHUD_CATALOG
                else _TURNOVER_EXPECTED_DIRECTIONS
            )
            valid = (
                common
                and dict(cast(Mapping[str, Any], factors["expected_directions"]))
                == expected
                and factors["signal_frequency"] == "calendar_month_end"
                and factors["portfolio_label"] == "next_rebalance_open"
                and factors["minimum_valid_days"] == 15
                and factors["turnover_history_months"] == 12
                and factors["minimum_signal_symbols"] == 100
                and float(factors["minimum_median_coverage"]) == 0.80
                and factors["ic_newey_west_lag"] == 1
                and portfolio["rebalance_every_signals"] == 1
                and portfolio["annualization_periods"] == 12
                and 1 <= threads <= 2
            )
        else:
            valid = common and 1 <= threads <= 4
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("invalid daily-value-factor config")


def _report(
    *,
    config: Mapping[str, Any],
    bar_snapshot_id: str,
    bar_manifest_sha256: str,
    daily_snapshot_id: str,
    daily_manifest_sha256: str,
    candidates: tuple[str, ...],
    panel: pl.DataFrame,
    results: Mapping[str, pl.DataFrame],
    summary: pl.DataFrame,
    conclusion: str,
    monthly: bool,
) -> dict[str, object]:
    return {
        "schema_version": (
            "m2-monthly-liquidity-factor-report-v1"
            if monthly
            else "m2-daily-value-factor-report-v1"
        ),
        "conclusion": conclusion,
        "hypothesis": config["research"]["hypothesis"],
        "bar_snapshot_id": bar_snapshot_id,
        "bar_manifest_sha256": bar_manifest_sha256,
        "daily_basic_snapshot_id": daily_snapshot_id,
        "daily_basic_manifest_sha256": daily_manifest_sha256,
        "candidate_symbol_count": len(candidates),
        "panel_rows": panel.height,
        "daily_ic_rows": results["daily_ic"].height,
        "target_rows": results["targets"].height,
        "factor_summary": summary.to_dicts(),
        "redundancy_summary": results["redundancy_summary"].to_dicts(),
        "timing": {
            "signal": (
                "proven calendar-month-end close using only rows available by as_of"
                if monthly
                else "daily_basic row available after close of as_of session"
            ),
            "execution": "next exchange session open from verified stock bars",
            "label": (
                "fixed 1/5/20 next-open IC labels; portfolio exits at the next signal's next open"
                if monthly
                else "adjusted open(t+1+h)/adjusted open(t+1)-1"
            ),
        },
        "caveats": _report_caveats(monthly=monthly),
    }


def _report_caveats(*, monthly: bool) -> list[str]:
    shared = [
        "The 2019 liquid universe is PIT only at its freeze date and is not an evolving constituent universe.",
        "Daily-basic close is never used as the bar, label, execution or valuation authority.",
        "Historical ST flags, industries and full market-event replay are not available in this diagnostic.",
        "No result may exceed RESEARCH_ONLY without separate forward and market-event evidence.",
    ]
    if monthly:
        return [
            "Amihud and free-float turnover are daily-data liquidity proxies, not order-book impact or executable capacity estimates.",
            "A month requires at least fifteen valid observations; missing sessions are not forward-filled.",
            "The monthly next-rebalance portfolio is a research diagnostic, not the formal A-share account replay.",
            *shared,
        ]
    return [
        "Daily-basic ratios are vendor daily proxies, not reconstructed PIT financial-statement factors.",
        "Loss-making and non-positive denominator observations are null by the frozen factor formulas.",
        "The twenty-session portfolio is a factor diagnostic, not the formal A-share account replay.",
        *shared,
    ]


if __name__ == "__main__":
    raise SystemExit(main())
