"""Explicit two-fold M3 successor orchestration and terminal attestation.

This module owns only the package boundary around an actual M3 stage adapter.
The adapter is responsible for calling the existing stage builders and fresh
verifiers; this module supplies the ordered two-fold protocol, identity checks,
and the durable PASS-only completion record.

No path is discovered from a directory listing.  The caller supplies both
versioned configurations, both verified G1 releases, the new project/output
roots, and the UTC clock value.  The terminal verifier re-reads every receipt
and the complete controlled output tree before returning a verified value.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, NoReturn, Protocol, cast

from quant.data.m3_release import VerifiedG1Release, verify_g1_release
from quant.research.m3.config import LoadedM3Config, load_m3_config
from quant.research.m3.run_state import (
    StageReceipt,
    compute_work_key,
    path_for_artifact_digest,
    verify_stage_receipt_with_bytes,
)

if TYPE_CHECKING:
    from quant.research.m3.acceptance import AcceptanceDecisionV1
    from quant.research.m3.acceptance_stage import FormalAcceptanceStageResult
    from quant.research.m3.backtest_stage import FormalBacktestStageResult
    from quant.research.m3.orchestration import StageRunner
    from quant.research.m3.readiness_evidence import VerifiedReadinessEvidenceArtifact
    from quant.research.m3.reproducibility import FormalReproducibilityResult
    from quant.research.m3.tracking_stage import FormalTrackingStageResult

HORIZONS: tuple[int, int] = (5, 10)
TERMINAL_FILENAME = "completion.json"
TERMINAL_SCHEMA: Literal["m3-successor-terminal-v1"] = "m3-successor-terminal-v1"
TWO_FOLD_IDENTITY_VERSION = "m3-successor-two-fold-v1"
TREE_DIGEST_VERSION = "m3-successor-output-tree-v1"

GateName = Literal["summary", "reproducibility", "readiness", "acceptance"]
GateStatus = Literal["PASS", "FAIL"]
_WaveReceiptKey = tuple[str, str | None, int | None]
_GATES: tuple[GateName, ...] = (
    "summary",
    "reproducibility",
    "readiness",
    "acceptance",
)
_SCOPES = frozenset(
    {"SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "REPRO", "ACCEPTANCE"}
)
_FOLD_RE = re.compile(r"^fold_[0-9]{3}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_CONTROLLED_RUNTIME_DIRECTORIES = frozenset(
    {
        ".stage-locks",
        ".stage-tmp",
        "snapshots",
        "snapshot-requests",
        "receipts",
        "receipts/snapshot",
        "receipts/development-snapshot",
    }
)
_REQUIRED_SHARED_STAGES = (
    "snapshot",
    "provider",
    "provider-validation",
    "experiment-identity",
    "folds",
)
_CROSS_FOLD_STAGES = frozenset(
    {
        "snapshot",
        "provider",
        "provider-validation",
        "experiment-identity",
        "folds",
        "labels",
        "label-reconciliation",
    }
)
_SHARED_RECEIPT_STAGES = frozenset(
    {
        "snapshot",
        "provider",
        "provider-validation",
        "experiment-identity",
        "folds",
        "labels",
        "label-reconciliation",
    }
)
_GATE_IDENTITY_VERSION = "m3-successor-gate-identity-v1"
_REQUIRED_HORIZON_STAGES = (
    "labels",
    "label-reconciliation",
    "alignment",
    "train",
    "predictions",
    "evaluation",
    "targets",
    "backtest_plan",
    "backtest",
    "tracking",
)
_HORIZON_WORK_STAGES = _REQUIRED_HORIZON_STAGES[2:]
_SHARED_SINGLE_WAVES = (
    "snapshot",
    "provider",
    "provider-validation",
    "experiment-identity",
)
_EXPERIMENT_ARTIFACTS_WAVE = "experiment-artifacts"
_LABEL_RECONCILIATION_WAVE = "label-reconciliation"
_WORK_WAVE = "work"
_UPSTREAM_WAVES = (
    *_SHARED_SINGLE_WAVES,
    _EXPERIMENT_ARTIFACTS_WAVE,
    _LABEL_RECONCILIATION_WAVE,
    _WORK_WAVE,
)
_REQUIRED_RUN_PLAN_BUILDERS = frozenset(
    {
        "snapshot",
        "provider",
        "provider-validation",
        "experiment-identity",
        "experiment-artifacts",
        "label-reconciliation",
        "work",
        "summary",
    }
)
_FORBIDDEN_PSEUDO_BUILDERS = frozenset({"labels", "features", "folds"})
# Must match StageSpec / StageReceipt.stage names published by StageRunner.
_WORK_PRE_FORMAL_STAGES = (
    "features",
    "alignment",
    "train",
    "predictions",
    "evaluation",
    "targets",
    "backtest_plan",
)


class SuccessorRuntimeError(ValueError):
    """Stable, redacted boundary failure for the successor runtime."""

    _CODES = frozenset(
        {
            "SUCCESSOR_INPUT_INVALID",
            "SUCCESSOR_CONFIG_INVALID",
            "SUCCESSOR_RELEASE_INVALID",
            "SUCCESSOR_STAGE_FAILED",
            "SUCCESSOR_STAGE_INVALID",
            "SUCCESSOR_GATE_FAILED",
            "SUCCESSOR_TERMINAL_INVALID",
            "SUCCESSOR_TERMINAL_CONFLICT",
            "SUCCESSOR_TERMINAL_ALREADY_COMPLETE",
            "SUCCESSOR_TERMINAL_PUBLISH_FAILED",
        }
    )

    def __init__(self, code: str) -> None:
        if code not in self._CODES:
            raise ValueError("unknown successor runtime error code")
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"SuccessorRuntimeError({self.code!r})"


@dataclass(frozen=True)
class SuccessorRuntimeIdentity:
    """The runtime identities that every terminal and gate must share."""

    code_version: str
    dependency_fingerprint_sha256: str
    provider_runtime_fingerprint_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.code_version) is not str
            or not self.code_version
            or _CONTROL_RE.search(self.code_version)
            or not _is_hex64(self.dependency_fingerprint_sha256)
            or not _is_hex64(self.provider_runtime_fingerprint_sha256)
        ):
            raise ValueError("invalid successor runtime identity")


@dataclass(frozen=True)
class SuccessorConfigInput:
    """One explicit, versioned config file and its already-loaded object."""

    relative_path: PurePosixPath
    config: LoadedM3Config

    def __post_init__(self) -> None:
        if type(self.relative_path) is not PurePosixPath:
            raise ValueError("invalid successor config path")
        _validate_relative(self.relative_path.as_posix(), require_prefix="configs/")
        if type(self.config) is not LoadedM3Config:
            raise ValueError("invalid successor config")


@dataclass(frozen=True)
class SuccessorFoldRequest:
    """The complete explicit input for one fold lane."""

    fold: str
    config: SuccessorConfigInput
    release: VerifiedG1Release

    def __post_init__(self) -> None:
        if _FOLD_RE.fullmatch(self.fold) is None:
            raise ValueError("invalid successor fold")
        if type(self.config) is not SuccessorConfigInput:
            raise ValueError("invalid successor fold config")
        if type(self.release) is not VerifiedG1Release:
            raise ValueError("invalid successor fold release")


@dataclass(frozen=True)
class SuccessorToolchainBinding:
    """Explicit concrete toolchain binding; never discovered from PATH/env."""

    python_executable: Path
    qlib_dump_tool_path: Path
    timeout_seconds: float

    def __post_init__(self) -> None:
        path_type = type(Path())
        if (
            type(self.python_executable) is not path_type
            or type(self.qlib_dump_tool_path) is not path_type
        ):
            raise ValueError("invalid successor toolchain path type")
        if (
            type(self.timeout_seconds) is not float
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds != self.timeout_seconds  # NaN
            or self.timeout_seconds in (float("inf"), float("-inf"))
            or self.timeout_seconds <= 0.0
        ):
            raise ValueError("invalid successor toolchain timeout")


@dataclass(frozen=True)
class SuccessorRuntimeRequest:
    """Frozen caller inputs; no path or stage discovery is performed."""

    project_root: Path
    controlled_output_root: Path
    folds: tuple[SuccessorFoldRequest, ...]
    runtime_identity: SuccessorRuntimeIdentity
    now: dt.datetime
    toolchain: SuccessorToolchainBinding

    def __post_init__(self) -> None:
        if not isinstance(self.project_root, Path) or not isinstance(
            self.controlled_output_root, Path
        ):
            raise ValueError("invalid successor roots")
        if (
            type(self.folds) is not tuple
            or len(self.folds) != 2
            or any(type(item) is not SuccessorFoldRequest for item in self.folds)
            or tuple(item.fold for item in self.folds)
            != tuple(sorted(item.fold for item in self.folds))
            or len({item.fold for item in self.folds}) != 2
        ):
            raise ValueError("successor requires two distinct ordered folds")
        if type(self.runtime_identity) is not SuccessorRuntimeIdentity:
            raise ValueError("invalid successor runtime identity")
        if type(self.toolchain) is not SuccessorToolchainBinding:
            raise ValueError("invalid successor toolchain binding")
        _validate_utc(self.now)


@dataclass(frozen=True)
class WorkIdentity:
    fold: str
    horizon: int
    work_key: str

    def __post_init__(self) -> None:
        if _FOLD_RE.fullmatch(self.fold) is None or self.horizon not in HORIZONS:
            raise ValueError("invalid successor work identity")
        if not _is_hex64(self.work_key):
            raise ValueError("invalid successor work key")


@dataclass(frozen=True)
class StageReceiptRef:
    """Stable identity of one receipt, with explicit fold/horizon ownership."""

    node_id: str
    stage: str
    scope: str
    scope_key: str
    relative_path: str
    sha256: str
    fold: str | None
    horizon: int | None

    def __post_init__(self) -> None:
        if _TOKEN_RE.fullmatch(self.node_id) is None or _TOKEN_RE.fullmatch(
            self.stage
        ) is None:
            raise ValueError("invalid successor receipt identity")
        if self.scope not in _SCOPES or not _is_hex64(self.scope_key):
            raise ValueError("invalid successor receipt scope")
        _validate_relative(self.relative_path)
        if "receipts" not in PurePosixPath(self.relative_path).parts:
            raise ValueError(
                "successor receipt path must be under a receipts directory"
            )
        if not _is_hex64(self.sha256):
            raise ValueError("invalid successor receipt digest")
        if self.fold is not None and _FOLD_RE.fullmatch(self.fold) is None:
            raise ValueError("invalid successor receipt fold")
        if self.horizon is not None and self.horizon not in HORIZONS:
            raise ValueError("invalid successor receipt horizon")


@dataclass(frozen=True)
class FoldExecution:
    """Result returned after one adapter has run and fresh-verified its lane."""

    fold: str
    config_raw_sha256: str
    config_full_sha256: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    snapshot_id: str
    experiment_key: str
    work_identities: tuple[WorkIdentity, ...]
    receipts: tuple[StageReceiptRef, ...]

    def __post_init__(self) -> None:
        if _FOLD_RE.fullmatch(self.fold) is None:
            raise ValueError("invalid successor fold execution")
        for value in (
            self.config_raw_sha256,
            self.config_full_sha256,
            self.g1_release_id,
            self.g1_release_manifest_sha256,
            self.snapshot_id,
            self.experiment_key,
        ):
            if not _is_hex64(value):
                raise ValueError("invalid successor execution identity")
        if (
            type(self.work_identities) is not tuple
            or tuple(item.horizon for item in self.work_identities)
            != HORIZONS
            or any(type(item) is not WorkIdentity for item in self.work_identities)
            or any(item.fold != self.fold for item in self.work_identities)
        ):
            raise ValueError("successor work identity closure invalid")
        if (
            type(self.receipts) is not tuple
            or tuple(item.node_id for item in self.receipts)
            != tuple(sorted(item.node_id for item in self.receipts))
            or len({item.node_id for item in self.receipts}) != len(self.receipts)
            or any(type(item) is not StageReceiptRef for item in self.receipts)
        ):
            raise ValueError("successor receipt closure invalid")


@dataclass(frozen=True)
class GateExecution:
    """Output of one terminal prerequisite, before it is fresh-verified."""

    gate: GateName
    status: GateStatus
    identity: str
    receipt_refs: tuple[StageReceiptRef, ...]

    def __post_init__(self) -> None:
        if self.gate not in _GATES or self.status not in {"PASS", "FAIL"}:
            raise ValueError("invalid successor gate")
        if not _is_hex64(self.identity):
            raise ValueError("invalid successor gate identity")
        if (
            type(self.receipt_refs) is not tuple
            or not self.receipt_refs
            or any(type(item) is not StageReceiptRef for item in self.receipt_refs)
            or tuple(item.node_id for item in self.receipt_refs)
            != tuple(sorted(item.node_id for item in self.receipt_refs))
            or len({item.node_id for item in self.receipt_refs})
            != len(self.receipt_refs)
        ):
            raise ValueError("invalid successor gate receipts")

    @property
    def receipt_node_ids(self) -> tuple[str, ...]:
        return tuple(item.node_id for item in self.receipt_refs)


@dataclass(frozen=True)
class GateVerification:
    """Proof returned by the adapter's existing fresh verifier."""

    gate: GateName
    identity: str
    receipt_node_ids: tuple[str, ...]
    status: Literal["PASS"] = "PASS"

    def __post_init__(self) -> None:
        if (
            self.gate not in _GATES
            or self.status != "PASS"
            or not _is_hex64(self.identity)
            or self.receipt_node_ids != tuple(sorted(self.receipt_node_ids))
            or not self.receipt_node_ids
        ):
            raise ValueError("invalid successor gate verification")


