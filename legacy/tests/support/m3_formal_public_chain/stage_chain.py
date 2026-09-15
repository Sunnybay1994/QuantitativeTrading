"""Public snapshot→backtest_plan stage chain for C0 formal resolver inputs."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast

import polars as pl

from quant.backtest.a_share_plan import (
    BacktestPlanFreshVerificationContext,
    build_backtest_plan_artifact,
    verify_backtest_plan_artifact,
)
from quant.data.m3_release import VerifiedG1Release
from quant.research.m3.alignment import (
    build_alignment_artifact,
    verify_alignment_artifact,
)
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    AlignmentBuildSpec,
    AlignmentUpstreamPaths,
    ExperimentIdentitySpec,
    FeatureBuildSpec,
    FeatureUpstreamPaths,
    FoldPlanBuildSpec,
    FoldPlanUpstreamPaths,
    LabelBuildSpec,
    ModelUpstreamPaths,
    PredictionBuildSpec,
    PredictionUpstreamPaths,
    ProviderBuildSpec,
    ProviderValidationSpec,
    SnapshotBuildResult,
    SnapshotBuildSpec,
    TargetBuildSpec,
    TargetUpstreamPaths,
)
from quant.research.m3.experiment_identity import (
    build_experiment_identity_manifest,
    experiment_identity_manifest_bytes,
)
from quant.research.m3.features import build_feature_artifact, verify_feature_artifact
from quant.research.m3.fetch_qlib_tool import build_qlib_dump_tool_spec
from quant.research.m3.folds import build_temporal_fold_plan, verify_fold_plan_artifact
from quant.research.m3.labels import (
    build_label_artifact,
    verify_experiment_identity,
    verify_label_artifact,
)
from quant.research.m3.model import (
    build_lightgbm_training_spec,
    build_model_artifact,
    verify_model_artifact,
)
from quant.research.m3.predictions import (
    build_prediction_artifact,
    verify_prediction_artifact,
)
from quant.research.m3.provider import (
    ProviderRuntimeFingerprint,
    materialize_qlib_provider,
    verify_provider_artifact,
)
from quant.research.m3.provider_validation import (
    plan_provider_probe,
    validate_provider_public_api,
    verify_provider_validation_artifact,
)
from quant.research.m3.run_state import (
    compute_experiment_key,
    compute_provider_key,
    compute_provider_validation_key,
    compute_snapshot_request_key,
    compute_work_key,
    publish_stage_receipt,
    select_artifact_root,
)
from quant.research.m3.snapshot import (
    build_snapshot_artifact,
    build_snapshot_request_record,
    verify_snapshot_artifact,
)
from quant.research.m3.targets import build_target_artifact, verify_target_artifact

_PROVIDER_FIELDS = ("open", "high", "low", "close", "vwap", "volume", "factor")
_REAL_SUBPROCESS_RUN = subprocess.run

@dataclass(frozen=True)
class StageChainResult:
    snapshot_id: str
    fold: str
    work_key: str

def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        default=lambda item: item.isoformat(), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()

def _pairs(
    paths: Sequence[Path], roots: Mapping[str, Path]
) -> list[tuple[str, Path]]:
    return [
        (select_artifact_root(path, artifact_roots=roots)[0], path) for path in paths
    ]

def _timed(timings: Any, name: str, fn: Any) -> Any:
    started = time.perf_counter()
    result = fn()
    timings.stages_seconds[name] = time.perf_counter() - started
    return result

def _mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=False)
    return path

def _outs(root: Path, *names: str) -> list[Path]:
    return [root / name for name in names]

def _rcpt(
    receipt: Path,
    *,
    stage: str,
    scope: Literal["SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "REPRO", "ACCEPTANCE"],
    scope_key: str,
    roots: Mapping[str, Path],
    inputs: Sequence[Path],
    outputs: Sequence[Path],
) -> Path:
    receipt.parent.mkdir(parents=True, exist_ok=True)
    publish_stage_receipt(
        receipt_path=receipt, stage=stage, scope=scope, scope_key=scope_key, artifact_roots=roots,
        inputs=_pairs(inputs, roots), outputs=_pairs(outputs, roots),
    )
    return receipt

def _feature_worker_boundary(
    argv: list[str], **kwargs: Any
) -> subprocess.CompletedProcess[bytes]:
    """Deterministic external worker boundary for Alpha158 only; other argv pass through."""
    if "build-alpha158-formal" not in argv:
        return _REAL_SUBPROCESS_RUN(argv, **kwargs)
    request_path = Path(argv[argv.index("--request") + 1])
    output = Path(argv[argv.index("--output-root") + 1])
    request = json.loads(request_path.read_bytes())
    names = [f"ALPHA{index:03d}" for index in range(1, 159)]
    expressions = [f"FORMAL_ALPHA158_{index:03d}" for index in range(1, 159)]
    for segment in ("train", "validation", "test"):
        records = [
            {
                "as_of": dt.date.fromisoformat(day),
                "symbol": symbol,
                **{name: float(index) for index, name in enumerate(names, 1)},
            }
            for _, day, symbol in (
                row for row in request["eligible_rows"] if row[0] == segment
            )
        ]
        schema = {
            "as_of": pl.Date,
            "symbol": pl.Utf8,
            **{name: pl.Float64 for name in names},
        }
        pl.DataFrame(records, schema=schema).write_parquet(
            output / f"raw_{segment}.parquet"
        )
    response = {
        **{key: value for key, value in request.items() if key != "eligible_rows"},
        "response_schema_version": "m3-feature-worker-response-v1",
        "input_names": names,
        "expressions": expressions,
    }
    (output / "worker-response.json").write_bytes(_canonical(response))
    return subprocess.CompletedProcess(argv, 0, b"", b"")

def publish_formal_stages_to_backtest_plan(
    *,
    project_root: Path,
    stage_root: Path,
    config: LoadedM3Config,
    release: VerifiedG1Release,
    code_version: str,
    dependency_fingerprint_sha256: str,
    provider_runtime_fingerprint: ProviderRuntimeFingerprint,
    horizon: int,
    timings: Any,
) -> StageChainResult:
    external = project_root / "data" / "external" / "qlib" / "v0.9.7"
    dump_tool_path = external / "dump_bin.py"
    roots: dict[str, Path] = {
        "G1_RELEASE": release.release.root,
        "G8": stage_root,
        "EXTERNAL_QLIB": external,
    }
    py = Path(sys.executable)
    receipts = stage_root / "receipts"
    g1 = dict(release.artifact_paths)
    g1_manifest = release.release.manifest_path
    quality = release.release.root / "quality.json"
    snap_spec = SnapshotBuildSpec(
        snapshot_request_key=compute_snapshot_request_key(
            g1_release_id=release.manifest.release_id, g1_release_manifest_sha256=release.manifest_sha256,
            snapshot_config_sha256=config.snapshot_config_sha256, code_version=code_version,
        ),
        config_version=config.config_version, snapshot_config_sha256=config.snapshot_config_sha256,
        code_version=code_version, history_start=release.manifest.history_start,
        history_end=release.manifest.history_end, staging_schema_version="m3-qlib-staging-v1",
        adjustment_formula_version="qlib_yahoo_like_v1",
    )

    def _snapshot() -> Any:
        build_dir = _mkdir(stage_root / ".tmp_snapshot_build")
        built = build_snapshot_artifact(
            release=release, config=config, spec=snap_spec, output_root=build_dir
        )
        final = stage_root / "snapshots" / built.manifest.snapshot_id
        if final.exists():
            raise FileExistsError(final)
        final.parent.mkdir(parents=True, exist_ok=True)
        build_dir.rename(final)
        result = SnapshotBuildResult(
            root=final.resolve(strict=True), manifest=built.manifest, manifest_sha256=built.manifest_sha256,
        )
        request = build_snapshot_request_record(
            release=release, config=config, spec=snap_spec, result=result
        )
        req_path = (
            stage_root / "snapshot-requests" / f"{snap_spec.snapshot_request_key}.json"
        )
        req_path.parent.mkdir(parents=True, exist_ok=True)
        req_path.write_bytes(_canonical(asdict(request)))
        receipt = _rcpt(
            receipts / "snapshot" / f"{snap_spec.snapshot_request_key}.json",
            stage="snapshot", scope="SNAPSHOT", scope_key=snap_spec.snapshot_request_key, roots=roots,
            inputs=[
                g1_manifest,
                g1["bar_1d.parquet"],
                g1["universe_membership.parquet"],
                g1["trade_calendar.parquet"],
            ],
            outputs=[
                req_path,
                final / "manifest.json",
                final / "session_calendar.parquet",
                *sorted((final / "staging").glob("*.parquet")),
            ],
        )
        return (
            verify_snapshot_artifact(
                snapshot_root=final, snapshot_request_path=req_path, snapshot_receipt_path=receipt,
                release=release, config=config, spec=snap_spec, artifact_roots=roots,
            ),
            req_path,
            receipt,
        )
    snapshot, snap_req, snap_receipt = _timed(timings, "snapshot", _snapshot)
    snap_id = snapshot.manifest.snapshot_id
    snap_manifest = snapshot.root / "manifest.json"
    tool_spec = build_qlib_dump_tool_spec(config)
    provider_spec = ProviderBuildSpec(
        snapshot_id=snap_id, snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_key=compute_provider_key(
            snapshot_id=snap_id, provider_config_hash=config.provider_config_sha256,
            dump_tool_sha256=tool_spec.sha256, qlib_version=tool_spec.qlib_version,
            provider_runtime_fingerprint_sha256=provider_runtime_fingerprint.sha256,
            code_version=code_version,
        ),
        provider_config_sha256=config.provider_config_sha256, dump_tool=tool_spec, qlib_version="0.9.7",
        code_version=code_version, runtime_fingerprint=provider_runtime_fingerprint,
        fields=_PROVIDER_FIELDS, frequency="day", dump_contract_version="m3-qlib-dump-all-v1",
    )

    def _provider() -> Any:
        out = _mkdir(stage_root / "providers" / provider_spec.provider_key)
        built = materialize_qlib_provider(
            snapshot=snapshot, qlib_dump_script=dump_tool_path, python_executable=py, config=config,
            spec=provider_spec, output_root=out, timeout_seconds=3600.0,
        )
        receipt = _rcpt(
            receipts / "provider" / f"{provider_spec.provider_key}.json",
            stage="provider", scope="PROVIDER", scope_key=provider_spec.provider_key, roots=roots,
            inputs=[
                snap_manifest,
                snap_req,
                snap_receipt,
                snapshot.session_calendar_path,
                *snapshot.staging_paths,
                dump_tool_path,
            ],
            outputs=[
                built.root / "provider_manifest.json",
                *(built.root / item.relative_path for item in built.manifest.files),
            ],
        )
        return (
            verify_provider_artifact(
                provider_root=built.root, provider_receipt_path=receipt, snapshot=snapshot, config=config,
                artifact_roots=roots,
            ),
            receipt,
        )
    provider, provider_receipt = _timed(timings, "provider", _provider)
    provider_manifest = provider.root / "provider_manifest.json"
    validation_key = compute_provider_validation_key(
        provider_key=provider.manifest.provider_key,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        provider_validation_config_sha256=config.provider_validation_config_sha256,
        provider_runtime_fingerprint_sha256=provider_runtime_fingerprint.sha256,
        code_version=code_version,
    )
    validation_spec = ProviderValidationSpec(
        provider_validation_key=validation_key,
        provider_validation_config_sha256=config.provider_validation_config_sha256,
        code_version=code_version, qlib_version="0.9.7",
        sampling_policy_version="provider_market_stratified_hash_first_last_v1",
        worker_protocol_version="m3-qlib-worker-v1",
    )

    def _validation() -> Any:
        out = _mkdir(stage_root / "provider-validations" / validation_key)
        probe = plan_provider_probe(
            snapshot=snapshot, provider=provider, config=config, spec=validation_spec
        )
        validate_provider_public_api(
            snapshot=snapshot, provider=provider, probe_plan=probe, config=config, spec=validation_spec,
            python_executable=py, output_root=out, timeout_seconds=1800.0,
        )
        receipt = _rcpt(
            receipts / "provider-validation" / f"{validation_key}.json",
            stage="provider-validation", scope="PROVIDER", scope_key=validation_key, roots=roots,
            inputs=[
                snap_manifest,
                snapshot.session_calendar_path,
                *snapshot.staging_paths,
                provider_manifest,
                *(
                    provider.root / item.relative_path
                    for item in provider.manifest.files
                ),
                snap_req,
                snap_receipt,
                provider_receipt,
            ],
            outputs=_outs(
                out, "provider_validation.parquet", "provider_validation.json"
            ),
        )
        return (
            verify_provider_validation_artifact(
                validation_root=out, validation_receipt_path=receipt, snapshot=snapshot, provider=provider,
                config=config, spec=validation_spec, artifact_roots=roots,
            ),
            receipt,
        )
    _timed(timings, "provider-validation", _validation)
    experiment_spec = ExperimentIdentitySpec(
        scientific_config_sha256=config.scientific_config_sha256,
        dependency_fingerprint_sha256=dependency_fingerprint_sha256, code_version=code_version,
    )
    experiment_key = compute_experiment_key(
        snapshot_id=snap_id, provider_receipt_sha256=provider.provider_receipt_sha256,
        scientific_config_hash=config.scientific_config_sha256, code_version=code_version,
        dependency_fingerprint_sha256=dependency_fingerprint_sha256,
    )

    def _experiment() -> Any:
        manifest = build_experiment_identity_manifest(
            snapshot=snapshot, provider=provider, config=config, spec=experiment_spec
        )
        out = _mkdir(stage_root / "runs" / experiment_key)
        (out / "experiment_manifest.json").write_bytes(
            experiment_identity_manifest_bytes(manifest)
        )
        receipt = _rcpt(
            receipts / "experiment-identity" / f"{experiment_key}.json",
            stage="experiment-identity", scope="EXPERIMENT", scope_key=experiment_key, roots=roots,
            inputs=[snap_receipt, snap_manifest, provider_receipt, provider_manifest],
            outputs=[out / "experiment_manifest.json"],
        )
        return (
            verify_experiment_identity(
                experiment_root=out, experiment_receipt_path=receipt, snapshot=snapshot, provider=provider,
                config=config, spec=experiment_spec, artifact_roots=roots,
            ),
            receipt,
        )
    experiment, experiment_receipt = _timed(timings, "experiment", _experiment)
    experiment_manifest = experiment.root / "experiment_manifest.json"
    label_spec = LabelBuildSpec(
        experiment_key=experiment_key, experiment_manifest_sha256=experiment.manifest_sha256,
        horizon_sessions=cast(Any, horizon), benchmark=cast(Any, config.section("data")["benchmark"]),
        label_version=cast(str, config.section("labels")["label_version"]),
        label_build_code_version=code_version,
    )

    def _labels() -> Any:
        out = _mkdir(stage_root / "labels" / experiment_key / f"h{horizon}")
        build_label_artifact(
            release=release, snapshot=snapshot, experiment=experiment, config=config,
            experiment_spec=experiment_spec, spec=label_spec, output_root=out,
        )
        receipt = _rcpt(
            receipts / "labels" / f"{experiment_key}-h{horizon}.json",
            stage="labels", scope="EXPERIMENT", scope_key=experiment_key, roots=roots,
            inputs=[
                experiment_receipt,
                experiment_manifest,
                g1_manifest,
                g1["bar_1d.parquet"],
                g1["benchmark_bar_1d.parquet"],
                g1["eligible_keys.parquet"],
                snap_receipt,
                snap_manifest,
                snapshot.session_calendar_path,
            ],
            outputs=_outs(
                out, "diagnostics.parquet", "label_manifest.json", "labels.parquet"
            ),
        )
        return (
            verify_label_artifact(
                label_root=out, label_receipt_path=receipt, release=release, snapshot=snapshot,
                experiment=experiment, config=config, experiment_spec=experiment_spec, spec=label_spec,
                artifact_roots=roots,
            ),
            receipt,
        )
    label, label_receipt = _timed(timings, "label", _labels)
    walk = config.section("walk_forward")
    fold_spec = FoldPlanBuildSpec(
        experiment_key=experiment_key, experiment_manifest_sha256=experiment.manifest_sha256,
        snapshot_id=snap_id, snapshot_manifest_sha256=snapshot.manifest_sha256,
        signal_start=snapshot.request.signal_start, signal_end=snapshot.request.signal_end,
        train_sessions=cast(int, walk["train_sessions"]),
        validation_sessions=cast(int, walk["validation_sessions"]),
        test_sessions=cast(int, walk["test_sessions"]), step_sessions=cast(int, walk["step_sessions"]),
        embargo_sessions=cast(int, walk["embargo_sessions"]),
        max_horizon_sessions=max(
            cast(tuple[int, ...], config.section("labels")["horizons_sessions"])
        ),
    )
    fold_upstream = FoldPlanUpstreamPaths(
        snapshot_request_path=snap_req, snapshot_receipt_path=snap_receipt,
        provider_dump_tool_path=dump_tool_path, provider_receipt_path=provider_receipt,
        experiment_receipt_path=experiment_receipt,
    )

    def _base_vk(**extra: Any) -> dict[str, Any]:
        return {
            "release": release,
            "snapshot": snapshot,
            "snapshot_spec": snap_spec,
            "provider": provider,
            "provider_spec": provider_spec,
            "experiment": experiment,
            "experiment_spec": experiment_spec,
            "config": config,
            "artifact_roots": roots,
            **extra,
        }

    def _folds() -> Any:
        out = _mkdir(stage_root / "folds" / experiment_key)
        build_temporal_fold_plan(
            snapshot=snapshot, experiment=experiment, config=config, spec=fold_spec, output_root=out,
        )
        receipt = _rcpt(
            receipts / "folds" / f"{experiment_key}.json",
            stage="folds", scope="EXPERIMENT", scope_key=experiment_key, roots=roots,
            inputs=[
                snap_req,
                snap_manifest,
                snap_receipt,
                snapshot.session_calendar_path,
                experiment_manifest,
                experiment_receipt,
            ],
            outputs=[out / "folds.json"],
        )
        return (
            verify_fold_plan_artifact(
                root=out, receipt_path=receipt,
                **_base_vk(spec=fold_spec, upstream_paths=fold_upstream),
            ),
            receipt,
        )
    folds, fold_receipt = _timed(timings, "folds", _folds)
    planned = folds.manifest.folds[0]
    fold_name = planned.name
    folds_json = folds.root / "folds.json"

    def _vk(**extra: Any) -> dict[str, Any]:
        return _base_vk(folds=folds, fold_spec=fold_spec, **extra)
    feature_spec = FeatureBuildSpec(
        experiment_key=experiment_key, experiment_manifest_sha256=experiment.manifest_sha256,
        fold=fold_name, planned_fold_sha256=planned.planned_fold_sha256,
        provider_key=provider.manifest.provider_key, provider_manifest_sha256=provider.manifest_sha256,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        feature_version=cast(str, config.section("features")["feature_version"]),
        expected_qlib_version="0.9.7", worker_protocol_version="m3-qlib-worker-v1",
    )
    feature_upstream = FeatureUpstreamPaths(
        fold_receipt_path=fold_receipt, fold_upstream_paths=fold_upstream
    )

    def _features() -> Any:
        out = _mkdir(stage_root / "features" / experiment_key / fold_name)
        previous = subprocess.run
        subprocess.run = _feature_worker_boundary  # type: ignore[assignment]
        try:
            build_feature_artifact(
                **_vk(
                    spec=feature_spec, upstream_paths=feature_upstream, python_executable=py, output_root=out,
                    timeout_seconds=1800.0,
                )
            )
        finally:
            subprocess.run = previous  # type: ignore[assignment]
        receipt = _rcpt(
            receipts / "features" / f"{experiment_key}.{fold_name}.json",
            stage="features", scope="EXPERIMENT", scope_key=experiment_key, roots=roots,
            inputs=[
                g1_manifest,
                g1["eligible_keys.parquet"],
                snap_req,
                snap_manifest,
                snap_receipt,
                snapshot.session_calendar_path,
                provider_manifest,
                provider_receipt,
                experiment_manifest,
                experiment_receipt,
                folds_json,
                fold_receipt,
            ],
            outputs=_outs(
                out,
                "coverage.parquet",
                "feature_manifest.json",
                "request.json",
                "test.parquet",
                "train.parquet",
                "validation.parquet",
                "worker-response.json",
            ),
        )
        return (
            verify_feature_artifact(
                root=out, receipt_path=receipt,
                **_vk(spec=feature_spec, upstream_paths=feature_upstream),
            ),
            receipt,
        )
    feature, feature_receipt = _timed(timings, "feature", _features)
    feature_manifest = feature.root / "feature_manifest.json"
    label_manifest = label.root / "label_manifest.json"
    work_key = compute_work_key(
        experiment_key=experiment_key, fold=fold_name, horizon=horizon
    )
    alignment_spec = AlignmentBuildSpec(
        experiment_key=experiment_key, work_key=work_key, fold=fold_name,
        planned_fold_sha256=planned.planned_fold_sha256, horizon_sessions=cast(Any, horizon),
        feature_manifest_sha256=feature.manifest_sha256, label_manifest_sha256=label.manifest_sha256,
    )
    alignment_upstream = AlignmentUpstreamPaths(
        feature_receipt_path=feature_receipt, feature_upstream_paths=feature_upstream,
        label_receipt_path=label_receipt,
    )

    def _alignment() -> Any:
        out = _mkdir(stage_root / "work" / work_key / "alignment")
        build_alignment_artifact(
            feature=feature, label=label, folds=folds, experiment=experiment, config=config,
            spec=alignment_spec, output_root=out,
        )
        receipt = _rcpt(
            receipts / "alignment" / f"{work_key}.json",
            stage="alignment", scope="WORK", scope_key=work_key, roots=roots,
            inputs=[
                feature_manifest,
                feature_receipt,
                label_manifest,
                label_receipt,
                folds_json,
                fold_receipt,
                experiment_manifest,
            ],
            outputs=_outs(
                out,
                "alignment_manifest.json",
                "diagnostics.parquet",
                "train.parquet",
                "validation.parquet",
            ),
        )
        return (
            verify_alignment_artifact(
                root=out, receipt_path=receipt,
                **_vk(
                    feature=feature, feature_spec=feature_spec, label=label, label_spec=label_spec,
                    spec=alignment_spec, upstream_paths=alignment_upstream,
                ),
            ),
            receipt,
        )
    alignment, alignment_receipt = _timed(timings, "alignment", _alignment)
    model_spec = build_lightgbm_training_spec(config)
    model_upstream = ModelUpstreamPaths(
        alignment_receipt_path=alignment_receipt, alignment_upstream_paths=alignment_upstream,
    )

    def _work_vk(**extra: Any) -> dict[str, Any]:
        return _vk(
            feature=feature, feature_spec=feature_spec, label=label, label_spec=label_spec,
            alignment=alignment, alignment_spec=alignment_spec,
            **extra,
        )

    def _model() -> Any:
        out = _mkdir(stage_root / "work" / work_key / "train")
        build_model_artifact(
            **_work_vk(
                spec=model_spec, upstream_paths=model_upstream, output_root=out
            )
        )
        receipt = _rcpt(
            receipts / "train" / f"{work_key}.json",
            stage="model", scope="WORK", scope_key=work_key, roots=roots,
            inputs=[
                alignment.root / "alignment_manifest.json",
                alignment_receipt,
                feature_manifest,
                feature_receipt,
                label_manifest,
                label_receipt,
                experiment_manifest,
            ],
            outputs=_outs(
                out, "model.metadata.json", "model.txt", "validation_curve.parquet"
            ),
        )
        return (
            verify_model_artifact(
                root=out, receipt_path=receipt,
                **_work_vk(spec=model_spec, upstream_paths=model_upstream),
            ),
            receipt,
        )
    model, model_receipt = _timed(timings, "model", _model)
    prediction_spec = PredictionBuildSpec(
        experiment_key=experiment_key, work_key=work_key, fold=fold_name,
        horizon_sessions=cast(Any, horizon), model="lightgbm",
        model_version=model.manifest.model_version,
    )
    prediction_upstream = PredictionUpstreamPaths(
        model_receipt_path=model_receipt, model_upstream_paths=model_upstream,
        feature_receipt_path=feature_receipt, feature_upstream_paths=feature_upstream,
        fold_receipt_path=fold_receipt,
    )

    def _pred_vk(**extra: Any) -> dict[str, Any]:
        return _work_vk(model=model, model_spec=model_spec, **extra)

    def _prediction() -> Any:
        out = _mkdir(stage_root / "work" / work_key / "predictions")
        build_prediction_artifact(
            **_pred_vk(
                spec=prediction_spec, upstream_paths=prediction_upstream, output_root=out,
            )
        )
        receipt = _rcpt(
            receipts / "predictions" / f"{work_key}.json",
            stage="predictions", scope="WORK", scope_key=work_key, roots=roots,
            inputs=[
                model.root / "model.metadata.json",
                model_receipt,
                feature_manifest,
                feature_receipt,
                folds_json,
                fold_receipt,
                experiment_manifest,
                alignment_receipt,
            ],
            outputs=_outs(out, "prediction_manifest.json", "predictions.parquet"),
        )
        return (
            verify_prediction_artifact(
                root=out, receipt_path=receipt,
                **_pred_vk(spec=prediction_spec, upstream_paths=prediction_upstream),
            ),
            receipt,
        )
    prediction, prediction_receipt = _timed(timings, "prediction", _prediction)
    portfolio = config.section("portfolio")
    features_cfg = config.section("features")
    target_spec = TargetBuildSpec(
        experiment_key=experiment_key, work_key=work_key, fold=fold_name,
        horizon_sessions=cast(Any, horizon), strategy=cast(Any, portfolio["strategy"]),
        strategy_version=cast(str, portfolio["strategy_version"]), top_k=cast(int, portfolio["top_k"]),
        cash_buffer=cast(float, portfolio["cash_buffer"]),
        max_weight=cast(float, portfolio["max_weight"]),
        minimum_scorable_coverage=cast(
            float, features_cfg["minimum_scorable_coverage"]
        ),
    )
    target_upstream = TargetUpstreamPaths(
        feature_receipt_path=feature_receipt, prediction_receipt_path=prediction_receipt,
        prediction_upstream_paths=prediction_upstream, fold_receipt_path=fold_receipt,
        experiment_receipt_path=experiment_receipt,
    )

    def _tgt_vk(**extra: Any) -> dict[str, Any]:
        return _pred_vk(
            prediction=prediction, prediction_spec=prediction_spec, **extra
        )

    def _target_chain_inputs(*, include_target: bool) -> list[Path]:
        items = [
            g1_manifest,
            quality,
            g1["eligible_keys.parquet"],
            feature_manifest,
            feature_receipt,
            feature.root / "coverage.parquet",
            feature.root / "test.parquet",
            prediction.root / "prediction_manifest.json",
            prediction_receipt,
            prediction.root / "predictions.parquet",
            folds_json,
            fold_receipt,
            experiment_manifest,
            experiment_receipt,
        ]
        if include_target:
            items.extend(
                [
                    target.root / "target_manifest.json",
                    target_receipt,
                    target.root / "target_weights.parquet",
                    target.root / "target_daily.parquet",
                    g1["trade_calendar.parquet"],
                ]
            )
        return items

    def _target() -> Any:
        out = _mkdir(stage_root / "work" / work_key / "targets")
        build_target_artifact(
            **_tgt_vk(
                spec=target_spec, upstream_paths=target_upstream, output_root=out
            )
        )
        receipt = _rcpt(
            receipts / "targets" / f"{work_key}.json",
            stage="targets", scope="WORK", scope_key=work_key, roots=roots,
            inputs=_target_chain_inputs(include_target=False),
            outputs=_outs(
                out,
                "target_daily.parquet",
                "target_manifest.json",
                "target_weights.parquet",
            ),
        )
        return (
            verify_target_artifact(
                root=out, receipt_path=receipt,
                **_tgt_vk(spec=target_spec, upstream_paths=target_upstream),
            ),
            receipt,
        )
    target, target_receipt = _timed(timings, "target", _target)
    plan_fresh = BacktestPlanFreshVerificationContext(
        snapshot=snapshot, snapshot_spec=snap_spec, provider=provider, provider_spec=provider_spec,
        experiment_spec=experiment_spec, fold_spec=fold_spec, feature=feature, feature_spec=feature_spec,
        label=label, label_spec=label_spec, alignment=alignment, alignment_spec=alignment_spec,
        model=model, model_spec=model_spec, prediction=prediction, prediction_spec=prediction_spec,
        target_spec=target_spec, target_upstream_paths=target_upstream,
        target_receipt_path=target_receipt,
    )

    def _plan() -> Any:
        out = _mkdir(stage_root / "work" / work_key / "backtest_plan")
        build_backtest_plan_artifact(
            target=target, release=release, folds=folds, experiment=experiment, config=config,
            fresh_context=plan_fresh, artifact_roots=roots, output_root=out,
        )
        receipt = _rcpt(
            receipts / "backtest_plan" / f"{work_key}.json",
            stage="backtest-plan", scope="WORK", scope_key=work_key, roots=roots,
            inputs=_target_chain_inputs(include_target=True),
            outputs=_outs(
                out,
                "cost_schedule.json",
                "manifest.json",
                "schedule_diagnostics.parquet",
                "scheduled_targets.parquet",
            ),
        )
        return verify_backtest_plan_artifact(
            root=out, receipt_path=receipt, target=target, release=release, folds=folds,
            experiment=experiment, config=config, fresh_context=plan_fresh, artifact_roots=roots,
        )
    _timed(timings, "backtest_plan", _plan)
    timings.file_counts["stage_tree"] = sum(
        1 for _ in stage_root.rglob("*") if _.is_file()
    )
    return StageChainResult(snapshot_id=snap_id, fold=fold_name, work_key=work_key)
