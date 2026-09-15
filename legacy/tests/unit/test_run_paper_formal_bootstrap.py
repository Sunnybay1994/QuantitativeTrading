"""STATIC-authored unit tests for formal bootstrap operator CLI."""

from __future__ import annotations

import datetime as dt
import functools
import json
import os
import stat
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace

import pytest

import quant.execution.paper_formal_bootstrap as bootstrap_mod
import quant.execution.run_paper_formal_bootstrap as cli
from quant.domain.canonical_wire import canonical_json_bytes
from quant.execution.paper_formal_bootstrap import (
    FormalPaperBootstrapError,
    VerifiedFormalPaperRuntimeBootstrap,
)
from quant.execution.run_paper_formal_bootstrap import (
    EXIT_INPUT,
    EXIT_RUNTIME,
    EXIT_SUCCESS,
    main,
)

FIXED_NOW = dt.datetime(2026, 8, 12, 10, 0, 0, 123456, tzinfo=dt.timezone.utc)
SESSION = "2026-08-12"
_INPUT = "PAPER_FORMAL_BOOTSTRAP_CLI_INPUT_INVALID"
_RUNTIME = "PAPER_FORMAL_BOOTSTRAP_CLI_RUNTIME_FAILED"
_SCHEMA = "m4-formal-bootstrap-operator-result-v1"

_RESULT_KEYS = (
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
)