def compute_successor_gate_identity(
    *,
    gate: GateName,
    folds: tuple[FoldExecution, ...],
    prior_gates: tuple[GateExecution, ...],
) -> str:
    """Derive the deterministic identity used by one successor Gate."""

    if (
        gate not in _GATES
        or type(folds) is not tuple
        or any(type(item) is not FoldExecution for item in folds)
        or type(prior_gates) is not tuple
        or any(type(item) is not GateExecution for item in prior_gates)
    ):
        _fail("SUCCESSOR_GATE_FAILED")
    return _sha256_json(
        [
            _GATE_IDENTITY_VERSION,
            gate,
            [_execution_join_payload(item) for item in folds],
            [[item.gate, item.identity] for item in prior_gates],
        ]
    )


def _execution_join_payload(execution: FoldExecution) -> list[object]:
    return [
        execution.fold,
        execution.snapshot_id,
        execution.experiment_key,
        [
            [item.fold, item.horizon, item.work_key]
            for item in execution.work_identities
        ],
    ]


def _resolve_canonical_g8_stage_root(request: SuccessorRuntimeRequest) -> Path:
    """Resolve the sole G8 root from both fold configs; must equal controlled output."""

    try:
        project = _real_directory(request.project_root)
        controlled = _real_directory(request.controlled_output_root)
        resolved: list[Path] = []
        for item in request.folds:
            stage = project_stage_root(
                project_root=project, config=item.config.config
            )
            resolved.append(stage.resolve(strict=True))
        if len(set(resolved)) != 1:
            raise ValueError
        canonical = resolved[0]
        if canonical != controlled.resolve(strict=True):
            raise ValueError
        return canonical
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_INPUT_INVALID")


def _artifact_roots_for_receipt_stage(
    *,
    stage: str,
    project_root: Path,
    canonical_stage_root: Path,
) -> Mapping[str, Path]:
    """Select the unique root map for one receipt stage (PROJECT or G8)."""

    if stage == "acceptance":
        return MappingProxyType({"G8": canonical_stage_root})
    return MappingProxyType({"PROJECT": project_root})


@dataclass(frozen=True)
class ConfigBinding:
    relative_path: str
    config_version: str
    raw_config_sha256: str
    full_config_sha256: str
    scientific_config_sha256: str


@dataclass(frozen=True)
class FoldBinding:
    fold: str
    config_raw_sha256: str
    config_full_sha256: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    g1_release_root: str
    snapshot_id: str
    experiment_key: str
    work_identities: tuple[WorkIdentity, ...]
    receipt_node_ids: tuple[str, ...]


@dataclass(frozen=True)
class TerminalAttestation:
    """Canonical payload written as ``completion.json``."""

    schema_version: Literal["m3-successor-terminal-v1"]
    two_fold_identity: str
    attested_at: str
    terminal_status: Literal["PASS"]
    runtime_identity: SuccessorRuntimeIdentity
    configs: tuple[ConfigBinding, ...]
    folds: tuple[FoldBinding, ...]
    horizons: tuple[int, ...]
    receipts: tuple[StageReceiptRef, ...]
    gates: tuple[GateExecution, ...]
    controlled_output_root: str
    controlled_output_tree_sha256: str

    def __post_init__(self) -> None:
        if (
            self.schema_version != TERMINAL_SCHEMA
            or not _is_hex64(self.two_fold_identity)
            or not _is_canonical_utc_text(self.attested_at)
            or self.terminal_status != "PASS"
            or type(self.runtime_identity) is not SuccessorRuntimeIdentity
            or type(self.configs) is not tuple
            or len(self.configs) != 2
            or type(self.folds) is not tuple
            or len(self.folds) != 2
            or self.horizons != HORIZONS
            or type(self.receipts) is not tuple
            or type(self.gates) is not tuple
            or tuple(item.gate for item in self.gates) != _GATES
            or any(item.status != "PASS" for item in self.gates)
            or not _is_hex64(self.controlled_output_tree_sha256)
        ):
            raise ValueError("invalid successor terminal attestation")


@dataclass(frozen=True)
class VerifiedTerminalAttestation:
    terminal_path: Path
    attestation: TerminalAttestation

    def __post_init__(self) -> None:
        if not isinstance(self.terminal_path, Path) or type(
            self.attestation
        ) is not TerminalAttestation:
            raise ValueError("invalid verified successor terminal")


@dataclass(frozen=True)
class SuccessorRunResult:
    terminal_path: Path
    attestation: TerminalAttestation
    folds: tuple[FoldExecution, ...]
    gates: tuple[GateExecution, ...]
    reused: bool


@dataclass(frozen=True)
class SuccessorStageContext:
    request: SuccessorRuntimeRequest
    fold: str | None

    @property
    def project_root(self) -> Path:
        return self.request.project_root.resolve(strict=True)

    @property
    def artifact_roots(self) -> Mapping[str, Path]:
        """The only root registry passed to StageRunner and receipt verifiers."""

        return MappingProxyType({"PROJECT": self.project_root})


class SuccessorStageApi(Protocol):
    """Adapter boundary for existing production stages and fresh verifiers."""

    def run_fold(
        self, *, request: SuccessorFoldRequest, context: SuccessorStageContext,
        resume: bool,
    ) -> FoldExecution: ...

    def verify_fold(
        self, *, execution: FoldExecution, context: SuccessorStageContext
    ) -> None: ...

    def run_summary(
        self, *, folds: tuple[FoldExecution, ...], context: SuccessorStageContext,
        resume: bool,
    ) -> GateExecution: ...

    def run_reproducibility(
        self, *, folds: tuple[FoldExecution, ...], summary: GateExecution,
        context: SuccessorStageContext, resume: bool,
    ) -> GateExecution: ...

    def run_readiness(
        self, *, folds: tuple[FoldExecution, ...], summary: GateExecution,
        reproducibility: GateExecution, context: SuccessorStageContext,
        resume: bool,
    ) -> GateExecution: ...

    def run_acceptance(
        self, *, folds: tuple[FoldExecution, ...], summary: GateExecution,
        reproducibility: GateExecution, readiness: GateExecution,
        context: SuccessorStageContext, resume: bool,
    ) -> GateExecution: ...

    def verify_gate(
        self,
        *,
        gate: GateExecution,
        folds: tuple[FoldExecution, ...],
        prior_gates: tuple[GateExecution, ...],
        context: SuccessorStageContext,
    ) -> GateVerification: ...


class SuccessorProductionStageRunnerFactory(Protocol):
    """Narrow constructor boundary for the existing PROJECT-only StageRunner."""

    def __call__(
        self, *, project_root: Path, stage_root: Path, config: LoadedM3Config
    ) -> "StageRunner": ...


class SuccessorProductionWaveRunner(Protocol):
    """Build and verify one real upstream wave through the existing public API."""

    def __call__(
        self,
        *,
        wave: str,
        request: SuccessorFoldRequest,
        context: SuccessorStageContext,
        runner: "StageRunner",
        public_apis: "SuccessorPublicApiBundle",
        prior_refs: tuple[StageReceiptRef, ...],
        resume: bool,
    ) -> tuple[StageReceiptRef, ...]: ...


class SuccessorProductionFormalStageRunner(Protocol):
    """One formal backtest or tracking call, never the whole successor sequence."""

    def __call__(
        self,
        *,
        stage: Literal["backtest", "tracking"],
        horizon: int,
        request: SuccessorFoldRequest,
        context: SuccessorStageContext,
        runner: "StageRunner",
        public_apis: "SuccessorPublicApiBundle",
        prior_refs: tuple[StageReceiptRef, ...],
        resume: bool,
    ) -> StageReceiptRef: ...


class SuccessorProductionFoldVerifier(Protocol):
    """Fresh verifier for the already assembled fold receipt closure."""

    def __call__(
        self,
        *,
        execution: FoldExecution,
        context: SuccessorStageContext,
        public_apis: "SuccessorPublicApiBundle",
    ) -> None: ...


class SuccessorProductionGateRunner(Protocol):
    """One public gate API, with prior gates supplied as immutable input."""

    def __call__(
        self,
        *,
        folds: tuple[FoldExecution, ...],
        prior_gates: tuple[GateExecution, ...],
        context: SuccessorStageContext,
        runner: "StageRunner",
        public_apis: "SuccessorPublicApiBundle",
        resume: bool,
    ) -> GateExecution: ...


class SuccessorProductionGateVerifier(Protocol):
    """Fresh verifier wrapper around one existing formal gate verifier."""

    def __call__(
        self,
        *,
        gate: GateExecution,
        folds: tuple[FoldExecution, ...],
        prior_gates: tuple[GateExecution, ...],
        context: SuccessorStageContext,
        runner: "StageRunner",
        public_apis: "SuccessorPublicApiBundle",
    ) -> object: ...


@dataclass(frozen=True)
class SuccessorPublicApiBundle:
    """References to existing public M3 APIs used by production bridges.

    The bundle contains no successor implementation.  Its narrow injected
    bridge callbacks receive this bundle so a production worker can call the
    existing StageRunner/run-plan builders and formal APIs without copying
    their stage logic into this package.
    """

    stage_runner_type: type[Any]
    run_plan_builders: Mapping[str, Callable[..., object]]
    formal_backtest_run_plan: Callable[..., object]
    formal_backtest_stage: Callable[..., "FormalBacktestStageResult"]
    formal_tracking_run_plan: Callable[..., object]
    formal_tracking_stage: Callable[..., "FormalTrackingStageResult"]
    summary_builder: Callable[..., object]
    summary_verifier: Callable[..., object]
    reproducibility_stage: Callable[..., "FormalReproducibilityResult"]
    reproducibility_verifier: Callable[..., object]
    readiness_stage: Callable[..., "VerifiedReadinessEvidenceArtifact"]
    readiness_verifier: Callable[..., "VerifiedReadinessEvidenceArtifact"]
    acceptance_stage: Callable[..., "FormalAcceptanceStageResult"]
    acceptance_audit: Callable[..., "AcceptanceDecisionV1"]

    def __post_init__(self) -> None:
        if not isinstance(self.stage_runner_type, type):
            raise ValueError("invalid successor public StageRunner binding")
        if (
            not isinstance(self.run_plan_builders, Mapping)
            or not self.run_plan_builders
            or set(self.run_plan_builders) != _REQUIRED_RUN_PLAN_BUILDERS
            or _FORBIDDEN_PSEUDO_BUILDERS.intersection(self.run_plan_builders)
            or any(
                type(name) is not str or not name or not callable(builder)
                for name, builder in self.run_plan_builders.items()
            )
            or any(
                not callable(value)
                for value in (
                    self.formal_backtest_run_plan,
                    self.formal_backtest_stage,
                    self.formal_tracking_run_plan,
                    self.formal_tracking_stage,
                    self.summary_builder,
                    self.summary_verifier,
                    self.reproducibility_stage,
                    self.reproducibility_verifier,
                    self.readiness_stage,
                    self.readiness_verifier,
                    self.acceptance_stage,
                    self.acceptance_audit,
                )
            )
        ):
            raise ValueError("incomplete successor public API bundle")
        object.__setattr__(
            self,
            "run_plan_builders",
            MappingProxyType(dict(self.run_plan_builders)),
        )


