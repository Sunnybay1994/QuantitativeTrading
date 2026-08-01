from __future__ import annotations

import json
from pathlib import Path

from quant.research.run_m3 import main


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
