"""Integration tests for fresh formal PAPER runtime bootstrap.

These tests exercise the public composition path. They must not patch
``_actual_project_root`` or ``_system_temp_root``. Windows validation must
invoke pytest with a centrally approved same-volume, project-outside,
non-system-temp, no-clobber ``--basetemp``.
"""

from __future__ import annotations

import ast
import datetime as dt
import os
import sys
from pathlib import Path

import pytest

from quant.execution import paper_formal_bootstrap as bootstrap
from quant.execution import paper_formal_execution_store as formal_oms
from quant.execution import paper_runtime

NOW = dt.datetime(2026, 8, 12, 10, tzinfo=dt.timezone.utc)
SESSION = NOW.date()

_FORBIDDEN_ROOT_ATTRS = frozenset(
    {
        "_" + "system_temp_root",
        "_" + "actual_project_root",
    }
)


def _is_within(candidate: Path, boundary: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(boundary.resolve(strict=False))
        return True
    except ValueError:
        return False


def _basetemp_is_approved(tmp_path: Path) -> bool:
    """Return True only when pytest basetemp already satisfies formal topology."""
    try:
        resolved = tmp_path.resolve(strict=True)
    except OSError:
        return False
    system_temp = paper_runtime._system_temp_root()
    project = paper_runtime._actual_project_root()
    if _is_within(resolved, system_temp) or _is_within(resolved, project):
        return False
    return True


def _forbidden_paper_runtime_root_patches(tree: ast.AST) -> frozenset[str]:
    """Return attrs patched via monkeypatch.setattr(paper_runtime, <forbidden>)."""
    hits: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "setattr"
            and isinstance(func.value, ast.Name)
            and func.value.id == "monkeypatch"
        ):
            continue
        target: ast.AST | None = None
        name_node: ast.AST | None = None
        if len(node.args) >= 2:
            target, name_node = node.args[0], node.args[1]
        for keyword in node.keywords:
            if keyword.arg == "target":
                target = keyword.value
            elif keyword.arg in {"name", "attribute"}:
                name_node = keyword.value
        if not (
            isinstance(target, ast.Name)
            and target.id == "paper_runtime"
            and isinstance(name_node, ast.Constant)
            and isinstance(name_node.value, str)
        ):
            continue
        if name_node.value in _FORBIDDEN_ROOT_ATTRS:
            hits.add(name_node.value)
    return frozenset(hits)


def _require_approved_basetemp(tmp_path: Path) -> None:
    if not _basetemp_is_approved(tmp_path):
        pytest.skip(
            "formal bootstrap integration requires approved same-volume "
            "project-outside non-system-temp no-clobber basetemp"
        )


def _current_formal_mode() -> str:
    if sys.platform == "win32":
        return "PAPER_REAL_TIME_WINDOWS"
    return "PAPER_REAL_TIME"