_PUBLIC_API_CALLABLE_FIELDS = (
    "formal_backtest_run_plan",
    "formal_backtest_stage",
    "formal_tracking_run_plan",
    "formal_tracking_stage",
    "summary_builder",
    "summary_verifier",
    "reproducibility_stage",
    "reproducibility_verifier",
    "readiness_stage",
    "readiness_verifier",
    "acceptance_stage",
    "acceptance_audit",
)


def _require_canonical_public_api_bundle(
    candidate: SuccessorPublicApiBundle,
    canonical: SuccessorPublicApiBundle,
) -> None:
    """Reject caller substitutions for every production builder/verifier."""

    try:
        if (
            type(candidate) is not SuccessorPublicApiBundle
            or type(canonical) is not SuccessorPublicApiBundle
            or candidate.stage_runner_type is not canonical.stage_runner_type
            or tuple(sorted(candidate.run_plan_builders))
            != tuple(sorted(canonical.run_plan_builders))
            or any(
                candidate.run_plan_builders[name]
                is not canonical.run_plan_builders[name]
                for name in canonical.run_plan_builders
            )
            or any(
                getattr(candidate, field) is not getattr(canonical, field)
                for field in _PUBLIC_API_CALLABLE_FIELDS
            )
        ):
            raise ValueError
    except Exception:
        _fail("SUCCESSOR_INPUT_INVALID")


def make_public_successor_api_bundle() -> SuccessorPublicApiBundle:
    """Bind the current public M3 builders and formal verifier APIs.

    Imports remain local so the contract module stays cold-importable.  The
    actual domain arguments and worker execution remain in the narrow bridge
    callbacks injected into :class:`ProductionSuccessorStageAdapter`.
    """

    try:
        from quant.research.m3.acceptance_stage import (
            audit_formal_m3_acceptance,
            run_formal_acceptance_stage,
        )
        from quant.research.m3.backtest_stage import (
            make_formal_backtest_run_plan,
            run_formal_backtest_stage,
        )
        from quant.research.m3.evaluate import (
            build_research_summary_artifact,
            verify_research_summary_stage_artifact,
        )
        from quant.research.m3.experiment_identity import (
            make_experiment_identity_run_plan,
        )
        from quant.research.m3.orchestration import (
            StageRunner,
            make_experiment_artifact_run_plan,
            make_label_reconciliation_run_plan,
            make_provider_materialization_run_plan,
            make_provider_validation_run_plan,
            make_snapshot_run_plan,
            make_summary_run_plan,
            make_work_run_plan,
        )
        from quant.research.m3.readiness_evidence import (
            run_readiness_evidence_stage,
            verify_readiness_evidence_artifact,
        )
        from quant.research.m3.reproducibility import (
            run_formal_reproducibility_stage,
            verify_formal_reproducibility_artifact,
        )
        from quant.research.m3.tracking_stage import (
            make_formal_tracking_run_plan,
            run_formal_tracking_stage,
        )
        return SuccessorPublicApiBundle(
            stage_runner_type=StageRunner,
            run_plan_builders={
                "snapshot": make_snapshot_run_plan,
                "provider": make_provider_materialization_run_plan,
                "provider-validation": make_provider_validation_run_plan,
                "experiment-identity": make_experiment_identity_run_plan,
                "experiment-artifacts": make_experiment_artifact_run_plan,
                "label-reconciliation": make_label_reconciliation_run_plan,
                "work": make_work_run_plan,
                "summary": make_summary_run_plan,
            },
            formal_backtest_run_plan=make_formal_backtest_run_plan,
            formal_backtest_stage=run_formal_backtest_stage,
            formal_tracking_run_plan=make_formal_tracking_run_plan,
            formal_tracking_stage=run_formal_tracking_stage,
            summary_builder=build_research_summary_artifact,
            summary_verifier=verify_research_summary_stage_artifact,
            reproducibility_stage=run_formal_reproducibility_stage,
            reproducibility_verifier=verify_formal_reproducibility_artifact,
            readiness_stage=run_readiness_evidence_stage,
            readiness_verifier=verify_readiness_evidence_artifact,
            acceptance_stage=run_formal_acceptance_stage,
            acceptance_audit=audit_formal_m3_acceptance,
        )
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_INPUT_INVALID")


@dataclass(frozen=True)
class SuccessorProductionDependencies:
    """Narrow, one-wave/one-gate adapters around the public M3 APIs.

    No field accepts or returns the seven-method ``SuccessorStageApi``.  The
    concrete adapter below owns the complete wave and Gate sequence; these
    dependencies only translate one call into the existing public API.
    """

    stage_runner_factory: SuccessorProductionStageRunnerFactory
    run_upstream_wave: SuccessorProductionWaveRunner
    run_formal_stage: SuccessorProductionFormalStageRunner
    verify_fold: SuccessorProductionFoldVerifier
    run_summary: SuccessorProductionGateRunner
    verify_summary: SuccessorProductionGateVerifier
    run_reproducibility: SuccessorProductionGateRunner
    verify_reproducibility: SuccessorProductionGateVerifier
    run_readiness: SuccessorProductionGateRunner
    verify_readiness: SuccessorProductionGateVerifier
    run_acceptance: SuccessorProductionGateRunner
    verify_acceptance: SuccessorProductionGateVerifier
    verify_gate: SuccessorProductionGateVerifier

    def __post_init__(self) -> None:
        if any(
            not callable(value)
            for value in (
                self.stage_runner_factory,
                self.run_upstream_wave,
                self.run_formal_stage,
                self.verify_fold,
                self.run_summary,
                self.verify_summary,
                self.run_reproducibility,
                self.verify_reproducibility,
                self.run_readiness,
                self.verify_readiness,
                self.run_acceptance,
                self.verify_acceptance,
                self.verify_gate,
            )
        ):
            _fail("SUCCESSOR_INPUT_INVALID")
        if self.stage_runner_factory is not make_project_stage_runner:
            _fail("SUCCESSOR_INPUT_INVALID")


