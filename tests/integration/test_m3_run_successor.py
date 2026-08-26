"""Integration contracts for the narrow production successor CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import quant.research.m3.run_successor as run_successor
from quant.research.m3.run_successor import EXIT_INPUT, EXIT_RUNTIME, EXIT_SUCCESS, main
from quant.research.m3.successor_bridge import (
    BRIDGE_INPUT_ERROR,
    BRIDGE_RUNTIME_ERROR,
    SuccessorBridgeError,
    SuccessorBridgeResultProjection,
)


def test_cli_help_creates_no_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.rglob("*"))
    code = main(["--help"])
    after = set(tmp_path.rglob("*"))
    assert code == EXIT_SUCCESS
    assert after == before
    assert capsys.readouterr().err == ""


def test_cli_success_and_failure_boundary_with_bridge_spy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = (tmp_path / "req.json").resolve()
    request.write_bytes(b"{}")

    projection = SuccessorBridgeResultProjection(
        schema_version="m3-successor-bridge-result-v1",
        terminal_status="PASS",
        two_fold_identity="c" * 64,
        attested_at="2026-08-26T12:00:00.000000Z",
        reused=True,
        controlled_output_root="output/stage",
        fold_ids=("fold_001", "fold_002"),
        gate_names=("summary", "reproducibility", "readiness", "acceptance"),
        receipt_node_ids=("r1", "r2"),
        receipt_sha256s=("d" * 64, "e" * 64),
    )

    monkeypatch.setattr(
        run_successor,
        "run_production_successor_bridge",
        lambda **_k: object(),
    )
    monkeypatch.setattr(
        run_successor,
        "project_successor_bridge_result",
        lambda _r: projection,
    )
    code = main(["--request", str(request)])
    out = capsys.readouterr()
    assert code == EXIT_SUCCESS
    payload = json.loads(out.out)
    assert payload["reused"] is True
    assert payload["receipt_node_ids"] == ["r1", "r2"]
    assert str(tmp_path) not in out.out
    assert out.err == ""

    def boom_input(**_k: object) -> None:
        raise SuccessorBridgeError(BRIDGE_INPUT_ERROR)

    monkeypatch.setattr(run_successor, "run_production_successor_bridge", boom_input)
    code = main(["--request", str(request)])
    err = capsys.readouterr()
    assert code == EXIT_INPUT
    assert err.err == f"{BRIDGE_INPUT_ERROR}\n"
    assert str(request) not in err.err

    def boom_runtime(**_k: object) -> None:
        raise SuccessorBridgeError(BRIDGE_RUNTIME_ERROR)

    monkeypatch.setattr(run_successor, "run_production_successor_bridge", boom_runtime)
    code = main(["--request", str(request)])
    err = capsys.readouterr()
    assert code == EXIT_RUNTIME
    assert err.err == f"{BRIDGE_RUNTIME_ERROR}\n"
    assert str(request) not in err.err

    def boom_bare(**_k: object) -> None:
        raise RuntimeError(str(request))

    monkeypatch.setattr(run_successor, "run_production_successor_bridge", boom_bare)
    code = main(["--request", str(request)])
    err = capsys.readouterr()
    assert code == EXIT_RUNTIME
    assert err.err == f"{BRIDGE_RUNTIME_ERROR}\n"
    assert str(request) not in err.err
