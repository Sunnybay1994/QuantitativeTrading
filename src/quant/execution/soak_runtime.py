"""Minimal single-session closure for the Windows PAPER soak track."""

from __future__ import annotations

import datetime as dt
import errno
import os
import stat
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Protocol, cast

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

from quant.execution.paper_formal_broker_snapshot import (
    _finalize_and_query_formal_paper_broker_eod,
)
from quant.execution.paper_formal_schedule import (
    VerifiedFormalPaperSoakSchedule,
    verify_existing_formal_paper_soak_schedule,
)
from quant.execution.paper_formal_service import (
    VerifiedFormalPaperServiceComposition,
    verify_existing_formal_paper_service_composition,
)
from quant.execution.paper_policy import (
    VerifiedPaperExecutionPolicy,
    verify_existing_paper_execution_policy,
)
from quant.execution.paper_runtime import (
    VerifiedPaperRuntimeEnvironment,
    verify_existing_paper_runtime_preflight,
)
from quant.execution.reconcile import (
    RecoveryResult,
    ReconciliationResult,
    build_broker_snapshot,
    reconcile,
    recover_local_state,
)
from quant.execution.soak import (
    SoakGateDecision,
    SoakRunManifest,
    SoakSessionReceipt,
    SoakEvidenceKind,
    VerifiedPaperSoakEvidence,
    append_soak_session,
    build_soak_run,
    decide_soak_gate,
    _session_order_semantic_closure_identity,
    verify_soak_evidence,
)

_LOCK_NAME = "paper-soak-session.lock"
_REPARSE_POINT = 0x400


class SessionReportPort(Protocol):
    """Narrow boundary implemented by the reporting layer."""

    def build(
        self,
        *,
        recovery: RecoveryResult,
        reconciliation: ReconciliationResult,
        as_of: dt.datetime,
    ) -> object: ...


class FormalPaperSoakSessionError(ValueError):
    """Stable, sanitized single-session closure failure."""

    def __init__(self) -> None:
        self.code = "PAPER_SOAK_SESSION_INVALID"
        super().__init__(self.code)

    @property
    def __context__(self) -> None:
        return None

    @__context__.setter
    def __context__(self, value: BaseException | None) -> None:
        del value


@dataclass(frozen=True, slots=True)
class FormalPaperSoakSessionResult:
    """Exact fresh result for one appended or replayed session."""

    manifest: SoakRunManifest
    session_receipt: SoakSessionReceipt
    evidence: VerifiedPaperSoakEvidence
    decision: SoakGateDecision
    replayed: bool


