from __future__ import annotations

import builtins
import datetime as dt
import importlib
import inspect
import logging
import os
import pickle
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from quant.domain.enums import Currency, Market
from quant.execution import paper_account as account
from quant.execution import paper_broker_binding as binding
from quant.execution import paper_policy as policy_module
from quant.execution import paper_runtime as runtime_module
from quant.execution.paper_broker_store import (
    PaperBrokerPolicyDescriptor,
    build_paper_account_descriptor,
)

NOW = dt.datetime(2026, 8, 12, 10, 0, tzinfo=dt.timezone.utc)
FORMAL_ACCOUNT = (
    Path(__file__).resolve().parents[2]
    / "configs"
    / "trading"
    / "accounts"
    / "formal_paper_a_share_v1.toml"
)


def _environment(
    project_root: Path,
    *,
    account_selector: str = "formal_paper_a_share_v1",
    config_identity: str = "b" * 64,
    verification_identity: str = "c" * 64,
) -> runtime_module.VerifiedPaperRuntimeEnvironment:
    config = runtime_module.FormalPaperRuntimeConfig(
        source_path=project_root / "runtime.toml",
        source_file_identity="1" * 64,
        source_parent_identity="2" * 64,
        raw_sha256="3" * 64,
        schema_version="paper-runtime-config-v2",
        runtime_version="paper_runtime_v2",
        mode="PAPER_REAL_TIME",
        runtime_root=project_root / "absent-runtime",
        broker_root=project_root / "absent-broker",
        evidence_root=project_root / "absent-evidence",
        anchor_root=project_root / "absent-anchor",
        log_root=project_root / "absent-log",
        project_root=project_root,
        oms_sqlite_filename="oms.sqlite3",
        broker_sqlite_filename="broker.sqlite3",
        account_selector=account_selector,
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
    session_date: dt.date = dt.date(2026, 8, 12),
    policy_identity: str = "d" * 64,
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
        fill_policy_version="fill-v1",
        fault_policy_version="fault-v1",
        finality_policy_version="finality-v1",
        clock_policy_version="clock-v1",
        fx_snapshot_identity=None,
        policy_identity=policy_identity,
        verified_at=NOW,
        _attestation=policy_module._PolicyAttestation(b"delegated-verifier"),
    )


def _broker_binding(
    *,
    session_date: dt.date = dt.date(2026, 8, 12),
    binding_identity: str = "e" * 64,
) -> binding.VerifiedFormalPaperBrokerPolicyBinding:
    return binding.VerifiedFormalPaperBrokerPolicyBinding(
        schema_version="formal-paper-broker-policy-binding-v1",
        classification="formal-paper-simulation",
        session_date=session_date,
        runtime_environment_identity="c" * 64,
        runtime_config_identity="b" * 64,
        execution_policy_identity="d" * 64,
        adapter_policy_version="adapter-v1",
        fill_policy_version="fill-v1",
        fault_policy_version="fault-v1",
        finality_policy_version="finality-v1",
        clock_policy_version="clock-v1",
        cost_schedule_identity="8" * 64,
        fx_snapshot_identity=None,
        binding_identity=binding_identity,
        verified_at=NOW,
        _attestation=binding._BindingAttestation(b"delegated-verifier"),
    )


def _project(tmp_path: Path, raw: bytes | None = None) -> Path:
    root = tmp_path / "checkout"
    parent = root / "configs" / "trading" / "accounts"
    parent.mkdir(parents=True)
    (parent / "formal_paper_a_share_v1.toml").write_bytes(
        FORMAL_ACCOUNT.read_bytes() if raw is None else raw
    )
    return root


def _allow_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        account,
        "verify_existing_formal_paper_broker_policy_binding",
        lambda *, binding, environment, policy, now: binding,
    )


def _load(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    environment: runtime_module.VerifiedPaperRuntimeEnvironment | None = None,
    policy: policy_module.VerifiedPaperExecutionPolicy | None = None,
    broker_binding: binding.VerifiedFormalPaperBrokerPolicyBinding | None = None,
) -> account.VerifiedFormalPaperAccountDescriptor:
    _allow_fresh(monkeypatch)
    return account.load_verified_formal_paper_account_descriptor(
        environment=environment or _environment(root),
        policy=policy or _policy(),
        binding=broker_binding or _broker_binding(),
        now=NOW,
    )


