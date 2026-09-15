"""G8C-C1 formal backtest CLI wiring focused unit tests."""

from __future__ import annotations

import datetime as dt
import inspect
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any

import pytest

from quant.backtest.a_share_execution import resolve_a_share_order_quantity_rule
from quant.research import run_m3
from quant.research.m3.backtest_stage import FormalBacktestStageResult
from quant.research.m3.config import load_m3_config
from quant.research.m3.formal_cli_resolve import FormalCliResolveError
from quant.research.m3.orchestration import M3StageRunnerError
from quant.research.run_m3 import main
from tests.support.m3_formal_public_chain.g1_inputs import (
    _execution_compatible_symbols,
)

_ID = "a" * 64
_WORK = "b" * 64
_CONFIG_REL = PurePosixPath("configs/research/m3_qlib_example.toml")
_C0_PAIRS = (
    ("FORMAL_CLI_INPUT_INVALID", 2),
    ("FORMAL_CLI_CONFIG_INVALID", 2),
    ("FORMAL_CLI_RUNTIME_IDENTITY_INVALID", 2),
    ("FORMAL_CLI_G1_INVALID", 3),
    ("FORMAL_CLI_UPSTREAM_INVALID", 3),
    ("FORMAL_CLI_DEPENDENCY_UNAVAILABLE", 4),
    ("FORMAL_CLI_ARTIFACT_MISSING", 5),
    ("FORMAL_CLI_CLOSURE_DRIFT", 5),
)
_STAGE_CODES = (
    "STAGE_INPUT_INVALID",
    "STAGE_LOCK_FAILED",
    "STAGE_BUILD_FAILED",
    "STAGE_OUTPUT_INVALID",
    "STAGE_PUBLISH_FAILED",
    "STAGE_RECOVERY_CONFLICT",
    "STAGE_ALREADY_COMPLETE",
)


def test_public_chain_g1_symbols_are_execution_compatible() -> None:
    symbols = _execution_compatible_symbols()
    assert len(symbols) == len(set(symbols)) == 300
    for symbol in symbols:
        resolve_a_share_order_quantity_rule(symbol=symbol, date=dt.date(2016, 2, 1))


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _argv(
    config: str,
    *,
    snapshot_id: str = _ID,
    fold: str = "fold_001",
    horizon: str = "5",
    no_resume: bool = False,
) -> list[str]:
    argv = [
        "backtest",
        "--config",
        config,
        "--snapshot-id",
        snapshot_id,
        "--fold",
        fold,
        "--horizon",
        horizon,
    ]
    if no_resume:
        argv.append("--no-resume")
    return argv


def _payload(capsys: Any) -> dict[str, Any]:
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    return json.loads(captured.out)


def _failure(payload: dict[str, Any]) -> dict[str, Any]:
    assert payload["ok"] is False
    assert payload["command"] == "backtest"
    assert len(payload["failures"]) == 1
    return payload["failures"][0]


