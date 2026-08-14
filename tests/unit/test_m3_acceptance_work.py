"""Focused G9D work-level acceptance orchestration tests."""

from __future__ import annotations

import importlib.util
import re
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import quant.research.m3.acceptance_work as work_module
from quant.backtest.a_share_plan import G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION
from quant.backtest.a_share_reporting import backtest_artifact_output_relative_paths
from quant.research.m3.acceptance import build_acceptance_evidence_plan
from quant.research.m3.acceptance_work import (
    M3AcceptanceWorkError,
    audit_acceptance_work,
)
from quant.research.m3.run_state import publish_stage_receipt

_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "_g9c_test_support", Path(__file__).with_name("test_m3_acceptance_upstream.py")
)
assert _SUPPORT_SPEC is not None and _SUPPORT_SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SUPPORT_SPEC)
sys.modules[_SUPPORT_SPEC.name] = _SUPPORT
_SUPPORT_SPEC.loader.exec_module(_SUPPORT)
_bundle = cast(Any, getattr(_SUPPORT, "_bundle"))
_sha = cast(Any, getattr(_SUPPORT, "_sha"))
_write = cast(Any, getattr(_SUPPORT, "_write"))


def _publish_work_receipts(bundle: Any) -> Any:
    outputs = {
        "features": ("feature_manifest.json",),
        "alignment": ("alignment_manifest.json",),
        "train": ("model.metadata.json",),
        "predictions": ("prediction_manifest.json",),
        "reproducibility": ("reproducibility.json",),
        "evaluation": ("evaluation_manifest.json", "metrics.json"),
        "summary": ("manifest.json", "metrics.json"),
        "targets": ("target_manifest.json",),
        "backtest-plan": ("manifest.json",),
        "backtest": backtest_artifact_output_relative_paths(),
    }
    receipt_hashes: dict[tuple[str, str], str] = {}
    for locator in bundle.plan.evidence:
        if locator.gate not in {"G5", "G6", "G7"}:
            continue
        paths = tuple(
            _write(
                bundle.root / "fake" / locator.gate / locator.node_id / name,
                f"{locator.node_id}:{name}".encode(),
            )
            for name in outputs[locator.expected_stage]
        )
        inputs: tuple[tuple[str, Path], ...] = ()
        if locator.expected_stage == "backtest":
            inputs = tuple(
                (
                    "G8",
                    _write(
                        bundle.root / "fake" / "backtest-inputs" / f"{locator.node_id}.{index}",
                        str(index).encode(),
                    ),
                )
                for index in range(21)
            )
        receipt_path = bundle.root.joinpath(
            *locator.receipt_relative_path.split("/")
        )
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        publish_stage_receipt(
            receipt_path=receipt_path,
            stage=locator.expected_stage,
            scope=locator.expected_scope,
            scope_key=locator.expected_scope_key,
            artifact_roots=bundle.roots,
            inputs=inputs,
            outputs=tuple(("G8", path) for path in paths),
        )
        receipt_hashes[(locator.gate, locator.node_id)] = _sha(receipt_path)

    comparisons = tuple(
        replace(
            item,
            feature_receipt_sha256=receipt_hashes[("G5", f"features.{item.fold}")],
            alignment_receipt_sha256=receipt_hashes[
                ("G5", f"alignment.{item.fold}.h{item.horizon}")
            ],
            reproducibility_receipt_sha256=receipt_hashes[
                ("G5", f"reproducibility.{item.fold}.h{item.horizon}")
            ],
        )
        for item in bundle.subject.comparisons
    )
    subject = replace(bundle.subject, comparisons=comparisons)
    return replace(
        bundle,
        subject=subject,
        plan=build_acceptance_evidence_plan(subject=subject, config=bundle.config),
    )


def _horizon(path: Path) -> int:
    matched = re.search(r"\.h(\d+)(?:/|\.|$)", path.as_posix())
    if matched is None:
        raise AssertionError(f"missing horizon in {path.name}")
    return int(matched.group(1))


def _fold(path: Path) -> str:
    matched = re.search(r"fold_\d+", path.as_posix())
    if matched is None:
        raise AssertionError(f"missing fold in {path.name}")
    return matched.group(0)


