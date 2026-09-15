"""Narrow operator CLI for formal PAPER runtime bootstrap initialize/reopen.

Parses explicit argv only, takes one canonical UTC now, invokes package-owned
public bootstrap/reopen/fresh-verify callables, and emits a redacted identity
projection. Does not copy bootstrap/policy/P2 logic, invent roots, or perform
cleanup/retry/submit/soak/network.
"""

from __future__ import annotations

import argparse
import datetime as dt
import functools
import os
import re
import stat
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal, NoReturn

from quant.domain.canonical_wire import canonical_json_bytes
from quant.execution import paper_formal_bootstrap as _bootstrap_mod
from quant.execution.paper_formal_bootstrap import (
    FormalPaperBootstrapError,
    VerifiedFormalPaperRuntimeBootstrap,
)

EXIT_SUCCESS = 0
EXIT_INPUT = 2
EXIT_RUNTIME = 3

_INPUT_CODE = "PAPER_FORMAL_BOOTSTRAP_CLI_INPUT_INVALID"
_RUNTIME_CODE = "PAPER_FORMAL_BOOTSTRAP_CLI_RUNTIME_FAILED"
_RESULT_SCHEMA = "m4-formal-bootstrap-operator-result-v1"
_REPARSE = 0x400
_PATH_TYPE = type(Path())
# Stable public bootstrap codes only: ASCII, leading A-Z, then A-Z0-9_ (no whitespace/control/path).
_STABLE_PUBLIC_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")

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

ModeName = Literal["initialize", "reopen"]
_BootstrapCallable = Callable[..., VerifiedFormalPaperRuntimeBootstrap]


class _InputError(Exception):
    """CLI argv/path/date/mode failure; never carries path or usage text."""


class _RuntimeFailed(Exception):
    """CLI callable-drift / fresh-identity / unexpected failure boundary."""


class _QuietParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise _InputError from None


def _build_callable_authority(
    true_bootstrap: _BootstrapCallable,
    true_reopen: _BootstrapCallable,
    true_verify: _BootstrapCallable,
) -> Callable[[], tuple[_BootstrapCallable, _BootstrapCallable, _BootstrapCallable]]:
    """Capture import-time package-owned bodies; bilateral impostors cannot pass."""

    true_bootstrap_code = getattr(true_bootstrap, "__code__", None)
    true_reopen_code = getattr(true_reopen, "__code__", None)
    true_verify_code = getattr(true_verify, "__code__", None)

    def _require_owned_api() -> tuple[
        _BootstrapCallable, _BootstrapCallable, _BootstrapCallable
    ]:
        bootstrap_fn = _bootstrap_mod.bootstrap_fresh_formal_paper_runtime
        reopen_fn = _bootstrap_mod.reopen_verified_formal_paper_runtime
        verify_fn = _bootstrap_mod.verify_existing_formal_paper_runtime_bootstrap
        if (
            bootstrap_fn is not true_bootstrap
            or reopen_fn is not true_reopen
            or verify_fn is not true_verify
        ):
            raise _RuntimeFailed from None
        if (
            getattr(bootstrap_fn, "__code__", None) is not true_bootstrap_code
            or getattr(reopen_fn, "__code__", None) is not true_reopen_code
            or getattr(verify_fn, "__code__", None) is not true_verify_code
        ):
            raise _RuntimeFailed from None
        for candidate in (bootstrap_fn, reopen_fn, verify_fn):
            if isinstance(candidate, functools.partial):
                raise _RuntimeFailed from None
            if getattr(candidate, "__wrapped__", None) is not None:
                raise _RuntimeFailed from None
        return bootstrap_fn, reopen_fn, verify_fn

    return _require_owned_api


# Closure-captured package-owned true bodies (not rewritable module aliases alone).
_require_owned_api = _build_callable_authority(
    _bootstrap_mod.bootstrap_fresh_formal_paper_runtime,
    _bootstrap_mod.reopen_verified_formal_paper_runtime,
    _bootstrap_mod.verify_existing_formal_paper_runtime_bootstrap,
)


def _is_link_or_reparse(info: os.stat_result) -> bool:
    return bool(
        stat.S_ISLNK(info.st_mode)
        or (getattr(info, "st_file_attributes", 0) & _REPARSE)
    )


def _require_exact_config_path(path: object) -> Path:
    """Accept only current-platform concrete absolute regular file Path metadata."""

    if type(path) is not _PATH_TYPE:
        raise _InputError from None
    concrete = path
    if not concrete.is_absolute() or concrete != concrete.absolute():
        raise _InputError from None
    try:
        info = os.lstat(concrete)
    except OSError:
        raise _InputError from None
    if (
        not stat.S_ISREG(info.st_mode)
        or _is_link_or_reparse(info)
        or getattr(os.path, "isjunction", lambda _p: False)(concrete)
    ):
        raise _InputError from None
    return concrete


def _require_session_date(value: object) -> dt.date:
    if type(value) is not str:
        raise _InputError from None
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        raise _InputError from None
    if type(parsed) is not dt.date or parsed.isoformat() != value:
        raise _InputError from None
    return parsed


