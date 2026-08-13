"""Thin M3 CLI for verified continuation execution."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Never, TypeAlias

import polars as pl

from quant.data.m3_mappers import compute_benchmark_source_snapshot_id
from quant.data.m3_release import (
    G1Release,
    VerifiedG1Release,
    verify_g1_release,
)
from quant.research.m3.config import LoadedM3Config, M3ConfigError, load_m3_config
from quant.research.m3.contracts import (
    ExperimentIdentitySpec,
    ProviderValidationSpec,
    SnapshotBuildSpec,
    VerifiedProviderArtifact,
    VerifiedProviderValidationArtifact,
    VerifiedSnapshotArtifact,
)
from quant.research.m3.experiment_identity import (
    build_experiment_identity_manifest,
    make_experiment_identity_handler,
    make_experiment_identity_run_plan,
    verify_experiment_identity_output,
)
from quant.research.m3.labels import verify_experiment_identity
from quant.research.m3.orchestration import (
    M3StageRunnerError,
    SnapshotStageResult,
    StageBuildReport,
    StageContext,
    StageRunner,
    make_snapshot_run_plan,
)
from quant.research.m3.readiness import ReadinessIssue, audit_m3_readiness
from quant.research.m3.provider import verify_provider_artifact
from quant.research.m3.provider_validation import (
    read_provider_validation_summary,
    verify_provider_validation_artifact,
)
from quant.research.m3.runtime_identity import (
    M3SourceDigestV1,
    compute_m3_runtime_identity,
)
from quant.research.m3.run_state import ArtifactDigest, compute_snapshot_request_key
from quant.research.m3.snapshot import (
    build_snapshot_artifact,
    build_snapshot_request_record,
    read_snapshot_manifest,
    read_snapshot_request_record,
    verify_snapshot_build_result,
    verify_snapshot_artifact,
)

_Execute = Callable[[argparse.Namespace], Mapping[str, Any]]
_PUBLIC_COMMANDS = (
    "readiness",
    "snapshot",
    "train",
    "evaluate",
    "backtest",
    "run-all",
    "verify-reproducibility",
    "acceptance-audit",
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_FOLD = re.compile(r"^fold_[0-9]{3}$")
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_DRIVE_ABS = re.compile(r"^[A-Za-z]:/")
_FORMAL_CLI_EXIT_BY_CODE = {
    "FORMAL_CLI_INPUT_INVALID": 2,
    "FORMAL_CLI_CONFIG_INVALID": 2,
    "FORMAL_CLI_RUNTIME_IDENTITY_INVALID": 2,
    "FORMAL_CLI_G1_INVALID": 3,
    "FORMAL_CLI_UPSTREAM_INVALID": 3,
    "FORMAL_CLI_DEPENDENCY_UNAVAILABLE": 4,
    "FORMAL_CLI_ARTIFACT_MISSING": 5,
    "FORMAL_CLI_CLOSURE_DRIFT": 5,
}
_STAGE_RUNNER_CODES = frozenset(
    {
        "STAGE_INPUT_INVALID",
        "STAGE_LOCK_FAILED",
        "STAGE_BUILD_FAILED",
        "STAGE_OUTPUT_INVALID",
        "STAGE_PUBLISH_FAILED",
        "STAGE_RECOVERY_CONFLICT",
        "STAGE_ALREADY_COMPLETE",
    }
)
_SECRET = re.compile(
    r"(?:token|password|secret|api[_-]?key|bearer)", re.IGNORECASE
)
_ABSOLUTE_PATH = re.compile(
    r"(?:^|[\s='\"])(?:[A-Za-z]:[\\/]|/{1,2}[^/\s]|\\\\[^\\\s]+[\\/])"
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class CommandFailure:
    """One sanitized CLI failure with a process-exit classification."""

    scope: str
    node_id: str
    error_code: str
    exit_code: int

    def __post_init__(self) -> None:
        if (
            not _safe_label(self.scope)
            or not _safe_label(self.node_id)
            or _ERROR_CODE.fullmatch(self.error_code) is None
            or type(self.exit_code) is not int
            or not 2 <= self.exit_code <= 8
        ):
            raise ValueError("invalid command failure")


@dataclass(frozen=True, slots=True)
class CommandSummary:
    """Canonical aggregate returned by an injected public-command dispatcher."""

    command: str
    failures: tuple[CommandFailure, ...] = ()
    details: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.command not in _PUBLIC_COMMANDS:
            raise ValueError("invalid command summary")
        if type(self.failures) is not tuple or any(
            type(item) is not CommandFailure for item in self.failures
        ):
            raise ValueError("invalid command summary")
        _safe_json(self.details or {})

    @property
    def exit_code(self) -> int:
        return min((item.exit_code for item in self.failures), default=0)

    def payload(self) -> dict[str, JsonValue]:
        failures = sorted(
            self.failures,
            key=lambda item: (item.scope, item.node_id, item.error_code),
        )
        payload: dict[str, JsonValue] = {
            "command": self.command,
            "failures": [
                {
                    "error_code": item.error_code,
                    "exit_code": item.exit_code,
                    "node_id": item.node_id,
                    "scope": item.scope,
                }
                for item in failures
            ],
            "ok": not failures,
        }
        for key, value in sorted((self.details or {}).items()):
            if key in payload:
                raise ValueError("reserved command summary detail")
            payload[key] = _safe_json(value)
        return payload


class M3CliUsageError(ValueError):
    code = "M3_CLI_USAGE_INVALID"


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        del message
        raise M3CliUsageError("M3_CLI_USAGE_INVALID")


def _safe_label(value: object) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= 128
        and not _SECRET.search(value)
        and not value.startswith(("/", "\\\\"))
        and _ABSOLUTE_PATH.search(value) is None
        and all(character.isalnum() or character in "_.:-" for character in value)
    )


def _safe_json(value: Any) -> JsonValue:
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("unsafe command summary")
        return value
    if type(value) is str:
        if (
            _SECRET.search(value)
            or _ABSOLUTE_PATH.search(value) is not None
        ):
            raise ValueError("unsafe command summary")
        return value
    if isinstance(value, Mapping):
        output: dict[str, JsonValue] = {}
        for key, item in value.items():
            if type(key) is not str or not _safe_label(key):
                raise ValueError("unsafe command summary")
            output[key] = _safe_json(item)
        return output
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_safe_json(item) for item in value]
    raise ValueError("unsafe command summary")


def _identity(value: str) -> str:
    if _HEX64.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("invalid identity")
    return value


def _fold(value: str) -> str:
    if _FOLD.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("invalid fold")
    return value


def _add_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, required=True)


def _add_snapshot_work(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--snapshot-id", type=_identity, required=True)
    parser.add_argument("--fold", type=_fold, required=True)
    parser.add_argument("--horizon", type=int, choices=(5, 10), required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="python -m quant.research.run_m3")
    subparsers = parser.add_subparsers(
        dest="command", required=True, parser_class=_ArgumentParser
    )
    experiment = subparsers.add_parser("experiment-identity")
    for name in (
        "project-root",
        "config",
        "g1-release-root",
        "snapshot-artifact-root",
        "snapshot-root",
        "snapshot-request-path",
        "snapshot-receipt-path",
        "provider-artifact-root",
        "provider-root",
        "provider-receipt-path",
        "provider-validation-artifact-root",
        "provider-validation-root",
        "provider-validation-receipt-path",
        "external-qlib-root",
        "stage-root",
    ):
        experiment.add_argument(f"--{name}", type=Path, required=True)
    experiment.add_argument("--provider-validation-code-version", required=True)
    experiment.add_argument("--no-resume", action="store_true")

    readiness = subparsers.add_parser("readiness")
    _add_config(readiness)
    readiness.add_argument("--g1-release-id", type=_identity, required=True)
    readiness.set_defaults(stop_stage="readiness")

    snapshot = subparsers.add_parser("snapshot")
    _add_config(snapshot)
    snapshot.add_argument("--g1-release-id", type=_identity, required=True)
    snapshot.set_defaults(stop_stage="snapshot")

    for name, stop_stage in (
        ("train", "train"),
        ("evaluate", "evaluation"),
        ("verify-reproducibility", "comparison"),
    ):
        command = subparsers.add_parser(name)
        _add_config(command)
        _add_snapshot_work(command)
        command.set_defaults(stop_stage=stop_stage)

    backtest = subparsers.add_parser("backtest")
    backtest.add_argument("--config", type=str, required=True)
    _add_snapshot_work(backtest)
    backtest.add_argument("--no-resume", action="store_true")
    backtest.set_defaults(stop_stage="backtest")

    run_all = subparsers.add_parser("run-all")
    _add_config(run_all)
    source = run_all.add_mutually_exclusive_group(required=True)
    source.add_argument("--g1-release-id", type=_identity)
    source.add_argument("--snapshot-id", type=_identity)
    run_all.set_defaults(stop_stage="tracking")

    acceptance = subparsers.add_parser("acceptance-audit")
    _add_config(acceptance)
    acceptance.add_argument("--snapshot-id", type=_identity, required=True)
    acceptance.set_defaults(stop_stage="acceptance")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    execute: _Execute | None = None,
    dispatcher: Callable[[argparse.Namespace], CommandSummary | Mapping[str, Any]]
    | None = None,
) -> int:
    """Parse once, execute an injected command, and emit exactly one JSON value."""
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = build_parser().parse_args(raw_argv)
    except M3CliUsageError:
        command = raw_argv[0] if raw_argv and raw_argv[0] in _PUBLIC_COMMANDS else None
        if command is None:
            payload: Mapping[str, Any] = {
                "ok": False,
                "error_code": "M3_CLI_USAGE_INVALID",
            }
        else:
            payload = CommandSummary(
                command=command,
                failures=(
                    CommandFailure(
                        scope="command",
                        node_id=command,
                        error_code="M3_CLI_USAGE_INVALID",
                        exit_code=2,
                    ),
                ),
            ).payload()
        exit_code = 2
    else:
        if args.command == "experiment-identity":
            payload, exit_code = _run_legacy(args, execute)
        else:
            payload, exit_code = _run_public(
                args, _dispatch_public if dispatcher is None else dispatcher
            )
    sys.stdout.write(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    )
    return exit_code


def _run_legacy(
    args: argparse.Namespace, execute: _Execute | None
) -> tuple[Mapping[str, Any], int]:
    try:
        result = (execute or _execute_experiment_identity)(args)
        return {"ok": True, **dict(result)}, 0
    except Exception as exc:
        code = getattr(exc, "code", "M3_COMMAND_FAILED")
        safe_code = code if type(code) is str and _ERROR_CODE.fullmatch(code) else "M3_COMMAND_FAILED"
        return {"ok": False, "error_code": safe_code}, 5


def _run_public(
    args: argparse.Namespace,
    dispatcher: Callable[[argparse.Namespace], CommandSummary | Mapping[str, Any]]
    | None,
) -> tuple[Mapping[str, Any], int]:
    command = str(args.command)
    try:
        if dispatcher is None:
            summary = CommandSummary(
                command=command,
                failures=(
                    CommandFailure(
                        scope="command",
                        node_id=command,
                        error_code="M3_COMMAND_HANDLER_UNAVAILABLE",
                        exit_code=5,
                    ),
                ),
            )
        else:
            # Dispatcher stdout is untrusted and discarded. Structured,
            # sanitized failures belong in the command summary.
            with redirect_stdout(io.StringIO()):
                dispatched = dispatcher(args)
            if type(dispatched) is CommandSummary:
                summary = dispatched
                if summary.command != command:
                    raise ValueError("command summary mismatch")
            elif isinstance(dispatched, Mapping):
                summary = CommandSummary(command=command, details=dispatched)
            else:
                raise ValueError("invalid command dispatcher result")
        return summary.payload(), summary.exit_code
    except Exception:
        summary = CommandSummary(
            command=command,
            failures=(
                CommandFailure(
                    scope="command",
                    node_id=command,
                    error_code="M3_COMMAND_FAILED",
                    exit_code=5,
                ),
            ),
        )
        return summary.payload(), 5


def _lexical_backtest_config_relative(
    *, project_root: Path, config_arg: str
) -> PurePosixPath:
    """Convert caller --config to an exact project-relative PurePosixPath.

    Only lexical conversion is allowed. The caller original path is never
    replaced by ``Path.resolve()`` before C0 anchors it.
    """
    if type(config_arg) is not str or not config_arg or "\\" in config_arg:
        raise ValueError("invalid config")
    if config_arg.startswith("//") or config_arg.startswith("\\\\"):
        raise ValueError("invalid config")
    if len(config_arg) >= 2 and config_arg[1] == ":" and (
        len(config_arg) == 2 or config_arg[2] != "/"
    ):
        raise ValueError("invalid config")
    if config_arg.startswith("/") or _DRIVE_ABS.match(config_arg) is not None:
        root_text = project_root.as_posix().rstrip("/")
        prefix = root_text + "/"
        if config_arg == root_text or not config_arg.startswith(prefix):
            raise ValueError("invalid config")
        remainder = config_arg[len(prefix) :]
        if any(part in {".", ".."} for part in remainder.split("/")):
            raise ValueError("invalid config")
        relative = PurePosixPath(remainder)
    else:
        if any(part in {".", ".."} for part in config_arg.split("/")):
            raise ValueError("invalid config")
        relative = PurePosixPath(config_arg)
    text = relative.as_posix()
    parts = relative.parts
    if (
        not text
        or text.startswith("/")
        or "\\" in text
        or relative.is_absolute()
        or relative.drive
        or not parts
        or parts[0] != "configs"
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("invalid config")
    return relative


def _load_backtest_config(
    args: argparse.Namespace,
) -> tuple[Path, PurePosixPath, LoadedM3Config] | None:
    try:
        project_root = Path.cwd().resolve(strict=True)
        config_relative = _lexical_backtest_config_relative(
            project_root=project_root, config_arg=str(args.config)
        )
        config = load_m3_config(project_root.joinpath(*config_relative.parts))
    except Exception:
        return None
    return project_root, config_relative, config


def _map_formal_cli_resolve_error(exc: BaseException, error_type: type) -> tuple[str, int]:
    if type(exc) is not error_type:
        return ("M3_COMMAND_FAILED", 5)
    code = getattr(exc, "code", None)
    exit_code = getattr(exc, "exit_code", None)
    if type(code) is not str or type(exit_code) is not int:
        return ("M3_COMMAND_FAILED", 5)
    expected = _FORMAL_CLI_EXIT_BY_CODE.get(code)
    if expected is None or exit_code != expected:
        return ("M3_COMMAND_FAILED", 5)
    return (code, exit_code)


def _map_stage_runner_error(exc: BaseException) -> tuple[str, int]:
    if type(exc) is not M3StageRunnerError:
        return ("M3_COMMAND_FAILED", 5)
    code = getattr(exc, "code", None)
    if type(code) is not str or code not in _STAGE_RUNNER_CODES:
        return ("M3_COMMAND_FAILED", 5)
    return (code, 5)


def _formal_backtest_reused(result: object, result_type: type) -> bool:
    if type(result) is not result_type:
        raise ValueError("invalid stage result")
    reused = getattr(result, "reused", None)
    if type(reused) is not bool:
        raise ValueError("invalid stage result")
    return reused


def resolve_formal_backtest_cli_inputs(**kwargs: Any) -> Any:
    """Lazy public-resolver wrapper so cold import stays free of C0/G8 modules."""
    from quant.research.m3.formal_cli_resolve import (
        resolve_formal_backtest_cli_inputs as resolve,
    )

    return resolve(**kwargs)


def run_formal_backtest_stage(**kwargs: Any) -> Any:
    """Lazy formal-stage wrapper so cold import stays free of G8 modules."""
    from quant.research.m3.backtest_stage import run_formal_backtest_stage as run_stage

    return run_stage(**kwargs)


def _dispatch_formal_backtest(args: argparse.Namespace) -> CommandSummary:
    command = "backtest"
    loaded = _load_backtest_config(args)
    if loaded is None:
        return _failure_summary(
            command, error_code="M3_CONFIG_INVALID", exit_code=2
        )
    project_root, config_relative, config = loaded

    from quant.research.m3.formal_cli_resolve import FormalCliResolveError

    resolution = None
    resolve_mapped: tuple[str, int] | None = None
    try:
        resolution = resolve_formal_backtest_cli_inputs(
            project_root=project_root,
            config=config,
            config_relative=config_relative,
            snapshot_id=args.snapshot_id,
            fold=args.fold,
            horizon=args.horizon,
        )
    except Exception as exc:
        resolve_mapped = _map_formal_cli_resolve_error(exc, FormalCliResolveError)
    if resolve_mapped is not None or resolution is None:
        mapped = resolve_mapped or ("M3_COMMAND_FAILED", 5)
        return _failure_summary(
            command, error_code=mapped[0], exit_code=mapped[1]
        )

    from quant.research.m3.backtest_stage import FormalBacktestStageResult

    stage_result = None
    stage_mapped: tuple[str, int] | None = None
    reused = None
    work_key = None
    try:
        stage_result = run_formal_backtest_stage(
            stage_root=resolution.stage_root,
            target=resolution.target,
            plan=resolution.plan,
            release=resolution.release,
            experiment=resolution.experiment,
            config=resolution.config,
            fresh_context=resolution.fresh_context,
            artifact_roots=resolution.artifact_roots,
            resume=not args.no_resume,
        )
        reused = _formal_backtest_reused(stage_result, FormalBacktestStageResult)
        work_key = resolution.work_key
        if type(work_key) is not str:
            raise ValueError("invalid resolution")
    except Exception as exc:
        if stage_result is None:
            stage_mapped = _map_stage_runner_error(exc)
        else:
            stage_mapped = ("M3_COMMAND_FAILED", 5)
    if stage_mapped is not None:
        return _failure_summary(
            command, error_code=stage_mapped[0], exit_code=stage_mapped[1]
        )
    if type(reused) is not bool or type(work_key) is not str:
        return _failure_summary(
            command, error_code="M3_COMMAND_FAILED", exit_code=5
        )
    return CommandSummary(
        command=command,
        details={
            "fold": args.fold,
            "horizon": args.horizon,
            "reused": reused,
            "snapshot_id": args.snapshot_id,
            "stop_stage": "backtest",
            "work_key": work_key,
        },
    )


def _dispatch_public(args: argparse.Namespace) -> CommandSummary:
    command = str(args.command)
    if command == "backtest":
        return _dispatch_formal_backtest(args)
    if command not in {"readiness", "snapshot"}:
        return _failure_summary(
            command, error_code="M3_COMMAND_HANDLER_UNAVAILABLE", exit_code=5
        )
    try:
        project_root = Path.cwd().resolve(strict=True)
        config_path = args.config.resolve(strict=True)
        config_relative = PurePosixPath(
            config_path.relative_to(project_root).as_posix()
        )
        config = load_m3_config(config_path)
    except (M3ConfigError, OSError, TypeError, ValueError):
        return _failure_summary(
            command, error_code="M3_CONFIG_INVALID", exit_code=2
        )

    try:
        release = _verify_requested_release(
            project_root=project_root, release_id=args.g1_release_id
        )
    except Exception:
        return _failure_summary(
            command, error_code="G1_RELEASE_INVALID", exit_code=3
        )

    try:
        issues = _audit_verified_release(release=release, config=config)
    except Exception:
        return _failure_summary(
            command, error_code="M3_READINESS_FAILED", exit_code=3
        )
    errors = tuple(issue for issue in issues if issue.severity == "ERROR")
    if errors:
        return CommandSummary(
            command=command,
            failures=tuple(
                CommandFailure(
                    scope="snapshot",
                    node_id="readiness",
                    error_code=issue.code,
                    exit_code=(
                        4
                        if issue.code in {"QLIB_NOT_IMPORTABLE", "PYTHON_UNSUPPORTED"}
                        else 3
                    ),
                )
                for issue in errors
            ),
            details={"issue_count": len(issues)},
        )
    if command == "readiness":
        return CommandSummary(
            command=command,
            details={
                "g1_release_id": release.release.release_id,
                "issue_count": len(issues),
                "stop_stage": "readiness",
            },
        )

    try:
        if config.raw_config_sha256 is None:
            raise ValueError("missing frozen config digest")
        runtime = compute_m3_runtime_identity(
            project_root=project_root,
            config_paths=(config_relative,),
            frozen_config_digests=(
                M3SourceDigestV1(
                    config_relative.as_posix(), config.raw_config_sha256
                ),
            ),
        )
    except Exception:
        return _failure_summary(
            command, error_code="M3_RUNTIME_IDENTITY_INVALID", exit_code=2
        )
    try:
        result = _run_snapshot_stage(
            project_root=project_root,
            release=release,
            config=config,
            code_version=runtime.code_version,
        )
    except M3StageRunnerError as exc:
        return _failure_summary(command, error_code=exc.code, exit_code=5)
    except Exception:
        return _failure_summary(
            command, error_code="M3_SNAPSHOT_FAILED", exit_code=5
        )
    return CommandSummary(
        command=command,
        details={
            "g1_release_id": release.release.release_id,
            "reused": result.reused,
            "snapshot_id": result.build.manifest.snapshot_id,
            "stop_stage": "snapshot",
        },
    )


def _failure_summary(
    command: str, *, error_code: str, exit_code: int
) -> CommandSummary:
    return CommandSummary(
        command=command,
        failures=(
            CommandFailure(
                scope="command",
                node_id=command,
                error_code=error_code,
                exit_code=exit_code,
            ),
        ),
    )


def _verify_requested_release(
    *, project_root: Path, release_id: str
) -> VerifiedG1Release:
    release_root = project_root / "data" / "clean" / "m3_g1" / "releases" / release_id
    return verify_g1_release(
        release=G1Release(
            release_id=release_id,
            root=release_root,
            manifest_path=release_root / "manifest.json",
            quality_path=release_root / "quality.json",
        )
    )


def _audit_verified_release(
    *, release: VerifiedG1Release, config: LoadedM3Config
) -> tuple[ReadinessIssue, ...]:
    paths = dict(release.artifact_paths)
    benchmark_receipts = tuple(
        (
            item.endpoint,
            item.request_id,
            item.stable_response_sha256,
        )
        for item in release.manifest.input_receipts
        if item.source == "tushare"
        and item.endpoint in {"fund_daily", "fund_adj", "fund_div"}
    )
    expected_snapshot = compute_benchmark_source_snapshot_id(
        identities=benchmark_receipts
    )
    issues = audit_m3_readiness(
        bars=pl.read_parquet(paths["bar_1d.parquet"]),
        instruments=pl.read_parquet(paths["instrument.parquet"]),
        membership=pl.read_parquet(paths["universe_membership.parquet"]),
        calendars=pl.read_parquet(paths["trade_calendar.parquet"]),
        benchmark_bars=pl.read_parquet(paths["benchmark_bar_1d.parquet"]),
        config=config.document,
        expected_benchmark_source_snapshot_id=expected_snapshot,
    )
    return tuple(issues)


def _run_snapshot_stage(
    *, project_root: Path, release: VerifiedG1Release,
    config: LoadedM3Config, code_version: str,
) -> SnapshotStageResult:
    spec = SnapshotBuildSpec(
        snapshot_request_key=compute_snapshot_request_key(
            g1_release_id=release.release.release_id,
            g1_release_manifest_sha256=release.manifest_sha256,
            snapshot_config_sha256=config.snapshot_config_sha256,
            code_version=code_version,
        ),
        config_version=config.config_version,
        snapshot_config_sha256=config.snapshot_config_sha256,
        code_version=code_version,
        history_start=release.manifest.history_start,
        history_end=release.manifest.history_end,
        staging_schema_version="m3-qlib-staging-v1",
        adjustment_formula_version="qlib_yahoo_like_v1",
    )
    stage_root = _prepare_stage_root(project_root=project_root, config=config)
    roots = {"G1_RELEASE": release.release.root, "G8": stage_root}
    paths = dict(release.artifact_paths)
    input_paths = (
        release.release.manifest_path,
        paths["bar_1d.parquet"],
        paths["universe_membership.parquet"],
        paths["trade_calendar.parquet"],
    )
    plan = make_snapshot_run_plan(
        snapshot_request_key=spec.snapshot_request_key,
        inputs=tuple(
            _digest_release_file(path=path, release_root=release.release.root)
            for path in input_paths
        ),
    )
    runner = StageRunner(stage_root=stage_root, artifact_roots=roots, config=config)

    def handler(context: StageContext) -> StageBuildReport:
        build_snapshot_artifact(
            release=release,
            config=config,
            spec=spec,
            output_root=context.temp_output_root,
        )
        return StageBuildReport(
            tuple(
                sorted(
                    path.relative_to(context.temp_output_root).as_posix()
                    for path in context.temp_output_root.rglob("*")
                    if path.is_file()
                )
            )
        )

    def closure(root: Path) -> tuple[Any, Any]:
        build = verify_snapshot_build_result(
            snapshot_root=root, release=release, config=config, spec=spec
        )
        request = build_snapshot_request_record(
            release=release, config=config, spec=spec, result=build
        )
        return build, request

    result = runner.run_snapshot(
        node=plan.nodes[0], handler=handler, closure_verifier=closure
    )
    verify_snapshot_artifact(
        snapshot_root=result.snapshot_root,
        snapshot_request_path=result.request_record_path,
        snapshot_receipt_path=result.receipt_path,
        release=release,
        config=config,
        spec=spec,
        artifact_roots=roots,
    )
    return result


def _prepare_stage_root(*, project_root: Path, config: LoadedM3Config) -> Path:
    logical = config.section("tracking")["artifact_root"]
    if type(logical) is not str:
        raise ValueError("invalid artifact root")
    candidate = project_root.joinpath(*PurePosixPath(logical).parts)
    ancestor = candidate
    while not ancestor.exists():
        ancestor = ancestor.parent
    if not ancestor.resolve(strict=True).is_relative_to(project_root):
        raise ValueError("artifact root outside project")
    candidate.mkdir(parents=True, exist_ok=True)
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(project_root):
        raise ValueError("artifact root outside project")
    return resolved


def _digest_release_file(*, path: Path, release_root: Path) -> ArtifactDigest:
    raw = path.read_bytes()
    return ArtifactDigest(
        root_alias="G1_RELEASE",
        relative_path=path.relative_to(release_root).as_posix(),
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _execute_experiment_identity(args: argparse.Namespace) -> Mapping[str, Any]:
    project_root = args.project_root.resolve(strict=True)
    config_path = args.config.resolve(strict=True)
    try:
        config_relative = PurePosixPath(
            config_path.relative_to(project_root).as_posix()
        )
    except ValueError:
        raise ValueError("config outside project root") from None
    config = load_m3_config(config_path)
    runtime = compute_m3_runtime_identity(
        project_root=project_root,
        config_paths=(config_relative,),
    )
    roots = _artifact_roots(args)
    snapshot, provider, validation = _load_verified_inputs(
        args=args,
        config=config,
        artifact_roots=roots,
    )
    spec = ExperimentIdentitySpec(
        scientific_config_sha256=config.scientific_config_sha256,
        dependency_fingerprint_sha256=runtime.dependency_fingerprint_sha256,
        code_version=runtime.code_version,
    )
    plan = make_experiment_identity_run_plan(
        snapshot=snapshot,
        provider=provider,
        provider_validation=validation,
        config=config,
        spec=spec,
        artifact_roots=roots,
    )
    node = plan.nodes[0]
    expected = build_experiment_identity_manifest(
        snapshot=snapshot,
        provider=provider,
        config=config,
        spec=spec,
    )
    runner = StageRunner(
        stage_root=args.stage_root,
        artifact_roots=roots,
        config=config,
    )
    result = runner.run_experiment_identity(
        node=node,
        handler=make_experiment_identity_handler(
            snapshot=snapshot,
            provider=provider,
            spec=spec,
        ),
        output_verifier=lambda root: verify_experiment_identity_output(
            root=root, expected=expected
        ),
        final_verifier=lambda root, receipt: verify_experiment_identity(
            experiment_root=root,
            experiment_receipt_path=receipt,
            snapshot=snapshot,
            provider=provider,
            config=config,
            spec=spec,
            artifact_roots=roots,
        ),
        resume=not args.no_resume,
    )
    return {
        "command": "experiment-identity",
        "experiment_key": result.verified.manifest.experiment_key,
        "reused": result.reused,
    }


def _artifact_roots(args: argparse.Namespace) -> dict[str, Path]:
    roots = {
        "G1_RELEASE": args.g1_release_root,
        "G2A": args.snapshot_artifact_root,
        "G2B": args.provider_artifact_root,
        "G2C": args.provider_validation_artifact_root,
        "EXTERNAL_QLIB": args.external_qlib_root,
        "G8": args.stage_root,
    }
    return {name: path.resolve(strict=True) for name, path in roots.items()}


def _load_verified_inputs(
    *,
    args: argparse.Namespace,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
) -> tuple[
    VerifiedSnapshotArtifact,
    VerifiedProviderArtifact,
    VerifiedProviderValidationArtifact,
]:
    request = read_snapshot_request_record(args.snapshot_request_path)
    manifest = read_snapshot_manifest(args.snapshot_root / "manifest.json")
    release_root = args.g1_release_root
    release = verify_g1_release(
        release=G1Release(
            release_id=request.g1_release_id,
            root=release_root,
            manifest_path=release_root / "manifest.json",
            quality_path=release_root / "quality.json",
        )
    )
    snapshot_spec = SnapshotBuildSpec(
        snapshot_request_key=request.snapshot_request_key,
        config_version=manifest.config_version,
        snapshot_config_sha256=manifest.snapshot_config_sha256,
        code_version=request.code_version,
        history_start=manifest.history_start,
        history_end=manifest.history_end,
        staging_schema_version=manifest.staging_schema_version,
        adjustment_formula_version=manifest.adjustment_formula_version,
    )
    snapshot = verify_snapshot_artifact(
        snapshot_root=args.snapshot_root,
        snapshot_request_path=args.snapshot_request_path,
        snapshot_receipt_path=args.snapshot_receipt_path,
        release=release,
        config=config,
        spec=snapshot_spec,
        artifact_roots=artifact_roots,
    )
    provider = verify_provider_artifact(
        provider_root=args.provider_root,
        provider_receipt_path=args.provider_receipt_path,
        snapshot=snapshot,
        config=config,
        artifact_roots=artifact_roots,
    )
    summary = read_provider_validation_summary(
        args.provider_validation_root / "provider_validation.json"
    )
    validation_spec = ProviderValidationSpec(
        provider_validation_key=summary.provider_validation_key,
        provider_validation_config_sha256=(
            summary.provider_validation_config_sha256
        ),
        code_version=args.provider_validation_code_version,
        qlib_version="0.9.7",
        sampling_policy_version="provider_market_stratified_hash_first_last_v1",
        worker_protocol_version="m3-qlib-worker-v1",
    )
    validation = verify_provider_validation_artifact(
        validation_root=args.provider_validation_root,
        validation_receipt_path=args.provider_validation_receipt_path,
        snapshot=snapshot,
        provider=provider,
        config=config,
        spec=validation_spec,
        artifact_roots=artifact_roots,
    )
    return snapshot, provider, validation


if __name__ == "__main__":
    raise SystemExit(main())
