"""Formal summary StageRunner publication compatibility unit tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pickle
import shutil
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import asdict, replace
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any, Literal, cast

import pytest

import quant.research.m3.evaluate as evaluate_module
import quant.research.m3.orchestration as orchestration_module
import quant.research.m3.provider as provider_module
import quant.research.m3.provider_validation as provider_validation_module
import quant.research.m3.summary_stage as summary_stage
from quant.data.m3_release import platform_supports_renameat2_noreplace
from quant.research.m3.contracts import (
    ExperimentIdentitySpec,
    ResearchSummaryUpstreamPaths,
    VerifiedEvaluationArtifact,
    VerifiedExperimentIdentity,
)
from quant.research.m3.evaluate import (
    EvaluationFreshVerificationContext,
    FormalSummaryStagePublicationIdentity,
    build_research_summary_stage_artifact,
    verify_research_summary_stage_artifact,
    verify_research_summary_stage_precommit,
    verify_research_summary_stage_publication,
)
from quant.research.m3.experiment_identity import (
    build_experiment_identity_manifest,
    make_experiment_identity_handler,
    make_experiment_identity_run_plan,
    verify_experiment_identity_output,
)
from quant.research.m3.labels import verify_experiment_identity
from quant.research.m3.orchestration import (
    SUMMARY_STAGE_SPEC,
    ExternalInput,
    M3StageRunnerError,
    StageRunner,
    StaticDirectoryPublication,
    make_summary_run_plan,
    select_run_plan_nodes,
)
from quant.research.m3.run_state import compute_work_key
from quant.research.m3.summary_stage import (
    FormalSummaryStageResult,
    run_formal_summary_stage,
)
from quant.research.m3.successor_runtime import GateExecution

_SUMMARY_SPEC = importlib.util.spec_from_file_location(
    "m3_formal_summary_support_for_stage",
    Path(__file__).with_name("test_m3_formal_research_summary_artifact.py"),
)
assert _SUMMARY_SPEC is not None and _SUMMARY_SPEC.loader is not None
_SUMMARY = importlib.util.module_from_spec(_SUMMARY_SPEC)
_SUMMARY_SPEC.loader.exec_module(_SUMMARY)

_EXP_SPEC = importlib.util.spec_from_file_location(
    "m3_formal_experiment_identity_support_for_summary_stage",
    Path(__file__).with_name("test_m3_experiment_identity.py"),
)
assert _EXP_SPEC is not None and _EXP_SPEC.loader is not None
_EXP = importlib.util.module_from_spec(_EXP_SPEC)
_EXP_SPEC.loader.exec_module(_EXP)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity_for(
    *,
    stage_root: Path,
    experiment_key: str,
    model: str,
    model_version: str,
    horizon: int = 5,
) -> FormalSummaryStagePublicationIdentity:
    return FormalSummaryStagePublicationIdentity(
        stage_root=stage_root,
        node_id=f"summary.h{horizon}.{model}.{model_version}",
        final_relative_path=PurePosixPath(
            f"summaries/{experiment_key}/h{horizon}/{model}/{model_version}"
        ),
        experiment_key=experiment_key,
        horizon_sessions=cast(Any, horizon),
        model=model,
        model_version=model_version,
    )


def _assert_shared_subprocess_run(expected: Any) -> None:
    """Lock subprocess/provider/provider_validation on one shared callable."""
    assert subprocess.run is expected
    assert provider_module.subprocess.run is expected
    assert provider_validation_module.subprocess.run is expected


def _restore_shared_subprocess_run(
    monkeypatch: pytest.MonkeyPatch, original: Any,
) -> None:
    """Restore the exact pre-entry shared worker callable (not an invented stand-in)."""
    monkeypatch.setattr(subprocess, "run", original)
    _assert_shared_subprocess_run(original)


def _publish_formal_experiment_identity(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    upstream_stage_root: Path,
) -> tuple[VerifiedExperimentIdentity, Path, Any, ExperimentIdentitySpec, Mapping[str, Path]]:
    """Publish real formal experiment via public StageRunner API only.

    Authority split (§20): outer monkeypatch may retain deterministic
    ``build_provider_runtime_fingerprint`` and StageRunner
    ``commit_directory_noreplace`` test substitutes. Shared ``subprocess.run``
    worker fakes must be restored to the exact pre-entry callable before legacy
    summary support and before post-publish typed fresh verify.
    """
    support = tmp_path / "exp-identity-support"
    support.mkdir()
    original_subprocess_run = subprocess.run
    original_runtime_fingerprint = provider_module.build_provider_runtime_fingerprint
    original_commit = orchestration_module.commit_directory_noreplace
    _assert_shared_subprocess_run(original_subprocess_run)

    primary_error: BaseException | None = None

    try:
        (
            _common,
            _ignored_stage,
            support_roots,
            snapshot,
            provider,
            validation,
            config,
            spec,
        ) = _EXP._fixture(support, monkeypatch)
        # Worker fake active; runtime identity + commit substitutes retained on outer.
        assert subprocess.run is not original_subprocess_run
        _assert_shared_subprocess_run(subprocess.run)
        assert (
            provider_module.build_provider_runtime_fingerprint
            is not original_runtime_fingerprint
        )
        assert (
            orchestration_module.commit_directory_noreplace is not original_commit
        )

        publish_roots = {
            "root": support_roots["root"],
            "EXTERNAL_QLIB": support_roots["EXTERNAL_QLIB"],
            "stage": upstream_stage_root,
        }
        plan = make_experiment_identity_run_plan(
            snapshot=snapshot,
            provider=provider,
            provider_validation=validation,
            config=config,
            spec=spec,
            artifact_roots=publish_roots,
        )
        node = plan.nodes[0]
        expected = build_experiment_identity_manifest(
            snapshot=snapshot, provider=provider, config=config, spec=spec
        )
        runner = StageRunner(
            stage_root=upstream_stage_root,
            artifact_roots=publish_roots,
            config=config,
        )

        def output_verifier(root: Path) -> Any:
            return verify_experiment_identity_output(root=root, expected=expected)

        def final_verifier(root: Path, receipt: Path) -> VerifiedExperimentIdentity:
            return verify_experiment_identity(
                experiment_root=root,
                experiment_receipt_path=receipt,
                snapshot=snapshot,
                provider=provider,
                config=config,
                spec=spec,
                artifact_roots=publish_roots,
            )

        published = runner.run_experiment_identity(
            node=node,
            handler=make_experiment_identity_handler(
                snapshot=snapshot, provider=provider, spec=spec
            ),
            output_verifier=output_verifier,
            final_verifier=final_verifier,
        )
        experiment = published.verified
        receipt_path = published.receipt_path.resolve(strict=True)
        assert type(experiment) is VerifiedExperimentIdentity
        assert experiment.root == (
            upstream_stage_root / "runs" / expected.experiment_key
        ).resolve(strict=True)
        assert receipt_path == (
            upstream_stage_root
            / "receipts"
            / "experiment-identity"
            / f"{expected.experiment_key}.json"
        ).resolve(strict=True)
        payload = json.loads(receipt_path.read_bytes().decode("utf-8"))
        assert payload["stage"] == "experiment-identity"
        assert payload["scope"] == "EXPERIMENT"
        assert payload["scope_key"] == expected.experiment_key
        assert published.receipt.stage == "experiment-identity"
        assert published.receipt.scope == "EXPERIMENT"
        assert published.receipt.scope_key == expected.experiment_key
        assert experiment.experiment_receipt_sha256 == _sha(receipt_path)
        assert experiment.manifest_sha256 == _sha(
            experiment.root / "experiment_manifest.json"
        )
        assert (experiment.root / "experiment_manifest.json").is_file()

        # Worker authority restore immediately after publication; identity/commit remain.
        _restore_shared_subprocess_run(monkeypatch, original_subprocess_run)
        assert (
            provider_module.build_provider_runtime_fingerprint
            is not original_runtime_fingerprint
        )
        assert (
            orchestration_module.commit_directory_noreplace is not original_commit
        )

        # Fresh typed verify with worker restored + identity/commit substitutes kept.
        fresh = verify_experiment_identity(
            experiment_root=experiment.root,
            experiment_receipt_path=receipt_path,
            snapshot=snapshot,
            provider=provider,
            config=config,
            spec=spec,
            artifact_roots=publish_roots,
        )
        assert type(fresh) is VerifiedExperimentIdentity
        assert fresh.root == experiment.root
        assert fresh.manifest == experiment.manifest
        assert fresh.manifest_sha256 == experiment.manifest_sha256
        assert fresh.experiment_receipt_sha256 == experiment.experiment_receipt_sha256
        assert experiment.manifest_sha256 == _sha(
            experiment.root / "experiment_manifest.json"
        )
        assert experiment.experiment_receipt_sha256 == _sha(receipt_path)
        return experiment, receipt_path, config, spec, publish_roots
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        try:
            if subprocess.run is not original_subprocess_run:
                _restore_shared_subprocess_run(monkeypatch, original_subprocess_run)
        except BaseException:
            if primary_error is not None:
                pass
            else:
                raise


def _bind_context_to_formal_experiment(
    context: EvaluationFreshVerificationContext,
    *,
    experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec,
    experiment_receipt: Path,
) -> EvaluationFreshVerificationContext:
    fold_up = (
        context.evaluation_upstream_paths.prediction_upstream_paths
        .feature_upstream_paths.fold_upstream_paths
    )
    new_fold_up = replace(
        fold_up, experiment_receipt_path=experiment_receipt
    )
    new_feature_up = replace(
        context.evaluation_upstream_paths.prediction_upstream_paths
        .feature_upstream_paths,
        fold_upstream_paths=new_fold_up,
    )
    new_prediction_up = replace(
        context.evaluation_upstream_paths.prediction_upstream_paths,
        feature_upstream_paths=new_feature_up,
    )
    new_eval_up = replace(
        context.evaluation_upstream_paths,
        prediction_upstream_paths=new_prediction_up,
    )
    return replace(
        context,
        experiment=experiment,
        experiment_spec=experiment_spec,
        evaluation_upstream_paths=new_eval_up,
    )


def _materialize_canonical_evaluation(
    *,
    source: VerifiedEvaluationArtifact,
    source_context: EvaluationFreshVerificationContext,
    upstream_stage_root: Path,
    experiment_key: str,
    scientific_config_sha256: str,
    horizon_sessions: Literal[5, 10],
) -> tuple[VerifiedEvaluationArtifact, EvaluationFreshVerificationContext, Path]:
    """Place one fold/horizon evaluation on public work publication paths."""
    work_key = compute_work_key(
        experiment_key=experiment_key,
        fold=source.manifest.fold,
        horizon=horizon_sessions,
    )
    root = upstream_stage_root / "work" / work_key / "evaluation"
    root.mkdir(parents=True)
    shutil.copy2(source.root / "daily_ic.parquet", root / "daily_ic.parquet")

    metrics = replace(
        source.metrics,
        experiment_key=experiment_key,
        work_key=work_key,
        horizon_sessions=horizon_sessions,
    )
    metrics_raw = evaluate_module._canonical_bytes(asdict(metrics))
    (root / "metrics.json").write_bytes(metrics_raw)
    metrics_sha = hashlib.sha256(metrics_raw).hexdigest()

    manifest = replace(
        source.manifest,
        experiment_key=experiment_key,
        work_key=work_key,
        horizon_sessions=horizon_sessions,
        scientific_config_sha256=scientific_config_sha256,
        metrics_sha256=metrics_sha,
    )
    manifest_raw = evaluate_module._canonical_bytes(asdict(manifest))
    (root / "evaluation_manifest.json").write_bytes(manifest_raw)
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()

    receipt = (
        upstream_stage_root / "receipts" / "evaluation" / f"{work_key}.json"
    )
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_bytes(
        f"canonical-evaluation-receipt:{work_key}".encode()
    )
    receipt_sha = _sha(receipt)

    evaluation = VerifiedEvaluationArtifact(
        root=root.resolve(strict=True),
        daily=source.daily,
        metrics=metrics,
        manifest=manifest,
        manifest_sha256=manifest_sha,
        evaluation_receipt_sha256=receipt_sha,
    )
    evaluation_spec = replace(
        source_context.evaluation_spec,
        experiment_key=experiment_key,
        work_key=work_key,
        horizon_sessions=horizon_sessions,
    )
    context_updates: dict[str, Any] = {"evaluation_spec": evaluation_spec}
    if horizon_sessions != source_context.evaluation_spec.horizon_sessions:
        context_updates["label_spec"] = replace(
            source_context.label_spec, horizon_sessions=horizon_sessions
        )
        context_updates["prediction_spec"] = replace(
            source_context.prediction_spec, horizon_sessions=horizon_sessions
        )
    fresh = replace(source_context, **context_updates)
    return evaluation, fresh, receipt


def _stage_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    project = tmp_path
    stage_root = project / "stage"
    stage_root.mkdir()
    (stage_root / ".stage-tmp").mkdir()
    upstream_stage_root = project / "upstream-eval-stage"
    upstream_stage_root.mkdir()

    # Capture shared worker BEFORE formal publish; legacy feature fixture must
    # later capture this exact callable (not a leaked provider-validation fake).
    legacy_feature_subprocess_run = subprocess.run
    _assert_shared_subprocess_run(legacy_feature_subprocess_run)
    original_runtime_fingerprint = provider_module.build_provider_runtime_fingerprint
    original_commit = orchestration_module.commit_directory_noreplace

    (
        experiment,
        experiment_receipt,
        config,
        experiment_spec,
        _publish_roots,
    ) = _publish_formal_experiment_identity(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        upstream_stage_root=upstream_stage_root,
    )
    # Worker restored; runtime identity + StageRunner commit substitutes may remain.
    _assert_shared_subprocess_run(legacy_feature_subprocess_run)
    assert (
        provider_module.build_provider_runtime_fingerprint
        is not original_runtime_fingerprint
    )
    assert orchestration_module.commit_directory_noreplace is not original_commit

    experiment_key = experiment.manifest.experiment_key
    scientific_config_sha256 = experiment.manifest.scientific_config_sha256
    assert scientific_config_sha256 == config.scientific_config_sha256
    assert scientific_config_sha256 == experiment_spec.scientific_config_sha256
    assert set(config.section("labels")["horizons_sessions"]) == {5, 10}

    eval_support = tmp_path / "summary-eval-support"
    eval_support.mkdir()
    template = _SUMMARY._context(eval_support, monkeypatch)
    # Legacy feature `_build_feature_bundle` captures/restores subprocess.run;
    # after that path, the shared callable must still be the pre-publish original.
    _assert_shared_subprocess_run(legacy_feature_subprocess_run)
    model = template["evaluations"][0].manifest.model
    model_version = template["evaluations"][0].manifest.model_version
    legacy_experiment_receipt = template["upstream"].experiment_receipt_path
    assert "development-experiment-identity" in (
        legacy_experiment_receipt.as_posix()
    )

    h5: list[VerifiedEvaluationArtifact] = []
    h5_contexts: list[EvaluationFreshVerificationContext] = []
    h5_receipts: list[Path] = []
    for item, ctx in zip(
        template["evaluations"], template["contexts"], strict=True
    ):
        evaluation, fresh, receipt = _materialize_canonical_evaluation(
            source=item,
            source_context=ctx,
            upstream_stage_root=upstream_stage_root,
            experiment_key=experiment_key,
            scientific_config_sha256=scientific_config_sha256,
            horizon_sessions=5,
        )
        fresh = _bind_context_to_formal_experiment(
            fresh,
            experiment=experiment,
            experiment_spec=experiment_spec,
            experiment_receipt=experiment_receipt,
        )
        h5.append(evaluation)
        h5_contexts.append(fresh)
        h5_receipts.append(receipt)

    h10: list[VerifiedEvaluationArtifact] = []
    h10_contexts: list[EvaluationFreshVerificationContext] = []
    h10_receipts: list[Path] = []
    for item, ctx in zip(h5, h5_contexts, strict=True):
        evaluation, fresh, receipt = _materialize_canonical_evaluation(
            source=item,
            source_context=ctx,
            upstream_stage_root=upstream_stage_root,
            experiment_key=experiment_key,
            scientific_config_sha256=scientific_config_sha256,
            horizon_sessions=10,
        )
        fresh = _bind_context_to_formal_experiment(
            fresh,
            experiment=experiment,
            experiment_spec=experiment_spec,
            experiment_receipt=experiment_receipt,
        )
        h10.append(evaluation)
        h10_contexts.append(fresh)
        h10_receipts.append(receipt)

    evaluations = tuple(h5) + tuple(h10)
    contexts = tuple(h5_contexts) + tuple(h10_contexts)
    upstream = ResearchSummaryUpstreamPaths(
        experiment_receipt_path=experiment_receipt,
        evaluation_receipt_paths=tuple(h5_receipts) + tuple(h10_receipts),
    )
    h5_upstream = ResearchSummaryUpstreamPaths(
        experiment_receipt_path=experiment_receipt,
        evaluation_receipt_paths=tuple(h5_receipts),
    )

    roots = [item.root for item in evaluations]
    receipt_paths = list(upstream.evaluation_receipt_paths)
    assert len(set(roots)) == len(roots)
    assert len(set(receipt_paths)) == len(receipt_paths)
    for item, ctx, receipt in zip(
        evaluations, contexts, receipt_paths, strict=True
    ):
        expected_key = compute_work_key(
            experiment_key=experiment_key,
            fold=item.manifest.fold,
            horizon=item.manifest.horizon_sessions,
        )
        assert item.manifest.work_key == expected_key
        assert item.metrics.work_key == expected_key
        assert item.manifest.experiment_key == experiment_key
        assert item.metrics.experiment_key == experiment_key
        assert (
            item.manifest.scientific_config_sha256
            == scientific_config_sha256
        )
        assert ctx.evaluation_spec.work_key == expected_key
        assert ctx.evaluation_spec.experiment_key == experiment_key
        assert ctx.experiment is experiment
        assert ctx.experiment_spec is experiment_spec
        assert (
            ctx.experiment_spec.scientific_config_sha256
            == scientific_config_sha256
        )
        nested_receipt = (
            ctx.evaluation_upstream_paths.prediction_upstream_paths
            .feature_upstream_paths.fold_upstream_paths.experiment_receipt_path
        )
        assert nested_receipt == experiment_receipt
        assert nested_receipt.resolve(strict=True) == (
            experiment_receipt.resolve(strict=True)
        )
        assert "development-experiment-identity" not in nested_receipt.as_posix()
        assert nested_receipt != legacy_experiment_receipt
        assert item.manifest.horizon_sessions == item.metrics.horizon_sessions
        assert (
            item.manifest.horizon_sessions
            == ctx.evaluation_spec.horizon_sessions
        )
        assert item.root == (
            upstream_stage_root / "work" / expected_key / "evaluation"
        ).resolve(strict=True)
        assert receipt == (
            upstream_stage_root
            / "receipts"
            / "evaluation"
            / f"{expected_key}.json"
        )
        assert item.evaluation_receipt_sha256 == _sha(receipt)
        assert item.manifest_sha256 == _sha(
            item.root / "evaluation_manifest.json"
        )
        assert (item.root / "metrics.json").read_bytes() == (
            evaluate_module._canonical_bytes(asdict(item.metrics))
        )
        assert (item.root / "evaluation_manifest.json").read_bytes() == (
            evaluate_module._canonical_bytes(asdict(item.manifest))
        )

    assert "development-experiment-identity" not in (
        experiment_receipt.as_posix()
    )
    assert upstream.experiment_receipt_path == experiment_receipt
    assert h5_upstream.experiment_receipt_path == experiment_receipt
    assert upstream.experiment_receipt_path != legacy_experiment_receipt
    plan = make_summary_run_plan(
        config=config,
        experiment=experiment,
        evaluations=evaluations,
        artifact_roots={"PROJECT": project},
    )
    assert plan.continuation == "SUMMARY"
    assert {node.node_id for node in plan.nodes} == {
        f"summary.h5.{model}.{model_version}",
        f"summary.h10.{model}.{model_version}",
    }
    plan_receipt_paths = {
        item.artifact.relative_path
        for node in plan.nodes
        for item in node.inputs
        if isinstance(item, ExternalInput)
    }
    assert any(
        path.endswith(f"receipts/experiment-identity/{experiment_key}.json")
        for path in plan_receipt_paths
    )
    assert not any(
        "development-experiment-identity" in path for path in plan_receipt_paths
    )

    by_root = {item.root: item for item in evaluations}
    monkeypatch.setattr(
        evaluate_module,
        "verify_evaluation_artifact",
        lambda **call: by_root[call["root"]],
    )
    return {
        "context": template,
        "project": project,
        "stage_root": stage_root,
        "upstream_stage_root": upstream_stage_root,
        "artifact_roots": {"PROJECT": project},
        "evaluations": evaluations,
        "contexts": contexts,
        "upstream": upstream,
        "experiment": experiment,
        "config": config,
        "model": model,
        "model_version": model_version,
        "h5": h5,
        "h5_contexts": h5_contexts,
        "h5_upstream": h5_upstream,
        "summary_plan": plan,
        "experiment_receipt": experiment_receipt,
        "experiment_spec": experiment_spec,
    }


def test_publication_identity_rejects_path_and_model_drift(
    tmp_path: Path,
) -> None:
    stage_root = tmp_path / "stage"
    stage_root.mkdir()
    with pytest.raises(ValueError):
        FormalSummaryStagePublicationIdentity(
            stage_root=stage_root,
            node_id="summary.h5.lightgbm.v1",
            final_relative_path=PurePosixPath("summaries/x/h5/lightgbm/v1"),
            experiment_key="a" * 64,
            horizon_sessions=5,
            model="lightgbm",
            model_version="v1",
        )
    with pytest.raises(ValueError):
        FormalSummaryStagePublicationIdentity(
            stage_root=cast(Any, str(stage_root)),
            node_id="summary.h5.lightgbm.v1",
            final_relative_path=PurePosixPath(
                f"summaries/{'a' * 64}/h5/lightgbm/v1"
            ),
            experiment_key="a" * 64,
            horizon_sessions=5,
            model="lightgbm",
            model_version="v1",
        )


def test_stage_build_rejects_arbitrary_temp_ancestry_prefix_and_nonempty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _stage_bundle(tmp_path, monkeypatch)
    identity = _identity_for(
        stage_root=bundle["stage_root"],
        experiment_key=bundle["experiment"].manifest.experiment_key,
        model=bundle["model"],
        model_version=bundle["model_version"],
    )
    kwargs = {
        "identity": identity,
        "evaluations": bundle["h5"],
        "evaluation_contexts": bundle["h5_contexts"],
        "experiment": bundle["experiment"],
        "config": bundle["config"],
        "upstream_paths": bundle["h5_upstream"],
        "artifact_roots": bundle["artifact_roots"],
    }
    arbitrary = tmp_path / "arbitrary"
    arbitrary.mkdir()
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        build_research_summary_stage_artifact(**kwargs, output_root=arbitrary)

    nested = bundle["stage_root"] / ".stage-tmp" / "nested" / f".{identity.node_id}.x"
    nested.parent.mkdir(parents=True)
    nested.mkdir()
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        build_research_summary_stage_artifact(**kwargs, output_root=nested)

    wrong_prefix = bundle["stage_root"] / ".stage-tmp" / ".summary.other.x"
    wrong_prefix.mkdir()
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        build_research_summary_stage_artifact(**kwargs, output_root=wrong_prefix)

    nonempty = (
        bundle["stage_root"] / ".stage-tmp" / f".{identity.node_id}.nonempty"
    )
    nonempty.mkdir()
    (nonempty / "extra.txt").write_bytes(b"x")
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        build_research_summary_stage_artifact(**kwargs, output_root=nonempty)


def test_temp_leaf_exact_ownership_rejects_longer_sibling_and_bad_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _stage_bundle(tmp_path, monkeypatch)
    model_version = bundle["model_version"]
    identity = _identity_for(
        stage_root=bundle["stage_root"],
        experiment_key=bundle["experiment"].manifest.experiment_key,
        model=bundle["model"],
        model_version=model_version,
    )
    assert identity.node_id == (
        f"summary.h5.{bundle['model']}.{model_version}"
    )
    assert identity.node_id.endswith(f".{model_version}")
    kwargs = {
        "identity": identity,
        "evaluations": bundle["h5"],
        "evaluation_contexts": bundle["h5_contexts"],
        "experiment": bundle["experiment"],
        "config": bundle["config"],
        "upstream_paths": bundle["h5_upstream"],
        "artifact_roots": bundle["artifact_roots"],
    }
    sibling = (
        bundle["stage_root"] / ".stage-tmp" / f".{identity.node_id}.2.abc12xyz"
    )
    sibling.mkdir()
    # startswith would accept this longer sibling; exact suffix ownership must not.
    assert sibling.name.startswith(f".{identity.node_id}.")
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        build_research_summary_stage_artifact(**kwargs, output_root=sibling)
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        verify_research_summary_stage_precommit(
            **kwargs, root=sibling,
        )

    bad_chars = (
        bundle["stage_root"] / ".stage-tmp" / f".{identity.node_id}.ABC-DEF"
    )
    bad_chars.mkdir()
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        build_research_summary_stage_artifact(**kwargs, output_root=bad_chars)

    with pytest.raises(ValueError, match="formal summary stage temp root invalid"):
        evaluate_module._require_stage_temp_leaf_name(
            node_id=identity.node_id,
            leaf_name=f".{identity.node_id}.",
        )
    with pytest.raises(ValueError, match="formal summary stage temp root invalid"):
        evaluate_module._require_stage_temp_leaf_name(
            node_id=identity.node_id,
            leaf_name=f".{identity.node_id}.nested/extra",
        )

    legal = bundle["stage_root"] / ".stage-tmp" / f".{identity.node_id}.tmp0abcd"
    legal.mkdir()
    build_research_summary_stage_artifact(**kwargs, output_root=legal)


def _try_dir_symlink(target: Path, link: Path) -> bool:
    try:
        os.symlink(target, link, target_is_directory=True)
        return link.exists() or link.is_symlink()
    except OSError:
        if os.name != "nt":
            return False
        completed = __import__("subprocess").run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        return completed.returncode == 0 and link.exists()


def _mark_reparse(
    monkeypatch: pytest.MonkeyPatch, module: Any, marked: Path,
) -> None:
    real_lstat = module.os.lstat
    marked_key = os.path.normcase(os.path.abspath(str(marked)))

    def hostile_lstat(path: object, *args: Any, **kwargs: Any) -> Any:
        status = real_lstat(path, *args, **kwargs)
        try:
            key = os.path.normcase(os.path.abspath(str(path)))
        except OSError:
            return status
        if key == marked_key:
            values = {
                name: getattr(status, name)
                for name in dir(status)
                if name.startswith("st_")
            }
            values["st_file_attributes"] = getattr(
                status, "st_file_attributes", 0
            ) | 0x400
            return SimpleNamespace(**values)
        return status

    monkeypatch.setattr(module.os, "lstat", hostile_lstat)


def test_temp_final_symlink_and_reparse_injection_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _stage_bundle(tmp_path, monkeypatch)
    identity = _identity_for(
        stage_root=bundle["stage_root"],
        experiment_key=bundle["experiment"].manifest.experiment_key,
        model=bundle["model"],
        model_version=bundle["model_version"],
    )
    kwargs = {
        "identity": identity,
        "evaluations": bundle["h5"],
        "evaluation_contexts": bundle["h5_contexts"],
        "experiment": bundle["experiment"],
        "config": bundle["config"],
        "upstream_paths": bundle["h5_upstream"],
        "artifact_roots": bundle["artifact_roots"],
    }
    real_temp = bundle["stage_root"] / ".stage-tmp" / f".{identity.node_id}.reallf"
    real_temp.mkdir()
    build_research_summary_stage_artifact(**kwargs, output_root=real_temp)
    verify_research_summary_stage_precommit(**kwargs, root=real_temp)

    # Attribute-injection reparse must always exist even if host cannot symlink.
    with monkeypatch.context() as marked:
        _mark_reparse(marked, evaluate_module, real_temp)
        with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
            build_research_summary_stage_artifact(**kwargs, output_root=real_temp)
        with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
            verify_research_summary_stage_precommit(**kwargs, root=real_temp)

    final_root = bundle["stage_root"].joinpath(*identity.final_relative_path.parts)
    final_root.parent.mkdir(parents=True, exist_ok=True)
    if final_root.exists():
        shutil.rmtree(final_root)
    final_root.mkdir(parents=True)
    for name in evaluate_module._SUMMARY_FILES:
        shutil.copy2(real_temp / name, final_root / name)
    with monkeypatch.context() as marked:
        _mark_reparse(marked, evaluate_module, final_root)
        with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
            verify_research_summary_stage_publication(**kwargs, root=final_root)
        with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
            verify_research_summary_stage_artifact(
                **kwargs,
                root=final_root,
                receipt_path=bundle["stage_root"] / "receipts" / "missing.json",
            )
    with monkeypatch.context() as marked:
        _mark_reparse(marked, summary_stage, final_root)
        dispatcher = summary_stage._make_summary_stage_closure_dispatcher(**kwargs)
        with pytest.raises(ValueError):
            dispatcher(final_root)
    with monkeypatch.context() as marked:
        _mark_reparse(marked, summary_stage, real_temp)
        dispatcher = summary_stage._make_summary_stage_closure_dispatcher(**kwargs)
        with pytest.raises(ValueError):
            dispatcher(real_temp)

    # Host symlink/junction when permitted; otherwise injection above already covers.
    link_target = tmp_path / "link-target-dir"
    link_target.mkdir()
    for name in evaluate_module._SUMMARY_FILES:
        shutil.copy2(real_temp / name, link_target / name)
    temp_link = bundle["stage_root"] / ".stage-tmp" / f".{identity.node_id}.symtmp"
    if _try_dir_symlink(link_target, temp_link):
        with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
            build_research_summary_stage_artifact(**kwargs, output_root=temp_link)
        with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
            verify_research_summary_stage_precommit(**kwargs, root=temp_link)
        with pytest.raises(ValueError):
            summary_stage._make_summary_stage_closure_dispatcher(**kwargs)(temp_link)

    if final_root.exists():
        shutil.rmtree(final_root)
    final_link_parent = final_root.parent
    final_link_parent.mkdir(parents=True, exist_ok=True)
    if _try_dir_symlink(link_target, final_root):
        with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
            verify_research_summary_stage_publication(**kwargs, root=final_root)
        with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
            verify_research_summary_stage_artifact(
                **kwargs,
                root=final_root,
                receipt_path=bundle["stage_root"] / "receipts" / "missing.json",
            )
        with pytest.raises(ValueError):
            summary_stage._make_summary_stage_closure_dispatcher(**kwargs)(final_root)


def test_dispatcher_r3_final_junction_and_lexical_alias_reject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reviewer R3: final leaf junction/symlink + lexical alias must not resolve-bypass."""
    bundle = _stage_bundle(tmp_path, monkeypatch)
    identity = _identity_for(
        stage_root=bundle["stage_root"],
        experiment_key=bundle["experiment"].manifest.experiment_key,
        model=bundle["model"],
        model_version=bundle["model_version"],
    )
    kwargs = {
        "identity": identity,
        "evaluations": bundle["h5"],
        "evaluation_contexts": bundle["h5_contexts"],
        "experiment": bundle["experiment"],
        "config": bundle["config"],
        "upstream_paths": bundle["h5_upstream"],
        "artifact_roots": bundle["artifact_roots"],
    }
    real_temp = bundle["stage_root"] / ".stage-tmp" / f".{identity.node_id}.r3seed"
    real_temp.mkdir()
    build_research_summary_stage_artifact(**kwargs, output_root=real_temp)

    independent = tmp_path / "independent-summary-target"
    independent.mkdir()
    for name in evaluate_module._SUMMARY_FILES:
        shutil.copy2(real_temp / name, independent / name)

    final_root = bundle["stage_root"].joinpath(*identity.final_relative_path.parts)
    final_root.parent.mkdir(parents=True, exist_ok=True)

    # Always-on lexical alias: same bytes, wrong lexical path → never publication success.
    wrong_lexical = bundle["stage_root"] / "wrong-lexical-final"
    wrong_lexical.mkdir()
    for name in evaluate_module._SUMMARY_FILES:
        shutil.copy2(real_temp / name, wrong_lexical / name)
    assert os.path.normcase(str(Path(os.path.abspath(wrong_lexical)))) != os.path.normcase(
        str(Path(os.path.abspath(final_root)))
    )
    phase_calls: list[tuple[str, Path]] = []
    real_pub = summary_stage.verify_research_summary_stage_publication
    real_pre = summary_stage.verify_research_summary_stage_precommit

    def tracking_pub(**values: Any) -> Any:
        phase_calls.append(("publication", values["root"]))
        return real_pub(**values)

    def tracking_pre(**values: Any) -> Any:
        phase_calls.append(("pre", values["root"]))
        return real_pre(**values)

    with monkeypatch.context() as marked:
        marked.setattr(
            summary_stage, "verify_research_summary_stage_publication", tracking_pub
        )
        marked.setattr(
            summary_stage, "verify_research_summary_stage_precommit", tracking_pre
        )
        with pytest.raises(ValueError):
            summary_stage._make_summary_stage_closure_dispatcher(**kwargs)(
                wrong_lexical
            )
        assert [name for name, _ in phase_calls] == ["pre"]
        assert all(
            os.path.normcase(str(root))
            == os.path.normcase(str(Path(os.path.abspath(wrong_lexical))))
            for name, root in phase_calls
        )

    # `..` lexical collapse to a non-existent final leaf must fail closed (no resolve fill-in).
    dotted = final_root.parent.joinpath("_missing_child_", "..", final_root.name)
    dotted_abs = Path(os.path.abspath(dotted))
    with pytest.raises(ValueError):
        summary_stage._make_summary_stage_closure_dispatcher(**kwargs)(dotted_abs)

    # Host-supported: shadow symlink whose resolve target has summary bytes but leaf ≠ final.
    shadow = bundle["stage_root"] / "shadow-not-final"
    if _try_dir_symlink(independent, shadow):
        phase_calls.clear()
        with monkeypatch.context() as marked:
            marked.setattr(
                summary_stage,
                "verify_research_summary_stage_publication",
                tracking_pub,
            )
            marked.setattr(
                summary_stage,
                "verify_research_summary_stage_precommit",
                tracking_pre,
            )
            with pytest.raises(ValueError):
                summary_stage._make_summary_stage_closure_dispatcher(**kwargs)(shadow)
            # Reject at non-follow lstat — no phase success / no final reinterpretation.
            assert phase_calls == []

    # Host-supported R3 core: exact final lexical leaf is junction/symlink → independent target.
    if final_root.exists() or final_root.is_symlink():
        try:
            final_root.unlink(missing_ok=True)
        except OSError:
            shutil.rmtree(final_root, ignore_errors=True)
    if not _try_dir_symlink(independent, final_root):
        return

    leaf_info = os.lstat(final_root)
    assert bool(
        stat.S_ISLNK(leaf_info.st_mode)
        or (
            getattr(leaf_info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
    )
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        verify_research_summary_stage_publication(**kwargs, root=final_root)

    phase_calls.clear()
    successes: list[str] = []

    def pub_ok(**values: Any) -> Any:
        phase_calls.append(("publication", values["root"]))
        result = real_pub(**values)
        successes.append("publication")
        return result

    def pre_ok(**values: Any) -> Any:
        phase_calls.append(("pre", values["root"]))
        result = real_pre(**values)
        successes.append("pre")
        return result

    with monkeypatch.context() as marked:
        marked.setattr(
            summary_stage, "verify_research_summary_stage_publication", pub_ok
        )
        marked.setattr(
            summary_stage, "verify_research_summary_stage_precommit", pre_ok
        )
        with pytest.raises(ValueError):
            summary_stage._make_summary_stage_closure_dispatcher(**kwargs)(final_root)
        assert successes == []
        # Either fail before phase, or phase receives the raw junction leaf and fails.
        assert all(
            os.path.normcase(str(root)) == os.path.normcase(str(final_root))
            for _name, root in phase_calls
        )


def test_precommit_rejects_extra_nested_and_wrong_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _stage_bundle(tmp_path, monkeypatch)
    identity = _identity_for(
        stage_root=bundle["stage_root"],
        experiment_key=bundle["experiment"].manifest.experiment_key,
        model=bundle["model"],
        model_version=bundle["model_version"],
    )
    temp_root = (
        bundle["stage_root"] / ".stage-tmp" / f".{identity.node_id}.ok"
    )
    temp_root.mkdir()
    build_research_summary_stage_artifact(
        identity=identity,
        evaluations=bundle["h5"],
        evaluation_contexts=bundle["h5_contexts"],
        experiment=bundle["experiment"],
        config=bundle["config"],
        upstream_paths=bundle["h5_upstream"],
        artifact_roots=bundle["artifact_roots"],
        output_root=temp_root,
    )
    (temp_root / "extra.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        verify_research_summary_stage_precommit(
            identity=identity,
            root=temp_root,
            evaluations=bundle["h5"],
            evaluation_contexts=bundle["h5_contexts"],
            experiment=bundle["experiment"],
            config=bundle["config"],
            upstream_paths=bundle["h5_upstream"],
            artifact_roots=bundle["artifact_roots"],
        )
    (temp_root / "extra.json").unlink()
    nested = temp_root / "subdir"
    nested.mkdir()
    (nested / "x.bin").write_bytes(b"1")
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        verify_research_summary_stage_precommit(
            identity=identity,
            root=temp_root,
            evaluations=bundle["h5"],
            evaluation_contexts=bundle["h5_contexts"],
            experiment=bundle["experiment"],
            config=bundle["config"],
            upstream_paths=bundle["h5_upstream"],
            artifact_roots=bundle["artifact_roots"],
        )
    shutil.rmtree(nested)
    wrong = _identity_for(
        stage_root=bundle["stage_root"],
        experiment_key=bundle["experiment"].manifest.experiment_key,
        model=bundle["model"],
        model_version="other",
    )
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        verify_research_summary_stage_precommit(
            identity=wrong,
            root=temp_root,
            evaluations=bundle["h5"],
            evaluation_contexts=bundle["h5_contexts"],
            experiment=bundle["experiment"],
            config=bundle["config"],
            upstream_paths=bundle["h5_upstream"],
            artifact_roots=bundle["artifact_roots"],
        )


def test_three_phase_verifiers_are_mutually_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _stage_bundle(tmp_path, monkeypatch)
    identity = _identity_for(
        stage_root=bundle["stage_root"],
        experiment_key=bundle["experiment"].manifest.experiment_key,
        model=bundle["model"],
        model_version=bundle["model_version"],
    )
    temp_root = bundle["stage_root"] / ".stage-tmp" / f".{identity.node_id}.phase"
    temp_root.mkdir()
    build_research_summary_stage_artifact(
        identity=identity,
        evaluations=bundle["h5"],
        evaluation_contexts=bundle["h5_contexts"],
        experiment=bundle["experiment"],
        config=bundle["config"],
        upstream_paths=bundle["h5_upstream"],
        artifact_roots=bundle["artifact_roots"],
        output_root=temp_root,
    )
    final_root = bundle["stage_root"].joinpath(*identity.final_relative_path.parts)
    final_root.mkdir(parents=True)
    for name in evaluate_module._SUMMARY_FILES:
        shutil.copy2(temp_root / name, final_root / name)

    # temp must not enter publication/artifact
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        verify_research_summary_stage_publication(
            identity=identity,
            root=temp_root,
            evaluations=bundle["h5"],
            evaluation_contexts=bundle["h5_contexts"],
            experiment=bundle["experiment"],
            config=bundle["config"],
            upstream_paths=bundle["h5_upstream"],
            artifact_roots=bundle["artifact_roots"],
        )
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        verify_research_summary_stage_artifact(
            identity=identity,
            root=temp_root,
            receipt_path=bundle["stage_root"] / "receipts" / "missing.json",
            evaluations=bundle["h5"],
            evaluation_contexts=bundle["h5_contexts"],
            experiment=bundle["experiment"],
            config=bundle["config"],
            upstream_paths=bundle["h5_upstream"],
            artifact_roots=bundle["artifact_roots"],
        )
    # final must not enter precommit
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        verify_research_summary_stage_precommit(
            identity=identity,
            root=final_root,
            evaluations=bundle["h5"],
            evaluation_contexts=bundle["h5_contexts"],
            experiment=bundle["experiment"],
            config=bundle["config"],
            upstream_paths=bundle["h5_upstream"],
            artifact_roots=bundle["artifact_roots"],
        )
    published = verify_research_summary_stage_publication(
        identity=identity,
        root=final_root,
        evaluations=bundle["h5"],
        evaluation_contexts=bundle["h5_contexts"],
        experiment=bundle["experiment"],
        config=bundle["config"],
        upstream_paths=bundle["h5_upstream"],
        artifact_roots=bundle["artifact_roots"],
    )
    assert published.summary_receipt_sha256 == "0" * 64


def test_dispatcher_routes_without_temp_final_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _stage_bundle(tmp_path, monkeypatch)
    identity = _identity_for(
        stage_root=bundle["stage_root"],
        experiment_key=bundle["experiment"].manifest.experiment_key,
        model=bundle["model"],
        model_version=bundle["model_version"],
    )
    temp_root = bundle["stage_root"] / ".stage-tmp" / f".{identity.node_id}.disp"
    temp_root.mkdir()
    build_research_summary_stage_artifact(
        identity=identity,
        evaluations=bundle["h5"],
        evaluation_contexts=bundle["h5_contexts"],
        experiment=bundle["experiment"],
        config=bundle["config"],
        upstream_paths=bundle["h5_upstream"],
        artifact_roots=bundle["artifact_roots"],
        output_root=temp_root,
    )
    calls: list[str] = []
    real_pre = summary_stage.verify_research_summary_stage_precommit
    real_pub = summary_stage.verify_research_summary_stage_publication

    def pre(**kwargs: Any) -> Any:
        calls.append("pre")
        return real_pre(**kwargs)

    def pub(**kwargs: Any) -> Any:
        calls.append("publication")
        return real_pub(**kwargs)

    monkeypatch.setattr(summary_stage, "verify_research_summary_stage_precommit", pre)
    monkeypatch.setattr(
        summary_stage, "verify_research_summary_stage_publication", pub
    )
    dispatcher = summary_stage._make_summary_stage_closure_dispatcher(
        identity=identity,
        evaluations=bundle["h5"],
        evaluation_contexts=bundle["h5_contexts"],
        experiment=bundle["experiment"],
        config=bundle["config"],
        upstream_paths=bundle["h5_upstream"],
        artifact_roots=bundle["artifact_roots"],
    )
    dispatcher(temp_root)
    assert calls == ["pre"]

    final_root = bundle["stage_root"].joinpath(*identity.final_relative_path.parts)
    final_root.mkdir(parents=True)
    for name in evaluate_module._SUMMARY_FILES:
        shutil.copy2(temp_root / name, final_root / name)
    calls.clear()
    dispatcher(final_root)
    assert calls == ["publication"]

    # tampered temp content must fail closed as precommit, never reinterpret as final
    (temp_root / "metrics.json").write_bytes(b'{"tampered":true}')
    calls.clear()
    with pytest.raises(ValueError):
        dispatcher(temp_root)
    assert calls == ["pre"]
    assert "publication" not in calls

    # canonical final tamper must fail as publication, never reinterpret as temp
    (final_root / "metrics.json").write_bytes(b'{"tampered":true}')
    calls.clear()
    with pytest.raises(ValueError):
        dispatcher(final_root)
    assert calls == ["publication"]
    assert "pre" not in calls

    # arbitrary root rejects without phase reinterpretation
    arbitrary = bundle["project"] / "arbitrary-root"
    arbitrary.mkdir()
    for name in evaluate_module._SUMMARY_FILES:
        shutil.copy2(temp_root / name, arbitrary / name)
    calls.clear()
    with pytest.raises(ValueError):
        dispatcher(arbitrary)
    assert calls == ["pre"]
    assert "publication" not in calls


def _unique_summary_plan_node(
    nodes: tuple[Any, ...] | list[Any],
    *,
    horizon: int | None = None,
    node_id: str | None = None,
) -> Any:
    """Locate one summary plan node by exact node_id or unique horizon."""
    if node_id is not None:
        matches = [item for item in nodes if item.node_id == node_id]
    elif horizon is not None:
        matches = [item for item in nodes if item.horizon == horizon]
    else:
        raise AssertionError("node_id or horizon required")
    assert len(matches) == 1, (node_id, horizon, [item.node_id for item in nodes])
    return matches[0]


def test_plan_selection_rejects_zero_partial_and_publication_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _stage_bundle(tmp_path, monkeypatch)
    plan = make_summary_run_plan(
        config=bundle["config"],
        experiment=bundle["experiment"],
        evaluations=bundle["evaluations"],
        artifact_roots=bundle["artifact_roots"],
    )
    assert plan.continuation == "SUMMARY"
    assert len(plan.nodes) == 2
    selected = select_run_plan_nodes(
        plan,
        expected_continuation="SUMMARY",
        expected_node_ids=tuple(item.node_id for item in plan.nodes),
    )
    assert len(selected) == 2
    # Lexicographic closure puts h10 before h5; never treat selected[0] as h5.
    assert selected[0].node_id.startswith("summary.h10.")
    assert selected[1].node_id.startswith("summary.h5.")

    h5_node = _unique_summary_plan_node(selected, horizon=5)
    h10_node = _unique_summary_plan_node(selected, horizon=10)
    assert h5_node is _unique_summary_plan_node(
        selected,
        node_id=(
            f"summary.h5.{bundle['model']}.{bundle['model_version']}"
        ),
    )
    assert h10_node is _unique_summary_plan_node(
        selected,
        node_id=(
            f"summary.h10.{bundle['model']}.{bundle['model_version']}"
        ),
    )
    assert h5_node.node_id != h10_node.node_id
    assert h5_node.horizon == 5
    assert h10_node.horizon == 10

    with pytest.raises(ValueError):
        select_run_plan_nodes(
            plan,
            expected_continuation="SUMMARY",
            expected_node_ids=(),
        )
    with pytest.raises(ValueError):
        select_run_plan_nodes(
            plan,
            expected_continuation="SUMMARY",
            expected_node_ids=(h5_node.node_id,),
        )

    experiment_key = bundle["experiment"].manifest.experiment_key
    model = bundle["model"]
    model_version = bundle["model_version"]

    def _plan_with(*, replacement: Any) -> Any:
        by_id = {item.node_id: item for item in selected}
        by_id[replacement.node_id] = replacement
        # Keep full plan node-id closure; order follows select_run_plan_nodes.
        return replace(
            plan,
            nodes=tuple(by_id[item.node_id] for item in selected),
        )

    # Non-target horizon drift must not masquerade as current-horizon failure.
    drifted_h10 = replace(
        h10_node,
        publication=StaticDirectoryPublication(
            f"summaries/{experiment_key}/h10/{model}/drifted"
        ),
    )
    plan_h10_drift = _plan_with(replacement=drifted_h10)
    identity_h5, selected_h5 = summary_stage._select_canonical_summary_node(
        plan=plan_h10_drift,
        evaluations=bundle["evaluations"],
        experiment=bundle["experiment"],
        horizon_sessions=5,
        stage_root=bundle["stage_root"],
    )
    assert selected_h5.node_id == h5_node.node_id
    assert identity_h5.node_id == h5_node.node_id
    with pytest.raises(ValueError):
        summary_stage._select_canonical_summary_node(
            plan=plan_h10_drift,
            evaluations=bundle["evaluations"],
            experiment=bundle["experiment"],
            horizon_sessions=10,
            stage_root=bundle["stage_root"],
        )

    # Target horizon model_version directory drift must stably reject.
    drifted_h5 = replace(
        h5_node,
        publication=StaticDirectoryPublication(
            f"summaries/{experiment_key}/h5/{model}/drifted"
        ),
    )
    plan_h5_drift = _plan_with(replacement=drifted_h5)
    with pytest.raises(ValueError):
        summary_stage._select_canonical_summary_node(
            plan=plan_h5_drift,
            evaluations=bundle["evaluations"],
            experiment=bundle["experiment"],
            horizon_sessions=5,
            stage_root=bundle["stage_root"],
        )
    # Undrifted h10 remains selectable under full closure.
    identity_h10, selected_h10 = summary_stage._select_canonical_summary_node(
        plan=plan_h5_drift,
        evaluations=bundle["evaluations"],
        experiment=bundle["experiment"],
        horizon_sessions=10,
        stage_root=bundle["stage_root"],
    )
    assert selected_h10.node_id == h10_node.node_id
    assert identity_h10.model_version == model_version


def test_run_rejects_non_project_roots_gate_execution_and_result_forge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _stage_bundle(tmp_path, monkeypatch)
    with pytest.raises(M3StageRunnerError) as caught:
        run_formal_summary_stage(
            stage_root=bundle["stage_root"],
            artifact_roots={"root": bundle["project"]},
            config=bundle["config"],
            evaluations=bundle["evaluations"],
            evaluation_contexts=bundle["contexts"],
            experiment=bundle["experiment"],
            horizon_sessions=5,
            upstream_paths=bundle["upstream"],
        )
    assert caught.value.code == "STAGE_INPUT_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None

    assert GateExecution is not None
    with pytest.raises(TypeError):
        run_formal_summary_stage(
            stage_root=bundle["stage_root"],
            artifact_roots=bundle["artifact_roots"],
            config=bundle["config"],
            evaluations=bundle["evaluations"],
            evaluation_contexts=bundle["contexts"],
            experiment=bundle["experiment"],
            horizon_sessions=5,
            upstream_paths=bundle["upstream"],
            gate_execution=object(),  # type: ignore[call-arg]
        )

    with pytest.raises(ValueError, match="M3_FORMAL_SUMMARY_STAGE_INVALID"):
        FormalSummaryStageResult(
            final_root=cast(Any, "root"),
            receipt_path=cast(Any, "receipt"),
            verified=cast(Any, object()),
            receipt=cast(Any, object()),
            reused=False,
        )
    assert "__reduce__" in FormalSummaryStageResult.__dict__
    source = Path(summary_stage.__file__).read_text(encoding="utf-8")
    assert "GateExecution" not in source


def test_evaluation_order_invariant_and_conflict_identity_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _stage_bundle(tmp_path, monkeypatch)
    identity = _identity_for(
        stage_root=bundle["stage_root"],
        experiment_key=bundle["experiment"].manifest.experiment_key,
        model=bundle["model"],
        model_version=bundle["model_version"],
    )
    first_root = bundle["stage_root"] / ".stage-tmp" / f".{identity.node_id}.a"
    second_root = bundle["stage_root"] / ".stage-tmp" / f".{identity.node_id}.b"
    first_root.mkdir()
    second_root.mkdir()
    ordered = bundle["h5"]
    reordered = (ordered[1], ordered[0], ordered[2])
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        build_research_summary_stage_artifact(
            identity=identity,
            evaluations=reordered,
            evaluation_contexts=bundle["h5_contexts"],
            experiment=bundle["experiment"],
            config=bundle["config"],
            upstream_paths=bundle["h5_upstream"],
            artifact_roots=bundle["artifact_roots"],
            output_root=first_root,
        )
    conflict = replace(
        ordered[1],
        manifest=replace(ordered[1].manifest, model_version="conflict"),
    )
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        build_research_summary_stage_artifact(
            identity=identity,
            evaluations=(ordered[0], conflict, ordered[2]),
            evaluation_contexts=bundle["h5_contexts"],
            experiment=bundle["experiment"],
            config=bundle["config"],
            upstream_paths=bundle["h5_upstream"],
            artifact_roots=bundle["artifact_roots"],
            output_root=second_root,
        )


@pytest.mark.skipif(
    not platform_supports_renameat2_noreplace(),
    reason="host lacks atomic directory no-replace publication",
)
def test_run_formal_summary_stage_publish_resume_and_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _stage_bundle(tmp_path, monkeypatch)
    result = run_formal_summary_stage(
        stage_root=bundle["stage_root"],
        artifact_roots=bundle["artifact_roots"],
        config=bundle["config"],
        evaluations=bundle["evaluations"],
        evaluation_contexts=bundle["contexts"],
        experiment=bundle["experiment"],
        horizon_sessions=5,
        upstream_paths=bundle["upstream"],
        resume=True,
    )
    assert result.reused is False
    assert result.receipt.stage == "research-summary"
    assert result.verified.root == result.final_root
    assert result.final_root.name == bundle["model_version"]
    with pytest.raises(TypeError, match="M3_FORMAL_SUMMARY_STAGE_INVALID"):
        pickle.dumps(result)

    resumed = run_formal_summary_stage(
        stage_root=bundle["stage_root"],
        artifact_roots=bundle["artifact_roots"],
        config=bundle["config"],
        evaluations=bundle["evaluations"],
        evaluation_contexts=bundle["contexts"],
        experiment=bundle["experiment"],
        horizon_sessions=5,
        upstream_paths=bundle["upstream"],
        resume=True,
    )
    assert resumed.reused is True
    assert resumed.final_root == result.final_root

    (result.final_root / "metrics.json").write_bytes(b'{"tampered":true}')
    with pytest.raises(M3StageRunnerError) as caught:
        run_formal_summary_stage(
            stage_root=bundle["stage_root"],
            artifact_roots=bundle["artifact_roots"],
            config=bundle["config"],
            evaluations=bundle["evaluations"],
            evaluation_contexts=bundle["contexts"],
            experiment=bundle["experiment"],
            horizon_sessions=5,
            upstream_paths=bundle["upstream"],
            resume=True,
        )
    assert caught.value.code in {
        "STAGE_RECOVERY_CONFLICT",
        "STAGE_OUTPUT_INVALID",
    }
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_final_verifier_rejects_handmade_root_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _stage_bundle(tmp_path, monkeypatch)
    identity = _identity_for(
        stage_root=bundle["stage_root"],
        experiment_key=bundle["experiment"].manifest.experiment_key,
        model=bundle["model"],
        model_version=bundle["model_version"],
    )
    handmade = bundle["stage_root"].joinpath(*identity.final_relative_path.parts)
    handmade.mkdir(parents=True)
    temp_root = (
        bundle["stage_root"] / ".stage-tmp" / f".{identity.node_id}.hand"
    )
    temp_root.mkdir()
    build_research_summary_stage_artifact(
        identity=identity,
        evaluations=bundle["h5"],
        evaluation_contexts=bundle["h5_contexts"],
        experiment=bundle["experiment"],
        config=bundle["config"],
        upstream_paths=bundle["h5_upstream"],
        artifact_roots=bundle["artifact_roots"],
        output_root=temp_root,
    )
    for name in evaluate_module._SUMMARY_FILES:
        shutil.copy2(temp_root / name, handmade / name)
    fake_receipt = bundle["stage_root"] / "receipts" / "handmade.json"
    fake_receipt.parent.mkdir(parents=True, exist_ok=True)
    fake_receipt.write_bytes(b"{}")
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        verify_research_summary_stage_artifact(
            identity=identity,
            root=handmade,
            receipt_path=fake_receipt,
            evaluations=bundle["h5"],
            evaluation_contexts=bundle["h5_contexts"],
            experiment=bundle["experiment"],
            config=bundle["config"],
            upstream_paths=bundle["h5_upstream"],
            artifact_roots=bundle["artifact_roots"],
        )


def test_handler_output_report_matches_summary_stage_spec() -> None:
    assert summary_stage._SUMMARY_OUTPUTS == tuple(
        sorted(item.relative_path for item in SUMMARY_STAGE_SPEC.outputs)
    )
    assert summary_stage._SUMMARY_OUTPUTS == (
        "daily_ic.parquet",
        "fold_metrics.parquet",
        "manifest.json",
        "metrics.json",
    )
