"""Integration tests for formal bootstrap operator CLI.

Exercise real public bootstrap/reopen through the CLI. Must not patch
``_actual_project_root`` or ``_system_temp_root``. Windows validation must use a
centrally approved same-volume, project-outside, non-system-temp, no-clobber
``--basetemp``.
"""

from __future__ import annotations

import ast
import datetime as dt
import gc
import json
import os
import sys
from pathlib import Path

import pytest

import quant.execution.paper_formal_bootstrap as bootstrap
import quant.execution.run_paper_formal_bootstrap as cli
from quant.domain.canonical_wire import canonical_json_bytes
from quant.execution import paper_formal_execution_store as formal_oms
from quant.execution import paper_runtime
from quant.execution.run_paper_formal_bootstrap import (
    EXIT_INPUT,
    EXIT_RUNTIME,
    EXIT_SUCCESS,
    main,
)

NOW = dt.datetime(2026, 8, 12, 10, tzinfo=dt.timezone.utc)
SESSION = "2026-08-12"
_SCHEMA = "m4-formal-bootstrap-operator-result-v1"
_INPUT = "PAPER_FORMAL_BOOTSTRAP_CLI_INPUT_INVALID"
_FORBIDDEN_ROOT_ATTRS = frozenset(
    {
        "_" + "system_temp_root",
        "_" + "actual_project_root",
    }
)

_RESULT_KEYS = {
    "schema_version",
    "mode",
    "session_date",
    "bootstrap_identity",
    "config_identity",
    "config_raw_sha256",
    "source_file_identity",
    "runtime_environment_identity",
    "runtime_layout_identity",
    "execution_policy_identity",
    "broker_binding_identity",
    "account_verification_identity",
    "broker_capability_identity",
    "gateway_identity",
    "execution_store_identity",
    "barrier_epoch",
    "barrier_capability_identity",
    "barrier_lock_identity",
}

# §13 exhaustive identity grouping (supersedes §12 "exclude only bootstrap_identity").
_TIME_BOUND_KEYS = frozenset(
    {
        "bootstrap_identity",
        "runtime_environment_identity",
        "execution_policy_identity",
        "broker_binding_identity",
        "account_verification_identity",
        "broker_capability_identity",
    }
)
_DURABLE_KEYS = frozenset(
    {
        "session_date",
        "config_identity",
        "config_raw_sha256",
        "source_file_identity",
        "runtime_layout_identity",
        "gateway_identity",
        "execution_store_identity",
        "barrier_epoch",
        "barrier_capability_identity",
        "barrier_lock_identity",
    }
)
_CONTROL_KEYS = frozenset({"schema_version", "mode"})
_HEX64 = frozenset("0123456789abcdef")

assert _TIME_BOUND_KEYS.isdisjoint(_DURABLE_KEYS)
assert _TIME_BOUND_KEYS.isdisjoint(_CONTROL_KEYS)
assert _DURABLE_KEYS.isdisjoint(_CONTROL_KEYS)
assert _TIME_BOUND_KEYS | _DURABLE_KEYS | _CONTROL_KEYS == frozenset(_RESULT_KEYS)
assert len(_TIME_BOUND_KEYS) == 6
assert len(_DURABLE_KEYS) == 10