def _fake_verified(**overrides: object) -> SimpleNamespace:
    payload = {
        "schema_version": "formal-paper-runtime-bootstrap-v1",
        "classification": "formal-paper-simulation",
        "bootstrap_identity": "b" * 64,
        "session_date": dt.date(2026, 8, 12),
        "config_path": Path("/secret/config.toml"),
        "config_identity": "c" * 64,
        "config_raw_sha256": "d" * 64,
        "source_file_identity": "e" * 64,
        "runtime_environment_identity": "f" * 64,
        "runtime_layout_identity": "1" * 64,
        "execution_policy_identity": "2" * 64,
        "broker_binding_identity": "3" * 64,
        "account_verification_identity": "4" * 64,
        "account_id": "acct-must-not-leak",
        "broker_capability_identity": "5" * 64,
        "gateway_identity": "6" * 64,
        "execution_store_identity": "7" * 64,
        "barrier_epoch": "8" * 64,
        "barrier_capability_identity": "9" * 64,
        "barrier_lock_identity": "0" * 64,
        "verified_at": FIXED_NOW,
        "token": b"raw-token-must-not-leak",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _write_config(tmp_path: Path) -> Path:
    parent = (tmp_path / "cfg").resolve()
    parent.mkdir(parents=True, exist_ok=True)
    path = type(Path())(parent / "runtime.toml")
    path.write_text("[meta]\n", encoding="utf-8", newline="\n")
    return path


def _argv(config: Path, *, mode: str, session: str = SESSION) -> list[str]:
    return [
        "--config",
        str(config),
        "--session-date",
        session,
        f"--{mode}",
    ]


def _install_owned_seam(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bootstrap_fn: object | None = None,
    reopen_fn: object | None = None,
    verify_fn: object | None = None,
) -> dict[str, list[dict[str, object]]]:
    """Unit seam: replace owned-api resolver after authenticity gate is bypassed."""

    calls: dict[str, list[dict[str, object]]] = {
        "bootstrap": [],
        "reopen": [],
        "verify": [],
    }
    capability = _fake_verified()

    def default_bootstrap(**kwargs: object) -> object:
        calls["bootstrap"].append(kwargs)
        kwargs["__result__"] = capability
        return capability

    def default_reopen(**kwargs: object) -> object:
        calls["reopen"].append(kwargs)
        kwargs["__result__"] = capability
        return capability

    def default_verify(**kwargs: object) -> object:
        calls["verify"].append(kwargs)
        return kwargs["bootstrap"]

    resolved_bootstrap = bootstrap_fn if bootstrap_fn is not None else default_bootstrap
    resolved_reopen = reopen_fn if reopen_fn is not None else default_reopen
    resolved_verify = verify_fn if verify_fn is not None else default_verify

    monkeypatch.setattr(
        cli,
        "_require_owned_api",
        lambda: (resolved_bootstrap, resolved_reopen, resolved_verify),
    )
    monkeypatch.setattr(cli, "_canonical_utc_now", lambda: FIXED_NOW)
    # Force projection type gate to accept the SimpleNamespace stand-in.
    monkeypatch.setattr(
        cli,
        "VerifiedFormalPaperRuntimeBootstrap",
        SimpleNamespace,
    )
    return calls


def test_help_is_zero_business_io(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = tmp_path / "must-not-touch"
    boom_calls: list[str] = []

    def boom() -> None:
        boom_calls.append("owned")
        raise AssertionError("owned api must not run on --help")

    monkeypatch.setattr(cli, "_require_owned_api", boom)
    code = main(["--help"])
    captured = capsys.readouterr()
    assert code == EXIT_SUCCESS
    assert boom_calls == []
    assert captured.err == ""
    assert "usage" in captured.out.lower() or "config" in captured.out.lower()
    assert not sentinel.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--initialize"],
        ["--config", "x", "--initialize"],
        ["--session-date", SESSION, "--initialize"],
        ["--config", "x", "--session-date", SESSION],
        ["--config", "x", "--session-date", SESSION, "--initialize", "--reopen"],
        ["--config", "x", "--session-date", SESSION, "--initialize", "extra"],
        ["--config", "x", "--session-date", SESSION, "--initialize", "--now", "x"],
        ["--config", "x", "--session-date", SESSION, "--root", "/tmp", "--initialize"],
    ],
)
def test_argv_shape_failures_are_stable_input(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(argv)
    captured = capsys.readouterr()
    assert code == EXIT_INPUT
    assert captured.out == ""
    assert captured.err == f"{_INPUT}\n"
    assert "usage" not in captured.err.lower()
    assert ":" not in captured.err
    assert "\\" not in captured.err
    assert "/" not in captured.err.replace(_INPUT, "")


def test_relative_config_is_input_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    relative = Path("runtime.toml")
    relative.write_text("[meta]\n", encoding="utf-8")
    _install_owned_seam(monkeypatch)
    code = main(_argv(relative, mode="initialize"))
    captured = capsys.readouterr()
    assert code == EXIT_INPUT
    assert captured.out == ""
    assert captured.err == f"{_INPUT}\n"
    assert "runtime.toml" not in captured.err


@pytest.mark.parametrize(
    "factory",
    [
        lambda p: PurePosixPath(p.as_posix()),
        lambda p: PureWindowsPath(str(p)),
        lambda p: type("SubPath", (Path,), {})(p),
    ],
)
def test_purepath_and_subclass_config_rejected(factory: object, tmp_path: Path) -> None:
    real = _write_config(tmp_path)
    bad = factory(real)  # type: ignore[operator]
    with pytest.raises(cli._InputError):
        cli._require_exact_config_path(bad)


def test_missing_and_directory_config_are_input_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_owned_seam(monkeypatch)
    missing = (tmp_path / "missing.toml").resolve()
    code = main(_argv(missing, mode="initialize"))
    err = capsys.readouterr()
    assert code == EXIT_INPUT
    assert err.out == ""
    assert err.err == f"{_INPUT}\n"
    assert str(missing) not in err.err

    directory = (tmp_path / "dir").resolve()
    directory.mkdir()
    code = main(_argv(directory, mode="initialize"))
    err = capsys.readouterr()
    assert code == EXIT_INPUT
    assert err.out == ""
    assert err.err == f"{_INPUT}\n"
    assert str(directory) not in err.err


def test_symlink_or_reparse_config_is_input_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real = _write_config(tmp_path)
    link = tmp_path / "linked.toml"
    created = False
    try:
        link.symlink_to(real)
        created = link.is_symlink()
    except OSError:
        created = False

    _install_owned_seam(monkeypatch)
    if created:
        target = type(Path())(link.absolute())
    else:
        target = real
        real_lstat = cli.os.lstat

        def marked_lstat(path: object, *args: object, **kwargs: object) -> os.stat_result:
            info = real_lstat(path, *args, **kwargs)
            if os.path.normcase(os.fspath(path)) != os.path.normcase(os.fspath(target)):
                return info
            values = list(info)
            # Windows: stat.S_IFMT is a function, not a bitmask. Compose symlink
            # file-type bits with the original permission bits only.
            values[0] = stat.S_IFLNK | stat.S_IMODE(info.st_mode)
            return os.stat_result(values)

        monkeypatch.setattr(cli.os, "lstat", marked_lstat)

    code = main(_argv(target, mode="initialize"))
    captured = capsys.readouterr()
    assert code == EXIT_INPUT
    assert captured.out == ""
    assert captured.err == f"{_INPUT}\n"
    assert str(target) not in captured.err


@pytest.mark.parametrize(
    "session",
    [
        "2026/08/12",
        "2026-8-12",
        "2026-08-12T10:00:00",
        "2026-08-12T10:00:00Z",
        " 2026-08-12",
        "2026-08-12 ",
        "2026-02-30",
        "not-a-date",
        "",
    ],
)
def test_non_canonical_session_date_is_input_invalid(
    session: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _write_config(tmp_path)
    _install_owned_seam(monkeypatch)
    code = main(_argv(config, mode="initialize", session=session))
    captured = capsys.readouterr()
    assert code == EXIT_INPUT
    assert captured.out == ""
    assert captured.err == f"{_INPUT}\n"
    assert session.strip() == "" or session not in captured.err or session == _INPUT


def test_initialize_and_reopen_call_order_same_now_and_fresh_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)
    calls = _install_owned_seam(monkeypatch)

    code = main(_argv(config, mode="initialize"))
    out = capsys.readouterr()
    assert code == EXIT_SUCCESS
    assert out.err == ""
    assert len(calls["bootstrap"]) == 1
    assert calls["reopen"] == []
    assert len(calls["verify"]) == 1
    assert calls["bootstrap"][0]["now"] is FIXED_NOW
    assert calls["verify"][0]["now"] is FIXED_NOW
    assert calls["bootstrap"][0]["session_date"] == dt.date(2026, 8, 12)
    assert calls["bootstrap"][0]["config_path"] == config
    # Fresh verifier must receive the exact capability object from initialize.
    assert calls["verify"][0]["bootstrap"] is calls["bootstrap"][0]["__result__"]

    calls["bootstrap"].clear()
    calls["verify"].clear()
    code = main(_argv(config, mode="reopen"))
    out = capsys.readouterr()
    assert code == EXIT_SUCCESS
    assert calls["bootstrap"] == []
    assert len(calls["reopen"]) == 1
    assert len(calls["verify"]) == 1
    assert calls["reopen"][0]["now"] is FIXED_NOW
    assert calls["verify"][0]["now"] is FIXED_NOW
    assert calls["verify"][0]["bootstrap"] is calls["reopen"][0]["__result__"]


def test_fresh_equal_but_not_identical_is_runtime_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)
    first = _fake_verified(bootstrap_identity="a" * 64)
    second = _fake_verified(bootstrap_identity="a" * 64)

    def bootstrap(**_kwargs: object) -> object:
        return first

    def verify(**_kwargs: object) -> object:
        return second

    _install_owned_seam(
        monkeypatch, bootstrap_fn=bootstrap, verify_fn=verify
    )
    code = main(_argv(config, mode="initialize"))
    captured = capsys.readouterr()
    assert code == EXIT_RUNTIME
    assert captured.out == ""
    assert captured.err == f"{_RUNTIME}\n"


