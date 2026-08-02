from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant.research.run_m3 import CommandFailure, CommandSummary, main


def _argv(root: Path) -> list[str]:
    path_options = (
        "project-root",
        "config",
        "g1-release-root",
        "snapshot-artifact-root",
        "snapshot-root",
        "snapshot-request-path",
        "snapshot-receipt-path",
        "provider-artifact-root",
        "provider-root",
        "provider-receipt-path",
        "provider-validation-artifact-root",
        "provider-validation-root",
        "provider-validation-receipt-path",
        "external-qlib-root",
        "stage-root",
    )
    args = ["experiment-identity"]
    for option in path_options:
        args.extend((f"--{option}", str(root)))
    args.extend(("--provider-validation-code-version", "m3-g2c-v1"))
    return args


def test_cli_emits_one_canonical_json_with_injected_execution(
    tmp_path: Path, capsys
) -> None:
    code = main(
        _argv(tmp_path),
        execute=lambda _args: {"command": "experiment-identity", "reused": False},
    )
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert json.loads(captured.out) == {
        "command": "experiment-identity",
        "ok": True,
        "reused": False,
    }
    assert captured.out == json.dumps(
        json.loads(captured.out),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ) + "\n"


def test_cli_redacts_internal_exception_and_usage_errors(capsys) -> None:
    secret = "TOKEN=should-not-appear"

    def fail(_args):
        raise RuntimeError(secret)

    code = main(_argv(Path("fixture")), execute=fail)
    output = capsys.readouterr().out
    assert code == 5
    assert secret not in output
    assert json.loads(output) == {"error_code": "M3_COMMAND_FAILED", "ok": False}

    code = main(["experiment-identity"])
    output = capsys.readouterr().out
    assert code == 2
    assert json.loads(output) == {"error_code": "M3_CLI_USAGE_INVALID", "ok": False}


_ID = "1" * 64


@pytest.mark.parametrize(
    ("command", "identity_args", "stop_stage"),
    [
        ("readiness", ["--g1-release-id", _ID], "readiness"),
        ("snapshot", ["--g1-release-id", _ID], "snapshot"),
        (
            "train",
            ["--snapshot-id", _ID, "--fold", "fold_001", "--horizon", "5"],
            "train",
        ),
        (
            "evaluate",
            ["--snapshot-id", _ID, "--fold", "fold_001", "--horizon", "10"],
            "evaluation",
        ),
        (
            "backtest",
            ["--snapshot-id", _ID, "--fold", "fold_001", "--horizon", "5"],
            "backtest",
        ),
        ("run-all", ["--snapshot-id", _ID], "tracking"),
        (
            "verify-reproducibility",
            ["--snapshot-id", _ID, "--fold", "fold_001", "--horizon", "10"],
            "comparison",
        ),
        ("acceptance-audit", ["--snapshot-id", _ID], "acceptance"),
    ],
)
def test_public_commands_have_strict_identity_args_and_stop_points(
    command: str,
    identity_args: list[str],
    stop_stage: str,
    tmp_path: Path,
    capsys,
) -> None:
    observed: list[tuple[str, Path, str]] = []

    def dispatch(args):
        observed.append((args.command, args.config, args.stop_stage))
        return {"reused": True}

    code = main(
        [command, "--config", str(tmp_path / "m3.toml"), *identity_args],
        dispatcher=dispatch,
    )
    output = capsys.readouterr().out
    assert code == 0
    assert observed == [(command, tmp_path / "m3.toml", stop_stage)]
    assert json.loads(output) == {
        "command": command,
        "failures": [],
        "ok": True,
        "reused": True,
    }
    assert output.count("\n") == 1
    assert output == json.dumps(
        json.loads(output), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ) + "\n"


