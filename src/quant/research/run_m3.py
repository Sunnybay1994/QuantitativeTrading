"""Thin M3 CLI for verified continuation execution."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Never

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


class M3CliUsageError(ValueError):
    code = "M3_CLI_USAGE_INVALID"


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        del message
        raise M3CliUsageError("M3_CLI_USAGE_INVALID")


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
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    execute: _Execute | None = None,
) -> int:
    """Parse once, execute an injected command, and emit exactly one JSON value."""
    try:
        args = build_parser().parse_args(argv)
        result = (execute or _execute_experiment_identity)(args)
        payload: Mapping[str, Any] = {"ok": True, **dict(result)}
        exit_code = 0
    except Exception as exc:
        code = getattr(exc, "code", "M3_COMMAND_FAILED")
        payload = {"ok": False, "error_code": str(code)}
        exit_code = 2 if isinstance(exc, M3CliUsageError) else 5
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