def _assert_error(error: account.FormalPaperAccountError, code: str) -> None:
    assert str(error) == code
    assert repr(error) == f"FormalPaperAccountError({code!r})"
    assert error.__cause__ is None
    assert error.__context__ is None


def test_versioned_formal_account_source_bytes_match_canonical_renderer() -> None:
    raw = FORMAL_ACCOUNT.read_bytes()
    assert b"\r" not in raw
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.endswith(b"\n")
    assert not raw.endswith(b"\n\n")
    text = raw.decode("utf-8")
    document = tomllib.loads(text)
    assert text == account._render_canonical(document)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda raw: raw.replace(b"\n", b"\r\n"),
        lambda raw: b"\xef\xbb\xbf" + raw,
        lambda raw: raw + b"\n",
    ),
)
def test_crlf_bom_and_extra_newline_fail_closed_via_public_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[bytes], bytes],
) -> None:
    raw = mutate(FORMAL_ACCOUNT.read_bytes())
    root = _project(tmp_path, raw)
    with pytest.raises(account.FormalPaperAccountError) as caught:
        _load(root, monkeypatch)
    _assert_error(caught.value, "PAPER_ACCOUNT_SOURCE_INVALID")


def test_exact_fresh_load_and_existing_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    environment = _environment(root)
    policy = _policy()
    broker_binding = _broker_binding()
    first = _load(
        root,
        monkeypatch,
        environment=environment,
        policy=policy,
        broker_binding=broker_binding,
    )
    second = _load(
        root,
        monkeypatch,
        environment=environment,
        policy=policy,
        broker_binding=broker_binding,
    )

    assert type(first) is account.VerifiedFormalPaperAccountDescriptor
    assert first == second
    assert first.schema_version == "formal-paper-account-v1"
    assert first.classification == "formal-paper-simulation"
    assert first.selector == "formal_paper_a_share_v1"
    assert first.session_date == dt.date(2026, 8, 12)
    assert first.account_descriptor.account_label == "FORMAL_PAPER_A_SHARE"
    assert first.account_descriptor.base_currency is Currency.CNY
    assert first.account_descriptor.created_at == dt.datetime(
        2026, 8, 10, 0, 0, tzinfo=dt.timezone.utc
    )
    assert first.account_descriptor.initial_snapshot.cash[0].settled == Decimal(
        "500000.00"
    )
    assert first.risk_counter_scope == f"paper-{first.account_id}"
    assert len(first.account_id) == len(first.verification_identity) == 64
    assert first.account_id == first.account_descriptor.account_id
    assert (
        first.account_id
        != first.account_descriptor.initial_snapshot.snapshot_id
    )
    assert account.verify_existing_formal_paper_account_descriptor(
        capability=first,
        environment=environment,
        policy=policy,
        binding=broker_binding,
        now=NOW + dt.timedelta(hours=1),
    ) is first
    assert not any((root / name).exists() for name in ("absent-runtime", "absent-broker"))
    with pytest.raises(TypeError):
        pickle.dumps(first)


def test_stable_account_id_is_cross_platform_semantic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    verified = _load(root, monkeypatch)
    assert verified.account_id == verified.account_descriptor.account_id
    assert verified.account_id != verified.initial_snapshot_identity
    assert verified.source_file_identity != verified.account_id


@pytest.mark.parametrize(
    "selector",
    (
        "development_account_v1",
        "unknown_account_v1",
        "formal_paper.example",
        "../formal_paper_a_share_v1",
        "formal/paper_a_share_v1",
    ),
)
def test_non_allowlisted_selector_is_rejected_before_source_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selector: str,
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    _allow_fresh(monkeypatch)
    with pytest.raises(account.FormalPaperAccountError) as caught:
        account.load_verified_formal_paper_account_descriptor(
            environment=_environment(root, account_selector=selector),
            policy=_policy(),
            binding=_broker_binding(),
            now=NOW,
        )
    _assert_error(caught.value, "PAPER_ACCOUNT_SELECTOR_UNSUPPORTED")


