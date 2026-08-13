"""Owned session root, capability gate, config copy, and cleanup."""

from __future__ import annotations

import os
import platform
import shutil
import stat
import sys
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal

import pytest

from quant.data.m3_release import platform_supports_renameat2_noreplace
from quant.research.m3.config import LoadedM3Config, load_m3_config
from quant.research.m3.provider import build_provider_runtime_fingerprint
from quant.research.m3.runtime_identity import (
    M3SourceDigestV1,
    compute_m3_runtime_identity,
)

_WORKTREE = Path(__file__).resolve().parents[3]
_EXPECTED_WIN_PYTHON = Path(r"D:\Miniforge3\envs\m3chain312\python.exe")
_CONFIG_REL = PurePosixPath("configs/research/_m3_f0r2_chain_session.toml")
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_OwnedKind = Literal["file", "dir"]
_OwnedToken = tuple[int, int, _OwnedKind]


@dataclass(frozen=True)
class FormalChainLocator:
    project_root: Path
    config_relative: PurePosixPath
    snapshot_id: str
    fold: str
    horizon: int
    g1_release_id: str
    stage_root: Path
    work_key: str
    session_id: str
    config: LoadedM3Config
    code_version: str
    dependency_fingerprint_sha256: str
    provider_runtime_fingerprint_sha256: str
    owned_paths: tuple[Path, ...]
    owned_identities: tuple[tuple[Path, int, int, str], ...]
    timings: FormalChainTiming


@dataclass
class FormalChainTiming:
    stages_seconds: dict[str, float] = field(default_factory=dict)
    total_seconds: float = 0.0
    file_counts: dict[str, int] = field(default_factory=dict)


def _require_windows_m3chain312() -> None:
    if sys.platform != "win32":
        reason = (
            f"WSL/non-Windows: platform_supports_renameat2_noreplace="
            f"{platform_supports_renameat2_noreplace()} "
            f"(DrvFS/capability gate; zero chain writes)"
        )
        pytest.skip(reason)
    actual = Path(sys.executable).resolve()
    expected = _EXPECTED_WIN_PYTHON.resolve()
    if actual != expected:
        raise RuntimeError(
            f"Windows actual must use exact {expected}; got {actual}"
        )
    if not platform_supports_renameat2_noreplace():
        raise RuntimeError("Windows no-replace capability unexpectedly false")
    fp = build_provider_runtime_fingerprint()
    if fp.sha256 != (
        "8f1148c7aa7ec73e46eb7bf897488ca81b547952f4299ff073a0a8b9835cc227"
    ):
        raise RuntimeError(
            f"provider fingerprint drifted before writes: {fp.sha256}"
        )


def _write_owned_config(
    *,
    project_root: Path,
    stage_rel: str,
    signal_start: object,
    signal_end: object,
) -> Path:
    source = (project_root / "configs/research/m3_qlib_example.toml").read_text(
        encoding="utf-8"
    )
    replacements = {
        "start_date = 2016-01-04": f"start_date = {signal_start}",
        "end_date = 2026-06-26": f"end_date = {signal_end}",
        "minimum_train_sessions = 756": "minimum_train_sessions = 1",
        "minimum_cross_section_symbols = 100": "minimum_cross_section_symbols = 5",
        "train_sessions = 756": "train_sessions = 1",
        "validation_sessions = 126": "validation_sessions = 1",
        "test_sessions = 126": "test_sessions = 1",
        "step_sessions = 126": "step_sessions = 1",
        "embargo_sessions = 10": "embargo_sessions = 10",
        "minimum_scorable_coverage = 0.98": "minimum_scorable_coverage = 0.0",
        "num_boost_round = 500": "num_boost_round = 20",
        "early_stopping_rounds = 50": "early_stopping_rounds = 5",
        'artifact_root = "artifacts/research/m3"': (
            f'artifact_root = "{stage_rel}"'
        ),
        "top_k = 30": "top_k = 5",
    }
    for old, new in replacements.items():
        if source.count(old) != 1:
            raise RuntimeError(f"config template anchor missing: {old!r}")
        source = source.replace(old, new)
    path = project_root.joinpath(*_CONFIG_REL.parts)
    if path.exists():
        raise FileExistsError(path)
    path.write_text(source, encoding="utf-8")
    return path


