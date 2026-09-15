"""Deterministic receipt-only integration fixture for successor terminal proof."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import replace
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Callable, Literal

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


def _release_alias(source: VerifiedG1Release, *, root: Path) -> VerifiedG1Release:
    """Build a distinct verified wrapper with the source release identity."""
    alias = object.__new__(VerifiedG1Release)
    object.__setattr__(
        alias,
        "release",
        SimpleNamespace(root=root, release_id=source.release.release_id),
    )
    object.__setattr__(
        alias,
        "manifest",
        SimpleNamespace(release_id=source.manifest.release_id),
    )
    object.__setattr__(alias, "manifest_sha256", source.manifest_sha256)
    object.__setattr__(alias, "quality", source.quality)
    object.__setattr__(alias, "quality_sha256", source.quality_sha256)
    object.__setattr__(alias, "artifact_paths", source.artifact_paths)
    return alias


def _public_api_substitutes(
    *,
    builder_call_records: list[tuple[str, str]] | None = None,
) -> runtime.SuccessorPublicApiBundle:
    def marker(**_kwargs: object) -> object:
        return object()

    experiment_artifacts_sentinel = object()
    label_reconciliation_sentinel = object()
    work_sentinel = object()

    def experiment_artifacts_builder(**kwargs: object) -> object:
        wave = kwargs.get("wave")
        assert isinstance(wave, str)
        if builder_call_records is not None:
            builder_call_records.append(("experiment-artifacts", wave))
        return experiment_artifacts_sentinel

    def label_reconciliation_builder(**kwargs: object) -> object:
        wave = kwargs.get("wave")
        assert isinstance(wave, str)
        if builder_call_records is not None:
            builder_call_records.append(("label-reconciliation", wave))
        return label_reconciliation_sentinel

    def work_builder(**kwargs: object) -> object:
        wave = kwargs.get("wave")
        assert isinstance(wave, str)
        if builder_call_records is not None:
            builder_call_records.append(("work", wave))
        return work_sentinel

    return runtime.SuccessorPublicApiBundle(
        stage_runner_type=StageRunner,
        run_plan_builders={
            stage: (
                experiment_artifacts_builder
                if stage == "experiment-artifacts"
                else label_reconciliation_builder
                if stage == "label-reconciliation"
                else work_builder
                if stage == "work"
                else marker
            )
            for stage in (
                "snapshot",
                "provider",
                "provider-validation",
                "experiment-identity",
                "experiment-artifacts",
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
        alias_physical_receipt: bool = False,
        require_reconstructed_context: bool = False,
        masquerade_join_scope: bool = False,
        collide_readiness_keys: bool = False,
        force_acceptance_identity_as_key: bool = False,
        force_acceptance_identity_masquerade: bool = False,
        force_acceptance_project_alias: bool = False,
        force_acceptance_mixed_alias: bool = False,
        force_summary_g8_alias: bool = False,
    ) -> None:
        self.project_root = project_root
        self.experiment_key = _hex("experiment")
        self.snapshot_id = _hex("snapshot")
        self.omit_horizon = omit_horizon
        self.drift_work_scope = drift_work_scope
        self.alias_physical_receipt = alias_physical_receipt
        self.require_reconstructed_context = require_reconstructed_context
        self.masquerade_join_scope = masquerade_join_scope
        self.collide_readiness_keys = collide_readiness_keys
        self.force_acceptance_identity_as_key = force_acceptance_identity_as_key
        self.force_acceptance_identity_masquerade = force_acceptance_identity_masquerade
        self.force_acceptance_project_alias = force_acceptance_project_alias
        self.force_acceptance_mixed_alias = force_acceptance_mixed_alias
        self.force_summary_g8_alias = force_summary_g8_alias
        self.fold_verifications = 0
        self.gate_verifications = 0
        self.gate_contexts: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
        self.public_api_calls: list[str] = []
        self.builder_call_records: list[tuple[str, str]] = []
        self._stub_wave_cache: dict[str, tuple[runtime.StageReceiptRef, ...]] = {}
        self.public_apis = _public_api_substitutes(
            builder_call_records=self.builder_call_records,
        )

    def _stage_root(self) -> Path:
        return self.project_root / "output" / "stage"

    @property
    def dependencies(self) -> runtime.SuccessorProductionDependencies:
        import quant.research.m3.successor_downstream_stage as downstream
        import quant.research.m3.successor_upstream_stage as upstream

        return runtime.SuccessorProductionDependencies(
            stage_runner_factory=runtime.make_project_stage_runner,
            run_upstream_wave=upstream.run_successor_upstream_wave,
            run_formal_stage=downstream.run_successor_formal_stage,
            verify_fold=downstream.verify_successor_fold,
            run_summary=upstream.run_successor_formal_summary_gate,
            verify_summary=downstream.verify_successor_summary_gate,
            run_reproducibility=downstream.run_successor_reproducibility_gate,
            verify_reproducibility=downstream.verify_successor_reproducibility_gate,
            run_readiness=downstream.run_successor_readiness_gate,
            verify_readiness=downstream.verify_successor_readiness_gate,
            run_acceptance=downstream.run_successor_acceptance_gate,
            verify_acceptance=downstream.verify_successor_acceptance_gate,
            verify_gate=downstream.verify_successor_terminal_gate,
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
        root_alias: str | None = None,
    ) -> runtime.StageReceiptRef:
        if root_alias is None:
            if stage == "acceptance" and self.force_acceptance_mixed_alias:
                root_alias = "MIXED"
            elif stage == "acceptance" and not self.force_acceptance_project_alias:
                root_alias = "G8"
            elif stage == "research-summary" and self.force_summary_g8_alias:
                root_alias = "G8"
            else:
                root_alias = "PROJECT"
        stage_root = self._stage_root()
        if root_alias == "MIXED":
            artifact_roots = {"G8": stage_root, "PROJECT": self.project_root}
            relative = PurePosixPath(f"output/stage/receipts/{stage}/{node_id}.json")
            input_path = stage_root / "artifacts" / f"{node_id}-input.bin"
            output_path = stage_root / "artifacts" / f"{node_id}.bin"
            input_path.parent.mkdir(parents=True, exist_ok=True)
            if not input_path.exists():
                input_path.write_bytes(b"mixed-project-input")
            if not output_path.exists():
                output_path.write_bytes(node_id.encode("ascii"))
            receipt_path = self.project_root.joinpath(*relative.parts)
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            publish_stage_receipt(
                receipt_path=receipt_path,
                stage=stage,
                scope=scope,
                scope_key=scope_key,
                artifact_roots=artifact_roots,
                inputs=(("PROJECT", input_path),),
                outputs=(("G8", output_path),),
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
        if root_alias == "G8":
            artifact_roots = {"G8": stage_root}
            relative = PurePosixPath(f"output/stage/receipts/{stage}/{node_id}.json")
            output_path = stage_root / "artifacts" / f"{node_id}.bin"
        else:
            artifact_roots = {"PROJECT": self.project_root}
            relative = PurePosixPath(
                "output/stage/receipts/features/shared-alias.json"
                if self.alias_physical_receipt and stage == "features"
                else f"output/stage/receipts/{stage}/{node_id}.json"
            )
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
        receipt_path = self.project_root.joinpath(*relative.parts)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not output_path.exists():
            output_path.write_bytes(node_id.encode("ascii"))
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        publish_stage_receipt(
            receipt_path=receipt_path,
            stage=stage,
            scope=scope,
            scope_key=scope_key,
            artifact_roots=artifact_roots,
            inputs=(),
            outputs=((root_alias, output_path),),
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
        fold: str | None,
    ) -> runtime.StageReceiptRef:
        effective = self._effective_horizon(horizon)
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
        fold_suffix = f"-{fold}" if fold is not None else ""
        return self._receipt(
            node_id=f"{stage}{fold_suffix}{suffix}",
            stage=stage,
            scope=scope,
            scope_key=scope_key,
            fold=fold,
            horizon=effective,
        )

    def run_upstream_wave(
        self,
        *,
        wave: str,
        request: runtime.SuccessorFoldRequest,
        context: runtime.SuccessorStageContext,
        runner: StageRunner,
        public_apis: runtime.SuccessorPublicApiBundle,
        prior_refs: tuple[runtime.StageReceiptRef, ...],
        resume: bool,
    ) -> tuple[runtime.StageReceiptRef, ...]:
        assert context.request is not None
        assert type(runner) is StageRunner
        assert type(prior_refs) is tuple
        assert wave not in {"labels", "features", "folds"}
        assert all(type(item) is runtime.StageReceiptRef for item in prior_refs)
        cached = self._stub_wave_cache.get(wave)
        if cached is not None:
            return cached
        builder = public_apis.run_plan_builders[wave]
        self.public_api_calls.append(wave)
        builder(wave=wave)
        refs: list[runtime.StageReceiptRef] = []
        if wave in runtime._SHARED_SINGLE_WAVES:
            refs.append(
                self._stage_receipt(stage=wave, horizon=None, fold=None)
            )
        elif wave == "experiment-artifacts":
            for horizon in runtime.HORIZONS:
                refs.append(
                    self._stage_receipt(
                        stage="labels", horizon=horizon, fold=None,
                    )
                )
            refs.append(
                self._stage_receipt(stage="folds", horizon=None, fold=None)
            )
        elif wave == "label-reconciliation":
            for horizon in runtime.HORIZONS:
                refs.append(
                    self._stage_receipt(
                        stage="label-reconciliation",
                        horizon=horizon,
                        fold=None,
                    )
                )
        elif wave == "work":
            for fold_request in context.request.folds:
                fold = fold_request.fold
                refs.append(
                    self._stage_receipt(
                        stage="features", horizon=None, fold=fold,
                    )
                )
                for horizon in runtime.HORIZONS:
                    for stage in runtime._WORK_PRE_FORMAL_STAGES[1:]:
                        refs.append(
                            self._stage_receipt(
                                stage=stage, horizon=horizon, fold=fold,
                            )
                        )
        else:
            raise AssertionError(f"unexpected wave {wave}")
        result = tuple(sorted(refs, key=lambda item: item.node_id))
        self._stub_wave_cache[wave] = result
        return result

    def run_formal_stage(
        self,
        *,
        stage: Literal["backtest", "tracking"],
        horizon: int,
        request: runtime.SuccessorFoldRequest,
        context: runtime.SuccessorStageContext,
        runner: StageRunner,
        public_apis: runtime.SuccessorPublicApiBundle,
        prior_refs: tuple[runtime.StageReceiptRef, ...],
        resume: bool,
    ) -> runtime.StageReceiptRef:
        assert context.fold == request.fold and resume is True
        assert type(runner) is StageRunner
        assert type(prior_refs) is tuple
        assert all(type(item) is runtime.StageReceiptRef for item in prior_refs)
        assert tuple(item.node_id for item in prior_refs) == tuple(
            sorted(item.node_id for item in prior_refs)
        )
        if stage == "backtest":
            plan_builder = public_apis.formal_backtest_run_plan
            stage_runner = public_apis.formal_backtest_stage
        else:
            plan_builder = public_apis.formal_tracking_run_plan
            stage_runner = public_apis.formal_tracking_stage
            backtest_matches = tuple(
                item
                for item in prior_refs
                if item.stage == "backtest"
                and item.fold == request.fold
                and item.horizon == horizon
            )
            assert len(backtest_matches) == 1
        self.public_api_calls.append(f"{stage}-run-plan")
        plan_builder(stage=stage, horizon=horizon)
        stage_runner(stage=stage, horizon=horizon)
        return self._stage_receipt(
            stage=stage,
            horizon=horizon,
            fold=request.fold,
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
            experiment_keys = {item.experiment_key for item in folds}
            assert len(experiment_keys) == 1
            physical_key = next(iter(experiment_keys))
            for horizon in runtime.HORIZONS:
                refs.append(
                    self._receipt(
                        node_id=f"gate-summary-h{horizon}",
                        stage="research-summary",
                        scope="EXPERIMENT",
                        scope_key=physical_key,
                        fold=None,
                        horizon=horizon,
                    )
                )
        elif gate == "reproducibility":
            for fold in ("fold_001", "fold_002"):
                for horizon in runtime.HORIZONS:
                    physical_key = _hex(f"comparison:{fold}:{horizon}")
                    published = physical_key
                    if self.masquerade_join_scope:
                        # Publish real comparison_key bytes, then point the ref
                        # at a legacy successor join-hash disguise.
                        published = physical_key
                    ref = self._receipt(
                        node_id=f"gate-repro-{fold}-h{horizon}",
                        stage="reproducibility",
                        scope="REPRO",
                        scope_key=published,
                        fold=fold,
                        horizon=horizon,
                    )
                    if self.masquerade_join_scope:
                        ref = replace(ref, scope_key=_hex(f"legacy-join:{fold}:{horizon}"))
                    refs.append(ref)
        elif gate == "readiness":
            physical_key = (
                _hex("readiness:collided")
                if self.collide_readiness_keys
                else _hex("readiness:global")
            )
            refs.append(
                self._receipt(
                    node_id="gate-readiness",
                    stage="readiness-evidence",
                    scope="ACCEPTANCE",
                    scope_key=physical_key,
                    fold=None,
                    horizon=None,
                )
            )
            if self.collide_readiness_keys:
                # Adversarial: duplicate fold-bound copy of same readiness bytes.
                refs.append(
                    self._receipt(
                        node_id="gate-readiness-fold-dup",
                        stage="readiness-evidence",
                        scope="ACCEPTANCE",
                        scope_key=physical_key,
                        fold="fold_001",
                        horizon=None,
                    )
                )
        else:
            physical_key = (
                identity
                if self.force_acceptance_identity_as_key
                else _hex("acceptance-physical-key")
            )
            ref = self._receipt(
                node_id="gate-acceptance",
                stage="acceptance",
                scope="ACCEPTANCE",
                scope_key=(
                    _hex("acceptance-physical-key")
                    if self.force_acceptance_identity_masquerade
                    else physical_key
                ),
                fold=None,
                horizon=None,
            )
            if self.force_acceptance_identity_masquerade:
                ref = replace(ref, scope_key=identity)
            refs.append(ref)
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
    *,
    same_config: bool = False,
    same_physical: bool = False,
) -> tuple[
    runtime.SuccessorRuntimeRequest,
    _DeterministicProductionBoundary,
    dict[Path, LoadedM3Config],
    dict[str, VerifiedG1Release],
]:
    project = tmp_path / "successor-project"
    (project / "configs").mkdir(parents=True)
    (project / "output" / "stage").mkdir(parents=True)
    python_path = type(Path())(project / "toolchain" / "python.exe")
    python_path.parent.mkdir(parents=True)
    python_path.write_bytes(b"fixture-python")
    dump_path = type(Path())(project / "data" / "external" / "qlib" / "v0.9.7" / "dump_bin.py")
    dump_path.parent.mkdir(parents=True)
    dump_path.write_bytes(b"dump")
    configs: dict[Path, LoadedM3Config] = {}
    releases: dict[str, VerifiedG1Release] = {}
    folds: list[runtime.SuccessorFoldRequest] = []
    shared_path = project / "configs" / "shared.toml"
    scientific = _hex("scientific")
    for fold, raw_label in (("fold_001", "config-a"), ("fold_002", "config-b")):
        if same_config:
            raw_label = "config-a"
        raw_bytes = raw_label.encode("ascii")
        raw = hashlib.sha256(raw_bytes).hexdigest()
        full = _hex(f"full:{raw_label}")
        config = _config(raw=raw, full=full, scientific=scientific)
        path = (
            shared_path
            if same_physical
            else project / "configs" / f"{fold}.toml"
        )
        if not path.exists():
            path.write_bytes(raw_bytes)
        configs[path.resolve()] = config
        release = _release(project_root=project, fold=fold)
        releases[release.release.release_id] = release
        folds.append(
            runtime.SuccessorFoldRequest(
                fold=fold,
                config=runtime.SuccessorConfigInput(
                    relative_path=(
                        PurePosixPath("configs/shared.toml")
                        if same_physical
                        else PurePosixPath(f"configs/{fold}.toml")
                    ),
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
        toolchain=runtime.SuccessorToolchainBinding(
            python_executable=python_path,
            qlib_dump_tool_path=dump_path,
            timeout_seconds=30.0,
        ),
    )
    boundary = _DeterministicProductionBoundary(project)
    return request, boundary, configs, releases


def _install_fixture_verifiers(
    monkeypatch: pytest.MonkeyPatch,
    configs: dict[Path, LoadedM3Config],
    releases: dict[str, VerifiedG1Release],
    public_apis: runtime.SuccessorPublicApiBundle,
    boundary: _DeterministicProductionBoundary | None = None,
    load_calls: list[Path] | None = None,
    runtime_read_calls: list[Path] | None = None,
    release_calls: list[str] | None = None,
    release_overrides: dict[int, VerifiedG1Release] | None = None,
    after_load: Callable[[Path, int], None] | None = None,
) -> None:
    import quant.research.m3.successor_downstream_stage as downstream
    import quant.research.m3.successor_upstream_stage as upstream

    def load_config(path: Path) -> LoadedM3Config:
        if load_calls is not None:
            load_calls.append(path.resolve())
        result = configs[path.resolve()]
        if after_load is not None:
            after_load(path.resolve(), len(load_calls) if load_calls is not None else 0)
        return result

    def verify_release(release: object) -> VerifiedG1Release:
        assert isinstance(release, SimpleNamespace)
        if release_calls is not None:
            release_calls.append(release.release_id)
        if release_overrides is not None and id(release) in release_overrides:
            return release_overrides[id(release)]
        return releases[release.release_id]

    monkeypatch.setattr(runtime, "load_m3_config", load_config)
    monkeypatch.setattr(runtime, "verify_g1_release", verify_release)
    if runtime_read_calls is not None:
        original_read = runtime._read_regular_file

        def read_file(path: Path) -> bytes:
            resolved = path.resolve()
            runtime_read_calls.append(resolved)
            return original_read(path)

        monkeypatch.setattr(runtime, "_read_regular_file", read_file)
    monkeypatch.setattr(
        runtime,
        "make_public_successor_api_bundle",
        lambda: public_apis,
    )
    monkeypatch.setattr(
        upstream,
        "validate_successor_toolchain_binding",
        lambda **_kwargs: (
            "/fixture/python",
            "data/external/qlib/v0.9.7/dump_bin.py",
            4,
            _hex("dump-bytes"),
        ),
    )
    if boundary is not None:
        monkeypatch.setattr(
            upstream, "run_successor_upstream_wave", boundary.run_upstream_wave
        )
        monkeypatch.setattr(
            upstream, "run_successor_formal_summary_gate", boundary.run_summary
        )
        monkeypatch.setattr(
            downstream, "run_successor_formal_stage", boundary.run_formal_stage
        )
        monkeypatch.setattr(downstream, "verify_successor_fold", boundary.verify_fold)
        monkeypatch.setattr(
            downstream, "verify_successor_summary_gate", boundary.verify_summary
        )
        monkeypatch.setattr(
            downstream,
            "run_successor_reproducibility_gate",
            boundary.run_reproducibility,
        )
        monkeypatch.setattr(
            downstream,
            "verify_successor_reproducibility_gate",
            boundary.verify_reproducibility,
        )
        monkeypatch.setattr(
            downstream, "run_successor_readiness_gate", boundary.run_readiness
        )
        monkeypatch.setattr(
            downstream, "verify_successor_readiness_gate", boundary.verify_readiness
        )
        monkeypatch.setattr(
            downstream, "run_successor_acceptance_gate", boundary.run_acceptance
        )
        monkeypatch.setattr(
            downstream, "verify_successor_acceptance_gate", boundary.verify_acceptance
        )
        monkeypatch.setattr(
            downstream, "verify_successor_terminal_gate", boundary.verify_gate
        )
        boundary._stub_wave_cache.clear()
        upstream._reset_wave_registry_for_tests()


def _observe_validation_rounds(
    monkeypatch: pytest.MonkeyPatch,
    *,
    runtime_read_calls: list[Path],
    load_calls: list[Path],
    release_calls: list[str],
    validation_rounds: list[tuple[list[Path], list[Path], list[str]]],
) -> None:
    original_validate_request = runtime._validate_request

    def validate_request(request: runtime.SuccessorRuntimeRequest) -> None:
        read_start = len(runtime_read_calls)
        load_start = len(load_calls)
        release_start = len(release_calls)
        original_validate_request(request)
        validation_rounds.append(
            (
                runtime_read_calls[read_start:],
                load_calls[load_start:],
                release_calls[release_start:],
            )
        )

    monkeypatch.setattr(runtime, "_validate_request", validate_request)


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
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)

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


def test_same_config_paths_run_two_distinct_folds_with_fresh_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(
        tmp_path, same_config=True, same_physical=True
    )
    (request.project_root / "configs" / "unbound.toml").write_bytes(b"unbound")
    shared_path = (request.project_root / "configs" / "shared.toml").resolve()
    terminal_path = (
        request.controlled_output_root / runtime.TERMINAL_FILENAME
    ).resolve()
    load_calls: list[Path] = []
    runtime_read_calls: list[Path] = []
    release_calls: list[str] = []
    validation_rounds: list[tuple[list[Path], list[Path], list[str]]] = []
    _install_fixture_verifiers(
        monkeypatch,
        configs,
        releases,
        boundary.public_apis,
        boundary,
        load_calls=load_calls,
        runtime_read_calls=runtime_read_calls,
        release_calls=release_calls,
    )
    _observe_validation_rounds(
        monkeypatch,
        runtime_read_calls=runtime_read_calls,
        load_calls=load_calls,
        release_calls=release_calls,
        validation_rounds=validation_rounds,
    )

    result = _run(request, boundary)

    expected_release_calls = [
        request.folds[0].release.manifest.release_id,
        request.folds[1].release.manifest.release_id,
    ]
    expected_round = (
        [shared_path, shared_path],
        [shared_path, shared_path],
        expected_release_calls,
    )
    assert validation_rounds == [expected_round, expected_round]
    assert release_calls == expected_release_calls + expected_release_calls
    assert [path for path in runtime_read_calls if path == shared_path] == [
        shared_path,
        shared_path,
        shared_path,
        shared_path,
    ]
    assert all(
        path == shared_path
        or path.is_relative_to(request.controlled_output_root)
        for path in runtime_read_calls
    )
    assert terminal_path in runtime_read_calls
    assert (request.project_root / "configs" / "unbound.toml").resolve() not in runtime_read_calls
    assert len(result.folds) == 2
    assert {fold.fold for fold in result.folds} == {"fold_001", "fold_002"}
    assert result.folds[0].config_raw_sha256 == result.folds[1].config_raw_sha256
    assert result.folds[0].config_full_sha256 == result.folds[1].config_full_sha256
    assert result.folds[0].g1_release_id != result.folds[1].g1_release_id
    work_ownership = {
        (work.fold, work.horizon)
        for execution in result.folds
        for work in execution.work_identities
    }
    assert work_ownership == {
        ("fold_001", 5),
        ("fold_001", 10),
        ("fold_002", 5),
        ("fold_002", 10),
    }
    assert all(
        work.work_key
        == compute_work_key(
            experiment_key=execution.experiment_key,
            fold=work.fold,
            horizon=work.horizon,
        )
        for execution in result.folds
        for work in execution.work_identities
    )
    first_refs = {ref.node_id: ref for ref in result.folds[0].receipts}
    second_refs = {ref.node_id: ref for ref in result.folds[1].receipts}
    shared_node_ids = first_refs.keys() & second_refs.keys()
    assert shared_node_ids
    assert all(
        first_refs[node_id] == second_refs[node_id]
        and first_refs[node_id].fold is None
        and first_refs[node_id].stage in runtime._SHARED_RECEIPT_STAGES
        for node_id in shared_node_ids
    )
    assert not (first_refs.keys() & second_refs.keys()) - shared_node_ids
    assert tuple(gate.gate for gate in result.gates) == (
        "summary",
        "reproducibility",
        "readiness",
        "acceptance",
    )
    for index, gate in enumerate(result.gates):
        assert gate.identity == runtime.compute_successor_gate_identity(
            gate=gate.gate,
            folds=result.folds,
            prior_gates=result.gates[:index],
        )
    assert len(result.attestation.folds) == 2
    for binding, fold_request, execution in zip(
        result.attestation.folds,
        request.folds,
        result.folds,
        strict=True,
    ):
        assert binding.fold == execution.fold == fold_request.fold
        assert binding.config_raw_sha256 == fold_request.config.config.raw_config_sha256
        assert binding.config_full_sha256 == fold_request.config.config.full_config_sha256
        assert binding.g1_release_id == fold_request.release.manifest.release_id
        assert (
            binding.g1_release_manifest_sha256
            == fold_request.release.manifest_sha256
        )
    assert result.attestation.two_fold_identity == runtime.two_fold_identity(request)
    assert not tuple(request.controlled_output_root.glob(".completion.json.*.tmp"))


def test_same_config_distinct_paths_with_equal_bytes_are_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path, same_config=True)
    _install_fixture_verifiers(
        monkeypatch,
        configs,
        releases,
        boundary.public_apis,
        boundary,
    )

    result = _run(request, boundary)

    assert tuple(item.config.relative_path for item in request.folds) == (
        PurePosixPath("configs/fold_001.toml"),
        PurePosixPath("configs/fold_002.toml"),
    )
    assert request.folds[0].config.config == request.folds[1].config.config
    assert result.folds[0].config_raw_sha256 == result.folds[1].config_raw_sha256
    assert result.folds[0].config_full_sha256 == result.folds[1].config_full_sha256


def test_same_config_replay_is_exact_and_second_fold_tamper_fails_fresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(
        tmp_path, same_config=True, same_physical=True
    )
    _install_fixture_verifiers(
        monkeypatch,
        configs,
        releases,
        boundary.public_apis,
        boundary,
    )

    first = _run(request, boundary)
    first_public_api_calls = tuple(boundary.public_api_calls)
    replay = _run(request, boundary)

    assert replay.reused is True
    assert replay.terminal_path == first.terminal_path
    assert replay.attestation == first.attestation
    assert replay.attestation.two_fold_identity == first.attestation.two_fold_identity
    assert (
        tuple(boundary.public_api_calls[: len(first_public_api_calls)])
        == first_public_api_calls
    )
    replay_suffix = tuple(boundary.public_api_calls[len(first_public_api_calls) :])
    assert replay_suffix == (
        "summary-public-verify",
        "reproducibility-public-verify",
        "readiness-public-verify",
        "acceptance-public-verify",
    )
    assert not any(
        call in runtime._UPSTREAM_WAVES
        or call.endswith("-run-plan")
        or call.endswith("-public-run")
        or call == "publication"
        for call in replay_suffix
    )
    calls_after_replay = len(boundary.public_api_calls)

    config_path = request.project_root / "configs" / "shared.toml"
    original = config_path.read_bytes()
    config_path.write_bytes(original + b"\ndrift")
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        _run(request, boundary)
    assert error.value.code == "SUCCESSOR_INPUT_INVALID"
    assert len(boundary.public_api_calls) == calls_after_replay


def test_same_physical_second_fold_drift_fails_before_stage_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(
        tmp_path, same_config=True, same_physical=True
    )
    shared_path = (request.project_root / "configs" / "shared.toml").resolve()
    original = shared_path.read_bytes()
    load_calls: list[Path] = []
    runtime_read_calls: list[Path] = []
    release_calls: list[str] = []

    def tamper_after_first_load(path: Path, count: int) -> None:
        if count == 1:
            path.write_bytes(original + b"\ndrift")

    _install_fixture_verifiers(
        monkeypatch,
        configs,
        releases,
        boundary.public_apis,
        boundary,
        load_calls=load_calls,
        runtime_read_calls=runtime_read_calls,
        release_calls=release_calls,
        after_load=tamper_after_first_load,
    )

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        _run(request, boundary)

    assert error.value.code == "SUCCESSOR_INPUT_INVALID"
    assert runtime_read_calls == [shared_path, shared_path]
    assert load_calls == [shared_path]
    assert len(release_calls) == 1
    assert boundary.public_api_calls == []
    assert not (request.controlled_output_root / runtime.TERMINAL_FILENAME).exists()
    assert not (request.controlled_output_root / "receipts").exists()


def test_same_config_duplicate_release_identity_fails_before_stage_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(
        tmp_path, same_config=True, same_physical=True
    )
    first_release = request.folds[0].release
    alias = _release_alias(
        first_release,
        root=request.folds[1].release.release.root,
    )
    folds = (
        request.folds[0],
        replace(request.folds[1], release=alias),
    )
    request = replace(request, folds=folds)
    release_overrides = {
        id(first_release.release): first_release,
        id(alias.release): alias,
    }
    _install_fixture_verifiers(
        monkeypatch,
        configs,
        releases,
        boundary.public_apis,
        boundary,
        release_overrides=release_overrides,
    )

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        _run(request, boundary)

    assert error.value.code == "SUCCESSOR_INPUT_INVALID"
    assert boundary.public_api_calls == []
    assert not (request.controlled_output_root / runtime.TERMINAL_FILENAME).exists()
    assert not (request.controlled_output_root / "receipts").exists()


def test_terminal_rejects_receipt_bytes_and_unknown_tree_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)
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
        monkeypatch, configs_2, releases_2, boundary_2.public_apis, boundary_2
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
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)

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
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)
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
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)
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


def test_real_waves_call_builders_once_with_mapped_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)

    assert "labels" not in boundary.public_apis.run_plan_builders
    assert "features" not in boundary.public_apis.run_plan_builders
    assert "folds" not in boundary.public_apis.run_plan_builders
    assert (
        boundary.public_apis.run_plan_builders["experiment-artifacts"]
        is not boundary.public_apis.run_plan_builders["label-reconciliation"]
    )
    assert (
        boundary.public_apis.run_plan_builders["experiment-artifacts"]
        is not boundary.public_apis.run_plan_builders["work"]
    )

    adapter = _adapter(boundary)
    first = adapter.run_fold(
        request=request.folds[0],
        context=runtime.SuccessorStageContext(
            request=request,
            fold=request.folds[0].fold,
        ),
        resume=True,
    )
    second = adapter.run_fold(
        request=request.folds[1],
        context=runtime.SuccessorStageContext(
            request=request,
            fold=request.folds[1].fold,
        ),
        resume=True,
    )

    assert boundary.builder_call_records == [
        ("experiment-artifacts", "experiment-artifacts"),
        ("label-reconciliation", "label-reconciliation"),
        ("work", "work"),
    ]
    assert {
        (ref.stage, ref.horizon)
        for ref in first.receipts
        if ref.stage in {"labels", "folds"}
    } == {("folds", None), ("labels", 5), ("labels", 10)}
    assert {
        (ref.stage, ref.fold, ref.horizon)
        for ref in first.receipts
        if ref.stage == "features"
    } == {("features", "fold_001", None)}
    assert {
        (ref.stage, ref.fold, ref.horizon)
        for ref in second.receipts
        if ref.stage == "features"
    } == {("features", "fold_002", None)}
    assert all(
        ref.stage != "labels" or ref.fold is None
        for ref in (*first.receipts, *second.receipts)
    )


def test_wave_cache_rejects_cross_request_poison_and_resume_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_a, boundary, configs, releases = _request(tmp_path)
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)
    adapter = _adapter(boundary)

    adapter.run_fold(
        request=request_a.folds[0],
        context=runtime.SuccessorStageContext(
            request=request_a, fold=request_a.folds[0].fold,
        ),
        resume=True,
    )

    # resume drift on the second fold of the same request
    with pytest.raises(runtime.SuccessorRuntimeError) as resume_error:
        adapter.run_fold(
            request=request_a.folds[1],
            context=runtime.SuccessorStageContext(
                request=request_a, fold=request_a.folds[1].fold,
            ),
            resume=False,
        )
    assert resume_error.value.code == "SUCCESSOR_INPUT_INVALID"

    # Fresh adapter for happy-path second fold, then poison with request B
    adapter_ok = _adapter(boundary)
    boundary.builder_call_records.clear()
    boundary._stub_wave_cache.clear()
    adapter_ok.run_fold(
        request=request_a.folds[0],
        context=runtime.SuccessorStageContext(
            request=request_a, fold=request_a.folds[0].fold,
        ),
        resume=True,
    )
    adapter_ok.run_fold(
        request=request_a.folds[1],
        context=runtime.SuccessorStageContext(
            request=request_a, fold=request_a.folds[1].fold,
        ),
        resume=True,
    )
    assert boundary.builder_call_records == [
        ("experiment-artifacts", "experiment-artifacts"),
        ("label-reconciliation", "label-reconciliation"),
        ("work", "work"),
    ]

    request_b, boundary_b, configs_b, releases_b = _request(tmp_path / "poison-b")
    _install_fixture_verifiers(monkeypatch, configs_b, releases_b, boundary_b.public_apis, boundary_b)
    with pytest.raises(runtime.SuccessorRuntimeError) as poison_error:
        adapter_ok.run_fold(
            request=request_b.folds[0],
            context=runtime.SuccessorStageContext(
                request=request_b, fold=request_b.folds[0].fold,
            ),
            resume=True,
        )
    assert poison_error.value.code == "SUCCESSOR_INPUT_INVALID"


def test_wave_cache_rejects_duplicate_and_third_fold_consumption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)
    adapter = _adapter(boundary)

    adapter.run_fold(
        request=request.folds[0],
        context=runtime.SuccessorStageContext(
            request=request, fold=request.folds[0].fold,
        ),
        resume=True,
    )
    with pytest.raises(runtime.SuccessorRuntimeError) as duplicate_error:
        adapter.run_fold(
            request=request.folds[0],
            context=runtime.SuccessorStageContext(
                request=request, fold=request.folds[0].fold,
            ),
            resume=True,
        )
    assert duplicate_error.value.code == "SUCCESSOR_STAGE_INVALID"

    adapter.run_fold(
        request=request.folds[1],
        context=runtime.SuccessorStageContext(
            request=request, fold=request.folds[1].fold,
        ),
        resume=True,
    )
    with pytest.raises(runtime.SuccessorRuntimeError) as third_error:
        adapter.run_fold(
            request=request.folds[0],
            context=runtime.SuccessorStageContext(
                request=request, fold=request.folds[0].fold,
            ),
            resume=True,
        )
    assert third_error.value.code == "SUCCESSOR_STAGE_INVALID"
    assert boundary.builder_call_records == [
        ("experiment-artifacts", "experiment-artifacts"),
        ("label-reconciliation", "label-reconciliation"),
        ("work", "work"),
    ]


def test_scope_key_drift_cannot_join_work_to_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    boundary.drift_work_scope = True
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        _run(request, boundary)

    assert error.value.code == "SUCCESSOR_STAGE_INVALID"
    assert not (request.controlled_output_root / runtime.TERMINAL_FILENAME).exists()


def test_legacy_join_hash_masquerading_as_comparison_key_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    boundary.masquerade_join_scope = True
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        _run(request, boundary)

    assert error.value.code == "SUCCESSOR_TERMINAL_INVALID"
    assert not (request.controlled_output_root / runtime.TERMINAL_FILENAME).exists()


def test_readiness_extra_fold_bound_receipt_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    boundary.collide_readiness_keys = True
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        _run(request, boundary)

    assert error.value.code == "SUCCESSOR_GATE_FAILED"
    assert not (request.controlled_output_root / runtime.TERMINAL_FILENAME).exists()


def test_acceptance_physical_key_may_differ_from_gate_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)

    result = _run(request, boundary)
    acceptance = next(item for item in result.gates if item.gate == "acceptance")
    assert len(acceptance.receipt_refs) == 1
    assert acceptance.receipt_refs[0].scope_key == _hex("acceptance-physical-key")
    assert acceptance.receipt_refs[0].scope_key != acceptance.identity


def test_acceptance_project_alias_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    boundary.force_acceptance_project_alias = True
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        _run(request, boundary)

    assert error.value.code == "SUCCESSOR_TERMINAL_INVALID"
    assert not (request.controlled_output_root / runtime.TERMINAL_FILENAME).exists()


def test_non_acceptance_g8_alias_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    boundary.force_summary_g8_alias = True
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        _run(request, boundary)

    assert error.value.code == "SUCCESSOR_TERMINAL_INVALID"
    assert not (request.controlled_output_root / runtime.TERMINAL_FILENAME).exists()


def test_divergent_fold_stage_roots_fail_before_stage_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    divergent = object.__new__(LoadedM3Config)
    for name in (
        "document",
        "config_version",
        "full_config_sha256",
        "g1_config_sha256",
        "snapshot_config_sha256",
        "provider_config_sha256",
        "scientific_config_sha256",
        "provider_validation_config_sha256",
        "label_reconciliation_config_sha256",
        "acceptance_config_sha256",
        "canonical_tracking_uri",
        "tracking_target_key",
        "raw_config_sha256",
    ):
        object.__setattr__(divergent, name, getattr(request.folds[1].config.config, name))
    object.__setattr__(
        divergent,
        "document",
        {"tracking": {"artifact_root": "output/other-stage"}},
    )
    (request.project_root / "output" / "other-stage").mkdir(parents=True)
    configs[request.project_root.joinpath("configs", "fold_002.toml").resolve()] = divergent
    folds = (
        request.folds[0],
        replace(
            request.folds[1],
            config=replace(request.folds[1].config, config=divergent),
        ),
    )
    request = replace(request, folds=folds)
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        _run(request, boundary)

    assert error.value.code == "SUCCESSOR_INPUT_INVALID"
    assert not (request.controlled_output_root / runtime.TERMINAL_FILENAME).exists()


def test_controlled_root_mismatch_with_canonical_g8_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    other = request.project_root / "output" / "controlled-other"
    other.mkdir(parents=True)
    request = replace(request, controlled_output_root=other)
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        _run(request, boundary)

    assert error.value.code == "SUCCESSOR_INPUT_INVALID"
    assert not (other / runtime.TERMINAL_FILENAME).exists()


def test_distinct_node_same_receipt_path_and_bytes_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    boundary.alias_physical_receipt = True
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        _run(request, boundary)

    assert error.value.code == "SUCCESSOR_TERMINAL_INVALID"
    assert not (request.controlled_output_root / runtime.TERMINAL_FILENAME).exists()


def test_acceptance_mixed_project_g8_alias_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    boundary.force_acceptance_mixed_alias = True
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        _run(request, boundary)

    assert error.value.code == "SUCCESSOR_TERMINAL_INVALID"
    assert not (request.controlled_output_root / runtime.TERMINAL_FILENAME).exists()


def test_acceptance_identity_masquerade_fails_receipt_verify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, boundary, configs, releases = _request(tmp_path)
    boundary.force_acceptance_identity_masquerade = True
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)

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
    _install_fixture_verifiers(monkeypatch, configs, releases, boundary.public_apis, boundary)

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