@pytest.fixture
def fs_tmp_path() -> Iterator[Path]:
    temp_parent = None if os.name == "nt" else "/tmp"
    root = Path(tempfile.mkdtemp(dir=temp_parent, prefix="m3-g8c-c1-"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _copy_example_config(root: Path) -> Path:
    target = root.joinpath(*_CONFIG_REL.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    source = _project_root() / _CONFIG_REL
    shutil.copyfile(source, target)
    return target


def _fake_project(fs_root: Path) -> Path:
    _copy_example_config(fs_root)
    (fs_root / "src" / "quant").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_project_root() / "pyproject.toml", fs_root / "pyproject.toml")
    return fs_root


def _shell_stage_result(*, reused: bool) -> FormalBacktestStageResult:
    result = object.__new__(FormalBacktestStageResult)
    object.__setattr__(result, "final_root", Path("final"))
    object.__setattr__(result, "receipt_path", Path("receipt"))
    object.__setattr__(result, "verified", object())
    object.__setattr__(result, "receipt", object())
    object.__setattr__(result, "reused", reused)
    return result


def _resolution(*, config: object, work_key: str = _WORK) -> SimpleNamespace:
    return SimpleNamespace(
        stage_root=Path("stage"),
        target=object(),
        plan=object(),
        release=object(),
        experiment=object(),
        config=config,
        fresh_context=object(),
        artifact_roots={"G8": Path("stage")},
        work_key=work_key,
    )


def _patch_wiring(
    monkeypatch: pytest.MonkeyPatch,
    *,
    resolution: SimpleNamespace | None = None,
    reused: bool = False,
    stage_error: BaseException | None = None,
) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"load": [], "resolve": [], "stage": []}

    def load(path: Path) -> object:
        calls["load"].append(path)
        return object() if resolution is None else resolution.config

    def resolve(**kwargs: Any) -> SimpleNamespace:
        calls["resolve"].append(kwargs)
        return resolution if resolution is not None else _resolution(config=kwargs["config"])

    def stage(**kwargs: Any) -> FormalBacktestStageResult:
        calls["stage"].append(kwargs)
        if stage_error is not None:
            raise stage_error
        return _shell_stage_result(reused=reused)

    monkeypatch.setattr(run_m3, "load_m3_config", load)
    monkeypatch.setattr(run_m3, "resolve_formal_backtest_cli_inputs", resolve)
    monkeypatch.setattr(run_m3, "run_formal_backtest_stage", stage)
    return calls


def test_cold_import_does_not_load_heavy_deps() -> None:
    script = (
        "import sys\n"
        "heavy={'mlflow','qlib','lightgbm'}\n"
        "before={n.split('.',1)[0] for n in sys.modules}\n"
        "import quant.research.run_m3 as m\n"
        "after={n.split('.',1)[0] for n in sys.modules}\n"
        "loaded=(after & heavy) - (before & heavy)\n"
        "assert not loaded, loaded\n"
        "assert 'backtest' in m._PUBLIC_COMMANDS\n"
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


def test_source_has_no_tracking_or_resolution_cli_entry() -> None:
    source = inspect.getsource(run_m3._dispatch_formal_backtest)
    assert "run_formal_tracking_stage" not in source
    assert "mlflow" not in source.lower()
    parser_source = inspect.getsource(run_m3.build_parser)
    backtest_block = parser_source.split('backtest = subparsers.add_parser("backtest")', 1)[1]
    backtest_block = backtest_block.split("run_all = subparsers.add_parser", 1)[0]
    for forbidden in (
        "stage-root",
        "artifact-roots",
        "work-key",
        "experiment-key",
        "resolution",
        "tracking-uri",
        "mlflow",
    ):
        assert forbidden not in backtest_block


def test_exact_call_order_identity_and_default_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    _copy_example_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    loaded = object()
    resolution = _resolution(config=loaded)
    calls = _patch_wiring(monkeypatch, resolution=resolution, reused=False)

    def load(path: Path) -> object:
        calls["load"].append(path)
        return loaded

    monkeypatch.setattr(run_m3, "load_m3_config", load)
    code = main(_argv(_CONFIG_REL.as_posix()))
    payload = _payload(capsys)
    assert code == 0
    assert payload == {
        "command": "backtest",
        "failures": [],
        "fold": "fold_001",
        "horizon": 5,
        "ok": True,
        "reused": False,
        "snapshot_id": _ID,
        "stop_stage": "backtest",
        "work_key": _WORK,
    }
    assert len(calls["load"]) == 1
    assert len(calls["resolve"]) == 1
    assert len(calls["stage"]) == 1
    assert calls["load"][0] == tmp_path.joinpath(*_CONFIG_REL.parts)
    resolve_kwargs = calls["resolve"][0]
    assert resolve_kwargs["project_root"] == tmp_path.resolve(strict=True)
    assert resolve_kwargs["config"] is loaded
    assert resolve_kwargs["config_relative"] == _CONFIG_REL
    assert resolve_kwargs["snapshot_id"] == _ID
    assert resolve_kwargs["fold"] == "fold_001"
    assert resolve_kwargs["horizon"] == 5
    stage_kwargs = calls["stage"][0]
    assert stage_kwargs["stage_root"] is resolution.stage_root
    assert stage_kwargs["target"] is resolution.target
    assert stage_kwargs["plan"] is resolution.plan
    assert stage_kwargs["release"] is resolution.release
    assert stage_kwargs["experiment"] is resolution.experiment
    assert stage_kwargs["config"] is loaded
    assert stage_kwargs["fresh_context"] is resolution.fresh_context
    assert stage_kwargs["artifact_roots"] is resolution.artifact_roots
    assert stage_kwargs["resume"] is True
    assert "final_root" not in payload
    assert "receipt_path" not in payload
    assert str(tmp_path) not in json.dumps(payload)


def test_no_resume_maps_boolean_and_already_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    _copy_example_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    loaded = object()
    resolution = _resolution(config=loaded)
    calls = _patch_wiring(
        monkeypatch,
        resolution=resolution,
        stage_error=M3StageRunnerError("STAGE_ALREADY_COMPLETE"),
    )

    def load(path: Path) -> object:
        calls["load"].append(path)
        return loaded

    monkeypatch.setattr(run_m3, "load_m3_config", load)
    code = main(_argv(_CONFIG_REL.as_posix(), no_resume=True))
    payload = _payload(capsys)
    assert code == 5
    assert _failure(payload) == {
        "error_code": "STAGE_ALREADY_COMPLETE",
        "exit_code": 5,
        "node_id": "backtest",
        "scope": "command",
    }
    assert calls["stage"][0]["resume"] is False


def test_independent_main_calls_are_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    _copy_example_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    loaded_first = object()
    loaded_second = object()
    loads = [loaded_first, loaded_second]
    resolutions = [
        _resolution(config=loaded_first),
        _resolution(config=loaded_second),
    ]
    results = [
        _shell_stage_result(reused=False),
        _shell_stage_result(reused=True),
    ]
    calls: dict[str, int] = {"load": 0, "resolve": 0, "stage": 0}

    def load(_path: Path) -> object:
        item = loads[calls["load"]]
        calls["load"] += 1
        return item

    def resolve(**kwargs: Any) -> SimpleNamespace:
        item = resolutions[calls["resolve"]]
        assert kwargs["config"] is item.config
        calls["resolve"] += 1
        return item

    def stage(**kwargs: Any) -> FormalBacktestStageResult:
        item = resolutions[calls["stage"]]
        assert kwargs["config"] is item.config
        assert kwargs["target"] is item.target
        result = results[calls["stage"]]
        calls["stage"] += 1
        return result

    monkeypatch.setattr(run_m3, "load_m3_config", load)
    monkeypatch.setattr(run_m3, "resolve_formal_backtest_cli_inputs", resolve)
    monkeypatch.setattr(run_m3, "run_formal_backtest_stage", stage)
    first = main(_argv(_CONFIG_REL.as_posix()))
    first_payload = _payload(capsys)
    second = main(_argv(_CONFIG_REL.as_posix()))
    second_payload = _payload(capsys)
    assert first == 0 and second == 0
    assert first_payload["reused"] is False
    assert second_payload["reused"] is True
    assert calls == {"load": 2, "resolve": 2, "stage": 2}


def test_absolute_under_root_config_is_lexically_converted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    config_path = _copy_example_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    loaded = object()
    resolution = _resolution(config=loaded)
    calls = _patch_wiring(monkeypatch, resolution=resolution)

    def load(path: Path) -> object:
        calls["load"].append(path)
        return loaded

    monkeypatch.setattr(run_m3, "load_m3_config", load)
    absolute = config_path.as_posix()
    if "\\" in absolute:
        pytest.skip("host Path.as_posix still contains backslash")
    code = main(_argv(absolute))
    payload = _payload(capsys)
    assert code == 0
    assert payload["ok"] is True
    assert calls["resolve"][0]["config_relative"] == _CONFIG_REL
    assert calls["load"][0] == tmp_path.joinpath(*_CONFIG_REL.parts)


@pytest.mark.parametrize(
    "config_arg",
    [
        "configs/../configs/research/m3_qlib_example.toml",
        "configs/./research/m3_qlib_example.toml",
        r"configs\research\m3_qlib_example.toml",
        "C:/outside/configs/research/m3_qlib_example.toml",
        "//server/share/configs/research/m3_qlib_example.toml",
        "research/m3_qlib_example.toml",
        "C:configs/research/m3_qlib_example.toml",
    ],
)
def test_lexical_config_rejects_before_load_and_stage(
    config_arg: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    monkeypatch.chdir(tmp_path)
    calls = {"load": 0, "resolve": 0, "stage": 0}

    def boom_load(_path: Path) -> object:
        calls["load"] += 1
        raise AssertionError("load must not run")

    def boom_resolve(**_kwargs: Any) -> object:
        calls["resolve"] += 1
        raise AssertionError("resolve must not run")

    def boom_stage(**_kwargs: Any) -> object:
        calls["stage"] += 1
        raise AssertionError("stage must not run")

    monkeypatch.setattr(run_m3, "load_m3_config", boom_load)
    monkeypatch.setattr(run_m3, "resolve_formal_backtest_cli_inputs", boom_resolve)
    monkeypatch.setattr(run_m3, "run_formal_backtest_stage", boom_stage)
    monkeypatch.setattr(
        Path,
        "mkdir",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("mkdir")),
    )
    code = main(_argv(config_arg))
    payload = _payload(capsys)
    assert code == 2
    assert _failure(payload)["error_code"] == "M3_CONFIG_INVALID"
    assert calls == {"load": 0, "resolve": 0, "stage": 0}
    assert not (tmp_path / "artifacts").exists()


def test_missing_config_is_invalid_and_zero_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    stage_calls: list[str] = []
    monkeypatch.setattr(
        run_m3,
        "run_formal_backtest_stage",
        lambda **_k: stage_calls.append("called"),
    )
    code = main(_argv(_CONFIG_REL.as_posix()))
    payload = _payload(capsys)
    assert code == 2
    assert _failure(payload)["error_code"] == "M3_CONFIG_INVALID"
    assert stage_calls == []
    assert not (tmp_path / "artifacts").exists()


def _assert_zero_stage(
    *,
    config_arg: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    expected_code: str,
    expected_exit: int,
) -> None:
    writes: list[str] = []
    stage_calls: list[str] = []
    real_open = open

    def guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        text = str(mode)
        if any(flag in text for flag in ("w", "a", "x", "+")):
            writes.append(text)
            raise AssertionError("write open forbidden")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", guarded_open)
    monkeypatch.setattr(
        Path,
        "mkdir",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("mkdir")),
    )
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("socket")),
    )
    monkeypatch.setattr(
        run_m3,
        "run_formal_backtest_stage",
        lambda **_k: stage_calls.append("called"),
    )
    code = main(_argv(config_arg))
    payload = _payload(capsys)
    assert code == expected_exit
    assert _failure(payload)["error_code"] == expected_code
    assert stage_calls == []
    assert writes == []


