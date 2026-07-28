"""R1C-A: thin G1 CLI + fake continuation unit tests (zero network by default)."""

from __future__ import annotations

import errno
import io
import json
import socket
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from quant.data.connectors.baostock import BaostockConnector
from quant.data.connectors.tushare import TushareConnector
from quant.research.m3 import run_g1 as cli_mod
from quant.research.m3.config import LoadedM3Config, load_m3_config
from quant.research.m3.g1_workflow import (
    G1WorkflowCountsV1,
    M3G1WorkflowError,
    VerifiedG1WorkflowStateV1,
)
from quant.research.m3.run_g1 import (
    G1CliResultV1,
    _classify_tushare_error,
    _run,
    main,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _PROJECT_ROOT / "configs" / "research" / "m3_qlib_example.toml"


def _require_symlink(
    link: Path, target: Path, *, target_is_directory: bool = False
) -> None:
    """Create a symlink; skip only when Windows reports missing symlink privilege (1314)."""
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        if sys.platform == "win32" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows session lacks SeCreateSymbolicLinkPrivilege")
        raise


def _fast_config(root: Path) -> Path:
    text = _CONFIG_PATH.read_text(encoding="utf-8")
    variant = (
        text.replace("start_date = 2016-01-04", "start_date = 2016-02-01")
        .replace("end_date = 2026-06-26", "end_date = 2016-02-01")
        .replace("request_rate_per_minute = 60", "request_rate_per_minute = 600000")
        .replace("max_attempts = 5", "max_attempts = 1")
        .replace("retry_base_seconds = 2.0", "retry_base_seconds = 0.0")
    )
    path = root / "m3_r1c.toml"
    path.write_text(variant, encoding="utf-8")
    return path


def _project_root(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    quant = root / "src" / "quant"
    quant.mkdir(parents=True)
    (root / "pyproject.toml").write_bytes(b"[project]\nname='r1c'\n")
    (quant / "pkg.py").write_bytes(b"VALUE = 1\n")
    return root


def _root_and_config(tmp_path: Path) -> tuple[Path, Path]:
    root = _project_root(tmp_path)
    return root, _fast_config(root)


def _empty_state(
    *,
    stages: tuple[str, ...] = (),
    counts: G1WorkflowCountsV1 | None = None,
    candidate: Any = None,
    prepared: Any = None,
    published: Any = None,
) -> VerifiedG1WorkflowStateV1:
    mock = MagicMock(spec=VerifiedG1WorkflowStateV1)
    mock.completed_stages = stages
    mock.counts = counts or G1WorkflowCountsV1(
        index_requests=2,
        history_requests=0,
        reference_requests=0,
        history_symbols=0,
    )
    mock.candidate = candidate
    mock.prepared = prepared
    mock.published = published
    return mock  # type: ignore[return-value]


def _history_result(
    state: Any,
    *,
    max_new_requests: int | None = None,
    new_requests_committed: int = 0,
) -> Any:
    return MagicMock(
        state=state,
        max_new_requests=max_new_requests,
        new_requests_committed=new_requests_committed,
    )


def _argv(config: Path, root: Path, *parts: str) -> list[str]:
    return ["--config", str(config), "--project-root", str(root), *parts]


def _parse_stdout(buf: io.StringIO) -> dict[str, Any]:
    text = buf.getvalue()
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 1, text
    return json.loads(lines[0])


# --- classifier ---


def test_classify_timeout_and_network_errno() -> None:
    assert _classify_tushare_error(TimeoutError()) == "NETWORK"
    err = OSError(errno.ECONNRESET, "connection reset")
    assert _classify_tushare_error(err) == "NETWORK"
    plain = OSError(errno.ENOENT, "no such file")
    assert _classify_tushare_error(plain) == "PERMANENT"


def test_classify_rate_limit_and_transient() -> None:
    assert _classify_tushare_error(RuntimeError("Rate Limit exceeded")) == "RATE_LIMIT"
    assert _classify_tushare_error(RuntimeError("每分钟最多访问 200 次")) == "RATE_LIMIT"
    assert _classify_tushare_error(RuntimeError("HTTP 503")) == "TRANSIENT_SERVER"
    assert _classify_tushare_error(RuntimeError("temporarily unavailable")) == (
        "TRANSIENT_SERVER"
    )
    assert _classify_tushare_error(RuntimeError("bad request")) == "PERMANENT"


def test_classify_malicious_chain_and_sensitive_message() -> None:
    class Boom:
        def __str__(self) -> str:
            raise RuntimeError("token=secret /home/evil")

    class Cycle(BaseException):
        def __init__(self) -> None:
            self.__cause__ = self  # type: ignore[assignment]

        def __str__(self) -> str:
            return "token=abc /mnt/g/x"

    assert _classify_tushare_error(Boom()) == "PERMANENT"  # type: ignore[arg-type]
    assert _classify_tushare_error(Cycle()) == "PERMANENT"


# --- argparse / config ---


def test_argparse_rejects_token_and_unknown(tmp_path: Path) -> None:
    root, config = _root_and_config(tmp_path)
    # No unambiguous command → command=None
    for bad in (
        _argv(config, root, "not-a-command"),
        _argv(config, root, "--token", "status"),
        _argv(config, root, "status", "history"),
    ):
        out, err = io.StringIO(), io.StringIO()
        code = main(bad, stdout=out, stderr=err)
        assert code == 2
        payload = _parse_stdout(out)
        assert payload["schema_version"] == "m3-g1-cli-result-v1"
        assert payload["outcome"] == "FAILED"
        assert payload["error_code"] == "CLI_ARGUMENT_INVALID"
        assert payload["command"] is None
        assert err.getvalue().strip() == "CLI:CLI_ARGUMENT_INVALID"

    # Command already identified → retain literal on later failures
    cases = [
        (["status"], "status"),
        (_argv(config, root, "--token", "x", "status"), "status"),
        (_argv(config, root, "--raw-root", "/tmp", "status"), "status"),
        (_argv(config, root, "status", "--version", "9"), "status"),
    ]
    for argv, expected_command in cases:
        out, err = io.StringIO(), io.StringIO()
        code = main(argv, stdout=out, stderr=err)
        assert code == 2
        payload = _parse_stdout(out)
        assert payload["error_code"] == "CLI_ARGUMENT_INVALID"
        assert payload["command"] == expected_command
        assert err.getvalue().strip() == "CLI:CLI_ARGUMENT_INVALID"


def test_argparse_missing_command_sets_command_none(tmp_path: Path) -> None:
    root, config = _root_and_config(tmp_path)
    out, err = io.StringIO(), io.StringIO()
    code = main(
        ["--config", str(config), "--project-root", str(root)],
        stdout=out,
        stderr=err,
    )
    assert code == 2
    payload = _parse_stdout(out)
    assert payload["command"] is None
    assert payload["error_code"] == "CLI_ARGUMENT_INVALID"
    assert err.getvalue().strip() == "CLI:CLI_ARGUMENT_INVALID"


def test_argparse_skips_config_value_looking_like_command(tmp_path: Path) -> None:
    root, config = _root_and_config(tmp_path)
    # --config value is literally "status"; real command is history + unknown option
    decoy = root / "status"
    decoy.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
    argv = [
        "--config",
        str(decoy),
        "--project-root",
        str(root),
        "history",
        "--unknown-flag",
        "1",
    ]
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, stdout=out, stderr=err)
    assert code == 2
    payload = _parse_stdout(out)
    assert payload["command"] == "history"
    assert payload["error_code"] == "CLI_ARGUMENT_INVALID"
    assert err.getvalue().strip() == "CLI:CLI_ARGUMENT_INVALID"
    assert str(decoy) not in out.getvalue()
    assert str(decoy) not in err.getvalue()


def test_config_symlink_rejected(tmp_path: Path) -> None:
    root, real = _root_and_config(tmp_path)
    link = root / "link.toml"
    _require_symlink(link, real)
    out, err = io.StringIO(), io.StringIO()
    code = main(_argv(link, root, "status"), stdout=out, stderr=err)
    assert code == 2
    payload = _parse_stdout(out)
    assert payload["error_code"] == "CLI_CONFIG_INVALID"
    assert payload["command"] == "status"
    assert err.getvalue().strip() == "CLI:CLI_CONFIG_INVALID"
    assert str(link) not in out.getvalue()
    assert str(link) not in err.getvalue()


# --- connector boundaries ---


def test_status_prepare_publish_never_construct_connectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _root_and_config(tmp_path)

    def boom_ts() -> TushareConnector:
        raise AssertionError("tushare constructed")

    def boom_bs() -> BaostockConnector:
        raise AssertionError("baostock constructed")

    monkeypatch.setattr(cli_mod, "_new_tushare_connector", boom_ts)
    monkeypatch.setattr(cli_mod, "_new_baostock_connector", boom_bs)
    monkeypatch.setattr(
        cli_mod, "inspect_g1_workflow", lambda **_k: _empty_state(stages=())
    )
    result, code = _run(_argv(config, root, "status"), write_output=False)
    assert code == 0 and result.outcome == "INCOMPLETE"

    monkeypatch.setattr(
        cli_mod,
        "prepare_g1_workflow",
        lambda **_k: _empty_state(
            stages=("INDEX", "HISTORY", "REFERENCE", "PREPARE"),
            counts=G1WorkflowCountsV1(2, 10, 30, 5),
            candidate=MagicMock(primary_candidate_key="a" * 64),
            prepared=MagicMock(release_id="b" * 64),
        ),
    )
    result, code = _run(_argv(config, root, "prepare"), write_output=False)
    assert code == 0 and result.release_id == "b" * 64

    monkeypatch.setattr(
        cli_mod,
        "publish_g1_workflow",
        lambda **_k: (_ for _ in ()).throw(
            M3G1WorkflowError(
                "G1_WORKFLOW_PUBLISH_UNSUPPORTED",
                operation="PUBLISH",
                cause_category="UNSUPPORTED",
            )
        ),
    )
    monkeypatch.setattr(
        cli_mod,
        "inspect_g1_workflow",
        lambda **_k: _empty_state(
            stages=("INDEX", "HISTORY", "REFERENCE"),
            counts=G1WorkflowCountsV1(2, 10, 30, 5),
            candidate=MagicMock(primary_candidate_key="a" * 64),
        ),
    )
    result, code = _run(_argv(config, root, "publish"), write_output=False)
    assert code == 7
    assert result.error_code == "G1_WORKFLOW_PUBLISH_UNSUPPORTED"


def test_status_incomplete_exit_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, config = _root_and_config(tmp_path)
    monkeypatch.setattr(
        cli_mod,
        "inspect_g1_workflow",
        lambda **_k: _empty_state(stages=("INDEX",)),
    )
    monkeypatch.setattr(
        cli_mod,
        "_new_tushare_connector",
        lambda: (_ for _ in ()).throw(AssertionError("no ts")),
    )
    monkeypatch.setattr(
        cli_mod,
        "_new_baostock_connector",
        lambda: (_ for _ in ()).throw(AssertionError("no bs")),
    )
    out, err = io.StringIO(), io.StringIO()
    code = main(_argv(config, root, "status"), stdout=out, stderr=err)
    assert code == 0
    payload = _parse_stdout(out)
    assert payload["outcome"] == "INCOMPLETE"
    assert payload["completed_stages"] == ["INDEX"]
    assert payload["error_code"] is None
    assert err.getvalue() == ""


def test_history_without_index_no_connector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _root_and_config(tmp_path)
    constructed: list[str] = []

    def ts() -> TushareConnector:
        constructed.append("ts")
        return TushareConnector(pro_client=object())

    monkeypatch.setattr(cli_mod, "_new_tushare_connector", ts)
    monkeypatch.setattr(
        cli_mod,
        "inspect_g1_workflow",
        lambda **_k: _empty_state(stages=()),
    )

    def history(**_k: Any) -> Any:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_INDEX_INCOMPLETE",
            operation="HISTORY",
            cause_category="JOURNAL",
        )

    # CLI should still construct tushare for history command per task
    # (index/history instantiate Tushare). But if we want precondition check
    # before connector — task says index/history 只实例化 Tushare.
    # So connector IS constructed for history. Test single-command does not
    # auto-fill INDEX: workflow raises INDEX_INCOMPLETE.
    monkeypatch.setattr(cli_mod, "run_g1_history_stage", history)
    result, code = _run(_argv(config, root, "history"), write_output=False)
    assert result.outcome == "FAILED"
    assert result.error_code == "G1_WORKFLOW_INDEX_INCOMPLETE"
    assert code == 4
    assert constructed == ["ts"]