def close_formal_paper_soak_session(
    *,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    composition: VerifiedFormalPaperServiceComposition,
    schedule: VerifiedFormalPaperSoakSchedule,
    session_date: dt.date,
    now: dt.datetime,
    report_port: SessionReportPort,
) -> FormalPaperSoakSessionResult:
    """Close one exact Windows PAPER session without dispatching an order."""
    try:
        if (
            type(environment) is not VerifiedPaperRuntimeEnvironment
            or type(policy) is not VerifiedPaperExecutionPolicy
            or type(composition) is not VerifiedFormalPaperServiceComposition
            or type(schedule) is not VerifiedFormalPaperSoakSchedule
            or type(session_date) is not dt.date
            or not _utc(now)
            or not callable(getattr(report_port, "build", None))
        ):
            raise ValueError

        # This first verification is read-only path authorization.  All retained
        # identities are verified again under the writer lock below.
        verify_existing_paper_runtime_preflight(
            environment,
            config_path=environment.config.source_path,
            now=now,
        )
        with _hold_session_lock(environment.config.log_root):
            _verify_fresh_chain(
                environment=environment,
                policy=policy,
                composition=composition,
                schedule=schedule,
                session_date=session_date,
                now=now,
            )
            config = environment.config
            manifest = build_soak_run(
                root=config.evidence_root,
                anchor_root=config.anchor_root,
                evidence_kind=SoakEvidenceKind.PAPER_REAL_TIME_WINDOWS,
                source_identity=schedule.schedule_identity,
                config_identity=config.config_identity,
                gateway_identity=composition.gateway_identity,
                store_identity=composition.execution_store_identity,
                account_identity=composition.account_id,
                expected_sessions=schedule.expected_sessions,
                expected_schedule_identity=schedule.expected_schedule_identity,
                started_at=schedule.readiness_completed_at,
            )
            before = _verified_windows_evidence(
                root=config.evidence_root,
                anchor_root=config.anchor_root,
                manifest=manifest,
            )
            existing = _session_receipt(before, session_date)
            missing = tuple(
                item
                for item in schedule.expected_sessions
                if item not in {receipt.session_date for receipt in before.sessions}
            )
            if existing is None and (not missing or missing[0] != session_date):
                raise ValueError

            store = composition.store_opener.open()
            if store is not composition._execution_store.store:
                raise ValueError
            recovery = recover_local_state(store)
            closure_identity = _session_order_semantic_closure_identity(
                recovery, session_date=session_date
            )

            broker_capability = composition._execution_store.broker_store
            if existing is not None and broker_capability.store.read_session_finality(
                session_date=session_date
            ) is None:
                raise ValueError
            broker_evidence = _finalize_and_query_formal_paper_broker_eod(
                store_capability=broker_capability,
                environment=environment,
                policy=policy,
                binding=composition._execution_store.binding,
                account=composition._execution_store.account,
                session_date=session_date,
                now=now,
                gateway_identity=composition.gateway_identity,
                order_semantic_closure_identity=closure_identity,
            )
            broker_snapshot = build_broker_snapshot(
                source_identity=broker_evidence.source_identity,
                as_of=broker_evidence.as_of,
                finality=broker_evidence.finality,
                account=broker_evidence.account,
                orders=broker_evidence.orders,
                events=broker_evidence.events,
            )
            reconciliation = reconcile(
                recovery, broker_snapshot, broker_evidence.as_of
            )
            fresh_recovery = recover_local_state(store)
            fresh_closure_identity = _session_order_semantic_closure_identity(
                fresh_recovery, session_date=session_date
            )
            if (
                fresh_recovery.recovery_id != recovery.recovery_id
                or fresh_closure_identity != closure_identity
            ):
                raise ValueError
            recovery = fresh_recovery

            if existing is not None:
                if (
                    existing.recovery_id != recovery.recovery_id
                    or existing.reconciliation_id
                    != reconciliation.reconciliation_id
                ):
                    raise ValueError
                _verify_fresh_chain(
                    environment=environment,
                    policy=policy,
                    composition=composition,
                    schedule=schedule,
                    session_date=session_date,
                    now=now,
                )
                decision = _fresh_decision(
                    evidence=before,
                    root=config.evidence_root,
                    anchor_root=config.anchor_root,
                    now=now,
                )
                return FormalPaperSoakSessionResult(
                    manifest, existing, before, decision, True
                )

            report = report_port.build(
                recovery=recovery,
                reconciliation=reconciliation,
                as_of=broker_evidence.as_of,
            )
            receipt = append_soak_session(
                root=config.evidence_root,
                anchor_root=config.anchor_root,
                manifest=manifest,
                session_date=session_date,
                invocation_started_at=now,
                invocation_completed_at=now,
                source_identity=manifest.source_identity,
                config_identity=manifest.config_identity,
                gateway_identity=manifest.gateway_identity,
                store_identity=manifest.store_identity,
                account_identity=manifest.account_identity,
                recovery=recovery,
                reconciliation=reconciliation,
                execution_report=cast(Any, report),
            )
            evidence = _verified_windows_evidence(
                root=config.evidence_root,
                anchor_root=config.anchor_root,
                manifest=manifest,
            )
            if _session_receipt(evidence, session_date) != receipt:
                raise ValueError
            _verify_fresh_chain(
                environment=environment,
                policy=policy,
                composition=composition,
                schedule=schedule,
                session_date=session_date,
                now=now,
            )
            decision = _fresh_decision(
                evidence=evidence,
                root=config.evidence_root,
                anchor_root=config.anchor_root,
                now=now,
            )
            return FormalPaperSoakSessionResult(
                manifest, receipt, evidence, decision, False
            )
    except FormalPaperSoakSessionError:
        raise
    except Exception:
        pass
    raise FormalPaperSoakSessionError() from None


def _verify_fresh_chain(
    *,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    composition: VerifiedFormalPaperServiceComposition,
    schedule: VerifiedFormalPaperSoakSchedule,
    session_date: dt.date,
    now: dt.datetime,
) -> None:
    verify_existing_paper_runtime_preflight(
        environment,
        config_path=environment.config.source_path,
        now=now,
    )
    fresh_policy = verify_existing_paper_execution_policy(
        policy=policy, environment=environment, now=now
    )
    fresh_composition = verify_existing_formal_paper_service_composition(
        composition=composition, now=now
    )
    fresh_schedule = verify_existing_formal_paper_soak_schedule(
        schedule=schedule, now=now
    )
    execution_store = composition._execution_store
    if (
        fresh_policy != policy
        or fresh_composition is not composition
        or fresh_schedule is not schedule
        or environment.config.mode != "PAPER_REAL_TIME_WINDOWS"
        or policy.session_date != session_date
        or execution_store.environment is not environment
        or execution_store.policy is not policy
        or execution_store.account.session_date != session_date
        or execution_store.broker_store.session_date != session_date
        or execution_store.store_identity != composition.execution_store_identity
        or execution_store.gateway_identity != composition.gateway_identity
        or execution_store.account_id != composition.account_id
        or composition._ledger_provider._execution_store is not execution_store
        or schedule._provider is not composition._ledger_provider
        or schedule.ledger_provider_identity
        != composition.ledger_provider_identity
        or session_date not in schedule.expected_sessions
    ):
        raise ValueError


