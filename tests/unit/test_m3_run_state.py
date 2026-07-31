"""E3: 严格 receipt / identity（R1–R4）。"""

from __future__ import annotations

import hashlib
import json
import errno
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from quant.research.m3 import (
    ArtifactDigest,
    StageReceipt,
    compute_experiment_key,
    compute_label_reconciliation_key,
    compute_provider_key,
    compute_provider_validation_key,
    compute_snapshot_request_key,
    compute_work_key,
    publish_stage_receipt,
    verify_stage_receipt,
)


def _hex(n: int = 0) -> str:
    return f"{n:064x}"


@pytest.fixture
def fs_tmp_path() -> Iterator[Path]:
    """Native Linux FS temp dir so symlink/hardlink tests actually run."""
    root = Path(tempfile.mkdtemp(dir="/tmp", prefix="m3-e3-"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _write(path: Path, content: bytes = b"payload") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _publish_simple(
    root: Path,
    *,
    scope_key: str | None = None,
    content: bytes = b"abc",
    stage: str = "snapshot",
    scope: str = "SNAPSHOT",
) -> tuple[Path, Path, dict[str, Path], StageReceipt]:
    artifact = _write(root / "a.bin", content)
    receipt_path = root / "receipt.json"
    roots = {"root": root}
    receipt = publish_stage_receipt(
        receipt_path=receipt_path,
        stage=stage,
        scope=scope,  # type: ignore[arg-type]
        scope_key=scope_key or _hex(1),
        artifact_roots=roots,
        inputs=[],
        outputs=[("root", artifact)],
    )
    return artifact, receipt_path, roots, receipt


# --- R4 identity keys ---


def test_identity_keys_stable_bare_hex_and_sensitive() -> None:
    provider = compute_provider_key(
        snapshot_id=_hex(1),
        provider_config_hash=_hex(2),
        dump_tool_sha256=_hex(3),
        qlib_version="0.9.7",
        provider_runtime_fingerprint_sha256=_hex(4),
        code_version="code-a",
    )
    assert provider == compute_provider_key(
        snapshot_id=_hex(1),
        provider_config_hash=_hex(2),
        dump_tool_sha256=_hex(3),
        qlib_version="0.9.7",
        provider_runtime_fingerprint_sha256=_hex(4),
        code_version="code-a",
    )
    assert len(provider) == 64
    assert provider == provider.lower()
    assert ":" not in provider
    assert not provider.startswith("sha256:")

    assert provider != compute_provider_key(
        snapshot_id=_hex(9),
        provider_config_hash=_hex(2),
        dump_tool_sha256=_hex(3),
        qlib_version="0.9.7",
        provider_runtime_fingerprint_sha256=_hex(4),
        code_version="code-a",
    )
    assert provider != compute_provider_key(
        snapshot_id=_hex(1),
        provider_config_hash=_hex(2),
        dump_tool_sha256=_hex(3),
        qlib_version="0.9.8",
        provider_runtime_fingerprint_sha256=_hex(4),
        code_version="code-a",
    )
    assert provider != compute_provider_key(
        snapshot_id=_hex(1),
        provider_config_hash=_hex(2),
        dump_tool_sha256=_hex(3),
        qlib_version="0.9.7",
        provider_runtime_fingerprint_sha256=_hex(8),
        code_version="code-a",
    )

    experiment = compute_experiment_key(
        snapshot_id=_hex(1),
        provider_receipt_sha256=_hex(5),
        scientific_config_hash=_hex(6),
        code_version="code-a",
        dependency_fingerprint_sha256=_hex(7),
    )
    assert len(experiment) == 64
    assert ":" not in experiment

    work = compute_work_key(experiment_key=experiment, fold="fold_001", horizon=5)
    assert len(work) == 64
    assert work != compute_work_key(
        experiment_key=experiment, fold="fold_002", horizon=5
    )
    assert work != compute_work_key(
        experiment_key=experiment, fold="fold_001", horizon=10
    )


def test_json_array_join_collision_via_public_keys() -> None:
    """('ab','c') 与 ('a','bc') 在字符串拼接下碰撞，规范 JSON 数组不碰撞。"""
    base = dict(
        snapshot_id=_hex(1),
        provider_config_hash=_hex(2),
        dump_tool_sha256=_hex(3),
        provider_runtime_fingerprint_sha256=_hex(4),
    )
    left = compute_provider_key(**base, qlib_version="ab", code_version="c")
    right = compute_provider_key(**base, qlib_version="a", code_version="bc")
    assert left != right
    assert "ab" + "c" == "a" + "bc"


def test_r4_change_propagation_matrix() -> None:
    snap = _hex(1)
    provider_cfg = _hex(2)
    dump = _hex(3)
    runtime = _hex(4)
    code = "code-a"
    sci = _hex(5)
    dep_full = _hex(6)
    dep_lgbm_changed = _hex(16)
    dep_numpy_changed = _hex(26)
    provider_receipt = _hex(7)
    validation_cfg = _hex(8)
    validation_cfg2 = _hex(18)
    validation_receipt = _hex(9)
    validation_receipt2 = _hex(19)
    label_manifest = _hex(10)
    recon_cfg = _hex(11)
    recon_cfg2 = _hex(21)

    provider = compute_provider_key(
        snapshot_id=snap,
        provider_config_hash=provider_cfg,
        dump_tool_sha256=dump,
        qlib_version="0.9.7",
        provider_runtime_fingerprint_sha256=runtime,
        code_version=code,
    )
    experiment = compute_experiment_key(
        snapshot_id=snap,
        provider_receipt_sha256=provider_receipt,
        scientific_config_hash=sci,
        code_version=code,
        dependency_fingerprint_sha256=dep_full,
    )
    validation = compute_provider_validation_key(
        provider_key=provider,
        provider_receipt_sha256=provider_receipt,
        provider_validation_config_sha256=validation_cfg,
        provider_runtime_fingerprint_sha256=runtime,
        code_version=code,
    )
    recon = compute_label_reconciliation_key(
        experiment_key=experiment,
        horizon=5,
        provider_validation_receipt_sha256=validation_receipt,
        label_manifest_sha256=label_manifest,
        label_reconciliation_config_sha256=recon_cfg,
        dependency_fingerprint_sha256=dep_full,
        code_version=code,
    )
    work = compute_work_key(experiment_key=experiment, fold="fold_001", horizon=5)
    snap_req = compute_snapshot_request_key(
        g1_release_id=_hex(30),
        g1_release_manifest_sha256=_hex(31),
        snapshot_config_sha256=_hex(32),
        code_version=code,
    )

    # Only LightGBM (dependency fingerprint) → provider unchanged; experiment/recon/work change
    exp_lgbm = compute_experiment_key(
        snapshot_id=snap,
        provider_receipt_sha256=provider_receipt,
        scientific_config_hash=sci,
        code_version=code,
        dependency_fingerprint_sha256=dep_lgbm_changed,
    )
    assert provider == compute_provider_key(
        snapshot_id=snap,
        provider_config_hash=provider_cfg,
        dump_tool_sha256=dump,
        qlib_version="0.9.7",
        provider_runtime_fingerprint_sha256=runtime,
        code_version=code,
    )
    assert exp_lgbm != experiment
    recon_lgbm = compute_label_reconciliation_key(
        experiment_key=exp_lgbm,
        horizon=5,
        provider_validation_receipt_sha256=validation_receipt,
        label_manifest_sha256=label_manifest,
        label_reconciliation_config_sha256=recon_cfg,
        dependency_fingerprint_sha256=dep_lgbm_changed,
        code_version=code,
    )
    assert recon_lgbm != recon
    assert compute_work_key(
        experiment_key=exp_lgbm, fold="fold_001", horizon=5
    ) != work

    # Only NumPy/pandas/Qlib → provider runtime changes → provider/experiment/recon/work all change
    provider_np = compute_provider_key(
        snapshot_id=snap,
        provider_config_hash=provider_cfg,
        dump_tool_sha256=dump,
        qlib_version="0.9.7",
        provider_runtime_fingerprint_sha256=_hex(44),
        code_version=code,
    )
    assert provider_np != provider
    exp_np = compute_experiment_key(
        snapshot_id=snap,
        provider_receipt_sha256=provider_receipt,
        scientific_config_hash=sci,
        code_version=code,
        dependency_fingerprint_sha256=dep_numpy_changed,
    )
    assert exp_np != experiment
    assert (
        compute_label_reconciliation_key(
            experiment_key=exp_np,
            horizon=5,
            provider_validation_receipt_sha256=validation_receipt,
            label_manifest_sha256=label_manifest,
            label_reconciliation_config_sha256=recon_cfg,
            dependency_fingerprint_sha256=dep_numpy_changed,
            code_version=code,
        )
        != recon
    )
    assert compute_work_key(experiment_key=exp_np, fold="fold_001", horizon=5) != work

    # Only provider sampling (validation cfg) → snap/provider/experiment/work unchanged;
    # provider-validation AND reconciliation change (do NOT assert "only validation")
    validation2 = compute_provider_validation_key(
        provider_key=provider,
        provider_receipt_sha256=provider_receipt,
        provider_validation_config_sha256=validation_cfg2,
        provider_runtime_fingerprint_sha256=runtime,
        code_version=code,
    )
    assert validation2 != validation
    assert provider == compute_provider_key(
        snapshot_id=snap,
        provider_config_hash=provider_cfg,
        dump_tool_sha256=dump,
        qlib_version="0.9.7",
        provider_runtime_fingerprint_sha256=runtime,
        code_version=code,
    )
    assert experiment == compute_experiment_key(
        snapshot_id=snap,
        provider_receipt_sha256=provider_receipt,
        scientific_config_hash=sci,
        code_version=code,
        dependency_fingerprint_sha256=dep_full,
    )
    assert work == compute_work_key(
        experiment_key=experiment, fold="fold_001", horizon=5
    )
    assert snap_req == compute_snapshot_request_key(
        g1_release_id=_hex(30),
        g1_release_manifest_sha256=_hex(31),
        snapshot_config_sha256=_hex(32),
        code_version=code,
    )
    recon_via_new_validation_receipt = compute_label_reconciliation_key(
        experiment_key=experiment,
        horizon=5,
        provider_validation_receipt_sha256=validation_receipt2,
        label_manifest_sha256=label_manifest,
        label_reconciliation_config_sha256=recon_cfg,
        dependency_fingerprint_sha256=dep_full,
        code_version=code,
    )
    assert recon_via_new_validation_receipt != recon

    # Only label recon tolerance → only recon changes
    recon2 = compute_label_reconciliation_key(
        experiment_key=experiment,
        horizon=5,
        provider_validation_receipt_sha256=validation_receipt,
        label_manifest_sha256=label_manifest,
        label_reconciliation_config_sha256=recon_cfg2,
        dependency_fingerprint_sha256=dep_full,
        code_version=code,
    )
    assert recon2 != recon
    assert provider == compute_provider_key(
        snapshot_id=snap,
        provider_config_hash=provider_cfg,
        dump_tool_sha256=dump,
        qlib_version="0.9.7",
        provider_runtime_fingerprint_sha256=runtime,
        code_version=code,
    )
    assert experiment == compute_experiment_key(
        snapshot_id=snap,
        provider_receipt_sha256=provider_receipt,
        scientific_config_hash=sci,
        code_version=code,
        dependency_fingerprint_sha256=dep_full,
    )
    assert work == compute_work_key(
        experiment_key=experiment, fold="fold_001", horizon=5
    )

    # h=5 vs h=10 reconciliation differs; snapshot request binds G1/narrow config
    recon_h10 = compute_label_reconciliation_key(
        experiment_key=experiment,
        horizon=10,
        provider_validation_receipt_sha256=validation_receipt,
        label_manifest_sha256=label_manifest,
        label_reconciliation_config_sha256=recon_cfg,
        dependency_fingerprint_sha256=dep_full,
        code_version=code,
    )
    assert recon_h10 != recon
    assert snap_req != compute_snapshot_request_key(
        g1_release_id=_hex(30),
        g1_release_manifest_sha256=_hex(99),
        snapshot_config_sha256=_hex(32),
        code_version=code,
    )
    assert validation != compute_provider_validation_key(
        provider_key=provider,
        provider_receipt_sha256=_hex(70),
        provider_validation_config_sha256=validation_cfg,
        provider_runtime_fingerprint_sha256=runtime,
        code_version=code,
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"snapshot_id": "snap-a"},
        {"snapshot_id": "A" * 64},
        {"snapshot_id": "0" * 63},
        {"provider_config_hash": True},
        {"dump_tool_sha256": 1},
        {"qlib_version": ""},
        {"qlib_version": " unavailable "},
        {"qlib_version": "UNAVAILABLE"},
        {"qlib_version": "x\x00y"},
        {"code_version": " unavailable"},
        {"provider_runtime_fingerprint_sha256": "sha256:" + "0" * 64},
    ],
)
def test_provider_key_rejects_illegal_inputs(kwargs: dict[str, object]) -> None:
    base: dict[str, object] = {
        "snapshot_id": _hex(1),
        "provider_config_hash": _hex(2),
        "dump_tool_sha256": _hex(3),
        "qlib_version": "0.9.7",
        "provider_runtime_fingerprint_sha256": _hex(4),
        "code_version": "code-a",
    }
    base.update(kwargs)
    with pytest.raises(ValueError):
        compute_provider_key(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize("horizon", [True, False, 0, -1, "5", 5.0])
def test_work_key_rejects_bad_horizon(horizon: object) -> None:
    with pytest.raises(ValueError, match="horizon"):
        compute_work_key(experiment_key=_hex(1), fold="fold_001", horizon=horizon)  # type: ignore[arg-type]


@pytest.mark.parametrize("fold", ["", " fold", "a/b", "a\\b", "a:b", "a.b", "a..b"])
def test_work_key_rejects_bad_fold(fold: str) -> None:
    with pytest.raises(ValueError):
        compute_work_key(experiment_key=_hex(1), fold=fold, horizon=5)


def test_unavailable_rejected_case_insensitive() -> None:
    with pytest.raises(ValueError, match="unavailable"):
        compute_provider_key(
            snapshot_id=_hex(1),
            provider_config_hash=_hex(2),
            dump_tool_sha256=_hex(3),
            qlib_version="0.9.7",
            provider_runtime_fingerprint_sha256=_hex(4),
            code_version="UnAvAiLaBlE",
        )


# --- R1 value objects / JSON ---


def test_stage_receipt_default_version_and_rejects_bad() -> None:
    digest = ArtifactDigest(
        root_alias="root",
        relative_path="a.bin",
        size_bytes=1,
        sha256=_hex(0),
    )
    ok = StageReceipt(
        stage="snapshot",
        scope="SNAPSHOT",
        scope_key=_hex(1),
        inputs=(),
        outputs=(digest,),
    )
    assert ok.receipt_version == "m3-stage-receipt-v1"
    with pytest.raises(ValueError, match="receipt_version"):
        StageReceipt(
            receipt_version="m3-stage-receipt-v0",  # type: ignore[arg-type]
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            inputs=(),
            outputs=(digest,),
        )
    with pytest.raises(ValueError, match="tuple"):
        StageReceipt(
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            inputs=[],  # type: ignore[arg-type]
            outputs=(digest,),
        )


def test_artifact_digest_and_receipt_reject_direct_illegal_construct() -> None:
    with pytest.raises(ValueError):
        ArtifactDigest(
            root_alias="root",
            relative_path="a.bin",
            size_bytes=1,
            sha256="ABCD" + "0" * 60,
        )
    with pytest.raises(ValueError):
        ArtifactDigest(
            root_alias="root",
            relative_path="a.bin",
            size_bytes=True,  # type: ignore[arg-type]
            sha256=_hex(0),
        )
    with pytest.raises(ValueError):
        ArtifactDigest(
            root_alias="",
            relative_path="a.bin",
            size_bytes=1,
            sha256=_hex(0),
        )
    good = ArtifactDigest(
        root_alias="root",
        relative_path="a.bin",
        size_bytes=1,
        sha256=_hex(0),
    )
    other = ArtifactDigest(
        root_alias="root",
        relative_path="b.bin",
        size_bytes=1,
        sha256=_hex(1),
    )
    # unsorted outputs
    with pytest.raises(ValueError, match="升序"):
        StageReceipt(
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            inputs=(),
            outputs=(other, good),
        )
    # cross duplicate
    with pytest.raises(ValueError, match="交叉"):
        StageReceipt(
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            inputs=(good,),
            outputs=(good,),
        )


def test_publish_and_verify_round_trip(fs_tmp_path: Path) -> None:
    snap_root = fs_tmp_path / "snapshots"
    work_root = fs_tmp_path / "work"
    inp = _write(snap_root / "manifest.json", b'{"ok":true}')
    out = _write(work_root / "metrics.json", b'{"ic":0.1}')
    receipt_path = work_root / "stage.complete.json"
    roots = {"snapshot": snap_root, "work": work_root}
    scope_key = _hex(11)

    receipt = publish_stage_receipt(
        receipt_path=receipt_path,
        stage="evaluation",
        scope="WORK",
        scope_key=scope_key,
        artifact_roots=roots,
        inputs=[("snapshot", inp)],
        outputs=[("work", out)],
    )
    verified = verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots)
    assert verified == receipt
    assert verified is not None
    assert verified.receipt_version == "m3-stage-receipt-v1"
    assert verified.inputs[0].relative_path == "manifest.json"
    assert verified.outputs[0].sha256 == hashlib.sha256(b'{"ic":0.1}').hexdigest()

    raw = receipt_path.read_bytes()
    assert b"\n" not in raw
    assert not raw.startswith(b"\xef\xbb\xbf")
    payload = json.loads(raw)
    assert list(payload.keys()) == sorted(
        ["receipt_version", "stage", "scope", "scope_key", "inputs", "outputs"]
    )