class ProductionSuccessorStageAdapter:
    """Concrete, package-owned implementation of ``SuccessorStageApi``.

    The adapter owns the fixed real-wave and four-Gate order.  Injected
    callbacks are deliberately limited to one existing wave or one existing
    formal API call, so a caller cannot replace this order with a handwritten
    ``run_fold``/``run_*`` sequence or pseudo single-transition markers.
    """

    def __init__(
        self,
        *,
        dependencies: SuccessorProductionDependencies,
        public_apis: SuccessorPublicApiBundle | None = None,
    ) -> None:
        try:
            if type(dependencies) is not SuccessorProductionDependencies:
                raise ValueError
            if any(
                not callable(value)
                for value in (
                    dependencies.stage_runner_factory,
                    dependencies.run_upstream_wave,
                    dependencies.run_formal_stage,
                    dependencies.verify_fold,
                    dependencies.run_summary,
                    dependencies.verify_summary,
                    dependencies.run_reproducibility,
                    dependencies.verify_reproducibility,
                    dependencies.run_readiness,
                    dependencies.verify_readiness,
                    dependencies.run_acceptance,
                    dependencies.verify_acceptance,
                    dependencies.verify_gate,
                )
            ):
                raise ValueError
            bound_public_apis = make_public_successor_api_bundle()
            if public_apis is not None:
                _require_canonical_public_api_bundle(
                    public_apis,
                    bound_public_apis,
                )
            from quant.research.m3.orchestration import StageRunner

            if (
                dependencies.stage_runner_factory is not make_project_stage_runner
                or bound_public_apis.stage_runner_type is not StageRunner
            ):
                raise ValueError
            from quant.research.m3 import successor_downstream_stage as downstream
            from quant.research.m3 import successor_upstream_stage as upstream

            if (
                dependencies.run_upstream_wave
                is not upstream.run_successor_upstream_wave
                or dependencies.run_summary
                is not upstream.run_successor_formal_summary_gate
                or dependencies.run_formal_stage
                is not downstream.run_successor_formal_stage
                or dependencies.verify_fold is not downstream.verify_successor_fold
                or dependencies.verify_summary
                is not downstream.verify_successor_summary_gate
                or dependencies.run_reproducibility
                is not downstream.run_successor_reproducibility_gate
                or dependencies.verify_reproducibility
                is not downstream.verify_successor_reproducibility_gate
                or dependencies.run_readiness
                is not downstream.run_successor_readiness_gate
                or dependencies.verify_readiness
                is not downstream.verify_successor_readiness_gate
                or dependencies.run_acceptance
                is not downstream.run_successor_acceptance_gate
                or dependencies.verify_acceptance
                is not downstream.verify_successor_acceptance_gate
                or dependencies.verify_gate
                is not downstream.verify_successor_terminal_gate
            ):
                raise ValueError
        except SuccessorRuntimeError:
            raise
        except Exception:
            _fail("SUCCESSOR_INPUT_INVALID")
        self._dependencies = dependencies
        self._public_apis = bound_public_apis
        self._wave_binding: tuple[str, Path, bool, tuple[str, str]] | None = None
        self._consumed_folds: set[str] = set()

    @property
    def dependencies(self) -> SuccessorProductionDependencies:
        """Return the immutable dependency binding used by this adapter."""

        return self._dependencies

    @property
    def public_apis(self) -> SuccessorPublicApiBundle:
        """Return the existing public API references used by the bridge."""

        return self._public_apis

    def run_fold(
        self,
        *,
        request: SuccessorFoldRequest,
        context: SuccessorStageContext,
        resume: bool,
    ) -> FoldExecution:
        self._bind_runtime_wave_session(
            runtime_request=context.request,
            fold=request.fold,
            resume=resume,
        )
        runner = self._runner(context=context, config=request.config.config)
        refs: list[StageReceiptRef] = []
        for wave in _UPSTREAM_WAVES:
            wave_refs = self._run_wave(
                wave=wave,
                request=request,
                context=context,
                runner=runner,
                prior_refs=tuple(sorted(refs, key=lambda item: item.node_id)),
                resume=resume,
            )
            if wave == _WORK_WAVE:
                refs.extend(
                    item
                    for item in wave_refs
                    if _work_receipt_belongs_to_fold(item, request.fold)
                )
            else:
                refs.extend(wave_refs)
        for horizon in HORIZONS:
            for stage in ("backtest", "tracking"):
                refs.append(
                    self._receipt(
                        self._dependencies.run_formal_stage(
                            stage=cast(Literal["backtest", "tracking"], stage),
                            horizon=horizon,
                            request=request,
                            context=context,
                            runner=runner,
                            public_apis=self._public_apis,
                            prior_refs=tuple(
                                sorted(refs, key=lambda item: item.node_id)
                            ),
                            resume=resume,
                        )
                    )
                )
        snapshot = self._one_ref(refs, stage="snapshot", horizon=None)
        experiment = self._one_ref(refs, stage="experiment-identity", horizon=None)
        raw = request.config.config.raw_config_sha256
        if raw is None:
            _fail("SUCCESSOR_CONFIG_INVALID")
        try:
            execution = FoldExecution(
                fold=request.fold,
                config_raw_sha256=raw,
                config_full_sha256=request.config.config.full_config_sha256,
                g1_release_id=request.release.manifest.release_id,
                g1_release_manifest_sha256=request.release.manifest_sha256,
                snapshot_id=snapshot.scope_key,
                experiment_key=experiment.scope_key,
                work_identities=tuple(
                    WorkIdentity(
                        fold=request.fold,
                        horizon=horizon,
                        work_key=compute_work_key(
                            experiment_key=experiment.scope_key,
                            fold=request.fold,
                            horizon=horizon,
                        ),
                    )
                    for horizon in HORIZONS
                ),
                receipts=tuple(sorted(refs, key=lambda item: item.node_id)),
            )
            _validate_fold_execution(context.request, request, execution)
            return execution
        except SuccessorRuntimeError:
            raise
        except Exception:
            _fail("SUCCESSOR_STAGE_INVALID")

    def _bind_runtime_wave_session(
        self,
        *,
        runtime_request: SuccessorRuntimeRequest,
        fold: str,
        resume: bool,
    ) -> None:
        try:
            if type(runtime_request) is not SuccessorRuntimeRequest or type(resume) is not bool:
                raise ValueError
            if type(fold) is not str or not fold:
                raise ValueError
            identity = two_fold_identity(runtime_request)
            project = _real_directory(runtime_request.project_root)
            expected_folds = tuple(item.fold for item in runtime_request.folds)
            if (
                len(expected_folds) != 2
                or expected_folds[0] == expected_folds[1]
                or fold not in expected_folds
            ):
                raise ValueError
            binding = (identity, project, resume, expected_folds)
            if self._wave_binding is None:
                self._wave_binding = binding
                self._consumed_folds = set()
            elif self._wave_binding != binding:
                _fail("SUCCESSOR_INPUT_INVALID")
            if fold in self._consumed_folds:
                _fail("SUCCESSOR_STAGE_INVALID")
            if len(self._consumed_folds) >= 2:
                _fail("SUCCESSOR_STAGE_INVALID")
            self._consumed_folds.add(fold)
        except SuccessorRuntimeError:
            raise
        except Exception:
            _fail("SUCCESSOR_INPUT_INVALID")

    def _assert_wave_binding(
        self, *, runtime_request: SuccessorRuntimeRequest, resume: bool
    ) -> None:
        if self._wave_binding is None:
            raise ValueError
        identity, project, bound_resume, expected_folds = self._wave_binding
        if (
            identity != two_fold_identity(runtime_request)
            or project != _real_directory(runtime_request.project_root)
            or bound_resume != resume
            or expected_folds != tuple(item.fold for item in runtime_request.folds)
        ):
            _fail("SUCCESSOR_INPUT_INVALID")

    def _run_wave(
        self,
        *,
        wave: str,
        request: SuccessorFoldRequest,
        context: SuccessorStageContext,
        runner: "StageRunner",
        prior_refs: tuple[StageReceiptRef, ...],
        resume: bool,
    ) -> tuple[StageReceiptRef, ...]:
        """Always invoke the package-owned upstream runner with explicit priors.

        Same-process physical-wave resume is owned by
        ``successor_upstream_stage`` (exact resume + fresh receipt verify).
        This adapter never returns an in-memory tuple without that call.
        """

        self._assert_wave_binding(runtime_request=context.request, resume=resume)
        try:
            raw = self._dependencies.run_upstream_wave(
                wave=wave,
                request=request,
                context=context,
                runner=runner,
                public_apis=self._public_apis,
                prior_refs=prior_refs,
                resume=resume,
            )
            refs = _coerce_wave_refs(raw)
            _validate_wave_receipt_closure(
                wave=wave,
                refs=refs,
                request=context.request,
            )
        except SuccessorRuntimeError:
            raise
        except Exception:
            _fail("SUCCESSOR_STAGE_INVALID")
        return refs

    def verify_fold(
        self, *, execution: FoldExecution, context: SuccessorStageContext
    ) -> None:
        self._dependencies.verify_fold(
            execution=execution,
            context=context,
            public_apis=self._public_apis,
        )

    def run_summary(
        self,
        *,
        folds: tuple[FoldExecution, ...],
        context: SuccessorStageContext,
        resume: bool,
    ) -> GateExecution:
        return self._run_gate(
            run=self._dependencies.run_summary,
            verify=self._dependencies.verify_summary,
            folds=folds,
            prior_gates=(),
            context=context,
            resume=resume,
        )

    def run_reproducibility(
        self,
        *,
        folds: tuple[FoldExecution, ...],
        summary: GateExecution,
        context: SuccessorStageContext,
        resume: bool,
    ) -> GateExecution:
        return self._run_gate(
            run=self._dependencies.run_reproducibility,
            verify=self._dependencies.verify_reproducibility,
            folds=folds,
            prior_gates=(summary,),
            context=context,
            resume=resume,
        )

    def run_readiness(
        self,
        *,
        folds: tuple[FoldExecution, ...],
        summary: GateExecution,
        reproducibility: GateExecution,
        context: SuccessorStageContext,
        resume: bool,
    ) -> GateExecution:
        return self._run_gate(
            run=self._dependencies.run_readiness,
            verify=self._dependencies.verify_readiness,
            folds=folds,
            prior_gates=(summary, reproducibility),
            context=context,
            resume=resume,
        )

    def run_acceptance(
        self,
        *,
        folds: tuple[FoldExecution, ...],
        summary: GateExecution,
        reproducibility: GateExecution,
        readiness: GateExecution,
        context: SuccessorStageContext,
        resume: bool,
    ) -> GateExecution:
        return self._run_gate(
            run=self._dependencies.run_acceptance,
            verify=self._dependencies.verify_acceptance,
            folds=folds,
            prior_gates=(summary, reproducibility, readiness),
            context=context,
            resume=resume,
        )

    def verify_gate(
        self,
        *,
        gate: GateExecution,
        folds: tuple[FoldExecution, ...],
        prior_gates: tuple[GateExecution, ...],
        context: SuccessorStageContext,
    ) -> GateVerification:
        runner = self._runner(
            context=context, config=context.request.folds[0].config.config
        )
        result = self._dependencies.verify_gate(
            gate=gate,
            folds=folds,
            prior_gates=prior_gates,
            context=context,
            runner=runner,
            public_apis=self._public_apis,
        )
        if type(result) is not GateVerification:
            _fail("SUCCESSOR_GATE_FAILED")
        return result

    def _runner(
        self, *, context: SuccessorStageContext, config: LoadedM3Config
    ) -> "StageRunner":
        try:
            from quant.research.m3.orchestration import StageRunner
        except Exception:
            _fail("SUCCESSOR_INPUT_INVALID")
        if (
            self._dependencies.stage_runner_factory is not make_project_stage_runner
            or self._public_apis.stage_runner_type is not StageRunner
        ):
            _fail("SUCCESSOR_INPUT_INVALID")
        stage_root = project_stage_root(
            project_root=context.project_root,
            config=config,
        )
        runner = self._dependencies.stage_runner_factory(
            project_root=context.project_root,
            stage_root=stage_root,
            config=config,
        )
        if type(runner) is not StageRunner:
            _fail("SUCCESSOR_INPUT_INVALID")
        roots = getattr(runner, "_artifact_roots", None)
        actual_stage_root = getattr(runner, "_stage_root", None)
        if (
            type(roots) is not dict
            or roots != {"PROJECT": context.project_root}
            or not isinstance(actual_stage_root, Path)
            or actual_stage_root != stage_root
        ):
            _fail("SUCCESSOR_INPUT_INVALID")
        return runner

    def _run_gate(
        self,
        *,
        run: SuccessorProductionGateRunner,
        verify: SuccessorProductionGateVerifier,
        folds: tuple[FoldExecution, ...],
        prior_gates: tuple[GateExecution, ...],
        context: SuccessorStageContext,
        resume: bool,
    ) -> GateExecution:
        if not callable(run) or not callable(verify):
            _fail("SUCCESSOR_INPUT_INVALID")
        runner = self._runner(
            context=context, config=context.request.folds[0].config.config
        )
        gate = run(
            folds=folds,
            prior_gates=prior_gates,
            context=context,
            runner=runner,
            public_apis=self._public_apis,
            resume=resume,
        )
        if type(gate) is not GateExecution:
            _fail("SUCCESSOR_GATE_FAILED")
        _validate_gate_execution(
            gate.gate,
            gate,
            executions=folds,
            known=prior_gates,
        )
        verify(
            gate=gate,
            folds=folds,
            prior_gates=prior_gates,
            context=context,
            runner=runner,
            public_apis=self._public_apis,
        )
        return gate

    @staticmethod
    def _receipt(value: object) -> StageReceiptRef:
        if type(value) is not StageReceiptRef:
            _fail("SUCCESSOR_STAGE_INVALID")
        return value

    @staticmethod
    def _one_ref(
        refs: Sequence[StageReceiptRef], *, stage: str, horizon: int | None
    ) -> StageReceiptRef:
        found = tuple(item for item in refs if item.stage == stage and item.horizon == horizon)
        if len(found) != 1:
            _fail("SUCCESSOR_STAGE_INVALID")
        return found[0]


def _coerce_wave_refs(value: object) -> tuple[StageReceiptRef, ...]:
    if type(value) is not tuple or not value:
        raise ValueError
    if any(type(item) is not StageReceiptRef for item in value):
        raise ValueError
    refs = cast(tuple[StageReceiptRef, ...], value)
    if (
        tuple(item.node_id for item in refs)
        != tuple(sorted(item.node_id for item in refs))
        or len({item.node_id for item in refs}) != len(refs)
    ):
        raise ValueError
    return refs


def _work_receipt_belongs_to_fold(ref: StageReceiptRef, fold: str) -> bool:
    if ref.stage == "features":
        return ref.fold == fold
    if ref.stage in _WORK_PRE_FORMAL_STAGES:
        return ref.fold == fold
    return False


def _validate_wave_receipt_closure(
    *,
    wave: str,
    refs: tuple[StageReceiptRef, ...],
    request: SuccessorRuntimeRequest,
) -> None:
    if wave in _FORBIDDEN_PSEUDO_BUILDERS or wave not in {
        *_UPSTREAM_WAVES,
    }:
        raise ValueError
    if wave in _SHARED_SINGLE_WAVES:
        if len(refs) != 1 or refs[0].stage != wave or refs[0].horizon is not None:
            raise ValueError
        return
    if wave == _EXPERIMENT_ARTIFACTS_WAVE:
        expected_experiment_artifact_keys: set[_WaveReceiptKey] = {
            ("folds", None, None),
            *(("labels", None, horizon) for horizon in HORIZONS),
        }
        actual_experiment_artifact_keys: set[_WaveReceiptKey] = {
            (item.stage, item.fold, item.horizon) for item in refs
        }
        if (
            actual_experiment_artifact_keys != expected_experiment_artifact_keys
            or len(refs) != len(expected_experiment_artifact_keys)
        ):
            raise ValueError
        if any(item.fold is not None for item in refs):
            raise ValueError
        return
    if wave == _LABEL_RECONCILIATION_WAVE:
        expected_label_reconciliation_keys: set[_WaveReceiptKey] = {
            ("label-reconciliation", None, horizon) for horizon in HORIZONS
        }
        actual_label_reconciliation_keys: set[_WaveReceiptKey] = {
            (item.stage, item.fold, item.horizon) for item in refs
        }
        if (
            actual_label_reconciliation_keys != expected_label_reconciliation_keys
            or len(refs) != len(expected_label_reconciliation_keys)
        ):
            raise ValueError
        if any(item.fold is not None for item in refs):
            raise ValueError
        return
    if wave != _WORK_WAVE:
        raise ValueError
    folds = tuple(item.fold for item in request.folds)
    expected_work_keys: set[_WaveReceiptKey] = set()
    for fold in folds:
        expected_work_keys.add(("features", fold, None))
        for horizon in HORIZONS:
            for stage in _WORK_PRE_FORMAL_STAGES[1:]:
                expected_work_keys.add((stage, fold, horizon))
    actual_work_keys: set[_WaveReceiptKey] = {
        (item.stage, item.fold, item.horizon) for item in refs
    }
    if actual_work_keys != expected_work_keys or len(refs) != len(expected_work_keys):
        raise ValueError


def make_production_successor_stage_adapter(
    *,
    dependencies: SuccessorProductionDependencies,
    public_apis: SuccessorPublicApiBundle | None = None,
) -> ProductionSuccessorStageAdapter:
    """Construct the tracked concrete production adapter or fail closed."""

    return ProductionSuccessorStageAdapter(
        dependencies=dependencies,
        public_apis=public_apis,
    )


