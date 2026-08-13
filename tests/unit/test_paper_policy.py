from __future__ import annotations

import datetime as dt
import inspect
import os
import pickle
import shutil
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from quant.domain.enums import Currency, Market
from quant.execution import paper_policy as policy
from quant.execution import paper_runtime as runtime

NOW = dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
FORMAL_POLICY = (
    Path(__file__).resolve().parents[2]
    / "configs"
    / "trading"
    / "policies"
    / "paper_a_share_v1.toml"
)


def _formal_environment(
    project_root: Path,
    *,
    selector: str = "paper_a_share_v1",
    oms_filename: str = "oms.sqlite3",
) -> runtime.VerifiedPaperRuntimeEnvironment:
    config = runtime.FormalPaperRuntimeConfig(
        source_path=project_root / "runtime.toml",
        source_file_identity="a" * 64,
        source_parent_identity="b" * 64,
        raw_sha256="c" * 64,
        schema_version="paper-runtime-config-v2",
        runtime_version="paper_runtime_v2",
        mode="PAPER_REAL_TIME",
        runtime_root=project_root / "absent-runtime",
        broker_root=project_root / "absent-broker",
        evidence_root=project_root / "absent-evidence",
        anchor_root=project_root / "absent-anchor",
        log_root=project_root / "absent-log",
        project_root=project_root,
        oms_sqlite_filename=oms_filename,
        broker_sqlite_filename="broker.sqlite3",
        account_selector="formal_account_v1",
        source_selector="formal_source_v1",
        policy_selector=selector,
        expected_schedule_selector="formal_schedule_v1",
        config_identity="d" * 64,
    )
    environment = object.__new__(runtime.VerifiedPaperRuntimeEnvironment)
    object.__setattr__(environment, "schema_version", "paper-runtime-environment-v2")
    object.__setattr__(environment, "config", config)
    object.__setattr__(environment, "verified_at", NOW)
    object.__setattr__(environment, "verification_identity", "e" * 64)
    return environment


def _project(tmp_path: Path, raw: bytes | None = None) -> Path:
    root = tmp_path / "checkout"
    parent = root / "configs" / "trading" / "policies"
    parent.mkdir(parents=True)
    (parent / "paper_a_share_v1.toml").write_bytes(
        FORMAL_POLICY.read_bytes() if raw is None else raw
    )
    return root


def _allow_formal_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(policy, "_fresh_verify_environment", lambda environment, now: None)


def _load(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    session_date: dt.date = dt.date(2026, 8, 9),
    environment: runtime.VerifiedPaperRuntimeEnvironment | None = None,
) -> policy.VerifiedPaperExecutionPolicy:
    _allow_formal_runtime(monkeypatch)
    return policy.load_verified_paper_execution_policy(
        environment=environment or _formal_environment(root),
        session_date=session_date,
        now=NOW,
    )


def _assert_sanitized(exc: policy.PaperExecutionPolicyError, code: str) -> None:
    assert str(exc) == code
    assert repr(exc) == f"PaperExecutionPolicyError({code!r})"
    assert exc.__cause__ is None
    assert exc.__context__ is None


@pytest.mark.parametrize("session_date", [dt.date(2026, 1, 1), dt.date(2026, 8, 9)])
def test_formal_contract_has_exact_a_share_policy_and_fresh_existing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    session_date: dt.date,
) -> None:
    root = _project(tmp_path)
    environment = _formal_environment(root)
    verified = _load(root, monkeypatch, session_date=session_date, environment=environment)

    assert type(verified) is policy.VerifiedPaperExecutionPolicy
    assert verified.schema_version == "paper-execution-policy-v1"
    assert verified.selector == "paper_a_share_v1"
    assert verified.supported_markets == (Market.SH, Market.SZ)
    assert tuple(item.market for item in verified.execution_cost_schedule.periods) == (
        Market.SH,
        Market.SZ,
    )
    assert all(
        item.settlement_currency is Currency.CNY
        for item in verified.execution_cost_schedule.periods
    )
    assert verified.minimum_order_notionals[0].currency is Currency.CNY
    assert verified.minimum_order_notionals[0].amount == Decimal("1.00")
    assert verified.fx_snapshot_identity is None
    assert len(verified.raw_sha256) == len(verified.policy_identity) == 64
    assert policy.verify_existing_paper_execution_policy(
        policy=verified,
        environment=environment,
        now=NOW,
    ) == verified
    assert not any((root / name).exists() for name in ("absent-runtime", "absent-broker"))


@pytest.mark.parametrize(
    "selector",
    (
        "unknown_policy_v1",
        "paper_a_share.example",
        "development_policy_v1",
        "../paper_a_share_v1",
        "paper/a_share_v1",
    ),
)
def test_non_allowlisted_or_path_selector_is_rejected_before_source_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selector: str,
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    _allow_formal_runtime(monkeypatch)
    with pytest.raises(policy.PaperExecutionPolicyError) as caught:
        policy.load_verified_paper_execution_policy(
            environment=_formal_environment(root, selector=selector),
            session_date=dt.date(2026, 8, 9),
            now=NOW,
        )
    _assert_sanitized(caught.value, "PAPER_POLICY_SELECTOR_UNSUPPORTED")


