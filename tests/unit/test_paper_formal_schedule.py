from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import replace

import pytest

from quant.execution.paper_formal_ledger import (
    VerifiedFormalPaperLedgerContextProvider,
)
from quant.execution import paper_formal_schedule as formal

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 8, 9, 12, tzinfo=UTC)


def _provider() -> VerifiedFormalPaperLedgerContextProvider:
    start = dt.date(2026, 8, 10)
    sessions = tuple(
        day
        for offset in range(70)
        if (day := start + dt.timedelta(days=offset)).weekday() < 5
    )
    value = object.__new__(VerifiedFormalPaperLedgerContextProvider)
    object.__setattr__(value, "provider_identity", hashlib.sha256(b"provider").hexdigest())
    object.__setattr__(value, "open_sessions", sessions)
    return value


def test_schedule_is_contiguous_and_spans_at_least_35_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    monkeypatch.setattr(
        formal,
        "verify_existing_formal_paper_ledger_context_provider",
        lambda *, provider, now: provider,
    )
    schedule = formal.build_verified_formal_paper_soak_schedule(
        provider=provider,
        readiness_completed_at=NOW,
        not_before=dt.date(2026, 8, 12),
        now=NOW,
    )
    assert schedule.expected_sessions[0] == dt.date(2026, 8, 12)
    assert (schedule.expected_sessions[-1] - schedule.expected_sessions[0]).days >= 35
    expected = tuple(
        item
        for item in provider.open_sessions
        if schedule.expected_sessions[0] <= item <= schedule.expected_sessions[-1]
    )
    assert schedule.expected_sessions == expected
    assert (
        formal.verify_existing_formal_paper_soak_schedule(
            schedule=schedule, now=NOW
        )
        is schedule
    )
    forged = replace(schedule, expected_sessions=schedule.expected_sessions[:-1])
    with pytest.raises(formal.FormalPaperScheduleError):
        formal.verify_existing_formal_paper_soak_schedule(
            schedule=forged, now=NOW
        )


def test_insufficient_calendar_and_hostile_verifier_fail_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    object.__setattr__(provider, "open_sessions", provider.open_sessions[:3])
    monkeypatch.setattr(
        formal,
        "verify_existing_formal_paper_ledger_context_provider",
        lambda *, provider, now: provider,
    )
    with pytest.raises(formal.FormalPaperScheduleError) as caught:
        formal.build_verified_formal_paper_soak_schedule(
            provider=provider,
            readiness_completed_at=NOW,
            not_before=NOW.date(),
            now=NOW,
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None

    def hostile(**kwargs: object) -> object:
        del kwargs
        raise RuntimeError("TOKEN=/hostile/path")

    monkeypatch.setattr(
        formal, "verify_existing_formal_paper_ledger_context_provider", hostile
    )
    with pytest.raises(formal.FormalPaperScheduleError) as hostile_error:
        formal.build_verified_formal_paper_soak_schedule(
            provider=provider,
            readiness_completed_at=NOW,
            not_before=NOW.date(),
            now=NOW,
        )
    assert str(hostile_error.value) == "PAPER_FORMAL_SCHEDULE_INVALID"
