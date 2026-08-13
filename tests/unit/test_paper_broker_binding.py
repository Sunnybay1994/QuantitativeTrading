from __future__ import annotations

import builtins
import datetime as dt
import importlib
import inspect
import logging
import os
import pickle
import socket
import sqlite3
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from quant.domain.enums import Market
from quant.execution import paper_broker_binding as binding
from quant.execution import paper_policy as policy_module
from quant.execution import paper_runtime as runtime_module
from quant.execution.paper_broker_store import PaperBrokerPolicyDescriptor

NOW = dt.datetime(2026, 8, 9, 10, 0, tzinfo=dt.timezone.utc)


def _environment(
    *, config_identity: str = "b" * 64, verification_identity: str = "c" * 64
) -> runtime_module.VerifiedPaperRuntimeEnvironment:
    root = Path("formal-project").absolute()
    config = runtime_module.FormalPaperRuntimeConfig(
        source_path=root / "runtime.toml",
        source_file_identity="1" * 64,
        source_parent_identity="2" * 64,
        raw_sha256="3" * 64,
        schema_version="paper-runtime-config-v2",
        runtime_version="paper_runtime_v2",
        mode="PAPER_REAL_TIME",
        runtime_root=root / "runtime",
        broker_root=root / "broker",
        evidence_root=root / "evidence",
        anchor_root=root / "anchor",
        log_root=root / "log",
        project_root=root,
        oms_sqlite_filename="oms.sqlite3",
        broker_sqlite_filename="broker.sqlite3",
        account_selector="formal_account_v1",
        source_selector="formal_source_v1",
        policy_selector="paper_a_share_v1",
        expected_schedule_selector="formal_schedule_v1",
        config_identity=config_identity,
    )
    return runtime_module.VerifiedPaperRuntimeEnvironment(
        schema_version="paper-runtime-environment-v2",
        config=config,
        layout=object(),  # type: ignore[arg-type]
        platform=object(),  # type: ignore[arg-type]
        verified_at=NOW,
        verification_identity=verification_identity,
        _attestation=runtime_module._EnvironmentAttestation(b"delegated-verifier"),
    )


def _policy(
    *,
    session_date: dt.date = dt.date(2026, 8, 9),
    policy_identity: str = "d" * 64,
    fill_policy_version: str = "fill-v1",
) -> policy_module.VerifiedPaperExecutionPolicy:
    root = Path("formal-project").absolute()
    return policy_module.VerifiedPaperExecutionPolicy(
        schema_version="paper-execution-policy-v1",
        selector="paper_a_share_v1",
        session_date=session_date,
        source_path=root / "configs/trading/policies/paper_a_share_v1.toml",
        source_file_identity="4" * 64,
        source_parent_identity="5" * 64,
        raw_sha256="6" * 64,
        trading_config=object(),  # type: ignore[arg-type]
        trading_config_identity="7" * 64,
        supported_markets=(Market.SH, Market.SZ),
        execution_cost_schedule=object(),  # type: ignore[arg-type]
        cost_schedule_identity="8" * 64,
        minimum_order_notionals=(),
        a_share_rule_selector="a-share-v1",
        adapter_policy_version="adapter-v1",
        fill_policy_version=fill_policy_version,
        fault_policy_version="fault-v1",
        finality_policy_version="finality-v1",
        clock_policy_version="clock-v1",
        fx_snapshot_identity=None,
        policy_identity=policy_identity,
        verified_at=NOW,
        _attestation=policy_module._PolicyAttestation(b"delegated-verifier"),
    )


def _allow_fresh(
    monkeypatch: pytest.MonkeyPatch,
    expected_policy: policy_module.VerifiedPaperExecutionPolicy,
) -> None:
    monkeypatch.setattr(
        binding,
        "verify_existing_paper_runtime_preflight",
        lambda environment, *, config_path, now: None,
    )
    monkeypatch.setattr(
        binding,
        "verify_existing_paper_execution_policy",
        lambda *, policy, environment, now: expected_policy,
    )


