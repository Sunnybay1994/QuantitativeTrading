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
    CLASSIC_FACTOR_NAMES,
    DAILY_VALUE_FACTOR_NAMES,
    DAILY_VALUE_FACTOR_SPECS,
    compute_classic_daily_factors,
    compute_daily_value_factors,
)
from quant.research.classic_factor_evaluation import evaluate_factor_redundancy
from quant.research.factor_labels import build_next_open_factor_labels
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
from quant.settings import resolve_data_root

_REFERENCE_FACTORS = CLASSIC_FACTOR_NAMES + ("log_total_market_value",)
_CODE_PATHS = (
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
    panel = build_daily_value_panel(
        daily_basic=daily_basic,
        bars=bars,
        sessions=sessions,
        horizons=tuple(cast(list[int], factors["horizons"])),
    ).filter(
        (pl.col("trade_date") >= cast(dt.date, data["research_start"]))
        & (pl.col("history_rows") >= cast(int, factors["minimum_history_rows"]))
        & (pl.col("liquidity_20") >= float(universe["minimum_average_amount"]))
    )
    if panel.is_empty():
        raise ValueError("daily-value panel is empty")

    results = evaluate_walk_forward(
        panel=panel,
        factors=DAILY_VALUE_FACTOR_NAMES,
        horizons=tuple(cast(list[int], factors["horizons"])),
        folds=_folds(config),
        minimum_symbols=cast(int, factors["minimum_daily_symbols"]),
        groups=cast(int, factors["groups"]),
        top_k=cast(int, portfolio["top_k"]),
        rebalance_every=cast(int, portfolio["rebalance_every_sessions"]),
        initial_cash=Decimal(str(portfolio["initial_cash"])),
        cost_multipliers=tuple(
            Decimal(str(value)) for value in portfolio["cost_multipliers"]
        ),
        costs=_cost_periods(project_root, portfolio),
        strategy_name=cast(str, config["research"]["strategy_name"]),
        strategy_version=cast(str, config["research"]["strategy_version"]),
    )
    summary = summarize_factors(
        cast(pl.DataFrame, results["fold_metrics"]),
        factors=DAILY_VALUE_FACTOR_NAMES,
        admission=cast(Mapping[str, Any], config["admission"]),
    )
    redundancy_daily, redundancy_summary = evaluate_factor_redundancy(
        panel,
        factors=DAILY_VALUE_FACTOR_NAMES,
        reference_factors=_REFERENCE_FACTORS,
        start_date=cast(dt.date, data["research_start"]),
        end_date=cast(dt.date, data["research_end"]),
        minimum_symbols=cast(int, factors["minimum_daily_symbols"]),
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
    coverage = build_daily_value_coverage(panel)
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
    )
    outputs = {
        "daily_ic.parquet": _parquet(cast(pl.DataFrame, results["daily_ic"])),
        "daily_value_coverage.parquet": _parquet(coverage),
        "factor_catalog.json": canonical_json_bytes(
            [
                {
                    "mechanism": spec.mechanism,
                    "missing_rule": spec.missing_rule,
                    "name": spec.name,
                    "source": spec.source,
                }
                for spec in DAILY_VALUE_FACTOR_SPECS
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
        selection_metric="walk_forward_rank_ic_with_redundancy_gate",
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
            ("factor_count", len(DAILY_VALUE_FACTOR_NAMES)),
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


def build_daily_value_coverage(panel: pl.DataFrame) -> pl.DataFrame:
    """Return deterministic per-date coverage for every pre-registered proxy."""
    if not isinstance(panel, pl.DataFrame) or panel.is_empty():
        raise ValueError("daily-value coverage panel is empty")
    frames: list[pl.DataFrame] = []
    for factor in DAILY_VALUE_FACTOR_NAMES:
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
    maxima = redundancy_summary.group_by("factor_a").agg(
        pl.col("median_abs_rank_corr").max().alias("max_median_abs_rank_corr")
    )
    return (
        summary.join(
            maxima,
            left_on="factor",
            right_on="factor_a",
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


def _validate_config(config: Mapping[str, Any], *, threads: int) -> None:
    try:
        data = cast(Mapping[str, Any], config["data"])
        factors = cast(Mapping[str, Any], config["factors"])
        portfolio = cast(Mapping[str, Any], config["portfolio"])
        valid = (
            type(data["bar_snapshot_id"]) is str
            and len(cast(str, data["bar_snapshot_id"])) == 64
            and set(cast(str, data["bar_snapshot_id"]))
            <= set("0123456789abcdef")
            and tuple(cast(list[str], factors["names"]))
            == DAILY_VALUE_FACTOR_NAMES
            and factors["catalog"] == "tushare_daily_basic_value_proxy_v1"
            and tuple(cast(list[str], factors["redundancy_reference_names"]))
            == _REFERENCE_FACTORS
            and float(factors["maximum_median_absolute_rank_correlation"]) == 0.80
            and tuple(cast(list[int], factors["horizons"])) == (1, 5, 20)
            and tuple(float(value) for value in portfolio["cost_multipliers"])
            == (0.5, 1.0, 2.0)
            and portfolio["selection_horizon_sessions"] == 20
            and type(threads) is int
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
) -> dict[str, object]:
    return {
        "schema_version": "m2-daily-value-factor-report-v1",
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
            "signal": "daily_basic row available after close of as_of session",
            "execution": "next exchange session open from verified stock bars",
            "label": "adjusted open(t+1+h)/adjusted open(t+1)-1",
        },
        "caveats": [
            "Daily-basic ratios are vendor daily proxies, not reconstructed PIT financial-statement factors.",
            "The 2019 liquid universe is PIT only at its freeze date and is not an evolving constituent universe.",
            "Daily-basic close is never used as the bar, label, execution or valuation authority.",
            "Loss-making and non-positive denominator observations are null by the frozen factor formulas.",
            "Historical ST flags, industries and full market-event replay are not available in this diagnostic.",
            "The twenty-session portfolio is a factor diagnostic, not the formal A-share account replay.",
            "No result may exceed RESEARCH_ONLY without separate financial PIT, forward and market-event evidence.",
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