def _verified_windows_evidence(
    *, root: Path, anchor_root: Path, manifest: SoakRunManifest
) -> VerifiedPaperSoakEvidence:
    evidence = verify_soak_evidence(
        root=root, anchor_root=anchor_root, manifest=manifest
    )
    if (
        type(evidence) is not VerifiedPaperSoakEvidence
        or evidence.manifest != manifest
        or manifest.evidence_kind is not SoakEvidenceKind.PAPER_REAL_TIME_WINDOWS
        or manifest.formal_gate_eligible
    ):
        raise ValueError
    return evidence


def _session_receipt(
    evidence: VerifiedPaperSoakEvidence, session_date: dt.date
) -> SoakSessionReceipt | None:
    matches = tuple(
        receipt
        for receipt in evidence.sessions
        if receipt.session_date == session_date
    )
    if len(matches) > 1:
        raise ValueError
    return None if not matches else matches[0]


def _fresh_decision(
    *,
    evidence: VerifiedPaperSoakEvidence,
    root: Path,
    anchor_root: Path,
    now: dt.datetime,
) -> SoakGateDecision:
    decision = decide_soak_gate(
        evidence, root=root, anchor_root=anchor_root, as_of=now
    )
    if decision.run_id != evidence.manifest.run_id or decision.status == "PASS":
        raise ValueError
    return decision


@contextmanager
def _hold_session_lock(root: Path) -> Iterator[None]:
    descriptor = _acquire_session_lock(root)
    primary = False
    try:
        yield
    except BaseException:
        primary = True
        raise
    finally:
        release_failed = False
        try:
            _release_lock(descriptor)
        except Exception:
            release_failed = True
        try:
            os.close(descriptor)
        except OSError:
            release_failed = True
        if release_failed and not primary:
            raise FormalPaperSoakSessionError() from None


def _acquire_session_lock(root: Path) -> int:
    descriptor = -1
    try:
        if not isinstance(root, Path) or not root.is_absolute():
            raise ValueError
        before = os.lstat(root)
        if not stat.S_ISDIR(before.st_mode) or _is_reparse(root, before):
            raise ValueError
        lock_path = root / _LOCK_NAME
        try:
            lock_before = os.lstat(lock_path)
        except FileNotFoundError:
            lock_before = None
        if lock_before is not None and not _valid_lock_status(lock_path, lock_before):
            raise ValueError
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        if sys.platform != "win32":
            flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(lock_path, flags, 0o600)
        opened = os.fstat(descriptor)
        current = os.lstat(lock_path)
        root_after_open = os.lstat(root)
        if (
            not _valid_lock_status(lock_path, opened)
            or not _valid_lock_status(lock_path, current)
            or _object_identity(opened) != _object_identity(current)
            or _object_identity(before) != _object_identity(root_after_open)
        ):
            raise ValueError
        if opened.st_size == 0:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.write(descriptor, b"\0") != 1:
                raise OSError
            os.fsync(descriptor)
        elif opened.st_size != 1:
            raise ValueError
        _apply_lock(descriptor)
        locked = os.fstat(descriptor)
        current = os.lstat(lock_path)
        root_after_lock = os.lstat(root)
        if (
            locked.st_size != 1
            or not _valid_lock_status(lock_path, locked)
            or not _valid_lock_status(lock_path, current)
            or _object_identity(locked) != _object_identity(current)
            or _object_identity(before) != _object_identity(root_after_lock)
        ):
            raise ValueError
        result = descriptor
        descriptor = -1
        return result
    except Exception:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise FormalPaperSoakSessionError() from None


def _apply_lock(descriptor: int) -> None:
    try:
        if sys.platform == "win32":
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in {
            errno.EACCES,
            errno.EAGAIN,
            getattr(errno, "EWOULDBLOCK", errno.EAGAIN),
        }:
            raise FormalPaperSoakSessionError() from None
        raise


def _release_lock(descriptor: int) -> None:
    if sys.platform == "win32":
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


def _valid_lock_status(path: Path, value: os.stat_result) -> bool:
    return (
        stat.S_ISREG(value.st_mode)
        and not stat.S_ISLNK(value.st_mode)
        and not _is_reparse(path, value)
        and value.st_nlink == 1
    )


def _is_reparse(path: Path, value: os.stat_result) -> bool:
    if stat.S_ISLNK(value.st_mode):
        return True
    is_junction = getattr(os.path, "isjunction", None)
    if callable(is_junction) and is_junction(path):
        return True
    return bool(getattr(value, "st_file_attributes", 0) & _REPARSE_POINT)


def _object_identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _utc(value: object) -> bool:
    return (
        type(value) is dt.datetime
        and cast(dt.datetime, value).tzinfo is not None
        and cast(dt.datetime, value).utcoffset() == dt.timedelta(0)
    )


__all__ = [
    "FormalPaperSoakSessionError",
    "FormalPaperSoakSessionResult",
    "SessionReportPort",
    "close_formal_paper_soak_session",
]
