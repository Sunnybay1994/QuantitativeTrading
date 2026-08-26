"""M4-B1B2: public formal broker EOD finalize/query boundary tests.

Covers the package-owned ``finalize_and_query_formal_paper_broker_eod``
surface consumed by ``soak_runtime`` (INFRA-007: no underscore-helper
import from that caller). All setup reuses the real formal broker store
chain from ``test_paper_formal_broker_store`` rather than mocks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant.execution import paper_formal_broker_snapshot as formal_snapshot
from quant.execution import paper_formal_broker_store as formal
from tests.unit.test_paper_formal_broker_store import NOW, _allow_chain, _chains

_ZERO_CLOSURE = "a" * 64


def _capability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    cold, materialized = _chains(tmp_path)
    _allow_chain(monkeypatch, materialized)
    capability = formal.initialize_verified_formal_paper_broker_store(
        environment=cold[0], policy=cold[1], binding=cold[2], account=cold[3], now=NOW
    )
    return capability, materialized


def test_public_finalize_symbol_is_importable_without_underscore_helper() -> None:
    assert "finalize_and_query_formal_paper_broker_eod" in formal_snapshot.__all__
    assert hasattr(formal_snapshot, "finalize_and_query_formal_paper_broker_eod")


def test_finalize_zero_command_session_marks_finality_and_returns_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capability, materialized = _capability(tmp_path, monkeypatch)
    environment, policy, binding, account = materialized
    assert capability.store.read_session_finality(session_date=NOW.date()) is None

    evidence = formal_snapshot.finalize_and_query_formal_paper_broker_eod(
        store_capability=capability,
        environment=environment,
        policy=policy,
        binding=binding,
        account=account,
        session_date=NOW.date(),
        now=NOW,
        gateway_identity=capability.gateway_identity,
        order_semantic_closure_identity=_ZERO_CLOSURE,
    )
    assert evidence.gateway_identity == capability.gateway_identity
    assert evidence.finality == "END_OF_DAY"
    assert evidence.orders == () and evidence.events == ()

    marker = capability.store.read_session_finality(session_date=NOW.date())
    assert marker is not None
    assert marker.order_semantic_closure_identity == _ZERO_CLOSURE
    capability.store.close()


def test_finalize_resume_with_existing_marker_is_zero_write_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capability, materialized = _capability(tmp_path, monkeypatch)
    environment, policy, binding, account = materialized
    first = formal_snapshot.finalize_and_query_formal_paper_broker_eod(
        store_capability=capability,
        environment=environment,
        policy=policy,
        binding=binding,
        account=account,
        session_date=NOW.date(),
        now=NOW,
        gateway_identity=capability.gateway_identity,
        order_semantic_closure_identity=_ZERO_CLOSURE,
    )
    marker_after_first = capability.store.read_session_finality(session_date=NOW.date())

    second = formal_snapshot.finalize_and_query_formal_paper_broker_eod(
        store_capability=capability,
        environment=environment,
        policy=policy,
        binding=binding,
        account=account,
        session_date=NOW.date(),
        now=NOW,
        gateway_identity=capability.gateway_identity,
        order_semantic_closure_identity=_ZERO_CLOSURE,
    )
    marker_after_second = capability.store.read_session_finality(session_date=NOW.date())
    assert marker_after_first == marker_after_second
    assert second.source_identity == first.source_identity
    capability.store.close()


def test_finalize_resume_rejects_mismatched_zero_closure_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capability, materialized = _capability(tmp_path, monkeypatch)
    environment, policy, binding, account = materialized
    formal_snapshot.finalize_and_query_formal_paper_broker_eod(
        store_capability=capability,
        environment=environment,
        policy=policy,
        binding=binding,
        account=account,
        session_date=NOW.date(),
        now=NOW,
        gateway_identity=capability.gateway_identity,
        order_semantic_closure_identity=_ZERO_CLOSURE,
    )
    with pytest.raises(formal_snapshot.FormalPaperBrokerSnapshotError) as caught:
        formal_snapshot.finalize_and_query_formal_paper_broker_eod(
            store_capability=capability,
            environment=environment,
            policy=policy,
            binding=binding,
            account=account,
            session_date=NOW.date(),
            now=NOW,
            gateway_identity=capability.gateway_identity,
            order_semantic_closure_identity="b" * 64,
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    capability.store.close()


def test_finalize_rejects_forged_capability_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capability, materialized = _capability(tmp_path, monkeypatch)
    environment, policy, binding, account = materialized
    forged = object()
    with pytest.raises(formal_snapshot.FormalPaperBrokerSnapshotError) as caught:
        formal_snapshot.finalize_and_query_formal_paper_broker_eod(
            store_capability=forged,  # type: ignore[arg-type]
            environment=environment,
            policy=policy,
            binding=binding,
            account=account,
            session_date=NOW.date(),
            now=NOW,
            gateway_identity=capability.gateway_identity,
            order_semantic_closure_identity=_ZERO_CLOSURE,
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    capability.store.close()


def test_finalize_rejects_mismatched_gateway_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capability, materialized = _capability(tmp_path, monkeypatch)
    environment, policy, binding, account = materialized
    with pytest.raises(formal_snapshot.FormalPaperBrokerSnapshotError) as caught:
        formal_snapshot.finalize_and_query_formal_paper_broker_eod(
            store_capability=capability,
            environment=environment,
            policy=policy,
            binding=binding,
            account=account,
            session_date=NOW.date(),
            now=NOW,
            gateway_identity="0" * 64,
            order_semantic_closure_identity=_ZERO_CLOSURE,
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    capability.store.close()


def test_finalize_rejects_wrong_session_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import datetime as dt

    capability, materialized = _capability(tmp_path, monkeypatch)
    environment, policy, binding, account = materialized
    with pytest.raises(formal_snapshot.FormalPaperBrokerSnapshotError) as caught:
        formal_snapshot.finalize_and_query_formal_paper_broker_eod(
            store_capability=capability,
            environment=environment,
            policy=policy,
            binding=binding,
            account=account,
            session_date=NOW.date() + dt.timedelta(days=1),
            now=NOW,
            gateway_identity=capability.gateway_identity,
            order_semantic_closure_identity=_ZERO_CLOSURE,
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    capability.store.close()


@pytest.mark.parametrize(
    "bad_identity",
    ["", "z" * 64, "a" * 63, "A" * 64, "a" * 65],
)
def test_finalize_rejects_malformed_order_semantic_closure_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_identity: str
) -> None:
    capability, materialized = _capability(tmp_path, monkeypatch)
    environment, policy, binding, account = materialized
    with pytest.raises(formal_snapshot.FormalPaperBrokerSnapshotError) as caught:
        formal_snapshot.finalize_and_query_formal_paper_broker_eod(
            store_capability=capability,
            environment=environment,
            policy=policy,
            binding=binding,
            account=account,
            session_date=NOW.date(),
            now=NOW,
            gateway_identity=capability.gateway_identity,
            order_semantic_closure_identity=bad_identity,
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    capability.store.close()


def test_finalize_hostile_fresh_verify_error_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capability, materialized = _capability(tmp_path, monkeypatch)
    environment, policy, binding, account = materialized
    monkeypatch.setattr(
        formal_snapshot,
        "verify_existing_formal_paper_broker_store_capability",
        lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("HOSTILE_FORMAL_FINALIZE_MARKER")
        ),
    )
    with pytest.raises(formal_snapshot.FormalPaperBrokerSnapshotError) as caught:
        formal_snapshot.finalize_and_query_formal_paper_broker_eod(
            store_capability=capability,
            environment=environment,
            policy=policy,
            binding=binding,
            account=account,
            session_date=NOW.date(),
            now=NOW,
            gateway_identity=capability.gateway_identity,
            order_semantic_closure_identity=_ZERO_CLOSURE,
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "HOSTILE" not in str(caught.value)
    capability.store.close()
