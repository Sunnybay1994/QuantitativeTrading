"""Publish one source-bound, research-only M2 forward target run."""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import hashlib
import io
import json
import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, Sequence, cast

import polars as pl

from quant.backtest import schedule_next_trading_day
from quant.data.m2_forward_source_repository import (
    M2ForwardSourceSlice,
    load_m2_forward_source_slice,
)
from quant.domain import TargetWeightSchema, TradeCalendarSchema
from quant.factors import compute_trend_factors_from_prices
from quant.portfolio import scale_target_weights_to_volatility
from quant.research.lightweight_run import (
    LightweightResearchRunV1,
    ResearchInputDigestV1,
    canonical_json_bytes,
    compute_code_sha256,
    dataframe_input_digest,
    publish_lightweight_research_run,
    verify_lightweight_research_run,
)
from quant.settings import resolve_data_root
from quant.strategies import RegimeFilteredEtfTrendStrategy

_EXPECTED_ARTIFACT_KIND = "non_deploying_forward_observation"
_EXPECTED_CONCLUSION = "RESEARCH_ONLY"
_SOURCE_BINDING_SCHEMA = "m2-forward-source-binding-v1"
_CODE_PATHS = (
    "src/quant/backtest/timing.py",
    "src/quant/data/m2_forward_source_repository.py",
    "src/quant/factors/trend.py",
    "src/quant/portfolio/selection.py",
    "src/quant/research/lightweight_run.py",
    "src/quant/research/run_s2_forward_observation.py",
    "src/quant/strategies/baselines.py",
)


class M2ForwardObservationError(ValueError):
    """Stable, path-free failure for an invalid forward publication request."""


def _invalid_observation() -> NoReturn:
    raise M2ForwardObservationError("M2_FORWARD_OBSERVATION_INVALID") from None


@dataclass(frozen=True, slots=True)
class _ForwardSpec:
    source_run_id: str
    source_config_relative_path: str
    source_config_sha256: str
    candidate_frozen_date: dt.date
    first_eligible_signal_date: dt.date
    selected_top_k: int
    selected_regression_window: int
    candidate_symbols: tuple[str, ...]
    data_start: dt.date
    minimum_history_observations: int


