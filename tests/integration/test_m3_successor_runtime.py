"""Deterministic receipt-only integration fixture for successor terminal proof."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import replace
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Literal

import pytest

import quant.research.m3.successor_runtime as runtime
from quant.data.m3_release import VerifiedG1Release
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.orchestration import StageRunner
from quant.research.m3.run_state import compute_work_key, publish_stage_receipt


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _config(*, raw: str, full: str, scientific: str) -> LoadedM3Config:
    config = object.__new__(LoadedM3Config)
    object.__setattr__(
        config,
        "document",
        {"tracking": {"artifact_root": "output/stage"}},
    )
    object.__setattr__(config, "config_version", "test-config-v1")
    object.__setattr__(config, "full_config_sha256", full)
    object.__setattr__(config, "g1_config_sha256", _hex(f"g1:{raw}"))
    object.__setattr__(config, "snapshot_config_sha256", _hex(f"snapshot:{raw}"))
    object.__setattr__(config, "provider_config_sha256", _hex(f"provider:{raw}"))
    object.__setattr__(
        config,
        "scientific_config_sha256",
        scientific,
    )
    object.__setattr__(
        config,
        "provider_validation_config_sha256",
        _hex(f"provider-validation:{raw}"),
    )
    object.__setattr__(
        config,
        "label_reconciliation_config_sha256",
        _hex(f"label-reconciliation:{raw}"),
    )
    object.__setattr__(config, "acceptance_config_sha256", _hex(f"acceptance:{raw}"))
    object.__setattr__(config, "canonical_tracking_uri", "file:///test")
    object.__setattr__(config, "tracking_target_key", _hex(f"tracking:{raw}"))
    object.__setattr__(config, "raw_config_sha256", raw)
    return config


def _release(*, project_root: Path, fold: str) -> VerifiedG1Release:
    release_id = _hex(f"release:{fold}")
    release_root = project_root / "g1" / fold
    release_root.mkdir(parents=True)
    release = SimpleNamespace(root=release_root, release_id=release_id)
    manifest = SimpleNamespace(release_id=release_id)
    verified = object.__new__(VerifiedG1Release)
    object.__setattr__(verified, "release", release)
    object.__setattr__(verified, "manifest", manifest)
    object.__setattr__(verified, "manifest_sha256", _hex(f"manifest:{fold}"))
    object.__setattr__(verified, "quality", SimpleNamespace())
    object.__setattr__(verified, "quality_sha256", _hex(f"quality:{fold}"))
    object.__setattr__(verified, "artifact_paths", ())
    return verified


def _public_api_substitutes(
    *,
    builder_call_records: list[tuple[str, str]] | None = None,
) -> runtime.SuccessorPublicApiBundle:
    def marker(**_kwargs: object) -> object:
        return object()

    folds_sentinel = object()
    label_reconciliation_sentinel = object()

    def folds_builder(**kwargs: object) -> object:
        stage = kwargs.get("stage")
        assert isinstance(stage, str)
        if builder_call_records is not None:
            builder_call_records.append(("folds", stage))
        return folds_sentinel

    def label_reconciliation_builder(**kwargs: object) -> object:
        stage = kwargs.get("stage")
        assert isinstance(stage, str)
        if builder_call_records is not None:
            builder_call_records.append(("label-reconciliation", stage))
        return label_reconciliation_sentinel

    return runtime.SuccessorPublicApiBundle(
        stage_runner_type=StageRunner,
        run_plan_builders={
            stage: (
                folds_builder
                if stage == "folds"
                else label_reconciliation_builder
                if stage == "label-reconciliation"
                else marker
            )
            for stage in (
                "snapshot",
                "provider",
                "provider-validation",
                "experiment-identity",
                "folds",
                "label-reconciliation",
                "work",
                "summary",
            )
        },
        formal_backtest_run_plan=marker,
        formal_backtest_stage=marker,
        formal_tracking_run_plan=marker,
        formal_tracking_stage=marker,
        summary_builder=marker,
        summary_verifier=marker,
        reproducibility_stage=marker,
        reproducibility_verifier=marker,
        readiness_stage=marker,
        readiness_verifier=marker,
        acceptance_stage=marker,
        acceptance_audit=marker,
    )


class _DeterministicProductionBoundary:
    """One-stage/gate substitutes consumed by the concrete production adapter."""

    def __init__(
        self,
        project_root: Path,
        *,
        omit_horizon: int | None = None,
        drift_work_scope: bool = False,
        drift_reproducibility_scope: bool = False,
        alias_physical_receipt: bool = False,
        require_reconstructed_context: bool = False,
    ) -> None:
        self.project_root = project_root
        self.experiment_key = _hex("experiment")
        self.snapshot_id = _hex("snapshot")
        self.omit_horizon = omit_horizon
        self.drift_work_scope = drift_work_scope
        self.drift_reproducibility_scope = drift_reproducibility_scope
        self.alias_physical_receipt = alias_physical_receipt
        self.require_reconstructed_context = require_reconstructed_context
        self.fold_verifications = 0
        self.gate_verifications = 0
        self.gate_contexts: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
        self.public_api_calls: list[str] = []
        self.builder_call_records: list[tuple[str, str]] = []
        self.public_apis = _public_api_substitutes(
            builder_call_records=self.builder_call_records,
        )

    @property
    def dependencies(self) -> runtime.SuccessorProductionDependencies:
        return runtime.SuccessorProductionDependencies(
            stage_runner_factory=runtime.make_project_stage_runner,
            run_upstream_stage=self.run_upstream_stage,
            run_formal_stage=self.run_formal_stage,
            verify_fold=self.verify_fold,
            run_summary=self.run_summary,
            verify_summary=self.verify_summary,
            run_reproducibility=self.run_reproducibility,
            verify_reproducibility=self.verify_reproducibility,
            run_readiness=self.run_readiness,
            verify_readiness=self.verify_readiness,
            run_acceptance=self.run_acceptance,
            verify_acceptance=self.verify_acceptance,
            verify_gate=self.verify_gate,
        )

    def _receipt(
        self,
        *,
        node_id: str,
        stage: str,
        scope: str,
        scope_key: str,
        fold: str | None,
        horizon: int | None,
    ) -> runtime.StageReceiptRef:
        relative = PurePosixPath(
            "output/stage/receipts/features/shared-alias.json"
            if self.alias_physical_receipt and stage == "features"
            else f"output/stage/receipts/{stage}/{node_id}.json"
        )
        receipt_path = self.project_root.joinpath(*relative.parts)
        output_path = (
            self.project_root
            / "output"
            / "stage"
            / "artifacts"
            / (
                "features-shared-alias.bin"
                if self.alias_physical_receipt and stage == "features"
                else f"{node_id}.bin"
            )
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not output_path.exists():
            output_path.write_bytes(node_id.encode("ascii"))
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        publish_stage_receipt(
            receipt_path=receipt_path,
            stage=stage,
            scope=scope,
            scope_key=scope_key,
            artifact_roots={"PROJECT": self.project_root},
            inputs=(),
            outputs=(("PROJECT", output_path),),
        )
        return runtime.StageReceiptRef(
            node_id=node_id,
            stage=stage,
            scope=scope,
            scope_key=scope_key,
            relative_path=relative.as_posix(),
            sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            fold=fold,
            horizon=horizon,
        )

    def _effective_horizon(self, horizon: int | None) -> int | None:
        if self.omit_horizon is not None and horizon == self.omit_horizon:
            return runtime.HORIZONS[0]
        return horizon

    def _stage_receipt(
        self,
        *,
        stage: str,
        horizon: int | None,
        request: runtime.SuccessorFoldRequest,
    ) -> runtime.StageReceiptRef:
        effective = self._effective_horizon(horizon)
        fold = request.fold if stage in {"features", *runtime._HORIZON_WORK_STAGES} else None
        scope = "WORK" if stage in runtime._HORIZON_WORK_STAGES else (
            "SNAPSHOT" if stage == "snapshot" else
            "PROVIDER" if stage in {"provider", "provider-validation"} else
            "EXPERIMENT"
        )
        if stage == "snapshot":
            scope_key = self.snapshot_id
        elif stage == "provider":
            scope_key = _hex("provider")
        elif stage == "provider-validation":
            scope_key = _hex("provider-validation")
        elif stage in {"experiment-identity", "folds", "features", "labels"}:
            scope_key = self.experiment_key
        elif stage == "label-reconciliation":
            scope_key = _hex(f"label-reconciliation:{effective}")
        else:
            assert fold is not None and effective is not None
            scope_key = (
                _hex("drifted-work")
                if self.drift_work_scope
                else compute_work_key(
                    experiment_key=self.experiment_key,
                    fold=fold,
                    horizon=effective,
                )
            )
        suffix = f"-h{effective}" if effective is not None else ""
        fold_suffix = f"-{request.fold}" if fold is not None else ""
        return self._receipt(
            node_id=f"{stage}{fold_suffix}{suffix}",
            stage=stage,
            scope=scope,
            scope_key=scope_key,
            fold=fold,
            horizon=effective,
        )

    def _builder_name(self, stage: str) -> str:
        if stage == "labels":
            return "folds"
        if stage in {
            "features",
            "alignment",
            "train",
            "predictions",
            "evaluation",
            "targets",
            "backtest-plan",
        }:
            return "work"
        return stage

    def run_upstream_stage(
        self,
        *,
        stage: str,
        horizon: int | None,
        request: runtime.SuccessorFoldRequest,
        context: runtime.SuccessorStageContext,
        runner: StageRunner,
        public_apis: runtime.SuccessorPublicApiBundle,
        resume: bool,
    ) -> runtime.StageReceiptRef:
        assert context.fold == request.fold and resume is True
        assert type(runner) is StageRunner
        builder = public_apis.run_plan_builders[self._builder_name(stage)]
        self.public_api_calls.append(self._builder_name(stage))
        builder(stage=stage, horizon=horizon)
        return self._stage_receipt(
            stage=stage,
            horizon=horizon,
            request=request,
        )

    def run_formal_stage(
        self,
        *,
        stage: Literal["backtest", "tracking"],
        horizon: int,
        request: runtime.SuccessorFoldRequest,
        context: runtime.SuccessorStageContext,
        runner: StageRunner,
        public_apis: runtime.SuccessorPublicApiBundle,
        resume: bool,
    ) -> runtime.StageReceiptRef:
        assert context.fold == request.fold and resume is True
        assert type(runner) is StageRunner
        if stage == "backtest":
            plan_builder = public_apis.formal_backtest_run_plan
            stage_runner = public_apis.formal_backtest_stage
        else:
            plan_builder = public_apis.formal_tracking_run_plan
            stage_runner = public_apis.formal_tracking_stage
        self.public_api_calls.append(f"{stage}-run-plan")
        plan_builder(stage=stage, horizon=horizon)
        stage_runner(stage=stage, horizon=horizon)
        return self._stage_receipt(
            stage=stage,
            horizon=horizon,
            request=request,
        )

    def verify_fold(
        self,
        *,
        execution: runtime.FoldExecution,
        context: runtime.SuccessorStageContext,
        public_apis: runtime.SuccessorPublicApiBundle,
    ) -> None:
        del public_apis
        assert context.fold == execution.fold
        self.fold_verifications += 1

    def _gate(
        self,
        gate: runtime.GateName,
        *,
        folds: tuple[runtime.FoldExecution, ...],
        prior_gates: tuple[runtime.GateExecution, ...],
    ) -> runtime.GateExecution:
        identity = runtime.compute_successor_gate_identity(
            gate=gate,
            folds=folds,
            prior_gates=prior_gates,
        )
        refs: list[runtime.StageReceiptRef] = []
        if gate == "summary":
            for horizon in runtime.HORIZONS:
                refs.append(
                    self._receipt(
                        node_id=f"gate-summary-h{horizon}",
                        stage="research-summary",
                        scope="EXPERIMENT",
                        scope_key=runtime.compute_successor_gate_scope_key(
                            gate=gate,
                            fold=None,
                            horizon=horizon,
                            folds=folds,
                            prior_gates=prior_gates,
                        ),
                        fold=None,
                        horizon=horizon,
                    )
                )
        elif gate == "reproducibility":
            for fold in ("fold_001", "fold_002"):
                for horizon in runtime.HORIZONS:
                    refs.append(
                        self._receipt(
                            node_id=f"gate-repro-{fold}-h{horizon}",
                            stage="reproducibility",
                            scope="REPRO",
                            scope_key=(
                                _hex(f"drifted-repro:{fold}:{horizon}")
                                if self.drift_reproducibility_scope
                                else runtime.compute_successor_gate_scope_key(
                                    gate=gate,
                                    fold=fold,
                                    horizon=horizon,
                                    folds=folds,
                                    prior_gates=prior_gates,
                                )
                            ),
                            fold=fold,
                            horizon=horizon,
                        )
                    )
        elif gate == "readiness":
            for fold in ("fold_001", "fold_002"):
                refs.append(
                    self._receipt(
                        node_id=f"gate-readiness-{fold}",
                        stage="readiness-evidence",
                        scope="ACCEPTANCE",
                        scope_key=runtime.compute_successor_gate_scope_key(
                            gate=gate,
                            fold=fold,
                            horizon=None,
                            folds=folds,
                            prior_gates=prior_gates,
                        ),
                        fold=fold,
                        horizon=None,
                    )
                )
        else:
            refs.append(
                self._receipt(
                    node_id="gate-acceptance",
                    stage="acceptance",
                    scope="ACCEPTANCE",
                    scope_key=runtime.compute_successor_gate_scope_key(
                        gate=gate,
                        fold=None,
                        horizon=None,
                        folds=folds,
                        prior_gates=prior_gates,
                    ),
                    fold=None,
                    horizon=None,
                )
            )
        return runtime.GateExecution(
            gate=gate,
            status="PASS",
            identity=identity,
            receipt_refs=tuple(sorted(refs, key=lambda item: item.node_id)),
        )

    def _run_gate(
        self,
        *,
        gate: runtime.GateName,
        folds: tuple[runtime.FoldExecution, ...],
        prior_gates: tuple[runtime.GateExecution, ...],
        context: runtime.SuccessorStageContext,
        runner: StageRunner,
        public_apis: runtime.SuccessorPublicApiBundle,
        resume: bool,
    ) -> runtime.GateExecution:
        assert type(runner) is StageRunner
        del context, resume
        self.public_api_calls.append(f"{gate}-public-run")
        getattr(
            public_apis,
            {
                "summary": "summary_builder",
                "reproducibility": "reproducibility_stage",
                "readiness": "readiness_stage",
                "acceptance": "acceptance_stage",
            }[gate],
        )(gate=gate)
        return self._gate(gate, folds=folds, prior_gates=prior_gates)

    def run_summary(self, **kwargs: object) -> runtime.GateExecution:
        return self._run_gate(gate="summary", **kwargs)

    def run_reproducibility(self, **kwargs: object) -> runtime.GateExecution:
        return self._run_gate(gate="reproducibility", **kwargs)

    def run_readiness(self, **kwargs: object) -> runtime.GateExecution:
        return self._run_gate(gate="readiness", **kwargs)

    def run_acceptance(self, **kwargs: object) -> runtime.GateExecution:
        return self._run_gate(gate="acceptance", **kwargs)

    def _verify_gate_public(
        self, *, gate: runtime.GateExecution, public_apis: runtime.SuccessorPublicApiBundle
    ) -> object:
        verifier_name = {
            "summary": "summary_verifier",
            "reproducibility": "reproducibility_verifier",
            "readiness": "readiness_verifier",
            "acceptance": "acceptance_audit",
        }[gate.gate]
        self.public_api_calls.append(f"{gate.gate}-public-verify")
        return getattr(public_apis, verifier_name)(gate=gate)

    def _verify_gate_dependency(self, **kwargs: object) -> object:
        public_apis = kwargs["public_apis"]
        gate = kwargs["gate"]
        assert type(public_apis) is runtime.SuccessorPublicApiBundle
        assert type(gate) is runtime.GateExecution
        return self._verify_gate_public(gate=gate, public_apis=public_apis)

    def verify_summary(self, **kwargs: object) -> object:
        return self._verify_gate_dependency(**kwargs)

    def verify_reproducibility(self, **kwargs: object) -> object:
        return self._verify_gate_dependency(**kwargs)

    def verify_readiness(self, **kwargs: object) -> object:
        return self._verify_gate_dependency(**kwargs)

    def verify_acceptance(self, **kwargs: object) -> object:
        return self._verify_gate_dependency(**kwargs)

    def verify_gate(
        self,
        *,
        gate: runtime.GateExecution,
        folds: tuple[runtime.FoldExecution, ...],
        prior_gates: tuple[runtime.GateExecution, ...],
        context: runtime.SuccessorStageContext,
        runner: StageRunner,
        public_apis: runtime.SuccessorPublicApiBundle,
    ) -> runtime.GateVerification:
        assert type(gate) is runtime.GateExecution
        assert type(folds) is tuple
        assert type(prior_gates) is tuple
        assert type(context) is runtime.SuccessorStageContext
        assert type(runner) is StageRunner
        assert type(public_apis) is runtime.SuccessorPublicApiBundle
        fold_values = tuple(item.fold for item in folds)
        prior_values = tuple(item.gate for item in prior_gates)
        assert all(type(item) is runtime.FoldExecution for item in folds)
        assert all(type(item) is runtime.GateExecution for item in prior_gates)
        if self.require_reconstructed_context:
            assert fold_values == ("fold_001", "fold_002")
            expected_prior = {
                "summary": (),
                "reproducibility": ("summary",),
                "readiness": ("summary", "reproducibility"),
                "acceptance": ("summary", "reproducibility", "readiness"),
            }[gate.gate]
            assert prior_values == expected_prior
        self.gate_contexts.append((gate.gate, fold_values, prior_values))
        self.gate_verifications += 1
        self._verify_gate_public(gate=gate, public_apis=public_apis)
        return runtime.GateVerification(
            gate=gate.gate,
            identity=gate.identity,
            receipt_node_ids=gate.receipt_node_ids,
        )


def _request(
    tmp_path: Path,
) -> tuple[
    runtime.SuccessorRuntimeRequest,
    _DeterministicProductionBoundary,
    dict[Path, LoadedM3Config],
    dict[str, VerifiedG1Release],
]:
    project = tmp_path / "successor-project"
    (project / "configs").mkdir(parents=True)
    (project / "output" / "stage").mkdir(parents=True)
    configs: dict[Path, LoadedM3Config] = {}
    releases: dict[str, VerifiedG1Release] = {}
    folds: list[runtime.SuccessorFoldRequest] = []
    scientific = _hex("scientific")
    for fold, raw_label in (("fold_001", "config-a"), ("fold_002", "config-b")):
        raw_bytes = raw_label.encode("ascii")
        raw = hashlib.sha256(raw_bytes).hexdigest()
        full = _hex(f"full:{raw_label}")
        config = _config(raw=raw, full=full, scientific=scientific)
        path = project / "configs" / f"{fold}.toml"
        path.write_bytes(raw_bytes)
        configs[path.resolve()] = config
        release = _release(project_root=project, fold=fold)
        releases[release.release.release_id] = release
        folds.append(
            runtime.SuccessorFoldRequest(
                fold=fold,
                config=runtime.SuccessorConfigInput(
                    relative_path=PurePosixPath(f"configs/{fold}.toml"),
                    config=config,
                ),
                release=release,
            )
        )
    request = runtime.SuccessorRuntimeRequest(
        project_root=project,
        controlled_output_root=project / "output" / "stage",
        folds=tuple(folds),
        runtime_identity=runtime.SuccessorRuntimeIdentity(
            code_version="successor-fixture-v1",
            dependency_fingerprint_sha256=_hex("dependencies"),
            provider_runtime_fingerprint_sha256=_hex("provider-runtime"),
        ),
        now=dt.datetime(2026, 8, 23, 12, 0, tzinfo=dt.timezone.utc),
    )
    boundary = _DeterministicProductionBoundary(project)
    return request, boundary, configs, releases


def _install_fixture_verifiers(
    monkeypatch: pytest.MonkeyPatch,
    configs: dict[Path, LoadedM3Config],
    releases: dict[str, VerifiedG1Release],
    public_apis: runtime.SuccessorPublicApiBundle,
) -> None:
    monkeypatch.setattr(
        runtime,
        "load_m3_config",
        lambda path: configs[path.resolve()],
    )
    monkeypatch.setattr(
        runtime,
        "verify_g1_release",
        lambda release: releases[release.release_id],
    )
    monkeypatch.setattr(
        runtime,
        "make_public_successor_api_bundle",
        lambda: public_apis,
    )


def _adapter(boundary: _DeterministicProductionBoundary) -> runtime.ProductionSuccessorStageAdapter:
    return runtime.make_production_successor_stage_adapter(
        dependencies=boundary.dependencies,
    )


def _run(
    request: runtime.SuccessorRuntimeRequest,
    boundary: _DeterministicProductionBoundary,
) -> runtime.SuccessorRunResult:
    return runtime.run_production_two_fold_successor(
        request=request,
        dependencies=boundary.dependencies,
        resume=True,
    )


def test_two_fold_terminal_is_durable_and_replayable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis)

    first = _run(request, boundary)
    second = _run(request, boundary)

    assert first.reused is False
    assert second.reused is True
    assert first.attestation == second.attestation
    assert first.terminal_path.read_text(encoding="utf-8").endswith("}")
    assert boundary.fold_verifications == 6
    assert boundary.gate_verifications == 12
    first_fold_refs = {ref.node_id: ref for ref in first.folds[0].receipts}
    second_fold_refs = {ref.node_id: ref for ref in first.folds[1].receipts}
    shared_node_ids = first_fold_refs.keys() & second_fold_refs.keys()
    assert shared_node_ids
    assert all(
        first_fold_refs[node_id] == second_fold_refs[node_id]
        and first_fold_refs[node_id].fold is None
        and first_fold_refs[node_id].stage in runtime._SHARED_RECEIPT_STAGES
        for node_id in shared_node_ids
    )
    assert first.gates[0].gate == "summary"
    assert boundary.gate_contexts[0] == (
        "summary",
        ("fold_001", "fold_002"),
        (),
    )
    assert "backtest-run-plan" in boundary.public_api_calls
    assert "tracking-run-plan" in boundary.public_api_calls
    assert "summary-public-run" in boundary.public_api_calls
    assert "acceptance-public-verify" in boundary.public_api_calls
    assert not tuple(request.controlled_output_root.glob(".completion.json.*.tmp"))


def test_terminal_rejects_receipt_bytes_and_unknown_tree_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis)
    first = _run(request, boundary)
    adapter = _adapter(boundary)

    config_path = request.project_root / "configs" / "fold_001.toml"
    original_config = config_path.read_bytes()
    config_path.write_bytes(original_config + b"\ndrift")
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        runtime.verify_terminal_attestation(
            request=request,
            fold_verifier=adapter.verify_fold,
            gate_verifier=adapter.verify_gate,
        )
    assert error.value.code == "SUCCESSOR_TERMINAL_INVALID"
    config_path.write_bytes(original_config)

    snapshot_refs = tuple(
        ref
        for ref in first.attestation.receipts
        if ref.stage == "snapshot" and ref.fold is None and ref.horizon is None
    )
    assert len(snapshot_refs) == 1
    snapshot_ref = snapshot_refs[0]
    assert snapshot_ref.scope == "SNAPSHOT"
    assert snapshot_ref.scope_key == boundary.snapshot_id
    snapshot_path_shape = PurePosixPath(snapshot_ref.relative_path).parts
    assert snapshot_path_shape[:4] == ("output", "stage", "receipts", "snapshot")
    assert len(snapshot_path_shape) == 5
    assert snapshot_path_shape[-1].endswith(".json")
    receipt = request.project_root / snapshot_ref.relative_path
    assert receipt.is_file()
    original_receipt = receipt.read_bytes()
    assert hashlib.sha256(original_receipt).hexdigest() == snapshot_ref.sha256
    receipt.write_bytes(original_receipt + b"\n")
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        runtime.verify_terminal_attestation(
            request=request,
            fold_verifier=adapter.verify_fold,
            gate_verifier=adapter.verify_gate,
        )
    assert error.value.code == "SUCCESSOR_TERMINAL_INVALID"

    # Rebuild the independent fixture before testing the unknown-entry branch.
    request_2, boundary_2, configs_2, releases_2 = _request(tmp_path / "second")
    _install_fixture_verifiers(
        monkeypatch, configs_2, releases_2, boundary_2.public_apis
    )
    _run(request_2, boundary_2)
    adapter_2 = _adapter(boundary_2)
    (request_2.controlled_output_root / "unexpected.json").write_text(
        "unknown", encoding="utf-8"
    )
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        runtime.verify_terminal_attestation(
            request=request_2,
            fold_verifier=adapter_2.verify_fold,
            gate_verifier=adapter_2.verify_gate,
        )
    assert error.value.code == "SUCCESSOR_TERMINAL_INVALID"


def test_missing_h10_cannot_publish_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    boundary.omit_horizon = 10
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis)

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        _run(request, boundary)

    assert error.value.code == "SUCCESSOR_STAGE_INVALID"
    assert not (request.controlled_output_root / runtime.TERMINAL_FILENAME).exists()


def test_missing_production_dependency_fails_before_any_successor_write(
    tmp_path: Path,
) -> None:
    request, boundary, _configs, _releases = _request(tmp_path)
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        runtime.make_production_successor_stage_adapter(
            dependencies=replace(
                boundary.dependencies,
                run_readiness=None,
            ),
            public_apis=boundary.public_apis,
        )

    assert error.value.code == "SUCCESSOR_INPUT_INVALID"
    assert not (request.controlled_output_root / runtime.TERMINAL_FILENAME).exists()
    assert not (request.controlled_output_root / "receipts").exists()
    assert not (request.controlled_output_root / "artifacts").exists()


def test_request_rejects_a_missing_second_fold(tmp_path: Path) -> None:
    request, _boundary, _configs, _releases = _request(tmp_path)

    with pytest.raises(ValueError):
        replace(request, folds=(request.folds[0], request.folds[0]))


def test_effective_horizon_requires_explicit_omit_setting() -> None:
    default_boundary = _DeterministicProductionBoundary(Path("fixture-project"))
    assert default_boundary._effective_horizon(None) is None

    explicit_boundary = _DeterministicProductionBoundary(
        Path("fixture-project"),
        omit_horizon=10,
    )
    assert explicit_boundary._effective_horizon(10) == runtime.HORIZONS[0]
    assert explicit_boundary._effective_horizon(None) is None


def test_terminal_rejects_unknown_empty_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis)
    _run(request, boundary)

    (request.controlled_output_root / "unknown-empty").mkdir()
    adapter = _adapter(boundary)
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        runtime.verify_terminal_attestation(
            request=request,
            fold_verifier=adapter.verify_fold,
            gate_verifier=adapter.verify_gate,
        )

    assert error.value.code == "SUCCESSOR_TERMINAL_INVALID"


def test_production_factory_rejects_arbitrary_stage_runner_bypass(
    tmp_path: Path,
) -> None:
    request, boundary, _configs, _releases = _request(tmp_path)

    def bypass_runner(**_kwargs: object) -> object:
        return object()

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        runtime.make_production_successor_stage_adapter(
            dependencies=replace(
                boundary.dependencies,
                stage_runner_factory=bypass_runner,
            ),
            public_apis=boundary.public_apis,
        )

    assert error.value.code == "SUCCESSOR_INPUT_INVALID"
    assert not (request.controlled_output_root / runtime.TERMINAL_FILENAME).exists()
    assert not (request.controlled_output_root / "receipts").exists()
    assert not (request.controlled_output_root / "artifacts").exists()


def test_runner_accepts_concrete_path_subclass_and_rejects_invalid_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis)
    context = runtime.SuccessorStageContext(request=request, fold="fold_001")
    config = request.folds[0].config.config

    adapter = _adapter(boundary)
    runner = adapter._runner(context=context, config=config)
    actual_stage_root = getattr(runner, "_stage_root")
    expected_stage_root = runtime.project_stage_root(
        project_root=request.project_root,
        config=config,
    )
    assert isinstance(actual_stage_root, Path)
    assert type(actual_stage_root) is not Path
    assert actual_stage_root == expected_stage_root

    original_factory = runtime.make_project_stage_runner

    def non_path_factory(
        *, project_root: Path, stage_root: Path, config: LoadedM3Config
    ) -> StageRunner:
        candidate = original_factory(
            project_root=project_root,
            stage_root=stage_root,
            config=config,
        )
        object.__setattr__(candidate, "_stage_root", str(stage_root))
        return candidate

    def mismatched_root_factory(
        *, project_root: Path, stage_root: Path, config: LoadedM3Config
    ) -> StageRunner:
        candidate = original_factory(
            project_root=project_root,
            stage_root=stage_root,
            config=config,
        )
        object.__setattr__(candidate, "_stage_root", stage_root / "unexpected")
        return candidate

    for invalid_factory in (non_path_factory, mismatched_root_factory):
        monkeypatch.setattr(runtime, "make_project_stage_runner", invalid_factory)
        dependencies = replace(
            boundary.dependencies,
            stage_runner_factory=invalid_factory,
        )
        invalid_adapter = runtime.make_production_successor_stage_adapter(
            dependencies=dependencies,
        )
        with pytest.raises(runtime.SuccessorRuntimeError) as error:
            invalid_adapter._runner(context=context, config=config)
        assert error.value.code == "SUCCESSOR_INPUT_INVALID"


def test_production_factory_rejects_marker_public_api_bundle(
    tmp_path: Path,
) -> None:
    request, boundary, _configs, _releases = _request(tmp_path)

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        runtime.make_production_successor_stage_adapter(
            dependencies=boundary.dependencies,
            public_apis=boundary.public_apis,
        )

    assert error.value.code == "SUCCESSOR_INPUT_INVALID"
    assert not (request.controlled_output_root / runtime.TERMINAL_FILENAME).exists()
    assert not (request.controlled_output_root / "receipts").exists()
    assert not (request.controlled_output_root / "artifacts").exists()


def test_labels_routes_to_canonical_folds_builder_not_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis)

    assert "labels" not in boundary.public_apis.run_plan_builders
    assert (
        boundary.public_apis.run_plan_builders["folds"]
        is not boundary.public_apis.run_plan_builders["label-reconciliation"]
    )

    adapter = _adapter(boundary)
    adapter.run_fold(
        request=request.folds[0],
        context=runtime.SuccessorStageContext(
            request=request,
            fold=request.folds[0].fold,
        ),
        resume=True,
    )

    assert [
        record
        for record in boundary.builder_call_records
        if record[1] == "labels"
    ] == [("folds", "labels")] * len(runtime.HORIZONS)
    assert [
        record
        for record in boundary.builder_call_records
        if record[1] == "label-reconciliation"
    ] == [
        ("label-reconciliation", "label-reconciliation")
    ] * len(runtime.HORIZONS)


def test_scope_key_drift_cannot_join_work_to_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    boundary.drift_work_scope = True
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis)

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        _run(request, boundary)

    assert error.value.code == "SUCCESSOR_STAGE_INVALID"
    assert not (request.controlled_output_root / runtime.TERMINAL_FILENAME).exists()


def test_reproducibility_scope_key_drift_cannot_join_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    boundary.drift_reproducibility_scope = True
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis)

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        _run(request, boundary)

    assert error.value.code == "SUCCESSOR_GATE_FAILED"
    assert not (request.controlled_output_root / runtime.TERMINAL_FILENAME).exists()


def test_distinct_node_same_receipt_path_and_bytes_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    boundary.alias_physical_receipt = True
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis)

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        _run(request, boundary)

    assert error.value.code == "SUCCESSOR_TERMINAL_INVALID"
    assert not (request.controlled_output_root / runtime.TERMINAL_FILENAME).exists()


def test_fresh_gate_verifier_requires_reconstructed_fold_and_prior_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    boundary.require_reconstructed_context = True
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis)

    _run(request, boundary)

    expected = [
        ("summary", ("fold_001", "fold_002"), ()),
        ("reproducibility", ("fold_001", "fold_002"), ("summary",)),
        (
            "readiness",
            ("fold_001", "fold_002"),
            ("summary", "reproducibility"),
        ),
        (
            "acceptance",
            ("fold_001", "fold_002"),
            ("summary", "reproducibility", "readiness"),
        ),
    ]
    assert boundary.gate_contexts == expected + expected