def _assert_error(
    error: binding.FormalPaperBrokerPolicyBindingError, code: str
) -> None:
    assert str(error) == code
    assert repr(error) == f"FormalPaperBrokerPolicyBindingError({code!r})"
    assert error.__cause__ is None
    assert error.__context__ is None


def test_exact_fresh_binding_and_existing_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    policy = _policy()
    _allow_fresh(monkeypatch, policy)

    first = binding.bind_verified_formal_paper_broker_policy(
        environment=environment, policy=policy, now=NOW
    )
    second = binding.bind_verified_formal_paper_broker_policy(
        environment=environment, policy=policy, now=NOW
    )

    assert type(first) is binding.VerifiedFormalPaperBrokerPolicyBinding
    assert first == second
    assert first.schema_version == "formal-paper-broker-policy-binding-v1"
    assert first.classification == "formal-paper-simulation"
    assert first.session_date == dt.date(2026, 8, 9)
    assert first.runtime_environment_identity == "c" * 64
    assert first.runtime_config_identity == "b" * 64
    assert first.execution_policy_identity == "d" * 64
    assert first.fx_snapshot_identity is None
    assert len(first.binding_identity) == 64
    assert binding.verify_existing_formal_paper_broker_policy_binding(
        binding=first,
        environment=environment,
        policy=policy,
        now=NOW + dt.timedelta(hours=1),
    ) is first
    with pytest.raises(TypeError):
        pickle.dumps(first)


def test_development_and_forged_inputs_fail_before_verifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        binding,
        "verify_existing_paper_runtime_preflight",
        lambda *args, **kwargs: calls.append("runtime"),
    )
    monkeypatch.setattr(
        binding,
        "verify_existing_paper_execution_policy",
        lambda *args, **kwargs: calls.append("policy"),
    )
    development = object.__new__(runtime_module.DevelopmentPaperRuntimeEnvironment)
    with pytest.raises(binding.FormalPaperBrokerPolicyBindingError) as caught:
        binding.bind_verified_formal_paper_broker_policy(
            environment=development,  # type: ignore[arg-type]
            policy=_policy(),
            now=NOW,
        )
    _assert_error(caught.value, "PAPER_BROKER_BINDING_ENVIRONMENT_INVALID")

    descriptor = object.__new__(PaperBrokerPolicyDescriptor)
    with pytest.raises(binding.FormalPaperBrokerPolicyBindingError) as caught:
        binding.bind_verified_formal_paper_broker_policy(
            environment=_environment(),
            policy=descriptor,  # type: ignore[arg-type]
            now=NOW,
        )
    _assert_error(caught.value, "PAPER_BROKER_BINDING_POLICY_INVALID")
    assert calls == []


@pytest.mark.parametrize("hostile", [{}, object()])
def test_dict_duck_and_object_new_cannot_pass_existing(hostile: object) -> None:
    for candidate in (
        hostile,
        object.__new__(binding.VerifiedFormalPaperBrokerPolicyBinding),
    ):
        with pytest.raises(binding.FormalPaperBrokerPolicyBindingError) as caught:
            binding.verify_existing_formal_paper_broker_policy_binding(
                binding=candidate,  # type: ignore[arg-type]
                environment=_environment(),
                policy=_policy(),
                now=NOW,
            )
        _assert_error(caught.value, "PAPER_BROKER_BINDING_INVALID")


