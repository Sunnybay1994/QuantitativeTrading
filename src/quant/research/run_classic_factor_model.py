"""Run the pre-registered M2 five-factor LightGBM experiment."""

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
from quant.factors import (
    compute_classic_daily_factors,
    compute_second_batch_daily_factors,
)
from quant.research.classic_factor_model import (
    MODEL_FEATURES,
    MODEL_SCORE,
    ClassicFactorLightgbmSpec,
    evaluate_lightgbm_walk_forward,
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
    "src/quant/factors/classic_second_batch.py",
    "src/quant/portfolio/selection.py",
    "src/quant/research/classic_factor_composite.py",
    "src/quant/research/classic_factor_evaluation.py",
    "src/quant/research/classic_factor_model.py",
    "src/quant/research/factor_labels.py",
    "src/quant/research/lightweight_run.py",
    "src/quant/research/run_classic_factor_model.py",
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 M2 五因子 LightGBM 研究")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/research/m2_classic_factor_lightgbm.toml"),
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
    features = cast(Mapping[str, Any], config["features"])
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
    first = compute_classic_daily_factors(bars)
    second = compute_second_batch_daily_factors(bars)
    factor_values = first.join(
        second.select(
            "symbol",
            "trade_date",
            "alpha158_corr20",
            "alpha158_wvma20",
        ),
        on=["symbol", "trade_date"],
        how="inner",
        validate="1:1",
    )
    sessions = tuple(sorted(set(bars.get_column("trade_date").to_list())))
    panel = build_next_open_factor_labels(
        factor_values=factor_values,
        bars=bars,
        sessions=sessions,
        horizons=(1, 5, 20),
    ).filter(
        (pl.col("trade_date") >= cast(dt.date, data["research_start"]))
        & (pl.col("history_rows") >= cast(int, features["minimum_history_rows"]))
        & (
            pl.col("liquidity_20")
            >= float(universe["minimum_average_amount"])
        )
    )
    risk_symbol = cast(str, risk["benchmark"])
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
    folds = _folds(config)
    model_spec = _model_spec(config)
    cost_periods = _cost_periods(project_root, portfolio)
    results, models = evaluate_lightgbm_walk_forward(
        panel=panel,
        folds=folds,
        spec=model_spec,
        minimum_symbols=cast(int, features["minimum_daily_symbols"]),
        groups=cast(int, features["groups"]),
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
        factors=(MODEL_SCORE,),
        admission=cast(Mapping[str, Any], config["admission"]),
    )
    cash_period_fraction = cast(
        float,
        results["periods"].select(
            (pl.col("invested_weight") == 0).mean()
        ).item(),
    )
    if cast(bool, risk["require_zero_cash_period_fraction"]) and (
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
        gpu_probe="UNAVAILABLE_NONZERO_EXIT",
    )
    outputs = {
        "daily_ic.parquet": _parquet(results["daily_ic"]),
        "factor_summary.parquet": _parquet(summary),
        "fold_metrics.parquet": _parquet(results["fold_metrics"]),
        "group_returns.parquet": _parquet(results["group_returns"]),
        "model_metadata.parquet": _parquet(results["model_metadata"]),
        "periods.parquet": _parquet(results["periods"]),
        "portfolio_nav.parquet": _parquet(results["portfolio_nav"]),
        "predictions.parquet": _parquet(results["predictions"]),
        "report.json": canonical_json_bytes(report),
        "targets.parquet": _parquet(results["targets"]),
        **{f"model_fold_{fold}.txt": payload for fold, payload in models.items()},
    }
    mean_test_rank_ic = cast(float, summary.item(0, "mean_test_rank_ic"))
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
        selection_metric="validation_l2_early_stopping_test_rank_ic",
        inputs=_inputs(
            snapshot_manifest_sha256=snapshot.manifest_sha256,
            stock_rows=snapshot.stock_rows,
            fund_rows=snapshot.fund_rows,
            start=cast(dt.date, data["warmup_start"]),
            end=cast(dt.date, data["research_end"]),
        ),
        outputs=(),
        aggregate_metrics=(
            ("candidate_symbols", len(candidates)),
            ("cash_period_fraction", cash_period_fraction),
            ("mean_test_rank_ic", mean_test_rank_ic),
            ("model_feature_count", len(MODEL_FEATURES)),
            ("passing_model_count", passing.height),
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
                "mean_test_rank_ic": mean_test_rank_ic,
                "reused": reused,
                "root": str(root),
                "run_id": complete.run_id,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _validate_config(config: Mapping[str, Any], *, threads: int) -> None:
    features = cast(Mapping[str, Any], config["features"])
    model = cast(Mapping[str, Any], config["model"]["lightgbm"])
    risk = cast(Mapping[str, Any], config["risk_control"])
    portfolio = cast(Mapping[str, Any], config["portfolio"])
    if (
        tuple(cast(list[str], features["names"])) != MODEL_FEATURES
        or tuple(cast(list[str], features["excluded_redundant_names"]))
        != ("alpha158_ma20",)
        or features["transform"]
        != "daily_cross_sectional_average_rank_centered"
        or features["label_horizon_sessions"] != 20
        or model["model_version"] != "m2_classic_five_factor_lgb_v1"
        or model["device_type"] != "cpu"
        or model["deterministic"] is not True
        or model["force_col_wise"] is not True
        or model["num_threads"] != 4
        or risk["method"] != "unlevered_benchmark_volatility_target"
        or risk["benchmark"] != "510300.SH"
        or risk["lookback_observations"] != 60
        or float(risk["annualized_volatility"]) != 0.12
        or risk["annualization_sessions"] != 252
        or risk["require_zero_cash_period_fraction"] is not True
        or portfolio["selection_horizon_sessions"] != 20
        or tuple(float(value) for value in portfolio["cost_multipliers"])
        != (0.5, 1.0, 2.0)
        or type(threads) is not int
        or not 1 <= threads <= 4
    ):
        raise ValueError("invalid classic-factor LightGBM config")
    _model_spec(config)


def _model_spec(config: Mapping[str, Any]) -> ClassicFactorLightgbmSpec:
    row = cast(Mapping[str, Any], config["model"]["lightgbm"])
    return ClassicFactorLightgbmSpec(
        objective=cast(str, row["objective"]),
        metric=cast(str, row["metric"]),
        device_type=cast(str, row["device_type"]),
        learning_rate=float(row["learning_rate"]),
        num_leaves=cast(int, row["num_leaves"]),
        max_depth=cast(int, row["max_depth"]),
        feature_fraction=float(row["feature_fraction"]),
        bagging_fraction=float(row["bagging_fraction"]),
        bagging_freq=cast(int, row["bagging_freq"]),
        num_boost_round=cast(int, row["num_boost_round"]),
        early_stopping_rounds=cast(int, row["early_stopping_rounds"]),
        seed=cast(int, row["seed"]),
        num_threads=cast(int, row["num_threads"]),
    )


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


def _report(
    *,
    config: Mapping[str, Any],
    snapshot_manifest_sha256: str,
    candidates: tuple[str, ...],
    panel: pl.DataFrame,
    results: Mapping[str, pl.DataFrame],
    summary: pl.DataFrame,
    conclusion: str,
    gpu_probe: str,
) -> dict[str, object]:
    return {
        "schema_version": "m2-classic-factor-lightgbm-report-v1",
        "conclusion": conclusion,
        "hypothesis": config["research"]["hypothesis"],
        "snapshot_id": config["data"]["snapshot_id"],
        "snapshot_manifest_sha256": snapshot_manifest_sha256,
        "candidate_symbol_count": len(candidates),
        "panel_rows": panel.height,
        "features": list(MODEL_FEATURES),
        "model_metadata": results["model_metadata"].to_dicts(),
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
        "resources": {
            "model_device": "cpu",
            "model_threads": 4,
            "gpu_probe": gpu_probe,
        },
        "timing": {
            "signal": "close of as_of session",
            "execution": "next exchange session open",
            "label": "adjusted open(t+21)/adjusted open(t+1)-1",
            "selection": "validation l2 early stopping; test exactly once",
        },
        "caveats": [
            "The five features were chosen after observing earlier test results, so this is not an independent final holdout.",
            "The 2019 liquid universe is PIT at its freeze date but is not an evolving historical constituent universe.",
            "Historical ST flags, industry membership and authoritative suspension facts are unavailable in this snapshot.",
            "Missing exact next-session opens produce null labels and are never forward-filled.",
            "The non-overlapping portfolio is a factor diagnostic, not the formal A-share account replay.",
            "The 510300 volatility target uses signal-date-known closes, only reduces exposure, and assigns zero return to cash.",
            "The Windows LightGBM GPU probe exited nonzero; this run uses deterministic CPU training with four threads.",
            "No result from this run may exceed RESEARCH_ONLY or alter the frozen forward candidate.",
        ],
    }


def _inputs(
    *,
    snapshot_manifest_sha256: str,
    stock_rows: int,
    fund_rows: int,
    start: dt.date,
    end: dt.date,
) -> tuple[ResearchInputDigestV1, ...]:
    return (
        ResearchInputDigestV1(
            name="tushare-fund-bars",
            rows=fund_rows,
            min_date=start,
            max_date=end,
            content_sha256=snapshot_manifest_sha256,
        ),
        ResearchInputDigestV1(
            name="tushare-stock-bars",
            rows=stock_rows,
            min_date=start,
            max_date=end,
            content_sha256=snapshot_manifest_sha256,
        ),
    )


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