def test_development_and_forged_inputs_fail_before_verifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        account,
        "verify_existing_formal_paper_broker_policy_binding",
        lambda *args, **kwargs: calls.append("binding"),
    )
    development = object.__new__(runtime_module.DevelopmentPaperRuntimeEnvironment)
    with pytest.raises(account.FormalPaperAccountError) as caught:
        account.load_verified_formal_paper_account_descriptor(
            environment=development,  # type: ignore[arg-type]
            policy=_policy(),
            binding=_broker_binding(),
            now=NOW,
        )
    _assert_error(caught.value, "PAPER_ACCOUNT_ENVIRONMENT_INVALID")

    descriptor = object.__new__(PaperBrokerPolicyDescriptor)
    with pytest.raises(account.FormalPaperAccountError) as caught:
        account.load_verified_formal_paper_account_descriptor(
            environment=_environment(Path("formal-project").absolute()),
            policy=descriptor,  # type: ignore[arg-type]
            binding=_broker_binding(),
            now=NOW,
        )
    _assert_error(caught.value, "PAPER_ACCOUNT_POLICY_BINDING_INVALID")
    assert calls == []


@pytest.mark.parametrize("hostile", [{}, object()])
def test_dict_duck_and_object_new_cannot_pass_existing(hostile: object) -> None:
    for candidate in (
        hostile,
        object.__new__(account.VerifiedFormalPaperAccountDescriptor),
    ):
        with pytest.raises(account.FormalPaperAccountError) as caught:
            account.verify_existing_formal_paper_account_descriptor(
                capability=candidate,  # type: ignore[arg-type]
                environment=_environment(Path("formal-project").absolute()),
                policy=_policy(),
                binding=_broker_binding(),
                now=NOW,
            )
        _assert_error(caught.value, "PAPER_ACCOUNT_INVALID")


def test_subclass_clone_and_cross_capability_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    environment = _environment(root)
    policy = _policy()
    broker_binding = _broker_binding()
    verified = _load(
        root,
        monkeypatch,
        environment=environment,
        policy=policy,
        broker_binding=broker_binding,
    )

    class SubAccount(account.VerifiedFormalPaperAccountDescriptor):
        pass

    subclass = object.__new__(SubAccount)
    for field in inspect.get_annotations(account.VerifiedFormalPaperAccountDescriptor):
        object.__setattr__(subclass, field, getattr(verified, field))
    object.__setattr__(subclass, "_attestation", verified._attestation)
    clone = replace(verified, account_id="f" * 64)
    for candidate in (subclass, clone):
        with pytest.raises(account.FormalPaperAccountError) as caught:
            account.verify_existing_formal_paper_account_descriptor(
                capability=candidate,
                environment=environment,
                policy=policy,
                binding=broker_binding,
                now=NOW,
            )
        _assert_error(caught.value, "PAPER_ACCOUNT_INVALID")

    other_environment = _environment(root, config_identity="9" * 64)
    with pytest.raises(account.FormalPaperAccountError) as caught:
        account.verify_existing_formal_paper_account_descriptor(
            capability=verified,
            environment=other_environment,
            policy=policy,
            binding=broker_binding,
            now=NOW,
        )
    _assert_error(caught.value, "PAPER_ACCOUNT_STALE")


@pytest.mark.parametrize(
    ("old", "new", "code"),
    (
        (
            b'account_label = "FORMAL_PAPER_A_SHARE"',
            b'account_label = "OTHER_LABEL"',
            "PAPER_ACCOUNT_SEMANTICS_INVALID",
        ),
        (
            b'settled_cny = "500000.00"',
            b'settled_cny = "1000000.00"',
            "PAPER_ACCOUNT_SEMANTICS_INVALID",
        ),
        (
            b'available_cny = "500000.00"',
            b'available_cny = "499999.99"',
            "PAPER_ACCOUNT_SEMANTICS_INVALID",
        ),
        (
            b'receivable_cny = "0.00"',
            b'receivable_cny = "1.00"',
            "PAPER_ACCOUNT_SEMANTICS_INVALID",
        ),
        (
            b'base_currency = "CNY"',
            b'base_currency = "HKD"',
            "PAPER_ACCOUNT_SEMANTICS_INVALID",
        ),
        (
            b'as_of = "2026-08-10T00:00:00Z"',
            b'as_of = "2026-08-11T00:00:00Z"',
            "PAPER_ACCOUNT_SEMANTICS_INVALID",
        ),
        (
            b'settled_cny = "500000.00"',
            b'settled_cny = 500000.00',
            "PAPER_ACCOUNT_SOURCE_INVALID",
        ),
        (
            b'settled_cny = "500000.00"',
            b'settled_cny = "0.00"',
            "PAPER_ACCOUNT_SEMANTICS_INVALID",
        ),
    ),
)
def test_noncanonical_and_semantic_drift_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    old: bytes,
    new: bytes,
    code: str,
) -> None:
    raw = FORMAL_ACCOUNT.read_bytes().replace(old, new, 1)
    root = _project(tmp_path, raw)
    with pytest.raises(account.FormalPaperAccountError) as caught:
        _load(root, monkeypatch)
    _assert_error(caught.value, code)


