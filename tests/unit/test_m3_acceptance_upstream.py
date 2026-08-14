"""Focused G9C acceptance checks over strict fake upstream evidence."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import polars as pl
import pytest

from quant.research.m3.acceptance import (
    AcceptanceEvidencePlanV1,
    VerifiedAcceptanceSubject,
    VerifiedComparisonIdentityV1,
    VerifiedRuntimeIdentity,
    build_acceptance_evidence_plan,
)
from quant.research.m3.acceptance_upstream import (
    M3AcceptanceUpstreamError,
    audit_acceptance_upstream,
)
from quant.research.m3.config import LoadedM3Config, load_m3_config
from quant.research.m3.contracts import (
    ExperimentIdentityManifestV1,
    FoldPlanManifestV1,
    LabelArtifactManifest,
    LabelReconciliationSummaryV1,
    PlannedFold,
    ProviderManifestV1,
    ProviderValidationSummaryV1,
    SnapshotArtifactEntryV1,
    SnapshotManifestV1,
    SnapshotRequestRecordV1,
    VerifiedExperimentIdentity,
    VerifiedFoldPlanArtifact,
    VerifiedProviderArtifact,
    VerifiedProviderValidationArtifact,
    VerifiedSnapshotArtifact,
)
from quant.research.m3.readiness_evidence import (
    ReadinessEvidenceReportV1,
    VerifiedReadinessEvidenceArtifact,
)
from quant.research.m3.run_state import (
    ArtifactDigest,
    StageReceipt,
    publish_stage_receipt,
)
from quant.research.m3.snapshot import snapshot_id_from_manifest

_EXAMPLE = Path("configs/research/m3_qlib_example.toml")


def _hex(character: str) -> str:
    return character * 64


def _canonical(value: object) -> bytes:
    def default(item: object) -> str:
        if type(item) is dt.date:
            return item.isoformat()
        raise TypeError

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        default=default,
    ).encode("utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config(tmp_path: Path, *, enabled: bool) -> LoadedM3Config:
    raw = _EXAMPLE.read_text(encoding="utf-8")
    raw = raw.replace("enabled = false", f"enabled = {str(enabled).lower()}", 1)
    path = tmp_path / "m3.toml"
    path.write_text(raw, encoding="utf-8")
    return load_m3_config(path)


def _write(path: Path, raw: bytes = b"evidence") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def _publish(
    root: Path,
    *,
    relative: str,
    stage: str,
    scope: str,
    scope_key: str,
    output: Path,
) -> tuple[StageReceipt, str]:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    receipt = publish_stage_receipt(
        receipt_path=path,
        stage=stage,
        scope=scope,  # type: ignore[arg-type]
        scope_key=scope_key,
        artifact_roots={"G8": root},
        inputs=(),
        outputs=(("G8", output),),
    )
    return receipt, _sha(path)


@dataclass(frozen=True)
class _Bundle:
    subject: VerifiedAcceptanceSubject
    plan: AcceptanceEvidencePlanV1
    config: LoadedM3Config
    roots: dict[str, Path]
    root: Path


def _bundle(tmp_path: Path, *, enabled: bool = True) -> _Bundle:
    config = _config(tmp_path, enabled=enabled)
    root = tmp_path / "stage"
    root.mkdir()
    roots = {"G8": root}

    readiness_key = _hex("a")
    snapshot_id = _hex("b")
    request_key = _hex("c")
    release_id = _hex("d")
    release_manifest_sha = _hex("e")
    snapshot_manifest_sha = _hex("f")
    provider_key = _hex("1")
    provider_manifest_sha = _hex("2")
    validation_key = _hex("3")
    experiment_key = _hex("4")
    experiment_manifest_sha = _hex("5")
    dependency_sha = _hex("6")
    runtime_sha = _hex("7")
    code_version = "test-code-v1"

    readiness_report = ReadinessEvidenceReportV1(
        "m3-readiness-evidence-v1",
        readiness_key,
        release_id,
        release_manifest_sha,
        config.full_config_sha256,
        runtime_sha,
        code_version,
        dependency_sha,
        (),
    )
    readiness_output = _write(
        root / "fake/readiness/readiness_report.json",
        _canonical(asdict(readiness_report)) + b"\n",
    )
    readiness_receipt, readiness_receipt_sha = _publish(
        root,
        relative=f"receipts/readiness-evidence/{readiness_key}.json",
        stage="readiness-evidence",
        scope="ACCEPTANCE",
        scope_key=readiness_key,
        output=readiness_output,
    )
    readiness = VerifiedReadinessEvidenceArtifact(
        readiness_output.parent,
        readiness_report,
        readiness_receipt.outputs[0],
        readiness_receipt,
        readiness_receipt_sha,
    )

    history_start = dt.date(2015, 1, 1)
    history_end = dt.date(2026, 7, 10)
    signal_start = config.section("data")["start_date"]
    signal_end = config.section("data")["end_date"]
    assert type(signal_start) is dt.date and type(signal_end) is dt.date
    snapshot_manifest = SnapshotManifestV1(
        "m3-snapshot-manifest-v1",
        snapshot_id,
        config.config_version,
        config.snapshot_config_sha256,
        release_id,
        release_manifest_sha,
        "tushare",
        "CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1",
        history_start,
        history_end,
        signal_start,
        signal_end,
        1,
        1,
        history_start,
        history_end,
        _hex("8"),
        2,
        history_start,
        history_end,
        "parquet",
        "m3-snapshot-staging-v1",
        "qlib_yahoo_like_v1",
        _hex("9"),
        (
            SnapshotArtifactEntryV1(
                "calendar.parquet", _hex("0"), 1, 1, "calendar", None,
                history_start, history_end,
            ),
        ),
    )
    snapshot_id = snapshot_id_from_manifest(
        json.loads(_canonical(asdict(snapshot_manifest)))
    )
    snapshot_manifest = replace(snapshot_manifest, snapshot_id=snapshot_id)
    snapshot_output = _write(
        root / "fake/snapshot/manifest.json",
        _canonical(asdict(snapshot_manifest)),
    )
    snapshot_manifest_sha = _sha(snapshot_output)
    _, snapshot_receipt_sha = _publish(
        root,
        relative=f"receipts/snapshot/{request_key}.json",
        stage="snapshot",
        scope="SNAPSHOT",
        scope_key=request_key,
        output=snapshot_output,
    )
    request = SnapshotRequestRecordV1(
        "m3-snapshot-request-v1",
        request_key,
        snapshot_id,
        snapshot_manifest_sha,
        release_id,
        release_manifest_sha,
        config.snapshot_config_sha256,
        code_version,
        history_start,
        history_end,
        signal_start,
        signal_end,
    )
    snapshot = VerifiedSnapshotArtifact(
        root / "fake/snapshot",
        request,
        _hex("a"),
        snapshot_manifest,
        snapshot_manifest_sha,
        snapshot_receipt_sha,
        root / "fake/snapshot/calendar.parquet",
        (root / "fake/snapshot/data.parquet",),
    )

    logical_argv = (
        "<PYTHON>", "<DUMP_TOOL>", "dump_all", "--data_path",
        "<SNAPSHOT_STAGING>", "--qlib_dir", "<PROVIDER_TEMP>/provider",
        "--freq", "day", "--file_suffix", ".parquet",
        "--date_field_name", "date", "--symbol_field_name", "symbol",
        "--include_fields", "open,high,low,close,vwap,volume,factor",
        "--max_workers", "1",
    )
    provider_manifest = ProviderManifestV1(
        "m3-provider-manifest-v1",
        provider_key,
        snapshot_id,
        snapshot_manifest_sha,
        config.provider_config_sha256,
        "0.9.7",
        _hex("b"),
        1,
        "m3-qlib-dump-all-v1",
        runtime_sha,
        code_version,
        "day",
        ("open", "high", "low", "close", "vwap", "volume", "factor"),
        "<f4",
        snapshot_manifest.session_calendar_sha256,
        2,
        history_start,
        history_end,
        1,
        _hex("c"),
        _hex("d"),
        logical_argv,
        (ArtifactDigest("provider", "provider/calendars/day.txt", 1, _hex("e")),),
    )
    provider_output = _write(
        root / "fake/provider/provider_manifest.json",
        _canonical(asdict(provider_manifest)),
    )
    provider_manifest_sha = _sha(provider_output)
    _, provider_receipt_sha = _publish(
        root,
        relative=f"receipts/provider/{provider_key}.json",
        stage="provider",
        scope="PROVIDER",
        scope_key=provider_key,
        output=provider_output,
    )
    provider_root = root / "fake/provider"
    provider = VerifiedProviderArtifact(
        provider_root,
        provider_root / "provider",
        provider_manifest,
        provider_manifest_sha,
        provider_receipt_sha,
    )

    validation_summary = ProviderValidationSummaryV1(
        "m3-provider-validation-v1",
        validation_key,
        provider_key,
        provider_receipt_sha,
        provider_manifest_sha,
        snapshot_id,
        config.provider_validation_config_sha256,
        runtime_sha,
        "0.9.7",
        "provider_market_stratified_hash_first_last_v1",
        "m3-qlib-worker-v1",
        _hex("f"),
        _hex("1"),
        _hex("2"),
        _hex("3"),
        60,
        2,
        420,
        14,
        _hex("4"),
        434,
        provider_manifest.calendar_sha256,
        provider_manifest.instrument_ranges_sha256,
        0, 0, 0, 0, 0, 0, 0, 0,
        _hex("5"),
        _hex("6"),
        _hex("7"),
        True,
    )
    validation_output = _write(
        root / "fake/validation/provider_validation.json",
        _canonical(asdict(validation_summary)),
    )
    validation_summary_sha = _sha(validation_output)
    _, validation_receipt_sha = _publish(
        root,
        relative=f"receipts/provider-validation/{validation_key}.json",
        stage="provider-validation",
        scope="PROVIDER",
        scope_key=validation_key,
        output=validation_output,
    )
    provider_validation = VerifiedProviderValidationArtifact(
        root / "fake/validation",
        pl.DataFrame(),
        validation_summary,
        validation_summary_sha,
        validation_receipt_sha,
    )

    experiment_manifest = ExperimentIdentityManifestV1(
        "m3-experiment-identity-v1",
        experiment_key,
        snapshot_id,
        snapshot_manifest_sha,
        provider_key,
        provider_manifest_sha,
        provider_receipt_sha,
        config.scientific_config_sha256,
        dependency_sha,
        code_version,
    )
    experiment_output = _write(
        root / "fake/experiment/experiment_manifest.json",
        _canonical(asdict(experiment_manifest)),
    )
    experiment_manifest_sha = _sha(experiment_output)
    _, experiment_receipt_sha = _publish(
        root,
        relative=f"receipts/experiment-identity/{experiment_key}.json",
        stage="experiment-identity",
        scope="EXPERIMENT",
        scope_key=experiment_key,
        output=experiment_output,
    )
    experiment = VerifiedExperimentIdentity(
        root / "fake/experiment",
        experiment_manifest,
        experiment_manifest_sha,
        experiment_receipt_sha,
    )

    fold = PlannedFold(
        "fold_001",
        (dt.date(2018, 1, 2),),
        (dt.date(2018, 1, 3),),
        (dt.date(2018, 1, 4),),
        (dt.date(2018, 1, 5),),
        (dt.date(2018, 1, 8),),
        dt.date(2018, 1, 3),
        dt.date(2018, 1, 5),
        _hex("9"),
    )
    fold_body = asdict(fold)
    fold_body.pop("planned_fold_sha256")
    fold = replace(
        fold,
        planned_fold_sha256=hashlib.sha256(_canonical(fold_body)).hexdigest(),
    )
    folds_manifest = FoldPlanManifestV1(
        "m3-fold-plan-v1",
        experiment_key,
        experiment_manifest_sha,
        snapshot_id,
        snapshot_manifest_sha,
        snapshot_manifest.session_calendar_sha256,
        _hex("a"),
        config.scientific_config_sha256,
        signal_start,
        signal_end,
        10,
        (fold,),
    )
    folds_output = _write(
        root / "fake/folds/folds.json",
        _canonical(asdict(folds_manifest)),
    )
    folds_manifest_sha = _sha(folds_output)
    _, folds_receipt_sha = _publish(
        root,
        relative=f"receipts/folds/{experiment_key}.json",
        stage="folds",
        scope="EXPERIMENT",
        scope_key=experiment_key,
        output=folds_output,
    )
    folds = VerifiedFoldPlanArtifact(
        root / "fake/folds",
        folds_manifest,
        folds_manifest_sha,
        folds_receipt_sha,
    )

    comparisons: list[VerifiedComparisonIdentityV1] = []
    label_config = config.section("labels")
    validation_labels = config.section("validation")["labels"]
    assert isinstance(validation_labels, Mapping)
    for horizon, character in ((5, "c"), (10, "d")):
        label_manifest = LabelArtifactManifest(
            "m3-label-artifact-v1",
            experiment_key,
            experiment_manifest_sha,
            release_id,
            release_manifest_sha,
            snapshot_id,
            snapshot_manifest_sha,
            horizon,
            "510300.SH",
            str(label_config["label_version"]),
            code_version,
            _hex("e"), _hex("f"), snapshot_manifest.session_calendar_sha256,
            _hex("1"), _hex("2"), 1, _hex("3"), _hex("4"), 0,
            _hex("5"), 1, 1, 0,
        )
        label_path = _write(
            root / f"fake/labels/h{horizon}/label_manifest.json",
            _canonical(asdict(label_manifest)),
        )
        _, label_receipt_sha = _publish(
            root,
            relative=f"receipts/labels/{experiment_key}-h{horizon}.json",
            stage="labels",
            scope="EXPERIMENT",
            scope_key=experiment_key,
            output=label_path,
        )
        reconciliation_key = _hex(character)
        reconciliation = LabelReconciliationSummaryV1(
            "m3-label-reconciliation-v1",
            reconciliation_key,
            experiment_key,
            horizon,
            validation_receipt_sha,
            _sha(label_path),
            config.label_reconciliation_config_sha256,
            dependency_sha,
            code_version,
            "m3-qlib-worker-v1",
            "0.9.7",
            f"Ref($close,-{horizon})/Ref($open,-1)-1",
            _hex("6"),
            1,
            _hex("7"),
            0, 0, 0, 0,
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
            float(validation_labels["qlib_expression_atol"]),
            float(validation_labels["benchmark_return_atol"]),
            float(validation_labels["label_return_atol"]),
            True,
        )
        reconciliation_path = _write(
            root / f"fake/reconciliation/h{horizon}/reconciliation.json",
            _canonical(asdict(reconciliation)),
        )
        _publish(
            root,
            relative=(
                f"receipts/label-reconciliation/{reconciliation_key}.json"
            ),
            stage="label-reconciliation",
            scope="EXPERIMENT",
            scope_key=reconciliation_key,
            output=reconciliation_path,
        )
        comparisons.append(
            VerifiedComparisonIdentityV1(
                "fold_001",
                horizon,
                _hex("8" if horizon == 5 else "9"),
                _hex("1" if horizon == 5 else "2"),
                _hex("3"),
                _sha(label_path),
                label_receipt_sha,
                _hex("4"),
                reconciliation_key,
                _hex("5"),
                _hex("6"),
            )
        )

    runtime = VerifiedRuntimeIdentity(
        code_version,
        runtime_sha,
        dependency_sha,
        config.full_config_sha256,
        readiness_receipt_sha,
    )
    subject = VerifiedAcceptanceSubject(
        snapshot,
        provider,
        provider_validation,
        experiment,
        folds,
        readiness,
        runtime,
        tuple(comparisons),
    )
    plan = build_acceptance_evidence_plan(subject=subject, config=config)
    return _Bundle(subject, plan, config, roots, root)


def test_g9c_accepts_one_strict_fake_g0_g4_closure(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    results = audit_acceptance_upstream(
        subject=bundle.subject,
        plan=bundle.plan,
        config=bundle.config,
        artifact_roots=bundle.roots,
    )

    assert tuple(item.gate for item in results) == ("G0", "G1", "G2", "G3", "G4")
    assert all(item.status == "PASS" for item in results)
    assert all(item.evidence for item in results)


def test_g9c_keeps_independent_gates_after_one_receipt_drift(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    reconciliation = bundle.root / "fake/reconciliation/h5/reconciliation.json"
    reconciliation.write_bytes(reconciliation.read_bytes() + b"\n")

    results = audit_acceptance_upstream(
        subject=bundle.subject,
        plan=bundle.plan,
        config=bundle.config,
        artifact_roots=bundle.roots,
    )

    assert tuple(item.status for item in results) == (
        "PASS", "PASS", "PASS", "FAIL", "PASS"
    )
    assert {(issue.code, issue.subject) for issue in results[3].issues} == {
        ("UPSTREAM_INVALID", "node:label-reconciliation.h5")
    }


def test_g9c_reports_config_disabled_without_masking_other_gates(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, enabled=False)
    results = audit_acceptance_upstream(
        subject=bundle.subject,
        plan=bundle.plan,
        config=bundle.config,
        artifact_roots=bundle.roots,
    )

    assert results[0].status == "FAIL"
    assert tuple(issue.code for issue in results[0].issues) == ("CONFIG_DISABLED",)
    assert all(item.status == "PASS" for item in results[1:])


def test_g9c_rejects_provider_count_drift_as_g2_only(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    summary = replace(
        bundle.subject.provider_validation.summary,
        emitted_key_count=59,
        emitted_comparison_count=413,
        details_row_count=427,
    )
    validation = replace(bundle.subject.provider_validation, summary=summary)
    subject = replace(bundle.subject, provider_validation=validation)
    plan = build_acceptance_evidence_plan(subject=subject, config=bundle.config)

    results = audit_acceptance_upstream(
        subject=subject,
        plan=plan,
        config=bundle.config,
        artifact_roots=bundle.roots,
    )

    assert tuple(item.status for item in results) == (
        "PASS", "PASS", "FAIL", "PASS", "PASS"
    )
    assert tuple(issue.code for issue in results[2].issues) == (
        "PROVIDER_VALIDATION_FAILED",
    )


def test_g9c_rejects_reconstructed_subject_not_backed_by_receipt_bytes(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    manifest = replace(
        bundle.subject.provider.manifest,
        output_tree_sha256=_hex("0"),
    )
    provider = replace(bundle.subject.provider, manifest=manifest)
    subject = replace(bundle.subject, provider=provider)
    plan = build_acceptance_evidence_plan(subject=subject, config=bundle.config)

    results = audit_acceptance_upstream(
        subject=subject,
        plan=plan,
        config=bundle.config,
        artifact_roots=bundle.roots,
    )

    assert results[2].status == "FAIL"
    assert tuple(issue.code for issue in results[2].issues) == (
        "PROVIDER_IDENTITY_INVALID",
    )


def test_g9c_invalid_caller_is_stable_and_redacted(tmp_path: Path) -> None:
    with pytest.raises(M3AcceptanceUpstreamError) as caught:
        audit_acceptance_upstream(
            subject=object(),  # type: ignore[arg-type]
            plan=object(),  # type: ignore[arg-type]
            config=object(),  # type: ignore[arg-type]
            artifact_roots={"G8": tmp_path},
        )
    assert str(caught.value) == "M3_ACCEPTANCE_UPSTREAM_INVALID"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