def make_canonical_successor_production_dependencies() -> SuccessorProductionDependencies:
    """Zero-arg factory: bind R2A upstream, R2S summary, and package downstream by ``is``."""

    from quant.research.m3 import successor_downstream_stage as downstream
    from quant.research.m3 import successor_upstream_stage as upstream

    return SuccessorProductionDependencies(
        stage_runner_factory=make_project_stage_runner,
        run_upstream_wave=upstream.run_successor_upstream_wave,
        run_formal_stage=downstream.run_successor_formal_stage,
        verify_fold=downstream.verify_successor_fold,
        run_summary=upstream.run_successor_formal_summary_gate,
        verify_summary=downstream.verify_successor_summary_gate,
        run_reproducibility=downstream.run_successor_reproducibility_gate,
        verify_reproducibility=downstream.verify_successor_reproducibility_gate,
        run_readiness=downstream.run_successor_readiness_gate,
        verify_readiness=downstream.verify_successor_readiness_gate,
        run_acceptance=downstream.run_successor_acceptance_gate,
        verify_acceptance=downstream.verify_successor_acceptance_gate,
        verify_gate=downstream.verify_successor_terminal_gate,
    )


def run_production_two_fold_successor(
    *,
    request: SuccessorRuntimeRequest,
    dependencies: SuccessorProductionDependencies,
    public_apis: SuccessorPublicApiBundle | None = None,
    resume: bool = True,
) -> SuccessorRunResult:
    """Run the frozen sequence through the package-owned concrete adapter."""

    adapter = make_production_successor_stage_adapter(
        dependencies=dependencies,
        public_apis=public_apis,
    )
    return run_two_fold_successor(request=request, api=adapter, resume=resume)


class FoldVerifier(Protocol):
    def __call__(
        self, *, execution: FoldExecution, context: SuccessorStageContext
    ) -> None: ...


class GateVerifier(Protocol):
    def __call__(
        self,
        *,
        gate: GateExecution,
        folds: tuple[FoldExecution, ...],
        prior_gates: tuple[GateExecution, ...],
        context: SuccessorStageContext,
    ) -> GateVerification: ...


def project_stage_root(*, project_root: Path, config: LoadedM3Config) -> Path:
    """Resolve the configured professional stage root below PROJECT only."""

    try:
        project = _real_directory(project_root)
        if type(config) is not LoadedM3Config:
            raise ValueError
        logical = config.section("tracking")["artifact_root"]
        if type(logical) is not str:
            raise ValueError
        relative = PurePosixPath(logical)
        _validate_relative(relative.as_posix())
        stage = _real_directory(project.joinpath(*relative.parts))
        if not stage.is_relative_to(project):
            raise ValueError
        return stage
    except Exception:
        _fail("SUCCESSOR_INPUT_INVALID")


def make_project_stage_runner(
    *, project_root: Path, stage_root: Path, config: LoadedM3Config
) -> "StageRunner":
    """Construct the shared runner with the frozen PROJECT-only root mapping.

    The import is intentionally local: importing the successor contract does
    not import optional research workers.  The returned object is the existing
    ``quant.research.m3.orchestration.StageRunner`` instance, not a replacement.
    """

    try:
        from quant.research.m3.orchestration import StageRunner

        project = _real_directory(project_root)
        stage = _real_directory(stage_root)
        if not stage.is_relative_to(project):
            raise ValueError
        return StageRunner(
            stage_root=stage,
            artifact_roots={"PROJECT": project},
            config=config,
        )
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_INPUT_INVALID")


def two_fold_identity(request: SuccessorRuntimeRequest) -> str:
    """Return the deterministic identity of the explicit two-fold input set."""

    from quant.research.m3.successor_upstream_stage import (
        validate_successor_toolchain_binding,
    )

    try:
        python_posix, dump_relative, dump_size, dump_sha256 = (
            validate_successor_toolchain_binding(
                project_root=request.project_root,
                toolchain=request.toolchain,
                fold_configs=tuple(item.config.config for item in request.folds),
            )
        )
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_INPUT_INVALID")
    values = [
        TWO_FOLD_IDENTITY_VERSION,
        [
            [
                item.fold,
                item.config.relative_path.as_posix(),
                item.config.config.raw_config_sha256,
                item.config.config.full_config_sha256,
                item.release.manifest.release_id,
                item.release.manifest_sha256,
            ]
            for item in request.folds
        ],
        list(HORIZONS),
        [
            "m3-successor-toolchain-identity-v1",
            python_posix,
            dump_relative,
            dump_size,
            dump_sha256,
            request.toolchain.timeout_seconds,
        ],
    ]
    return _sha256_json(values)


def run_two_fold_successor(
    *, request: SuccessorRuntimeRequest, api: SuccessorStageApi, resume: bool = True
) -> SuccessorRunResult:
    """Run the fixed fold→summary→repro→readiness→acceptance sequence."""

    required = (
        "run_fold",
        "verify_fold",
        "run_summary",
        "run_reproducibility",
        "run_readiness",
        "run_acceptance",
        "verify_gate",
    )
    if any(not callable(getattr(api, name, None)) for name in required):
        _fail("SUCCESSOR_INPUT_INVALID")
    if type(request) is not SuccessorRuntimeRequest or type(resume) is not bool:
        _fail("SUCCESSOR_INPUT_INVALID")
    _validate_request(request)
    canonical_stage_root = _resolve_canonical_g8_stage_root(request)
    terminal = _terminal_path(request)
    if terminal.exists():
        if not resume:
            _fail("SUCCESSOR_TERMINAL_ALREADY_COMPLETE")
        verified = verify_terminal_attestation(
            request=request,
            fold_verifier=api.verify_fold,
            gate_verifier=api.verify_gate,
        )
        return SuccessorRunResult(
            terminal_path=verified.terminal_path,
            attestation=verified.attestation,
            folds=_fold_executions_from_attestation(verified.attestation),
            gates=verified.attestation.gates,
            reused=True,
        )

    context = SuccessorStageContext(request=request, fold=None)
    executions: list[FoldExecution] = []
    for fold_request in request.folds:
        fold_context = SuccessorStageContext(request=request, fold=fold_request.fold)
        try:
            execution = api.run_fold(
                request=fold_request, context=fold_context, resume=resume
            )
            _validate_fold_execution(request, fold_request, execution)
            api.verify_fold(execution=execution, context=fold_context)
            try:
                _verify_receipts(
                    project_root=request.project_root,
                    controlled_output_root=request.controlled_output_root,
                    refs=execution.receipts,
                    canonical_stage_root=canonical_stage_root,
                )
            except SuccessorRuntimeError:
                _fail("SUCCESSOR_STAGE_INVALID")
        except SuccessorRuntimeError:
            raise
        except Exception:
            _fail("SUCCESSOR_STAGE_FAILED")
        executions.append(execution)
    folds = tuple(executions)

    gates: list[GateExecution] = []
    try:
        summary = api.run_summary(folds=folds, context=context, resume=resume)
        _validate_gate_execution("summary", summary, executions=folds, known=())
        _verify_receipts(
            project_root=request.project_root,
            controlled_output_root=request.controlled_output_root,
            refs=summary.receipt_refs,
            canonical_stage_root=canonical_stage_root,
        )
        _require_fresh_gate(
            api.verify_gate,
            summary,
            folds=folds,
            prior_gates=(),
            context=context,
        )
        gates.append(summary)

        reproducibility = api.run_reproducibility(
            folds=folds, summary=summary, context=context, resume=resume
        )
        _validate_gate_execution(
            "reproducibility", reproducibility, executions=folds, known=tuple(gates)
        )
        _verify_receipts(
            project_root=request.project_root,
            controlled_output_root=request.controlled_output_root,
            refs=reproducibility.receipt_refs,
            canonical_stage_root=canonical_stage_root,
        )
        _require_fresh_gate(
            api.verify_gate,
            reproducibility,
            folds=folds,
            prior_gates=tuple(gates),
            context=context,
        )
        gates.append(reproducibility)

        readiness = api.run_readiness(
            folds=folds,
            summary=summary,
            reproducibility=reproducibility,
            context=context,
            resume=resume,
        )
        _validate_gate_execution(
            "readiness", readiness, executions=folds, known=tuple(gates)
        )
        _verify_receipts(
            project_root=request.project_root,
            controlled_output_root=request.controlled_output_root,
            refs=readiness.receipt_refs,
            canonical_stage_root=canonical_stage_root,
        )
        _require_fresh_gate(
            api.verify_gate,
            readiness,
            folds=folds,
            prior_gates=tuple(gates),
            context=context,
        )
        gates.append(readiness)

        acceptance = api.run_acceptance(
            folds=folds,
            summary=summary,
            reproducibility=reproducibility,
            readiness=readiness,
            context=context,
            resume=resume,
        )
        _validate_gate_execution(
            "acceptance", acceptance, executions=folds, known=tuple(gates)
        )
        _verify_receipts(
            project_root=request.project_root,
            controlled_output_root=request.controlled_output_root,
            refs=acceptance.receipt_refs,
            canonical_stage_root=canonical_stage_root,
        )
        _require_fresh_gate(
            api.verify_gate,
            acceptance,
            folds=folds,
            prior_gates=tuple(gates),
            context=context,
        )
        gates.append(acceptance)
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_GATE_FAILED")

    attestation = _build_attestation(
        request=request, folds=folds, gates=tuple(gates),
    )
    _publish_terminal(request=request, attestation=attestation)
    verified = verify_terminal_attestation(
        request=request,
        fold_verifier=api.verify_fold,
        gate_verifier=api.verify_gate,
    )
    return SuccessorRunResult(
        terminal_path=verified.terminal_path,
        attestation=verified.attestation,
        folds=folds,
        gates=tuple(gates),
        reused=False,
    )


def verify_terminal_attestation(
    *, request: SuccessorRuntimeRequest, fold_verifier: FoldVerifier,
    gate_verifier: GateVerifier,
) -> VerifiedTerminalAttestation:
    """Freshly verify canonical terminal bytes, receipts, gates, and tree."""

    try:
        try:
            _validate_request(request)
        except SuccessorRuntimeError:
            _fail("SUCCESSOR_TERMINAL_INVALID")
        if not callable(fold_verifier) or not callable(gate_verifier):
            raise ValueError
        terminal = _terminal_path(request)
        raw = _read_regular_file(terminal)
        attestation = _parse_attestation(raw)
        expected_identity = two_fold_identity(request)
        if (
            attestation.two_fold_identity != expected_identity
            or attestation.attested_at != _utc_text(request.now)
            or attestation.runtime_identity != request.runtime_identity
            or attestation.controlled_output_root
            != _relative_to_project(request.controlled_output_root, request.project_root)
            or attestation.horizons != HORIZONS
        ):
            raise ValueError
        _validate_attestation_bindings(request, attestation)
        refs = {item.node_id: item for item in attestation.receipts}
        canonical_stage_root = _resolve_canonical_g8_stage_root(request)
        _verify_receipts(
            project_root=request.project_root,
            controlled_output_root=request.controlled_output_root,
            refs=attestation.receipts,
            canonical_stage_root=canonical_stage_root,
        )
        _verify_controlled_tree(
            request=request,
            refs=attestation.receipts,
            expected_tree_sha256=attestation.controlled_output_tree_sha256,
        )
        executions = _fold_executions_from_attestation(attestation)
        for execution in executions:
            fold_request = next(
                item for item in request.folds if item.fold == execution.fold
            )
            fold_context = SuccessorStageContext(request=request, fold=execution.fold)
            _require_fresh_fold(fold_verifier, execution, fold_context)
            _validate_fold_execution(request, fold_request, execution)
        prior_gates: list[GateExecution] = []
        for gate in attestation.gates:
            _require_fresh_gate(
                gate_verifier,
                gate,
                folds=executions,
                prior_gates=tuple(prior_gates),
                context=SuccessorStageContext(request=request, fold=None),
                failure_code="SUCCESSOR_TERMINAL_INVALID",
            )
            prior_gates.append(gate)
        # Ensure every reference is owned by one fold or one terminal gate.
        owned = {
            node_id
            for execution in executions
            for node_id in _fold_receipt_ids(execution)
        }
        owned.update(node_id for gate in attestation.gates for node_id in gate.receipt_node_ids)
        if owned != set(refs):
            raise ValueError
        return VerifiedTerminalAttestation(terminal_path=terminal, attestation=attestation)
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_TERMINAL_INVALID")