def _comparison(bundle: Any, path: Path) -> Any:
    fold = _fold(path)
    horizon = _horizon(path)
    return next(
        item
        for item in bundle.subject.comparisons
        if item.fold == fold and item.horizon == horizon
    )


def _install_readers(
    monkeypatch: pytest.MonkeyPatch,
    bundle: Any,
    *,
    evaluation_coverage: float | Mapping[tuple[str, int], float] = 1.0,
    rank_ic_mean: float = 0.01,
) -> None:
    experiment = bundle.subject.experiment
    snapshot = bundle.subject.snapshot
    provider = bundle.subject.provider
    folds = bundle.subject.folds
    config = bundle.config
    model_section = config.section("model")["lightgbm"]
    assert isinstance(model_section, Mapping)
    model_version = str(model_section["model_version"])

    def feature(path: Path) -> Any:
        return SimpleNamespace(
            experiment_key=experiment.manifest.experiment_key,
            fold=_fold(path),
            snapshot_id=snapshot.manifest.snapshot_id,
            provider_key=provider.manifest.provider_key,
            scientific_config_sha256=config.scientific_config_sha256,
        )

    def alignment(path: Path) -> Any:
        comparison = _comparison(bundle, path)
        return SimpleNamespace(
            experiment_key=experiment.manifest.experiment_key,
            work_key=comparison.work_key,
            fold=comparison.fold,
            horizon_sessions=comparison.horizon,
            feature_manifest_sha256=_sha(
                bundle.root
                / f"fake/G5/features.{comparison.fold}/feature_manifest.json"
            ),
            label_manifest_sha256=comparison.label_manifest_sha256,
        )

    def model(path: Path) -> Any:
        comparison = _comparison(bundle, path)
        base = bundle.root / "fake/G5"
        return SimpleNamespace(
            experiment_key=experiment.manifest.experiment_key,
            work_key=comparison.work_key,
            fold=comparison.fold,
            horizon_sessions=comparison.horizon,
            alignment_manifest_sha256=_sha(
                base / f"alignment.{comparison.fold}.h{comparison.horizon}/alignment_manifest.json"
            ),
            feature_manifest_sha256=_sha(
                base / f"features.{comparison.fold}/feature_manifest.json"
            ),
            label_manifest_sha256=comparison.label_manifest_sha256,
            model_sha256="a" * 64,
            selected_feature_schema_sha256="b" * 64,
        )

    def prediction(path: Path) -> Any:
        comparison = _comparison(bundle, path)
        base = bundle.root / "fake/G5"
        return SimpleNamespace(
            experiment_key=experiment.manifest.experiment_key,
            work_key=comparison.work_key,
            fold=comparison.fold,
            horizon_sessions=comparison.horizon,
            model_manifest_sha256=_sha(
                base / f"train.{comparison.fold}.h{comparison.horizon}/model.metadata.json"
            ),
            model_sha256="a" * 64,
            feature_manifest_sha256=_sha(
                base / f"features.{comparison.fold}/feature_manifest.json"
            ),
            selected_feature_schema_sha256="b" * 64,
            snapshot_id=snapshot.manifest.snapshot_id,
            n_eligible=10,
            n_scorable=10,
            n_predicted=10,
        )

    def evaluation_manifest(path: Path) -> Any:
        comparison = _comparison(bundle, path)
        base = bundle.root / "fake"
        metrics_path = path.parent / "metrics.json"
        return SimpleNamespace(
            experiment_key=experiment.manifest.experiment_key,
            work_key=comparison.work_key,
            fold=comparison.fold,
            horizon_sessions=comparison.horizon,
            prediction_manifest_sha256=_sha(
                base
                / "G5"
                / f"predictions.{comparison.fold}.h{comparison.horizon}"
                / "prediction_manifest.json"
            ),
            label_manifest_sha256=comparison.label_manifest_sha256,
            feature_manifest_sha256=_sha(
                base
                / "G5"
                / f"features.{comparison.fold}"
                / "feature_manifest.json"
            ),
            fold_plan_manifest_sha256=folds.manifest_sha256,
            scientific_config_sha256=config.scientific_config_sha256,
            metrics_sha256=_sha(metrics_path),
            model="lightgbm",
            model_version=model_version,
        )

    def evaluation_metrics(path: Path) -> Any:
        comparison = _comparison(bundle, path)
        coverage = (
            evaluation_coverage[(comparison.fold, comparison.horizon)]
            if isinstance(evaluation_coverage, Mapping)
            else evaluation_coverage
        )
        return SimpleNamespace(
            experiment_key=experiment.manifest.experiment_key,
            work_key=comparison.work_key,
            fold=comparison.fold,
            horizon_sessions=comparison.horizon,
            model="lightgbm",
            model_version=model_version,
            feature_coverage=1.0,
            prediction_coverage=1.0,
            label_coverage=1.0,
            evaluation_coverage=coverage,
            n_dates=10,
            n_computable_dates=10,
            rank_ic_mean=rank_ic_mean,
            rank_icir=-0.1,
        )

    def summary_manifest(path: Path) -> Any:
        horizon = _horizon(path)
        comparisons = tuple(
            sorted(
                (
                    item
                    for item in bundle.subject.comparisons
                    if item.horizon == horizon
                ),
                key=lambda item: item.fold,
            )
        )
        evaluation_paths = tuple(
            bundle.root
            / "fake/G6"
            / f"evaluation.{comparison.fold}.h{horizon}"
            / "evaluation_manifest.json"
            for comparison in comparisons
        )
        evaluation_receipts = tuple(
            bundle.root / f"receipts/evaluation/{comparison.work_key}.json"
            for comparison in comparisons
        )
        return SimpleNamespace(
            experiment_key=experiment.manifest.experiment_key,
            horizon_sessions=horizon,
            model="lightgbm",
            model_version=model_version,
            scientific_config_sha256=config.scientific_config_sha256,
            folds=tuple(item.fold for item in comparisons),
            evaluation_manifest_sha256s=tuple(
                _sha(item) for item in evaluation_paths
            ),
            evaluation_receipt_sha256s=tuple(
                _sha(item) for item in evaluation_receipts
            ),
            metrics_sha256=_sha(path.parent / "metrics.json"),
        )

    def summary_metrics(path: Path) -> Any:
        horizon = _horizon(path)
        return SimpleNamespace(
            experiment_key=experiment.manifest.experiment_key,
            horizon_sessions=horizon,
            folds=tuple(
                item.fold
                for item in bundle.subject.comparisons
                if item.horizon == horizon
            ),
        )

    def target(path: Path) -> Any:
        comparison = _comparison(bundle, path)
        prediction_path = (
            bundle.root
            / "fake/G5"
            / f"predictions.{comparison.fold}.h{comparison.horizon}"
            / "prediction_manifest.json"
        )
        return SimpleNamespace(
            experiment_key=experiment.manifest.experiment_key,
            experiment_manifest_sha256=experiment.manifest_sha256,
            work_key=comparison.work_key,
            g1_release_id=bundle.subject.readiness.report.g1_release_id,
            g1_release_manifest_sha256=bundle.subject.readiness.report.g1_release_manifest_sha256,
            scientific_config_sha256=config.scientific_config_sha256,
            prediction_manifest_sha256=_sha(prediction_path),
            feature_manifest_sha256=_sha(
                bundle.root
                / f"fake/G5/features.{comparison.fold}/feature_manifest.json"
            ),
            fold_plan_manifest_sha256=folds.manifest_sha256,
            snapshot_id=snapshot.manifest.snapshot_id,
            fold=comparison.fold,
            horizon_sessions=comparison.horizon,
        )

    def plan(path: Path) -> Any:
        comparison = _comparison(bundle, path)
        target_path = (
            bundle.root
            / "fake/G7"
            / f"targets.{comparison.fold}.h{comparison.horizon}"
            / "target_manifest.json"
        )
        target_receipt = bundle.root / f"receipts/targets/{comparison.work_key}.json"
        return SimpleNamespace(
            experiment_key=experiment.manifest.experiment_key,
            work_key=comparison.work_key,
            target_manifest_sha256=_sha(target_path),
            target_receipt_sha256=_sha(target_receipt),
            g1_release_id=bundle.subject.readiness.report.g1_release_id,
            g1_release_manifest_sha256=bundle.subject.readiness.report.g1_release_manifest_sha256,
            scientific_config_sha256=config.scientific_config_sha256,
            fold_plan_manifest_sha256=folds.manifest_sha256,
            fold=comparison.fold,
            horizon_sessions=comparison.horizon,
            order_quantity_rule_version=G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION,
        )

    def backtest_metrics(path: Path) -> Any:
        comparison = _comparison(bundle, path)
        scenarios = tuple(
            SimpleNamespace(
                scenario=name,
                test_net_excess_return=-0.02,
                test_turnover=0.3,
                test_max_drawdown=-0.1,
            )
            for name in ("0p5x", "1p0x", "2p0x")
        )
        return SimpleNamespace(
            experiment_key=experiment.manifest.experiment_key,
            work_key=comparison.work_key,
            scenarios=scenarios,
        )

    def backtest_bundle(path: Path) -> Any:
        comparison = _comparison(bundle, path)
        base = path.parent
        target_path = (
            bundle.root
            / "fake/G7"
            / f"targets.{comparison.fold}.h{comparison.horizon}"
            / "target_manifest.json"
        )
        plan_path = (
            bundle.root
            / "fake/G7"
            / f"backtest-plan.{comparison.fold}.h{comparison.horizon}"
            / "manifest.json"
        )
        return SimpleNamespace(
            experiment_key=experiment.manifest.experiment_key,
            experiment_manifest_sha256=experiment.manifest_sha256,
            work_key=comparison.work_key,
            scientific_config_sha256=config.scientific_config_sha256,
            target_manifest_sha256=_sha(target_path),
            backtest_plan_manifest_sha256=_sha(plan_path),
            g1_release_id=bundle.subject.readiness.report.g1_release_id,
            g1_release_manifest_sha256=(
                bundle.subject.readiness.report.g1_release_manifest_sha256
            ),
            order_quantity_rule_version=G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION,
            common_target_manifest_sha256=_sha(target_path),
            backtest_metrics_sha256=_sha(base / "backtest_metrics.json"),
            scenario_manifest_sha256s=tuple(
                (name, _sha(base / name / "manifest.json"))
                for name in ("0p5x", "1p0x", "2p0x")
            ),
            common_market_facts_sha256="c" * 64,
        )

    def backtest_scenario(path: Path) -> Any:
        comparison = _comparison(bundle, path)
        name = path.parent.name
        target_path = (
            bundle.root
            / "fake/G7"
            / f"targets.{comparison.fold}.h{comparison.horizon}"
            / "target_manifest.json"
        )
        plan_path = (
            bundle.root
            / "fake/G7"
            / f"backtest-plan.{comparison.fold}.h{comparison.horizon}"
            / "manifest.json"
        )
        return SimpleNamespace(
            scenario=name,
            experiment_key=experiment.manifest.experiment_key,
            work_key=comparison.work_key,
            scientific_config_sha256=config.scientific_config_sha256,
            target_manifest_sha256=_sha(target_path),
            backtest_plan_manifest_sha256=_sha(plan_path),
            g1_release_id=bundle.subject.readiness.report.g1_release_id,
            g1_release_manifest_sha256=(
                bundle.subject.readiness.report.g1_release_manifest_sha256
            ),
            fold=comparison.fold,
            horizon_sessions=comparison.horizon,
            order_quantity_rule_version=G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION,
            input_market_facts_sha256="c" * 64,
            metrics_sha256=_sha(path.parent / "metrics.json"),
        )

    monkeypatch.setattr(work_module, "read_feature_manifest", feature)
    monkeypatch.setattr(work_module, "read_alignment_manifest", alignment)
    monkeypatch.setattr(work_module, "read_model_manifest", model)
    monkeypatch.setattr(work_module, "read_prediction_manifest", prediction)
    monkeypatch.setattr(work_module, "read_evaluation_manifest", evaluation_manifest)
    monkeypatch.setattr(work_module, "read_evaluation_metrics", evaluation_metrics)
    monkeypatch.setattr(work_module, "read_research_summary_manifest", summary_manifest)
    monkeypatch.setattr(work_module, "read_research_summary_metrics", summary_metrics)
    monkeypatch.setattr(work_module, "read_target_manifest", target)
    monkeypatch.setattr(work_module, "read_backtest_plan_manifest", plan)
    monkeypatch.setattr(work_module, "read_backtest_bundle_manifest", backtest_bundle)
    monkeypatch.setattr(work_module, "read_backtest_metrics", backtest_metrics)
    monkeypatch.setattr(work_module, "read_backtest_scenario_manifest", backtest_scenario)
    monkeypatch.setattr(work_module, "_fresh_verify_backtest", lambda **kwargs: None)
    monkeypatch.setattr(
        work_module,
        "verify_formal_reproducibility_artifact",
        lambda **kwargs: SimpleNamespace(comparison_key=kwargs["comparison_key"]),
    )