def test_index_instantiates_only_tushare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _root_and_config(tmp_path)
    hits: list[str] = []

    def ts() -> TushareConnector:
        hits.append("ts")
        return TushareConnector(pro_client=object())

    def bs() -> BaostockConnector:
        hits.append("bs")
        raise AssertionError("baostock must not construct")

    monkeypatch.setattr(cli_mod, "_new_tushare_connector", ts)
    monkeypatch.setattr(cli_mod, "_new_baostock_connector", bs)
    monkeypatch.setattr(
        cli_mod,
        "run_g1_index_stage",
        lambda **_k: _empty_state(stages=("INDEX",)),
    )
    result, code = _run(_argv(config, root, "index"), write_output=False)
    assert code == 0
    assert result.outcome == "SUCCESS"
    assert result.completed_stages == ("INDEX",)
    assert hits == ["ts"]


def test_reference_instantiates_only_baostock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _root_and_config(tmp_path)
    hits: list[str] = []

    monkeypatch.setattr(
        cli_mod,
        "_new_tushare_connector",
        lambda: (_ for _ in ()).throw(AssertionError("no ts")),
    )

    def bs() -> BaostockConnector:
        hits.append("bs")
        return BaostockConnector(client=object())

    monkeypatch.setattr(cli_mod, "_new_baostock_connector", bs)
    monkeypatch.setattr(
        cli_mod,
        "run_g1_reference_stage",
        lambda **_k: _empty_state(
            stages=("INDEX", "HISTORY", "REFERENCE"),
            counts=G1WorkflowCountsV1(2, 10, 30, 5),
            candidate=MagicMock(primary_candidate_key="c" * 64),
        ),
    )
    result, code = _run(_argv(config, root, "reference"), write_output=False)
    assert code == 0
    assert result.outcome == "SUCCESS"
    assert hits == ["bs"]
    assert result.primary_candidate_key == "c" * 64
    assert result.release_id is None