def _is_within(candidate: Path, boundary: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(boundary.resolve(strict=False))
        return True
    except ValueError:
        return False


def _basetemp_is_approved(tmp_path: Path) -> bool:
    try:
        resolved = tmp_path.resolve(strict=True)
    except OSError:
        return False
    system_temp = paper_runtime._system_temp_root()
    project = paper_runtime._actual_project_root()
    if _is_within(resolved, system_temp) or _is_within(resolved, project):
        return False
    return True


def _require_approved_basetemp(tmp_path: Path) -> None:
    if not _basetemp_is_approved(tmp_path):
        pytest.skip(
            "formal bootstrap operator CLI integration requires approved "
            "same-volume project-outside non-system-temp no-clobber basetemp"
        )


def _forbidden_paper_runtime_root_patches(tree: ast.AST) -> frozenset[str]:
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


def _close_capability(capability: bootstrap.VerifiedFormalPaperRuntimeBootstrap) -> None:
    capability.execution_store.store.close()
    capability.broker_store.store.close()


def _assert_canonical_hex64(value: object) -> str:
    """TIME_BOUND identity fields must stay canonical lowercase 64-hex."""

    assert type(value) is str
    assert len(value) == 64
    assert value == value.lower()
    assert all(character in _HEX64 for character in value)
    return value


def _time_bound_from_payload(payload: dict[str, object]) -> dict[str, str]:
    assert set(payload) == _RESULT_KEYS
    result = {
        key: _assert_canonical_hex64(payload[key]) for key in sorted(_TIME_BOUND_KEYS)
    }
    return result


def _durable_from_payload(payload: dict[str, object]) -> dict[str, object]:
    assert set(payload) == _RESULT_KEYS
    return {key: payload[key] for key in sorted(_DURABLE_KEYS)}


def _time_bound_from_capability(
    capability: bootstrap.VerifiedFormalPaperRuntimeBootstrap,
) -> dict[str, str]:
    return {
        "account_verification_identity": _assert_canonical_hex64(
            capability.account_verification_identity
        ),
        "bootstrap_identity": _assert_canonical_hex64(capability.bootstrap_identity),
        "broker_binding_identity": _assert_canonical_hex64(
            capability.broker_binding_identity
        ),
        "broker_capability_identity": _assert_canonical_hex64(
            capability.broker_capability_identity
        ),
        "execution_policy_identity": _assert_canonical_hex64(
            capability.execution_policy_identity
        ),
        "runtime_environment_identity": _assert_canonical_hex64(
            capability.runtime_environment_identity
        ),
    }


def _durable_from_capability(
    capability: bootstrap.VerifiedFormalPaperRuntimeBootstrap,
) -> dict[str, object]:
    return {
        "barrier_capability_identity": capability.barrier_capability_identity,
        "barrier_epoch": capability.barrier_epoch,
        "barrier_lock_identity": capability.barrier_lock_identity,
        "config_identity": capability.config_identity,
        "config_raw_sha256": capability.config_raw_sha256,
        "execution_store_identity": capability.execution_store_identity,
        "gateway_identity": capability.gateway_identity,
        "runtime_layout_identity": capability.runtime_layout_identity,
        "session_date": capability.session_date.isoformat(),
        "source_file_identity": capability.source_file_identity,
    }


def _assert_operator_envelope(payload: dict[str, object], *, mode: str) -> None:
    assert set(payload) == _RESULT_KEYS
    assert payload["schema_version"] == _SCHEMA
    assert payload["mode"] == mode
    assert "account_id" not in payload
    assert "verified_at" not in payload
    assert "config_path" not in payload


def _assert_result_key_partition() -> None:
    assert _TIME_BOUND_KEYS.isdisjoint(_DURABLE_KEYS)
    assert _TIME_BOUND_KEYS.isdisjoint(_CONTROL_KEYS)
    assert _DURABLE_KEYS.isdisjoint(_CONTROL_KEYS)
    assert _TIME_BOUND_KEYS | _DURABLE_KEYS | _CONTROL_KEYS == frozenset(_RESULT_KEYS)
    assert len(_TIME_BOUND_KEYS) == 6
    assert len(_DURABLE_KEYS) == 10


_WIN_FORMAL = pytest.mark.skipif(
    sys.platform == "win32"
    and not (
        os.environ.get("CONDA_DEFAULT_ENV") == "base"
        and Path(os.environ.get("CONDA_PREFIX", "")).name.lower() == "miniforge3"
    ),
    reason="Windows formal platform proof requires D:/Miniforge3 base",
)


@_WIN_FORMAL
def test_cli_public_initialize_and_reopen_identity_projection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Real public fixture + CLI initialize/reopen with §13 identity grouping.

    TIME_BOUND exact6 are per-verification (verified_at in public identity chains).
    DURABLE exact10 stay equal across fresh reopen, including runtime_layout_identity.
    Same-call CLI↔capability full equality remains unit owned-capability responsibility.
    """

    _assert_result_key_partition()
    _require_approved_basetemp(tmp_path)
    config_path = _write_formal_config(tmp_path)

    code = main(
        [
            "--config",
            str(config_path),
            "--session-date",
            SESSION,
            "--initialize",
        ]
    )
    captured = capsys.readouterr()
    assert code == EXIT_SUCCESS
    assert captured.err == ""
    assert captured.out.endswith("\n")
    assert captured.out.count("\n") == 1
    payload = json.loads(captured.out)
    assert captured.out.encode("utf-8")[:-1] == canonical_json_bytes(payload)
    _assert_operator_envelope(payload, mode="initialize")
    time_bound_cli_init = _time_bound_from_payload(payload)
    durable_cli_init = _durable_from_payload(payload)
    assert durable_cli_init["session_date"] == SESSION
    assert str(config_path) not in captured.out
    assert str(tmp_path) not in captured.out
    assert "account_id" not in captured.out
    assert "verified_at" not in captured.out

    # Drop any process-local store refs retained only by the CLI stack frame.
    # Public reopen now must be >= CLI process UTC now used at initialize.
    gc.collect()
    after_cli = dt.datetime.now(dt.timezone.utc)
    capability = bootstrap.reopen_verified_formal_paper_runtime(
        config_path=config_path, session_date=NOW.date(), now=after_cli
    )
    verified = bootstrap.verify_existing_formal_paper_runtime_bootstrap(
        bootstrap=capability, now=after_cli
    )
    assert verified is capability
    time_bound_public_after_init = _time_bound_from_capability(capability)
    durable_public_after_init = _durable_from_capability(capability)
    assert durable_public_after_init == durable_cli_init
    _close_capability(capability)

    code = main(
        [
            "--config",
            str(config_path),
            "--session-date",
            SESSION,
            "--reopen",
        ]
    )
    reopen_out = capsys.readouterr()
    assert code == EXIT_SUCCESS
    assert reopen_out.err == ""
    reopen_payload = json.loads(reopen_out.out)
    assert reopen_out.out.encode("utf-8")[:-1] == canonical_json_bytes(reopen_payload)
    _assert_operator_envelope(reopen_payload, mode="reopen")
    time_bound_cli_reopen = _time_bound_from_payload(reopen_payload)
    durable_cli_reopen = _durable_from_payload(reopen_payload)
    assert durable_cli_reopen == durable_cli_init
    assert durable_cli_reopen["runtime_layout_identity"] == durable_cli_init[
        "runtime_layout_identity"
    ]
    assert durable_cli_reopen["barrier_epoch"] == durable_cli_init["barrier_epoch"]
    assert (
        durable_cli_reopen["execution_store_identity"]
        == durable_cli_init["execution_store_identity"]
    )
    assert str(config_path) not in reopen_out.out
    assert "verified_at" not in reopen_out.out
    gc.collect()
    after_reopen = dt.datetime.now(dt.timezone.utc)
    reopened = bootstrap.reopen_verified_formal_paper_runtime(
        config_path=config_path, session_date=NOW.date(), now=after_reopen
    )
    time_bound_public_after_reopen = _time_bound_from_capability(reopened)
    durable_public_after_reopen = _durable_from_capability(reopened)
    assert durable_public_after_reopen == durable_cli_init

    fresh_time_bound = (
        time_bound_cli_init,
        time_bound_public_after_init,
        time_bound_cli_reopen,
        time_bound_public_after_reopen,
    )
    for key in sorted(_TIME_BOUND_KEYS):
        values = tuple(sample[key] for sample in fresh_time_bound)
        assert all(type(item) is str and len(item) == 64 for item in values)
        assert len(set(values)) == 4

    _close_capability(reopened)


@_WIN_FORMAL
def test_cli_closing_bundle_rejects_reopen_fail_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _require_approved_basetemp(tmp_path)
    config_path = _write_formal_config(tmp_path)
    bootstrapped = bootstrap.bootstrap_fresh_formal_paper_runtime(
        config_path=config_path, session_date=NOW.date(), now=NOW
    )
    row, _closure = formal_oms.transition_formal_session_barrier_to_closing(
        capability=bootstrapped.execution_store, nonce="cli-close", now=NOW
    )
    assert row.state == "CLOSING"
    _close_capability(bootstrapped)

    code = main(
        [
            "--config",
            str(config_path),
            "--session-date",
            SESSION,
            "--reopen",
        ]
    )
    captured = capsys.readouterr()
    assert code == EXIT_RUNTIME
    assert captured.out == ""
    assert captured.err.endswith("\n")
    assert captured.err.count("\n") == 1
    assert captured.err.startswith("PAPER_FORMAL_BOOTSTRAP_")
    assert str(config_path) not in captured.err
    assert "usage" not in captured.err.lower()
    assert "Traceback" not in captured.err


@_WIN_FORMAL
def test_cli_partial_root_initialize_fail_closed_without_cli_cleanup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _require_approved_basetemp(tmp_path)
    config_path = _write_formal_config(tmp_path / "partial")
    config = paper_runtime.load_paper_runtime_config(config_path)
    assert type(config) is paper_runtime.FormalPaperRuntimeConfig
    config.broker_root.mkdir(mode=0o700)
    assert config.broker_root.is_dir()

    code = main(
        [
            "--config",
            str(config_path),
            "--session-date",
            SESSION,
            "--initialize",
        ]
    )
    captured = capsys.readouterr()
    assert code == EXIT_RUNTIME
    assert captured.out == ""
    assert captured.err == "PAPER_FORMAL_BOOTSTRAP_ROOTS_NOT_ABSENT\n"
    assert config.broker_root.is_dir()
    assert str(config.broker_root) not in captured.err
    assert str(config_path) not in captured.err


def test_cli_help_and_input_errors_do_not_touch_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.rglob("*"))
    assert main(["--help"]) == EXIT_SUCCESS
    assert main([]) == EXIT_INPUT
    after = set(tmp_path.rglob("*"))
    assert after == before
    err = capsys.readouterr()
    assert _INPUT in err.err or err.err == ""


def test_integration_module_does_not_patch_forbidden_runtime_roots() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    module_tree = ast.parse(source)
    assert _forbidden_paper_runtime_root_patches(module_tree) == frozenset()
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
    for attr in sorted(_FORBIDDEN_ROOT_ATTRS):
        needle = "monkeypatch.setattr(paper_runtime, " + '"' + attr + '"'
        assert needle in synthetic_source
        assert needle not in source


def test_cli_module_does_not_import_private_bootstrap_helpers() -> None:
    source = Path(cli.__file__).read_text(encoding="utf-8")
    forbidden = (
        "_load_formal_config",
        "_load_cold_chain",
        "_require_absent_runtime_roots",
        "initialize_verified_formal_paper_broker_store",
        "initialize_verified_formal_paper_execution_store",
        "shutil",
        "rmtree",
    )
    for name in forbidden:
        assert name not in source