def _project_identity(
    *,
    mode: ModeName,
    verified: VerifiedFormalPaperRuntimeBootstrap,
) -> dict[str, object]:
    if type(verified) is not VerifiedFormalPaperRuntimeBootstrap:
        raise _RuntimeFailed from None
    payload: dict[str, object] = {
        "schema_version": _RESULT_SCHEMA,
        "mode": mode,
        "session_date": verified.session_date.isoformat(),
        "bootstrap_identity": verified.bootstrap_identity,
        "config_identity": verified.config_identity,
        "config_raw_sha256": verified.config_raw_sha256,
        "source_file_identity": verified.source_file_identity,
        "runtime_environment_identity": verified.runtime_environment_identity,
        "runtime_layout_identity": verified.runtime_layout_identity,
        "execution_policy_identity": verified.execution_policy_identity,
        "broker_binding_identity": verified.broker_binding_identity,
        "account_verification_identity": verified.account_verification_identity,
        "broker_capability_identity": verified.broker_capability_identity,
        "gateway_identity": verified.gateway_identity,
        "execution_store_identity": verified.execution_store_identity,
        "barrier_epoch": verified.barrier_epoch,
        "barrier_capability_identity": verified.barrier_capability_identity,
        "barrier_lock_identity": verified.barrier_lock_identity,
    }
    if tuple(payload) != _RESULT_KEYS:
        raise _RuntimeFailed from None
    return payload


def _emit_success(payload: dict[str, object]) -> None:
    line = canonical_json_bytes(payload).decode("ascii")
    sys.stdout.write(line)
    sys.stdout.write("\n")


def _emit_code(code: str) -> None:
    sys.stderr.write(f"{code}\n")


def _stable_public_error_code(code: object) -> str | None:
    """Return ``code`` verbatim only when it is an exact stable ASCII token.

    Rejects non-str, empty, non-ASCII, whitespace, CR/LF/TAB/ESC/controls,
    slash/backslash/colon, Unicode, path-like, or otherwise malformed values.
    Never sanitizes or partially emits a hostile code.
    """

    if type(code) is not str or not code or not code.isascii():
        return None
    if _STABLE_PUBLIC_CODE.fullmatch(code) is None:
        return None
    return code


def _canonical_utc_now() -> dt.datetime:
    """Return one aware UTC process now; body is exactly datetime.now(timezone.utc)."""

    return dt.datetime.now(dt.timezone.utc)


def _build_parser() -> _QuietParser:
    parser = _QuietParser(
        prog="python -m quant.execution.run_paper_formal_bootstrap",
        description=(
            "Initialize or reopen a formal PAPER runtime via package-owned "
            "bootstrap public API and emit a redacted identity projection."
        ),
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Exact concrete absolute path to the validated formal runtime config.",
    )
    parser.add_argument(
        "--session-date",
        required=True,
        help="Canonical session date YYYY-MM-DD (exact round-trip).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--initialize",
        action="store_true",
        help="Fresh formal root/epoch bootstrap then fresh verify.",
    )
    mode.add_argument(
        "--reopen",
        action="store_true",
        help="Reopen a complete OPEN formal bundle then fresh verify.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse argv, invoke public bootstrap/reopen/verify, emit one JSON line."""

    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except _InputError:
        _emit_code(_INPUT_CODE)
        return EXIT_INPUT
    except SystemExit as error:
        code = error.code
        if code in (0, None):
            return EXIT_SUCCESS
        _emit_code(_INPUT_CODE)
        return EXIT_INPUT

    try:
        config_path = _require_exact_config_path(args.config)
        session_date = _require_session_date(args.session_date)
        if bool(args.initialize) == bool(args.reopen):
            raise _InputError from None
        mode: ModeName = "initialize" if args.initialize else "reopen"
        bootstrap_fn, reopen_fn, verify_fn = _require_owned_api()
        now = _canonical_utc_now()
        if type(now) is not dt.datetime or now.tzinfo is None:
            raise _RuntimeFailed from None
        if now.utcoffset() != dt.timedelta(0):
            raise _RuntimeFailed from None
        if mode == "initialize":
            capability = bootstrap_fn(
                config_path=config_path,
                session_date=session_date,
                now=now,
            )
        else:
            capability = reopen_fn(
                config_path=config_path,
                session_date=session_date,
                now=now,
            )
        verified = verify_fn(bootstrap=capability, now=now)
        if verified is not capability:
            raise _RuntimeFailed from None
        payload = _project_identity(mode=mode, verified=verified)
        _emit_success(payload)
        return EXIT_SUCCESS
    except _InputError:
        _emit_code(_INPUT_CODE)
        return EXIT_INPUT
    except FormalPaperBootstrapError as error:
        stable = _stable_public_error_code(error.code)
        if stable is None:
            _emit_code(_RUNTIME_CODE)
            return EXIT_RUNTIME
        _emit_code(stable)
        return EXIT_RUNTIME
    except _RuntimeFailed:
        _emit_code(_RUNTIME_CODE)
        return EXIT_RUNTIME
    except SystemExit:
        # Business-segment SystemExit is unexpected; never leak path/usage codes.
        # KeyboardInterrupt / GeneratorExit remain uncaught (process-control).
        _emit_code(_RUNTIME_CODE)
        return EXIT_RUNTIME
    except Exception:
        _emit_code(_RUNTIME_CODE)
        return EXIT_RUNTIME


if __name__ == "__main__":
    raise SystemExit(main())
