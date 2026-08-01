from __future__ import annotations

import importlib.metadata
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import quant.research.m3.runtime_identity as identity_module
from quant.research.m3.runtime_identity import (
    M3RuntimeIdentityError,
    compute_m3_runtime_identity,
    runtime_identity_bytes,
)


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src" / "quant").mkdir(parents=True)
    (root / "configs" / "research").mkdir(parents=True)
    (root / "src" / "quant" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "configs" / "research" / "m3_qlib_example.toml").write_text(
        "version = 1\n", encoding="utf-8"
    )
    (root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    return root


def _versions(monkeypatch: pytest.MonkeyPatch, *, missing: str | None = None) -> None:
    def version(name: str) -> str:
        if name == missing:
            raise importlib.metadata.PackageNotFoundError(name)
        return f"1.0-{name}"

    monkeypatch.setattr(identity_module.importlib.metadata, "version", version)


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def test_git_clean_and_dirty_content_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    _versions(monkeypatch)
    _git("init", cwd=root)
    _git("add", ".", cwd=root)
    _git(
        "-c", "user.name=M3 Test", "-c", "user.email=m3@example.invalid",
        "commit", "-m", "fixture", cwd=root,
    )
    clean = compute_m3_runtime_identity(project_root=root)
    assert clean.code_source == "git"
    assert f"-{clean.git_commit}-clean-" in clean.code_version
    assert clean.git_dirty_content_sha256 is None

    source = root / "src" / "quant" / "module.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")
    dirty = compute_m3_runtime_identity(project_root=root)
    assert dirty.code_version != clean.code_version
    assert dirty.git_dirty_content_sha256 is not None
    first_dirty = dirty.code_version
    source.write_text("VALUE = 3\n", encoding="utf-8")
    assert compute_m3_runtime_identity(project_root=root).code_version != first_dirty


def test_git_assume_unchanged_cannot_hide_source_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    _versions(monkeypatch)
    _git("init", cwd=root)
    _git("add", ".", cwd=root)
    _git(
        "-c", "user.name=M3 Test", "-c", "user.email=m3@example.invalid",
        "commit", "-m", "fixture", cwd=root,
    )
    source = root / "src" / "quant" / "module.py"
    first = compute_m3_runtime_identity(project_root=root)
    _git("update-index", "--assume-unchanged", "src/quant/module.py", cwd=root)
    source.write_text("VALUE = 999\n", encoding="utf-8")

    hidden = compute_m3_runtime_identity(project_root=root)

    assert hidden.git_status_sha256 == first.git_status_sha256
    assert hidden.source_tree_sha256 != first.source_tree_sha256
    assert hidden.code_version != first.code_version


def test_git_ignored_python_source_is_still_identity_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    _versions(monkeypatch)
    (root / ".gitignore").write_text("src/quant/generated.py\n", encoding="utf-8")
    _git("init", cwd=root)
    _git("add", ".", cwd=root)
    _git(
        "-c", "user.name=M3 Test", "-c", "user.email=m3@example.invalid",
        "commit", "-m", "fixture", cwd=root,
    )
    first = compute_m3_runtime_identity(project_root=root)
    ignored = root / "src" / "quant" / "generated.py"
    ignored.write_text("VALUE = 1\n", encoding="utf-8")

    second = compute_m3_runtime_identity(project_root=root)

    assert second.git_status_sha256 == first.git_status_sha256
    assert second.source_tree_sha256 != first.source_tree_sha256
    assert second.code_version != first.code_version


def test_nested_source_reparse_point_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    _versions(monkeypatch)
    nested = root / "src" / "quant" / "nested"
    nested.mkdir()
    real_lstat = identity_module.os.lstat

    def marked_lstat(path: object):
        status = real_lstat(path)
        if Path(path) == nested:
            values = {
                name: getattr(status, name)
                for name in dir(status)
                if name.startswith("st_")
            }
            values["st_file_attributes"] = 0x400
            return SimpleNamespace(**values)
        return status

    monkeypatch.setattr(identity_module.os, "lstat", marked_lstat)
    with pytest.raises(M3RuntimeIdentityError) as exc:
        compute_m3_runtime_identity(project_root=root)
    assert exc.value.code == "M3_RUNTIME_IDENTITY_SOURCE_INVALID"


def test_source_fallback_and_not_installed_are_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    _versions(monkeypatch, missing="lightgbm")
    first = compute_m3_runtime_identity(project_root=root)
    second = compute_m3_runtime_identity(project_root=root)
    assert first == second
    assert first.code_source == "source-tree-fallback"
    assert first.code_version == f"m3-source-v1-{first.source_tree_sha256}"
    assert dict((item.distribution, item.version) for item in first.dependencies)[
        "lightgbm"
    ] == "NOT_INSTALLED"
    assert b"NOT_INSTALLED" in runtime_identity_bytes(first)


def test_probe_drift_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    _versions(monkeypatch)
    original = identity_module._probe
    calls = 0

    def drifting(project: Path, configs: tuple[object, ...]):
        nonlocal calls
        calls += 1
        result = original(project, configs)  # type: ignore[arg-type]
        if calls == 2:
            source = project / "src" / "quant" / "module.py"
            source.write_text("VALUE = 9\n", encoding="utf-8")
            return original(project, configs)  # type: ignore[arg-type]
        return result

    monkeypatch.setattr(identity_module, "_probe", drifting)
    with pytest.raises(M3RuntimeIdentityError) as exc:
        compute_m3_runtime_identity(project_root=root)
    assert exc.value.code == "M3_RUNTIME_IDENTITY_DRIFT"


def test_git_metadata_failure_does_not_silently_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    _versions(monkeypatch)
    (root / ".git").mkdir()

    class Result:
        returncode = 1
        stdout = b""

    monkeypatch.setattr(identity_module.subprocess, "run", lambda *a, **k: Result())
    with pytest.raises(M3RuntimeIdentityError) as exc:
        compute_m3_runtime_identity(project_root=root)
    assert exc.value.code == "M3_RUNTIME_IDENTITY_GIT_INVALID"
