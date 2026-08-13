"""Fixed-command, identity-bound M3 engineering quality artifact (G9A)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal, NoReturn, Protocol, cast

from quant.research.m3.config import LoadedM3Config, load_m3_config
from quant.research.m3.orchestration import (
    ExternalInput,
    QUALITY_STAGE_SPEC,
    StageBuildReport,
    StageContext,
    StageNode,
    StageRunner,
    StaticDirectoryPublication,
)
from quant.research.m3.run_state import ArtifactDigest, StageReceipt, verify_stage_receipt
from quant.research.m3.runtime_identity import (
    M3RuntimeIdentityV1,
    M3SourceDigestV1,
    compute_m3_runtime_identity,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_POLICY: Literal["m3-quality-commands-v1"] = "m3-quality-commands-v1"
_SCHEMA: Literal["m3-quality-report-v1"] = "m3-quality-report-v1"
_CODE = "M3_QUALITY_ARTIFACT_INVALID"
_ROLLBACK_CODE = "M3_QUALITY_ROLLBACK_FAILED"
_LOG_SCHEMA = "m3-quality-command-log-v1"
_IMPORT_POLICY = "m3-import-isolation-v1"
_CHECK_NAMES = ("pytest", "ruff", "mypy", "import_isolation")
_OUTPUT_NAMES = ("pytest.log", "ruff.log", "mypy.log", "import_isolation.json")
_ABSOLUTE = re.compile(r"(?i)(?:[a-z]:[\\/]|/(?:home|mnt|users|tmp|var|opt)/)")
_SECRET = re.compile(
    r"(?i)(?:password|passwd|secret|api[_-]?key|access[_-]?token|bearer)\s*[:=]"
)


class M3QualityGateError(ValueError):
    """Stable, redacted G9A failure."""

    code: str

    def __init__(self, code: str = _CODE) -> None:
        if code not in {_CODE, _ROLLBACK_CODE}:
            raise ValueError("unknown quality error")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CommandExecution:
    exit_code: int
    stdout: bytes
    stderr: bytes

    def __post_init__(self) -> None:
        if (
            type(self.exit_code) is not int
            or type(self.stdout) is not bytes
            or type(self.stderr) is not bytes
        ):
            raise M3QualityGateError()


class CommandExecutor(Protocol):
    def run(
        self, *, argv: tuple[str, ...], cwd: Path, env: Mapping[str, str]
    ) -> CommandExecution: ...


@dataclass(frozen=True)
class QualityCheckResultV1:
    name: Literal["pytest", "ruff", "mypy", "import_isolation"]
    logical_argv: tuple[str, ...]
    exit_code: int
    stdout_sha256: str
    stderr_sha256: str

    def __post_init__(self) -> None:
        if (
            self.name not in _CHECK_NAMES
            or type(self.logical_argv) is not tuple
            or not self.logical_argv
            or any(type(value) is not str or not value for value in self.logical_argv)
            or type(self.exit_code) is not int
            or not _HEX64.fullmatch(self.stdout_sha256)
            or not _HEX64.fullmatch(self.stderr_sha256)
        ):
            raise M3QualityGateError()


@dataclass(frozen=True)
class QualityReportV1:
    schema_version: Literal["m3-quality-report-v1"]
    quality_key: str
    command_policy_version: Literal["m3-quality-commands-v1"]
    code_version: str
    dependency_fingerprint_sha256: str
    checks: tuple[QualityCheckResultV1, ...]
    passed: Literal[True]

    def __post_init__(self) -> None:
        if (
            self.schema_version != _SCHEMA
            or not _HEX64.fullmatch(self.quality_key)
            or self.command_policy_version != _POLICY
            or type(self.code_version) is not str
            or not self.code_version
            or not _HEX64.fullmatch(self.dependency_fingerprint_sha256)
            or type(self.checks) is not tuple
            or tuple(item.name for item in self.checks) != _CHECK_NAMES
            or any(type(item) is not QualityCheckResultV1 for item in self.checks)
            or any(item.exit_code != 0 for item in self.checks)
            or self.passed is not True
        ):
            raise M3QualityGateError()


@dataclass(frozen=True)
class VerifiedQualityArtifact:
    report: QualityReportV1
    report_digest: ArtifactDigest
    receipt: StageReceipt
    receipt_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.report) is not QualityReportV1
            or type(self.report_digest) is not ArtifactDigest
            or type(self.receipt) is not StageReceipt
            or not _HEX64.fullmatch(self.receipt_sha256)
        ):
            raise M3QualityGateError()

    def __reduce__(self) -> Any:
        raise TypeError(_CODE)


@dataclass(frozen=True)
class _Command:
    name: Literal["pytest", "ruff", "mypy", "import_isolation"]
    actual_tail: tuple[str, ...]
    logical_tail: tuple[str, ...]
    output_name: str


class _SubprocessExecutor:
    def run(
        self, *, argv: tuple[str, ...], cwd: Path, env: Mapping[str, str]
    ) -> CommandExecution:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=50_400,
            check=False,
        )
        return CommandExecution(completed.returncode, completed.stdout, completed.stderr)


def run_quality_gate(
    *, project_root: Path, config: LoadedM3Config,
    config_relative: PurePosixPath, executor: CommandExecutor | None = None,
    resume: bool = True,
) -> VerifiedQualityArtifact:
    """Run the fixed quality registry and publish only a complete PASS artifact."""
    failed = False
    result: VerifiedQualityArtifact | None = None
    try:
        result = _run_quality_gate(
            project_root=project_root,
            config=config,
            config_relative=config_relative,
            executor=_SubprocessExecutor() if executor is None else executor,
            resume=resume,
        )
    except Exception:
        failed = True
    if failed or result is None:
        _fail(_CODE)
    return result


def verify_quality_artifact(
    *, root: Path, receipt_path: Path, project_root: Path,
    config: LoadedM3Config, config_relative: PurePosixPath,
    artifact_roots: Mapping[str, Path],
) -> VerifiedQualityArtifact:
    """Freshly bind one quality artifact to current code/dependency/config."""
    failed = False
    result: VerifiedQualityArtifact | None = None
    try:
        project = _real_directory(project_root)
        config_path = _real_file(project.joinpath(*config_relative.parts))
        runtime = _runtime(project, config, config_relative)
        roots = MappingProxyType(dict(artifact_roots))
        result = _verify_quality_tree(
            root=root,
            receipt_path=receipt_path,
            artifact_roots=roots,
            runtime=runtime,
            config=config,
            expected_inputs=_quality_inputs(
                project=project,
                config_path=config_path,
                runtime=runtime,
                roots=roots,
            ),
        )
    except Exception:
        failed = True
    if failed or result is None:
        _fail(_CODE)
    return result


def _run_quality_gate(
    *, project_root: Path, config: LoadedM3Config,
    config_relative: PurePosixPath, executor: CommandExecutor, resume: bool,
) -> VerifiedQualityArtifact:
    if (
        type(config) is not LoadedM3Config
        or not isinstance(config_relative, PurePosixPath)
        or not callable(getattr(executor, "run", None))
        or type(resume) is not bool
    ):
        raise ValueError
    project = _real_directory(project_root)
    config_path = _real_file(project.joinpath(*config_relative.parts))
    if hashlib.sha256(config_path.read_bytes()).hexdigest() != config.raw_config_sha256:
        raise ValueError
    before = _runtime(project, config, config_relative)
    quality_key = _quality_key(before, config)
    stage_root = _stage_root(project, config)
    # One non-overlapping project root is required because the quality receipt
    # binds both source/config inputs and its stage-owned outputs.
    roots = MappingProxyType({"PROJECT": project})
    inputs = _quality_inputs(
        project=project, config_path=config_path, runtime=before, roots=roots
    )
    node = StageNode(
        node_id=f"quality-{quality_key[:16]}",
        spec_name=QUALITY_STAGE_SPEC.name,
        scope="ACCEPTANCE",
        scope_key=quality_key,
        fold=None,
        horizon=None,
        dependencies=(),
        inputs=inputs,
        publication=StaticDirectoryPublication(f"acceptance/quality/{quality_key}"),
        output_specs=QUALITY_STAGE_SPEC.outputs,
        receipt_path=f"receipts/quality/{quality_key}.json",
    )
    runner = StageRunner(stage_root=stage_root, artifact_roots=roots, config=config)

    def handler(context: StageContext) -> StageBuildReport:
        checks: list[QualityCheckResultV1] = []
        env = _quality_environment()
        for command in _commands(project):
            execution = executor.run(
                argv=(sys.executable, *command.actual_tail), cwd=project, env=env
            )
            stdout = _normalize_log(execution.stdout, project=project)
            stderr = _normalize_log(execution.stderr, project=project)
            _validate_log(stdout)
            _validate_log(stderr)
            if execution.exit_code != 0:
                raise ValueError
            checks.append(
                QualityCheckResultV1(
                    name=command.name,
                    logical_argv=("<PYTHON>", *command.logical_tail),
                    exit_code=execution.exit_code,
                    stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                    stderr_sha256=hashlib.sha256(stderr).hexdigest(),
                )
            )
            _write_exclusive(
                context.temp_output_root / command.output_name,
                _canonical_bytes(
                    {
                        "schema_version": _LOG_SCHEMA,
                        "name": command.name,
                        "exit_code": execution.exit_code,
                        "stdout": stdout.decode("utf-8"),
                        "stderr": stderr.decode("utf-8"),
                    }
                ),
            )
        after_config = load_m3_config(config_path)
        after = _runtime(project, after_config, config_relative)
        if (
            after.code_version != before.code_version
            or after.dependency_fingerprint_sha256
            != before.dependency_fingerprint_sha256
            or after_config.full_config_sha256 != config.full_config_sha256
            or after_config.raw_config_sha256 != config.raw_config_sha256
        ):
            raise ValueError
        report = QualityReportV1(
            schema_version=_SCHEMA,
            quality_key=quality_key,
            command_policy_version=_POLICY,
            code_version=after.code_version,
            dependency_fingerprint_sha256=after.dependency_fingerprint_sha256,
            checks=tuple(checks),
            passed=True,
        )
        _write_exclusive(
            context.temp_output_root / "quality_report.json",
            _canonical_bytes(asdict(report)),
        )
        return StageBuildReport(
            tuple(sorted(item.relative_path for item in QUALITY_STAGE_SPEC.outputs))
        )

    def closure(candidate: Path) -> None:
        current_config = load_m3_config(config_path)
        current = _runtime(project, current_config, config_relative)
        _verify_quality_tree_without_receipt(
            root=candidate, runtime=current, config=current_config,
            quality_key=quality_key,
        )

    static = runner.run_static(
        node=node, handler=handler, closure_verifier=closure, resume=resume
    )
    return _verify_quality_tree(
        root=static.final_root,
        receipt_path=static.receipt_path,
        artifact_roots=roots,
        runtime=_runtime(project, config, config_relative),
        config=config,
        expected_inputs=inputs,
    )


def _commands(project: Path) -> tuple[_Command, ...]:
    import_code = (
        "import ast,json,pathlib,sys\n"
        f"root=pathlib.Path({str(project)!r})\n"
        f"sys.path.insert(0,{str(project / 'src')!r})\n"
        "import quant.domain,quant.strategies,quant.backtest\n"
        "heavy={'qlib','lightgbm','mlflow'}\n"
        "assert not heavy&set(sys.modules)\n"
        "allowed={'qlib':'src/quant/research/m3/qlib_adapter.py',"
        "'lightgbm':'src/quant/research/m3/model.py',"
        "'mlflow':'src/quant/research/m3/tracking.py'}\n"
        "bad=[]\n"
        "for p in sorted((root/'src'/'quant').rglob('*.py')):\n"
        " tree=ast.parse(p.read_text(encoding='utf-8'))\n"
        " for n in ast.walk(tree):\n"
        "  names=([a.name for a in n.names] if isinstance(n,ast.Import) else "
        "([n.module] if isinstance(n,ast.ImportFrom) and n.module else []))\n"
        "  for imported in names:\n"
        "   package=imported.split('.')[0]\n"
        "   relative=p.relative_to(root).as_posix()\n"
        "   if package in heavy and relative!=allowed[package]: bad.append([relative,package])\n"
        "assert not bad,bad\n"
        "print(json.dumps({'policy':'m3-import-isolation-v1','passed':True},"
        "sort_keys=True,separators=(',',':')))\n"
    )
    return (
        _Command("pytest", ("-m", "pytest", "-q"), ("-m", "pytest", "-q"), "pytest.log"),
        _Command(
            "ruff",
            ("-m", "ruff", "check", "src", "tests"),
            ("-m", "ruff", "check", "src", "tests"),
            "ruff.log",
        ),
        _Command("mypy", ("-m", "mypy", "src"), ("-m", "mypy", "src"), "mypy.log"),
        _Command(
            "import_isolation",
            ("-I", "-c", import_code),
            ("-I", "-c", _IMPORT_POLICY),
            "import_isolation.json",
        ),
    )


def _verify_quality_tree(
    *, root: Path, receipt_path: Path, artifact_roots: Mapping[str, Path],
    runtime: M3RuntimeIdentityV1, config: LoadedM3Config,
    expected_inputs: tuple[ExternalInput, ...],
) -> VerifiedQualityArtifact:
    quality_key = _quality_key(runtime, config)
    report = _verify_quality_tree_without_receipt(
        root=root, runtime=runtime, config=config, quality_key=quality_key
    )
    receipt = verify_stage_receipt(
        receipt_path=receipt_path, artifact_roots=artifact_roots
    )
    if (
        type(receipt) is not StageReceipt
        or receipt.stage != "quality"
        or receipt.scope != "ACCEPTANCE"
        or receipt.scope_key != quality_key
        or receipt.inputs != tuple(item.artifact for item in expected_inputs)
        or receipt.outputs
        != tuple(
            sorted(
                (
                    _digest(root / item.relative_path, artifact_roots)
                    for item in QUALITY_STAGE_SPEC.outputs
                ),
                key=lambda item: (item.root_alias, item.relative_path),
            )
        )
    ):
        raise ValueError
    receipt_raw = _real_file(receipt_path).read_bytes()
    report_path = root / "quality_report.json"
    return VerifiedQualityArtifact(
        report=report,
        report_digest=_digest(report_path, artifact_roots),
        receipt=receipt,
        receipt_sha256=hashlib.sha256(receipt_raw).hexdigest(),
    )


def _verify_quality_tree_without_receipt(
    *, root: Path, runtime: M3RuntimeIdentityV1,
    config: LoadedM3Config, quality_key: str,
) -> QualityReportV1:
    directory = _real_directory(root)
    expected = {item.relative_path for item in QUALITY_STAGE_SPEC.outputs}
    if {item.name for item in os.scandir(directory)} != expected:
        raise ValueError
    raw_report = _real_file(directory / "quality_report.json").read_bytes()
    value = _strict_json(raw_report)
    checks_raw = value.get("checks")
    if type(checks_raw) is not list:
        raise ValueError
    checks = tuple(
        QualityCheckResultV1(
            name=cast(Any, item["name"]),
            logical_argv=tuple(cast(Sequence[str], item["logical_argv"])),
            exit_code=cast(int, item["exit_code"]),
            stdout_sha256=cast(str, item["stdout_sha256"]),
            stderr_sha256=cast(str, item["stderr_sha256"]),
        )
        for item in checks_raw
        if type(item) is dict
    )
    report = QualityReportV1(
        schema_version=cast(Any, value.get("schema_version")),
        quality_key=cast(str, value.get("quality_key")),
        command_policy_version=cast(Any, value.get("command_policy_version")),
        code_version=cast(str, value.get("code_version")),
        dependency_fingerprint_sha256=cast(
            str, value.get("dependency_fingerprint_sha256")
        ),
        checks=checks,
        passed=cast(Any, value.get("passed")),
    )
    if (
        raw_report != _canonical_bytes(asdict(report))
        or report.quality_key != quality_key
        or report.code_version != runtime.code_version
        or report.dependency_fingerprint_sha256
        != runtime.dependency_fingerprint_sha256
    ):
        raise ValueError
    for output_name, check in zip(_OUTPUT_NAMES, report.checks, strict=True):
        log = _strict_json(_real_file(directory / output_name).read_bytes())
        if (
            log.get("schema_version") != _LOG_SCHEMA
            or log.get("name") != check.name
            or log.get("exit_code") != 0
            or type(log.get("stdout")) is not str
            or type(log.get("stderr")) is not str
            or hashlib.sha256(cast(str, log["stdout"]).encode()).hexdigest()
            != check.stdout_sha256
            or hashlib.sha256(cast(str, log["stderr"]).encode()).hexdigest()
            != check.stderr_sha256
        ):
            raise ValueError
        _validate_log(cast(str, log["stdout"]).encode())
        _validate_log(cast(str, log["stderr"]).encode())
    return report


def _runtime(
    project: Path, config: LoadedM3Config, relative: PurePosixPath
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


def _quality_key(runtime: M3RuntimeIdentityV1, config: LoadedM3Config) -> str:
    return hashlib.sha256(
        _canonical_bytes(
            [
                "m3-quality-key-v1",
                _POLICY,
                runtime.code_version,
                runtime.dependency_fingerprint_sha256,
                config.full_config_sha256,
            ]
        )
    ).hexdigest()


def _quality_inputs(
    *, project: Path, config_path: Path, runtime: M3RuntimeIdentityV1,
    roots: Mapping[str, Path],
) -> tuple[ExternalInput, ...]:
    paths = {config_path, project / "pyproject.toml"}
    paths.update(project / item.relative_path for item in runtime.source_files)
    return tuple(
        ExternalInput(_digest(path, roots))
        for path in sorted(paths, key=lambda item: str(item).casefold())
    )


def _stage_root(project: Path, config: LoadedM3Config) -> Path:
    logical = config.section("tracking")["artifact_root"]
    if type(logical) is not str:
        raise ValueError
    relative = PurePosixPath(logical)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
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
        root_alias=alias,
        relative_path=leaf.relative_to(root).as_posix(),
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _normalize_log(raw: bytes, *, project: Path) -> bytes:
    text = raw.decode("utf-8", "strict").replace("\r\n", "\n")
    replacements = (
        (str(project.resolve()), "<WORKSPACE>"),
        (str(project.resolve()).replace("\\", "/"), "<WORKSPACE>"),
        (str(Path(sys.prefix).resolve()), "<PYTHON>"),
        (str(Path(sys.prefix).resolve()).replace("\\", "/"), "<PYTHON>"),
        (str(Path(sys.executable).resolve()), "<PYTHON>"),
        (str(Path(sys.executable).resolve()).replace("\\", "/"), "<PYTHON>"),
    )
    for before, after in replacements:
        text = text.replace(before, after)
    return text.encode("utf-8")


def _validate_log(raw: bytes) -> None:
    text = raw.decode("utf-8", "strict")
    if _ABSOLUTE.search(text) or _SECRET.search(text) or "\x00" in text:
        raise ValueError


def _quality_environment() -> Mapping[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env["PYTHONHASHSEED"] = "0"
    return MappingProxyType(env)


def _strict_json(raw: bytes) -> dict[str, object]:
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


def _write_exclusive(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


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


def _fail(code: str) -> NoReturn:
    error = M3QualityGateError(code)
    error.__cause__ = None
    error.__context__ = None
    raise error


__all__ = [
    "CommandExecution",
    "CommandExecutor",
    "M3QualityGateError",
    "QualityCheckResultV1",
    "QualityReportV1",
    "VerifiedQualityArtifact",
    "run_quality_gate",
    "verify_quality_artifact",
]