def test_leaf_symlink_is_rejected_before_stage(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    root = _fake_project(fs_tmp_path)
    real_config = root.joinpath(*_CONFIG_REL.parts)
    linked = root / "configs" / "research" / "alias.toml"
    try:
        os.symlink(real_config, linked)
    except OSError:
        pytest.skip("host does not permit leaf symlink creation")
    monkeypatch.chdir(root)
    _assert_zero_stage(
        config_arg="configs/research/alias.toml",
        monkeypatch=monkeypatch,
        capsys=capsys,
        expected_code="FORMAL_CLI_CONFIG_INVALID",
        expected_exit=2,
    )


def test_intermediate_symlink_or_junction_is_rejected_before_stage(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    root = _fake_project(fs_tmp_path)
    real_dir = root / "configs" / "research"
    alias_parent = root / "configs" / "alias"
    try:
        os.symlink(real_dir, alias_parent, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("host does not permit directory symlink creation")
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(alias_parent), str(real_dir)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 or not alias_parent.exists():
            pytest.skip("host does not permit directory symlink/junction creation")
    monkeypatch.chdir(root)
    _assert_zero_stage(
        config_arg="configs/alias/m3_qlib_example.toml",
        monkeypatch=monkeypatch,
        capsys=capsys,
        expected_code="FORMAL_CLI_CONFIG_INVALID",
        expected_exit=2,
    )


def test_hardlink_alias_is_rejected_before_stage(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    root = _fake_project(fs_tmp_path)
    real_config = root.joinpath(*_CONFIG_REL.parts)
    hard = root / "configs" / "research" / "hard_alias.toml"
    try:
        os.link(real_config, hard)
    except OSError:
        pytest.skip("host does not permit hardlink creation")
    monkeypatch.chdir(root)
    _assert_zero_stage(
        config_arg="configs/research/hard_alias.toml",
        monkeypatch=monkeypatch,
        capsys=capsys,
        expected_code="FORMAL_CLI_CONFIG_INVALID",
        expected_exit=2,
    )
    assert stat.S_ISREG(os.lstat(real_config).st_mode)


def test_same_bytes_inode_replace_during_resolve_is_zero_stage(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    root = _fake_project(fs_tmp_path)
    real_config = root.joinpath(*_CONFIG_REL.parts)
    monkeypatch.chdir(root)
    import quant.research.m3.formal_cli_resolve as resolve_module

    expected = os.lstat(real_config)
    replaced = {"done": False}
    real_open = os.open

    def hostile_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        target = Path(path)
        if (
            not replaced["done"]
            and target.name == "m3_qlib_example.toml"
            and target.parent.name == "research"
        ):
            replaced["done"] = True
            payload = target.read_bytes()
            target.unlink()
            target.write_bytes(payload)
            after = os.lstat(target)
            if (after.st_dev, after.st_ino) == (expected.st_dev, expected.st_ino):
                pytest.skip("host reuses inode identity for same-bytes rewrite")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(resolve_module.os, "open", hostile_open)
    stage_calls: list[str] = []
    monkeypatch.setattr(
        run_m3,
        "run_formal_backtest_stage",
        lambda **_k: stage_calls.append("called"),
    )
    code = main(_argv(_CONFIG_REL.as_posix()))
    payload = _payload(capsys)
    assert code == 2
    assert _failure(payload)["error_code"] == "FORMAL_CLI_CONFIG_INVALID"
    assert stage_calls == []


@pytest.mark.parametrize(("code", "exit_code"), _C0_PAIRS)
def test_c0_pairs_passthrough(
    code: str,
    exit_code: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    _copy_example_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_m3, "load_m3_config", lambda _path: object())
    monkeypatch.setattr(
        run_m3,
        "resolve_formal_backtest_cli_inputs",
        lambda **_k: (_ for _ in ()).throw(FormalCliResolveError(code, exit_code)),
    )
    stage_calls: list[str] = []
    monkeypatch.setattr(
        run_m3,
        "run_formal_backtest_stage",
        lambda **_k: stage_calls.append("called"),
    )
    result = main(_argv(_CONFIG_REL.as_posix()))
    payload = _payload(capsys)
    assert result == exit_code
    assert _failure(payload) == {
        "error_code": code,
        "exit_code": exit_code,
        "node_id": "backtest",
        "scope": "command",
    }
    assert stage_calls == []


@pytest.mark.parametrize(
    "exc",
    [
        FormalCliResolveError("FORMAL_CLI_INPUT_INVALID", 5),
        FormalCliResolveError("UNKNOWN_FORMAL_CODE", 2),
        FormalCliResolveError("TOKEN=secret", 2),
        RuntimeError("TOKEN=C:\\private\\candidate.json"),
    ],
)
def test_unknown_mismatch_and_hostile_resolve_fail_closed(
    exc: BaseException,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    _copy_example_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_m3, "load_m3_config", lambda _path: object())
    monkeypatch.setattr(
        run_m3,
        "resolve_formal_backtest_cli_inputs",
        lambda **_k: (_ for _ in ()).throw(exc),
    )
    code = main(_argv(_CONFIG_REL.as_posix()))
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert code == 5
    assert _failure(payload)["error_code"] == "M3_COMMAND_FAILED"
    assert "TOKEN" not in output
    assert "private" not in output.lower()
    assert "C:\\" not in output
    assert "/private" not in output


def test_subclass_resolve_error_is_command_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    class SubResolve(FormalCliResolveError):
        pass

    _copy_example_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_m3, "load_m3_config", lambda _path: object())
    monkeypatch.setattr(
        run_m3,
        "resolve_formal_backtest_cli_inputs",
        lambda **_k: (_ for _ in ()).throw(
            SubResolve("FORMAL_CLI_INPUT_INVALID", 2)
        ),
    )
    code = main(_argv(_CONFIG_REL.as_posix()))
    payload = _payload(capsys)
    assert code == 5
    assert _failure(payload)["error_code"] == "M3_COMMAND_FAILED"


@pytest.mark.parametrize("code", _STAGE_CODES)
def test_stage_runner_codes_map_to_exit_five(
    code: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    _copy_example_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    loaded = object()
    monkeypatch.setattr(run_m3, "load_m3_config", lambda _path: loaded)
    monkeypatch.setattr(
        run_m3,
        "resolve_formal_backtest_cli_inputs",
        lambda **_k: _resolution(config=loaded),
    )
    monkeypatch.setattr(
        run_m3,
        "run_formal_backtest_stage",
        lambda **_k: (_ for _ in ()).throw(M3StageRunnerError(code)),
    )
    result = main(_argv(_CONFIG_REL.as_posix()))
    payload = _payload(capsys)
    assert result == 5
    assert _failure(payload) == {
        "error_code": code,
        "exit_code": 5,
        "node_id": "backtest",
        "scope": "command",
    }


def test_hostile_stage_and_non_exact_result_are_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    _copy_example_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    loaded = object()
    monkeypatch.setattr(run_m3, "load_m3_config", lambda _path: loaded)
    monkeypatch.setattr(
        run_m3,
        "resolve_formal_backtest_cli_inputs",
        lambda **_k: _resolution(config=loaded),
    )

    def hostile(**_kwargs: Any) -> object:
        raise RuntimeError("TOKEN=secret Bearer abc C:\\Windows /home/u \\\\server\\share")

    monkeypatch.setattr(run_m3, "run_formal_backtest_stage", hostile)
    code = main(_argv(_CONFIG_REL.as_posix()))
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert code == 5
    assert _failure(payload)["error_code"] == "M3_COMMAND_FAILED"
    assert "TOKEN" not in output
    assert "Bearer" not in output
    assert "C:\\" not in output
    assert "/home/" not in output
    assert "\\\\server" not in output

    monkeypatch.setattr(
        run_m3,
        "run_formal_backtest_stage",
        lambda **_k: SimpleNamespace(reused=False),
    )
    code = main(_argv(_CONFIG_REL.as_posix()))
    payload = json.loads(capsys.readouterr().out)
    assert code == 5
    assert _failure(payload)["error_code"] == "M3_COMMAND_FAILED"


def test_unsafe_work_key_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    _copy_example_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    loaded = object()
    monkeypatch.setattr(run_m3, "load_m3_config", lambda _path: loaded)
    monkeypatch.setattr(
        run_m3,
        "resolve_formal_backtest_cli_inputs",
        lambda **_k: _resolution(config=loaded, work_key="C:\\private\\work"),
    )
    monkeypatch.setattr(
        run_m3,
        "run_formal_backtest_stage",
        lambda **_k: _shell_stage_result(reused=False),
    )
    code = main(_argv(_CONFIG_REL.as_posix()))
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert code == 5
    assert _failure(payload)["error_code"] == "M3_COMMAND_FAILED"
    assert "private" not in output.lower()


def test_dispatcher_stdout_is_discarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    _copy_example_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    loaded = object()
    monkeypatch.setattr(run_m3, "load_m3_config", lambda _path: loaded)

    def resolve(**_kwargs: Any) -> SimpleNamespace:
        print("TOKEN=/private/resolve")
        return _resolution(config=loaded)

    def stage(**_kwargs: Any) -> FormalBacktestStageResult:
        print("TOKEN=C:\\private\\stage")
        return _shell_stage_result(reused=False)

    monkeypatch.setattr(run_m3, "resolve_formal_backtest_cli_inputs", resolve)
    monkeypatch.setattr(run_m3, "run_formal_backtest_stage", stage)
    code = main(_argv(_CONFIG_REL.as_posix()))
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.count("\n") == 1
    assert "TOKEN" not in captured.out
    assert "private" not in captured.out
    assert captured.err == ""


def test_parser_rejects_invalid_snapshot_fold_horizon(capsys: Any) -> None:
    invalid = [
        _argv("configs/research/x.toml", snapshot_id="ZZ"),
        _argv("configs/research/x.toml", fold="fold_01"),
        _argv("configs/research/x.toml", horizon="20"),
    ]
    for argv in invalid:
        code = main(argv)
        payload = json.loads(capsys.readouterr().out)
        assert code == 2
        assert payload["failures"][0]["error_code"] == "M3_CLI_USAGE_INVALID"


def test_real_load_object_is_passed_to_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    config_path = _copy_example_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    observed: dict[str, object] = {}

    def resolve(**kwargs: Any) -> SimpleNamespace:
        observed["config"] = kwargs["config"]
        observed["relative"] = kwargs["config_relative"]
        return _resolution(config=kwargs["config"])

    monkeypatch.setattr(run_m3, "resolve_formal_backtest_cli_inputs", resolve)
    monkeypatch.setattr(
        run_m3,
        "run_formal_backtest_stage",
        lambda **_k: _shell_stage_result(reused=False),
    )
    code = main(_argv(_CONFIG_REL.as_posix()))
    payload = _payload(capsys)
    assert code == 0
    assert payload["ok"] is True
    assert observed["relative"] == _CONFIG_REL
    assert type(observed["config"]) is type(load_m3_config(config_path))
    assert observed["config"].raw_config_sha256 == load_m3_config(config_path).raw_config_sha256
