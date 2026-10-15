"""G8C-C0 F0 R5: honest public formal-chain + fixture-teardown residual observe."""

from __future__ import annotations

import inspect
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

import pytest
from tests.support.m3_formal_public_chain import public_formal_chain_session
from tests.support.m3_formal_public_chain import session as chain_session
from tests.support.m3_formal_public_chain.session import (
    _LAST_OWNED_CLEANUP_REPORT,
    _entity_token,
    _owned_cleanup,
)

from quant.research.m3.backtest_stage import run_formal_backtest_stage
from quant.research.m3.formal_cli_resolve import (
    FormalBacktestCliResolution,
    FormalCliResolveError,
    resolve_formal_backtest_cli_inputs,
)

_ROOT = Path(__file__).resolve().parents[2]
_VERIFY_ORDER = (
    "verify_g1_release",
    "verify_snapshot_artifact",
    "verify_provider_artifact",
    "verify_provider_validation_artifact",
    "verify_experiment_identity",
    "verify_label_artifact",
    "verify_fold_plan_artifact",
    "verify_feature_artifact",
    "verify_alignment_artifact",
    "verify_model_artifact",
    "verify_prediction_artifact",
    "verify_target_artifact",
    "verify_backtest_plan_artifact",
)


def _tree_signature(root: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    if not root.exists():
        return out
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        st = os.lstat(path)
        out[str(path.relative_to(root))] = (st.st_size, st.st_mtime_ns)
    return out


def _bindable_to_stage(resolution: FormalBacktestCliResolution) -> None:
    stage_params = set(inspect.signature(run_formal_backtest_stage).parameters)
    required = {
        "stage_root",
        "target",
        "plan",
        "release",
        "experiment",
        "config",
        "fresh_context",
        "artifact_roots",
    }
    assert required <= stage_params
    resolution_fields = {item.name for item in fields(FormalBacktestCliResolution)}
    assert required <= resolution_fields | {"artifact_roots"}
    assert resolution.stage_root.is_dir()
    assert resolution.work_key
    assert resolution.artifact_roots["G8"] == resolution.stage_root
    assert resolution.plan.manifest.work_key == resolution.work_key


def _require_distinct_inode(before: os.stat_result, after: os.stat_result, *, label: str) -> None:
    if (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino):
        raise RuntimeError(
            f"{label}: Windows/lstat identity cannot distinguish same-path replacement "
            f"(dev={before.st_dev} ino={before.st_ino}); refusing path-trust fallback"
        )


def _try_dir_link(link: Path, target: Path) -> str | None:
    try:
        os.symlink(target, link, target_is_directory=True)
        return "symlink"
    except OSError:
        if os.name != "nt":
            return None
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0 and link.exists():
            return "junction"
        return None


def _is_link_or_reparse_path(path: Path) -> bool:
    st = os.lstat(path)
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(
        stat.S_ISLNK(st.st_mode)
        or (attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    )


def test_owned_cleanup_skips_same_path_replaced_directory(tmp_path: Path) -> None:
    owned = tmp_path / "stage_root"
    owned.mkdir()
    (owned / "owned_marker.txt").write_text("owned", encoding="utf-8")
    token0 = _entity_token(owned)
    assert token0 is not None
    st0 = os.lstat(owned)
    aside = tmp_path / "owned_renamed_aside"
    owned.rename(aside)
    owned.mkdir()
    sentinel = owned / "FOREIGN_SENTINEL.txt"
    sentinel.write_text("foreign", encoding="utf-8")
    _require_distinct_inode(st0, os.lstat(owned), label="directory ABA")
    try:
        report = _owned_cleanup({owned: token0})
        assert owned.is_dir()
        assert sentinel.is_file()
        assert sentinel.read_text(encoding="utf-8") == "foreign"
        assert aside.is_dir()
        assert any(item.startswith("skip-changed-dir:") for item in report)
    finally:
        if owned.exists():
            shutil.rmtree(owned)
        if aside.exists():
            shutil.rmtree(aside)


def test_owned_cleanup_directory_identity_required_without_token_refresh(
    tmp_path: Path,
) -> None:
    source = inspect.getsource(public_formal_chain_session)
    finally_src = source.split("finally:", 1)[1]
    assert "_entity_token" not in finally_src
    assert "owned_tokens[" not in finally_src
    owned = tmp_path / "stage_root"
    owned.mkdir()
    token0 = _entity_token(owned)
    assert token0 is not None
    st0 = os.lstat(owned)
    aside = tmp_path / "aside"
    owned.rename(aside)
    owned.mkdir()
    sentinel = owned / "FOREIGN_SENTINEL.txt"
    sentinel.write_text("foreign", encoding="utf-8")
    token_now = _entity_token(owned)
    assert token_now is not None
    _require_distinct_inode(st0, os.lstat(owned), label="no-refresh directory ABA")
    assert token0 != token_now
    try:
        report = _owned_cleanup({owned: token0})
        assert owned.exists() and sentinel.exists()
        assert any(item.startswith("skip-changed-dir:") for item in report)
    finally:
        if owned.exists():
            shutil.rmtree(owned)
        if aside.exists():
            shutil.rmtree(aside)


def test_owned_cleanup_skips_same_path_replaced_file(tmp_path: Path) -> None:
    owned = tmp_path / "session.toml"
    owned.write_text("owned-config\n", encoding="utf-8")
    token0 = _entity_token(owned)
    assert token0 is not None
    st0 = os.lstat(owned)
    aside = tmp_path / "session_aside.toml"
    owned.rename(aside)
    owned.write_text("foreign-config\n", encoding="utf-8")
    _require_distinct_inode(st0, os.lstat(owned), label="file ABA")
    try:
        report = _owned_cleanup({owned: token0})
        assert owned.is_file()
        assert owned.read_text(encoding="utf-8") == "foreign-config\n"
        assert aside.is_file()
        assert any(item.startswith("skip-changed-file:") for item in report)
    finally:
        owned.unlink(missing_ok=True)
        aside.unlink(missing_ok=True)


def test_owned_cleanup_skips_type_and_link_drift(tmp_path: Path) -> None:
    dir_path = tmp_path / "was_dir"
    dir_path.mkdir()
    dir_token = _entity_token(dir_path)
    assert dir_token is not None
    dir_path.rmdir()
    dir_path.write_text("now-a-file", encoding="utf-8")
    try:
        report = _owned_cleanup({dir_path: dir_token})
        assert dir_path.is_file()
        assert any(item.startswith("skip-type-drift:") for item in report)
    finally:
        dir_path.unlink(missing_ok=True)

    file_path = tmp_path / "was_file"
    file_path.write_text("owned", encoding="utf-8")
    file_token = _entity_token(file_path)
    assert file_token is not None
    file_path.unlink()
    file_path.mkdir()
    (file_path / "keep.txt").write_text("foreign-dir", encoding="utf-8")
    try:
        report = _owned_cleanup({file_path: file_token})
        assert file_path.is_dir()
        assert (file_path / "keep.txt").is_file()
        assert any(item.startswith("skip-type-drift:") for item in report)
    finally:
        if file_path.exists():
            shutil.rmtree(file_path)

    target = tmp_path / "link_target"
    target.mkdir()
    (target / "FOREIGN_SENTINEL.txt").write_text("do-not-follow", encoding="utf-8")
    link_path = tmp_path / "was_owned_dir"
    link_path.mkdir()
    link_token = _entity_token(link_path)
    assert link_token is not None
    link_path.rmdir()
    kind = _try_dir_link(link_path, target)
    if kind is None:
        if target.exists():
            shutil.rmtree(target)
        return
    try:
        assert _is_link_or_reparse_path(link_path)
        report = _owned_cleanup({link_path: link_token})
        assert link_path.exists()
        assert (target / "FOREIGN_SENTINEL.txt").is_file()
        assert any(item.startswith("skip-special:") for item in report)
    finally:
        if link_path.exists():
            if _is_link_or_reparse_path(link_path):
                link_path.unlink()
            else:
                shutil.rmtree(link_path)
        if target.exists():
            shutil.rmtree(target)


def test_owned_cleanup_removes_unreplaced_owned_file_and_dir(tmp_path: Path) -> None:
    owned_file = tmp_path / "session.toml"
    owned_file.write_text("owned\n", encoding="utf-8")
    file_token = _entity_token(owned_file)
    assert file_token is not None
    owned_file.write_text("same-inode-mtime-drift\n", encoding="utf-8")
    assert _entity_token(owned_file) == file_token

    owned_dir = tmp_path / "stage_root"
    owned_dir.mkdir()
    dir_token = _entity_token(owned_dir)
    assert dir_token is not None
    (owned_dir / "receipts").mkdir()
    (owned_dir / "receipts" / "plan.json").write_text("{}", encoding="utf-8")
    assert _entity_token(owned_dir) == dir_token

    report = _owned_cleanup({owned_file: file_token, owned_dir: dir_token})
    assert not owned_file.exists()
    assert not owned_dir.exists()
    assert any(item.startswith(f"removed:{owned_file}") for item in report)
    assert any(item.startswith(f"removed:{owned_dir}") for item in report)


def test_owned_cleanup_retains_on_lstat_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = tmp_path / "session.toml"
    owned.write_text("keep-me\n", encoding="utf-8")
    token = _entity_token(owned)
    assert token is not None
    real_lstat = os.lstat

    def hostile_lstat(path: str | os.PathLike[str], *args: object, **kwargs: object) -> os.stat_result:
        if Path(path) == owned:
            raise OSError("hostile-lstat")
        return real_lstat(path)

    monkeypatch.setattr(chain_session.os, "lstat", hostile_lstat)
    report = _owned_cleanup({owned: token})
    assert owned.is_file()
    assert owned.read_text(encoding="utf-8") == "keep-me\n"
    assert any(item.startswith("skip-check-error:") for item in report)


def _profile_verifiers(call: object) -> tuple[FormalBacktestCliResolution, list[str]]:
    """Observe top-level verifier order via shims on formal_cli_resolve.

    Nested upstream re-verify inside another verifier goes through that module's
    own imports, so wrapping only ``formal_cli_resolve`` records exact-once
    top-level calls among the contracted 13 names. Avoids ``sys.setprofile``,
    which makes Windows resolve pathologically slow.
    """
    import quant.research.m3.formal_cli_resolve as resolve_mod

    order: list[str] = []
    originals = {name: getattr(resolve_mod, name) for name in _VERIFY_ORDER}

    def _wrap(name: str, fn: object):
        def wrapped(*args: object, **kwargs: object) -> object:
            order.append(name)
            return fn(*args, **kwargs)  # type: ignore[operator]

        return wrapped

    try:
        for name, fn in originals.items():
            setattr(resolve_mod, name, _wrap(name, fn))
        result = call()  # type: ignore[operator]
    finally:
        for name, fn in originals.items():
            setattr(resolve_mod, name, fn)
    assert isinstance(result, FormalBacktestCliResolution)
    return result, order


@pytest.fixture(scope="module")
def formal_chain_locator():
    with public_formal_chain_session(horizon=5) as locator:
        stage_root = locator.stage_root
        config_path = locator.project_root.joinpath(*locator.config_relative.parts)
        g1_root = (
            locator.project_root
            / "data"
            / "clean"
            / "m3_g1"
            / "releases"
            / locator.g1_release_id
        )
        yield locator
    leftover_f0r = list((_ROOT / "artifacts" / "research" / "m3").glob("_f0r*"))
    report = list(_LAST_OWNED_CLEANUP_REPORT)
    residual = {
        "stage_exists": stage_root.exists(),
        "config_exists": config_path.exists(),
        "g1_exists": g1_root.exists(),
        "leftover_f0r": leftover_f0r,
        "cleanup_report": report,
    }
    assert not residual["stage_exists"], residual
    assert not residual["config_exists"], residual
    assert not residual["g1_exists"], residual
    assert leftover_f0r == [], residual
    assert report, residual
    removed = "\n".join(report)
    assert f"removed:{stage_root}" in removed, residual
    assert f"removed:{config_path}" in removed, residual
    assert f"removed:{g1_root}" in removed, residual


def test_windows_actual_resolve_happy_path_zero_write_and_bindable(
    formal_chain_locator,
) -> None:
    locator = formal_chain_locator
    g1_root = (
        locator.project_root
        / "data"
        / "clean"
        / "m3_g1"
        / "releases"
        / locator.g1_release_id
    )
    before_g1 = _tree_signature(g1_root)
    before_stage = _tree_signature(locator.stage_root)

    def _once() -> FormalBacktestCliResolution:
        return resolve_formal_backtest_cli_inputs(
            project_root=locator.project_root,
            config=locator.config,
            config_relative=locator.config_relative,
            snapshot_id=locator.snapshot_id,
            fold=locator.fold,
            horizon=locator.horizon,
        )

    resolution, order = _profile_verifiers(_once)
    assert before_g1 == _tree_signature(g1_root)
    assert before_stage == _tree_signature(locator.stage_root)
    assert order == list(_VERIFY_ORDER)
    assert resolution.work_key == locator.work_key
    _bindable_to_stage(resolution)

    again, order2 = _profile_verifiers(_once)
    assert order2 == list(_VERIFY_ORDER)
    assert again.work_key == resolution.work_key
    assert again.release.manifest.release_id == resolution.release.manifest.release_id
    assert again.plan.manifest_sha256 == resolution.plan.manifest_sha256
    assert again.target.manifest_sha256 == resolution.target.manifest_sha256
    assert again.experiment.manifest_sha256 == resolution.experiment.manifest_sha256
    assert _tree_signature(g1_root) == before_g1
    assert _tree_signature(locator.stage_root) == before_stage


def test_missing_backtest_plan_receipt_fails_closed_zero_write(
    formal_chain_locator,
) -> None:
    locator = formal_chain_locator
    receipt = (
        locator.stage_root / "receipts" / "backtest_plan" / f"{locator.work_key}.json"
    )
    assert receipt.is_file()
    payload = receipt.read_bytes()
    before = _tree_signature(locator.stage_root)
    receipt.unlink()
    try:
        with pytest.raises(FormalCliResolveError) as exc:
            resolve_formal_backtest_cli_inputs(
                project_root=locator.project_root,
                config=locator.config,
                config_relative=locator.config_relative,
                snapshot_id=locator.snapshot_id,
                fold=locator.fold,
                horizon=locator.horizon,
            )
        assert exc.value.__cause__ is None
        after = _tree_signature(locator.stage_root)
        assert set(after) <= set(before)
        assert str(receipt.relative_to(locator.stage_root)) not in after
    finally:
        receipt.write_bytes(payload)


def test_config_entity_replace_fails_closed_zero_write(
    formal_chain_locator,
) -> None:
    locator = formal_chain_locator
    config_path = locator.project_root.joinpath(*locator.config_relative.parts)
    original = config_path.read_bytes()
    before_stage = _tree_signature(locator.stage_root)
    config_path.write_bytes(original + b"\n# hostile-entity-replace\n")
    try:
        with pytest.raises(FormalCliResolveError) as exc:
            resolve_formal_backtest_cli_inputs(
                project_root=locator.project_root,
                config=locator.config,
                config_relative=locator.config_relative,
                snapshot_id=locator.snapshot_id,
                fold=locator.fold,
                horizon=locator.horizon,
            )
        assert exc.value.__cause__ is None
        assert _tree_signature(locator.stage_root) == before_stage
    finally:
        config_path.write_bytes(original)


def test_runtime_code_version_drift_fails_closed_zero_write(
    formal_chain_locator,
) -> None:
    """Current runtime code_version must match snapshot request; mutate fails closed."""
    locator = formal_chain_locator
    req_dir = locator.stage_root / "snapshot-requests"
    req_paths = sorted(req_dir.glob("*.json"))
    assert len(req_paths) == 1
    req_path = req_paths[0]
    original = req_path.read_bytes()
    payload = json.loads(original)
    payload["code_version"] = "hostile-runtime-drift-" + payload["code_version"]
    req_path.write_bytes(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    )
    before = _tree_signature(locator.stage_root)
    try:
        with pytest.raises(FormalCliResolveError) as exc:
            resolve_formal_backtest_cli_inputs(
                project_root=locator.project_root,
                config=locator.config,
                config_relative=locator.config_relative,
                snapshot_id=locator.snapshot_id,
                fold=locator.fold,
                horizon=locator.horizon,
            )
        assert exc.value.__cause__ is None
        assert _tree_signature(locator.stage_root) == before
    finally:
        req_path.write_bytes(original)


def test_cross_platform_dependency_fingerprint_drift_fails_closed_zero_write(
    formal_chain_locator,
) -> None:
    """Simulate cross-platform stage reuse via dependency_fingerprint drift."""
    locator = formal_chain_locator
    runs = sorted((locator.stage_root / "runs").glob("*/experiment_manifest.json"))
    assert len(runs) == 1
    manifest_path = runs[0]
    original = manifest_path.read_bytes()
    payload = json.loads(original)
    old = payload["dependency_fingerprint_sha256"]
    payload["dependency_fingerprint_sha256"] = ("ab" * 32) if old != "ab" * 32 else "cd" * 32
    manifest_path.write_bytes(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    )
    before = _tree_signature(locator.stage_root)
    try:
        with pytest.raises(FormalCliResolveError) as exc:
            resolve_formal_backtest_cli_inputs(
                project_root=locator.project_root,
                config=locator.config,
                config_relative=locator.config_relative,
                snapshot_id=locator.snapshot_id,
                fold=locator.fold,
                horizon=locator.horizon,
            )
        assert exc.value.__cause__ is None
        assert _tree_signature(locator.stage_root) == before
    finally:
        manifest_path.write_bytes(original)


def test_wsl_capability_gate_skips_before_chain_writes() -> None:
    if sys.platform == "win32":
        pytest.skip("Windows actual path covered by happy-path fixture")
    from quant.data.m3_release import platform_supports_renameat2_noreplace

    assert platform_supports_renameat2_noreplace() is False
    markers_before = list((_ROOT / "artifacts" / "research" / "m3").glob("_f0r2_*"))
    with pytest.raises(pytest.skip.Exception), public_formal_chain_session():
        raise AssertionError("must skip before any owned write")
    assert list((_ROOT / "artifacts" / "research" / "m3").glob("_f0r2_*")) == markers_before
