"""Thin M3 CLI for verified continuation execution."""

from __future__ import annotations

import argparse
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

from quant.data.m3_release import G1Release, verify_g1_release
from quant.research.m3.config import LoadedM3Config, load_m3_config
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
from quant.research.m3.orchestration import StageRunner
from quant.research.m3.provider import verify_provider_artifact
from quant.research.m3.provider_validation import (
    read_provider_validation_summary,
    verify_provider_validation_artifact,
)
from quant.research.m3.runtime_identity import compute_m3_runtime_identity
from quant.research.m3.snapshot import (
    read_snapshot_manifest,
    read_snapshot_request_record,
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
        ("backtest", "backtest"),
        ("verify-reproducibility", "comparison"),
    ):
        command = subparsers.add_parser(name)
        _add_config(command)
        _add_snapshot_work(command)
        command.set_defaults(stop_stage=stop_stage)

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
            payload, exit_code = _run_public(args, dispatcher)
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