def test_acceptance_scope_round_trip(fs_tmp_path: Path) -> None:
    _artifact, receipt_path, roots, receipt = _publish_simple(
        fs_tmp_path / "acc",
        scope="ACCEPTANCE",
        stage="acceptance_audit",
        scope_key=_hex(12),
    )
    assert receipt.scope == "ACCEPTANCE"
    assert verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots) == receipt


def test_identical_republish_reuses_after_verify(fs_tmp_path: Path) -> None:
    artifact, receipt_path, roots, first = _publish_simple(fs_tmp_path / "root")
    before = receipt_path.read_bytes()
    second = publish_stage_receipt(
        receipt_path=receipt_path,
        stage="snapshot",
        scope="SNAPSHOT",
        scope_key=_hex(1),
        artifact_roots=roots,
        inputs=[],
        outputs=[("root", artifact)],
    )
    assert first == second
    assert receipt_path.read_bytes() == before


def test_reuse_refused_when_artifact_mutated(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, receipt_path, roots, _ = _publish_simple(fs_tmp_path / "root")
    same_bytes = receipt_path.read_bytes()
    receipt_path.unlink()
    artifact.write_bytes(b"abc")

    def link_then_mutate(
        src: str | os.PathLike[str], dst: str | os.PathLike[str]
    ) -> None:
        Path(dst).write_bytes(same_bytes)
        artifact.write_bytes(b"mutated")
        raise FileExistsError(errno.EEXIST, "exists")

    monkeypatch.setattr(os, "link", link_then_mutate)
    with pytest.raises(ValueError, match="hash|大小"):
        publish_stage_receipt(
            receipt_path=receipt_path,
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots=roots,
            inputs=[],
            outputs=[("root", artifact)],
        )


def test_conflicting_receipt_rejected(fs_tmp_path: Path) -> None:
    root = fs_tmp_path / "root"
    a = _write(root / "a.bin", b"a")
    b = _write(root / "b.bin", b"b")
    receipt_path = root / "receipt.json"
    roots = {"root": root}
    publish_stage_receipt(
        receipt_path=receipt_path,
        stage="snapshot",
        scope="SNAPSHOT",
        scope_key=_hex(1),
        artifact_roots=roots,
        inputs=[],
        outputs=[("root", a)],
    )
    with pytest.raises(ValueError, match="冲突"):
        publish_stage_receipt(
            receipt_path=receipt_path,
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots=roots,
            inputs=[],
            outputs=[("root", b)],
        )
    # original bytes preserved
    assert verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots) is not None


