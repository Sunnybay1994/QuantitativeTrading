"""Formal G9B-F0 readiness evidence bound to one fresh G1 release."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal, NoReturn, cast

import polars as pl

from quant.data.m3_mappers import compute_benchmark_source_snapshot_id
from quant.data.m3_release import G1ManifestV5, VerifiedG1Release, verify_g1_release
from quant.research.m3.config import LoadedM3Config, load_m3_config
from quant.research.m3.orchestration import (
    ExternalInput,
    READINESS_EVIDENCE_STAGE_SPEC,
    StageBuildReport,
    StageContext,
    StageNode,
    StageRunner,
    StaticDirectoryPublication,
)
from quant.research.m3.provider import build_provider_runtime_fingerprint
from quant.research.m3.readiness import ReadinessIssue, audit_m3_readiness
from quant.research.m3.run_state import ArtifactDigest, StageReceipt, verify_stage_receipt
from quant.research.m3.runtime_identity import (
    M3RuntimeIdentityV1,
    M3SourceDigestV1,
    compute_m3_runtime_identity,
)

_CODE = "M3_READINESS_EVIDENCE_INVALID"
_SCHEMA = "m3-readiness-evidence-v1"
_KEY_VERSION = "m3-readiness-evidence-key-v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_READINESS_FILES = (
    "bar_1d.parquet",
    "benchmark_bar_1d.parquet",
    "instrument.parquet",
    "trade_calendar.parquet",
    "universe_membership.parquet",
)


class M3ReadinessEvidenceError(ValueError):
    """Stable, redacted readiness evidence failure."""

    code: str

    def __init__(self) -> None:
        self.code = _CODE
        super().__init__(_CODE)


@dataclass(frozen=True)
class ReadinessEvidenceReportV1:
    schema_version: Literal["m3-readiness-evidence-v1"]
    readiness_key: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    full_config_sha256: str
    provider_runtime_fingerprint_sha256: str
    code_version: str
    dependency_fingerprint_sha256: str
    issues: tuple[ReadinessIssue, ...]

    def __post_init__(self) -> None:
        if (
            self.schema_version != _SCHEMA
            or not _is_hex64(self.readiness_key)
            or not _is_hex64(self.g1_release_id)
            or not _is_hex64(self.g1_release_manifest_sha256)
            or not _is_hex64(self.full_config_sha256)
            or not _is_hex64(self.provider_runtime_fingerprint_sha256)
            or type(self.code_version) is not str
            or not self.code_version
            or not _is_hex64(self.dependency_fingerprint_sha256)
            or type(self.issues) is not tuple
            or any(type(item) is not ReadinessIssue for item in self.issues)
            or self.issues != _canonical_issues(self.issues)
        ):
            raise M3ReadinessEvidenceError()
        for issue in self.issues:
            if (
                type(issue.code) is not str
                or not issue.code
                or issue.severity not in {"ERROR", "WARNING"}
                or type(issue.message) is not str
                or not issue.message
            ):
                raise M3ReadinessEvidenceError()


@dataclass(frozen=True)
class VerifiedReadinessEvidenceArtifact:
    root: Path
    report: ReadinessEvidenceReportV1
    report_digest: ArtifactDigest
    receipt: StageReceipt
    receipt_sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.root, Path)
            or type(self.report) is not ReadinessEvidenceReportV1
            or type(self.report_digest) is not ArtifactDigest
            or type(self.receipt) is not StageReceipt
            or not _is_hex64(self.receipt_sha256)
        ):
            raise M3ReadinessEvidenceError()

    def __reduce__(self) -> Any:
        raise TypeError(_CODE)


def run_readiness_evidence_stage(
    *,
    project_root: Path,
    config: LoadedM3Config,
    config_relative: PurePosixPath,
    release: VerifiedG1Release,
    resume: bool = True,
) -> VerifiedReadinessEvidenceArtifact:
    """Publish one canonical readiness report and strict stage receipt."""
    result: VerifiedReadinessEvidenceArtifact | None = None
    failed = False
    try:
        result = _run_stage(
            project_root=project_root,
            config=config,
            config_relative=config_relative,
            release=release,
            resume=resume,
        )
    except Exception:
        failed = True
    if failed or result is None:
        _fail()
    return result


def verify_readiness_evidence_artifact(
    *,
    root: Path,
    receipt_path: Path,
    project_root: Path,
    config: LoadedM3Config,
    config_relative: PurePosixPath,
    release: VerifiedG1Release,
) -> VerifiedReadinessEvidenceArtifact:
    """Freshly rebuild readiness evidence from current G1/config/runtime bytes."""
    result: VerifiedReadinessEvidenceArtifact | None = None
    failed = False
    try:
        project, config_path = _validate_outer(
            project_root=project_root,
            config=config,
            config_relative=config_relative,
            release=release,
        )
        fresh = _fresh_release(release)
        runtime = _runtime(project, config, config_relative)
        provider_sha = build_provider_runtime_fingerprint().sha256
        key = _readiness_key(
            release=fresh,
            config=config,
            runtime=runtime,
            provider_sha=provider_sha,
        )
        stage_root = _stage_root(project, config)
        expected_root = stage_root / "acceptance" / "readiness" / key
        expected_receipt = (
            stage_root / "receipts" / "readiness-evidence" / f"{key}.json"
        )
        if root.resolve(strict=True) != expected_root.resolve(strict=True):
            raise ValueError
        if receipt_path.resolve(strict=True) != expected_receipt.resolve(strict=True):
            raise ValueError
        roots = MappingProxyType({"PROJECT": project})
        result = _verify_tree(
            root=expected_root,
            receipt_path=expected_receipt,
            roots=roots,
            expected_inputs=_inputs(
                project=project,
                config_path=config_path,
                release=fresh,
                runtime=runtime,
                roots=roots,
            ),
            expected_report=_build_report(
                release=fresh,
                config=config,
                runtime=runtime,
                provider_sha=provider_sha,
            ),
        )
    except Exception:
        failed = True
    if failed or result is None:
        _fail()
    return result


def _run_stage(
    *,
    project_root: Path,
    config: LoadedM3Config,
    config_relative: PurePosixPath,
    release: VerifiedG1Release,
    resume: bool,
) -> VerifiedReadinessEvidenceArtifact:
    if type(resume) is not bool:
        raise ValueError
    project, config_path = _validate_outer(
        project_root=project_root,
        config=config,
        config_relative=config_relative,
        release=release,
    )
    fresh = _fresh_release(release)
    runtime = _runtime(project, config, config_relative)
    provider_sha = build_provider_runtime_fingerprint().sha256
    key = _readiness_key(
        release=fresh,
        config=config,
        runtime=runtime,
        provider_sha=provider_sha,
    )
    stage_root = _stage_root(project, config)
    roots = MappingProxyType({"PROJECT": project})
    inputs = _inputs(
        project=project,
        config_path=config_path,
        release=fresh,
        runtime=runtime,
        roots=roots,
    )
    node = StageNode(
        node_id=f"readiness-evidence-{key[:16]}",
        spec_name=READINESS_EVIDENCE_STAGE_SPEC.name,
        scope="ACCEPTANCE",
        scope_key=key,
        fold=None,
        horizon=None,
        dependencies=(),
        inputs=inputs,
        publication=StaticDirectoryPublication(f"acceptance/readiness/{key}"),
        output_specs=READINESS_EVIDENCE_STAGE_SPEC.outputs,
        receipt_path=f"receipts/readiness-evidence/{key}.json",
    )
    runner = StageRunner(stage_root=stage_root, artifact_roots=roots, config=config)

    def handler(context: StageContext) -> StageBuildReport:
        current_config = load_m3_config(config_path)
        current_release = _fresh_release(release)
        current_runtime = _runtime(project, current_config, config_relative)
        current_provider = build_provider_runtime_fingerprint().sha256
        report = _build_report(
            release=current_release,
            config=current_config,
            runtime=current_runtime,
            provider_sha=current_provider,
        )
        if report.readiness_key != key or current_config != config:
            raise ValueError
        _write_exclusive(
            context.temp_output_root / "readiness_report.json",
            _canonical_bytes(_report_payload(report)),
        )
        return StageBuildReport(("readiness_report.json",))

    def closure(candidate: Path) -> None:
        current_config = load_m3_config(config_path)
        current_release = _fresh_release(release)
        current_runtime = _runtime(project, current_config, config_relative)
        current_provider = build_provider_runtime_fingerprint().sha256
        expected = _build_report(
            release=current_release,
            config=current_config,
            runtime=current_runtime,
            provider_sha=current_provider,
        )
        if expected.readiness_key != key:
            raise ValueError
        _verify_tree_without_receipt(candidate, expected)

    static = runner.run_static(
        node=node,
        handler=handler,
        closure_verifier=closure,
        resume=resume,
    )
    final_config = load_m3_config(config_path)
    final_release = _fresh_release(release)
    final_runtime = _runtime(project, final_config, config_relative)
    final_provider = build_provider_runtime_fingerprint().sha256
    expected_report = _build_report(
        release=final_release,
        config=final_config,
        runtime=final_runtime,
        provider_sha=final_provider,
    )
    if expected_report.readiness_key != key or final_config != config:
        raise ValueError
    return _verify_tree(
        root=static.final_root,
        receipt_path=static.receipt_path,
        roots=roots,
        expected_inputs=inputs,
        expected_report=expected_report,
    )


def _validate_outer(
    *,
    project_root: Path,
    config: LoadedM3Config,
    config_relative: PurePosixPath,
    release: VerifiedG1Release,
) -> tuple[Path, Path]:
    if (
        type(config) is not LoadedM3Config
        or type(config_relative) is not PurePosixPath
        or type(release) is not VerifiedG1Release
        or type(release.manifest) is not G1ManifestV5
        or config.raw_config_sha256 is None
    ):
        raise ValueError
    if (
        config_relative.is_absolute()
        or not config_relative.parts
        or config_relative.parts[0] != "configs"
        or any(part in {"", ".", ".."} for part in config_relative.parts)
    ):
        raise ValueError
    project = _real_directory(project_root)
    config_path = _real_file(project.joinpath(*config_relative.parts))
    if hashlib.sha256(config_path.read_bytes()).hexdigest() != config.raw_config_sha256:
        raise ValueError
    if not release.release.root.is_relative_to(project):
        raise ValueError
    return project, config_path


def _fresh_release(outer: VerifiedG1Release) -> VerifiedG1Release:
    fresh = verify_g1_release(release=outer.release)
    if type(fresh) is not VerifiedG1Release or fresh != outer:
        raise ValueError
    return fresh


def _build_report(
    *,
    release: VerifiedG1Release,
    config: LoadedM3Config,
    runtime: M3RuntimeIdentityV1,
    provider_sha: str,
) -> ReadinessEvidenceReportV1:
    paths = dict(release.artifact_paths)
    identities = tuple(
        (item.endpoint, item.request_id, item.stable_response_sha256)
        for item in release.manifest.input_receipts
        if item.source == "tushare"
        and item.endpoint in {"fund_daily", "fund_adj", "fund_div"}
    )
    expected_snapshot = compute_benchmark_source_snapshot_id(identities=identities)
    issues = audit_m3_readiness(
        bars=pl.read_parquet(paths["bar_1d.parquet"]),
        instruments=pl.read_parquet(paths["instrument.parquet"]),
        membership=pl.read_parquet(paths["universe_membership.parquet"]),
        calendars=pl.read_parquet(paths["trade_calendar.parquet"]),
        benchmark_bars=pl.read_parquet(paths["benchmark_bar_1d.parquet"]),
        config=config.document,
        expected_benchmark_source_snapshot_id=expected_snapshot,
    )
    key = _readiness_key(
        release=release,
        config=config,
        runtime=runtime,
        provider_sha=provider_sha,
    )
    return ReadinessEvidenceReportV1(
        schema_version="m3-readiness-evidence-v1",
        readiness_key=key,
        g1_release_id=release.release.release_id,
        g1_release_manifest_sha256=release.manifest_sha256,
        full_config_sha256=config.full_config_sha256,
        provider_runtime_fingerprint_sha256=provider_sha,
        code_version=runtime.code_version,
        dependency_fingerprint_sha256=runtime.dependency_fingerprint_sha256,
        issues=_canonical_issues(tuple(issues)),
    )


def _readiness_key(
    *,
    release: VerifiedG1Release,
    config: LoadedM3Config,
    runtime: M3RuntimeIdentityV1,
    provider_sha: str,
) -> str:
    return hashlib.sha256(
        _canonical_bytes(
            [
                _KEY_VERSION,
                release.release.release_id,
                release.manifest_sha256,
                config.full_config_sha256,
                provider_sha,
                runtime.code_version,
                runtime.dependency_fingerprint_sha256,
            ]
        )
    ).hexdigest()


def _inputs(
    *,
    project: Path,
    config_path: Path,
    release: VerifiedG1Release,
    runtime: M3RuntimeIdentityV1,
    roots: Mapping[str, Path],
) -> tuple[ExternalInput, ...]:
    paths = {
        config_path,
        project / "pyproject.toml",
        release.release.manifest_path,
        release.release.quality_path,
    }
    paths.update(project / item.relative_path for item in runtime.source_files)
    release_paths = dict(release.artifact_paths)
    paths.update(release_paths[name] for name in _READINESS_FILES)
    return tuple(
        ExternalInput(_digest(path, roots))
        for path in sorted(paths, key=lambda item: str(item).casefold())
    )


def _verify_tree(
    *,
    root: Path,
    receipt_path: Path,
    roots: Mapping[str, Path],
    expected_inputs: tuple[ExternalInput, ...],
    expected_report: ReadinessEvidenceReportV1,
) -> VerifiedReadinessEvidenceArtifact:
    report = _verify_tree_without_receipt(root, expected_report)
    receipt = verify_stage_receipt(
        receipt_path=receipt_path,
        artifact_roots=roots,
    )
    report_path = root / "readiness_report.json"
    output = _digest(report_path, roots)
    if (
        type(receipt) is not StageReceipt
        or receipt.stage != "readiness-evidence"
        or receipt.scope != "ACCEPTANCE"
        or receipt.scope_key != report.readiness_key
        or receipt.inputs != tuple(item.artifact for item in expected_inputs)
        or receipt.outputs != (output,)
    ):
        raise ValueError
    raw_receipt = _real_file(receipt_path).read_bytes()
    return VerifiedReadinessEvidenceArtifact(
        root=_real_directory(root),
        report=report,
        report_digest=output,
        receipt=receipt,
        receipt_sha256=hashlib.sha256(raw_receipt).hexdigest(),
    )


def _verify_tree_without_receipt(
    root: Path,
    expected: ReadinessEvidenceReportV1,
) -> ReadinessEvidenceReportV1:
    directory = _real_directory(root)
    if {entry.name for entry in os.scandir(directory)} != {"readiness_report.json"}:
        raise ValueError
    raw = _real_file(directory / "readiness_report.json").read_bytes()
    value = _strict_json(raw)
    issues_raw = value.get("issues")
    if type(issues_raw) is not list:
        raise ValueError
    issues = tuple(
        ReadinessIssue(
            code=cast(str, item.get("code")),
            severity=cast(Any, item.get("severity")),
            message=cast(str, item.get("message")),
        )
        for item in issues_raw
        if type(item) is dict
    )
    if len(issues) != len(issues_raw):
        raise ValueError
    report = ReadinessEvidenceReportV1(
        schema_version=cast(Literal["m3-readiness-evidence-v1"], value.get("schema_version")),
        readiness_key=cast(str, value.get("readiness_key")),
        g1_release_id=cast(str, value.get("g1_release_id")),
        g1_release_manifest_sha256=cast(
            str,
            value.get("g1_release_manifest_sha256"),
        ),
        full_config_sha256=cast(str, value.get("full_config_sha256")),
        provider_runtime_fingerprint_sha256=cast(
            str,
            value.get("provider_runtime_fingerprint_sha256"),
        ),
        code_version=cast(str, value.get("code_version")),
        dependency_fingerprint_sha256=cast(
            str,
            value.get("dependency_fingerprint_sha256"),
        ),
        issues=issues,
    )
    if value != _report_payload(report) or report != expected:
        raise ValueError
    return report


def _report_payload(report: ReadinessEvidenceReportV1) -> dict[str, object]:
    value = asdict(report)
    value["issues"] = [asdict(item) for item in report.issues]
    return value


def _runtime(
    project: Path,
    config: LoadedM3Config,
    relative: PurePosixPath,
) -> M3RuntimeIdentityV1:
    if config.raw_config_sha256 is None:
        raise ValueError
    return compute_m3_runtime_identity(
        project_root=project,
        config_paths=(relative,),
        frozen_config_digests=(
            M3SourceDigestV1(relative.as_posix(), config.raw_config_sha256),
        ),
    )


def _stage_root(project: Path, config: LoadedM3Config) -> Path:
    logical = config.section("tracking")["artifact_root"]
    if type(logical) is not str:
        raise ValueError
    relative = PurePosixPath(logical)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError
    return _real_directory(project.joinpath(*relative.parts))


def _digest(path: Path, roots: Mapping[str, Path]) -> ArtifactDigest:
    leaf = _real_file(path)
    matches = [
        (alias, root.resolve(strict=True))
        for alias, root in roots.items()
        if leaf.is_relative_to(root.resolve(strict=True))
    ]
    if not matches:
        raise ValueError
    alias, root = max(matches, key=lambda item: len(item[1].parts))
    raw = leaf.read_bytes()
    return ArtifactDigest(
        alias,
        leaf.relative_to(root).as_posix(),
        len(raw),
        hashlib.sha256(raw).hexdigest(),
    )


def _canonical_issues(
    value: tuple[ReadinessIssue, ...],
) -> tuple[ReadinessIssue, ...]:
    return tuple(
        sorted(value, key=lambda item: (item.severity, item.code, item.message))
    )


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _strict_json(raw: bytes) -> dict[str, object]:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    if type(value) is not dict or _canonical_bytes(value) != raw:
        raise ValueError
    return cast(dict[str, object], value)


def _write_exclusive(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _real_directory(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    st = resolved.lstat()
    if not stat.S_ISDIR(st.st_mode) or resolved.is_symlink() or _is_reparse(st):
        raise ValueError
    return resolved


def _real_file(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    st = resolved.lstat()
    if (
        not stat.S_ISREG(st.st_mode)
        or resolved.is_symlink()
        or _is_reparse(st)
        or st.st_nlink != 1
    ):
        raise ValueError
    return resolved


def _is_reparse(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & _REPARSE)


def _is_hex64(value: object) -> bool:
    return type(value) is str and _HEX64.fullmatch(value) is not None


def _fail() -> NoReturn:
    raise M3ReadinessEvidenceError() from None


__all__ = [
    "M3ReadinessEvidenceError",
    "ReadinessEvidenceReportV1",
    "VerifiedReadinessEvidenceArtifact",
    "run_readiness_evidence_stage",
    "verify_readiness_evidence_artifact",
]