def test_unknown_duplicate_and_invalid_utf8_are_source_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads = (
        FORMAL_ACCOUNT.read_bytes().replace(
            b"[account]\n", b"[account]\nextra = \"x\"\n"
        ),
        FORMAL_ACCOUNT.read_bytes().replace(
            b'account_version = "formal_paper_a_share_v1"\n',
            b'account_version = "formal_paper_a_share_v1"\naccount_version = "dup"\n',
        ),
        b"\xff\xfe",
    )
    for index, raw in enumerate(payloads):
        root = _project(tmp_path / str(index), raw)
        with pytest.raises(account.FormalPaperAccountError) as caught:
            _load(root, monkeypatch)
        _assert_error(caught.value, "PAPER_ACCOUNT_SOURCE_INVALID")


def test_now_is_explicit_aware_utc_and_not_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    environment = _environment(root)
    policy = _policy()
    broker_binding = _broker_binding()
    _allow_fresh(monkeypatch)
    for timestamp in (
        NOW.replace(tzinfo=None),
        NOW.astimezone(dt.timezone(dt.timedelta(hours=8))),
        NOW - dt.timedelta(microseconds=1),
    ):
        with pytest.raises(account.FormalPaperAccountError) as caught:
            account.load_verified_formal_paper_account_descriptor(
                environment=environment,
                policy=policy,
                binding=broker_binding,
                now=timestamp,
            )
        _assert_error(caught.value, "PAPER_ACCOUNT_STALE")


def test_persistent_same_inode_drift_is_rejected_before_mint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    source = root / "configs" / "trading" / "accounts" / "formal_paper_a_share_v1.toml"

    def mutate(path: Path) -> None:
        assert path == source
        with path.open("ab") as stream:
            stream.write(b"\n")

    _allow_fresh(monkeypatch)
    monkeypatch.setattr(account, "_before_account_mint_hook", mutate)
    with pytest.raises(account.FormalPaperAccountError) as caught:
        account.load_verified_formal_paper_account_descriptor(
            environment=_environment(root),
            policy=_policy(),
            binding=_broker_binding(),
            now=NOW,
        )
    _assert_error(caught.value, "PAPER_ACCOUNT_SOURCE_INVALID")


def test_same_bytes_inode_replacement_stales_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    environment = _environment(root)
    policy = _policy()
    broker_binding = _broker_binding()
    verified = _load(
        root,
        monkeypatch,
        environment=environment,
        policy=policy,
        broker_binding=broker_binding,
    )
    source = verified.source_path
    replacement = source.with_suffix(".replacement")
    replacement.write_bytes(source.read_bytes())
    os.replace(replacement, source)
    with pytest.raises(account.FormalPaperAccountError) as caught:
        account.verify_existing_formal_paper_account_descriptor(
            capability=verified,
            environment=environment,
            policy=policy,
            binding=broker_binding,
            now=NOW,
        )
    _assert_error(caught.value, "PAPER_ACCOUNT_STALE")


def test_hardlink_account_is_rejected_where_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    source = root / "configs" / "trading" / "accounts" / "formal_paper_a_share_v1.toml"
    alias = source.with_suffix(".alias")
    try:
        os.link(source, alias)
    except OSError:
        pytest.skip("hard links unavailable")
    with pytest.raises(account.FormalPaperAccountError) as caught:
        _load(root, monkeypatch)
    _assert_error(caught.value, "PAPER_ACCOUNT_SOURCE_INVALID")