def _validate_request(request: SuccessorRuntimeRequest) -> None:
    try:
        project = _real_directory(request.project_root)
        controlled = _real_directory(request.controlled_output_root)
        if not controlled.is_relative_to(project):
            raise ValueError
        if _terminal_path(request).parent != controlled:
            raise ValueError
        scientific_identities: set[str] = set()
        release_identities: list[tuple[str, str]] = []
        for item in request.folds:
            config = item.config.config
            raw_path = project.joinpath(*item.config.relative_path.parts)
            raw = _read_regular_file(raw_path)
            if (
                config.raw_config_sha256 is None
                or hashlib.sha256(raw).hexdigest() != config.raw_config_sha256
                or not _is_hex64(config.full_config_sha256)
                or not _is_hex64(config.raw_config_sha256)
            ):
                raise ValueError
            fresh_config = load_m3_config(raw_path)
            if fresh_config != config:
                raise ValueError
            scientific_identities.add(config.scientific_config_sha256)
            fresh_release = verify_g1_release(release=item.release.release)
            if fresh_release != item.release:
                raise ValueError
            release_root = _real_directory(item.release.release.root)
            if not release_root.is_relative_to(project):
                raise ValueError
            if item.release.manifest.release_id != item.release.release.release_id:
                raise ValueError
            release_identities.append(
                (item.release.manifest.release_id, item.release.manifest_sha256)
            )
        # Existing summary/work contracts join folds on the scientific config
        # projection.  Raw/full identities are already closed independently
        # for every fold above and need not be artificially distinct.
        if len(scientific_identities) != 1:
            raise ValueError
        if len(release_identities) != 2 or len(set(release_identities)) != 2:
            raise ValueError
        # Canonical G8 must be uniquely resolved from both fold configs and
        # equal the controlled output root before any stage / worker work.
        _resolve_canonical_g8_stage_root(request)
        from quant.research.m3.successor_upstream_stage import (
            validate_successor_toolchain_binding,
        )

        # Toolchain must validate before any controlled root / worker work.
        validate_successor_toolchain_binding(
            project_root=project,
            toolchain=request.toolchain,
            fold_configs=tuple(item.config.config for item in request.folds),
        )
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_INPUT_INVALID")


def _validate_fold_execution(
    request: SuccessorRuntimeRequest,
    fold_request: SuccessorFoldRequest,
    execution: FoldExecution,
) -> None:
    try:
        if (
            type(execution) is not FoldExecution
            or execution.fold != fold_request.fold
            or execution.config_raw_sha256
            != fold_request.config.config.raw_config_sha256
            or execution.config_full_sha256
            != fold_request.config.config.full_config_sha256
            or execution.g1_release_id != fold_request.release.manifest.release_id
            or execution.g1_release_manifest_sha256 != fold_request.release.manifest_sha256
            or len(execution.work_identities) != 2
        ):
            raise ValueError
        for work in execution.work_identities:
            expected_work_key = compute_work_key(
                experiment_key=execution.experiment_key,
                fold=work.fold,
                horizon=work.horizon,
            )
            if work.work_key != expected_work_key:
                raise ValueError
        snapshot_refs = tuple(
            item
            for item in execution.receipts
            if item.stage == "snapshot" and item.horizon is None
        )
        experiment_refs = tuple(
            item
            for item in execution.receipts
            if item.stage == "experiment-identity" and item.horizon is None
        )
        if (
            len(snapshot_refs) != 1
            or len(experiment_refs) != 1
            or snapshot_refs[0].scope_key != execution.snapshot_id
            or experiment_refs[0].scope_key != execution.experiment_key
        ):
            raise ValueError
        expected_receipts: dict[tuple[str, int | None], int] = {}
        for stage in _REQUIRED_SHARED_STAGES:
            expected_receipts[(stage, None)] = 1
        expected_receipts[("features", None)] = 1
        for horizon in HORIZONS:
            expected_receipts[("labels", horizon)] = 1
            expected_receipts[("label-reconciliation", horizon)] = 1
            for stage in _HORIZON_WORK_STAGES:
                expected_receipts[(stage, horizon)] = 1
        observed: dict[tuple[str, int | None], int] = {}
        scope_by_stage = {
            "snapshot": "SNAPSHOT",
            "provider": "PROVIDER",
            "provider-validation": "PROVIDER",
            "experiment-identity": "EXPERIMENT",
            "folds": "EXPERIMENT",
            "features": "EXPERIMENT",
            "labels": "EXPERIMENT",
            "label-reconciliation": "EXPERIMENT",
            **{stage: "WORK" for stage in _HORIZON_WORK_STAGES},
        }
        for ref in execution.receipts:
            if ref.stage in _CROSS_FOLD_STAGES:
                if ref.fold is not None:
                    raise ValueError
            elif ref.fold != execution.fold:
                raise ValueError
            key = (ref.stage, ref.horizon)
            observed[key] = observed.get(key, 0) + 1
            if scope_by_stage.get(ref.stage) != ref.scope:
                raise ValueError
            if ref.stage in {"snapshot", "provider", "provider-validation"}:
                if ref.horizon is not None:
                    raise ValueError
            if ref.stage == "snapshot" and ref.scope_key != execution.snapshot_id:
                raise ValueError
            if ref.stage in {"experiment-identity", "folds", "features"}:
                if ref.scope != "EXPERIMENT" or ref.scope_key != execution.experiment_key:
                    raise ValueError
            if ref.stage == "labels":
                if ref.scope != "EXPERIMENT" or ref.scope_key != execution.experiment_key:
                    raise ValueError
            if ref.stage == "label-reconciliation":
                if ref.scope != "EXPERIMENT":
                    raise ValueError
            if ref.stage in _HORIZON_WORK_STAGES:
                if ref.scope != "WORK":
                    raise ValueError
                work = next(
                    item
                    for item in execution.work_identities
                    if item.horizon == ref.horizon
                )
                if ref.scope_key != work.work_key:
                    raise ValueError
        if observed != expected_receipts:
            raise ValueError
        if request.folds[0].fold == request.folds[1].fold:
            raise ValueError
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")


def _validate_gate_execution(
    expected_gate: GateName,
    gate: GateExecution,
    *,
    executions: tuple[FoldExecution, ...],
    known: tuple[GateExecution, ...],
) -> None:
    try:
        if type(gate) is not GateExecution or gate.gate != expected_gate:
            raise ValueError
        if gate.status != "PASS":
            _fail("SUCCESSOR_GATE_FAILED")
        refs = _lookup_refs(executions, known, gate)
        if gate.identity != compute_successor_gate_identity(
            gate=expected_gate,
            folds=executions,
            prior_gates=known,
        ):
            raise ValueError
        if expected_gate == "summary":
            experiment_keys = {execution.experiment_key for execution in executions}
            if len(refs) != 2 or {item.horizon for item in refs} != set(HORIZONS):
                raise ValueError
            if len(experiment_keys) != 1:
                raise ValueError
            if any(
                item.stage != "research-summary"
                or item.fold is not None
                or item.scope != "EXPERIMENT"
                or item.scope_key != next(iter(experiment_keys))
                for item in refs
            ):
                raise ValueError
        elif expected_gate == "reproducibility":
            pairs = {(item.fold, item.horizon) for item in refs}
            if len(refs) != 4 or pairs != {
                (execution.fold, horizon)
                for execution in executions
                for horizon in HORIZONS
            }:
                raise ValueError
            if any(
                item.stage != "reproducibility" or item.scope != "REPRO"
                for item in refs
            ):
                raise ValueError
            if len({item.scope_key for item in refs}) != len(refs):
                raise ValueError
        elif expected_gate == "readiness":
            # Single global readiness physical receipt (no fold dimension).
            # Aggregate two-fold closure stays on gate.identity only.
            if len(refs) != 1:
                raise ValueError
            item = refs[0]
            if (
                item.fold is not None
                or item.horizon is not None
                or item.stage != "readiness-evidence"
                or item.scope != "ACCEPTANCE"
                or not _is_hex64(item.scope_key)
            ):
                raise ValueError
        else:
            # acceptance_key is the public physical key; may differ from aggregate identity.
            if (
                len(refs) != 1
                or refs[0].stage != "acceptance"
                or refs[0].fold is not None
                or refs[0].scope != "ACCEPTANCE"
                or not _is_hex64(refs[0].scope_key)
            ):
                raise ValueError
        if any(item.scope not in {"EXPERIMENT", "REPRO", "ACCEPTANCE"} for item in refs):
            raise ValueError
        if any(not _is_hex64(item.scope_key) for item in refs):
            raise ValueError
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_GATE_FAILED")


def _lookup_refs(
    executions: tuple[FoldExecution, ...],
    known: tuple[GateExecution, ...],
    gate: GateExecution,
) -> tuple[StageReceiptRef, ...]:
    try:
        owned: dict[str, tuple[StageReceiptRef, tuple[str, str]]] = {}

        def claim(ref: StageReceiptRef, owner: tuple[str, str]) -> None:
            previous = owned.get(ref.node_id)
            if previous is not None:
                if previous[0] != ref or not _shared_receipt_duplicate_allowed(
                    ref,
                    previous[1],
                    owner,
                ):
                    raise ValueError
                return
            owned[ref.node_id] = (ref, owner)

        for execution in executions:
            for ref in execution.receipts:
                claim(ref, ("fold", execution.fold))
        for prior in known:
            for ref in prior.receipt_refs:
                claim(ref, ("gate", prior.gate))
        for ref in gate.receipt_refs:
            claim(ref, ("gate", gate.gate))
        return gate.receipt_refs
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_GATE_FAILED")


def _require_fresh_fold(
    verifier: FoldVerifier,
    execution: FoldExecution,
    context: SuccessorStageContext,
) -> None:
    try:
        verifier(execution=execution, context=context)
    except SuccessorRuntimeError:
        _fail("SUCCESSOR_TERMINAL_INVALID")
    except Exception:
        _fail("SUCCESSOR_TERMINAL_INVALID")


def _require_fresh_gate(
    verifier: GateVerifier,
    gate: GateExecution,
    *,
    folds: tuple[FoldExecution, ...],
    prior_gates: tuple[GateExecution, ...],
    context: SuccessorStageContext,
    failure_code: Literal["SUCCESSOR_GATE_FAILED", "SUCCESSOR_TERMINAL_INVALID"] = (
        "SUCCESSOR_GATE_FAILED"
    ),
) -> None:
    try:
        proof = verifier(
            gate=gate,
            folds=folds,
            prior_gates=prior_gates,
            context=context,
        )
        if (
            type(proof) is not GateVerification
            or proof.gate != gate.gate
            or proof.identity != gate.identity
            or proof.receipt_node_ids != gate.receipt_node_ids
            or proof.status != "PASS"
        ):
            raise ValueError
    except SuccessorRuntimeError:
        _fail(failure_code)
    except Exception:
        _fail(failure_code)


def _build_attestation(
    *,
    request: SuccessorRuntimeRequest,
    folds: tuple[FoldExecution, ...],
    gates: tuple[GateExecution, ...],
) -> TerminalAttestation:
    try:
        all_refs = [ref for execution in folds for ref in execution.receipts]
        all_refs.extend(ref for gate in gates for ref in gate.receipt_refs)
        _validate_global_receipt_ownership(
            project_root=request.project_root,
            folds=folds,
            gates=gates,
        )
        refs = _unique_refs(all_refs)
        canonical_stage_root = _resolve_canonical_g8_stage_root(request)
        _verify_receipts(
            project_root=request.project_root,
            controlled_output_root=request.controlled_output_root,
            refs=refs,
            canonical_stage_root=canonical_stage_root,
        )
        tree_sha = _controlled_tree_sha256(
            request=request, refs=refs,
        )
        config_bindings = tuple(
            _config_binding(item.config) for item in request.folds
        )
        fold_bindings = tuple(
            FoldBinding(
                fold=execution.fold,
                config_raw_sha256=execution.config_raw_sha256,
                config_full_sha256=execution.config_full_sha256,
                g1_release_id=execution.g1_release_id,
                g1_release_manifest_sha256=execution.g1_release_manifest_sha256,
                g1_release_root=_relative_to_project(
                    next(
                        item.release.release.root
                        for item in request.folds
                        if item.fold == execution.fold
                    ),
                    request.project_root,
                ),
                snapshot_id=execution.snapshot_id,
                experiment_key=execution.experiment_key,
                work_identities=execution.work_identities,
                receipt_node_ids=tuple(ref.node_id for ref in execution.receipts),
            )
            for execution in folds
        )
        attestation = TerminalAttestation(
            schema_version=TERMINAL_SCHEMA,
            two_fold_identity=two_fold_identity(request),
            attested_at=_utc_text(request.now),
            terminal_status="PASS",
            runtime_identity=request.runtime_identity,
            configs=config_bindings,
            folds=fold_bindings,
            horizons=HORIZONS,
            receipts=refs,
            gates=gates,
            controlled_output_root=_relative_to_project(
                request.controlled_output_root, request.project_root
            ),
            controlled_output_tree_sha256=tree_sha,
        )
        _validate_attestation_bindings(request, attestation)
        return attestation
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_TERMINAL_INVALID")


