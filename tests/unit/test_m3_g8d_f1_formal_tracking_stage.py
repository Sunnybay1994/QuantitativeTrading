"""Focused G8D-F1 formal tracking StageRunner contract tests."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
import pickle
import threading
from collections.abc import Mapping
from dataclasses import replace
from decimal import localcontext
from pathlib import Path
from typing import Any, cast

import pytest

import quant.research.m3.tracking as tracking_module
from quant.backtest.a_share_reporting import (
    backtest_artifact_output_relative_paths,
    build_backtest_artifact,
)
from quant.research.m3.evaluate import EvaluationFreshVerificationContext
from quant.research.m3.orchestration import (
    TRACKING_STAGE_SPEC,
    ExternalInput,
    M3StageRunnerError,
    StaticDirectoryPublication,
)
from quant.research.m3.tracking import (
    FormalTrackingFreshVerificationContext,
    RemoteTrackingRunV1,
    TrackingRequestV1,
    build_formal_tracking_request,
    compute_tracking_key,
    formal_tracking_input_paths,
    formal_tracking_upload_paths,
    register_remote_tracking_run,
    register_tracking_request,
)
from quant.research.m3.tracking_stage import (
    FormalTrackingStageResult,
    make_formal_tracking_run_plan,
    run_formal_tracking_stage,
)

_G8_SPEC = importlib.util.spec_from_file_location(
    "m3_g8d_g8_support",
    Path(__file__).with_name("test_m3_g8_r1_formal_backtest_stage.py"),
)
assert _G8_SPEC is not None and _G8_SPEC.loader is not None
_G8 = importlib.util.module_from_spec(_G8_SPEC)
_G8_SPEC.loader.exec_module(_G8)

_EVAL_SPEC = importlib.util.spec_from_file_location(
    "m3_g8d_eval_support",
    Path(__file__).with_name("test_m3_formal_evaluation_artifact.py"),
)
assert _EVAL_SPEC is not None and _EVAL_SPEC.loader is not None
_EVAL = importlib.util.module_from_spec(_EVAL_SPEC)
_EVAL_SPEC.loader.exec_module(_EVAL)

_G7F_SPEC = importlib.util.spec_from_file_location(
    "m3_g8d_g7f_support",
    Path(__file__).with_name("test_m3_g7f_formal_backtest_artifact.py"),
)
assert _G7F_SPEC is not None and _G7F_SPEC.loader is not None
_G7F = importlib.util.module_from_spec(_G7F_SPEC)
_G7F_SPEC.loader.exec_module(_G7F)


class FakeTrackingClient:
    def __init__(self) -> None:
        self.runs: list[RemoteTrackingRunV1] = []
        self.created = 0
        self.params: dict[str, str] = {}
        self.metrics: dict[str, float] = {}
        self.uploads: list[tuple[Path, str]] = []
        self.find_calls = 0
        self.create_calls = 0
        self.crash_after_finish = False
        self.lock = threading.Lock()

    def find_runs(
        self, *, experiment_name: str, tracking_key: str
    ) -> tuple[RemoteTrackingRunV1, ...]:
        with self.lock:
            self.find_calls += 1
            return tuple(
                run
                for run in self.runs
                if run.tags.get("quant_tracking_key") == tracking_key
            )

    def create_run(self, *, experiment_name: str, tags: Mapping[str, str]) -> str:
        with self.lock:
            self.create_calls += 1
            self.created += 1
            run_id = f"run-{self.created}"
            self.runs.append(
                RemoteTrackingRunV1(run_id=run_id, status="RUNNING", tags=dict(tags))
            )
            return run_id

    def log_params(self, *, run_id: str, params: Mapping[str, str]) -> None:
        self.params.update(params)

    def log_metrics(self, *, run_id: str, metrics: Mapping[str, float]) -> None:
        self.metrics.update(metrics)

    def log_artifact(
        self, *, run_id: str, local_path: Path, artifact_path: str
    ) -> None:
        self.uploads.append((local_path, artifact_path))

    def finish_run(self, *, run_id: str) -> None:
        with self.lock:
            self.runs = [
                replace(run, status="FINISHED") if run.run_id == run_id else run
                for run in self.runs
            ]
            if self.crash_after_finish:
                raise RuntimeError("synthetic crash after remote success")


def _build_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    bt_dir = tmp_path / "bt"
    ev_dir = tmp_path / "ev"
    bt_dir.mkdir(exist_ok=True)
    ev_dir.mkdir(exist_ok=True)
    bt = _G8._case(bt_dir, monkeypatch)
    kwargs = bt["kwargs"]
    target = kwargs["target"]
    config = kwargs["config"]
    release = kwargs["release"]
    experiment = kwargs["experiment"]
    build_backtest_artifact(
        **kwargs,
        artifact_roots=bt["roots"],
        output_root=bt["root"],
    )
    backtest_receipt = _G7F._publish_receipt(
        {
            "kwargs": kwargs,
            "root": bt["root"],
            "roots": bt["roots"],
            "context": {"common": bt_dir},
            "upstream_paths": kwargs["fresh_context"].upstream_paths,
        }
    )
    from quant.backtest.a_share_reporting import verify_backtest_artifact

    backtest = verify_backtest_artifact(
        root=bt["root"],
        receipt_path=backtest_receipt,
        **kwargs,
        artifact_roots=bt["roots"],
    )

    ev_context = _EVAL._evaluation_context(ev_dir, monkeypatch)
    evaluation_root, evaluation_receipt, _, evaluation = _EVAL._build_publish_verify(
        ev_context, "g8d"
    )
    ekw = ev_context["evaluation_kwargs"]
    work_key = target.manifest.work_key
    evaluation = replace(
        evaluation,
        manifest=replace(
            evaluation.manifest,
            work_key=work_key,
            experiment_key=target.manifest.experiment_key,
            scientific_config_sha256=target.manifest.scientific_config_sha256,
            fold=target.manifest.fold,
            horizon_sessions=target.manifest.horizon_sessions,
            model=target.manifest.model,
            model_version=target.manifest.model_version,
            prediction_manifest_sha256=target.manifest.prediction_manifest_sha256,
            feature_manifest_sha256=target.manifest.feature_manifest_sha256,
            fold_plan_manifest_sha256=target.manifest.fold_plan_manifest_sha256,
            eligible_keys_sha256=target.manifest.eligible_keys_sha256,
        ),
        metrics=replace(
            evaluation.metrics,
            work_key=work_key,
            experiment_key=target.manifest.experiment_key,
            fold=target.manifest.fold,
            horizon_sessions=target.manifest.horizon_sessions,
            model=target.manifest.model,
            model_version=target.manifest.model_version,
        ),
    )
    evaluation_spec = replace(
        ekw["spec"],
        work_key=work_key,
        experiment_key=target.manifest.experiment_key,
        fold=target.manifest.fold,
        horizon_sessions=cast(Any, target.manifest.horizon_sessions),
    )
    evaluation_context = EvaluationFreshVerificationContext(
        release=release,
        snapshot=ekw["snapshot"],
        snapshot_spec=ekw["snapshot_spec"],
        provider=ekw["provider"],
        provider_spec=ekw["provider_spec"],
        experiment=experiment,
        experiment_spec=ekw["experiment_spec"],
        folds=ekw["folds"],
        fold_spec=ekw["fold_spec"],
        feature=ekw["feature"],
        feature_spec=ekw["feature_spec"],
        label=ekw["label"],
        label_spec=ekw["label_spec"],
        alignment=ekw["alignment"],
        alignment_spec=ekw["alignment_spec"],
        model=ekw["model"],
        model_spec=ekw["model_spec"],
        prediction=ekw["prediction"],
        prediction_spec=ekw["prediction_spec"],
        evaluation_spec=evaluation_spec,
        evaluation_upstream_paths=ekw["upstream_paths"],
    )
    fresh_context = FormalTrackingFreshVerificationContext(
        evaluation_context=evaluation_context,
        evaluation_receipt_path=evaluation_receipt,
        target=target,
        plan=kwargs["plan"],
        release=release,
        experiment=experiment,
        backtest_context=kwargs["fresh_context"],
        backtest_receipt_path=backtest_receipt,
    )
    roots = {
        **cast(dict[str, Path], ev_context["evaluation_kwargs"]["artifact_roots"]),
        **cast(dict[str, Path], bt["roots"]),
    }
    return {
        "evaluation": evaluation,
        "backtest": backtest,
        "config": config,
        "fresh_context": fresh_context,
        "roots": roots,
        "target": target,
        "bt": bt,
        "evaluation_root": evaluation_root,
        "evaluation_receipt": evaluation_receipt,
        "backtest_receipt": backtest_receipt,
        "default_stage_root": bt["stage_root"],
    }


def _attach_runtime(
    base: dict[str, Any],
    *,
    stage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    stage_root.mkdir(parents=True, exist_ok=True)
    verifier_calls: list[tuple[str, object]] = []
    evaluation = base["evaluation"]
    backtest = base["backtest"]

    def fake_verify_evaluation(**call: Any) -> Any:
        verifier_calls.append(("evaluation", call["root"]))
        return evaluation

    def fake_verify_backtest(**call: Any) -> Any:
        verifier_calls.append(("backtest", call["root"]))
        return backtest

    monkeypatch.setattr(
        tracking_module, "verify_evaluation_artifact", fake_verify_evaluation
    )
    monkeypatch.setattr(
        "quant.backtest.a_share_reporting.verify_backtest_artifact",
        fake_verify_backtest,
    )
    return {
        **base,
        "stage_root": stage_root,
        "client": FakeTrackingClient(),
        "verifier_calls": verifier_calls,
    }


def _case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    base = _build_artifacts(tmp_path, monkeypatch)
    return _attach_runtime(
        base,
        stage_root=base["default_stage_root"],
        monkeypatch=monkeypatch,
    )


@pytest.fixture(scope="module")
def _module_artifacts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from _pytest.monkeypatch import MonkeyPatch

    root = tmp_path_factory.mktemp("g8d-f1-shared")
    monkeypatch = MonkeyPatch()
    try:
        return _build_artifacts(root, monkeypatch)
    finally:
        monkeypatch.undo()


@pytest.fixture
def case(
    _module_artifacts: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    stage_root = _module_artifacts["default_stage_root"].parent / f"stage-{tmp_path.name}"
    return _attach_runtime(
        _module_artifacts,
        stage_root=stage_root,
        monkeypatch=monkeypatch,
    )


def _run_kwargs(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage_root": case["stage_root"],
        "evaluation": case["evaluation"],
        "backtest": case["backtest"],
        "config": case["config"],
        "fresh_context": case["fresh_context"],
        "artifact_roots": case["roots"],
        "client": case["client"],
    }


def test_formal_plan_and_request_close_34_11_22_2_tags_metrics(
    case: dict[str, Any],
) -> None:
    paths = formal_tracking_input_paths(
        evaluation=case["evaluation"],
        backtest=case["backtest"],
        fresh_context=case["fresh_context"],
    )
    assert len(paths) == len(set(paths)) == 34
    uploads = formal_tracking_upload_paths(
        evaluation=case["evaluation"],
        backtest=case["backtest"],
    )
    assert len(uploads) == len(set(uploads)) == 11
    assert set(p.name for p in uploads if "0p5x" not in str(p) and "1p0x" not in str(p) and "2p0x" not in str(p)) >= {
        "daily_ic.parquet",
        "evaluation_manifest.json",
        "metrics.json",
        "backtest_manifest.json",
        "backtest_metrics.json",
    }
    plan = make_formal_tracking_run_plan(
        evaluation=case["evaluation"],
        backtest=case["backtest"],
        config=case["config"],
        fresh_context=case["fresh_context"],
        artifact_roots=case["roots"],
    )
    assert plan.continuation == "WORK"
    assert len(plan.nodes) == 1
    node = plan.nodes[0]
    target = case["target"]
    assert node.node_id == (
        f"tracking.{target.manifest.fold}.h{target.manifest.horizon_sessions}"
    )
    assert node.spec_name == "tracking"
    assert node.scope == "WORK"
    assert node.scope_key == target.manifest.work_key
    assert node.dependencies == ()
    assert len(node.inputs) == 34
    assert all(type(item) is ExternalInput for item in node.inputs)
    digests = tuple(cast(ExternalInput, item).artifact for item in node.inputs)
    assert digests == tuple(
        sorted(digests, key=lambda item: (item.root_alias, item.relative_path))
    )
    assert node.publication == StaticDirectoryPublication(
        f"work/{target.manifest.work_key}/tracking"
    )
    assert node.receipt_path == f"receipts/tracking/{target.manifest.work_key}.json"
    assert node.output_specs == TRACKING_STAGE_SPEC.outputs
    assert case["verifier_calls"] == []

    request = build_formal_tracking_request(
        evaluation=case["evaluation"],
        backtest=case["backtest"],
        config=case["config"],
        fresh_context=case["fresh_context"],
        artifact_roots=case["roots"],
    )
    assert [name for name, _ in case["verifier_calls"]] == ["evaluation", "backtest"]
    assert request.tracking_target_key == case["config"].tracking_target_key
    assert request.work_key == target.manifest.work_key
    assert tuple(key for key, _ in request.params) == tracking_module._FORMAL_PARAM_KEYS
    assert dict(request.params)["scenario_count"] == "3"
    assert dict(request.tags) == {
        "formal_gate_eligible": "true",
        "release_kind": "formal",
    }
    assert "example_id" not in dict(request.tags)
    assert len(request.artifacts) == 11
    assert all(
        item.root_alias in case["roots"] for item in request.artifacts
    )
    assert not any(
        Path(item.relative_path).is_absolute() for item in request.artifacts
    )
    metric_keys = [key for key, _ in request.metrics]
    assert metric_keys == sorted(metric_keys)
    assert any(key.startswith("evaluation.") for key in metric_keys)
    assert any(key.startswith("backtest.0p5x.") for key in metric_keys)
    assert any(key.startswith("backtest.1p0x.") for key in metric_keys)
    assert any(key.startswith("backtest.2p0x.") for key in metric_keys)
    assert all("status_counts" not in key for key in metric_keys)


def test_identity_mismatches_and_input_hostility_are_stage_input_invalid(
    case: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = replace(
        case["backtest"],
        manifest=replace(case["backtest"].manifest, work_key="f" * 64),
    )
    with pytest.raises(M3StageRunnerError) as caught:
        make_formal_tracking_run_plan(
            evaluation=case["evaluation"],
            backtest=stale,
            config=case["config"],
            fresh_context=case["fresh_context"],
            artifact_roots=case["roots"],
        )
    assert caught.value.code == "STAGE_INPUT_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None

    other = replace(
        case["evaluation"],
        manifest=replace(case["evaluation"].manifest, work_key="a" * 64),
        metrics=replace(case["evaluation"].metrics, work_key="a" * 64),
    )

    def other_eval(**_kwargs: Any) -> Any:
        return other

    monkeypatch.setattr(tracking_module, "verify_evaluation_artifact", other_eval)
    with pytest.raises(M3StageRunnerError) as caught:
        run_formal_tracking_stage(**_run_kwargs(case))
    assert caught.value.code == "STAGE_INPUT_INVALID"

    nested = case["roots"]["test"] / "nested-under-test"
    nested.mkdir(exist_ok=True)
    with pytest.raises(M3StageRunnerError, match="STAGE_INPUT_INVALID"):
        make_formal_tracking_run_plan(
            evaluation=case["evaluation"],
            backtest=case["backtest"],
            config=case["config"],
            fresh_context=case["fresh_context"],
            artifact_roots={"outer": case["roots"]["test"], "inner": nested},
        )


def test_remote_zero_one_two_and_marker_crash_recovery(
    case: dict[str, Any],
    tmp_path: Path,
) -> None:
    request = build_formal_tracking_request(
        evaluation=case["evaluation"],
        backtest=case["backtest"],
        config=case["config"],
        fresh_context=case["fresh_context"],
        artifact_roots=case["roots"],
    )
    request_sha = hashlib.sha256(
        tracking_module._canonical_bytes(
            tracking_module._request_mapping(request)
        )
    ).hexdigest()
    experiment_name = cast(str, case["config"].section("tracking")["experiment_name"])
    lock_root = tmp_path / "locks" / "remote"
    client = case["client"]
    marker = register_remote_tracking_run(
        request=request,
        request_sha256=request_sha,
        tracking_uri=case["config"].canonical_tracking_uri,
        experiment_name=experiment_name,
        artifact_roots=case["roots"],
        lock_root=lock_root,
        client=client,
    )
    assert client.create_calls == 1
    assert client.runs[0].status == "FINISHED"
    protected = {
        "quant_tracking_key",
        "quant_tracking_target_key",
        "quant_request_sha256",
        "quant_artifact_digest_sha256",
        "quant_work_key",
    }
    assert protected <= set(client.runs[0].tags)
    assert set(dict(request.tags)) <= set(client.runs[0].tags)
    reused = register_remote_tracking_run(
        request=request,
        request_sha256=request_sha,
        tracking_uri=case["config"].canonical_tracking_uri,
        experiment_name=experiment_name,
        artifact_roots=case["roots"],
        lock_root=lock_root,
        client=client,
    )
    assert reused.mlflow_run_id == marker.mlflow_run_id
    assert client.create_calls == 1

    conflict = FakeTrackingClient()
    conflict.runs = [
        RemoteTrackingRunV1(
            run_id="x",
            status="FAILED",
            tags={
                "quant_tracking_key": compute_tracking_key(
                    work_key=request.work_key, request_sha256=request_sha
                ),
                "quant_tracking_target_key": request.tracking_target_key,
                "quant_request_sha256": request_sha,
                "quant_artifact_digest_sha256": marker.artifact_digest_sha256,
                "quant_work_key": request.work_key,
            },
        )
    ]
    with pytest.raises(ValueError, match="remote tracking run is FAILED"):
        register_remote_tracking_run(
            request=request,
            request_sha256=request_sha,
            tracking_uri=case["config"].canonical_tracking_uri,
            experiment_name=experiment_name,
            artifact_roots=case["roots"],
            lock_root=tmp_path / "locks" / "failed",
            client=conflict,
        )

    multi = FakeTrackingClient()
    key = compute_tracking_key(work_key=request.work_key, request_sha256=request_sha)
    tags = {
        "quant_tracking_key": key,
        "quant_tracking_target_key": request.tracking_target_key,
        "quant_request_sha256": request_sha,
        "quant_artifact_digest_sha256": marker.artifact_digest_sha256,
        "quant_work_key": request.work_key,
    }
    multi.runs = [
        RemoteTrackingRunV1(run_id="a", status="FINISHED", tags=tags),
        RemoteTrackingRunV1(run_id="b", status="FINISHED", tags=tags),
    ]
    with pytest.raises(ValueError, match="multiple remote tracking runs"):
        register_remote_tracking_run(
            request=request,
            request_sha256=request_sha,
            tracking_uri=case["config"].canonical_tracking_uri,
            experiment_name=experiment_name,
            artifact_roots=case["roots"],
            lock_root=tmp_path / "locks" / "multi",
            client=multi,
        )

    crash_client = FakeTrackingClient()
    crash_client.crash_after_finish = True
    with pytest.raises(RuntimeError, match="synthetic crash"):
        register_remote_tracking_run(
            request=request,
            request_sha256=request_sha,
            tracking_uri=case["config"].canonical_tracking_uri,
            experiment_name=experiment_name,
            artifact_roots=case["roots"],
            lock_root=tmp_path / "locks" / "crash",
            client=crash_client,
        )
    crash_client.crash_after_finish = False
    recovered = register_remote_tracking_run(
        request=request,
        request_sha256=request_sha,
        tracking_uri=case["config"].canonical_tracking_uri,
        experiment_name=experiment_name,
        artifact_roots=case["roots"],
        lock_root=tmp_path / "locks" / "crash",
        client=crash_client,
    )
    assert recovered.mlflow_run_id == "run-1"
    assert crash_client.create_calls == 1


def test_finished_remote_reuse_requires_request_tags_exact(
    case: dict[str, Any],
    tmp_path: Path,
) -> None:
    request = build_formal_tracking_request(
        evaluation=case["evaluation"],
        backtest=case["backtest"],
        config=case["config"],
        fresh_context=case["fresh_context"],
        artifact_roots=case["roots"],
    )
    request_sha = hashlib.sha256(
        tracking_module._canonical_bytes(
            tracking_module._request_mapping(request)
        )
    ).hexdigest()
    experiment_name = cast(str, case["config"].section("tracking")["experiment_name"])
    tracking_key = compute_tracking_key(
        work_key=request.work_key, request_sha256=request_sha
    )
    artifact_sha = tracking_module._artifact_digest_sha256(request.artifacts)
    protected = {
        "quant_tracking_key": tracking_key,
        "quant_tracking_target_key": request.tracking_target_key,
        "quant_request_sha256": request_sha,
        "quant_artifact_digest_sha256": artifact_sha,
        "quant_work_key": request.work_key,
    }
    request_tags = dict(request.tags)
    assert request_tags == {
        "formal_gate_eligible": "true",
        "release_kind": "formal",
    }

    def _register(client: FakeTrackingClient, lock_name: str) -> Any:
        return register_remote_tracking_run(
            request=request,
            request_sha256=request_sha,
            tracking_uri=case["config"].canonical_tracking_uri,
            experiment_name=experiment_name,
            artifact_roots=case["roots"],
            lock_root=tmp_path / "locks" / lock_name,
            client=client,
        )

    eligible_drift = FakeTrackingClient()
    eligible_drift.runs = [
        RemoteTrackingRunV1(
            run_id="drift-eligible",
            status="FINISHED",
            tags={
                **protected,
                **request_tags,
                "formal_gate_eligible": "false",
            },
        )
    ]
    with pytest.raises(ValueError, match="remote tracking run content conflict"):
        _register(eligible_drift, "eligible-drift")
    assert eligible_drift.create_calls == 0

    release_drift = FakeTrackingClient()
    release_drift.runs = [
        RemoteTrackingRunV1(
            run_id="drift-release",
            status="FINISHED",
            tags={
                **protected,
                **request_tags,
                "release_kind": "development_example",
            },
        )
    ]
    with pytest.raises(ValueError, match="remote tracking run content conflict"):
        _register(release_drift, "release-drift")
    assert release_drift.create_calls == 0

    missing_eligible = FakeTrackingClient()
    missing_eligible.runs = [
        RemoteTrackingRunV1(
            run_id="missing-eligible",
            status="FINISHED",
            tags={**protected, "release_kind": "formal"},
        )
    ]
    with pytest.raises(ValueError, match="remote tracking run content conflict"):
        _register(missing_eligible, "missing-eligible")
    assert missing_eligible.create_calls == 0

    missing_release = FakeTrackingClient()
    missing_release.runs = [
        RemoteTrackingRunV1(
            run_id="missing-release",
            status="FINISHED",
            tags={**protected, "formal_gate_eligible": "true"},
        )
    ]
    with pytest.raises(ValueError, match="remote tracking run content conflict"):
        _register(missing_release, "missing-release")
    assert missing_release.create_calls == 0

    reused_client = FakeTrackingClient()
    reused_client.runs = [
        RemoteTrackingRunV1(
            run_id="reuse-exact",
            status="FINISHED",
            tags={
                **protected,
                **request_tags,
                "operator_note": "extra-ordinary-allowed",
            },
        )
    ]
    reused = _register(reused_client, "reuse-exact")
    assert reused.mlflow_run_id == "reuse-exact"
    assert reused_client.create_calls == 0

    protected_conflict = FakeTrackingClient()
    protected_conflict.runs = [
        RemoteTrackingRunV1(
            run_id="protected-drift",
            status="FINISHED",
            tags={
                **protected,
                **request_tags,
                "quant_request_sha256": "0" * 64,
            },
        )
    ]
    with pytest.raises(ValueError, match="remote tracking run content conflict"):
        _register(protected_conflict, "protected-drift")
    assert protected_conflict.create_calls == 0

    class HostileGet(dict[str, str]):
        def get(self, key: str, default: object = None) -> object:
            raise RuntimeError("TOKEN=secret file:///tmp PID=9")

    hostile = FakeTrackingClient()
    hostile.runs = [
        RemoteTrackingRunV1(
            run_id="hostile-tags",
            status="FINISHED",
            tags=HostileGet({**protected, **request_tags}),
        )
    ]
    with pytest.raises(RuntimeError, match="TOKEN=secret"):
        _register(hostile, "hostile-tags")
    assert hostile.create_calls == 0


def test_development_register_api_remains_compatible(
    tmp_path: Path,
) -> None:
    journal_spec = importlib.util.spec_from_file_location(
        "m3_g8d_tracking_journal_support",
        Path(__file__).with_name("test_m3_tracking_journal.py"),
    )
    assert journal_spec is not None and journal_spec.loader is not None
    journal = importlib.util.module_from_spec(journal_spec)
    journal_spec.loader.exec_module(journal)
    request, root = journal._request(tmp_path)
    client = journal.FakeTrackingClient()
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    marker = register_tracking_request(
        request=request,
        request_path=(journal_dir / "request.json").resolve(),
        marker_path=(journal_dir / "marker.json").resolve(),
        tracking_uri=journal._URI,
        experiment_name=journal._EXPERIMENT,
        artifact_roots={"evaluation": root},
        client=client,
    )
    assert marker.mlflow_run_id == "run-1"
    assert (journal_dir / ".tracking-locks").exists()


def test_stage_result_rejects_pickle_and_nominal_forgery() -> None:
    with pytest.raises(ValueError, match="M3_FORMAL_TRACKING_STAGE_INVALID"):
        FormalTrackingStageResult(
            final_root=cast(Any, "root"),
            receipt_path=cast(Any, "receipt"),
            request=cast(Any, object()),
            marker=cast(Any, object()),
            receipt=cast(Any, object()),
            reused=False,
        )
    assert "__reduce__" in FormalTrackingStageResult.__dict__
    assert "__reduce__" in FormalTrackingFreshVerificationContext.__dict__
    forged = object.__new__(FormalTrackingFreshVerificationContext)
    with pytest.raises(TypeError, match="M3_FORMAL_TRACKING_CONTEXT_INVALID"):
        pickle.dumps(forged)


def test_upload_allowlist_rejects_wrong_counts_and_hardlinks(
    case: dict[str, Any],
    tmp_path: Path,
) -> None:
    uploads = list(
        formal_tracking_upload_paths(
            evaluation=case["evaluation"],
            backtest=case["backtest"],
        )
    )
    assert len(uploads) == 11
    assert len(backtest_artifact_output_relative_paths()) == 29
    source = case["fresh_context"].evaluation_receipt_path
    copied = case["roots"]["test"] / "receipt-copy-for-hardlink.json"
    copied.write_bytes(source.read_bytes())
    linked = case["roots"]["test"] / "hardlinked-receipt.json"
    try:
        os.link(copied, linked)
    except OSError:
        pytest.skip("host lacks hardlink support")
    assert os.lstat(linked).st_nlink > 1
    assert os.lstat(source).st_nlink == 1
    with pytest.raises(M3StageRunnerError) as caught:
        make_formal_tracking_run_plan(
            evaluation=case["evaluation"],
            backtest=case["backtest"],
            config=case["config"],
            fresh_context=replace(
                case["fresh_context"],
                evaluation_receipt_path=linked,
            ),
            artifact_roots=case["roots"],
        )
    assert caught.value.code == "STAGE_INPUT_INVALID"


def test_hostile_client_and_decimal_context_are_stable(
    case: dict[str, Any],
) -> None:

    class HostileClient(FakeTrackingClient):
        def find_runs(self, **kwargs: Any) -> tuple[RemoteTrackingRunV1, ...]:
            raise RuntimeError("TOKEN=secret file:///tmp PID=1 C:\\private")

    case["client"] = HostileClient()
    with pytest.raises(M3StageRunnerError) as caught:
        run_formal_tracking_stage(**_run_kwargs(case))
    assert caught.value.code == "STAGE_BUILD_FAILED"
    assert str(caught.value) == "STAGE_BUILD_FAILED"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "TOKEN" not in str(caught.value)
    assert not tuple(case["stage_root"].rglob("tracking_request.json"))

    with localcontext() as context:
        context.prec = 5
        request = build_formal_tracking_request(
            evaluation=case["evaluation"],
            backtest=case["backtest"],
            config=case["config"],
            fresh_context=case["fresh_context"],
            artifact_roots=case["roots"],
        )
    assert type(request) is TrackingRequestV1
    assert all(type(value) is float for _, value in request.metrics)


def test_cold_import_does_not_load_heavy_deps() -> None:
    import sys

    modules = ("mlflow", "qlib", "lightgbm")
    before = {name: name in sys.modules for name in modules}
    importlib.import_module("quant.research.m3.tracking")
    importlib.import_module("quant.research.m3.tracking_stage")
    after = {name: name in sys.modules for name in modules}
    for name in modules:
        assert before[name] == after[name] or not after[name]