def test_concurrent_noclobber_same_and_conflict(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = fs_tmp_path / "root"
    artifact = _write(root / "a.bin", b"abc")
    receipt_path = root / "receipt.json"
    roots = {"root": root}
    scope_key = _hex(1)

    first = publish_stage_receipt(
        receipt_path=receipt_path,
        stage="snapshot",
        scope="SNAPSHOT",
        scope_key=scope_key,
        artifact_roots=roots,
        inputs=[],
        outputs=[("root", artifact)],
    )
    same_bytes = receipt_path.read_bytes()
    receipt_path.unlink()

    def link_same(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        Path(dst).write_bytes(same_bytes)
        raise FileExistsError(errno.EEXIST, "exists")

    monkeypatch.setattr(os, "link", link_same)
    reused = publish_stage_receipt(
        receipt_path=receipt_path,
        stage="snapshot",
        scope="SNAPSHOT",
        scope_key=scope_key,
        artifact_roots=roots,
        inputs=[],
        outputs=[("root", artifact)],
    )
    assert reused == first
    assert receipt_path.read_bytes() == same_bytes

    receipt_path.unlink()
    conflict_bytes = same_bytes.replace(scope_key.encode(), _hex(2).encode())

    def link_conflict(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        Path(dst).write_bytes(conflict_bytes)
        raise FileExistsError(errno.EEXIST, "exists")

    monkeypatch.setattr(os, "link", link_conflict)
    with pytest.raises(ValueError, match="冲突"):
        publish_stage_receipt(
            receipt_path=receipt_path,
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=scope_key,
            artifact_roots=roots,
            inputs=[],
            outputs=[("root", artifact)],
        )
    assert receipt_path.read_bytes() == conflict_bytes


def test_verify_missing_returns_none(fs_tmp_path: Path) -> None:
    root = fs_tmp_path / "root"
    root.mkdir()
    assert (
        verify_stage_receipt(
            receipt_path=root / "missing.json",
            artifact_roots={"root": root},
        )
        is None
    )


def test_verify_rejects_corrupt_mismatch_and_old_versionless(fs_tmp_path: Path) -> None:
    artifact, receipt_path, roots, _ = _publish_simple(fs_tmp_path / "root")
    artifact.write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash|大小"):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots)

    receipt_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="非法|UTF-8|JSON"):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots)

    # old versionless receipt fail-closed
    legacy = {
        "stage": "snapshot",
        "scope": "SNAPSHOT",
        "scope_key": _hex(1),
        "inputs": [],
        "outputs": [
            {
                "root_alias": "root",
                "relative_path": "a.bin",
                "size_bytes": 3,
                "sha256": hashlib.sha256(b"abc").hexdigest(),
            }
        ],
    }
    artifact.write_bytes(b"abc")
    receipt_path.write_bytes(
        json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    with pytest.raises(ValueError, match="字段|receipt_version|版本"):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots)


def test_rejects_noncanonical_json_bom_crlf_reorder_trailing(
    fs_tmp_path: Path,
) -> None:
    artifact, receipt_path, roots, receipt = _publish_simple(fs_tmp_path / "root")
    canonical = receipt_path.read_bytes()

    # trailing newline
    receipt_path.write_bytes(canonical + b"\n")
    with pytest.raises(ValueError, match="规范|字节"):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots)

    # BOM
    receipt_path.write_bytes(b"\xef\xbb\xbf" + canonical)
    with pytest.raises(ValueError, match="BOM|规范|字节"):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots)

    # CRLF
    text = canonical.decode("utf-8").replace(",", ",\r\n")
    receipt_path.write_bytes(text.encode("utf-8"))
    with pytest.raises(ValueError, match="CRLF|规范|字节|非法"):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots)

    # field reordering / indentation via pretty print
    payload = json.loads(canonical)
    receipt_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="规范|字节"):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots)

    # restore and sanity
    receipt_path.write_bytes(canonical)
    assert verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots) == receipt
    assert artifact.exists()


