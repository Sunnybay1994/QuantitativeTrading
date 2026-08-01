from __future__ import annotations

import importlib.metadata
import subprocess
from pathlib import Path

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
    assert clean.code_version.endswith("-clean")
    assert clean.git_dirty_content_sha256 is None

    source = root / "src" / "quant" / "module.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")
    dirty = compute_m3_runtime_identity(project_root=root)
    assert dirty.code_version != clean.code_version
    assert dirty.git_dirty_content_sha256 is not None
    first_dirty = dirty.code_version
    source.write_text("VALUE = 3\n", encoding="utf-8")
    assert compute_m3_runtime_identity(project_root=root).code_version != first_dirty


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
