"""Crash-safe local tracking journal and a lazy MLflow adapter for M3."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from quant.data._journal_lock import hold_journal_writer_lock
from quant.data.m3_release import VerifiedG1Release
from quant.research.m3.config import LoadedM3Config, canonical_tracking_target_key
from quant.research.m3.contracts import (
    AShareScenarioMetricsV1,
    EvaluationMetricsV1,
    VerifiedBacktestArtifact,
    VerifiedBacktestPlanArtifact,
    VerifiedEvaluationArtifact,
    VerifiedExperimentIdentity,
    VerifiedTargetArtifact,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleBacktestArtifact,
    VerifiedDevelopmentExampleEvaluationArtifact,
)
from quant.research.m3.evaluate import (
    EvaluationFreshVerificationContext,
    verify_evaluation_artifact,
)
from quant.research.m3.run_state import ArtifactDigest, select_artifact_root

if TYPE_CHECKING:
    from quant.backtest.a_share_reporting import (
        BacktestArtifactFreshVerificationContext,
    )

_HEX64 = frozenset("0123456789abcdef")
_REQUEST_KEYS = (
    "schema_version",
    "tracking_target_key",
    "work_key",
    "params",
    "tags",
    "metrics",
    "artifacts",
)
_MARKER_KEYS = (
    "schema_version",
    "tracking_target_key",
    "tracking_key",
    "request_sha256",
    "mlflow_run_id",
    "artifact_digest_sha256",
)
_FORBIDDEN_KEY_FRAGMENTS = (
    "token",
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "credential",
    "private_key",
)
_PROTECTED_TAGS = frozenset(
    {
        "quant_tracking_key",
        "quant_tracking_target_key",
        "quant_request_sha256",
        "quant_artifact_digest_sha256",
        "quant_work_key",
    }
)
_FORMAL_PARAM_KEYS = (
    "backtest_manifest_sha256",
    "backtest_plan_manifest_sha256",
    "backtest_receipt_sha256",
    "eligible_keys_sha256",
    "evaluation_dates_sha256",
    "evaluation_manifest_sha256",
    "evaluation_receipt_sha256",
    "experiment_key",
    "feature_manifest_sha256",
    "fold",
    "fold_plan_manifest_sha256",
    "g1_release_id",
    "g1_release_manifest_sha256",
    "horizon_sessions",
    "label_manifest_sha256",
    "model",
    "model_version",
    "prediction_manifest_sha256",
    "scenario_count",
    "scientific_config_sha256",
    "target_manifest_sha256",
    "work_key",
)
_FORMAL_EVALUATION_FILES = (
    "daily_ic.parquet",
    "evaluation_manifest.json",
    "metrics.json",
)
_FORMAL_UPLOAD_BACKTEST_RELATIVE = (
    "0p5x/manifest.json",
    "0p5x/metrics.json",
    "1p0x/manifest.json",
    "1p0x/metrics.json",
    "2p0x/manifest.json",
    "2p0x/metrics.json",
    "backtest_manifest.json",
    "backtest_metrics.json",
)
_FORMAL_SCENARIO_ORDER: tuple[Literal["0p5x", "1p0x", "2p0x"], ...] = (
    "0p5x",
    "1p0x",
    "2p0x",
)
_FORMAL_CONTEXT_ERROR = "M3_FORMAL_TRACKING_CONTEXT_INVALID"
TrackingStatus = Literal["RUNNING", "FINISHED", "FAILED", "KILLED"]


@dataclass(frozen=True)
class FormalTrackingFreshVerificationContext:
    """Process-local inputs required to freshly verify formal tracking sources."""

    evaluation_context: EvaluationFreshVerificationContext
    evaluation_receipt_path: Path
    target: VerifiedTargetArtifact
    plan: VerifiedBacktestPlanArtifact
    release: VerifiedG1Release
    experiment: VerifiedExperimentIdentity
    backtest_context: BacktestArtifactFreshVerificationContext
    backtest_receipt_path: Path

    def __post_init__(self) -> None:
        from quant.backtest.a_share_reporting import (
            BacktestArtifactFreshVerificationContext as BacktestFreshContext,
        )

        if (
            type(self.evaluation_context) is not EvaluationFreshVerificationContext
            or not isinstance(self.evaluation_receipt_path, Path)
            or type(self.target) is not VerifiedTargetArtifact
            or type(self.plan) is not VerifiedBacktestPlanArtifact
            or type(self.release) is not VerifiedG1Release
            or type(self.experiment) is not VerifiedExperimentIdentity
            or type(self.backtest_context) is not BacktestFreshContext
            or not isinstance(self.backtest_receipt_path, Path)
        ):
            raise ValueError(_FORMAL_CONTEXT_ERROR)

    def __reduce__(self) -> Any:
        raise TypeError(_FORMAL_CONTEXT_ERROR)

@dataclass(frozen=True)
class TrackingRequestV1:
    schema_version: Literal["m3-tracking-request-v1"]
    tracking_target_key: str
    work_key: str
    params: tuple[tuple[str, str], ...]
    tags: tuple[tuple[str, str], ...]
    metrics: tuple[tuple[str, float], ...]
    artifacts: tuple[ArtifactDigest, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "m3-tracking-request-v1":
            raise ValueError("tracking request schema invalid")
        _require_hex64("tracking_target_key", self.tracking_target_key)
        _require_hex64("work_key", self.work_key)
        _validate_string_pairs(self.params, label="params")
        _validate_string_pairs(self.tags, label="tags")
        if any(key in _PROTECTED_TAGS for key, _ in self.tags):
            raise ValueError("tracking request contains protected tag")
        _validate_metric_pairs(self.metrics)
        _validate_artifacts(self.artifacts)


@dataclass(frozen=True)
class TrackingMarkerV1:
    schema_version: Literal["m3-tracking-marker-v1"]
    tracking_target_key: str
    tracking_key: str
    request_sha256: str
    mlflow_run_id: str
    artifact_digest_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-tracking-marker-v1":
            raise ValueError("tracking marker schema invalid")
        for name in (
            "tracking_target_key",
            "tracking_key",
            "request_sha256",
            "artifact_digest_sha256",
        ):
            _require_hex64(name, getattr(self, name))
        _require_stable_string("mlflow_run_id", self.mlflow_run_id)


@dataclass(frozen=True)
class RemoteTrackingRunV1:
    run_id: str
    status: TrackingStatus
    tags: Mapping[str, str]

    def __post_init__(self) -> None:
        _require_stable_string("run_id", self.run_id)
        if self.status not in {"RUNNING", "FINISHED", "FAILED", "KILLED"}:
            raise ValueError("remote tracking status invalid")
        if not isinstance(self.tags, Mapping) or any(
            type(key) is not str or type(value) is not str
            for key, value in self.tags.items()
        ):
            raise ValueError("remote tracking tags invalid")


class TrackingClientProtocol(Protocol):
    """Small fake-friendly boundary around MLflow client operations."""

    def find_runs(
        self, *, experiment_name: str, tracking_key: str
    ) -> Sequence[RemoteTrackingRunV1]: ...

    def create_run(self, *, experiment_name: str, tags: Mapping[str, str]) -> str: ...

    def log_params(self, *, run_id: str, params: Mapping[str, str]) -> None: ...

    def log_metrics(self, *, run_id: str, metrics: Mapping[str, float]) -> None: ...

    def log_artifact(
        self, *, run_id: str, local_path: Path, artifact_path: str
    ) -> None: ...

    def finish_run(self, *, run_id: str) -> None: ...


def formal_tracking_input_paths(
    *,
    evaluation: VerifiedEvaluationArtifact,
    backtest: VerifiedBacktestArtifact,
    fresh_context: FormalTrackingFreshVerificationContext,
) -> tuple[Path, ...]:
    """Return the exact unordered physical 34-file formal tracking input closure."""
    from quant.backtest.a_share_reporting import backtest_artifact_output_relative_paths

    if (
        type(evaluation) is not VerifiedEvaluationArtifact
        or type(backtest) is not VerifiedBacktestArtifact
        or type(fresh_context) is not FormalTrackingFreshVerificationContext
    ):
        raise ValueError("formal tracking input identity invalid")
    evaluation_paths = tuple(
        Path(os.path.abspath(evaluation.root / name))
        for name in _FORMAL_EVALUATION_FILES
    )
    backtest_paths = tuple(
        Path(os.path.abspath(backtest.root / name))
        for name in backtest_artifact_output_relative_paths()
    )
    result = (
        *evaluation_paths,
        Path(os.path.abspath(fresh_context.evaluation_receipt_path)),
        *backtest_paths,
        Path(os.path.abspath(fresh_context.backtest_receipt_path)),
    )
    if len(result) != 34 or len(set(result)) != 34:
        raise ValueError("formal tracking input closure invalid")
    return result


def formal_tracking_upload_paths(
    *,
    evaluation: VerifiedEvaluationArtifact,
    backtest: VerifiedBacktestArtifact,
) -> tuple[Path, ...]:
    """Return the exact 11-file MLflow upload allowlist for formal tracking."""
    if (
        type(evaluation) is not VerifiedEvaluationArtifact
        or type(backtest) is not VerifiedBacktestArtifact
    ):
        raise ValueError("formal tracking upload identity invalid")
    evaluation_paths = tuple(
        Path(os.path.abspath(evaluation.root / name))
        for name in _FORMAL_EVALUATION_FILES
    )
    backtest_paths = tuple(
        Path(os.path.abspath(backtest.root / name))
        for name in _FORMAL_UPLOAD_BACKTEST_RELATIVE
    )
    result = (*evaluation_paths, *backtest_paths)
    if len(result) != 11 or len(set(result)) != 11:
        raise ValueError("formal tracking upload closure invalid")
    return result


def build_formal_tracking_request(
    *,
    evaluation: VerifiedEvaluationArtifact,
    backtest: VerifiedBacktestArtifact,
    config: LoadedM3Config,
    fresh_context: FormalTrackingFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> TrackingRequestV1:
    """Build a secret-free formal tracking request from freshly verified work artifacts."""
    fresh_evaluation, fresh_backtest = _fresh_formal_tracking_sources(
        evaluation=evaluation,
        backtest=backtest,
        config=config,
        fresh_context=fresh_context,
        artifact_roots=artifact_roots,
    )
    return _build_formal_tracking_request_from_fresh(
        evaluation=fresh_evaluation,
        backtest=fresh_backtest,
        config=config,
        artifact_roots=artifact_roots,
    )


def build_tracking_request(
    *,
    tracking_target_key: str,
    evaluation: VerifiedDevelopmentExampleEvaluationArtifact | None = None,
    backtest: VerifiedDevelopmentExampleBacktestArtifact | None = None,
    params: Mapping[str, object] | None = None,
    tags: Mapping[str, object] | None = None,
) -> TrackingRequestV1:
    """Build a secret-free request from verified development work artifacts."""
    if evaluation is None and backtest is None:
        raise ValueError("tracking requires a verified work artifact")
    if evaluation is not None and type(evaluation) is not VerifiedDevelopmentExampleEvaluationArtifact:
        raise ValueError("evaluation must be verified development artifact")
    if backtest is not None and type(backtest) is not VerifiedDevelopmentExampleBacktestArtifact:
        raise ValueError("backtest must be verified development artifact")

    works = {
        item.manifest.work_key
        for item in (evaluation, backtest)
        if item is not None
    }
    examples = {
        item.example_id for item in (evaluation, backtest) if item is not None
    }
    if len(works) != 1 or len(examples) != 1:
        raise ValueError("tracking work artifact identity mismatch")
    work_key = next(iter(works))
    example_id = next(iter(examples))

    base_params: dict[str, object] = {"work_key": work_key}
    base_tags: dict[str, object] = {
        "release_kind": "development_example",
        "formal_gate_eligible": "false",
        "example_id": example_id,
    }
    metric_values: dict[str, float] = {}
    artifacts: list[ArtifactDigest] = []
    if evaluation is not None:
        base_params.update(
            {
                "fold": evaluation.manifest.fold,
                "horizon_sessions": evaluation.manifest.horizon_sessions,
                "model": evaluation.manifest.model,
                "model_version": evaluation.manifest.model_version,
            }
        )
        metric_values.update(_numeric_metrics("evaluation", evaluation.metrics))
        artifacts.extend(
            _artifact_digests(
                "evaluation",
                evaluation.root,
                ("metrics.json", "manifest.json"),
            )
        )
    if backtest is not None:
        base_params["scenario_count"] = len(backtest.metrics.scenarios)
        for scenario in backtest.metrics.scenarios:
            metric_values.update(
                _numeric_metrics(f"backtest.{scenario.scenario}", scenario)
            )
        artifacts.extend(
            _artifact_digests(
                "backtest",
                backtest.root,
                (
                    "backtest_metrics.json",
                    "backtest_manifest.json",
                    "0p5x/metrics.json",
                    "0p5x/manifest.json",
                    "1p0x/metrics.json",
                    "1p0x/manifest.json",
                    "2p0x/metrics.json",
                    "2p0x/manifest.json",
                ),
            )
        )
    _merge_unique(base_params, params, label="params")
    _merge_unique(base_tags, tags, label="tags")
    _assert_safe_value(base_params, "params")
    _assert_safe_value(base_tags, "tags")
    return TrackingRequestV1(
        schema_version="m3-tracking-request-v1",
        tracking_target_key=tracking_target_key,
        work_key=work_key,
        params=tuple(sorted((key, _stringify(value)) for key, value in base_params.items())),
        tags=tuple(sorted((key, _stringify(value)) for key, value in base_tags.items())),
        metrics=tuple(sorted(metric_values.items())),
        artifacts=tuple(sorted(artifacts, key=_artifact_key)),
    )


def compute_tracking_key(*, work_key: str, request_sha256: str) -> str:
    """Return the sole tracking-run identity derived from work and request."""
    payload = [
        "m3-tracking-key-v1",
        _require_hex64("work_key", work_key),
        _require_hex64("request_sha256", request_sha256),
    ]
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def publish_tracking_request(*, path: Path, request: TrackingRequestV1) -> str:
    if type(request) is not TrackingRequestV1:
        raise ValueError("tracking request type invalid")
    raw = _canonical_bytes(_request_mapping(request))
    _publish_no_clobber(path, raw)
    return hashlib.sha256(raw).hexdigest()


def read_tracking_request(path: Path) -> TrackingRequestV1:
    raw = _read_regular(path)
    payload = _strict_json(raw, _REQUEST_KEYS)
    request = TrackingRequestV1(
        schema_version=payload["schema_version"],
        tracking_target_key=payload["tracking_target_key"],
        work_key=payload["work_key"],
        params=_parse_pairs(payload["params"], float_values=False),
        tags=_parse_pairs(payload["tags"], float_values=False),
        metrics=_parse_pairs(payload["metrics"], float_values=True),
        artifacts=_parse_artifacts(payload["artifacts"]),
    )
    if raw != _canonical_bytes(_request_mapping(request)):
        raise ValueError("tracking request is not canonical")
    return request


def publish_tracking_marker(*, path: Path, marker: TrackingMarkerV1) -> None:
    if type(marker) is not TrackingMarkerV1:
        raise ValueError("tracking marker type invalid")
    _publish_no_clobber(path, _canonical_bytes(asdict(marker)))


def read_tracking_marker(path: Path) -> TrackingMarkerV1:
    raw = _read_regular(path)
    payload = _strict_json(raw, _MARKER_KEYS)
    marker = TrackingMarkerV1(**cast(Any, payload))
    if raw != _canonical_bytes(asdict(marker)):
        raise ValueError("tracking marker is not canonical")
    return marker


def register_tracking_request(
    *,
    request: TrackingRequestV1,
    request_path: Path,
    marker_path: Path,
    tracking_uri: str,
    experiment_name: str,
    artifact_roots: Mapping[str, Path],
    client: TrackingClientProtocol | None = None,
) -> TrackingMarkerV1:
    """Idempotently register one request, recovering only an exact FINISHED run."""
    target_key = canonical_tracking_target_key(
        tracking_uri=tracking_uri,
        experiment_name=experiment_name,
    )
    if target_key != request.tracking_target_key:
        raise ValueError("tracking target identity mismatch")
    request_sha = publish_tracking_request(path=request_path, request=request)
    tracking_key = compute_tracking_key(
        work_key=request.work_key, request_sha256=request_sha
    )
    artifact_sha = _artifact_digest_sha256(request.artifacts)
    roots = _validate_artifact_roots(artifact_roots)
    _verify_artifacts(request.artifacts, roots)
    remote = client or create_mlflow_tracking_client(tracking_uri=tracking_uri)
    lock_root = marker_path.parent / ".tracking-locks" / target_key / tracking_key
    lock_root.mkdir(parents=True, exist_ok=True)
    with hold_journal_writer_lock(journal_root=lock_root.resolve(strict=True)):
        local_marker: TrackingMarkerV1 | None = None
        if marker_path.exists() or marker_path.is_symlink():
            local_marker = read_tracking_marker(marker_path)
            expected_marker_identity = (
                target_key,
                tracking_key,
                request_sha,
                artifact_sha,
            )
            actual_marker_identity = (
                local_marker.tracking_target_key,
                local_marker.tracking_key,
                local_marker.request_sha256,
                local_marker.artifact_digest_sha256,
            )
            if actual_marker_identity != expected_marker_identity:
                raise ValueError("local tracking marker identity conflict")
        marker = _register_remote_locked(
            request=request,
            request_sha=request_sha,
            tracking_key=tracking_key,
            artifact_sha=artifact_sha,
            experiment_name=experiment_name,
            roots=roots,
            remote=remote,
            local_marker=local_marker,
        )
        publish_tracking_marker(path=marker_path, marker=marker)
        return marker


def register_remote_tracking_run(
    *,
    request: TrackingRequestV1,
    request_sha256: str,
    tracking_uri: str,
    experiment_name: str,
    artifact_roots: Mapping[str, Path],
    lock_root: Path,
    client: TrackingClientProtocol | None = None,
) -> TrackingMarkerV1:
    """Idempotently register one request remotely without writing journal files."""
    if type(request) is not TrackingRequestV1 or not isinstance(lock_root, Path):
        raise ValueError("remote tracking registration input invalid")
    expected_sha = hashlib.sha256(
        _canonical_bytes(_request_mapping(request))
    ).hexdigest()
    if (
        type(request_sha256) is not str
        or request_sha256 != expected_sha
        or len(request_sha256) != 64
    ):
        raise ValueError("tracking request digest mismatch")
    target_key = canonical_tracking_target_key(
        tracking_uri=tracking_uri,
        experiment_name=experiment_name,
    )
    if target_key != request.tracking_target_key:
        raise ValueError("tracking target identity mismatch")
    tracking_key = compute_tracking_key(
        work_key=request.work_key, request_sha256=request_sha256
    )
    artifact_sha = _artifact_digest_sha256(request.artifacts)
    roots = _validate_artifact_roots(artifact_roots)
    _verify_artifacts(request.artifacts, roots)
    remote = client or create_mlflow_tracking_client(tracking_uri=tracking_uri)
    lock_root.mkdir(parents=True, exist_ok=True)
    with hold_journal_writer_lock(journal_root=lock_root.resolve(strict=True)):
        return _register_remote_locked(
            request=request,
            request_sha=request_sha256,
            tracking_key=tracking_key,
            artifact_sha=artifact_sha,
            experiment_name=experiment_name,
            roots=roots,
            remote=remote,
            local_marker=None,
        )


def create_mlflow_tracking_client(*, tracking_uri: str) -> TrackingClientProtocol:
    """Import MLflow only when a real remote client is explicitly requested."""
    from mlflow.tracking import MlflowClient  # type: ignore[import-not-found]

    return _MlflowClientAdapter(MlflowClient(tracking_uri=tracking_uri))


class _MlflowClientAdapter:
    def __init__(self, client: Any) -> None:
        self._client = client

    def _experiment_id(self, name: str) -> str:
        experiment = self._client.get_experiment_by_name(name)
        if experiment is None:
            return cast(str, self._client.create_experiment(name))
        return cast(str, experiment.experiment_id)

    def find_runs(
        self, *, experiment_name: str, tracking_key: str
    ) -> Sequence[RemoteTrackingRunV1]:
        experiment = self._client.get_experiment_by_name(experiment_name)
        if experiment is None:
            return ()
        escaped = tracking_key.replace("'", "\\'")
        runs = self._client.search_runs(
            experiment_ids=[experiment.experiment_id],
            filter_string=f"tags.quant_tracking_key = '{escaped}'",
            max_results=2,
        )
        return tuple(
            RemoteTrackingRunV1(
                run_id=run.info.run_id,
                status=run.info.status,
                tags=dict(run.data.tags),
            )
            for run in runs
        )

    def create_run(self, *, experiment_name: str, tags: Mapping[str, str]) -> str:
        run = self._client.create_run(
            experiment_id=self._experiment_id(experiment_name), tags=dict(tags)
        )
        return cast(str, run.info.run_id)

    def log_params(self, *, run_id: str, params: Mapping[str, str]) -> None:
        for key, value in params.items():
            self._client.log_param(run_id, key, value)

    def log_metrics(self, *, run_id: str, metrics: Mapping[str, float]) -> None:
        for key, value in metrics.items():
            self._client.log_metric(run_id, key, value)

    def log_artifact(
        self, *, run_id: str, local_path: Path, artifact_path: str
    ) -> None:
        self._client.log_artifact(run_id, str(local_path), artifact_path)

    def finish_run(self, *, run_id: str) -> None:
        self._client.set_terminated(run_id, status="FINISHED")


def log_m3_run(
    *,
    tracking_uri: str,
    experiment_name: str,
    params: Mapping[str, object],
    metrics: Mapping[str, float],
    artifacts: Sequence[Path],
    tags: Mapping[str, str],
) -> str:
    """Legacy thin logging entrypoint; retained for callers outside G8."""
    _assert_safe_value(params, "params")
    _assert_safe_value(tags, "tags")
    if any(type(value) is not float or not math.isfinite(value) for value in metrics.values()):
        raise ValueError("metrics must contain finite exact floats")
    for path in artifacts:
        if not path.is_file():
            raise FileNotFoundError("tracking artifact does not exist")
    import mlflow  # type: ignore[import-not-found]

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)
    with mlflow.start_run() as run:
        mlflow.log_params({key: _stringify(value) for key, value in params.items()})
        mlflow.log_metrics(dict(metrics))
        for key, value in tags.items():
            mlflow.set_tag(key, value)
        for path in artifacts:
            mlflow.log_artifact(str(path))
        return cast(str, run.info.run_id)


def _register_remote_locked(
    *,
    request: TrackingRequestV1,
    request_sha: str,
    tracking_key: str,
    artifact_sha: str,
    experiment_name: str,
    roots: Mapping[str, Path],
    remote: TrackingClientProtocol,
    local_marker: TrackingMarkerV1 | None,
) -> TrackingMarkerV1:
    expected_tags = {
        "quant_tracking_key": tracking_key,
        "quant_tracking_target_key": request.tracking_target_key,
        "quant_request_sha256": request_sha,
        "quant_artifact_digest_sha256": artifact_sha,
        "quant_work_key": request.work_key,
    }
    matches = tuple(
        remote.find_runs(
            experiment_name=experiment_name,
            tracking_key=tracking_key,
        )
    )
    if len(matches) > 1:
        raise ValueError("multiple remote tracking runs")
    if local_marker is not None and not matches:
        raise ValueError("local tracking marker has no remote run")
    if matches:
        run = matches[0]
        _validate_remote_run(run, {**dict(request.tags), **expected_tags})
        if local_marker is not None and run.run_id != local_marker.mlflow_run_id:
            raise ValueError("local and remote tracking run conflict")
        return _marker(
            request=request,
            tracking_key=tracking_key,
            request_sha=request_sha,
            artifact_sha=artifact_sha,
            run_id=run.run_id,
        )

    run_id = remote.create_run(
        experiment_name=experiment_name,
        tags={**dict(request.tags), **expected_tags},
    )
    _require_stable_string("mlflow_run_id", run_id)
    remote.log_params(run_id=run_id, params=dict(request.params))
    remote.log_metrics(run_id=run_id, metrics=dict(request.metrics))
    for digest in request.artifacts:
        local = roots[digest.root_alias] / PurePosixPath(digest.relative_path)
        parent = PurePosixPath(digest.relative_path).parent.as_posix()
        artifact_path = (
            digest.root_alias if parent == "." else f"{digest.root_alias}/{parent}"
        )
        remote.log_artifact(
            run_id=run_id,
            local_path=local,
            artifact_path=artifact_path,
        )
    remote.finish_run(run_id=run_id)
    return _marker(
        request=request,
        tracking_key=tracking_key,
        request_sha=request_sha,
        artifact_sha=artifact_sha,
        run_id=run_id,
    )


def _fresh_formal_tracking_sources(
    *,
    evaluation: VerifiedEvaluationArtifact,
    backtest: VerifiedBacktestArtifact,
    config: LoadedM3Config,
    fresh_context: FormalTrackingFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> tuple[VerifiedEvaluationArtifact, VerifiedBacktestArtifact]:
    from quant.backtest.a_share_reporting import verify_backtest_artifact

    if (
        type(evaluation) is not VerifiedEvaluationArtifact
        or type(backtest) is not VerifiedBacktestArtifact
        or type(config) is not LoadedM3Config
        or type(fresh_context) is not FormalTrackingFreshVerificationContext
        or not isinstance(artifact_roots, Mapping)
        or not artifact_roots
    ):
        raise ValueError("formal tracking fresh input invalid")
    evaluation_context = fresh_context.evaluation_context
    fresh_evaluation = verify_evaluation_artifact(
        root=evaluation.root,
        receipt_path=fresh_context.evaluation_receipt_path,
        release=evaluation_context.release,
        snapshot=evaluation_context.snapshot,
        snapshot_spec=evaluation_context.snapshot_spec,
        provider=evaluation_context.provider,
        provider_spec=evaluation_context.provider_spec,
        experiment=evaluation_context.experiment,
        experiment_spec=evaluation_context.experiment_spec,
        folds=evaluation_context.folds,
        fold_spec=evaluation_context.fold_spec,
        feature=evaluation_context.feature,
        feature_spec=evaluation_context.feature_spec,
        label=evaluation_context.label,
        label_spec=evaluation_context.label_spec,
        alignment=evaluation_context.alignment,
        alignment_spec=evaluation_context.alignment_spec,
        model=evaluation_context.model,
        model_spec=evaluation_context.model_spec,
        prediction=evaluation_context.prediction,
        prediction_spec=evaluation_context.prediction_spec,
        config=config,
        spec=evaluation_context.evaluation_spec,
        upstream_paths=evaluation_context.evaluation_upstream_paths,
        artifact_roots=artifact_roots,
    )
    fresh_backtest = verify_backtest_artifact(
        root=backtest.root,
        receipt_path=fresh_context.backtest_receipt_path,
        target=fresh_context.target,
        plan=fresh_context.plan,
        release=fresh_context.release,
        experiment=fresh_context.experiment,
        config=config,
        fresh_context=fresh_context.backtest_context,
        artifact_roots=artifact_roots,
    )
    _assert_fresh_evaluation_matches(evaluation, fresh_evaluation)
    _assert_fresh_backtest_matches(backtest, fresh_backtest)
    _assert_formal_tracking_identity_chain(
        evaluation=fresh_evaluation,
        backtest=fresh_backtest,
        config=config,
        fresh_context=fresh_context,
    )
    return fresh_evaluation, fresh_backtest


def _assert_fresh_evaluation_matches(
    outer: VerifiedEvaluationArtifact,
    fresh: VerifiedEvaluationArtifact,
) -> None:
    if (
        type(fresh) is not VerifiedEvaluationArtifact
        or fresh.root.resolve(strict=True) != outer.root.resolve(strict=True)
        or not fresh.daily.equals(outer.daily)
        or fresh.metrics != outer.metrics
        or fresh.manifest != outer.manifest
        or fresh.manifest_sha256 != outer.manifest_sha256
        or fresh.evaluation_receipt_sha256 != outer.evaluation_receipt_sha256
    ):
        raise ValueError("formal tracking evaluation fresh mismatch")


def _assert_fresh_backtest_matches(
    outer: VerifiedBacktestArtifact,
    fresh: VerifiedBacktestArtifact,
) -> None:
    if (
        type(fresh) is not VerifiedBacktestArtifact
        or fresh.root.resolve(strict=True) != outer.root.resolve(strict=True)
        or fresh.metrics != outer.metrics
        or fresh.manifest != outer.manifest
        or fresh.manifest_sha256 != outer.manifest_sha256
        or fresh.backtest_receipt_sha256 != outer.backtest_receipt_sha256
    ):
        raise ValueError("formal tracking backtest fresh mismatch")


def _assert_formal_tracking_identity_chain(
    *,
    evaluation: VerifiedEvaluationArtifact,
    backtest: VerifiedBacktestArtifact,
    config: LoadedM3Config,
    fresh_context: FormalTrackingFreshVerificationContext,
) -> None:
    evaluation_manifest = evaluation.manifest
    backtest_manifest = backtest.manifest
    target_manifest = fresh_context.target.manifest
    plan_manifest = fresh_context.plan.manifest
    evaluation_context = fresh_context.evaluation_context
    facts = fresh_context.backtest_context.facts_fresh_context
    if (
        evaluation_manifest.work_key != backtest_manifest.work_key
        or evaluation_manifest.experiment_key != backtest_manifest.experiment_key
        or evaluation_manifest.scientific_config_sha256
        != backtest_manifest.scientific_config_sha256
        or evaluation_manifest.fold != target_manifest.fold
        or evaluation_manifest.horizon_sessions != target_manifest.horizon_sessions
        or evaluation_manifest.model != target_manifest.model
        or evaluation_manifest.model_version != target_manifest.model_version
        or plan_manifest.work_key != backtest_manifest.work_key
        or plan_manifest.fold != target_manifest.fold
        or plan_manifest.horizon_sessions != target_manifest.horizon_sessions
        or plan_manifest.experiment_key != backtest_manifest.experiment_key
        or plan_manifest.scientific_config_sha256
        != backtest_manifest.scientific_config_sha256
        or target_manifest.work_key != backtest_manifest.work_key
        or target_manifest.experiment_key != backtest_manifest.experiment_key
        or target_manifest.scientific_config_sha256
        != backtest_manifest.scientific_config_sha256
        or evaluation_context.release is not fresh_context.release
        or evaluation_context.experiment is not fresh_context.experiment
        or facts.config is not config
        or facts.experiment is not fresh_context.experiment
        or facts.target is not fresh_context.target
        or fresh_context.backtest_context.facts_fresh_context.config.scientific_config_sha256
        != config.scientific_config_sha256
        or evaluation_manifest.scientific_config_sha256 != config.scientific_config_sha256
        or backtest_manifest.scientific_config_sha256 != config.scientific_config_sha256
        or evaluation_context.experiment.manifest.experiment_key
        != evaluation_manifest.experiment_key
        or fresh_context.experiment.manifest.experiment_key
        != evaluation_manifest.experiment_key
        or fresh_context.release.manifest.release_id
        != backtest_manifest.g1_release_id
        or fresh_context.release.manifest_sha256
        != backtest_manifest.g1_release_manifest_sha256
        or evaluation_context.evaluation_spec.work_key != evaluation_manifest.work_key
        or evaluation_context.evaluation_spec.fold != evaluation_manifest.fold
        or evaluation_context.evaluation_spec.horizon_sessions
        != evaluation_manifest.horizon_sessions
        or evaluation_context.evaluation_spec.experiment_key
        != evaluation_manifest.experiment_key
    ):
        raise ValueError("formal tracking identity chain invalid")


def _build_formal_tracking_request_from_fresh(
    *,
    evaluation: VerifiedEvaluationArtifact,
    backtest: VerifiedBacktestArtifact,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
) -> TrackingRequestV1:
    experiment_name = config.section("tracking")["experiment_name"]
    if type(experiment_name) is not str:
        raise ValueError("tracking experiment_name invalid")
    expected_target = canonical_tracking_target_key(
        tracking_uri=config.canonical_tracking_uri,
        experiment_name=experiment_name,
    )
    if config.tracking_target_key != expected_target:
        raise ValueError("tracking target identity mismatch")
    evaluation_manifest = evaluation.manifest
    backtest_manifest = backtest.manifest
    work_key = evaluation_manifest.work_key
    if work_key != backtest_manifest.work_key:
        raise ValueError("formal tracking work identity mismatch")
    params = {
        "backtest_manifest_sha256": backtest.manifest_sha256,
        "backtest_plan_manifest_sha256": backtest_manifest.backtest_plan_manifest_sha256,
        "backtest_receipt_sha256": backtest.backtest_receipt_sha256,
        "eligible_keys_sha256": evaluation_manifest.eligible_keys_sha256,
        "evaluation_dates_sha256": evaluation_manifest.evaluation_dates_sha256,
        "evaluation_manifest_sha256": evaluation.manifest_sha256,
        "evaluation_receipt_sha256": evaluation.evaluation_receipt_sha256,
        "experiment_key": evaluation_manifest.experiment_key,
        "feature_manifest_sha256": evaluation_manifest.feature_manifest_sha256,
        "fold": evaluation_manifest.fold,
        "fold_plan_manifest_sha256": evaluation_manifest.fold_plan_manifest_sha256,
        "g1_release_id": backtest_manifest.g1_release_id,
        "g1_release_manifest_sha256": backtest_manifest.g1_release_manifest_sha256,
        "horizon_sessions": evaluation_manifest.horizon_sessions,
        "label_manifest_sha256": evaluation_manifest.label_manifest_sha256,
        "model": evaluation_manifest.model,
        "model_version": evaluation_manifest.model_version,
        "prediction_manifest_sha256": evaluation_manifest.prediction_manifest_sha256,
        "scenario_count": "3",
        "scientific_config_sha256": evaluation_manifest.scientific_config_sha256,
        "target_manifest_sha256": backtest_manifest.target_manifest_sha256,
        "work_key": work_key,
    }
    if tuple(sorted(params)) != _FORMAL_PARAM_KEYS:
        raise ValueError("formal tracking params closure invalid")
    metric_values: dict[str, float] = {}
    metric_values.update(_formal_numeric_metrics("evaluation", evaluation.metrics))
    scenarios = {
        item.scenario: item for item in backtest.metrics.scenarios
    }
    for scenario in _FORMAL_SCENARIO_ORDER:
        metric_values.update(
            _formal_numeric_metrics(f"backtest.{scenario}", scenarios[scenario])
        )
    artifacts = tuple(
        sorted(
            (
                _digest_path(path, artifact_roots=artifact_roots)
                for path in formal_tracking_upload_paths(
                    evaluation=evaluation,
                    backtest=backtest,
                )
            ),
            key=_artifact_key,
        )
    )
    if len(artifacts) != 11:
        raise ValueError("formal tracking upload digests invalid")
    tags = {
        "formal_gate_eligible": "true",
        "release_kind": "formal",
    }
    _assert_safe_value(params, "params")
    _assert_safe_value(tags, "tags")
    return TrackingRequestV1(
        schema_version="m3-tracking-request-v1",
        tracking_target_key=config.tracking_target_key,
        work_key=work_key,
        params=tuple(
            (key, _stringify(params[key])) for key in _FORMAL_PARAM_KEYS
        ),
        tags=tuple(sorted((key, value) for key, value in tags.items())),
        metrics=tuple(sorted(metric_values.items())),
        artifacts=artifacts,
    )


def _formal_numeric_metrics(prefix: str, value: object) -> dict[str, float]:
    if type(value) not in {EvaluationMetricsV1, AShareScenarioMetricsV1}:
        raise ValueError("formal tracking metrics type invalid")
    result: dict[str, float] = {}
    for field in fields(cast(Any, value)):
        if field.name in {"schema_version", "status_counts", "scenario"}:
            continue
        item = getattr(value, field.name)
        if item is None:
            continue
        if isinstance(item, Decimal):
            raise ValueError("formal tracking metric decimal drift")
        if type(item) is bool or type(item) not in {int, float}:
            continue
        number = float(item)
        if not math.isfinite(number):
            raise ValueError("tracking metric is not finite")
        result[f"{prefix}.{field.name}"] = number
    return result


def _digest_path(
    path: Path,
    *,
    artifact_roots: Mapping[str, Path],
) -> ArtifactDigest:
    absolute = Path(os.path.abspath(path))
    alias, root = select_artifact_root(absolute, artifact_roots=artifact_roots)
    resolved = absolute.resolve(strict=True)
    if os.path.normcase(str(resolved)) != os.path.normcase(str(absolute)):
        raise ValueError("tracking artifact path invalid")
    raw = _read_regular(absolute)
    relative = resolved.relative_to(root).as_posix()
    return ArtifactDigest(
        root_alias=alias,
        relative_path=relative,
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _marker(
    *,
    request: TrackingRequestV1,
    tracking_key: str,
    request_sha: str,
    artifact_sha: str,
    run_id: str,
) -> TrackingMarkerV1:
    return TrackingMarkerV1(
        schema_version="m3-tracking-marker-v1",
        tracking_target_key=request.tracking_target_key,
        tracking_key=tracking_key,
        request_sha256=request_sha,
        mlflow_run_id=run_id,
        artifact_digest_sha256=artifact_sha,
    )


def _validate_remote_run(
    run: RemoteTrackingRunV1, expected_tags: Mapping[str, str]
) -> None:
    if type(run) is not RemoteTrackingRunV1:
        raise ValueError("remote tracking run type invalid")
    if run.status != "FINISHED":
        raise ValueError(f"remote tracking run is {run.status}")
    if any(run.tags.get(key) != value for key, value in expected_tags.items()):
        raise ValueError("remote tracking run content conflict")


def _numeric_metrics(prefix: str, value: object) -> dict[str, float]:
    result: dict[str, float] = {}
    for field in fields(cast(Any, value)):
        item = getattr(value, field.name)
        if item is None or type(item) not in {int, float} or type(item) is bool:
            continue
        number = float(item)
        if not math.isfinite(number):
            raise ValueError("tracking metric is not finite")
        result[f"{prefix}.{field.name}"] = number
    return result


def _artifact_digests(alias: str, root: Path, names: Sequence[str]) -> list[ArtifactDigest]:
    result: list[ArtifactDigest] = []
    for name in names:
        path = root / name
        raw = _read_regular(path)
        result.append(
            ArtifactDigest(
                root_alias=alias,
                relative_path=name,
                size_bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
    return result


def _artifact_digest_sha256(artifacts: tuple[ArtifactDigest, ...]) -> str:
    return hashlib.sha256(
        _canonical_bytes([asdict(item) for item in artifacts])
    ).hexdigest()


def _verify_artifacts(
    artifacts: tuple[ArtifactDigest, ...], roots: Mapping[str, Path]
) -> None:
    for digest in artifacts:
        root = roots.get(digest.root_alias)
        if root is None:
            raise ValueError("tracking artifact root missing")
        raw = _read_regular(root / PurePosixPath(digest.relative_path))
        if len(raw) != digest.size_bytes or hashlib.sha256(raw).hexdigest() != digest.sha256:
            raise ValueError("tracking artifact digest drift")


def _validate_artifact_roots(roots: Mapping[str, Path]) -> dict[str, Path]:
    if not isinstance(roots, Mapping) or not roots:
        raise ValueError("tracking artifact roots invalid")
    result: dict[str, Path] = {}
    for alias, root in roots.items():
        _require_stable_string("artifact root alias", alias)
        if "/" in alias or "\\" in alias or not isinstance(root, Path):
            raise ValueError("tracking artifact roots invalid")
        resolved = root.resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("tracking artifact root invalid")
        result[alias] = resolved
    return result


def _merge_unique(
    target: dict[str, object], values: Mapping[str, object] | None, *, label: str
) -> None:
    if values is None:
        return
    if not isinstance(values, Mapping):
        raise ValueError(f"tracking {label} invalid")
    _assert_safe_value(values, label)
    overlap = set(target) & set(values)
    if overlap:
        raise ValueError(f"tracking {label} conflicts with derived fields")
    target.update(values)


def _validate_string_pairs(value: object, *, label: str) -> None:
    if type(value) is not tuple:
        raise ValueError(f"tracking {label} must be exact tuple")
    previous: str | None = None
    for item in value:
        if type(item) is not tuple or len(item) != 2:
            raise ValueError(f"tracking {label} pair invalid")
        key, text = item
        _require_stable_string(f"{label} key", key)
        _require_stable_string(f"{label} value", text)
        _assert_safe_string(key, f"{label}.key")
        _assert_safe_string(text, f"{label}.{key}")
        if previous is not None and key <= previous:
            raise ValueError(f"tracking {label} not strictly sorted")
        previous = key


def _validate_metric_pairs(value: object) -> None:
    if type(value) is not tuple:
        raise ValueError("tracking metrics must be exact tuple")
    previous: str | None = None
    for item in value:
        if type(item) is not tuple or len(item) != 2:
            raise ValueError("tracking metric pair invalid")
        key, number = item
        _require_stable_string("metric key", key)
        if type(number) is not float or not math.isfinite(number):
            raise ValueError("tracking metric must be finite exact float")
        if previous is not None and key <= previous:
            raise ValueError("tracking metrics not strictly sorted")
        previous = key


def _validate_artifacts(value: object) -> None:
    if type(value) is not tuple or not value:
        raise ValueError("tracking artifacts must be non-empty exact tuple")
    previous: tuple[str, str] | None = None
    for item in value:
        if type(item) is not ArtifactDigest:
            raise ValueError("tracking artifact digest type invalid")
        key = _artifact_key(item)
        if previous is not None and key <= previous:
            raise ValueError("tracking artifacts not strictly sorted")
        previous = key


def _artifact_key(value: ArtifactDigest) -> tuple[str, str]:
    return value.root_alias, value.relative_path


def _request_mapping(request: TrackingRequestV1) -> dict[str, object]:
    return {
        "schema_version": request.schema_version,
        "tracking_target_key": request.tracking_target_key,
        "work_key": request.work_key,
        "params": [list(item) for item in request.params],
        "tags": [list(item) for item in request.tags],
        "metrics": [list(item) for item in request.metrics],
        "artifacts": [asdict(item) for item in request.artifacts],
    }


def _parse_pairs(value: object, *, float_values: bool) -> Any:
    if type(value) is not list:
        raise ValueError("tracking pair list invalid")
    result: list[tuple[str, object]] = []
    for item in value:
        if type(item) is not list or len(item) != 2 or type(item[0]) is not str:
            raise ValueError("tracking pair invalid")
        expected = float if float_values else str
        if type(item[1]) is not expected:
            raise ValueError("tracking pair value invalid")
        result.append((item[0], item[1]))
    return tuple(result)


def _parse_artifacts(value: object) -> tuple[ArtifactDigest, ...]:
    if type(value) is not list:
        raise ValueError("tracking artifacts JSON invalid")
    result: list[ArtifactDigest] = []
    for item in value:
        if type(item) is not dict or set(item) != {
            "root_alias", "relative_path", "size_bytes", "sha256"
        }:
            raise ValueError("tracking artifact JSON invalid")
        result.append(ArtifactDigest(**cast(Any, item)))
    return tuple(result)


def _strict_json(raw: bytes, keys: tuple[str, ...]) -> dict[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValueError("tracking JSON invalid") from None
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError("tracking JSON keys invalid")
    return cast(dict[str, Any], value)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _publish_no_clobber(path: Path, raw: bytes) -> None:
    if not isinstance(path, Path) or not path.is_absolute() or not path.parent.is_dir():
        raise ValueError("tracking journal path invalid")
    if path.exists() or path.is_symlink():
        if _read_regular(path) != raw:
            raise ValueError("tracking journal conflict")
        return
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, path)
        except FileExistsError:
            if _read_regular(path) != raw:
                raise ValueError("tracking journal conflict") from None
    except OSError:
        raise ValueError("tracking journal publish failed") from None
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _read_regular(path: Path) -> bytes:
    if not isinstance(path, Path):
        raise ValueError("tracking path invalid")
    try:
        if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
            raise ValueError("tracking file is not regular")
        return path.read_bytes()
    except OSError:
        raise ValueError("tracking file read failed") from None


def _require_hex64(name: str, value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in _HEX64 for char in value):
        raise ValueError(f"{name} must be bare lowercase hex64")
    return value


def _require_stable_string(name: str, value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{name} must be stable non-empty string")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{name} contains control characters")
    return value


def _stringify(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple)):
        return _canonical_bytes(value).decode("ascii")
    return str(value)


def _assert_safe_value(
    value: object,
    location: str,
    *,
    seen: set[int] | None = None,
) -> None:
    if seen is None:
        seen = set()
    obj_id = id(value)
    if obj_id in seen:
        raise ValueError(f"{location} 包含循环引用")
    if isinstance(value, (str, bytes, int, float, bool, type(None))):
        if isinstance(value, str):
            _assert_safe_string(value, location)
        return
    if isinstance(value, Path):
        _assert_safe_string(str(value), location)
        return
    if isinstance(value, Mapping):
        seen.add(obj_id)
        try:
            for key, item in value.items():
                key_text = str(key)
                _assert_safe_string(key_text, f"{location}.key")
                if any(fragment in key_text.casefold() for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                    raise ValueError(f"{location} 禁止包含敏感键")
                _assert_safe_value(item, f"{location}.{key_text}", seen=seen)
        finally:
            seen.discard(obj_id)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        seen.add(obj_id)
        try:
            for index, item in enumerate(value):
                _assert_safe_value(item, f"{location}[{index}]", seen=seen)
        finally:
            seen.discard(obj_id)
        return
    _assert_safe_string(str(value), location)


def _assert_safe_string(text: str, location: str) -> None:
    lower = text.casefold()
    secret_fragments = (
        "token=", "token:", "bearer ", "password=", "password:",
        "secret=", "secret:", "api_key=", "api_key:",
    )
    absolute = (
        text.startswith(("/", "\\\\", "file:"))
        or (len(text) >= 3 and text[0].isalpha() and text[1] == ":" and text[2] in "/\\")
    )
    if any(fragment in lower for fragment in secret_fragments):
        raise ValueError(f"{location} 疑似包含凭据内容")
    if absolute:
        raise ValueError(f"{location} 禁止写入绝对本机路径")