def test_run_all_stop_after_and_lazy_connectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _root_and_config(tmp_path)
    hits: list[str] = []

    monkeypatch.setattr(
        cli_mod,
        "_new_tushare_connector",
        lambda: hits.append("ts") or TushareConnector(pro_client=object()),
    )
    monkeypatch.setattr(
        cli_mod,
        "_new_baostock_connector",
        lambda: hits.append("bs") or BaostockConnector(client=object()),
    )
    monkeypatch.setattr(
        cli_mod,
        "inspect_g1_workflow",
        lambda **_k: _empty_state(stages=()),
    )
    monkeypatch.setattr(
        cli_mod,
        "run_g1_index_stage",
        lambda **_k: _empty_state(stages=("INDEX",)),
    )
    result, code = _run(
        _argv(config, root, "run-all", "--stop-after", "INDEX"),
        write_output=False,
    )
    assert code == 0
    assert result.outcome == "SUCCESS"
    assert result.completed_stages == ("INDEX",)
    assert hits == ["ts"]
    assert "bs" not in hits


def test_run_all_mid_failure_no_later_connector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _root_and_config(tmp_path)
    hits: list[str] = []

    monkeypatch.setattr(
        cli_mod,
        "_new_tushare_connector",
        lambda: hits.append("ts") or TushareConnector(pro_client=object()),
    )
    monkeypatch.setattr(
        cli_mod,
        "_new_baostock_connector",
        lambda: hits.append("bs") or BaostockConnector(client=object()),
    )
    monkeypatch.setattr(
        cli_mod, "inspect_g1_workflow", lambda **_k: _empty_state(stages=("INDEX",))
    )
    monkeypatch.setattr(
        cli_mod,
        "run_g1_history_stage",
        lambda **_k: (_ for _ in ()).throw(
            M3G1WorkflowError(
                "G1_WORKFLOW_EXECUTION_FAILED",
                operation="HISTORY",
                cause_category="NETWORK",
            )
        ),
    )
    result, code = _run(
        _argv(config, root, "run-all", "--stop-after", "REFERENCE"),
        write_output=False,
    )
    assert code == 4
    assert result.error_code == "G1_WORKFLOW_EXECUTION_FAILED"
    assert hits == ["ts"]
    assert "bs" not in hits