def test_rejects_duplicate_keys_unknown_fields_bad_types(fs_tmp_path: Path) -> None:
    root = fs_tmp_path / "root"
    artifact = _write(root / "a.bin", b"abc")
    receipt_path = root / "receipt.json"
    roots = {"root": root}
    digest = {
        "root_alias": "root",
        "relative_path": "a.bin",
        "size_bytes": 3,
        "sha256": hashlib.sha256(b"abc").hexdigest(),
    }
    base = {
        "receipt_version": "m3-stage-receipt-v1",
        "stage": "snapshot",
        "scope": "SNAPSHOT",
        "scope_key": _hex(1),
        "inputs": [],
        "outputs": [digest],
    }

    # duplicate top-level key
    dup_top = (
        '{"receipt_version":"m3-stage-receipt-v1","receipt_version":"m3-stage-receipt-v1",'
        '"stage":"snapshot","scope":"SNAPSHOT","scope_key":"'
        + _hex(1)
        + '","inputs":[],"outputs":['
        + json.dumps(digest, separators=(",", ":"))
        + "]}"
    )
    receipt_path.write_text(dup_top, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots)

    # duplicate digest key
    dup_digest = (
        '{"inputs":[],"outputs":[{"root_alias":"root","relative_path":"a.bin",'
        '"size_bytes":3,"size_bytes":3,"sha256":"'
        + digest["sha256"]
        + '"}],"receipt_version":"m3-stage-receipt-v1","scope":"SNAPSHOT","scope_key":"'
        + _hex(1)
        + '","stage":"snapshot"}'
    )
    receipt_path.write_text(dup_digest, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots)

    # unknown field
    unknown = dict(base)
    unknown["extra"] = 1
    receipt_path.write_bytes(
        json.dumps(unknown, sort_keys=True, separators=(",", ":")).encode()
    )
    with pytest.raises(ValueError, match="字段"):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots)

    # size_bytes bool
    bad = dict(base)
    bad["outputs"] = [{**digest, "size_bytes": True}]
    receipt_path.write_bytes(
        json.dumps(bad, sort_keys=True, separators=(",", ":")).encode()
    )
    with pytest.raises(ValueError, match="size_bytes"):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots)

    # size_bytes string number
    bad2 = dict(base)
    bad2["outputs"] = [{**digest, "size_bytes": "3"}]
    receipt_path.write_bytes(
        json.dumps(bad2, sort_keys=True, separators=(",", ":")).encode()
    )
    with pytest.raises(ValueError, match="size_bytes"):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots)

    # uppercase hash
    bad3 = dict(base)
    bad3["outputs"] = [{**digest, "sha256": digest["sha256"].upper()}]
    receipt_path.write_bytes(
        json.dumps(bad3, sort_keys=True, separators=(",", ":")).encode()
    )
    with pytest.raises(ValueError, match="hex|sha256"):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots)

    # empty stage
    bad4 = dict(base)
    bad4["stage"] = ""
    receipt_path.write_bytes(
        json.dumps(bad4, sort_keys=True, separators=(",", ":")).encode()
    )
    with pytest.raises(ValueError, match="stage"):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots)

    # NaN
    nan_raw = (
        json.dumps(base, sort_keys=True, separators=(",", ":"))
        .replace('"stage":"snapshot"', '"stage":NaN')
        .encode()
    )
    receipt_path.write_bytes(nan_raw)
    with pytest.raises(ValueError):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots)

    assert artifact.exists()