def test_wrapper_partial_marker_and_bilateral_impostor_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)
    true_bootstrap = bootstrap_mod.bootstrap_fresh_formal_paper_runtime
    true_reopen = bootstrap_mod.reopen_verified_formal_paper_runtime
    true_verify = bootstrap_mod.verify_existing_formal_paper_runtime_bootstrap

    def wrapper(**_kwargs: object) -> object:
        return _fake_verified()

    wrapper.__wrapped__ = true_bootstrap  # type: ignore[attr-defined]
    partial = functools.partial(true_bootstrap)
    marker = object()

    def impostor(**_kwargs: object) -> object:
        return _fake_verified()

    cases = [
        ("bootstrap", wrapper),
        ("bootstrap", partial),
        ("bootstrap", marker),
        ("both", impostor),
    ]
    for kind, fake in cases:
        monkeypatch.setattr(
            bootstrap_mod, "bootstrap_fresh_formal_paper_runtime", true_bootstrap
        )
        monkeypatch.setattr(
            bootstrap_mod, "reopen_verified_formal_paper_runtime", true_reopen
        )
        monkeypatch.setattr(
            bootstrap_mod, "verify_existing_formal_paper_runtime_bootstrap", true_verify
        )
        if kind == "bootstrap":
            monkeypatch.setattr(
                bootstrap_mod, "bootstrap_fresh_formal_paper_runtime", fake
            )
        else:
            monkeypatch.setattr(
                bootstrap_mod, "bootstrap_fresh_formal_paper_runtime", fake
            )
            monkeypatch.setattr(
                bootstrap_mod, "verify_existing_formal_paper_runtime_bootstrap", fake
            )
        monkeypatch.setattr(cli, "_canonical_utc_now", lambda: FIXED_NOW)
        code = main(_argv(config, mode="initialize"))
        captured = capsys.readouterr()
        assert code == EXIT_RUNTIME
        assert captured.out == ""
        assert captured.err == f"{_RUNTIME}\n"
        assert str(config) not in captured.err


