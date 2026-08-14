"""G9G two-fold by two-horizon acceptance integration closure."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

import quant.research.m3.acceptance_stage as stage_module
import quant.research.m3.acceptance_tracking as tracking_module
import quant.research.m3.acceptance_work as work_module
import quant.research.m3.orchestration as orchestration_module
from quant.research.m3.acceptance import (
    M3AcceptanceAuditError,
    M3AcceptancePlanError,
    RemoteTrackingObservationV1,
    build_acceptance_evidence_plan,
    compute_acceptance_key,
    audit_m3_acceptance,
)
from quant.research.m3.acceptance_stage import run_formal_acceptance_stage
from quant.research.m3.acceptance_tracking import audit_acceptance_tracking
from quant.research.m3.contracts import (
    PlannedFold,
    VerifiedFoldPlanArtifact,
)
from quant.research.m3.quality_gate import M3QualityGateError, run_quality_gate
from quant.research.m3.tracking import verify_tracking_remote


def _support(name: str, relative: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "unit" / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_UPSTREAM = _support("_g9g_upstream_support", "test_m3_acceptance_upstream.py")
_WORK = _support("_g9g_work_support", "test_m3_acceptance_work.py")
_TRACKING = _support("_g9g_tracking_support", "test_m3_acceptance_tracking.py")
_QUALITY = _support("_g9g_quality_support", "test_m3_quality_gate.py")

_bundle = cast(Any, getattr(_UPSTREAM, "_bundle"))
_canonical = cast(Any, getattr(_UPSTREAM, "_canonical"))
_publish = cast(Any, getattr(_UPSTREAM, "_publish"))
_sha = cast(Any, getattr(_UPSTREAM, "_sha"))
_publish_work_receipts = cast(Any, getattr(_WORK, "_publish_work_receipts"))
_install_readers = cast(Any, getattr(_WORK, "_install_readers"))
_complete_bundle = cast(Any, getattr(_TRACKING, "_complete_bundle"))
_observation = cast(Any, getattr(_TRACKING, "_observation"))
_Remote = cast(Any, getattr(_TRACKING, "_Remote"))
_remote_run = cast(Any, getattr(_TRACKING, "_remote_run"))


def _identity(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _two_fold_bundle(tmp_path: Path) -> Any:
    base = _bundle(tmp_path)
    fold_1 = base.subject.folds.manifest.folds[0]
    fold_2 = PlannedFold(
        "fold_002",
        (dt.date(2019, 1, 2),),
        (dt.date(2019, 1, 3),),
        (dt.date(2019, 1, 4),),
        (dt.date(2019, 1, 7),),
        (dt.date(2019, 1, 8),),
        dt.date(2019, 1, 3),
        dt.date(2019, 1, 7),
        "0" * 64,
    )
    fold_body = asdict(fold_2)
    fold_body.pop("planned_fold_sha256")
    fold_2 = replace(
        fold_2,
        planned_fold_sha256=hashlib.sha256(_canonical(fold_body)).hexdigest(),
    )
    manifest = replace(
        base.subject.folds.manifest,
        folds=(fold_1, fold_2),
    )
    output = base.root / "fake/folds/folds.json"
    output.write_bytes(_canonical(asdict(manifest)))
    receipt_path = (
        base.root
        / "receipts/folds"
        / f"{base.subject.experiment.manifest.experiment_key}.json"
    )
    receipt_path.unlink()
    _, receipt_sha = _publish(
        base.root,
        relative=receipt_path.relative_to(base.root).as_posix(),
        stage="folds",
        scope="EXPERIMENT",
        scope_key=base.subject.experiment.manifest.experiment_key,
        output=output,
    )
    folds = VerifiedFoldPlanArtifact(
        output.parent,
        manifest,
        _sha(output),
        receipt_sha,
    )
    comparisons = list(base.subject.comparisons)
    for item in base.subject.comparisons:
        comparisons.append(
            replace(
                item,
                fold="fold_002",
                work_key=_identity(f"work:fold_002:h{item.horizon}"),
                comparison_key=_identity(
                    f"comparison:fold_002:h{item.horizon}"
                ),
                feature_receipt_sha256=_identity(
                    f"feature:fold_002:h{item.horizon}"
                ),
                alignment_receipt_sha256=_identity(
                    f"alignment:fold_002:h{item.horizon}"
                ),
                reproducibility_receipt_sha256=_identity(
                    f"repro:fold_002:h{item.horizon}"
                ),
            )
        )
    subject = replace(
        base.subject,
        folds=folds,
        comparisons=tuple(
            sorted(comparisons, key=lambda item: (item.fold, item.horizon))
        ),
    )
    return replace(
        base,
        subject=subject,
        plan=build_acceptance_evidence_plan(
            subject=subject,
            config=base.config,
        ),
    )


def _prepared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    low_coverage: tuple[str, int] | None = None,
    rank_ic_mean: float = 0.01,
) -> tuple[Any, Any]:
    bundle = _publish_work_receipts(_two_fold_bundle(tmp_path))
    bundle, quality = _complete_bundle(tmp_path, bundle=bundle)
    coverage: float | dict[tuple[str, int], float] = 1.0
    if low_coverage is not None:
        coverage = {
            (item.fold, item.horizon): (
                0.5
                if (item.fold, item.horizon) == low_coverage
                else 1.0
            )
            for item in bundle.subject.comparisons
        }
    _install_readers(
        monkeypatch,
        bundle,
        evaluation_coverage=coverage,
        rank_ic_mean=rank_ic_mean,
    )
    monkeypatch.setattr(
        tracking_module,
        "_project_config",
        lambda *args, **kwargs: (tmp_path, Path("m3.toml")),
    )
    monkeypatch.setattr(
        tracking_module,
        "verify_quality_artifact",
        lambda **kwargs: quality,
    )
    return bundle, quality


def _audit(bundle: Any, quality: Any, verifier: Any = _observation) -> Any:
    return audit_m3_acceptance(
        subject=bundle.subject,
        plan=bundle.plan,
        quality=quality,
        config=bundle.config,
        artifact_roots=bundle.roots,
        tracking_verifier=verifier,
    )


def _install_stage_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        stage_module,
        "create_mlflow_tracking_client",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        stage_module,
        "verify_tracking_remote",
        lambda **kwargs: _observation(
            marker=kwargs["marker"],
            request=kwargs["request"],
        ),
    )


def test_two_fold_two_horizon_closes_g0_g9_and_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, quality = _prepared(tmp_path, monkeypatch)
    unrelated = bundle.root / "old-experiment/password.txt"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("TOKEN must not be scanned", encoding="utf-8")

    decision = _audit(bundle, quality)
    tracking = audit_acceptance_tracking(
        subject=bundle.subject,
        plan=bundle.plan,
        quality=quality,
        config=bundle.config,
        artifact_roots=bundle.roots,
        tracking_verifier=_observation,
    )

    assert len(bundle.subject.comparisons) == 4
    assert len(bundle.plan.expected_work_keys) == 4
    assert len(bundle.plan.expected_comparison_keys) == 4
    assert len(
        tuple(
            item
            for item in bundle.plan.evidence
            if item.gate == "G6" and item.node_id.startswith("summary.")
        )
    ) == 2
    assert all(
        item.expected_stage == "research-summary"
        and item.receipt_relative_path.startswith("receipts/research-summary/")
        for item in bundle.plan.evidence
        if item.gate == "G6" and item.node_id.startswith("summary.")
    )
    assert len(
        tuple(item for item in bundle.plan.evidence if item.gate == "G8")
    ) == 4
    assert len(tracking.observations) == 4
    assert tuple(item.gate for item in decision.gate_results) == tuple(
        f"G{index}" for index in range(10)
    )
    assert all(item.status == "PASS" for item in decision.gate_results)

    _install_stage_remote(monkeypatch)
    first = run_formal_acceptance_stage(
        subject=bundle.subject,
        plan=bundle.plan,
        quality=quality,
        config=bundle.config,
        artifact_roots=bundle.roots,
    )
    second = run_formal_acceptance_stage(
        subject=bundle.subject,
        plan=bundle.plan,
        quality=quality,
        config=bundle.config,
        artifact_roots=bundle.roots,
    )
    assert first.reused is False
    assert second.reused is True
    assert first.decision == second.decision == decision
    raw = (first.final_root / "acceptance_report.json").read_text(
        encoding="utf-8"
    )
    assert tuple(path.name for path in first.final_root.iterdir()) == (
        "acceptance_report.json",
    )
    assert str(tmp_path) not in raw
    assert all(
        token not in raw.lower()
        for token in ("password", "token", "created_at", "timestamp", "uri")
    )


def test_scientific_signs_do_not_replace_per_work_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    low_root = tmp_path / "low"
    low_root.mkdir()
    low, low_quality = _prepared(
        low_root,
        monkeypatch,
        low_coverage=("fold_002", 5),
    )
    failed = _audit(low, low_quality)
    assert failed.gate_results[5].status == "PASS"
    assert failed.gate_results[6].status == "FAIL"
    assert failed.gate_results[7].status == "FAIL"

    negative_root = tmp_path / "negative"
    negative_root.mkdir()
    negative, negative_quality = _prepared(
        negative_root,
        monkeypatch,
        rank_ic_mean=-0.25,
    )
    passed = _audit(negative, negative_quality)
    assert passed.overall_status == "PASS"
    assert all(item.status == "PASS" for item in passed.gate_results)


@pytest.mark.parametrize(
    "mode",
    [
        "copied_experiment",
        "wrong_model_horizon",
        "wrong_target_release",
        "one_scenario_target",
        "scaled_stamp_tax",
    ],
)
def test_cross_work_and_scenario_identity_drift_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    bundle, quality = _prepared(tmp_path, monkeypatch)
    if mode in {"copied_experiment", "wrong_model_horizon"}:
        original_model_reader = work_module.read_model_manifest

        def reader(path: Path) -> Any:
            value = original_model_reader(path)
            if "fold_002.h10" in path.as_posix():
                return SimpleNamespace(
                    **{
                        **vars(value),
                        (
                            "experiment_key"
                            if mode == "copied_experiment"
                            else "horizon_sessions"
                        ): (
                            "0" * 64
                            if mode == "copied_experiment"
                            else 5
                        ),
                    }
                )
            return value

        monkeypatch.setattr(work_module, "read_model_manifest", reader)
    elif mode == "wrong_target_release":
        original_target_reader = work_module.read_target_manifest

        def reader(path: Path) -> Any:
            value = original_target_reader(path)
            if "fold_002.h10" in path.as_posix():
                return SimpleNamespace(
                    **{**vars(value), "g1_release_id": "0" * 64}
                )
            return value

        monkeypatch.setattr(work_module, "read_target_manifest", reader)
    elif mode == "one_scenario_target":
        original_scenario_reader = work_module.read_backtest_scenario_manifest

        def reader(path: Path) -> Any:
            value = original_scenario_reader(path)
            if (
                "fold_002.h10" in path.as_posix()
                and path.parent.name == "1p0x"
            ):
                return SimpleNamespace(
                    **{
                        **vars(value),
                        "target_manifest_sha256": "0" * 64,
                    }
                )
            return value

        monkeypatch.setattr(
            work_module,
            "read_backtest_scenario_manifest",
            reader,
        )
    else:
        def reject_scaled_stamp_tax(**kwargs: Any) -> None:
            comparison = kwargs["comparison"]
            if comparison.fold == "fold_002" and comparison.horizon == 10:
                raise ValueError("stamp tax was incorrectly scaled")

        monkeypatch.setattr(
            work_module,
            "_fresh_verify_backtest",
            reject_scaled_stamp_tax,
        )

    decision = _audit(bundle, quality)
    assert decision.overall_status == "FAIL"
    assert any(
        item.status == "FAIL" for item in decision.gate_results[5:8]
    )


def test_reused_comparison_identity_is_not_a_plan(
    tmp_path: Path,
) -> None:
    bundle = _two_fold_bundle(tmp_path)
    comparisons = list(bundle.subject.comparisons)
    comparisons[1] = replace(
        comparisons[1],
        comparison_key=comparisons[0].comparison_key,
    )
    subject = replace(bundle.subject, comparisons=tuple(comparisons))
    with pytest.raises(M3AcceptancePlanError):
        build_acceptance_evidence_plan(subject=subject, config=bundle.config)


def test_green_quality_with_missing_candidate_writes_no_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, quality = _prepared(tmp_path, monkeypatch)
    assert quality.report.passed is True
    comparison = bundle.subject.comparisons[-1]
    target = (
        bundle.root
        / "fake/G7"
        / f"targets.{comparison.fold}.h{comparison.horizon}"
        / "target_manifest.json"
    )
    target.unlink()
    _install_stage_remote(monkeypatch)

    with pytest.raises(ValueError) as caught:
        run_formal_acceptance_stage(
            subject=bundle.subject,
            plan=bundle.plan,
            quality=quality,
            config=bundle.config,
            artifact_roots=bundle.roots,
        )
    assert str(caught.value) == "M3_ACCEPTANCE_STAGE_INVALID"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert not (bundle.root / "acceptance/final").exists()


@pytest.mark.parametrize(
    "mode",
    ["duplicate", "unknown", "nan", "wrong_scope", "wrong_key", "missing_output"],
)
def test_receipt_contract_tamper_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    bundle, quality = _prepared(tmp_path, monkeypatch)
    locator = next(
        item
        for item in bundle.plan.evidence
        if item.node_id == "features.fold_001"
    )
    path = bundle.root.joinpath(*locator.receipt_relative_path.split("/"))
    raw = path.read_text(encoding="utf-8")
    if mode == "duplicate":
        raw = raw.replace(
            '"receipt_version":',
            '"receipt_version":"m3-stage-receipt-v1","receipt_version":',
            1,
        )
    else:
        value = json.loads(raw)
        if mode == "unknown":
            value["unknown"] = "field"
        elif mode == "nan":
            value["outputs"][0]["size_bytes"] = float("nan")
        elif mode == "wrong_scope":
            value["scope"] = "WORK"
        elif mode == "wrong_key":
            value["scope_key"] = "0" * 64
        else:
            value["outputs"] = []
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=True,
        )
    path.write_text(raw, encoding="utf-8")

    try:
        decision = _audit(bundle, quality)
    except M3AcceptanceAuditError:
        pass
    else:
        assert decision.overall_status == "FAIL"
    assert not (bundle.root / "acceptance/final").exists()


@pytest.mark.parametrize("kind", ["hardlink", "symlink"])
def test_linked_receipt_output_is_not_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    bundle, quality = _prepared(tmp_path, monkeypatch)
    comparison = bundle.subject.comparisons[0]
    base = (
        bundle.root
        / "fake/G7"
        / f"backtest.{comparison.fold}.h{comparison.horizon}"
    )
    source = base / "0p5x/nav.parquet"
    target = base / "1p0x/nav.parquet"
    target.unlink()
    try:
        if kind == "hardlink":
            os.link(source, target)
        else:
            target.symlink_to(source)
    except OSError as error:
        pytest.skip(f"platform does not permit {kind}: {error.winerror}")

    with pytest.raises(M3AcceptanceAuditError):
        _audit(bundle, quality)


@pytest.mark.parametrize(
    "mode",
    ["zero", "duplicate", "unfinished", "hash", "target", "network"],
)
def test_tracking_failure_matrix_creates_no_acceptance_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    bundle, quality = _prepared(tmp_path, monkeypatch)
    calls = 0
    remotes: list[Any] = []

    def verifier(*, marker: Any, request: Any) -> RemoteTrackingObservationV1:
        nonlocal calls
        calls += 1
        if mode in {"zero", "duplicate", "unfinished"}:
            run = _remote_run(
                request,
                marker,
                status="RUNNING" if mode == "unfinished" else "FINISHED",
            )
            runs = () if mode == "zero" else ((run, run) if mode == "duplicate" else (run,))
            remote = _Remote(runs)
            remotes.append(remote)
            return verify_tracking_remote(
                marker=marker,
                request=request,
                experiment_name="m3-test",
                client=remote,
            )
        if mode == "network":
            raise RuntimeError(f"remote-{mode}")
        value = _observation(marker=marker, request=request)
        if mode == "hash":
            return replace(value, request_sha256="0" * 64)
        return replace(value, tracking_target_key="0" * 64)

    decision = _audit(bundle, quality, verifier)
    assert calls >= 1
    assert decision.overall_status == "FAIL"
    assert decision.gate_results[8].status == "FAIL"
    assert all(remote.mutations == 0 for remote in remotes)
    assert not (bundle.root / "acceptance/final").exists()


def test_acceptance_key_binds_all_late_evidence_and_core_import_is_light(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, quality = _prepared(tmp_path, monkeypatch)
    decision = _audit(bundle, quality)
    receipts = tuple(
        _sha(bundle.root.joinpath(*item.receipt_relative_path.split("/")))
        for item in bundle.plan.evidence
    )
    base = {
        "experiment_key": decision.experiment_key,
        "acceptance_config_sha256": decision.acceptance_config_sha256,
        "tracking_target_key": decision.tracking_target_key,
        "quality_receipt_sha256": quality.receipt_sha256,
        "tracking_observations_sha256": (
            decision.tracking_observations_sha256
        ),
        "required_receipt_sha256s": receipts,
    }
    keys = {
        compute_acceptance_key(**base),
        compute_acceptance_key(
            **{**base, "acceptance_config_sha256": "1" * 64}
        ),
        compute_acceptance_key(
            **{**base, "quality_receipt_sha256": "2" * 64}
        ),
        compute_acceptance_key(
            **{**base, "tracking_observations_sha256": "3" * 64}
        ),
        compute_acceptance_key(
            **{
                **base,
                "required_receipt_sha256s": (
                    "4" * 64,
                    *receipts[1:],
                ),
            }
        ),
    }
    assert len(keys) == 5

    project = Path(__file__).resolve().parents[2]
    script = (
        "import sys;"
        f"sys.path.insert(0,{str(project / 'src')!r});"
        "import quant.research.m3.acceptance;"
        "forbidden={'qlib','lightgbm','mlflow'};"
        "assert not forbidden.intersection(sys.modules);"
        "print('G9G_COLD_IMPORT_PASS')"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "G9G_COLD_IMPORT_PASS"


def test_quality_code_dependency_drift_and_acceptance_conflict_are_no_clobber(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quality_root = tmp_path / "quality"
    quality_root.mkdir()
    project, config = getattr(_QUALITY, "_project")(quality_root)
    executor = getattr(_QUALITY, "_Executor")(drift=True)
    with pytest.raises(M3QualityGateError):
        run_quality_gate(
            project_root=project,
            config=config,
            config_relative=getattr(_QUALITY, "_CONFIG"),
            executor=executor,
        )
    assert not tuple(
        (project / "artifacts/research/m3").rglob("quality_report.json")
    )

    dependency_root = tmp_path / "dependency-quality"
    dependency_root.mkdir()
    dependency_project, dependency_config = getattr(_QUALITY, "_project")(
        dependency_root
    )
    base_executor = getattr(_QUALITY, "_Executor")

    class _DependencyDriftExecutor(base_executor):  # type: ignore[misc, valid-type]
        def run(self, **kwargs: Any) -> Any:
            execution = super().run(**kwargs)
            if len(self.calls) == 4:
                pyproject = kwargs["cwd"] / "pyproject.toml"
                pyproject.write_bytes(pyproject.read_bytes() + b"\n# drift\n")
            return execution

    with pytest.raises(M3QualityGateError):
        run_quality_gate(
            project_root=dependency_project,
            config=dependency_config,
            config_relative=getattr(_QUALITY, "_CONFIG"),
            executor=_DependencyDriftExecutor(),
        )
    assert not tuple(
        (dependency_project / "artifacts/research/m3").rglob(
            "quality_report.json"
        )
    )

    acceptance_root = tmp_path / "acceptance"
    acceptance_root.mkdir()
    bundle, quality = _prepared(acceptance_root, monkeypatch)
    _install_stage_remote(monkeypatch)
    first = run_formal_acceptance_stage(
        subject=bundle.subject,
        plan=bundle.plan,
        quality=quality,
        config=bundle.config,
        artifact_roots=bundle.roots,
    )
    report = first.final_root / "acceptance_report.json"
    report.write_bytes(b"conflict")
    with pytest.raises(ValueError) as caught:
        run_formal_acceptance_stage(
            subject=bundle.subject,
            plan=bundle.plan,
            quality=quality,
            config=bundle.config,
            artifact_roots=bundle.roots,
        )
    assert str(caught.value) == "M3_ACCEPTANCE_STAGE_INVALID"
    assert report.read_bytes() == b"conflict"


def test_acceptance_publish_recovers_exact_concurrent_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, quality = _prepared(tmp_path, monkeypatch)
    _install_stage_remote(monkeypatch)
    calls = 0

    def concurrent_exact(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        shutil.copytree(source, target)
        raise OSError("simulated exact concurrent publish")

    monkeypatch.setattr(
        orchestration_module,
        "commit_directory_noreplace",
        concurrent_exact,
    )
    result = run_formal_acceptance_stage(
        subject=bundle.subject,
        plan=bundle.plan,
        quality=quality,
        config=bundle.config,
        artifact_roots=bundle.roots,
    )
    assert calls == 1
    assert result.reused is False
    assert tuple(path.name for path in result.final_root.iterdir()) == (
        "acceptance_report.json",
    )
