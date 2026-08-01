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
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol, cast

from quant.data._journal_lock import hold_journal_writer_lock
from quant.research.m3.config import canonical_tracking_target_key
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleBacktestArtifact,
    VerifiedDevelopmentExampleEvaluationArtifact,
)
from quant.research.m3.run_state import ArtifactDigest

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
TrackingStatus = Literal["RUNNING", "FINISHED", "FAILED", "KILLED"]


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
        expected_tags = {
            "quant_tracking_key": tracking_key,
            "quant_tracking_target_key": target_key,
            "quant_request_sha256": request_sha,
            "quant_artifact_digest_sha256": artifact_sha,
            "quant_work_key": request.work_key,
        }
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
            _validate_remote_run(run, expected_tags)
            if local_marker is not None and run.run_id != local_marker.mlflow_run_id:
                raise ValueError("local and remote tracking run conflict")
            marker = _marker(
                request=request,
                tracking_key=tracking_key,
                request_sha=request_sha,
                artifact_sha=artifact_sha,
                run_id=run.run_id,
            )
            publish_tracking_marker(path=marker_path, marker=marker)
            return marker

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
            artifact_path = digest.root_alias if parent == "." else f"{digest.root_alias}/{parent}"
            remote.log_artifact(
                run_id=run_id,
                local_path=local,
                artifact_path=artifact_path,
            )
        remote.finish_run(run_id=run_id)
        marker = _marker(
            request=request,
            tracking_key=tracking_key,
            request_sha=request_sha,
            artifact_sha=artifact_sha,
            run_id=run_id,
        )
        publish_tracking_marker(path=marker_path, marker=marker)
        return marker


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
