"""G8C-C0 formal backtest CLI input resolver focused unit tests."""

from __future__ import annotations

import importlib
import inspect
import os
import pickle
import shutil
import socket
import stat
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

import quant.research.m3.formal_cli_resolve as resolve_module
from quant.research.m3.config import load_m3_config
from quant.research.m3.formal_cli_resolve import (
    FormalBacktestCliResolution,
    FormalCliResolveError,
    resolve_formal_backtest_cli_inputs,
)

_HEX = "a" * 64
_CONFIG_REL = PurePosixPath("configs/research/m3_qlib_example.toml")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_config() -> Any:
    return load_m3_config(_project_root() / _CONFIG_REL)


@pytest.fixture
def fs_tmp_path() -> Iterator[Path]:
    """Native host filesystem temp dir for symlink/hardlink/reparse tests."""
    temp_parent = None if os.name == "nt" else "/tmp"
    root = Path(tempfile.mkdtemp(dir=temp_parent, prefix="m3-g8c-c0-"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _fake_project(fs_root: Path, *, config_bytes: bytes | None = None) -> tuple[Path, Path, Any]:
    """Minimal project layout with a real configs/... leaf under fs_root."""
    real_root = _project_root()
    source = real_root / _CONFIG_REL
    payload = source.read_bytes() if config_bytes is None else config_bytes
    config_dir = fs_root / "configs" / "research"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "m3_qlib_example.toml"
    config_path.write_bytes(payload)
    (fs_root / "src" / "quant").mkdir(parents=True)
    (fs_root / "pyproject.toml").write_text(
        (real_root / "pyproject.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    config = load_m3_config(config_path)
    return fs_root, config_path, config


def _assert_config_fail_before_runtime(
    *,
    project_root: Path,
    config: Any,
    config_relative: PurePosixPath,
    monkeypatch: pytest.MonkeyPatch,
    marker: str = "TOKEN=secret",
) -> FormalCliResolveError:
    """Assert config-path failures short-circuit before runtime identity."""
    writes: list[str] = []
    real_open = open
    runtime_calls: list[str] = []

    def guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        text = str(mode)
        if any(flag in text for flag in ("w", "a", "x", "+")):
            writes.append(text)
            raise AssertionError("write open forbidden")
        return real_open(file, mode, *args, **kwargs)

    def boom_runtime(**_kwargs: Any) -> Any:
        runtime_calls.append("called")
        raise AssertionError("compute_m3_runtime_identity must not run")

    monkeypatch.setattr("builtins.open", guarded_open)
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(AssertionError("mkdir")))
    monkeypatch.setattr(socket, "socket", lambda *a, **k: (_ for _ in ()).throw(AssertionError("socket")))
    monkeypatch.setattr(resolve_module, "compute_m3_runtime_identity", boom_runtime)

    with pytest.raises(FormalCliResolveError) as caught:
        resolve_formal_backtest_cli_inputs(
            project_root=project_root,
            config=config,
            config_relative=config_relative,
            snapshot_id=_HEX,
            fold="fold_001",
            horizon=5,
        )
    error = caught.value
    assert error.code == "FORMAL_CLI_CONFIG_INVALID"
    assert error.exit_code == 2
    assert error.__cause__ is None
    assert error.__context__ is None
    assert runtime_calls == []
    assert writes == []
    message = str(error)
    assert marker not in message
    assert "TOKEN" not in message
    assert _HEX not in message
    assert str(project_root) not in message
    assert "\\" not in message or message == error.code
    return error


def test_public_signature_and_lazy_export() -> None:
    sig = inspect.signature(resolve_formal_backtest_cli_inputs)
    assert list(sig.parameters) == [
        "project_root",
        "config",
        "config_relative",
        "snapshot_id",
        "fold",
        "horizon",
    ]
    hints = inspect.get_annotations(
        resolve_formal_backtest_cli_inputs, eval_str=True
    )
    assert hints["config_relative"] is PurePosixPath
    public = importlib.import_module("quant.research.m3")
    assert public.FormalCliResolveError is FormalCliResolveError
    assert public.FormalBacktestCliResolution is FormalBacktestCliResolution
    assert public.resolve_formal_backtest_cli_inputs is resolve_formal_backtest_cli_inputs


def test_cold_import_does_not_load_heavy_deps() -> None:
    script = (
        "import sys\n"
        "heavy={'mlflow','qlib','lightgbm'}\n"
        "before={n.split('.',1)[0] for n in sys.modules}\n"
        "import quant.research.m3.formal_cli_resolve as m\n"
        "after={n.split('.',1)[0] for n in sys.modules}\n"
        "loaded=(after & heavy) - (before & heavy)\n"
        "assert not loaded, loaded\n"
        "assert m.resolve_formal_backtest_cli_inputs is not None\n"
    )
    env = dict(**__import__("os").environ)
    env["PYTHONPATH"] = str(_project_root() / "src")
    completed = __import__("subprocess").run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    "relative",
    [
        PurePosixPath("/configs/research/x.toml"),
        PurePosixPath("research/x.toml"),
        PurePosixPath(""),
        PurePosixPath("configs/research/research/x.toml"),
        Path("configs/research/m3_qlib_example.toml"),
    ],
)
def test_config_relative_rejects_non_exact_posix(relative: object) -> None:
    with pytest.raises(FormalCliResolveError) as caught:
        resolve_formal_backtest_cli_inputs(
            project_root=_project_root(),
            config=_load_config(),
            config_relative=relative,  # type: ignore[arg-type]
            snapshot_id=_HEX,
            fold="fold_001",
            horizon=5,
        )
    assert caught.value.exit_code == 2
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    message = str(caught.value)
    assert "\\" not in message
    assert "TOKEN" not in message
    assert str(_project_root()) not in message


def test_rejects_bool_horizon_and_bad_fold() -> None:
    config = _load_config()
    root = _project_root()
    with pytest.raises(FormalCliResolveError) as bool_horizon:
        resolve_formal_backtest_cli_inputs(
            project_root=root,
            config=config,
            config_relative=_CONFIG_REL,
            snapshot_id=_HEX,
            fold="fold_001",
            horizon=True,  # type: ignore[arg-type]
        )
    assert bool_horizon.value.exit_code == 2
    with pytest.raises(FormalCliResolveError) as bad_fold:
        resolve_formal_backtest_cli_inputs(
            project_root=root,
            config=config,
            config_relative=_CONFIG_REL,
            snapshot_id=_HEX,
            fold="fold_1",
            horizon=5,
        )
    assert bad_fold.value.exit_code == 2
    with pytest.raises(FormalCliResolveError) as bad_snap:
        resolve_formal_backtest_cli_inputs(
            project_root=root,
            config=config,
            config_relative=_CONFIG_REL,
            snapshot_id="A" * 64,
            fold="fold_001",
            horizon=5,
        )
    assert bad_snap.value.exit_code == 2


def test_old_five_parameter_call_rejected() -> None:
    with pytest.raises(TypeError):
        resolve_formal_backtest_cli_inputs(  # type: ignore[call-arg]
            project_root=_project_root(),
            config=_load_config(),
            snapshot_id=_HEX,
            fold="fold_001",
            horizon=5,
        )


def test_resolution_not_pickleable() -> None:
    with pytest.raises(TypeError):
        pickle.dumps(
            FormalBacktestCliResolution.__new__(FormalBacktestCliResolution)
        )


def test_missing_snapshot_fail_closed_zero_write(monkeypatch: pytest.MonkeyPatch) -> None:
    root = _project_root()
    config = _load_config()
    writes: list[str] = []
    real_open = open

    def guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        text = str(mode)
        if any(flag in text for flag in ("w", "a", "x", "+")):
            writes.append(text)
            raise AssertionError("write open forbidden")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", guarded_open)
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(AssertionError("mkdir")))
    monkeypatch.setattr(socket, "socket", lambda *a, **k: (_ for _ in ()).throw(AssertionError("socket")))

    with pytest.raises(FormalCliResolveError) as caught:
        resolve_formal_backtest_cli_inputs(
            project_root=root,
            config=config,
            config_relative=_CONFIG_REL,
            snapshot_id=_HEX,
            fold="fold_001",
            horizon=5,
        )
    assert caught.value.exit_code in {3, 5}
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert writes == []
    message = str(caught.value)
    assert _HEX not in message
    assert str(root) not in message


def test_config_raw_hash_mismatch(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, _config_path, config = _fake_project(fs_tmp_path)
    object.__setattr__(config, "raw_config_sha256", "b" * 64)
    _assert_config_fail_before_runtime(
        project_root=project,
        config=config,
        config_relative=_CONFIG_REL,
        monkeypatch=monkeypatch,
    )


def test_no_caller_roots_or_digest_parameters() -> None:
    params = inspect.signature(resolve_formal_backtest_cli_inputs).parameters
    assert "artifact_roots" not in params
    assert "digest" not in params
    assert "g1_receipt_path" not in params
    assert "release" not in params
    assert "frozen_config_digests" not in params


def test_rejects_leaf_symlink_before_runtime(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, real_config, config = _fake_project(fs_tmp_path)
    linked = project / "configs" / "research" / "via_link.toml"
    try:
        os.symlink(real_config, linked)
    except OSError:
        completed = __import__("subprocess").run(
            ["cmd", "/c", "mklink", str(linked), str(real_config)],
            check=False,
            capture_output=True,
            text=True,
        ) if os.name == "nt" else None
        if completed is None or completed.returncode != 0 or not linked.exists():
            pytest.skip("host does not permit leaf symlink creation")
    st = os.lstat(linked)
    assert bool(
        stat.S_ISLNK(st.st_mode)
        or (
            getattr(st, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
    )
    assert real_config.is_file() and not real_config.is_symlink()
    relative = PurePosixPath("configs/research/via_link.toml")
    _assert_config_fail_before_runtime(
        project_root=project,
        config=config,
        config_relative=relative,
        monkeypatch=monkeypatch,
    )


def test_rejects_intermediate_symlink_or_junction_before_runtime(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, _real_config, config = _fake_project(fs_tmp_path)
    real_dir = project / "configs" / "research"
    alias_parent = project / "configs" / "alias_parent"
    try:
        os.symlink(real_dir, alias_parent, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("host does not permit directory symlink creation")
        # Windows junction fallback when symlink privilege is unavailable.
        completed = __import__("subprocess").run(
            ["cmd", "/c", "mklink", "/J", str(alias_parent), str(real_dir)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 or not alias_parent.exists():
            pytest.skip("host does not permit directory symlink/junction creation")
    st = os.lstat(alias_parent)
    assert bool(
        stat.S_ISLNK(st.st_mode)
        or (
            getattr(st, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
    )
    relative = PurePosixPath("configs/alias_parent/m3_qlib_example.toml")
    _assert_config_fail_before_runtime(
        project_root=project,
        config=config,
        config_relative=relative,
        monkeypatch=monkeypatch,
    )


def test_rejects_hardlink_alias_before_runtime(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, real_config, config = _fake_project(fs_tmp_path)
    hard = project / "configs" / "research" / "hard_alias.toml"
    try:
        os.link(real_config, hard)
    except OSError:
        pytest.skip("host does not permit hardlink creation")
    assert os.lstat(real_config).st_nlink >= 2
    assert os.lstat(hard).st_nlink >= 2
    _assert_config_fail_before_runtime(
        project_root=project,
        config=config,
        config_relative=_CONFIG_REL,
        monkeypatch=monkeypatch,
    )
    _assert_config_fail_before_runtime(
        project_root=project,
        config=config,
        config_relative=PurePosixPath("configs/research/hard_alias.toml"),
        monkeypatch=monkeypatch,
    )


def test_rejects_same_bytes_inode_replace_during_stable_open(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, config_path, config = _fake_project(fs_tmp_path)
    expected = os.lstat(config_path)
    real_open = os.open
    replaced = {"done": False}

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
                # Some DrvFS remounts reuse inode numbers; force a size-stable
                # metadata drift by rewriting again with identical bytes.
                target.unlink()
                target.write_bytes(payload)
                after = os.lstat(target)
            if (after.st_dev, after.st_ino) == (expected.st_dev, expected.st_ino):
                pytest.skip("host reuses inode identity for same-bytes rewrite")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(resolve_module.os, "open", hostile_open)
    _assert_config_fail_before_runtime(
        project_root=project,
        config=config,
        config_relative=_CONFIG_REL,
        monkeypatch=monkeypatch,
    )


def test_hostile_anchor_exception_is_redacted_before_runtime(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, _config_path, config = _fake_project(fs_tmp_path)
    real_lstat = os.lstat

    def hostile_lstat(path: Any, *args: Any, **kwargs: Any) -> Any:
        text = str(path)
        if "m3_qlib_example.toml" in text.replace("\\", "/"):
            raise RuntimeError(
                "TOKEN=secret SQL=select PID=123 C:\\private "
                f"hash={_HEX} root={project}"
            )
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(resolve_module.os, "lstat", hostile_lstat)
    writes: list[str] = []
    real_open = open
    runtime_calls: list[str] = []

    def guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        text = str(mode)
        if any(flag in text for flag in ("w", "a", "x", "+")):
            writes.append(text)
            raise AssertionError("write open forbidden")
        return real_open(file, mode, *args, **kwargs)

    def boom_runtime(**_kwargs: Any) -> Any:
        runtime_calls.append("called")
        raise AssertionError("compute_m3_runtime_identity must not run")

    monkeypatch.setattr("builtins.open", guarded_open)
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(AssertionError("mkdir")))
    monkeypatch.setattr(socket, "socket", lambda *a, **k: (_ for _ in ()).throw(AssertionError("socket")))
    monkeypatch.setattr(resolve_module, "compute_m3_runtime_identity", boom_runtime)

    with pytest.raises(FormalCliResolveError) as caught:
        resolve_formal_backtest_cli_inputs(
            project_root=project,
            config=config,
            config_relative=_CONFIG_REL,
            snapshot_id=_HEX,
            fold="fold_001",
            horizon=5,
        )
    error = caught.value
    assert error.code in {
        "FORMAL_CLI_CONFIG_INVALID",
        "FORMAL_CLI_CLOSURE_DRIFT",
    }
    assert error.exit_code in {2, 5}
    assert error.__cause__ is None
    assert error.__context__ is None
    assert runtime_calls == []
    assert writes == []
    message = str(error)
    assert "TOKEN" not in message
    assert "SQL=" not in message
    assert "PID=" not in message
    assert _HEX not in message
    assert str(project) not in message
    assert "C:\\private" not in message
