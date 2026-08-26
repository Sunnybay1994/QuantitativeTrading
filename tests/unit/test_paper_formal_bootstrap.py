"""STATIC-authored focused unit tests for formal PAPER runtime bootstrap."""

from __future__ import annotations

import copy
import datetime as dt
import pickle
from dataclasses import replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace

import pytest

from quant.execution import paper_formal_bootstrap as bootstrap
from quant.execution import paper_formal_execution_store as formal_oms
from quant.execution.paper_formal_broker_store import (
    FormalPaperBrokerStoreError,
    VerifiedFormalPaperBrokerStoreCapability,
    _StoreAttestation,
)
from quant.execution.paper_runtime import FormalPaperRuntimeConfig
from quant.execution.session_barrier import SessionBarrierRow

NOW = dt.datetime(2026, 8, 12, 10, tzinfo=dt.timezone.utc)
SESSION = NOW.date()
LOCK_ID = "a" * 64
BROKER_DESC = "b" * 64
ACCT_DESC = "c" * 64


def _assert_bootstrap_error(error: bootstrap.FormalPaperBootstrapError, code: str) -> None:
    assert error.code == code
    assert str(error) == code
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "/" not in code and "\\" not in code


def _config(tmp_path: Path) -> FormalPaperRuntimeConfig:
    parent = tmp_path / "paper-parent"
    parent.mkdir(parents=True, exist_ok=True)
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    return FormalPaperRuntimeConfig(
        source_path=(tmp_path / "config-parent" / "runtime.toml").resolve(),
        source_file_identity="1" * 64,
        source_parent_identity="2" * 64,
        raw_sha256="3" * 64,
        schema_version="paper-runtime-config-v2",
        runtime_version="paper_runtime_v2",
        mode="PAPER_REAL_TIME_WINDOWS",
        runtime_root=parent / "runtime",
        broker_root=parent / "broker",
        evidence_root=parent / "evidence",
        anchor_root=parent / "anchor",
        log_root=parent / "log",
        project_root=project,
        oms_sqlite_filename="oms.sqlite3",
        broker_sqlite_filename="broker.sqlite3",
        account_selector="formal_paper_a_share_v1",
        source_selector="formal_source_v1",
        policy_selector="paper_a_share_v1",
        expected_schedule_selector="formal_schedule_v1",
        config_identity="4" * 64,
    )


def _open_row(**overrides: object) -> SessionBarrierRow:
    payload = {
        "barrier_schema": "m4-session-barrier-v1",
        "barrier_epoch": "e" * 64,
        "session_date": SESSION.isoformat(),
        "account_identity": ACCT_DESC,
        "oms_store_identity": "o" * 64,
        "broker_store_identity": BROKER_DESC,
        "gateway_identity": "g" * 64,
        "config_identity": "4" * 64,
        "lock_identity": LOCK_ID,
        "state": "OPEN",
        "close_token_identity": None,
        "created_at": "2026-08-12T10:00:00Z",
        "transitioned_at": "2026-08-12T10:00:00Z",
        "row_identity": "r" * 64,
        "terminal_successor_identity": None,
    }
    payload.update(overrides)
    return SessionBarrierRow(**payload)  # type: ignore[arg-type]


def _fake_store(*, barrier_enabled: bool = True, row: SessionBarrierRow | None = None):
    current = row if row is not None else _open_row()

    def _read() -> SessionBarrierRow:
        return current

    return SimpleNamespace(
        session_barrier_enabled=lambda: barrier_enabled,
        read_session_barrier_row=_read,
        close=lambda: None,
        descriptor=SimpleNamespace(descriptor_identity=BROKER_DESC),
    )


def _policy(*, identity: str, session_date: dt.date = SESSION) -> SimpleNamespace:
    return SimpleNamespace(
        session_date=session_date,
        policy_identity=identity,
        verified_at=NOW,
        source_path=Path("/policy.toml"),
        source_file_identity="p1" * 32,
        raw_sha256="p2" * 32,
        cost_schedule_identity="p3" * 32,
        trading_config_identity="p4" * 32,
        selector="paper_a_share_v1",
    )


def _binding(
    *,
    identity: str,
    env_id: str,
    policy_id: str,
    config_id: str = "4" * 64,
    cost_schedule_identity: str = "p3" * 32,
):
    return SimpleNamespace(
        binding_identity=identity,
        verified_at=NOW,
        session_date=SESSION,
        runtime_environment_identity=env_id,
        runtime_config_identity=config_id,
        execution_policy_identity=policy_id,
        cost_schedule_identity=cost_schedule_identity,
    )