def test_subclass_clone_and_cross_capability_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    policy = _policy()
    _allow_fresh(monkeypatch, policy)
    verified = binding.bind_verified_formal_paper_broker_policy(
        environment=environment, policy=policy, now=NOW
    )

    class SubBinding(binding.VerifiedFormalPaperBrokerPolicyBinding):
        pass

    subclass = object.__new__(SubBinding)
    for field in inspect.get_annotations(
        binding.VerifiedFormalPaperBrokerPolicyBinding
    ):
        object.__setattr__(subclass, field, getattr(verified, field))
    object.__setattr__(subclass, "_attestation", verified._attestation)
    clone = replace(verified, execution_policy_identity="f" * 64)
    for candidate in (subclass, clone):
        with pytest.raises(binding.FormalPaperBrokerPolicyBindingError) as caught:
            binding.verify_existing_formal_paper_broker_policy_binding(
                binding=candidate,
                environment=environment,
                policy=policy,
                now=NOW,
            )
        _assert_error(caught.value, "PAPER_BROKER_BINDING_INVALID")

    other_environment = _environment(config_identity="9" * 64)
    with pytest.raises(binding.FormalPaperBrokerPolicyBindingError) as caught:
        binding.verify_existing_formal_paper_broker_policy_binding(
            binding=verified,
            environment=other_environment,
            policy=policy,
            now=NOW,
        )
    _assert_error(caught.value, "PAPER_BROKER_BINDING_STALE")


def test_policy_session_and_nested_version_drift_are_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    original = _policy()
    _allow_fresh(monkeypatch, original)
    verified = binding.bind_verified_formal_paper_broker_policy(
        environment=environment, policy=original, now=NOW
    )

    for drifted in (
        _policy(session_date=dt.date(2026, 8, 10)),
        _policy(fill_policy_version="fill-v2"),
    ):
        monkeypatch.setattr(
            binding,
            "verify_existing_paper_execution_policy",
            lambda *, policy, environment, now: drifted,
        )
        with pytest.raises(binding.FormalPaperBrokerPolicyBindingError) as caught:
            binding.verify_existing_formal_paper_broker_policy_binding(
                binding=verified,
                environment=environment,
                policy=drifted,
                now=NOW,
            )
        _assert_error(caught.value, "PAPER_BROKER_BINDING_STALE")


def test_policy_fresh_verifier_must_return_exact_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    requested = _policy()
    _allow_fresh(monkeypatch, _policy(policy_identity="e" * 64))
    with pytest.raises(binding.FormalPaperBrokerPolicyBindingError) as caught:
        binding.bind_verified_formal_paper_broker_policy(
            environment=environment, policy=requested, now=NOW
        )
    _assert_error(caught.value, "PAPER_BROKER_BINDING_POLICY_INVALID")


def test_now_is_explicit_aware_utc_and_not_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    policy = _policy()
    _allow_fresh(monkeypatch, policy)
    for timestamp in (
        NOW.replace(tzinfo=None),
        NOW.astimezone(dt.timezone(dt.timedelta(hours=8))),
        NOW - dt.timedelta(microseconds=1),
    ):
        with pytest.raises(binding.FormalPaperBrokerPolicyBindingError) as caught:
            binding.bind_verified_formal_paper_broker_policy(
                environment=environment, policy=policy, now=timestamp
            )
        _assert_error(caught.value, "PAPER_BROKER_BINDING_STALE")


def _hostile_exception() -> RuntimeError:
    marker = "TOKEN C:/private sqlite:///secret hostile-marker"
    outer = RuntimeError(marker)
    inner = ValueError(marker)
    outer.__cause__ = inner
    inner.__context__ = outer
    return outer