def test_wrong_return_type_is_runtime_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)

    def bootstrap(**_kwargs: object) -> object:
        return {"not": "capability"}

    def verify(**kwargs: object) -> object:
        return kwargs["bootstrap"]

    _install_owned_seam(monkeypatch, bootstrap_fn=bootstrap, verify_fn=verify)
    # Restore real type gate for this case.
    monkeypatch.setattr(
        cli, "VerifiedFormalPaperRuntimeBootstrap", VerifiedFormalPaperRuntimeBootstrap
    )
    code = main(_argv(config, mode="initialize"))
    captured = capsys.readouterr()
    assert code == EXIT_RUNTIME
    assert captured.out == ""
    assert captured.err == f"{_RUNTIME}\n"


@pytest.mark.parametrize(
    ("error", "stderr_code", "exit_code"),
    [
        (
            FormalPaperBootstrapError("PAPER_FORMAL_BOOTSTRAP_CONFIG_INVALID"),
            "PAPER_FORMAL_BOOTSTRAP_CONFIG_INVALID",
            EXIT_RUNTIME,
        ),
        (
            FormalPaperBootstrapError("PAPER_FORMAL_BOOTSTRAP_STALE"),
            "PAPER_FORMAL_BOOTSTRAP_STALE",
            EXIT_RUNTIME,
        ),
        (
            FormalPaperBootstrapError("PAPER_FORMAL_BOOTSTRAP_NOT_FOUND"),
            "PAPER_FORMAL_BOOTSTRAP_NOT_FOUND",
            EXIT_RUNTIME,
        ),
        (
            RuntimeError(r"C:\secret\root\config.toml"),
            _RUNTIME,
            EXIT_RUNTIME,
        ),
        (
            ValueError("/tmp/absolute/config.toml leaked"),
            _RUNTIME,
            EXIT_RUNTIME,
        ),
        (
            OSError("path identity drift near /secret"),
            _RUNTIME,
            EXIT_RUNTIME,
        ),
    ],
)
def test_public_and_unknown_errors_are_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: BaseException,
    stderr_code: str,
    exit_code: int,
) -> None:
    config = _write_config(tmp_path)
    secret = str(config)

    def boom(**_kwargs: object) -> object:
        raise error

    _install_owned_seam(monkeypatch, bootstrap_fn=boom)
    code = main(_argv(config, mode="initialize"))
    captured = capsys.readouterr()
    assert code == exit_code
    assert captured.out == ""
    assert captured.err == f"{stderr_code}\n"
    assert secret not in captured.err
    assert "secret" not in captured.err.lower() or stderr_code.lower().find("secret") >= 0
    assert r"C:\secret" not in captured.err
    assert "/tmp/absolute" not in captured.err
    assert "Traceback" not in captured.err
    assert "RuntimeError" not in captured.err
    assert "ValueError" not in captured.err


