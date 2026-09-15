"""Focused wiring tests for the formal tracking CLI command."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any

import pytest

from quant.research import run_m3
from quant.research.m3.formal_cli_resolve import FormalCliResolveError
from quant.research.m3.orchestration import M3StageRunnerError
from quant.research.m3.tracking_stage import FormalTrackingStageResult
from quant.research.run_m3 import main

_ID = "a" * 64
_WORK = "b" * 64
_CONFIG_REL = PurePosixPath("configs/research/m3_qlib_example.toml")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _copy_config(root: Path) -> None:
    target = root.joinpath(*_CONFIG_REL.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_project_root() / _CONFIG_REL, target)


def _argv(*, no_resume: bool = False) -> list[str]:
    result = [
        "tracking",
        "--config",
        _CONFIG_REL.as_posix(),
        "--snapshot-id",
        _ID,
        "--fold",
        "fold_001",
        "--horizon",
        "5",
    ]
    if no_resume:
        result.append("--no-resume")
    return result


def _payload(capsys: Any) -> dict[str, Any]:
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    return json.loads(captured.out)


def _resolution(config: object) -> SimpleNamespace:
    return SimpleNamespace(
        stage_root=Path("stage"),
        artifact_roots={"G8": Path("stage")},
        config=SimpleNamespace(canonical_tracking_uri="sqlite:///safe.db")
        if config is None
        else config,
        evaluation=object(),
        backtest=object(),
        fresh_context=object(),
        work_key=_WORK,
    )


def _stage_result(*, reused: bool) -> FormalTrackingStageResult:
    result = object.__new__(FormalTrackingStageResult)
    object.__setattr__(result, "reused", reused)
    return result


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    resolve_error: BaseException | None = None,
    client_error: BaseException | None = None,
    stage_error: BaseException | None = None,
    reused: bool = False,
) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"resolve": [], "client": [], "stage": []}
    loaded = SimpleNamespace(canonical_tracking_uri="sqlite:///safe.db")

    monkeypatch.setattr(run_m3, "load_m3_config", lambda _path: loaded)

    def resolve(**kwargs: Any) -> SimpleNamespace:
        calls["resolve"].append(kwargs)
        if resolve_error is not None:
            raise resolve_error
        return _resolution(loaded)

    def client(**kwargs: Any) -> object:
        calls["client"].append(kwargs)
        if client_error is not None:
            raise client_error
        return object()

    def stage(**kwargs: Any) -> FormalTrackingStageResult:
        calls["stage"].append(kwargs)
        if stage_error is not None:
            raise stage_error
        return _stage_result(reused=reused)

    monkeypatch.setattr(run_m3, "resolve_formal_tracking_cli_inputs", resolve)
    monkeypatch.setattr(run_m3, "create_mlflow_tracking_client", client)
    monkeypatch.setattr(run_m3, "run_formal_tracking_stage", stage)
    return calls


def test_tracking_success_uses_config_target_and_exact_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    _copy_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    calls = _install(monkeypatch, reused=True)

    assert main(_argv()) == 0
    assert _payload(capsys) == {
        "command": "tracking",
        "failures": [],
        "fold": "fold_001",
        "horizon": 5,
        "ok": True,
        "reused": True,
        "snapshot_id": _ID,
        "stop_stage": "tracking",
        "work_key": _WORK,
    }
    assert len(calls["resolve"]) == len(calls["client"]) == len(calls["stage"]) == 1
    assert calls["resolve"][0]["config_relative"] == _CONFIG_REL
    assert calls["client"][0] == {"tracking_uri": "sqlite:///safe.db"}
    stage = calls["stage"][0]
    assert stage["resume"] is True
    assert stage["client"] is not None
    assert "tracking_uri" not in json.dumps(_payload_after_empty(capsys))


def _payload_after_empty(capsys: Any) -> dict[str, object]:
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    return {}


def test_no_resume_and_stage_failure_are_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    _copy_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    calls = _install(
        monkeypatch,
        stage_error=M3StageRunnerError("STAGE_ALREADY_COMPLETE"),
    )

    assert main(_argv(no_resume=True)) == 5
    payload = _payload(capsys)
    assert payload["failures"][0]["error_code"] == "STAGE_ALREADY_COMPLETE"
    assert calls["stage"][0]["resume"] is False


@pytest.mark.parametrize(
    ("error", "expected", "exit_code"),
    [
        (FormalCliResolveError("FORMAL_CLI_UPSTREAM_INVALID", 3), "FORMAL_CLI_UPSTREAM_INVALID", 3),
        (RuntimeError("hostile"), "M3_COMMAND_FAILED", 5),
    ],
)
def test_resolve_failure_short_circuits_client_and_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    error: BaseException,
    expected: str,
    exit_code: int,
) -> None:
    _copy_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    calls = _install(monkeypatch, resolve_error=error)

    assert main(_argv()) == exit_code
    payload = _payload(capsys)
    assert payload["failures"][0]["error_code"] == expected
    assert calls["client"] == []
    assert calls["stage"] == []


@pytest.mark.parametrize(
    ("error", "expected", "exit_code"),
    [
        (ModuleNotFoundError("mlflow"), "FORMAL_CLI_DEPENDENCY_UNAVAILABLE", 4),
        (RuntimeError("TOKEN=/secret"), "M3_COMMAND_FAILED", 5),
    ],
)
def test_client_failure_is_sanitized_and_stage_is_not_called(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    error: BaseException,
    expected: str,
    exit_code: int,
) -> None:
    _copy_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    calls = _install(monkeypatch, client_error=error)

    assert main(_argv()) == exit_code
    raw = json.dumps(_payload(capsys))
    assert expected in raw
    assert "TOKEN" not in raw and "/secret" not in raw
    assert calls["stage"] == []


def test_parser_surface_and_cold_import_stay_narrow() -> None:
    parser = run_m3.build_parser()
    parsed = parser.parse_args(_argv())
    assert parsed.command == "tracking"
    for forbidden in ("stage_root", "artifact_roots", "work_key", "tracking_uri", "client"):
        assert not hasattr(parsed, forbidden)

    script = (
        "import sys\n"
        "heavy={'mlflow','qlib','lightgbm'}\n"
        "before={n.split('.',1)[0] for n in sys.modules}\n"
        "import quant.research.run_m3 as m\n"
        "after={n.split('.',1)[0] for n in sys.modules}\n"
        "assert not ((after & heavy) - (before & heavy))\n"
        "assert 'tracking' in m._PUBLIC_COMMANDS\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_project_root() / "src")
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
