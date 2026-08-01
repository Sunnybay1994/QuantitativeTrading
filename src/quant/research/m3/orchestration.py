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
from quant.data.m3_release import commit_directory_noreplace
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    SnapshotBuildResult,
    SnapshotRequestRecordV1,
    VerifiedEvaluationArtifact,
    VerifiedExperimentIdentity,
    VerifiedFoldPlanArtifact,
    VerifiedLabelArtifact,
    VerifiedLabelReconciliationArtifact,
)
from quant.research.m3.run_state import (
    ArtifactDigest,
    Scope,
    StageReceipt,
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
    verify_development_example_g1_release,
)
from quant.research.m3.snapshot import (
    read_snapshot_request_record,
    snapshot_request_record_bytes,
)

_NODE_PATTERN = re.compile(r"^[a-z0-9._-]+$")
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


@dataclass(frozen=True)
class SnapshotStageResult:
    snapshot_root: Path
    request_record_path: Path
    receipt_path: Path
    build: SnapshotBuildResult
    request: SnapshotRequestRecordV1
    receipt: StageReceipt
    reused: bool


class StageRunner:
    """Serial G8B runner; this increment implements snapshot publication only."""

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
                _remove_owned_temp(temp_root, self._stage_root / ".stage-tmp")

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
        if type(alias) is not str or _NODE_PATTERN.fullmatch(alias) is None:
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


