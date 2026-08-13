"""G8C-C1 honest public-chain backtest CLI integration."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from tests.support.m3_formal_public_chain import FormalChainLocator, public_formal_chain_session
from tests.support.m3_formal_public_chain.session import _LAST_OWNED_CLEANUP_REPORT

from quant.research.run_m3 import main

_ROOT = Path(__file__).resolve().parents[2]


def _tree_signature(root: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    if not root.exists():
        return out
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        # StageRunner intentionally retains one empty advisory lock per node.
        # It is synchronization metadata, not a business artifact mutation.
        if path.name == ".writer.lock":
            continue
        st = os.lstat(path)
        # Artifact paths are canonical POSIX relative paths on every host.
        out[path.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns)
    return out


def _g1_root(locator: FormalChainLocator) -> Path:
    return (
        locator.project_root
        / "data"
        / "clean"
        / "m3_g1"
        / "releases"
        / locator.g1_release_id
    )


def test_tree_signature_excludes_persistent_advisory_lock(tmp_path: Path) -> None:
    business = tmp_path / "work" / "result.json"
    lock = tmp_path / ".stage-locks" / ("a" * 64) / ".writer.lock"
    business.parent.mkdir(parents=True)
    lock.parent.mkdir(parents=True)
    business.write_bytes(b"{}")
    lock.write_bytes(b"\x00")

    assert set(_tree_signature(tmp_path)) == {"work/result.json"}


@pytest.fixture(scope="module")
def formal_chain_locator():
    with public_formal_chain_session(horizon=5) as locator:
        stage_root = locator.stage_root
        config_path = locator.project_root.joinpath(*locator.config_relative.parts)
        g1_root = _g1_root(locator)
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


def test_wsl_capability_gate_skips_before_chain_writes() -> None:
    if sys_is_windows():
        pytest.skip("Windows actual path covered by happy-path fixture")
    from quant.data.m3_release import platform_supports_renameat2_noreplace

    assert platform_supports_renameat2_noreplace() is False
    markers_before = list((_ROOT / "artifacts" / "research" / "m3").glob("_f0r*"))
    with pytest.raises(pytest.skip.Exception), public_formal_chain_session():
        raise AssertionError("must skip before any owned write")
    assert list((_ROOT / "artifacts" / "research" / "m3").glob("_f0r*")) == markers_before


def sys_is_windows() -> bool:
    return os.name == "nt"


def test_windows_actual_cli_happy_path_zero_write_boundary_and_canonical_json(
    formal_chain_locator, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    locator = formal_chain_locator
    g1_root = _g1_root(locator)
    before_g1 = _tree_signature(g1_root)
    before_stage = _tree_signature(locator.stage_root)
    monkeypatch.chdir(locator.project_root)
    args = [
        "backtest",
        "--config",
        locator.config_relative.as_posix(),
        "--snapshot-id",
        locator.snapshot_id,
        "--fold",
        locator.fold,
        "--horizon",
        str(locator.horizon),
    ]
    code = main(args)
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    payload = json.loads(captured.out)
    assert code == 0, payload
    assert payload == {
        "command": "backtest",
        "failures": [],
        "fold": locator.fold,
        "horizon": locator.horizon,
        "ok": True,
        "reused": False,
        "snapshot_id": locator.snapshot_id,
        "stop_stage": "backtest",
        "work_key": locator.work_key,
    }
    assert captured.out == json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ) + "\n"
    text = captured.out.lower()
    assert "token" not in text
    assert "bearer" not in text
    assert "mlflow" not in text
    assert str(locator.stage_root) not in captured.out
    assert str(g1_root) not in captured.out
    assert "final_root" not in payload
    assert "receipt_path" not in payload
    assert _tree_signature(g1_root) == before_g1
    after_stage = _tree_signature(locator.stage_root)
    new_files = set(after_stage) - set(before_stage)
    assert new_files
    assert all(
        path.startswith(f"work/{locator.work_key}/backtest/")
        or path == f"receipts/backtest/{locator.work_key}.json"
        for path in new_files
    ), sorted(new_files)
    assert f"receipts/backtest/{locator.work_key}.json" in after_stage
    resumed_code = main(args)
    resumed = capsys.readouterr()
    assert resumed.err == ""
    assert resumed.out.count("\n") == 1
    resumed_payload = json.loads(resumed.out)
    assert resumed_code == 0, resumed_payload
    assert resumed_payload == {**payload, "reused": True}
    assert _tree_signature(g1_root) == before_g1
    assert _tree_signature(locator.stage_root) == after_stage
    leftover_outside = [
        path
        for path in (_ROOT / "artifacts" / "research" / "m3").glob("_f0r*")
        if path != locator.stage_root
    ]
    assert leftover_outside == []