def test_development_and_forged_runtime_objects_are_rejected(tmp_path: Path) -> None:
    _project(tmp_path)
    with pytest.raises(policy.PaperExecutionPolicyError) as forged:
        policy.load_verified_paper_execution_policy(
            environment=object.__new__(runtime.VerifiedPaperRuntimeEnvironment),
            session_date=dt.date(2026, 8, 9),
            now=NOW,
        )
    _assert_sanitized(forged.value, "PAPER_POLICY_ENVIRONMENT_INVALID")

    development = object.__new__(runtime.DevelopmentPaperRuntimeEnvironment)
    with pytest.raises(policy.PaperExecutionPolicyError) as caught:
        policy.load_verified_paper_execution_policy(
            environment=development,  # type: ignore[arg-type]
            session_date=dt.date(2026, 8, 9),
            now=NOW,
        )
    _assert_sanitized(caught.value, "PAPER_POLICY_ENVIRONMENT_INVALID")


def test_public_runtime_attestation_is_freshly_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    environment = _formal_environment(root)

    def hostile(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("TOKEN C:/private sqlite:///secret hostile-marker")

    monkeypatch.setattr(policy, "verify_existing_paper_runtime_preflight", hostile)
    with pytest.raises(policy.PaperExecutionPolicyError) as caught:
        policy.load_verified_paper_execution_policy(
            environment=environment,
            session_date=dt.date(2026, 8, 9),
            now=NOW,
        )
    _assert_sanitized(caught.value, "PAPER_POLICY_ENVIRONMENT_INVALID")
    assert "hostile" not in repr(caught.value)


@pytest.mark.parametrize(
    ("old", "new", "code"),
    (
        (b'mode = "PAPER"', b'mode = "SHADOW"', "PAPER_POLICY_SEMANTICS_INVALID"),
        (
            b'sqlite_uri = "sqlite:///oms.sqlite3"',
            b'sqlite_uri = "sqlite:///other.sqlite3"',
            "PAPER_POLICY_SEMANTICS_INVALID",
        ),
        (
            b'minimum_order_notional_cny = "1.00"',
            b'minimum_order_notional_cny = 1.00',
            "PAPER_POLICY_SOURCE_INVALID",
        ),
        (
            b'supported_markets = ["SH", "SZ"]',
            b'supported_markets = ["SH"]',
            "PAPER_POLICY_SEMANTICS_INVALID",
        ),
        (
            b'market = "SZ"',
            b'market = "HK"',
            "PAPER_POLICY_SEMANTICS_INVALID",
        ),
        (
            b'max_symbol_weight = 0.10',
            b'max_symbol_weight = 0.1',
            "PAPER_POLICY_SOURCE_INVALID",
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
    raw = FORMAL_POLICY.read_bytes().replace(old, new, 1)
    root = _project(tmp_path, raw)
    with pytest.raises(policy.PaperExecutionPolicyError) as caught:
        _load(root, monkeypatch)
    _assert_sanitized(caught.value, code)


def test_unknown_duplicate_and_invalid_utf8_are_source_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads = (
        FORMAL_POLICY.read_bytes().replace(b"[selectors]\n", b"[selectors]\nextra = \"x\"\n"),
        FORMAL_POLICY.read_bytes().replace(
            b'policy_version = "paper_a_share_v1"\n',
            b'policy_version = "paper_a_share_v1"\npolicy_version = "duplicate"\n',
        ),
        b"\xff\xfe",
    )
    for index, raw in enumerate(payloads):
        root = _project(tmp_path / str(index), raw)
        with pytest.raises(policy.PaperExecutionPolicyError) as caught:
            _load(root, monkeypatch)
        _assert_sanitized(caught.value, "PAPER_POLICY_SOURCE_INVALID")


def test_session_and_now_boundaries_are_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    _allow_formal_runtime(monkeypatch)
    environment = _formal_environment(root)
    with pytest.raises(policy.PaperExecutionPolicyError) as early:
        policy.load_verified_paper_execution_policy(
            environment=environment,
            session_date=dt.date(2025, 12, 31),
            now=NOW,
        )
    _assert_sanitized(early.value, "PAPER_POLICY_SEMANTICS_INVALID")
    with pytest.raises(policy.PaperExecutionPolicyError) as stale:
        policy.load_verified_paper_execution_policy(
            environment=environment,
            session_date=dt.date(2026, 8, 9),
            now=NOW - dt.timedelta(microseconds=1),
        )
    _assert_sanitized(stale.value, "PAPER_POLICY_STALE")


def test_wrong_oms_filename_cannot_rebind_formal_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    with pytest.raises(policy.PaperExecutionPolicyError) as caught:
        _load(root, monkeypatch, environment=_formal_environment(root, oms_filename="other.db"))
    _assert_sanitized(caught.value, "PAPER_POLICY_SEMANTICS_INVALID")


def test_persistent_same_inode_drift_is_rejected_before_mint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    source = root / "configs" / "trading" / "policies" / "paper_a_share_v1.toml"

    def mutate(path: Path) -> None:
        assert path == source
        with path.open("ab") as stream:
            stream.write(b"\n")

    _allow_formal_runtime(monkeypatch)
    monkeypatch.setattr(policy, "_before_policy_mint_hook", mutate)
    with pytest.raises(policy.PaperExecutionPolicyError) as caught:
        policy.load_verified_paper_execution_policy(
            environment=_formal_environment(root),
            session_date=dt.date(2026, 8, 9),
            now=NOW,
        )
    _assert_sanitized(caught.value, "PAPER_POLICY_SOURCE_INVALID")


def test_same_bytes_inode_replacement_stales_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    environment = _formal_environment(root)
    verified = _load(root, monkeypatch, environment=environment)
    source = verified.source_path
    replacement = source.with_suffix(".replacement")
    replacement.write_bytes(source.read_bytes())
    os.replace(replacement, source)
    with pytest.raises(policy.PaperExecutionPolicyError) as caught:
        policy.verify_existing_paper_execution_policy(
            policy=verified,
            environment=environment,
            now=NOW,
        )
    _assert_sanitized(caught.value, "PAPER_POLICY_STALE")


def test_hardlink_policy_is_rejected_where_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    source = root / "configs" / "trading" / "policies" / "paper_a_share_v1.toml"
    alias = source.with_suffix(".alias")
    try:
        os.link(source, alias)
    except OSError:
        pytest.skip("hard links unavailable")
    with pytest.raises(policy.PaperExecutionPolicyError) as caught:
        _load(root, monkeypatch)
    _assert_sanitized(caught.value, "PAPER_POLICY_SOURCE_INVALID")


def test_symlink_policy_is_rejected_where_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    source = root / "configs" / "trading" / "policies" / "paper_a_share_v1.toml"
    target = source.with_suffix(".real")
    shutil.move(source, target)
    try:
        source.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(policy.PaperExecutionPolicyError) as caught:
        _load(root, monkeypatch)
    _assert_sanitized(caught.value, "PAPER_POLICY_SOURCE_INVALID")


@pytest.mark.parametrize(
    "target",
    [
        "trading_config_identity",
        "cost_schedule_identity",
        "trading_config",
        "execution_cost_schedule",
    ],
)
def test_existing_rejects_whole_rehash_without_private_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    root = _project(tmp_path)
    environment = _formal_environment(root)
    verified = _load(root, monkeypatch, environment=environment)
    if target == "trading_config_identity":
        forged = replace(verified, trading_config_identity="f" * 64)
    elif target == "cost_schedule_identity":
        forged = replace(verified, cost_schedule_identity="f" * 64)
    elif target == "trading_config":
        forged = replace(verified, trading_config=object())  # type: ignore[arg-type]
    else:
        forged = replace(
            verified,
            execution_cost_schedule=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(policy.PaperExecutionPolicyError) as caught:
        policy.verify_existing_paper_execution_policy(
            policy=forged,
            environment=environment,
            now=NOW,
        )
    _assert_sanitized(caught.value, "PAPER_POLICY_STALE")
    with pytest.raises(TypeError):
        pickle.dumps(verified)


def test_hostile_parser_and_builders_are_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    _allow_formal_runtime(monkeypatch)

    def hostile(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("TOKEN C:/private sqlite:///secret hostile-marker")

    for name in ("TradingConfig", "build_execution_cost_schedule"):
        with monkeypatch.context() as scoped:
            scoped.setattr(policy, "_fresh_verify_environment", lambda environment, now: None)
            scoped.setattr(policy, name, hostile)
            with pytest.raises(policy.PaperExecutionPolicyError) as caught:
                policy.load_verified_paper_execution_policy(
                    environment=_formal_environment(root),
                    session_date=dt.date(2026, 8, 9),
                    now=NOW,
                )
            _assert_sanitized(caught.value, "PAPER_POLICY_SEMANTICS_INVALID")
            assert "hostile" not in repr(caught.value)


def test_public_surface_has_one_mint_no_generic_signer_or_key() -> None:
    assert tuple(inspect.signature(policy.load_verified_paper_execution_policy).parameters) == (
        "environment",
        "session_date",
        "now",
    )
    assert tuple(inspect.signature(policy.verify_existing_paper_execution_policy).parameters) == (
        "policy",
        "environment",
        "now",
    )
    assert not hasattr(policy, "_create_policy_api")
    assert not hasattr(policy, "sign_policy")
    assert not hasattr(policy, "build_verified_policy")
    assert not any(type(value) is bytes and len(value) == 32 for value in vars(policy).values())