def main(argv: Sequence[str] | None = None) -> int:
    """Build a standard research-only run for one completed forward month-end."""
    parser = argparse.ArgumentParser(description="生成 M2 冻结候选的标准前向目标 run")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/research/m2_s2_volatility_target_forward.toml"),
    )
    parser.add_argument("--source-run-root", type=Path, required=True)
    parser.add_argument("--as-of", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument("--project-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    project_root = args.project_root.resolve(strict=True)
    config_path = _inside(project_root, args.config)
    data_root = resolve_data_root(args.data_root, base=project_root)
    artifact_root = args.artifact_root
    if not artifact_root.is_absolute():
        artifact_root = project_root / artifact_root
    root, run, reused = publish_forward_research_run(
        project_root=project_root,
        artifact_root=artifact_root,
        config_path=config_path,
        source_run_root=args.source_run_root,
        data_root=data_root,
        as_of=args.as_of,
    )
    print(
        json.dumps(
            {
                "path": root.relative_to(project_root).as_posix(),
                "reused": reused,
                "run_id": run.run_id,
                "status": run.conclusion,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def publish_forward_research_run(
    *,
    project_root: Path,
    artifact_root: Path,
    config_path: Path,
    source_run_root: Path,
    data_root: Path,
    as_of: dt.date,
) -> tuple[Path, LightweightResearchRunV1, bool]:
    """Freshly bind source evidence and publish one standard immutable run."""
    failed = False
    result: tuple[Path, LightweightResearchRunV1, bool] | None = None
    try:
        result = _publish_forward_research_run(
            project_root=project_root,
            artifact_root=artifact_root,
            config_path=config_path,
            source_run_root=source_run_root,
            data_root=data_root,
            as_of=as_of,
        )
    except Exception:
        failed = True
    if failed or result is None:
        _invalid_observation()
    return result


def _publish_forward_research_run(
    *,
    project_root: Path,
    artifact_root: Path,
    config_path: Path,
    source_run_root: Path,
    data_root: Path,
    as_of: dt.date,
) -> tuple[Path, LightweightResearchRunV1, bool]:
    if (
        not isinstance(project_root, Path)
        or not isinstance(artifact_root, Path)
        or not isinstance(config_path, Path)
        or not isinstance(source_run_root, Path)
        or not isinstance(data_root, Path)
        or type(as_of) is not dt.date
    ):
        raise ValueError("invalid forward inputs")
    root = _anchored_directory(project_root)
    forward_path = _inside(root, config_path)
    forward_payload = _read_stable_file(forward_path)
    config = _parse_toml(forward_payload)
    spec = _validate_config(config=config, as_of=as_of)
    config_relative_path = forward_path.relative_to(root).as_posix()
    forward_config_sha256 = hashlib.sha256(forward_payload).hexdigest()

    source_root = Path(os.path.abspath(source_run_root))
    source_run = verify_lightweight_research_run(run_root=source_root)
    if source_run.run_id != spec.source_run_id:
        raise ValueError("source run id mismatch")
    source_manifest_payload = _read_stable_file(source_root / "run.json")
    source_config_path = _inside(root, Path(spec.source_config_relative_path))
    source_config_payload = _read_stable_file(source_config_path)
    source_config_sha256 = hashlib.sha256(source_config_payload).hexdigest()
    if (
        source_run.config_relative_path != spec.source_config_relative_path
        or source_run.config_sha256 != spec.source_config_sha256
        or source_config_sha256 != spec.source_config_sha256
    ):
        raise ValueError("source config mismatch")
    _require_source_compatibility(source_run=source_run, config=config, spec=spec)

    report_descriptor = next(
        (
            output
            for output in source_run.outputs
            if output.relative_path == "report.json"
        ),
        None,
    )
    if report_descriptor is None:
        raise ValueError("source report missing")
    source_report_path = source_root / "report.json"
    source_report_payload = _read_stable_file(source_report_path)
    selected_parameters = _validate_source_report(
        payload=source_report_payload,
        expected_size=report_descriptor.size_bytes,
        expected_sha256=report_descriptor.sha256,
        source_run=source_run,
        spec=spec,
    )

    source_slice = load_m2_forward_source_slice(
        data_root=data_root,
        candidate_symbols=spec.candidate_symbols,
        data_start=spec.data_start,
        as_of=as_of,
    )
    calendars = TradeCalendarSchema.validate(source_slice.calendars).sort(
        "market", "date"
    )
    next_common_open = _require_complete_month_and_next_open(calendars, as_of)
    prices = _validated_prices(
        prices=source_slice.prices,
        candidates=spec.candidate_symbols,
        as_of=as_of,
        minimum_observations=spec.minimum_history_observations,
    )
    target_weights, scheduled_targets = _build_targets(
        config=config,
        candidates=spec.candidate_symbols,
        prices=prices,
        calendars=calendars,
        as_of=as_of,
    )
    _validate_targets(
        targets=target_weights,
        scheduled=scheduled_targets,
        next_common_open=next_common_open,
    )

    calendar_input = dataframe_input_digest(
        name="calendars",
        frame=calendars,
        sort_by=("market", "date"),
        date_column="date",
    )
    price_input = dataframe_input_digest(
        name="research-prices",
        frame=prices,
        sort_by=("trade_date", "symbol"),
        date_column="trade_date",
    )
    _require_receipt_inputs(
        source_slice=source_slice,
        calendar_input=calendar_input,
        price_input=price_input,
    )
    source_manifest_sha256 = hashlib.sha256(source_manifest_payload).hexdigest()
    source_report_sha256 = hashlib.sha256(source_report_payload).hexdigest()
    source_receipt_sha256 = hashlib.sha256(source_slice.source_receipt).hexdigest()
    inputs = tuple(
        sorted(
            (
                calendar_input,
                price_input,
                ResearchInputDigestV1(
                    "source-config", 1, None, None, source_config_sha256
                ),
                ResearchInputDigestV1(
                    "source-data-receipt", 1, None, None, source_receipt_sha256
                ),
                ResearchInputDigestV1(
                    "source-report", 1, None, None, source_report_sha256
                ),
                ResearchInputDigestV1(
                    "source-run-manifest", 1, None, None, source_manifest_sha256
                ),
            ),
            key=lambda item: item.name,
        )
    )

    target_payload = _parquet_bytes(target_weights)
    scheduled_payload = _parquet_bytes(scheduled_targets)
    binding_payload = canonical_json_bytes(
        {
            "forward_as_of": as_of,
            "schema_version": _SOURCE_BINDING_SCHEMA,
            "source_conclusion": source_run.conclusion,
            "source_config_relative_path": source_run.config_relative_path,
            "source_config_sha256": source_run.config_sha256,
            "source_data_receipt_sha256": source_receipt_sha256,
            "source_last_fold": source_run.folds[-1].fold,
            "source_report_relative_path": "report.json",
            "source_report_sha256": source_report_sha256,
            "source_run_id": source_run.run_id,
            "source_run_manifest_sha256": source_manifest_sha256,
            "source_selected_parameters": selected_parameters,
            "source_selection_metric": source_run.selection_metric,
            "source_snapshot_id": source_slice.source_snapshot_id,
        }
    )
    execution_dates = scheduled_targets.get_column("execution_date").unique()
    positive_count = target_weights.filter(pl.col("weight") > 0).height
    target_weight_sum = float(target_weights.get_column("weight").sum())
    run = LightweightResearchRunV1(
        schema_version="lightweight-research-run-v1",
        run_id="",
        hypothesis_id=source_run.hypothesis_id,
        hypothesis=source_run.hypothesis,
        strategy_name=source_run.strategy_name,
        strategy_version=source_run.strategy_version,
        conclusion="RESEARCH_ONLY",
        random_seed=source_run.random_seed,
        config_relative_path=config_relative_path,
        config_sha256=forward_config_sha256,
        code_sha256=compute_code_sha256(
            project_root=root, relative_paths=_CODE_PATHS
        ),
        universe_name=source_run.universe_name,
        universe_frozen_as_of=source_run.universe_frozen_as_of,
        candidate_symbols=source_run.candidate_symbols,
        data_start=spec.data_start,
        data_end=as_of,
        signal_timing="close",
        execution_timing="next_session_open",
        valuation_timing="close",
        folds=source_run.folds,
        cost_multipliers=source_run.cost_multipliers,
        selection_metric=source_run.selection_metric,
        inputs=inputs,
        outputs=(),
        aggregate_metrics=(
            ("forward_execution_session_count", len(execution_dates)),
            ("forward_positive_symbol_count", positive_count),
            ("forward_target_count", target_weights.height),
            ("forward_target_weight_sum", target_weight_sum),
        ),
        caveats=source_run.caveats
        + (
            "Source folds, costs, and selection metric are lineage only; "
            "they are not realized forward evaluation.",
            "This run contains a forward target observation and no realized "
            "return, Sharpe, or drawdown evidence.",
            "RESEARCH_ONLY does not authorize PAPER, live orders, or automated admission.",
        ),
    )
    output_payloads = {
        "scheduled_targets.parquet": scheduled_payload,
        "source_binding.json": binding_payload,
        "source_data_receipt.json": source_slice.source_receipt,
        "target_weights.parquet": target_payload,
    }

    source_after = verify_lightweight_research_run(run_root=source_root)
    source_slice_after = load_m2_forward_source_slice(
        data_root=data_root,
        candidate_symbols=spec.candidate_symbols,
        data_start=spec.data_start,
        as_of=as_of,
    )
    if (
        source_after != source_run
        or _read_stable_file(forward_path) != forward_payload
        or _read_stable_file(source_root / "run.json") != source_manifest_payload
        or _read_stable_file(source_report_path) != source_report_payload
        or _read_stable_file(source_config_path) != source_config_payload
        or source_slice_after.source_snapshot_id != source_slice.source_snapshot_id
        or source_slice_after.source_receipt != source_slice.source_receipt
        or not source_slice_after.prices.equals(source_slice.prices)
        or not source_slice_after.calendars.equals(source_slice.calendars)
    ):
        raise ValueError("forward source changed before publication")
    return publish_lightweight_research_run(
        artifact_root=artifact_root,
        run=run,
        output_payloads=output_payloads,
    )


def _parse_toml(payload: bytes) -> dict[str, Any]:
    value = tomllib.loads(payload.decode("utf-8"))
    if type(value) is not dict:
        raise ValueError("forward config invalid")
    return cast(dict[str, Any], value)


def _validate_config(*, config: dict[str, Any], as_of: dt.date) -> _ForwardSpec:
    forward = _mapping(config.get("forward_observation"))
    if set(forward) != {
        "artifact_kind",
        "candidate_frozen_date",
        "candidate_source_config_relative_path",
        "candidate_source_config_sha256",
        "candidate_source_run_id",
        "first_eligible_signal_date",
        "selected_regression_window",
        "selected_top_k",
    }:
        raise ValueError("forward config fields mismatch")
    research = _mapping(config.get("research"))
    strategy = _mapping(_mapping(config.get("strategy")).get("etf_regime_trend"))
    data = _mapping(config.get("data"))
    candidates = _candidates(config)
    spec = _ForwardSpec(
        source_run_id=_hex64(forward["candidate_source_run_id"]),
        source_config_relative_path=_relative_path(
            forward["candidate_source_config_relative_path"]
        ),
        source_config_sha256=_hex64(forward["candidate_source_config_sha256"]),
        candidate_frozen_date=_date(forward["candidate_frozen_date"]),
        first_eligible_signal_date=_date(forward["first_eligible_signal_date"]),
        selected_top_k=_positive_int(forward["selected_top_k"]),
        selected_regression_window=_positive_int(
            forward["selected_regression_window"]
        ),
        candidate_symbols=candidates,
        data_start=_date(data.get("start_date")),
        minimum_history_observations=_positive_int(
            data.get("minimum_history_observations")
        ),
    )
    if (
        forward["artifact_kind"] != _EXPECTED_ARTIFACT_KIND
        or research.get("conclusion") != _EXPECTED_CONCLUSION
        or research.get("strategy_kind") != "etf_regime_trend"
        or strategy.get("top_k") != spec.selected_top_k
        or strategy.get("regression_window") != spec.selected_regression_window
        or as_of < spec.first_eligible_signal_date
        or as_of <= spec.candidate_frozen_date
    ):
        raise ValueError("forward candidate mismatch")
    return spec


def _require_source_compatibility(
    *,
    source_run: LightweightResearchRunV1,
    config: dict[str, Any],
    spec: _ForwardSpec,
) -> None:
    research = _mapping(config.get("research"))
    universe = _mapping(config.get("universe"))
    strategy = _mapping(_mapping(config.get("strategy")).get("etf_regime_trend"))
    backtest = _mapping(config.get("backtest"))
    walk_forward = _mapping(config.get("walk_forward"))
    data = _mapping(config.get("data"))
    cost_multipliers = tuple(walk_forward.get("cost_multipliers", ()))
    if (
        source_run.conclusion != _EXPECTED_CONCLUSION
        or source_run.hypothesis_id != research.get("hypothesis_id")
        or source_run.hypothesis != research.get("hypothesis")
        or source_run.strategy_name != research.get("strategy_kind")
        or source_run.strategy_version != research.get("strategy_version")
        or source_run.random_seed != research.get("random_seed")
        or source_run.universe_name != universe.get("name")
        or source_run.universe_frozen_as_of != universe.get("frozen_as_of")
        or source_run.candidate_symbols != spec.candidate_symbols
        or source_run.data_start != data.get("start_date")
        or source_run.data_end != data.get("end_date")
        or source_run.signal_timing != strategy.get("signal_timing")
        or source_run.execution_timing != strategy.get("execution_timing")
        or source_run.execution_timing != backtest.get("execution_timing")
        or source_run.valuation_timing != backtest.get("valuation_timing")
        or source_run.selection_metric != walk_forward.get("selection_metric")
        or source_run.cost_multipliers != cost_multipliers
    ):
        raise ValueError("source run is incompatible with forward config")


def _validate_source_report(
    *,
    payload: bytes,
    expected_size: int,
    expected_sha256: str,
    source_run: LightweightResearchRunV1,
    spec: _ForwardSpec,
) -> dict[str, int]:
    if len(payload) != expected_size or hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("source report digest mismatch")
    value = json.loads(
        payload.decode("utf-8"),
        object_pairs_hook=_unique_json_object,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON")),
    )
    if type(value) is not dict or canonical_json_bytes(value) != payload:
        raise ValueError("source report is not canonical")
    report = cast(dict[str, object], value)
    folds = report.get("folds")
    if (
        type(folds) is not list
        or len(folds) != len(source_run.folds)
        or any(type(item) is not dict for item in folds)
    ):
        raise ValueError("source report folds invalid")
    fold_numbers = tuple(
        cast(dict[str, object], item).get("fold") for item in folds
    )
    if fold_numbers != tuple(item.fold for item in source_run.folds):
        raise ValueError("source report fold identity mismatch")
    last = cast(dict[str, object], folds[-1])
    selected = last.get("selected_parameters")
    expected = {
        "regression_window": spec.selected_regression_window,
        "top_k": spec.selected_top_k,
    }
    if (
        last.get("fold") != source_run.folds[-1].fold
        or selected != expected
        or report.get("hypothesis_id") != source_run.hypothesis_id
        or report.get("selection_metric") != source_run.selection_metric
        or report.get("config") != source_run.config_relative_path
    ):
        raise ValueError("source report selection mismatch")
    return expected


def _require_complete_month_and_next_open(
    calendars: pl.DataFrame, as_of: dt.date
) -> dt.date:
    month_last = dt.date(
        as_of.year,
        as_of.month,
        calendar.monthrange(as_of.year, as_of.month)[1],
    )
    month_start = as_of.replace(day=1)
    for market in ("SH", "SZ"):
        month = calendars.filter(
            (pl.col("market") == market)
            & pl.col("date").is_between(month_start, month_last, closed="both")
        )
        if (
            month.is_empty()
            or month.get_column("date").max() != month_last
            or month.filter(pl.col("is_open")).get_column("date").max() != as_of
        ):
            raise ValueError("forward month is incomplete")
    common = (
        calendars.filter((pl.col("date") > as_of) & pl.col("is_open"))
        .group_by("date")
        .agg(pl.col("market").n_unique().alias("market_count"))
        .filter(pl.col("market_count") == 2)
        .get_column("date")
        .min()
    )
    if type(common) is not dt.date:
        raise ValueError("next common open session missing")
    return common


def _validated_prices(
    *,
    prices: pl.DataFrame,
    candidates: tuple[str, ...],
    as_of: dt.date,
    minimum_observations: int,
) -> pl.DataFrame:
    selected = prices.filter(
        pl.col("symbol").is_in(candidates)
        & (pl.col("adjustment_method") == "TOTAL_RETURN_DIVIDEND")
        & (pl.col("trade_date") <= as_of)
    ).sort("trade_date", "symbol")
    coverage = {
        symbol: (count, maximum)
        for symbol, count, maximum in selected.group_by("symbol").agg(
            pl.len().alias("count"), pl.col("trade_date").max().alias("maximum")
        ).iter_rows()
    }
    if any(
        coverage.get(symbol, (0, None))[0] < minimum_observations
        or coverage.get(symbol, (0, None))[1] != as_of
        for symbol in candidates
    ):
        raise ValueError("candidate prices are incomplete")
    return selected


def _build_targets(
    *,
    config: dict[str, Any],
    candidates: tuple[str, ...],
    prices: pl.DataFrame,
    calendars: pl.DataFrame,
    as_of: dt.date,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    strategy_config = _mapping(_mapping(config["strategy"])["etf_regime_trend"])
    factors = compute_trend_factors_from_prices(
        prices,
        as_of=as_of,
        source=None,
        momentum_windows=tuple(strategy_config["momentum_windows"]),
        regression_window=cast(int, strategy_config["regression_window"]),
        factor_version=cast(str, strategy_config["factor_version"]),
    )
    strategy = RegimeFilteredEtfTrendStrategy(
        candidates=candidates,
        regime_symbol=cast(str, strategy_config["regime_symbol"]),
        top_k=cast(int, strategy_config["top_k"]),
        cash_buffer=cast(float, strategy_config["cash_buffer"]),
        factor_version=cast(str, strategy_config["factor_version"]),
        momentum_windows=tuple(strategy_config["momentum_windows"]),
        regression_window=cast(int, strategy_config["regression_window"]),
        name=cast(str, _mapping(config["research"])["hypothesis_id"]).replace(
            "-", "_"
        ),
        version=cast(str, _mapping(config["research"])["strategy_version"]),
    )
    targets = TargetWeightSchema.validate(
        strategy.target_weights(as_of, factors)
    ).sort("as_of", "strategy", "strategy_version", "symbol")
    volatility_target = _mapping(strategy_config.get("volatility_target"))
    if set(volatility_target) != {
        "annualization_sessions",
        "annualized_volatility",
        "lookback_observations",
    }:
        raise ValueError("volatility target invalid")
    targets = scale_target_weights_to_volatility(
        targets=targets,
        prices=prices,
        lookback_observations=cast(int, volatility_target["lookback_observations"]),
        annualized_target_volatility=cast(
            float, volatility_target["annualized_volatility"]
        ),
        annualization_sessions=cast(int, volatility_target["annualization_sessions"]),
    ).sort("as_of", "strategy", "strategy_version", "symbol")
    scheduled = schedule_next_trading_day(targets, calendars).select(
        "execution_date",
        "as_of",
        "strategy",
        "strategy_version",
        "symbol",
        "weight",
    )
    return targets, scheduled.sort(
        "execution_date", "as_of", "strategy", "strategy_version", "symbol"
    )


def _validate_targets(
    *, targets: pl.DataFrame, scheduled: pl.DataFrame, next_common_open: dt.date
) -> None:
    canonical_targets = TargetWeightSchema.validate(targets).select(
        "as_of", "strategy", "strategy_version", "symbol", "weight"
    )
    if (
        targets.columns != canonical_targets.columns
        or targets.schema != canonical_targets.schema
        or not targets.equals(canonical_targets)
        or scheduled.height != targets.height
        or scheduled.columns
        != [
            "execution_date",
            "as_of",
            "strategy",
            "strategy_version",
            "symbol",
            "weight",
        ]
        or scheduled.get_column("execution_date").unique().to_list()
        != [next_common_open]
        or not scheduled.drop("execution_date").equals(targets)
        or float(targets.get_column("weight").sum()) > 1.0 + 1e-9
    ):
        raise ValueError("forward target contract invalid")


def _require_receipt_inputs(
    *,
    source_slice: M2ForwardSourceSlice,
    calendar_input: ResearchInputDigestV1,
    price_input: ResearchInputDigestV1,
) -> None:
    value = json.loads(
        source_slice.source_receipt.decode("utf-8"),
        object_pairs_hook=_unique_json_object,
    )
    if type(value) is not dict or canonical_json_bytes(value) != source_slice.source_receipt:
        raise ValueError("source receipt invalid")
    receipt = cast(dict[str, object], value)
    expected = [
        _input_mapping(calendar_input),
        _input_mapping(price_input),
    ]
    if receipt.get("logical_inputs") != expected:
        raise ValueError("source receipt input mismatch")


def _input_mapping(value: ResearchInputDigestV1) -> dict[str, object]:
    return {
        "content_sha256": value.content_sha256,
        "max_date": None if value.max_date is None else value.max_date.isoformat(),
        "min_date": None if value.min_date is None else value.min_date.isoformat(),
        "name": value.name,
        "rows": value.rows,
    }


def _candidates(config: dict[str, Any]) -> tuple[str, ...]:
    universe = _mapping(config.get("universe"))
    candidates = tuple(
        sorted(
            symbol
            for group in ("wide", "industry", "hong_kong_theme")
            for symbol in _string_list(universe.get(group))
        )
    )
    if not candidates or len(candidates) != len(set(candidates)):
        raise ValueError("forward universe invalid")
    return candidates


def _read_stable_file(path: Path) -> bytes:
    before = os.lstat(path)
    if (
        not stat.S_ISREG(before.st_mode)
        or _is_link_or_reparse(before)
        or getattr(before, "st_nlink", 1) != 1
    ):
        raise ValueError("invalid forward file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    after = os.lstat(path)
    if (
        not _same_open_file(before, opened)
        or not _same_file_snapshot(before, after)
        or _is_link_or_reparse(after)
        or getattr(after, "st_nlink", 1) != 1
    ):
        raise ValueError("unstable forward file")
    return b"".join(chunks)


def _anchored_directory(path: Path) -> Path:
    root = Path(os.path.abspath(path))
    resolved = root.resolve(strict=True)
    info = os.lstat(root)
    if (
        os.path.normcase(os.fspath(root)) != os.path.normcase(os.fspath(resolved))
        or not stat.S_ISDIR(info.st_mode)
        or _is_link_or_reparse(info)
    ):
        raise ValueError("invalid project root")
    return root


def _inside(root: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else root / path
    absolute = Path(os.path.abspath(candidate))
    resolved = absolute.resolve(strict=True)
    if (
        os.path.normcase(os.fspath(absolute))
        != os.path.normcase(os.fspath(resolved))
        or (resolved != root and root not in resolved.parents)
    ):
        raise ValueError("path outside project root")
    return resolved


def _same_file_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    return os.path.samestat(left, right) and (
        stat.S_IFMT(left.st_mode),
        left.st_size,
        getattr(left, "st_mtime_ns", int(left.st_mtime * 1_000_000_000)),
        getattr(left, "st_ctime_ns", int(left.st_ctime * 1_000_000_000)),
        getattr(left, "st_nlink", 1),
    ) == (
        stat.S_IFMT(right.st_mode),
        right.st_size,
        getattr(right, "st_mtime_ns", int(right.st_mtime * 1_000_000_000)),
        getattr(right, "st_ctime_ns", int(right.st_ctime * 1_000_000_000)),
        getattr(right, "st_nlink", 1),
    )


def _same_open_file(left: os.stat_result, right: os.stat_result) -> bool:
    return os.path.samestat(left, right) and (
        stat.S_IFMT(left.st_mode),
        left.st_size,
        getattr(left, "st_nlink", 1),
    ) == (
        stat.S_IFMT(right.st_mode),
        right.st_size,
        getattr(right, "st_nlink", 1),
    )


def _is_link_or_reparse(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & marker)


def _mapping(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError("forward config mapping invalid")
    return cast(dict[str, Any], value)


def _string_list(value: object) -> list[str]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise ValueError("forward config symbols invalid")
    return cast(list[str], value)


def _positive_int(value: object) -> int:
    if type(value) is not int or cast(int, value) <= 0:
        raise ValueError("forward config integer invalid")
    return cast(int, value)


def _date(value: object) -> dt.date:
    if type(value) is not dt.date:
        raise ValueError("forward config date invalid")
    return cast(dt.date, value)


def _hex64(value: object) -> str:
    if (
        type(value) is not str
        or len(cast(str, value)) != 64
        or not set(cast(str, value)) <= set("0123456789abcdef")
    ):
        raise ValueError("forward config digest invalid")
    return cast(str, value)


def _relative_path(value: object) -> str:
    if type(value) is not str or "\\" in cast(str, value):
        raise ValueError("forward config path invalid")
    path = Path(cast(str, value))
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("forward config path invalid")
    return path.as_posix()


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _parquet_bytes(frame: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.write_parquet(buffer, compression="zstd", statistics=True)
    return buffer.getvalue()


__all__ = [
    "M2ForwardObservationError",
    "publish_forward_research_run",
]


if __name__ == "__main__":
    raise SystemExit(main())
