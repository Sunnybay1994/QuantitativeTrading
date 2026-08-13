"""Deterministic A-share backtest plans for the M3 development chain."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields
from decimal import Decimal
from functools import wraps
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar, cast

import polars as pl

from quant.domain import TargetWeightSchema, TradeCalendarSchema
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    AShareCostPeriod,
    BacktestPlanManifestV1,
    BacktestWindow,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleBacktestPlanArtifact,
    VerifiedDevelopmentExampleExperimentIdentity,
    VerifiedDevelopmentExampleFoldPlanArtifact,
    VerifiedDevelopmentExampleG1Release,
    VerifiedDevelopmentExampleTargetArtifact,
)
from quant.research.m3.run_state import (
    ArtifactDigest,
    path_for_artifact_digest,
    verify_stage_receipt_with_bytes,
)
from quant.research.m3.targets import read_target_manifest

G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION = "sse_szse_limit_order_quantity_v1"
_FILES = {
    "cost_schedule.json",
    "manifest.json",
    "schedule_diagnostics.parquet",
    "scheduled_targets.parquet",
}
_SCHEDULED_COLUMNS = [
    "as_of",
    "strategy",
    "strategy_version",
    "symbol",
    "weight",
    "execution_date",
]
_DIAGNOSTICS_SCHEMA = {
    "as_of": pl.Date,
    "execution_date": pl.Date,
    "n_targets": pl.Int64,
    "total_target_weight": pl.Float64,
    "session_lag": pl.Int64,
}
_P = ParamSpec("_P")
_T = TypeVar("_T")


def _plan_boundary(function: Callable[_P, _T]) -> Callable[_P, _T]:
    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        try:
            return function(*args, **kwargs)
        except ValueError:
            raise
        except Exception:
            raise ValueError("M3_BACKTEST_PLAN_INVALID") from None

    return wrapped


class BacktestPlanUpstreamPaths:
    """Receipt paths not derivable from the verified artifact roots."""

    def __init__(
        self,
        *,
        target_receipt_path: Path,
        fold_receipt_path: Path,
        experiment_receipt_path: Path,
    ) -> None:
        paths = (target_receipt_path, fold_receipt_path, experiment_receipt_path)
        if any(not isinstance(path, Path) for path in paths) or len(set(paths)) != 3:
            raise ValueError("backtest plan upstream paths invalid")
        self.target_receipt_path = target_receipt_path
        self.fold_receipt_path = fold_receipt_path
        self.experiment_receipt_path = experiment_receipt_path


@_plan_boundary
def build_development_example_backtest_plan_artifact(
    *,
    target: VerifiedDevelopmentExampleTargetArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    output_root: Path,
) -> BacktestPlanManifestV1:
    """Build a closed development-only schedule without touching formal roots."""
    _require_empty_directory(output_root)
    _validate_inputs(target, release, folds, experiment, config)
    sessions = _sh_open_sessions(release)
    scheduled, diagnostics, window = _schedule_targets(target, folds, sessions)
    cost_payload = _cost_schedule_payload(config)
    cost_bytes = _canonical_bytes(cost_payload)

    scheduled_path = output_root / "scheduled_targets.parquet"
    diagnostics_path = output_root / "schedule_diagnostics.parquet"
    cost_path = output_root / "cost_schedule.json"
    _write_parquet(scheduled, scheduled_path)
    _write_parquet(diagnostics, diagnostics_path)
    _write_exclusive(cost_path, cost_bytes)
    manifest = _make_manifest(
        target=target,
        release=release,
        folds=folds,
        experiment=experiment,
        config=config,
        window=window,
        sessions=sessions,
        cost_bytes=cost_bytes,
        scheduled_path=scheduled_path,
        diagnostics_path=diagnostics_path,
    )
    _write_exclusive(output_root / "manifest.json", _canonical_bytes(asdict(manifest)))
    return manifest


@_plan_boundary
def verify_development_example_backtest_plan_artifact(
    *,
    root: Path,
    receipt_path: Path,
    target: VerifiedDevelopmentExampleTargetArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    upstream_paths: BacktestPlanUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedDevelopmentExampleBacktestPlanArtifact:
    """Freshly recompute the complete plan and receipt closure."""
    _validate_inputs(target, release, folds, experiment, config)
    _validate_upstream_bytes(target, release, folds, experiment, upstream_paths)
    if (
        not root.is_dir()
        or root.is_symlink()
        or {entry.name for entry in os.scandir(root)} != _FILES
    ):
        raise ValueError("backtest plan tree closure drift")
    manifest_raw = (root / "manifest.json").read_bytes()
    manifest = read_backtest_plan_manifest(root / "manifest.json")
    scheduled = _read_scheduled(root / "scheduled_targets.parquet")
    diagnostics = _read_diagnostics(root / "schedule_diagnostics.parquet")
    sessions = _sh_open_sessions(release)
    expected_scheduled, expected_diagnostics, window = _schedule_targets(
        target, folds, sessions
    )
    if not scheduled.equals(expected_scheduled) or not diagnostics.equals(
        expected_diagnostics
    ):
        raise ValueError("backtest plan content drift")
    cost_bytes = (root / "cost_schedule.json").read_bytes()
    if cost_bytes != _canonical_bytes(_cost_schedule_payload(config)):
        raise ValueError("backtest plan cost schedule drift")
    expected_manifest = _make_manifest(
        target=target,
        release=release,
        folds=folds,
        experiment=experiment,
        config=config,
        window=window,
        sessions=sessions,
        cost_bytes=cost_bytes,
        scheduled_path=root / "scheduled_targets.parquet",
        diagnostics_path=root / "schedule_diagnostics.parquet",
    )
    if manifest != expected_manifest:
        raise ValueError("backtest plan manifest drift")
    verified_receipt = verify_stage_receipt_with_bytes(
        receipt_path=receipt_path, artifact_roots=artifact_roots
    )
    if verified_receipt is None:
        raise ValueError("backtest plan receipt missing")
    receipt = verified_receipt.receipt
    inputs = _receipt_inputs(target, release, folds, experiment, upstream_paths)
    outputs = tuple(root / name for name in sorted(_FILES))
    if (
        receipt.stage != "development-backtest-plan"
        or receipt.scope != "WORK"
        or receipt.scope_key != target.manifest.work_key
        or not _digest_paths_equal(receipt.inputs, inputs, artifact_roots)
        or not _digest_paths_equal(receipt.outputs, outputs, artifact_roots)
    ):
        raise ValueError("backtest plan receipt closure drift")
    return VerifiedDevelopmentExampleBacktestPlanArtifact(
        release_kind="development_example",
        formal_gate_eligible=False,
        example_id=target.example_id,
        root=root.resolve(strict=True),
        scheduled_targets=scheduled,
        manifest=manifest,
        manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
        plan_receipt_sha256=verified_receipt.sha256,
    )


@_plan_boundary
def read_backtest_plan_manifest(path: Path) -> BacktestPlanManifestV1:
    raw = path.read_bytes()
    payload = _strict_object(raw)
    if set(payload) != {field.name for field in fields(BacktestPlanManifestV1)}:
        raise ValueError("backtest plan manifest fields drift")
    window_raw = payload.get("window")
    if type(window_raw) is not dict:
        raise ValueError("backtest plan window invalid")
    window_fields = {field.name for field in fields(BacktestWindow)}
    if set(window_raw) != window_fields:
        raise ValueError("backtest plan window fields drift")
    window = BacktestWindow(
        signal_dates=tuple(
            dt.date.fromisoformat(cast(str, value))
            for value in cast(list[object], window_raw["signal_dates"])
        ),
        execution_dates=tuple(
            dt.date.fromisoformat(cast(str, value))
            for value in cast(list[object], window_raw["execution_dates"])
        ),
        first_execution_date=dt.date.fromisoformat(
            cast(str, window_raw["first_execution_date"])
        ),
        terminal_valuation_date=dt.date.fromisoformat(
            cast(str, window_raw["terminal_valuation_date"])
        ),
        force_liquidation=cast(Any, window_raw["force_liquidation"]),
    )
    values = dict(payload)
    values["window"] = window
    manifest = BacktestPlanManifestV1(**cast(Any, values))
    if raw != _canonical_bytes(asdict(manifest)):
        raise ValueError("backtest plan manifest non-canonical")
    return manifest


def _validate_inputs(
    target: VerifiedDevelopmentExampleTargetArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
) -> None:
    if (
        type(target) is not VerifiedDevelopmentExampleTargetArtifact
        or type(release) is not VerifiedDevelopmentExampleG1Release
        or type(folds) is not VerifiedDevelopmentExampleFoldPlanArtifact
        or type(experiment) is not VerifiedDevelopmentExampleExperimentIdentity
        or type(config) is not LoadedM3Config
    ):
        raise ValueError("backtest plan inputs invalid")
    planned = next(
        (item for item in folds.manifest.folds if item.name == target.manifest.fold), None
    )
    if (
        len({target.example_id, folds.example_id, experiment.example_id}) != 1
        or target.example_id != release.manifest.example_id
        or planned is None
        or target.manifest.experiment_key != experiment.manifest.experiment_key
        or target.manifest.experiment_manifest_sha256 != experiment.manifest_sha256
        or target.manifest.g1_release_id != release.manifest.release_id
        or target.manifest.g1_release_manifest_sha256 != release.manifest_sha256
        or target.manifest.fold_plan_manifest_sha256 != folds.manifest_sha256
        or target.manifest.horizon_sessions
        not in cast(tuple[int, ...], config.section("labels")["horizons_sessions"])
        or target.manifest.scientific_config_sha256 != config.scientific_config_sha256
        or experiment.manifest.scientific_config_sha256
        != config.scientific_config_sha256
    ):
        raise ValueError("backtest plan identity drift")
    manifest_path = target.root / "target_manifest.json"
    targets_path = target.root / "target_weights.parquet"
    daily_path = target.root / "target_daily.parquet"
    if (
        _file_sha(manifest_path) != target.manifest_sha256
        or read_target_manifest(manifest_path) != target.manifest
        or not _read_target_weights(targets_path).equals(target.targets)
        or not pl.read_parquet(daily_path).equals(target.target_daily)
    ):
        raise ValueError("backtest plan target capability stale")
    targets = _read_target_weights(targets_path)
    signal_dates = tuple(sorted(set(cast(list[dt.date], targets["as_of"].to_list()))))
    if (
        signal_dates != planned.test_dates
        or any(not symbol.endswith((".SH", ".SZ")) for symbol in targets["symbol"])
        or targets["strategy"].n_unique() != 1
        or targets["strategy_version"].n_unique() != 1
        or targets.item(0, "strategy") != target.manifest.strategy
        or targets.item(0, "strategy_version") != target.manifest.strategy_version
    ):
        raise ValueError("backtest plan target domain invalid")


def _sh_open_sessions(
    release: VerifiedDevelopmentExampleG1Release,
) -> tuple[dt.date, ...]:
    path = dict(release.artifact_paths)["trade_calendar.parquet"]
    calendar = TradeCalendarSchema.validate(pl.read_parquet(path))
    sessions = tuple(
        cast(
            list[dt.date],
            calendar.filter((pl.col("market") == "SH") & pl.col("is_open"))
            .sort("date")
            .get_column("date")
            .to_list(),
        )
    )
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("backtest plan SH calendar invalid")
    return sessions


def _schedule_targets(
    target: VerifiedDevelopmentExampleTargetArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    sessions: tuple[dt.date, ...],
) -> tuple[pl.DataFrame, pl.DataFrame, BacktestWindow]:
    planned = next(item for item in folds.manifest.folds if item.name == target.manifest.fold)
    signals = planned.test_dates
    execution: list[dt.date] = []
    for signal in signals:
        following = next((day for day in sessions if day > signal), None)
        if following is None:
            raise ValueError("backtest plan missing next execution session")
        execution.append(following)
    mapping = pl.DataFrame(
        {"as_of": signals, "execution_date": execution},
        schema={"as_of": pl.Date, "execution_date": pl.Date},
    )
    scheduled = (
        target.targets.join(mapping, on="as_of", how="left")
        .select(_SCHEDULED_COLUMNS)
        .sort("execution_date", "as_of", "symbol")
    )
    if scheduled["execution_date"].null_count() or scheduled.height != target.targets.height:
        raise ValueError("backtest plan incomplete signal batch")
    diagnostics_rows: list[dict[str, object]] = []
    for signal, execution_date in zip(signals, execution, strict=True):
        batch = target.targets.filter(pl.col("as_of") == signal)
        if batch.is_empty():
            raise ValueError("backtest plan empty signal batch")
        diagnostics_rows.append(
            {
                "as_of": signal,
                "execution_date": execution_date,
                "n_targets": batch.height,
                "total_target_weight": float(batch["weight"].sum()),
                "session_lag": 1,
            }
        )
    diagnostics = pl.DataFrame(diagnostics_rows, schema=_DIAGNOSTICS_SCHEMA).sort(
        "as_of"
    )
    window = BacktestWindow(
        signal_dates=signals,
        execution_dates=tuple(execution),
        first_execution_date=execution[0],
        terminal_valuation_date=execution[-1],
        force_liquidation=False,
    )
    return scheduled, diagnostics, window


def _cost_schedule_payload(config: LoadedM3Config) -> dict[str, object]:
    costs = config.section("costs")
    raw_periods = cast(Sequence[Mapping[str, object]], costs["a_share_periods"])
    base = tuple(_cost_period(item) for item in raw_periods)
    _validate_cost_periods(base)
    multipliers = (Decimal("0.5"), Decimal("1"), Decimal("2"))
    schedules: list[dict[str, object]] = []
    for multiplier in multipliers:
        schedules.append(
            {
                "multiplier": _decimal_text(multiplier),
                "periods": [
                    _period_payload(period, multiplier) for period in base
                ],
            }
        )
    return {
        "multipliers": [_decimal_text(value) for value in multipliers],
        "scaled_components": list(cast(tuple[str, ...], costs["scaled_components"])),
        "schedules": schedules,
    }


def _cost_period(raw: Mapping[str, object]) -> AShareCostPeriod:
    return AShareCostPeriod(
        effective_from=cast(dt.date, raw["effective_from"]),
        effective_to=cast(dt.date | None, raw.get("effective_to")),
        commission_rate=Decimal(str(raw["commission_rate"])),
        commission_min=Decimal(str(raw["commission_min"])),
        stamp_tax_sell=Decimal(str(raw["stamp_tax_sell"])),
        transfer_fee=Decimal(str(raw["transfer_fee"])),
        slippage=Decimal(str(raw["slippage"])),
    )


def _validate_cost_periods(periods: tuple[AShareCostPeriod, ...]) -> None:
    if not periods:
        raise ValueError("backtest plan cost schedule empty")
    for index, period in enumerate(periods):
        if (period.effective_to is None) != (index == len(periods) - 1):
            raise ValueError("backtest plan open cost interval invalid")
        if index:
            previous = periods[index - 1]
            assert previous.effective_to is not None
            if period.effective_from != previous.effective_to + dt.timedelta(days=1):
                raise ValueError("backtest plan cost intervals not contiguous")


def _period_payload(period: AShareCostPeriod, multiplier: Decimal) -> dict[str, object]:
    return {
        "effective_from": period.effective_from.isoformat(),
        "effective_to": (
            None if period.effective_to is None else period.effective_to.isoformat()
        ),
        "commission_rate": _decimal_text(period.commission_rate * multiplier),
        "commission_min": _decimal_text(period.commission_min * multiplier),
        "stamp_tax_sell": _decimal_text(period.stamp_tax_sell),
        "transfer_fee": _decimal_text(period.transfer_fee),
        "slippage": _decimal_text(period.slippage * multiplier),
    }


def _make_manifest(
    *,
    target: VerifiedDevelopmentExampleTargetArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    window: BacktestWindow,
    sessions: tuple[dt.date, ...],
    cost_bytes: bytes,
    scheduled_path: Path,
    diagnostics_path: Path,
) -> BacktestPlanManifestV1:
    return BacktestPlanManifestV1(
        schema_version="m3-a-share-backtest-plan-v1",
        experiment_key=target.manifest.experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        work_key=target.manifest.work_key,
        target_manifest_sha256=target.manifest_sha256,
        target_receipt_sha256=target.target_receipt_sha256,
        g1_release_id=release.manifest.release_id,
        g1_release_manifest_sha256=release.manifest_sha256,
        scientific_config_sha256=config.scientific_config_sha256,
        fold_plan_manifest_sha256=folds.manifest_sha256,
        fold=target.manifest.fold,
        horizon_sessions=target.manifest.horizon_sessions,
        window=window,
        session_calendar_sha256=_sha256_json(
            [day.isoformat() for day in sessions]
        ),
        cost_schedule_sha256=hashlib.sha256(cost_bytes).hexdigest(),
        cost_schedule_version=cast(str, config.section("costs")["schedule_version"]),
        order_quantity_rule_version=G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION,
        scheduled_targets_sha256=_file_sha(scheduled_path),
        schedule_diagnostics_sha256=_file_sha(diagnostics_path),
    )


def _validate_upstream_bytes(
    target: VerifiedDevelopmentExampleTargetArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    paths: BacktestPlanUpstreamPaths,
) -> None:
    checks = (
        (target.root / "target_manifest.json", target.manifest_sha256),
        (paths.target_receipt_path, target.target_receipt_sha256),
        (release.release.manifest_path, release.manifest_sha256),
        (release.release.root / "receipt.json", release.receipt_sha256),
        (folds.root / "folds.json", folds.manifest_sha256),
        (paths.fold_receipt_path, folds.folds_receipt_sha256),
        (experiment.root / "experiment_manifest.json", experiment.manifest_sha256),
        (paths.experiment_receipt_path, experiment.experiment_receipt_sha256),
    )
    if any(not path.is_file() or _file_sha(path) != digest for path, digest in checks):
        raise ValueError("backtest plan upstream bytes stale")


def _receipt_inputs(
    target: VerifiedDevelopmentExampleTargetArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    paths: BacktestPlanUpstreamPaths,
) -> tuple[Path, ...]:
    return (
        target.root / "target_manifest.json",
        paths.target_receipt_path,
        target.root / "target_weights.parquet",
        target.root / "target_daily.parquet",
        release.release.manifest_path,
        release.release.root / "receipt.json",
        dict(release.artifact_paths)["trade_calendar.parquet"],
        folds.root / "folds.json",
        paths.fold_receipt_path,
        experiment.root / "experiment_manifest.json",
        paths.experiment_receipt_path,
    )


def _read_target_weights(path: Path) -> pl.DataFrame:
    frame = TargetWeightSchema.validate(pl.read_parquet(path)).sort("as_of", "symbol")
    if frame.columns != [
        "as_of", "strategy", "strategy_version", "symbol", "weight"
    ] or frame.n_unique(["as_of", "symbol"]) != frame.height:
        raise ValueError("backtest plan target schema drift")
    return frame


def _read_scheduled(path: Path) -> pl.DataFrame:
    frame = pl.read_parquet(path)
    if frame.columns != _SCHEDULED_COLUMNS or frame.schema != {
        "as_of": pl.Date,
        "strategy": pl.String,
        "strategy_version": pl.String,
        "symbol": pl.String,
        "weight": pl.Float64,
        "execution_date": pl.Date,
    }:
        raise ValueError("backtest scheduled targets schema drift")
    TargetWeightSchema.validate(frame.drop("execution_date"))
    if not frame.equals(frame.sort("execution_date", "as_of", "symbol")):
        raise ValueError("backtest scheduled targets order drift")
    return frame


def _read_diagnostics(path: Path) -> pl.DataFrame:
    frame = pl.read_parquet(path)
    if (
        frame.columns != list(_DIAGNOSTICS_SCHEMA)
        or frame.schema != _DIAGNOSTICS_SCHEMA
        or not frame.equals(frame.sort("as_of"))
    ):
        raise ValueError("backtest schedule diagnostics drift")
    return frame


def _strict_object(raw: bytes) -> dict[str, object]:
    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=hook,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")),
    )
    if type(value) is not dict or raw != _canonical_bytes(value):
        raise ValueError("non-canonical JSON")
    return value


def _canonical_bytes(value: object) -> bytes:
    def normalize(item: object) -> object:
        if type(item) is dt.date:
            return item.isoformat()
        if isinstance(item, Mapping):
            return {str(key): normalize(child) for key, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [normalize(child) for child in item]
        return item

    return json.dumps(
        normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _digest_paths_equal(
    digests: tuple[ArtifactDigest, ...],
    paths: Sequence[Path],
    roots: Mapping[str, Path],
) -> bool:
    if len(digests) != len(paths):
        return False
    actual = tuple(
        sorted(
            os.path.normcase(
                os.path.abspath(path_for_artifact_digest(item, artifact_roots=roots))
            )
            for item in digests
        )
    )
    expected = tuple(sorted(os.path.normcase(os.path.abspath(path)) for path in paths))
    return actual == expected and len(set(actual)) == len(actual)


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_empty_directory(path: Path) -> None:
    if not path.is_dir() or path.is_symlink() or any(path.iterdir()):
        raise ValueError("backtest plan output must be an empty real directory")


def _write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
        0o644,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _write_parquet(frame: pl.DataFrame, path: Path) -> None:
    frame.write_parquet(
        path,
        compression="zstd",
        compression_level=3,
        statistics=True,
        row_group_size=65536,
        use_pyarrow=False,
    )


__all__ = [
    "AShareCostPeriod",
    "BacktestPlanManifestV1",
    "BacktestPlanUpstreamPaths",
    "BacktestWindow",
    "G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION",
    "build_development_example_backtest_plan_artifact",
    "read_backtest_plan_manifest",
    "verify_development_example_backtest_plan_artifact",
]