def test_symlink_account_is_rejected_where_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    source = root / "configs" / "trading" / "accounts" / "formal_paper_a_share_v1.toml"
    target = source.with_suffix(".real")
    shutil.move(source, target)
    try:
        source.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(account.FormalPaperAccountError) as caught:
        _load(root, monkeypatch)
    _assert_error(caught.value, "PAPER_ACCOUNT_SOURCE_INVALID")


@pytest.mark.parametrize(
    "target",
    [
        "account_id",
        "verification_identity",
        "risk_counter_scope",
        "account_descriptor",
    ],
)
def test_existing_rejects_whole_rehash_without_private_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    root = _project(tmp_path)
    environment = _environment(root)
    policy = _policy()
    broker_binding = _broker_binding()
    verified = _load(
        root,
        monkeypatch,
        environment=environment,
        policy=policy,
        broker_binding=broker_binding,
    )
    if target == "account_id":
        forged = replace(verified, account_id="f" * 64)
    elif target == "verification_identity":
        forged = replace(verified, verification_identity="f" * 64)
    elif target == "risk_counter_scope":
        forged = replace(verified, risk_counter_scope="paper-forged")
    else:
        forged = replace(verified, account_descriptor=object())  # type: ignore[arg-type]
    with pytest.raises(account.FormalPaperAccountError) as caught:
        account.verify_existing_formal_paper_account_descriptor(
            capability=forged,
            environment=environment,
            policy=policy,
            binding=broker_binding,
            now=NOW,
        )
    expected = "PAPER_ACCOUNT_STALE" if target == "account_descriptor" else "PAPER_ACCOUNT_INVALID"
    _assert_error(caught.value, expected)


def _hostile_exception() -> RuntimeError:
    marker = "TOKEN C:/private sqlite:///secret hostile-marker"
    outer = RuntimeError(marker)
    inner = ValueError(marker)
    outer.__cause__ = inner
    inner.__context__ = outer
    return outer


