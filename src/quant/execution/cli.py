"""Content-addressed, PAPER-only operator CLI for durable execution."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import NoReturn, cast

from quant.domain.canonical_wire import canonical_json_bytes, utc_datetime_text
from quant.domain.enums import ExecutionMode
from quant.execution.cli_ports import (
    CliDependencies,
    CliPortError,
    verify_broker_evidence,
    verify_paper_gateway,
    verify_planning_load,
    verify_target_load,
)
from quant.execution.config import trading_config_identity
from quant.execution.contracts import (
    build_cancel_command,
    build_cancel_command_identity,
    build_order_command_identity,
    build_order_plan_identity,
)
from quant.execution.reconcile import (
    RecoveryResult,
    build_broker_snapshot,
    reconcile,
    recover_local_state,
)
from quant.execution.service import ExecutionService, ExecutionServiceError
from quant.execution.store import ExecutionStore, OutboxDeliveryState
from quant.execution.wire import encode_order_aggregate
from quant.portfolio.order_planner import build_order_plan

_OUTPUT_SCHEMA = "m4-paper-cli-output-v1"
_CHALLENGE_SCHEMA = "m4-paper-cli-challenge-v1"
_HEX = frozenset("0123456789abcdef")
_CONFIRM_ACTIONS = frozenset({"approve", "paper-submit", "cancel"})
_COMMANDS = ("inspect", "plan", "approve", "paper-submit", "cancel", "reconcile")


class CliUsageError(ValueError):
    """Stable argparse failure."""


class _ConfirmationPrinted(Exception):
    """Internal control flow after emitting a canonical challenge."""


@dataclass(frozen=True, slots=True)
class _CliFailure(Exception):
    exit_code: int
    code: str


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise CliUsageError("CLI_USAGE_INVALID") from None

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        del status, message
        raise CliUsageError("CLI_USAGE_INVALID") from None


def _parser() -> _Parser:
    parser = _Parser(add_help=False, allow_abbrev=False)
    subs = parser.add_subparsers(dest="action", required=True)
    subs.add_parser("inspect", add_help=False, allow_abbrev=False)
    subs.add_parser("plan", add_help=False, allow_abbrev=False)
    for action in ("approve", "paper-submit"):
        child = subs.add_parser(action, add_help=False, allow_abbrev=False)
        child.add_argument("--confirm-sha256")
    cancel = subs.add_parser("cancel", add_help=False, allow_abbrev=False)
    cancel.add_argument("--command-id", required=True)
    cancel.add_argument("--confirm-sha256")
    subs.add_parser("reconcile", add_help=False, allow_abbrev=False)
    return parser


def main(argv: Sequence[str] | None = None, *, dependencies: CliDependencies) -> int:
    """Run exactly one PAPER operator action and return its stable exit code."""
    try:
        if type(dependencies) is not CliDependencies:
            raise _CliFailure(10, "CLI_DEPENDENCIES_INVALID")
        args = _parser().parse_args(None if argv is None else list(argv))
        action = cast(str, args.action)
        if action not in _COMMANDS:
            raise _CliFailure(2, "CLI_USAGE_INVALID")
        return _run(action, args, dependencies)
    except CliUsageError:
        _stderr("CLI_USAGE_INVALID")
        return 2
    except _ConfirmationPrinted:
        return 20
    except _CliFailure as failure:
        _stderr(failure.code)
        return failure.exit_code
    except Exception:
        _stderr("CLI_INTERNAL_FAILURE")
        return 70


def _run(action: str, args: argparse.Namespace, dependencies: CliDependencies) -> int:
    if action == "inspect":
        return _inspect(dependencies)
    if action == "plan":
        return _plan(dependencies)
    if action == "approve":
        return _approve(cast(str | None, args.confirm_sha256), dependencies)
    if action == "paper-submit":
        return _paper_submit(cast(str | None, args.confirm_sha256), dependencies)
    if action == "cancel":
        return _cancel(
            cast(str, args.command_id), cast(str | None, args.confirm_sha256), dependencies
        )
    if action == "reconcile":
        return _reconcile(dependencies)
    raise _CliFailure(2, "CLI_USAGE_INVALID")


def _inspect(dependencies: CliDependencies) -> int:
    local = _recover(_store(dependencies))
    _stdout(
        _output(
            action="inspect",
            status="ok",
            code="LOCAL_RECOVERY_COMPLETE",
            content_identity=local.recovery_id,
            counts={
                "cancel_commands": len(local.cancel_commands),
                "commands": len(local.commands),
                "deliveries": len(local.deliveries),
                "events": len(local.events),
                "issues": len(local.issues),
            },
            issue_codes=tuple(sorted({item.code for item in local.issues})),
        )
    )
    return 0


def _plan(dependencies: CliDependencies) -> int:
    local = _recover(_store(dependencies))
    plan, targets, planning = _fresh_plan(dependencies)
    now = _now(dependencies)
    challenge = _build_challenge(
        action="plan",
        store_recovery_id=local.recovery_id,
        subject_ids=(plan.plan_id,),
        source_identities=_planning_sources(targets, planning),
        gateway_identity=None,
        now=now,
    )
    payload = _output(
            action="plan",
            status="planned",
            code="PLAN_READY",
            content_identity=_digest(challenge),
            counts={"intents": len(plan.intents), "rejections": len(plan.rejections)},
        )
    payload["challenge"] = challenge
    _stdout(payload)
    return 0


def _approve(confirm: str | None, dependencies: CliDependencies) -> int:
    store = _store(dependencies)
    local = _recover(store)
    plan, targets, planning = _fresh_plan(dependencies)
    challenge = _build_challenge(
        action="approve",
        store_recovery_id=local.recovery_id,
        subject_ids=(plan.plan_id,),
        source_identities=_planning_sources(targets, planning),
        gateway_identity=None,
        now=_now(dependencies),
    )
    _confirm_or_emit("approve", challenge, confirm)
    gateway = _gateway(dependencies)
    service = _service(dependencies, store, gateway)
    try:
        staged = service.plan_and_stage(
            targets=targets.targets,
            target_identity=targets.target_identity,
            market=planning.market,
            account=planning.account,
            planner_config=planning.planner_config,
        )
        if build_order_plan_identity(staged.plan) != plan.plan_id:
            raise _CliFailure(20, "APPROVAL_FRESH_PLAN_DRIFT")
    except _CliFailure:
        raise
    except ExecutionServiceError as error:
        _raise_service(error)
    except Exception:
        raise _CliFailure(70, "APPROVAL_INTERNAL_FAILURE") from None
    _stdout(
        _output(
            action="approve",
            status="completed",
            code="APPROVAL_STAGED_REPLAY" if staged.replayed else "APPROVAL_STAGED",
            content_identity=staged.plan.plan_id,
            counts={"commands": len(staged.staged_command_ids)},
        )
    )
    return 0


def _paper_submit(confirm: str | None, dependencies: CliDependencies) -> int:
    store = _store(dependencies)
    local = _recover(store)
    gateway_identity = _gateway_identity(dependencies)
    command_ids = _pending_command_ids(local)
    if not command_ids:
        if local.deliveries and all(
            item.state is OutboxDeliveryState.SENT for item in local.deliveries
        ):
            _stdout(
                _output(
                    action="paper-submit",
                    status="completed",
                    code="SUBMIT_ALREADY_COMPLETE",
                    content_identity=local.recovery_id,
                    counts={"commands": 0, "events": 0},
                )
            )
            return 0
        raise _CliFailure(30, "SUBMIT_SELECTION_EMPTY")
    challenge = _build_challenge(
        action="paper-submit",
        store_recovery_id=local.recovery_id,
        subject_ids=command_ids,
        source_identities={"command_set_identity": _digest_list(command_ids)},
        gateway_identity=gateway_identity,
        now=_now(dependencies),
    )
    challenge_id = _confirm_or_emit("paper-submit", challenge, confirm)
    gateway = _gateway(dependencies, expected_identity=gateway_identity)
    service = _service(dependencies, store, gateway)
    try:
        result = service.dispatch_exact_pending_commands(command_ids=command_ids)
    except ExecutionServiceError as error:
        _raise_service(error)
    except Exception:
        raise _CliFailure(70, "SUBMIT_INTERNAL_FAILURE") from None
    observed = tuple(sorted(item.command_id for item in result.items))
    if result.claimed_count != len(command_ids) or observed != command_ids:
        raise _CliFailure(30, "SUBMIT_SELECTION_DRIFT")
    bad_codes = tuple(sorted({item.code for item in result.items if item.code != "SENT"}))
    if bad_codes:
        if any("UNKNOWN" in code or "LEASE" in code for code in bad_codes):
            raise _CliFailure(30, "SUBMIT_QUERY_REQUIRED")
        raise _CliFailure(50, "SUBMIT_RETRY_REQUIRED")
    _stdout(
        _output(
            action="paper-submit",
            status="completed",
            code="SUBMIT_COMPLETE",
            content_identity=_digest(
                {
                    "challenge_identity": challenge_id,
                    "command_ids": list(command_ids),
                    "event_ids": [
                        event_id for item in result.items for event_id in item.callback_event_ids
                    ],
                }
            ),
            counts={"commands": len(command_ids), "events": sum(len(i.callback_event_ids) for i in result.items)},
        )
    )
    return 0


def _cancel(command_id: str, confirm: str | None, dependencies: CliDependencies) -> int:
    if not _hex64(command_id):
        raise _CliFailure(10, "CANCEL_COMMAND_ID_INVALID")
    store = _store(dependencies)
    local = _recover(store)
    gateway_identity = _gateway_identity(dependencies)
    planning = _fresh_planning(dependencies)
    command, aggregate = _cancel_subject(local, command_id)
    existing = tuple(item for item in local.cancel_commands if item.command_id == command_id)
    if existing:
        cancel_command = existing[0]
    else:
        try:
            cancel_command = build_cancel_command(
                command=command, aggregate=aggregate, as_of=_now(dependencies)
            )
        except Exception:
            raise _CliFailure(40, "CANCEL_NOT_ALLOWED") from None
    cancel_id = build_cancel_command_identity(cancel_command)
    challenge = _build_challenge(
        action="cancel",
        store_recovery_id=local.recovery_id,
        subject_ids=(
            cancel_id,
            command_id,
            _text_identity(cast(str, aggregate.broker_order_id)),
            _aggregate_id(aggregate),
        ),
        source_identities={
            "command_identity": build_order_command_identity(command),
            "planner_config_identity": planning.planner_config.config_identity,
            "trading_config_identity": trading_config_identity(
                planning.planner_config.trading_config
            ),
        },
        gateway_identity=gateway_identity,
        now=_now(dependencies),
    )
    _confirm_or_emit("cancel", challenge, confirm)
    completed = next(
        (
            item
            for item in local.cancel_deliveries
            if item.cancel_id == cancel_id and item.state is OutboxDeliveryState.SENT
        ),
        None,
    )
    if completed is not None:
        _stdout(
            _output(
                action="cancel",
                status="completed",
                code="CANCEL_ALREADY_COMPLETED",
                content_identity=cancel_id,
                counts={"events": sum(1 for item in local.cancel_event_links if item.cancel_id == cancel_id)},
            )
        )
        return 0
    gateway = _gateway(dependencies, expected_identity=gateway_identity)
    service = _service(dependencies, store, gateway)
    try:
        staged = service.stage_cancel(
            command_id=command_id,
            trading_config=planning.planner_config.trading_config,
        )
        if build_cancel_command_identity(staged.cancel) != cancel_id:
            raise _CliFailure(20, "CANCEL_FRESH_STATE_DRIFT")
        result = service.dispatch_cancel(cancel_id=cancel_id)
    except _CliFailure:
        raise
    except ExecutionServiceError as error:
        _raise_service(error)
    except Exception:
        raise _CliFailure(70, "CANCEL_INTERNAL_FAILURE") from None
    if result.code != "SENT":
        if "UNKNOWN" in result.code or "LEASE" in result.code:
            raise _CliFailure(30, "CANCEL_QUERY_REQUIRED")
        raise _CliFailure(50, "CANCEL_RETRY_REQUIRED")
    _stdout(
        _output(
            action="cancel",
            status="completed",
            code="CANCEL_COMPLETE",
            content_identity=cancel_id,
            counts={"events": len(result.callback_event_ids)},
        )
    )
    return 0


def _reconcile(dependencies: CliDependencies) -> int:
    store = _store(dependencies)
    local = _recover(store)
    gateway_identity = _gateway_identity(dependencies)
    try:
        raw_evidence = dependencies.broker_snapshot_port.query_and_verify(
            gateway_identity=gateway_identity
        )
        evidence = verify_broker_evidence(raw_evidence)
        if evidence.gateway_identity != gateway_identity:
            raise CliPortError("CLI_BROKER_EVIDENCE_INVALID")
        broker = build_broker_snapshot(
            source_identity=evidence.source_identity,
            as_of=evidence.as_of,
            finality=evidence.finality,
            account=evidence.account,
            orders=evidence.orders,
            events=evidence.events,
        )
    except CliPortError:
        raise _CliFailure(10, "BROKER_EVIDENCE_INVALID") from None
    except Exception:
        raise _CliFailure(10, "BROKER_EVIDENCE_INVALID") from None
    try:
        result = reconcile(local, broker, evidence.as_of)
    except Exception:
        raise _CliFailure(70, "RECONCILE_INTERNAL_FAILURE") from None
    if not result.gate_passed:
        if evidence.finality == "INTRADAY" or result.disposition == "QUERY_REQUIRED":
            raise _CliFailure(30, "RECONCILE_QUERY_REQUIRED")
        raise _CliFailure(40, "RECONCILE_MANUAL_REQUIRED")
    _stdout(
        _output(
            action="reconcile",
            status="completed",
            code="RECONCILE_GATE_PASS",
            content_identity=result.reconciliation_id,
            counts={"differences": 0},
        )
    )
    return 0


def _fresh_plan(dependencies: CliDependencies):  # type: ignore[no-untyped-def]
    targets = _fresh_targets(dependencies)
    planning = _fresh_planning(dependencies)
    try:
        plan = build_order_plan(
            targets=targets.targets,
            target_identity=targets.target_identity,
            market=planning.market,
            account=planning.account,
            config=planning.planner_config,
        )
        build_order_plan_identity(plan)
    except Exception:
        raise _CliFailure(10, "PLAN_INPUT_INVALID") from None
    return plan, targets, planning


def _fresh_targets(dependencies: CliDependencies):  # type: ignore[no-untyped-def]
    try:
        return verify_target_load(dependencies.target_loader.load())
    except Exception:
        raise _CliFailure(10, "TARGET_IDENTITY_INVALID") from None


def _fresh_planning(dependencies: CliDependencies):  # type: ignore[no-untyped-def]
    try:
        return verify_planning_load(dependencies.planning_loader.load())
    except Exception:
        raise _CliFailure(10, "PLANNING_IDENTITY_INVALID") from None


def _store(dependencies: CliDependencies) -> ExecutionStore:
    try:
        store = dependencies.store_opener.open()
        if type(store) is not ExecutionStore:
            raise TypeError
        return store
    except Exception:
        raise _CliFailure(50, "STORE_OPEN_FAILED") from None


def _recover(store: ExecutionStore) -> RecoveryResult:
    try:
        return recover_local_state(store)
    except Exception:
        raise _CliFailure(40, "LOCAL_RECOVERY_BLOCKED") from None


def _gateway(
    dependencies: CliDependencies, *, expected_identity: str | None = None
):  # type: ignore[no-untyped-def]
    try:
        gateway = verify_paper_gateway(dependencies.paper_gateway_factory.open())
        if expected_identity is not None and gateway.gateway_identity != expected_identity:
            raise ValueError
        return gateway
    except Exception:
        raise _CliFailure(10, "PAPER_GATEWAY_INVALID") from None


def _gateway_identity(dependencies: CliDependencies) -> str:
    try:
        identity = dependencies.paper_gateway_factory.identity()
        if not _hex64(identity):
            raise ValueError
        return identity
    except Exception:
        raise _CliFailure(10, "PAPER_GATEWAY_INVALID") from None


def _service(dependencies: CliDependencies, store: ExecutionStore, gateway):  # type: ignore[no-untyped-def]
    try:
        service = dependencies.service_factory.build(
            store=store, gateway=gateway.submit, cancel_gateway=gateway.cancel
        )
        if type(service) is not ExecutionService:
            raise TypeError
        return service
    except Exception:
        raise _CliFailure(70, "SERVICE_FACTORY_FAILED") from None


def _now(dependencies: CliDependencies) -> dt.datetime:
    try:
        value = dependencies.clock.now()
        if (
            type(value) is not dt.datetime
            or value.tzinfo is None
            or value.utcoffset() != dt.timedelta(0)
        ):
            raise ValueError
        return value
    except Exception:
        raise _CliFailure(10, "CLI_CLOCK_INVALID") from None


def _pending_command_ids(local: RecoveryResult) -> tuple[str, ...]:
    ids = tuple(
        sorted(item.command_id for item in local.deliveries if item.state is OutboxDeliveryState.PENDING)
    )
    if any(item.state in {OutboxDeliveryState.LEASED, OutboxDeliveryState.UNKNOWN} for item in local.deliveries):
        raise _CliFailure(30, "SUBMIT_LOCAL_QUERY_REQUIRED")
    return ids


def _cancel_subject(local: RecoveryResult, command_id: str):  # type: ignore[no-untyped-def]
    commands = {item.command_id: item for item in local.commands}
    aggregates = {item.command_id: item for item in local.order_aggregates}
    command = commands.get(command_id)
    aggregate = aggregates.get(command_id)
    if command is None or aggregate is None or command.mode is not ExecutionMode.PAPER:
        raise _CliFailure(10, "CANCEL_SUBJECT_INVALID")
    if aggregate.broker_order_id is None:
        raise _CliFailure(40, "CANCEL_BROKER_ORDER_MISSING")
    return command, aggregate


def _planning_sources(targets, planning) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {
        "account_snapshot_id": planning.account.snapshot_id,
        "market_snapshot_id": planning.market.snapshot_id,
        "planner_config_identity": planning.planner_config.config_identity,
        "target_receipt_identity": targets.receipt_identity,
        "target_verification_identity": targets.verification_identity,
        "trading_config_identity": trading_config_identity(planning.planner_config.trading_config),
    }


def _build_challenge(
    *,
    action: str,
    store_recovery_id: str,
    subject_ids: tuple[str, ...],
    source_identities: Mapping[str, str],
    gateway_identity: str | None,
    now: dt.datetime,
) -> dict[str, object]:
    issued = now.replace(second=0, microsecond=0, minute=(now.minute // 5) * 5)
    expires = issued + dt.timedelta(minutes=10)
    return {
        "action": action,
        "expires_at": utc_datetime_text(expires),
        "gateway_identity": gateway_identity,
        "issued_at": utc_datetime_text(issued),
        "mode": "PAPER",
        "schema_version": _CHALLENGE_SCHEMA,
        "source_identities": dict(sorted(source_identities.items())),
        "store_recovery_id": store_recovery_id,
        "subject_ids": list(subject_ids),
    }


def _confirm_or_emit(action: str, challenge: dict[str, object], confirm: str | None) -> str:
    challenge_id = _digest(challenge)
    if confirm is None:
        payload = _output(
            action=action,
            status="confirmation_required",
            code="CONFIRMATION_REQUIRED",
            content_identity=challenge_id,
            counts={"subjects": len(cast(list[object], challenge["subject_ids"]))},
        )
        payload["challenge"] = challenge
        _stdout(payload)
        raise _ConfirmationPrinted
    if not _hex64(confirm):
        raise _CliFailure(10, "CONFIRMATION_INVALID")
    if action not in _CONFIRM_ACTIONS or confirm != challenge_id:
        raise _CliFailure(20, "CONFIRMATION_DRIFT")
    return challenge_id


def _output(
    *, action: str, status: str, code: str, content_identity: str, counts: Mapping[str, int],
    issue_codes: tuple[str, ...] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "action": action,
        "code": code,
        "content_identity": content_identity,
        "counts": dict(sorted(counts.items())),
        "schema": _OUTPUT_SCHEMA,
        "status": status,
    }
    if issue_codes is not None:
        value["issue_codes"] = list(issue_codes)
    return value


def _raise_service(error: ExecutionServiceError) -> NoReturn:
    code = error.code
    if "DRIFT" in code:
        raise _CliFailure(20, "CONFIRMATION_DRIFT") from None
    if "LIMIT" in code or "RISK" in code:
        raise _CliFailure(40, "EXECUTION_RISK_BLOCKED") from None
    if "CLAIM" in code or "LEASE" in code or "UNKNOWN" in code:
        raise _CliFailure(30, "EXECUTION_QUERY_REQUIRED") from None
    if "WRITE" in code or "BUSY" in code:
        raise _CliFailure(50, "EXECUTION_RETRY_REQUIRED") from None
    raise _CliFailure(70, "EXECUTION_INTERNAL_FAILURE") from None


def _aggregate_id(value: object) -> str:
    try:
        return hashlib.sha256(encode_order_aggregate(value)).hexdigest()  # type: ignore[arg-type]
    except Exception:
        raise _CliFailure(10, "CANCEL_AGGREGATE_INVALID") from None


def _digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest_list(values: tuple[str, ...]) -> str:
    return hashlib.sha256(canonical_json_bytes({"values": list(values)})).hexdigest()


def _text_identity(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hex64(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(char in _HEX for char in value)


def _stdout(value: Mapping[str, object]) -> None:
    print(canonical_json_bytes(value).decode("utf-8"))


def _stderr(code: str) -> None:
    print(code, file=sys.stderr)


__all__ = ["main"]
