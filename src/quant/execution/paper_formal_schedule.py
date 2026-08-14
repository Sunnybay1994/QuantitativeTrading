"""Verified formal PAPER soak schedule derived from a fresh calendar provider."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from typing import NoReturn, SupportsIndex

from quant.domain.canonical_wire import canonical_json_bytes, utc_datetime_text
from quant.execution.paper_formal_ledger import (
    VerifiedFormalPaperLedgerContextProvider,
    verify_existing_formal_paper_ledger_context_provider,
)
from quant.execution.soak import expected_schedule_identity

_SCHEMA = "formal-paper-soak-schedule-v1"
_MINIMUM_SPAN_DAYS = 35


class FormalPaperScheduleError(ValueError):
    """Stable, sanitized formal schedule failure."""

    def __init__(self) -> None:
        self.code = "PAPER_FORMAL_SCHEDULE_INVALID"
        super().__init__(self.code)

    @property
    def __context__(self) -> None:
        return None

    @__context__.setter
    def __context__(self, value: BaseException | None) -> None:
        del value


@dataclass(frozen=True, slots=True)
class _Attestation:
    token: bytes = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal PAPER schedule is process-local")


@dataclass(frozen=True, slots=True)
class VerifiedFormalPaperSoakSchedule:
    """Process-local proof of one contiguous future open-session window."""

    schema_version: str
    schedule_identity: str
    expected_schedule_identity: str
    ledger_provider_identity: str
    readiness_completed_at: dt.datetime
    not_before: dt.date
    expected_sessions: tuple[dt.date, ...]
    verified_at: dt.datetime
    _provider: VerifiedFormalPaperLedgerContextProvider = field(
        repr=False, compare=False
    )
    _attestation: _Attestation = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal PAPER schedule is process-local")


class _Failure(Exception):
    pass


def _create_api():  # type: ignore[no-untyped-def]
    key = secrets.token_bytes(32)

    def token(value: VerifiedFormalPaperSoakSchedule) -> bytes:
        return hmac.new(
            key, canonical_json_bytes(_payload(value)), hashlib.sha256
        ).digest()

    def valid(value: VerifiedFormalPaperSoakSchedule) -> bool:
        try:
            return type(value._attestation) is _Attestation and hmac.compare_digest(
                value._attestation.token, token(value)
            )
        except Exception:
            return False

    def build_verified_formal_paper_soak_schedule(
        *,
        provider: VerifiedFormalPaperLedgerContextProvider,
        readiness_completed_at: dt.datetime,
        not_before: dt.date,
        now: dt.datetime,
    ) -> VerifiedFormalPaperSoakSchedule:
        try:
            timestamp = _utc(now)
            readiness = _utc(readiness_completed_at)
            if type(not_before) is not dt.date or readiness > timestamp:
                raise _Failure
            fresh = verify_existing_formal_paper_ledger_context_provider(
                provider=provider, now=timestamp
            )
            if fresh is not provider:
                raise _Failure
            sessions = _select(
                provider.open_sessions,
                max(not_before, readiness.date() + dt.timedelta(days=1)),
            )
            expected_identity = expected_schedule_identity(sessions)
            stable = {
                "schema_version": _SCHEMA,
                "expected_schedule_identity": expected_identity,
                "ledger_provider_identity": provider.provider_identity,
                "readiness_completed_at": utc_datetime_text(readiness),
                "not_before": not_before.isoformat(),
                "expected_sessions": [item.isoformat() for item in sessions],
            }
            value = VerifiedFormalPaperSoakSchedule(
                schema_version=_SCHEMA,
                schedule_identity=_digest(stable),
                expected_schedule_identity=expected_identity,
                ledger_provider_identity=provider.provider_identity,
                readiness_completed_at=readiness,
                not_before=not_before,
                expected_sessions=sessions,
                verified_at=timestamp,
                _provider=provider,
                _attestation=_Attestation(b""),
            )
            object.__setattr__(value, "_attestation", _Attestation(token(value)))
            if not valid(value):
                raise _Failure
            return value
        except Exception:
            pass
        raise FormalPaperScheduleError() from None

    def verify_existing_formal_paper_soak_schedule(
        *, schedule: VerifiedFormalPaperSoakSchedule, now: dt.datetime
    ) -> VerifiedFormalPaperSoakSchedule:
        try:
            timestamp = _utc(now)
            if (
                type(schedule) is not VerifiedFormalPaperSoakSchedule
                or not valid(schedule)
                or timestamp < schedule.verified_at
            ):
                raise _Failure
            provider = verify_existing_formal_paper_ledger_context_provider(
                provider=schedule._provider, now=timestamp
            )
            sessions = _select(
                provider.open_sessions,
                max(
                    schedule.not_before,
                    schedule.readiness_completed_at.date() + dt.timedelta(days=1),
                ),
            )
            if (
                provider is not schedule._provider
                or sessions != schedule.expected_sessions
                or expected_schedule_identity(sessions)
                != schedule.expected_schedule_identity
                or schedule.schedule_identity != _digest(_stable(schedule))
            ):
                raise _Failure
            return schedule
        except Exception:
            pass
        raise FormalPaperScheduleError() from None

    return (
        build_verified_formal_paper_soak_schedule,
        verify_existing_formal_paper_soak_schedule,
    )


(
    build_verified_formal_paper_soak_schedule,
    verify_existing_formal_paper_soak_schedule,
) = _create_api()
del _create_api


def _select(sessions: tuple[dt.date, ...], start: dt.date) -> tuple[dt.date, ...]:
    if (
        type(sessions) is not tuple
        or not sessions
        or sessions != tuple(sorted(set(sessions)))
    ):
        raise _Failure
    selected = tuple(item for item in sessions if item >= start)
    if not selected:
        raise _Failure
    terminal = next(
        (
            item
            for item in selected
            if (item - selected[0]).days >= _MINIMUM_SPAN_DAYS
        ),
        None,
    )
    if terminal is None:
        raise _Failure
    return tuple(item for item in selected if item <= terminal)


def _stable(value: VerifiedFormalPaperSoakSchedule) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "expected_schedule_identity": value.expected_schedule_identity,
        "ledger_provider_identity": value.ledger_provider_identity,
        "readiness_completed_at": utc_datetime_text(value.readiness_completed_at),
        "not_before": value.not_before.isoformat(),
        "expected_sessions": [item.isoformat() for item in value.expected_sessions],
    }


def _payload(value: VerifiedFormalPaperSoakSchedule) -> dict[str, object]:
    return {**_stable(value), "verified_at": utc_datetime_text(value.verified_at)}


def _digest(value: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _utc(value: dt.datetime) -> dt.datetime:
    if type(value) is not dt.datetime or value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise _Failure
    return value


__all__ = [
    "FormalPaperScheduleError",
    "VerifiedFormalPaperSoakSchedule",
    "build_verified_formal_paper_soak_schedule",
    "verify_existing_formal_paper_soak_schedule",
]
