"""Run the frozen M2 ``daily_basic`` value-proxy research study."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
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
from quant.factors.max_daily_basic_control import (
    MAX_DAILY_BASIC_CONTROL_NAMES,
    MAX_DAILY_BASIC_CONTROL_SPECS,
    compute_max_daily_basic_control,
)
from quant.research.classic_factor_evaluation import evaluate_factor_redundancy
from quant.research.factor_labels import (
    build_next_open_factor_labels,
    build_next_rebalance_open_labels,
)
from quant.research.lightweight_run import (
    LightweightResearchRunV1,
    ResearchInputDigestV1,
    ResearchFoldV1,
    canonical_json_bytes,
    compute_code_sha256,
    publish_lightweight_research_run,
    verify_lightweight_research_run,
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
_MAX_CONTROL_CATALOG = "max_daily_basic_size_turnover_control_v1"
_REFERENCE_FACTORS = CLASSIC_FACTOR_NAMES + ("log_total_market_value",)
_AMIHUD_REFERENCE_FACTORS = _REFERENCE_FACTORS + DAILY_VALUE_FACTOR_NAMES + TURNOVER_FACTOR_NAMES
_TURNOVER_REFERENCE_FACTORS = _REFERENCE_FACTORS + DAILY_VALUE_FACTOR_NAMES + AMIHUD_FACTOR_NAMES
_AMIHUD_EXPECTED_DIRECTIONS = {"amihud_illiquidity_monthly": 1}
_TURNOVER_EXPECTED_DIRECTIONS = {
    "free_float_turnover_level_monthly": -1,
    "free_float_turnover_abnormal_12m": -1,
}
_MAX_CONTROL_REFERENCE_FACTORS = (
    "max_daily_return_20",
    "log_total_market_value",
    "turnover_rate_free",
)
_MAX_CONTROL_EXPECTED_DIRECTIONS = {
    "max_daily_return_20_size_turnover_residual": -1,
}
_RAW_MAX_RUN_ID = (
    "10dea14f1fcbbbeb78871cddb7b00cd06d77cf005c3a776c4713f5a4f4129bb3"
)
_RAW_MAX_BAR_SNAPSHOT_ID = (
    "b79a7b5e66dee0ae439c030078414157ca6c1f3b6ce7fbe5e36ff3910c1089d2"
)
_MAX_CONTROL_DAILY_BASIC_SNAPSHOT_ID = (
    "e97c0e9c82c445bbc9b389e8e8504f61b0b67d2f789208f75625526c38b4c03c"
)
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
_MAX_CONTROL_CODE_PATHS = _BASE_CODE_PATHS + (
    "src/quant/factors/classic_fifth_batch.py",
    "src/quant/factors/max_daily_basic_control.py",
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
    parser.add_argument("--raw-max-run-root", type=Path)
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
    catalog = cast(str, factors["catalog"])
    max_control = catalog == _MAX_CONTROL_CATALOG
    if max_control:
        if (
            args.daily_basic_snapshot_id
            != cast(Mapping[str, Any], config["max_control"])[
                "daily_basic_snapshot_id"
            ]
        ):
            raise ValueError("MAX control daily-basic snapshot does not match")
        if args.raw_max_run_root is None:
            raise ValueError("MAX control requires a raw MAX run root")
        raw_max_root = (
            args.raw_max_run_root
            if args.raw_max_run_root.is_absolute()
            else project_root / args.raw_max_run_root
        ).resolve(strict=True)
        raw_max_run = verify_lightweight_research_run(run_root=raw_max_root)
    else:
        if args.raw_max_run_root is not None:
            raise ValueError("raw MAX run root is only valid for MAX control")
        raw_max_run = None
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
    folds = _folds(config)
    if raw_max_run is not None:
        _validate_raw_max_reference(
            raw_max_run,
            config=config,
            bar_manifest_sha256=bar_snapshot.manifest_sha256,
            candidates=candidates,
            folds=folds,
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
    control_diagnostics: pl.DataFrame | None = None
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
    elif max_control:
        control = cast(Mapping[str, Any], config["max_control"])
        panel, control_diagnostics = build_max_daily_basic_control_panel(
            daily_basic=daily_basic,
            bars=bars,
            sessions=sessions,
            horizons=tuple(cast(list[int], factors["horizons"])),
            minimum_regression_rows=cast(
                int, control["minimum_regression_rows"]
            ),
            maximum_condition_number=float(control["maximum_condition_number"]),
            orthogonality_tolerance=float(
                control["normal_equation_orthogonality_tolerance"]
            ),
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
        folds=folds,
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
        ic_newey_west_lag=(
            cast(int, factors["ic_newey_west_lag"]) if monthly else None
        ),
        fixed_direction=(-1 if max_control else None),
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
    if not max_control:
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
    elif max_control:
        if control_diagnostics is None:
            raise ValueError("MAX control diagnostics are missing")
        coverage_config = cast(Mapping[str, Any], config["coverage"])
        coverage, coverage_summary = evaluate_max_control_coverage(
            panel,
            factors=factor_names,
            start_date=cast(dt.date, data["research_start"]),
            end_date=cast(dt.date, data["research_end"]),
            folds=folds,
            rebalance_every_sessions=cast(
                int, portfolio["rebalance_every_sessions"]
            ),
            minimum_rebalance_symbols=cast(
                int, coverage_config["minimum_rebalance_symbols"]
            ),
            minimum_median_coverage=float(
                coverage_config["minimum_median_coverage"]
            ),
        )
        schedule_alignment = evaluate_max_control_schedule_alignment(
            panel,
            cast(pl.DataFrame, results["targets"]),
            factors=factor_names,
            folds=folds,
            rebalance_every_sessions=cast(
                int, portfolio["rebalance_every_sessions"]
            ),
        )
        research_dates = panel.select("trade_date").unique().sort("trade_date")
        research_diagnostics = research_dates.join(
            control_diagnostics,
            on="trade_date",
            how="left",
            validate="1:1",
        ).sort("trade_date")
        summary = apply_max_control_admission_gates(
            summary,
            fold_metrics=cast(pl.DataFrame, results["fold_metrics"]),
            coverage_summary=coverage_summary,
            schedule_alignment=schedule_alignment,
            regression_diagnostics=research_diagnostics,
            expected_direction=cast(
                int,
                cast(Mapping[str, Any], config["max_control"])[
                    "expected_direction"
                ],
            ),
        )
        results["factor_coverage_summary"] = coverage_summary
        results["rebalance_schedule_alignment"] = schedule_alignment
        results["control_regression_diagnostics"] = research_diagnostics
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
        max_control=max_control,
    )
    outputs = {
        "daily_ic.parquet": _parquet(cast(pl.DataFrame, results["daily_ic"])),
        (
            "monthly_signal_coverage.parquet"
            if monthly
            else (
                "max_control_coverage.parquet"
                if max_control
                else "daily_value_coverage.parquet"
            )
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
    if max_control:
        outputs.update(
            {
                "control_regression_diagnostics.parquet": _parquet(
                    cast(pl.DataFrame, results["control_regression_diagnostics"])
                ),
                "factor_coverage_summary.parquet": _parquet(
                    cast(pl.DataFrame, results["factor_coverage_summary"])
                ),
                "rebalance_schedule_alignment.parquet": _parquet(
                    cast(pl.DataFrame, results["rebalance_schedule_alignment"])
                ),
            }
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
            project_root=project_root,
            relative_paths=(
                _LIQUIDITY_CODE_PATHS
                if monthly
                else (_MAX_CONTROL_CODE_PATHS if max_control else _BASE_CODE_PATHS)
            ),
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
            else (
                "walk_forward_rank_ic_with_size_turnover_control_gates"
                if max_control
                else "walk_forward_rank_ic_with_redundancy_gate"
            )
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


def build_max_daily_basic_control_panel(
    *,
    daily_basic: pl.DataFrame,
    bars: pl.DataFrame,
    sessions: tuple[dt.date, ...],
    horizons: tuple[int, ...] = (1, 5, 20),
    minimum_regression_rows: int,
    maximum_condition_number: float,
    orthogonality_tolerance: float,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Join controlled MAX to bar-only labels and return OLS diagnostics."""
    controlled, diagnostics = compute_max_daily_basic_control(
        bars,
        daily_basic,
        sessions=sessions,
        minimum_regression_rows=minimum_regression_rows,
        maximum_condition_number=maximum_condition_number,
        orthogonality_tolerance=orthogonality_tolerance,
    )
    bar_values = compute_classic_daily_factors(bars)
    factor_values = controlled.join(
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
        raise ValueError("controlled MAX and bar snapshots do not overlap")
    return (
        build_next_open_factor_labels(
            factor_values=factor_values,
            bars=bars,
            sessions=sessions,
            horizons=horizons,
        ),
        diagnostics,
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


def evaluate_max_control_coverage(
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
    """Measure all-date and frozen-rebalance coverage for controlled MAX."""
    if (
        not isinstance(panel, pl.DataFrame)
        or panel.is_empty()
        or "exit_date_20" not in panel.columns
        or type(factors) is not tuple
        or not factors
        or any(
            type(name) is not str or name not in panel.columns
            for name in factors
        )
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
        or not 0.0 < minimum_median_coverage <= 1.0
    ):
        raise ValueError("invalid controlled MAX coverage request")
    research = panel.filter(
        pl.col("trade_date").is_between(start_date, end_date, closed="both")
    )
    if research.is_empty():
        raise ValueError("controlled MAX coverage window is empty")
    scheduled_dates = tuple(
        date
        for fold in folds
        for date in _max_control_scheduled_dates(
            research,
            fold=fold,
            rebalance_every_sessions=rebalance_every_sessions,
        )
    )
    if not scheduled_dates or len(scheduled_dates) != len(set(scheduled_dates)):
        raise ValueError("controlled MAX rebalance schedule is invalid")
    daily = build_factor_coverage(research, factors=factors).with_columns(
        pl.col("trade_date").is_in(scheduled_dates).alias("scheduled_rebalance")
    )
    rows: list[dict[str, object]] = []
    for factor in factors:
        one = daily.filter(pl.col("factor") == factor)
        scheduled = one.filter(pl.col("scheduled_rebalance"))
        if scheduled.height != len(scheduled_dates):
            raise ValueError("controlled MAX coverage schedule is incomplete")
        minimum_valid_rows = cast(
            int, scheduled.get_column("valid_rows").min()
        )
        median_coverage = cast(float, one.get_column("coverage").median())
        rows.append(
            {
                "factor": factor,
                "dates": one.height,
                "scheduled_rebalance_dates": len(scheduled_dates),
                "minimum_rebalance_valid_rows": minimum_valid_rows,
                "median_coverage": median_coverage,
                "coverage_passed": (
                    minimum_valid_rows >= minimum_rebalance_symbols
                    and median_coverage >= minimum_median_coverage
                ),
            }
        )
    return daily.sort("factor", "trade_date"), pl.DataFrame(rows).sort("factor")


def evaluate_max_control_schedule_alignment(
    panel: pl.DataFrame,
    targets: pl.DataFrame,
    *,
    factors: tuple[str, ...],
    folds: tuple[ResearchFoldV1, ...],
    rebalance_every_sessions: int,
) -> pl.DataFrame:
    """Compare actual targets with the factor-independent frozen schedule."""
    if (
        not isinstance(panel, pl.DataFrame)
        or panel.is_empty()
        or not {"trade_date", "exit_date_20"}.issubset(panel.columns)
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
        raise ValueError("invalid controlled MAX schedule request")
    rows: list[dict[str, object]] = []
    for factor in factors:
        for fold in folds:
            expected = _max_control_scheduled_dates(
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
            missing = tuple(sorted(expected_set - actual_set))
            unexpected = tuple(sorted(actual_set - expected_set))
            rows.append(
                {
                    "factor": factor,
                    "fold": fold.fold,
                    "expected_rebalance_dates": len(expected),
                    "actual_rebalance_dates": len(actual),
                    "missing_rebalance_dates": len(missing),
                    "unexpected_rebalance_dates": len(unexpected),
                    "missing_dates": missing,
                    "unexpected_dates": unexpected,
                    "schedule_aligned": actual == expected,
                }
            )
    return pl.DataFrame(rows).sort("factor", "fold")


def apply_max_control_admission_gates(
    summary: pl.DataFrame,
    *,
    fold_metrics: pl.DataFrame,
    coverage_summary: pl.DataFrame,
    schedule_alignment: pl.DataFrame,
    regression_diagnostics: pl.DataFrame,
    expected_direction: int,
) -> pl.DataFrame:
    """Apply fixed-direction, OLS, coverage and schedule gates to controlled MAX."""
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
        or not isinstance(coverage_summary, pl.DataFrame)
        or coverage_summary.is_empty()
        or not {"factor", "coverage_passed"}.issubset(coverage_summary.columns)
        or not isinstance(schedule_alignment, pl.DataFrame)
        or schedule_alignment.is_empty()
        or not {"factor", "fold", "schedule_aligned"}.issubset(
            schedule_alignment.columns
        )
        or not isinstance(regression_diagnostics, pl.DataFrame)
        or regression_diagnostics.is_empty()
        or not {"trade_date", "regression_valid"}.issubset(
            regression_diagnostics.columns
        )
        or expected_direction not in {-1, 1}
    ):
        raise ValueError("invalid controlled MAX admission gate request")
    factor_names = tuple(summary.get_column("factor").to_list())
    if (
        set(coverage_summary.get_column("factor").to_list()) != set(factor_names)
        or set(schedule_alignment.get_column("factor").to_list())
        != set(factor_names)
        or regression_diagnostics.select(
            pl.col("trade_date").is_duplicated().any()
        ).item()
    ):
        raise ValueError("controlled MAX gate evidence is incomplete")
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
    schedule = schedule_alignment.group_by("factor").agg(
        pl.col("schedule_aligned").all().alias("schedule_alignment_passed")
    )
    regression_passed = cast(
        bool,
        regression_diagnostics.select(
            pl.col("regression_valid").fill_null(False).all()
        ).item(),
    )
    return (
        summary.join(directions, on="factor", how="left", validate="1:1")
        .join(coverage_summary, on="factor", how="left", validate="1:1")
        .join(schedule, on="factor", how="left", validate="1:1")
        .with_columns(
            pl.lit(expected_direction).alias("expected_direction"),
            (
                (pl.col("selected_direction_count") == 1)
                & (pl.col("selected_direction") == expected_direction)
            ).fill_null(False).alias("fixed_direction_passed"),
            pl.col("validation_direction_passed")
            .fill_null(False)
            .alias("validation_direction_passed"),
            pl.col("coverage_passed").fill_null(False).alias("coverage_passed"),
            pl.col("schedule_alignment_passed")
            .fill_null(False)
            .alias("schedule_alignment_passed"),
            pl.lit(regression_passed).alias("regression_passed"),
        )
        .with_columns(
            pl.when(
                (pl.col("research_status") == "RESEARCH_ONLY")
                & pl.col("fixed_direction_passed")
                & pl.col("validation_direction_passed")
                & pl.col("coverage_passed")
                & pl.col("schedule_alignment_passed")
                & pl.col("regression_passed")
            )
            .then(pl.lit("RESEARCH_ONLY"))
            .otherwise(pl.lit("REJECTED"))
            .alias("research_status")
        )
        .sort("factor")
    )


def _max_control_scheduled_dates(
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


def _validate_raw_max_reference(
    raw_run: LightweightResearchRunV1,
    *,
    config: Mapping[str, Any],
    bar_manifest_sha256: str,
    candidates: tuple[str, ...],
    folds: tuple[ResearchFoldV1, ...],
) -> None:
    """Bind the control study to the canonical, freshly verified raw MAX run."""
    if type(raw_run) is not LightweightResearchRunV1:
        raise ValueError("raw MAX reference does not match controlled study")
    data = cast(Mapping[str, Any], config["data"])
    universe = cast(Mapping[str, Any], config["universe"])
    portfolio = cast(Mapping[str, Any], config["portfolio"])
    control = cast(Mapping[str, Any], config["max_control"])
    stock_inputs = tuple(
        item for item in raw_run.inputs if item.name == "tushare-stock-bars"
    )
    if (
        raw_run.run_id != control["raw_max_run_id"]
        or raw_run.run_id != _RAW_MAX_RUN_ID
        or raw_run.hypothesis_id != "m2-classic-fifth-batch-max-lottery-v1"
        or raw_run.conclusion != "RESEARCH_ONLY"
        or raw_run.config_relative_path
        != "configs/research/m2_classic_daily_factors_fifth_batch.toml"
        or raw_run.universe_frozen_as_of != universe["freeze_end"]
        or raw_run.candidate_symbols != candidates
        or raw_run.data_start != data["research_start"]
        or raw_run.data_end != data["research_end"]
        or raw_run.signal_timing != "close"
        or raw_run.execution_timing != "next_session_open"
        or raw_run.valuation_timing != "close"
        or raw_run.folds != folds
        or raw_run.cost_multipliers
        != tuple(float(value) for value in portfolio["cost_multipliers"])
        or len(stock_inputs) != 1
        or stock_inputs[0].content_sha256 != bar_manifest_sha256
        or stock_inputs[0].min_date != data["warmup_start"]
        or stock_inputs[0].max_date != data["research_end"]
    ):
        raise ValueError("raw MAX reference does not match controlled study")


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
    if catalog == _MAX_CONTROL_CATALOG:
        return (
            MAX_DAILY_BASIC_CONTROL_NAMES,
            MAX_DAILY_BASIC_CONTROL_SPECS,
            _MAX_CONTROL_REFERENCE_FACTORS,
            False,
        )
    raise ValueError("invalid daily-value-factor config")


def _validate_config(config: Mapping[str, Any], *, threads: int) -> None:
    try:
        data = cast(Mapping[str, Any], config["data"])
        factors = cast(Mapping[str, Any], config["factors"])
        portfolio = cast(Mapping[str, Any], config["portfolio"])
        admission = cast(Mapping[str, Any], config["admission"])
        factor_names, _, reference_names, monthly = _study_contract(config)
        catalog = cast(str, factors["catalog"])
        max_control = catalog == _MAX_CONTROL_CATALOG
        common = (
            type(data["bar_snapshot_id"]) is str
            and len(cast(str, data["bar_snapshot_id"])) == 64
            and set(cast(str, data["bar_snapshot_id"]))
            <= set("0123456789abcdef")
            and tuple(cast(list[str], factors["names"])) == factor_names
            and tuple(cast(list[str], factors["redundancy_reference_names"]))
            == reference_names
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
                and float(factors["maximum_median_absolute_rank_correlation"])
                == 0.80
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
        elif max_control:
            control = cast(Mapping[str, Any], config["max_control"])
            coverage = cast(Mapping[str, Any], config["coverage"])
            condition_limit = float(control["maximum_condition_number"])
            orthogonality_tolerance = float(
                control["normal_equation_orthogonality_tolerance"]
            )
            valid = (
                common
                and data["bar_snapshot_id"] == _RAW_MAX_BAR_SNAPSHOT_ID
                and factors["minimum_history_rows"] == 120
                and factors["minimum_daily_symbols"] == 100
                and factors["groups"] == 5
                and control["raw_max_run_id"] == _RAW_MAX_RUN_ID
                and control["daily_basic_snapshot_id"]
                == _MAX_CONTROL_DAILY_BASIC_SNAPSHOT_ID
                and control["raw_factor"] == "max_daily_return_20"
                and tuple(cast(list[str], control["controls"]))
                == ("log_total_market_value", "turnover_rate_free")
                and control["rank_method"] == "average"
                and control["regression"]
                == "cross_sectional_rank_ols_with_intercept"
                and control["singularity_rule"]
                == "positive_smallest_eigenvalue"
                and control["minimum_regression_rows"] == 100
                and math.isfinite(condition_limit)
                and condition_limit == 1_000_000.0
                and math.isfinite(orthogonality_tolerance)
                and orthogonality_tolerance == 1e-10
                and control["expected_direction"]
                == _MAX_CONTROL_EXPECTED_DIRECTIONS[factor_names[0]]
                and control["trial_budget"] == 1
                and coverage["minimum_rebalance_symbols"] == 100
                and float(coverage["minimum_median_coverage"]) == 0.80
                and portfolio["rebalance_every_sessions"] == 20
                and float(admission["minimum_mean_test_rank_ic"]) == 0.01
                and admission["minimum_positive_test_folds"] == 2
                and admission["require_direction_consistency"] is True
                and admission["require_positive_2x_cost_return"] is True
                and 1 <= threads <= 2
            )
        else:
            valid = (
                common
                and catalog == _DAILY_VALUE_CATALOG
                and float(factors["maximum_median_absolute_rank_correlation"])
                == 0.80
                and 1 <= threads <= 4
            )
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
    max_control: bool,
) -> dict[str, object]:
    control_summary: dict[str, object] = {}
    if max_control:
        diagnostics = cast(
            pl.DataFrame, results["control_regression_diagnostics"]
        )
        condition_values = diagnostics.filter(
            pl.col("condition_number").is_not_null()
            & pl.col("condition_number").is_finite()
        ).get_column("condition_number")
        error_values = diagnostics.filter(
            pl.col("orthogonality_error").is_not_null()
            & pl.col("orthogonality_error").is_finite()
        ).get_column("orthogonality_error")
        control_summary = {
            "dates": diagnostics.height,
            "passing_dates": diagnostics.filter(
                pl.col("regression_valid").fill_null(False)
            ).height,
            "minimum_complete_rows": cast(
                int, diagnostics.get_column("complete_rows").min()
            ),
            "maximum_condition_number": (
                cast(float, condition_values.max())
                if not condition_values.is_empty()
                else None
            ),
            "maximum_orthogonality_error": (
                cast(float, error_values.max())
                if not error_values.is_empty()
                else None
            ),
        }
    return {
        "schema_version": (
            "m2-monthly-liquidity-factor-report-v1"
            if monthly
            else (
                "m2-max-daily-basic-control-report-v1"
                if max_control
                else "m2-daily-value-factor-report-v1"
            )
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
        "factor_coverage_summary": (
            results["factor_coverage_summary"].to_dicts()
            if max_control
            else []
        ),
        "rebalance_schedule_alignment": (
            results["rebalance_schedule_alignment"].to_dicts()
            if max_control
            else []
        ),
        "control_regression_summary": control_summary,
        "max_control": config.get("max_control", {}),
        "timing": {
            "signal": (
                "proven calendar-month-end close using only rows available by as_of"
                if monthly
                else (
                    "same-session close MAX, size and free-float turnover known by as_of"
                    if max_control
                    else "daily_basic row available after close of as_of session"
                )
            ),
            "execution": "next exchange session open from verified stock bars",
            "label": (
                "fixed 1/5/20 next-open IC labels; portfolio exits at the next signal's next open"
                if monthly
                else "adjusted open(t+1+h)/adjusted open(t+1)-1"
            ),
        },
        "caveats": _report_caveats(monthly=monthly, max_control=max_control),
    }


def _report_caveats(*, monthly: bool, max_control: bool) -> list[str]:
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
    if max_control:
        return [
            "The control signal is a project-specific cross-sectional rank-OLS "
            "residual, not a claimed replication of a published portfolio sort "
            "or Fama-MacBeth specification.",
            "Raw MAX, size and turnover correlations are explanatory diagnostics "
            "and are not reused as a self-redundancy rejection gate.",
            "Every regression date must satisfy the frozen row-count, smallest-"
            "eigenvalue, condition-number and normal-equation checks; controls "
            "are never filled.",
            "The raw MAX run is freshly verified and must retain the same bar "
            "snapshot, candidate universe, folds and close-to-next-open timing.",
            "The twenty-session portfolio is a factor diagnostic, not the formal "
            "A-share account replay.",
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