def _is_link_or_reparse(st: os.stat_result) -> bool:
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _REPARSE)


def _regular_kind(st: os.stat_result) -> _OwnedKind | None:
    if _is_link_or_reparse(st):
        return None
    if stat.S_ISDIR(st.st_mode):
        return "dir"
    if stat.S_ISREG(st.st_mode):
        return "file"
    return None


def _entity_token(path: Path) -> _OwnedToken | None:
    """Bind (dev, ino, kind); ignore mtime/content/child writes."""
    try:
        st = os.lstat(path)
    except OSError:
        return None
    kind = _regular_kind(st)
    if kind is None:
        return None
    return (st.st_dev, st.st_ino, kind)


def _record_owned(owned: dict[Path, _OwnedToken | None], path: Path) -> None:
    token = _entity_token(path)
    if token is None:
        raise RuntimeError(f"cannot bind stable lstat identity for owned path: {path}")
    owned[path] = token


_LAST_OWNED_CLEANUP_REPORT: list[str] = []


def _skip_mismatch(path: Path, expected_kind: _OwnedKind, st: os.stat_result) -> str:
    kind = _regular_kind(st)
    if kind is None:
        return f"skip-special:{path}"
    if kind != expected_kind:
        return f"skip-type-drift:{path}"
    label = "dir" if expected_kind == "dir" else "file"
    return f"skip-changed-{label}:{path}"


def _remove_verified_dir(path: Path, *, exp_dev: int, exp_ino: int) -> None:
    shutil.rmtree(path)
    deadline = time.monotonic() + 5.0
    while True:
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            return
        if (
            _regular_kind(st) != "dir"
            or (st.st_dev, st.st_ino) != (exp_dev, exp_ino)
            or _is_link_or_reparse(st)
        ):
            raise OSError("owned dir identity drifted after rmtree")
        try:
            path.rmdir()
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)


def _owned_cleanup(owned: Mapping[Path, _OwnedToken | None]) -> list[str]:
    report: list[str] = []
    for path in sorted(owned, key=lambda p: len(p.parts), reverse=True):
        expected = owned[path]
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            report.append(f"missing:{path}")
            continue
        except OSError as exc:
            report.append(f"skip-check-error:{path}:{exc}")
            continue
        if expected is None:
            report.append(f"skip-unbound:{path}")
            continue
        exp_dev, exp_ino, exp_kind = expected
        kind = _regular_kind(st)
        if (
            kind is None
            or kind != exp_kind
            or (st.st_dev, st.st_ino) != (exp_dev, exp_ino)
        ):
            report.append(_skip_mismatch(path, exp_kind, st))
            continue
        try:
            st2 = os.lstat(path)
        except FileNotFoundError:
            report.append(f"missing:{path}")
            continue
        except OSError as exc:
            report.append(f"skip-check-error:{path}:{exc}")
            continue
        kind2 = _regular_kind(st2)
        if (
            kind2 != exp_kind
            or (st2.st_dev, st2.st_ino) != (exp_dev, exp_ino)
            or _is_link_or_reparse(st2)
        ):
            report.append(_skip_mismatch(path, exp_kind, st2))
            continue
        try:
            if exp_kind == "dir":
                _remove_verified_dir(path, exp_dev=exp_dev, exp_ino=exp_ino)
            else:
                path.unlink()
            report.append(f"removed:{path}")
        except OSError as exc:
            report.append(f"error:{path}:{exc}")
    return report