def test_path_safety_and_error_messages_without_abs(
    fs_tmp_path: Path,
) -> None:
    root = fs_tmp_path / "root"
    root.mkdir()
    artifact = _write(root / "a.bin", b"abc")
    receipt_path = root / "receipt.json"
    roots = {"root": root}

    with pytest.raises(ValueError, match="未知") as exc_unknown:
        publish_stage_receipt(
            receipt_path=receipt_path,
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots=roots,
            inputs=[("other", artifact)],
            outputs=[],
        )
    assert str(fs_tmp_path) not in str(exc_unknown.value)
    assert str(root) not in str(exc_unknown.value)

    with pytest.raises(ValueError, match="重复"):
        publish_stage_receipt(
            receipt_path=receipt_path,
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots=roots,
            inputs=[("root", artifact), ("root", artifact)],
            outputs=[],
        )

    outside = _write(fs_tmp_path / "outside.bin", b"x")
    with pytest.raises(ValueError, match="root|越界|不在") as exc_out:
        publish_stage_receipt(
            receipt_path=receipt_path,
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots=roots,
            inputs=[],
            outputs=[("root", outside)],
        )
    assert str(outside) not in str(exc_out.value)


def test_exception_chain_and_traceback_omit_absolute_paths(
    fs_tmp_path: Path,
) -> None:
    import traceback

    root = fs_tmp_path / "root"
    root.mkdir()
    roots = {"root": root}
    abs_markers = (
        str(fs_tmp_path),
        str(root.resolve()),
        os.path.abspath(str(fs_tmp_path)),
    )

    def _assert_sanitized(exc: BaseException) -> None:
        assert exc.__cause__ is None
        rendered = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        for marker in abs_markers:
            assert marker not in str(exc)
            assert marker not in rendered
        # raise ... from None 必须抑制 context 展示，避免底层绝对路径进入 traceback
        assert getattr(exc, "__suppress_context__", False) or exc.__context__ is None

    # 越界 artifact：底层 relative_to 消息含绝对路径，不得进入 cause/traceback
    outside = _write(fs_tmp_path / "outside.bin", b"x")
    with pytest.raises(ValueError) as exc_out:
        publish_stage_receipt(
            receipt_path=root / "receipt.json",
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots=roots,
            inputs=[],
            outputs=[("root", outside)],
        )
    _assert_sanitized(exc_out.value)

    # 缺失 receipt parent
    missing_parent = root / "missing_dir" / "receipt.json"
    with pytest.raises(ValueError, match="不存在") as exc_parent:
        publish_stage_receipt(
            receipt_path=missing_parent,
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots=roots,
            inputs=[],
            outputs=[("root", _write(root / "a.bin", b"a"))],
        )
    _assert_sanitized(exc_parent.value)

    # 缺失 artifact leaf
    ghost = root / "ghost.bin"
    with pytest.raises(ValueError, match="缺失") as exc_miss:
        publish_stage_receipt(
            receipt_path=root / "receipt2.json",
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(2),
            artifact_roots=roots,
            inputs=[],
            outputs=[("root", ghost)],
        )
    _assert_sanitized(exc_miss.value)


def test_receipt_self_ref_input_output_and_hardlink(fs_tmp_path: Path) -> None:
    root = fs_tmp_path / "root"
    root.mkdir()
    roots = {"root": root}
    receipt_path = root / "self.json"
    fake = _write(receipt_path, b"{}")
    with pytest.raises(ValueError, match="receipt"):
        publish_stage_receipt(
            receipt_path=fake,
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots=roots,
            inputs=[],
            outputs=[("root", fake)],
        )

    artifact = _write(root / "a.bin", b"abc")
    published = root / "receipt.json"
    publish_stage_receipt(
        receipt_path=published,
        stage="snapshot",
        scope="SNAPSHOT",
        scope_key=_hex(1),
        artifact_roots=roots,
        inputs=[],
        outputs=[("root", artifact)],
    )
    # existing receipt listed as its own input
    with pytest.raises(ValueError, match="receipt"):
        publish_stage_receipt(
            receipt_path=published,
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(2),
            artifact_roots=roots,
            inputs=[("root", published)],
            outputs=[("root", artifact)],
        )

    # receipt hard-link as input of the same receipt path
    hl = root / "receipt_hl.json"
    os.link(published, hl)
    with pytest.raises(ValueError, match="receipt"):
        publish_stage_receipt(
            receipt_path=published,
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(3),
            artifact_roots=roots,
            inputs=[("root", hl)],
            outputs=[("root", artifact)],
        )

    # receipt_path hard-linked to an output artifact
    linked_receipt = root / "linked_receipt.json"
    os.link(artifact, linked_receipt)
    with pytest.raises(ValueError, match="receipt|物理"):
        publish_stage_receipt(
            receipt_path=linked_receipt,
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(4),
            artifact_roots=roots,
            inputs=[],
            outputs=[("root", artifact)],
        )


def test_nested_root_aliasing_and_hardlink_dedupe(fs_tmp_path: Path) -> None:
    parent = fs_tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    file_path = _write(child / "x.bin", b"xx")
    receipt_path = parent / "receipt.json"
    roots = {"A": parent, "B": child}

    # nested roots OK for distinct files
    other = _write(parent / "y.bin", b"yy")
    publish_stage_receipt(
        receipt_path=receipt_path,
        stage="snapshot",
        scope="SNAPSHOT",
        scope_key=_hex(1),
        artifact_roots=roots,
        inputs=[],
        outputs=[("A", other), ("B", file_path)],
    )

    # same physical file via parent/child relative paths
    receipt_path.unlink()
    with pytest.raises(ValueError, match="物理|重复"):
        publish_stage_receipt(
            receipt_path=receipt_path,
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots=roots,
            inputs=[("A", file_path)],
            outputs=[("B", file_path)],
        )

    # hard-link duplicate
    hl = parent / "x_hl.bin"
    os.link(file_path, hl)
    with pytest.raises(ValueError, match="物理|重复"):
        publish_stage_receipt(
            receipt_path=receipt_path,
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(2),
            artifact_roots={"A": parent},
            inputs=[("A", file_path)],
            outputs=[("A", hl)],
        )


