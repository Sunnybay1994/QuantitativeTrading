"""Fresh-process formal train/predict/evaluate reproducibility (G8E)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, NoReturn, cast

import polars as pl

from quant.research.m3.config import LoadedM3Config, load_m3_config
from quant.research.m3.contracts import (
    EvaluationSpec,
    EvaluationUpstreamPaths,
    ModelUpstreamPaths,
    PredictionBuildSpec,
    PredictionUpstreamPaths,
)
from quant.research.m3.evaluate import (
    build_evaluation_artifact,
    verify_evaluation_artifact,
)
from quant.research.m3.formal_cli_resolve import (
    FormalReproducibilityCliResolution,
    resolve_formal_reproducibility_cli_inputs,
)
from quant.research.m3.model import (
    build_lightgbm_training_spec,
    build_model_artifact,
    training_params_sha256,
    verify_model_artifact,
)
from quant.research.m3.orchestration import (
    ExternalInput,
    REPRODUCIBILITY_STAGE_SPEC,
    StageBuildReport,
    StageContext,
    StageNode,
    StageRunner,
    StaticDirectoryPublication,
)
from quant.research.m3.predictions import (
    build_prediction_artifact,
    verify_prediction_artifact,
)
from quant.research.m3.run_state import ArtifactDigest, StageReceipt, publish_stage_receipt

_HEX64 = frozenset("0123456789abcdef")
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_ATTEMPT_FILES = frozenset(
    {
        "model.txt",
        "model.metadata.json",
        "predictions.parquet",
        "prediction_manifest.json",
        "daily_ic.parquet",
        "metrics.json",
        "read_audit.json",
    }
)
_CODE = "M3_REPRODUCIBILITY_INVALID"
_ROLLBACK_CODE = "M3_REPRODUCIBILITY_ROLLBACK_FAILED"
_WORKER_PROTOCOL = "m3-reproducibility-worker-v1"
_REPORT_SCHEMA = "m3-reproducibility-v1"
_AUDIT_SCHEMA = "m3-reproducibility-read-audit-v1"


class M3ReproducibilityError(ValueError):
    """Stable, redacted G8E failure."""

    code: str

    def __init__(self, code: str = _CODE) -> None:
        if code not in {_CODE, _ROLLBACK_CODE}:
            raise ValueError("unknown reproducibility error")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FormalReproducibilityResult:
    comparison_key: str
    root: Path
    receipt_path: Path
    receipt: StageReceipt
    reused: bool

    def __post_init__(self) -> None:
        if (
            not _is_hex64(self.comparison_key)
            or not isinstance(self.root, Path)
            or not isinstance(self.receipt_path, Path)
            or type(self.receipt) is not StageReceipt
            or type(self.reused) is not bool
        ):
            raise M3ReproducibilityError()

    def __reduce__(self) -> Any:
        raise TypeError(_CODE)


def run_formal_reproducibility_stage(
    *,
    project_root: Path,
    config: LoadedM3Config,
    config_relative: PurePosixPath,
    snapshot_id: str,
    fold: str,
    horizon: int,
    python_executable: Path,
    resume: bool = True,
) -> FormalReproducibilityResult:
    """Run two isolated formal attempts and publish one strict REPRO receipt."""
    failed = False
    rollback_failed = False
    result: FormalReproducibilityResult | None = None
    try:
        result = _run_stage(
            project_root=project_root,
            config=config,
            config_relative=config_relative,
            snapshot_id=snapshot_id,
            fold=fold,
            horizon=horizon,
            python_executable=python_executable,
            resume=resume,
        )
    except M3ReproducibilityError as error:
        rollback_failed = error.code == _ROLLBACK_CODE
        failed = not rollback_failed
    except Exception:
        failed = True
    if rollback_failed:
        _fail(_ROLLBACK_CODE)
    if failed or result is None:
        _fail(_CODE)
    return result


def verify_formal_reproducibility_artifact(
    *,
    root: Path,
    receipt_path: Path,
    artifact_roots: Mapping[str, Path],
    comparison_key: str,
    score_atol: float,
    metric_atol: float,
    code_version: str,
    dependency_fingerprint_sha256: str,
    python_executable_sha256: str,
) -> FormalReproducibilityResult:
    """Recompute the portable comparison and verify its strict stage receipt."""
    failed = False
    result: FormalReproducibilityResult | None = None
    try:
        _verify_comparison_tree(
            root=root,
            comparison_key=comparison_key,
            score_atol=score_atol,
            metric_atol=metric_atol,
            code_version=code_version,
            dependency_fingerprint_sha256=dependency_fingerprint_sha256,
            python_executable_sha256=python_executable_sha256,
        )
        from quant.research.m3.run_state import verify_stage_receipt

        receipt = verify_stage_receipt(receipt_path=receipt_path, artifact_roots=artifact_roots)
        if (
            type(receipt) is not StageReceipt
            or receipt.stage != "reproducibility"
            or receipt.scope != "REPRO"
            or receipt.scope_key != comparison_key
            or any(
                item.root_alias != "PROJECT"
                for item in (*receipt.inputs, *receipt.outputs)
            )
        ):
            raise ValueError
        result = FormalReproducibilityResult(
            comparison_key=comparison_key,
            root=root.resolve(strict=True),
            receipt_path=receipt_path.resolve(strict=True),
            receipt=receipt,
            reused=True,
        )
    except Exception:
        failed = True
    if failed or result is None:
        _fail(_CODE)
    return result


def _run_stage(
    *,
    project_root: Path,
    config: LoadedM3Config,
    config_relative: PurePosixPath,
    snapshot_id: str,
    fold: str,
    horizon: int,
    python_executable: Path,
    resume: bool,
) -> FormalReproducibilityResult:
    if (
        type(config) is not LoadedM3Config
        or not isinstance(config_relative, PurePosixPath)
        or type(resume) is not bool
    ):
        raise ValueError
    root = _real_directory(project_root)
    executable = _real_file(python_executable)
    resolution = resolve_formal_reproducibility_cli_inputs(
        project_root=root,
        config=config,
        config_relative=config_relative,
        snapshot_id=snapshot_id,
        fold=fold,
        horizon=horizon,
    )
    model_spec = build_lightgbm_training_spec(config)
    acceptance = config.section("acceptance")
    score_atol = _finite_nonnegative_float(acceptance["reproducibility_score_atol"])
    metric_atol = _finite_nonnegative_float(acceptance["reproducibility_metric_atol"])
    comparison_key = _comparison_key(
        resolution=resolution,
        params_sha256=training_params_sha256(model_spec),
        score_atol=score_atol,
        metric_atol=metric_atol,
        python_executable_sha256=_file_sha256(executable),
    )
    python_executable_sha256 = _file_sha256(executable)
    artifact_roots = _project_only_artifact_roots(root)
    inputs = _external_inputs(
        resolution=resolution,
        project_root=root,
        config_path=root.joinpath(*config_relative.parts),
        artifact_roots=artifact_roots,
    )
    node = StageNode(
        node_id=f"reproducibility-{comparison_key[:16]}",
        spec_name=REPRODUCIBILITY_STAGE_SPEC.name,
        scope="REPRO",
        scope_key=comparison_key,
        fold=fold,
        horizon=horizon,
        dependencies=(),
        inputs=inputs,
        publication=StaticDirectoryPublication(f"repro/{comparison_key}"),
        output_specs=REPRODUCIBILITY_STAGE_SPEC.outputs,
        receipt_path=f"receipts/reproducibility/{comparison_key}.json",
    )
    runner = StageRunner(
        stage_root=resolution.stage_root,
        artifact_roots=artifact_roots,
        config=config,
    )

    def handler(context: StageContext) -> StageBuildReport:
        for attempt in (1, 2):
            _launch_worker(
                python_executable=executable,
                project_root=root,
                config_relative=config_relative,
                snapshot_id=snapshot_id,
                fold=fold,
                horizon=horizon,
                attempt=attempt,
                attempt_root=context.temp_output_root / f"attempt={attempt}",
            )
        _write_comparison(
            root=context.temp_output_root,
            comparison_key=comparison_key,
            score_atol=score_atol,
            metric_atol=metric_atol,
            code_version=resolution.runtime.code_version,
            dependency_fingerprint_sha256=(resolution.runtime.dependency_fingerprint_sha256),
            python_executable_sha256=python_executable_sha256,
        )
        return StageBuildReport(
            tuple(
                path.relative_to(context.temp_output_root).as_posix()
                for path in _regular_files(context.temp_output_root)
            )
        )

    def closure(candidate: Path) -> None:
        _verify_comparison_tree(
            root=candidate,
            comparison_key=comparison_key,
            score_atol=score_atol,
            metric_atol=metric_atol,
            code_version=resolution.runtime.code_version,
            dependency_fingerprint_sha256=(resolution.runtime.dependency_fingerprint_sha256),
            python_executable_sha256=python_executable_sha256,
        )

    static = runner.run_static(node=node, handler=handler, closure_verifier=closure, resume=resume)
    return FormalReproducibilityResult(
        comparison_key=comparison_key,
        root=static.final_root,
        receipt_path=static.receipt_path,
        receipt=static.receipt,
        reused=static.reused,
    )


def _comparison_key(
    *,
    resolution: FormalReproducibilityCliResolution,
    params_sha256: str,
    score_atol: float,
    metric_atol: float,
    python_executable_sha256: str,
) -> str:
    return compute_formal_reproducibility_comparison_key(
        work_key=resolution.work_key,
        feature_receipt_sha256=resolution.feature.feature_receipt_sha256,
        label_receipt_sha256=resolution.label.label_receipt_sha256,
        alignment_receipt_sha256=resolution.alignment.alignment_receipt_sha256,
        params_sha256=params_sha256,
        code_version=resolution.runtime.code_version,
        dependency_fingerprint_sha256=(
            resolution.runtime.dependency_fingerprint_sha256
        ),
        python_executable_sha256=python_executable_sha256,
        acceptance_config_sha256=resolution.config.acceptance_config_sha256,
        score_atol=score_atol,
        metric_atol=metric_atol,
    )


def compute_formal_reproducibility_comparison_key(
    *,
    work_key: str,
    feature_receipt_sha256: str,
    label_receipt_sha256: str,
    alignment_receipt_sha256: str,
    params_sha256: str,
    code_version: str,
    dependency_fingerprint_sha256: str,
    python_executable_sha256: str,
    acceptance_config_sha256: str,
    score_atol: float,
    metric_atol: float,
) -> str:
    """Return the single public G8E comparison identity formula."""
    hashes = (
        work_key,
        feature_receipt_sha256,
        label_receipt_sha256,
        alignment_receipt_sha256,
        params_sha256,
        dependency_fingerprint_sha256,
        python_executable_sha256,
        acceptance_config_sha256,
    )
    if (
        any(not _is_hex64(value) for value in hashes)
        or type(code_version) is not str
        or not code_version
        or type(score_atol) is not float
        or not math.isfinite(score_atol)
        or score_atol < 0.0
        or type(metric_atol) is not float
        or not math.isfinite(metric_atol)
        or metric_atol < 0.0
    ):
        _fail(_CODE)
    payload = [
        "m3-reproducibility-comparison-v1",
        work_key,
        feature_receipt_sha256,
        label_receipt_sha256,
        alignment_receipt_sha256,
        params_sha256,
        code_version,
        dependency_fingerprint_sha256,
        python_executable_sha256,
        acceptance_config_sha256,
        _canonical_float(score_atol),
        _canonical_float(metric_atol),
    ]
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _external_inputs(
    *,
    resolution: FormalReproducibilityCliResolution,
    project_root: Path,
    config_path: Path,
    artifact_roots: Mapping[str, Path],
) -> tuple[ExternalInput, ...]:
    paths = {
        config_path,
        project_root / "pyproject.toml",
        resolution.feature.root / "feature_manifest.json",
        resolution.feature_receipt_path,
        resolution.label.root / "label_manifest.json",
        resolution.label_receipt_path,
        resolution.alignment.root / "alignment_manifest.json",
        resolution.alignment_receipt_path,
    }
    paths.update(project_root / item.relative_path for item in resolution.runtime.source_files)
    return tuple(
        ExternalInput(_digest_for_path(path, artifact_roots=artifact_roots))
        for path in sorted(paths, key=lambda item: str(item).casefold())
    )


def _project_only_artifact_roots(project_root: Path) -> Mapping[str, Path]:
    """Return the one non-overlapping root used by the REPRO receipt."""
    return MappingProxyType({"PROJECT": project_root})


def _launch_worker(
    *,
    python_executable: Path,
    project_root: Path,
    config_relative: PurePosixPath,
    snapshot_id: str,
    fold: str,
    horizon: int,
    attempt: int,
    attempt_root: Path,
) -> None:
    if attempt not in {1, 2}:
        raise ValueError
    bootstrap = (
        "import sys;"
        "sys.path.insert(0, sys.argv[1]);"
        "from quant.research.m3.reproducibility import _worker_entry;"
        "raise SystemExit(_worker_entry(sys.argv[2:]))"
    )
    with tempfile.TemporaryDirectory(prefix=f"m3-repro-{attempt}-") as private:
        private_root = Path(private)
        env = _worker_environment(private_root)
        command = (
            str(python_executable),
            "-I",
            "-c",
            bootstrap,
            str(project_root / "src"),
            str(project_root),
            config_relative.as_posix(),
            snapshot_id,
            fold,
            str(horizon),
            str(attempt),
            str(attempt_root),
        )
        completed = subprocess.run(
            command,
            cwd=project_root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=3600,
            check=False,
        )
    if completed.returncode != 0 or completed.stdout != b"G8E_WORKER_OK\n":
        raise ValueError


def _worker_environment(private_root: Path) -> dict[str, str]:
    keep = (
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "HOME",
        "USERPROFILE",
        "CONDA_PREFIX",
        "LD_LIBRARY_PATH",
        "LANG",
        "LC_ALL",
    )
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env.update(
        {
            "PYTHONHASHSEED": "0",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "TEMP": str(private_root),
            "TMP": str(private_root),
            "TMPDIR": str(private_root),
            "XDG_CACHE_HOME": str(private_root / "cache"),
        }
    )
    return env


def _worker_entry(argv: Sequence[str]) -> int:
    try:
        if len(argv) != 7:
            raise ValueError
        project_root = Path(argv[0])
        relative = PurePosixPath(argv[1])
        snapshot_id, fold = argv[2], argv[3]
        horizon, attempt = int(argv[4]), int(argv[5])
        attempt_root = Path(argv[6])
        _execute_worker(
            project_root=project_root,
            config_relative=relative,
            snapshot_id=snapshot_id,
            fold=fold,
            horizon=horizon,
            attempt=attempt,
            attempt_root=attempt_root,
        )
    except Exception:
        return 1
    sys.stdout.write("G8E_WORKER_OK\n")
    return 0


def _execute_worker(
    *,
    project_root: Path,
    config_relative: PurePosixPath,
    snapshot_id: str,
    fold: str,
    horizon: int,
    attempt: int,
    attempt_root: Path,
) -> None:
    if attempt not in {1, 2} or attempt_root.exists():
        raise ValueError
    project = _real_directory(project_root)
    config_path = _real_file(project.joinpath(*config_relative.parts))
    opened: set[str] = set()

    def audit(event: str, args: tuple[object, ...]) -> None:
        if event != "open" or not args or not isinstance(args[0], (str, bytes)):
            return
        mode = args[1] if len(args) > 1 else None
        if isinstance(mode, str) and "r" not in mode and "+" not in mode:
            return
        if isinstance(mode, int) and mode & (os.O_WRONLY | os.O_RDWR):
            return
        try:
            path = Path(os.fsdecode(args[0])).absolute()
            relative_path = path.relative_to(project)
        except (OSError, ValueError):
            return
        opened.add(relative_path.as_posix())

    sys.addaudithook(audit)
    config = load_m3_config(config_path)
    resolution = resolve_formal_reproducibility_cli_inputs(
        project_root=project,
        config=config,
        config_relative=config_relative,
        snapshot_id=snapshot_id,
        fold=fold,
        horizon=horizon,
    )
    forbidden = (
        resolution.stage_root / "work" / resolution.work_key / "train",
        resolution.stage_root / "work" / resolution.work_key / "predictions",
        resolution.stage_root / "work" / resolution.work_key / "evaluation",
        resolution.stage_root / "repro",
    )
    for relative_path in opened:
        absolute = project / Path(relative_path)
        if any(_is_within(absolute, prefix) for prefix in forbidden):
            raise ValueError

    with tempfile.TemporaryDirectory(prefix=f"m3-repro-worker-{attempt}-") as raw:
        scratch = Path(raw)
        _build_attempt(
            resolution=resolution,
            scratch=scratch,
            attempt_root=attempt_root,
            attempt=attempt,
            opened=opened,
            forbidden=forbidden,
            project_root=project,
        )


def _build_attempt(
    *,
    resolution: FormalReproducibilityCliResolution,
    scratch: Path,
    attempt_root: Path,
    attempt: int,
    opened: set[str],
    forbidden: tuple[Path, ...],
    project_root: Path,
) -> None:
    scratch.mkdir(exist_ok=True)
    model_root = scratch / "train"
    prediction_root = scratch / "predictions"
    evaluation_root = scratch / "evaluation"
    receipt_root = scratch / "receipts"
    receipt_root.mkdir()
    roots = MappingProxyType({**dict(resolution.artifact_roots), "ATTEMPT": scratch})
    model_spec = build_lightgbm_training_spec(resolution.config)
    model_upstream = ModelUpstreamPaths(
        alignment_receipt_path=resolution.alignment_receipt_path,
        alignment_upstream_paths=resolution.alignment_upstream_paths,
    )
    build_model_artifact(
        release=resolution.release,
        snapshot=resolution.snapshot,
        snapshot_spec=resolution.snapshot_spec,
        provider=resolution.provider,
        provider_spec=resolution.provider_spec,
        experiment=resolution.experiment,
        experiment_spec=resolution.experiment_spec,
        folds=resolution.folds,
        fold_spec=resolution.fold_spec,
        feature=resolution.feature,
        feature_spec=resolution.feature_spec,
        label=resolution.label,
        label_spec=resolution.label_spec,
        alignment=resolution.alignment,
        alignment_spec=resolution.alignment_spec,
        config=resolution.config,
        spec=model_spec,
        upstream_paths=model_upstream,
        artifact_roots=roots,
        output_root=model_root,
    )
    model_receipt = receipt_root / "model.json"
    publish_stage_receipt(
        receipt_path=model_receipt,
        stage="model",
        scope="WORK",
        scope_key=resolution.work_key,
        artifact_roots=roots,
        inputs=(
            ("G8", resolution.alignment.root / "alignment_manifest.json"),
            ("G8", resolution.alignment_receipt_path),
            ("G8", resolution.feature.root / "feature_manifest.json"),
            ("G8", resolution.feature_receipt_path),
            ("G8", resolution.label.root / "label_manifest.json"),
            ("G8", resolution.label_receipt_path),
            ("G8", resolution.experiment.root / "experiment_manifest.json"),
        ),
        outputs=tuple(
            ("ATTEMPT", model_root / name)
            for name in ("model.metadata.json", "model.txt", "validation_curve.parquet")
        ),
    )
    model = verify_model_artifact(
        root=model_root,
        receipt_path=model_receipt,
        release=resolution.release,
        snapshot=resolution.snapshot,
        snapshot_spec=resolution.snapshot_spec,
        provider=resolution.provider,
        provider_spec=resolution.provider_spec,
        experiment=resolution.experiment,
        experiment_spec=resolution.experiment_spec,
        folds=resolution.folds,
        fold_spec=resolution.fold_spec,
        feature=resolution.feature,
        feature_spec=resolution.feature_spec,
        label=resolution.label,
        label_spec=resolution.label_spec,
        alignment=resolution.alignment,
        alignment_spec=resolution.alignment_spec,
        config=resolution.config,
        spec=model_spec,
        upstream_paths=model_upstream,
        artifact_roots=roots,
    )
    prediction_spec = PredictionBuildSpec(
        experiment_key=resolution.experiment.manifest.experiment_key,
        work_key=resolution.work_key,
        fold=resolution.alignment.manifest.fold,
        horizon_sessions=cast(Any, resolution.alignment.manifest.horizon_sessions),
        model="lightgbm",
        model_version=model.manifest.model_version,
    )
    prediction_upstream = PredictionUpstreamPaths(
        model_receipt_path=model_receipt,
        model_upstream_paths=model_upstream,
        feature_receipt_path=resolution.feature_receipt_path,
        feature_upstream_paths=resolution.feature_upstream_paths,
        fold_receipt_path=resolution.fold_receipt_path,
    )
    build_prediction_artifact(
        release=resolution.release,
        snapshot=resolution.snapshot,
        snapshot_spec=resolution.snapshot_spec,
        provider=resolution.provider,
        provider_spec=resolution.provider_spec,
        experiment=resolution.experiment,
        experiment_spec=resolution.experiment_spec,
        folds=resolution.folds,
        fold_spec=resolution.fold_spec,
        feature=resolution.feature,
        feature_spec=resolution.feature_spec,
        label=resolution.label,
        label_spec=resolution.label_spec,
        alignment=resolution.alignment,
        alignment_spec=resolution.alignment_spec,
        model=model,
        model_spec=model_spec,
        config=resolution.config,
        spec=prediction_spec,
        upstream_paths=prediction_upstream,
        artifact_roots=roots,
        output_root=prediction_root,
    )
    prediction_receipt = receipt_root / "predictions.json"
    publish_stage_receipt(
        receipt_path=prediction_receipt,
        stage="predictions",
        scope="WORK",
        scope_key=resolution.work_key,
        artifact_roots=roots,
        inputs=(
            ("ATTEMPT", model.root / "model.metadata.json"),
            ("ATTEMPT", model_receipt),
            ("G8", resolution.feature.root / "feature_manifest.json"),
            ("G8", resolution.feature_receipt_path),
            ("G8", resolution.folds.root / "folds.json"),
            ("G8", resolution.fold_receipt_path),
            ("G8", resolution.experiment.root / "experiment_manifest.json"),
            ("G8", resolution.alignment_receipt_path),
        ),
        outputs=tuple(
            ("ATTEMPT", prediction_root / name)
            for name in ("prediction_manifest.json", "predictions.parquet")
        ),
    )
    prediction = verify_prediction_artifact(
        root=prediction_root,
        receipt_path=prediction_receipt,
        release=resolution.release,
        snapshot=resolution.snapshot,
        snapshot_spec=resolution.snapshot_spec,
        provider=resolution.provider,
        provider_spec=resolution.provider_spec,
        experiment=resolution.experiment,
        experiment_spec=resolution.experiment_spec,
        folds=resolution.folds,
        fold_spec=resolution.fold_spec,
        feature=resolution.feature,
        feature_spec=resolution.feature_spec,
        label=resolution.label,
        label_spec=resolution.label_spec,
        alignment=resolution.alignment,
        alignment_spec=resolution.alignment_spec,
        model=model,
        model_spec=model_spec,
        config=resolution.config,
        spec=prediction_spec,
        upstream_paths=prediction_upstream,
        artifact_roots=roots,
    )
    minimum = resolution.config.section("evaluation")["minimum_ic_symbols"]
    if type(minimum) is not int:
        raise ValueError
    evaluation_spec = EvaluationSpec(
        experiment_key=resolution.experiment.manifest.experiment_key,
        work_key=resolution.work_key,
        fold=resolution.alignment.manifest.fold,
        horizon_sessions=cast(Any, resolution.alignment.manifest.horizon_sessions),
        minimum_ic_symbols=minimum,
    )
    evaluation_upstream = EvaluationUpstreamPaths(
        prediction_receipt_path=prediction_receipt,
        prediction_upstream_paths=prediction_upstream,
        label_receipt_path=resolution.label_receipt_path,
        feature_receipt_path=resolution.feature_receipt_path,
        fold_receipt_path=resolution.fold_receipt_path,
    )
    build_evaluation_artifact(
        release=resolution.release,
        snapshot=resolution.snapshot,
        snapshot_spec=resolution.snapshot_spec,
        provider=resolution.provider,
        provider_spec=resolution.provider_spec,
        experiment=resolution.experiment,
        experiment_spec=resolution.experiment_spec,
        folds=resolution.folds,
        fold_spec=resolution.fold_spec,
        feature=resolution.feature,
        feature_spec=resolution.feature_spec,
        label=resolution.label,
        label_spec=resolution.label_spec,
        alignment=resolution.alignment,
        alignment_spec=resolution.alignment_spec,
        model=model,
        model_spec=model_spec,
        prediction=prediction,
        prediction_spec=prediction_spec,
        config=resolution.config,
        spec=evaluation_spec,
        upstream_paths=evaluation_upstream,
        artifact_roots=roots,
        output_root=evaluation_root,
    )
    evaluation_receipt = receipt_root / "evaluation.json"
    evaluation_inputs = _evaluation_inputs(
        resolution=resolution,
        prediction=prediction,
        prediction_receipt=prediction_receipt,
    )
    publish_stage_receipt(
        receipt_path=evaluation_receipt,
        stage="evaluation",
        scope="WORK",
        scope_key=resolution.work_key,
        artifact_roots=roots,
        inputs=tuple((_alias_for(path, roots), path) for path in evaluation_inputs),
        outputs=tuple(
            ("ATTEMPT", evaluation_root / name)
            for name in ("daily_ic.parquet", "evaluation_manifest.json", "metrics.json")
        ),
    )
    verify_evaluation_artifact(
        root=evaluation_root,
        receipt_path=evaluation_receipt,
        release=resolution.release,
        snapshot=resolution.snapshot,
        snapshot_spec=resolution.snapshot_spec,
        provider=resolution.provider,
        provider_spec=resolution.provider_spec,
        experiment=resolution.experiment,
        experiment_spec=resolution.experiment_spec,
        folds=resolution.folds,
        fold_spec=resolution.fold_spec,
        feature=resolution.feature,
        feature_spec=resolution.feature_spec,
        label=resolution.label,
        label_spec=resolution.label_spec,
        alignment=resolution.alignment,
        alignment_spec=resolution.alignment_spec,
        model=model,
        model_spec=model_spec,
        prediction=prediction,
        prediction_spec=prediction_spec,
        config=resolution.config,
        spec=evaluation_spec,
        upstream_paths=evaluation_upstream,
        artifact_roots=roots,
    )
    for relative_path in opened:
        absolute = project_root / Path(relative_path)
        if any(_is_within(absolute, prefix) for prefix in forbidden):
            raise ValueError
    attempt_root.mkdir()
    selected = {
        model_root / "model.txt": "model.txt",
        model_root / "model.metadata.json": "model.metadata.json",
        prediction_root / "predictions.parquet": "predictions.parquet",
        prediction_root / "prediction_manifest.json": "prediction_manifest.json",
        evaluation_root / "daily_ic.parquet": "daily_ic.parquet",
        evaluation_root / "metrics.json": "metrics.json",
    }
    for source, name in selected.items():
        _write_exclusive(attempt_root / name, source.read_bytes())
    audit = {
        "schema_version": _AUDIT_SCHEMA,
        "worker_protocol_version": _WORKER_PROTOCOL,
        "attempt": attempt,
        "fresh_process": True,
        "work_key": resolution.work_key,
        "code_version": resolution.runtime.code_version,
        "dependency_fingerprint_sha256": (resolution.runtime.dependency_fingerprint_sha256),
        "python_implementation": resolution.runtime.python_implementation,
        "python_version": resolution.runtime.python_version,
        "python_executable_sha256": _file_sha256(Path(sys.executable)),
        "read_paths_sha256": hashlib.sha256(_canonical_bytes(sorted(opened))).hexdigest(),
        "normal_work_outputs_read": False,
        "other_attempt_read": False,
    }
    _write_exclusive(attempt_root / "read_audit.json", _canonical_bytes(audit))


def _evaluation_inputs(
    *,
    resolution: FormalReproducibilityCliResolution,
    prediction: Any,
    prediction_receipt: Path,
) -> tuple[Path, ...]:
    experiment_receipt = (
        resolution.feature_upstream_paths.fold_upstream_paths.experiment_receipt_path
    )
    return (
        resolution.release.release.manifest_path,
        dict(resolution.release.artifact_paths)["eligible_keys.parquet"],
        resolution.feature.root / "feature_manifest.json",
        resolution.feature_receipt_path,
        resolution.feature.root / "coverage.parquet",
        resolution.feature.root / "test.parquet",
        prediction.root / "prediction_manifest.json",
        prediction_receipt,
        prediction.root / "predictions.parquet",
        resolution.label.root / "label_manifest.json",
        resolution.label_receipt_path,
        resolution.label.root / "labels.parquet",
        resolution.label.root / "diagnostics.parquet",
        resolution.folds.root / "folds.json",
        resolution.fold_receipt_path,
        resolution.experiment.root / "experiment_manifest.json",
        experiment_receipt,
    )


def _write_comparison(
    *,
    root: Path,
    comparison_key: str,
    score_atol: float,
    metric_atol: float,
    code_version: str,
    dependency_fingerprint_sha256: str,
    python_executable_sha256: str,
) -> None:
    payload = _comparison_payload(
        root=root,
        comparison_key=comparison_key,
        score_atol=score_atol,
        metric_atol=metric_atol,
        code_version=code_version,
        dependency_fingerprint_sha256=dependency_fingerprint_sha256,
        python_executable_sha256=python_executable_sha256,
    )
    _write_exclusive(root / "reproducibility.json", _canonical_bytes(payload))


def _verify_comparison_tree(
    *,
    root: Path,
    comparison_key: str,
    score_atol: float,
    metric_atol: float,
    code_version: str,
    dependency_fingerprint_sha256: str,
    python_executable_sha256: str,
) -> None:
    if not _is_hex64(comparison_key) or not root.is_dir() or root.is_symlink():
        raise ValueError
    if {item.name for item in os.scandir(root)} != {
        "attempt=1",
        "attempt=2",
        "reproducibility.json",
    }:
        raise ValueError
    for attempt in (1, 2):
        directory = root / f"attempt={attempt}"
        if (
            not directory.is_dir()
            or directory.is_symlink()
            or {item.name for item in os.scandir(directory)} != _ATTEMPT_FILES
        ):
            raise ValueError
        _validate_audit(
            directory / "read_audit.json",
            attempt=attempt,
            code_version=code_version,
            dependency_fingerprint_sha256=dependency_fingerprint_sha256,
            python_executable_sha256=python_executable_sha256,
        )
    expected = _comparison_payload(
        root=root,
        comparison_key=comparison_key,
        score_atol=score_atol,
        metric_atol=metric_atol,
        code_version=code_version,
        dependency_fingerprint_sha256=dependency_fingerprint_sha256,
        python_executable_sha256=python_executable_sha256,
    )
    actual = _strict_json(root / "reproducibility.json")
    if actual != expected or (root / "reproducibility.json").read_bytes() != _canonical_bytes(
        expected
    ):
        raise ValueError


def _comparison_payload(
    *,
    root: Path,
    comparison_key: str,
    score_atol: float,
    metric_atol: float,
    code_version: str,
    dependency_fingerprint_sha256: str,
    python_executable_sha256: str,
) -> dict[str, object]:
    first = pl.read_parquet(root / "attempt=1" / "predictions.parquet")
    second = pl.read_parquet(root / "attempt=2" / "predictions.parquet")
    expected_columns = ("as_of", "symbol", "score", "rank")
    if tuple(first.columns) != expected_columns or tuple(second.columns) != expected_columns:
        raise ValueError
    first_keys = first.select("as_of", "symbol", "rank")
    second_keys = second.select("as_of", "symbol", "rank")
    if not first_keys.equals(second_keys) or first.height <= 0:
        raise ValueError
    scores_one = first.get_column("score").to_list()
    scores_two = second.get_column("score").to_list()
    if any(
        not isinstance(value, float) or not math.isfinite(value)
        for value in (*scores_one, *scores_two)
    ):
        raise ValueError
    score_diff = max(abs(left - right) for left, right in zip(scores_one, scores_two, strict=True))
    if score_diff > score_atol:
        raise ValueError
    metrics_one = _strict_json(root / "attempt=1" / "metrics.json")
    metrics_two = _strict_json(root / "attempt=2" / "metrics.json")
    if set(metrics_one) != set(metrics_two):
        raise ValueError
    metric_diff = 0.0
    for key in sorted(metrics_one):
        left, right = metrics_one[key], metrics_two[key]
        if left is None or right is None:
            if left is not None or right is not None:
                raise ValueError
        elif type(left) in {int, float} and type(right) in {int, float}:
            left_float = float(cast(int | float, left))
            right_float = float(cast(int | float, right))
            if not math.isfinite(left_float) or not math.isfinite(right_float):
                raise ValueError
            metric_diff = max(metric_diff, abs(left_float - right_float))
        elif left != right:
            raise ValueError
    if metric_diff > metric_atol:
        raise ValueError
    return {
        "schema_version": _REPORT_SCHEMA,
        "comparison_key": comparison_key,
        "worker_protocol_version": _WORKER_PROTOCOL,
        "code_version": code_version,
        "dependency_fingerprint_sha256": dependency_fingerprint_sha256,
        "python_executable_sha256": python_executable_sha256,
        "attempts": 2,
        "prediction_row_count": first.height,
        "prediction_keys_sha256": hashlib.sha256(
            first_keys.write_json().encode("utf-8")
        ).hexdigest(),
        "score_atol": _canonical_float(score_atol),
        "score_max_abs_diff": _canonical_float(score_diff),
        "metric_atol": _canonical_float(metric_atol),
        "metric_max_abs_diff": _canonical_float(metric_diff),
        "metric_keys": sorted(metrics_one),
        "passed": True,
        "attempt_output_sha256": [
            {
                name: hashlib.sha256((root / f"attempt={attempt}" / name).read_bytes()).hexdigest()
                for name in sorted(_ATTEMPT_FILES)
            }
            for attempt in (1, 2)
        ],
    }


def _validate_audit(
    path: Path,
    *,
    attempt: int,
    code_version: str,
    dependency_fingerprint_sha256: str,
    python_executable_sha256: str,
) -> None:
    value = _strict_json(path)
    if value != {
        "schema_version": _AUDIT_SCHEMA,
        "worker_protocol_version": _WORKER_PROTOCOL,
        "attempt": attempt,
        "fresh_process": True,
        "work_key": value.get("work_key"),
        "code_version": code_version,
        "dependency_fingerprint_sha256": dependency_fingerprint_sha256,
        "python_implementation": value.get("python_implementation"),
        "python_version": value.get("python_version"),
        "python_executable_sha256": python_executable_sha256,
        "read_paths_sha256": value.get("read_paths_sha256"),
        "normal_work_outputs_read": False,
        "other_attempt_read": False,
    } or (
        not _is_hex64(value.get("work_key"))
        or not _is_hex64(value.get("read_paths_sha256"))
        or not _is_hex64(dependency_fingerprint_sha256)
        or not _is_hex64(python_executable_sha256)
        or type(code_version) is not str
        or not code_version
        or type(value.get("python_implementation")) is not str
        or not value.get("python_implementation")
        or type(value.get("python_version")) is not str
        or not value.get("python_version")
    ):
        raise ValueError


def _strict_json(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
    )
    if type(value) is not dict or raw != _canonical_bytes(value):
        raise ValueError
    return cast(dict[str, object], value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _canonical_float(value: float) -> str:
    if not math.isfinite(value) or value < 0:
        raise ValueError
    return format(value, ".17g")


def _finite_nonnegative_float(value: object) -> float:
    if type(value) is not float or not math.isfinite(value) or value < 0:
        raise ValueError
    return value


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(_real_file(path).read_bytes()).hexdigest()


def _digest_for_path(path: Path, *, artifact_roots: Mapping[str, Path]) -> ArtifactDigest:
    leaf = _real_file(path)
    alias = _alias_for(leaf, artifact_roots)
    root = artifact_roots[alias].resolve(strict=True)
    raw = leaf.read_bytes()
    return ArtifactDigest(
        root_alias=alias,
        relative_path=leaf.relative_to(root).as_posix(),
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _alias_for(path: Path, roots: Mapping[str, Path]) -> str:
    leaf = path.resolve(strict=True)
    matches = [
        (alias, root.resolve(strict=True))
        for alias, root in roots.items()
        if leaf.is_relative_to(root.resolve(strict=True))
    ]
    if not matches:
        raise ValueError
    return max(matches, key=lambda item: len(item[1].parts))[0]


def _real_directory(path: Path) -> Path:
    if not isinstance(path, Path):
        raise ValueError
    resolved = path.resolve(strict=True)
    st = os.lstat(resolved)
    if (
        not stat.S_ISDIR(st.st_mode)
        or stat.S_ISLNK(st.st_mode)
        or bool(getattr(st, "st_file_attributes", 0) & _REPARSE)
    ):
        raise ValueError
    return resolved


def _real_file(path: Path) -> Path:
    if not isinstance(path, Path):
        raise ValueError
    resolved = path.resolve(strict=True)
    st = os.lstat(resolved)
    if (
        not stat.S_ISREG(st.st_mode)
        or stat.S_ISLNK(st.st_mode)
        or bool(getattr(st, "st_file_attributes", 0) & _REPARSE)
        or st.st_nlink != 1
    ):
        raise ValueError
    return resolved


def _regular_files(root: Path) -> tuple[Path, ...]:
    result: list[Path] = []
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for directory in directories:
            if (current_path / directory).is_symlink():
                raise ValueError
        result.extend(_real_file(current_path / name) for name in files)
    return tuple(sorted(result, key=lambda item: item.relative_to(root).as_posix()))


def _write_exclusive(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.absolute().relative_to(root.absolute())
    except ValueError:
        return False
    return True


def _is_hex64(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _HEX64


def _fail(code: str) -> NoReturn:
    error = M3ReproducibilityError(code)
    error.__cause__ = None
    error.__context__ = None
    raise error


__all__ = [
    "FormalReproducibilityResult",
    "M3ReproducibilityError",
    "run_formal_reproducibility_stage",
    "verify_formal_reproducibility_artifact",
]