@pytest.mark.parametrize(
    "argv",
    [
        ["run-all", "--config", "m3.toml"],
        [
            "run-all",
            "--config",
            "m3.toml",
            "--g1-release-id",
            _ID,
            "--snapshot-id",
            _ID,
        ],
        ["train", "--config", "m3.toml", "--snapshot-id", _ID],
        [
            "train",
            "--config",
            "m3.toml",
            "--snapshot-id",
            _ID,
            "--fold",
            "fold_01",
            "--horizon",
            "5",
        ],
        [
            "train",
            "--config",
            "m3.toml",
            "--snapshot-id",
            _ID,
            "--fold",
            "fold_001",
            "--horizon",
            "20",
        ],
    ],
)
def test_public_usage_errors_are_code_two_before_dispatch(argv: list[str], capsys) -> None:
    calls = 0

    def dispatch(_args):
        nonlocal calls
        calls += 1
        return {}

    code = main(argv, dispatcher=dispatch)
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert calls == 0
    assert payload["ok"] is False
    assert payload["failures"] == [
        {
            "error_code": "M3_CLI_USAGE_INVALID",
            "exit_code": 2,
            "node_id": argv[0],
            "scope": "command",
        }
    ]


def test_failure_summary_is_sorted_and_uses_minimum_exit_code(capsys) -> None:
    def dispatch(_args):
        return CommandSummary(
            command="run-all",
            failures=(
                CommandFailure("work", "fold_002:10", "TRACKING_FAILED", 6),
                CommandFailure("shared", "provider", "DEPENDENCY_MISSING", 4),
                CommandFailure("work", "fold_001:5", "STAGE_FAILED", 5),
            ),
        )

    code = main(
        ["run-all", "--config", "m3.toml", "--snapshot-id", _ID],
        dispatcher=dispatch,
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 4
    assert [
        (item["scope"], item["node_id"], item["error_code"])
        for item in payload["failures"]
    ] == [
        ("shared", "provider", "DEPENDENCY_MISSING"),
        ("work", "fold_001:5", "STAGE_FAILED"),
        ("work", "fold_002:10", "TRACKING_FAILED"),
    ]


@pytest.mark.parametrize(
    "unsafe",
    [
        {"message": "Bearer private-value"},
        {"nested": [{"token": "private-value"}]},
        {"artifact": "C:\\private\\candidate.json"},
        {"artifact": "/private/candidate.json"},
        {"artifact": "//server/私有/candidate.json"},
    ],
)
def test_public_summary_and_exceptions_are_sanitized(unsafe: object, capsys) -> None:
    code = main(
        ["snapshot", "--config", "m3.toml", "--g1-release-id", _ID],
        dispatcher=lambda _args: unsafe,  # type: ignore[arg-type,return-value]
    )
    output = capsys.readouterr().out
    assert code == 5
    assert "private" not in output.lower()
    assert json.loads(output)["failures"][0]["error_code"] == "M3_COMMAND_FAILED"

    def fail(_args):
        raise RuntimeError("TOKEN=C:\\private\\candidate.json")

    code = main(
        ["snapshot", "--config", "m3.toml", "--g1-release-id", _ID],
        dispatcher=fail,
    )
    output = capsys.readouterr().out
    assert code == 5
    assert "private" not in output.lower()
    assert "TOKEN" not in output


def test_dispatcher_diagnostics_are_discarded_from_public_streams(capsys) -> None:
    def dispatch(_args):
        print("TOKEN=/private/handler")
        return {"snapshot_id": _ID}

    code = main(
        ["snapshot", "--config", "m3.toml", "--g1-release-id", _ID],
        dispatcher=dispatch,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.count("\n") == 1
    assert "TOKEN" not in captured.out
    assert "private" not in captured.out
    assert captured.err == ""


def test_dispatcher_exception_cannot_forge_error_code(capsys) -> None:
    class FakeGateError(RuntimeError):
        code = "ACCEPTANCE_GATE_PASSED"

    def fail(_args):
        raise FakeGateError("TOKEN=C:\\private\\candidate.json")

    code = main(
        ["snapshot", "--config", "m3.toml", "--g1-release-id", _ID],
        dispatcher=fail,
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 5
    assert payload["failures"][0]["error_code"] == "M3_COMMAND_FAILED"


def test_missing_public_handler_is_explicit_and_does_not_fake_artifacts(capsys) -> None:
    code = main(["readiness", "--config", "m3.toml", "--g1-release-id", _ID])
    payload = json.loads(capsys.readouterr().out)
    assert code == 5
    assert payload == {
        "command": "readiness",
        "failures": [
            {
                "error_code": "M3_COMMAND_HANDLER_UNAVAILABLE",
                "exit_code": 5,
                "node_id": "readiness",
                "scope": "command",
            }
        ],
        "ok": False,
    }