def test_run_all_resume_skips_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _root_and_config(tmp_path)
    calls: list[str] = []

    monkeypatch.setattr(
        cli_mod,
        "inspect_g1_workflow",
        lambda **_k: _empty_state(
            stages=("INDEX", "HISTORY"),
            counts=G1WorkflowCountsV1(2, 10, 0, 5),
            candidate=MagicMock(primary_candidate_key="d" * 64),
        ),
    )

    def index(**_k: Any) -> Any:
        calls.append("index")
        raise AssertionError("should skip")

    def history(**_k: Any) -> Any:
        calls.append("history")
        raise AssertionError("should skip")

    def reference(**_k: Any) -> Any:
        calls.append("reference")
        return _empty_state(
            stages=("INDEX", "HISTORY", "REFERENCE"),
            counts=G1WorkflowCountsV1(2, 10, 30, 5),
            candidate=MagicMock(primary_candidate_key="d" * 64),
        )

    monkeypatch.setattr(cli_mod, "run_g1_index_stage", index)
    monkeypatch.setattr(cli_mod, "run_g1_history_stage", history)
    monkeypatch.setattr(cli_mod, "run_g1_reference_stage", reference)
    monkeypatch.setattr(
        cli_mod,
        "_new_baostock_connector",
        lambda: BaostockConnector(client=object()),
    )
    result, code = _run(
        _argv(config, root, "run-all", "--stop-after", "REFERENCE"),
        write_output=False,
    )
    assert code == 0
    assert calls == ["reference"]
    assert result.completed_stages == ("INDEX", "HISTORY", "REFERENCE")


def test_prepare_twice_identity_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _root_and_config(tmp_path)
    cand = MagicMock(primary_candidate_key="e" * 64)
    prep = MagicMock(release_id="f" * 64)
    state = _empty_state(
        stages=("INDEX", "HISTORY", "REFERENCE", "PREPARE"),
        counts=G1WorkflowCountsV1(2, 10, 30, 5),
        candidate=cand,
        prepared=prep,
    )
    monkeypatch.setattr(cli_mod, "prepare_g1_workflow", lambda **_k: state)
    monkeypatch.setattr(
        cli_mod,
        "_new_tushare_connector",
        lambda: (_ for _ in ()).throw(AssertionError()),
    )
    a, ca = _run(_argv(config, root, "prepare"), write_output=False)
    b, cb = _run(_argv(config, root, "prepare"), write_output=False)
    assert ca == cb == 0
    assert a.primary_candidate_key == b.primary_candidate_key == "e" * 64
    assert a.release_id == b.release_id == "f" * 64
    assert a.manifest_sha256 is None