def _publish_terminal(
    *, request: SuccessorRuntimeRequest, attestation: TerminalAttestation
) -> None:
    terminal = _terminal_path(request)
    raw = _canonical_bytes(attestation)
    temp: Path | None = None
    try:
        if terminal.exists():
            if _read_regular_file(terminal) != raw:
                _fail("SUCCESSOR_TERMINAL_CONFLICT")
            return
        fd, name = tempfile.mkstemp(
            prefix=f".{TERMINAL_FILENAME}.", suffix=".tmp", dir=str(terminal.parent)
        )
        temp = Path(name)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, terminal)
        except FileExistsError:
            if _read_regular_file(terminal) != raw:
                _fail("SUCCESSOR_TERMINAL_CONFLICT")
        except OSError:
            _fail("SUCCESSOR_TERMINAL_PUBLISH_FAILED")
        _fsync_directory(terminal.parent)
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_TERMINAL_PUBLISH_FAILED")
    finally:
        if temp is not None:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                # A leftover temporary item is itself a terminal failure.
                raise SuccessorRuntimeError("SUCCESSOR_TERMINAL_PUBLISH_FAILED") from None


def _validate_attestation_bindings(
    request: SuccessorRuntimeRequest, attestation: TerminalAttestation
) -> None:
    try:
        expected_configs = tuple(_config_binding(item.config) for item in request.folds)
        if attestation.configs != expected_configs:
            raise ValueError
        if tuple(item.fold for item in attestation.folds) != tuple(
            item.fold for item in request.folds
        ):
            raise ValueError
        if len({item.fold for item in attestation.folds}) != 2:
            raise ValueError
        if tuple(item.gate for item in attestation.gates) != _GATES:
            raise ValueError
        refs = {item.node_id: item for item in attestation.receipts}
        if len(refs) != len(attestation.receipts):
            raise ValueError
        if tuple(refs) != tuple(sorted(refs)):
            raise ValueError
        executions: list[FoldExecution] = []
        for fold_binding, fold_request in zip(
            attestation.folds, request.folds, strict=True
        ):
            if (
                fold_binding.config_raw_sha256 != fold_request.config.config.raw_config_sha256
                or fold_binding.config_full_sha256 != fold_request.config.config.full_config_sha256
                or fold_binding.g1_release_id != fold_request.release.manifest.release_id
                or fold_binding.g1_release_manifest_sha256 != fold_request.release.manifest_sha256
                or fold_binding.g1_release_root
                != _relative_to_project(fold_request.release.release.root, request.project_root)
                or len(fold_binding.receipt_node_ids) != len(set(fold_binding.receipt_node_ids))
            ):
                raise ValueError
            execution = _fold_execution_from_binding(attestation, fold_binding)
            _validate_fold_execution(request, fold_request, execution)
            executions.append(execution)
        execution_tuple = tuple(executions)
        for index, gate in enumerate(attestation.gates):
            _validate_gate_execution(
                _GATES[index],
                gate,
                executions=execution_tuple,
                known=attestation.gates[:index],
            )
        _validate_global_receipt_ownership(
            project_root=request.project_root,
            folds=execution_tuple,
            gates=attestation.gates,
        )
        gate_ids = {
            node_id for gate in attestation.gates for node_id in gate.receipt_node_ids
        }
        if len(gate_ids) != sum(len(gate.receipt_node_ids) for gate in attestation.gates):
            raise ValueError
        fold_ids = {
            node_id for execution in executions for node_id in _fold_receipt_ids(execution)
        }
        if gate_ids & fold_ids or fold_ids | gate_ids != set(refs):
            raise ValueError
        for gate in attestation.gates:
            if any(
                node_id not in refs or refs[node_id] != ref
                for ref in gate.receipt_refs
                for node_id in (ref.node_id,)
            ):
                raise ValueError
    except Exception:
        _fail("SUCCESSOR_TERMINAL_INVALID")


def _fold_executions_from_attestation(
    attestation: TerminalAttestation,
) -> tuple[FoldExecution, ...]:
    return tuple(_fold_execution_from_binding(attestation, item) for item in attestation.folds)


def _fold_execution_from_binding(
    attestation: TerminalAttestation, binding: FoldBinding
) -> FoldExecution:
    refs = {item.node_id: item for item in attestation.receipts}
    return FoldExecution(
        fold=binding.fold,
        config_raw_sha256=binding.config_raw_sha256,
        config_full_sha256=binding.config_full_sha256,
        g1_release_id=binding.g1_release_id,
        g1_release_manifest_sha256=binding.g1_release_manifest_sha256,
        snapshot_id=binding.snapshot_id,
        experiment_key=binding.experiment_key,
        work_identities=binding.work_identities,
        receipts=tuple(refs[item] for item in binding.receipt_node_ids),
    )


def _fold_receipt_ids(execution: FoldExecution) -> tuple[str, ...]:
    return tuple(item.node_id for item in execution.receipts)


def _validate_global_receipt_ownership(
    *,
    project_root: Path,
    folds: tuple[FoldExecution, ...],
    gates: tuple[GateExecution, ...],
) -> None:
    """Reject path, bytes, semantic-owner and node aliases across all refs."""

    try:
        project = _real_directory(project_root)
        entries: list[tuple[StageReceiptRef, tuple[str, str]]] = []
        for execution in folds:
            entries.extend(
                (ref, ("fold", execution.fold)) for ref in execution.receipts
            )
        for gate in gates:
            entries.extend(
                (ref, ("gate", gate.gate)) for ref in gate.receipt_refs
            )
        by_node: dict[str, tuple[StageReceiptRef, tuple[str, str]]] = {}
        by_path: dict[Path, tuple[StageReceiptRef, tuple[str, str]]] = {}
        by_bytes: dict[str, tuple[StageReceiptRef, tuple[str, str]]] = {}
        by_owner: dict[
            tuple[str, str, str, str | None, int | None],
            tuple[StageReceiptRef, tuple[str, str]],
        ] = {}
        for ref, owner in entries:
            previous_node = by_node.get(ref.node_id)
            if previous_node is not None:
                if previous_node[0] != ref or not _shared_receipt_duplicate_allowed(
                    ref, previous_node[1], owner
                ):
                    raise ValueError
            else:
                by_node[ref.node_id] = (ref, owner)
            physical_path = _path_from_relative(
                project, ref.relative_path
            ).resolve(strict=False)
            previous_path = by_path.get(physical_path)
            if previous_path is not None and previous_path[0].node_id != ref.node_id:
                raise ValueError
            by_path[physical_path] = (ref, owner)
            previous_bytes = by_bytes.get(ref.sha256)
            if previous_bytes is not None and previous_bytes[0].node_id != ref.node_id:
                raise ValueError
            by_bytes[ref.sha256] = (ref, owner)
            semantic_owner = (
                ref.stage,
                ref.scope,
                ref.scope_key,
                ref.fold,
                ref.horizon,
            )
            previous_owner = by_owner.get(semantic_owner)
            if (
                previous_owner is not None
                and previous_owner[0].node_id != ref.node_id
            ):
                raise ValueError
            by_owner[semantic_owner] = (ref, owner)
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_TERMINAL_INVALID")


def _shared_receipt_duplicate_allowed(
    ref: StageReceiptRef,
    first_owner: tuple[str, str],
    second_owner: tuple[str, str],
) -> bool:
    return (
        ref.stage in _SHARED_RECEIPT_STAGES
        and ref.fold is None
        and first_owner[0] == "fold"
        and second_owner[0] == "fold"
        and first_owner[1] != second_owner[1]
    )


def _unique_refs(refs: Sequence[StageReceiptRef]) -> tuple[StageReceiptRef, ...]:
    by_id: dict[str, StageReceiptRef] = {}
    by_path: dict[str, str] = {}
    by_bytes: dict[str, str] = {}
    by_owner: dict[tuple[str, str, str, str | None, int | None], str] = {}
    for ref in refs:
        previous = by_id.get(ref.node_id)
        if previous is not None and previous != ref:
            _fail("SUCCESSOR_TERMINAL_INVALID")
        previous_path = by_path.get(ref.relative_path)
        if previous_path is not None and previous_path != ref.node_id:
            _fail("SUCCESSOR_TERMINAL_INVALID")
        by_path[ref.relative_path] = ref.node_id
        previous_bytes = by_bytes.get(ref.sha256)
        if previous_bytes is not None and previous_bytes != ref.node_id:
            _fail("SUCCESSOR_TERMINAL_INVALID")
        by_bytes[ref.sha256] = ref.node_id
        semantic_owner = (
            ref.stage,
            ref.scope,
            ref.scope_key,
            ref.fold,
            ref.horizon,
        )
        previous_owner = by_owner.get(semantic_owner)
        if previous_owner is not None and previous_owner != ref.node_id:
            _fail("SUCCESSOR_TERMINAL_INVALID")
        by_owner[semantic_owner] = ref.node_id
        by_id[ref.node_id] = ref
    return tuple(by_id[item] for item in sorted(by_id))


def _verify_receipts(
    *,
    project_root: Path,
    controlled_output_root: Path,
    refs: Sequence[StageReceiptRef],
    canonical_stage_root: Path,
) -> Mapping[str, StageReceipt]:
    try:
        project = _real_directory(project_root)
        controlled = _real_directory(controlled_output_root)
        canonical = _real_directory(canonical_stage_root)
        if canonical.resolve(strict=True) != controlled.resolve(strict=True):
            raise ValueError
        result: dict[str, StageReceipt] = {}
        for ref in refs:
            path = _path_from_relative(project, ref.relative_path)
            if not path.is_relative_to(controlled):
                raise ValueError
            roots = _artifact_roots_for_receipt_stage(
                stage=ref.stage,
                project_root=project,
                canonical_stage_root=canonical,
            )
            expected_alias = "G8" if ref.stage == "acceptance" else "PROJECT"
            verified = verify_stage_receipt_with_bytes(
                receipt_path=path,
                artifact_roots=roots,
            )
            if (
                verified is None
                or verified.sha256 != ref.sha256
                or verified.receipt.stage != ref.stage
                or verified.receipt.scope != ref.scope
                or verified.receipt.scope_key != ref.scope_key
                or any(
                    digest.root_alias != expected_alias
                    for digest in (*verified.receipt.inputs, *verified.receipt.outputs)
                )
            ):
                raise ValueError
            if any(
                not path_for_artifact_digest(
                    digest, artifact_roots=dict(roots)
                ).is_relative_to(controlled)
                for digest in verified.receipt.outputs
            ):
                raise ValueError
            result[ref.node_id] = verified.receipt
        return MappingProxyType(result)
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_TERMINAL_INVALID")


def _verify_controlled_tree(
    *,
    request: SuccessorRuntimeRequest,
    refs: Sequence[StageReceiptRef],
    expected_tree_sha256: str,
) -> None:
    actual = _controlled_tree_sha256(request=request, refs=refs)
    if actual != expected_tree_sha256:
        _fail("SUCCESSOR_TERMINAL_INVALID")


