"""M3 G1-R1C thin CLI: parse args and call R1B workflow; no workflow state machine."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TextIO, cast

from quant.data.connectors.baostock import BaostockConnector
from quant.data.connectors.tushare import TushareConnector
from quant.research.m3.config import LoadedM3Config, M3ConfigError, load_m3_config
from quant.research.m3.g1_workflow import (
    M3G1WorkflowError,
    Operation,
    Stage,
    VerifiedG1WorkflowStateV1,
    inspect_g1_workflow,
    prepare_g1_workflow,
    publish_g1_workflow,
    run_g1_history_stage,
    run_g1_index_stage,
    run_g1_reference_stage,
)

Command = Literal[
    "status", "index", "history", "reference", "prepare", "publish", "run-all"
]
Outcome = Literal["SUCCESS", "INCOMPLETE", "FAILED"]
StopAfter = Literal["INDEX", "HISTORY", "REFERENCE", "PREPARE", "PUBLISH"]

_SCHEMA: Literal["m3-g1-cli-result-v1"] = "m3-g1-cli-result-v1"
_COMMANDS: tuple[Command, ...] = (
    "status",
    "index",
    "history",
    "reference",
    "prepare",
    "publish",
    "run-all",
)
_STOP_AFTER: tuple[StopAfter, ...] = (
    "INDEX",
    "HISTORY",
    "REFERENCE",
    "PREPARE",
    "PUBLISH",
)
_STAGE_ORDER: tuple[Stage, ...] = (
    "INDEX",
    "HISTORY",
    "REFERENCE",
    "PREPARE",
    "PUBLISH",
)
_WORKFLOW_CODES = frozenset(
    {
        "G1_WORKFLOW_INPUT_INVALID",
        "G1_WORKFLOW_PROJECT_ROOT_INVALID",
        "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
        "G1_WORKFLOW_INDEX_INCOMPLETE",
        "G1_WORKFLOW_HISTORY_INCOMPLETE",
        "G1_WORKFLOW_REFERENCE_INCOMPLETE",
        "G1_WORKFLOW_JOURNAL_INVALID",
        "G1_WORKFLOW_EXECUTION_FAILED",
        "G1_WORKFLOW_QUALITY_FAILED",
        "G1_WORKFLOW_PUBLISH_UNSUPPORTED",
        "G1_WORKFLOW_PUBLISH_FAILED",
        "G1_WORKFLOW_IDENTITY_MISMATCH",
    }
)
_CLI_CODES = frozenset(
    {
        "CLI_ARGUMENT_INVALID",
        "CLI_CONFIG_INVALID",
        "CLI_INTERNAL_ERROR",
        "OUTPUT_REDACTION_FAILED",
    }
)
_NETWORK_ERRNOS = frozenset(
    {
        errno.ECONNREFUSED,
        errno.ECONNRESET,
        errno.ETIMEDOUT,
        errno.ENETUNREACH,
        errno.EHOSTUNREACH,
        errno.EPIPE,
        errno.ENETDOWN,
        errno.ECONNABORTED,
    }
)
_SENSITIVE = re.compile(
    r"(?:"
    r"(?:token|password|secret|api_key|apikey)\s*[:=]"
    r"|Bearer\s"
    r"|[A-Za-z]:\\"
    r"|/mnt/[A-Za-z]/"
    r"|/home/"
    r"|tushare\.local\.toml"
    r")",
    re.IGNORECASE,
)
_FORBIDDEN_FLAGS = frozenset(
    {
        "--token",
        "--raw-root",
        "--journal-root",
        "--release-root",
        "--request-rate",
        "--max-attempts",
        "--retry-base-seconds",
        "--version-override",
    }
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_OPERATIONS: frozenset[str] = frozenset(
    {"INSPECT", "INDEX", "HISTORY", "REFERENCE", "PREPARE", "PUBLISH"}
)
_VALUE_OPTIONS = frozenset(
    {
        "--config",
        "--project-root",
        "--stop-after",
        "--max-new-requests",
        "--token",
        "--raw-root",
        "--journal-root",
        "--release-root",
        "--request-rate",
        "--max-attempts",
        "--retry-base-seconds",
        "--version-override",
    }
)


@dataclass(frozen=True)
class G1CliResultV1:
    schema_version: Literal["m3-g1-cli-result-v1"]
    command: Command | None
    outcome: Outcome
    completed_stages: tuple[Stage, ...]
    index_requests: int
    history_requests: int
    reference_requests: int
    history_symbols: int
    primary_candidate_key: str | None
    release_id: str | None
    manifest_sha256: str | None
    error_code: str | None
    error_operation: Operation | None
    max_new_requests: int | None
    new_requests_committed: int | None

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA:
            raise ValueError("cli result schema_version 非法")
        if self.command is not None and (
            type(self.command) is not str or self.command not in _COMMANDS
        ):
            raise ValueError("cli result command 非法")
        if self.outcome not in {"SUCCESS", "INCOMPLETE", "FAILED"}:
            raise ValueError("cli result outcome 非法")
        if type(self.completed_stages) is not tuple:
            raise ValueError("cli result completed_stages 非法")
        if self.completed_stages != _STAGE_ORDER[: len(self.completed_stages)]:
            raise ValueError("cli result completed_stages 必须是固定前缀")
        for name in (
            "index_requests",
            "history_requests",
            "reference_requests",
            "history_symbols",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError("cli result counts 非法")
        if self.max_new_requests is not None and (
            type(self.max_new_requests) is not int or self.max_new_requests <= 0
        ):
            raise ValueError("cli result max_new_requests 非法")
        if self.new_requests_committed is not None and (
            type(self.new_requests_committed) is not int or self.new_requests_committed < 0
        ):
            raise ValueError("cli result new_requests_committed 非法")
        for name in ("primary_candidate_key", "release_id", "manifest_sha256"):
            value = getattr(self, name)
            if value is not None and (
                type(value) is not str or _HEX64.fullmatch(value) is None
            ):
                raise ValueError("cli result digest 非法")
        has_history = "HISTORY" in self.completed_stages
        has_prepare = "PREPARE" in self.completed_stages
        has_publish = "PUBLISH" in self.completed_stages
        if not has_history:
            if (
                self.primary_candidate_key is not None
                or self.release_id is not None
                or self.manifest_sha256 is not None
            ):
                raise ValueError("cli result identity 生命周期非法")
        elif not has_prepare:
            if self.primary_candidate_key is None:
                raise ValueError("cli result identity 生命周期非法")
            if self.release_id is not None or self.manifest_sha256 is not None:
                raise ValueError("cli result identity 生命周期非法")
        elif not has_publish:
            if self.primary_candidate_key is None or self.release_id is None:
                raise ValueError("cli result identity 生命周期非法")
            if self.manifest_sha256 is not None:
                raise ValueError("cli result identity 生命周期非法")
        else:
            if (
                self.primary_candidate_key is None
                or self.release_id is None
                or self.manifest_sha256 is None
            ):
                raise ValueError("cli result identity 生命周期非法")
        if self.outcome == "FAILED":
            if self.error_code is None:
                raise ValueError("FAILED 必须有 error_code")
            if type(self.error_code) is not str:
                raise ValueError("cli result error_code 非法")
            if self.error_code in _WORKFLOW_CODES:
                if (
                    type(self.error_operation) is not str
                    or self.error_operation not in _OPERATIONS
                ):
                    raise ValueError("workflow error 必须有合法 error_operation")
            elif self.error_code in _CLI_CODES:
                if self.error_operation is not None:
                    raise ValueError("CLI-only error 不得携带 error_operation")
            else:
                raise ValueError("cli result error_code 非法")
        else:
            if self.error_code is not None or self.error_operation is not None:
                raise ValueError("非 FAILED 不得带 error 字段")


def _classify_tushare_error(exc: BaseException) -> str:
    """Private classifier for R1B/B2A; never retains or emits exception text."""
    seen: set[int] = set()
    current: BaseException | None = exc
    depth = 0
    while current is not None and depth < 32:
        ident = id(current)
        if ident in seen:
            break
        seen.add(ident)
        depth += 1
        if isinstance(current, TimeoutError):
            return "NETWORK"
        if isinstance(current, OSError):
            en = getattr(current, "errno", None)
            if type(en) is int and en in _NETWORK_ERRNOS:
                return "NETWORK"
        text = _safe_exc_text(current)
        lower = text.lower()
        if (
            "rate limit" in lower
            or "too many requests" in lower
            or "每分钟最多访问" in text
            or "访问频次" in text
        ):
            return "RATE_LIMIT"
        if (
            "502" in text
            or "503" in text
            or "504" in text
            or "temporarily unavailable" in lower
        ):
            return "TRANSIENT_SERVER"
        nxt: BaseException | None = None
        cause = getattr(current, "__cause__", None)
        ctx = getattr(current, "__context__", None)
        if isinstance(cause, BaseException):
            nxt = cause
        elif isinstance(ctx, BaseException):
            nxt = ctx
        current = nxt
    return "PERMANENT"


def _safe_exc_text(exc: BaseException) -> str:
    try:
        return str(exc)
    except BaseException:
        return ""


def _new_tushare_connector() -> TushareConnector:
    return TushareConnector()


def _new_baostock_connector() -> BaostockConnector:
    return BaostockConnector()


def _failed(
    *,
    command: Command | None,
    error_code: str,
    error_operation: Operation | None,
    state: VerifiedG1WorkflowStateV1 | None = None,
    max_new_requests: int | None = None,
    new_requests_committed: int | None = 0,
) -> G1CliResultV1:
    if state is None:
        return G1CliResultV1(
            schema_version=_SCHEMA,
            command=command,
            outcome="FAILED",
            completed_stages=(),
            index_requests=0,
            history_requests=0,
            reference_requests=0,
            history_symbols=0,
            primary_candidate_key=None,
            release_id=None,
            manifest_sha256=None,
            error_code=error_code,
            error_operation=error_operation,
            max_new_requests=max_new_requests,
            new_requests_committed=new_requests_committed,
        )
    key, release_id, manifest = _identity_from_state(state)
    return G1CliResultV1(
        schema_version=_SCHEMA,
        command=command,
        outcome="FAILED",
        completed_stages=state.completed_stages,
        index_requests=state.counts.index_requests,
        history_requests=state.counts.history_requests,
        reference_requests=state.counts.reference_requests,
        history_symbols=state.counts.history_symbols,
        primary_candidate_key=key,
        release_id=release_id,
        manifest_sha256=manifest,
        error_code=error_code,
        error_operation=error_operation,
        max_new_requests=max_new_requests,
        new_requests_committed=new_requests_committed,
    )


def _success_from_state(
    *,
    command: Command,
    state: VerifiedG1WorkflowStateV1,
    outcome: Outcome,
    max_new_requests: int | None = None,
    new_requests_committed: int | None = 0,
) -> G1CliResultV1:
    key, release_id, manifest = _identity_from_state(state)
    return G1CliResultV1(
        schema_version=_SCHEMA,
        command=command,
        outcome=outcome,
        completed_stages=state.completed_stages,
        index_requests=state.counts.index_requests,
        history_requests=state.counts.history_requests,
        reference_requests=state.counts.reference_requests,
        history_symbols=state.counts.history_symbols,
        primary_candidate_key=key,
        release_id=release_id,
        manifest_sha256=manifest,
        error_code=None,
        error_operation=None,
        max_new_requests=max_new_requests,
        new_requests_committed=new_requests_committed,
    )


def _identity_from_state(
    state: VerifiedG1WorkflowStateV1,
) -> tuple[str | None, str | None, str | None]:
    stages = state.completed_stages
    key: str | None = None
    release_id: str | None = None
    manifest: str | None = None
    if any(s in stages for s in ("HISTORY", "REFERENCE", "PREPARE", "PUBLISH")):
        cand = state.candidate
        if cand is not None:
            key = cand.primary_candidate_key
    if "PUBLISH" in stages and state.published is not None:
        release_id = state.published.release.release_id
        manifest = state.published.manifest_sha256
    elif "PREPARE" in stages and state.prepared is not None:
        release_id = state.prepared.release_id
    return key, release_id, manifest


def _exit_for_workflow(exc: M3G1WorkflowError) -> int:
    code = exc.code
    if code in {
        "G1_WORKFLOW_INPUT_INVALID",
        "G1_WORKFLOW_PROJECT_ROOT_INVALID",
    }:
        return 2
    if code in {
        "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
        "G1_WORKFLOW_JOURNAL_INVALID",
        "G1_WORKFLOW_IDENTITY_MISMATCH",
    }:
        return 3
    if code in {
        "G1_WORKFLOW_INDEX_INCOMPLETE",
        "G1_WORKFLOW_HISTORY_INCOMPLETE",
    }:
        return 4
    if code == "G1_WORKFLOW_REFERENCE_INCOMPLETE":
        return 5
    if code == "G1_WORKFLOW_QUALITY_FAILED":
        return 6
    if code in {
        "G1_WORKFLOW_PUBLISH_UNSUPPORTED",
        "G1_WORKFLOW_PUBLISH_FAILED",
    }:
        return 7
    if code == "G1_WORKFLOW_EXECUTION_FAILED":
        if exc.operation in {"INDEX", "HISTORY"}:
            return 4
        if exc.operation == "REFERENCE":
            return 5
        return 2
    return 2


def _result_mapping(result: G1CliResultV1) -> dict[str, Any]:
    return {
        "schema_version": result.schema_version,
        "command": result.command,
        "outcome": result.outcome,
        "completed_stages": list(result.completed_stages),
        "index_requests": result.index_requests,
        "history_requests": result.history_requests,
        "reference_requests": result.reference_requests,
        "history_symbols": result.history_symbols,
        "primary_candidate_key": result.primary_candidate_key,
        "release_id": result.release_id,
        "manifest_sha256": result.manifest_sha256,
        "error_code": result.error_code,
        "error_operation": result.error_operation,
        "max_new_requests": result.max_new_requests,
        "new_requests_committed": result.new_requests_committed,
    }


def _sensitive_hit(payload: bytes) -> bool:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return _SENSITIVE.search(text) is not None


def _emit(
    result: G1CliResultV1,
    exit_code: int,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    mapping = _result_mapping(result)
    try:
        raw = json.dumps(
            mapping,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return _emit_redaction_failed(stdout=stdout, stderr=stderr, command=result.command)

    if _sensitive_hit(raw):
        return _emit_redaction_failed(stdout=stdout, stderr=stderr, command=result.command)

    stdout.write(raw.decode("utf-8"))
    stdout.write("\n")
    if result.outcome == "FAILED" and result.error_code is not None:
        op = result.error_operation if result.error_operation is not None else "CLI"
        stderr.write(f"{op}:{result.error_code}\n")
    return exit_code


def _emit_redaction_failed(
    *, stdout: TextIO, stderr: TextIO, command: Command | None
) -> int:
    safe = G1CliResultV1(
        schema_version=_SCHEMA,
        command=command,
        outcome="FAILED",
        completed_stages=(),
        index_requests=0,
        history_requests=0,
        reference_requests=0,
        history_symbols=0,
        primary_candidate_key=None,
        release_id=None,
        manifest_sha256=None,
        error_code="OUTPUT_REDACTION_FAILED",
        error_operation=None,
        max_new_requests=None,
        new_requests_committed=0,
    )
    raw = json.dumps(
        _result_mapping(safe),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    stdout.write(raw)
    stdout.write("\n")
    stderr.write("CLI:OUTPUT_REDACTION_FAILED\n")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quant.research.m3.run_g1",
        add_help=True,
        exit_on_error=False,
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in _COMMANDS:
        if name == "run-all":
            p = sub.add_parser(name)
            p.add_argument(
                "--stop-after",
                choices=_STOP_AFTER,
                default="PREPARE",
            )
        elif name == "history":
            p = sub.add_parser(name)
            p.add_argument(
                "--max-new-requests",
                type=_parse_cli_max_new_requests,
                default=None,
            )
        else:
            sub.add_parser(name)
    return parser


def _parse_cli_max_new_requests(raw: str) -> int:
    if type(raw) is not str:
        raise argparse.ArgumentTypeError("max-new-requests must be strict positive int")
    if not raw.isdigit() or str(int(raw)) != raw or int(raw) <= 0:
        raise argparse.ArgumentTypeError("max-new-requests must be strict positive int")
    return int(raw)


def _reject_forbidden(argv: Sequence[str]) -> bool:
    for item in argv:
        if item in _FORBIDDEN_FLAGS or item.startswith("--token="):
            return True
        if item.startswith("--raw-root=") or item.startswith("--journal-root="):
            return True
        if item.startswith("--release-root="):
            return True
    return False


def _peek_command(argv: Sequence[str]) -> Command | None:
    """Identify an unambiguous command for error attribution; never guess."""
    found: list[str] = []
    i = 0
    n = len(argv)
    while i < n:
        item = argv[i]
        if item in _VALUE_OPTIONS:
            i += 2
            continue
        skipped_eq = False
        for option in _VALUE_OPTIONS:
            if item.startswith(f"{option}="):
                i += 1
                skipped_eq = True
                break
        if skipped_eq:
            continue
        if item.startswith("-"):
            i += 1
            # Unknown option may take a value; consume one non-command token.
            if i < n and not argv[i].startswith("-") and argv[i] not in _COMMANDS:
                i += 1
            continue
        if item in _COMMANDS:
            found.append(item)
        else:
            return None
        i += 1
    if len(found) == 1:
        return cast(Command, found[0])
    return None


def _config_path_fingerprint(path: Path) -> tuple[int, int, int, int, str]:
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ValueError("CLI_CONFIG_INVALID")
    payload = path.read_bytes()
    if len(payload) != st.st_size:
        raise ValueError("CLI_CONFIG_INVALID")
    return (
        st.st_dev,
        st.st_ino,
        st.st_size,
        st.st_mtime_ns,
        hashlib.sha256(payload).hexdigest(),
    )


def _validate_config_path(path: Path, *, project_root: Path) -> LoadedM3Config:
    try:
        root = Path(os.path.abspath(os.fspath(project_root)))
        candidate = Path(os.path.abspath(os.fspath(path.expanduser())))
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            raise ValueError("CLI_CONFIG_INVALID") from None
        if ".." in relative.parts:
            raise ValueError("CLI_CONFIG_INVALID")
        if type(candidate.name) is not str or not candidate.name.endswith(".toml"):
            raise ValueError("CLI_CONFIG_INVALID")

        chain: list[Path] = []
        current = candidate
        while True:
            chain.append(current)
            if current == root:
                break
            parent = current.parent
            if parent == current:
                raise ValueError("CLI_CONFIG_INVALID")
            current = parent

        for node in reversed(chain):
            node_st = os.lstat(node)
            if stat.S_ISLNK(node_st.st_mode):
                raise ValueError("CLI_CONFIG_INVALID")
            if node == candidate:
                if not stat.S_ISREG(node_st.st_mode):
                    raise ValueError("CLI_CONFIG_INVALID")
            elif not stat.S_ISDIR(node_st.st_mode):
                raise ValueError("CLI_CONFIG_INVALID")

        before = _config_path_fingerprint(candidate)
        loaded = load_m3_config(candidate)
        after = _config_path_fingerprint(candidate)
        if before != after:
            raise ValueError("CLI_CONFIG_INVALID")
        return loaded
    except M3ConfigError:
        raise
    except ValueError:
        raise
    except Exception:
        raise ValueError("CLI_CONFIG_INVALID") from None


def _try_inspect(
    *, project_root: Path, config: LoadedM3Config
) -> VerifiedG1WorkflowStateV1 | None:
    try:
        return inspect_g1_workflow(project_root=project_root, config=config)
    except Exception:
        return None


def _run_command(
    *,
    command: Command,
    project_root: Path,
    config: LoadedM3Config,
    stop_after: StopAfter = "PREPARE",
    max_new_requests: int | None = None,
) -> tuple[G1CliResultV1, int]:
    last_state: VerifiedG1WorkflowStateV1 | None = None
    try:
        if command == "status":
            state = inspect_g1_workflow(project_root=project_root, config=config)
            if "PUBLISH" in state.completed_stages:
                return _success_from_state(
                    command=command, state=state, outcome="SUCCESS"
                ), 0
            return _success_from_state(
                command=command, state=state, outcome="INCOMPLETE"
            ), 0

        if command == "index":
            connector = _new_tushare_connector()
            state = run_g1_index_stage(
                project_root=project_root,
                config=config,
                connector=connector,
                classify_error=_classify_tushare_error,
            )
            return _success_from_state(
                command=command, state=state, outcome="SUCCESS"
            ), 0

        if command == "history":
            connector = _new_tushare_connector()
            history_result = run_g1_history_stage(
                project_root=project_root,
                config=config,
                connector=connector,
                classify_error=_classify_tushare_error,
                max_new_requests=max_new_requests,
            )
            state = history_result.state
            outcome: Outcome = (
                "INCOMPLETE"
                if (
                    max_new_requests is not None
                    and "HISTORY" not in state.completed_stages
                )
                else "SUCCESS"
            )
            return _success_from_state(
                command=command,
                state=state,
                outcome=outcome,
                max_new_requests=history_result.max_new_requests,
                new_requests_committed=history_result.new_requests_committed,
            ), 0

        if command == "reference":
            bao = _new_baostock_connector()
            state = run_g1_reference_stage(
                project_root=project_root,
                config=config,
                connector=bao,
            )
            return _success_from_state(
                command=command, state=state, outcome="SUCCESS"
            ), 0

        if command == "prepare":
            state = prepare_g1_workflow(project_root=project_root, config=config)
            return _success_from_state(
                command=command, state=state, outcome="SUCCESS"
            ), 0

        if command == "publish":
            state = publish_g1_workflow(project_root=project_root, config=config)
            return _success_from_state(
                command=command, state=state, outcome="SUCCESS"
            ), 0

        # run-all
        stop_idx = _STOP_AFTER.index(stop_after)
        state = inspect_g1_workflow(project_root=project_root, config=config)
        last_state = state
        completed = set(state.completed_stages)

        if stop_idx >= 0 and "INDEX" not in completed:
            connector = _new_tushare_connector()
            state = run_g1_index_stage(
                project_root=project_root,
                config=config,
                connector=connector,
                classify_error=_classify_tushare_error,
            )
            last_state = state
            completed = set(state.completed_stages)
        if stop_after == "INDEX":
            return _success_from_state(
                command=command, state=state, outcome="SUCCESS"
            ), 0

        if stop_idx >= 1 and "HISTORY" not in completed:
            connector = _new_tushare_connector()
            history_result = run_g1_history_stage(
                project_root=project_root,
                config=config,
                connector=connector,
                classify_error=_classify_tushare_error,
            )
            state = history_result.state
            last_state = state
            completed = set(state.completed_stages)
        if stop_after == "HISTORY":
            return _success_from_state(
                command=command, state=state, outcome="SUCCESS"
            ), 0

        if stop_idx >= 2 and "REFERENCE" not in completed:
            bao = _new_baostock_connector()
            state = run_g1_reference_stage(
                project_root=project_root,
                config=config,
                connector=bao,
            )
            last_state = state
            completed = set(state.completed_stages)
        if stop_after == "REFERENCE":
            return _success_from_state(
                command=command, state=state, outcome="SUCCESS"
            ), 0

        if stop_idx >= 3:
            # PREPARE is not durable; always compute when requested.
            state = prepare_g1_workflow(project_root=project_root, config=config)
            last_state = state
        if stop_after == "PREPARE":
            return _success_from_state(
                command=command, state=state, outcome="SUCCESS"
            ), 0

        state = publish_g1_workflow(project_root=project_root, config=config)
        return _success_from_state(command=command, state=state, outcome="SUCCESS"), 0

    except M3G1WorkflowError as exc:
        fallback = last_state
        if fallback is None:
            fallback = _try_inspect(project_root=project_root, config=config)
        return (
            _failed(
                command=command,
                error_code=exc.code,
                error_operation=exc.operation,
                state=fallback,
            ),
            _exit_for_workflow(exc),
        )


def _run(
    argv: Sequence[str] | None = None,
    *,
    write_output: bool = True,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> tuple[G1CliResultV1, int]:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    peeked = _peek_command(raw_argv)

    if _reject_forbidden(raw_argv):
        result = _failed(
            command=peeked,
            error_code="CLI_ARGUMENT_INVALID",
            error_operation=None,
        )
        code = 2
        if write_output:
            return result, _emit(result, code, stdout=out, stderr=err)
        return result, code

    parser = _build_parser()
    try:
        args = parser.parse_args(raw_argv)
    except (SystemExit, argparse.ArgumentError):
        result = _failed(
            command=peeked,
            error_code="CLI_ARGUMENT_INVALID",
            error_operation=None,
        )
        code = 2
        if write_output:
            return result, _emit(result, code, stdout=out, stderr=err)
        return result, code

    command = cast(Command, args.command)
    if command not in _COMMANDS:
        result = _failed(
            command=None,
            error_code="CLI_ARGUMENT_INVALID",
            error_operation=None,
        )
        code = 2
        if write_output:
            return result, _emit(result, code, stdout=out, stderr=err)
        return result, code

    project_root = (
        Path.cwd() if args.project_root is None else Path(args.project_root)
    )
    try:
        project_root = project_root.expanduser().resolve(strict=False)
    except Exception:
        result = _failed(
            command=command,
            error_code="CLI_ARGUMENT_INVALID",
            error_operation=None,
        )
        code = 2
        if write_output:
            return result, _emit(result, code, stdout=out, stderr=err)
        return result, code

    try:
        config = _validate_config_path(Path(args.config), project_root=project_root)
    except M3ConfigError:
        result = _failed(
            command=command,
            error_code="CLI_CONFIG_INVALID",
            error_operation=None,
        )
        code = 2
        if write_output:
            return result, _emit(result, code, stdout=out, stderr=err)
        return result, code
    except ValueError:
        result = _failed(
            command=command,
            error_code="CLI_CONFIG_INVALID",
            error_operation=None,
        )
        code = 2
        if write_output:
            return result, _emit(result, code, stdout=out, stderr=err)
        return result, code
    except Exception:
        result = _failed(
            command=command,
            error_code="CLI_INTERNAL_ERROR",
            error_operation=None,
        )
        code = 2
        if write_output:
            return result, _emit(result, code, stdout=out, stderr=err)
        return result, code

    stop_after: StopAfter = "PREPARE"
    max_new_requests: int | None = None
    if command == "run-all":
        stop_after = cast(StopAfter, getattr(args, "stop_after", "PREPARE"))
    if command == "history":
        max_new_requests = getattr(args, "max_new_requests", None)

    try:
        result, code = _run_command(
            command=command,
            project_root=project_root,
            config=config,
            stop_after=stop_after,
            max_new_requests=max_new_requests,
        )
    except M3G1WorkflowError as exc:
        result = _failed(
            command=command,
            error_code=exc.code,
            error_operation=exc.operation,
        )
        code = _exit_for_workflow(exc)
    except Exception:
        result = _failed(
            command=command,
            error_code="CLI_INTERNAL_ERROR",
            error_operation=None,
        )
        code = 2

    if write_output:
        return result, _emit(result, code, stdout=out, stderr=err)
    return result, code


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    _result, code = _run(argv, write_output=True, stdout=stdout, stderr=stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
