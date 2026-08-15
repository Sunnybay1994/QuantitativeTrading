"""Run the frozen first-batch PIT financial-quality factor study."""

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
from quant.data.financial_repository import (
    TushareFinancialHistoryQuery,
    read_tushare_financial_history,
)
from quant.data.publish_tushare_bulk_clean import verify_tushare_bulk_clean_snapshot
from quant.data.publish_tushare_daily_basic import verify_tushare_daily_basic_snapshot
from quant.data.publish_tushare_financials import verify_tushare_financial_snapshot
from quant.factors import (
    CLASSIC_FACTOR_NAMES,
    DAILY_VALUE_FACTOR_NAMES,
    PIT_QUALITY_FACTOR_NAMES,
    PIT_QUALITY_FACTOR_SPECS,
    compute_classic_daily_factors,
    compute_daily_value_factors,
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
from quant.research.pit_quality_research import (
    build_pit_quality_signal_values,
    monthly_signal_sessions,
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
from quant.research.run_daily_value_factors import apply_redundancy_gate
from quant.settings import resolve_data_root

_REFERENCE_FACTORS = CLASSIC_FACTOR_NAMES + DAILY_VALUE_FACTOR_NAMES + ("log_total_market_value",)
_CODE_PATHS = (
    "src/quant/data/audit_tushare_bulk_clean.py",
    "src/quant/data/audit_tushare_daily_basic.py",
    "src/quant/data/audit_tushare_financials.py",
    "src/quant/data/clean_snapshot_repository.py",
    "src/quant/data/daily_basic_repository.py",
    "src/quant/data/financial_clean.py",
    "src/quant/data/financial_pit.py",
    "src/quant/data/financial_repository.py",
    "src/quant/data/m3_release.py",
    "src/quant/data/publish_tushare_bulk_clean.py",
    "src/quant/data/publish_tushare_daily_basic.py",
    "src/quant/data/publish_tushare_financials.py",
    "src/quant/data/tushare_bulk.py",
    "src/quant/data/tushare_bulk_ingest.py",
    "src/quant/domain/schemas.py",
    "src/quant/factors/classic.py",
    "src/quant/factors/daily_value.py",
    "src/quant/factors/pit_quality.py",
    "src/quant/research/classic_factor_evaluation.py",
    "src/quant/research/factor_labels.py",
    "src/quant/research/lightweight_run.py",
    "src/quant/research/pit_quality_research.py",
    "src/quant/research/run_classic_factors.py",
    "src/quant/research/run_daily_value_factors.py",
    "src/quant/research/run_pit_quality_factors.py",
)


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one immutable three-snapshot PIT quality research run."""
    parser = argparse.ArgumentParser(description="运行 M2 PIT 财务质量因子研究")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/research/m2_pit_quality_factors.toml"),
    )
    parser.add_argument("--daily-basic-snapshot-id", required=True)
    parser.add_argument("--financial-snapshot-id", required=True)
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
    bar_snapshot_id = cast(str, data["bar_snapshot_id"])
    bar_snapshot = verify_tushare_bulk_clean_snapshot(
        data_root=data_root, snapshot_id=bar_snapshot_id
    )
    daily_snapshot = verify_tushare_daily_basic_snapshot(
        data_root=data_root, snapshot_id=args.daily_basic_snapshot_id
    )
    financial_snapshot = verify_tushare_financial_snapshot(
        data_root=data_root, snapshot_id=args.financial_snapshot_id
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
            start_date=cast(dt.date, data["research_start"]),
            end_date=cast(dt.date, data["research_end"]),
            symbols=candidates,
            threads=args.threads,
        ),
    )
    history_start = cast(dt.date, data["financial_history_start"])
    history_end = cast(dt.date, data["research_end"])
    income = read_tushare_financial_history(
        data_root=data_root,
        query=TushareFinancialHistoryQuery(
            snapshot_id=args.financial_snapshot_id,
            dataset="income",
            start_period=history_start,
            end_period=history_end,
            symbols=candidates,
            threads=args.threads,
        ),
    )
    balance = read_tushare_financial_history(
        data_root=data_root,
        query=TushareFinancialHistoryQuery(
            snapshot_id=args.financial_snapshot_id,
            dataset="balancesheet",
            start_period=history_start,
            end_period=history_end,
            symbols=candidates,
            threads=args.threads,
        ),
    )
    cash = read_tushare_financial_history(
        data_root=data_root,
        query=TushareFinancialHistoryQuery(
            snapshot_id=args.financial_snapshot_id,
            dataset="cashflow",
            start_period=history_start,
            end_period=history_end,
            symbols=candidates,
            threads=args.threads,
        ),
    )
    sessions = tuple(sorted(set(bars.get_column("trade_date").to_list())))
    signal_dates = monthly_signal_sessions(
        sessions,
        start=cast(dt.date, data["research_start"]),
        end=cast(dt.date, data["research_end"]),
    )
    if not signal_dates:
        raise ValueError("PIT quality signal calendar is empty")
    signals = build_pit_quality_signal_values(
        income_history=income,
        balance_history=balance,
        cash_history=cash,
        signal_dates=signal_dates,
        candidate_symbols=candidates,
        allowed_report_types=tuple(cast(list[str], factors["allowed_report_types"])),
    )
    panel = build_pit_quality_panel(
        signal_values=signals.factors,
        daily_basic=daily_basic,
        bars=bars,
        sessions=sessions,
        horizons=tuple(cast(list[int], factors["horizons"])),
    ).filter(
        (pl.col("history_rows") >= cast(int, factors["minimum_history_rows"]))
        & (pl.col("liquidity_20") >= float(universe["minimum_average_amount"]))
    )
    if panel.is_empty():
        raise ValueError("PIT quality evaluation panel is empty")

    results = evaluate_walk_forward(
        panel=panel,
        factors=PIT_QUALITY_FACTOR_NAMES,
        horizons=tuple(cast(list[int], factors["horizons"])),
        folds=_folds(config),
        minimum_symbols=cast(int, factors["minimum_signal_symbols"]),
        groups=cast(int, factors["groups"]),
        top_k=cast(int, portfolio["top_k"]),
        rebalance_every=cast(int, portfolio["rebalance_every_signals"]),
        initial_cash=Decimal(str(portfolio["initial_cash"])),
        cost_multipliers=tuple(Decimal(str(value)) for value in portfolio["cost_multipliers"]),
        costs=_cost_periods(project_root, portfolio),
        strategy_name=cast(str, config["research"]["strategy_name"]),
        strategy_version=cast(str, config["research"]["strategy_version"]),
        portfolio_return_column="label_rebalance",
        portfolio_execution_date_column="execution_date_rebalance",
        portfolio_exit_date_column="exit_date_rebalance",
        portfolio_annualization_periods=float(portfolio["annualization_periods"]),
        ic_newey_west_lag=cast(int, factors["newey_west_lag"]),
    )
    summary = summarize_factors(
        cast(pl.DataFrame, results["fold_metrics"]),
        factors=PIT_QUALITY_FACTOR_NAMES,
        admission=cast(Mapping[str, Any], config["admission"]),
    )
    redundancy_daily, redundancy_summary = evaluate_factor_redundancy(
        panel,
        factors=PIT_QUALITY_FACTOR_NAMES,
        reference_factors=_REFERENCE_FACTORS,
        start_date=cast(dt.date, data["research_start"]),
        end_date=cast(dt.date, data["research_end"]),
        minimum_symbols=cast(int, factors["minimum_signal_symbols"]),
    )
    redundancy_summary = attach_redundancy_signal_coverage(
        redundancy_summary,
        expected_signal_dates=len(signal_dates),
        minimum_coverage=float(factors["minimum_redundancy_signal_coverage"]),
    )
    summary = apply_redundancy_gate(
        summary,
        redundancy_summary=redundancy_summary,
        maximum_median_absolute_rank_correlation=float(
            factors["maximum_median_absolute_rank_correlation"]
        ),
    )
    summary = apply_redundancy_signal_coverage_gate(
        summary,
        redundancy_summary=redundancy_summary,
    )
    results["redundancy_daily"] = redundancy_daily
    results["redundancy_summary"] = redundancy_summary
    coverage = build_pit_quality_coverage(signals.eligibility)
    summary, coverage = apply_pit_quality_coverage_gate(
        summary,
        coverage=coverage,
        signal_dates=signal_dates,
        minimum_signal_symbols=cast(int, factors["minimum_signal_symbols"]),
        minimum_median_signal_coverage=float(factors["minimum_median_signal_coverage"]),
    )
    passing = summary.filter(pl.col("research_status") == "RESEARCH_ONLY")
    conclusion = "RESEARCH_ONLY" if passing.height else "REJECTED"
    report = _report(
        config=config,
        bar_snapshot_id=bar_snapshot.snapshot_id,
        bar_manifest_sha256=bar_snapshot.manifest_sha256,
        daily_snapshot_id=daily_snapshot.snapshot_id,
        daily_manifest_sha256=daily_snapshot.manifest_sha256,
        financial_snapshot_id=financial_snapshot.snapshot_id,
        financial_manifest_sha256=financial_snapshot.manifest_sha256,
        financial_dataset_rows=financial_snapshot.dataset_rows,
        candidates=candidates,
        signal_dates=signal_dates,
        panel=panel,
        eligibility=signals.eligibility,
        quarantined=signals.quarantined,
        results=results,
        summary=summary,
        conclusion=conclusion,
    )
    outputs = {
        "daily_ic.parquet": _parquet(cast(pl.DataFrame, results["daily_ic"])),
        "factor_catalog.json": canonical_json_bytes(
            [
                {
                    "direction": spec.direction,
                    "formula": spec.formula,
                    "invalid_rule": spec.invalid_rule,
                    "name": spec.name,
                }
                for spec in PIT_QUALITY_FACTOR_SPECS
            ]
        ),
        "factor_summary.parquet": _parquet(summary),
        "fold_metrics.parquet": _parquet(cast(pl.DataFrame, results["fold_metrics"])),
        "group_returns.parquet": _parquet(cast(pl.DataFrame, results["group_returns"])),
        "pit_eligibility.parquet": _parquet(signals.eligibility),
        "pit_quarantine.parquet": _parquet(signals.quarantined),
        "portfolio_nav.parquet": _parquet(cast(pl.DataFrame, results["portfolio_nav"])),
        "redundancy_daily.parquet": _parquet(redundancy_daily),
        "redundancy_summary.parquet": _parquet(redundancy_summary),
        "report.json": canonical_json_bytes(report),
        "signal_coverage.parquet": _parquet(coverage),
        "targets.parquet": _parquet(cast(pl.DataFrame, results["targets"])),
    }
    folds = _folds(config)
    financial_rows = sum(rows for _, rows in financial_snapshot.dataset_rows)
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
        universe_frozen_as_of=cast(dt.date, universe["freeze_end"]),
        candidate_symbols=candidates,
        data_start=cast(dt.date, data["research_start"]),
        data_end=cast(dt.date, data["research_end"]),
        signal_timing="close",
        execution_timing="next_session_open",
        valuation_timing="close",
        folds=folds,
        cost_multipliers=tuple(float(value) for value in portfolio["cost_multipliers"]),
        selection_metric="monthly_pit_walk_forward_rank_ic_with_redundancy_gate",
        inputs=(
            ResearchInputDigestV1(
                name="tushare-daily-basic",
                rows=daily_snapshot.rows,
                min_date=cast(dt.date, data["research_start"]),
                max_date=cast(dt.date, data["research_end"]),
                content_sha256=daily_snapshot.manifest_sha256,
            ),
            ResearchInputDigestV1(
                name="tushare-financials",
                rows=financial_rows,
                min_date=history_start,
                max_date=history_end,
                content_sha256=financial_snapshot.manifest_sha256,
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
            ("factor_count", len(PIT_QUALITY_FACTOR_NAMES)),
            ("panel_rows", panel.height),
            ("passing_factor_count", passing.height),
            ("pit_eligibility_rows", signals.eligibility.height),
            ("quarantine_rows", signals.quarantined.height),
            ("signal_dates", len(signal_dates)),
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


def build_pit_quality_panel(
    *,
    signal_values: pl.DataFrame,
    daily_basic: pl.DataFrame,
    bars: pl.DataFrame,
    sessions: tuple[dt.date, ...],
    horizons: tuple[int, ...] = (1, 5, 20),
) -> pl.DataFrame:
    """Join sparse PIT signals to controls and two honest open-return labels."""
    required = {
        "symbol",
        "trade_date",
        "financial_period_end",
        *PIT_QUALITY_FACTOR_NAMES,
    }
    if (
        not isinstance(signal_values, pl.DataFrame)
        or signal_values.is_empty()
        or not required <= set(signal_values.columns)
        or signal_values.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item()
    ):
        raise ValueError("invalid PIT quality signal values")
    classic = compute_classic_daily_factors(bars)
    daily = compute_daily_value_factors(daily_basic)
    if daily.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("daily-basic controls contain duplicate symbol-date keys")
    controls = classic.select(
        "symbol",
        "trade_date",
        "history_rows",
        "liquidity_20",
        *CLASSIC_FACTOR_NAMES,
    ).join(
        daily.select(
            "symbol",
            "trade_date",
            *DAILY_VALUE_FACTOR_NAMES,
            "log_total_market_value",
        ),
        on=["symbol", "trade_date"],
        how="left",
        validate="1:1",
    )
    values = signal_values.join(
        controls,
        on=["symbol", "trade_date"],
        how="inner",
        validate="1:1",
    )
    if values.is_empty():
        raise ValueError("PIT signals do not overlap verified market controls")
    fixed_horizon = build_next_open_factor_labels(
        factor_values=values,
        bars=bars,
        sessions=sessions,
        horizons=horizons,
    )
    return build_next_rebalance_open_labels(
        factor_values=fixed_horizon,
        bars=bars,
        sessions=sessions,
    )


def build_pit_quality_coverage(eligibility: pl.DataFrame) -> pl.DataFrame:
    """Reconcile mutually exclusive eligibility reasons by month and factor."""
    required = {
        "as_of",
        "symbol",
        "factor",
        "financial_period_end",
        "status",
    }
    if (
        not isinstance(eligibility, pl.DataFrame)
        or eligibility.is_empty()
        or not required <= set(eligibility.columns)
        or eligibility.select(pl.struct("as_of", "symbol", "factor").is_duplicated().any()).item()
    ):
        raise ValueError("PIT quality eligibility is invalid")
    result = (
        eligibility.group_by("as_of", "factor")
        .agg(
            pl.len().alias("eligible_rows"),
            (pl.col("status") == "VALID").sum().alias("valid_rows"),
            (pl.col("status") == "MISSING_CHAIN").sum().alias("missing_chain_rows"),
            (pl.col("status") == "NON_INDUSTRIAL").sum().alias("non_industrial_rows"),
            (pl.col("status") == "INVALID_DENOMINATOR").sum().alias("invalid_denominator_rows"),
            (pl.col("status") == "QUARANTINED").sum().alias("quarantined_rows"),
            pl.col("financial_period_end").min().alias("min_period_end"),
            pl.col("financial_period_end").max().alias("max_period_end"),
        )
        .with_columns(
            (pl.col("valid_rows") / pl.col("eligible_rows")).alias("coverage"),
            (
                pl.col("valid_rows")
                + pl.col("missing_chain_rows")
                + pl.col("non_industrial_rows")
                + pl.col("invalid_denominator_rows")
                + pl.col("quarantined_rows")
            ).alias("_reconciled_rows"),
        )
        .rename({"as_of": "trade_date"})
        .sort("factor", "trade_date")
    )
    if result.filter(pl.col("eligible_rows") != pl.col("_reconciled_rows")).height:
        raise ValueError("PIT quality eligibility does not reconcile")
    return result.drop("_reconciled_rows")


def apply_pit_quality_coverage_gate(
    summary: pl.DataFrame,
    *,
    coverage: pl.DataFrame,
    signal_dates: tuple[dt.date, ...],
    minimum_signal_symbols: int,
    minimum_median_signal_coverage: float,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Reject factors whose complete pre-registered signal calendar lacks usable rows."""
    required = (
        "factor",
        "trade_date",
        "eligible_rows",
        "valid_rows",
        "missing_chain_rows",
        "non_industrial_rows",
        "invalid_denominator_rows",
        "quarantined_rows",
        "coverage",
        "min_period_end",
        "max_period_end",
    )
    if (
        not isinstance(summary, pl.DataFrame)
        or summary.is_empty()
        or not {"factor", "research_status"} <= set(summary.columns)
        or summary.get_column("factor").n_unique() != summary.height
        or not isinstance(coverage, pl.DataFrame)
        or not set(required) <= set(coverage.columns)
        or signal_dates != tuple(sorted(signal_dates))
        or len(signal_dates) != len(set(signal_dates))
        or not signal_dates
        or any(type(value) is not dt.date for value in signal_dates)
        or type(minimum_signal_symbols) is not int
        or minimum_signal_symbols < 2
        or type(minimum_median_signal_coverage) is not float
        or not 0 < minimum_median_signal_coverage <= 1
        or (
            not coverage.is_empty()
            and coverage.select(pl.struct("factor", "trade_date").is_duplicated().any()).item()
        )
    ):
        raise ValueError("invalid PIT quality coverage gate")
    factors = tuple(sorted(cast(list[str], summary.get_column("factor").to_list())))
    if coverage.filter(
        ~pl.col("factor").is_in(factors) | ~pl.col("trade_date").is_in(signal_dates)
    ).height:
        raise ValueError("PIT quality coverage is outside the pre-registered calendar")
    expected = pl.DataFrame(
        {
            "factor": [factor for factor in factors for _ in signal_dates],
            "trade_date": [date for _ in factors for date in signal_dates],
        },
        schema={"factor": pl.String(), "trade_date": pl.Date()},
    )
    count_columns = (
        "eligible_rows",
        "valid_rows",
        "missing_chain_rows",
        "non_industrial_rows",
        "invalid_denominator_rows",
        "quarantined_rows",
    )
    completed = (
        expected.join(
            coverage.select(*required),
            on=["factor", "trade_date"],
            how="left",
            validate="1:1",
        )
        .with_columns(
            *(pl.col(name).fill_null(0).alias(name) for name in count_columns),
            pl.col("coverage").fill_null(0.0).alias("coverage"),
            pl.lit(minimum_signal_symbols).alias("minimum_signal_symbols"),
        )
        .with_columns(
            (pl.col("valid_rows") >= minimum_signal_symbols).alias(
                "daily_minimum_signal_symbols_passed"
            )
        )
        .sort("factor", "trade_date")
    )
    gate = (
        completed.group_by("factor")
        .agg(
            pl.len().alias("expected_signal_dates"),
            pl.col("valid_rows").min().alias("minimum_valid_signal_symbols"),
            pl.col("coverage").median().alias("median_signal_coverage"),
            pl.col("daily_minimum_signal_symbols_passed")
            .all()
            .alias("all_signal_dates_have_minimum_symbols"),
        )
        .with_columns(
            (
                pl.col("all_signal_dates_have_minimum_symbols")
                & (pl.col("median_signal_coverage") >= minimum_median_signal_coverage)
            ).alias("pit_signal_coverage_passed"),
            pl.lit(minimum_median_signal_coverage).alias(
                "minimum_median_signal_coverage"
            ),
        )
    )
    gated = summary.join(gate, on="factor", how="left", validate="1:1").with_columns(
        pl.when(
            (pl.col("research_status") == "RESEARCH_ONLY")
            & pl.col("pit_signal_coverage_passed").fill_null(False)
        )
        .then(pl.lit("RESEARCH_ONLY"))
        .otherwise(pl.lit("REJECTED"))
        .alias("research_status")
    )
    return gated.sort("factor"), completed


def attach_redundancy_signal_coverage(
    summary: pl.DataFrame,
    *,
    expected_signal_dates: int,
    minimum_coverage: float,
) -> pl.DataFrame:
    """Bind every redundancy pair to the complete pre-registered signal calendar."""
    if (
        not isinstance(summary, pl.DataFrame)
        or summary.is_empty()
        or not {"factor_a", "factor_b", "dates"} <= set(summary.columns)
        or type(expected_signal_dates) is not int
        or expected_signal_dates <= 0
        or not 0 < minimum_coverage <= 1
        or summary.filter((pl.col("dates") <= 0) | (pl.col("dates") > expected_signal_dates)).height
    ):
        raise ValueError("invalid redundancy signal coverage")
    return summary.with_columns(
        pl.lit(expected_signal_dates).alias("expected_signal_dates"),
        pl.col("dates").alias("valid_signal_dates"),
        (pl.col("dates") / expected_signal_dates).alias("signal_date_coverage"),
        (pl.col("dates") / expected_signal_dates >= minimum_coverage).alias(
            "signal_date_coverage_passed"
        ),
    ).sort("factor_a", "factor_b")


def apply_redundancy_signal_coverage_gate(
    summary: pl.DataFrame,
    *,
    redundancy_summary: pl.DataFrame,
) -> pl.DataFrame:
    """Reject a factor when any pre-registered redundancy pair lacks dates."""
    if (
        not isinstance(summary, pl.DataFrame)
        or summary.is_empty()
        or not {"factor", "research_status"} <= set(summary.columns)
        or not isinstance(redundancy_summary, pl.DataFrame)
        or redundancy_summary.is_empty()
        or not {"factor_a", "signal_date_coverage_passed"} <= set(redundancy_summary.columns)
    ):
        raise ValueError("invalid redundancy signal coverage gate")
    by_factor = redundancy_summary.group_by("factor_a").agg(
        pl.col("signal_date_coverage_passed").all().alias("redundancy_signal_coverage_passed")
    )
    result = summary.join(
        by_factor,
        left_on="factor",
        right_on="factor_a",
        how="left",
        validate="1:1",
    ).with_columns(
        pl.col("redundancy_signal_coverage_passed")
        .fill_null(False)
        .alias("redundancy_signal_coverage_passed")
    )
    return result.with_columns(
        pl.when(
            (pl.col("research_status") == "RESEARCH_ONLY")
            & pl.col("redundancy_signal_coverage_passed")
        )
        .then(pl.lit("RESEARCH_ONLY"))
        .otherwise(pl.lit("REJECTED"))
        .alias("research_status")
    ).sort("factor")


def _validate_config(config: Mapping[str, Any], *, threads: int) -> None:
    try:
        data = cast(Mapping[str, Any], config["data"])
        factors = cast(Mapping[str, Any], config["factors"])
        portfolio = cast(Mapping[str, Any], config["portfolio"])
        dates = (
            data["financial_history_start"],
            data["warmup_start"],
            data["research_start"],
            data["research_end"],
        )
        valid = (
            type(data["bar_snapshot_id"]) is str
            and len(cast(str, data["bar_snapshot_id"])) == 64
            and set(cast(str, data["bar_snapshot_id"])) <= set("0123456789abcdef")
            and all(type(value) is dt.date for value in dates)
            and cast(dt.date, data["financial_history_start"])
            <= cast(dt.date, data["warmup_start"])
            < cast(dt.date, data["research_start"])
            <= cast(dt.date, data["research_end"])
            and tuple(cast(list[str], factors["names"])) == PIT_QUALITY_FACTOR_NAMES
            and factors["catalog"] == "tushare_pit_quality_v1"
            and factors["report_type_freeze_status"] == "FROZEN"
            and tuple(cast(list[str], factors["allowed_report_types"]))
            == tuple(sorted(cast(list[str], factors["allowed_report_types"])))
            and len(cast(list[str], factors["allowed_report_types"])) > 0
            and len(set(cast(list[str], factors["allowed_report_types"])))
            == len(cast(list[str], factors["allowed_report_types"]))
            and all(
                type(value) is str and value.isdigit()
                for value in cast(list[object], factors["allowed_report_types"])
            )
            and tuple(cast(list[str], factors["redundancy_reference_names"])) == _REFERENCE_FACTORS
            and float(factors["maximum_median_absolute_rank_correlation"]) == 0.80
            and float(factors["minimum_redundancy_signal_coverage"]) == 1.0
            and float(factors["minimum_median_signal_coverage"]) == 0.80
            and tuple(cast(list[int], factors["horizons"])) == (1, 5, 20)
            and factors["newey_west_lag"] == 1
            and tuple(float(value) for value in portfolio["cost_multipliers"]) == (0.5, 1.0, 2.0)
            and portfolio["rebalance_every_signals"] == 1
            and float(portfolio["annualization_periods"]) == 12.0
            and type(threads) is int
            and 1 <= threads <= 2
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("invalid PIT-quality-factor config")


def _report(
    *,
    config: Mapping[str, Any],
    bar_snapshot_id: str,
    bar_manifest_sha256: str,
    daily_snapshot_id: str,
    daily_manifest_sha256: str,
    financial_snapshot_id: str,
    financial_manifest_sha256: str,
    financial_dataset_rows: tuple[tuple[str, int], ...],
    candidates: tuple[str, ...],
    signal_dates: tuple[dt.date, ...],
    panel: pl.DataFrame,
    eligibility: pl.DataFrame,
    quarantined: pl.DataFrame,
    results: Mapping[str, pl.DataFrame],
    summary: pl.DataFrame,
    conclusion: str,
) -> dict[str, object]:
    return {
        "schema_version": "m2-pit-quality-factor-report-v1",
        "conclusion": conclusion,
        "hypothesis": config["research"]["hypothesis"],
        "bar_snapshot_id": bar_snapshot_id,
        "bar_manifest_sha256": bar_manifest_sha256,
        "daily_basic_snapshot_id": daily_snapshot_id,
        "daily_basic_manifest_sha256": daily_manifest_sha256,
        "financial_snapshot_id": financial_snapshot_id,
        "financial_manifest_sha256": financial_manifest_sha256,
        "financial_dataset_rows": dict(financial_dataset_rows),
        "candidate_symbol_count": len(candidates),
        "signal_date_count": len(signal_dates),
        "first_signal_date": signal_dates[0],
        "last_signal_date": signal_dates[-1],
        "panel_rows": panel.height,
        "eligibility_rows": eligibility.height,
        "eligibility_summary": (
            eligibility.group_by("factor", "status").len().sort("factor", "status").to_dicts()
        ),
        "quarantine_rows": quarantined.height,
        "quarantine_summary": (
            quarantined.group_by("dataset", "quarantine_reason")
            .len()
            .sort("dataset", "quarantine_reason")
            .to_dicts()
            if not quarantined.is_empty()
            else []
        ),
        "daily_ic_rows": results["daily_ic"].height,
        "target_rows": results["targets"].height,
        "factor_summary": summary.to_dicts(),
        "redundancy_summary": results["redundancy_summary"].to_dicts(),
        "timing": {
            "signal": "proven exchange month-end close; available_date must be earlier",
            "execution": "next exchange session open",
            "ic_label": "adjusted open(t+1+h)/adjusted open(t+1)-1",
            "portfolio_label": "current next-open to next month-end signal next-open",
        },
        "caveats": [
            "The 2019 liquid universe is frozen rather than an evolving PIT constituent universe.",
            "A truncated final calendar month is excluded because it is not a proven month end.",
            "Historical industry classifications and explicit industry-neutral portfolios are unavailable.",
            "Daily-basic and price-volume controls measure redundancy but do not replace the statement formulas.",
            "fina_indicator supplier cross-check is NOT_EVALUATED in v1 and cannot alter canonical factors.",
            "The monthly portfolio is a factor diagnostic, not the formal A-share account replay.",
            "Historical ST flags and complete market-event replay remain outside this research run.",
            "No result may exceed RESEARCH_ONLY without post-freeze forward and market-event evidence.",
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