def _controlled_tree_sha256(
    *, request: SuccessorRuntimeRequest, refs: Sequence[StageReceiptRef]
) -> str:
    try:
        project = _real_directory(request.project_root)
        controlled = _real_directory(request.controlled_output_root)
        canonical = _resolve_canonical_g8_stage_root(request)
        expected_files: set[str] = set()
        for ref in refs:
            receipt_path = _path_from_relative(project, ref.relative_path)
            expected_files.add(_relative_to_project(receipt_path, controlled))
            roots = _artifact_roots_for_receipt_stage(
                stage=ref.stage,
                project_root=project,
                canonical_stage_root=canonical,
            )
            verified = verify_stage_receipt_with_bytes(
                receipt_path=receipt_path,
                artifact_roots=roots,
            )
            if verified is None:
                raise ValueError
            for digest in verified.receipt.outputs:
                path = path_for_artifact_digest(
                    digest, artifact_roots=dict(roots)
                )
                if path.is_relative_to(controlled):
                    expected_files.add(_relative_to_project(path, controlled))
        entries = _walk_controlled_tree(controlled)
        actual_files = {item[0] for item in entries if item[1] == "F"}
        actual_directories = {item[0] for item in entries if item[1] == "D"}
        if actual_files - expected_files:
            raise ValueError
        if expected_files - actual_files:
            raise ValueError
        expected_directories = _parent_directories(expected_files)
        if any(
            relative not in expected_directories
            and relative not in _CONTROLLED_RUNTIME_DIRECTORIES
            and not _is_stage_lock_directory(relative)
            for relative in actual_directories
        ):
            raise ValueError
        lines = [f"{TREE_DIGEST_VERSION}\n".encode("ascii")]
        for relative, kind, size, entry_digest in entries:
            if kind == "D":
                lines.append(f"D\0{relative}\n".encode("utf-8"))
            else:
                lines.append(
                    f"F\0{relative}\0{size}\0{entry_digest}\n".encode("utf-8")
                )
        return hashlib.sha256(b"".join(lines)).hexdigest()
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_TERMINAL_INVALID")


def _parent_directories(files: set[str]) -> set[str]:
    directories = {""}
    for relative in files:
        path = PurePosixPath(relative)
        directories.update(
            str(parent)
            for parent in path.parents
            if str(parent) != "."
        )
    return directories


def _is_stage_lock_directory(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    return (
        len(parts) == 2
        and parts[0] == ".stage-locks"
        and _is_hex64(parts[1])
    )


def _walk_controlled_tree(root: Path) -> tuple[tuple[str, Literal["D", "F"], int, str], ...]:
    result: list[tuple[str, Literal["D", "F"], int, str]] = []

    def visit(directory: Path) -> None:
        try:
            children = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError:
            raise ValueError from None
        for entry in children:
            relative = Path(entry.path).resolve(strict=False).relative_to(root).as_posix()
            parts = PurePosixPath(relative).parts
            if entry.name == TERMINAL_FILENAME and relative == TERMINAL_FILENAME:
                continue
            if (".stage-tmp" in parts and len(parts) > 1) or (
                parts and parts[-1].endswith(".tmp")
            ):
                raise ValueError
            if any(
                part.startswith(".")
                and part not in {".stage-locks", ".stage-tmp"}
                for part in parts
            ):
                raise ValueError
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode) or _is_reparse(info):
                raise ValueError
            if stat.S_ISDIR(info.st_mode):
                result.append((relative, "D", 0, ""))
                visit(Path(entry.path))
            elif stat.S_ISREG(info.st_mode):
                if not _regular_file_link_count_allowed(info.st_nlink):
                    raise ValueError
                raw = _read_regular_file(Path(entry.path))
                result.append((relative, "F", len(raw), hashlib.sha256(raw).hexdigest()))
            else:
                raise ValueError

    visit(root)
    return tuple(sorted(result, key=lambda item: item[0]))


def _config_binding(config_input: SuccessorConfigInput) -> ConfigBinding:
    config = config_input.config
    raw = config.raw_config_sha256
    if raw is None:
        _fail("SUCCESSOR_CONFIG_INVALID")
    return ConfigBinding(
        relative_path=config_input.relative_path.as_posix(),
        config_version=config.config_version,
        raw_config_sha256=raw,
        full_config_sha256=config.full_config_sha256,
        scientific_config_sha256=config.scientific_config_sha256,
    )


def _terminal_path(request: SuccessorRuntimeRequest) -> Path:
    return request.controlled_output_root.resolve(strict=True) / TERMINAL_FILENAME


def _parse_attestation(raw: bytes) -> TerminalAttestation:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        if type(value) is not dict or _canonical_bytes(value) != raw:
            raise ValueError
        root = _exact_object(
            value,
            {
                "schema_version",
                "two_fold_identity",
                "attested_at",
                "terminal_status",
                "runtime_identity",
                "configs",
                "folds",
                "horizons",
                "receipts",
                "gates",
                "controlled_output_root",
                "controlled_output_tree_sha256",
            },
        )
        runtime = _exact_object(
            root["runtime_identity"],
            {
                "code_version",
                "dependency_fingerprint_sha256",
                "provider_runtime_fingerprint_sha256",
            },
        )
        configs = tuple(
            ConfigBinding(
                **cast(dict[str, Any], _exact_object(
                    item,
                    {
                        "relative_path",
                        "config_version",
                        "raw_config_sha256",
                        "full_config_sha256",
                        "scientific_config_sha256",
                    },
                )))
            for item in _exact_list(root["configs"])
        )
        folds: list[FoldBinding] = []
        for item in _exact_list(root["folds"]):
            body = _exact_object(
                item,
                {
                    "fold",
                    "config_raw_sha256",
                    "config_full_sha256",
                    "g1_release_id",
                    "g1_release_manifest_sha256",
                    "g1_release_root",
                    "snapshot_id",
                    "experiment_key",
                    "work_identities",
                    "receipt_node_ids",
                },
            )
            work = tuple(
                WorkIdentity(**cast(dict[str, Any], _exact_object(
                    child, {"fold", "horizon", "work_key"}
                )))
                for child in _exact_list(body["work_identities"])
            )
            folds.append(
                FoldBinding(
                    fold=cast(str, body["fold"]),
                    config_raw_sha256=cast(str, body["config_raw_sha256"]),
                    config_full_sha256=cast(str, body["config_full_sha256"]),
                    g1_release_id=cast(str, body["g1_release_id"]),
                    g1_release_manifest_sha256=cast(
                        str, body["g1_release_manifest_sha256"]
                    ),
                    g1_release_root=cast(str, body["g1_release_root"]),
                    snapshot_id=cast(str, body["snapshot_id"]),
                    experiment_key=cast(str, body["experiment_key"]),
                    work_identities=work,
                    receipt_node_ids=tuple(
                        cast(str, item)
                        for item in _exact_list(body["receipt_node_ids"])
                    ),
                )
            )
        receipts = tuple(
            StageReceiptRef(
                **cast(dict[str, Any], _exact_object(
                    item,
                    {
                        "node_id",
                        "stage",
                        "scope",
                        "scope_key",
                        "relative_path",
                        "sha256",
                        "fold",
                        "horizon",
                    },
                )))
            for item in _exact_list(root["receipts"])
        )
        gates_list: list[GateExecution] = []
        for item in _exact_list(root["gates"]):
            body = _exact_object(
                item, {"gate", "status", "identity", "receipt_refs"}
            )
            gate_refs = tuple(
                StageReceiptRef(
                    **cast(
                        dict[str, Any],
                        _exact_object(
                            child,
                            {
                                "node_id",
                                "stage",
                                "scope",
                                "scope_key",
                                "relative_path",
                                "sha256",
                                "fold",
                                "horizon",
                            },
                        ),
                    )
                )
                for child in _exact_list(body["receipt_refs"])
            )
            gates_list.append(
                GateExecution(
                    gate=cast(GateName, body["gate"]),
                    status=cast(GateStatus, body["status"]),
                    identity=cast(str, body["identity"]),
                    receipt_refs=gate_refs,
                )
            )
        gates = tuple(gates_list)
        return TerminalAttestation(
            schema_version=cast(Literal["m3-successor-terminal-v1"], root["schema_version"]),
            two_fold_identity=cast(str, root["two_fold_identity"]),
            attested_at=cast(str, root["attested_at"]),
            terminal_status=cast(Literal["PASS"], root["terminal_status"]),
            runtime_identity=SuccessorRuntimeIdentity(**cast(dict[str, Any], runtime)),
            configs=configs,
            folds=tuple(folds),
            horizons=tuple(cast(int, item) for item in _exact_list(root["horizons"])),
            receipts=receipts,
            gates=gates,
            controlled_output_root=cast(str, root["controlled_output_root"]),
            controlled_output_tree_sha256=cast(str, root["controlled_output_tree_sha256"]),
        )
    except Exception:
        _fail("SUCCESSOR_TERMINAL_INVALID")


def _exact_object(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError
    return cast(dict[str, object], value)


def _exact_list(value: object) -> list[object]:
    if type(value) is not list:
        raise ValueError
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        asdict(cast(Any, value))
        if hasattr(value, "__dataclass_fields__")
        else value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _real_directory(path: Path) -> Path:
    absolute = _absolute_no_links(path)
    resolved = absolute.resolve(strict=True)
    info = resolved.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or resolved.is_symlink()
        or _is_reparse(info)
    ):
        raise ValueError
    return resolved


def _read_regular_file(path: Path) -> bytes:
    absolute = _absolute_no_links(path)
    resolved = absolute.resolve(strict=True)
    info = resolved.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or resolved.is_symlink()
        or _is_reparse(info)
        or not _regular_file_link_count_allowed(info.st_nlink)
    ):
        raise ValueError
    return resolved.read_bytes()


def _regular_file_link_count_allowed(nlink: int) -> bool:
    if sys.platform == "win32":
        return nlink in {0, 1}
    return nlink == 1


def _is_reparse(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _path_from_relative(root: Path, relative: str) -> Path:
    _validate_relative(relative)
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    absolute = _absolute_no_links(candidate)
    resolved = absolute.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)):
        raise ValueError
    return resolved


def _absolute_no_links(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    try:
        for part in absolute.parts[1:]:
            current /= part
            info = os.lstat(current)
            if stat.S_ISLNK(info.st_mode) or _is_reparse(info):
                raise ValueError
    except (OSError, ValueError):
        raise ValueError from None
    return absolute


def _relative_to_project(path: Path, root: Path) -> str:
    return path.resolve(strict=True).relative_to(root.resolve(strict=True)).as_posix()


def _validate_relative(value: str, *, require_prefix: str | None = None) -> None:
    if (
        type(value) is not str
        or not value
        or "\\" in value
        or ":" in value
    ):
        raise ValueError("invalid relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix() or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError("invalid relative path")
    if require_prefix is not None and not value.startswith(require_prefix):
        raise ValueError("invalid relative path prefix")


def _is_hex64(value: object) -> bool:
    return type(value) is str and _HEX64_RE.fullmatch(value) is not None


def _validate_utc(value: object) -> None:
    if (
        type(value) is not dt.datetime
        or value.tzinfo is None
        or value.utcoffset() != dt.timedelta(0)
    ):
        raise ValueError("now must be timezone-aware UTC")


def _utc_text(value: dt.datetime) -> str:
    _validate_utc(value)
    return value.astimezone(dt.timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _is_canonical_utc_text(value: object) -> bool:
    if type(value) is not str or not value.endswith("Z"):
        return False
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return _utc_text(parsed) == value


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _fail(code: str) -> NoReturn:
    raise SuccessorRuntimeError(code) from None


__all__ = [
    "ConfigBinding",
    "FoldExecution",
    "FoldBinding",
    "GateExecution",
    "GateName",
    "GateVerification",
    "HORIZONS",
    "ProductionSuccessorStageAdapter",
    "StageReceiptRef",
    "SuccessorProductionDependencies",
    "SuccessorProductionFoldVerifier",
    "SuccessorProductionGateRunner",
    "SuccessorProductionGateVerifier",
    "SuccessorProductionFormalStageRunner",
    "SuccessorProductionWaveRunner",
    "SuccessorProductionStageRunnerFactory",
    "SuccessorPublicApiBundle",
    "SuccessorConfigInput",
    "SuccessorFoldRequest",
    "SuccessorRunResult",
    "SuccessorRuntimeError",
    "SuccessorRuntimeIdentity",
    "SuccessorRuntimeRequest",
    "SuccessorStageApi",
    "SuccessorStageContext",
    "TerminalAttestation",
    "VerifiedTerminalAttestation",
    "WorkIdentity",
    "compute_successor_gate_identity",
    "make_canonical_successor_production_dependencies",
    "make_production_successor_stage_adapter",
    "make_public_successor_api_bundle",
    "make_project_stage_runner",
    "project_stage_root",
    "run_production_two_fold_successor",
    "run_two_fold_successor",
    "two_fold_identity",
    "verify_terminal_attestation",
]
