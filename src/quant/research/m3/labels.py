"""Independent label build: next-open to h-close excess vs total-return benchmark."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import math
import os
import stat
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Mapping, cast

import polars as pl

from quant.domain import BenchmarkBar1dSchema, ForwardReturnLabelSchema
from quant.data.m3_identity import clean_table_content_sha256
from quant.data.m3_release import VerifiedG1Release, verify_g1_release
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    ExperimentIdentityManifestV1,
    ExperimentIdentitySpec,
    LabelArtifactManifest,
    LabelBuildSpec,
    VerifiedExperimentIdentity,
    VerifiedLabelArtifact,
    VerifiedProviderArtifact,
    VerifiedSnapshotArtifact,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleExperimentIdentity,
    VerifiedDevelopmentExampleG1Release,
    VerifiedDevelopmentExampleLabelArtifact,
    VerifiedDevelopmentExampleProviderArtifact,
    VerifiedDevelopmentExampleSnapshotArtifact,
    compute_development_experiment_key,
    verify_development_example_g1_release,
)
from quant.research.m3.run_state import (
    ArtifactDigest,
    StageReceipt,
    compute_experiment_key,
    path_for_artifact_digest,
    select_artifact_root,
    verify_stage_receipt_with_bytes,
)
from quant.research.m3.provider import (
    verify_development_example_provider_artifact,
    verify_provider_artifact,
)

_EMPTY_LABELS = pl.DataFrame(
    schema={
        "as_of": pl.Date,
        "symbol": pl.Utf8,
        "benchmark": pl.Utf8,
        "horizon_sessions": pl.Int64,
        "return_start_date": pl.Date,
        "return_end_date": pl.Date,
        "available_as_of": pl.Date,
        "raw_return": pl.Float64,
        "benchmark_return": pl.Float64,
        "relative_return": pl.Float64,
        "label_version": pl.Utf8,
    }
)

_EMPTY_DIAGNOSTICS = pl.DataFrame(
    schema={
        "as_of": pl.Date,
        "horizon_sessions": pl.Int64,
        "reason": pl.Utf8,
        "sample_count": pl.Int64,
    }
)


@dataclass(frozen=True)
class LabelBuildResult:
    labels: pl.DataFrame
    diagnostics: pl.DataFrame


def compute_forward_relative_labels(
    *,
    bars: pl.DataFrame,
    benchmark_bars: pl.DataFrame,
    eligible_keys: pl.DataFrame,
    calendars: pl.DataFrame,
    horizons: Sequence[int],
    benchmark: str,
    label_version: str,
) -> LabelBuildResult:
    """Build forward relative labels over PIT eligible keys only."""
    if not horizons:
        raise ValueError("horizons 不得为空")
    if any(type(h) is not int or h <= 0 for h in horizons):
        raise ValueError("horizon 必须为正整数")
    if tuple(horizons) != tuple(sorted(set(horizons))):
        raise ValueError("horizons 必须唯一递增")
    if type(benchmark) is not str or not benchmark or type(label_version) is not str or not label_version:
        raise ValueError("benchmark/label_version 非法")

    keys = _validate_eligible_keys(eligible_keys)
    _reject_duplicate_key(bars, ["symbol", "trade_date"], "bars")
    bars = _validate_label_bars(bars)
    bench = _validate_benchmark_bars(benchmark_bars, benchmark)
    _reject_duplicate_key(bench, ["benchmark", "trade_date"], "benchmark_bars")

    open_dates = (
        calendars.filter((pl.col("market") == "SH") & pl.col("is_open"))
        .sort("date")
        .get_column("date")
        .to_list()
    )
    if not open_dates or open_dates != sorted(set(open_dates)):
        raise ValueError("SH open calendar 必须非空唯一递增")
    date_to_idx = {date: idx for idx, date in enumerate(open_dates)}
    stock_lookup = _stock_lookup(bars)
    bench_lookup = _bench_lookup(bench)

    label_rows: list[dict[str, object]] = []
    diag_counts: dict[tuple[dt.date, int, str], int] = {}

    for key in keys.iter_rows(named=True):
        as_of: dt.date = key["as_of"]
        symbol: str = key["symbol"]
        as_of_idx = date_to_idx.get(as_of)
        for horizon in horizons:
            h = int(horizon)
            reason = _first_failure_reason(
                as_of_idx=as_of_idx,
                horizon=h,
                n_sessions=len(open_dates),
                symbol=symbol,
                open_dates=open_dates,
                stock_lookup=stock_lookup,
                bench_lookup=bench_lookup,
            )
            if reason is not None:
                diag_key = (as_of, h, reason)
                diag_counts[diag_key] = diag_counts.get(diag_key, 0) + 1
                continue

            assert as_of_idx is not None
            entry_date = open_dates[as_of_idx + 1]
            exit_date = open_dates[as_of_idx + h]
            entry = stock_lookup[(symbol, entry_date)]
            exit_bar = stock_lookup[(symbol, exit_date)]
            bench_entry = bench_lookup[entry_date]
            bench_exit = bench_lookup[exit_date]
            raw_return = (
                exit_bar["close"] * exit_bar["adj_factor"]
            ) / (entry["open"] * entry["adj_factor"]) - 1.0
            benchmark_return = bench_exit["close"] / bench_entry["open"] - 1.0
            label_rows.append(
                {
                    "as_of": as_of,
                    "symbol": symbol,
                    "benchmark": benchmark,
                    "horizon_sessions": h,
                    "return_start_date": entry_date,
                    "return_end_date": exit_date,
                    "available_as_of": exit_date,
                    "raw_return": float(raw_return),
                    "benchmark_return": float(benchmark_return),
                    "relative_return": float(raw_return - benchmark_return),
                    "label_version": label_version,
                }
            )

    raw_labels = (
        pl.DataFrame(label_rows, schema=_EMPTY_LABELS.schema)
        if label_rows
        else _EMPTY_LABELS
    )
    labels = ForwardReturnLabelSchema.validate(raw_labels).sort(
        ["as_of", "horizon_sessions", "symbol"]
    )

    if diag_counts:
        diagnostics = pl.DataFrame(
            [
                {
                    "as_of": as_of,
                    "horizon_sessions": horizon,
                    "reason": reason,
                    "sample_count": count,
                }
                for (as_of, horizon, reason), count in diag_counts.items()
            ],
            schema=_EMPTY_DIAGNOSTICS.schema,
        ).sort(["as_of", "horizon_sessions", "reason"])
    else:
        diagnostics = _EMPTY_DIAGNOSTICS

    expected = keys.height * len(horizons)
    observed = labels.height + int(diagnostics.get_column("sample_count").sum() or 0)
    if expected != observed:
        raise RuntimeError(
            f"label conservation broken: eligible*horizons={expected} "
            f"labels+diagnostics={observed}"
        )

    return LabelBuildResult(labels=labels, diagnostics=diagnostics)


def _validate_eligible_keys(eligible_keys: pl.DataFrame) -> pl.DataFrame:
    if eligible_keys.columns != ["as_of", "symbol"] or eligible_keys.schema != {
        "as_of": pl.Date, "symbol": pl.Utf8,
    }:
        raise ValueError("eligible_keys schema 非法")
    keys = eligible_keys.select("as_of", "symbol")
    if keys.is_empty():
        raise ValueError("eligible_keys 不得为空")
    dup = keys.group_by("as_of", "symbol").len().filter(pl.col("len") > 1)
    if not dup.is_empty():
        raise ValueError("eligible_keys 存在重复 (as_of, symbol)")
    return keys.sort(["as_of", "symbol"])


def _validate_benchmark_bars(benchmark_bars: pl.DataFrame, benchmark: str) -> pl.DataFrame:
    frame = BenchmarkBar1dSchema.validate(benchmark_bars)
    codes = set(frame.get_column("benchmark").unique().to_list())
    if codes != {benchmark}:
        raise ValueError(
            f"benchmark_bars 必须只含显式基准 {benchmark!r}，实际为 {sorted(codes)!r}"
        )
    return frame


def _validate_label_bars(frame: pl.DataFrame) -> pl.DataFrame:
    expected = [
        "symbol", "trade_date", "open", "high", "low", "close", "volume",
        "amount", "adj_factor", "source",
    ]
    if frame.columns != expected:
        raise ValueError("bars schema 非法")
    if (
        frame.schema["symbol"] != pl.Utf8
        or frame.schema["trade_date"] != pl.Date
        or frame.schema["source"] != pl.Utf8
    ):
        raise ValueError("bars key dtype 非法")
    numeric = expected[2:-1]
    if any(not frame.schema[name].is_numeric() for name in numeric):
        raise ValueError("bars numeric dtype 非法")
    finite_columns = ["open", "high", "low", "close", "volume", "amount"]
    invalid = frame.filter(
        pl.any_horizontal(
            *[pl.col(name).is_null() | pl.col(name).is_nan() | pl.col(name).is_infinite()
              for name in finite_columns]
        )
        | (pl.col("open") <= 0)
        | (pl.col("high") <= 0)
        | (pl.col("low") <= 0)
        | (pl.col("close") <= 0)
        | (pl.col("volume") < 0)
        | (pl.col("amount") < 0)
        | (pl.col("low") > pl.col("open"))
        | (pl.col("low") > pl.col("close"))
        | (pl.col("high") < pl.col("open"))
        | (pl.col("high") < pl.col("close"))
    )
    if not invalid.is_empty():
        raise ValueError("bars value 非法")
    return frame


def _reject_duplicate_key(frame: pl.DataFrame, columns: list[str], name: str) -> None:
    dup = frame.group_by(columns).len().filter(pl.col("len") > 1)
    if not dup.is_empty():
        key = ", ".join(columns)
        raise ValueError(f"{name} 存在重复 ({key})")


def _factor_invalid(value: float | None) -> bool:
    if value is None:
        return True
    number = float(value)
    return (not math.isfinite(number)) or number <= 0.0


def _first_failure_reason(
    *,
    as_of_idx: int | None,
    horizon: int,
    n_sessions: int,
    symbol: str,
    open_dates: list[dt.date],
    stock_lookup: dict[tuple[str, dt.date], dict[str, float]],
    bench_lookup: dict[dt.date, dict[str, float]],
) -> str | None:
    if as_of_idx is None or as_of_idx + 1 >= n_sessions or as_of_idx + horizon >= n_sessions:
        return "TAIL_INCOMPLETE"
    entry_date = open_dates[as_of_idx + 1]
    exit_date = open_dates[as_of_idx + horizon]
    if entry_date not in bench_lookup:
        return "BENCHMARK_ENTRY_MISSING"
    if exit_date not in bench_lookup:
        return "BENCHMARK_EXIT_MISSING"
    entry = stock_lookup.get((symbol, entry_date))
    if entry is None:
        return "ASSET_ENTRY_BAR_MISSING"
    exit_bar = stock_lookup.get((symbol, exit_date))
    if exit_bar is None:
        return "ASSET_EXIT_BAR_MISSING"
    if _factor_invalid(entry["adj_factor"]):
        return "ASSET_ENTRY_FACTOR_INVALID"
    if _factor_invalid(exit_bar["adj_factor"]):
        return "ASSET_EXIT_FACTOR_INVALID"
    return None


def _stock_lookup(
    frame: pl.DataFrame,
) -> dict[tuple[str, dt.date], dict[str, float]]:
    lookup: dict[tuple[str, dt.date], dict[str, float]] = {}
    cols = ["symbol", "trade_date", "open", "close", "adj_factor"]
    for row in frame.select(cols).iter_rows(named=True):
        factor = row["adj_factor"]
        lookup[(row["symbol"], row["trade_date"])] = {
            "open": float(row["open"]),
            "close": float(row["close"]),
            "adj_factor": float("nan") if factor is None else float(factor),
        }
    return lookup


def _bench_lookup(frame: pl.DataFrame) -> dict[dt.date, dict[str, float]]:
    lookup: dict[dt.date, dict[str, float]] = {}
    for row in frame.select("trade_date", "open", "close").iter_rows(named=True):
        lookup[row["trade_date"]] = {
            "open": float(row["open"]),
            "close": float(row["close"]),
        }
    return lookup


_LABEL_FILES = frozenset({
    "labels.parquet", "diagnostics.parquet", "label_manifest.json",
})
_DIAGNOSTIC_SCHEMA = {
    "as_of": pl.Date,
    "horizon_sessions": pl.Int64,
    "reason": pl.Utf8,
    "sample_count": pl.Int64,
}


class M3LabelArtifactError(ValueError):
    """Stable G3A boundary error; no input paths or payloads are exposed."""

    _CODES = frozenset({
        "LABEL_ARTIFACT_INPUT_INVALID", "LABEL_ARTIFACT_IDENTITY_MISMATCH",
    })

    def __init__(self, code: str) -> None:
        if code not in self._CODES:
            raise ValueError("unknown label artifact error code")
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"M3LabelArtifactError({self.code!r})"


def _label_boundary(code: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(function)
        def wrapped(*args: object, **kwargs: object) -> Any:
            try:
                return function(*args, **kwargs)
            except M3LabelArtifactError:
                raise
            except Exception:
                pass
            # Raise outside the handler so ``__context__`` cannot retain paths,
            # payloads or credentials from the implementation exception.
            sanitized = M3LabelArtifactError(code)
            sanitized.__suppress_context__ = True
            raise sanitized

        return wrapped

    return decorate


@dataclass(frozen=True)
class _LabelSource:
    release_id: str
    release_manifest_sha256: str
    release_manifest_path: Path
    artifact_paths: Mapping[str, Path]
    release_file_hashes: Mapping[str, str]
    snapshot_id: str
    snapshot_manifest_sha256: str
    snapshot_manifest_path: Path
    snapshot_manifest_canonical_bytes: bytes
    snapshot_session_calendar_sha256: str
    snapshot_calendar_path: Path
    snapshot_request_key: str
    snapshot_receipt_sha256: str
    experiment_root: Path
    experiment: ExperimentIdentityManifestV1
    experiment_manifest_sha256: str
    experiment_receipt_sha256: str
    example_id: str | None


def _verify_snapshot_receipt_closure(
    *,
    receipt: StageReceipt | None,
    receipt_sha256: str,
    receipt_path: Path,
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    artifact_roots: Mapping[str, Path],
    example_id: str | None,
) -> None:
    """Rebuild the exact G2A receipt paths from the verified snapshot bundle."""
    stage = "snapshot" if example_id is None else "development-snapshot"
    key = snapshot.request.snapshot_request_key
    if (
        receipt is None
        or receipt.stage != stage
        or receipt.scope != "SNAPSHOT"
        or receipt.scope_key != key
        or receipt_sha256 != snapshot.snapshot_receipt_sha256
    ):
        raise ValueError("snapshot receipt identity drift")
    manifest_candidates = tuple(
        item
        for item in receipt.inputs
        if item.sha256 == snapshot.manifest.g1_release_manifest_sha256
        and Path(item.relative_path).name == "manifest.json"
    )
    if len(manifest_candidates) != 1:
        raise ValueError("snapshot release manifest input drift")
    release_manifest = path_for_artifact_digest(
        manifest_candidates[0], artifact_roots=artifact_roots
    )
    artifact_root = (
        release_manifest.parent
        if example_id is None
        else release_manifest.parent / "contract"
    )
    expected_inputs = _digests(
        (
            release_manifest,
            artifact_root / "bar_1d.parquet",
            artifact_root / "universe_membership.parquet",
            artifact_root / "trade_calendar.parquet",
        ),
        artifact_roots,
    )
    root = _artifact_root_for(snapshot.root, artifact_roots=artifact_roots)
    request_path = root / "snapshot-requests" / f"{key}.json"
    request_raw = _read_regular(request_path)
    if (
        request_raw != _canonical_contract_bytes(asdict(snapshot.request))
        or hashlib.sha256(request_raw).hexdigest() != snapshot.request_sha256
    ):
        raise ValueError("snapshot request bundle drift")
    expected_outputs = _digests(
        (
            request_path,
            snapshot.root / "manifest.json",
            snapshot.session_calendar_path,
            *snapshot.staging_paths,
        ),
        artifact_roots,
    )
    if receipt.inputs != expected_inputs or receipt.outputs != expected_outputs:
        raise ValueError("snapshot receipt closure drift")


def _verify_experiment_receipt_from_source(
    *,
    source: _LabelSource,
    experiment_receipt_path: Path,
    snapshot_receipt_path: Path,
    artifact_roots: Mapping[str, Path],
) -> None:
    """Recheck the G8 receipt before labels consume an experiment capability."""
    _require_real_directory(source.experiment_root)
    if {item.name for item in os.scandir(source.experiment_root)} != {
        "experiment_manifest.json"
    }:
        raise ValueError("experiment tree closure drift")
    manifest_path = source.experiment_root / "experiment_manifest.json"
    manifest_raw = _read_regular(manifest_path)
    disk_manifest = _parse_experiment_identity_manifest(manifest_raw)
    if disk_manifest != source.experiment:
        raise ValueError("experiment manifest bundle drift")
    receipt, receipt_sha = _verify_stage_receipt_secure(
        receipt_path=experiment_receipt_path, artifact_roots=artifact_roots
    )
    if (
        hashlib.sha256(manifest_raw).hexdigest()
        != source.experiment_manifest_sha256
        or receipt_sha != source.experiment_receipt_sha256
        or hashlib.sha256(_read_regular(snapshot_receipt_path)).hexdigest()
        != source.snapshot_receipt_sha256
        or hashlib.sha256(_read_regular(source.snapshot_manifest_path)).hexdigest()
        != source.snapshot_manifest_sha256
    ):
        raise ValueError("experiment upstream bytes drift")
    stage = (
        "experiment-identity"
        if source.example_id is None
        else "development-experiment-identity"
    )
    provider_stage = (
        "provider" if source.example_id is None else "development-provider"
    )
    provider_manifest_candidates = tuple(
        item
        for item in (() if receipt is None else receipt.inputs)
        if item.sha256 == source.experiment.provider_manifest_sha256
        and Path(item.relative_path).name == "provider_manifest.json"
    )
    if len(provider_manifest_candidates) != 1:
        raise ValueError("experiment provider manifest input drift")
    provider_manifest_path = path_for_artifact_digest(
        provider_manifest_candidates[0], artifact_roots=artifact_roots
    )
    provider_artifact_root = _artifact_root_for(
        provider_manifest_path, artifact_roots=artifact_roots
    )
    provider_receipt_path = (
        provider_artifact_root
        / "receipts"
        / provider_stage
        / f"{source.experiment.provider_key}.json"
    )
    expected_inputs = _digests(
        (
            snapshot_receipt_path,
            source.snapshot_manifest_path,
            provider_receipt_path,
            provider_manifest_path,
        ),
        artifact_roots,
    )
    expected_outputs = _digests((manifest_path,), artifact_roots)
    if (
        receipt is None
        or receipt.stage != stage
        or receipt.scope != "EXPERIMENT"
        or receipt.scope_key != source.experiment.experiment_key
        or receipt.inputs != expected_inputs
        or receipt.outputs != expected_outputs
    ):
        raise ValueError("experiment receipt closure drift")


def _verify_stage_receipt_secure(
    *, receipt_path: Path, artifact_roots: Mapping[str, Path]
) -> tuple[StageReceipt, str]:
    """Reuse the shared E3 root and file-identity verifier."""
    verified = verify_stage_receipt_with_bytes(
        receipt_path=receipt_path, artifact_roots=artifact_roots
    )
    if verified is None:
        raise ValueError("receipt missing")
    return verified.receipt, verified.sha256


@_label_boundary("LABEL_ARTIFACT_INPUT_INVALID")
def read_experiment_identity_manifest(path: Path) -> ExperimentIdentityManifestV1:
    """Read the only canonical G8 experiment identity representation."""
    return _parse_experiment_identity_manifest(_read_regular(path))


def _parse_experiment_identity_manifest(raw: bytes) -> ExperimentIdentityManifestV1:
    payload = _strict_json(raw)
    expected = {
        "schema_version", "experiment_key", "snapshot_id",
        "snapshot_manifest_sha256", "provider_key", "provider_manifest_sha256",
        "provider_receipt_sha256", "scientific_config_sha256",
        "dependency_fingerprint_sha256", "code_version",
    }
    if set(payload) != expected:
        raise ValueError("experiment manifest fields drift")
    manifest = ExperimentIdentityManifestV1(**cast(Any, payload))
    if _canonical_bytes(asdict(manifest)) != raw:
        raise ValueError("experiment manifest not canonical")
    return manifest


@_label_boundary("LABEL_ARTIFACT_IDENTITY_MISMATCH")
def verify_experiment_identity(
    *, experiment_root: Path, experiment_receipt_path: Path,
    snapshot: VerifiedSnapshotArtifact, provider: VerifiedProviderArtifact,
    config: LoadedM3Config, spec: ExperimentIdentitySpec,
    artifact_roots: Mapping[str, Path],
) -> VerifiedExperimentIdentity:
    if type(snapshot) is not VerifiedSnapshotArtifact or type(provider) is not VerifiedProviderArtifact:
        raise ValueError("formal experiment requires formal inputs")
    manifest, manifest_sha, receipt_sha = _verify_experiment(
        experiment_root=experiment_root,
        experiment_receipt_path=experiment_receipt_path,
        snapshot=snapshot,
        provider=provider,
        config=config,
        spec=spec,
        artifact_roots=artifact_roots,
        example_id=None,
    )
    return VerifiedExperimentIdentity(
        root=experiment_root.resolve(strict=True), manifest=manifest,
        manifest_sha256=manifest_sha, experiment_receipt_sha256=receipt_sha,
    )


@_label_boundary("LABEL_ARTIFACT_IDENTITY_MISMATCH")
def verify_development_example_experiment_identity(
    *, experiment_root: Path, experiment_receipt_path: Path,
    snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    provider: VerifiedDevelopmentExampleProviderArtifact,
    config: LoadedM3Config, spec: ExperimentIdentitySpec,
    artifact_roots: Mapping[str, Path],
) -> VerifiedDevelopmentExampleExperimentIdentity:
    if (
        type(snapshot) is not VerifiedDevelopmentExampleSnapshotArtifact
        or type(provider) is not VerifiedDevelopmentExampleProviderArtifact
        or snapshot.example_id != provider.example_id
    ):
        raise ValueError("development experiment inputs do not match")
    manifest, manifest_sha, receipt_sha = _verify_experiment(
        experiment_root=experiment_root,
        experiment_receipt_path=experiment_receipt_path,
        snapshot=snapshot,
        provider=provider,
        config=config,
        spec=spec,
        artifact_roots=artifact_roots,
        example_id=snapshot.example_id,
    )
    return VerifiedDevelopmentExampleExperimentIdentity(
        release_kind="development_example", formal_gate_eligible=False,
        example_id=snapshot.example_id, root=experiment_root.resolve(strict=True),
        manifest=manifest, manifest_sha256=manifest_sha,
        experiment_receipt_sha256=receipt_sha,
    )


def _verify_experiment(
    *, experiment_root: Path, experiment_receipt_path: Path,
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    provider: VerifiedProviderArtifact | VerifiedDevelopmentExampleProviderArtifact,
    config: LoadedM3Config, spec: ExperimentIdentitySpec,
    artifact_roots: Mapping[str, Path], example_id: str | None,
) -> tuple[ExperimentIdentityManifestV1, str, str]:
    if type(config) is not LoadedM3Config or type(spec) is not ExperimentIdentitySpec:
        raise ValueError("experiment config/spec invalid")
    _require_real_directory(experiment_root)
    if {item.name for item in os.scandir(experiment_root)} != {
        "experiment_manifest.json"
    }:
        raise ValueError("experiment tree closure drift")
    manifest_path = experiment_root / "experiment_manifest.json"
    manifest_raw = _read_regular(manifest_path)
    manifest = _parse_experiment_identity_manifest(manifest_raw)
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    expected_key = (
        compute_experiment_key(
            snapshot_id=snapshot.manifest.snapshot_id,
            provider_receipt_sha256=provider.provider_receipt_sha256,
            scientific_config_hash=spec.scientific_config_sha256,
            code_version=spec.code_version,
            dependency_fingerprint_sha256=spec.dependency_fingerprint_sha256,
        )
        if example_id is None
        else compute_development_experiment_key(
            example_id=example_id,
            snapshot_id=snapshot.manifest.snapshot_id,
            provider_receipt_sha256=provider.provider_receipt_sha256,
            scientific_config_sha256=spec.scientific_config_sha256,
            code_version=spec.code_version,
            dependency_fingerprint_sha256=spec.dependency_fingerprint_sha256,
        )
    )
    expected = ExperimentIdentityManifestV1(
        schema_version="m3-experiment-identity-v1",
        experiment_key=expected_key,
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_key=provider.manifest.provider_key,
        provider_manifest_sha256=provider.manifest_sha256,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        scientific_config_sha256=config.scientific_config_sha256,
        dependency_fingerprint_sha256=spec.dependency_fingerprint_sha256,
        code_version=spec.code_version,
    )
    if spec.scientific_config_sha256 != config.scientific_config_sha256 or manifest != expected:
        raise ValueError("experiment identity drift")
    snapshot_manifest = snapshot.root / "manifest.json"
    provider_manifest = provider.root / "provider_manifest.json"
    snapshot_manifest_raw = _read_regular(snapshot_manifest)
    if (
        snapshot_manifest_raw != _canonical_contract_bytes(asdict(snapshot.manifest))
        or hashlib.sha256(snapshot_manifest_raw).hexdigest()
        != snapshot.manifest_sha256
    ):
        raise ValueError("snapshot manifest drift")
    provider_manifest_raw = _read_regular(provider_manifest)
    if (
        provider_manifest_raw != _canonical_contract_bytes(asdict(provider.manifest))
        or hashlib.sha256(provider_manifest_raw).hexdigest()
        != provider.manifest_sha256
    ):
        raise ValueError("provider manifest drift")
    snapshot_artifact_root = _artifact_root_for(
        snapshot.root, artifact_roots=artifact_roots
    )
    provider_artifact_root = _artifact_root_for(
        provider.root, artifact_roots=artifact_roots
    )
    snapshot_stage = "snapshot" if example_id is None else "development-snapshot"
    provider_stage = "provider" if example_id is None else "development-provider"
    snapshot_receipt = snapshot_artifact_root / "receipts" / snapshot_stage / f"{snapshot.request.snapshot_request_key}.json"
    provider_receipt = provider_artifact_root / "receipts" / provider_stage / f"{provider.manifest.provider_key}.json"
    upstream_snapshot, snapshot_receipt_sha = _verify_stage_receipt_secure(
        receipt_path=snapshot_receipt, artifact_roots=artifact_roots
    )
    upstream_provider, provider_receipt_sha = _verify_stage_receipt_secure(
        receipt_path=provider_receipt, artifact_roots=artifact_roots
    )
    if snapshot_receipt_sha != snapshot.snapshot_receipt_sha256:
        raise ValueError("snapshot receipt drift")
    if provider_receipt_sha != provider.provider_receipt_sha256:
        raise ValueError("provider receipt drift")
    _verify_snapshot_receipt_closure(
        receipt=upstream_snapshot,
        receipt_sha256=snapshot_receipt_sha,
        receipt_path=snapshot_receipt,
        snapshot=snapshot,
        artifact_roots=artifact_roots,
        example_id=example_id,
    )
    fresh_provider = (
        verify_provider_artifact(
            provider_root=provider.root,
            provider_receipt_path=provider_receipt,
            snapshot=cast(VerifiedSnapshotArtifact, snapshot),
            config=config,
            artifact_roots=artifact_roots,
        )
        if example_id is None
        else verify_development_example_provider_artifact(
            provider_root=provider.root,
            provider_receipt_path=provider_receipt,
            snapshot=cast(VerifiedDevelopmentExampleSnapshotArtifact, snapshot),
            config=config,
            artifact_roots=artifact_roots,
        )
    )
    if fresh_provider != provider:
        raise ValueError("provider bundle drift")
    if (
        upstream_snapshot is None or upstream_snapshot.stage != snapshot_stage
        or upstream_snapshot.scope != "SNAPSHOT"
        or upstream_snapshot.scope_key != snapshot.request.snapshot_request_key
        or upstream_provider is None or upstream_provider.stage != provider_stage
        or upstream_provider.scope != "PROVIDER"
        or upstream_provider.scope_key != provider.manifest.provider_key
    ):
        raise ValueError("upstream receipt identity drift")
    receipt, receipt_sha = _verify_stage_receipt_secure(
        receipt_path=experiment_receipt_path, artifact_roots=artifact_roots
    )
    expected_stage = "experiment-identity" if example_id is None else "development-experiment-identity"
    expected_inputs = _digests(
        (
            snapshot_receipt, snapshot_manifest, provider_receipt, provider_manifest,
        ), artifact_roots,
    )
    expected_outputs = _digests((manifest_path,), artifact_roots)
    if (
        receipt is None or receipt.stage != expected_stage
        or receipt.scope != "EXPERIMENT" or receipt.scope_key != expected_key
        or receipt.inputs != expected_inputs or receipt.outputs != expected_outputs
    ):
        raise ValueError("experiment receipt closure drift")
    return manifest, manifest_sha, receipt_sha


@_label_boundary("LABEL_ARTIFACT_INPUT_INVALID")
def build_label_artifact(
    *, release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    experiment: VerifiedExperimentIdentity, config: LoadedM3Config,
    experiment_spec: ExperimentIdentitySpec, spec: LabelBuildSpec,
    output_root: Path,
) -> LabelArtifactManifest:
    if (
        type(release) is not VerifiedG1Release
        or type(snapshot) is not VerifiedSnapshotArtifact
        or type(experiment) is not VerifiedExperimentIdentity
    ):
        raise ValueError("formal labels require formal inputs")
    source = _formal_label_source(release, snapshot, experiment)
    return _build_labels(
        source=source, config=config, experiment_spec=experiment_spec,
        spec=spec, output_root=output_root,
    )


@_label_boundary("LABEL_ARTIFACT_INPUT_INVALID")
def build_development_example_label_artifact(
    *, release: VerifiedDevelopmentExampleG1Release,
    snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config, experiment_spec: ExperimentIdentitySpec,
    spec: LabelBuildSpec, output_root: Path,
) -> LabelArtifactManifest:
    if (
        type(release) is not VerifiedDevelopmentExampleG1Release
        or type(snapshot) is not VerifiedDevelopmentExampleSnapshotArtifact
        or type(experiment) is not VerifiedDevelopmentExampleExperimentIdentity
        or len({release.manifest.example_id, snapshot.example_id, experiment.example_id}) != 1
    ):
        raise ValueError("development labels require matching inputs")
    source = _development_label_source(release, snapshot, experiment)
    return _build_labels(
        source=source, config=config, experiment_spec=experiment_spec,
        spec=spec, output_root=output_root,
    )


def _build_labels(
    *, source: _LabelSource, config: LoadedM3Config,
    experiment_spec: ExperimentIdentitySpec, spec: LabelBuildSpec,
    output_root: Path,
) -> LabelArtifactManifest:
    _validate_label_spec(source, config, experiment_spec, spec)
    _require_empty_directory(output_root)
    frames, entries = _read_label_inputs(source)
    result = compute_forward_relative_labels(
        bars=frames["bar_1d.parquet"],
        benchmark_bars=frames["benchmark_bar_1d.parquet"],
        eligible_keys=frames["eligible_keys.parquet"],
        calendars=frames["calendar"],
        horizons=[spec.horizon_sessions], benchmark=spec.benchmark,
        label_version=spec.label_version,
    )
    labels = result.labels.sort(["as_of", "horizon_sessions", "symbol"])
    diagnostics = result.diagnostics.sort(["as_of", "horizon_sessions", "reason"])
    _validate_label_frames(labels, diagnostics, spec)
    manifest = _make_label_manifest(
        source=source, spec=spec, labels=labels, diagnostics=diagnostics,
        entries=entries,
        candidate_count=frames["eligible_keys.parquet"].height,
    )
    _write_exclusive(output_root / "labels.parquet", _parquet_bytes(labels))
    _write_exclusive(
        output_root / "diagnostics.parquet", _parquet_bytes(diagnostics)
    )
    _write_exclusive(
        output_root / "label_manifest.json", _canonical_bytes(asdict(manifest))
    )
    if (
        not _read_parquet(output_root / "labels.parquet").equals(labels)
        or not _read_parquet(output_root / "diagnostics.parquet").equals(diagnostics)
        or read_label_artifact_manifest(output_root / "label_manifest.json") != manifest
    ):
        raise ValueError("label output readback drift")
    return manifest


@_label_boundary("LABEL_ARTIFACT_INPUT_INVALID")
def read_label_artifact_manifest(path: Path) -> LabelArtifactManifest:
    return _parse_label_artifact_manifest(_read_regular(path))


def _parse_label_artifact_manifest(raw: bytes) -> LabelArtifactManifest:
    payload = _strict_json(raw)
    expected = {
        "schema_version", "experiment_key", "experiment_manifest_sha256",
        "g1_release_id", "g1_release_manifest_sha256", "snapshot_id",
        "snapshot_manifest_sha256", "horizon_sessions", "benchmark",
        "label_version", "label_build_code_version", "eligible_keys_sha256",
        "bars_sha256", "session_calendar_sha256", "benchmark_bars_sha256",
        "labels_sha256", "labels_row_count", "label_key_sha256",
        "diagnostics_sha256", "diagnostics_row_count", "diagnostic_key_sha256",
        "candidate_count", "success_count", "diagnostic_count",
    }
    if set(payload) != expected:
        raise ValueError("label manifest fields drift")
    manifest = LabelArtifactManifest(**cast(Any, payload))
    if _canonical_bytes(asdict(manifest)) != raw:
        raise ValueError("label manifest not canonical")
    return manifest


@_label_boundary("LABEL_ARTIFACT_IDENTITY_MISMATCH")
def verify_label_artifact(
    *, label_root: Path, label_receipt_path: Path,
    release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    experiment: VerifiedExperimentIdentity, config: LoadedM3Config,
    experiment_spec: ExperimentIdentitySpec, spec: LabelBuildSpec,
    artifact_roots: Mapping[str, Path],
) -> VerifiedLabelArtifact:
    if (
        type(release) is not VerifiedG1Release
        or type(snapshot) is not VerifiedSnapshotArtifact
        or type(experiment) is not VerifiedExperimentIdentity
    ):
        raise ValueError("formal label verifier requires formal inputs")
    parts = _verify_labels(
        label_root=label_root, label_receipt_path=label_receipt_path,
        source=_formal_label_source(release, snapshot, experiment), config=config,
        experiment_spec=experiment_spec, spec=spec, artifact_roots=artifact_roots,
    )
    return VerifiedLabelArtifact(
        root=label_root.resolve(strict=True), labels=parts[0], diagnostics=parts[1],
        manifest=parts[2], manifest_sha256=parts[3], label_receipt_sha256=parts[4],
    )


@_label_boundary("LABEL_ARTIFACT_IDENTITY_MISMATCH")
def verify_development_example_label_artifact(
    *, label_root: Path, label_receipt_path: Path,
    release: VerifiedDevelopmentExampleG1Release,
    snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config, experiment_spec: ExperimentIdentitySpec,
    spec: LabelBuildSpec,
    artifact_roots: Mapping[str, Path],
) -> VerifiedDevelopmentExampleLabelArtifact:
    if (
        type(release) is not VerifiedDevelopmentExampleG1Release
        or type(snapshot) is not VerifiedDevelopmentExampleSnapshotArtifact
        or type(experiment) is not VerifiedDevelopmentExampleExperimentIdentity
        or len({release.manifest.example_id, snapshot.example_id, experiment.example_id}) != 1
    ):
        raise ValueError("development label verifier requires matching inputs")
    parts = _verify_labels(
        label_root=label_root, label_receipt_path=label_receipt_path,
        source=_development_label_source(release, snapshot, experiment),
        config=config, experiment_spec=experiment_spec, spec=spec,
        artifact_roots=artifact_roots,
    )
    return VerifiedDevelopmentExampleLabelArtifact(
        release_kind="development_example", formal_gate_eligible=False,
        example_id=snapshot.example_id, root=label_root.resolve(strict=True),
        labels=parts[0], diagnostics=parts[1], manifest=parts[2],
        manifest_sha256=parts[3], label_receipt_sha256=parts[4],
    )


def _verify_labels(
    *, label_root: Path, label_receipt_path: Path, source: _LabelSource,
    config: LoadedM3Config, experiment_spec: ExperimentIdentitySpec,
    spec: LabelBuildSpec,
    artifact_roots: Mapping[str, Path],
) -> tuple[pl.DataFrame, pl.DataFrame, LabelArtifactManifest, str, str]:
    _validate_label_spec(source, config, experiment_spec, spec)
    _require_real_directory(label_root)
    if {item.name for item in os.scandir(label_root)} != _LABEL_FILES:
        raise ValueError("label tree closure drift")
    labels = _read_parquet(label_root / "labels.parquet")
    diagnostics = _read_parquet(label_root / "diagnostics.parquet")
    _validate_label_frames(labels, diagnostics, spec)
    manifest_path = label_root / "label_manifest.json"
    manifest_raw = _read_regular(manifest_path)
    manifest = _parse_label_artifact_manifest(manifest_raw)
    input_frames, entries = _read_label_inputs(source)
    rebuilt = compute_forward_relative_labels(
        bars=input_frames["bar_1d.parquet"],
        benchmark_bars=input_frames["benchmark_bar_1d.parquet"],
        eligible_keys=input_frames["eligible_keys.parquet"],
        calendars=input_frames["calendar"], horizons=[spec.horizon_sessions],
        benchmark=spec.benchmark, label_version=spec.label_version,
    )
    if not labels.equals(rebuilt.labels) or not diagnostics.equals(rebuilt.diagnostics):
        raise ValueError("label frame rebuild drift")
    expected = _make_label_manifest(
        source=source, spec=spec, labels=labels, diagnostics=diagnostics,
        entries=entries,
        candidate_count=input_frames["eligible_keys.parquet"].height,
    )
    if manifest != expected:
        raise ValueError("label manifest drift")
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    snapshot_artifact_root = _artifact_root_for(
        source.snapshot_manifest_path, artifact_roots=artifact_roots
    )
    experiment_artifact_root = _artifact_root_for(
        source.experiment_root, artifact_roots=artifact_roots
    )
    snapshot_stage = (
        "snapshot" if source.example_id is None else "development-snapshot"
    )
    experiment_stage = (
        "experiment-identity"
        if source.example_id is None
        else "development-experiment-identity"
    )
    snapshot_receipt_path = (
        snapshot_artifact_root
        / "receipts"
        / snapshot_stage
        / f"{source.snapshot_request_key}.json"
    )
    experiment_receipt_path = (
        experiment_artifact_root
        / "receipts"
        / experiment_stage
        / f"{source.experiment.experiment_key}.json"
    )
    _verify_experiment_receipt_from_source(
        source=source,
        experiment_receipt_path=experiment_receipt_path,
        snapshot_receipt_path=snapshot_receipt_path,
        artifact_roots=artifact_roots,
    )
    receipt, receipt_sha = _verify_stage_receipt_secure(
        receipt_path=label_receipt_path, artifact_roots=artifact_roots
    )
    input_paths = (
        experiment_receipt_path,
        source.experiment_root / "experiment_manifest.json",
        source.release_manifest_path,
        source.artifact_paths["bar_1d.parquet"],
        source.artifact_paths["benchmark_bar_1d.parquet"],
        source.artifact_paths["eligible_keys.parquet"],
        snapshot_receipt_path,
        source.snapshot_manifest_path,
        source.snapshot_calendar_path,
    )
    output_paths = tuple(label_root / name for name in sorted(_LABEL_FILES))
    expected_stage = "labels" if source.example_id is None else "development-labels"
    if (
        receipt is None or receipt.stage != expected_stage
        or receipt.scope != "EXPERIMENT"
        or receipt.scope_key != source.experiment.experiment_key
        or receipt.inputs != _digests(input_paths, artifact_roots)
        or receipt.outputs != _digests(output_paths, artifact_roots)
    ):
        raise ValueError("label receipt closure drift")
    return (
        labels, diagnostics, manifest, manifest_sha,
        receipt_sha,
    )


def _formal_label_source(
    release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    experiment: VerifiedExperimentIdentity,
) -> _LabelSource:
    fresh = verify_g1_release(release=release.release)
    if fresh != release:
        raise ValueError("formal release drift")
    return _LabelSource(
        release_id=release.manifest.release_id,
        release_manifest_sha256=release.manifest_sha256,
        release_manifest_path=release.release.manifest_path,
        artifact_paths=dict(release.artifact_paths),
        release_file_hashes={
            item.path: item.content_sha256 for item in release.manifest.files
        },
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        snapshot_manifest_path=snapshot.root / "manifest.json",
        snapshot_manifest_canonical_bytes=_canonical_contract_bytes(
            asdict(snapshot.manifest)
        ),
        snapshot_session_calendar_sha256=snapshot.manifest.session_calendar_sha256,
        snapshot_calendar_path=snapshot.session_calendar_path,
        snapshot_request_key=snapshot.request.snapshot_request_key,
        snapshot_receipt_sha256=snapshot.snapshot_receipt_sha256,
        experiment_root=experiment.root,
        experiment=experiment.manifest,
        experiment_manifest_sha256=experiment.manifest_sha256,
        experiment_receipt_sha256=experiment.experiment_receipt_sha256,
        example_id=None,
    )


def _development_label_source(
    release: VerifiedDevelopmentExampleG1Release,
    snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
) -> _LabelSource:
    fresh = verify_development_example_g1_release(root=release.release.root)
    if fresh != release:
        raise ValueError("development release drift")
    return _LabelSource(
        release_id=release.manifest.contract_release_id,
        release_manifest_sha256=release.manifest_sha256,
        release_manifest_path=release.release.manifest_path,
        artifact_paths=dict(release.artifact_paths),
        release_file_hashes={
            item.path: item.content_sha256 for item in release.manifest.files
        },
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        snapshot_manifest_path=snapshot.root / "manifest.json",
        snapshot_manifest_canonical_bytes=_canonical_contract_bytes(
            asdict(snapshot.manifest)
        ),
        snapshot_session_calendar_sha256=snapshot.manifest.session_calendar_sha256,
        snapshot_calendar_path=snapshot.session_calendar_path,
        snapshot_request_key=snapshot.request.snapshot_request_key,
        snapshot_receipt_sha256=snapshot.snapshot_receipt_sha256,
        experiment_root=experiment.root,
        experiment=experiment.manifest,
        experiment_manifest_sha256=experiment.manifest_sha256,
        experiment_receipt_sha256=experiment.experiment_receipt_sha256,
        example_id=snapshot.example_id,
    )


def _validate_label_spec(
    source: _LabelSource, config: LoadedM3Config,
    experiment_spec: ExperimentIdentitySpec, spec: LabelBuildSpec,
) -> None:
    if (
        type(config) is not LoadedM3Config
        or type(experiment_spec) is not ExperimentIdentitySpec
        or type(spec) is not LabelBuildSpec
    ):
        raise ValueError("label config/spec invalid")
    labels_cfg = config.section("labels")
    data_cfg = config.section("data")
    expected_experiment_key = (
        compute_experiment_key(
            snapshot_id=source.snapshot_id,
            provider_receipt_sha256=source.experiment.provider_receipt_sha256,
            scientific_config_hash=experiment_spec.scientific_config_sha256,
            code_version=experiment_spec.code_version,
            dependency_fingerprint_sha256=(
                experiment_spec.dependency_fingerprint_sha256
            ),
        )
        if source.example_id is None
        else compute_development_experiment_key(
            example_id=source.example_id,
            snapshot_id=source.snapshot_id,
            provider_receipt_sha256=source.experiment.provider_receipt_sha256,
            scientific_config_sha256=experiment_spec.scientific_config_sha256,
            code_version=experiment_spec.code_version,
            dependency_fingerprint_sha256=(
                experiment_spec.dependency_fingerprint_sha256
            ),
        )
    )
    if (
        spec.experiment_key != source.experiment.experiment_key
        or spec.experiment_manifest_sha256 != source.experiment_manifest_sha256
        or spec.horizon_sessions not in cast(tuple[int, ...], labels_cfg["horizons_sessions"])
        or spec.benchmark != data_cfg["benchmark"]
        or spec.label_version != labels_cfg["label_version"]
        or source.experiment.snapshot_id != source.snapshot_id
        or source.experiment.snapshot_manifest_sha256 != source.snapshot_manifest_sha256
        or experiment_spec.scientific_config_sha256
        != config.scientific_config_sha256
        or source.experiment.scientific_config_sha256
        != experiment_spec.scientific_config_sha256
        or source.experiment.dependency_fingerprint_sha256
        != experiment_spec.dependency_fingerprint_sha256
        or source.experiment.code_version != experiment_spec.code_version
        or source.experiment.experiment_key != expected_experiment_key
    ):
        raise ValueError("label identity/config drift")
    if source.experiment_root.joinpath("experiment_manifest.json").is_file() is False:
        raise ValueError("experiment manifest unavailable")
    if hashlib.sha256(
        _read_regular(source.experiment_root / "experiment_manifest.json")
    ).hexdigest() != source.experiment_manifest_sha256:
        raise ValueError("experiment manifest bytes drift")
    snapshot_manifest_raw = _read_regular(source.snapshot_manifest_path)
    if (
        snapshot_manifest_raw != source.snapshot_manifest_canonical_bytes
        or hashlib.sha256(snapshot_manifest_raw).hexdigest()
        != source.snapshot_manifest_sha256
    ):
        raise ValueError("snapshot manifest bytes drift")


def _read_label_inputs(
    source: _LabelSource,
) -> tuple[dict[str, pl.DataFrame], dict[str, str]]:
    paths = source.artifact_paths
    for name in ("bar_1d.parquet", "benchmark_bar_1d.parquet", "eligible_keys.parquet"):
        if name not in paths:
            raise ValueError("G1 label input missing")
    bars = _read_parquet(paths["bar_1d.parquet"])
    benchmark = _read_parquet(paths["benchmark_bar_1d.parquet"])
    eligible = _read_parquet(paths["eligible_keys.parquet"])
    calendar = _read_parquet(source.snapshot_calendar_path)
    if calendar.columns != ["date"] or calendar.schema["date"] != pl.Date:
        raise ValueError("snapshot calendar schema drift")
    dates = calendar.get_column("date").to_list()
    if not dates or dates != sorted(set(dates)):
        raise ValueError("snapshot calendar order drift")
    calendar_for_labels = pl.DataFrame({
        "market": ["SH"] * len(dates), "date": dates,
        "is_open": [True] * len(dates),
    }).with_columns(pl.col("date").cast(pl.Date))
    entries = dict(source.release_file_hashes)
    for name, frame in (
        ("bar_1d.parquet", bars),
        ("benchmark_bar_1d.parquet", benchmark),
        ("eligible_keys.parquet", eligible),
    ):
        table_name = {
            "bar_1d.parquet": "bar_1d",
            "benchmark_bar_1d.parquet": "benchmark_bar_1d",
            "eligible_keys.parquet": "eligible_keys",
        }[name]
        if clean_table_content_sha256(table_name=table_name, frame=frame) != entries[name]:
            raise ValueError("G1 logical input drift")
    session_sha = _sha256_json([day.isoformat() for day in dates])
    if session_sha != source.snapshot_session_calendar_sha256:
        raise ValueError("snapshot calendar digest drift")
    entries["session_calendar.parquet"] = session_sha
    return {
        "bar_1d.parquet": bars,
        "benchmark_bar_1d.parquet": benchmark,
        "eligible_keys.parquet": eligible,
        "calendar": calendar_for_labels,
    }, entries


def _make_label_manifest(
    *, source: _LabelSource, spec: LabelBuildSpec, labels: pl.DataFrame,
    diagnostics: pl.DataFrame, entries: Mapping[str, str],
    candidate_count: int | None = None,
) -> LabelArtifactManifest:
    diagnostic_count = int(diagnostics.get_column("sample_count").sum() or 0)
    observed = labels.height + diagnostic_count
    expected_candidates = observed if candidate_count is None else candidate_count
    if observed != expected_candidates:
        raise ValueError("label candidate conservation drift")
    return LabelArtifactManifest(
        schema_version="m3-label-artifact-v1",
        experiment_key=source.experiment.experiment_key,
        experiment_manifest_sha256=source.experiment_manifest_sha256,
        g1_release_id=source.release_id,
        g1_release_manifest_sha256=source.release_manifest_sha256,
        snapshot_id=source.snapshot_id,
        snapshot_manifest_sha256=source.snapshot_manifest_sha256,
        horizon_sessions=spec.horizon_sessions,
        benchmark=spec.benchmark,
        label_version=spec.label_version,
        label_build_code_version=spec.label_build_code_version,
        eligible_keys_sha256=entries["eligible_keys.parquet"],
        bars_sha256=entries["bar_1d.parquet"],
        session_calendar_sha256=entries["session_calendar.parquet"],
        benchmark_bars_sha256=entries["benchmark_bar_1d.parquet"],
        labels_sha256=clean_table_content_sha256(
            table_name="m3_label_artifact_labels", frame=labels
        ),
        labels_row_count=labels.height,
        label_key_sha256=_key_hash(
            labels, ("as_of", "symbol", "benchmark", "horizon_sessions", "label_version")
        ),
        diagnostics_sha256=clean_table_content_sha256(
            table_name="m3_label_artifact_diagnostics", frame=diagnostics
        ),
        diagnostics_row_count=diagnostics.height,
        diagnostic_key_sha256=_key_hash(
            diagnostics, ("as_of", "horizon_sessions", "reason")
        ),
        candidate_count=expected_candidates,
        success_count=labels.height,
        diagnostic_count=diagnostic_count,
    )


def _validate_label_frames(
    labels: pl.DataFrame, diagnostics: pl.DataFrame, spec: LabelBuildSpec,
) -> None:
    validated = ForwardReturnLabelSchema.validate(labels)
    if validated.columns != labels.columns or validated.dtypes != labels.dtypes:
        raise ValueError("label frame coercion drift")
    if labels.get_column("horizon_sessions").unique().to_list() not in (
        [], [spec.horizon_sessions],
    ):
        raise ValueError("label horizon drift")
    if labels.get_column("benchmark").unique().to_list() not in ([], [spec.benchmark]):
        raise ValueError("label benchmark drift")
    if labels.get_column("label_version").unique().to_list() not in ([], [spec.label_version]):
        raise ValueError("label version drift")
    if diagnostics.schema != _DIAGNOSTIC_SCHEMA:
        raise ValueError("diagnostics schema drift")
    if diagnostics.get_column("horizon_sessions").unique().to_list() not in (
        [], [spec.horizon_sessions],
    ):
        raise ValueError("diagnostics horizon drift")
    if labels.rows() != labels.sort(["as_of", "horizon_sessions", "symbol"]).rows():
        raise ValueError("labels order drift")
    if diagnostics.rows() != diagnostics.sort(
        ["as_of", "horizon_sessions", "reason"]
    ).rows():
        raise ValueError("diagnostics order drift")
    if diagnostics.get_column("sample_count").min() is not None and cast(
        int, diagnostics.get_column("sample_count").min()
    ) <= 0:
        raise ValueError("diagnostics sample_count invalid")


def _strict_json(raw: bytes) -> dict[str, object]:
    def hook(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(
        raw.decode("utf-8"), object_pairs_hook=hook,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
    )
    if type(value) is not dict:
        raise ValueError("JSON object required")
    return value


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _canonical_contract_bytes(value: object) -> bytes:
    def normalize(item: object) -> object:
        if type(item) is dt.date:
            return item.isoformat()
        if isinstance(item, Mapping):
            return {str(key): normalize(child) for key, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [normalize(child) for child in item]
        return item

    return _canonical_bytes(normalize(value))


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _key_hash(frame: pl.DataFrame, columns: tuple[str, ...]) -> str:
    rows = []
    for row in frame.select(*columns).iter_rows():
        rows.append([
            item.isoformat() if type(item) is dt.date else item for item in row
        ])
    return _sha256_json(rows)


def _parquet_bytes(frame: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.write_parquet(
        buffer, compression="zstd", compression_level=3, statistics=True,
        row_group_size=65536, use_pyarrow=False,
    )
    return buffer.getvalue()


def _read_parquet(path: Path) -> pl.DataFrame:
    return pl.read_parquet(io.BytesIO(_read_regular(path)))


def _read_regular(path: Path) -> bytes:
    _reject_parent_links(path.parent)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        _validate_open_regular(before)
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read()
        after = os.fstat(descriptor)
        _validate_open_regular(after)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            getattr(before, "st_mtime_ns", None),
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            getattr(after, "st_mtime_ns", None),
        )
        if identity_before != identity_after or len(raw) != after.st_size:
            raise ValueError("artifact changed while reading")
        _reject_parent_links(path.parent)
        current = os.lstat(path)
        if (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino):
            raise ValueError("artifact path identity changed")
        return raw
    finally:
        os.close(descriptor)


def _validate_open_regular(info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("artifact is not a regular file")
    if getattr(info, "st_nlink", 1) != 1:
        raise ValueError("artifact link count invalid")
    if getattr(info, "st_file_attributes", 0) & getattr(
        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
    ):
        raise ValueError("artifact reparse point invalid")


def _reject_parent_links(path: Path) -> None:
    current = path.absolute()
    while True:
        info = os.lstat(current)
        if stat.S_ISLNK(info.st_mode) or getattr(
            info, "st_file_attributes", 0
        ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise ValueError("artifact parent link invalid")
        if current == current.parent:
            break
        current = current.parent


def _require_real_directory(path: Path) -> None:
    _reject_parent_links(path.parent)
    info = os.lstat(path)
    if (
        not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    ):
        raise ValueError("artifact directory invalid")


def _require_empty_directory(path: Path) -> None:
    _require_real_directory(path)
    if any(path.iterdir()):
        raise ValueError("artifact output must be empty")


def _write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
        0o644,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _artifact_root_for(
    path: Path, *, artifact_roots: Mapping[str, Path]
) -> Path:
    _, root = select_artifact_root(path, artifact_roots=artifact_roots)
    return root


def _digests(
    paths: Sequence[Path], artifact_roots: Mapping[str, Path],
) -> tuple[ArtifactDigest, ...]:
    output: list[ArtifactDigest] = []
    for path in paths:
        raw = _read_regular(path)
        alias, root = select_artifact_root(path, artifact_roots=artifact_roots)
        absolute = Path(os.path.abspath(path))
        output.append(ArtifactDigest(
            root_alias=alias, relative_path=absolute.relative_to(root).as_posix(),
            size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
        ))
    return tuple(sorted(output, key=lambda item: (item.root_alias, item.relative_path)))