def test_hostile_verifier_exception_graphs_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    policy = _policy()

    def hostile(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise _hostile_exception()

    monkeypatch.setattr(binding, "verify_existing_paper_runtime_preflight", hostile)
    with pytest.raises(binding.FormalPaperBrokerPolicyBindingError) as caught:
        binding.bind_verified_formal_paper_broker_policy(
            environment=environment, policy=policy, now=NOW
        )
    _assert_error(caught.value, "PAPER_BROKER_BINDING_ENVIRONMENT_INVALID")
    assert "hostile" not in repr(caught.value)

    monkeypatch.setattr(
        binding,
        "verify_existing_paper_runtime_preflight",
        lambda environment, *, config_path, now: None,
    )
    monkeypatch.setattr(binding, "verify_existing_paper_execution_policy", hostile)
    with pytest.raises(binding.FormalPaperBrokerPolicyBindingError) as caught:
        binding.bind_verified_formal_paper_broker_policy(
            environment=environment, policy=policy, now=NOW
        )
    _assert_error(caught.value, "PAPER_BROKER_BINDING_POLICY_INVALID")


def test_binding_has_zero_io_db_log_socket_or_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    policy = _policy()
    _allow_fresh(monkeypatch, policy)

    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("forbidden side effect")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(logging.Logger, "_log", forbidden)
    monkeypatch.setattr(time, "time", forbidden)
    verified = binding.bind_verified_formal_paper_broker_policy(
        environment=environment, policy=policy, now=NOW
    )
    assert binding.verify_existing_formal_paper_broker_policy_binding(
        binding=verified,
        environment=environment,
        policy=policy,
        now=NOW,
    ) is verified


def test_public_surface_is_exact_and_has_no_generic_mint_or_key() -> None:
    assert binding.__all__ == [
        "FormalPaperBrokerPolicyBindingError",
        "VerifiedFormalPaperBrokerPolicyBinding",
        "bind_verified_formal_paper_broker_policy",
        "verify_existing_formal_paper_broker_policy_binding",
    ]
    namespace: dict[str, object] = {}
    exec("from quant.execution.paper_broker_binding import *", {}, namespace)
    assert {name for name in namespace if not name.startswith("_")} == set(
        binding.__all__
    )
    assert tuple(
        inspect.signature(binding.bind_verified_formal_paper_broker_policy).parameters
    ) == ("environment", "policy", "now")
    assert tuple(
        inspect.signature(
            binding.verify_existing_formal_paper_broker_policy_binding
        ).parameters
    ) == ("binding", "environment", "policy", "now")
    assert not hasattr(binding, "_create_binding_api")
    assert not hasattr(binding, "sign_binding")
    assert not hasattr(binding, "build_binding")
    assert not any(
        type(value) is bytes and len(value) == 32 for value in vars(binding).values()
    )
    with pytest.raises(TypeError):
        binding.bind_verified_formal_paper_broker_policy(
            environment=_environment(),
            policy=_policy(),
            now=NOW,
            classification="formal-paper-simulation",  # type: ignore[call-arg]
        )


def test_reload_invalidates_old_process_local_attestation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get("QUANT_PAPER_BINDING_RELOAD_CHILD") != "1":
        environment = os.environ.copy()
        environment["QUANT_PAPER_BINDING_RELOAD_CHILD"] = "1"
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                f"{Path(__file__).resolve()}::test_reload_invalidates_old_process_local_attestation",
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        return
    environment = _environment()
    policy = _policy()
    with monkeypatch.context() as scoped:
        _allow_fresh(scoped, policy)
        old = binding.bind_verified_formal_paper_broker_policy(
            environment=environment, policy=policy, now=NOW
        )
    importlib.reload(binding)
    with pytest.raises(binding.FormalPaperBrokerPolicyBindingError) as caught:
        binding.verify_existing_formal_paper_broker_policy_binding(
            binding=old,
            environment=environment,
            policy=policy,
            now=NOW,
        )
    _assert_error(caught.value, "PAPER_BROKER_BINDING_INVALID")


def test_cold_import_does_not_load_broker_db_soak_or_research_stacks() -> None:
    code = (
        "import sys; import quant.execution.paper_broker_binding; "
        "blocked=('quant.execution.paper_broker_store','quant.execution.soak',"
        "'sqlite3','qlib','lightgbm','mlflow'); "
        "assert not any(name in sys.modules for name in blocked); "
        "print('RUN0B2C_IMPORT_PASS')"
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "src"
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "RUN0B2C_IMPORT_PASS"
