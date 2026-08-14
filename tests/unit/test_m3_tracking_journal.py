"""G8D tracking request journal and fake remote recovery tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from quant.research.m3.config import canonical_tracking_target_key
from quant.research.m3.contracts import EvaluationManifestV1, EvaluationMetricsV1
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleEvaluationArtifact,
)
from quant.research.m3.tracking import (
    RemoteTrackingRunV1,
    TrackingMarkerV1,
    TrackingRequestV1,
    build_tracking_request,
    compute_tracking_key,
    publish_tracking_marker,
    publish_tracking_request,
    read_tracking_marker,
    read_tracking_request,
    register_tracking_request,
)

_HEX_A = "a" * 64
_HEX_B = "b" * 64
_URI = "sqlite:///artifacts/research/m3/test-tracking.db"
_EXPERIMENT = "m3-development-test"


class FakeTrackingClient:
    def __init__(self) -> None:
        self.runs: list[RemoteTrackingRunV1] = []
        self.created = 0
        self.params: dict[str, str] = {}
        self.metrics: dict[str, float] = {}
        self.uploads: list[tuple[Path, str]] = []
        self.crash_after_finish = False

    def find_runs(
        self, *, experiment_name: str, tracking_key: str
    ) -> tuple[RemoteTrackingRunV1, ...]:
        assert experiment_name == _EXPERIMENT
        return tuple(
            run
            for run in self.runs
            if run.tags.get("quant_tracking_key") == tracking_key
        )

    def create_run(self, *, experiment_name: str, tags: Mapping[str, str]) -> str:
        assert experiment_name == _EXPERIMENT
        self.created += 1
        run_id = f"run-{self.created}"
        self.runs.append(
            RemoteTrackingRunV1(run_id=run_id, status="RUNNING", tags=dict(tags))
        )
        return run_id

    def log_params(self, *, run_id: str, params: Mapping[str, str]) -> None:
        assert run_id
        self.params.update(params)

    def log_metrics(self, *, run_id: str, metrics: Mapping[str, float]) -> None:
        assert run_id
        self.metrics.update(metrics)

    def log_artifact(
        self, *, run_id: str, local_path: Path, artifact_path: str
    ) -> None:
        assert run_id
        self.uploads.append((local_path, artifact_path))

    def finish_run(self, *, run_id: str) -> None:
        self.runs = [
            replace(run, status="FINISHED") if run.run_id == run_id else run
            for run in self.runs
        ]
        if self.crash_after_finish:
            raise RuntimeError("synthetic crash after remote success")


def _evaluation(tmp_path: Path) -> VerifiedDevelopmentExampleEvaluationArtifact:
    root = tmp_path / "development-example-evaluation"
    root.mkdir(parents=True)
    metrics = EvaluationMetricsV1(
        schema_version="m3-evaluation-metrics-v1",
        experiment_key=_HEX_A,
        work_key=_HEX_B,
        fold="fold-0",
        horizon_sessions=5,
        model="lightgbm",
        model_version="test-v1",
        n_dates=0,
        n_computable_dates=0,
        n_eligible=0,
        n_scorable=0,
        n_predicted=0,
        n_labeled=0,
        n_evaluated=0,
        feature_coverage=None,
        prediction_coverage=None,
        label_coverage=None,
        evaluation_coverage=None,
        pearson_ic_mean=None,
        rank_ic_mean=None,
        pearson_icir=None,
        rank_icir=None,
        status_counts=(
            ("NO_ELIGIBLE", 0),
            ("NO_LABELS", 0),
            ("NO_PREDICTIONS", 0),
            ("INSUFFICIENT_SYMBOLS", 0),
            ("BOTH_ZERO_VARIANCE", 0),
            ("SCORE_ZERO_VARIANCE", 0),
            ("LABEL_ZERO_VARIANCE", 0),
            ("COMPUTABLE", 0),
        ),
        daily_sha256=_HEX_A,
    )
    manifest = EvaluationManifestV1(
        schema_version="m3-evaluation-artifact-v1",
        experiment_key=_HEX_A,
        work_key=_HEX_B,
        prediction_manifest_sha256=_HEX_A,
        label_manifest_sha256=_HEX_A,
        feature_manifest_sha256=_HEX_A,
        fold_plan_manifest_sha256=_HEX_A,
        eligible_keys_sha256=_HEX_A,
        evaluation_dates_sha256=_HEX_A,
        scientific_config_sha256=_HEX_A,
        fold="fold-0",
        horizon_sessions=5,
        model="lightgbm",
        model_version="test-v1",
        daily_sha256=_HEX_A,
        metrics_sha256=_HEX_A,
    )
    (root / "metrics.json").write_text(
        json.dumps({"nullable_metric": None}, separators=(",", ":")),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps({"work_key": _HEX_B}, separators=(",", ":")),
        encoding="utf-8",
    )
    return VerifiedDevelopmentExampleEvaluationArtifact(
        release_kind="development_example",
        formal_gate_eligible=False,
        example_id="development-example-" + "c" * 64,
        root=root,
        daily=pl.DataFrame(),
        metrics=metrics,
        manifest=manifest,
        manifest_sha256=_HEX_A,
        evaluation_receipt_sha256=_HEX_A,
    )


def _request(tmp_path: Path, **kwargs: Any) -> tuple[TrackingRequestV1, Path]:
    evaluation = _evaluation(tmp_path)
    request = build_tracking_request(
        tracking_target_key=canonical_tracking_target_key(
            tracking_uri=_URI, experiment_name=_EXPERIMENT
        ),
        evaluation=evaluation,
        **kwargs,
    )
    return request, evaluation.root


def _register(
    tmp_path: Path,
    request: TrackingRequestV1,
    root: Path,
    client: FakeTrackingClient,
) -> TrackingMarkerV1:
    journal = tmp_path / "journal"
    journal.mkdir(exist_ok=True)
    return register_tracking_request(
        request=request,
        request_path=(journal / "request.json").resolve(),
        marker_path=(journal / "marker.json").resolve(),
        tracking_uri=_URI,
        experiment_name=_EXPERIMENT,
        artifact_roots={"evaluation": root},
        client=client,
    )


def test_request_is_strict_canonical_secret_free_and_no_clobber(
    tmp_path: Path,
) -> None:
    request, root = _request(tmp_path)
    assert request.metrics
    assert all(value is not None for _, value in request.metrics)
    request_path = (tmp_path / "request.json").resolve()
    request_sha = publish_tracking_request(path=request_path, request=request)
    assert publish_tracking_request(path=request_path, request=request) == request_sha
    assert read_tracking_request(request_path) == request
    assert compute_tracking_key(
        work_key=request.work_key, request_sha256=request_sha
    ) == compute_tracking_key(work_key=request.work_key, request_sha256=request_sha)

    changed = replace(request, tags=(*request.tags, ("z", "changed")))
    with pytest.raises(ValueError):
        publish_tracking_request(path=request_path, request=changed)
    with pytest.raises(ValueError):
        _request(tmp_path / "nested", params={"outer": {"api_token": "redacted"}})
    with pytest.raises(ValueError):
        _request(tmp_path / "absolute", tags={"output": str(root.resolve())})

    marker = TrackingMarkerV1(
        schema_version="m3-tracking-marker-v1",
        tracking_target_key=request.tracking_target_key,
        tracking_key=_HEX_A,
        request_sha256=request_sha,
        mlflow_run_id="run-1",
        artifact_digest_sha256=_HEX_B,
    )
    marker_path = (tmp_path / "marker.json").resolve()
    publish_tracking_marker(path=marker_path, marker=marker)
    publish_tracking_marker(path=marker_path, marker=marker)
    assert read_tracking_marker(marker_path) == marker
    with pytest.raises(ValueError):
        publish_tracking_marker(
            path=marker_path, marker=replace(marker, mlflow_run_id="run-2")
        )


def test_zero_then_one_finished_remote_is_idempotent_and_preserves_hierarchy(
    tmp_path: Path,
) -> None:
    request, root = _request(tmp_path)
    client = FakeTrackingClient()
    first = _register(tmp_path, request, root, client)
    second = _register(tmp_path, request, root, client)

    assert first == second
    assert client.created == 1
    assert client.runs[0].status == "FINISHED"
    assert client.runs[0].tags["quant_tracking_key"] == first.tracking_key
    assert client.runs[0].tags["quant_request_sha256"] == first.request_sha256
    assert set(client.uploads) == {
        (root / "metrics.json", "evaluation"),
        (root / "manifest.json", "evaluation"),
    }
    assert all(value is not None for value in client.metrics.values())
    client.runs.clear()
    with pytest.raises(ValueError, match="no remote run"):
        _register(tmp_path, request, root, client)
    assert client.created == 1


@pytest.mark.parametrize("status", ["RUNNING", "FAILED", "KILLED"])
def test_non_finished_remote_fails_without_second_run(
    tmp_path: Path,
    status: str,
) -> None:
    request, root = _request(tmp_path)
    client = FakeTrackingClient()
    marker = _register(tmp_path, request, root, client)
    (tmp_path / "journal" / "marker.json").unlink()
    client.runs = [replace(client.runs[0], status=status)]  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=status):
        _register(tmp_path, request, root, client)
    assert client.created == 1
    assert marker.mlflow_run_id == client.runs[0].run_id


def test_multiple_or_conflicting_finished_runs_fail_closed(
    tmp_path: Path,
) -> None:
    request, root = _request(tmp_path)
    client = FakeTrackingClient()
    marker = _register(tmp_path, request, root, client)
    (tmp_path / "journal" / "marker.json").unlink()
    original = client.runs[0]
    client.runs.append(replace(original, run_id="run-duplicate"))
    with pytest.raises(ValueError, match="multiple"):
        _register(tmp_path, request, root, client)
    assert client.created == 1

    client.runs = [
        replace(
            original,
            tags={**dict(original.tags), "quant_request_sha256": "f" * 64},
        )
    ]
    with pytest.raises(ValueError, match="conflict"):
        _register(tmp_path, request, root, client)
    assert marker.tracking_key == original.tags["quant_tracking_key"]


def test_remote_success_before_marker_recovers_same_run_and_uri_switch_is_sanitized(
    tmp_path: Path,
) -> None:
    request, root = _request(tmp_path)
    client = FakeTrackingClient()
    client.crash_after_finish = True
    with pytest.raises(RuntimeError, match="synthetic crash"):
        _register(tmp_path, request, root, client)
    assert not (tmp_path / "journal" / "marker.json").exists()
    assert client.runs[0].status == "FINISHED"

    client.crash_after_finish = False
    marker = _register(tmp_path, request, root, client)
    assert marker.mlflow_run_id == "run-1"
    assert client.created == 1

    secret_uri = "https://user:password@example.invalid/mlflow"
    with pytest.raises(ValueError) as exc_info:
        register_tracking_request(
            request=request,
            request_path=(tmp_path / "other-request.json").resolve(),
            marker_path=(tmp_path / "other-marker.json").resolve(),
            tracking_uri=secret_uri,
            experiment_name=_EXPERIMENT,
            artifact_roots={"evaluation": root},
            client=client,
        )
    assert secret_uri not in str(exc_info.value)


def test_artifact_digest_drift_and_duplicate_json_are_rejected(tmp_path: Path) -> None:
    request, root = _request(tmp_path)
    client = FakeTrackingClient()
    (root / "metrics.json").write_bytes(b"drift")
    with pytest.raises(ValueError, match="digest drift"):
        _register(tmp_path, request, root, client)
    assert client.created == 0

    duplicate = (tmp_path / "duplicate.json").resolve()
    duplicate.write_text(
        '{"schema_version":"m3-tracking-request-v1",'
        '"schema_version":"m3-tracking-request-v1"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        read_tracking_request(duplicate)

    digest = hashlib.sha256(b"x").hexdigest()
    assert len(digest) == 64
