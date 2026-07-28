"""P4C immutable release: strict reader, identity closure, atomic publish."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import socket
from dataclasses import asdict
from pathlib import Path
from typing import Any

import polars as pl
import pytest

import quant.data as qd
import quant.data.m3_release as release_mod
from quant.data.connectors.cninfo import CNINFO_STOCK_ALLOTMENT_FIELDS
from quant.data.m3_g1_candidate import G1BuildInputs, G1Candidate, build_g1_candidate
from quant.data.m3_identity import clean_table_content_sha256
from quant.data.m3_reference import (
    CrossSourceSamplePlan,
    G1CrossSourcePolicy,
    ReferenceRequestPlanV1,
    VerifiedReferenceResponse,
    plan_baostock_reference_requests,
    plan_cross_source_reconciliation,
)
from quant.data.m3_release import (
    G1ManifestV1,
    G1ManifestV2,
    G1ManifestV3,
    G1ManifestV4,
    G1ManifestV5,
    G1PreparedRelease,
    G1QualityReportV1,
    G1Release,
    G1ReleaseInputs,
    M3ReleaseError,
    prepare_g1_release,
    publish_g1_release,
    read_cross_source_summary,
    read_g1_manifest,
    read_g1_quality,
    verify_g1_release,
)
from quant.data.storage import RawStore
from tests.unit import test_m3_reference as ref_tests


def _injectable_renameat2_noreplace(src: Path, dst: Path) -> None:
    """Test-only directory commit with no-clobber semantics when kernel lacks the flag."""
    if dst.exists():
        raise M3ReleaseError("G1_RELEASE_CONCURRENT_PUBLISH")
    os.rename(src, dst)


@pytest.fixture
def publish_capable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure publish path can commit on hosts without RENAME_NOREPLACE (e.g. WSL1)."""
    if release_mod.platform_supports_renameat2_noreplace():
        return
    monkeypatch.setattr(
        release_mod, "_renameat2_noreplace", _injectable_renameat2_noreplace
    )


@pytest.fixture(scope="module")
def happy_inputs() -> G1BuildInputs:
    return ref_tests._build_inputs()


@pytest.fixture(scope="module")
def happy_candidate(happy_inputs: G1BuildInputs) -> G1Candidate:
    return build_g1_candidate(inputs=happy_inputs)


@pytest.fixture(scope="module")
def policy() -> G1CrossSourcePolicy:
    return ref_tests._policy()


@pytest.fixture(scope="module")
def sample_plan(happy_candidate: G1Candidate, policy: G1CrossSourcePolicy) -> CrossSourceSamplePlan:
    return plan_cross_source_reconciliation(candidate=happy_candidate, policy=policy)


@pytest.fixture(scope="module")
def request_plan(sample_plan: CrossSourceSamplePlan) -> ReferenceRequestPlanV1:
    return plan_baostock_reference_requests(sample_plan=sample_plan)


@pytest.fixture(scope="module")
def reference_responses(
    happy_candidate: G1Candidate,
    sample_plan: CrossSourceSamplePlan,
    request_plan: ReferenceRequestPlanV1,
) -> tuple[VerifiedReferenceResponse, ...]:
    return ref_tests._perfect_reference_responses(
        happy_candidate, sample_plan, request_plan
    )


@pytest.fixture(scope="module")
def release_inputs(
    happy_inputs: G1BuildInputs,
    policy: G1CrossSourcePolicy,
    reference_responses: tuple[VerifiedReferenceResponse, ...],
) -> G1ReleaseInputs:
    return G1ReleaseInputs(
        build_inputs=happy_inputs,
        cross_source_policy=policy,
        reference_responses=reference_responses,
    )


@pytest.fixture(scope="module")
def prepared(release_inputs: G1ReleaseInputs) -> G1PreparedRelease:
    return prepare_g1_release(inputs=release_inputs)


def _entries(root: Path) -> set[str]:
    return {path.name for path in root.iterdir()}


def test_inputs_exact_rebuild(release_inputs: G1ReleaseInputs) -> None:
    again = G1ReleaseInputs(
        build_inputs=release_inputs.build_inputs,
        cross_source_policy=release_inputs.cross_source_policy,
        reference_responses=release_inputs.reference_responses,
    )
    assert again.build_inputs.build_spec == release_inputs.build_inputs.build_spec
    assert again.cross_source_policy == release_inputs.cross_source_policy
    assert len(again.reference_responses) == 30