def _account(
    *,
    verification: str,
    env_id: str,
    policy_id: str,
    binding_id: str,
    config_id: str = "4" * 64,
):
    descriptor = SimpleNamespace(account_id="acct-1")
    return SimpleNamespace(
        account_id="acct-1",
        verification_identity=verification,
        descriptor_identity=ACCT_DESC,
        verified_at=NOW,
        session_date=SESSION,
        runtime_environment_identity=env_id,
        runtime_config_identity=config_id,
        execution_policy_identity=policy_id,
        broker_binding_identity=binding_id,
        source_path=Path("/account.toml"),
        source_file_identity="a1" * 32,
        raw_sha256="a2" * 32,
        account_descriptor=descriptor,
        initial_snapshot_identity="a3" * 32,
        selector="formal_paper_a_share_v1",
    )


def _environment(config: FormalPaperRuntimeConfig, *, verification: str, layout: str):
    return SimpleNamespace(
        config=config,
        verification_identity=verification,
        layout=SimpleNamespace(
            layout_identity=layout,
            root_identities=(
                ("runtime", "r0" * 32),
                ("broker", "br" * 32),
                ("evidence", "ev" * 32),
                ("anchor", "an" * 32),
                ("log", "lg" * 32),
            ),
        ),
        verified_at=NOW,
    )


def _broker_cap(*, env, policy, binding, account, layout_id: str):
    return VerifiedFormalPaperBrokerStoreCapability(
        schema_version="formal-paper-broker-store-capability-v1",
        classification="formal-paper-simulation",
        session_date=SESSION,
        runtime_environment_identity=env.verification_identity,
        runtime_config_identity=env.config.config_identity,
        runtime_layout_identity=layout_id,
        execution_policy_identity=policy.policy_identity,
        broker_binding_identity=binding.binding_identity,
        account_verification_identity=account.verification_identity,
        account_id=account.account_id,
        account_descriptor_identity=account.descriptor_identity,
        genesis_source_identity="gs" * 32,
        genesis_raw_sha256="gr" * 32,
        policy_descriptor_identity="pd" * 32,
        store_descriptor_identity=BROKER_DESC,
        gateway_identity="g" * 64,
        broker_root_identity="br" * 32,
        database_filename=env.config.broker_sqlite_filename,
        oms_separation_identity="os" * 32,
        capability_identity="k" * 64,
        verified_at=NOW,
        _store=_fake_store(),  # type: ignore[arg-type]
        _attestation=_StoreAttestation(b"unit-test"),
    )


def _execution_cap(*, env, policy, binding, account, broker):
    store = _fake_store(
        row=_open_row(
            barrier_epoch="e" * 64,
            oms_store_identity="o" * 64,
            gateway_identity=broker.gateway_identity,
            config_identity=env.config.config_identity,
            account_identity=account.descriptor_identity,
            broker_store_identity=BROKER_DESC,
            session_date=SESSION.isoformat(),
            lock_identity=LOCK_ID,
        )
    )
    return SimpleNamespace(
        store_identity="o" * 64,
        barrier_epoch="e" * 64,
        barrier_capability_identity="bc" * 32,
        gateway_identity=broker.gateway_identity,
        account_id=account.account_id,
        policy_descriptor_identity=broker.policy_descriptor_identity,
        environment=env,
        policy=policy,
        binding=binding,
        account=account,
        broker_store=broker,
        store=store,
        verified_at=NOW,
    )


def _cold_and_final(tmp_path: Path):
    config = _config(tmp_path)
    cold_env = _environment(config, verification="env-cold", layout="layout-cold")
    cold_policy = _policy(identity="policy-cold")
    cold_binding = _binding(
        identity="binding-cold", env_id="env-cold", policy_id="policy-cold"
    )
    cold_account = _account(
        verification="account-cold",
        env_id="env-cold",
        policy_id="policy-cold",
        binding_id="binding-cold",
    )
    final_env = _environment(config, verification="env-final", layout="layout-final")
    final_policy = _policy(identity="policy-final")
    final_binding = _binding(
        identity="binding-final", env_id="env-final", policy_id="policy-final"
    )
    final_account = _account(
        verification="account-final",
        env_id="env-final",
        policy_id="policy-final",
        binding_id="binding-final",
    )
    broker = _broker_cap(
        env=final_env,
        policy=final_policy,
        binding=final_binding,
        account=final_account,
        layout_id="layout-final",
    )
    execution = _execution_cap(
        env=final_env,
        policy=final_policy,
        binding=final_binding,
        account=final_account,
        broker=broker,
    )
    cold = bootstrap._FreshChain(cold_env, cold_policy, cold_binding, cold_account)
    final = bootstrap._FreshChain(final_env, final_policy, final_binding, final_account)
    return config, cold, final, broker, execution


