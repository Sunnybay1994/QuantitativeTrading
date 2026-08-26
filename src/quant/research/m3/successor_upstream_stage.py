"""M3-G8F-R2A: unique successor upstream-wave and formal-summary-gate wiring.

This module owns the only production bridge between the narrow
``successor_runtime`` contracts and the existing formal M3 ``StageRunner`` /
``make_*_run_plan`` / ``verify_*_artifact`` public APIs.  It never scans
directories, never guesses filenames, and never publishes a node outside a
complete, canonically-built :class:`~quant.research.m3.orchestration.RunPlan`.

Every prior input is re-verified from its exact ``StageReceiptRef`` before use
(fresh bytes, fresh receipt, fresh typed artifact).  Every produced receipt is
returned as a fresh :class:`StageReceiptRef` built from the real
:class:`~quant.research.m3.run_state.StageReceipt` that
:class:`~quant.research.m3.orchestration.StageRunner` actually published.

Error codes are the only externally visible failure signal
(:class:`quant.research.m3.successor_runtime.SuccessorRuntimeError`); no
absolute path, credential or underlying exception text ever crosses this
boundary.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
import os
import stat
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal, NoReturn, Protocol

if TYPE_CHECKING:
    from quant.backtest.a_share_reporting import BacktestArtifactFreshVerificationContext
    from quant.data.m3_release import VerifiedG1Release
    from quant.research.m3.config import LoadedM3Config
    from quant.research.m3.contracts import (
        AlignmentBuildSpec,
        ExperimentIdentitySpec,
        FeatureBuildSpec,
        FoldPlanBuildSpec,
        LabelBuildSpec,
        LabelReconciliationSpec,
        LightgbmTrainingSpec,
        PredictionBuildSpec,
        ProviderBuildSpec,
        ResearchSummaryUpstreamPaths,
        SnapshotBuildResult,
        SnapshotBuildSpec,
        SnapshotRequestRecordV1,
        TargetBuildSpec,
        VerifiedAlignmentArtifact,
        VerifiedBacktestArtifact,
        VerifiedBacktestPlanArtifact,
        VerifiedEvaluationArtifact,
        VerifiedExperimentIdentity,
        VerifiedFeatureArtifact,
        VerifiedFoldPlanArtifact,
        VerifiedLabelArtifact,
        VerifiedLabelReconciliationArtifact,
        VerifiedModelArtifact,
        VerifiedPredictionArtifact,
        VerifiedProviderArtifact,
        VerifiedProviderValidationArtifact,
        VerifiedSnapshotArtifact,
        VerifiedTargetArtifact,
    )
    from quant.research.m3.evaluate import (
        EvaluationFreshVerificationContext,
        FormalSummaryStagePublicationIdentity,
    )
    from quant.research.m3.orchestration import (
        ArtifactDigest,
        RunPlan,
        StageContext,
        StageNode,
        StageRunner,
        StaticStageResult,
    )
    from quant.research.m3.run_state import StageReceipt
    from quant.research.m3.successor_runtime import (
        FoldExecution,
        GateExecution,
        StageReceiptRef,
        SuccessorFoldRequest,
        SuccessorPublicApiBundle,
        SuccessorRuntimeRequest,
        SuccessorStageContext,
        SuccessorToolchainBinding,
    )
    from quant.research.m3.tracking import FormalTrackingFreshVerificationContext


class _ReceiptNodeView(Protocol):
    """Minimal node identity consumed by ``_new_receipt_ref``."""

    @property
    def node_id(self) -> str: ...

    @property
    def fold(self) -> str | None: ...

    @property
    def horizon(self) -> int | None: ...


_PATH_TYPE = type(Path())
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

_UPSTREAM_WAVES = (
    "snapshot",
    "provider",
    "provider-validation",
    "experiment-identity",
    "experiment-artifacts",
    "label-reconciliation",
    "work",
)

# stage -> exact expected count of prior receipts of that stage, for one wave.
_REQUIRED_PRIOR_STAGES: dict[str, dict[str, int]] = {
    "snapshot": {},
    "provider": {"snapshot": 1},
    "provider-validation": {"snapshot": 1, "provider": 1},
    "experiment-identity": {"snapshot": 1, "provider": 1, "provider-validation": 1},
    "experiment-artifacts": {
        "snapshot": 1, "provider": 1, "provider-validation": 1,
        "experiment-identity": 1,
    },
    "label-reconciliation": {
        "snapshot": 1, "provider": 1, "provider-validation": 1,
        "experiment-identity": 1, "folds": 1, "labels": 2,
    },
    "work": {
        "snapshot": 1, "provider": 1, "provider-validation": 1,
        "experiment-identity": 1, "folds": 1, "labels": 2,
        "label-reconciliation": 2,
    },
}


def _fail(code: str) -> NoReturn:
    from quant.research.m3.successor_runtime import SuccessorRuntimeError

    raise SuccessorRuntimeError(code)


def _require_run_plan(value: object) -> "RunPlan":
    from quant.research.m3.orchestration import RunPlan

    if type(value) is not RunPlan:
        _fail("SUCCESSOR_STAGE_INVALID")
    return value


def _require_horizon(value: object) -> Literal[5, 10]:
    if type(value) is int:
        if value == 5:
            return 5
        if value == 10:
            return 10
    _fail("SUCCESSOR_STAGE_INVALID")


def _require_benchmark(value: object) -> Literal["510300.SH"]:
    if value == "510300.SH":
        return "510300.SH"
    _fail("SUCCESSOR_CONFIG_INVALID")


def _require_dump_contract(value: object) -> Literal["m3-qlib-dump-all-v1"]:
    if value == "m3-qlib-dump-all-v1":
        return "m3-qlib-dump-all-v1"
    _fail("SUCCESSOR_STAGE_INVALID")


def _require_frequency(value: object) -> Literal["day"]:
    if value == "day":
        return "day"
    _fail("SUCCESSOR_STAGE_INVALID")


def _require_strategy(value: object) -> Literal["topk"]:
    if value == "topk":
        return "topk"
    _fail("SUCCESSOR_CONFIG_INVALID")


def _require_toolchain(value: object) -> "SuccessorToolchainBinding":
    from quant.research.m3.successor_runtime import SuccessorToolchainBinding

    if type(value) is not SuccessorToolchainBinding:
        _fail("SUCCESSOR_INPUT_INVALID")
    return value


def _require_str(value: object, *, code: str = "SUCCESSOR_CONFIG_INVALID") -> str:
    if type(value) is not str:
        _fail(code)
    return value


def _require_int(value: object, *, code: str = "SUCCESSOR_CONFIG_INVALID") -> int:
    if type(value) is not int:
        _fail(code)
    return value


def _require_float(value: object, *, code: str = "SUCCESSOR_CONFIG_INVALID") -> float:
    if type(value) is not float:
        _fail(code)
    return value


def _require_str_tuple(
    value: object, *, code: str = "SUCCESSOR_CONFIG_INVALID",
) -> tuple[str, ...]:
    if type(value) is not tuple:
        _fail(code)
    items: list[str] = []
    for item in value:
        if type(item) is not str:
            _fail(code)
        items.append(item)
    return tuple(items)


def _require_positive_int(
    value: object, *, code: str = "SUCCESSOR_CONFIG_INVALID",
) -> int:
    result = _require_int(value, code=code)
    if result <= 0:
        _fail(code)
    return result


def _require_finite_float(
    value: object, *, code: str = "SUCCESSOR_CONFIG_INVALID",
) -> float:
    result = _require_float(value, code=code)
    if not math.isfinite(result):
        _fail(code)
    return result


def _require_path(value: object, *, code: str = "SUCCESSOR_STAGE_INVALID") -> Path:
    if type(value) is not _PATH_TYPE:
        _fail(code)
    return value


def _is_hex64(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _sha256_json(value: object) -> str:
    import json

    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# --------------------------------------------------------------------------
# Toolchain binding (SSOT type lives on successor_runtime)
# --------------------------------------------------------------------------


def _require_concrete_absolute_regular_file(path: Path) -> Path:
    if type(path) is not _PATH_TYPE or not path.is_absolute():
        _fail("SUCCESSOR_INPUT_INVALID")
    try:
        info = os.lstat(path)
    except OSError:
        _fail("SUCCESSOR_INPUT_INVALID")
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or bool(getattr(info, "st_file_attributes", 0) & _REPARSE)
    ):
        _fail("SUCCESSOR_INPUT_INVALID")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        _fail("SUCCESSOR_INPUT_INVALID")
    if os.path.normcase(str(path)) != os.path.normcase(str(resolved)):
        _fail("SUCCESSOR_INPUT_INVALID")
    return resolved


def _require_real_project_root(project_root: Path) -> Path:
    if type(project_root) is not _PATH_TYPE or not project_root.is_absolute():
        _fail("SUCCESSOR_INPUT_INVALID")
    try:
        info = os.lstat(project_root)
        resolved = project_root.resolve(strict=True)
    except OSError:
        _fail("SUCCESSOR_INPUT_INVALID")
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or bool(getattr(info, "st_file_attributes", 0) & _REPARSE)
        or os.path.normcase(str(project_root)) != os.path.normcase(str(resolved))
    ):
        _fail("SUCCESSOR_INPUT_INVALID")
    return resolved


def validate_successor_toolchain_binding(
    *,
    project_root: Path,
    toolchain: object,
    fold_configs: tuple["LoadedM3Config", ...],
) -> tuple[str, str, int, str]:
    """Validate one toolchain binding and return its identity tuple.

    Returns ``(resolved_python_posix, project_relative_dump_posix,
    dump_size_bytes, dump_sha256)``.  Never launches a process, never touches
    the network, never falls back to ``sys.executable`` or a PATH lookup.
    """

    from quant.research.m3.config import LoadedM3Config
    from quant.research.m3.fetch_qlib_tool import DEFAULT_TARGET_PATH, build_qlib_dump_tool_spec
    from quant.research.m3.successor_runtime import SuccessorToolchainBinding

    resolved_root = _require_real_project_root(project_root)
    if type(toolchain) is not SuccessorToolchainBinding:
        _fail("SUCCESSOR_INPUT_INVALID")
    if (
        type(fold_configs) is not tuple
        or len(fold_configs) != 2
        or any(type(item) is not LoadedM3Config for item in fold_configs)
    ):
        _fail("SUCCESSOR_INPUT_INVALID")

    resolved_python = _require_concrete_absolute_regular_file(toolchain.python_executable)
    resolved_dump = _require_concrete_absolute_regular_file(toolchain.qlib_dump_tool_path)

    try:
        expected_dump = (resolved_root / DEFAULT_TARGET_PATH).resolve(strict=True)
    except OSError:
        _fail("SUCCESSOR_INPUT_INVALID")
    # Character-equal resolved path vs project_root / DEFAULT_TARGET_PATH.
    if os.path.normcase(str(resolved_dump)) != os.path.normcase(str(expected_dump)):
        _fail("SUCCESSOR_INPUT_INVALID")

    try:
        relative = resolved_dump.relative_to(resolved_root)
    except ValueError:
        _fail("SUCCESSOR_INPUT_INVALID")

    try:
        specs = tuple(build_qlib_dump_tool_spec(config) for config in fold_configs)
    except Exception:
        _fail("SUCCESSOR_CONFIG_INVALID")
    if specs[0] != specs[1]:
        _fail("SUCCESSOR_INPUT_INVALID")
    spec = specs[0]

    try:
        raw = resolved_dump.read_bytes()
    except OSError:
        _fail("SUCCESSOR_INPUT_INVALID")
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != spec.size_bytes or digest != spec.sha256:
        _fail("SUCCESSOR_INPUT_INVALID")
    if (
        type(toolchain.timeout_seconds) is not float
        or isinstance(toolchain.timeout_seconds, bool)
        or not math.isfinite(toolchain.timeout_seconds)
        or toolchain.timeout_seconds <= 0.0
    ):
        _fail("SUCCESSOR_INPUT_INVALID")

    return (resolved_python.as_posix(), relative.as_posix(), len(raw), digest)


def _toolchain_identity(
    *, project_root: Path, toolchain: object, fold_configs: tuple["LoadedM3Config", ...],
) -> str:
    python_posix, dump_relative, dump_size, dump_sha256 = validate_successor_toolchain_binding(
        project_root=project_root, toolchain=toolchain, fold_configs=fold_configs,
    )
    return _sha256_json(
        ["m3-successor-toolchain-identity-v1", python_posix, dump_relative, dump_size, dump_sha256]
    )


# --------------------------------------------------------------------------
# UpstreamWaveContext
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class UpstreamWaveContext:
    """Immutable binding for exactly one upstream-wave call.

    Carries no runner, no mutable cache, no directory-discovery result and no
    unverified artifact.  ``prior_refs`` must already be the stable-sorted,
    freshly-verified closure this wave depends on.
    """

    request: "SuccessorRuntimeRequest"
    stage_context: "SuccessorStageContext"
    prior_refs: tuple["StageReceiptRef", ...]
    transition_identity: str

    def __post_init__(self) -> None:
        from quant.research.m3.successor_runtime import (
            StageReceiptRef,
            SuccessorRuntimeRequest,
            SuccessorStageContext,
        )

        if type(self.request) is not SuccessorRuntimeRequest:
            raise ValueError("invalid upstream wave request")
        if type(self.stage_context) is not SuccessorStageContext:
            raise ValueError("invalid upstream wave stage context")
        if self.stage_context.request is not self.request:
            raise ValueError("upstream wave context/request identity drift")
        if type(self.prior_refs) is not tuple or any(
            type(item) is not StageReceiptRef for item in self.prior_refs
        ):
            raise ValueError("invalid upstream wave prior refs")
        node_ids = tuple(item.node_id for item in self.prior_refs)
        if node_ids != tuple(sorted(node_ids)) or len(set(node_ids)) != len(node_ids):
            raise ValueError("upstream wave prior refs must be uniquely sorted")
        if not _is_hex64(self.transition_identity):
            raise ValueError("invalid upstream wave transition identity")


def compute_upstream_wave_transition_identity(
    *, request: "SuccessorRuntimeRequest", wave: str, prior_refs: tuple["StageReceiptRef", ...],
) -> str:
    """Deterministic identity binding one wave call to its exact prior closure."""

    from quant.research.m3.successor_runtime import two_fold_identity

    return _sha256_json(
        [
            "m3-successor-upstream-wave-transition-v1",
            two_fold_identity(request),
            wave,
            [
                [
                    item.node_id, item.stage, item.scope, item.scope_key,
                    item.relative_path, item.sha256, item.fold, item.horizon,
                ]
                for item in prior_refs
            ],
        ]
    )


# --------------------------------------------------------------------------
# Process-local physical wave registry (sealed canonical success only)
# --------------------------------------------------------------------------

_REGISTRY_LOCK = threading.Lock()
_WAVE_SUCCESS_SEAL = object()


class _CanonicalWaveSuccess:
    """Unforgeable success state produced only after full canonical closure.

    Plain ``tuple[StageReceiptRef, ...]`` pre-seeds (or any other object) are
    rejected: they must not elevate caller ``resume=False`` to StageRunner resume.
    """

    __slots__ = ("refs", "_seal")

    def __init__(
        self,
        refs: tuple["StageReceiptRef", ...],
        *,
        seal: object,
    ) -> None:
        if seal is not _WAVE_SUCCESS_SEAL:
            raise TypeError("canonical wave success requires module seal")
        self.refs = refs
        self._seal = seal

    def authorized(self) -> bool:
        return self._seal is _WAVE_SUCCESS_SEAL


_WAVE_REGISTRY: dict[tuple[str, str, str, str], _CanonicalWaveSuccess] = {}


def _reset_wave_registry_for_tests() -> None:
    """Test-only: clear the process-local physical-wave registry."""

    with _REGISTRY_LOCK:
        _WAVE_REGISTRY.clear()


def _registry_key(
    *, request: "SuccessorRuntimeRequest", project_root: Path, wave: str, toolchain_identity: str,
) -> tuple[str, str, str, str]:
    from quant.research.m3.successor_runtime import two_fold_identity

    return (
        two_fold_identity(request),
        os.path.normcase(str(project_root)),
        wave,
        toolchain_identity,
    )


def _refs_fingerprint(
    refs: tuple["StageReceiptRef", ...],
) -> tuple[tuple[str, str, str, str, str], ...]:
    return tuple(
        (item.node_id, item.relative_path, item.sha256, item.stage, item.scope_key)
        for item in refs
    )


def _effective_resume_from_registry(
    cached: object | None,
    *,
    caller_resume: bool,
) -> bool:
    """Authorize second-fold resume only from sealed canonical success.

    Missing entry → honor caller resume. Poison / wrong-type entry → fail closed.
    """

    if cached is None:
        return caller_resume
    if type(cached) is not _CanonicalWaveSuccess or not cached.authorized():
        _fail("SUCCESSOR_STAGE_INVALID")
    return True


def _seal_wave_success(refs: tuple["StageReceiptRef", ...]) -> _CanonicalWaveSuccess:
    return _CanonicalWaveSuccess(refs, seal=_WAVE_SUCCESS_SEAL)


def _toolchain_identity_for_context(context: "SuccessorStageContext") -> str:
    toolchain = context.request.toolchain
    fold_configs = tuple(item.config.config for item in context.request.folds)
    return _toolchain_identity(
        project_root=context.project_root, toolchain=toolchain, fold_configs=fold_configs,
    )


# --------------------------------------------------------------------------
# Generic proof-capture build/verify pattern for StageRunner.run_static
# --------------------------------------------------------------------------


def _capture_tree_proof(root: Path) -> dict[str, bytes]:
    proof: dict[str, bytes] = {}
    if not root.exists():
        return proof
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            _fail("SUCCESSOR_STAGE_INVALID")
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or bool(
            getattr(info, "st_file_attributes", 0) & _REPARSE
        ):
            _fail("SUCCESSOR_STAGE_INVALID")
        proof[path.relative_to(root).as_posix()] = path.read_bytes()
    return proof


def _run_static_node_with_proof(
    *,
    runner: "StageRunner",
    node: "StageNode",
    plan: "RunPlan",
    resume: bool,
    build: Callable[[Path], object],
) -> tuple["StaticStageResult", object]:
    """Run one static node, capturing the build's own output bytes as proof.

    The closure verifier compares the freshly built temp/final tree bytes to
    the captured proof; on a resumed (no rebuild) path it is a no-op because
    the caller always re-verifies content independently afterward via the
    stage's dedicated ``verify_*_artifact``.
    """

    from quant.research.m3.orchestration import StageBuildReport

    captured: list[tuple[object, dict[str, bytes]]] = []

    def handler(stage_context: "StageContext") -> "StageBuildReport":
        if stage_context.node is not node:
            raise ValueError("stage context node identity drift")
        manifest = build(stage_context.temp_output_root)
        proof = _capture_tree_proof(stage_context.temp_output_root)
        captured.append((manifest, proof))
        return StageBuildReport(tuple(sorted(proof)))

    def closure(root: Path) -> None:
        if captured:
            if _capture_tree_proof(root) != captured[0][1]:
                _fail("SUCCESSOR_STAGE_INVALID")

    try:
        static = runner.run_static(
            node=node, handler=handler, closure_verifier=closure, resume=resume, plan=plan,
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")
    manifest = captured[0][0] if captured else None
    return static, manifest


# --------------------------------------------------------------------------
# Prior-receipt reconstruction
# --------------------------------------------------------------------------


def _verify_prior_receipt(ref: "StageReceiptRef", *, project_root: Path) -> "StageReceipt":
    from quant.research.m3.run_state import verify_stage_receipt_with_bytes

    receipt_path = project_root / ref.relative_path
    try:
        verified = verify_stage_receipt_with_bytes(
            receipt_path=receipt_path, artifact_roots={"PROJECT": project_root},
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")
    if (
        verified is None
        or verified.sha256 != ref.sha256
        or verified.receipt.stage != ref.stage
        or verified.receipt.scope != ref.scope
        or verified.receipt.scope_key != ref.scope_key
    ):
        _fail("SUCCESSOR_STAGE_INVALID")
    return verified.receipt


def _receipt_output_path(receipt: "StageReceipt", *, name: str, project_root: Path) -> Path:
    matches = [
        item for item in receipt.outputs if PurePosixPath(item.relative_path).name == name
    ]
    if len(matches) != 1:
        _fail("SUCCESSOR_STAGE_INVALID")
    return project_root / matches[0].relative_path


def _group_prior_refs_by_stage(
    prior_refs: tuple["StageReceiptRef", ...], *, wave: str,
) -> dict[str, tuple["StageReceiptRef", ...]]:
    required = _REQUIRED_PRIOR_STAGES[wave]
    by_stage: dict[str, list["StageReceiptRef"]] = {}
    for ref in prior_refs:
        by_stage.setdefault(ref.stage, []).append(ref)
    if set(by_stage) != set(required):
        _fail("SUCCESSOR_STAGE_INVALID")
    for stage, count in required.items():
        if len(by_stage[stage]) != count:
            _fail("SUCCESSOR_STAGE_INVALID")
    return {stage: tuple(items) for stage, items in by_stage.items()}


def _canonical_horizons_from_config(
    config: "LoadedM3Config",
) -> tuple[Literal[5, 10], ...]:
    """Return the request's canonical horizon tuple (sorted, unique)."""

    from quant.research.m3.successor_runtime import HORIZONS

    try:
        raw = config.section("labels")["horizons_sessions"]
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")
    if type(raw) is not tuple and type(raw) is not list:
        _fail("SUCCESSOR_STAGE_INVALID")
    narrowed = tuple(_require_horizon(item) for item in raw)
    horizons = tuple(sorted(set(narrowed)))
    if not horizons or horizons != tuple(sorted(HORIZONS)):
        _fail("SUCCESSOR_STAGE_INVALID")
    return (5, 10)


