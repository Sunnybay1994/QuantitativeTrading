"""G8 stage contracts and crash-safe snapshot publication prerequisite.

Provider and experiment continuation builders are intentionally deferred: their
static identities depend on receipts produced by earlier stages.  They must be
implemented as separately verified waves, never with surrogate plan hashes.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Literal, TypeAlias, cast

from quant.data._journal_lock import hold_journal_writer_lock
from quant.data.m3_release import VerifiedG1Release, commit_directory_noreplace
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    ExperimentIdentitySpec,
    LabelReconciliationSpec,
    ProviderBuildSpec,
    ProviderValidationSpec,
    SnapshotBuildResult,
    SnapshotRequestRecordV1,
    VerifiedEvaluationArtifact,
    VerifiedExperimentIdentity,
    VerifiedFoldPlanArtifact,
    VerifiedLabelArtifact,
    VerifiedLabelReconciliationArtifact,
    VerifiedProviderArtifact,
    VerifiedProviderValidationArtifact,
    VerifiedSnapshotArtifact,
)
from quant.research.m3.run_state import (
    ArtifactDigest,
    Scope,
    StageReceipt,
    compute_provider_key,
    compute_provider_validation_key,
    compute_label_reconciliation_key,
    compute_experiment_key,
    compute_work_key,
    publish_stage_receipt,
    verify_stage_receipt,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleEvaluationArtifact,
    VerifiedDevelopmentExampleExperimentIdentity,
    VerifiedDevelopmentExampleFoldPlanArtifact,
    VerifiedDevelopmentExampleG1Release,
    VerifiedDevelopmentExampleLabelArtifact,
    VerifiedDevelopmentExampleLabelReconciliationArtifact,
    VerifiedDevelopmentExampleProviderArtifact,
    VerifiedDevelopmentExampleProviderValidationArtifact,
    VerifiedDevelopmentExampleSnapshotArtifact,
    compute_development_provider_key,
    compute_development_provider_validation_key,
    compute_development_label_reconciliation_key,
    compute_development_experiment_key,
    verify_development_example_g1_release,
)
from quant.research.m3.snapshot import (
    read_snapshot_request_record,
    snapshot_request_record_bytes,
)

_NODE_PATTERN = re.compile(r"^[a-z0-9._-]+$")
_ROOT_ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_HEX64 = frozenset("0123456789abcdef")


class M3StageRunnerError(ValueError):
    """Stable G8A/G8B boundary error."""

    _CODES = frozenset({
        "STAGE_INPUT_INVALID",
        "STAGE_LOCK_FAILED",
        "STAGE_BUILD_FAILED",
        "STAGE_OUTPUT_INVALID",
        "STAGE_PUBLISH_FAILED",
        "STAGE_RECOVERY_CONFLICT",
        "STAGE_ALREADY_COMPLETE",
    })

    def __init__(self, code: str) -> None:
        if code not in self._CODES:
            raise ValueError("unknown stage runner error code")
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"M3StageRunnerError({self.code!r})"


@dataclass(frozen=True)
class OutputSpec:
    relative_path: str
    kind: Literal["FILE", "TREE"]
    closure_manifest: str | None

    def __post_init__(self) -> None:
        _validate_relative(self.relative_path, allow_dot=False)
        if self.kind not in {"FILE", "TREE"}:
            raise ValueError("output kind 非法")
        if self.kind == "FILE" and self.closure_manifest is not None:
            raise ValueError("FILE output 不得声明 closure manifest")
        if self.kind == "TREE":
            if type(self.closure_manifest) is not str:
                raise ValueError("TREE output 必须声明 closure manifest")
            _validate_relative(self.closure_manifest, allow_dot=False)


@dataclass(frozen=True)
class StageSpec:
    name: str
    scope: Scope
    dependencies: tuple[str, ...]
    outputs: tuple[OutputSpec, ...]

    def __post_init__(self) -> None:
        _validate_node_id(self.name)
        _validate_scope(self.scope)
        _validate_name_tuple(self.dependencies, label="stage dependencies")
        _validate_outputs(self.outputs)


@dataclass(frozen=True)
class StaticDirectoryPublication:
    final_directory: str

    def __post_init__(self) -> None:
        _validate_relative(self.final_directory, allow_dot=False)


@dataclass(frozen=True)
class SnapshotContentPublication:
    content_directory_parent: Literal["snapshots"]
    request_record_path: str
    manifest_relative_path: Literal["manifest.json"]
    content_id_field: Literal["snapshot_id"]

    def __post_init__(self) -> None:
        if self.content_directory_parent != "snapshots":
            raise ValueError("snapshot content parent 非法")
        _validate_relative(self.request_record_path, allow_dot=False)
        if not self.request_record_path.startswith("snapshot-requests/"):
            raise ValueError("snapshot request path 非法")
        if self.manifest_relative_path != "manifest.json":
            raise ValueError("snapshot manifest path 非法")
        if self.content_id_field != "snapshot_id":
            raise ValueError("snapshot content id field 非法")


PublicationSpec: TypeAlias = StaticDirectoryPublication | SnapshotContentPublication


@dataclass(frozen=True)
class ExternalInput:
    artifact: ArtifactDigest

    def __post_init__(self) -> None:
        if type(self.artifact) is not ArtifactDigest:
            raise ValueError("external input artifact 非法")


@dataclass(frozen=True)
class StageOutputInput:
    producer_node_id: str
    root_alias: str
    relative_path: str

    def __post_init__(self) -> None:
        _validate_node_id(self.producer_node_id)
        if type(self.root_alias) is not str or not self.root_alias:
            raise ValueError("stage output root alias 非法")
        _validate_relative(self.relative_path, allow_dot=False)


InputSpec: TypeAlias = ExternalInput | StageOutputInput


@dataclass(frozen=True)
class StageNode:
    node_id: str
    spec_name: str
    scope: Scope
    scope_key: str
    fold: str | None
    horizon: int | None
    dependencies: tuple[str, ...]
    inputs: tuple[InputSpec, ...]
    publication: PublicationSpec
    output_specs: tuple[OutputSpec, ...]
    receipt_path: str

    def __post_init__(self) -> None:
        _validate_node_id(self.node_id)
        _validate_node_id(self.spec_name)
        _validate_scope(self.scope)
        _require_hex64(self.scope_key)
        if self.fold is not None and (type(self.fold) is not str or not self.fold):
            raise ValueError("node fold 非法")
        if self.horizon is not None and (
            type(self.horizon) is not int or self.horizon <= 0
        ):
            raise ValueError("node horizon 非法")
        _validate_name_tuple(self.dependencies, label="node dependencies")
        if type(self.inputs) is not tuple or any(
            type(item) not in {ExternalInput, StageOutputInput} for item in self.inputs
        ):
            raise ValueError("node inputs 非法")
        if type(self.publication) not in {
            StaticDirectoryPublication, SnapshotContentPublication,
        }:
            raise ValueError("node publication 非法")
        _validate_outputs(self.output_specs)
        _validate_relative(self.receipt_path, allow_dot=False)
        if not self.receipt_path.startswith("receipts/"):
            raise ValueError("node receipt path 非法")
        for item in self.inputs:
            if type(item) is StageOutputInput and (
                item.producer_node_id not in self.dependencies
            ):
                raise ValueError("StageOutputInput producer 不在 dependencies")


@dataclass(frozen=True)
class RunPlan:
    continuation: Literal["SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "SUMMARY"]
    nodes: tuple[StageNode, ...]

    def __post_init__(self) -> None:
        if self.continuation not in {
            "SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "SUMMARY",
        }:
            raise ValueError("continuation 非法")
        if type(self.nodes) is not tuple or not self.nodes:
            raise ValueError("run plan nodes 不得为空")
        ids = tuple(item.node_id for item in self.nodes)
        if len(set(ids)) != len(ids):
            raise ValueError("run plan node id 重复")
        positions = {node_id: index for index, node_id in enumerate(ids)}
        receipts = tuple(item.receipt_path for item in self.nodes)
        if len(set(receipts)) != len(receipts):
            raise ValueError("run plan receipt path 冲突")
        for index, node in enumerate(self.nodes):
            spec = STAGE_SPEC_REGISTRY.get(node.spec_name)
            if spec is None or node.scope != spec.scope or node.output_specs != spec.outputs:
                raise ValueError("run plan stage spec drift")
            for item in node.inputs:
                if type(item) is StageOutputInput:
                    if item.producer_node_id not in positions:
                        continue
                    producer = self.nodes[positions[item.producer_node_id]]
                    if not _output_path_is_covered(
                        item.relative_path, producer.output_specs
                    ):
                        raise ValueError("stage output input is not producer-covered")
            if any(dep not in positions or positions[dep] >= index for dep in node.dependencies):
                raise ValueError("run plan DAG 非法或排序不稳定")
        static = tuple(
            (node.node_id, node.publication.final_directory)
            for node in self.nodes
            if type(node.publication) is StaticDirectoryPublication
        )
        for left_index, (left_id, left) in enumerate(static):
            left_path = PurePosixPath(left)
            for right_id, right in static[left_index + 1:]:
                right_path = PurePosixPath(right)
                if (
                    left_path == right_path
                    or left_path in right_path.parents
                    or right_path in left_path.parents
                ):
                    raise ValueError(
                        f"static publication conflict: {left_id}/{right_id}"
                    )


@dataclass(frozen=True)
class ResolvedInput:
    digest: ArtifactDigest
    path: Path

    def __post_init__(self) -> None:
        if type(self.digest) is not ArtifactDigest or not isinstance(self.path, Path):
            raise ValueError("resolved input 非法")


@dataclass(frozen=True)
class StageContext:
    node: StageNode
    inputs: tuple[ResolvedInput, ...]
    temp_output_root: Path
    config: LoadedM3Config

    def __post_init__(self) -> None:
        if type(self.node) is not StageNode or type(self.config) is not LoadedM3Config:
            raise ValueError("stage context 非法")
        if type(self.inputs) is not tuple or any(
            type(item) is not ResolvedInput for item in self.inputs
        ):
            raise ValueError("stage context inputs 非法")
        if not isinstance(self.temp_output_root, Path):
            raise ValueError("stage context temp root 非法")


@dataclass(frozen=True)
class StageBuildReport:
    output_relative_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.output_relative_paths) is not tuple:
            raise ValueError("stage build report 非法")
        for value in self.output_relative_paths:
            _validate_relative(value, allow_dot=False)
        if self.output_relative_paths != tuple(sorted(set(self.output_relative_paths))):
            raise ValueError("stage build report paths 必须唯一排序")


StageHandler: TypeAlias = Callable[[StageContext], StageBuildReport]
SnapshotClosureVerifier: TypeAlias = Callable[
    [Path], tuple[SnapshotBuildResult, SnapshotRequestRecordV1]
]
StaticClosureVerifier: TypeAlias = Callable[[Path], None]
ExperimentOutputVerifier: TypeAlias = Callable[[Path], object]
ExperimentFinalVerifier: TypeAlias = Callable[
    [Path, Path], VerifiedExperimentIdentity
]


@dataclass(frozen=True)
class SnapshotStageResult:
    snapshot_root: Path
    request_record_path: Path
    receipt_path: Path
    build: SnapshotBuildResult
    request: SnapshotRequestRecordV1
    receipt: StageReceipt
    reused: bool


@dataclass(frozen=True)
class StaticStageResult:
    final_root: Path
    receipt_path: Path
    receipt: StageReceipt
    reused: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.final_root, Path)
            or not isinstance(self.receipt_path, Path)
            or type(self.receipt) is not StageReceipt
            or type(self.reused) is not bool
        ):
            raise ValueError("static stage result invalid")


@dataclass(frozen=True)
class ExperimentIdentityStageResult:
    experiment_root: Path
    receipt_path: Path
    verified: VerifiedExperimentIdentity
    receipt: StageReceipt
    reused: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.experiment_root, Path)
            or not isinstance(self.receipt_path, Path)
            or type(self.verified) is not VerifiedExperimentIdentity
            or type(self.receipt) is not StageReceipt
            or type(self.reused) is not bool
        ):
            raise ValueError("experiment identity stage result invalid")


class StageRunner:
    """Serial G8B runner for snapshot and static immutable publications."""

    def __init__(
        self, *, stage_root: Path, artifact_roots: Mapping[str, Path],
        config: LoadedM3Config,
    ) -> None:
        try:
            _require_real_directory(stage_root, label="stage root")
            if type(config) is not LoadedM3Config:
                raise ValueError
            roots = _validate_roots(artifact_roots)
            _alias_for_path(stage_root, roots)
        except (TypeError, ValueError, OSError):
            raise M3StageRunnerError("STAGE_INPUT_INVALID") from None
        self._stage_root = stage_root.resolve(strict=True)
        self._artifact_roots = roots
        self._config = config
        self._prepare_owned_directories()

    def run_snapshot(
        self, *, node: StageNode, handler: StageHandler,
        closure_verifier: SnapshotClosureVerifier, resume: bool = True,
    ) -> SnapshotStageResult:
        try:
            self._validate_snapshot_node(node)
            if type(resume) is not bool:
                raise ValueError
            lock_root = self._lock_root(node)
        except (TypeError, ValueError, OSError):
            raise M3StageRunnerError("STAGE_INPUT_INVALID") from None
        try:
            with hold_journal_writer_lock(journal_root=lock_root):
                return self._run_snapshot_locked(
                    node=node, handler=handler,
                    closure_verifier=closure_verifier, resume=resume,
                    receipt_stage="snapshot",
                )
        except M3StageRunnerError:
            raise
        except Exception:
            raise M3StageRunnerError("STAGE_LOCK_FAILED") from None

    def run_development_snapshot(
        self, *, node: StageNode, handler: StageHandler,
        closure_verifier: SnapshotClosureVerifier, resume: bool = True,
    ) -> SnapshotStageResult:
        """Run an explicitly non-Gate snapshot from a development example release."""
        try:
            self._validate_development_snapshot_node(node)
            if type(resume) is not bool:
                raise ValueError
            lock_root = self._lock_root(node)
        except (TypeError, ValueError, OSError):
            raise M3StageRunnerError("STAGE_INPUT_INVALID") from None
        try:
            with hold_journal_writer_lock(journal_root=lock_root):
                return self._run_snapshot_locked(
                    node=node, handler=handler,
                    closure_verifier=closure_verifier, resume=resume,
                    receipt_stage="development-snapshot",
                )
        except M3StageRunnerError:
            raise
        except Exception:
            raise M3StageRunnerError("STAGE_LOCK_FAILED") from None

    def run_experiment_identity(
        self,
        *,
        node: StageNode,
        handler: StageHandler,
        output_verifier: ExperimentOutputVerifier,
        final_verifier: ExperimentFinalVerifier,
        resume: bool = True,
    ) -> ExperimentIdentityStageResult:
        """Run the formal ExperimentIdentity through the shared static runner."""
        def verify_output(root: Path) -> None:
            output_verifier(root)

        static = self.run_static(
            node=node,
            handler=handler,
            closure_verifier=verify_output,
            resume=resume,
        )
        invalid = False
        verified: VerifiedExperimentIdentity | None = None
        try:
            candidate = final_verifier(static.final_root, static.receipt_path)
            if (
                type(candidate) is not VerifiedExperimentIdentity
                or candidate.manifest.experiment_key != node.scope_key
            ):
                raise ValueError
            verified = candidate
        except Exception:
            invalid = True
        if invalid or verified is None:
            raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT") from None
        return ExperimentIdentityStageResult(
            experiment_root=static.final_root,
            receipt_path=static.receipt_path,
            verified=verified,
            receipt=static.receipt,
            reused=static.reused,
        )

    def run_static(
        self, *, node: StageNode, handler: StageHandler,
        closure_verifier: StaticClosureVerifier, resume: bool = True,
        plan: RunPlan | None = None,
    ) -> StaticStageResult:
        """Run one fully resolved static node with immutable recovery semantics."""
        try:
            self._validate_static_node(node)
            if type(resume) is not bool or not callable(closure_verifier):
                raise ValueError
            plan_nodes = self._plan_nodes_for(node=node, plan=plan)
            self._prepare_static_parents(node)
            lock_root = self._lock_root(node)
        except (TypeError, ValueError, OSError):
            raise M3StageRunnerError("STAGE_INPUT_INVALID") from None
        try:
            with hold_journal_writer_lock(journal_root=lock_root):
                return self._run_static_locked(
                    node=node, handler=handler,
                    closure_verifier=closure_verifier, resume=resume,
                    plan_nodes=plan_nodes,
                )
        except M3StageRunnerError:
            raise
        except Exception:
            raise M3StageRunnerError("STAGE_LOCK_FAILED") from None

    def _run_static_locked(
        self, *, node: StageNode, handler: StageHandler,
        closure_verifier: StaticClosureVerifier, resume: bool,
        plan_nodes: Mapping[str, StageNode],
    ) -> StaticStageResult:
        publication = cast(StaticDirectoryPublication, node.publication)
        final_root = self._stage_root / publication.final_directory
        receipt_path = self._stage_root / node.receipt_path
        receipt = self._read_receipt(receipt_path)
        if receipt is not None:
            result = self._verify_completed_static(
                node=node, final_root=final_root, receipt_path=receipt_path,
                receipt=receipt, closure_verifier=closure_verifier,
                plan_nodes=plan_nodes,
            )
            if not resume:
                raise M3StageRunnerError("STAGE_ALREADY_COMPLETE")
            return result

        final_state = _leaf_state(final_root)
        if final_state not in {"missing", "directory"}:
            raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT")
        final_preexisting = final_state == "directory"
        if final_preexisting:
            try:
                self._verify_static_closure(
                    root=final_root, node=node,
                    closure_verifier=closure_verifier,
                )
            except Exception:
                raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT") from None

        resolved = self._resolve_static_inputs(node=node, plan_nodes=plan_nodes)
        temp_root = Path(tempfile.mkdtemp(
            prefix=f".{node.node_id}.", dir=self._stage_root / ".stage-tmp"
        ))
        committed = False
        try:
            context = StageContext(
                node=node, inputs=resolved, temp_output_root=temp_root,
                config=self._config,
            )
            try:
                report = handler(context)
            except Exception:
                raise M3StageRunnerError("STAGE_BUILD_FAILED") from None
            if type(report) is not StageBuildReport:
                raise M3StageRunnerError("STAGE_OUTPUT_INVALID")
            try:
                temp_outputs = self._verify_static_closure(
                    root=temp_root, node=node,
                    closure_verifier=closure_verifier,
                )
                if report.output_relative_paths != tuple(
                    path.relative_to(temp_root).as_posix() for path in temp_outputs
                ):
                    raise ValueError
            except M3StageRunnerError:
                raise
            except Exception:
                raise M3StageRunnerError("STAGE_OUTPUT_INVALID") from None

            if final_preexisting:
                if not _trees_equal(temp_root, final_root):
                    raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT")
            else:
                try:
                    commit_directory_noreplace(temp_root, final_root)
                    committed = True
                except Exception:
                    if (
                        _leaf_state(final_root) != "directory"
                        or not _trees_equal(temp_root, final_root)
                    ):
                        raise M3StageRunnerError("STAGE_PUBLISH_FAILED") from None

            try:
                final_outputs = self._verify_static_closure(
                    root=final_root, node=node,
                    closure_verifier=closure_verifier,
                )
                if tuple(
                    path.relative_to(final_root).as_posix()
                    for path in final_outputs
                ) != report.output_relative_paths:
                    raise ValueError
            except Exception:
                raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT") from None
            receipt = self._publish_static_receipt(
                node=node, receipt_path=receipt_path,
                resolved=resolved, outputs=final_outputs,
            )
            self._validate_static_receipt(
                node=node, receipt=receipt, resolved=resolved,
                outputs=final_outputs,
            )
            return StaticStageResult(
                final_root=final_root, receipt_path=receipt_path,
                receipt=receipt, reused=final_preexisting,
            )
        finally:
            if not committed and temp_root.exists():
                _remove_owned_temp(
                    temp_root, self._stage_root / ".stage-tmp",
                    expected_prefix=f".{node.node_id}.",
                )

    def _run_snapshot_locked(
        self, *, node: StageNode, handler: StageHandler,
        closure_verifier: SnapshotClosureVerifier, resume: bool,
        receipt_stage: str,
    ) -> SnapshotStageResult:
        receipt_path = self._stage_root / node.receipt_path
        publication = cast(SnapshotContentPublication, node.publication)
        request_path = self._stage_root / publication.request_record_path
        existing_receipt = self._read_receipt(receipt_path)
        if existing_receipt is not None:
            result = self._verify_completed_snapshot(
                node=node, request_path=request_path, receipt_path=receipt_path,
                receipt=existing_receipt, closure_verifier=closure_verifier,
                receipt_stage=receipt_stage,
            )
            if not resume:
                raise M3StageRunnerError("STAGE_ALREADY_COMPLETE")
            return result

        resolved = self._resolve_external_inputs(node)
        temp_root = Path(tempfile.mkdtemp(
            prefix=f".{node.node_id}.", dir=self._stage_root / ".stage-tmp"
        ))
        committed = False
        try:
            context = StageContext(
                node=node, inputs=resolved, temp_output_root=temp_root,
                config=self._config,
            )
            try:
                report = handler(context)
            except Exception:
                raise M3StageRunnerError("STAGE_BUILD_FAILED") from None
            if type(report) is not StageBuildReport:
                raise M3StageRunnerError("STAGE_OUTPUT_INVALID")
            try:
                build, request = closure_verifier(temp_root)
                if type(build) is not SnapshotBuildResult:
                    raise ValueError
                if type(request) is not SnapshotRequestRecordV1:
                    raise ValueError
                if request.snapshot_request_key != node.scope_key:
                    raise ValueError
                expected_report = _regular_tree_relative_paths(temp_root)
                if report.output_relative_paths != expected_report:
                    raise ValueError
            except M3StageRunnerError:
                raise
            except Exception:
                raise M3StageRunnerError("STAGE_OUTPUT_INVALID") from None

            final_root = self._stage_root / "snapshots" / build.manifest.snapshot_id
            request_bytes = snapshot_request_record_bytes(request)
            mapping_exists = _leaf_state(request_path)
            final_exists = _leaf_state(final_root)
            if mapping_exists not in {"missing", "file"}:
                raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT")
            if final_exists not in {"missing", "directory"}:
                raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT")
            if not resume and (
                final_exists == "directory" or mapping_exists == "file"
            ):
                raise M3StageRunnerError("STAGE_ALREADY_COMPLETE")
            if mapping_exists == "file" and _read_plain_file(request_path) != request_bytes:
                raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT")
            if mapping_exists == "file" and final_exists == "missing":
                raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT")
            if final_exists == "directory":
                try:
                    final_build, final_request = closure_verifier(final_root)
                except Exception:
                    raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT") from None
                if final_build.manifest.snapshot_id != build.manifest.snapshot_id:
                    raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT")
                if snapshot_request_record_bytes(final_request) != request_bytes:
                    raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT")
                if not _trees_equal(temp_root, final_root):
                    raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT")
            else:
                try:
                    commit_directory_noreplace(temp_root, final_root)
                    committed = True
                except Exception:
                    if _leaf_state(final_root) != "directory" or not _trees_equal(
                        temp_root, final_root
                    ):
                        raise M3StageRunnerError("STAGE_PUBLISH_FAILED") from None
            _publish_immutable_file(request_path, request_bytes)
            outputs = (request_path, *_regular_tree_paths(final_root))
            receipt = publish_stage_receipt(
                receipt_path=receipt_path,
                stage=receipt_stage,
                scope="SNAPSHOT",
                scope_key=node.scope_key,
                artifact_roots=self._artifact_roots,
                inputs=tuple(
                    (item.digest.root_alias, item.path) for item in resolved
                ),
                outputs=tuple(
                    (_alias_for_path(path, self._artifact_roots), path)
                    for path in outputs
                ),
            )
            final_build, final_request = closure_verifier(final_root)
            if snapshot_request_record_bytes(final_request) != request_bytes:
                raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT")
            _validate_receipt_paths(
                receipt=receipt, roots=self._artifact_roots,
                expected_inputs={item.path for item in resolved},
                expected_outputs=set(outputs),
                expected_stage=receipt_stage,
            )
            return SnapshotStageResult(
                snapshot_root=final_root, request_record_path=request_path,
                receipt_path=receipt_path, build=final_build,
                request=final_request, receipt=receipt, reused=False,
            )
        finally:
            if not committed and temp_root.exists():
                _remove_owned_temp(
                    temp_root, self._stage_root / ".stage-tmp",
                    expected_prefix=".snapshot.",
                )

    def _verify_completed_snapshot(
        self, *, node: StageNode, request_path: Path, receipt_path: Path,
        receipt: StageReceipt, closure_verifier: SnapshotClosureVerifier,
        receipt_stage: str,
    ) -> SnapshotStageResult:
        try:
            request = read_snapshot_request_record(request_path)
            if request.snapshot_request_key != node.scope_key:
                raise ValueError
            final_root = self._stage_root / "snapshots" / request.snapshot_id
            build, rebuilt_request = closure_verifier(final_root)
            if snapshot_request_record_bytes(rebuilt_request) != _read_plain_file(request_path):
                raise ValueError
            resolved = self._resolve_external_inputs(node)
            outputs = (request_path, *_regular_tree_paths(final_root))
            _validate_receipt_paths(
                receipt=receipt, roots=self._artifact_roots,
                expected_inputs={item.path for item in resolved},
                expected_outputs=set(outputs),
                expected_stage=receipt_stage,
            )
            return SnapshotStageResult(
                snapshot_root=final_root, request_record_path=request_path,
                receipt_path=receipt_path, build=build, request=rebuilt_request,
                receipt=receipt, reused=True,
            )
        except M3StageRunnerError:
            raise
        except Exception:
            raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT") from None

    def _read_receipt(self, receipt_path: Path) -> StageReceipt | None:
        try:
            return verify_stage_receipt(
                receipt_path=receipt_path, artifact_roots=self._artifact_roots
            )
        except Exception:
            raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT") from None

    def _resolve_external_inputs(self, node: StageNode) -> tuple[ResolvedInput, ...]:
        resolved: list[ResolvedInput] = []
        try:
            for item in node.inputs:
                if type(item) is not ExternalInput:
                    raise ValueError
                digest = item.artifact
                root = self._artifact_roots[digest.root_alias]
                path = root / Path(digest.relative_path)
                raw = _read_plain_file(path)
                if len(raw) != digest.size_bytes:
                    raise ValueError
                if hashlib.sha256(raw).hexdigest() != digest.sha256:
                    raise ValueError
                resolved.append(ResolvedInput(digest=digest, path=path.resolve(strict=True)))
        except Exception:
            raise M3StageRunnerError("STAGE_INPUT_INVALID") from None
        return tuple(resolved)

    def _resolve_static_inputs(
        self, *, node: StageNode, plan_nodes: Mapping[str, StageNode],
    ) -> tuple[ResolvedInput, ...]:
        dependency_receipts: dict[str, StageReceipt] = {}
        for dependency_id in node.dependencies:
            producer = plan_nodes[dependency_id]
            dependency_receipts[dependency_id] = self._verify_dependency_static(
                producer
            )
        resolved: list[ResolvedInput] = []
        try:
            for item in node.inputs:
                if type(item) is ExternalInput:
                    digest = item.artifact
                    path = self._path_for_digest(digest)
                else:
                    stage_input = cast(StageOutputInput, item)
                    producer = plan_nodes[stage_input.producer_node_id]
                    publication = cast(
                        StaticDirectoryPublication, producer.publication
                    )
                    expected = (
                        self._stage_root / publication.final_directory
                        / stage_input.relative_path
                    ).resolve(strict=True)
                    matches = tuple(
                        digest
                        for digest in dependency_receipts[
                            stage_input.producer_node_id
                        ].outputs
                        if digest.root_alias == stage_input.root_alias
                        and self._path_for_digest(digest) == expected
                    )
                    if len(matches) != 1:
                        raise ValueError
                    digest = matches[0]
                    path = expected
                resolved.append(ResolvedInput(digest=digest, path=path))
        except M3StageRunnerError:
            raise
        except Exception:
            raise M3StageRunnerError("STAGE_INPUT_INVALID") from None
        return tuple(resolved)

    def _path_for_digest(self, digest: ArtifactDigest) -> Path:
        root = self._artifact_roots[digest.root_alias]
        path = root / Path(digest.relative_path)
        raw = _read_plain_file(path)
        if (
            len(raw) != digest.size_bytes
            or hashlib.sha256(raw).hexdigest() != digest.sha256
        ):
            raise ValueError
        return path.resolve(strict=True)

    def _verify_dependency_static(self, node: StageNode) -> StageReceipt:
        try:
            self._validate_static_node(node)
            receipt_path = self._stage_root / node.receipt_path
            receipt = self._read_receipt(receipt_path)
            if receipt is None:
                raise ValueError
            publication = cast(StaticDirectoryPublication, node.publication)
            final_root = self._stage_root / publication.final_directory
            outputs = _static_output_paths(final_root, node.output_specs)
            self._validate_static_receipt_outputs(
                node=node, receipt=receipt, outputs=outputs,
            )
        except Exception:
            raise M3StageRunnerError("STAGE_INPUT_INVALID") from None
        return receipt

    def _verify_static_closure(
        self, *, root: Path, node: StageNode,
        closure_verifier: StaticClosureVerifier,
    ) -> tuple[Path, ...]:
        closure_verifier(root)
        return _static_output_paths(root, node.output_specs)

    def _verify_completed_static(
        self, *, node: StageNode, final_root: Path, receipt_path: Path,
        receipt: StageReceipt, closure_verifier: StaticClosureVerifier,
        plan_nodes: Mapping[str, StageNode],
    ) -> StaticStageResult:
        try:
            resolved = self._resolve_static_inputs(
                node=node, plan_nodes=plan_nodes
            )
            outputs = self._verify_static_closure(
                root=final_root, node=node,
                closure_verifier=closure_verifier,
            )
            self._validate_static_receipt(
                node=node, receipt=receipt, resolved=resolved,
                outputs=outputs,
            )
            return StaticStageResult(
                final_root=final_root, receipt_path=receipt_path,
                receipt=receipt, reused=True,
            )
        except M3StageRunnerError:
            raise
        except Exception:
            raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT") from None

    def _publish_static_receipt(
        self, *, node: StageNode, receipt_path: Path,
        resolved: tuple[ResolvedInput, ...], outputs: tuple[Path, ...],
    ) -> StageReceipt:
        try:
            return publish_stage_receipt(
                receipt_path=receipt_path,
                stage=node.spec_name,
                scope=node.scope,
                scope_key=node.scope_key,
                artifact_roots=self._artifact_roots,
                inputs=tuple(
                    (item.digest.root_alias, item.path) for item in resolved
                ),
                outputs=tuple(
                    (_alias_for_path(path, self._artifact_roots), path)
                    for path in outputs
                ),
            )
        except Exception:
            raise M3StageRunnerError("STAGE_PUBLISH_FAILED") from None

    def _validate_static_receipt(
        self, *, node: StageNode, receipt: StageReceipt,
        resolved: tuple[ResolvedInput, ...], outputs: tuple[Path, ...],
    ) -> None:
        self._validate_static_receipt_outputs(
            node=node, receipt=receipt, outputs=outputs,
        )
        if _digest_paths(receipt.inputs, self._artifact_roots) != {
            item.path.resolve(strict=True) for item in resolved
        }:
            raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT")

    def _validate_static_receipt_outputs(
        self, *, node: StageNode, receipt: StageReceipt,
        outputs: tuple[Path, ...],
    ) -> None:
        if (
            receipt.stage != node.spec_name
            or receipt.scope != node.scope
            or receipt.scope_key != node.scope_key
            or _digest_paths(receipt.outputs, self._artifact_roots)
            != {path.resolve(strict=True) for path in outputs}
        ):
            raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT")

    def _prepare_static_parents(self, node: StageNode) -> None:
        publication = cast(StaticDirectoryPublication, node.publication)
        for path in (
            self._stage_root / publication.final_directory,
            self._stage_root / node.receipt_path,
        ):
            _ensure_real_parent_directories(path=path, root=self._stage_root)

    @staticmethod
    def _plan_nodes_for(
        *, node: StageNode, plan: RunPlan | None,
    ) -> dict[str, StageNode]:
        if plan is None:
            if node.dependencies:
                raise ValueError("static dependency nodes require a RunPlan")
            return {node.node_id: node}
        if type(plan) is not RunPlan:
            raise ValueError
        nodes = {item.node_id: item for item in plan.nodes}
        if nodes.get(node.node_id) != node:
            raise ValueError("static node is not the plan node")
        if any(dependency not in nodes for dependency in node.dependencies):
            raise ValueError("static dependency absent from plan")
        return nodes

    def _prepare_owned_directories(self) -> None:
        for relative in (
            ".stage-locks", ".stage-tmp", "snapshots", "snapshot-requests",
            "receipts", "receipts/snapshot", "receipts/development-snapshot",
        ):
            path = self._stage_root / relative
            try:
                path.mkdir(exist_ok=True)
                _require_real_directory(path, label="stage-owned directory")
            except (OSError, ValueError):
                raise M3StageRunnerError("STAGE_INPUT_INVALID") from None

    def _lock_root(self, node: StageNode) -> Path:
        lock_id = hashlib.sha256(
            f"{node.scope}\0{node.scope_key}\0{node.node_id}".encode("ascii")
        ).hexdigest()
        path = self._stage_root / ".stage-locks" / lock_id
        try:
            path.mkdir(exist_ok=True)
            _require_real_directory(path, label="stage lock")
            return path.resolve(strict=True)
        except (OSError, ValueError):
            raise M3StageRunnerError("STAGE_LOCK_FAILED") from None

    @staticmethod
    def _validate_snapshot_node(node: StageNode) -> None:
        if type(node) is not StageNode:
            raise ValueError
        if node.spec_name != "snapshot" or node.scope != "SNAPSHOT":
            raise ValueError
        if node.dependencies or node.fold is not None or node.horizon is not None:
            raise ValueError
        if type(node.publication) is not SnapshotContentPublication:
            raise ValueError
        if node.output_specs != SNAPSHOT_STAGE_SPEC.outputs:
            raise ValueError
        expected_request = f"snapshot-requests/{node.scope_key}.json"
        expected_receipt = f"receipts/snapshot/{node.scope_key}.json"
        if node.publication.request_record_path != expected_request:
            raise ValueError
        if node.receipt_path != expected_receipt:
            raise ValueError

    @staticmethod
    def _validate_static_node(node: StageNode) -> None:
        if type(node) is not StageNode:
            raise ValueError
        spec = STAGE_SPEC_REGISTRY.get(node.spec_name)
        if (
            spec is None
            or type(node.publication) is not StaticDirectoryPublication
            or node.scope != spec.scope
            or node.output_specs != spec.outputs
        ):
            raise ValueError("static node contract drift")
        final_path = PurePosixPath(node.publication.final_directory)
        receipt_path = PurePosixPath(node.receipt_path)
        if (
            final_path == receipt_path
            or final_path in receipt_path.parents
            or receipt_path in final_path.parents
        ):
            raise ValueError("static receipt must be outside output")

    @staticmethod
    def _validate_development_snapshot_node(node: StageNode) -> None:
        if type(node) is not StageNode:
            raise ValueError
        if node.spec_name != "development-snapshot" or node.scope != "SNAPSHOT":
            raise ValueError
        if node.dependencies or node.fold is not None or node.horizon is not None:
            raise ValueError
        if type(node.publication) is not SnapshotContentPublication:
            raise ValueError
        if node.output_specs != DEVELOPMENT_SNAPSHOT_STAGE_SPEC.outputs:
            raise ValueError
        expected_request = f"snapshot-requests/{node.scope_key}.json"
        expected_receipt = f"receipts/development-snapshot/{node.scope_key}.json"
        if node.publication.request_record_path != expected_request:
            raise ValueError
        if node.receipt_path != expected_receipt:
            raise ValueError


def _validate_relative(value: str, *, allow_dot: bool) -> None:
    if type(value) is not str or not value or "\\" in value:
        raise ValueError("relative path 非法")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise ValueError("relative path 非法")
    if not allow_dot and "." in path.parts:
        raise ValueError("relative path 非法")


def _validate_node_id(value: str) -> None:
    if type(value) is not str or _NODE_PATTERN.fullmatch(value) is None:
        raise ValueError("node id 非法")


def _validate_scope(value: object) -> None:
    if value not in {"SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "REPRO", "ACCEPTANCE"}:
        raise ValueError("scope 非法")


def _require_hex64(value: object) -> None:
    if type(value) is not str or len(value) != 64 or any(
        char not in _HEX64 for char in value
    ):
        raise ValueError("scope key 非法")


def _validate_name_tuple(values: object, *, label: str) -> None:
    if type(values) is not tuple:
        raise ValueError(f"{label} 非法")
    for value in values:
        _validate_node_id(value)
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{label} 必须唯一排序")


def _validate_outputs(values: object) -> None:
    if type(values) is not tuple or not values:
        raise ValueError("outputs 不得为空")
    if any(type(item) is not OutputSpec for item in values):
        raise ValueError("outputs 元素非法")
    paths = tuple(item.relative_path for item in values)
    if paths != tuple(sorted(set(paths))):
        raise ValueError("outputs path 必须唯一排序")


def _output_path_is_covered(path: str, outputs: tuple[OutputSpec, ...]) -> bool:
    candidate = PurePosixPath(path)
    return any(
        candidate == PurePosixPath(output.relative_path)
        or (
            output.kind == "TREE"
            and PurePosixPath(output.relative_path) in candidate.parents
        )
        for output in outputs
    )


def _validate_roots(roots: Mapping[str, Path]) -> dict[str, Path]:
    if not isinstance(roots, Mapping) or not roots:
        raise ValueError("artifact roots 非法")
    result: dict[str, Path] = {}
    for alias, root in roots.items():
        if type(alias) is not str or _ROOT_ALIAS_PATTERN.fullmatch(alias) is None:
            raise ValueError("artifact root alias 非法")
        _require_real_directory(root, label="artifact root")
        resolved = root.resolve(strict=True)
        if resolved in result.values():
            raise ValueError("artifact roots 物理重复")
        result[alias] = resolved
    ordered = tuple(result.values())
    for left in ordered:
        for right in ordered:
            if left != right and (left.is_relative_to(right) or right.is_relative_to(left)):
                raise ValueError("artifact roots 不得嵌套")
    return result


def _alias_for_path(path: Path, roots: Mapping[str, Path]) -> str:
    resolved = path.resolve(strict=True)
    aliases = [alias for alias, root in roots.items() if resolved.is_relative_to(root)]
    if len(aliases) != 1:
        raise ValueError("path 必须属于唯一 artifact root")
    return aliases[0]


def _ensure_real_parent_directories(*, path: Path, root: Path) -> None:
    resolved_root = root.resolve(strict=True)
    parent = path.parent.absolute()
    if not parent.is_relative_to(resolved_root):
        raise ValueError("stage-owned parent escaped stage root")
    current = resolved_root
    for part in parent.relative_to(resolved_root).parts:
        current = current / part
        try:
            current.mkdir()
        except FileExistsError:
            pass
        _require_real_directory(current, label="stage-owned parent")


def _require_real_directory(path: Path, *, label: str) -> None:
    _reject_parent_links(path.parent, label=label)
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or _is_reparse(st):
        raise ValueError(f"{label} 必须为真实目录")


def _reject_parent_links(path: Path, *, label: str) -> None:
    current = path.absolute()
    for candidate in (current, *current.parents):
        st = os.lstat(candidate)
        if stat.S_ISLNK(st.st_mode) or _is_reparse(st):
            raise ValueError(f"{label} ancestor 非法")


def _is_reparse(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & 0x400)


def _leaf_state(path: Path) -> Literal["missing", "file", "directory", "other"]:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "other"
    if stat.S_ISLNK(st.st_mode) or _is_reparse(st):
        return "other"
    if stat.S_ISREG(st.st_mode) and st.st_nlink == 1:
        return "file"
    if stat.S_ISDIR(st.st_mode):
        return "directory"
    return "other"


def _read_plain_file(path: Path) -> bytes:
    if _leaf_state(path) != "file":
        raise ValueError("artifact 必须为单链接普通文件")
    _reject_parent_links(path.parent, label="artifact")
    return path.read_bytes()


def _regular_tree_paths(root: Path) -> tuple[Path, ...]:
    _require_real_directory(root, label="published tree")
    paths: list[Path] = []
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directories:
            _require_real_directory(current_path / name, label="published tree")
        for name in files:
            path = current_path / name
            _read_plain_file(path)
            paths.append(path.resolve(strict=True))
    return tuple(sorted(paths, key=lambda item: item.relative_to(root).as_posix()))


def _regular_tree_relative_paths(root: Path) -> tuple[str, ...]:
    return tuple(path.relative_to(root.resolve(strict=True)).as_posix() for path in (
        _regular_tree_paths(root)
    ))


def _static_output_paths(
    root: Path, output_specs: tuple[OutputSpec, ...],
) -> tuple[Path, ...]:
    _require_real_directory(root, label="static output")
    all_paths = _regular_tree_paths(root)
    actual = {
        path.relative_to(root.resolve(strict=True)).as_posix(): path
        for path in all_paths
    }
    expected: set[str] = set()
    tree_roots: list[PurePosixPath] = []
    for output in output_specs:
        relative = PurePosixPath(output.relative_path)
        target = root / output.relative_path
        if output.kind == "FILE":
            _read_plain_file(target)
            expected.add(output.relative_path)
            continue
        _require_real_directory(target, label="static TREE output")
        tree_roots.append(relative)
        closure = cast(str, output.closure_manifest)
        _read_plain_file(root / closure)
        expected.add(closure)
        expected.update(
            path.relative_to(root.resolve(strict=True)).as_posix()
            for path in _regular_tree_paths(target)
        )
    if set(actual) != expected:
        raise ValueError("static output file closure drift")
    for current, directories, _files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directories:
            directory = current_path / name
            _require_real_directory(directory, label="static output directory")
            relative = PurePosixPath(
                directory.relative_to(root.resolve(strict=True)).as_posix()
            )
            if not any(
                relative == tree
                or tree in relative.parents
                or relative in PurePosixPath(output.relative_path).parents
                for tree in tree_roots
                for output in output_specs
            ) and not any(
                relative in PurePosixPath(output.relative_path).parents
                for output in output_specs
            ):
                raise ValueError("static output directory closure drift")
    return tuple(actual[name] for name in sorted(actual))


def _trees_equal(left: Path, right: Path) -> bool:
    try:
        left_paths = _regular_tree_paths(left)
        right_paths = _regular_tree_paths(right)
        left_rel = tuple(path.relative_to(left.resolve(strict=True)).as_posix() for path in left_paths)
        right_rel = tuple(path.relative_to(right.resolve(strict=True)).as_posix() for path in right_paths)
        if left_rel != right_rel:
            return False
        return all(
            _read_plain_file(left / relative) == _read_plain_file(right / relative)
            for relative in left_rel
        )
    except (OSError, ValueError):
        return False


def _publish_immutable_file(path: Path, payload: bytes) -> None:
    parent = path.parent
    _require_real_directory(parent, label="immutable file parent")
    state = _leaf_state(path)
    if state == "file":
        if _read_plain_file(path) != payload:
            raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT")
        return
    if state != "missing":
        raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT")
    fd = -1
    temp_path: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=parent)
        temp_path = Path(name)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_path, path)
        except FileExistsError:
            if _leaf_state(path) != "file" or _read_plain_file(path) != payload:
                raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT") from None
        except OSError:
            raise M3StageRunnerError("STAGE_PUBLISH_FAILED") from None
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                if not path.exists():
                    raise M3StageRunnerError("STAGE_PUBLISH_FAILED") from None


def _digest_paths(
    digests: Sequence[ArtifactDigest], roots: Mapping[str, Path],
) -> set[Path]:
    return {
        (roots[item.root_alias] / Path(item.relative_path)).resolve(strict=True)
        for item in digests
    }


def _validate_receipt_paths(
    *, receipt: StageReceipt, roots: Mapping[str, Path],
    expected_inputs: set[Path], expected_outputs: set[Path], expected_stage: str,
) -> None:
    if receipt.stage != expected_stage or receipt.scope != "SNAPSHOT":
        raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT")
    if _digest_paths(receipt.inputs, roots) != {
        path.resolve(strict=True) for path in expected_inputs
    }:
        raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT")
    if _digest_paths(receipt.outputs, roots) != {
        path.resolve(strict=True) for path in expected_outputs
    }:
        raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT")


def _remove_owned_temp(
    path: Path, temp_parent: Path, *, expected_prefix: str,
) -> None:
    try:
        resolved_parent = temp_parent.resolve(strict=True)
        resolved = path.resolve(strict=True)
        if (
            resolved.parent != resolved_parent
            or not resolved.name.startswith(expected_prefix)
        ):
            raise ValueError
        shutil.rmtree(resolved)
    except FileNotFoundError:
        return
    except (OSError, ValueError):
        raise M3StageRunnerError("STAGE_PUBLISH_FAILED") from None


SNAPSHOT_STAGE_SPEC = StageSpec(
    name="snapshot",
    scope="SNAPSHOT",
    dependencies=(),
    outputs=(
        OutputSpec("manifest.json", "FILE", None),
        OutputSpec("session_calendar.parquet", "FILE", None),
        OutputSpec("staging", "TREE", "manifest.json"),
    ),
)

DEVELOPMENT_SNAPSHOT_STAGE_SPEC = StageSpec(
    name="development-snapshot",
    scope="SNAPSHOT",
    dependencies=(),
    outputs=SNAPSHOT_STAGE_SPEC.outputs,
)

PROVIDER_STAGE_SPEC = StageSpec(
    "provider", "PROVIDER", ("snapshot",),
    (
        OutputSpec("provider", "TREE", "provider_manifest.json"),
        OutputSpec("provider_manifest.json", "FILE", None),
    ),
)
DEVELOPMENT_PROVIDER_STAGE_SPEC = StageSpec(
    "development-provider", "PROVIDER", ("development-snapshot",),
    PROVIDER_STAGE_SPEC.outputs,
)
PROVIDER_VALIDATION_STAGE_SPEC = StageSpec(
    "provider-validation", "PROVIDER", ("provider",),
    (
        OutputSpec("provider_validation.json", "FILE", None),
        OutputSpec("provider_validation.parquet", "FILE", None),
    ),
)
DEVELOPMENT_PROVIDER_VALIDATION_STAGE_SPEC = StageSpec(
    "development-provider-validation", "PROVIDER", ("development-provider",),
    PROVIDER_VALIDATION_STAGE_SPEC.outputs,
)
EXPERIMENT_IDENTITY_STAGE_SPEC = StageSpec(
    "experiment-identity", "EXPERIMENT", ("provider-validation",),
    (OutputSpec("experiment_manifest.json", "FILE", None),),
)
DEVELOPMENT_EXPERIMENT_IDENTITY_STAGE_SPEC = StageSpec(
    "development-experiment-identity", "EXPERIMENT",
    ("development-provider-validation",), EXPERIMENT_IDENTITY_STAGE_SPEC.outputs,
)
LABEL_STAGE_SPEC = StageSpec(
    "labels", "EXPERIMENT", ("experiment-identity",),
    (
        OutputSpec("diagnostics.parquet", "FILE", None),
        OutputSpec("label_manifest.json", "FILE", None),
        OutputSpec("labels.parquet", "FILE", None),
    ),
)
DEVELOPMENT_LABEL_STAGE_SPEC = StageSpec(
    "development-labels", "EXPERIMENT", ("development-experiment-identity",),
    LABEL_STAGE_SPEC.outputs,
)
LABEL_RECONCILIATION_STAGE_SPEC = StageSpec(
    "label-reconciliation", "EXPERIMENT", ("labels", "provider-validation"),
    (
        OutputSpec("reconciliation.json", "FILE", None),
        OutputSpec("reconciliation.parquet", "FILE", None),
    ),
)
DEVELOPMENT_LABEL_RECONCILIATION_STAGE_SPEC = StageSpec(
    "development-label-reconciliation", "EXPERIMENT",
    ("development-labels", "development-provider-validation"),
    LABEL_RECONCILIATION_STAGE_SPEC.outputs,
)
FOLDS_STAGE_SPEC = StageSpec(
    "folds", "EXPERIMENT", ("experiment-identity",),
    (OutputSpec("folds.json", "FILE", None),),
)
DEVELOPMENT_FOLDS_STAGE_SPEC = StageSpec(
    "development-folds", "EXPERIMENT", ("development-experiment-identity",),
    FOLDS_STAGE_SPEC.outputs,
)
FEATURES_STAGE_SPEC = StageSpec(
    "features", "EXPERIMENT", ("folds", "provider-validation"),
    (
        OutputSpec("coverage.parquet", "FILE", None),
        OutputSpec("feature_manifest.json", "FILE", None),
        OutputSpec("request.json", "FILE", None),
        OutputSpec("test.parquet", "FILE", None),
        OutputSpec("train.parquet", "FILE", None),
        OutputSpec("validation.parquet", "FILE", None),
        OutputSpec("worker-response.json", "FILE", None),
    ),
)
DEVELOPMENT_FEATURES_STAGE_SPEC = StageSpec(
    "development-features", "EXPERIMENT",
    ("development-folds", "development-provider-validation"),
    FEATURES_STAGE_SPEC.outputs,
)
ALIGNMENT_STAGE_SPEC = StageSpec(
    "alignment", "WORK", ("features",),
    (
        OutputSpec("alignment_manifest.json", "FILE", None),
        OutputSpec("diagnostics.parquet", "FILE", None),
        OutputSpec("train.parquet", "FILE", None),
        OutputSpec("validation.parquet", "FILE", None),
    ),
)
DEVELOPMENT_ALIGNMENT_STAGE_SPEC = StageSpec(
    "development-alignment", "WORK", ("development-features",),
    ALIGNMENT_STAGE_SPEC.outputs,
)
TRAIN_STAGE_SPEC = StageSpec(
    "train", "WORK", ("alignment",),
    (
        OutputSpec("model.metadata.json", "FILE", None),
        OutputSpec("model.txt", "FILE", None),
        OutputSpec("validation_curve.parquet", "FILE", None),
    ),
)
DEVELOPMENT_MODEL_STAGE_SPEC = StageSpec(
    "development-model", "WORK", ("development-alignment",),
    TRAIN_STAGE_SPEC.outputs,
)
PREDICTIONS_STAGE_SPEC = StageSpec(
    "predictions", "WORK", ("train",),
    (
        OutputSpec("prediction_manifest.json", "FILE", None),
        OutputSpec("predictions.parquet", "FILE", None),
    ),
)
DEVELOPMENT_PREDICTIONS_STAGE_SPEC = StageSpec(
    "development-predictions", "WORK", ("development-model",),
    PREDICTIONS_STAGE_SPEC.outputs,
)
EVALUATION_STAGE_SPEC = StageSpec(
    "evaluation", "WORK", ("predictions",),
    (
        OutputSpec("daily_ic.parquet", "FILE", None),
        OutputSpec("evaluation_manifest.json", "FILE", None),
        OutputSpec("metrics.json", "FILE", None),
    ),
)
DEVELOPMENT_EVALUATION_STAGE_SPEC = StageSpec(
    "development-evaluation", "WORK", ("development-predictions",),
    EVALUATION_STAGE_SPEC.outputs,
)
TARGETS_STAGE_SPEC = StageSpec(
    "targets", "WORK", ("evaluation",),
    (
        OutputSpec("target_daily.parquet", "FILE", None),
        OutputSpec("target_manifest.json", "FILE", None),
        OutputSpec("target_weights.parquet", "FILE", None),
    ),
)
DEVELOPMENT_TARGETS_STAGE_SPEC = StageSpec(
    "development-targets", "WORK", ("development-evaluation",),
    TARGETS_STAGE_SPEC.outputs,
)
BACKTEST_PLAN_STAGE_SPEC = StageSpec(
    "backtest_plan", "WORK", ("targets",),
    (
        OutputSpec("cost_schedule.json", "FILE", None),
        OutputSpec("manifest.json", "FILE", None),
        OutputSpec("schedule_diagnostics.parquet", "FILE", None),
        OutputSpec("scheduled_targets.parquet", "FILE", None),
    ),
)
DEVELOPMENT_BACKTEST_PLAN_STAGE_SPEC = StageSpec(
    "development-backtest-plan", "WORK", ("development-targets",),
    BACKTEST_PLAN_STAGE_SPEC.outputs,
)
BACKTEST_STAGE_SPEC = StageSpec(
    "backtest", "WORK", ("backtest_plan",),
    (
        OutputSpec("0p5x", "TREE", "0p5x/manifest.json"),
        OutputSpec("1p0x", "TREE", "1p0x/manifest.json"),
        OutputSpec("2p0x", "TREE", "2p0x/manifest.json"),
        OutputSpec("backtest_manifest.json", "FILE", None),
        OutputSpec("backtest_metrics.json", "FILE", None),
    ),
)
DEVELOPMENT_BACKTEST_STAGE_SPEC = StageSpec(
    "development-backtest", "WORK", ("development-backtest-plan",),
    BACKTEST_STAGE_SPEC.outputs,
)
TRACKING_STAGE_SPEC = StageSpec(
    "tracking", "WORK", ("backtest", "evaluation"),
    (
        OutputSpec("tracking_marker.json", "FILE", None),
        OutputSpec("tracking_request.json", "FILE", None),
    ),
)
DEVELOPMENT_TRACKING_STAGE_SPEC = StageSpec(
    "development-tracking", "WORK",
    ("development-backtest", "development-evaluation"),
    TRACKING_STAGE_SPEC.outputs,
)
SUMMARY_STAGE_SPEC = StageSpec(
    "summary", "EXPERIMENT", ("evaluation",),
    (
        OutputSpec("daily_ic.parquet", "FILE", None),
        OutputSpec("fold_metrics.parquet", "FILE", None),
        OutputSpec("manifest.json", "FILE", None),
        OutputSpec("metrics.json", "FILE", None),
    ),
)
DEVELOPMENT_SUMMARY_STAGE_SPEC = StageSpec(
    "development-research-summary", "EXPERIMENT",
    ("development-evaluation",), SUMMARY_STAGE_SPEC.outputs,
)
REPRODUCIBILITY_STAGE_SPEC = StageSpec(
    "reproducibility", "REPRO", (),
    (
        OutputSpec("attempt=1", "TREE", "attempt=1/read_audit.json"),
        OutputSpec("attempt=2", "TREE", "attempt=2/read_audit.json"),
        OutputSpec("reproducibility.json", "FILE", None),
    ),
)
QUALITY_STAGE_SPEC = StageSpec(
    "quality", "ACCEPTANCE", (),
    (
        OutputSpec("import_isolation.json", "FILE", None),
        OutputSpec("mypy.log", "FILE", None),
        OutputSpec("pytest.log", "FILE", None),
        OutputSpec("quality_report.json", "FILE", None),
        OutputSpec("ruff.log", "FILE", None),
    ),
)

STAGE_SPEC_REGISTRY: Mapping[str, StageSpec] = MappingProxyType({
    spec.name: spec for spec in (
        SNAPSHOT_STAGE_SPEC, DEVELOPMENT_SNAPSHOT_STAGE_SPEC,
        PROVIDER_STAGE_SPEC, DEVELOPMENT_PROVIDER_STAGE_SPEC,
        PROVIDER_VALIDATION_STAGE_SPEC,
        DEVELOPMENT_PROVIDER_VALIDATION_STAGE_SPEC,
        EXPERIMENT_IDENTITY_STAGE_SPEC,
        DEVELOPMENT_EXPERIMENT_IDENTITY_STAGE_SPEC,
        LABEL_STAGE_SPEC, DEVELOPMENT_LABEL_STAGE_SPEC,
        LABEL_RECONCILIATION_STAGE_SPEC,
        DEVELOPMENT_LABEL_RECONCILIATION_STAGE_SPEC,
        FOLDS_STAGE_SPEC, DEVELOPMENT_FOLDS_STAGE_SPEC,
        FEATURES_STAGE_SPEC, DEVELOPMENT_FEATURES_STAGE_SPEC,
        ALIGNMENT_STAGE_SPEC, DEVELOPMENT_ALIGNMENT_STAGE_SPEC,
        TRAIN_STAGE_SPEC, DEVELOPMENT_MODEL_STAGE_SPEC,
        PREDICTIONS_STAGE_SPEC, DEVELOPMENT_PREDICTIONS_STAGE_SPEC,
        EVALUATION_STAGE_SPEC, DEVELOPMENT_EVALUATION_STAGE_SPEC,
        TARGETS_STAGE_SPEC, DEVELOPMENT_TARGETS_STAGE_SPEC,
        BACKTEST_PLAN_STAGE_SPEC, DEVELOPMENT_BACKTEST_PLAN_STAGE_SPEC,
        BACKTEST_STAGE_SPEC, DEVELOPMENT_BACKTEST_STAGE_SPEC,
        TRACKING_STAGE_SPEC, DEVELOPMENT_TRACKING_STAGE_SPEC,
        SUMMARY_STAGE_SPEC, DEVELOPMENT_SUMMARY_STAGE_SPEC,
        REPRODUCIBILITY_STAGE_SPEC,
        QUALITY_STAGE_SPEC,
    )
})
STAGE_REGISTRY = STAGE_SPEC_REGISTRY


def get_m3_stage_registry() -> Mapping[str, StageSpec]:
    """Return the single immutable G8/G9 stage registry."""
    return STAGE_SPEC_REGISTRY

ExperimentArtifact = (
    VerifiedExperimentIdentity | VerifiedDevelopmentExampleExperimentIdentity
)
FoldArtifact = VerifiedFoldPlanArtifact | VerifiedDevelopmentExampleFoldPlanArtifact
LabelArtifact = VerifiedLabelArtifact | VerifiedDevelopmentExampleLabelArtifact
ReconciliationArtifact = (
    VerifiedLabelReconciliationArtifact
    | VerifiedDevelopmentExampleLabelReconciliationArtifact
)
EvaluationArtifact = (
    VerifiedEvaluationArtifact | VerifiedDevelopmentExampleEvaluationArtifact
)
SnapshotArtifact = VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact
ProviderArtifact = VerifiedProviderArtifact | VerifiedDevelopmentExampleProviderArtifact
ProviderValidationArtifact = (
    VerifiedProviderValidationArtifact
    | VerifiedDevelopmentExampleProviderValidationArtifact
)


def _require_config(config: LoadedM3Config) -> None:
    if type(config) is not LoadedM3Config:
        raise ValueError("plan config must be LoadedM3Config")


def _verified_digest(path: Path, *, root: Path, alias: str) -> ArtifactDigest:
    resolved_root = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(resolved_root):
        raise ValueError("verified artifact path escaped its root")
    raw = _read_plain_file(resolved)
    return ArtifactDigest(
        root_alias=alias,
        relative_path=resolved.relative_to(resolved_root).as_posix(),
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _external_files(
    *, root: Path, alias: str, relative_paths: Sequence[str],
) -> tuple[ExternalInput, ...]:
    return tuple(
        ExternalInput(_verified_digest(root / relative, root=root, alias=alias))
        for relative in sorted(set(relative_paths))
    )


def _static_node(
    *, node_id: str, spec: StageSpec, scope_key: str,
    final_directory: str, receipt_path: str,
    dependencies: Sequence[str] = (), inputs: Sequence[InputSpec] = (),
    fold: str | None = None, horizon: int | None = None,
) -> StageNode:
    return StageNode(
        node_id=node_id,
        spec_name=spec.name,
        scope=spec.scope,
        scope_key=scope_key,
        fold=fold,
        horizon=horizon,
        dependencies=tuple(sorted(set(dependencies))),
        inputs=tuple(inputs),
        publication=StaticDirectoryPublication(final_directory),
        output_specs=spec.outputs,
        receipt_path=receipt_path,
    )


def _development_example_id(*bundles: object) -> str | None:
    """Require one nominal track and return its development example identity."""
    development_types = {
        VerifiedDevelopmentExampleSnapshotArtifact,
        VerifiedDevelopmentExampleProviderArtifact,
        VerifiedDevelopmentExampleProviderValidationArtifact,
        VerifiedDevelopmentExampleExperimentIdentity,
        VerifiedDevelopmentExampleG1Release,
        VerifiedDevelopmentExampleLabelArtifact,
        VerifiedDevelopmentExampleFoldPlanArtifact,
        VerifiedDevelopmentExampleLabelReconciliationArtifact,
        VerifiedDevelopmentExampleEvaluationArtifact,
    }
    formal_types = {
        VerifiedSnapshotArtifact,
        VerifiedProviderArtifact,
        VerifiedProviderValidationArtifact,
        VerifiedExperimentIdentity,
        VerifiedG1Release,
        VerifiedLabelArtifact,
        VerifiedFoldPlanArtifact,
        VerifiedLabelReconciliationArtifact,
        VerifiedEvaluationArtifact,
    }
    types = {type(item) for item in bundles}
    if types <= formal_types:
        return None
    if not types <= development_types:
        raise ValueError("continuation verified identity mismatch")
    example_ids = {
        cast(
            str,
            getattr(item, "example_id")
            if hasattr(item, "example_id")
            else getattr(item, "manifest").example_id,
        )
        for item in bundles
    }
    if len(example_ids) != 1:
        raise ValueError("development continuation example identity mismatch")
    return next(iter(example_ids))


def _stage_root_for(root: Path, *, container: str) -> Path:
    resolved = root.resolve(strict=True)
    if resolved.parent.name != container:
        raise ValueError("verified artifact publication path drift")
    return resolved.parent.parent


def _stage_root_containing(root: Path, *, container: str) -> Path:
    resolved = root.resolve(strict=True)
    for parent in resolved.parents:
        if parent.name == container:
            return parent.parent
    raise ValueError("verified artifact publication path drift")


def _receipt_external(
    *, stage_root: Path, stage: str, key: str, expected_sha256: str,
) -> ExternalInput:
    digest = _verified_digest(
        stage_root / "receipts" / stage / f"{key}.json",
        root=stage_root,
        alias="stage",
    )
    if digest.sha256 != expected_sha256:
        raise ValueError("verified receipt bytes drift")
    return ExternalInput(digest)


def _snapshot_boundary_inputs(
    snapshot: SnapshotArtifact, *, include_request: bool = True,
    include_staging: bool = True,
) -> tuple[ExternalInput, ...]:
    stage = (
        "development-snapshot"
        if type(snapshot) is VerifiedDevelopmentExampleSnapshotArtifact
        else "snapshot"
    )
    stage_root = _stage_root_for(snapshot.root, container="snapshots")
    relative_paths = [
        f"snapshots/{snapshot.manifest.snapshot_id}/manifest.json",
        f"snapshots/{snapshot.manifest.snapshot_id}/session_calendar.parquet",
    ]
    if include_request:
        relative_paths.append(
            f"snapshot-requests/{snapshot.request.snapshot_request_key}.json"
        )
    if include_staging:
        relative_paths.extend(
            path.relative_to(stage_root).as_posix()
            for path in snapshot.staging_paths
        )
    direct = _external_files(
        root=stage_root,
        alias="stage",
        relative_paths=relative_paths,
    )
    if include_request:
        request = next(
            item for item in direct
            if item.artifact.relative_path.startswith("snapshot-requests/")
        )
        if request.artifact.sha256 != snapshot.request_sha256:
            raise ValueError("verified snapshot request bytes drift")
    return (
        *direct,
        _receipt_external(
            stage_root=stage_root,
            stage=stage,
            key=snapshot.request.snapshot_request_key,
            expected_sha256=snapshot.snapshot_receipt_sha256,
        ),
    )


def _provider_boundary_inputs(provider: ProviderArtifact) -> tuple[ExternalInput, ...]:
    stage = (
        "development-provider"
        if type(provider) is VerifiedDevelopmentExampleProviderArtifact
        else "provider"
    )
    stage_root = _stage_root_for(provider.root, container="providers")
    direct = _external_files(
        root=stage_root,
        alias="stage",
        relative_paths=(
            f"providers/{provider.manifest.provider_key}/provider_manifest.json",
            *(
                (provider.root / item.relative_path)
                .relative_to(stage_root)
                .as_posix()
                for item in provider.manifest.files
            ),
        ),
    )
    manifest = next(
        item for item in direct
        if item.artifact.relative_path.endswith("/provider_manifest.json")
    )
    if manifest.artifact.sha256 != provider.manifest_sha256:
        raise ValueError("verified provider manifest bytes drift")
    return (
        *direct,
        _receipt_external(
            stage_root=stage_root,
            stage=stage,
            key=provider.manifest.provider_key,
            expected_sha256=provider.provider_receipt_sha256,
        ),
    )


def _snapshot_identity_inputs(snapshot: SnapshotArtifact) -> tuple[ExternalInput, ...]:
    stage = (
        "development-snapshot"
        if type(snapshot) is VerifiedDevelopmentExampleSnapshotArtifact
        else "snapshot"
    )
    stage_root = _stage_root_for(snapshot.root, container="snapshots")
    manifest = _external_files(
        root=stage_root,
        alias="stage",
        relative_paths=(
            f"snapshots/{snapshot.manifest.snapshot_id}/manifest.json",
        ),
    )[0]
    if manifest.artifact.sha256 != snapshot.manifest_sha256:
        raise ValueError("verified snapshot manifest bytes drift")
    return (
        manifest,
        _receipt_external(
            stage_root=stage_root,
            stage=stage,
            key=snapshot.request.snapshot_request_key,
            expected_sha256=snapshot.snapshot_receipt_sha256,
        ),
    )


def _provider_identity_inputs(provider: ProviderArtifact) -> tuple[ExternalInput, ...]:
    stage = (
        "development-provider"
        if type(provider) is VerifiedDevelopmentExampleProviderArtifact
        else "provider"
    )
    stage_root = _stage_root_for(provider.root, container="providers")
    manifest = _external_files(
        root=stage_root,
        alias="stage",
        relative_paths=(
            f"providers/{provider.manifest.provider_key}/provider_manifest.json",
        ),
    )[0]
    if manifest.artifact.sha256 != provider.manifest_sha256:
        raise ValueError("verified provider manifest bytes drift")
    return (
        manifest,
        _receipt_external(
            stage_root=stage_root,
            stage=stage,
            key=provider.manifest.provider_key,
            expected_sha256=provider.provider_receipt_sha256,
        ),
    )


def _experiment_boundary_inputs(
    experiment: ExperimentArtifact,
) -> tuple[ExternalInput, ...]:
    stage = (
        "development-experiment-identity"
        if type(experiment) is VerifiedDevelopmentExampleExperimentIdentity
        else "experiment-identity"
    )
    stage_root = _stage_root_for(experiment.root, container="runs")
    direct = _external_files(
        root=stage_root,
        alias="stage",
        relative_paths=(
            f"runs/{experiment.manifest.experiment_key}/experiment_manifest.json",
        ),
    )
    if direct[0].artifact.sha256 != experiment.manifest_sha256:
        raise ValueError("verified experiment manifest bytes drift")
    return (
        *direct,
        _receipt_external(
            stage_root=stage_root,
            stage=stage,
            key=experiment.manifest.experiment_key,
            expected_sha256=experiment.experiment_receipt_sha256,
        ),
    )


def _provider_validation_boundary_inputs(
    validation: ProviderValidationArtifact,
) -> tuple[ExternalInput, ...]:
    stage = (
        "development-provider-validation"
        if type(validation) is VerifiedDevelopmentExampleProviderValidationArtifact
        else "provider-validation"
    )
    key = validation.summary.provider_validation_key
    stage_root = _stage_root_for(
        validation.root, container="provider-validations"
    )
    direct = _external_files(
        root=stage_root,
        alias="stage",
        relative_paths=(
            f"provider-validations/{key}/provider_validation.json",
            f"provider-validations/{key}/provider_validation.parquet",
        ),
    )
    summary = next(
        item for item in direct
        if item.artifact.relative_path.endswith("/provider_validation.json")
    )
    if summary.artifact.sha256 != validation.summary_sha256:
        raise ValueError("verified provider validation bytes drift")
    return (
        *direct,
        _receipt_external(
            stage_root=stage_root,
            stage=stage,
            key=key,
            expected_sha256=validation.validation_receipt_sha256,
        ),
    )


def _label_boundary_inputs(label: LabelArtifact) -> tuple[ExternalInput, ...]:
    stage = (
        "development-labels"
        if type(label) is VerifiedDevelopmentExampleLabelArtifact
        else "labels"
    )
    experiment_key = label.manifest.experiment_key
    horizon = label.manifest.horizon_sessions
    stage_root = _stage_root_containing(label.root, container="labels")
    direct = _external_files(
        root=stage_root,
        alias="stage",
        relative_paths=tuple(
            (label.root / name).relative_to(stage_root).as_posix()
            for name in ("diagnostics.parquet", "label_manifest.json", "labels.parquet")
        ),
    )
    manifest = next(
        item for item in direct
        if item.artifact.relative_path.endswith("/label_manifest.json")
    )
    if manifest.artifact.sha256 != label.manifest_sha256:
        raise ValueError("verified label manifest bytes drift")
    return (
        *direct,
        _receipt_external(
            stage_root=stage_root,
            stage=stage,
            key=f"{experiment_key}-h{horizon}",
            expected_sha256=label.label_receipt_sha256,
        ),
    )


def _fold_boundary_inputs(folds: FoldArtifact) -> tuple[ExternalInput, ...]:
    stage = (
        "development-folds"
        if type(folds) is VerifiedDevelopmentExampleFoldPlanArtifact
        else "folds"
    )
    stage_root = _stage_root_for(folds.root, container="folds")
    direct = _external_files(
        root=stage_root,
        alias="stage",
        relative_paths=(f"folds/{folds.manifest.experiment_key}/folds.json",),
    )
    if direct[0].artifact.sha256 != folds.manifest_sha256:
        raise ValueError("verified fold manifest bytes drift")
    return (
        *direct,
        _receipt_external(
            stage_root=stage_root,
            stage=stage,
            key=folds.manifest.experiment_key,
            expected_sha256=folds.folds_receipt_sha256,
        ),
    )


def _reconciliation_boundary_inputs(
    reconciliation: ReconciliationArtifact,
) -> tuple[ExternalInput, ...]:
    stage = (
        "development-label-reconciliation"
        if type(reconciliation)
        is VerifiedDevelopmentExampleLabelReconciliationArtifact
        else "label-reconciliation"
    )
    key = reconciliation.summary.reconciliation_key
    stage_root = _stage_root_for(
        reconciliation.root, container="label-reconciliations"
    )
    direct = _external_files(
        root=stage_root,
        alias="stage",
        relative_paths=(
            f"label-reconciliations/{key}/reconciliation.json",
            f"label-reconciliations/{key}/reconciliation.parquet",
        ),
    )
    summary = next(
        item for item in direct
        if item.artifact.relative_path.endswith("/reconciliation.json")
    )
    if summary.artifact.sha256 != reconciliation.summary_sha256:
        raise ValueError("verified reconciliation summary bytes drift")
    return (
        *direct,
        _receipt_external(
            stage_root=stage_root,
            stage=stage,
            key=key,
            expected_sha256=reconciliation.reconciliation_receipt_sha256,
        ),
    )


def _evaluation_boundary_inputs(
    evaluation: EvaluationArtifact,
) -> tuple[ExternalInput, ...]:
    stage = (
        "development-evaluation"
        if type(evaluation) is VerifiedDevelopmentExampleEvaluationArtifact
        else "evaluation"
    )
    stage_root = _stage_root_containing(evaluation.root, container="work")
    direct = _external_files(
        root=stage_root,
        alias="stage",
        relative_paths=tuple(
            (evaluation.root / name).relative_to(stage_root).as_posix()
            for name in ("daily_ic.parquet", "evaluation_manifest.json", "metrics.json")
        ),
    )
    manifest = next(
        item for item in direct
        if item.artifact.relative_path.endswith("/evaluation_manifest.json")
    )
    if manifest.artifact.sha256 != evaluation.manifest_sha256:
        raise ValueError("verified evaluation manifest bytes drift")
    return (
        *direct,
        _receipt_external(
            stage_root=stage_root,
            stage=stage,
            key=evaluation.manifest.work_key,
            expected_sha256=evaluation.evaluation_receipt_sha256,
        ),
    )


def _release_label_inputs(
    release: VerifiedG1Release | VerifiedDevelopmentExampleG1Release,
) -> tuple[ExternalInput, ...]:
    root = release.release.root.resolve(strict=True)
    selected = (
        release.release.manifest_path,
        *(dict(release.artifact_paths)[name] for name in (
            "bar_1d.parquet", "benchmark_bar_1d.parquet", "eligible_keys.parquet",
        )),
    )
    inputs = tuple(
        ExternalInput(_verified_digest(path, root=root, alias="g1-release"))
        for path in selected
    )
    manifest = next(
        item for item in inputs
        if item.artifact.relative_path == release.release.manifest_path.relative_to(root).as_posix()
    )
    if manifest.artifact.sha256 != release.manifest_sha256:
        raise ValueError("verified release manifest bytes drift")
    entries = {item.path: item for item in release.manifest.files}
    for item in inputs:
        name = Path(item.artifact.relative_path).name
        if name in entries and item.artifact.sha256 != entries[name].sha256:
            raise ValueError("verified release artifact bytes drift")
    return tuple(sorted(inputs, key=lambda item: (
        item.artifact.root_alias, item.artifact.relative_path,
    )))


def _release_reconciliation_inputs(
    release: VerifiedG1Release | VerifiedDevelopmentExampleG1Release,
) -> tuple[ExternalInput, ...]:
    root = release.release.root.resolve(strict=True)
    paths = (
        release.release.manifest_path,
        dict(release.artifact_paths)["benchmark_bar_1d.parquet"],
    )
    inputs = tuple(
        ExternalInput(_verified_digest(path, root=root, alias="g1-release"))
        for path in paths
    )
    if inputs[0].artifact.sha256 != release.manifest_sha256:
        raise ValueError("verified release manifest bytes drift")
    benchmark_entry = next(
        item for item in release.manifest.files
        if item.path == "benchmark_bar_1d.parquet"
    )
    if inputs[1].artifact.sha256 != benchmark_entry.sha256:
        raise ValueError("verified benchmark bytes drift")
    return tuple(sorted(inputs, key=lambda item: (
        item.artifact.root_alias, item.artifact.relative_path,
    )))


def _assert_release_snapshot_identity(
    release: VerifiedG1Release | VerifiedDevelopmentExampleG1Release,
    snapshot: SnapshotArtifact,
) -> None:
    release_id = (
        release.manifest.contract_release_id
        if type(release) is VerifiedDevelopmentExampleG1Release
        else release.manifest.release_id
    )
    if (
        snapshot.manifest.g1_release_id != release_id
        or snapshot.manifest.g1_release_manifest_sha256 != release.manifest_sha256
        or snapshot.request.g1_release_id != release_id
        or snapshot.request.g1_release_manifest_sha256 != release.manifest_sha256
    ):
        raise ValueError("release/snapshot identity drift")


def make_provider_materialization_run_plan(
    *, config: LoadedM3Config, snapshot: SnapshotArtifact,
    spec: ProviderBuildSpec, dump_tool_path: Path,
) -> RunPlan:
    """Build the identity-resolved provider materialization wave."""
    _require_config(config)
    if type(snapshot) not in {
        VerifiedSnapshotArtifact, VerifiedDevelopmentExampleSnapshotArtifact,
    } or type(spec) is not ProviderBuildSpec or not isinstance(dump_tool_path, Path):
        raise ValueError("provider continuation requires verified inputs")
    example_id = _development_example_id(snapshot)
    expected_key = (
        compute_provider_key(
            snapshot_id=snapshot.manifest.snapshot_id,
            provider_config_hash=config.provider_config_sha256,
            dump_tool_sha256=spec.dump_tool.sha256,
            qlib_version=spec.qlib_version,
            provider_runtime_fingerprint_sha256=spec.runtime_fingerprint.sha256,
            code_version=spec.code_version,
        )
        if example_id is None
        else compute_development_provider_key(
            example_id=example_id,
            snapshot_id=snapshot.manifest.snapshot_id,
            snapshot_manifest_sha256=snapshot.manifest_sha256,
            provider_config_sha256=config.provider_config_sha256,
            dump_tool_sha256=spec.dump_tool.sha256,
            qlib_version=spec.qlib_version,
            provider_runtime_fingerprint_sha256=spec.runtime_fingerprint.sha256,
            code_version=spec.code_version,
        )
    )
    if (
        spec.snapshot_id != snapshot.manifest.snapshot_id
        or spec.snapshot_manifest_sha256 != snapshot.manifest_sha256
        or spec.provider_config_sha256 != config.provider_config_sha256
        or spec.provider_key != expected_key
        or (
            example_id is None
            and spec.code_version.startswith("development-example/")
        )
        or (
            example_id is not None
            and not spec.code_version.startswith("development-example/")
        )
    ):
        raise ValueError("provider continuation identity drift")
    dump_digest = _verified_digest(
        dump_tool_path, root=dump_tool_path.parent, alias="qlib-dump-tool",
    )
    if (
        dump_digest.sha256 != spec.dump_tool.sha256
        or dump_digest.size_bytes != spec.dump_tool.size_bytes
    ):
        raise ValueError("provider dump tool identity drift")
    stage_spec = (
        PROVIDER_STAGE_SPEC
        if example_id is None
        else DEVELOPMENT_PROVIDER_STAGE_SPEC
    )
    node = _static_node(
        node_id=stage_spec.name,
        spec=stage_spec,
        scope_key=expected_key,
        final_directory=f"providers/{expected_key}",
        receipt_path=f"receipts/{stage_spec.name}/{expected_key}.json",
        inputs=(*_snapshot_boundary_inputs(snapshot), ExternalInput(dump_digest)),
    )
    return RunPlan("PROVIDER", (node,))


def make_provider_validation_run_plan(
    *, config: LoadedM3Config, snapshot: SnapshotArtifact,
    provider: ProviderArtifact, spec: ProviderValidationSpec,
) -> RunPlan:
    """Build validation only after provider bytes and receipt are verified."""
    _require_config(config)
    if type(spec) is not ProviderValidationSpec:
        raise ValueError("provider validation continuation requires verified inputs")
    example_id = _development_example_id(snapshot, provider)
    if (
        provider.manifest.snapshot_id != snapshot.manifest.snapshot_id
        or provider.manifest.snapshot_manifest_sha256 != snapshot.manifest_sha256
        or spec.provider_validation_config_sha256
        != config.provider_validation_config_sha256
        or spec.qlib_version != provider.manifest.qlib_version
    ):
        raise ValueError("provider validation continuation identity drift")
    expected_key = (
        compute_provider_validation_key(
            provider_key=provider.manifest.provider_key,
            provider_receipt_sha256=provider.provider_receipt_sha256,
            provider_validation_config_sha256=(
                config.provider_validation_config_sha256
            ),
            provider_runtime_fingerprint_sha256=(
                provider.manifest.provider_runtime_fingerprint_sha256
            ),
            code_version=spec.code_version,
        )
        if example_id is None
        else compute_development_provider_validation_key(
            example_id=example_id,
            provider_key=provider.manifest.provider_key,
            provider_receipt_sha256=provider.provider_receipt_sha256,
            provider_validation_config_sha256=(
                config.provider_validation_config_sha256
            ),
            provider_runtime_fingerprint_sha256=(
                provider.manifest.provider_runtime_fingerprint_sha256
            ),
            code_version=spec.code_version,
        )
    )
    if spec.provider_validation_key != expected_key:
        raise ValueError("provider validation key drift")
    stage_spec = (
        PROVIDER_VALIDATION_STAGE_SPEC
        if example_id is None
        else DEVELOPMENT_PROVIDER_VALIDATION_STAGE_SPEC
    )
    node = _static_node(
        node_id=stage_spec.name,
        spec=stage_spec,
        scope_key=expected_key,
        final_directory=f"provider-validations/{expected_key}",
        receipt_path=f"receipts/{stage_spec.name}/{expected_key}.json",
        inputs=(
            *_snapshot_boundary_inputs(snapshot),
            *_provider_boundary_inputs(provider),
        ),
    )
    return RunPlan("PROVIDER", (node,))


def make_experiment_identity_wave_plan(
    *, config: LoadedM3Config, snapshot: SnapshotArtifact,
    provider: ProviderArtifact,
    provider_validation: ProviderValidationArtifact,
    spec: ExperimentIdentitySpec,
) -> RunPlan:
    """Build ExperimentIdentity from four content inputs after a PASS-only gate."""
    _require_config(config)
    if type(spec) is not ExperimentIdentitySpec:
        raise ValueError("experiment identity continuation requires verified inputs")
    example_id = _development_example_id(snapshot, provider, provider_validation)
    summary = provider_validation.summary
    if (
        not summary.passed
        or provider.manifest.snapshot_id != snapshot.manifest.snapshot_id
        or provider.manifest.snapshot_manifest_sha256 != snapshot.manifest_sha256
        or summary.snapshot_id != snapshot.manifest.snapshot_id
        or summary.provider_key != provider.manifest.provider_key
        or summary.provider_manifest_sha256 != provider.manifest_sha256
        or summary.provider_receipt_sha256 != provider.provider_receipt_sha256
        or summary.provider_validation_config_sha256
        != config.provider_validation_config_sha256
        or summary.provider_runtime_fingerprint_sha256
        != provider.manifest.provider_runtime_fingerprint_sha256
        or spec.scientific_config_sha256 != config.scientific_config_sha256
    ):
        raise ValueError("experiment identity dependency gate drift")
    experiment_key = (
        compute_experiment_key(
            snapshot_id=snapshot.manifest.snapshot_id,
            provider_receipt_sha256=provider.provider_receipt_sha256,
            scientific_config_hash=config.scientific_config_sha256,
            code_version=spec.code_version,
            dependency_fingerprint_sha256=spec.dependency_fingerprint_sha256,
        )
        if example_id is None
        else compute_development_experiment_key(
            example_id=example_id,
            snapshot_id=snapshot.manifest.snapshot_id,
            provider_receipt_sha256=provider.provider_receipt_sha256,
            scientific_config_sha256=config.scientific_config_sha256,
            code_version=spec.code_version,
            dependency_fingerprint_sha256=spec.dependency_fingerprint_sha256,
        )
    )
    if (
        (example_id is None and spec.code_version.startswith("development-example/"))
        or (
            example_id is not None
            and not spec.code_version.startswith("development-example/")
        )
    ):
        raise ValueError("experiment identity code domain drift")
    stage_spec = (
        EXPERIMENT_IDENTITY_STAGE_SPEC
        if example_id is None
        else DEVELOPMENT_EXPERIMENT_IDENTITY_STAGE_SPEC
    )
    inputs = tuple(sorted(
        (*_snapshot_identity_inputs(snapshot), *_provider_identity_inputs(provider)),
        key=lambda item: (
            item.artifact.root_alias, item.artifact.relative_path,
        ),
    ))
    if len(inputs) != 4:
        raise ValueError("experiment identity content input closure drift")
    node = _static_node(
        node_id=stage_spec.name,
        spec=stage_spec,
        scope_key=experiment_key,
        final_directory=f"runs/{experiment_key}",
        receipt_path=f"receipts/{stage_spec.name}/{experiment_key}.json",
        inputs=inputs,
    )
    return RunPlan("EXPERIMENT", (node,))


def make_experiment_artifact_run_plan(
    *, config: LoadedM3Config,
    release: VerifiedG1Release | VerifiedDevelopmentExampleG1Release,
    snapshot: SnapshotArtifact, experiment: ExperimentArtifact,
) -> RunPlan:
    """Build the labels/folds wave after ExperimentIdentity is verified."""
    _require_config(config)
    example_id = _development_example_id(release, snapshot, experiment)
    _assert_release_snapshot_identity(release, snapshot)
    if (
        experiment.manifest.snapshot_id != snapshot.manifest.snapshot_id
        or experiment.manifest.snapshot_manifest_sha256 != snapshot.manifest_sha256
        or experiment.manifest.scientific_config_sha256
        != config.scientific_config_sha256
        or snapshot.request.signal_start != snapshot.manifest.signal_start
        or snapshot.request.signal_end != snapshot.manifest.signal_end
    ):
        raise ValueError("experiment continuation identity drift")
    horizons_value = config.section("labels")["horizons_sessions"]
    if type(horizons_value) is not tuple:
        raise ValueError("experiment continuation horizons invalid")
    horizons = tuple(sorted(cast(tuple[int, ...], horizons_value)))
    if not horizons or len(set(horizons)) != len(horizons):
        raise ValueError("experiment continuation horizons invalid")
    experiment_key = experiment.manifest.experiment_key
    label_spec = (
        LABEL_STAGE_SPEC if example_id is None else DEVELOPMENT_LABEL_STAGE_SPEC
    )
    folds_spec = (
        FOLDS_STAGE_SPEC if example_id is None else DEVELOPMENT_FOLDS_STAGE_SPEC
    )
    label_inputs = (
        *_release_label_inputs(release),
        *_snapshot_boundary_inputs(
            snapshot, include_request=False, include_staging=False,
        ),
        *_experiment_boundary_inputs(experiment),
    )
    nodes = [
        _static_node(
            node_id=f"labels.h{horizon}",
            spec=label_spec,
            scope_key=experiment_key,
            horizon=horizon,
            final_directory=f"labels/{experiment_key}/h{horizon}",
            receipt_path=(
                f"receipts/{label_spec.name}/{experiment_key}-h{horizon}.json"
            ),
            inputs=label_inputs,
        )
        for horizon in horizons
    ]
    nodes.append(_static_node(
        node_id="folds",
        spec=folds_spec,
        scope_key=experiment_key,
        final_directory=f"folds/{experiment_key}",
        receipt_path=f"receipts/{folds_spec.name}/{experiment_key}.json",
        inputs=(
            *_snapshot_boundary_inputs(
                snapshot, include_request=True, include_staging=False,
            ),
            *_experiment_boundary_inputs(experiment),
        ),
    ))
    return RunPlan("EXPERIMENT", tuple(nodes))


def make_label_reconciliation_run_plan(
    *, config: LoadedM3Config,
    release: VerifiedG1Release | VerifiedDevelopmentExampleG1Release,
    snapshot: SnapshotArtifact, provider: ProviderArtifact,
    provider_validation: ProviderValidationArtifact,
    experiment: ExperimentArtifact, labels: Sequence[LabelArtifact],
    specs: Sequence[LabelReconciliationSpec],
) -> RunPlan:
    """Build reconciliation only from verified labels with known manifest hashes."""
    _require_config(config)
    example_id = _development_example_id(
        release, snapshot, provider, provider_validation, experiment, *labels,
    )
    _assert_release_snapshot_identity(release, snapshot)
    if not labels or len(labels) != len(specs):
        raise ValueError("label reconciliation verified closure invalid")
    if (
        not provider_validation.summary.passed
        or provider.manifest.snapshot_id != snapshot.manifest.snapshot_id
        or provider_validation.summary.snapshot_id != snapshot.manifest.snapshot_id
        or provider_validation.summary.provider_key != provider.manifest.provider_key
        or provider_validation.summary.provider_receipt_sha256
        != provider.provider_receipt_sha256
        or provider_validation.summary.provider_manifest_sha256
        != provider.manifest_sha256
        or provider_validation.summary.provider_validation_config_sha256
        != config.provider_validation_config_sha256
        or provider_validation.summary.provider_runtime_fingerprint_sha256
        != provider.manifest.provider_runtime_fingerprint_sha256
        or experiment.manifest.provider_key != provider.manifest.provider_key
        or experiment.manifest.provider_receipt_sha256
        != provider.provider_receipt_sha256
        or experiment.manifest.snapshot_id != snapshot.manifest.snapshot_id
        or experiment.manifest.snapshot_manifest_sha256 != snapshot.manifest_sha256
    ):
        raise ValueError("label reconciliation upstream identity drift")
    label_by_horizon = {item.manifest.horizon_sessions: item for item in labels}
    spec_by_horizon: dict[int, LabelReconciliationSpec] = {
        item.horizon_sessions: item for item in specs
    }
    horizons_value = config.section("labels")["horizons_sessions"]
    if type(horizons_value) is not tuple:
        raise ValueError("label reconciliation horizons invalid")
    horizons = tuple(sorted(cast(tuple[int, ...], horizons_value)))
    if (
        set(label_by_horizon) != set(horizons)
        or set(spec_by_horizon) != set(horizons)
        or len(label_by_horizon) != len(labels)
        or len(spec_by_horizon) != len(specs)
    ):
        raise ValueError("label reconciliation horizon closure invalid")
    stage_spec = (
        LABEL_RECONCILIATION_STAGE_SPEC
        if example_id is None
        else DEVELOPMENT_LABEL_RECONCILIATION_STAGE_SPEC
    )
    common_inputs = (
        *_release_reconciliation_inputs(release),
        *_snapshot_boundary_inputs(
            snapshot, include_request=False, include_staging=False,
        ),
        *_provider_boundary_inputs(provider),
        *_provider_validation_boundary_inputs(provider_validation),
        *_experiment_boundary_inputs(experiment),
    )
    nodes: list[StageNode] = []
    for horizon in horizons:
        label = label_by_horizon[horizon]
        spec = spec_by_horizon[horizon]
        if (
            label.manifest.experiment_key != experiment.manifest.experiment_key
            or label.manifest.experiment_manifest_sha256
            != experiment.manifest_sha256
            or label.manifest.snapshot_id != snapshot.manifest.snapshot_id
            or label.manifest.snapshot_manifest_sha256 != snapshot.manifest_sha256
            or label.manifest.g1_release_id != snapshot.manifest.g1_release_id
            or label.manifest.g1_release_manifest_sha256
            != snapshot.manifest.g1_release_manifest_sha256
        ):
            raise ValueError("label reconciliation upstream identity drift")
        expected_key = (
            compute_label_reconciliation_key(
                experiment_key=experiment.manifest.experiment_key,
                horizon=horizon,
                provider_validation_receipt_sha256=(
                    provider_validation.validation_receipt_sha256
                ),
                label_manifest_sha256=label.manifest_sha256,
                label_reconciliation_config_sha256=(
                    config.label_reconciliation_config_sha256
                ),
                dependency_fingerprint_sha256=(
                    experiment.manifest.dependency_fingerprint_sha256
                ),
                code_version=spec.code_version,
            )
            if example_id is None
            else compute_development_label_reconciliation_key(
                example_id=example_id,
                experiment_key=experiment.manifest.experiment_key,
                horizon=horizon,
                provider_validation_receipt_sha256=(
                    provider_validation.validation_receipt_sha256
                ),
                label_manifest_sha256=label.manifest_sha256,
                label_reconciliation_config_sha256=(
                    config.label_reconciliation_config_sha256
                ),
                dependency_fingerprint_sha256=(
                    experiment.manifest.dependency_fingerprint_sha256
                ),
                code_version=spec.code_version,
            )
        )
        if (
            spec.reconciliation_key != expected_key
            or spec.experiment_key != experiment.manifest.experiment_key
            or spec.provider_validation_receipt_sha256
            != provider_validation.validation_receipt_sha256
            or spec.label_manifest_sha256 != label.manifest_sha256
            or spec.label_reconciliation_config_sha256
            != config.label_reconciliation_config_sha256
            or spec.dependency_fingerprint_sha256
            != experiment.manifest.dependency_fingerprint_sha256
        ):
            raise ValueError("label reconciliation identity drift")
        nodes.append(_static_node(
            node_id=f"label-reconciliation.h{horizon}",
            spec=stage_spec,
            scope_key=expected_key,
            horizon=horizon,
            final_directory=f"label-reconciliations/{expected_key}",
            receipt_path=f"receipts/{stage_spec.name}/{expected_key}.json",
            inputs=(*common_inputs, *_label_boundary_inputs(label)),
        ))
    return RunPlan("EXPERIMENT", tuple(nodes))


def make_work_run_plan(
    *, config: LoadedM3Config, experiment: ExperimentArtifact,
    folds: FoldArtifact, labels: Sequence[LabelArtifact],
    reconciliations: Sequence[ReconciliationArtifact],
) -> RunPlan:
    """Build fold-shared features and each ordered fold/horizon work chain."""
    _require_config(config)
    if type(experiment) not in {
        VerifiedExperimentIdentity, VerifiedDevelopmentExampleExperimentIdentity,
    } or type(folds) not in {
        VerifiedFoldPlanArtifact, VerifiedDevelopmentExampleFoldPlanArtifact,
    }:
        raise ValueError("work continuation requires verified experiment and folds")
    development = type(experiment) is VerifiedDevelopmentExampleExperimentIdentity
    allowed_label = (
        VerifiedDevelopmentExampleLabelArtifact if development else VerifiedLabelArtifact
    )
    allowed_reconciliation = (
        VerifiedDevelopmentExampleLabelReconciliationArtifact
        if development else VerifiedLabelReconciliationArtifact
    )
    if any(type(item) is not allowed_label for item in labels) or any(
        type(item) is not allowed_reconciliation for item in reconciliations
    ):
        raise ValueError("work continuation verified identity mismatch")
    _development_example_id(experiment, folds, *labels, *reconciliations)
    experiment_key = experiment.manifest.experiment_key
    if (
        folds.manifest.experiment_key != experiment_key
        or folds.manifest.experiment_manifest_sha256 != experiment.manifest_sha256
        or folds.manifest.snapshot_id != experiment.manifest.snapshot_id
        or folds.manifest.snapshot_manifest_sha256
        != experiment.manifest.snapshot_manifest_sha256
        or folds.manifest.scientific_config_sha256
        != config.scientific_config_sha256
        or experiment.manifest.scientific_config_sha256
        != config.scientific_config_sha256
    ):
        raise ValueError("work fold/experiment identity drift")
    folds_inputs = _fold_boundary_inputs(folds)
    experiment_inputs = _experiment_boundary_inputs(experiment)
    label_by_horizon = {item.manifest.horizon_sessions: item for item in labels}
    reconciliation_by_horizon = {
        item.summary.horizon_sessions: item for item in reconciliations
    }
    horizons = tuple(sorted(cast(Sequence[int], config.section("labels")["horizons_sessions"])))
    if set(label_by_horizon) != set(horizons) or set(reconciliation_by_horizon) != set(horizons):
        raise ValueError("work continuation label horizon closure invalid")
    if len(label_by_horizon) != len(labels) or len(reconciliation_by_horizon) != len(
        reconciliations
    ):
        raise ValueError("work continuation label horizon duplicate")
    g1_identities: set[tuple[str, str]] = set()
    validation_receipts: set[str] = set()
    for horizon in horizons:
        label = label_by_horizon[horizon]
        reconciliation = reconciliation_by_horizon[horizon]
        if (
            label.manifest.experiment_key != experiment_key
            or label.manifest.experiment_manifest_sha256
            != experiment.manifest_sha256
            or label.manifest.snapshot_id != experiment.manifest.snapshot_id
            or label.manifest.snapshot_manifest_sha256
            != experiment.manifest.snapshot_manifest_sha256
            or reconciliation.summary.experiment_key != experiment_key
            or reconciliation.summary.horizon_sessions != horizon
            or reconciliation.summary.label_manifest_sha256
            != label.manifest_sha256
            or not reconciliation.summary.passed
        ):
            raise ValueError("work label/reconciliation identity drift")
        g1_identities.add((
            label.manifest.g1_release_id,
            label.manifest.g1_release_manifest_sha256,
        ))
        validation_receipts.add(
            reconciliation.summary.provider_validation_receipt_sha256
        )
    if len(g1_identities) != 1 or len(validation_receipts) != 1:
        raise ValueError("work shared upstream identity drift")
    nodes: list[StageNode] = []
    feature_spec = (
        DEVELOPMENT_FEATURES_STAGE_SPEC if development else FEATURES_STAGE_SPEC
    )
    stage_defs: tuple[tuple[str, StageSpec], ...]
    if development:
        stage_defs = (
            ("alignment", DEVELOPMENT_ALIGNMENT_STAGE_SPEC),
            ("train", DEVELOPMENT_MODEL_STAGE_SPEC),
            ("predictions", DEVELOPMENT_PREDICTIONS_STAGE_SPEC),
            ("evaluation", DEVELOPMENT_EVALUATION_STAGE_SPEC),
            ("targets", DEVELOPMENT_TARGETS_STAGE_SPEC),
            ("backtest_plan", DEVELOPMENT_BACKTEST_PLAN_STAGE_SPEC),
            ("backtest", DEVELOPMENT_BACKTEST_STAGE_SPEC),
            ("tracking", DEVELOPMENT_TRACKING_STAGE_SPEC),
        )
    else:
        stage_defs = (
            ("alignment", ALIGNMENT_STAGE_SPEC),
            ("train", TRAIN_STAGE_SPEC),
            ("predictions", PREDICTIONS_STAGE_SPEC),
            ("evaluation", EVALUATION_STAGE_SPEC),
            ("targets", TARGETS_STAGE_SPEC),
            ("backtest_plan", BACKTEST_PLAN_STAGE_SPEC),
        )
    for planned_fold in sorted(folds.manifest.folds, key=lambda item: item.name):
        fold = planned_fold.name
        feature = _static_node(
            node_id=f"features.{fold}", spec=feature_spec,
            scope_key=experiment_key, fold=fold,
            final_directory=f"features/{experiment_key}/{fold}",
            receipt_path=(
                f"receipts/{feature_spec.name}/{experiment_key}.{fold}.json"
            ),
            inputs=(*folds_inputs, *experiment_inputs),
        )
        nodes.append(feature)
        for horizon in horizons:
            work_key = compute_work_key(
                experiment_key=experiment_key, fold=fold, horizon=horizon,
            )
            prefix = f"{fold}.h{horizon}"
            label = label_by_horizon[horizon]
            reconciliation = reconciliation_by_horizon[horizon]
            boundary_inputs = (
                *_label_boundary_inputs(label),
                *_reconciliation_boundary_inputs(reconciliation),
                *folds_inputs, *experiment_inputs,
            )
            chain: list[StageNode] = []
            previous = feature.node_id
            for stage_name, spec in stage_defs:
                node_id = f"{stage_name}.{prefix}"
                dependencies = [previous]
                inputs: list[InputSpec] = list(boundary_inputs)
                if previous == feature.node_id:
                    inputs.append(StageOutputInput(previous, "stage", "feature_manifest.json"))
                else:
                    previous_spec = STAGE_SPEC_REGISTRY[chain[-1].spec_name]
                    inputs.extend(
                        StageOutputInput(previous, "stage", output.relative_path)
                        for output in previous_spec.outputs
                    )
                if stage_name == "tracking":
                    evaluation_id = f"evaluation.{prefix}"
                    dependencies.append(evaluation_id)
                    inputs.append(StageOutputInput(evaluation_id, "stage", "metrics.json"))
                node = _static_node(
                    node_id=node_id, spec=spec, scope_key=work_key,
                    fold=fold, horizon=horizon,
                    final_directory=f"work/{work_key}/{stage_name}",
                    receipt_path=(
                        f"receipts/{spec.name}/{work_key}.json"
                    ),
                    dependencies=dependencies, inputs=inputs,
                )
                chain.append(node)
                previous = node.node_id
            nodes.extend(chain)
    return RunPlan("WORK", tuple(nodes))


def make_summary_run_plan(
    *, config: LoadedM3Config, experiment: ExperimentArtifact,
    evaluations: Sequence[EvaluationArtifact],
) -> RunPlan:
    """Build one summary per horizon/model/version from exact fold closures."""
    _require_config(config)
    if type(experiment) not in {
        VerifiedExperimentIdentity, VerifiedDevelopmentExampleExperimentIdentity,
    } or not evaluations:
        raise ValueError("summary continuation requires verified inputs")
    development = type(experiment) is VerifiedDevelopmentExampleExperimentIdentity
    expected = (
        VerifiedDevelopmentExampleEvaluationArtifact
        if development else VerifiedEvaluationArtifact
    )
    if any(type(item) is not expected for item in evaluations):
        raise ValueError("summary continuation verified identity mismatch")
    _development_example_id(experiment, *evaluations)
    experiment_key = experiment.manifest.experiment_key
    if experiment.manifest.scientific_config_sha256 != config.scientific_config_sha256:
        raise ValueError("summary experiment/config identity drift")
    groups: dict[tuple[int, str, str], list[EvaluationArtifact]] = {}
    for item in evaluations:
        manifest = item.manifest
        if (
            manifest.experiment_key != experiment_key
            or manifest.scientific_config_sha256
            != config.scientific_config_sha256
            or manifest.work_key
            != compute_work_key(
                experiment_key=experiment_key,
                fold=manifest.fold,
                horizon=manifest.horizon_sessions,
            )
        ):
            raise ValueError("summary evaluation identity drift")
        groups.setdefault(
            (manifest.horizon_sessions, manifest.model, manifest.model_version), []
        ).append(item)
    configured_horizons = set(
        cast(Sequence[int], config.section("labels")["horizons_sessions"])
    )
    if {key[0] for key in groups} != configured_horizons:
        raise ValueError("summary horizon closure drift")
    fold_closures = {
        tuple(sorted(item.manifest.fold for item in group))
        for group in groups.values()
    }
    if (
        any(len(group) < 2 for group in groups.values())
        or any(len({item.manifest.fold for item in group}) != len(group) for group in groups.values())
        or any(
            len({item.manifest.fold_plan_manifest_sha256 for item in group}) != 1
            or len({item.manifest.label_manifest_sha256 for item in group}) != 1
            for group in groups.values()
        )
        or len(fold_closures) != 1
    ):
        raise ValueError("summary exact fold closure drift")
    summary_spec = (
        DEVELOPMENT_SUMMARY_STAGE_SPEC if development else SUMMARY_STAGE_SPEC
    )
    nodes: list[StageNode] = []
    for horizon, model, model_version in sorted(groups):
        if (
            _NODE_PATTERN.fullmatch(model) is None
            or _NODE_PATTERN.fullmatch(model_version) is None
        ):
            raise ValueError("summary model path identity invalid")
        group = tuple(sorted(groups[(horizon, model, model_version)], key=lambda item: item.manifest.fold))
        inputs: list[InputSpec] = list(_experiment_boundary_inputs(experiment))
        for item in group:
            inputs.extend(_evaluation_boundary_inputs(item))
        identity = f"h{horizon}.{model}.{model_version}"
        nodes.append(_static_node(
            node_id=f"summary.{identity}", spec=summary_spec,
            scope_key=experiment_key, horizon=horizon,
            final_directory=f"summaries/{experiment_key}/h{horizon}/{model}/{model_version}",
            receipt_path=(
                f"receipts/{summary_spec.name}/{experiment_key}.{identity}.json"
            ),
            inputs=inputs,
        ))
    return RunPlan("SUMMARY", tuple(nodes))


def make_snapshot_run_plan(
    *, snapshot_request_key: str, inputs: Sequence[ArtifactDigest],
) -> RunPlan:
    """Build the only plan whose final directory is unknown until closure verify."""
    _require_hex64(snapshot_request_key)
    ordered = tuple(sorted(inputs, key=lambda item: (
        item.root_alias, item.relative_path
    )))
    if len(ordered) != 4 or len({
        (item.root_alias, item.relative_path) for item in ordered
    }) != 4:
        raise ValueError("snapshot plan 必须精确绑定四个 G1 inputs")
    node = StageNode(
        node_id="snapshot",
        spec_name=SNAPSHOT_STAGE_SPEC.name,
        scope="SNAPSHOT",
        scope_key=snapshot_request_key,
        fold=None,
        horizon=None,
        dependencies=(),
        inputs=tuple(ExternalInput(item) for item in ordered),
        publication=SnapshotContentPublication(
            content_directory_parent="snapshots",
            request_record_path=f"snapshot-requests/{snapshot_request_key}.json",
            manifest_relative_path="manifest.json",
            content_id_field="snapshot_id",
        ),
        output_specs=SNAPSHOT_STAGE_SPEC.outputs,
        receipt_path=f"receipts/snapshot/{snapshot_request_key}.json",
    )
    return RunPlan(continuation="SNAPSHOT", nodes=(node,))


def make_development_snapshot_run_plan(
    *, release: VerifiedDevelopmentExampleG1Release,
    snapshot_request_key: str, artifact_root: Path, root_alias: str,
) -> RunPlan:
    """Bind a development snapshot plan to four files from a verified example."""
    if type(release) is not VerifiedDevelopmentExampleG1Release:
        raise ValueError("development release 类型非法")
    verified = verify_development_example_g1_release(root=release.release.root)
    _require_hex64(snapshot_request_key)
    _require_real_directory(artifact_root, label="artifact root")
    if type(root_alias) is not str or _ROOT_ALIAS_PATTERN.fullmatch(root_alias) is None:
        raise ValueError("artifact root alias 非法")
    root = artifact_root.resolve(strict=True)
    paths = (
        verified.release.manifest_path,
        *(dict(verified.artifact_paths)[name] for name in (
            "bar_1d.parquet", "universe_membership.parquet",
            "trade_calendar.parquet",
        )),
    )
    inputs: list[ArtifactDigest] = []
    for path in paths:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise ValueError("development input 不属于 artifact root")
        raw = _read_plain_file(resolved)
        inputs.append(ArtifactDigest(
            root_alias=root_alias,
            relative_path=resolved.relative_to(root).as_posix(),
            size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
        ))
    ordered = tuple(sorted(inputs, key=lambda item: (
        item.root_alias, item.relative_path
    )))
    node = StageNode(
        node_id="snapshot",
        spec_name=DEVELOPMENT_SNAPSHOT_STAGE_SPEC.name,
        scope="SNAPSHOT",
        scope_key=snapshot_request_key,
        fold=None,
        horizon=None,
        dependencies=(),
        inputs=tuple(ExternalInput(item) for item in ordered),
        publication=SnapshotContentPublication(
            content_directory_parent="snapshots",
            request_record_path=f"snapshot-requests/{snapshot_request_key}.json",
            manifest_relative_path="manifest.json",
            content_id_field="snapshot_id",
        ),
        output_specs=DEVELOPMENT_SNAPSHOT_STAGE_SPEC.outputs,
        receipt_path=(
            f"receipts/development-snapshot/{snapshot_request_key}.json"
        ),
    )
    return RunPlan(continuation="SNAPSHOT", nodes=(node,))