def _patch_happy_path(monkeypatch, path, config, cold, final, broker, execution):
    monkeypatch.setattr(bootstrap, "_require_exact_config_path", lambda value: path)
    monkeypatch.setattr(bootstrap, "_load_formal_config", lambda value: config)
    monkeypatch.setattr(bootstrap, "_load_cold_chain", lambda **kwargs: cold)
    monkeypatch.setattr(bootstrap, "_require_absent_runtime_roots", lambda value: None)
    monkeypatch.setattr(
        bootstrap, "initialize_verified_formal_paper_broker_store", lambda **kwargs: broker
    )
    monkeypatch.setattr(bootstrap, "_reload_materialized_chain", lambda cold_chain, now: final)
    monkeypatch.setattr(
        bootstrap,
        "verify_existing_formal_paper_broker_store_capability",
        lambda **kwargs: broker,
    )
    monkeypatch.setattr(
        bootstrap,
        "initialize_verified_formal_paper_execution_store",
        lambda **kwargs: execution,
    )
    monkeypatch.setattr(
        bootstrap,
        "verify_existing_formal_paper_execution_store_capability",
        lambda **kwargs: execution,
    )


def test_path_subclass_purepath_and_relative_are_rejected(tmp_path: Path) -> None:
    absolute = (tmp_path / "runtime.toml").resolve()
    absolute.write_text("x\n", encoding="utf-8")

    class SubPath(type(Path())):  # type: ignore[misc,valid-type]
        pass

    for hostile in (
        SubPath(absolute),
        PurePosixPath(absolute.as_posix()),
        PureWindowsPath(str(absolute)),
        Path("relative.toml"),
        "not-a-path",
        None,
    ):
        with pytest.raises(bootstrap.FormalPaperBootstrapError) as caught:
            bootstrap.bootstrap_fresh_formal_paper_runtime(
                config_path=hostile,  # type: ignore[arg-type]
                session_date=SESSION,
                now=NOW,
            )
        _assert_bootstrap_error(caught.value, "PAPER_FORMAL_BOOTSTRAP_PATH_INVALID")


def test_config_symlink_leaf_is_rejected_without_patching_path_authority(
    tmp_path: Path,
) -> None:
    target = (tmp_path / "real-runtime.toml").resolve()
    target.write_text(
        'x = 1\n',
        encoding="utf-8",
        newline="\n",
    )
    link = tmp_path / "link-runtime.toml"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unsupported on this volume")
    concrete = type(Path())(link.resolve())
    # Use the symlink path object itself when concrete type matches.
    symlink_path = type(Path())(link)
    if not symlink_path.is_absolute():
        symlink_path = type(Path())(link.resolve())
    with pytest.raises(bootstrap.FormalPaperBootstrapError) as caught:
        bootstrap.bootstrap_fresh_formal_paper_runtime(
            config_path=symlink_path,
            session_date=SESSION,
            now=NOW,
        )
    assert caught.value.code in {
        "PAPER_FORMAL_BOOTSTRAP_PATH_INVALID",
        "PAPER_FORMAL_BOOTSTRAP_CONFIG_INVALID",
        "PAPER_FORMAL_BOOTSTRAP_ENVIRONMENT_INVALID",
    }
    del concrete