def test_g9d_accepts_each_strict_planned_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _publish_work_receipts(_bundle(tmp_path))
    _install_readers(monkeypatch, bundle)

    results = audit_acceptance_work(
        subject=bundle.subject,
        plan=bundle.plan,
        config=bundle.config,
        artifact_roots=bundle.roots,
    )

    assert tuple(item.gate for item in results) == ("G5", "G6", "G7")
    assert not results[1].issues, results[1].issues
    assert tuple(item.status for item in results) == ("PASS", "PASS", "PASS"), results


def test_g9d_fails_g6_and_dependent_g7_for_one_coverage_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _publish_work_receipts(_bundle(tmp_path))
    _install_readers(monkeypatch, bundle, evaluation_coverage=0.5)

    results = audit_acceptance_work(
        subject=bundle.subject,
        plan=bundle.plan,
        config=bundle.config,
        artifact_roots=bundle.roots,
    )

    assert results[0].status == "PASS"
    assert results[1].status == "FAIL"
    assert results[2].status == "FAIL"
    assert {item.code for item in results[1].issues} == {
        "SUMMARY_INVALID",
        "WORK_INVALID",
    }
    assert {item.code for item in results[2].issues} == {"DEPENDENCY_INVALID"}


def test_g9d_rejects_one_post_receipt_backtest_leaf_drift_as_g7_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _publish_work_receipts(_bundle(tmp_path))
    _install_readers(monkeypatch, bundle)
    comparison = bundle.subject.comparisons[0]
    drifted = (
        bundle.root
        / "fake/G7"
        / f"backtest.{comparison.fold}.h{comparison.horizon}"
        / "1p0x/nav.parquet"
    )
    drifted.write_bytes(b"post-receipt-drift")

    results = audit_acceptance_work(
        subject=bundle.subject,
        plan=bundle.plan,
        config=bundle.config,
        artifact_roots=bundle.roots,
    )

    assert tuple(item.status for item in results) == ("PASS", "PASS", "FAIL")
    assert "UPSTREAM_INVALID" in {item.code for item in results[2].issues}


def test_g9d_rejects_self_consistent_bundle_when_fresh_replay_disagrees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _publish_work_receipts(_bundle(tmp_path))
    _install_readers(monkeypatch, bundle)

    def reject_fresh_bundle(**kwargs: object) -> None:
        raise ValueError("fresh replay drift")

    monkeypatch.setattr(work_module, "_fresh_verify_backtest", reject_fresh_bundle)
    results = audit_acceptance_work(
        subject=bundle.subject,
        plan=bundle.plan,
        config=bundle.config,
        artifact_roots=bundle.roots,
    )

    assert tuple(item.status for item in results) == ("PASS", "PASS", "FAIL")
    assert {item.code for item in results[2].issues} == {"WORK_INVALID"}


def test_g9d_invalid_caller_is_stable_and_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _publish_work_receipts(_bundle(tmp_path))
    _install_readers(monkeypatch, bundle)

    with pytest.raises(M3AcceptanceWorkError) as caught:
        audit_acceptance_work(
            subject=object(),  # type: ignore[arg-type]
            plan=bundle.plan,
            config=bundle.config,
            artifact_roots=bundle.roots,
        )

    assert str(caught.value) == "M3_ACCEPTANCE_WORK_INVALID"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