def test_publish_unsupported_exit_7(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _root_and_config(tmp_path)
    publisher_called = {"n": 0}

    def publish(**_k: Any) -> Any:
        publisher_called["n"] += 1
        raise M3G1WorkflowError(
            "G1_WORKFLOW_PUBLISH_UNSUPPORTED",
            operation="PUBLISH",
            cause_category="UNSUPPORTED",
        )

    monkeypatch.setattr(cli_mod, "publish_g1_workflow", publish)
    monkeypatch.setattr(
        cli_mod,
        "inspect_g1_workflow",
        lambda **_k: _empty_state(
            stages=("INDEX", "HISTORY", "REFERENCE"),
            counts=G1WorkflowCountsV1(2, 10, 30, 5),
            candidate=MagicMock(primary_candidate_key="a" * 64),
        ),
    )
    out, err = io.StringIO(), io.StringIO()
    code = main(_argv(config, root, "publish"), stdout=out, stderr=err)
    assert code == 7
    payload = _parse_stdout(out)
    assert payload["error_code"] == "G1_WORKFLOW_PUBLISH_UNSUPPORTED"
    assert payload["outcome"] == "FAILED"
    assert err.getvalue().strip() == "PUBLISH:G1_WORKFLOW_PUBLISH_UNSUPPORTED"
    assert publisher_called["n"] == 1  # CLI called workflow once; workflow gates publisher


def test_stdout_strict_json_no_paths_or_nan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _root_and_config(tmp_path)
    monkeypatch.setattr(
        cli_mod,
        "inspect_g1_workflow",
        lambda **_k: _empty_state(stages=()),
    )
    out, err = io.StringIO(), io.StringIO()
    code = main(_argv(config, root, "status"), stdout=out, stderr=err)
    assert code == 0
    raw = out.getvalue().encode("utf-8")
    assert raw.count(b"\n") == 1 or raw.endswith(b"\n")
    payload = json.loads(out.getvalue().strip())
    assert set(payload.keys()) == {
        "schema_version",
        "command",
        "outcome",
        "completed_stages",
        "index_requests",
        "history_requests",
        "reference_requests",
        "history_symbols",
        "primary_candidate_key",
        "release_id",
        "manifest_sha256",
        "error_code",
        "error_operation",
        "max_new_requests",
        "new_requests_committed",
    }
    assert payload["max_new_requests"] is None
    assert payload["new_requests_committed"] == 0
    dumped = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert "/home/" not in dumped
    assert "token" not in dumped.lower()
    assert "NaN" not in dumped


def test_redaction_failure_on_sensitive_payload() -> None:
    bad = G1CliResultV1(
        schema_version="m3-g1-cli-result-v1",
        command="status",
        outcome="FAILED",
        completed_stages=(),
        index_requests=0,
        history_requests=0,
        reference_requests=0,
        history_symbols=0,
        primary_candidate_key=None,
        release_id=None,
        manifest_sha256=None,
        error_code="CLI_INTERNAL_ERROR",
        error_operation=None,
        max_new_requests=None,
        new_requests_committed=0,
    )
    object.__setattr__(bad, "error_code", "token = secret")
    out, err = io.StringIO(), io.StringIO()
    code = cli_mod._emit(bad, 2, stdout=out, stderr=err)
    assert code == 2
    payload = _parse_stdout(out)
    assert payload["error_code"] == "OUTPUT_REDACTION_FAILED"
    assert "token = secret" not in out.getvalue()
    assert "secret" not in out.getvalue().lower()
    assert err.getvalue().strip() == "CLI:OUTPUT_REDACTION_FAILED"


def test_exit_code_matrix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, config = _root_and_config(tmp_path)
    cases = [
        ("G1_WORKFLOW_SOURCE_CONTEXT_INVALID", "INSPECT", "SOURCE_SCHEMA", "status", 3),
        ("G1_WORKFLOW_JOURNAL_INVALID", "INSPECT", "JOURNAL", "status", 3),
        ("G1_WORKFLOW_IDENTITY_MISMATCH", "INDEX", "MEMBERSHIP", "index", 3),
        ("G1_WORKFLOW_EXECUTION_FAILED", "INDEX", "NETWORK", "index", 4),
        ("G1_WORKFLOW_EXECUTION_FAILED", "REFERENCE", "REFERENCE", "reference", 5),
        ("G1_WORKFLOW_QUALITY_FAILED", "PREPARE", "CANDIDATE", "prepare", 6),
        ("G1_WORKFLOW_PUBLISH_FAILED", "PUBLISH", "RELEASE", "publish", 7),
    ]
    for code_name, op, cat, cmd, expected in cases:
        def raiser(
            *,
            _code: str = code_name,
            _op: str = op,
            _cat: str = cat,
            **_k: Any,
        ) -> Any:
            raise M3G1WorkflowError(_code, operation=_op, cause_category=_cat)  # type: ignore[arg-type]

        monkeypatch.setattr(cli_mod, "inspect_g1_workflow", raiser)
        monkeypatch.setattr(cli_mod, "run_g1_index_stage", raiser)
        monkeypatch.setattr(cli_mod, "run_g1_reference_stage", raiser)
        monkeypatch.setattr(cli_mod, "prepare_g1_workflow", raiser)
        monkeypatch.setattr(cli_mod, "publish_g1_workflow", raiser)
        monkeypatch.setattr(
            cli_mod,
            "_new_tushare_connector",
            lambda: TushareConnector(pro_client=object()),
        )
        monkeypatch.setattr(
            cli_mod,
            "_new_baostock_connector",
            lambda: BaostockConnector(client=object()),
        )
        result, exit_code = _run(_argv(config, root, cmd), write_output=False)
        assert exit_code == expected, (code_name, cmd, exit_code)
        assert result.error_code == code_name


def test_unknown_exception_maps_internal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, config = _root_and_config(tmp_path)
    monkeypatch.setattr(
        cli_mod,
        "inspect_g1_workflow",
        lambda **_k: (_ for _ in ()).throw(RuntimeError("token=/home/x boom")),
    )
    out, err = io.StringIO(), io.StringIO()
    code = main(_argv(config, root, "status"), stdout=out, stderr=err)
    assert code == 2
    payload = _parse_stdout(out)
    assert payload["error_code"] == "CLI_INTERNAL_ERROR"
    assert "token" not in out.getvalue().lower()
    assert "/home/" not in out.getvalue()
    assert err.getvalue().strip() == "CLI:CLI_INTERNAL_ERROR"


def test_run_all_default_stop_prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _root_and_config(tmp_path)
    order: list[str] = []

    monkeypatch.setattr(
        cli_mod, "inspect_g1_workflow", lambda **_k: _empty_state(stages=())
    )

    def idx(**_k: Any) -> Any:
        order.append("index")
        return _empty_state(stages=("INDEX",))

    def hist(**_k: Any) -> Any:
        order.append("history")
        return _history_result(
            _empty_state(
                stages=("INDEX", "HISTORY"),
                counts=G1WorkflowCountsV1(2, 10, 0, 5),
                candidate=MagicMock(primary_candidate_key="b" * 64),
            )
        )

    def ref(**_k: Any) -> Any:
        order.append("reference")
        return _empty_state(
            stages=("INDEX", "HISTORY", "REFERENCE"),
            counts=G1WorkflowCountsV1(2, 10, 30, 5),
            candidate=MagicMock(primary_candidate_key="b" * 64),
        )

    def prep(**_k: Any) -> Any:
        order.append("prepare")
        return _empty_state(
            stages=("INDEX", "HISTORY", "REFERENCE", "PREPARE"),
            counts=G1WorkflowCountsV1(2, 10, 30, 5),
            candidate=MagicMock(primary_candidate_key="b" * 64),
            prepared=MagicMock(release_id="c" * 64),
        )

    def pub(**_k: Any) -> Any:
        order.append("publish")
        raise AssertionError("must not publish")

    monkeypatch.setattr(cli_mod, "run_g1_index_stage", idx)
    monkeypatch.setattr(cli_mod, "run_g1_history_stage", hist)
    monkeypatch.setattr(cli_mod, "run_g1_reference_stage", ref)
    monkeypatch.setattr(cli_mod, "prepare_g1_workflow", prep)
    monkeypatch.setattr(cli_mod, "publish_g1_workflow", pub)
    monkeypatch.setattr(
        cli_mod, "_new_tushare_connector", lambda: TushareConnector(pro_client=object())
    )
    monkeypatch.setattr(
        cli_mod, "_new_baostock_connector", lambda: BaostockConnector(client=object())
    )
    result, code = _run(_argv(config, root, "run-all"), write_output=False)
    assert code == 0
    assert order == ["index", "history", "reference", "prepare"]
    assert result.release_id == "c" * 64
    assert result.manifest_sha256 is None


def test_import_isolation() -> None:
    import quant.research.m3.run_g1 as mod

    assert hasattr(mod, "main")
    assert hasattr(mod, "_classify_tushare_error")
    assert hasattr(mod, "G1CliResultV1")


def test_zero_network_status_with_socket_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _root_and_config(tmp_path)
    monkeypatch.setattr(
        cli_mod, "inspect_g1_workflow", lambda **_k: _empty_state(stages=())
    )

    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("network forbidden")

    out, err = io.StringIO(), io.StringIO()
    with patch.object(socket, "socket", boom):
        code = main(_argv(config, root, "status"), stdout=out, stderr=err)
    assert code == 0
    assert _parse_stdout(out)["outcome"] == "INCOMPLETE"


def test_status_success_when_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _root_and_config(tmp_path)
    monkeypatch.setattr(
        cli_mod,
        "inspect_g1_workflow",
        lambda **_k: _empty_state(
            stages=("INDEX", "HISTORY", "REFERENCE", "PREPARE", "PUBLISH"),
            counts=G1WorkflowCountsV1(2, 10, 30, 5),
            candidate=MagicMock(primary_candidate_key="d" * 64),
            prepared=MagicMock(release_id="e" * 64),
            published=MagicMock(
                release=MagicMock(release_id="e" * 64),
                manifest_sha256="f" * 64,
            ),
        ),
    )
    result, code = _run(_argv(config, root, "status"), write_output=False)
    assert code == 0
    assert result.outcome == "SUCCESS"
    assert result.manifest_sha256 == "f" * 64
    assert result.release_id == "e" * 64


def test_loaded_config_path_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, config = _root_and_config(tmp_path)
    seen: dict[str, Any] = {}

    def insp(*, project_root: Path, config: LoadedM3Config) -> Any:
        seen["root"] = project_root
        seen["sha"] = config.g1_config_sha256
        return _empty_state(stages=())

    monkeypatch.setattr(cli_mod, "inspect_g1_workflow", insp)
    _run(_argv(config, root, "status"), write_output=False)
    assert seen["root"] == root.resolve()
    expected = load_m3_config(config).g1_config_sha256
    assert seen["sha"] == expected


def _cli_result(**overrides: Any) -> G1CliResultV1:
    base: dict[str, Any] = {
        "schema_version": "m3-g1-cli-result-v1",
        "command": "status",
        "outcome": "INCOMPLETE",
        "completed_stages": (),
        "index_requests": 0,
        "history_requests": 0,
        "reference_requests": 0,
        "history_symbols": 0,
        "primary_candidate_key": None,
        "release_id": None,
        "manifest_sha256": None,
        "error_code": None,
        "error_operation": None,
        "max_new_requests": None,
        "new_requests_committed": 0,
    }
    base.update(overrides)
    return G1CliResultV1(**base)


def test_cli_result_rejects_illegal_hex_and_identity_lifecycle() -> None:
    with pytest.raises(ValueError):
        _cli_result(
            completed_stages=("INDEX", "HISTORY"),
            primary_candidate_key="A" * 64,  # uppercase
            history_requests=1,
            history_symbols=1,
        )
    with pytest.raises(ValueError):
        _cli_result(
            completed_stages=("INDEX", "HISTORY"),
            primary_candidate_key="a" * 63,
            history_requests=1,
            history_symbols=1,
        )
    with pytest.raises(ValueError):
        _cli_result(
            completed_stages=("INDEX", "HISTORY"),
            primary_candidate_key="z" * 64,  # non-hex
            history_requests=1,
            history_symbols=1,
        )
    with pytest.raises(ValueError):
        _cli_result(primary_candidate_key="a" * 64)  # before HISTORY
    with pytest.raises(ValueError):
        _cli_result(
            completed_stages=("INDEX", "HISTORY"),
            primary_candidate_key="a" * 64,
            release_id="b" * 64,  # too early
            history_requests=1,
            history_symbols=1,
        )
    with pytest.raises(ValueError):
        _cli_result(
            completed_stages=("INDEX", "HISTORY", "REFERENCE", "PREPARE"),
            primary_candidate_key="a" * 64,
            release_id="b" * 64,
            manifest_sha256="c" * 64,  # too early
            history_requests=1,
            reference_requests=1,
            history_symbols=1,
        )
    with pytest.raises(ValueError):
        _cli_result(
            completed_stages=("INDEX", "HISTORY", "REFERENCE", "PREPARE"),
            primary_candidate_key="a" * 64,
            # missing release_id
            history_requests=1,
            reference_requests=1,
            history_symbols=1,
        )
    with pytest.raises(ValueError):
        _cli_result(
            completed_stages=("INDEX", "HISTORY", "REFERENCE", "PREPARE", "PUBLISH"),
            primary_candidate_key="a" * 64,
            release_id="b" * 64,
            # missing manifest
            history_requests=1,
            reference_requests=1,
            history_symbols=1,
        )


def test_cli_result_rejects_illegal_error_operation_closure() -> None:
    with pytest.raises(ValueError):
        _cli_result(
            outcome="FAILED",
            error_code="G1_WORKFLOW_EXECUTION_FAILED",
            error_operation=None,
        )
    with pytest.raises(ValueError):
        _cli_result(
            outcome="FAILED",
            error_code="CLI_ARGUMENT_INVALID",
            error_operation="INSPECT",
        )
    with pytest.raises(ValueError):
        _cli_result(
            outcome="FAILED",
            error_code="G1_WORKFLOW_EXECUTION_FAILED",
            error_operation="NOT_AN_OP",  # type: ignore[arg-type]
        )


def test_cli_result_accepts_legal_identity_samples() -> None:
    assert _cli_result(
        completed_stages=("INDEX", "HISTORY"),
        primary_candidate_key="a" * 64,
        history_requests=3,
        history_symbols=2,
        outcome="SUCCESS",
        command="history",
    ).primary_candidate_key == "a" * 64
    assert _cli_result(
        completed_stages=("INDEX", "HISTORY", "REFERENCE"),
        primary_candidate_key="a" * 64,
        history_requests=3,
        reference_requests=30,
        history_symbols=2,
        outcome="SUCCESS",
        command="reference",
    ).release_id is None
    assert _cli_result(
        completed_stages=("INDEX", "HISTORY", "REFERENCE", "PREPARE"),
        primary_candidate_key="a" * 64,
        release_id="b" * 64,
        history_requests=3,
        reference_requests=30,
        history_symbols=2,
        outcome="SUCCESS",
        command="prepare",
    ).manifest_sha256 is None
    assert _cli_result(
        completed_stages=("INDEX", "HISTORY", "REFERENCE", "PREPARE", "PUBLISH"),
        primary_candidate_key="a" * 64,
        release_id="b" * 64,
        manifest_sha256="c" * 64,
        history_requests=3,
        reference_requests=30,
        history_symbols=2,
        outcome="SUCCESS",
        command="publish",
    ).manifest_sha256 == "c" * 64
    failed = _cli_result(
        outcome="FAILED",
        error_code="G1_WORKFLOW_QUALITY_FAILED",
        error_operation="PREPARE",
        command="prepare",
    )
    assert failed.error_operation == "PREPARE"
    assert _cli_result(
        outcome="FAILED",
        error_code="CLI_CONFIG_INVALID",
        error_operation=None,
        command="status",
    ).error_code == "CLI_CONFIG_INVALID"


def test_config_outside_project_rejected(tmp_path: Path) -> None:
    root, config = _root_and_config(tmp_path)
    outside = tmp_path / "outside.toml"
    outside.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    code = main(_argv(outside, root, "status"), stdout=out, stderr=err)
    assert code == 2
    payload = _parse_stdout(out)
    assert payload["error_code"] == "CLI_CONFIG_INVALID"
    assert payload["command"] == "status"
    joined = out.getvalue() + err.getvalue()
    assert str(outside) not in joined
    assert "Traceback" not in joined


def test_config_dotdot_traversal_rejected(tmp_path: Path) -> None:
    root, config = _root_and_config(tmp_path)
    outside = tmp_path / "escape.toml"
    outside.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
    traversed = root / ".." / "escape.toml"
    out, err = io.StringIO(), io.StringIO()
    code = main(_argv(traversed, root, "status"), stdout=out, stderr=err)
    assert code == 2
    payload = _parse_stdout(out)
    assert payload["error_code"] == "CLI_CONFIG_INVALID"
    joined = out.getvalue() + err.getvalue()
    assert str(outside) not in joined
    assert err.getvalue().strip() == "CLI:CLI_CONFIG_INVALID"


def test_config_ancestor_symlink_rejected(tmp_path: Path) -> None:
    root, config = _root_and_config(tmp_path)
    real_dir = root / "real_cfg"
    real_dir.mkdir()
    real_cfg = real_dir / "nested.toml"
    real_cfg.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
    link_dir = root / "link_cfg"
    _require_symlink(link_dir, real_dir, target_is_directory=True)
    linked = link_dir / "nested.toml"
    out, err = io.StringIO(), io.StringIO()
    code = main(_argv(linked, root, "status"), stdout=out, stderr=err)
    assert code == 2
    payload = _parse_stdout(out)
    assert payload["error_code"] == "CLI_CONFIG_INVALID"
    assert payload["command"] == "status"
    assert str(linked) not in out.getvalue() + err.getvalue()


def test_config_replaced_during_read_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _root_and_config(tmp_path)
    calls = {"n": 0}
    real_load = cli_mod.load_m3_config

    def flaky_load(path: Path) -> LoadedM3Config:
        calls["n"] += 1
        loaded = real_load(path)
        path.write_text(path.read_text(encoding="utf-8") + "\n# mutated\n", encoding="utf-8")
        return loaded

    monkeypatch.setattr(cli_mod, "load_m3_config", flaky_load)
    out, err = io.StringIO(), io.StringIO()
    code = main(_argv(config, root, "status"), stdout=out, stderr=err)
    assert code == 2
    payload = _parse_stdout(out)
    assert payload["error_code"] == "CLI_CONFIG_INVALID"
    assert calls["n"] == 1
    assert str(config) not in out.getvalue() + err.getvalue()


def test_config_inside_project_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, config = _root_and_config(tmp_path)
    alt = root / "custom" / "anywhere.toml"
    alt.parent.mkdir(parents=True)
    alt.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(
        cli_mod, "inspect_g1_workflow", lambda **_k: _empty_state(stages=())
    )
    result, code = _run(_argv(alt, root, "status"), write_output=False)
    assert code == 0
    assert result.outcome == "INCOMPLETE"


def test_history_max_new_requests_illegal_cli_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _root_and_config(tmp_path)
    called = {"n": 0}

    def boom(**_k: Any) -> Any:
        called["n"] += 1
        raise AssertionError("must not run history")

    monkeypatch.setattr(cli_mod, "run_g1_history_stage", boom)
    monkeypatch.setattr(
        cli_mod, "_new_tushare_connector", lambda: TushareConnector(pro_client=object())
    )
    for bad in ("0", "-1", "1.0", "True", "01"):
        out, err = io.StringIO(), io.StringIO()
        code = main(
            _argv(config, root, "history", "--max-new-requests", bad),
            stdout=out,
            stderr=err,
        )
        assert code == 2
        payload = _parse_stdout(out)
        assert payload["error_code"] == "CLI_ARGUMENT_INVALID"
        assert payload["max_new_requests"] is None
        assert payload["new_requests_committed"] == 0
    assert called["n"] == 0


def test_history_max_new_incomplete_and_success_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _root_and_config(tmp_path)
    monkeypatch.setattr(
        cli_mod, "_new_tushare_connector", lambda: TushareConnector(pro_client=object())
    )

    def incomplete(**kwargs: Any) -> Any:
        assert kwargs.get("max_new_requests") == 2
        return _history_result(
            _empty_state(stages=("INDEX",)),
            max_new_requests=2,
            new_requests_committed=2,
        )

    monkeypatch.setattr(cli_mod, "run_g1_history_stage", incomplete)
    result, code = _run(
        _argv(config, root, "history", "--max-new-requests", "2"),
        write_output=False,
    )
    assert code == 0
    assert result.outcome == "INCOMPLETE"
    assert result.completed_stages == ("INDEX",)
    assert result.max_new_requests == 2
    assert result.new_requests_committed == 2

    def done(**kwargs: Any) -> Any:
        assert kwargs.get("max_new_requests") == 3
        return _history_result(
            _empty_state(
                stages=("INDEX", "HISTORY"),
                counts=G1WorkflowCountsV1(2, 10, 0, 5),
                candidate=MagicMock(primary_candidate_key="a" * 64),
            ),
            max_new_requests=3,
            new_requests_committed=1,
        )

    monkeypatch.setattr(cli_mod, "run_g1_history_stage", done)
    result2, code2 = _run(
        _argv(config, root, "history", "--max-new-requests", "3"),
        write_output=False,
    )
    assert code2 == 0
    assert result2.outcome == "SUCCESS"
    assert result2.completed_stages == ("INDEX", "HISTORY")
    assert result2.max_new_requests == 3
    assert result2.new_requests_committed == 1


def test_p0g_status_partial_history_shape_socket_and_connector_poison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P0G: INDEX-only incomplete (partial HISTORY shape) status is exit 0, zero net/write."""
    root, config = _root_and_config(tmp_path)
    # Matches inspect after Tushare complete + CNINFO missing/partial.
    monkeypatch.setattr(
        cli_mod,
        "inspect_g1_workflow",
        lambda **_k: _empty_state(
            stages=("INDEX",),
            counts=G1WorkflowCountsV1(
                index_requests=2,
                history_requests=120,
                reference_requests=0,
                history_symbols=30,
            ),
        ),
    )
    monkeypatch.setattr(
        cli_mod,
        "_new_tushare_connector",
        lambda: (_ for _ in ()).throw(AssertionError("tushare constructed")),
    )
    monkeypatch.setattr(
        cli_mod,
        "_new_baostock_connector",
        lambda: (_ for _ in ()).throw(AssertionError("baostock constructed")),
    )
    monkeypatch.setattr(
        cli_mod,
        "_new_cninfo_connector",
        lambda: (_ for _ in ()).throw(AssertionError("cninfo constructed")),
    )
    before = {
        path: path.stat().st_mtime_ns for path in root.rglob("*") if path.is_file()
    }

    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("network forbidden")

    out, err = io.StringIO(), io.StringIO()
    with patch.object(socket, "socket", boom):
        code = main(_argv(config, root, "status"), stdout=out, stderr=err)
    assert code == 0
    payload = _parse_stdout(out)
    assert payload["outcome"] == "INCOMPLETE"
    assert payload["completed_stages"] == ["INDEX"]
    assert payload["history_requests"] == 120
    assert payload["history_symbols"] == 30
    assert payload["error_code"] is None
    after = {path: path.stat().st_mtime_ns for path in root.rglob("*") if path.is_file()}
    assert after == before