def test_existing_partial_nested_cross_parent_and_project_roots_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    path = type(Path())(config.source_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "_require_exact_config_path", lambda value: path)
    called = {"broker": 0}
    monkeypatch.setattr(
        bootstrap,
        "initialize_verified_formal_paper_broker_store",
        lambda **kwargs: called.__setitem__("broker", called["broker"] + 1),
    )

    config.broker_root.mkdir()
    monkeypatch.setattr(bootstrap, "_load_formal_config", lambda value: config)
    with pytest.raises(bootstrap.FormalPaperBootstrapError) as partial:
        bootstrap.bootstrap_fresh_formal_paper_runtime(
            config_path=path, session_date=SESSION, now=NOW
        )
    _assert_bootstrap_error(partial.value, "PAPER_FORMAL_BOOTSTRAP_ROOTS_NOT_ABSENT")
    assert called["broker"] == 0

    nested = replace(config, evidence_root=config.runtime_root / "nested")
    if nested.broker_root.exists():
        nested.broker_root.rmdir()
    monkeypatch.setattr(bootstrap, "_load_formal_config", lambda value: nested)
    with pytest.raises(bootstrap.FormalPaperBootstrapError) as nest:
        bootstrap.bootstrap_fresh_formal_paper_runtime(
            config_path=path, session_date=SESSION, now=NOW
        )
    _assert_bootstrap_error(nest.value, "PAPER_FORMAL_BOOTSTRAP_LAYOUT_INVALID")

    other = tmp_path / "other-parent"
    other.mkdir()
    cross = replace(_config(tmp_path / "cross"), log_root=other / "log")
    monkeypatch.setattr(bootstrap, "_load_formal_config", lambda value: cross)
    with pytest.raises(bootstrap.FormalPaperBootstrapError) as cross_err:
        bootstrap.bootstrap_fresh_formal_paper_runtime(
            config_path=path, session_date=SESSION, now=NOW
        )
    _assert_bootstrap_error(cross_err.value, "PAPER_FORMAL_BOOTSTRAP_LAYOUT_INVALID")