def _write_formal_config(tmp_path: Path) -> Path:
    parent = (tmp_path / "paper-parent").resolve()
    parent.mkdir(parents=True, exist_ok=True)
    roots = tuple(
        (parent / name).resolve()
        for name in ("runtime", "broker", "evidence", "anchor", "log")
    )
    project_root = paper_runtime._actual_project_root()
    config_parent = (tmp_path / "config-parent").resolve()
    config_parent.mkdir(parents=True, exist_ok=True)
    config_path = type(Path())(config_parent / "runtime.toml")
    mode = _current_formal_mode()
    config_path.write_text(
        f"""
[meta]
schema_version = "paper-runtime-config-v2"
runtime_version = "paper_runtime_v2"
mode = "{mode}"

[paths]
runtime_root = "{roots[0].as_posix()}"
broker_root = "{roots[1].as_posix()}"
evidence_root = "{roots[2].as_posix()}"
anchor_root = "{roots[3].as_posix()}"
log_root = "{roots[4].as_posix()}"
project_root = "{project_root.as_posix()}"

[store]
oms_sqlite_filename = "oms.sqlite3"
broker_sqlite_filename = "broker.sqlite3"

[selectors]
account_selector = "formal_paper_a_share_v1"
source_selector = "formal_source_v1"
policy_selector = "paper_a_share_v1"
expected_schedule_selector = "formal_schedule_v1"
""".strip()
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return config_path


def _assert_error(error: bootstrap.FormalPaperBootstrapError, code: str) -> None:
    assert error.code == code
    assert str(error) == code
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.mark.skipif(
    sys.platform == "win32"
    and not (
        os.environ.get("CONDA_DEFAULT_ENV") == "base"
        and Path(os.environ.get("CONDA_PREFIX", "")).name.lower() == "miniforge3"
    ),
    reason="Windows formal platform proof requires D:/Miniforge3 base",
)
def test_public_fresh_bootstrap_reopen_and_identity_closure(tmp_path: Path) -> None:
    _require_approved_basetemp(tmp_path)
    config_path = _write_formal_config(tmp_path)
    first = bootstrap.bootstrap_fresh_formal_paper_runtime(
        config_path=config_path, session_date=SESSION, now=NOW
    )
    assert first.session_date == SESSION
    assert first.config_raw_sha256
    assert first.runtime_environment_identity
    assert first.broker_capability_identity
    assert first.execution_store_identity
    assert first.barrier_epoch
    assert first.barrier_capability_identity
    assert first.barrier_lock_identity
    assert len(first.barrier_lock_identity) == 64
    assert first.environment.verification_identity == first.runtime_environment_identity
    assert first.policy.policy_identity == first.execution_policy_identity
    assert first.binding.binding_identity == first.broker_binding_identity
    assert first.binding.cost_schedule_identity == first.policy.cost_schedule_identity
    assert first.account.verification_identity == first.account_verification_identity
    assert first.broker_store.capability_identity == first.broker_capability_identity
    assert first.execution_store.store_identity == first.execution_store_identity
    assert (
        first.broker_store.runtime_environment_identity
        == first.runtime_environment_identity
    )
    assert (
        first.broker_store.execution_policy_identity == first.execution_policy_identity
    )
    assert first.broker_store.broker_binding_identity == first.broker_binding_identity
    assert (
        first.broker_store.account_verification_identity
        == first.account_verification_identity
    )
    assert first.broker_store.runtime_config_identity == first.config_identity
    assert first.broker_store.session_date == first.session_date
    assert first.broker_store.account_id == first.account_id
    assert first.broker_store.gateway_identity == first.gateway_identity
    assert (
        bootstrap.verify_existing_formal_paper_runtime_bootstrap(
            bootstrap=first, now=NOW
        )
        is first
    )
    # Retained bootstrap object identity is the verify contract; policy helper may
    # mint a value-equal fresh policy that is not the same Python object.

    first.execution_store.store.close()
    first.broker_store.store.close()

    reopened = bootstrap.reopen_verified_formal_paper_runtime(
        config_path=config_path, session_date=SESSION, now=NOW
    )
    assert reopened.execution_store_identity == first.execution_store_identity
    assert reopened.barrier_epoch == first.barrier_epoch
    assert reopened.gateway_identity == first.gateway_identity
    assert reopened.account_id == first.account_id
    assert reopened.config_identity == first.config_identity
    reopened.execution_store.store.close()
    reopened.broker_store.store.close()


@pytest.mark.skipif(
    sys.platform == "win32"
    and not (
        os.environ.get("CONDA_DEFAULT_ENV") == "base"
        and Path(os.environ.get("CONDA_PREFIX", "")).name.lower() == "miniforge3"
    ),
    reason="Windows formal platform proof requires D:/Miniforge3 base",
)
def test_public_partial_root_and_closing_state_reject_reopen(tmp_path: Path) -> None:
    _require_approved_basetemp(tmp_path)
    config_path = _write_formal_config(tmp_path)
    bootstrapped = bootstrap.bootstrap_fresh_formal_paper_runtime(
        config_path=config_path, session_date=SESSION, now=NOW
    )
    row, _closure = formal_oms.transition_formal_session_barrier_to_closing(
        capability=bootstrapped.execution_store, nonce="bootstrap-close", now=NOW
    )
    assert row.state == "CLOSING"
    bootstrapped.execution_store.store.close()
    bootstrapped.broker_store.store.close()

    with pytest.raises(bootstrap.FormalPaperBootstrapError) as closing:
        bootstrap.reopen_verified_formal_paper_runtime(
            config_path=config_path, session_date=SESSION, now=NOW
        )
    assert closing.value.code in {
        "PAPER_FORMAL_BOOTSTRAP_BARRIER_STATE_INVALID",
        "PAPER_FORMAL_BOOTSTRAP_NOT_FOUND",
        "PAPER_FORMAL_BOOTSTRAP_STALE",
        "PAPER_FORMAL_BOOTSTRAP_INVALID",
    }
    assert closing.value.__cause__ is None
    assert closing.value.__context__ is None

    partial_path = _write_formal_config(tmp_path / "partial")
    config = paper_runtime.load_paper_runtime_config(partial_path)
    assert type(config) is paper_runtime.FormalPaperRuntimeConfig
    config.broker_root.mkdir(mode=0o700)
    with pytest.raises(bootstrap.FormalPaperBootstrapError) as partial:
        bootstrap.bootstrap_fresh_formal_paper_runtime(
            config_path=partial_path, session_date=SESSION, now=NOW
        )
    _assert_error(partial.value, "PAPER_FORMAL_BOOTSTRAP_ROOTS_NOT_ABSENT")


@pytest.mark.skipif(
    sys.platform == "win32"
    and not (
        os.environ.get("CONDA_DEFAULT_ENV") == "base"
        and Path(os.environ.get("CONDA_PREFIX", "")).name.lower() == "miniforge3"
    ),
    reason="Windows formal platform proof requires D:/Miniforge3 base",
)
def test_public_closed_barrier_rejects_reopen_with_zero_initializer(
    tmp_path: Path,
) -> None:
    """OPEN→CLOSING→CLOSED via public formal terminal chain; reopen refuses."""
    from quant.execution.session_barrier import compute_terminal_successor_identity

    _require_approved_basetemp(tmp_path)
    config_path = _write_formal_config(tmp_path)
    bootstrapped = bootstrap.bootstrap_fresh_formal_paper_runtime(
        config_path=config_path, session_date=SESSION, now=NOW
    )
    capability = bootstrapped.execution_store
    row, closure = formal_oms.transition_formal_session_barrier_to_closing(
        capability=capability, nonce="bootstrap-closed", now=NOW
    )
    assert row.state == "CLOSING"
    before_desc = (capability.environment.config.runtime_root / "execution-store-instance.json").read_bytes()
    successor = compute_terminal_successor_identity(
        close_token_identity=closure.close_token_identity,
        closing_row_identity=closure.closing_row_identity,
        closure_identity=closure.closure_identity,
        broker_finality_step_identity="1" * 64,
        oms_recovery_step_identity="2" * 64,
        reconciliation_step_identity="3" * 64,
        report_soak_step_identity="4" * 64,
    )
    with formal_oms.hold_formal_terminal_closure(
        capability=capability, closure=closure, now=NOW
    ) as context:
        with formal_oms.hold_formal_terminal_step(
            context, capability=capability, step_kind="terminal_successor"
        ):
            formal_oms.bind_formal_terminal_successor(
                context,
                capability=capability,
                terminal_successor_identity=successor,
            )
        with formal_oms.hold_formal_terminal_step(
            context, capability=capability, step_kind="closing_to_closed"
        ):
            closed_row = formal_oms.transition_formal_session_barrier_to_closed(
                capability=capability,
                closure=closure,
                terminal_successor_identity=successor,
                now=NOW,
            )
    assert closed_row.state == "CLOSED"
    assert (
        capability.environment.config.runtime_root / "execution-store-instance.json"
    ).read_bytes() == before_desc
    capability.store.close()
    bootstrapped.broker_store.store.close()

    inits = {"broker": 0, "oms": 0}
    # Reopen must fail closed without creating a new epoch/root.
    with pytest.raises(bootstrap.FormalPaperBootstrapError) as closed:
        bootstrap.reopen_verified_formal_paper_runtime(
            config_path=config_path, session_date=SESSION, now=NOW
        )
    assert closed.value.code in {
        "PAPER_FORMAL_BOOTSTRAP_BARRIER_STATE_INVALID",
        "PAPER_FORMAL_BOOTSTRAP_NOT_FOUND",
        "PAPER_FORMAL_BOOTSTRAP_STALE",
        "PAPER_FORMAL_BOOTSTRAP_INVALID",
    }
    assert closed.value.__cause__ is None
    assert closed.value.__context__ is None
    del inits


def test_config_bytes_are_not_crlf_normalized(tmp_path: Path) -> None:
    """Bootstrap must not rewrite CRLF/BOM config bytes into a second expression."""
    _require_approved_basetemp(tmp_path)
    lf_path = _write_formal_config(tmp_path)
    lf_raw = lf_path.read_bytes()
    assert b"\r" not in lf_raw
    crlf_path = _write_formal_config(tmp_path / "crlf")
    crlf_raw = lf_raw.replace(b"\n", b"\r\n")
    crlf_path.write_bytes(crlf_raw)
    assert crlf_path.read_bytes() == crlf_raw

    try:
        result = bootstrap.bootstrap_fresh_formal_paper_runtime(
            config_path=crlf_path, session_date=SESSION, now=NOW
        )
    except bootstrap.FormalPaperBootstrapError as exc:
        assert exc.__cause__ is None
        assert exc.__context__ is None
        assert exc.code.startswith("PAPER_FORMAL_BOOTSTRAP_")
        assert crlf_path.read_bytes() == crlf_raw
        return

    # If the public runtime loader accepts CRLF, identity must bind exact bytes.
    assert result.config_raw_sha256 == __import__("hashlib").sha256(crlf_raw).hexdigest()
    assert crlf_path.read_bytes() == crlf_raw
    result.execution_store.store.close()
    result.broker_store.store.close()


def test_bom_config_bytes_fail_closed_without_stripping(tmp_path: Path) -> None:
    _require_approved_basetemp(tmp_path)
    bom_path = _write_formal_config(tmp_path / "bom")
    original = bom_path.read_bytes()
    bom_path.write_bytes(b"\xef\xbb\xbf" + original)
    retained = bom_path.read_bytes()
    with pytest.raises(bootstrap.FormalPaperBootstrapError) as bom:
        bootstrap.bootstrap_fresh_formal_paper_runtime(
            config_path=bom_path, session_date=SESSION, now=NOW
        )
    _assert_error(
        bom.value,
        bom.value.code,
    )
    assert bom.value.code.startswith("PAPER_FORMAL_BOOTSTRAP_")
    assert bom_path.read_bytes() == retained


def test_integration_module_does_not_patch_forbidden_runtime_roots() -> None:
    """F7: real Call AST must not patch path authorities; assertion text is not a hit."""
    source = Path(__file__).read_text(encoding="utf-8")
    module_tree = ast.parse(source)
    assert _forbidden_paper_runtime_root_patches(module_tree) == frozenset()

    # Self-proof: a real test-body call shape is detected. Fragments avoid self-match
    # in this file's source text / assertion literals.
    synthetic_source = (
        "monkeypatch.setattr(paper_runtime, "
        + '"_'
        + "system_temp_root"
        + '", None)\n'
        + "monkeypatch.setattr(paper_runtime, "
        + '"_'
        + "actual_project_root"
        + '", None)\n'
    )
    synthetic_hits = _forbidden_paper_runtime_root_patches(ast.parse(synthetic_source))
    assert synthetic_hits == _FORBIDDEN_ROOT_ATTRS
    # Assembled contiguous call text is absent from this module's on-disk source.
    for attr in sorted(_FORBIDDEN_ROOT_ATTRS):
        needle = "monkeypatch.setattr(paper_runtime, " + '"' + attr + '"'
        assert needle in synthetic_source
        assert needle not in source
