"""Unit contracts for the narrow production successor CLI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import quant.research.m3.run_successor as run_successor
from quant.research.m3.run_successor import (
    EXIT_INPUT,
    EXIT_RUNTIME,
    EXIT_SUCCESS,
    main,
)
from quant.research.m3.successor_bridge import (
    BRIDGE_INPUT_ERROR,
    BRIDGE_RUNTIME_ERROR,
    REQUEST_SCHEMA_ID,
    SuccessorBridgeError,
    SuccessorBridgeResultProjection,
    successor_bridge_result_json_bytes,
)


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _canonical(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def test_help_is_zero_request_io(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sentinel = tmp_path / "must-not-be-touched"
    code = main(["--help"])
    captured = capsys.readouterr()
    assert code == EXIT_SUCCESS
    assert "usage" in captured.out.lower() or "request" in captured.out.lower()
    assert captured.err == ""
    assert not sentinel.exists()
    assert list(tmp_path.iterdir()) == []


def test_usage_failure_emits_stable_input_code_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main([])
    captured = capsys.readouterr()
    assert code == EXIT_INPUT
    assert captured.out == ""
    assert captured.err == f"{BRIDGE_INPUT_ERROR}\n"
    assert ":" not in captured.err
    assert "\\" not in captured.err
    assert "/" not in captured.err.replace(BRIDGE_INPUT_ERROR, "")


def test_success_stdout_is_one_canonical_json_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = tmp_path / "request.json"
    request.write_bytes(b"{}")

    projection = SuccessorBridgeResultProjection(
        schema_version="m3-successor-bridge-result-v1",
        terminal_status="PASS",
        two_fold_identity="a" * 64,
        attested_at="2026-08-26T10:00:00.000000Z",
        reused=False,
        controlled_output_root="output/stage",
        fold_ids=("fold_001", "fold_002"),
        gate_names=("summary", "reproducibility", "readiness", "acceptance"),
        receipt_node_ids=("n1",),
        receipt_sha256s=("b" * 64,),
    )

    class _Result:
        pass

    monkeypatch.setattr(
        run_successor,
        "run_production_successor_bridge",
        lambda **_kwargs: _Result(),
    )
    monkeypatch.setattr(
        run_successor,
        "project_successor_bridge_result",
        lambda _result: projection,
    )

    code = main(["--request", str(request.resolve())])
    captured = capsys.readouterr()
    assert code == EXIT_SUCCESS
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert captured.out.encode("ascii") == successor_bridge_result_json_bytes(
        projection
    ) + b"\n"
    assert json.loads(captured.out)["two_fold_identity"] == "a" * 64
    assert "tmp" not in captured.out.lower()
    assert str(tmp_path) not in captured.out


@pytest.mark.parametrize(
    ("error", "exit_code", "stderr_code"),
    [
        (SuccessorBridgeError(BRIDGE_INPUT_ERROR), EXIT_INPUT, BRIDGE_INPUT_ERROR),
        (SuccessorBridgeError(BRIDGE_RUNTIME_ERROR), EXIT_RUNTIME, BRIDGE_RUNTIME_ERROR),
        (RuntimeError(r"C:\secret\path\leak.json"), EXIT_RUNTIME, BRIDGE_RUNTIME_ERROR),
        (ValueError("/tmp/absolute/request.json"), EXIT_RUNTIME, BRIDGE_RUNTIME_ERROR),
    ],
)
def test_failure_codes_are_stable_and_path_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: BaseException,
    exit_code: int,
    stderr_code: str,
) -> None:
    secret = str(tmp_path / "secret-path" / "leak.json")

    def boom(**_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(run_successor, "run_production_successor_bridge", boom)
    code = main(["--request", secret])
    captured = capsys.readouterr()
    assert code == exit_code
    assert captured.out == ""
    assert captured.err == f"{stderr_code}\n"
    assert secret not in captured.err
    assert "secret-path" not in captured.err
    assert r"C:\secret" not in captured.err
    assert "/tmp/absolute" not in captured.err


def test_raw_nonfinite_request_is_stable_input_exit_two(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Loader re-encode of raw Infinity must be INPUT/2, never runtime/3."""

    project = tmp_path / "proj"
    project.mkdir()
    fold_a = _hex("release-a")
    fold_b = _hex("release-b")
    payload = {
        "schema_id": REQUEST_SCHEMA_ID,
        "project_root": str(project.resolve()),
        "controlled_output_root": "output/stage",
        "folds": [
            {
                "fold": "fold_001",
                "config_path": "configs/fold_001.toml",
                "config_raw_sha256": _hex("raw-a"),
                "config_full_sha256": _hex("full-a"),
                "g1_release_path": f"data/clean/m3_g1/releases/{fold_a}",
                "g1_release_id": fold_a,
                "g1_release_manifest_sha256": _hex("manifest-a"),
            },
            {
                "fold": "fold_002",
                "config_path": "configs/fold_002.toml",
                "config_raw_sha256": _hex("raw-b"),
                "config_full_sha256": _hex("full-b"),
                "g1_release_path": f"data/clean/m3_g1/releases/{fold_b}",
                "g1_release_id": fold_b,
                "g1_release_manifest_sha256": _hex("manifest-b"),
            },
        ],
        "runtime_identity": {
            "code_version": "bridge-fixture-v1",
            "dependency_fingerprint_sha256": _hex("deps"),
            "provider_runtime_fingerprint_sha256": _hex("provider"),
        },
        "now": "2026-08-26T10:00:00.000000Z",
        "toolchain": {
            "python_executable": str((project / "toolchain" / "python.exe").resolve()),
            "qlib_dump_tool_path": "data/external/qlib/v0.9.7/dump_bin.py",
            "qlib_dump_tool_size_bytes": 4,
            "qlib_dump_tool_sha256": hashlib.sha256(b"dump").hexdigest(),
            "timeout_seconds": 30.0,
        },
        "resume": False,
    }
    body = _canonical(payload).decode("ascii")
    needle = '"timeout_seconds":30.0'
    assert needle in body
    request = tmp_path / "request.json"
    request.write_bytes(body.replace(needle, '"timeout_seconds":Infinity').encode("ascii"))
    secret = str(request.resolve())

    code = main(["--request", secret])
    captured = capsys.readouterr()
    assert code == EXIT_INPUT
    assert captured.out == ""
    assert captured.err == f"{BRIDGE_INPUT_ERROR}\n"
    assert secret not in captured.err
    assert str(tmp_path) not in captured.err
    assert "Infinity" not in captured.err
    assert "ValueError" not in captured.err
    assert not (project / "output" / "stage").exists()