def test_fresh_bootstrap_public_sequence_and_field_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, cold, final, broker, execution = _cold_and_final(tmp_path)
    path = type(Path())(config.source_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")
    order: list[str] = []

    def _init_broker(**kwargs: object):
        order.append("broker")
        assert kwargs["environment"] is cold.environment
        return broker

    def _reload(cold_chain: object, now: object):
        order.append("reload")
        return final

    def _verify_broker(**kwargs: object):
        order.append("verify-broker")
        return broker

    def _init_oms(**kwargs: object):
        order.append("oms")
        assert kwargs["environment"] is final.environment
        assert kwargs["policy"] is final.policy
        return execution

    def _verify_oms(**kwargs: object):
        order.append("verify-oms")
        return execution

    monkeypatch.setattr(bootstrap, "_require_exact_config_path", lambda value: path)
    monkeypatch.setattr(bootstrap, "_load_formal_config", lambda value: config)
    monkeypatch.setattr(bootstrap, "_load_cold_chain", lambda **kwargs: cold)
    monkeypatch.setattr(bootstrap, "_require_absent_runtime_roots", lambda value: None)
    monkeypatch.setattr(
        bootstrap, "initialize_verified_formal_paper_broker_store", _init_broker
    )
    monkeypatch.setattr(bootstrap, "_reload_materialized_chain", _reload)
    monkeypatch.setattr(
        bootstrap, "verify_existing_formal_paper_broker_store_capability", _verify_broker
    )
    monkeypatch.setattr(
        bootstrap, "initialize_verified_formal_paper_execution_store", _init_oms
    )
    monkeypatch.setattr(
        bootstrap,
        "verify_existing_formal_paper_execution_store_capability",
        _verify_oms,
    )

    result = bootstrap.bootstrap_fresh_formal_paper_runtime(
        config_path=path, session_date=SESSION, now=NOW
    )
    assert order == [
        "broker",
        "reload",
        "verify-broker",
        "oms",
        "verify-broker",
        "verify-oms",
    ]
    assert result.execution_policy_identity == broker.execution_policy_identity
    assert result.runtime_environment_identity == broker.runtime_environment_identity
    assert result.broker_binding_identity == broker.broker_binding_identity
    assert result.account_verification_identity == broker.account_verification_identity
    assert result.config_identity == broker.runtime_config_identity
    assert result.session_date == broker.session_date
    assert result.gateway_identity == broker.gateway_identity
    assert result.barrier_lock_identity == LOCK_ID
    assert final.binding.cost_schedule_identity == final.policy.cost_schedule_identity
    assert cold.binding.cost_schedule_identity == cold.policy.cost_schedule_identity
    assert (
        cold.binding.cost_schedule_identity == final.binding.cost_schedule_identity
    )
    assert (
        result.binding.cost_schedule_identity == result.policy.cost_schedule_identity
    )
    assert (
        result.binding.cost_schedule_identity == cold.binding.cost_schedule_identity
    )
    assert (
        result.policy.cost_schedule_identity == cold.policy.cost_schedule_identity
    )


def test_forged_broker_chain_field_fork_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, cold, final, broker, execution = _cold_and_final(tmp_path)
    path = type(Path())(config.source_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")
    forked = replace(broker, execution_policy_identity="other" * 8)
    object.__setattr__(forked, "_store", broker.store)
    object.__setattr__(forked, "_attestation", broker._attestation)
    execution.broker_store = forked
    _patch_happy_path(monkeypatch, path, config, cold, final, forked, execution)
    with pytest.raises(bootstrap.FormalPaperBootstrapError) as caught:
        bootstrap.bootstrap_fresh_formal_paper_runtime(
            config_path=path, session_date=SESSION, now=NOW
        )
    _assert_bootstrap_error(caught.value, "PAPER_FORMAL_BOOTSTRAP_ROLLBACK_REQUIRED")


def test_reload_cold_policy_passthrough_rejects_before_oms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real STALE: materialized env + cold policy/binding/account must fail before OMS."""
    config, cold, final, broker, execution = _cold_and_final(tmp_path)
    path = type(Path())(config.source_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")
    poisoned = bootstrap._FreshChain(
        final.environment, cold.policy, cold.binding, cold.account
    )
    oms_calls = {"n": 0}

    monkeypatch.setattr(bootstrap, "_require_exact_config_path", lambda value: path)
    monkeypatch.setattr(bootstrap, "_load_formal_config", lambda value: config)
    monkeypatch.setattr(bootstrap, "_load_cold_chain", lambda **kwargs: cold)
    monkeypatch.setattr(bootstrap, "_require_absent_runtime_roots", lambda value: None)
    monkeypatch.setattr(
        bootstrap, "initialize_verified_formal_paper_broker_store", lambda **kwargs: broker
    )
    monkeypatch.setattr(
        bootstrap, "_reload_materialized_chain", lambda cold_chain, now: poisoned
    )
    monkeypatch.setattr(
        bootstrap,
        "verify_existing_formal_paper_broker_store_capability",
        lambda **kwargs: broker,
    )
    monkeypatch.setattr(
        bootstrap,
        "initialize_verified_formal_paper_execution_store",
        lambda **kwargs: oms_calls.__setitem__("n", oms_calls["n"] + 1) or execution,
    )
    with pytest.raises(bootstrap._Failure) as stale:
        bootstrap._require_materialized_left_cold(cold, poisoned)
    assert stale.value.code == "PAPER_FORMAL_BOOTSTRAP_STALE"
    with pytest.raises(bootstrap.FormalPaperBootstrapError) as caught:
        bootstrap.bootstrap_fresh_formal_paper_runtime(
            config_path=path, session_date=SESSION, now=NOW
        )
    _assert_bootstrap_error(caught.value, "PAPER_FORMAL_BOOTSTRAP_ROLLBACK_REQUIRED")
    # Underlying failure is STALE; broker bytes force manual cleanup elevation.
    assert oms_calls["n"] == 0


def test_economic_source_schedule_drift_rejects_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, cold, final, broker, execution = _cold_and_final(tmp_path)
    path = type(Path())(config.source_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")
    drifted_policy = _policy(identity="policy-final")
    drifted_policy.cost_schedule_identity = "drifted" * 8
    # Keep binding joined to drifted policy so economic stability (not join) fires.
    drifted_binding = _binding(
        identity="binding-final",
        env_id="env-final",
        policy_id="policy-final",
        cost_schedule_identity="drifted" * 8,
    )
    drifted = bootstrap._FreshChain(
        final.environment, drifted_policy, drifted_binding, final.account
    )
    drifted.account.execution_policy_identity = "policy-final"
    drifted.account.broker_binding_identity = "binding-final"
    oms = {"n": 0}
    writes = {"n": 0}
    monkeypatch.setattr(bootstrap, "_require_exact_config_path", lambda value: path)
    monkeypatch.setattr(bootstrap, "_load_formal_config", lambda value: config)
    monkeypatch.setattr(bootstrap, "_load_cold_chain", lambda **kwargs: cold)
    monkeypatch.setattr(bootstrap, "_require_absent_runtime_roots", lambda value: None)
    monkeypatch.setattr(
        bootstrap, "initialize_verified_formal_paper_broker_store", lambda **kwargs: broker
    )
    monkeypatch.setattr(
        bootstrap, "_reload_materialized_chain", lambda cold_chain, now: drifted
    )

    def _oms(**kwargs: object) -> object:
        oms["n"] += 1
        writes["n"] += 1
        return execution

    monkeypatch.setattr(
        bootstrap, "initialize_verified_formal_paper_execution_store", _oms
    )
    with pytest.raises(bootstrap.FormalPaperBootstrapError) as caught:
        bootstrap.bootstrap_fresh_formal_paper_runtime(
            config_path=path, session_date=SESSION, now=NOW
        )
    _assert_bootstrap_error(caught.value, "PAPER_FORMAL_BOOTSTRAP_ROLLBACK_REQUIRED")
    assert oms["n"] == 0
    assert writes["n"] == 0


def test_binding_cost_schedule_mismatch_vs_policy_rejects_before_oms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AE-R1: binding.cost_schedule_identity ≠ policy; join STALE; OMS=0 / zero writes."""
    config, cold, final, broker, execution = _cold_and_final(tmp_path)
    path = type(Path())(config.source_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")
    mismatched = _binding(
        identity="binding-final",
        env_id="env-final",
        policy_id="policy-final",
        cost_schedule_identity="evil" * 8,
    )
    poisoned = bootstrap._FreshChain(
        final.environment, final.policy, mismatched, final.account
    )
    oms = {"n": 0}
    writes = {"n": 0}
    monkeypatch.setattr(bootstrap, "_require_exact_config_path", lambda value: path)
    monkeypatch.setattr(bootstrap, "_load_formal_config", lambda value: config)
    monkeypatch.setattr(bootstrap, "_load_cold_chain", lambda **kwargs: cold)
    monkeypatch.setattr(bootstrap, "_require_absent_runtime_roots", lambda value: None)
    monkeypatch.setattr(
        bootstrap, "initialize_verified_formal_paper_broker_store", lambda **kwargs: broker
    )
    monkeypatch.setattr(
        bootstrap, "_reload_materialized_chain", lambda cold_chain, now: poisoned
    )

    def _oms(**kwargs: object) -> object:
        oms["n"] += 1
        writes["n"] += 1
        return execution

    monkeypatch.setattr(
        bootstrap, "initialize_verified_formal_paper_execution_store", _oms
    )
    with pytest.raises(bootstrap._Failure) as join:
        bootstrap._require_public_chain_join(poisoned)
    assert join.value.code == "PAPER_FORMAL_BOOTSTRAP_STALE"
    with pytest.raises(bootstrap.FormalPaperBootstrapError) as caught:
        bootstrap.bootstrap_fresh_formal_paper_runtime(
            config_path=path, session_date=SESSION, now=NOW
        )
    _assert_bootstrap_error(caught.value, "PAPER_FORMAL_BOOTSTRAP_ROLLBACK_REQUIRED")
    assert oms["n"] == 0
    assert writes["n"] == 0


def test_binding_cost_schedule_cold_current_drift_rejects_before_oms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cold→current binding cost_schedule drift with join intact; OMS=0 / zero writes."""
    config, cold, final, broker, execution = _cold_and_final(tmp_path)
    path = type(Path())(config.source_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")
    drifted_policy = _policy(identity="policy-final")
    drifted_policy.cost_schedule_identity = "drifted" * 8
    drifted_binding = _binding(
        identity="binding-final",
        env_id="env-final",
        policy_id="policy-final",
        cost_schedule_identity="drifted" * 8,
    )
    drifted = bootstrap._FreshChain(
        final.environment, drifted_policy, drifted_binding, final.account
    )
    drifted.account.execution_policy_identity = "policy-final"
    drifted.account.broker_binding_identity = "binding-final"
    assert drifted.binding.cost_schedule_identity == drifted.policy.cost_schedule_identity
    assert (
        cold.binding.cost_schedule_identity != drifted.binding.cost_schedule_identity
    )
    oms = {"n": 0}
    writes = {"n": 0}
    monkeypatch.setattr(bootstrap, "_require_exact_config_path", lambda value: path)
    monkeypatch.setattr(bootstrap, "_load_formal_config", lambda value: config)
    monkeypatch.setattr(bootstrap, "_load_cold_chain", lambda **kwargs: cold)
    monkeypatch.setattr(bootstrap, "_require_absent_runtime_roots", lambda value: None)
    monkeypatch.setattr(
        bootstrap, "initialize_verified_formal_paper_broker_store", lambda **kwargs: broker
    )
    monkeypatch.setattr(
        bootstrap, "_reload_materialized_chain", lambda cold_chain, now: drifted
    )

    def _oms(**kwargs: object) -> object:
        oms["n"] += 1
        writes["n"] += 1
        return execution

    monkeypatch.setattr(
        bootstrap, "initialize_verified_formal_paper_execution_store", _oms
    )
    with pytest.raises(bootstrap._Failure) as econ:
        bootstrap._require_economic_stability(cold, drifted)
    assert econ.value.code == "PAPER_FORMAL_BOOTSTRAP_STALE"
    with pytest.raises(bootstrap.FormalPaperBootstrapError) as caught:
        bootstrap.bootstrap_fresh_formal_paper_runtime(
            config_path=path, session_date=SESSION, now=NOW
        )
    _assert_bootstrap_error(caught.value, "PAPER_FORMAL_BOOTSTRAP_ROLLBACK_REQUIRED")
    assert oms["n"] == 0
    assert writes["n"] == 0


def test_oms_failure_after_broker_materialization_requires_manual_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, cold, final, broker, _execution = _cold_and_final(tmp_path)
    path = type(Path())(config.source_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")
    _patch_happy_path(monkeypatch, path, config, cold, final, broker, _execution)

    def _fail_oms(**kwargs: object) -> object:
        raise formal_oms.FormalPaperExecutionStoreError(
            "PAPER_FORMAL_EXECUTION_STORE_INVALID"
        )

    monkeypatch.setattr(
        bootstrap, "initialize_verified_formal_paper_execution_store", _fail_oms
    )
    with pytest.raises(bootstrap.FormalPaperBootstrapError) as caught:
        bootstrap.bootstrap_fresh_formal_paper_runtime(
            config_path=path, session_date=SESSION, now=NOW
        )
    _assert_bootstrap_error(caught.value, "PAPER_FORMAL_BOOTSTRAP_ROLLBACK_REQUIRED")


def test_toctou_broker_root_after_second_absent_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, cold, final, broker, execution = _cold_and_final(tmp_path)
    path = type(Path())(config.source_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")
    calls = {"absent": 0}

    def _absent(value: FormalPaperRuntimeConfig) -> None:
        calls["absent"] += 1
        if calls["absent"] >= 2:
            value.broker_root.mkdir(exist_ok=True)

    def _init_broker(**kwargs: object) -> object:
        if config.broker_root.exists():
            raise FormalPaperBrokerStoreError("PAPER_FORMAL_STORE_ALREADY_EXISTS")
        return broker

    monkeypatch.setattr(bootstrap, "_require_exact_config_path", lambda value: path)
    monkeypatch.setattr(bootstrap, "_load_formal_config", lambda value: config)
    monkeypatch.setattr(bootstrap, "_load_cold_chain", lambda **kwargs: cold)
    monkeypatch.setattr(bootstrap, "_require_absent_runtime_roots", _absent)
    monkeypatch.setattr(
        bootstrap, "initialize_verified_formal_paper_broker_store", _init_broker
    )
    with pytest.raises(bootstrap.FormalPaperBootstrapError) as caught:
        bootstrap.bootstrap_fresh_formal_paper_runtime(
            config_path=path, session_date=SESSION, now=NOW
        )
    _assert_bootstrap_error(caught.value, "PAPER_FORMAL_BOOTSTRAP_ROOTS_NOT_ABSENT")


@pytest.mark.parametrize(
    "field,value",
    [
        ("barrier_epoch", "1" * 64),
        ("session_date", "2099-01-01"),
        ("account_identity", "d" * 64),
        ("oms_store_identity", "1" * 64),
        ("broker_store_identity", "1" * 64),
        ("gateway_identity", "1" * 64),
        ("config_identity", "1" * 64),
        ("lock_identity", "1" * 64),
    ],
)
def test_open_barrier_wrong_identity_fields_reject_without_initializer(
    tmp_path: Path, field: str, value: str
) -> None:
    config, _cold, final, broker, execution = _cold_and_final(tmp_path)
    bad_row = _open_row(**{field: value})
    fake = _fake_store(row=bad_row)
    execution.store = fake
    object.__setattr__(broker, "_store", fake)
    with pytest.raises(bootstrap._Failure) as caught:
        bootstrap._require_open_barrier(  # type: ignore[arg-type]
            execution, expected_lock_identity=LOCK_ID
        )
    assert caught.value.code == "PAPER_FORMAL_BOOTSTRAP_BARRIER_STATE_INVALID"


def test_reopen_rejects_closing_and_closed_without_initializer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _cold, final, broker, execution = _cold_and_final(tmp_path)
    path = type(Path())(config.source_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")
    config.broker_root.mkdir()
    config.runtime_root.mkdir()
    inits = {"broker": 0, "oms": 0}

    monkeypatch.setattr(bootstrap, "_require_exact_config_path", lambda value: path)
    monkeypatch.setattr(bootstrap, "_load_formal_config", lambda value: config)
    monkeypatch.setattr(
        bootstrap, "_load_materialized_open_chain", lambda **kwargs: final
    )
    monkeypatch.setattr(
        bootstrap, "open_verified_formal_paper_broker_store", lambda **kwargs: broker
    )
    monkeypatch.setattr(
        bootstrap, "open_verified_formal_paper_execution_store", lambda **kwargs: execution
    )
    monkeypatch.setattr(
        bootstrap,
        "verify_existing_formal_paper_broker_store_capability",
        lambda **kwargs: broker,
    )
    monkeypatch.setattr(
        bootstrap,
        "verify_existing_formal_paper_execution_store_capability",
        lambda **kwargs: execution,
    )
    monkeypatch.setattr(
        bootstrap,
        "initialize_verified_formal_paper_broker_store",
        lambda **kwargs: inits.__setitem__("broker", inits["broker"] + 1),
    )
    monkeypatch.setattr(
        bootstrap,
        "initialize_verified_formal_paper_execution_store",
        lambda **kwargs: inits.__setitem__("oms", inits["oms"] + 1),
    )

    for state in ("CLOSING", "CLOSED"):
        fake = _fake_store(row=_open_row(state=state))
        execution.store = fake
        object.__setattr__(broker, "_store", fake)
        with pytest.raises(bootstrap.FormalPaperBootstrapError) as caught:
            bootstrap.reopen_verified_formal_paper_runtime(
                config_path=path, session_date=SESSION, now=NOW
            )
        _assert_bootstrap_error(
            caught.value, "PAPER_FORMAL_BOOTSTRAP_BARRIER_STATE_INVALID"
        )
    assert inits == {"broker": 0, "oms": 0}


def test_object_construction_pickle_and_replace_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, cold, final, broker, execution = _cold_and_final(tmp_path)
    path = type(Path())(config.source_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")
    _patch_happy_path(monkeypatch, path, config, cold, final, broker, execution)
    result = bootstrap.bootstrap_fresh_formal_paper_runtime(
        config_path=path, session_date=SESSION, now=NOW
    )
    with pytest.raises(TypeError):
        pickle.dumps(result)
    with pytest.raises(TypeError):
        copy.copy(result)
    forged = bootstrap.VerifiedFormalPaperRuntimeBootstrap(
        schema_version=result.schema_version,
        classification=result.classification,
        bootstrap_identity=result.bootstrap_identity,
        session_date=result.session_date,
        config_path=result.config_path,
        config_identity=result.config_identity,
        config_raw_sha256=result.config_raw_sha256,
        source_file_identity=result.source_file_identity,
        runtime_environment_identity=result.runtime_environment_identity,
        runtime_layout_identity=result.runtime_layout_identity,
        execution_policy_identity=result.execution_policy_identity,
        broker_binding_identity=result.broker_binding_identity,
        account_verification_identity=result.account_verification_identity,
        account_id=result.account_id,
        broker_capability_identity=result.broker_capability_identity,
        gateway_identity=result.gateway_identity,
        execution_store_identity=result.execution_store_identity,
        barrier_epoch=result.barrier_epoch,
        barrier_capability_identity=result.barrier_capability_identity,
        barrier_lock_identity=result.barrier_lock_identity,
        verified_at=result.verified_at,
        environment=result.environment,
        policy=result.policy,
        binding=result.binding,
        account=result.account,
        broker_store=result.broker_store,
        execution_store=result.execution_store,
        _attestation=bootstrap._Attestation(b"forged"),
    )
    with pytest.raises(bootstrap.FormalPaperBootstrapError) as caught:
        bootstrap.verify_existing_formal_paper_runtime_bootstrap(
            bootstrap=forged, now=NOW
        )
    _assert_bootstrap_error(caught.value, "PAPER_FORMAL_BOOTSTRAP_INVALID")


def test_public_verifier_wrong_type_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, cold, final, broker, execution = _cold_and_final(tmp_path)
    path = type(Path())(config.source_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")
    _patch_happy_path(monkeypatch, path, config, cold, final, broker, execution)
    monkeypatch.setattr(
        bootstrap,
        "verify_existing_formal_paper_broker_store_capability",
        lambda **kwargs: object(),
    )
    with pytest.raises(bootstrap.FormalPaperBootstrapError) as caught:
        bootstrap.bootstrap_fresh_formal_paper_runtime(
            config_path=path, session_date=SESSION, now=NOW
        )
    _assert_bootstrap_error(caught.value, "PAPER_FORMAL_BOOTSTRAP_ROLLBACK_REQUIRED")