def _unique_horizon_ref_map(
    refs: tuple["StageReceiptRef", ...],
    *,
    canonical_horizons: tuple[Literal[5, 10], ...],
) -> dict[Literal[5, 10], "StageReceiptRef"]:
    """Prove unique horizon closure before any horizon-keyed dict write.

    Rejects ``None`` horizon, duplicates, missing members, and extras relative
    to ``canonical_horizons``. Fail closed as ``SUCCESSOR_STAGE_INVALID``.
    """

    if type(refs) is not tuple or len(refs) != len(canonical_horizons):
        _fail("SUCCESSOR_STAGE_INVALID")
    mapping: dict[Literal[5, 10], "StageReceiptRef"] = {}
    for ref in refs:
        horizon = _require_horizon(ref.horizon)
        if horizon not in canonical_horizons or horizon in mapping:
            _fail("SUCCESSOR_STAGE_INVALID")
        mapping[horizon] = ref
    if set(mapping) != set(canonical_horizons):
        _fail("SUCCESSOR_STAGE_INVALID")
    return mapping


def _new_receipt_ref(
    *, receipt_path: Path, receipt: "StageReceipt", project_root: Path,
    node: _ReceiptNodeView,
) -> "StageReceiptRef":
    from quant.research.m3.run_state import verify_stage_receipt_with_bytes
    from quant.research.m3.successor_runtime import StageReceiptRef

    try:
        resolved = receipt_path.resolve(strict=True)
        relative = resolved.relative_to(project_root).as_posix()
        verified = verify_stage_receipt_with_bytes(
            receipt_path=resolved, artifact_roots={"PROJECT": project_root},
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")
    if verified is None or verified.receipt != receipt:
        _fail("SUCCESSOR_STAGE_INVALID")
    return StageReceiptRef(
        node_id=node.node_id,
        stage=receipt.stage,
        scope=receipt.scope,
        scope_key=receipt.scope_key,
        relative_path=relative,
        sha256=verified.sha256,
        fold=node.fold,
        horizon=node.horizon,
    )


# --------------------------------------------------------------------------
# Shared upstream chain reconstruction (used by work + label-reconciliation +
# the formal summary gate)
# --------------------------------------------------------------------------


@dataclass
class _RuntimeIds:
    code_version: str
    dependency_fingerprint_sha256: str
    provider_runtime_fingerprint_sha256: str


def _runtime_ids(context: "SuccessorStageContext") -> _RuntimeIds:
    identity = context.request.runtime_identity
    return _RuntimeIds(
        code_version=identity.code_version,
        dependency_fingerprint_sha256=identity.dependency_fingerprint_sha256,
        provider_runtime_fingerprint_sha256=identity.provider_runtime_fingerprint_sha256,
    )


@dataclass
class _SharedUpstream:
    release: "VerifiedG1Release"
    snapshot: "VerifiedSnapshotArtifact"
    snapshot_spec: "SnapshotBuildSpec"
    provider: "VerifiedProviderArtifact"
    provider_spec: "ProviderBuildSpec"
    provider_validation: "VerifiedProviderValidationArtifact"
    experiment: "VerifiedExperimentIdentity"
    experiment_spec: "ExperimentIdentitySpec"
    folds: "VerifiedFoldPlanArtifact | None" = None
    fold_spec: "FoldPlanBuildSpec | None" = None
    labels: dict[Literal[5, 10], "VerifiedLabelArtifact"] = field(default_factory=dict)
    label_specs: dict[Literal[5, 10], "LabelBuildSpec"] = field(default_factory=dict)
    label_receipt_paths: dict[Literal[5, 10], Path] = field(default_factory=dict)
    reconciliations: dict[
        Literal[5, 10], "VerifiedLabelReconciliationArtifact"
    ] = field(default_factory=dict)


def _reconstruct_provider_spec(
    *, provider: "VerifiedProviderArtifact", config: "LoadedM3Config",
) -> "ProviderBuildSpec":
    from quant.research.m3.contracts import ProviderBuildSpec
    from quant.research.m3.fetch_qlib_tool import build_qlib_dump_tool_spec
    from quant.research.m3.provider import build_provider_runtime_fingerprint

    try:
        dump_tool = build_qlib_dump_tool_spec(config)
        runtime_fingerprint = build_provider_runtime_fingerprint()
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")
    try:
        return ProviderBuildSpec(
            snapshot_id=provider.manifest.snapshot_id,
            snapshot_manifest_sha256=provider.manifest.snapshot_manifest_sha256,
            provider_key=provider.manifest.provider_key,
            provider_config_sha256=config.provider_config_sha256,
            dump_tool=dump_tool,
            qlib_version="0.9.7",
            code_version=provider.manifest.code_version,
            runtime_fingerprint=runtime_fingerprint,
            fields=_require_str_tuple(
                provider.manifest.fields, code="SUCCESSOR_STAGE_INVALID",
            ),
            frequency=_require_frequency(provider.manifest.frequency),
            dump_contract_version=_require_dump_contract(
                provider.manifest.dump_contract_version,
            ),
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")


def _reconstruct_shared_upstream(
    *,
    by_stage: Mapping[str, tuple["StageReceiptRef", ...]],
    project_root: Path,
    release: "VerifiedG1Release",
    config: "LoadedM3Config",
    ids: _RuntimeIds,
    dump_tool_path: Path,
    include_reconciliation: bool,
) -> _SharedUpstream:
    from quant.research.m3.contracts import (
        ExperimentIdentitySpec,
        FoldPlanBuildSpec,
        FoldPlanUpstreamPaths,
        LabelBuildSpec,
        SnapshotBuildSpec,
    )
    from quant.research.m3.folds import verify_fold_plan_artifact
    from quant.research.m3.labels import verify_experiment_identity, verify_label_artifact
    from quant.research.m3.provider import verify_provider_artifact
    from quant.research.m3.provider_validation import verify_provider_validation_artifact
    from quant.research.m3.run_state import compute_snapshot_request_key
    from quant.research.m3.snapshot import verify_snapshot_artifact

    snapshot_ref = by_stage["snapshot"][0]
    snapshot_receipt = _verify_prior_receipt(snapshot_ref, project_root=project_root)
    snapshot_request_key = compute_snapshot_request_key(
        g1_release_id=release.manifest.release_id,
        g1_release_manifest_sha256=release.manifest_sha256,
        snapshot_config_sha256=config.snapshot_config_sha256,
        code_version=ids.code_version,
    )
    if snapshot_request_key != snapshot_ref.scope_key:
        _fail("SUCCESSOR_STAGE_INVALID")
    snapshot_spec = SnapshotBuildSpec(
        snapshot_request_key=snapshot_request_key,
        config_version=config.config_version,
        snapshot_config_sha256=config.snapshot_config_sha256,
        code_version=ids.code_version,
        history_start=release.manifest.history_start,
        history_end=release.manifest.history_end,
        staging_schema_version="m3-qlib-staging-v1",
        adjustment_formula_version="qlib_yahoo_like_v1",
    )
    snapshot_root = _receipt_output_path(
        snapshot_receipt, name="manifest.json", project_root=project_root
    ).parent
    snapshot_request_path = _receipt_output_path(
        snapshot_receipt, name=f"{snapshot_request_key}.json", project_root=project_root
    )
    try:
        snapshot = verify_snapshot_artifact(
            snapshot_root=snapshot_root, snapshot_request_path=snapshot_request_path,
            snapshot_receipt_path=project_root / snapshot_ref.relative_path,
            release=release, config=config, spec=snapshot_spec,
            artifact_roots={"PROJECT": project_root},
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    provider_ref = by_stage["provider"][0]
    provider_receipt = _verify_prior_receipt(provider_ref, project_root=project_root)
    provider_root = _receipt_output_path(
        provider_receipt, name="manifest.json", project_root=project_root
    ).parent
    try:
        provider = verify_provider_artifact(
            provider_root=provider_root,
            provider_receipt_path=project_root / provider_ref.relative_path,
            snapshot=snapshot, config=config, artifact_roots={"PROJECT": project_root},
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")
    provider_spec = _reconstruct_provider_spec(provider=provider, config=config)

    validation_ref = by_stage["provider-validation"][0]
    validation_receipt = _verify_prior_receipt(validation_ref, project_root=project_root)
    validation_root = _receipt_output_path(
        validation_receipt, name="manifest.json", project_root=project_root
    ).parent
    try:
        from quant.research.m3.contracts import ProviderValidationSpec

        validation_spec = ProviderValidationSpec(
            provider_validation_key=validation_ref.scope_key,
            provider_validation_config_sha256=config.provider_validation_config_sha256,
            code_version=ids.code_version,
            qlib_version="0.9.7",
            sampling_policy_version="provider_market_stratified_hash_first_last_v1",
            worker_protocol_version="m3-qlib-worker-v1",
        )
        provider_validation = verify_provider_validation_artifact(
            validation_root=validation_root,
            validation_receipt_path=project_root / validation_ref.relative_path,
            snapshot=snapshot, provider=provider, config=config, spec=validation_spec,
            artifact_roots={"PROJECT": project_root},
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    experiment_ref = by_stage["experiment-identity"][0]
    experiment_receipt = _verify_prior_receipt(experiment_ref, project_root=project_root)
    experiment_root = _receipt_output_path(
        experiment_receipt, name="experiment_manifest.json", project_root=project_root
    ).parent
    experiment_spec = ExperimentIdentitySpec(
        scientific_config_sha256=config.scientific_config_sha256,
        dependency_fingerprint_sha256=ids.dependency_fingerprint_sha256,
        code_version=ids.code_version,
    )
    try:
        experiment = verify_experiment_identity(
            experiment_root=experiment_root,
            experiment_receipt_path=project_root / experiment_ref.relative_path,
            snapshot=snapshot, provider=provider, config=config, spec=experiment_spec,
            artifact_roots={"PROJECT": project_root},
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    result = _SharedUpstream(
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec,
        provider_validation=provider_validation, experiment=experiment,
        experiment_spec=experiment_spec,
    )

    if "labels" in by_stage:
        canonical_horizons = _canonical_horizons_from_config(config)
        label_by_horizon = _unique_horizon_ref_map(
            by_stage["labels"], canonical_horizons=canonical_horizons,
        )
        for horizon, label_ref in label_by_horizon.items():
            label_receipt = _verify_prior_receipt(label_ref, project_root=project_root)
            label_root = _receipt_output_path(
                label_receipt, name="manifest.json", project_root=project_root
            ).parent
            label_spec = LabelBuildSpec(
                experiment_key=experiment.manifest.experiment_key,
                experiment_manifest_sha256=experiment.manifest_sha256,
                horizon_sessions=horizon,
                benchmark=_require_benchmark(config.section("data")["benchmark"]),
                label_version=_require_str(config.section("labels")["label_version"]),
                label_build_code_version=ids.code_version,
            )
            try:
                label = verify_label_artifact(
                    label_root=label_root,
                    label_receipt_path=project_root / label_ref.relative_path,
                    release=release, snapshot=snapshot, experiment=experiment,
                    config=config, experiment_spec=experiment_spec, spec=label_spec,
                    artifact_roots={"PROJECT": project_root},
                )
            except Exception:
                _fail("SUCCESSOR_STAGE_INVALID")
            result.labels[horizon] = label
            result.label_specs[horizon] = label_spec
            result.label_receipt_paths[horizon] = project_root / label_ref.relative_path

    if "folds" in by_stage:
        folds_ref = by_stage["folds"][0]
        folds_receipt = _verify_prior_receipt(folds_ref, project_root=project_root)
        folds_root = _receipt_output_path(
            folds_receipt, name="manifest.json", project_root=project_root
        ).parent
        walk = config.section("walk_forward")
        fold_spec = FoldPlanBuildSpec(
            experiment_key=experiment.manifest.experiment_key,
            experiment_manifest_sha256=experiment.manifest_sha256,
            snapshot_id=snapshot.manifest.snapshot_id,
            snapshot_manifest_sha256=snapshot.manifest_sha256,
            signal_start=snapshot.request.signal_start,
            signal_end=snapshot.request.signal_end,
            train_sessions=_require_positive_int(walk["train_sessions"]),
            validation_sessions=_require_positive_int(walk["validation_sessions"]),
            test_sessions=_require_positive_int(walk["test_sessions"]),
            step_sessions=_require_positive_int(walk["step_sessions"]),
            embargo_sessions=_require_positive_int(walk["embargo_sessions"]),
            max_horizon_sessions=max(_canonical_horizons_from_config(config)),
        )
        fold_upstream = FoldPlanUpstreamPaths(
            snapshot_request_path=snapshot_request_path,
            snapshot_receipt_path=project_root / snapshot_ref.relative_path,
            provider_dump_tool_path=dump_tool_path,
            provider_receipt_path=project_root / provider_ref.relative_path,
            experiment_receipt_path=project_root / experiment_ref.relative_path,
        )
        try:
            folds = verify_fold_plan_artifact(
                root=folds_root, receipt_path=project_root / folds_ref.relative_path,
                release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
                provider=provider, provider_spec=provider_spec, experiment=experiment,
                experiment_spec=experiment_spec, config=config, spec=fold_spec,
                upstream_paths=fold_upstream, artifact_roots={"PROJECT": project_root},
            )
        except Exception:
            _fail("SUCCESSOR_STAGE_INVALID")
        result.folds = folds
        result.fold_spec = fold_spec

    if include_reconciliation and "label-reconciliation" in by_stage:
        from quant.research.m3.contracts import LabelReconciliationSpec
        from quant.research.m3.labels import verify_label_reconciliation_artifact

        canonical_horizons = _canonical_horizons_from_config(config)
        reconciliation_by_horizon = _unique_horizon_ref_map(
            by_stage["label-reconciliation"], canonical_horizons=canonical_horizons,
        )
        for horizon, reconciliation_ref in reconciliation_by_horizon.items():
            if horizon not in result.labels:
                _fail("SUCCESSOR_STAGE_INVALID")
            reconciliation_receipt = _verify_prior_receipt(
                reconciliation_ref, project_root=project_root
            )
            reconciliation_root = _receipt_output_path(
                reconciliation_receipt, name="manifest.json", project_root=project_root
            ).parent
            atol = config.section("label_reconciliation")
            reconciliation_spec = LabelReconciliationSpec(
                reconciliation_key=reconciliation_ref.scope_key,
                experiment_key=experiment.manifest.experiment_key,
                horizon_sessions=horizon,
                provider_validation_receipt_sha256=provider_validation.validation_receipt_sha256,
                label_manifest_sha256=result.labels[horizon].manifest_sha256,
                label_reconciliation_config_sha256=config.label_reconciliation_config_sha256,
                dependency_fingerprint_sha256=ids.dependency_fingerprint_sha256,
                code_version=ids.code_version,
                worker_protocol_version="m3-qlib-worker-v1",
                qlib_version="0.9.7",
                qlib_expression_atol=_require_finite_float(atol["qlib_expression_atol"]),
                benchmark_return_atol=_require_finite_float(atol["benchmark_return_atol"]),
                label_return_atol=_require_finite_float(atol["label_return_atol"]),
            )
            from quant.research.m3.contracts import LabelReconciliationReceiptPaths

            receipt_paths = LabelReconciliationReceiptPaths(
                snapshot_receipt_path=project_root / snapshot_ref.relative_path,
                provider_receipt_path=project_root / provider_ref.relative_path,
                provider_validation_receipt_path=project_root / validation_ref.relative_path,
                experiment_receipt_path=project_root / experiment_ref.relative_path,
                label_receipt_path=result.label_receipt_paths[horizon],
            )
            try:
                reconciliation = verify_label_reconciliation_artifact(
                    reconciliation_root=reconciliation_root,
                    reconciliation_receipt_path=project_root / reconciliation_ref.relative_path,
                    release=release, snapshot=snapshot, experiment=experiment,
                    provider=provider, provider_validation=provider_validation,
                    labels=result.labels[horizon], config=config, spec=reconciliation_spec,
                    receipt_paths=receipt_paths, artifact_roots={"PROJECT": project_root},
                )
            except Exception:
                _fail("SUCCESSOR_STAGE_INVALID")
            result.reconciliations[horizon] = reconciliation

    return result


# --------------------------------------------------------------------------
# Per-wave implementations
# --------------------------------------------------------------------------


def _g1_release_snapshot_inputs(
    release: "VerifiedG1Release", *, project_root: Path,
) -> tuple["ArtifactDigest", ...]:
    from quant.research.m3.orchestration import ArtifactDigest

    paths = (
        release.release.manifest_path,
        *(dict(release.artifact_paths)[name] for name in (
            "bar_1d.parquet", "universe_membership.parquet", "trade_calendar.parquet",
        )),
    )
    inputs: list[ArtifactDigest] = []
    for path in paths:
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            _fail("SUCCESSOR_RELEASE_INVALID")
        if not resolved.is_relative_to(project_root):
            _fail("SUCCESSOR_RELEASE_INVALID")
        raw = resolved.read_bytes()
        inputs.append(ArtifactDigest(
            root_alias="PROJECT",
            relative_path=resolved.relative_to(project_root).as_posix(),
            size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
        ))
    return tuple(inputs)


def _run_snapshot_wave(
    *, request: "SuccessorFoldRequest", context: "SuccessorStageContext",
    runner: "StageRunner", public_apis: "SuccessorPublicApiBundle",
    prior_refs: tuple["StageReceiptRef", ...], resume: bool,
) -> tuple["StageReceiptRef", ...]:
    from quant.research.m3.contracts import SnapshotBuildSpec
    from quant.research.m3.orchestration import StageBuildReport, select_run_plan_nodes
    from quant.research.m3.run_state import compute_snapshot_request_key
    from quant.research.m3.snapshot import (
        build_snapshot_artifact,
        build_snapshot_request_record,
        verify_snapshot_artifact,
        verify_snapshot_build_result,
    )

    if prior_refs:
        _fail("SUCCESSOR_STAGE_INVALID")
    project_root = context.project_root
    config = request.config.config
    release = request.release
    code_version = context.request.runtime_identity.code_version
    snapshot_request_key = compute_snapshot_request_key(
        g1_release_id=release.manifest.release_id,
        g1_release_manifest_sha256=release.manifest_sha256,
        snapshot_config_sha256=config.snapshot_config_sha256,
        code_version=code_version,
    )
    snapshot_spec = SnapshotBuildSpec(
        snapshot_request_key=snapshot_request_key,
        config_version=config.config_version,
        snapshot_config_sha256=config.snapshot_config_sha256,
        code_version=code_version,
        history_start=release.manifest.history_start,
        history_end=release.manifest.history_end,
        staging_schema_version="m3-qlib-staging-v1",
        adjustment_formula_version="qlib_yahoo_like_v1",
    )
    inputs = _g1_release_snapshot_inputs(release, project_root=project_root)
    plan_builder = public_apis.run_plan_builders["snapshot"]
    try:
        plan = _require_run_plan(
            plan_builder(snapshot_request_key=snapshot_request_key, inputs=inputs),
        )
        (node,) = select_run_plan_nodes(
            plan, expected_continuation="SNAPSHOT", expected_node_ids=("snapshot",),
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    def handler(stage_context: "StageContext") -> "StageBuildReport":
        if stage_context.node is not node:
            raise ValueError("snapshot stage context node identity drift")
        build_snapshot_artifact(
            release=release, config=config, spec=snapshot_spec,
            output_root=stage_context.temp_output_root,
        )
        relative = tuple(sorted(
            item.relative_to(stage_context.temp_output_root).as_posix()
            for item in stage_context.temp_output_root.rglob("*") if item.is_file()
        ))
        return StageBuildReport(relative)

    def closure(root: Path) -> tuple["SnapshotBuildResult", "SnapshotRequestRecordV1"]:
        build_result = verify_snapshot_build_result(
            snapshot_root=root, release=release, config=config, spec=snapshot_spec,
        )
        request_record = build_snapshot_request_record(
            release=release, config=config, spec=snapshot_spec, result=build_result,
        )
        return build_result, request_record

    try:
        result = runner.run_snapshot(
            node=node, handler=handler, closure_verifier=closure, resume=resume,
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    try:
        verified = verify_snapshot_artifact(
            snapshot_root=result.snapshot_root,
            snapshot_request_path=result.request_record_path,
            snapshot_receipt_path=result.receipt_path,
            release=release, config=config, spec=snapshot_spec,
            artifact_roots=context.artifact_roots,
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")
    if verified.manifest.snapshot_id != result.build.manifest.snapshot_id:
        _fail("SUCCESSOR_STAGE_INVALID")

    ref = _new_receipt_ref(
        receipt_path=result.receipt_path, receipt=result.receipt,
        project_root=project_root, node=node,
    )
    return (ref,)


def _reconstruct_snapshot_only(
    *, snapshot_ref: "StageReceiptRef", project_root: Path,
    release: "VerifiedG1Release", config: "LoadedM3Config", ids: _RuntimeIds,
) -> tuple["VerifiedSnapshotArtifact", "SnapshotBuildSpec"]:
    from quant.research.m3.contracts import SnapshotBuildSpec
    from quant.research.m3.run_state import compute_snapshot_request_key
    from quant.research.m3.snapshot import verify_snapshot_artifact

    snapshot_receipt = _verify_prior_receipt(snapshot_ref, project_root=project_root)
    snapshot_request_key = compute_snapshot_request_key(
        g1_release_id=release.manifest.release_id,
        g1_release_manifest_sha256=release.manifest_sha256,
        snapshot_config_sha256=config.snapshot_config_sha256,
        code_version=ids.code_version,
    )
    if snapshot_request_key != snapshot_ref.scope_key:
        _fail("SUCCESSOR_STAGE_INVALID")
    snapshot_spec = SnapshotBuildSpec(
        snapshot_request_key=snapshot_request_key,
        config_version=config.config_version,
        snapshot_config_sha256=config.snapshot_config_sha256,
        code_version=ids.code_version,
        history_start=release.manifest.history_start,
        history_end=release.manifest.history_end,
        staging_schema_version="m3-qlib-staging-v1",
        adjustment_formula_version="qlib_yahoo_like_v1",
    )
    snapshot_root = _receipt_output_path(
        snapshot_receipt, name="manifest.json", project_root=project_root
    ).parent
    snapshot_request_path = _receipt_output_path(
        snapshot_receipt, name=f"{snapshot_request_key}.json", project_root=project_root
    )
    try:
        snapshot = verify_snapshot_artifact(
            snapshot_root=snapshot_root, snapshot_request_path=snapshot_request_path,
            snapshot_receipt_path=project_root / snapshot_ref.relative_path,
            release=release, config=config, spec=snapshot_spec,
            artifact_roots={"PROJECT": project_root},
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")
    return snapshot, snapshot_spec


def _run_provider_wave(
    *, request: "SuccessorFoldRequest", context: "SuccessorStageContext",
    runner: "StageRunner", public_apis: "SuccessorPublicApiBundle",
    prior_refs: tuple["StageReceiptRef", ...], resume: bool,
) -> tuple["StageReceiptRef", ...]:
    from quant.research.m3.contracts import ProviderBuildSpec
    from quant.research.m3.fetch_qlib_tool import build_qlib_dump_tool_spec
    from quant.research.m3.orchestration import select_run_plan_nodes
    from quant.research.m3.provider import (
        build_provider_runtime_fingerprint,
        materialize_qlib_provider,
        verify_provider_artifact,
    )
    from quant.research.m3.run_state import compute_provider_key

    project_root = context.project_root
    config = request.config.config
    toolchain = _require_toolchain(context.request.toolchain)
    fold_configs = tuple(item.config.config for item in context.request.folds)
    validate_successor_toolchain_binding(
        project_root=project_root, toolchain=toolchain, fold_configs=fold_configs,
    )
    ids = _runtime_ids(context)
    by_stage = _group_prior_refs_by_stage(prior_refs, wave="provider")
    snapshot, _snapshot_spec = _reconstruct_snapshot_only(
        snapshot_ref=by_stage["snapshot"][0], project_root=project_root,
        release=request.release, config=config, ids=ids,
    )

    try:
        dump_tool = build_qlib_dump_tool_spec(config)
        runtime_fingerprint = build_provider_runtime_fingerprint()
    except Exception:
        _fail("SUCCESSOR_CONFIG_INVALID")
    provider_key = compute_provider_key(
        snapshot_id=snapshot.manifest.snapshot_id,
        provider_config_hash=config.provider_config_sha256,
        dump_tool_sha256=dump_tool.sha256,
        qlib_version=dump_tool.qlib_version,
        provider_runtime_fingerprint_sha256=runtime_fingerprint.sha256,
        code_version=ids.code_version,
    )
    provider_spec = ProviderBuildSpec(
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_key=provider_key,
        provider_config_sha256=config.provider_config_sha256,
        dump_tool=dump_tool,
        qlib_version="0.9.7",
        code_version=ids.code_version,
        runtime_fingerprint=runtime_fingerprint,
        fields=_require_str_tuple(config.section("provider")["fields"]),
        frequency="day",
        dump_contract_version="m3-qlib-dump-all-v1",
    )

    plan_builder = public_apis.run_plan_builders["provider"]
    try:
        plan = _require_run_plan(
            plan_builder(
                config=config, snapshot=snapshot, spec=provider_spec,
                dump_tool_path=toolchain.qlib_dump_tool_path,
                artifact_roots=context.artifact_roots,
            ),
        )
        (node,) = select_run_plan_nodes(
            plan, expected_continuation="PROVIDER",
            expected_node_ids=tuple(item.node_id for item in plan.nodes),
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    def build(output_root: Path) -> object:
        return materialize_qlib_provider(
            snapshot=snapshot, qlib_dump_script=toolchain.qlib_dump_tool_path,
            python_executable=toolchain.python_executable, config=config, spec=provider_spec,
            output_root=output_root, timeout_seconds=toolchain.timeout_seconds,
        )

    static, _manifest = _run_static_node_with_proof(
        runner=runner, node=node, plan=plan, resume=resume, build=build,
    )
    try:
        verify_provider_artifact(
            provider_root=static.final_root, provider_receipt_path=static.receipt_path,
            snapshot=snapshot, config=config, artifact_roots=context.artifact_roots,
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    ref = _new_receipt_ref(
        receipt_path=static.receipt_path, receipt=static.receipt,
        project_root=project_root, node=node,
    )
    return (ref,)


def _run_provider_validation_wave(
    *, request: "SuccessorFoldRequest", context: "SuccessorStageContext",
    runner: "StageRunner", public_apis: "SuccessorPublicApiBundle",
    prior_refs: tuple["StageReceiptRef", ...], resume: bool,
) -> tuple["StageReceiptRef", ...]:
    from quant.research.m3.contracts import ProviderValidationSpec
    from quant.research.m3.orchestration import select_run_plan_nodes
    from quant.research.m3.provider import build_provider_runtime_fingerprint, verify_provider_artifact
    from quant.research.m3.provider_validation import (
        plan_provider_probe,
        validate_provider_public_api,
        verify_provider_validation_artifact,
    )
    from quant.research.m3.run_state import compute_provider_validation_key

    project_root = context.project_root
    config = request.config.config
    toolchain = _require_toolchain(context.request.toolchain)
    fold_configs = tuple(item.config.config for item in context.request.folds)
    validate_successor_toolchain_binding(
        project_root=project_root, toolchain=toolchain, fold_configs=fold_configs,
    )
    ids = _runtime_ids(context)
    by_stage = _group_prior_refs_by_stage(prior_refs, wave="provider-validation")
    snapshot, _snapshot_spec = _reconstruct_snapshot_only(
        snapshot_ref=by_stage["snapshot"][0], project_root=project_root,
        release=request.release, config=config, ids=ids,
    )
    provider_ref = by_stage["provider"][0]
    provider_receipt = _verify_prior_receipt(provider_ref, project_root=project_root)
    provider_root = _receipt_output_path(
        provider_receipt, name="manifest.json", project_root=project_root
    ).parent
    try:
        provider = verify_provider_artifact(
            provider_root=provider_root,
            provider_receipt_path=project_root / provider_ref.relative_path,
            snapshot=snapshot, config=config, artifact_roots=context.artifact_roots,
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    try:
        runtime_fingerprint = build_provider_runtime_fingerprint()
    except Exception:
        _fail("SUCCESSOR_CONFIG_INVALID")
    validation_key = compute_provider_validation_key(
        provider_key=provider.manifest.provider_key,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        provider_validation_config_sha256=config.provider_validation_config_sha256,
        provider_runtime_fingerprint_sha256=runtime_fingerprint.sha256,
        code_version=ids.code_version,
    )
    validation_spec = ProviderValidationSpec(
        provider_validation_key=validation_key,
        provider_validation_config_sha256=config.provider_validation_config_sha256,
        code_version=ids.code_version,
        qlib_version="0.9.7",
        sampling_policy_version="provider_market_stratified_hash_first_last_v1",
        worker_protocol_version="m3-qlib-worker-v1",
    )

    plan_builder = public_apis.run_plan_builders["provider-validation"]
    try:
        plan = _require_run_plan(
            plan_builder(
                config=config, snapshot=snapshot, provider=provider, spec=validation_spec,
                artifact_roots=context.artifact_roots,
            ),
        )
        (node,) = select_run_plan_nodes(
            plan, expected_continuation="PROVIDER",
            expected_node_ids=tuple(item.node_id for item in plan.nodes),
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    def build(output_root: Path) -> object:
        probe_plan = plan_provider_probe(
            snapshot=snapshot, provider=provider, config=config, spec=validation_spec,
        )
        return validate_provider_public_api(
            snapshot=snapshot, provider=provider, probe_plan=probe_plan, config=config,
            spec=validation_spec, python_executable=toolchain.python_executable,
            output_root=output_root, timeout_seconds=toolchain.timeout_seconds,
        )

    static, _manifest = _run_static_node_with_proof(
        runner=runner, node=node, plan=plan, resume=resume, build=build,
    )
    try:
        verify_provider_validation_artifact(
            validation_root=static.final_root, validation_receipt_path=static.receipt_path,
            snapshot=snapshot, provider=provider, config=config, spec=validation_spec,
            artifact_roots=context.artifact_roots,
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    ref = _new_receipt_ref(
        receipt_path=static.receipt_path, receipt=static.receipt,
        project_root=project_root, node=node,
    )
    return (ref,)


def _run_experiment_identity_wave(
    *, request: "SuccessorFoldRequest", context: "SuccessorStageContext",
    runner: "StageRunner", public_apis: "SuccessorPublicApiBundle",
    prior_refs: tuple["StageReceiptRef", ...], resume: bool,
) -> tuple["StageReceiptRef", ...]:
    from quant.research.m3.contracts import ExperimentIdentitySpec, ProviderValidationSpec
    from quant.research.m3.experiment_identity import (
        build_experiment_identity_manifest,
        make_experiment_identity_handler,
        verify_experiment_identity_output,
    )
    from quant.research.m3.labels import verify_experiment_identity
    from quant.research.m3.orchestration import select_run_plan_nodes
    from quant.research.m3.provider import verify_provider_artifact
    from quant.research.m3.provider_validation import verify_provider_validation_artifact

    project_root = context.project_root
    config = request.config.config
    ids = _runtime_ids(context)
    by_stage = _group_prior_refs_by_stage(prior_refs, wave="experiment-identity")
    snapshot, _snapshot_spec = _reconstruct_snapshot_only(
        snapshot_ref=by_stage["snapshot"][0], project_root=project_root,
        release=request.release, config=config, ids=ids,
    )
    provider_ref = by_stage["provider"][0]
    provider_receipt = _verify_prior_receipt(provider_ref, project_root=project_root)
    provider_root = _receipt_output_path(
        provider_receipt, name="manifest.json", project_root=project_root
    ).parent
    try:
        provider = verify_provider_artifact(
            provider_root=provider_root,
            provider_receipt_path=project_root / provider_ref.relative_path,
            snapshot=snapshot, config=config, artifact_roots=context.artifact_roots,
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    validation_ref = by_stage["provider-validation"][0]
    validation_receipt = _verify_prior_receipt(validation_ref, project_root=project_root)
    validation_root = _receipt_output_path(
        validation_receipt, name="manifest.json", project_root=project_root
    ).parent
    validation_spec = ProviderValidationSpec(
        provider_validation_key=validation_ref.scope_key,
        provider_validation_config_sha256=config.provider_validation_config_sha256,
        code_version=ids.code_version,
        qlib_version="0.9.7",
        sampling_policy_version="provider_market_stratified_hash_first_last_v1",
        worker_protocol_version="m3-qlib-worker-v1",
    )
    try:
        provider_validation = verify_provider_validation_artifact(
            validation_root=validation_root,
            validation_receipt_path=project_root / validation_ref.relative_path,
            snapshot=snapshot, provider=provider, config=config, spec=validation_spec,
            artifact_roots=context.artifact_roots,
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    experiment_spec = ExperimentIdentitySpec(
        scientific_config_sha256=config.scientific_config_sha256,
        dependency_fingerprint_sha256=ids.dependency_fingerprint_sha256,
        code_version=ids.code_version,
    )
    plan_builder = public_apis.run_plan_builders["experiment-identity"]
    try:
        plan = _require_run_plan(
            plan_builder(
                snapshot=snapshot, provider=provider, provider_validation=provider_validation,
                config=config, spec=experiment_spec, artifact_roots=context.artifact_roots,
            ),
        )
        (node,) = select_run_plan_nodes(
            plan, expected_continuation="EXPERIMENT",
            expected_node_ids=tuple(item.node_id for item in plan.nodes),
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    handler = make_experiment_identity_handler(
        snapshot=snapshot, provider=provider, spec=experiment_spec,
    )

    def output_verifier(root: Path) -> None:
        expected_manifest = build_experiment_identity_manifest(
            snapshot=snapshot, provider=provider, config=config, spec=experiment_spec,
        )
        verify_experiment_identity_output(root=root, expected=expected_manifest)

    def final_verifier(experiment_root: Path, receipt_path: Path) -> "VerifiedExperimentIdentity":
        return verify_experiment_identity(
            experiment_root=experiment_root, experiment_receipt_path=receipt_path,
            snapshot=snapshot, provider=provider, config=config, spec=experiment_spec,
            artifact_roots=context.artifact_roots,
        )

    try:
        result = runner.run_experiment_identity(
            node=node, handler=handler, output_verifier=output_verifier,
            final_verifier=final_verifier, resume=resume,
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    ref = _new_receipt_ref(
        receipt_path=result.receipt_path, receipt=result.receipt,
        project_root=project_root, node=node,
    )
    return (ref,)


def _run_experiment_artifacts_wave(
    *, request: "SuccessorFoldRequest", context: "SuccessorStageContext",
    runner: "StageRunner", public_apis: "SuccessorPublicApiBundle",
    prior_refs: tuple["StageReceiptRef", ...], resume: bool,
) -> tuple["StageReceiptRef", ...]:
    from quant.research.m3.contracts import (
        ExperimentIdentitySpec,
        FoldPlanBuildSpec,
        FoldPlanUpstreamPaths,
        LabelBuildSpec,
        ProviderValidationSpec,
    )
    from quant.research.m3.folds import build_temporal_fold_plan, verify_fold_plan_artifact
    from quant.research.m3.labels import (
        build_label_artifact,
        verify_experiment_identity,
        verify_label_artifact,
    )
    from quant.research.m3.orchestration import select_run_plan_nodes
    from quant.research.m3.provider import verify_provider_artifact
    from quant.research.m3.provider_validation import verify_provider_validation_artifact

    project_root = context.project_root
    config = request.config.config
    ids = _runtime_ids(context)
    by_stage = _group_prior_refs_by_stage(prior_refs, wave="experiment-artifacts")
    release = request.release
    snapshot_ref = by_stage["snapshot"][0]
    snapshot, snapshot_spec = _reconstruct_snapshot_only(
        snapshot_ref=snapshot_ref, project_root=project_root,
        release=release, config=config, ids=ids,
    )
    snapshot_receipt = _verify_prior_receipt(snapshot_ref, project_root=project_root)
    snapshot_request_path = _receipt_output_path(
        snapshot_receipt, name=f"{snapshot_ref.scope_key}.json", project_root=project_root,
    )
    provider_ref = by_stage["provider"][0]
    provider_receipt = _verify_prior_receipt(provider_ref, project_root=project_root)
    provider_root = _receipt_output_path(
        provider_receipt, name="manifest.json", project_root=project_root
    ).parent
    try:
        provider = verify_provider_artifact(
            provider_root=provider_root,
            provider_receipt_path=project_root / provider_ref.relative_path,
            snapshot=snapshot, config=config, artifact_roots=context.artifact_roots,
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")
    provider_spec = _reconstruct_provider_spec(provider=provider, config=config)

    validation_ref = by_stage["provider-validation"][0]
    validation_receipt = _verify_prior_receipt(validation_ref, project_root=project_root)
    validation_root = _receipt_output_path(
        validation_receipt, name="manifest.json", project_root=project_root
    ).parent
    validation_spec = ProviderValidationSpec(
        provider_validation_key=validation_ref.scope_key,
        provider_validation_config_sha256=config.provider_validation_config_sha256,
        code_version=ids.code_version,
        qlib_version="0.9.7",
        sampling_policy_version="provider_market_stratified_hash_first_last_v1",
        worker_protocol_version="m3-qlib-worker-v1",
    )
    try:
        verify_provider_validation_artifact(
            validation_root=validation_root,
            validation_receipt_path=project_root / validation_ref.relative_path,
            snapshot=snapshot, provider=provider, config=config, spec=validation_spec,
            artifact_roots=context.artifact_roots,
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    experiment_ref = by_stage["experiment-identity"][0]
    experiment_receipt = _verify_prior_receipt(experiment_ref, project_root=project_root)
    experiment_root = _receipt_output_path(
        experiment_receipt, name="experiment_manifest.json", project_root=project_root
    ).parent
    experiment_spec = ExperimentIdentitySpec(
        scientific_config_sha256=config.scientific_config_sha256,
        dependency_fingerprint_sha256=ids.dependency_fingerprint_sha256,
        code_version=ids.code_version,
    )
    try:
        experiment = verify_experiment_identity(
            experiment_root=experiment_root,
            experiment_receipt_path=project_root / experiment_ref.relative_path,
            snapshot=snapshot, provider=provider, config=config, spec=experiment_spec,
            artifact_roots=context.artifact_roots,
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    horizons = _canonical_horizons_from_config(config)
    label_specs = {
        horizon: LabelBuildSpec(
            experiment_key=experiment.manifest.experiment_key,
            experiment_manifest_sha256=experiment.manifest_sha256,
            horizon_sessions=horizon,
            benchmark=_require_benchmark(config.section("data")["benchmark"]),
            label_version=_require_str(config.section("labels")["label_version"]),
            label_build_code_version=ids.code_version,
        )
        for horizon in horizons
    }
    walk = config.section("walk_forward")
    fold_spec = FoldPlanBuildSpec(
        experiment_key=experiment.manifest.experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        signal_start=snapshot.request.signal_start,
        signal_end=snapshot.request.signal_end,
        train_sessions=_require_positive_int(walk["train_sessions"]),
        validation_sessions=_require_positive_int(walk["validation_sessions"]),
        test_sessions=_require_positive_int(walk["test_sessions"]),
        step_sessions=_require_positive_int(walk["step_sessions"]),
        embargo_sessions=_require_positive_int(walk["embargo_sessions"]),
        max_horizon_sessions=max(horizons),
    )
    toolchain = _require_toolchain(context.request.toolchain)
    fold_upstream = FoldPlanUpstreamPaths(
        snapshot_request_path=snapshot_request_path,
        snapshot_receipt_path=project_root / snapshot_ref.relative_path,
        provider_dump_tool_path=toolchain.qlib_dump_tool_path,
        provider_receipt_path=project_root / provider_ref.relative_path,
        experiment_receipt_path=project_root / experiment_ref.relative_path,
    )

    plan_builder = public_apis.run_plan_builders["experiment-artifacts"]
    try:
        plan = _require_run_plan(
            plan_builder(
                config=config, release=release, snapshot=snapshot, experiment=experiment,
                artifact_roots=context.artifact_roots,
            ),
        )
        nodes = select_run_plan_nodes(
            plan, expected_continuation="EXPERIMENT",
            expected_node_ids=tuple(item.node_id for item in plan.nodes),
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    refs: list["StageReceiptRef"] = []
    for node in nodes:
        if node.spec_name == "folds":
            def build_folds(output_root: Path) -> object:
                return build_temporal_fold_plan(
                    snapshot=snapshot, experiment=experiment, config=config, spec=fold_spec,
                    output_root=output_root,
                )

            static, _manifest = _run_static_node_with_proof(
                runner=runner, node=node, plan=plan, resume=resume, build=build_folds,
            )
            try:
                verify_fold_plan_artifact(
                    root=static.final_root, receipt_path=static.receipt_path,
                    release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
                    provider=provider, provider_spec=provider_spec, experiment=experiment,
                    experiment_spec=experiment_spec, config=config, spec=fold_spec,
                    upstream_paths=fold_upstream, artifact_roots=context.artifact_roots,
                )
            except Exception:
                _fail("SUCCESSOR_STAGE_INVALID")
        elif node.spec_name == "labels":
            horizon = _require_horizon(node.horizon)
            if horizon not in label_specs:
                _fail("SUCCESSOR_STAGE_INVALID")
            label_spec = label_specs[horizon]

            def build_label(output_root: Path, _spec: "LabelBuildSpec" = label_spec) -> object:
                return build_label_artifact(
                    release=release, snapshot=snapshot, experiment=experiment, config=config,
                    experiment_spec=experiment_spec, spec=_spec, output_root=output_root,
                )

            static, _manifest = _run_static_node_with_proof(
                runner=runner, node=node, plan=plan, resume=resume, build=build_label,
            )
            try:
                verify_label_artifact(
                    label_root=static.final_root, label_receipt_path=static.receipt_path,
                    release=release, snapshot=snapshot, experiment=experiment, config=config,
                    experiment_spec=experiment_spec, spec=label_spec,
                    artifact_roots=context.artifact_roots,
                )
            except Exception:
                _fail("SUCCESSOR_STAGE_INVALID")
        else:
            _fail("SUCCESSOR_STAGE_INVALID")

        refs.append(_new_receipt_ref(
            receipt_path=static.receipt_path, receipt=static.receipt,
            project_root=project_root, node=node,
        ))

    return tuple(sorted(refs, key=lambda item: item.node_id))


_WAVE_HANDLERS: dict[str, Callable[..., tuple["StageReceiptRef", ...]]] = {}


def _require_canonical_public_api_bundle(
    candidate: "SuccessorPublicApiBundle", canonical: "SuccessorPublicApiBundle",
) -> None:
    if type(candidate) is not type(canonical):
        _fail("SUCCESSOR_INPUT_INVALID")
    for item in dataclasses.fields(canonical):
        left = getattr(candidate, item.name)
        right = getattr(canonical, item.name)
        if item.name == "run_plan_builders":
            if set(left) != set(right) or any(left[key] is not right[key] for key in right):
                _fail("SUCCESSOR_INPUT_INVALID")
            continue
        if left is not right:
            _fail("SUCCESSOR_INPUT_INVALID")


def run_successor_upstream_wave(
    *,
    wave: str,
    request: "SuccessorFoldRequest",
    context: "SuccessorStageContext",
    runner: "StageRunner",
    public_apis: "SuccessorPublicApiBundle",
    prior_refs: tuple["StageReceiptRef", ...],
    resume: bool,
) -> tuple["StageReceiptRef", ...]:
    """Run exactly one canonical upstream wave and return its fresh receipts.

    ``wave`` must be one of the seven fixed upstream waves.  ``public_apis``
    must be object-identical to :func:`make_public_successor_api_bundle`'s
    canonical builders (a wrapper is rejected).  ``prior_refs`` must be the
    exact, freshly-verifiable closure this wave requires -- no more, no less.
    A physical wave already published for the same two-fold identity, project
    root, wave and toolchain identity is resumed (not rebuilt) on the second
    fold call even when the caller passes ``resume=False``; any other reuse
    attempt fails closed.
    """

    from quant.research.m3.orchestration import StageRunner
    from quant.research.m3.successor_runtime import (
        StageReceiptRef,
        SuccessorFoldRequest,
        SuccessorPublicApiBundle,
        SuccessorRuntimeError,
        SuccessorStageContext,
        make_public_successor_api_bundle,
    )

    if wave not in _UPSTREAM_WAVES:
        _fail("SUCCESSOR_INPUT_INVALID")
    if (
        type(request) is not SuccessorFoldRequest
        or type(context) is not SuccessorStageContext
        or type(runner) is not StageRunner
        or type(public_apis) is not SuccessorPublicApiBundle
        or type(resume) is not bool
    ):
        _fail("SUCCESSOR_INPUT_INVALID")
    if context.fold != request.fold or request not in context.request.folds:
        _fail("SUCCESSOR_INPUT_INVALID")
    canonical = make_public_successor_api_bundle()
    _require_canonical_public_api_bundle(public_apis, canonical)

    if type(prior_refs) is not tuple or any(
        type(item) is not StageReceiptRef for item in prior_refs
    ):
        _fail("SUCCESSOR_STAGE_INVALID")
    node_ids = tuple(item.node_id for item in prior_refs)
    if node_ids != tuple(sorted(node_ids)) or len(set(node_ids)) != len(node_ids):
        _fail("SUCCESSOR_STAGE_INVALID")

    project_root = context.project_root
    try:
        transition_identity = compute_upstream_wave_transition_identity(
            request=context.request,
            wave=wave,
            prior_refs=prior_refs,
        )
        frozen = UpstreamWaveContext(
            request=context.request,
            stage_context=context,
            prior_refs=prior_refs,
            transition_identity=transition_identity,
        )
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    toolchain_identity = _toolchain_identity_for_context(frozen.stage_context)
    key = _registry_key(
        request=frozen.request,
        project_root=project_root,
        wave=wave,
        toolchain_identity=toolchain_identity,
    )

    with _REGISTRY_LOCK:
        cached = _WAVE_REGISTRY.get(key)
    # Same-process second fold: only a sealed canonical success (produced after
    # full plan publish + fresh receipt closure in this request lifecycle) may
    # elevate caller resume=False. Pre-seeded plain refs / poison fail closed.
    effective_resume = _effective_resume_from_registry(
        cached, caller_resume=resume,
    )

    handler = _WAVE_HANDLERS[wave]
    try:
        refs = handler(
            request=request,
            context=frozen.stage_context,
            runner=runner,
            public_apis=canonical,
            prior_refs=frozen.prior_refs,
            resume=effective_resume,
        )
    except Exception:
        # Failed waves must never be registered as successful.
        raise

    if (
        type(refs) is not tuple
        or not refs
        or any(type(item) is not StageReceiptRef for item in refs)
    ):
        _fail("SUCCESSOR_STAGE_INVALID")
    ref_ids = tuple(item.node_id for item in refs)
    if ref_ids != tuple(sorted(ref_ids)) or len(set(ref_ids)) != len(ref_ids):
        _fail("SUCCESSOR_STAGE_INVALID")
    # Fresh-verify every produced receipt before registering or returning.
    for ref in refs:
        _verify_prior_receipt(ref, project_root=project_root)

    sealed = _seal_wave_success(refs)
    with _REGISTRY_LOCK:
        existing = _WAVE_REGISTRY.get(key)
        if existing is None:
            _WAVE_REGISTRY[key] = sealed
        elif (
            type(existing) is not _CanonicalWaveSuccess
            or not existing.authorized()
            or _refs_fingerprint(existing.refs) != _refs_fingerprint(refs)
        ):
            _fail("SUCCESSOR_STAGE_INVALID")
    return refs


@dataclass
class _WorkFoldHorizonState:
    feature: "VerifiedFeatureArtifact"
    feature_spec: "FeatureBuildSpec"
    feature_receipt_path: Path
    alignment: "VerifiedAlignmentArtifact | None" = None
    alignment_spec: "AlignmentBuildSpec | None" = None
    alignment_receipt_path: Path | None = None
    model: "VerifiedModelArtifact | None" = None
    model_spec: "LightgbmTrainingSpec | None" = None
    model_receipt_path: Path | None = None
    prediction: "VerifiedPredictionArtifact | None" = None
    prediction_spec: "PredictionBuildSpec | None" = None
    prediction_receipt_path: Path | None = None


def _run_work_wave(
    *, request: "SuccessorFoldRequest", context: "SuccessorStageContext",
    runner: "StageRunner", public_apis: "SuccessorPublicApiBundle",
    prior_refs: tuple["StageReceiptRef", ...], resume: bool,
) -> tuple["StageReceiptRef", ...]:
    from quant.research.m3.alignment import build_alignment_artifact, verify_alignment_artifact
    from quant.research.m3.contracts import (
        AlignmentBuildSpec,
        AlignmentUpstreamPaths,
        EvaluationSpec,
        EvaluationUpstreamPaths,
        FeatureBuildSpec,
        FeatureUpstreamPaths,
        FoldPlanUpstreamPaths,
        ModelUpstreamPaths,
        PredictionBuildSpec,
        PredictionUpstreamPaths,
        TargetBuildSpec,
        TargetUpstreamPaths,
    )
    from quant.backtest.a_share_plan import (
        BacktestPlanFreshVerificationContext,
        build_backtest_plan_artifact,
        verify_backtest_plan_artifact,
    )
    from quant.research.m3.evaluate import build_evaluation_artifact, verify_evaluation_artifact
    from quant.research.m3.features import build_feature_artifact, verify_feature_artifact
    from quant.research.m3.model import (
        build_lightgbm_training_spec,
        build_model_artifact,
        verify_model_artifact,
    )
    from quant.research.m3.orchestration import select_run_plan_nodes
    from quant.research.m3.predictions import build_prediction_artifact, verify_prediction_artifact
    from quant.research.m3.run_state import compute_work_key
    from quant.research.m3.targets import build_target_artifact, verify_target_artifact

    project_root = context.project_root
    config = request.config.config
    release = request.release
    toolchain = _require_toolchain(context.request.toolchain)
    fold_configs = tuple(item.config.config for item in context.request.folds)
    validate_successor_toolchain_binding(
        project_root=project_root, toolchain=toolchain, fold_configs=fold_configs,
    )
    ids = _runtime_ids(context)
    by_stage = _group_prior_refs_by_stage(prior_refs, wave="work")
    shared = _reconstruct_shared_upstream(
        by_stage=by_stage, project_root=project_root, release=release, config=config,
        ids=ids, dump_tool_path=toolchain.qlib_dump_tool_path, include_reconciliation=True,
    )
    if shared.folds is None or shared.fold_spec is None:
        _fail("SUCCESSOR_STAGE_INVALID")
    folds_artifact = shared.folds
    fold_spec = shared.fold_spec

    snapshot_ref = by_stage["snapshot"][0]
    provider_ref = by_stage["provider"][0]
    experiment_ref = by_stage["experiment-identity"][0]
    folds_ref = by_stage["folds"][0]
    snapshot_receipt = _verify_prior_receipt(snapshot_ref, project_root=project_root)
    snapshot_request_path = _receipt_output_path(
        snapshot_receipt, name=f"{snapshot_ref.scope_key}.json", project_root=project_root,
    )
    fold_upstream = FoldPlanUpstreamPaths(
        snapshot_request_path=snapshot_request_path,
        snapshot_receipt_path=project_root / snapshot_ref.relative_path,
        provider_dump_tool_path=toolchain.qlib_dump_tool_path,
        provider_receipt_path=project_root / provider_ref.relative_path,
        experiment_receipt_path=project_root / experiment_ref.relative_path,
    )
    folds_receipt_path = project_root / folds_ref.relative_path

    portfolio = config.section("portfolio")
    features_cfg = config.section("features")
    evaluation_cfg = config.section("evaluation")
    feature_version = _require_str(features_cfg["feature_version"])
    minimum_scorable_coverage = _require_finite_float(
        features_cfg["minimum_scorable_coverage"],
    )
    minimum_ic_symbols = _require_int(evaluation_cfg["minimum_ic_symbols"])
    if minimum_ic_symbols < 2:
        _fail("SUCCESSOR_CONFIG_INVALID")
    strategy = _require_strategy(portfolio["strategy"])
    strategy_version = _require_str(portfolio["strategy_version"])
    top_k = _require_positive_int(portfolio["top_k"])
    cash_buffer = _require_finite_float(portfolio["cash_buffer"])
    max_weight = _require_finite_float(portfolio["max_weight"])

    plan_builder = public_apis.run_plan_builders["work"]
    try:
        plan = _require_run_plan(
            plan_builder(
                config=config, experiment=shared.experiment, folds=folds_artifact,
                labels=list(shared.labels.values()),
                reconciliations=list(shared.reconciliations.values()),
                artifact_roots=context.artifact_roots,
            ),
        )
        nodes = select_run_plan_nodes(
            plan, expected_continuation="WORK",
            expected_node_ids=tuple(item.node_id for item in plan.nodes),
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    feature_states: dict[str, _WorkFoldHorizonState] = {}
    states: dict[tuple[str, Literal[5, 10]], _WorkFoldHorizonState] = {}
    refs: list["StageReceiptRef"] = []
    targets_by_key: dict[tuple[str, Literal[5, 10]], "VerifiedTargetArtifact"] = {}
    target_paths_by_key: dict[tuple[str, Literal[5, 10]], Path] = {}
    target_specs_by_key: dict[tuple[str, Literal[5, 10]], "TargetBuildSpec"] = {}

    for node in nodes:
        fold = node.fold
        if fold is None:
            _fail("SUCCESSOR_STAGE_INVALID")
        planned = next(
            (item for item in folds_artifact.manifest.folds if item.name == fold), None,
        )
        if planned is None:
            _fail("SUCCESSOR_STAGE_INVALID")

        if node.spec_name == "features":
            feature_spec = FeatureBuildSpec(
                experiment_key=shared.experiment.manifest.experiment_key,
                experiment_manifest_sha256=shared.experiment.manifest_sha256,
                fold=fold,
                planned_fold_sha256=planned.planned_fold_sha256,
                provider_key=shared.provider.manifest.provider_key,
                provider_manifest_sha256=shared.provider.manifest_sha256,
                provider_receipt_sha256=shared.provider.provider_receipt_sha256,
                feature_version=feature_version,
                expected_qlib_version="0.9.7",
                worker_protocol_version="m3-qlib-worker-v1",
            )
            feature_upstream = FeatureUpstreamPaths(
                fold_receipt_path=folds_receipt_path, fold_upstream_paths=fold_upstream,
            )

            def build_feature(output_root: Path, _spec: "FeatureBuildSpec" = feature_spec) -> object:
                return build_feature_artifact(
                    release=release, snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
                    provider=shared.provider, provider_spec=shared.provider_spec,
                    experiment=shared.experiment, experiment_spec=shared.experiment_spec,
                    folds=folds_artifact, fold_spec=fold_spec, config=config, spec=_spec,
                    upstream_paths=feature_upstream, artifact_roots=context.artifact_roots,
                    python_executable=toolchain.python_executable, output_root=output_root,
                    timeout_seconds=toolchain.timeout_seconds,
                )

            static, _manifest = _run_static_node_with_proof(
                runner=runner, node=node, plan=plan, resume=resume, build=build_feature,
            )
            try:
                feature = verify_feature_artifact(
                    root=static.final_root, receipt_path=static.receipt_path,
                    release=release, snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
                    provider=shared.provider, provider_spec=shared.provider_spec,
                    experiment=shared.experiment, experiment_spec=shared.experiment_spec,
                    folds=folds_artifact, fold_spec=fold_spec, config=config, spec=feature_spec,
                    upstream_paths=feature_upstream, artifact_roots=context.artifact_roots,
                )
            except Exception:
                _fail("SUCCESSOR_STAGE_INVALID")
            feature_states[fold] = _WorkFoldHorizonState(
                feature=feature, feature_spec=feature_spec, feature_receipt_path=static.receipt_path,
            )
            refs.append(_new_receipt_ref(
                receipt_path=static.receipt_path, receipt=static.receipt,
                project_root=project_root, node=node,
            ))
            continue

        horizon = _require_horizon(node.horizon)
        if horizon not in shared.labels:
            _fail("SUCCESSOR_STAGE_INVALID")
        if fold not in feature_states:
            _fail("SUCCESSOR_STAGE_INVALID")
        base = feature_states[fold]
        feature = base.feature
        feature_spec = base.feature_spec
        feature_receipt_path = base.feature_receipt_path
        feature_upstream = FeatureUpstreamPaths(
            fold_receipt_path=folds_receipt_path, fold_upstream_paths=fold_upstream,
        )
        label = shared.labels[horizon]
        label_spec = shared.label_specs[horizon]
        label_receipt_path = shared.label_receipt_paths[horizon]
        work_key = compute_work_key(
            experiment_key=shared.experiment.manifest.experiment_key, fold=fold, horizon=horizon,
        )
        state = states.setdefault(
            (fold, horizon),
            _WorkFoldHorizonState(
                feature=feature, feature_spec=feature_spec,
                feature_receipt_path=feature_receipt_path,
            ),
        )

        if node.spec_name == "alignment":
            alignment_spec = AlignmentBuildSpec(
                experiment_key=shared.experiment.manifest.experiment_key, work_key=work_key,
                fold=fold, planned_fold_sha256=planned.planned_fold_sha256,
                horizon_sessions=horizon, feature_manifest_sha256=feature.manifest_sha256,
                label_manifest_sha256=label.manifest_sha256,
            )
            alignment_upstream = AlignmentUpstreamPaths(
                feature_receipt_path=feature_receipt_path, feature_upstream_paths=feature_upstream,
                label_receipt_path=label_receipt_path,
            )

            def build_alignment(
                output_root: Path, _spec: "AlignmentBuildSpec" = alignment_spec,
            ) -> object:
                return build_alignment_artifact(
                    feature=feature, label=label, folds=folds_artifact, experiment=shared.experiment,
                    config=config, spec=_spec, output_root=output_root,
                )

            static, _manifest = _run_static_node_with_proof(
                runner=runner, node=node, plan=plan, resume=resume, build=build_alignment,
            )
            try:
                alignment = verify_alignment_artifact(
                    root=static.final_root, receipt_path=static.receipt_path,
                    release=release, snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
                    provider=shared.provider, provider_spec=shared.provider_spec,
                    experiment=shared.experiment, experiment_spec=shared.experiment_spec,
                    folds=folds_artifact, fold_spec=fold_spec, feature=feature,
                    feature_spec=feature_spec, label=label, label_spec=label_spec,
                    config=config, spec=alignment_spec, upstream_paths=alignment_upstream,
                    artifact_roots=context.artifact_roots,
                )
            except Exception:
                _fail("SUCCESSOR_STAGE_INVALID")
            state.alignment = alignment
            state.alignment_spec = alignment_spec
            state.alignment_receipt_path = static.receipt_path

        elif node.spec_name == "train":
            if (
                state.alignment is None
                or state.alignment_spec is None
                or state.alignment_receipt_path is None
            ):
                _fail("SUCCESSOR_STAGE_INVALID")
            alignment = state.alignment
            alignment_spec = state.alignment_spec
            alignment_receipt_path = state.alignment_receipt_path
            try:
                model_spec = build_lightgbm_training_spec(config)
            except Exception:
                _fail("SUCCESSOR_CONFIG_INVALID")
            model_upstream = ModelUpstreamPaths(
                alignment_receipt_path=alignment_receipt_path,
                alignment_upstream_paths=AlignmentUpstreamPaths(
                    feature_receipt_path=feature_receipt_path,
                    feature_upstream_paths=feature_upstream,
                    label_receipt_path=label_receipt_path,
                ),
            )

            def build_model(output_root: Path, _spec: "LightgbmTrainingSpec" = model_spec) -> object:
                return build_model_artifact(
                    release=release, snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
                    provider=shared.provider, provider_spec=shared.provider_spec,
                    experiment=shared.experiment, experiment_spec=shared.experiment_spec,
                    folds=folds_artifact, fold_spec=fold_spec, feature=feature,
                    feature_spec=feature_spec, label=label, label_spec=label_spec,
                    alignment=alignment, alignment_spec=alignment_spec,
                    config=config, spec=_spec, upstream_paths=model_upstream,
                    artifact_roots=context.artifact_roots, output_root=output_root,
                )

            static, _manifest = _run_static_node_with_proof(
                runner=runner, node=node, plan=plan, resume=resume, build=build_model,
            )
            try:
                model = verify_model_artifact(
                    root=static.final_root, receipt_path=static.receipt_path,
                    release=release, snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
                    provider=shared.provider, provider_spec=shared.provider_spec,
                    experiment=shared.experiment, experiment_spec=shared.experiment_spec,
                    folds=folds_artifact, fold_spec=fold_spec, feature=feature,
                    feature_spec=feature_spec, label=label, label_spec=label_spec,
                    alignment=alignment, alignment_spec=alignment_spec,
                    config=config, spec=model_spec, upstream_paths=model_upstream,
                    artifact_roots=context.artifact_roots,
                )
            except Exception:
                _fail("SUCCESSOR_STAGE_INVALID")
            state.model = model
            state.model_spec = model_spec
            state.model_receipt_path = static.receipt_path

        elif node.spec_name == "predictions":
            if (
                state.model is None or state.model_spec is None
                or state.alignment is None or state.alignment_spec is None
                or state.model_receipt_path is None
                or state.alignment_receipt_path is None
            ):
                _fail("SUCCESSOR_STAGE_INVALID")
            model = state.model
            model_spec = state.model_spec
            alignment = state.alignment
            alignment_spec = state.alignment_spec
            model_receipt_path = state.model_receipt_path
            alignment_receipt_path = state.alignment_receipt_path
            prediction_spec = PredictionBuildSpec(
                experiment_key=shared.experiment.manifest.experiment_key, work_key=work_key,
                fold=fold, horizon_sessions=horizon, model="lightgbm",
                model_version=model.manifest.model_version,
            )
            model_upstream = ModelUpstreamPaths(
                alignment_receipt_path=alignment_receipt_path,
                alignment_upstream_paths=AlignmentUpstreamPaths(
                    feature_receipt_path=feature_receipt_path,
                    feature_upstream_paths=feature_upstream,
                    label_receipt_path=label_receipt_path,
                ),
            )
            prediction_upstream = PredictionUpstreamPaths(
                model_receipt_path=model_receipt_path, model_upstream_paths=model_upstream,
                feature_receipt_path=feature_receipt_path, feature_upstream_paths=feature_upstream,
                fold_receipt_path=folds_receipt_path,
            )

            def build_prediction(
                output_root: Path, _spec: "PredictionBuildSpec" = prediction_spec,
            ) -> object:
                return build_prediction_artifact(
                    release=release, snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
                    provider=shared.provider, provider_spec=shared.provider_spec,
                    experiment=shared.experiment, experiment_spec=shared.experiment_spec,
                    folds=folds_artifact, fold_spec=fold_spec, feature=feature,
                    feature_spec=feature_spec, label=label, label_spec=label_spec,
                    alignment=alignment, alignment_spec=alignment_spec,
                    model=model, model_spec=model_spec, config=config, spec=_spec,
                    upstream_paths=prediction_upstream, artifact_roots=context.artifact_roots,
                    output_root=output_root,
                )

            static, _manifest = _run_static_node_with_proof(
                runner=runner, node=node, plan=plan, resume=resume, build=build_prediction,
            )
            try:
                prediction = verify_prediction_artifact(
                    root=static.final_root, receipt_path=static.receipt_path,
                    release=release, snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
                    provider=shared.provider, provider_spec=shared.provider_spec,
                    experiment=shared.experiment, experiment_spec=shared.experiment_spec,
                    folds=folds_artifact, fold_spec=fold_spec, feature=feature,
                    feature_spec=feature_spec, label=label, label_spec=label_spec,
                    alignment=alignment, alignment_spec=alignment_spec,
                    model=model, model_spec=model_spec, config=config,
                    spec=prediction_spec, upstream_paths=prediction_upstream,
                    artifact_roots=context.artifact_roots,
                )
            except Exception:
                _fail("SUCCESSOR_STAGE_INVALID")
            state.prediction = prediction
            state.prediction_spec = prediction_spec
            state.prediction_receipt_path = static.receipt_path

        elif node.spec_name == "evaluation":
            if (
                state.model is None or state.model_spec is None
                or state.alignment is None or state.alignment_spec is None
                or state.prediction is None or state.prediction_spec is None
                or state.model_receipt_path is None
                or state.alignment_receipt_path is None
                or state.prediction_receipt_path is None
            ):
                _fail("SUCCESSOR_STAGE_INVALID")
            model = state.model
            model_spec = state.model_spec
            alignment = state.alignment
            alignment_spec = state.alignment_spec
            prediction = state.prediction
            prediction_spec = state.prediction_spec
            model_receipt_path = state.model_receipt_path
            alignment_receipt_path = state.alignment_receipt_path
            prediction_receipt_path = state.prediction_receipt_path
            evaluation_spec = EvaluationSpec(
                experiment_key=shared.experiment.manifest.experiment_key, work_key=work_key,
                fold=fold, horizon_sessions=horizon,
                minimum_ic_symbols=minimum_ic_symbols,
            )
            model_upstream = ModelUpstreamPaths(
                alignment_receipt_path=alignment_receipt_path,
                alignment_upstream_paths=AlignmentUpstreamPaths(
                    feature_receipt_path=feature_receipt_path,
                    feature_upstream_paths=feature_upstream,
                    label_receipt_path=label_receipt_path,
                ),
            )
            prediction_upstream = PredictionUpstreamPaths(
                model_receipt_path=model_receipt_path, model_upstream_paths=model_upstream,
                feature_receipt_path=feature_receipt_path, feature_upstream_paths=feature_upstream,
                fold_receipt_path=folds_receipt_path,
            )
            evaluation_upstream = EvaluationUpstreamPaths(
                prediction_receipt_path=prediction_receipt_path,
                prediction_upstream_paths=prediction_upstream,
                label_receipt_path=label_receipt_path, feature_receipt_path=feature_receipt_path,
                fold_receipt_path=folds_receipt_path,
            )

            def build_evaluation(
                output_root: Path, _spec: "EvaluationSpec" = evaluation_spec,
            ) -> object:
                return build_evaluation_artifact(
                    release=release, snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
                    provider=shared.provider, provider_spec=shared.provider_spec,
                    experiment=shared.experiment, experiment_spec=shared.experiment_spec,
                    folds=folds_artifact, fold_spec=fold_spec, feature=feature,
                    feature_spec=feature_spec, label=label, label_spec=label_spec,
                    alignment=alignment, alignment_spec=alignment_spec,
                    model=model, model_spec=model_spec,
                    prediction=prediction, prediction_spec=prediction_spec,
                    config=config, spec=_spec, upstream_paths=evaluation_upstream,
                    artifact_roots=context.artifact_roots, output_root=output_root,
                )

            static, _manifest = _run_static_node_with_proof(
                runner=runner, node=node, plan=plan, resume=resume, build=build_evaluation,
            )
            try:
                verify_evaluation_artifact(
                    root=static.final_root, receipt_path=static.receipt_path,
                    release=release, snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
                    provider=shared.provider, provider_spec=shared.provider_spec,
                    experiment=shared.experiment, experiment_spec=shared.experiment_spec,
                    folds=folds_artifact, fold_spec=fold_spec, feature=feature,
                    feature_spec=feature_spec, label=label, label_spec=label_spec,
                    alignment=alignment, alignment_spec=alignment_spec,
                    model=model, model_spec=model_spec,
                    prediction=prediction, prediction_spec=prediction_spec,
                    config=config, spec=evaluation_spec, upstream_paths=evaluation_upstream,
                    artifact_roots=context.artifact_roots,
                )
            except Exception:
                _fail("SUCCESSOR_STAGE_INVALID")

        elif node.spec_name == "targets":
            if (
                state.model is None or state.model_spec is None
                or state.alignment is None or state.alignment_spec is None
                or state.prediction is None or state.prediction_spec is None
                or state.model_receipt_path is None
                or state.alignment_receipt_path is None
                or state.prediction_receipt_path is None
            ):
                _fail("SUCCESSOR_STAGE_INVALID")
            model = state.model
            model_spec = state.model_spec
            alignment = state.alignment
            alignment_spec = state.alignment_spec
            prediction = state.prediction
            prediction_spec = state.prediction_spec
            model_receipt_path = state.model_receipt_path
            alignment_receipt_path = state.alignment_receipt_path
            prediction_receipt_path = state.prediction_receipt_path
            target_spec = TargetBuildSpec(
                experiment_key=shared.experiment.manifest.experiment_key, work_key=work_key,
                fold=fold, horizon_sessions=horizon, strategy=strategy,
                strategy_version=strategy_version, top_k=top_k,
                cash_buffer=cash_buffer, max_weight=max_weight,
                minimum_scorable_coverage=minimum_scorable_coverage,
            )
            model_upstream = ModelUpstreamPaths(
                alignment_receipt_path=alignment_receipt_path,
                alignment_upstream_paths=AlignmentUpstreamPaths(
                    feature_receipt_path=feature_receipt_path,
                    feature_upstream_paths=feature_upstream,
                    label_receipt_path=label_receipt_path,
                ),
            )
            prediction_upstream = PredictionUpstreamPaths(
                model_receipt_path=model_receipt_path, model_upstream_paths=model_upstream,
                feature_receipt_path=feature_receipt_path, feature_upstream_paths=feature_upstream,
                fold_receipt_path=folds_receipt_path,
            )
            target_upstream = TargetUpstreamPaths(
                feature_receipt_path=feature_receipt_path,
                prediction_receipt_path=prediction_receipt_path,
                prediction_upstream_paths=prediction_upstream,
                fold_receipt_path=folds_receipt_path,
                experiment_receipt_path=project_root / experiment_ref.relative_path,
            )

            def build_target(output_root: Path, _spec: "TargetBuildSpec" = target_spec) -> object:
                return build_target_artifact(
                    release=release, snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
                    provider=shared.provider, provider_spec=shared.provider_spec,
                    experiment=shared.experiment, experiment_spec=shared.experiment_spec,
                    folds=folds_artifact, fold_spec=fold_spec, feature=feature,
                    feature_spec=feature_spec, label=label, label_spec=label_spec,
                    alignment=alignment, alignment_spec=alignment_spec,
                    model=model, model_spec=model_spec,
                    prediction=prediction, prediction_spec=prediction_spec,
                    config=config, spec=_spec, upstream_paths=target_upstream,
                    artifact_roots=context.artifact_roots, output_root=output_root,
                )

            static, _manifest = _run_static_node_with_proof(
                runner=runner, node=node, plan=plan, resume=resume, build=build_target,
            )
            try:
                target = verify_target_artifact(
                    root=static.final_root, receipt_path=static.receipt_path,
                    release=release, snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
                    provider=shared.provider, provider_spec=shared.provider_spec,
                    experiment=shared.experiment, experiment_spec=shared.experiment_spec,
                    folds=folds_artifact, fold_spec=fold_spec, feature=feature,
                    feature_spec=feature_spec, label=label, label_spec=label_spec,
                    alignment=alignment, alignment_spec=alignment_spec,
                    model=model, model_spec=model_spec,
                    prediction=prediction, prediction_spec=prediction_spec,
                    config=config, spec=target_spec, upstream_paths=target_upstream,
                    artifact_roots=context.artifact_roots,
                )
            except Exception:
                _fail("SUCCESSOR_STAGE_INVALID")
            targets_by_key[(fold, horizon)] = target
            target_paths_by_key[(fold, horizon)] = static.receipt_path
            target_specs_by_key[(fold, horizon)] = target_spec

        elif node.spec_name == "backtest_plan":
            key = (fold, horizon)
            if (
                key not in targets_by_key
                or state.model is None or state.model_spec is None
                or state.alignment is None or state.alignment_spec is None
                or state.prediction is None or state.prediction_spec is None
                or state.model_receipt_path is None
                or state.alignment_receipt_path is None
                or state.prediction_receipt_path is None
            ):
                _fail("SUCCESSOR_STAGE_INVALID")
            model = state.model
            model_spec = state.model_spec
            alignment = state.alignment
            alignment_spec = state.alignment_spec
            prediction = state.prediction
            prediction_spec = state.prediction_spec
            model_receipt_path = state.model_receipt_path
            alignment_receipt_path = state.alignment_receipt_path
            prediction_receipt_path = state.prediction_receipt_path
            model_upstream = ModelUpstreamPaths(
                alignment_receipt_path=alignment_receipt_path,
                alignment_upstream_paths=AlignmentUpstreamPaths(
                    feature_receipt_path=feature_receipt_path,
                    feature_upstream_paths=feature_upstream,
                    label_receipt_path=label_receipt_path,
                ),
            )
            prediction_upstream = PredictionUpstreamPaths(
                model_receipt_path=model_receipt_path, model_upstream_paths=model_upstream,
                feature_receipt_path=feature_receipt_path, feature_upstream_paths=feature_upstream,
                fold_receipt_path=folds_receipt_path,
            )
            target_upstream = TargetUpstreamPaths(
                feature_receipt_path=feature_receipt_path,
                prediction_receipt_path=prediction_receipt_path,
                prediction_upstream_paths=prediction_upstream,
                fold_receipt_path=folds_receipt_path,
                experiment_receipt_path=project_root / experiment_ref.relative_path,
            )
            fresh_context = BacktestPlanFreshVerificationContext(
                snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
                provider=shared.provider, provider_spec=shared.provider_spec,
                experiment_spec=shared.experiment_spec, fold_spec=fold_spec,
                feature=feature, feature_spec=feature_spec, label=label, label_spec=label_spec,
                alignment=alignment, alignment_spec=alignment_spec,
                model=model, model_spec=model_spec,
                prediction=prediction, prediction_spec=prediction_spec,
                target_spec=target_specs_by_key[key],
                target_upstream_paths=target_upstream,
                target_receipt_path=target_paths_by_key[key],
            )

            def build_backtest_plan(
                output_root: Path, _fresh: "BacktestPlanFreshVerificationContext" = fresh_context,
            ) -> object:
                return build_backtest_plan_artifact(
                    target=targets_by_key[key], release=release, folds=folds_artifact,
                    experiment=shared.experiment, config=config, fresh_context=_fresh,
                    artifact_roots={"PROJECT": project_root},
                    output_root=output_root,
                )

            static, _manifest = _run_static_node_with_proof(
                runner=runner, node=node, plan=plan, resume=resume, build=build_backtest_plan,
            )
            try:
                verify_backtest_plan_artifact(
                    root=static.final_root, receipt_path=static.receipt_path,
                    target=targets_by_key[key], release=release, folds=folds_artifact,
                    experiment=shared.experiment, config=config, fresh_context=fresh_context,
                    artifact_roots=context.artifact_roots,
                )
            except Exception:
                _fail("SUCCESSOR_STAGE_INVALID")

        else:
            _fail("SUCCESSOR_STAGE_INVALID")

        refs.append(_new_receipt_ref(
            receipt_path=static.receipt_path, receipt=static.receipt,
            project_root=project_root, node=node,
        ))

    return tuple(sorted(refs, key=lambda item: item.node_id))


def _run_label_reconciliation_wave(
    *, request: "SuccessorFoldRequest", context: "SuccessorStageContext",
    runner: "StageRunner", public_apis: "SuccessorPublicApiBundle",
    prior_refs: tuple["StageReceiptRef", ...], resume: bool,
) -> tuple["StageReceiptRef", ...]:
    from quant.research.m3.contracts import LabelReconciliationSpec
    from quant.research.m3.labels import reconcile_labels_with_qlib, verify_label_reconciliation_artifact
    from quant.research.m3.orchestration import select_run_plan_nodes
    from quant.research.m3.run_state import compute_label_reconciliation_key

    project_root = context.project_root
    config = request.config.config
    toolchain = _require_toolchain(context.request.toolchain)
    fold_configs = tuple(item.config.config for item in context.request.folds)
    validate_successor_toolchain_binding(
        project_root=project_root, toolchain=toolchain, fold_configs=fold_configs,
    )
    ids = _runtime_ids(context)
    by_stage = _group_prior_refs_by_stage(prior_refs, wave="label-reconciliation")
    shared = _reconstruct_shared_upstream(
        by_stage=by_stage, project_root=project_root, release=request.release,
        config=config, ids=ids, dump_tool_path=toolchain.qlib_dump_tool_path,
        include_reconciliation=False,
    )

    atol = config.section("label_reconciliation")
    qlib_expression_atol = _require_finite_float(atol["qlib_expression_atol"])
    benchmark_return_atol = _require_finite_float(atol["benchmark_return_atol"])
    label_return_atol = _require_finite_float(atol["label_return_atol"])
    specs: dict[Literal[5, 10], "LabelReconciliationSpec"] = {}
    for raw_horizon, label in shared.labels.items():
        horizon = _require_horizon(raw_horizon)
        reconciliation_key = compute_label_reconciliation_key(
            experiment_key=shared.experiment.manifest.experiment_key,
            horizon=horizon,
            provider_validation_receipt_sha256=(
                shared.provider_validation.validation_receipt_sha256
            ),
            label_manifest_sha256=label.manifest_sha256,
            label_reconciliation_config_sha256=config.label_reconciliation_config_sha256,
            dependency_fingerprint_sha256=ids.dependency_fingerprint_sha256,
            code_version=ids.code_version,
        )
        specs[horizon] = LabelReconciliationSpec(
            reconciliation_key=reconciliation_key,
            experiment_key=shared.experiment.manifest.experiment_key,
            horizon_sessions=horizon,
            provider_validation_receipt_sha256=(
                shared.provider_validation.validation_receipt_sha256
            ),
            label_manifest_sha256=label.manifest_sha256,
            label_reconciliation_config_sha256=config.label_reconciliation_config_sha256,
            dependency_fingerprint_sha256=ids.dependency_fingerprint_sha256,
            code_version=ids.code_version,
            worker_protocol_version="m3-qlib-worker-v1",
            qlib_version="0.9.7",
            qlib_expression_atol=qlib_expression_atol,
            benchmark_return_atol=benchmark_return_atol,
            label_return_atol=label_return_atol,
        )

    plan_builder = public_apis.run_plan_builders["label-reconciliation"]
    ordered_horizons = tuple(sorted(specs))
    try:
        plan = _require_run_plan(
            plan_builder(
                config=config, release=request.release, snapshot=shared.snapshot,
                provider=shared.provider, provider_validation=shared.provider_validation,
                experiment=shared.experiment,
                labels=[shared.labels[horizon] for horizon in ordered_horizons],
                specs=[specs[horizon] for horizon in ordered_horizons],
                artifact_roots=context.artifact_roots,
            ),
        )
        nodes = select_run_plan_nodes(
            plan, expected_continuation="EXPERIMENT",
            expected_node_ids=tuple(item.node_id for item in plan.nodes),
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    from quant.research.m3.contracts import LabelReconciliationReceiptPaths

    snapshot_ref = by_stage["snapshot"][0]
    provider_ref = by_stage["provider"][0]
    validation_ref = by_stage["provider-validation"][0]
    experiment_ref = by_stage["experiment-identity"][0]

    refs: list["StageReceiptRef"] = []
    for node in nodes:
        horizon = _require_horizon(node.horizon)
        if horizon not in specs:
            _fail("SUCCESSOR_STAGE_INVALID")
        spec = specs[horizon]
        receipt_paths = LabelReconciliationReceiptPaths(
            snapshot_receipt_path=project_root / snapshot_ref.relative_path,
            provider_receipt_path=project_root / provider_ref.relative_path,
            provider_validation_receipt_path=project_root / validation_ref.relative_path,
            experiment_receipt_path=project_root / experiment_ref.relative_path,
            label_receipt_path=shared.label_receipt_paths[horizon],
        )

        def build(
            output_root: Path, _spec: "LabelReconciliationSpec" = spec,
            _paths: "LabelReconciliationReceiptPaths" = receipt_paths,
            _horizon: Literal[5, 10] = horizon,
        ) -> object:
            return reconcile_labels_with_qlib(
                release=request.release, snapshot=shared.snapshot, experiment=shared.experiment,
                provider=shared.provider, provider_validation=shared.provider_validation,
                labels=shared.labels[_horizon], config=config, spec=_spec,
                receipt_paths=_paths, artifact_roots=context.artifact_roots,
                python_executable=toolchain.python_executable, output_root=output_root,
                timeout_seconds=toolchain.timeout_seconds,
            )

        static, _manifest = _run_static_node_with_proof(
            runner=runner, node=node, plan=plan, resume=resume, build=build,
        )
        try:
            verify_label_reconciliation_artifact(
                reconciliation_root=static.final_root,
                reconciliation_receipt_path=static.receipt_path,
                release=request.release, snapshot=shared.snapshot, experiment=shared.experiment,
                provider=shared.provider, provider_validation=shared.provider_validation,
                labels=shared.labels[horizon], config=config, spec=spec,
                receipt_paths=receipt_paths, artifact_roots=context.artifact_roots,
            )
        except Exception:
            _fail("SUCCESSOR_STAGE_INVALID")

        refs.append(_new_receipt_ref(
            receipt_path=static.receipt_path, receipt=static.receipt,
            project_root=project_root, node=node,
        ))

    return tuple(sorted(refs, key=lambda item: item.node_id))


_WAVE_HANDLERS.update(
    {
        "snapshot": _run_snapshot_wave,
        "provider": _run_provider_wave,
        "provider-validation": _run_provider_validation_wave,
        "experiment-identity": _run_experiment_identity_wave,
        "experiment-artifacts": _run_experiment_artifacts_wave,
        "label-reconciliation": _run_label_reconciliation_wave,
        "work": _run_work_wave,
    }
)


# --------------------------------------------------------------------------
# Formal summary gate
# --------------------------------------------------------------------------


def _find_stage_refs(
    receipts: tuple["StageReceiptRef", ...], *, stage: str,
) -> tuple["StageReceiptRef", ...]:
    return tuple(item for item in receipts if item.stage == stage)


@dataclass(frozen=True)
class _SummaryNodeRef:
    """The minimal node-shaped identity ``_new_receipt_ref`` needs."""

    node_id: str
    fold: str | None
    horizon: int | None


_SUMMARY_SHARED_STAGES: dict[str, int] = {
    "snapshot": 1, "provider": 1, "provider-validation": 1,
    "experiment-identity": 1, "folds": 1, "labels": 2,
}


def _extract_summary_shared_stages(
    all_receipts: tuple["StageReceiptRef", ...],
    *,
    canonical_horizons: tuple[Literal[5, 10], ...],
) -> dict[str, tuple["StageReceiptRef", ...]]:
    """Pull the fold-shared upstream refs out of a merged receipt set.

    Unlike ``_group_prior_refs_by_stage`` (which enforces an exact stage-set
    match for a wave's *own* prior receipts), the merged receipts across both
    ``FoldExecution`` lanes also contain fold-specific work-wave outputs
    (features/alignment/train/predictions/evaluation/backtest_plan); this
    only requires the shared subset to be present with the expected count.
    Labels must still prove unique canonical horizon closure before use.
    """

    by_stage: dict[str, list["StageReceiptRef"]] = {}
    for ref in all_receipts:
        by_stage.setdefault(ref.stage, []).append(ref)
    for stage, count in _SUMMARY_SHARED_STAGES.items():
        if stage not in by_stage or len(by_stage[stage]) != count:
            _fail("SUCCESSOR_GATE_FAILED")
    # Prove label horizon closure before any downstream dict reconstruction.
    try:
        _unique_horizon_ref_map(
            tuple(by_stage["labels"]), canonical_horizons=canonical_horizons,
        )
    except Exception:
        _fail("SUCCESSOR_GATE_FAILED")
    return {stage: tuple(items) for stage, items in by_stage.items()}


def _reconstruct_work_chain_for_evaluation(
    *,
    shared: _SharedUpstream,
    fold: str,
    horizon: Literal[5, 10],
    project_root: Path,
    config: "LoadedM3Config",
    receipts: tuple["StageReceiptRef", ...],
    dump_tool_path: Path,
) -> tuple["VerifiedEvaluationArtifact", "EvaluationFreshVerificationContext"]:
    """Reconstruct one (fold, horizon) evaluation via fresh verify only."""

    from quant.research.m3.alignment import verify_alignment_artifact
    from quant.research.m3.contracts import (
        AlignmentBuildSpec,
        AlignmentUpstreamPaths,
        EvaluationSpec,
        EvaluationUpstreamPaths,
        FeatureBuildSpec,
        FeatureUpstreamPaths,
        FoldPlanUpstreamPaths,
        ModelUpstreamPaths,
        PredictionBuildSpec,
        PredictionUpstreamPaths,
    )
    from quant.research.m3.evaluate import EvaluationFreshVerificationContext, verify_evaluation_artifact
    from quant.research.m3.features import verify_feature_artifact
    from quant.research.m3.model import build_lightgbm_training_spec, verify_model_artifact
    from quant.research.m3.predictions import verify_prediction_artifact

    if shared.folds is None or shared.fold_spec is None or horizon not in shared.labels:
        _fail("SUCCESSOR_STAGE_INVALID")
    folds_artifact = shared.folds
    fold_spec = shared.fold_spec
    planned = next(
        (item for item in folds_artifact.manifest.folds if item.name == fold), None,
    )
    if planned is None:
        _fail("SUCCESSOR_STAGE_INVALID")

    def one(stage: str) -> "StageReceiptRef":
        matches = tuple(
            item for item in receipts
            if item.stage == stage and item.fold == fold and item.horizon in (horizon, None)
        )
        if len(matches) != 1:
            _fail("SUCCESSOR_STAGE_INVALID")
        return matches[0]

    snapshot_ref = _find_stage_refs(receipts, stage="snapshot")
    provider_ref = _find_stage_refs(receipts, stage="provider")
    experiment_ref = _find_stage_refs(receipts, stage="experiment-identity")
    folds_ref = _find_stage_refs(receipts, stage="folds")
    if not (snapshot_ref and provider_ref and experiment_ref and folds_ref):
        _fail("SUCCESSOR_STAGE_INVALID")
    snapshot_receipt = _verify_prior_receipt(snapshot_ref[0], project_root=project_root)
    snapshot_request_path = _receipt_output_path(
        snapshot_receipt, name=f"{snapshot_ref[0].scope_key}.json", project_root=project_root,
    )
    fold_upstream = FoldPlanUpstreamPaths(
        snapshot_request_path=snapshot_request_path,
        snapshot_receipt_path=project_root / snapshot_ref[0].relative_path,
        provider_dump_tool_path=dump_tool_path,
        provider_receipt_path=project_root / provider_ref[0].relative_path,
        experiment_receipt_path=project_root / experiment_ref[0].relative_path,
    )
    folds_receipt_path = project_root / folds_ref[0].relative_path

    feature_ref = one("features")
    feature_receipt = _verify_prior_receipt(feature_ref, project_root=project_root)
    feature_root = _receipt_output_path(
        feature_receipt, name="manifest.json", project_root=project_root
    ).parent
    features_cfg = config.section("features")
    feature_spec = FeatureBuildSpec(
        experiment_key=shared.experiment.manifest.experiment_key,
        experiment_manifest_sha256=shared.experiment.manifest_sha256,
        fold=fold, planned_fold_sha256=planned.planned_fold_sha256,
        provider_key=shared.provider.manifest.provider_key,
        provider_manifest_sha256=shared.provider.manifest_sha256,
        provider_receipt_sha256=shared.provider.provider_receipt_sha256,
        feature_version=_require_str(features_cfg["feature_version"]),
        expected_qlib_version="0.9.7",
        worker_protocol_version="m3-qlib-worker-v1",
    )
    feature_upstream = FeatureUpstreamPaths(
        fold_receipt_path=folds_receipt_path, fold_upstream_paths=fold_upstream,
    )
    try:
        feature = verify_feature_artifact(
            root=feature_root, receipt_path=project_root / feature_ref.relative_path,
            release=shared.release, snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
            provider=shared.provider, provider_spec=shared.provider_spec,
            experiment=shared.experiment, experiment_spec=shared.experiment_spec,
            folds=folds_artifact, fold_spec=fold_spec, config=config, spec=feature_spec,
            upstream_paths=feature_upstream, artifact_roots={"PROJECT": project_root},
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    label = shared.labels[horizon]
    label_spec = shared.label_specs[horizon]
    label_receipt_path = shared.label_receipt_paths[horizon]

    work_key_ref = one("alignment")
    alignment_receipt = _verify_prior_receipt(work_key_ref, project_root=project_root)
    alignment_root = _receipt_output_path(
        alignment_receipt, name="manifest.json", project_root=project_root
    ).parent
    work_key = work_key_ref.scope_key
    alignment_spec = AlignmentBuildSpec(
        experiment_key=shared.experiment.manifest.experiment_key, work_key=work_key,
        fold=fold, planned_fold_sha256=planned.planned_fold_sha256, horizon_sessions=horizon,
        feature_manifest_sha256=feature.manifest_sha256, label_manifest_sha256=label.manifest_sha256,
    )
    alignment_upstream = AlignmentUpstreamPaths(
        feature_receipt_path=project_root / feature_ref.relative_path,
        feature_upstream_paths=feature_upstream, label_receipt_path=label_receipt_path,
    )
    try:
        alignment = verify_alignment_artifact(
            root=alignment_root, receipt_path=project_root / work_key_ref.relative_path,
            release=shared.release, snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
            provider=shared.provider, provider_spec=shared.provider_spec,
            experiment=shared.experiment, experiment_spec=shared.experiment_spec,
            folds=folds_artifact, fold_spec=fold_spec, feature=feature,
            feature_spec=feature_spec, label=label, label_spec=label_spec, config=config,
            spec=alignment_spec, upstream_paths=alignment_upstream,
            artifact_roots={"PROJECT": project_root},
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    train_ref = one("train")
    model_receipt = _verify_prior_receipt(train_ref, project_root=project_root)
    model_root = _receipt_output_path(
        model_receipt, name="manifest.json", project_root=project_root
    ).parent
    try:
        model_spec = build_lightgbm_training_spec(config)
    except Exception:
        _fail("SUCCESSOR_CONFIG_INVALID")
    model_upstream = ModelUpstreamPaths(
        alignment_receipt_path=project_root / work_key_ref.relative_path,
        alignment_upstream_paths=alignment_upstream,
    )
    try:
        model = verify_model_artifact(
            root=model_root, receipt_path=project_root / train_ref.relative_path,
            release=shared.release, snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
            provider=shared.provider, provider_spec=shared.provider_spec,
            experiment=shared.experiment, experiment_spec=shared.experiment_spec,
            folds=folds_artifact, fold_spec=fold_spec, feature=feature,
            feature_spec=feature_spec, label=label, label_spec=label_spec,
            alignment=alignment, alignment_spec=alignment_spec, config=config, spec=model_spec,
            upstream_paths=model_upstream, artifact_roots={"PROJECT": project_root},
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    prediction_ref = one("predictions")
    prediction_receipt = _verify_prior_receipt(prediction_ref, project_root=project_root)
    prediction_root = _receipt_output_path(
        prediction_receipt, name="manifest.json", project_root=project_root
    ).parent
    prediction_spec = PredictionBuildSpec(
        experiment_key=shared.experiment.manifest.experiment_key, work_key=work_key,
        fold=fold, horizon_sessions=horizon, model="lightgbm",
        model_version=model.manifest.model_version,
    )
    prediction_upstream = PredictionUpstreamPaths(
        model_receipt_path=project_root / train_ref.relative_path,
        model_upstream_paths=model_upstream,
        feature_receipt_path=project_root / feature_ref.relative_path,
        feature_upstream_paths=feature_upstream, fold_receipt_path=folds_receipt_path,
    )
    try:
        prediction = verify_prediction_artifact(
            root=prediction_root, receipt_path=project_root / prediction_ref.relative_path,
            release=shared.release, snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
            provider=shared.provider, provider_spec=shared.provider_spec,
            experiment=shared.experiment, experiment_spec=shared.experiment_spec,
            folds=folds_artifact, fold_spec=fold_spec, feature=feature,
            feature_spec=feature_spec, label=label, label_spec=label_spec,
            alignment=alignment, alignment_spec=alignment_spec, model=model,
            model_spec=model_spec, config=config, spec=prediction_spec,
            upstream_paths=prediction_upstream, artifact_roots={"PROJECT": project_root},
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    evaluation_ref = one("evaluation")
    evaluation_receipt = _verify_prior_receipt(evaluation_ref, project_root=project_root)
    evaluation_root = _receipt_output_path(
        evaluation_receipt, name="manifest.json", project_root=project_root
    ).parent
    evaluation_cfg = config.section("evaluation")
    minimum_ic_symbols = _require_int(evaluation_cfg["minimum_ic_symbols"])
    if minimum_ic_symbols < 2:
        _fail("SUCCESSOR_CONFIG_INVALID")
    evaluation_spec = EvaluationSpec(
        experiment_key=shared.experiment.manifest.experiment_key, work_key=work_key,
        fold=fold, horizon_sessions=horizon,
        minimum_ic_symbols=minimum_ic_symbols,
    )
    evaluation_upstream = EvaluationUpstreamPaths(
        prediction_receipt_path=project_root / prediction_ref.relative_path,
        prediction_upstream_paths=prediction_upstream,
        label_receipt_path=label_receipt_path,
        feature_receipt_path=project_root / feature_ref.relative_path,
        fold_receipt_path=folds_receipt_path,
    )
    try:
        evaluation = verify_evaluation_artifact(
            root=evaluation_root, receipt_path=project_root / evaluation_ref.relative_path,
            release=shared.release, snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
            provider=shared.provider, provider_spec=shared.provider_spec,
            experiment=shared.experiment, experiment_spec=shared.experiment_spec,
            folds=folds_artifact, fold_spec=fold_spec, feature=feature,
            feature_spec=feature_spec, label=label, label_spec=label_spec,
            alignment=alignment, alignment_spec=alignment_spec, model=model,
            model_spec=model_spec, prediction=prediction, prediction_spec=prediction_spec,
            config=config, spec=evaluation_spec, upstream_paths=evaluation_upstream,
            artifact_roots={"PROJECT": project_root},
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")

    context = EvaluationFreshVerificationContext(
        release=shared.release, snapshot=shared.snapshot, snapshot_spec=shared.snapshot_spec,
        provider=shared.provider, provider_spec=shared.provider_spec,
        experiment=shared.experiment, experiment_spec=shared.experiment_spec,
        folds=folds_artifact, fold_spec=fold_spec, feature=feature,
        feature_spec=feature_spec, label=label, label_spec=label_spec,
        alignment=alignment, alignment_spec=alignment_spec, model=model, model_spec=model_spec,
        prediction=prediction, prediction_spec=prediction_spec,
        evaluation_spec=evaluation_spec, evaluation_upstream_paths=evaluation_upstream,
    )
    return evaluation, context


# --------------------------------------------------------------------------
# Package-owned formal fresh-rehydrate (explicit prior_refs only)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SuccessorFormalBacktestInputs:
    """Typed formal-backtest closure rebuilt from explicit prior receipt refs."""

    stage_root: Path
    artifact_roots: Mapping[str, Path]
    config: "LoadedM3Config"
    release: "VerifiedG1Release"
    experiment: "VerifiedExperimentIdentity"
    target: "VerifiedTargetArtifact"
    plan: "VerifiedBacktestPlanArtifact"
    fresh_context: "BacktestArtifactFreshVerificationContext"
    work_key: str
    fold: str
    horizon: Literal[5, 10]
    evaluation: "VerifiedEvaluationArtifact"
    evaluation_context: "EvaluationFreshVerificationContext"
    evaluation_receipt_path: Path


@dataclass(frozen=True)
class SuccessorFormalTrackingInputs:
    """Typed formal-tracking closure rebuilt from explicit prior receipt refs."""

    stage_root: Path
    artifact_roots: Mapping[str, Path]
    config: "LoadedM3Config"
    evaluation: "VerifiedEvaluationArtifact"
    backtest: "VerifiedBacktestArtifact"
    fresh_context: "FormalTrackingFreshVerificationContext"
    work_key: str
    fold: str
    horizon: Literal[5, 10]
    tracking_uri: str


def _require_sorted_unique_prior_refs(
    prior_refs: tuple["StageReceiptRef", ...],
) -> tuple["StageReceiptRef", ...]:
    from quant.research.m3.successor_runtime import StageReceiptRef

    if type(prior_refs) is not tuple or any(
        type(item) is not StageReceiptRef for item in prior_refs
    ):
        _fail("SUCCESSOR_STAGE_INVALID")
    node_ids = tuple(item.node_id for item in prior_refs)
    if node_ids != tuple(sorted(node_ids)) or len(set(node_ids)) != len(node_ids):
        _fail("SUCCESSOR_STAGE_INVALID")
    return prior_refs


def _one_fold_horizon_ref(
    prior_refs: tuple["StageReceiptRef", ...],
    *,
    stage: str,
    fold: str,
    horizon: int | None,
) -> "StageReceiptRef":
    matches = tuple(
        item
        for item in prior_refs
        if item.stage == stage and item.fold == fold and item.horizon == horizon
    )
    if len(matches) != 1:
        _fail("SUCCESSOR_STAGE_INVALID")
    return matches[0]


def _shared_by_stage_from_prior_refs(
    prior_refs: tuple["StageReceiptRef", ...],
    *,
    canonical_horizons: tuple[Literal[5, 10], ...],
) -> dict[str, tuple["StageReceiptRef", ...]]:
    try:
        return _extract_summary_shared_stages(
            prior_refs, canonical_horizons=canonical_horizons,
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")


def rehydrate_successor_formal_backtest_inputs(
    *,
    prior_refs: tuple["StageReceiptRef", ...],
    request: "SuccessorFoldRequest",
    context: "SuccessorStageContext",
    horizon: int,
) -> SuccessorFormalBacktestInputs:
    """Fresh-verify typed backtest inputs from explicit prior receipt paths only."""

    from types import MappingProxyType

    from quant.backtest.a_share_execution import AShareMarketFactsFreshVerificationContext
    from quant.backtest.a_share_plan import (
        BacktestPlanFreshVerificationContext,
        verify_backtest_plan_artifact,
    )
    from quant.backtest.a_share_reporting import (
        BacktestArtifactFreshVerificationContext,
        FormalBacktestArtifactUpstreamPaths,
    )
    from quant.research.m3.contracts import TargetBuildSpec, TargetUpstreamPaths
    from quant.research.m3.successor_runtime import (
        SuccessorFoldRequest,
        SuccessorStageContext,
        project_stage_root,
    )
    from quant.research.m3.targets import verify_target_artifact

    if type(context) is not SuccessorStageContext or type(request) is not SuccessorFoldRequest:
        _fail("SUCCESSOR_STAGE_INVALID")
    if context.fold not in (None, request.fold):
        _fail("SUCCESSOR_STAGE_INVALID")
    if request.fold not in {item.fold for item in context.request.folds}:
        _fail("SUCCESSOR_STAGE_INVALID")
    # Prefer the runtime-bound fold request object when present.
    bound = next(
        (item for item in context.request.folds if item.fold == request.fold),
        None,
    )
    if bound is None:
        _fail("SUCCESSOR_STAGE_INVALID")
    if (
        bound is not request
        and (
            bound.config.config.full_config_sha256 != request.config.config.full_config_sha256
            or bound.release.manifest_sha256 != request.release.manifest_sha256
        )
    ):
        _fail("SUCCESSOR_STAGE_INVALID")
    horizon_lit = _require_horizon(horizon)
    refs = _require_sorted_unique_prior_refs(prior_refs)
    project_root = context.project_root
    config = request.config.config
    release = request.release
    fold = request.fold
    toolchain = _require_toolchain(context.request.toolchain)
    validate_successor_toolchain_binding(
        project_root=project_root,
        toolchain=toolchain,
        fold_configs=tuple(item.config.config for item in context.request.folds),
    )
    ids = _runtime_ids(context)
    horizons = _canonical_horizons_from_config(config)
    by_stage = _shared_by_stage_from_prior_refs(refs, canonical_horizons=horizons)
    shared = _reconstruct_shared_upstream(
        by_stage=by_stage,
        project_root=project_root,
        release=release,
        config=config,
        ids=ids,
        dump_tool_path=toolchain.qlib_dump_tool_path,
        include_reconciliation=False,
    )
    if shared.folds is None or shared.fold_spec is None:
        _fail("SUCCESSOR_STAGE_INVALID")
    folds_artifact = shared.folds
    fold_spec = shared.fold_spec
    evaluation, eval_context = _reconstruct_work_chain_for_evaluation(
        shared=shared,
        fold=fold,
        horizon=horizon_lit,
        project_root=project_root,
        config=config,
        receipts=refs,
        dump_tool_path=toolchain.qlib_dump_tool_path,
    )
    evaluation_ref = _one_fold_horizon_ref(
        refs, stage="evaluation", fold=fold, horizon=horizon_lit,
    )
    evaluation_receipt_path = project_root / evaluation_ref.relative_path
    feature_ref = _one_fold_horizon_ref(
        refs, stage="features", fold=fold, horizon=None,
    )
    prediction_ref = _one_fold_horizon_ref(
        refs, stage="predictions", fold=fold, horizon=horizon_lit,
    )
    target_ref = _one_fold_horizon_ref(
        refs, stage="targets", fold=fold, horizon=horizon_lit,
    )
    plan_ref = _one_fold_horizon_ref(
        refs, stage="backtest_plan", fold=fold, horizon=horizon_lit,
    )
    experiment_ref = _find_stage_refs(refs, stage="experiment-identity")
    folds_ref = _find_stage_refs(refs, stage="folds")
    if len(experiment_ref) != 1 or len(folds_ref) != 1:
        _fail("SUCCESSOR_STAGE_INVALID")
    work_key = target_ref.scope_key
    if (
        plan_ref.scope_key != work_key
        or evaluation_ref.scope_key != work_key
        or prediction_ref.scope_key != work_key
    ):
        _fail("SUCCESSOR_STAGE_INVALID")
    portfolio = config.section("portfolio")
    features_cfg = config.section("features")
    target_spec = TargetBuildSpec(
        experiment_key=shared.experiment.manifest.experiment_key,
        work_key=work_key,
        fold=fold,
        horizon_sessions=horizon_lit,
        strategy=_require_strategy(portfolio["strategy"]),
        strategy_version=_require_str(portfolio["strategy_version"]),
        top_k=_require_positive_int(portfolio["top_k"]),
        cash_buffer=_require_finite_float(portfolio["cash_buffer"]),
        max_weight=_require_finite_float(portfolio["max_weight"]),
        minimum_scorable_coverage=_require_finite_float(
            features_cfg["minimum_scorable_coverage"],
        ),
    )
    prediction_upstream = eval_context.evaluation_upstream_paths.prediction_upstream_paths
    target_upstream = TargetUpstreamPaths(
        feature_receipt_path=project_root / feature_ref.relative_path,
        prediction_receipt_path=project_root / prediction_ref.relative_path,
        prediction_upstream_paths=prediction_upstream,
        fold_receipt_path=project_root / folds_ref[0].relative_path,
        experiment_receipt_path=project_root / experiment_ref[0].relative_path,
    )
    target_receipt = _verify_prior_receipt(target_ref, project_root=project_root)
    target_root = _receipt_output_path(
        target_receipt, name="target_manifest.json", project_root=project_root,
    ).parent
    artifact_roots = MappingProxyType({"PROJECT": project_root})
    try:
        target = verify_target_artifact(
            root=target_root,
            receipt_path=project_root / target_ref.relative_path,
            release=release,
            snapshot=shared.snapshot,
            snapshot_spec=shared.snapshot_spec,
            provider=shared.provider,
            provider_spec=shared.provider_spec,
            experiment=shared.experiment,
            experiment_spec=shared.experiment_spec,
            folds=folds_artifact,
            fold_spec=fold_spec,
            feature=eval_context.feature,
            feature_spec=eval_context.feature_spec,
            label=eval_context.label,
            label_spec=eval_context.label_spec,
            alignment=eval_context.alignment,
            alignment_spec=eval_context.alignment_spec,
            model=eval_context.model,
            model_spec=eval_context.model_spec,
            prediction=eval_context.prediction,
            prediction_spec=eval_context.prediction_spec,
            config=config,
            spec=target_spec,
            upstream_paths=target_upstream,
            artifact_roots=artifact_roots,
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")
    plan_fresh = BacktestPlanFreshVerificationContext(
        snapshot=shared.snapshot,
        snapshot_spec=shared.snapshot_spec,
        provider=shared.provider,
        provider_spec=shared.provider_spec,
        experiment_spec=shared.experiment_spec,
        fold_spec=fold_spec,
        feature=eval_context.feature,
        feature_spec=eval_context.feature_spec,
        label=eval_context.label,
        label_spec=eval_context.label_spec,
        alignment=eval_context.alignment,
        alignment_spec=eval_context.alignment_spec,
        model=eval_context.model,
        model_spec=eval_context.model_spec,
        prediction=eval_context.prediction,
        prediction_spec=eval_context.prediction_spec,
        target_spec=target_spec,
        target_upstream_paths=target_upstream,
        target_receipt_path=project_root / target_ref.relative_path,
    )
    plan_receipt = _verify_prior_receipt(plan_ref, project_root=project_root)
    plan_root = _receipt_output_path(
        plan_receipt, name="manifest.json", project_root=project_root,
    ).parent
    try:
        plan = verify_backtest_plan_artifact(
            root=plan_root,
            receipt_path=project_root / plan_ref.relative_path,
            target=target,
            release=release,
            folds=folds_artifact,
            experiment=shared.experiment,
            config=config,
            fresh_context=plan_fresh,
            artifact_roots=artifact_roots,
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")
    facts_fresh = AShareMarketFactsFreshVerificationContext(
        target=target,
        folds=folds_artifact,
        experiment=shared.experiment,
        config=config,
        plan_fresh_context=plan_fresh,
        plan_receipt_path=project_root / plan_ref.relative_path,
    )
    upstream_paths = FormalBacktestArtifactUpstreamPaths(
        target_receipt_path=project_root / target_ref.relative_path,
        plan_receipt_path=project_root / plan_ref.relative_path,
        experiment_receipt_path=project_root / experiment_ref[0].relative_path,
    )
    fresh_context = BacktestArtifactFreshVerificationContext(
        facts_fresh_context=facts_fresh,
        upstream_paths=upstream_paths,
        release=release,
    )
    try:
        stage_root = project_stage_root(project_root=project_root, config=config)
    except Exception:
        _fail("SUCCESSOR_INPUT_INVALID")
    return SuccessorFormalBacktestInputs(
        stage_root=stage_root,
        artifact_roots=artifact_roots,
        config=config,
        release=release,
        experiment=shared.experiment,
        target=target,
        plan=plan,
        fresh_context=fresh_context,
        work_key=work_key,
        fold=fold,
        horizon=horizon_lit,
        evaluation=evaluation,
        evaluation_context=eval_context,
        evaluation_receipt_path=evaluation_receipt_path,
    )


def rehydrate_successor_formal_tracking_inputs(
    *,
    prior_refs: tuple["StageReceiptRef", ...],
    request: "SuccessorFoldRequest",
    context: "SuccessorStageContext",
    horizon: int,
) -> SuccessorFormalTrackingInputs:
    """Fresh-verify tracking inputs; requires same fold/horizon backtest prior ref."""

    from quant.backtest.a_share_reporting import verify_backtest_artifact
    from quant.research.m3.successor_runtime import SuccessorFoldRequest, SuccessorStageContext
    from quant.research.m3.tracking import FormalTrackingFreshVerificationContext

    if type(context) is not SuccessorStageContext or type(request) is not SuccessorFoldRequest:
        _fail("SUCCESSOR_STAGE_INVALID")
    refs = _require_sorted_unique_prior_refs(prior_refs)
    horizon_lit = _require_horizon(horizon)
    backtest_ref = _one_fold_horizon_ref(
        refs, stage="backtest", fold=request.fold, horizon=horizon_lit,
    )
    base = rehydrate_successor_formal_backtest_inputs(
        prior_refs=refs,
        request=request,
        context=context,
        horizon=horizon_lit,
    )
    if backtest_ref.scope_key != base.work_key:
        _fail("SUCCESSOR_STAGE_INVALID")
    project_root = context.project_root
    backtest_receipt = _verify_prior_receipt(backtest_ref, project_root=project_root)
    backtest_root = _receipt_output_path(
        backtest_receipt, name="backtest_manifest.json", project_root=project_root,
    ).parent
    try:
        backtest = verify_backtest_artifact(
            root=backtest_root,
            receipt_path=project_root / backtest_ref.relative_path,
            target=base.target,
            plan=base.plan,
            release=base.release,
            experiment=base.experiment,
            config=base.config,
            fresh_context=base.fresh_context,
            artifact_roots=base.artifact_roots,
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")
    tracking_fresh = FormalTrackingFreshVerificationContext(
        evaluation_context=base.evaluation_context,
        evaluation_receipt_path=base.evaluation_receipt_path,
        target=base.target,
        plan=base.plan,
        release=base.release,
        experiment=base.experiment,
        backtest_context=base.fresh_context,
        backtest_receipt_path=project_root / backtest_ref.relative_path,
    )
    try:
        tracking_uri = base.config.canonical_tracking_uri
    except Exception:
        _fail("SUCCESSOR_CONFIG_INVALID")
    if type(tracking_uri) is not str or not tracking_uri:
        _fail("SUCCESSOR_CONFIG_INVALID")
    return SuccessorFormalTrackingInputs(
        stage_root=base.stage_root,
        artifact_roots=base.artifact_roots,
        config=base.config,
        evaluation=base.evaluation,
        backtest=backtest,
        fresh_context=tracking_fresh,
        work_key=base.work_key,
        fold=base.fold,
        horizon=horizon_lit,
        tracking_uri=tracking_uri,
    )


@dataclass(frozen=True)
class SuccessorSummaryHorizonVerifyInputs:
    """Typed inputs for one-horizon R2S stage summary fresh verifier."""

    identity: "FormalSummaryStagePublicationIdentity"
    root: Path
    receipt_path: Path
    evaluations: tuple["VerifiedEvaluationArtifact", ...]
    evaluation_contexts: tuple["EvaluationFreshVerificationContext", ...]
    experiment: "VerifiedExperimentIdentity"
    config: "LoadedM3Config"
    horizon_sessions: Literal[5, 10]
    upstream_paths: "ResearchSummaryUpstreamPaths"
    artifact_roots: Mapping[str, Path]
    expected_receipt_sha256: str


def rehydrate_successor_summary_horizon_verify_inputs(
    *,
    folds: tuple["FoldExecution", ...],
    context: "SuccessorStageContext",
    summary_ref: "StageReceiptRef",
) -> SuccessorSummaryHorizonVerifyInputs:
    """Fresh-rebuild one horizon's typed summary closure from explicit fold receipts."""

    from types import MappingProxyType

    from quant.research.m3.contracts import ResearchSummaryUpstreamPaths
    from quant.research.m3.evaluate import FormalSummaryStagePublicationIdentity
    from quant.research.m3.run_state import path_for_artifact_digest, verify_stage_receipt_with_bytes
    from quant.research.m3.successor_runtime import (
        FoldExecution,
        StageReceiptRef,
        SuccessorStageContext,
        project_stage_root,
    )

    if (
        type(context) is not SuccessorStageContext
        or type(folds) is not tuple
        or len(folds) != 2
        or any(type(item) is not FoldExecution for item in folds)
        or type(summary_ref) is not StageReceiptRef
    ):
        _fail("SUCCESSOR_GATE_FAILED")
    if (
        summary_ref.stage != "research-summary"
        or summary_ref.fold is not None
        or summary_ref.scope != "EXPERIMENT"
        or summary_ref.horizon not in {5, 10}
    ):
        _fail("SUCCESSOR_GATE_FAILED")
    horizon = _require_horizon(summary_ref.horizon)
    project_root = context.project_root
    config_by_fold = {item.fold: item.config.config for item in context.request.folds}
    release_by_fold = {item.fold: item.release for item in context.request.folds}
    if len(set(config_by_fold.values())) < 1:
        _fail("SUCCESSOR_GATE_FAILED")
    # Summary joins on scientific config; use the first fold's LoadedM3Config object.
    config = next(iter(config_by_fold.values()))
    release = next(iter(release_by_fold.values()))
    ids = _runtime_ids(context)
    toolchain = _require_toolchain(context.request.toolchain)
    validate_successor_toolchain_binding(
        project_root=project_root,
        toolchain=toolchain,
        fold_configs=tuple(config_by_fold[execution.fold] for execution in folds),
    )
    all_receipts = tuple(
        sorted(
            {ref for execution in folds for ref in execution.receipts},
            key=lambda item: item.node_id,
        )
    )
    horizons = _canonical_horizons_from_config(config)
    try:
        by_stage = _extract_summary_shared_stages(
            all_receipts, canonical_horizons=horizons,
        )
    except Exception:
        _fail("SUCCESSOR_GATE_FAILED")
    shared = _reconstruct_shared_upstream(
        by_stage=by_stage,
        project_root=project_root,
        release=release,
        config=config,
        ids=ids,
        dump_tool_path=toolchain.qlib_dump_tool_path,
        include_reconciliation=False,
    )
    evaluations = []
    eval_contexts = []
    evaluation_receipt_paths: list[Path] = []
    for execution in folds:
        evaluation, eval_context = _reconstruct_work_chain_for_evaluation(
            shared=shared,
            fold=execution.fold,
            horizon=horizon,
            project_root=project_root,
            config=config,
            receipts=execution.receipts,
            dump_tool_path=toolchain.qlib_dump_tool_path,
        )
        evaluations.append(evaluation)
        eval_contexts.append(eval_context)
        evaluation_ref = next(
            (
                item
                for item in execution.receipts
                if item.stage == "evaluation"
                and item.fold == execution.fold
                and item.horizon == horizon
            ),
            None,
        )
        if evaluation_ref is None:
            _fail("SUCCESSOR_GATE_FAILED")
        evaluation_receipt_paths.append(project_root / evaluation_ref.relative_path)
    experiment_receipt_path = (
        project_root / by_stage["experiment-identity"][0].relative_path
    )
    upstream_paths = ResearchSummaryUpstreamPaths(
        experiment_receipt_path=experiment_receipt_path,
        evaluation_receipt_paths=tuple(evaluation_receipt_paths),
    )
    models = {item.manifest.model for item in evaluations}
    versions = {item.manifest.model_version for item in evaluations}
    if len(models) != 1 or len(versions) != 1:
        _fail("SUCCESSOR_GATE_FAILED")
    model = next(iter(models))
    model_version = next(iter(versions))
    experiment_key = shared.experiment.manifest.experiment_key
    if summary_ref.scope_key != experiment_key:
        _fail("SUCCESSOR_GATE_FAILED")
    try:
        stage_root = project_stage_root(project_root=project_root, config=config)
    except Exception:
        _fail("SUCCESSOR_INPUT_INVALID")
    identity = FormalSummaryStagePublicationIdentity(
        stage_root=stage_root,
        node_id=f"summary.h{horizon}.{model}.{model_version}",
        final_relative_path=PurePosixPath(
            f"summaries/{experiment_key}/h{horizon}/{model}/{model_version}"
        ),
        experiment_key=experiment_key,
        horizon_sessions=horizon,
        model=model,
        model_version=model_version,
    )
    receipt_path = project_root / summary_ref.relative_path
    artifact_roots = MappingProxyType({"PROJECT": project_root})
    try:
        verified_receipt = verify_stage_receipt_with_bytes(
            receipt_path=receipt_path, artifact_roots=artifact_roots,
        )
    except Exception:
        _fail("SUCCESSOR_GATE_FAILED")
    if (
        verified_receipt is None
        or verified_receipt.sha256 != summary_ref.sha256
        or verified_receipt.receipt.stage != "research-summary"
        or verified_receipt.receipt.scope_key != experiment_key
    ):
        _fail("SUCCESSOR_GATE_FAILED")
    try:
        manifest_outputs = tuple(
            item
            for item in verified_receipt.receipt.outputs
            if PurePosixPath(item.relative_path).name == "manifest.json"
        )
        if len(manifest_outputs) != 1:
            raise ValueError
        root = path_for_artifact_digest(
            manifest_outputs[0], artifact_roots=artifact_roots,
        ).parent
    except Exception:
        _fail("SUCCESSOR_GATE_FAILED")
    expected_root = stage_root.joinpath(*identity.final_relative_path.parts)
    try:
        if root.resolve(strict=True) != expected_root.resolve(strict=True):
            raise ValueError
    except Exception:
        _fail("SUCCESSOR_GATE_FAILED")
    return SuccessorSummaryHorizonVerifyInputs(
        identity=identity,
        root=root,
        receipt_path=receipt_path,
        evaluations=tuple(evaluations),
        evaluation_contexts=tuple(eval_contexts),
        experiment=shared.experiment,
        config=config,
        horizon_sessions=horizon,
        upstream_paths=upstream_paths,
        artifact_roots=artifact_roots,
        expected_receipt_sha256=summary_ref.sha256,
    )


def run_successor_formal_summary_gate(
    *,
    folds: tuple["FoldExecution", ...],
    prior_gates: tuple["GateExecution", ...],
    context: "SuccessorStageContext",
    runner: "StageRunner",
    public_apis: "SuccessorPublicApiBundle",
    resume: bool,
) -> "GateExecution":
    """Run the formal research-summary stage for every configured horizon.

    Reconstructs each fold's evaluation chain from its own execution receipts
    via fresh ``verify_*`` calls only (no rebuilding), then calls R2S
    ``run_formal_summary_stage`` once per horizon and folds the real summary
    receipts into one ``GateExecution``.
    """

    from quant.research.m3.contracts import ResearchSummaryUpstreamPaths
    from quant.research.m3.successor_runtime import (
        FoldExecution,
        GateExecution,
        SuccessorPublicApiBundle,
        SuccessorStageContext,
        compute_successor_gate_identity,
        make_public_successor_api_bundle,
    )
    from quant.research.m3.summary_stage import run_formal_summary_stage

    if (
        type(context) is not SuccessorStageContext
        or type(public_apis) is not SuccessorPublicApiBundle
        or type(resume) is not bool
        or type(folds) is not tuple
        or len(folds) != 2
        or any(type(item) is not FoldExecution for item in folds)
        or type(prior_gates) is not tuple
        or any(type(item) is not GateExecution for item in prior_gates)
    ):
        _fail("SUCCESSOR_GATE_FAILED")
    canonical = make_public_successor_api_bundle()
    _require_canonical_public_api_bundle(public_apis, canonical)

    project_root = context.project_root
    config_by_fold = {item.fold: item.config.config for item in context.request.folds}
    release_by_fold = {item.fold: item.release for item in context.request.folds}
    ids = _runtime_ids(context)

    all_receipts = tuple(sorted(
        {ref for execution in folds for ref in execution.receipts},
        key=lambda item: item.node_id,
    ))
    if not all_receipts:
        _fail("SUCCESSOR_GATE_FAILED")

    horizon_sets = {
        _canonical_horizons_from_config(fold_config) for fold_config in config_by_fold.values()
    }
    if len(horizon_sets) != 1:
        _fail("SUCCESSOR_GATE_FAILED")
    horizons = next(iter(horizon_sets))

    toolchain = _require_toolchain(context.request.toolchain)
    fold_configs = tuple(config_by_fold[execution.fold] for execution in folds)
    validate_successor_toolchain_binding(
        project_root=project_root, toolchain=toolchain, fold_configs=fold_configs,
    )

    try:
        by_stage = _extract_summary_shared_stages(
            all_receipts,
            canonical_horizons=horizons,
        )
    except Exception:
        _fail("SUCCESSOR_GATE_FAILED")

    release = next(iter(release_by_fold.values()))
    config = next(iter(config_by_fold.values()))
    shared = _reconstruct_shared_upstream(
        by_stage=by_stage, project_root=project_root, release=release, config=config,
        ids=ids, dump_tool_path=toolchain.qlib_dump_tool_path,
        include_reconciliation=False,
    )

    experiment_receipt_path = project_root / by_stage["experiment-identity"][0].relative_path
    summary_refs: list["StageReceiptRef"] = []
    for horizon in horizons:
        evaluations = []
        eval_contexts = []
        evaluation_receipt_paths: list[Path] = []
        for execution in folds:
            evaluation, eval_context = _reconstruct_work_chain_for_evaluation(
                shared=shared, fold=execution.fold, horizon=horizon, project_root=project_root,
                config=config, receipts=execution.receipts,
                dump_tool_path=toolchain.qlib_dump_tool_path,
            )
            evaluations.append(evaluation)
            eval_contexts.append(eval_context)
            evaluation_ref = next(
                item for item in execution.receipts
                if item.stage == "evaluation" and item.fold == execution.fold
                and item.horizon == horizon
            )
            evaluation_receipt_paths.append(project_root / evaluation_ref.relative_path)

        upstream_paths = ResearchSummaryUpstreamPaths(
            experiment_receipt_path=experiment_receipt_path,
            evaluation_receipt_paths=tuple(evaluation_receipt_paths),
        )
        from quant.research.m3.successor_runtime import project_stage_root

        try:
            stage_root = project_stage_root(project_root=project_root, config=config)
        except Exception:
            _fail("SUCCESSOR_INPUT_INVALID")
        try:
            result = run_formal_summary_stage(
                stage_root=stage_root, artifact_roots=context.artifact_roots, config=config,
                evaluations=evaluations, evaluation_contexts=eval_contexts,
                experiment=shared.experiment, horizon_sessions=horizon,
                upstream_paths=upstream_paths, resume=resume,
            )
        except Exception:
            _fail("SUCCESSOR_STAGE_INVALID")

        summary_refs.append(_new_receipt_ref(
            receipt_path=result.receipt_path, receipt=result.receipt,
            project_root=project_root,
            node=_SummaryNodeRef(node_id=f"summary.h{horizon}", fold=None, horizon=horizon),
        ))

    identity = compute_successor_gate_identity(gate="summary", folds=folds, prior_gates=prior_gates)
    return GateExecution(
        gate="summary", status="PASS", identity=identity,
        receipt_refs=tuple(sorted(summary_refs, key=lambda item: item.node_id)),
    )


# --------------------------------------------------------------------------
# Canonical aliases
# --------------------------------------------------------------------------

CANONICAL_RUN_UPSTREAM_WAVE = run_successor_upstream_wave
CANONICAL_RUN_SUMMARY_GATE = run_successor_formal_summary_gate
CANONICAL_REHYDRATE_FORMAL_BACKTEST = rehydrate_successor_formal_backtest_inputs
CANONICAL_REHYDRATE_FORMAL_TRACKING = rehydrate_successor_formal_tracking_inputs
CANONICAL_REHYDRATE_SUMMARY_HORIZON = rehydrate_successor_summary_horizon_verify_inputs