@contextmanager
def public_formal_chain_session(
    *,
    project_root: Path | None = None,
    horizon: int = 5,
    diagnostic_retain: bool = False,
) -> Iterator[FormalChainLocator]:
    """Build one honest chain; retain only when an explicit diagnostic asks."""
    if type(diagnostic_retain) is not bool:
        raise TypeError("diagnostic_retain must be bool")
    _require_windows_m3chain312()
    root = (project_root or _WORKTREE).resolve(strict=True)
    session_id = uuid.uuid4().hex[:12]
    stage_rel = f"artifacts/research/m3/_f0r2_{session_id}"
    stage_root = root / PurePosixPath(stage_rel)
    g1_parent = root / "data" / "clean" / "m3_g1" / "releases"
    config_path = root.joinpath(*_CONFIG_REL.parts)
    owned_tokens: dict[Path, _OwnedToken | None] = {}
    timings = FormalChainTiming()
    locator: FormalChainLocator | None = None
    yielded = False
    t_all = time.perf_counter()
    try:
        if stage_root.exists():
            raise FileExistsError(stage_root)
        if config_path.exists():
            raise FileExistsError(config_path)
        stage_root.mkdir(parents=True, exist_ok=False)
        _record_owned(owned_tokens, stage_root)
        if diagnostic_retain:
            print("U6_RETAIN_STAGE stage_root_created", flush=True)
        from tests.support.m3_formal_public_chain.g1_inputs import publish_mini_formal_g1
        from tests.support.m3_formal_public_chain.stage_chain import (
            publish_formal_stages_to_backtest_plan,
        )

        g1_parent.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        release = publish_mini_formal_g1(output_root=g1_parent)
        timings.stages_seconds["g1"] = time.perf_counter() - t0
        if diagnostic_retain:
            print(
                f"U6_RETAIN_STAGE g1_complete "
                f"seconds={timings.stages_seconds['g1']:.3f}",
                flush=True,
            )
        g1_root = release.release.root
        _record_owned(owned_tokens, g1_root)
        timings.file_counts["g1"] = len(list(g1_root.iterdir()))
        _write_owned_config(
            project_root=root,
            stage_rel=stage_rel,
            signal_start=release.manifest.signal_start,
            signal_end=release.manifest.signal_end,
        )
        _record_owned(owned_tokens, config_path)
        config = load_m3_config(config_path)
        raw_sha = str(config.raw_config_sha256)
        runtime = compute_m3_runtime_identity(
            project_root=root,
            config_paths=(_CONFIG_REL,),
            frozen_config_digests=(
                M3SourceDigestV1(_CONFIG_REL.as_posix(), raw_sha),
            ),
        )
        provider_fp = build_provider_runtime_fingerprint()
        chain = publish_formal_stages_to_backtest_plan(
            project_root=root,
            stage_root=stage_root,
            config=config,
            release=release,
            code_version=runtime.code_version,
            dependency_fingerprint_sha256=runtime.dependency_fingerprint_sha256,
            provider_runtime_fingerprint=provider_fp,
            horizon=horizon,
            timings=timings,
        )
        timings.total_seconds = time.perf_counter() - t_all
        if diagnostic_retain:
            print(
                f"U6_RETAIN_STAGE backtest_plan_complete "
                f"seconds={timings.total_seconds:.3f}",
                flush=True,
            )
        locator = FormalChainLocator(
            project_root=root,
            config_relative=_CONFIG_REL,
            snapshot_id=chain.snapshot_id,
            fold=chain.fold,
            horizon=horizon,
            g1_release_id=release.manifest.release_id,
            stage_root=stage_root,
            work_key=chain.work_key,
            session_id=session_id,
            config=config,
            code_version=runtime.code_version,
            dependency_fingerprint_sha256=runtime.dependency_fingerprint_sha256,
            provider_runtime_fingerprint_sha256=provider_fp.sha256,
            owned_paths=tuple(owned_tokens),
            owned_identities=tuple(
                (path, token[0], token[1], token[2])
                for path, token in owned_tokens.items()
                if token is not None
            ),
            timings=timings,
        )
        yield locator
        yielded = True
    finally:
        # Never rebind tokens before cleanup. Identity is (dev, ino, kind) from
        # create time; child writes and same-inode mtime drift must not refresh
        # a same-path replacement into an owned entity.
        if diagnostic_retain and yielded:
            _LAST_OWNED_CLEANUP_REPORT[:] = [
                f"retained:{path}" for path in owned_tokens
            ]
        else:
            _LAST_OWNED_CLEANUP_REPORT[:] = _owned_cleanup(owned_tokens)


# silence unused import for type checkers reading platform string in reports
_ = platform.system