def test_duplicate_physical_root_alias_rejected(fs_tmp_path: Path) -> None:
    root = fs_tmp_path / "root"
    root.mkdir()
    artifact = _write(root / "a.bin", b"a")
    with pytest.raises(ValueError, match="物理 root|重复"):
        publish_stage_receipt(
            receipt_path=root / "receipt.json",
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots={"A": root, "B": root},
            inputs=[],
            outputs=[("A", artifact)],
        )


def test_receipt_outside_roots_and_missing_parent(fs_tmp_path: Path) -> None:
    root = fs_tmp_path / "root"
    root.mkdir()
    artifact = _write(root / "a.bin", b"a")
    outside = fs_tmp_path / "outside" / "receipt.json"
    outside.parent.mkdir()
    with pytest.raises(ValueError, match="root 内|不在"):
        publish_stage_receipt(
            receipt_path=outside,
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots={"root": root},
            inputs=[],
            outputs=[("root", artifact)],
        )

    missing_parent = root / "nope" / "receipt.json"
    with pytest.raises(ValueError, match="receipt_parent|不存在"):
        publish_stage_receipt(
            receipt_path=missing_parent,
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots={"root": root},
            inputs=[],
            outputs=[("root", artifact)],
        )


def test_unused_invalid_root_rejected_before_digest_read(fs_tmp_path: Path) -> None:
    root = fs_tmp_path / "root"
    root.mkdir()
    artifact = _write(root / "a.bin", b"a")
    missing = fs_tmp_path / "missing_root"
    with pytest.raises(ValueError, match="root|不存在"):
        publish_stage_receipt(
            receipt_path=root / "receipt.json",
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots={"root": root, "unused": missing},
            inputs=[],
            outputs=[("root", artifact)],
        )


def test_symlink_cases_rejected(fs_tmp_path: Path) -> None:
    root = fs_tmp_path / "root"
    root.mkdir()
    artifact = _write(root / "a.bin", b"abc")

    # root itself symlink
    linked_root = fs_tmp_path / "linked_root"
    os.symlink(root, linked_root)
    with pytest.raises(ValueError, match="symlink"):
        publish_stage_receipt(
            receipt_path=linked_root / "receipt.json",
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots={"root": linked_root},
            inputs=[],
            outputs=[("root", linked_root / "a.bin")],
        )

    # file symlink inside root
    outside = _write(fs_tmp_path / "secret.bin", b"secret")
    link = root / "escaped.bin"
    os.symlink(outside, link)
    with pytest.raises(ValueError, match="symlink|逃逸|越界"):
        publish_stage_receipt(
            receipt_path=root / "receipt.json",
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots={"root": root},
            inputs=[],
            outputs=[("root", link)],
        )

    # internal symlink to internal file
    internal_link = root / "alias.bin"
    os.symlink(artifact, internal_link)
    with pytest.raises(ValueError, match="symlink"):
        publish_stage_receipt(
            receipt_path=root / "receipt2.json",
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(2),
            artifact_roots={"root": root},
            inputs=[],
            outputs=[("root", internal_link)],
        )

    # parent dir symlink component under root
    real_dir = root / "realdir"
    real_dir.mkdir()
    _write(real_dir / "f.bin", b"f")
    os.symlink(real_dir, root / "symdir")
    with pytest.raises(ValueError, match="symlink"):
        publish_stage_receipt(
            receipt_path=root / "receipt3.json",
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(3),
            artifact_roots={"root": root},
            inputs=[],
            outputs=[("root", root / "symdir" / "f.bin")],
        )

    # ancestor symlink of root
    base = fs_tmp_path / "base"
    real_nested = base / "real" / "nested"
    real_nested.mkdir(parents=True)
    os.symlink(base / "real", base / "via")
    nested_root = base / "via" / "nested"
    _write(nested_root / "z.bin", b"z")
    with pytest.raises(ValueError, match="symlink"):
        publish_stage_receipt(
            receipt_path=nested_root / "receipt.json",
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(4),
            artifact_roots={"root": nested_root},
            inputs=[],
            outputs=[("root", nested_root / "z.bin")],
        )

    # dangling receipt symlink ≠ missing
    dangling = root / "dangling.json"
    os.symlink(root / "no_such_target.json", dangling)
    with pytest.raises(ValueError, match="symlink"):
        verify_stage_receipt(
            receipt_path=dangling, artifact_roots={"root": root}
        )

    # receipt parent chain symlink
    pub = root / "ok.json"
    publish_stage_receipt(
        receipt_path=pub,
        stage="snapshot",
        scope="SNAPSHOT",
        scope_key=_hex(5),
        artifact_roots={"root": root},
        inputs=[],
        outputs=[("root", artifact)],
    )
    # replace receipt with symlink to itself content elsewhere
    target = root / "target_receipt.json"
    shutil.copyfile(pub, target)
    pub.unlink()
    os.symlink(target, pub)
    with pytest.raises(ValueError, match="symlink"):
        verify_stage_receipt(receipt_path=pub, artifact_roots={"root": root})


def test_rejects_dotdot_and_absolute_in_verify(fs_tmp_path: Path) -> None:
    root = fs_tmp_path / "root"
    root.mkdir()
    receipt_path = root / "receipt.json"

    def write_bad(relative: str) -> None:
        payload = {
            "receipt_version": "m3-stage-receipt-v1",
            "stage": "snapshot",
            "scope": "SNAPSHOT",
            "scope_key": _hex(1),
            "inputs": [],
            "outputs": [
                {
                    "root_alias": "root",
                    "relative_path": relative,
                    "size_bytes": 1,
                    "sha256": _hex(0),
                }
            ],
        }
        receipt_path.write_bytes(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        )

    write_bad("../secret")
    with pytest.raises(ValueError, match=r"\.\.|非法"):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots={"root": root})

    write_bad("/etc/passwd")
    with pytest.raises(ValueError, match="绝对|非法"):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots={"root": root})

    write_bad("C:/Windows/system32")
    with pytest.raises(ValueError, match="POSIX|绝对|非法"):
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots={"root": root})


def test_control_char_rejected_in_stage() -> None:
    digest = ArtifactDigest(
        root_alias="root",
        relative_path="a.bin",
        size_bytes=1,
        sha256=_hex(0),
    )
    with pytest.raises(ValueError, match="控制"):
        StageReceipt(
            stage="bad\x00stage",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            inputs=(),
            outputs=(digest,),
        )


