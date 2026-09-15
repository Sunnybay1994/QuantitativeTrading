"""G4B formal FeatureArtifact closed loop over strict public upstream verifiers."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

import quant.data.m3_release as release_module
import quant.research.m3.provider as provider_module
from quant.data.m3_release import (
    G1ReleaseInputs,
    publish_g1_release,
    verify_g1_release,
)
from quant.research.m3.config import load_m3_config
from quant.research.m3.contracts import (
    ExperimentIdentitySpec,
    FeatureBuildSpec,
    FeatureUpstreamPaths,
    FoldPlanBuildSpec,
    FoldPlanUpstreamPaths,
    ProviderBuildSpec,
    SnapshotBuildSpec,
    VerifiedFeatureArtifact,
)
from quant.research.m3.experiment_identity import (
    build_experiment_identity_manifest,
    experiment_identity_manifest_bytes,
)
from quant.research.m3.features import build_feature_artifact, verify_feature_artifact
from quant.research.m3.fetch_qlib_tool import build_qlib_dump_tool_spec
from quant.research.m3.folds import build_temporal_fold_plan, verify_fold_plan_artifact
from quant.research.m3.labels import verify_experiment_identity
from quant.research.m3.provider import (
    materialize_qlib_provider,
    verify_provider_artifact,
)
from quant.research.m3.run_state import (
    compute_snapshot_request_key,
    compute_provider_key,
    publish_stage_receipt,
    verify_stage_receipt,
)
from quant.research.m3.snapshot import (
    build_snapshot_artifact,
    build_snapshot_request_record,
    verify_snapshot_artifact,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _load_support(filename: str, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(
        module_name, Path(__file__).with_name(filename)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_G1 = _load_support("test_m3_g1_release.py", "formal_feature_g1_support")
_PROVIDER = _load_support(
    "test_m3_provider_materialization.py", "formal_feature_provider_support"
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, default=lambda item: item.isoformat(), ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()


def _publish_capable(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    os.rename(source, destination)


def _verified_g1(root: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    happy = _G1.happy_inputs.__wrapped__()
    happy = replace(happy, signal_end=happy.history.end)
    candidate = _G1.happy_candidate.__wrapped__(happy)
    policy = _G1.policy.__wrapped__()
    sample = _G1.sample_plan.__wrapped__(candidate, policy)
    requests = _G1.request_plan.__wrapped__(sample)
    responses = _G1.reference_responses.__wrapped__(candidate, sample, requests)
    inputs = G1ReleaseInputs(
        build_inputs=happy,
        cross_source_policy=policy,
        reference_responses=responses,
    )
    monkeypatch.setattr(release_module, "_renameat2_noreplace", _publish_capable)
    return verify_g1_release(
        release=publish_g1_release(output_root=root, inputs=inputs)
    )


def _formal_config(root: Path, release: Any) -> Any:
    source = Path("configs/research/m3_qlib_example.toml").read_text(encoding="utf-8")
    replacements = {
        "start_date = 2016-01-04": f"start_date = {release.manifest.signal_start}",
        "end_date = 2026-06-26": f"end_date = {release.manifest.signal_end}",
        "minimum_train_sessions = 756": "minimum_train_sessions = 1",
        "train_sessions = 756": "train_sessions = 1",
        "validation_sessions = 126": "validation_sessions = 1",
        "test_sessions = 126": "test_sessions = 1",
        "step_sessions = 126": "step_sessions = 1",
    }
    for old, new in replacements.items():
        assert source.count(old) == 1
        source = source.replace(old, new)
    path = root / "formal-feature-config.toml"
    path.write_text(source, encoding="utf-8")
    return load_m3_config(path)


def _snapshot(common: Path, release: Any, config: Any) -> tuple[Any, Any, Path, Path]:
    spec = SnapshotBuildSpec(
        snapshot_request_key=compute_snapshot_request_key(
            g1_release_id=release.manifest.release_id,
            g1_release_manifest_sha256=release.manifest_sha256,
            snapshot_config_sha256=config.snapshot_config_sha256,
            code_version="g4b-formal-fixture-v1",
        ),
        config_version=config.config_version,
        snapshot_config_sha256=config.snapshot_config_sha256,
        code_version="g4b-formal-fixture-v1",
        history_start=release.manifest.history_start,
        history_end=release.manifest.history_end,
        staging_schema_version="m3-qlib-staging-v1",
        adjustment_formula_version="qlib_yahoo_like_v1",
    )
    root = common / "snapshot"
    root.mkdir()
    result = build_snapshot_artifact(
        release=release, config=config, spec=spec, output_root=root
    )
    request = build_snapshot_request_record(
        release=release, config=config, spec=spec, result=result
    )
    request_path = common / "snapshot-requests" / f"{spec.snapshot_request_key}.json"
    request_path.parent.mkdir()
    request_path.write_bytes(_canonical(asdict(request)))
    receipt = common / "receipts" / "snapshot" / f"{spec.snapshot_request_key}.json"
    receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=receipt, stage="snapshot", scope="SNAPSHOT",
        scope_key=spec.snapshot_request_key, artifact_roots={"root": common},
        inputs=[
            ("root", release.release.manifest_path),
            *(("root", dict(release.artifact_paths)[name]) for name in (
                "bar_1d.parquet", "universe_membership.parquet",
                "trade_calendar.parquet",
            )),
        ],
        outputs=[
            ("root", request_path), ("root", root / "manifest.json"),
            ("root", root / "session_calendar.parquet"),
            *(("root", path) for path in sorted((root / "staging").glob("*.parquet"))),
        ],
    )
    verified = verify_snapshot_artifact(
        snapshot_root=root, snapshot_request_path=request_path,
        snapshot_receipt_path=receipt, release=release, config=config,
        spec=spec, artifact_roots={"root": common},
    )
    return verified, spec, request_path, receipt


def _provider(
    common: Path, snapshot: Any, config: Any, snapshot_request: Path,
    snapshot_receipt: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, Any, Path, Path]:
    runtime = _PROVIDER._runtime()
    tool_spec = build_qlib_dump_tool_spec(config)
    code_version = "g4b-formal-provider-v1"
    spec = ProviderBuildSpec(
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_key=compute_provider_key(
            snapshot_id=snapshot.manifest.snapshot_id,
            provider_config_hash=config.provider_config_sha256,
            dump_tool_sha256=tool_spec.sha256,
            qlib_version=tool_spec.qlib_version,
            provider_runtime_fingerprint_sha256=runtime.sha256,
            code_version=code_version,
        ),
        provider_config_sha256=config.provider_config_sha256,
        dump_tool=tool_spec, qlib_version="0.9.7", code_version=code_version,
        runtime_fingerprint=runtime,
        fields=("open", "high", "low", "close", "vwap", "volume", "factor"),
        frequency="day", dump_contract_version="m3-qlib-dump-all-v1",
    )
    external = common.parent / "external_qlib"
    external.mkdir()
    tool = external / "dump_bin.py"
    shutil.copyfile(Path("data/external/qlib/v0.9.7/dump_bin.py"), tool)
    root = common / "provider"
    root.mkdir()
    monkeypatch.setattr(
        provider_module, "build_provider_runtime_fingerprint", _PROVIDER._runtime
    )
    monkeypatch.setattr(provider_module.subprocess, "run", _PROVIDER._fake_dump)
    result = materialize_qlib_provider(
        snapshot=snapshot, qlib_dump_script=tool,
        python_executable=Path(sys.executable), config=config, spec=spec,
        output_root=root, timeout_seconds=30.0,
    )
    receipt = common / "receipts" / "provider" / f"{spec.provider_key}.json"
    receipt.parent.mkdir(parents=True)
    roots = {"root": common, "EXTERNAL_QLIB": external}
    publish_stage_receipt(
        receipt_path=receipt, stage="provider", scope="PROVIDER",
        scope_key=spec.provider_key, artifact_roots=roots,
        inputs=[
            ("root", snapshot.root / "manifest.json"),
            ("root", snapshot_request), ("root", snapshot_receipt),
            ("root", snapshot.session_calendar_path),
            *(("root", path) for path in snapshot.staging_paths),
            ("EXTERNAL_QLIB", tool),
        ],
        outputs=[
            ("root", result.root / "provider_manifest.json"),
            *(("root", result.root / item.relative_path) for item in result.manifest.files),
        ],
    )
    verified = verify_provider_artifact(
        provider_root=result.root, provider_receipt_path=receipt,
        snapshot=snapshot, config=config, artifact_roots=roots,
    )
    return verified, spec, tool, receipt


def _fake_feature_worker(
    argv: list[str], **kwargs: Any,
) -> subprocess.CompletedProcess[bytes]:
    request_path = Path(argv[argv.index("--request") + 1])
    output = Path(argv[argv.index("--output-root") + 1])
    request = json.loads(request_path.read_bytes())
    names = [f"ALPHA{index:03d}" for index in range(1, 159)]
    expressions = [f"FORMAL_ALPHA158_{index:03d}" for index in range(1, 159)]
    for segment in ("train", "validation", "test"):
        records = []
        for _, day, symbol in (
            row for row in request["eligible_rows"] if row[0] == segment
        ):
            records.append({
                "as_of": dt.date.fromisoformat(day), "symbol": symbol,
                **{name: float(index) for index, name in enumerate(names, 1)},
            })
        schema = {
            "as_of": pl.Date, "symbol": pl.Utf8,
            **{name: pl.Float64 for name in names},
        }
        pl.DataFrame(records, schema=schema).write_parquet(
            output / f"raw_{segment}.parquet"
        )
    response = {
        **{key: value for key, value in request.items() if key != "eligible_rows"},
        "response_schema_version": "m3-feature-worker-response-v1",
        "input_names": names, "expressions": expressions,
    }
    (output / "worker-response.json").write_bytes(_canonical(response))
    return subprocess.CompletedProcess(argv, 0, b"", b"")


def test_formal_feature_build_receipt_fresh_verify_and_horizon_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common = tmp_path / "artifacts"
    common.mkdir()
    release = _verified_g1(common / "g1", monkeypatch)
    config = _formal_config(tmp_path, release)
    snapshot, snapshot_spec, snapshot_request, snapshot_receipt = _snapshot(
        common, release, config
    )
    provider, provider_spec, tool, provider_receipt = _provider(
        common, snapshot, config, snapshot_request, snapshot_receipt, monkeypatch
    )
    roots = {"root": common, "EXTERNAL_QLIB": tool.parent}
    experiment_spec = ExperimentIdentitySpec(
        scientific_config_sha256=config.scientific_config_sha256,
        dependency_fingerprint_sha256=hashlib.sha256(b"deps").hexdigest(),
        code_version="m3-git-v1-" + "a" * 40 + "-clean",
    )
    experiment_manifest = build_experiment_identity_manifest(
        snapshot=snapshot, provider=provider, config=config, spec=experiment_spec
    )
    experiment_root = common / "experiment"
    experiment_root.mkdir()
    (experiment_root / "experiment_manifest.json").write_bytes(
        experiment_identity_manifest_bytes(experiment_manifest)
    )
    experiment_receipt = common / "receipts" / "experiment-identity" / "main.json"
    experiment_receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=experiment_receipt, stage="experiment-identity",
        scope="EXPERIMENT", scope_key=experiment_manifest.experiment_key,
        artifact_roots=roots,
        inputs=[
            ("root", snapshot_receipt), ("root", snapshot.root / "manifest.json"),
            ("root", provider_receipt),
            ("root", provider.root / "provider_manifest.json"),
        ],
        outputs=[("root", experiment_root / "experiment_manifest.json")],
    )
    experiment = verify_experiment_identity(
        experiment_root=experiment_root,
        experiment_receipt_path=experiment_receipt, snapshot=snapshot,
        provider=provider, config=config, spec=experiment_spec,
        artifact_roots=roots,
    )
    walk = config.section("walk_forward")
    fold_spec = FoldPlanBuildSpec(
        experiment_key=experiment.manifest.experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        signal_start=snapshot.request.signal_start,
        signal_end=snapshot.request.signal_end,
        train_sessions=cast(int, walk["train_sessions"]),
        validation_sessions=cast(int, walk["validation_sessions"]),
        test_sessions=cast(int, walk["test_sessions"]),
        step_sessions=cast(int, walk["step_sessions"]),
        embargo_sessions=cast(int, walk["embargo_sessions"]),
        max_horizon_sessions=10,
    )
    fold_root = common / "folds"
    fold_root.mkdir()
    build_temporal_fold_plan(
        snapshot=snapshot, experiment=experiment, config=config,
        spec=fold_spec, output_root=fold_root,
    )
    fold_receipt = common / "receipts" / "folds" / "main.json"
    fold_receipt.parent.mkdir(parents=True)
    fold_paths = FoldPlanUpstreamPaths(
        snapshot_request_path=snapshot_request,
        snapshot_receipt_path=snapshot_receipt,
        provider_dump_tool_path=tool, provider_receipt_path=provider_receipt,
        experiment_receipt_path=experiment_receipt,
    )
    publish_stage_receipt(
        receipt_path=fold_receipt, stage="folds", scope="EXPERIMENT",
        scope_key=experiment.manifest.experiment_key, artifact_roots=roots,
        inputs=[
            ("root", snapshot_request), ("root", snapshot.root / "manifest.json"),
            ("root", snapshot_receipt), ("root", snapshot.session_calendar_path),
            ("root", experiment.root / "experiment_manifest.json"),
            ("root", experiment_receipt),
        ],
        outputs=[("root", fold_root / "folds.json")],
    )
    folds = verify_fold_plan_artifact(
        root=fold_root, receipt_path=fold_receipt, release=release,
        snapshot=snapshot, snapshot_spec=snapshot_spec, provider=provider,
        provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, config=config, spec=fold_spec,
        upstream_paths=fold_paths, artifact_roots=roots,
    )
    planned = folds.manifest.folds[0]
    feature_spec = FeatureBuildSpec(
        experiment_key=experiment.manifest.experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        fold=planned.name, planned_fold_sha256=planned.planned_fold_sha256,
        provider_key=provider.manifest.provider_key,
        provider_manifest_sha256=provider.manifest_sha256,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        feature_version=cast(str, config.section("features")["feature_version"]),
        expected_qlib_version="0.9.7",
        worker_protocol_version="m3-qlib-worker-v1",
    )
    upstream = FeatureUpstreamPaths(
        fold_receipt_path=fold_receipt, fold_upstream_paths=fold_paths
    )
    feature_root = common / "features"
    feature_root.mkdir()
    calls = 0

    def worker(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        nonlocal calls
        calls += 1
        return _fake_feature_worker(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", worker)
    build_feature_artifact(
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
        config=config, spec=feature_spec, upstream_paths=upstream,
        artifact_roots=roots, python_executable=Path(sys.executable),
        output_root=feature_root, timeout_seconds=60.0,
    )
    feature_receipt = common / "receipts" / "features" / "main.json"
    feature_receipt.parent.mkdir(parents=True)
    feature_inputs = [
        ("root", release.release.manifest_path),
        ("root", dict(release.artifact_paths)["eligible_keys.parquet"]),
        ("root", snapshot_request), ("root", snapshot.root / "manifest.json"),
        ("root", snapshot_receipt), ("root", snapshot.session_calendar_path),
        ("root", provider.root / "provider_manifest.json"),
        ("root", provider_receipt),
        ("root", experiment.root / "experiment_manifest.json"),
        ("root", experiment_receipt), ("root", folds.root / "folds.json"),
        ("root", fold_receipt),
    ]
    feature_outputs = [
        ("root", feature_root / name) for name in (
            "request.json", "worker-response.json", "train.parquet",
            "validation.parquet", "test.parquet", "coverage.parquet",
            "feature_manifest.json",
        )
    ]
    publish_stage_receipt(
        receipt_path=feature_receipt, stage="features", scope="EXPERIMENT",
        scope_key=experiment.manifest.experiment_key, artifact_roots=roots,
        inputs=feature_inputs, outputs=feature_outputs,
    )
    verified = verify_feature_artifact(
        root=feature_root, receipt_path=feature_receipt, release=release,
        snapshot=snapshot, snapshot_spec=snapshot_spec, provider=provider,
        provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
        config=config, spec=feature_spec, upstream_paths=upstream,
        artifact_roots=roots,
    )
    stage_receipt = verify_stage_receipt(
        receipt_path=feature_receipt, artifact_roots=roots
    )
    assert stage_receipt is not None
    assert stage_receipt.stage == "features"
    assert stage_receipt.scope == "EXPERIMENT"
    assert {item.root_alias for item in stage_receipt.inputs} == {"root"}
    assert {item.root_alias for item in stage_receipt.outputs} == {"root"}
    assert type(verified) is VerifiedFeatureArtifact
    request = json.loads((feature_root / "request.json").read_bytes())
    assert request["release_kind"] == "formal" and "example_id" not in request
    assert "provider_uri" not in request and request["provider_uri_sha256"]
    by_horizon = {5: verified, 10: verified}
    assert by_horizon[5].manifest_sha256 == by_horizon[10].manifest_sha256
    assert by_horizon[5].feature_receipt_sha256 == by_horizon[10].feature_receipt_sha256
    assert calls == 1

    request["injected_unknown"] = "x"
    response_path = feature_root / "worker-response.json"
    response = json.loads(response_path.read_bytes())
    response["injected_unknown"] = "x"
    (feature_root / "request.json").write_bytes(_canonical(request))
    response_path.write_bytes(_canonical(response))
    drift_receipt = common / "receipts" / "features" / "schema-drift.json"
    publish_stage_receipt(
        receipt_path=drift_receipt, stage="features", scope="EXPERIMENT",
        scope_key=experiment.manifest.experiment_key, artifact_roots=roots,
        inputs=feature_inputs, outputs=feature_outputs,
    )
    with pytest.raises(ValueError, match="feature worker response invalid"):
        verify_feature_artifact(
            root=feature_root, receipt_path=drift_receipt, release=release,
            snapshot=snapshot, snapshot_spec=snapshot_spec, provider=provider,
            provider_spec=provider_spec, experiment=experiment,
            experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
            config=config, spec=feature_spec, upstream_paths=upstream,
            artifact_roots=roots,
        )