def test_hostile_binding_verifier_exception_graphs_are_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)

    def hostile(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise _hostile_exception()

    monkeypatch.setattr(
        account, "verify_existing_formal_paper_broker_policy_binding", hostile
    )
    with pytest.raises(account.FormalPaperAccountError) as caught:
        account.load_verified_formal_paper_account_descriptor(
            environment=_environment(root),
            policy=_policy(),
            binding=_broker_binding(),
            now=NOW,
        )
    _assert_error(caught.value, "PAPER_ACCOUNT_POLICY_BINDING_INVALID")
    assert "hostile" not in repr(caught.value)


def test_account_has_zero_io_db_log_socket_or_wall_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    environment = _environment(root)
    policy = _policy()
    broker_binding = _broker_binding()
    _allow_fresh(monkeypatch)

    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("forbidden side effect")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(logging.Logger, "_log", forbidden)
    monkeypatch.setattr(time, "time", forbidden)
    verified = account.load_verified_formal_paper_account_descriptor(
        environment=environment,
        policy=policy,
        binding=broker_binding,
        now=NOW,
    )
    assert account.verify_existing_formal_paper_account_descriptor(
        capability=verified,
        environment=environment,
        policy=policy,
        binding=broker_binding,
        now=NOW,
    ) is verified


def test_public_surface_is_exact_and_has_no_generic_mint_or_key() -> None:
    assert account.__all__ == [
        "FormalPaperAccountError",
        "VerifiedFormalPaperAccountDescriptor",
        "load_verified_formal_paper_account_descriptor",
        "verify_existing_formal_paper_account_descriptor",
    ]
    namespace: dict[str, object] = {}
    exec("from quant.execution.paper_account import *", {}, namespace)
    assert {name for name in namespace if not name.startswith("_")} == set(
        account.__all__
    )
    assert tuple(
        inspect.signature(
            account.load_verified_formal_paper_account_descriptor
        ).parameters
    ) == ("environment", "policy", "binding", "now")
    assert tuple(
        inspect.signature(
            account.verify_existing_formal_paper_account_descriptor
        ).parameters
    ) == ("capability", "environment", "policy", "binding", "now")
    assert not hasattr(account, "_create_account_api")
    assert not any(
        type(value) is bytes and len(value) == 32 for value in vars(account).values()
    )
    with pytest.raises(TypeError):
        account.load_verified_formal_paper_account_descriptor(
            environment=_environment(Path("formal-project").absolute()),
            policy=_policy(),
            binding=_broker_binding(),
            now=NOW,
            account_id="f" * 64,  # type: ignore[call-arg]
        )


def _collect_nested_functions(
    root: object,
    *,
    seen: set[int] | None = None,
) -> list[object]:
    if seen is None:
        seen = set()
    collected: list[object] = []
    stack = [root]
    while stack:
        current = stack.pop()
        if not inspect.isfunction(current):
            continue
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        collected.append(current)
        closure = getattr(current, "__closure__", None)
        if closure is None:
            continue
        for cell in closure:
            stack.append(cell.cell_contents)
    return collected


def _public_closure_roots() -> tuple[object, ...]:
    return (
        account.load_verified_formal_paper_account_descriptor,
        account.verify_existing_formal_paper_account_descriptor,
        account.VerifiedFormalPaperAccountDescriptor.__init__,
        account.VerifiedFormalPaperAccountDescriptor.__repr__,
        account.VerifiedFormalPaperAccountDescriptor.__reduce_ex__,
    )


def test_public_loader_closure_has_no_raw_mint_or_token() -> None:
    nested: list[object] = []
    for root in _public_closure_roots():
        nested.extend(_collect_nested_functions(root))
    names = {getattr(fn, "__name__", "") for fn in nested}
    assert "_mint" not in names
    assert "_token" not in names
    for fn in nested:
        name = getattr(fn, "__name__", "")
        if name.startswith("_"):
            continue
        try:
            signature = inspect.signature(cast(Callable[..., object], fn))
        except (TypeError, ValueError):
            continue
        parameter_names = tuple(signature.parameters)
        if parameter_names == ("payload",) and signature.return_annotation is bytes:
            pytest.fail(f"generic payload signer reachable: {name!r}")
        if {"environment", "policy", "binding", "anchored", "parsed"}.issubset(
            set(parameter_names)
        ):
            pytest.fail(f"raw mint callable reachable: {name!r}")


def test_r1_zero_b2c_closure_mint_attack_cannot_be_reproduced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    environment = _environment(root)
    policy = _policy()
    broker_binding = _broker_binding()
    b2c_calls: list[str] = []
    hook_calls: list[Path] = []

    def counting_b2c(
        *,
        binding: binding.VerifiedFormalPaperBrokerPolicyBinding,
        environment: runtime_module.VerifiedPaperRuntimeEnvironment,
        policy: policy_module.VerifiedPaperExecutionPolicy,
        now: dt.datetime,
    ) -> binding.VerifiedFormalPaperBrokerPolicyBinding:
        del environment, policy, now
        b2c_calls.append("binding")
        return binding

    def counting_hook(path: Path) -> None:
        hook_calls.append(path)

    monkeypatch.setattr(
        account,
        "verify_existing_formal_paper_broker_policy_binding",
        counting_b2c,
    )
    monkeypatch.setattr(account, "_before_account_mint_hook", counting_hook)

    loader_nested = _collect_nested_functions(
        account.load_verified_formal_paper_account_descriptor
    )
    mint_callables = [
        fn
        for fn in loader_nested
        if getattr(fn, "__name__", "") == "_mint"
    ]
    assert mint_callables == []

    token_callables = [
        fn
        for fn in loader_nested
        if getattr(fn, "__name__", "") == "_token"
    ]
    assert token_callables == []

    legit = account.load_verified_formal_paper_account_descriptor(
        environment=environment,
        policy=policy,
        binding=broker_binding,
        now=NOW,
    )
    assert len(b2c_calls) == 2
    assert len(hook_calls) == 1
    assert account.verify_existing_formal_paper_account_descriptor(
        capability=legit,
        environment=environment,
        policy=policy,
        binding=broker_binding,
        now=NOW + dt.timedelta(hours=1),
    ) is legit


def test_private_helper_assembly_cannot_mint_accepted_capability(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    environment = _environment(root)
    policy = _policy()
    broker_binding = _broker_binding()
    selector = account._require_formal_selector(environment.config.account_selector)
    source = (
        environment.config.project_root
        / "configs"
        / "trading"
        / "accounts"
        / f"{selector}.toml"
    )
    anchored = account._open_anchored_account(source, environment.config.project_root)
    try:
        parsed = account._parse_account(anchored.raw, selector)
        snapshot = account._build_snapshot(parsed)
        account.build_account_snapshot_identity(snapshot)
        account_descriptor = build_paper_account_descriptor(
            account_label=parsed.account_label,
            created_at=parsed.as_of,
            base_currency=parsed.base_currency,
            initial_snapshot=snapshot,
        )
        risk_counter_scope = f"paper-{account_descriptor.account_id}"
        identity_payload = account._identity_payload(
            environment=environment,
            policy=policy,
            binding=broker_binding,
            anchored=anchored,
            parsed=parsed,
            account_descriptor=account_descriptor,
            selector=selector,
            risk_counter_scope=risk_counter_scope,
            verified_at=NOW,
        )
        assembled = account.VerifiedFormalPaperAccountDescriptor(
            schema_version="formal-paper-account-v1",
            classification="formal-paper-simulation",
            session_date=broker_binding.session_date,
            selector=selector,
            source_path=anchored.source_path,
            source_file_identity=anchored.source_file_identity,
            source_parent_identity=anchored.source_parent_identity,
            raw_sha256=anchored.raw_sha256,
            runtime_environment_identity=environment.verification_identity,
            runtime_config_identity=environment.config.config_identity,
            execution_policy_identity=policy.policy_identity,
            broker_binding_identity=broker_binding.binding_identity,
            account_descriptor=account_descriptor,
            account_id=account_descriptor.account_id,
            initial_snapshot_identity=account_descriptor.initial_snapshot_identity,
            descriptor_identity=account_descriptor.descriptor_identity,
            risk_counter_scope=risk_counter_scope,
            verification_identity=account._sha256(identity_payload),
            verified_at=NOW,
            _attestation=account._AccountAttestation(b"assembled-without-load-path"),
        )
    finally:
        anchored.close()

    with pytest.raises(account.FormalPaperAccountError) as caught:
        account.verify_existing_formal_paper_account_descriptor(
            capability=assembled,
            environment=environment,
            policy=policy,
            binding=broker_binding,
            now=NOW,
        )
    _assert_error(caught.value, "PAPER_ACCOUNT_INVALID")


def test_reload_invalidates_old_process_local_attestation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.environ.get("QUANT_PAPER_ACCOUNT_RELOAD_CHILD") != "1":
        environment = os.environ.copy()
        environment["QUANT_PAPER_ACCOUNT_RELOAD_CHILD"] = "1"
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
                f"--basetemp={tmp_path / 'reload-child'}",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        return
    root = _project(tmp_path)
    environment = _environment(root)
    policy = _policy()
    broker_binding = _broker_binding()
    with monkeypatch.context() as scoped:
        _allow_fresh(scoped)
        old = account.load_verified_formal_paper_account_descriptor(
            environment=environment,
            policy=policy,
            binding=broker_binding,
            now=NOW,
        )
    importlib.reload(account)
    with pytest.raises(account.FormalPaperAccountError) as caught:
        account.verify_existing_formal_paper_account_descriptor(
            capability=old,
            environment=environment,
            policy=policy,
            binding=broker_binding,
            now=NOW,
        )
    _assert_error(caught.value, "PAPER_ACCOUNT_INVALID")


def test_cold_import_does_not_load_soak_or_research_stacks() -> None:
    code = (
        "import sys; import quant.execution.paper_account; "
        "blocked=('quant.execution.soak','qlib','lightgbm','mlflow'); "
        "assert not any(name in sys.modules for name in blocked); "
        "print('RUN0B2D_IMPORT_PASS')"
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
    assert completed.stdout.strip() == "RUN0B2D_IMPORT_PASS"


def test_binding_session_cross_environment_policy_drift_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    environment = _environment(root)
    policy = _policy()
    broker_binding = _broker_binding()
    verified = _load(
        root,
        monkeypatch,
        environment=environment,
        policy=policy,
        broker_binding=broker_binding,
    )
    drifted_binding = _broker_binding(session_date=dt.date(2026, 8, 13))
    _allow_fresh(monkeypatch)
    with pytest.raises(account.FormalPaperAccountError) as caught:
        account.verify_existing_formal_paper_account_descriptor(
            capability=verified,
            environment=environment,
            policy=policy,
            binding=drifted_binding,
            now=NOW,
        )
    _assert_error(caught.value, "PAPER_ACCOUNT_STALE")