def test_input_order_does_not_affect_bytes(fs_tmp_path: Path) -> None:
    snap_root = fs_tmp_path / "snapshots"
    work_root = fs_tmp_path / "work"
    roots = {"snapshot": snap_root, "work": work_root}
    inp = _write(snap_root / "manifest.json", b'{"ok":true}')
    inp2 = _write(snap_root / "other.json", b"y")
    out = _write(work_root / "metrics.json", b'{"ic":0.1}')
    out2 = _write(work_root / "extra.json", b"x")
    receipt_path = work_root / "stage2.complete.json"
    scope_key = _hex(2)
    a = publish_stage_receipt(
        receipt_path=receipt_path,
        stage="evaluation",
        scope="WORK",
        scope_key=scope_key,
        artifact_roots=roots,
        inputs=[("snapshot", inp), ("snapshot", inp2)],
        outputs=[("work", out), ("work", out2)],
    )
    receipt_path.unlink()
    b = publish_stage_receipt(
        receipt_path=receipt_path,
        stage="evaluation",
        scope="WORK",
        scope_key=scope_key,
        artifact_roots=roots,
        inputs=[("snapshot", inp2), ("snapshot", inp)],
        outputs=[("work", out2), ("work", out)],
    )
    assert a == b


# --- 主验一次返工：临时 I/O 脱敏 / cleanup 优先级 / scope 类型 ---


_PRIVATE_ABS = "/tmp/e3-main-audit-PRIVATE/temp"


def _assert_exc_sanitized(exc: BaseException, *forbidden: str) -> None:
    import traceback

    assert isinstance(exc, ValueError)
    assert exc.__cause__ is None
    rendered = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    for marker in forbidden:
        assert marker not in str(exc)
        assert marker not in rendered
    assert getattr(exc, "__suppress_context__", False) or exc.__context__ is None