def test_success_projection_exact_keys_and_no_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)
    capability = _fake_verified()

    def bootstrap(**_kwargs: object) -> object:
        return capability

    def verify(**kwargs: object) -> object:
        assert kwargs["bootstrap"] is capability
        return capability

    _install_owned_seam(monkeypatch, bootstrap_fn=bootstrap, verify_fn=verify)
    code = main(_argv(config, mode="initialize"))
    captured = capsys.readouterr()
    assert code == EXIT_SUCCESS
    assert captured.err == ""
    assert captured.out.endswith("\n")
    assert captured.out.count("\n") == 1
    raw = captured.out.encode("utf-8")[:-1]
    payload = json.loads(captured.out)
    assert tuple(payload) == tuple(sorted(_RESULT_KEYS))
    assert set(payload) == set(_RESULT_KEYS)
    assert payload["schema_version"] == _SCHEMA
    assert payload["mode"] == "initialize"
    assert payload["session_date"] == SESSION
    assert payload["bootstrap_identity"] == "b" * 64
    assert raw == canonical_json_bytes(payload)
    forbidden = (
        str(config),
        str(tmp_path),
        "acct-must-not-leak",
        "verified_at",
        "raw-token",
        "config_path",
        "account_id",
        "token",
        "SimpleNamespace",
        FIXED_NOW.isoformat(),
    )
    for item in forbidden:
        assert item not in captured.out


def test_initialize_failure_does_not_delete_or_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)
    marker = tmp_path / "broker-root"
    marker.mkdir()
    attempts: list[int] = []

    def boom(**_kwargs: object) -> object:
        attempts.append(1)
        raise FormalPaperBootstrapError("PAPER_FORMAL_BOOTSTRAP_ROLLBACK_REQUIRED")

    _install_owned_seam(monkeypatch, bootstrap_fn=boom)
    assert "shutil" not in sys.modules or "shutil" not in vars(cli)
    assert not hasattr(cli, "shutil")

    code = main(_argv(config, mode="initialize"))
    captured = capsys.readouterr()
    assert code == EXIT_RUNTIME
    assert attempts == [1]
    assert captured.out == ""
    assert captured.err == "PAPER_FORMAL_BOOTSTRAP_ROLLBACK_REQUIRED\n"
    assert marker.exists()
    assert marker.is_dir()


def test_reopen_never_calls_initializer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)
    calls = _install_owned_seam(monkeypatch)
    code = main(_argv(config, mode="reopen"))
    assert code == EXIT_SUCCESS
    assert calls["bootstrap"] == []
    assert len(calls["reopen"]) == 1
    assert len(calls["verify"]) == 1
    assert capsys.readouterr().err == ""


def test_public_toctou_stable_code_is_runtime_not_success_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)

    def bootstrap(**_kwargs: object) -> object:
        raise FormalPaperBootstrapError("PAPER_FORMAL_BOOTSTRAP_STALE")

    _install_owned_seam(monkeypatch, bootstrap_fn=bootstrap)
    code = main(_argv(config, mode="initialize"))
    captured = capsys.readouterr()
    assert code == EXIT_RUNTIME
    assert captured.out == ""
    assert captured.err == "PAPER_FORMAL_BOOTSTRAP_STALE\n"
    assert "{" not in captured.out


def test_failure_stdout_is_empty_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)
    _install_owned_seam(
        monkeypatch,
        bootstrap_fn=lambda **_k: (_ for _ in ()).throw(
            FormalPaperBootstrapError("PAPER_FORMAL_BOOTSTRAP_INVALID")
        ),
    )
    code = main(_argv(config, mode="initialize"))
    captured = capsys.readouterr()
    assert code == EXIT_RUNTIME
    assert captured.out.encode("utf-8") == b""
    assert captured.err.encode("utf-8") == b"PAPER_FORMAL_BOOTSTRAP_INVALID\n"