def test_prepare_zero_io_network(
    release_inputs: G1ReleaseInputs, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("io/network forbidden")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(RawStore, "write", boom)
    monkeypatch.setattr("pathlib.Path.write_bytes", boom)
    monkeypatch.setattr("pathlib.Path.write_text", boom)
    monkeypatch.setattr("pathlib.Path.open", boom)
    prepared = prepare_g1_release(inputs=release_inputs)
    assert prepared.quality.passed is True
    assert prepared.quality.issues == ()
    assert prepared.primary_audit.passed is True
    assert prepared.reconciliation.passed is True


def test_release_identity_stable_under_row_shuffle(
    release_inputs: G1ReleaseInputs, prepared: G1PreparedRelease
) -> None:
    from quant.data.m3_backfill import VerifiedRawResponse

    frames = []
    for response in release_inputs.build_inputs.responses:
        frame = response.frame
        frames.append(frame.reverse() if frame.height > 1 else frame)
    rebuilt = tuple(
        VerifiedRawResponse(item.spec, item.receipt, item.receipt_sha256, frame)
        for item, frame in zip(release_inputs.build_inputs.responses, frames, strict=True)
    )
    altered = G1BuildInputs(
        build_spec=release_inputs.build_inputs.build_spec,
        request_plan=release_inputs.build_inputs.request_plan,
        responses=rebuilt,
        cninfo_responses=release_inputs.build_inputs.cninfo_responses,
        calendars=release_inputs.build_inputs.calendars.reverse(),
        instruments=release_inputs.build_inputs.instruments.reverse(),
        universe=release_inputs.build_inputs.universe,
        signal_start=release_inputs.build_inputs.signal_start,
        signal_end=release_inputs.build_inputs.signal_end,
        history=release_inputs.build_inputs.history,
        expected_constituent_count=release_inputs.build_inputs.expected_constituent_count,
        factor_ratio_rtol=release_inputs.build_inputs.factor_ratio_rtol,
    )
    other = prepare_g1_release(
        inputs=G1ReleaseInputs(
            build_inputs=altered,
            cross_source_policy=release_inputs.cross_source_policy,
            reference_responses=release_inputs.reference_responses,
        )
    )
    assert other.release_id == prepared.release_id


def test_release_identity_changes_on_calendar_cell(
    release_inputs: G1ReleaseInputs,
) -> None:
    calendars = release_inputs.build_inputs.calendars.with_columns(
        pl.when(pl.col("date") == release_inputs.build_inputs.history.start)
        .then(pl.lit(False))
        .otherwise(pl.col("is_open"))
        .alias("is_open")
    )
    altered = G1BuildInputs(
        build_spec=release_inputs.build_inputs.build_spec,
        request_plan=release_inputs.build_inputs.request_plan,
        responses=release_inputs.build_inputs.responses,
        cninfo_responses=release_inputs.build_inputs.cninfo_responses,
        calendars=calendars,
        instruments=release_inputs.build_inputs.instruments,
        universe=release_inputs.build_inputs.universe,
        signal_start=release_inputs.build_inputs.signal_start,
        signal_end=release_inputs.build_inputs.signal_end,
        history=release_inputs.build_inputs.history,
        expected_constituent_count=release_inputs.build_inputs.expected_constituent_count,
        factor_ratio_rtol=release_inputs.build_inputs.factor_ratio_rtol,
    )
    with pytest.raises(M3ReleaseError) as exc:
        prepare_g1_release(
            inputs=G1ReleaseInputs(
                build_inputs=altered,
                cross_source_policy=release_inputs.cross_source_policy,
                reference_responses=release_inputs.reference_responses,
            )
        )
    assert exc.value.code in {
        "G1_RELEASE_INPUT_INVALID",
        "G1_RELEASE_QUALITY_FAILED",
    }


def test_tolerance_change_changes_release_id(
    release_inputs: G1ReleaseInputs, prepared: G1PreparedRelease
) -> None:
    policy = G1CrossSourcePolicy(
        reference_source="baostock",
        sample_symbols=30,
        dates_per_symbol=20,
        price_atol=0.02,
        price_rtol=0.0001,
        volume_rtol=0.01,
        max_mismatch_rate=0.01,
    )
    other = prepare_g1_release(
        inputs=G1ReleaseInputs(
            build_inputs=release_inputs.build_inputs,
            cross_source_policy=policy,
            reference_responses=release_inputs.reference_responses,
        )
    )
    assert other.release_id != prepared.release_id


def test_no_caller_self_reported_candidate_entry() -> None:
    for fn in (prepare_g1_release, publish_g1_release):
        params = inspect.signature(fn).parameters
        assert "candidate" not in params
        assert "audit" not in params
        assert "quality" not in params


def test_quality_fail_zero_delta(
    tmp_path: Path,
    happy_candidate: G1Candidate,
    policy: G1CrossSourcePolicy,
    sample_plan: CrossSourceSamplePlan,
    request_plan: ReferenceRequestPlanV1,
    happy_inputs: G1BuildInputs,
    publish_capable: None,
) -> None:
    bad_responses = ref_tests._perfect_reference_responses(
        happy_candidate, sample_plan, request_plan
    )
    # Force cross-source fail with large mismatches beyond threshold.
    mismatched = ref_tests._bundle_with_n_mismatches(
        happy_candidate, sample_plan, request_plan, policy, 100
    )
    assert mismatched.passed is False
    # Build release inputs from mismatched responses extracted via helper path.
    responses = []
    by_symbol = ref_tests._sample_dates_by_symbol(sample_plan)
    remaining = 100
    for spec in request_plan.requests:
        dates = by_symbol[spec.symbol]
        rows = ref_tests._reference_rows_for_symbol(happy_candidate, spec.symbol, dates)
        for row in rows:
            if remaining > 0:
                row["close"] = ref_tests._num(float(row["close"]) + 1.0)
                remaining -= 1
        responses.append(
            ref_tests._make_verified_reference(spec, ref_tests._reference_frame(rows))
        )
    before = _entries(tmp_path) if tmp_path.exists() else set()
    with pytest.raises(M3ReleaseError) as exc:
        publish_g1_release(
            output_root=tmp_path,
            inputs=G1ReleaseInputs(
                build_inputs=happy_inputs,
                cross_source_policy=policy,
                reference_responses=tuple(responses),
            ),
        )
    assert exc.value.code == "G1_RELEASE_QUALITY_FAILED"
    assert _entries(tmp_path) == before
    del bad_responses


def test_publish_verify_happy_path(
    tmp_path: Path,
    release_inputs: G1ReleaseInputs,
    prepared: G1PreparedRelease,
    publish_capable: None,
) -> None:
    release = publish_g1_release(output_root=tmp_path, inputs=release_inputs)
    assert release.release_id == prepared.release_id
    assert release.root.name == release.release_id
    verified = verify_g1_release(release=release)
    assert verified.manifest.release_id == prepared.release_id
    assert len(verified.artifact_paths) == 17
    assert verified.quality.passed is True
    assert verified.quality.issues == ()
    names = {name for name, _ in verified.artifact_paths}
    assert names == set(release_mod._ARTIFACT_PATHS)
    assert "manifest.json" not in names
    # zero-write reuse
    marker = {p: p.stat().st_mtime_ns for p in release.root.iterdir()}
    again = publish_g1_release(output_root=tmp_path, inputs=release_inputs)
    assert again.root == release.root
    for path, mtime in marker.items():
        assert path.stat().st_mtime_ns == mtime


def test_quality_hash_not_in_release_id(prepared: G1PreparedRelease) -> None:
    assert prepared.quality.release_id == prepared.release_id
    quality_sha = hashlib.sha256(
        json.dumps(
            asdict(prepared.quality),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    assert quality_sha not in {
        prepared.release_id,
        prepared.reconciliation.summary_sha256,
        prepared.reconciliation.detail_sha256,
    }


def test_strict_json_readers(
    tmp_path: Path, release_inputs: G1ReleaseInputs, publish_capable: None
) -> None:
    release = publish_g1_release(output_root=tmp_path, inputs=release_inputs)
    manifest = read_g1_manifest(release.manifest_path)
    quality = read_g1_quality(release.quality_path)
    summary = read_cross_source_summary(release.root / "cross_source_reconciliation.json")
    assert manifest.release_id == release.release_id
    assert quality.passed is True
    assert summary.passed is True

    raw = release.manifest_path.read_bytes()
    # BOM
    bom_path = tmp_path / "bom.json"
    bom_path.write_bytes(b"\xef\xbb\xbf" + raw)
    with pytest.raises(M3ReleaseError) as exc:
        read_g1_manifest(bom_path)
    assert exc.value.code == "G1_RELEASE_JSON_INVALID"

    # duplicate key
    dup = raw.decode("utf-8").replace(
        '"schema_version":"m3-g1-manifest-v2"',
        '"schema_version":"m3-g1-manifest-v2","schema_version":"m3-g1-manifest-v2"',
        1,
    )
    dup_path = tmp_path / "dup.json"
    dup_path.write_text(dup, encoding="utf-8")
    with pytest.raises(M3ReleaseError):
        read_g1_manifest(dup_path)

    # non-canonical spacing
    spaced = json.dumps(json.loads(raw.decode("utf-8")), indent=2).encode("utf-8")
    spaced_path = tmp_path / "spaced.json"
    spaced_path.write_bytes(spaced)
    with pytest.raises(M3ReleaseError):
        read_g1_manifest(spaced_path)

    # bool as int
    quality_raw = json.loads(release.quality_path.read_text(encoding="utf-8"))
    quality_raw["error_count"] = False
    bad_q = tmp_path / "bad_q.json"
    bad_q.write_bytes(
        json.dumps(
            quality_raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )
    with pytest.raises(M3ReleaseError):
        read_g1_quality(bad_q)


def test_artifact_registry_closure(
    tmp_path: Path, release_inputs: G1ReleaseInputs, publish_capable: None
) -> None:
    release = publish_g1_release(output_root=tmp_path, inputs=release_inputs)
    verified = verify_g1_release(release=release)
    assert [p for p, _ in verified.artifact_paths] == sorted(release_mod._ARTIFACT_PATHS)
    assert set(_entries(release.root)) == set(release_mod._FINAL_ENTRY_NAMES)


def test_parquet_extra_column_rejected(
    tmp_path: Path, release_inputs: G1ReleaseInputs, publish_capable: None
) -> None:
    release = publish_g1_release(output_root=tmp_path, inputs=release_inputs)
    path = release.root / "instrument.parquet"
    frame = pl.read_parquet(path).with_columns(pl.lit("x").alias("extra"))
    # Directly overwrite final is outside publisher; simulate corrupted final for verifier.
    corrupted = tmp_path / "corrupt_case"
    corrupted.mkdir()
    # Copy tree then mutate one file via staging rewrite outside API.
    target = corrupted / release.release_id
    shutil.copytree(release.root, target)
    frame.write_parquet(target / "instrument.parquet", **release_mod._PARQUET_WRITE_KWARGS)
    with pytest.raises(M3ReleaseError):
        verify_g1_release(
            release=G1Release(
                release_id=release.release_id,
                root=target,
                manifest_path=target / "manifest.json",
                quality_path=target / "quality.json",
            )
        )


def test_coercible_dtype_rejected(
    tmp_path: Path, release_inputs: G1ReleaseInputs, publish_capable: None
) -> None:
    release = publish_g1_release(output_root=tmp_path, inputs=release_inputs)
    target_root = tmp_path / "dtype_case" / release.release_id
    shutil.copytree(release.root, target_root)
    frame = pl.read_parquet(target_root / "eligible_keys.parquet").with_columns(
        pl.col("symbol").cast(pl.Categorical)
    )
    frame.write_parquet(
        target_root / "eligible_keys.parquet", **release_mod._PARQUET_WRITE_KWARGS
    )
    with pytest.raises(M3ReleaseError):
        verify_g1_release(
            release=G1Release(
                release_id=release.release_id,
                root=target_root,
                manifest_path=target_root / "manifest.json",
                quality_path=target_root / "quality.json",
            )
        )


def test_primary_table_tamper_with_self_consistent_manifest_rejected(
    tmp_path: Path, release_inputs: G1ReleaseInputs, publish_capable: None
) -> None:
    release = publish_g1_release(output_root=tmp_path, inputs=release_inputs)
    target = tmp_path / "tamper" / release.release_id
    shutil.copytree(release.root, target)
    instruments = pl.read_parquet(target / "instrument.parquet")
    mutated = instruments.with_columns(pl.col("name") + "_x")
    raw = release_mod._frame_to_parquet_bytes(mutated)
    (target / "instrument.parquet").write_bytes(raw)
    manifest = read_g1_manifest(target / "manifest.json")
    files = []
    for entry in manifest.files:
        if entry.path != "instrument.parquet":
            files.append(entry)
            continue
        content = clean_table_content_sha256(table_name="instrument", frame=mutated)
        min_key, max_key = release_mod._key_range(mutated, entry.key_columns)
        files.append(
            release_mod.G1ArtifactEntryV1(
                path=entry.path,
                sha256=hashlib.sha256(raw).hexdigest(),
                content_sha256=content,
                size_bytes=len(raw),
                row_count=mutated.height,
                schema_name=entry.schema_name,
                table_schema_version=entry.table_schema_version,
                key_columns=entry.key_columns,
                min_key=min_key,
                max_key=max_key,
            )
        )
    new_manifest = G1ManifestV3(
        schema_version=manifest.schema_version,
        release_id=manifest.release_id,
        primary_candidate_key=manifest.primary_candidate_key,
        config_version=manifest.config_version,
        g1_config_sha256=manifest.g1_config_sha256,
        signal_start=manifest.signal_start,
        signal_end=manifest.signal_end,
        history_start=manifest.history_start,
        history_end=manifest.history_end,
        request_plan_sha256=manifest.request_plan_sha256,
        build_code_version=manifest.build_code_version,
        dependency_fingerprint_sha256=manifest.dependency_fingerprint_sha256,
        mapper_version=manifest.mapper_version,
        clean_schema_version=manifest.clean_schema_version,
        membership_method_version=manifest.membership_method_version,
        price_limit_method_version=manifest.price_limit_method_version,
        corporate_action_selection_version=manifest.corporate_action_selection_version,
        corporate_action_reconciliation_version=(
            manifest.corporate_action_reconciliation_version
        ),
        benchmark_mode=manifest.benchmark_mode,
        benchmark_method_version=manifest.benchmark_method_version,
        benchmark_dividend_reconciliation_version=(
            manifest.benchmark_dividend_reconciliation_version
        ),
        input_receipts=manifest.input_receipts,
        price_limit_required_keys_sha256=manifest.price_limit_required_keys_sha256,
        sample_plan_sha256=manifest.sample_plan_sha256,
        cross_source_summary_sha256=manifest.cross_source_summary_sha256,
        quality_sha256=manifest.quality_sha256,
        files=tuple(sorted(files, key=lambda e: e.path)),
    )
    (target / "manifest.json").write_bytes(
        release_mod._canonical_json_bytes(release_mod._manifest_to_jsonable(new_manifest))
    )
    with pytest.raises(M3ReleaseError) as exc:
        verify_g1_release(
            release=G1Release(
                release_id=release.release_id,
                root=target,
                manifest_path=target / "manifest.json",
                quality_path=target / "quality.json",
            )
        )
    assert exc.value.code in {
        "G1_RELEASE_IDENTITY_MISMATCH",
        "G1_RELEASE_VERIFY_FAILED",
        "G1_RELEASE_ARTIFACT_INVALID",
    }


def test_extra_hidden_and_fifo_rejected(
    tmp_path: Path, release_inputs: G1ReleaseInputs, publish_capable: None
) -> None:
    release = publish_g1_release(output_root=tmp_path, inputs=release_inputs)
    target = tmp_path / "extra" / release.release_id
    shutil.copytree(release.root, target)
    (target / ".hidden").write_text("x", encoding="utf-8")
    with pytest.raises(M3ReleaseError):
        verify_g1_release(
            release=G1Release(
                release_id=release.release_id,
                root=target,
                manifest_path=target / "manifest.json",
                quality_path=target / "quality.json",
            )
        )
    shutil.rmtree(target)
    shutil.copytree(release.root, target)
    fifo = target / "noise.fifo"
    os.mkfifo(fifo)
    with pytest.raises(M3ReleaseError):
        verify_g1_release(
            release=G1Release(
                release_id=release.release_id,
                root=target,
                manifest_path=target / "manifest.json",
                quality_path=target / "quality.json",
            )
        )


def test_symlink_and_hardlink_rejected(
    tmp_path: Path, release_inputs: G1ReleaseInputs, publish_capable: None
) -> None:
    release = publish_g1_release(output_root=tmp_path, inputs=release_inputs)
    target = tmp_path / "link" / release.release_id
    shutil.copytree(release.root, target)
    os.remove(target / "quality.json")
    os.symlink("manifest.json", target / "quality.json")
    with pytest.raises(M3ReleaseError):
        verify_g1_release(
            release=G1Release(
                release_id=release.release_id,
                root=target,
                manifest_path=target / "manifest.json",
                quality_path=target / "quality.json",
            )
        )
    shutil.rmtree(target)
    shutil.copytree(release.root, target)
    os.link(target / "manifest.json", target / "quality.json.bak")
    # Replace quality with hardlink to manifest → nlink>1 and/or content mismatch.
    os.remove(target / "quality.json")
    os.link(target / "manifest.json", target / "quality.json")
    with pytest.raises(M3ReleaseError):
        verify_g1_release(
            release=G1Release(
                release_id=release.release_id,
                root=target,
                manifest_path=target / "manifest.json",
                quality_path=target / "quality.json",
            )
        )


def _assert_verify_failed_sanitized(exc: BaseException, *, tmp_path: Path) -> None:
    assert isinstance(exc, M3ReleaseError)
    assert exc.code == "G1_RELEASE_VERIFY_FAILED"
    assert str(exc) == "G1_RELEASE_VERIFY_FAILED"
    assert exc.__cause__ is None
    text = str(exc)
    assert str(tmp_path) not in text
    assert "/mnt/" not in text


def test_verify_mid_ancestor_replaced_with_symlink_rejected(
    tmp_path: Path,
    release_inputs: G1ReleaseInputs,
    monkeypatch: pytest.MonkeyPatch,
    publish_capable: None,
) -> None:
    """P0-1: mid-verify ancestor→symlink must fail closed via public verify."""
    mid = tmp_path / "mid_symlink"
    alt = tmp_path / "alt_symlink"
    release = publish_g1_release(output_root=mid, inputs=release_inputs)
    real_parse = release_mod._parse_manifest_bytes

    def swap_then_parse(payload: bytes) -> Any:
        result = real_parse(payload)
        if mid.exists() and not mid.is_symlink():
            shutil.move(mid, alt)
            os.symlink(alt, mid)
        return result

    monkeypatch.setattr(release_mod, "_parse_manifest_bytes", swap_then_parse)
    try:
        with pytest.raises(M3ReleaseError) as excinfo:
            verify_g1_release(release=release)
        _assert_verify_failed_sanitized(excinfo.value, tmp_path=tmp_path)
    finally:
        monkeypatch.undo()
        if mid.is_symlink():
            mid.unlink()
        if mid.exists():
            shutil.rmtree(mid)
        if alt.exists():
            shutil.rmtree(alt)


def test_verify_mid_ancestor_real_dir_inode_drift_rejected(
    tmp_path: Path,
    release_inputs: G1ReleaseInputs,
    monkeypatch: pytest.MonkeyPatch,
    publish_capable: None,
) -> None:
    """P0-1: mid-verify ancestor real-dir inode drift (no symlink) must reject."""
    mid = tmp_path / "mid_inode"
    alt = tmp_path / "alt_inode"
    release = publish_g1_release(output_root=mid, inputs=release_inputs)
    real_parse = release_mod._parse_manifest_bytes

    def swap_real_dir_then_parse(payload: bytes) -> Any:
        result = real_parse(payload)
        if mid.exists() and not mid.is_symlink() and not alt.exists():
            shutil.move(mid, alt)
            mid.mkdir()
            shutil.move(alt / release.release_id, mid / release.release_id)
            if alt.exists():
                shutil.rmtree(alt)
        return result

    monkeypatch.setattr(release_mod, "_parse_manifest_bytes", swap_real_dir_then_parse)
    try:
        with pytest.raises(M3ReleaseError) as excinfo:
            verify_g1_release(release=release)
        _assert_verify_failed_sanitized(excinfo.value, tmp_path=tmp_path)
    finally:
        monkeypatch.undo()
        if mid.exists():
            shutil.rmtree(mid)
        if alt.exists():
            shutil.rmtree(alt)


def test_corrupt_final_not_overwritten(
    tmp_path: Path,
    release_inputs: G1ReleaseInputs,
    prepared: G1PreparedRelease,
    publish_capable: None,
) -> None:
    final = tmp_path / prepared.release_id
    final.mkdir()
    (final / "manifest.json").write_text("{}", encoding="utf-8")
    before = _entries(tmp_path)
    with pytest.raises(M3ReleaseError) as exc:
        publish_g1_release(output_root=tmp_path, inputs=release_inputs)
    assert exc.value.code == "G1_RELEASE_VERIFY_FAILED"
    assert _entries(tmp_path) == before
    assert (final / "manifest.json").read_text(encoding="utf-8") == "{}"


def test_empty_final_concurrent_not_overwritten(
    tmp_path: Path,
    release_inputs: G1ReleaseInputs,
    prepared: G1PreparedRelease,
    publish_capable: None,
) -> None:
    final = tmp_path / prepared.release_id
    final.mkdir()
    with pytest.raises(M3ReleaseError) as exc:
        publish_g1_release(output_root=tmp_path, inputs=release_inputs)
    assert exc.value.code == "G1_RELEASE_VERIFY_FAILED"
    assert list(final.iterdir()) == []


def test_renameat2_eexist_reuses_winner(
    tmp_path: Path,
    release_inputs: G1ReleaseInputs,
    prepared: G1PreparedRelease,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def fake(src: Path, dst: Path) -> None:
        calls["n"] += 1
        if not dst.exists():
            shutil.copytree(src, dst)
        raise M3ReleaseError("G1_RELEASE_CONCURRENT_PUBLISH")

    monkeypatch.setattr(release_mod, "_renameat2_noreplace", fake)
    reused = publish_g1_release(output_root=tmp_path, inputs=release_inputs)
    assert reused.release_id == prepared.release_id
    assert calls["n"] == 1
    assert (tmp_path / prepared.release_id / "manifest.json").is_file()


def test_renameat2_unsupported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, release_inputs: G1ReleaseInputs
) -> None:
    def boom(src: Path, dst: Path) -> None:
        raise M3ReleaseError("G1_RELEASE_PUBLISH_UNSUPPORTED")

    monkeypatch.setattr(release_mod, "_renameat2_noreplace", boom)
    with pytest.raises(M3ReleaseError) as exc:
        publish_g1_release(output_root=tmp_path, inputs=release_inputs)
    assert exc.value.code == "G1_RELEASE_PUBLISH_UNSUPPORTED"


def test_fsync_fault_and_primary_priority(
    tmp_path: Path,
    release_inputs: G1ReleaseInputs,
    monkeypatch: pytest.MonkeyPatch,
    publish_capable: None,
) -> None:
    real_fsync = os.fsync
    state = {"fail": False}

    def flaky(fd: int) -> None:
        if state["fail"]:
            raise OSError("fsync boom")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", flaky)
    state["fail"] = True
    with pytest.raises(M3ReleaseError) as exc:
        publish_g1_release(output_root=tmp_path, inputs=release_inputs)
    assert exc.value.code == "G1_RELEASE_IO_FAILED"
    assert not any(len(p.name) == 64 and p.is_dir() for p in tmp_path.iterdir())


def test_static_no_rename_fallback() -> None:
    source = Path(release_mod.__file__).read_text(encoding="utf-8")
    assert "os.rename(" not in source
    assert "os.replace(" not in source
    assert "renameat2" in source
    # Windows-native track uses MoveFileExW; must not silently fall back to os.rename.
    if os.name == "nt":
        assert "MoveFileExW" in source
        assert "_windows_movefileex_noreplace" in source
    # Binary write path must include O_BINARY on Windows (text mode corrupts parquet).
    assert "O_BINARY" in source
    assert "_O_BINARY" in source
    assert "_exclusive_write_bytes" in source
    assert "_fsync_directory" in source


def test_package_export_and_no_research_import() -> None:
    assert qd.prepare_g1_release is prepare_g1_release
    assert qd.publish_g1_release is publish_g1_release
    assert qd.verify_g1_release is verify_g1_release
    assert qd.M3ReleaseError is M3ReleaseError
    source = Path(release_mod.__file__).read_text(encoding="utf-8")
    assert "quant.research" not in source
    assert "BaostockConnector" not in source
    assert "TushareConnector" not in source


def test_error_surfaces_no_path_leak(
    tmp_path: Path, release_inputs: G1ReleaseInputs, publish_capable: None
) -> None:
    final = tmp_path / "not-a-hex"
    # Invalid release object
    with pytest.raises(ValueError):
        G1Release(
            release_id="zz",
            root=tmp_path / "zz",
            manifest_path=tmp_path / "zz" / "manifest.json",
            quality_path=tmp_path / "zz" / "quality.json",
        )
    release = publish_g1_release(output_root=tmp_path, inputs=release_inputs)
    # Corrupt quality path content
    release.quality_path.write_text("{bad", encoding="utf-8")
    with pytest.raises(M3ReleaseError) as exc:
        verify_g1_release(release=release)
    text = str(exc.value)
    assert str(tmp_path) not in text
    assert "traceback" not in text.lower()
    assert text == exc.value.code
    del final


def test_prepared_rejects_self_reported_quality(
    prepared: G1PreparedRelease,
) -> None:
    lying = G1QualityReportV1(
        schema_version="m3-g1-quality-v1",
        release_id=prepared.release_id,
        primary_candidate_key=prepared.candidate.primary_candidate_key,
        plan_sha256=prepared.candidate.request_plan.plan_sha256,
        error_count=0,
        warning_count=0,
        passed=True,
        issues=(),
    )
    # Different release_id self-report
    with pytest.raises(M3ReleaseError):
        G1PreparedRelease(
            candidate=prepared.candidate,
            primary_audit=prepared.primary_audit,
            reconciliation=prepared.reconciliation,
            release_id="b" * 64,
            quality=lying,
        )


def test_real_renameat2_noclobber(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    with pytest.raises(M3ReleaseError) as exc:
        release_mod._renameat2_noreplace(src, dst)
    # Supporting kernels / Windows MoveFileEx: concurrent; WSL1/unsupported: publish unsupported.
    assert exc.value.code in {
        "G1_RELEASE_CONCURRENT_PUBLISH",
        "G1_RELEASE_PUBLISH_UNSUPPORTED",
    }


def test_platform_probe_is_bool() -> None:
    assert isinstance(release_mod.platform_supports_renameat2_noreplace(), bool)


def _b1b_minimal_manifest_payload(*, schema: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    hex64 = "a" * 64
    receipt = {
        "source": "tushare",
        "request_id": hex64,
        "endpoint": "fund_daily",
        "parameters_sha256": hex64,
        "stable_response_sha256": hex64,
        "row_count": 1,
        "columns": ["ts_code"],
    }
    files = []
    for spec in release_mod._ARTIFACT_REGISTRY:
        row_count = 1 if spec.kind in {"summary", "quality"} else 0
        files.append(
            {
                "path": spec.path,
                "sha256": hex64,
                "content_sha256": hex64,
                "size_bytes": 1,
                "row_count": row_count,
                "schema_name": spec.schema_name,
                "table_schema_version": release_mod._TABLE_SCHEMA_VERSION,
                "key_columns": list(spec.key_columns),
                "min_key": None,
                "max_key": None,
            }
        )
    files.sort(key=lambda item: item["path"])
    payload: dict[str, Any] = {
        "schema_version": schema,
        "release_id": hex64,
        "primary_candidate_key": hex64,
        "config_version": "1.0.0",
        "g1_config_sha256": hex64,
        "signal_start": "2016-01-04",
        "signal_end": "2016-01-05",
        "history_start": "2015-10-08",
        "history_end": "2016-01-10",
        "request_plan_sha256": hex64,
        "build_code_version": "m3-g1-code-v1-" + hex64,
        "dependency_fingerprint_sha256": hex64,
        "mapper_version": "m3-g1-tushare-mapper-v1",
        "clean_schema_version": "m3-g1-clean-schema-v1",
        "membership_method_version": "tushare_monthly_observed_next_session_close_v1",
        "price_limit_method_version": "tushare_stk_limit_v1",
        "corporate_action_selection_version": "tushare_dividend_implemented_v1",
        "corporate_action_reconciliation_version": "adj_factor_jump_v1",
        "input_receipts": [receipt],
        "price_limit_required_keys_sha256": hex64,
        "sample_plan_sha256": hex64,
        "cross_source_summary_sha256": hex64,
        "quality_sha256": hex64,
        "files": files,
    }
    if schema == "m3-g1-manifest-v2":
        payload["mapper_version"] = "m3-g1-tushare-mapper-v2"
        payload["benchmark_mode"] = "TRADEABLE_ETF_TOTAL_RETURN_PROXY"
        payload["benchmark_method_version"] = (
            "tushare_510300_fund_daily_fund_adj_hfq_v1"
        )
        payload["benchmark_dividend_reconciliation_version"] = (
            "tushare_fund_div_implemented_cash_v1"
        )
    if schema == "m3-g1-manifest-v3":
        payload["mapper_version"] = "m3-g1-tushare-mapper-v3"
        payload["benchmark_mode"] = "TRADEABLE_ETF_TOTAL_RETURN_PROXY"
        payload["benchmark_method_version"] = (
            "tushare_510300_fund_daily_fund_adj_hfq_v1"
        )
        payload["benchmark_dividend_reconciliation_version"] = (
            "tushare_fund_div_implemented_cash_v1"
        )
    if schema == "m3-g1-manifest-v4":
        payload["mapper_version"] = "m3-g1-tushare-mapper-v4"
        payload["benchmark_mode"] = "TRADEABLE_ETF_TOTAL_RETURN_PROXY"
        payload["benchmark_method_version"] = (
            "tushare_510300_fund_daily_fund_adj_hfq_v1"
        )
        payload["benchmark_dividend_reconciliation_version"] = (
            "tushare_fund_div_implemented_cash_v1"
        )
        cninfo_receipt = {
            "source": "cninfo",
            "request_id": "b" * 64,
            "endpoint": "stock_allotment",
            "parameters_sha256": hex64,
            "stable_response_sha256": hex64,
            "row_count": 0,
            "columns": list(CNINFO_STOCK_ALLOTMENT_FIELDS),
        }
        # Manifest requires receipts sorted by (source, endpoint, request_id).
        payload["input_receipts"] = [cninfo_receipt, receipt]
        for item in payload["files"]:
            item["table_schema_version"] = "v2"
    if schema == "m3-g1-manifest-v5":
        payload["mapper_version"] = "m3-g1-tushare-mapper-v5"
        payload["benchmark_mode"] = "TRADEABLE_ETF_TOTAL_RETURN_PROXY"
        payload["benchmark_method_version"] = (
            "tushare_510300_fund_daily_fund_adj_hfq_v1"
        )
        payload["benchmark_dividend_reconciliation_version"] = (
            "tushare_fund_div_implemented_cash_v1"
        )
        cninfo_receipt = {
            "source": "cninfo",
            "request_id": "b" * 64,
            "endpoint": "stock_allotment",
            "parameters_sha256": hex64,
            "stable_response_sha256": hex64,
            "row_count": 0,
            "columns": list(CNINFO_STOCK_ALLOTMENT_FIELDS),
        }
        payload["input_receipts"] = [cninfo_receipt, receipt]
    if extra:
        payload.update(extra)
    return payload


def test_b1b_manifest_v1_strict_read_v2_current_and_forged_rejected() -> None:
    v1 = release_mod._parse_manifest_bytes(
        release_mod._canonical_json_bytes(_b1b_minimal_manifest_payload(schema="m3-g1-manifest-v1"))
    )
    assert type(v1) is G1ManifestV1
    assert not hasattr(v1, "benchmark_mode")

    v2 = release_mod._parse_manifest_bytes(
        release_mod._canonical_json_bytes(_b1b_minimal_manifest_payload(schema="m3-g1-manifest-v2"))
    )
    assert type(v2) is G1ManifestV2
    assert v2.benchmark_mode == "TRADEABLE_ETF_TOTAL_RETURN_PROXY"

    v3 = release_mod._parse_manifest_bytes(
        release_mod._canonical_json_bytes(_b1b_minimal_manifest_payload(schema="m3-g1-manifest-v3"))
    )
    assert type(v3) is G1ManifestV3
    assert v3.mapper_version == "m3-g1-tushare-mapper-v3"

    v4 = release_mod._parse_manifest_bytes(
        release_mod._canonical_json_bytes(_b1b_minimal_manifest_payload(schema="m3-g1-manifest-v4"))
    )
    assert type(v4) is G1ManifestV4
    assert v4.mapper_version == "m3-g1-tushare-mapper-v4"
    assert any(item.source == "cninfo" for item in v4.input_receipts)

    v5 = release_mod._parse_manifest_bytes(
        release_mod._canonical_json_bytes(_b1b_minimal_manifest_payload(schema="m3-g1-manifest-v5"))
    )
    assert type(v5) is G1ManifestV5
    assert v5.mapper_version == "m3-g1-tushare-mapper-v5"
    assert any(
        item.source == "cninfo"
        and item.columns == CNINFO_STOCK_ALLOTMENT_FIELDS
        for item in v5.input_receipts
    )

    # Current publish path only emits v5.
    assert release_mod._MANIFEST_SCHEMA == "m3-g1-manifest-v5"
    assert release_mod._build_manifest.__annotations__["return"] == "G1ManifestV5"
    assert release_mod._TABLE_SCHEMA_VERSION == "v3"

    with pytest.raises(M3ReleaseError):
        release_mod._parse_manifest_bytes(
            release_mod._canonical_json_bytes(
                _b1b_minimal_manifest_payload(schema="m3-g1-manifest-v9")
            )
        )
    # v1 payload must not silently accept v2 identity fields.
    with pytest.raises(M3ReleaseError):
        release_mod._parse_manifest_bytes(
            release_mod._canonical_json_bytes(
                _b1b_minimal_manifest_payload(
                    schema="m3-g1-manifest-v1",
                    extra={"benchmark_mode": "TRADEABLE_ETF_TOTAL_RETURN_PROXY"},
                )
            )
        )
    # Forged benchmark method on v2 fail-closed.
    with pytest.raises((M3ReleaseError, ValueError)):
        release_mod._parse_manifest_bytes(
            release_mod._canonical_json_bytes(
                _b1b_minimal_manifest_payload(
                    schema="m3-g1-manifest-v2",
                    extra={
                        "benchmark_method_version": "forged_index_daily_close_only_v0"
                    },
                )
            )
        )
    # v2 missing one identity field fail-closed.
    missing = _b1b_minimal_manifest_payload(schema="m3-g1-manifest-v2")
    del missing["benchmark_dividend_reconciliation_version"]
    with pytest.raises(M3ReleaseError):
        release_mod._parse_manifest_bytes(release_mod._canonical_json_bytes(missing))


def test_b1b_r4_manifest_mapper_version_exact_lock() -> None:
    """v1/v2/v3 must lock exact mapper literals; cross-version and unknown fail closed."""
    v1 = release_mod._parse_manifest_bytes(
        release_mod._canonical_json_bytes(
            _b1b_minimal_manifest_payload(schema="m3-g1-manifest-v1")
        )
    )
    assert type(v1) is G1ManifestV1
    assert v1.mapper_version == "m3-g1-tushare-mapper-v1"

    v2 = release_mod._parse_manifest_bytes(
        release_mod._canonical_json_bytes(
            _b1b_minimal_manifest_payload(schema="m3-g1-manifest-v2")
        )
    )
    assert type(v2) is G1ManifestV2
    assert v2.mapper_version == "m3-g1-tushare-mapper-v2"

    v3 = release_mod._parse_manifest_bytes(
        release_mod._canonical_json_bytes(
            _b1b_minimal_manifest_payload(schema="m3-g1-manifest-v3")
        )
    )
    assert type(v3) is G1ManifestV3
    assert v3.mapper_version == "m3-g1-tushare-mapper-v3"

    v4 = release_mod._parse_manifest_bytes(
        release_mod._canonical_json_bytes(
            _b1b_minimal_manifest_payload(schema="m3-g1-manifest-v4")
        )
    )
    assert type(v4) is G1ManifestV4
    assert v4.mapper_version == "m3-g1-tushare-mapper-v4"

    v5 = release_mod._parse_manifest_bytes(
        release_mod._canonical_json_bytes(
            _b1b_minimal_manifest_payload(schema="m3-g1-manifest-v5")
        )
    )
    assert type(v5) is G1ManifestV5
    assert v5.mapper_version == "m3-g1-tushare-mapper-v5"

    # v2 schema + v1 mapper must not parse as current v2 identity.
    with pytest.raises((M3ReleaseError, ValueError)):
        release_mod._parse_manifest_bytes(
            release_mod._canonical_json_bytes(
                _b1b_minimal_manifest_payload(
                    schema="m3-g1-manifest-v2",
                    extra={"mapper_version": "m3-g1-tushare-mapper-v1"},
                )
            )
        )
    # v1 schema + v2 mapper must not silently upgrade.
    with pytest.raises((M3ReleaseError, ValueError)):
        release_mod._parse_manifest_bytes(
            release_mod._canonical_json_bytes(
                _b1b_minimal_manifest_payload(
                    schema="m3-g1-manifest-v1",
                    extra={"mapper_version": "m3-g1-tushare-mapper-v2"},
                )
            )
        )
    # v3 schema must not accept v2 mapper (no old version disguised as current).
    with pytest.raises((M3ReleaseError, ValueError)):
        release_mod._parse_manifest_bytes(
            release_mod._canonical_json_bytes(
                _b1b_minimal_manifest_payload(
                    schema="m3-g1-manifest-v3",
                    extra={"mapper_version": "m3-g1-tushare-mapper-v2"},
                )
            )
        )
    # v2 schema must not accept v3 mapper (historical reader stays exact).
    with pytest.raises((M3ReleaseError, ValueError)):
        release_mod._parse_manifest_bytes(
            release_mod._canonical_json_bytes(
                _b1b_minimal_manifest_payload(
                    schema="m3-g1-manifest-v2",
                    extra={"mapper_version": "m3-g1-tushare-mapper-v3"},
                )
            )
        )
    # v4/current-v5 mix must fail closed.
    with pytest.raises((M3ReleaseError, ValueError)):
        release_mod._parse_manifest_bytes(
            release_mod._canonical_json_bytes(
                _b1b_minimal_manifest_payload(
                    schema="m3-g1-manifest-v4",
                    extra={"mapper_version": "m3-g1-tushare-mapper-v5"},
                )
            )
        )
    with pytest.raises((M3ReleaseError, ValueError)):
        release_mod._parse_manifest_bytes(
            release_mod._canonical_json_bytes(
                _b1b_minimal_manifest_payload(
                    schema="m3-g1-manifest-v5",
                    extra={"mapper_version": "m3-g1-tushare-mapper-v4"},
                )
            )
        )
    for bad_mapper in (
        "m3-g1-tushare-mapper-v9",
        "",
        "forged-mapper",
    ):
        with pytest.raises((M3ReleaseError, ValueError)):
            release_mod._parse_manifest_bytes(
                release_mod._canonical_json_bytes(
                    _b1b_minimal_manifest_payload(
                        schema="m3-g1-manifest-v2",
                        extra={"mapper_version": bad_mapper},
                    )
                )
            )
        with pytest.raises((M3ReleaseError, ValueError)):
            release_mod._parse_manifest_bytes(
                release_mod._canonical_json_bytes(
                    _b1b_minimal_manifest_payload(
                        schema="m3-g1-manifest-v1",
                        extra={"mapper_version": bad_mapper},
                    )
                )
            )
        with pytest.raises((M3ReleaseError, ValueError)):
            release_mod._parse_manifest_bytes(
                release_mod._canonical_json_bytes(
                    _b1b_minimal_manifest_payload(
                        schema="m3-g1-manifest-v3",
                        extra={"mapper_version": bad_mapper},
                    )
                )
            )
        with pytest.raises((M3ReleaseError, ValueError)):
            release_mod._parse_manifest_bytes(
                release_mod._canonical_json_bytes(
                    _b1b_minimal_manifest_payload(
                        schema="m3-g1-manifest-v4",
                        extra={"mapper_version": bad_mapper},
                    )
                )
            )
        with pytest.raises((M3ReleaseError, ValueError)):
            release_mod._parse_manifest_bytes(
                release_mod._canonical_json_bytes(
                    _b1b_minimal_manifest_payload(
                        schema="m3-g1-manifest-v5",
                        extra={"mapper_version": bad_mapper},
                    )
                )
            )

    # Non-string mapper_version fail-closed at construction.
    v2_payload = _b1b_minimal_manifest_payload(schema="m3-g1-manifest-v2")
    v2_payload["mapper_version"] = True
    with pytest.raises((M3ReleaseError, ValueError, TypeError)):
        release_mod._parse_manifest_bytes(
            release_mod._canonical_json_bytes(v2_payload)
        )
    v1_payload = _b1b_minimal_manifest_payload(schema="m3-g1-manifest-v1")
    v1_payload["mapper_version"] = 123
    with pytest.raises((M3ReleaseError, ValueError, TypeError)):
        release_mod._parse_manifest_bytes(
            release_mod._canonical_json_bytes(v1_payload)
        )
    v3_payload = _b1b_minimal_manifest_payload(schema="m3-g1-manifest-v3")
    v3_payload["mapper_version"] = True
    with pytest.raises((M3ReleaseError, ValueError, TypeError)):
        release_mod._parse_manifest_bytes(
            release_mod._canonical_json_bytes(v3_payload)
        )
    v4_payload = _b1b_minimal_manifest_payload(schema="m3-g1-manifest-v4")
    v4_payload["mapper_version"] = True
    with pytest.raises((M3ReleaseError, ValueError, TypeError)):
        release_mod._parse_manifest_bytes(
            release_mod._canonical_json_bytes(v4_payload)
        )
    v5_payload = _b1b_minimal_manifest_payload(schema="m3-g1-manifest-v5")
    v5_payload["mapper_version"] = True
    with pytest.raises((M3ReleaseError, ValueError, TypeError)):
        release_mod._parse_manifest_bytes(
            release_mod._canonical_json_bytes(v5_payload)
        )

    assert release_mod._MANIFEST_MAPPER_VERSION_V1 == "m3-g1-tushare-mapper-v1"
    assert release_mod._MANIFEST_MAPPER_VERSION_V2 == "m3-g1-tushare-mapper-v2"
    assert release_mod._MANIFEST_MAPPER_VERSION_V3 == "m3-g1-tushare-mapper-v3"
    assert release_mod._MANIFEST_MAPPER_VERSION_V4 == "m3-g1-tushare-mapper-v4"
    assert release_mod._MANIFEST_MAPPER_VERSION_V5 == "m3-g1-tushare-mapper-v5"


def test_p0f_r1_cninfo_projection_columns_exact_lock() -> None:
    from quant.data.m3_g1_candidate import G1ReceiptProjectionV1

    hex64 = "a" * 64
    base = {
        "source": "cninfo",
        "request_id": hex64,
        "endpoint": "stock_allotment",
        "parameters_sha256": hex64,
        "stable_response_sha256": hex64,
        "row_count": 0,
    }
    ok = G1ReceiptProjectionV1(**base, columns=CNINFO_STOCK_ALLOTMENT_FIELDS)
    assert ok.columns == CNINFO_STOCK_ALLOTMENT_FIELDS
    with pytest.raises(ValueError):
        G1ReceiptProjectionV1(**base, columns=("SECCODE",))
    with pytest.raises(ValueError):
        G1ReceiptProjectionV1(
            **base, columns=CNINFO_STOCK_ALLOTMENT_FIELDS + ("EXTRA",)
        )
    shuffled = tuple(reversed(CNINFO_STOCK_ALLOTMENT_FIELDS))
    with pytest.raises(ValueError):
        G1ReceiptProjectionV1(**base, columns=shuffled)
    # Non-CNINFO projections remain unconstrained beyond string tuple.
    tushare = G1ReceiptProjectionV1(
        source="tushare",
        request_id=hex64,
        endpoint="daily",
        parameters_sha256=hex64,
        stable_response_sha256=hex64,
        row_count=1,
        columns=("ts_code",),
    )
    assert tushare.columns == ("ts_code",)
    # Disk v5 parse rejects truncated CNINFO columns.
    truncated = _b1b_minimal_manifest_payload(schema="m3-g1-manifest-v5")
    truncated["input_receipts"][0]["columns"] = ["SECCODE"]
    with pytest.raises((M3ReleaseError, ValueError)):
        release_mod._parse_manifest_bytes(
            release_mod._canonical_json_bytes(truncated)
        )
