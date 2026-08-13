"""One-shot U6 retained-chain producer, private probe, and exact cleanup."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import stat
import sys
import traceback
import uuid
from decimal import Decimal, localcontext
from pathlib import Path, PurePosixPath
from typing import Any

from tests.support.m3_formal_public_chain.session import (
    _owned_cleanup,
    public_formal_chain_session,
)

_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_SCHEMA = "m3-g8c-c1-u6-retained-locator-v1"


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _exclusive_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(_canonical_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def _lstat_identity(path: Path) -> tuple[int, int, str]:
    status = os.lstat(path)
    if stat.S_ISLNK(status.st_mode) or (
        getattr(status, "st_file_attributes", 0) & _REPARSE
    ):
        raise RuntimeError("retained entity is a link/reparse point")
    if stat.S_ISDIR(status.st_mode):
        kind = "dir"
    elif stat.S_ISREG(status.st_mode):
        kind = "file"
    else:
        raise RuntimeError("retained entity is not a regular file/directory")
    return status.st_dev, status.st_ino, kind


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(root: Path) -> tuple[str, int]:
    root_dev, root_ino, root_kind = _lstat_identity(root)
    digest = hashlib.sha256()
    count = 0
    if root_kind == "file":
        payload = [".", "file", root.stat().st_size, _file_sha256(root)]
        digest.update(_canonical_bytes(payload))
        return digest.hexdigest(), 1
    digest.update(_canonical_bytes([".", "dir", root_dev, root_ino]))
    stack = [root]
    while stack:
        parent = stack.pop()
        entries = sorted(os.scandir(parent), key=lambda item: item.name)
        child_dirs: list[Path] = []
        for entry in entries:
            path = Path(entry.path)
            status = os.lstat(path)
            if stat.S_ISLNK(status.st_mode) or (
                getattr(status, "st_file_attributes", 0) & _REPARSE
            ):
                raise RuntimeError("retained tree contains link/reparse point")
            relative = path.relative_to(root).as_posix()
            if stat.S_ISDIR(status.st_mode):
                digest.update(_canonical_bytes([relative, "dir"]))
                child_dirs.append(path)
            elif stat.S_ISREG(status.st_mode):
                digest.update(
                    _canonical_bytes(
                        [relative, "file", status.st_size, _file_sha256(path)]
                    )
                )
            else:
                raise RuntimeError("retained tree contains special entity")
            count += 1
        stack.extend(reversed(child_dirs))
    return digest.hexdigest(), count


def _load_locator(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if type(value) is not dict or value.get("schema") != _SCHEMA:
        raise RuntimeError("invalid retained locator")
    return value


def produce(locator_path: Path) -> int:
    cleanup_token = uuid.uuid4().hex
    with public_formal_chain_session(horizon=5, diagnostic_retain=True) as locator:
        identities = []
        for path, device, inode, kind in locator.owned_identities:
            current = _lstat_identity(path)
            if current != (device, inode, kind):
                raise RuntimeError("owned identity drift before retention")
            tree_sha256, entry_count = _tree_digest(path)
            identities.append(
                {
                    "path": str(path),
                    "device": device,
                    "inode": inode,
                    "kind": kind,
                    "tree_sha256": tree_sha256,
                    "entry_count": entry_count,
                }
            )
        payload = {
            "schema": _SCHEMA,
            "created_at": dt.datetime.now(dt.UTC).isoformat(),
            "cleanup_token": cleanup_token,
            "project_root": str(locator.project_root),
            "config_relative": locator.config_relative.as_posix(),
            "snapshot_id": locator.snapshot_id,
            "fold": locator.fold,
            "horizon": locator.horizon,
            "g1_release_id": locator.g1_release_id,
            "stage_root": str(locator.stage_root),
            "work_key": locator.work_key,
            "session_id": locator.session_id,
            "code_version": locator.code_version,
            "dependency_fingerprint_sha256": locator.dependency_fingerprint_sha256,
            "provider_runtime_fingerprint_sha256": locator.provider_runtime_fingerprint_sha256,
            "owned": identities,
            "timings": {
                "stages_seconds": locator.timings.stages_seconds,
                "total_seconds": locator.timings.total_seconds,
                "file_counts": locator.timings.file_counts,
            },
        }
        _exclusive_json(locator_path, payload)
    print(f"U6_RETAINED locator={locator_path}", flush=True)
    return 0


def _shape(value: Any) -> dict[str, Any]:
    return {
        "scheduled_rows": value.plan.scheduled_targets.height,
        "execution_sessions": len(value.plan.manifest.window.execution_dates),
        "target_rows": value.target.targets.height,
    }


def probe(locator_path: Path, evidence_path: Path) -> int:
    from quant.backtest.a_share_execution import load_verified_a_share_market_facts
    from quant.backtest.a_share_reporting import _formal_config_values
    from quant.backtest.a_share_simulator import (
        _FORMAL_DECIMAL_CONTEXT,
        AShareSimulationError,
        AShareSimulationFreshVerificationContext,
        _simulate_formal_a_share_scenario,
    )
    from quant.research.m3.config import load_m3_config
    from quant.research.m3.formal_cli_resolve import resolve_formal_backtest_cli_inputs

    locator = _load_locator(locator_path)
    project_root = Path(locator["project_root"])
    relative = PurePosixPath(locator["config_relative"])
    config = load_m3_config(project_root.joinpath(*relative.parts))
    resolution = resolve_formal_backtest_cli_inputs(
        project_root=project_root,
        config=config,
        config_relative=relative,
        snapshot_id=locator["snapshot_id"],
        fold=locator["fold"],
        horizon=locator["horizon"],
    )
    facts_context = resolution.fresh_context.facts_fresh_context
    facts = load_verified_a_share_market_facts(
        release=resolution.release,
        plan=resolution.plan,
        fresh_context=facts_context,
        artifact_roots=resolution.artifact_roots,
    )
    periods, initial_cash, _ = _formal_config_values(config, resolution.plan)
    simulation_context = AShareSimulationFreshVerificationContext(
        release=resolution.release,
        facts_fresh_context=facts_context,
    )
    execution_exceptions: list[dict[str, Any]] = []

    monitoring = sys.monitoring
    tool_id = monitoring.DEBUGGER_ID

    def observe_raise(code: Any, offset: int, exception: BaseException) -> None:
        if Path(code.co_filename).name == "a_share_execution.py":
            message = str(exception)
            execution_exceptions.append(
                {
                    "type": f"{type(exception).__module__}.{type(exception).__qualname__}",
                    "function": code.co_name,
                    "bytecode_offset": offset,
                    "message_class": "empty" if message == "" else "redacted-text",
                    "message_sha256": hashlib.sha256(message.encode()).hexdigest(),
                }
            )
            del execution_exceptions[:-64]
    monitoring.use_tool_id(tool_id, "m3-u9-exception-observer")
    monitoring.register_callback(tool_id, monitoring.events.RAISE, observe_raise)
    try:
        monitoring.set_events(tool_id, monitoring.events.RAISE)
        with localcontext(_FORMAL_DECIMAL_CONTEXT):
            _simulate_formal_a_share_scenario(
                target=resolution.target,
                plan=resolution.plan,
                facts=facts,
                cost_periods=periods,
                multiplier=Decimal("0.5"),
                initial_cash=initial_cash,
                fresh_context=simulation_context,
                artifact_roots=resolution.artifact_roots,
            )
    except Exception as exc:
        frames = [
            {
                "file": Path(frame.filename).name,
                "line": frame.lineno,
                "function": frame.name,
            }
            for frame in traceback.extract_tb(exc.__traceback__)
            if "quant" in Path(frame.filename).parts
        ]
        message = str(exc)
        evidence = {
            "schema": "m3-g8c-c1-u6-private-probe-v1",
            "observed_at": dt.datetime.now(dt.UTC).isoformat(),
            "cleanup_token": locator["cleanup_token"],
            "exception_type": f"{type(exc).__module__}.{type(exc).__qualname__}",
            "message_class": "empty" if message == "" else "redacted-text",
            "message_sha256": hashlib.sha256(message.encode()).hexdigest(),
            "frames": frames,
            "execution_exception_events": execution_exceptions,
            "shape": _shape(resolution),
            "facts_rows": {
                "instruments": facts.instruments.height,
                "calendar": facts.calendar.height,
                "bars": facts.bars.height,
                "limits": facts.limits.height,
                "suspensions": facts.suspensions.height,
                "ledger": facts.corporate_actions.height,
                "reconciliation": facts.corporate_action_reconciliation.height,
                "benchmark": facts.benchmark_bars.height,
            },
            "public_mapping": {
                "exception_type": f"{AShareSimulationError.__module__}.{AShareSimulationError.__qualname__}",
                "message": "M3_A_SHARE_SIMULATION_INVALID",
            },
        }
        _exclusive_json(evidence_path, evidence)
        print(
            f"U6_PRIVATE_EXCEPTION type={evidence['exception_type']} "
            f"frame={frames[-1] if frames else None}",
            flush=True,
        )
        raise
    finally:
        monitoring.set_events(tool_id, monitoring.events.NO_EVENTS)
        monitoring.register_callback(tool_id, monitoring.events.RAISE, None)
        monitoring.free_tool_id(tool_id)
    _exclusive_json(
        evidence_path,
        {
            "schema": "m3-g8c-c1-u6-private-probe-v1",
            "observed_at": dt.datetime.now(dt.UTC).isoformat(),
            "cleanup_token": locator["cleanup_token"],
            "result": "unexpected-success",
            "shape": _shape(resolution),
        },
    )
    print("U6_PRIVATE_SUCCESS", flush=True)
    return 0


def cleanup(locator_path: Path, receipt_path: Path) -> int:
    locator = _load_locator(locator_path)
    owned: dict[Path, tuple[int, int, str]] = {}
    for item in locator["owned"]:
        path = Path(item["path"])
        expected = (item["device"], item["inode"], item["kind"])
        if _lstat_identity(path) != expected:
            raise RuntimeError("cleanup identity drift")
        tree_sha256, entry_count = _tree_digest(path)
        if (
            tree_sha256 != item["tree_sha256"]
            or entry_count != item["entry_count"]
        ):
            raise RuntimeError("cleanup tree drift")
        owned[path] = expected
    report = _owned_cleanup(owned)
    residual = [str(path) for path in owned if path.exists()]
    if residual or any(not line.startswith("removed:") for line in report):
        raise RuntimeError("cleanup did not remove exact owned roots")
    _exclusive_json(
        receipt_path,
        {
            "schema": "m3-g8c-c1-u6-cleanup-receipt-v1",
            "cleaned_at": dt.datetime.now(dt.UTC).isoformat(),
            "cleanup_token": locator["cleanup_token"],
            "removed": report,
            "residual": residual,
        },
    )
    print(f"U6_CLEANUP_COMPLETE receipt={receipt_path}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    producer = subparsers.add_parser("produce")
    producer.add_argument("--locator", type=Path, required=True)
    private = subparsers.add_parser("probe")
    private.add_argument("--locator", type=Path, required=True)
    private.add_argument("--evidence", type=Path, required=True)
    cleaner = subparsers.add_parser("cleanup")
    cleaner.add_argument("--locator", type=Path, required=True)
    cleaner.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "produce":
            return produce(args.locator)
        if args.command == "probe":
            return probe(args.locator, args.evidence)
        return cleanup(args.locator, args.receipt)
    except Exception as exc:  # noqa: BLE001 - diagnostic CLI redacts all failures
        print(f"U6_DIAGNOSTIC_FAILED type={type(exc).__module__}.{type(exc).__qualname__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