def test_publish_mkstemp_failure_sanitized(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = fs_tmp_path / "root"
    root.mkdir()
    artifact = _write(root / "a.bin", b"abc")
    marker = f"{_PRIVATE_ABS}/mkstemp"

    def boom(*_a: object, **_k: object) -> tuple[int, str]:
        raise PermissionError(errno.EACCES, "denied", marker)

    monkeypatch.setattr(tempfile, "mkstemp", boom)
    with pytest.raises(ValueError, match="临时文件创建失败") as exc_info:
        publish_stage_receipt(
            receipt_path=root / "receipt.json",
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots={"root": root},
            inputs=[],
            outputs=[("root", artifact)],
        )
    _assert_exc_sanitized(exc_info.value, marker, str(root), str(fs_tmp_path))


def test_publish_temp_write_failure_cleans_fd_and_temp(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = fs_tmp_path / "root"
    root.mkdir()
    artifact = _write(root / "a.bin", b"abc")
    marker = f"{_PRIVATE_ABS}/write"
    captured: dict[str, object] = {}

    real_mkstemp = tempfile.mkstemp

    def capture_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
        fd, name = real_mkstemp(*args, **kwargs)
        captured["fd"] = fd
        captured["name"] = name
        return fd, name

    def boom_fdopen(fd: int, *_a: object, **_k: object) -> object:
        raise OSError(errno.EIO, "io error", marker)

    monkeypatch.setattr(tempfile, "mkstemp", capture_mkstemp)
    monkeypatch.setattr(os, "fdopen", boom_fdopen)
    with pytest.raises(ValueError, match="临时文件写入失败") as exc_info:
        publish_stage_receipt(
            receipt_path=root / "receipt.json",
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots={"root": root},
            inputs=[],
            outputs=[("root", artifact)],
        )
    _assert_exc_sanitized(exc_info.value, marker, str(root))
    fd = captured["fd"]
    assert isinstance(fd, int)
    with pytest.raises(OSError):
        os.fstat(fd)
    assert not Path(str(captured["name"])).exists()
    assert not (root / "receipt.json").exists()
    leftovers = list(root.glob(".receipt.json.*.tmp"))
    assert leftovers == []


def test_publish_file_fsync_failure_sanitized_and_cleans_temp(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = fs_tmp_path / "root"
    root.mkdir()
    artifact = _write(root / "a.bin", b"abc")
    marker = f"{_PRIVATE_ABS}/fsync-file"
    captured: dict[str, str] = {}
    real_mkstemp = tempfile.mkstemp
    real_fsync = os.fsync
    state = {"n": 0}

    def capture_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
        fd, name = real_mkstemp(*args, **kwargs)
        captured["name"] = name
        return fd, name

    def boom_first_fsync(fd: int) -> None:
        state["n"] += 1
        if state["n"] == 1:
            raise OSError(errno.EIO, "fsync fail", marker)
        return real_fsync(fd)

    monkeypatch.setattr(tempfile, "mkstemp", capture_mkstemp)
    monkeypatch.setattr(os, "fsync", boom_first_fsync)
    with pytest.raises(ValueError, match="临时文件写入失败") as exc_info:
        publish_stage_receipt(
            receipt_path=root / "receipt.json",
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots={"root": root},
            inputs=[],
            outputs=[("root", artifact)],
        )
    _assert_exc_sanitized(exc_info.value, marker, str(root))
    assert not Path(captured["name"]).exists()
    assert list(root.glob(".receipt.json.*.tmp")) == []


def test_publish_cleanup_fail_after_success_keeps_receipt(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = fs_tmp_path / "root"
    root.mkdir()
    artifact = _write(root / "a.bin", b"abc")
    receipt_path = root / "receipt.json"
    roots = {"root": root}
    marker = f"{_PRIVATE_ABS}/unlink-after-publish"
    real_unlink = Path.unlink

    def boom_tmp_unlink(self: Path, *args: object, **kwargs: object) -> None:
        if self.suffix == ".tmp":
            raise PermissionError(errno.EACCES, "denied", marker)
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", boom_tmp_unlink)
    with pytest.raises(ValueError, match="临时文件清理失败") as exc_info:
        publish_stage_receipt(
            receipt_path=receipt_path,
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots=roots,
            inputs=[],
            outputs=[("root", artifact)],
        )
    _assert_exc_sanitized(exc_info.value, marker, str(root))
    assert receipt_path.is_file()
    verified = verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots)
    assert verified is not None
    # 清理测试残留临时文件（绕过失败注入）
    for leftover in root.glob(".receipt.json.*.tmp"):
        real_unlink(leftover)


def test_publish_link_and_cleanup_dual_fail_prefers_link(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = fs_tmp_path / "root"
    root.mkdir()
    artifact = _write(root / "a.bin", b"abc")
    link_marker = f"{_PRIVATE_ABS}/link"
    unlink_marker = f"{_PRIVATE_ABS}/unlink"
    real_unlink = Path.unlink

    def boom_link(
        src: str | os.PathLike[str], dst: str | os.PathLike[str]
    ) -> None:
        raise OSError(errno.EPERM, "link denied", link_marker)

    def boom_tmp_unlink(self: Path, *args: object, **kwargs: object) -> None:
        if self.suffix == ".tmp":
            raise PermissionError(errno.EACCES, "denied", unlink_marker)
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(os, "link", boom_link)
    monkeypatch.setattr(Path, "unlink", boom_tmp_unlink)
    with pytest.raises(ValueError, match="原子创建失败") as exc_info:
        publish_stage_receipt(
            receipt_path=root / "receipt.json",
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots={"root": root},
            inputs=[],
            outputs=[("root", artifact)],
        )
    assert "清理" not in str(exc_info.value)
    _assert_exc_sanitized(
        exc_info.value, link_marker, unlink_marker, str(root), str(fs_tmp_path)
    )
    for leftover in root.glob(".receipt.json.*.tmp"):
        real_unlink(leftover)


def test_fsync_parent_dir_close_priority(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quant.research.m3.run_state as run_state_mod
    from quant.research.m3.run_state import _fsync_parent_dir

    monkeypatch.setattr(run_state_mod, "_directory_fsync_supported", lambda: True)

    parent = fs_tmp_path / "parent"
    parent.mkdir()
    marker_fsync = f"{_PRIVATE_ABS}/dir-fsync"
    marker_close = f"{_PRIVATE_ABS}/dir-close"
    fake_fd = 51234

    monkeypatch.setattr(os, "open", lambda *_a, **_k: fake_fd)

    def boom_fsync(_fd: int) -> None:
        raise OSError(errno.EIO, "fsync", marker_fsync)

    def boom_close(_fd: int) -> None:
        raise OSError(errno.EIO, "close", marker_close)

    monkeypatch.setattr(os, "fsync", boom_fsync)
    monkeypatch.setattr(os, "close", boom_close)
    with pytest.raises(ValueError, match="父目录 fsync 失败") as dual:
        _fsync_parent_dir(parent)
    _assert_exc_sanitized(dual.value, marker_fsync, marker_close, str(parent))

    def ok_fsync(_fd: int) -> None:
        return None

    monkeypatch.setattr(os, "fsync", ok_fsync)
    with pytest.raises(ValueError, match="父目录 fsync 失败") as close_only:
        _fsync_parent_dir(parent)
    _assert_exc_sanitized(close_only.value, marker_close, str(parent))

    def unsupported_fsync(_fd: int) -> None:
        raise OSError(errno.EINVAL, "unsupported", marker_fsync)

    monkeypatch.setattr(os, "fsync", unsupported_fsync)
    with pytest.raises(ValueError, match="父目录 fsync 失败") as unsup_close:
        _fsync_parent_dir(parent)
    _assert_exc_sanitized(unsup_close.value, marker_fsync, marker_close, str(parent))


def test_reuse_success_then_cleanup_fail_not_silent(
    fs_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = fs_tmp_path / "root"
    artifact = _write(root / "a.bin", b"abc")
    receipt_path = root / "receipt.json"
    roots = {"root": root}
    first = publish_stage_receipt(
        receipt_path=receipt_path,
        stage="snapshot",
        scope="SNAPSHOT",
        scope_key=_hex(1),
        artifact_roots=roots,
        inputs=[],
        outputs=[("root", artifact)],
    )
    same_bytes = receipt_path.read_bytes()
    receipt_path.unlink()
    marker = f"{_PRIVATE_ABS}/reuse-cleanup"
    real_unlink = Path.unlink

    def link_same(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        Path(dst).write_bytes(same_bytes)
        raise FileExistsError(errno.EEXIST, "exists")

    def boom_tmp_unlink(self: Path, *args: object, **kwargs: object) -> None:
        if self.suffix == ".tmp":
            raise PermissionError(errno.EACCES, "denied", marker)
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(os, "link", link_same)
    monkeypatch.setattr(Path, "unlink", boom_tmp_unlink)
    with pytest.raises(ValueError, match="临时文件清理失败") as exc_info:
        publish_stage_receipt(
            receipt_path=receipt_path,
            stage="snapshot",
            scope="SNAPSHOT",
            scope_key=_hex(1),
            artifact_roots=roots,
            inputs=[],
            outputs=[("root", artifact)],
        )
    _assert_exc_sanitized(exc_info.value, marker, str(root))
    assert receipt_path.read_bytes() == same_bytes
    assert (
        verify_stage_receipt(receipt_path=receipt_path, artifact_roots=roots) == first
    )
    for leftover in root.glob(".receipt.json.*.tmp"):
        real_unlink(leftover)


def test_illegal_scope_types_stable_valueerror(fs_tmp_path: Path) -> None:
    digest = ArtifactDigest(
        root_alias="root",
        relative_path="a.bin",
        size_bytes=1,
        sha256=_hex(0),
    )
    for bad in (["SNAPSHOT"], {"SNAPSHOT": True}):
        with pytest.raises(ValueError, match="非法 scope") as direct:
            StageReceipt(
                stage="snapshot",
                scope=bad,  # type: ignore[arg-type]
                scope_key=_hex(1),
                inputs=(),
                outputs=(digest,),
            )
        assert not isinstance(direct.value, TypeError)
        _assert_exc_sanitized(direct.value)

    root = fs_tmp_path / "root"
    root.mkdir()
    artifact = _write(root / "a.bin", b"abc")
    receipt_path = root / "receipt.json"
    for bad in (["SNAPSHOT"], {"k": "SNAPSHOT"}):
        with pytest.raises(ValueError, match="非法 scope") as pub:
            publish_stage_receipt(
                receipt_path=receipt_path,
                stage="snapshot",
                scope=bad,  # type: ignore[arg-type]
                scope_key=_hex(1),
                artifact_roots={"root": root},
                inputs=[],
                outputs=[("root", artifact)],
            )
        assert not isinstance(pub.value, TypeError)
        _assert_exc_sanitized(pub.value, str(root))

    payload = {
        "receipt_version": "m3-stage-receipt-v1",
        "stage": "snapshot",
        "scope": ["SNAPSHOT"],
        "scope_key": _hex(1),
        "inputs": [],
        "outputs": [
            {
                "root_alias": "root",
                "relative_path": "a.bin",
                "size_bytes": 3,
                "sha256": hashlib.sha256(b"abc").hexdigest(),
            }
        ],
    }
    receipt_path.write_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )
    with pytest.raises(ValueError, match="非法 scope") as parsed:
        verify_stage_receipt(
            receipt_path=receipt_path, artifact_roots={"root": root}
        )
    assert not isinstance(parsed.value, TypeError)
    _assert_exc_sanitized(parsed.value, str(root))

    payload2 = dict(payload)
    payload2["scope"] = {"SNAPSHOT": 1}
    receipt_path.write_bytes(
        json.dumps(payload2, sort_keys=True, separators=(",", ":")).encode()
    )
    with pytest.raises(ValueError, match="非法 scope") as parsed2:
        verify_stage_receipt(
            receipt_path=receipt_path, artifact_roots={"root": root}
        )
    assert not isinstance(parsed2.value, TypeError)
    _assert_exc_sanitized(parsed2.value, str(root))


def test_no_os_replace_in_run_state_source() -> None:
    import quant.research.m3.run_state as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert "os.replace" not in source

