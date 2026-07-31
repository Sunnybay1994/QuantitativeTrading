"""M4 P3-RC1 durable daily risk counter CAS and corruption tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from quant.execution.risk import (
    DailyRiskCounters,
    build_daily_risk_counters_identity,
    deserialize_daily_risk_counters,
    serialize_daily_risk_counters,
)
from quant.execution.store import ExecutionStore, StoreError

UTC = dt.timezone.utc
SESSION = dt.date(2026, 7, 31)


def _hex(tag: str) -> str:
    return hashlib.sha256(tag.encode("utf-8")).hexdigest()


def _open(root: Path, name: str = "execution.db") -> ExecutionStore:
    return ExecutionStore.open(f"sqlite:///{name}", trusted_root=root)


def _counters(
    *,
    order_count: int = 3,
    cancel_count: int = 2,
    buy_notional: str = "1234.50",
) -> DailyRiskCounters:
    return DailyRiskCounters(
        session_date=SESSION,
        order_count=order_count,
        cancel_count=cancel_count,
        buy_notional=Decimal(buy_notional),
    )


def _at(minute: int) -> dt.datetime:
    return dt.datetime(2026, 7, 31, 8, minute, tzinfo=UTC)


def test_canonical_payload_and_identity_roundtrip() -> None:
    counters = _counters()
    payload = serialize_daily_risk_counters(counters)
    assert payload == (
        b'{"buy_notional":"1234.50","cancel_count":2,'
        b'"order_count":3,"session_date":"2026-07-31"}'
    )
    assert deserialize_daily_risk_counters(payload) == counters
    assert len(build_daily_risk_counters_identity(counters)) == 64
    with pytest.raises(ValueError, match="canonical"):
        deserialize_daily_risk_counters(payload + b" ")


def test_initialize_reopen_exact_retry_and_compare_and_set(tmp_path: Path) -> None:
    first = _counters()
    first_identity = build_daily_risk_counters_identity(first)
    store = _open(tmp_path)
    try:
        with store.transaction() as repo:
            assert repo.get_daily_risk_counters(SESSION) is None
            assert repo.compare_and_set_daily_risk_counters(
                expected_identity=None,
                counters=first,
                updated_at=_at(0),
            )
    finally:
        store.close()

    reopened = _open(tmp_path)
    try:
        with reopened.transaction() as repo:
            stored = repo.get_daily_risk_counters(SESSION)
            assert stored is not None
            assert stored.counters == first
            assert stored.identity == first_identity
            assert stored.updated_at == _at(0)
            assert not repo.compare_and_set_daily_risk_counters(
                expected_identity=None,
                counters=first,
                updated_at=_at(1),
            )
            updated = _counters(order_count=4, buy_notional="1334.50")
            assert repo.compare_and_set_daily_risk_counters(
                expected_identity=first_identity,
                counters=updated,
                updated_at=_at(2),
            )
            after = repo.get_daily_risk_counters(SESSION)
            assert after is not None
            assert after.counters == updated
            assert after.updated_at == _at(2)
    finally:
        reopened.close()


def test_two_workers_stale_compare_and_set_cannot_overwrite(tmp_path: Path) -> None:
    initial = _counters()
    initial_identity = build_daily_risk_counters_identity(initial)
    first = _open(tmp_path)
    second = _open(tmp_path)
    try:
        with first.transaction() as repo:
            repo.compare_and_set_daily_risk_counters(
                expected_identity=None,
                counters=initial,
                updated_at=_at(0),
            )
        with first.transaction() as repo:
            observed_a = repo.get_daily_risk_counters(SESSION)
        with second.transaction() as repo:
            observed_b = repo.get_daily_risk_counters(SESSION)
        assert observed_a is not None and observed_b is not None
        assert observed_a.identity == observed_b.identity == initial_identity

        winner = _counters(order_count=4)
        with first.transaction() as repo:
            repo.compare_and_set_daily_risk_counters(
                expected_identity=observed_a.identity,
                counters=winner,
                updated_at=_at(1),
            )
        with pytest.raises(StoreError, match="^RISK_COUNTERS_STALE$"):
            with second.transaction() as repo:
                repo.compare_and_set_daily_risk_counters(
                    expected_identity=observed_b.identity,
                    counters=_counters(cancel_count=3),
                    updated_at=_at(2),
                )
        with second.transaction() as repo:
            final = repo.get_daily_risk_counters(SESSION)
        assert final is not None
        assert final.counters == winner
    finally:
        first.close()
        second.close()


def test_counter_write_rolls_back_with_command_aggregate_and_outbox(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    with pytest.raises(RuntimeError, match="inject rollback"):
        with store.transaction() as repo:
            repo.put_command(command_id="cmd-1", identity=_hex("cmd"), payload=b"cmd")
            repo.put_order_aggregate(
                command_id="cmd-1",
                identity=_hex("aggregate"),
                payload=b"aggregate",
            )
            repo.put_outbox(
                outbox_key="outbox-1",
                identity=_hex("outbox"),
                payload=b"outbox",
            )
            repo.compare_and_set_daily_risk_counters(
                expected_identity=None,
                counters=_counters(),
                updated_at=_at(0),
            )
            raise RuntimeError("inject rollback")
    try:
        with store.transaction() as repo:
            assert repo.get_command("cmd-1") is None
            assert repo.get_order_aggregate("cmd-1") is None
            assert repo.get_outbox("outbox-1") is None
            assert repo.get_daily_risk_counters(SESSION) is None
    finally:
        store.close()


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("identity", "0" * 64),
        ("payload", b"{}"),
        ("updated_at", "2026-07-31T99:99:99.000000Z"),
    ],
)
def test_corrupt_counter_row_fails_closed(
    tmp_path: Path,
    column: str,
    value: object,
) -> None:
    store = _open(tmp_path)
    try:
        with store.transaction() as repo:
            repo.compare_and_set_daily_risk_counters(
                expected_identity=None,
                counters=_counters(),
                updated_at=_at(0),
            )
    finally:
        store.close()
    conn = sqlite3.connect(str(tmp_path / "execution.db"))
    try:
        conn.execute(
            f"UPDATE daily_risk_counters SET {column} = ? WHERE session_date = ?",
            (value, SESSION.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    reopened = _open(tmp_path)
    try:
        with pytest.raises(StoreError, match="^ROW_CORRUPT$"):
            with reopened.transaction() as repo:
                repo.get_daily_risk_counters(SESSION)
    finally:
        reopened.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("session_date", 7),
        ("order_count", True),
        ("cancel_count", -1),
        ("buy_notional", Decimal("NaN")),
    ],
)
def test_forged_counter_fails_before_sql(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    forged = _counters()
    object.__setattr__(forged, field, value)
    store = _open(tmp_path)
    try:
        with pytest.raises(StoreError, match="^COUNTERS_INVALID$") as exc_info:
            with store.transaction() as repo:
                repo.compare_and_set_daily_risk_counters(
                    expected_identity=None,
                    counters=forged,
                    updated_at=_at(0),
                )
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__context__ is None
        with store.transaction() as repo:
            assert repo.get_daily_risk_counters(SESSION) is None
    finally:
        store.close()


def test_missing_row_with_non_null_expected_identity_is_stale(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        with pytest.raises(StoreError, match="^RISK_COUNTERS_STALE$"):
            with store.transaction() as repo:
                repo.compare_and_set_daily_risk_counters(
                    expected_identity=_hex("missing"),
                    counters=_counters(),
                    updated_at=_at(0),
                )
    finally:
        store.close()


def test_deeply_nested_json_row_maps_to_scrubbed_row_corrupt(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        with store.transaction() as repo:
            repo.compare_and_set_daily_risk_counters(
                expected_identity=None,
                counters=_counters(),
                updated_at=_at(0),
            )
    finally:
        store.close()
    conn = sqlite3.connect(str(tmp_path / "execution.db"))
    try:
        conn.execute(
            "UPDATE daily_risk_counters SET payload = ? WHERE session_date = ?",
            (b"[" * 10_000 + b"]" * 10_000, SESSION.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    reopened = _open(tmp_path)
    try:
        with pytest.raises(StoreError, match="^ROW_CORRUPT$") as exc_info:
            with reopened.transaction() as repo:
                repo.get_daily_risk_counters(SESSION)
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__context__ is None
    finally:
        reopened.close()