def _remove_owned_temp(path: Path, temp_parent: Path) -> None:
    try:
        resolved_parent = temp_parent.resolve(strict=True)
        resolved = path.resolve(strict=True)
        if resolved.parent != resolved_parent or not resolved.name.startswith(".snapshot."):
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
PROVIDER_VALIDATION_STAGE_SPEC = StageSpec(
    "provider-validation", "PROVIDER", ("provider",),
    (
        OutputSpec("provider_validation.json", "FILE", None),
        OutputSpec("provider_validation.parquet", "FILE", None),
    ),
)
EXPERIMENT_STAGE_SPEC = StageSpec(
    "experiment", "EXPERIMENT", ("provider-validation",),
    (OutputSpec("experiment_manifest.json", "FILE", None),),
)
LABEL_STAGE_SPEC = StageSpec(
    "labels", "EXPERIMENT", ("experiment",),
    (
        OutputSpec("diagnostics.parquet", "FILE", None),
        OutputSpec("label_manifest.json", "FILE", None),
        OutputSpec("labels.parquet", "FILE", None),
    ),
)
LABEL_RECONCILIATION_STAGE_SPEC = StageSpec(
    "label-reconciliation", "EXPERIMENT", ("labels", "provider-validation"),
    (
        OutputSpec("reconciliation.json", "FILE", None),
        OutputSpec("reconciliation.parquet", "FILE", None),
    ),
)
FOLDS_STAGE_SPEC = StageSpec(
    "folds", "EXPERIMENT", ("label-reconciliation",),
    (OutputSpec("folds.json", "FILE", None),),
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
ALIGNMENT_STAGE_SPEC = StageSpec(
    "alignment", "WORK", ("features",),
    (
        OutputSpec("alignment_manifest.json", "FILE", None),
        OutputSpec("diagnostics.parquet", "FILE", None),
        OutputSpec("train.parquet", "FILE", None),
        OutputSpec("validation.parquet", "FILE", None),
    ),
)
TRAIN_STAGE_SPEC = StageSpec(
    "train", "WORK", ("alignment",),
    (
        OutputSpec("model.metadata.json", "FILE", None),
        OutputSpec("model.txt", "FILE", None),
        OutputSpec("validation_curve.parquet", "FILE", None),
    ),
)
PREDICTIONS_STAGE_SPEC = StageSpec(
    "predictions", "WORK", ("train",),
    (
        OutputSpec("prediction_manifest.json", "FILE", None),
        OutputSpec("predictions.parquet", "FILE", None),
    ),
)
EVALUATION_STAGE_SPEC = StageSpec(
    "evaluation", "WORK", ("predictions",),
    (
        OutputSpec("daily_ic.parquet", "FILE", None),
        OutputSpec("evaluation_manifest.json", "FILE", None),
        OutputSpec("metrics.json", "FILE", None),
    ),
)
TARGETS_STAGE_SPEC = StageSpec(
    "targets", "WORK", ("evaluation",),
    (
        OutputSpec("target_daily.parquet", "FILE", None),
        OutputSpec("target_manifest.json", "FILE", None),
        OutputSpec("target_weights.parquet", "FILE", None),
    ),
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
BACKTEST_STAGE_SPEC = StageSpec(
    "backtest", "WORK", ("backtest_plan",),
    (
        OutputSpec("0p5x", "TREE", "backtest_manifest.json"),
        OutputSpec("1p0x", "TREE", "backtest_manifest.json"),
        OutputSpec("2p0x", "TREE", "backtest_manifest.json"),
        OutputSpec("backtest_manifest.json", "FILE", None),
        OutputSpec("backtest_metrics.json", "FILE", None),
    ),
)
TRACKING_STAGE_SPEC = StageSpec(
    "tracking", "WORK", ("backtest", "evaluation"),
    (
        OutputSpec("tracking_marker.json", "FILE", None),
        OutputSpec("tracking_request.json", "FILE", None),
    ),
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

STAGE_SPEC_REGISTRY: Mapping[str, StageSpec] = MappingProxyType({
    spec.name: spec for spec in (
        SNAPSHOT_STAGE_SPEC, DEVELOPMENT_SNAPSHOT_STAGE_SPEC,
        PROVIDER_STAGE_SPEC, PROVIDER_VALIDATION_STAGE_SPEC,
        EXPERIMENT_STAGE_SPEC, LABEL_STAGE_SPEC,
        LABEL_RECONCILIATION_STAGE_SPEC, FOLDS_STAGE_SPEC,
        FEATURES_STAGE_SPEC, ALIGNMENT_STAGE_SPEC, TRAIN_STAGE_SPEC,
        PREDICTIONS_STAGE_SPEC, EVALUATION_STAGE_SPEC, TARGETS_STAGE_SPEC,
        BACKTEST_PLAN_STAGE_SPEC, BACKTEST_STAGE_SPEC, TRACKING_STAGE_SPEC,
        SUMMARY_STAGE_SPEC,
    )
})
STAGE_REGISTRY = STAGE_SPEC_REGISTRY

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
    experiment_key = experiment.manifest.experiment_key
    folds_inputs = _external_files(
        root=folds.root, alias="verified-folds", relative_paths=("folds.json",),
    )
    experiment_inputs = _external_files(
        root=experiment.root, alias="verified-experiment",
        relative_paths=("experiment_manifest.json",),
    )
    label_by_horizon = {item.manifest.horizon_sessions: item for item in labels}
    reconciliation_by_horizon = {
        item.summary.horizon_sessions: item for item in reconciliations
    }
    horizons = tuple(sorted(cast(Sequence[int], config.section("labels")["horizons_sessions"])))
    if set(label_by_horizon) != set(horizons) or set(reconciliation_by_horizon) != set(horizons):
        raise ValueError("work continuation label horizon closure invalid")
    nodes: list[StageNode] = []
    for planned_fold in sorted(folds.manifest.folds, key=lambda item: item.name):
        fold = planned_fold.name
        feature = _static_node(
            node_id=f"features.{fold}", spec=FEATURES_STAGE_SPEC,
            scope_key=experiment_key, fold=fold,
            final_directory=f"features/{experiment_key}/{fold}",
            receipt_path=f"receipts/features/{experiment_key}.{fold}.json",
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
                *_external_files(
                    root=label.root, alias=f"verified-label-h{horizon}",
                    relative_paths=("label_manifest.json", "labels.parquet"),
                ),
                *_external_files(
                    root=reconciliation.root,
                    alias=f"verified-reconciliation-h{horizon}",
                    relative_paths=(
                        "reconciliation.json", "reconciliation.parquet",
                    ),
                ),
                *folds_inputs, *experiment_inputs,
            )
            chain: list[StageNode] = []
            previous = feature.node_id
            stage_defs = (
                ("alignment", ALIGNMENT_STAGE_SPEC),
                ("train", TRAIN_STAGE_SPEC),
                ("predictions", PREDICTIONS_STAGE_SPEC),
                ("evaluation", EVALUATION_STAGE_SPEC),
                ("targets", TARGETS_STAGE_SPEC),
                ("backtest_plan", BACKTEST_PLAN_STAGE_SPEC),
                ("backtest", BACKTEST_STAGE_SPEC),
                ("tracking", TRACKING_STAGE_SPEC),
            )
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
                    receipt_path=f"receipts/work/{work_key}.{stage_name}.json",
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
    """Build one experiment summary from a strict verified evaluation closure."""
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
    experiment_key = experiment.manifest.experiment_key
    ordered = tuple(sorted(
        evaluations,
        key=lambda item: (item.manifest.fold, item.manifest.horizon_sessions),
    ))
    if len({
        (item.manifest.fold, item.manifest.horizon_sessions) for item in ordered
    }) != len(ordered):
        raise ValueError("summary evaluation fold/horizon duplicate")
    inputs: list[InputSpec] = list(_external_files(
        root=experiment.root, alias="verified-experiment",
        relative_paths=("experiment_manifest.json",),
    ))
    for index, item in enumerate(ordered):
        inputs.extend(_external_files(
            root=item.root, alias=f"verified-evaluation-{index:03d}",
            relative_paths=("daily_ic.parquet", "evaluation_manifest.json", "metrics.json"),
        ))
    summary = _static_node(
        node_id="summary", spec=SUMMARY_STAGE_SPEC, scope_key=experiment_key,
        final_directory=f"summaries/{experiment_key}",
        receipt_path=f"receipts/summary/{experiment_key}.json",
        inputs=inputs,
    )
    return RunPlan("SUMMARY", (summary,))


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
    if type(root_alias) is not str or _NODE_PATTERN.fullmatch(root_alias) is None:
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