@pytest.mark.parametrize(
    ("slot", "mode"),
    [
        ("bootstrap", "initialize"),
        ("reopen", "reopen"),
        ("verify", "initialize"),
    ],
)
def test_business_systemexit_maps_to_runtime_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    slot: str,
    mode: str,
) -> None:
    """AE-1 / F1: business-segment SystemExit never escapes main or leaks path codes."""

    config = _write_config(tmp_path)
    secret = r"C:\secret\root\config.toml"

    def raise_system_exit(**_kwargs: object) -> object:
        raise SystemExit(secret)

    capability = _fake_verified()
    bootstrap_fn: object | None = None
    reopen_fn: object | None = None
    verify_fn: object | None = None
    if slot == "bootstrap":
        bootstrap_fn = raise_system_exit
    elif slot == "reopen":
        reopen_fn = raise_system_exit
    else:

        def bootstrap_ok(**_kwargs: object) -> object:
            return capability

        def verify_boom(**_kwargs: object) -> object:
            raise SystemExit(secret)

        bootstrap_fn = bootstrap_ok
        verify_fn = verify_boom

    _install_owned_seam(
        monkeypatch,
        bootstrap_fn=bootstrap_fn,
        reopen_fn=reopen_fn,
        verify_fn=verify_fn,
    )
    code = main(_argv(config, mode=mode))
    captured = capsys.readouterr()
    assert code == EXIT_RUNTIME
    assert captured.out == ""
    assert captured.err == f"{_RUNTIME}\n"
    assert secret not in captured.err
    assert "usage" not in captured.err.lower()
    assert str(config) not in captured.err


@pytest.mark.parametrize(
    "hostile_code",
    [
        "PAPER_FORMAL_BOOTSTRAP_STALE\nY",
        "PAPER_FORMAL_BOOTSTRAP_STALE\rC:\\secret\\config.toml",
        "PAPER_FORMAL_BOOTSTRAP_STALE\tX",
        "PAPER_FORMAL_BOOTSTRAP_STALE\x1b[0m",
        " PAPER_FORMAL_BOOTSTRAP_STALE",
        "PAPER_FORMAL_BOOTSTRAP_STALE ",
        "paper_formal_bootstrap_stale",
        "1PAPER_FORMAL_BOOTSTRAP_STALE",
        "PAPER/FORMAL_BOOTSTRAP_STALE",
        "PAPER\\FORMAL_BOOTSTRAP_STALE",
        "PAPER:FORMAL_BOOTSTRAP_STALE",
        "PAPER_FORMAL_BOOTSTRAP_STALE/tmp/x",
        "纸面_BOOTSTRAP_STALE",
        "",
    ],
)
def test_hostile_formal_bootstrap_error_code_maps_wholly_to_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hostile_code: str,
) -> None:
    """AE-2 / F2: malformed public codes are never partially sanitized onto stderr."""

    config = _write_config(tmp_path)

    def boom(**_kwargs: object) -> object:
        raise FormalPaperBootstrapError(hostile_code)

    _install_owned_seam(monkeypatch, bootstrap_fn=boom)
    code = main(_argv(config, mode="initialize"))
    captured = capsys.readouterr()
    assert code == EXIT_RUNTIME
    assert captured.out == ""
    assert captured.err == f"{_RUNTIME}\n"
    assert captured.err.count("\n") == 1
    if hostile_code:
        assert hostile_code not in captured.err
    assert "\r" not in captured.err
    assert "\t" not in captured.err
    assert "\x1b" not in captured.err
    assert "secret" not in captured.err.lower()
    assert "/" not in captured.err.replace(_RUNTIME, "")
    assert "\\" not in captured.err


def test_non_str_formal_bootstrap_error_code_maps_to_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)
    forged = FormalPaperBootstrapError("PAPER_FORMAL_BOOTSTRAP_STALE")
    forged.code = None  # type: ignore[assignment]

    def boom(**_kwargs: object) -> object:
        raise forged

    _install_owned_seam(monkeypatch, bootstrap_fn=boom)
    code = main(_argv(config, mode="initialize"))
    captured = capsys.readouterr()
    assert code == EXIT_RUNTIME
    assert captured.out == ""
    assert captured.err == f"{_RUNTIME}\n"


def test_stable_public_error_code_helper_accepts_only_exact_token() -> None:
    assert (
        cli._stable_public_error_code("PAPER_FORMAL_BOOTSTRAP_STALE")
        == "PAPER_FORMAL_BOOTSTRAP_STALE"
    )
    assert cli._stable_public_error_code("PAPER_FORMAL_BOOTSTRAP_STALE\n") is None
    assert cli._stable_public_error_code("PAPER_FORMAL_BOOTSTRAP_STALE\rX") is None
    assert cli._stable_public_error_code("") is None
    assert cli._stable_public_error_code(None) is None
    assert cli._stable_public_error_code(123) is None
