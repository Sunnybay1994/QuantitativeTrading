"""Static-contract tests for the package-owned successor boundary."""

from __future__ import annotations

import hashlib
import stat
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import pytest

import quant.research.m3.successor_runtime as runtime
from quant.research.m3.run_state import publish_stage_receipt
from quant.research.m3.successor_runtime import (
    FoldExecution,
    GateExecution,
    HORIZONS,
    StageReceiptRef,
    SuccessorProductionDependencies,
    SuccessorRuntimeError,
    SuccessorRuntimeIdentity,
    WorkIdentity,
    _lookup_refs,
    _unique_refs,
    _validate_gate_execution,
)


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _receipt_ref(
    *, node_id: str, stage: str, fold: str | None, horizon: int | None
) -> StageReceiptRef:
    return StageReceiptRef(
        node_id=node_id,
        stage=stage,
        scope="EXPERIMENT" if stage == "research-summary" else "WORK",
        scope_key=_hex(node_id),
        relative_path=f"receipts/{stage}/{node_id}.json",
        sha256=_hex(f"receipt:{node_id}"),
        fold=fold,
        horizon=horizon,
    )


class _FakeDirEntry:
    def __init__(self, path: Path, info: SimpleNamespace) -> None:
        self.name = path.name
        self.path = str(path)
        self._info = info

    def stat(self, *, follow_symlinks: bool) -> SimpleNamespace:
        assert follow_symlinks is False
        return self._info


def _tree_stat(*, mode: int, nlink: int, file_attributes: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        st_mode=mode,
        st_nlink=nlink,
        st_file_attributes=file_attributes,
    )


def _fold_execution(
    *, fold: str, refs: tuple[StageReceiptRef, ...]
) -> FoldExecution:
    return FoldExecution(
        fold=fold,
        config_raw_sha256=_hex(f"raw:{fold}"),
        config_full_sha256=_hex(f"full:{fold}"),
        g1_release_id=_hex(f"release:{fold}"),
        g1_release_manifest_sha256=_hex(f"manifest:{fold}"),
        snapshot_id=_hex(f"snapshot:{fold}"),
        experiment_key=_hex(f"experiment:{fold}"),
        work_identities=tuple(
            WorkIdentity(
                fold=fold,
                horizon=horizon,
                work_key=_hex(f"work:{fold}:{horizon}"),
            )
            for horizon in HORIZONS
        ),
        receipts=tuple(sorted(refs, key=lambda item: item.node_id)),
    )


def _gate_execution(
    *,
    gate: Literal["summary", "reproducibility", "readiness", "acceptance"],
    ref: StageReceiptRef,
) -> GateExecution:
    return GateExecution(
        gate=gate,
        status="PASS",
        identity=_hex(f"gate:{gate}"),
        receipt_refs=(ref,),
    )


def _assert_lookup_refs_rejected(
    executions: tuple[FoldExecution, ...],
    known: tuple[GateExecution, ...],
    gate: GateExecution,
) -> None:
    with pytest.raises(SuccessorRuntimeError) as error:
        _lookup_refs(executions, known, gate)
    assert error.value.code == "SUCCESSOR_GATE_FAILED"


def test_summary_receipt_can_bind_horizon_without_fold() -> None:
    ref = _receipt_ref(
        node_id="summary-h005",
        stage="research-summary",
        fold=None,
        horizon=5,
    )
    gate = GateExecution(
        gate="summary",
        status="PASS",
        identity=_hex("summary"),
        receipt_refs=(ref,),
    )

    assert gate.receipt_node_ids == ("summary-h005",)
    assert gate.receipt_refs[0] == ref


def test_two_fold_work_identity_is_exactly_h5_h10() -> None:
    identities = tuple(
        WorkIdentity(
            fold="fold_001",
            horizon=horizon,
            work_key=_hex(f"fold_001:{horizon}"),
        )
        for horizon in HORIZONS
    )

    assert tuple(item.horizon for item in identities) == (5, 10)
    with pytest.raises(ValueError):
        WorkIdentity(
            fold="fold_001",
            horizon=20,
            work_key=_hex("fold_001:20"),
        )


def test_gate_rejects_id_only_or_unsorted_receipt_contract() -> None:
    first = _receipt_ref(
        node_id="summary-a",
        stage="research-summary",
        fold=None,
        horizon=5,
    )
    second = _receipt_ref(
        node_id="summary-b",
        stage="research-summary",
        fold=None,
        horizon=10,
    )

    with pytest.raises(ValueError):
        GateExecution(
            gate="summary",
            status="PASS",
            identity=_hex("summary"),
            receipt_refs=("summary-a", "summary-b"),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        GateExecution(
            gate="summary",
            status="PASS",
            identity=_hex("summary"),
            receipt_refs=(second, first),
        )


def test_runtime_identity_and_error_surface_are_stable() -> None:
    with pytest.raises(ValueError):
        SuccessorRuntimeIdentity(
            code_version="code\nversion",
            dependency_fingerprint_sha256=_hex("dependency"),
            provider_runtime_fingerprint_sha256=_hex("provider"),
        )

    error = SuccessorRuntimeError("SUCCESSOR_INPUT_INVALID")
    assert error.code == "SUCCESSOR_INPUT_INVALID"
    with pytest.raises(ValueError):
        SuccessorRuntimeError("UNKNOWN")


def test_platform_regular_file_link_count_and_link_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    monkeypatch.setattr(runtime, "_read_regular_file", lambda _path: b"payload")

    def walk(info: SimpleNamespace) -> tuple[tuple[str, str, int, str], ...]:
        entry = _FakeDirEntry(root / "candidate", info)
        monkeypatch.setattr(runtime.os, "scandir", lambda _directory: [entry])
        return runtime._walk_controlled_tree(root)

    regular_mode = stat.S_IFREG | 0o600
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    assert walk(_tree_stat(mode=regular_mode, nlink=0))
    assert walk(_tree_stat(mode=regular_mode, nlink=1))
    with pytest.raises(ValueError):
        walk(_tree_stat(mode=regular_mode, nlink=2))

    monkeypatch.setattr(runtime.sys, "platform", "linux")
    with pytest.raises(ValueError):
        walk(_tree_stat(mode=regular_mode, nlink=0))
    assert walk(_tree_stat(mode=regular_mode, nlink=1))
    with pytest.raises(ValueError):
        walk(_tree_stat(mode=regular_mode, nlink=2))

    with pytest.raises(ValueError):
        walk(_tree_stat(mode=stat.S_IFLNK | 0o777, nlink=0))
    with pytest.raises(ValueError):
        walk(_tree_stat(mode=regular_mode, nlink=0, file_attributes=0x400))


def test_production_dependencies_fail_closed_when_any_boundary_is_missing() -> None:
    with pytest.raises(SuccessorRuntimeError) as error:
        SuccessorProductionDependencies(
            stage_runner_factory=None,
            run_upstream_wave=None,
            run_formal_stage=None,
            verify_fold=None,
            run_summary=None,
            verify_summary=None,
            run_reproducibility=None,
            verify_reproducibility=None,
            run_readiness=None,
            verify_readiness=None,
            run_acceptance=None,
            verify_acceptance=None,
            verify_gate=None,
        )

    assert error.value.code == "SUCCESSOR_INPUT_INVALID"


def test_each_production_dependency_none_fails_closed() -> None:
    def callback(**_kwargs: object) -> object:
        return object()

    dependencies = SuccessorProductionDependencies(
        stage_runner_factory=runtime.make_project_stage_runner,
        run_upstream_wave=callback,
        run_formal_stage=callback,
        verify_fold=callback,
        run_summary=callback,
        verify_summary=callback,
        run_reproducibility=callback,
        verify_reproducibility=callback,
        run_readiness=callback,
        verify_readiness=callback,
        run_acceptance=callback,
        verify_acceptance=callback,
        verify_gate=callback,
    )
    for field in (
        "stage_runner_factory",
        "run_upstream_wave",
        "run_formal_stage",
        "verify_fold",
        "run_summary",
        "verify_summary",
        "run_reproducibility",
        "verify_reproducibility",
        "run_readiness",
        "verify_readiness",
        "run_acceptance",
        "verify_acceptance",
        "verify_gate",
    ):
        with pytest.raises(SuccessorRuntimeError) as error:
            replace(dependencies, **{field: None})
        assert error.value.code == "SUCCESSOR_INPUT_INVALID"


def test_pseudo_single_transition_builder_keys_are_rejected() -> None:
    def marker(**_kwargs: object) -> object:
        return object()

    builders = {
        name: marker
        for name in (
            "snapshot",
            "provider",
            "provider-validation",
            "experiment-identity",
            "experiment-artifacts",
            "label-reconciliation",
            "work",
            "summary",
            "labels",
        )
    }
    with pytest.raises(ValueError):
        runtime.SuccessorPublicApiBundle(
            stage_runner_type=object,
            run_plan_builders=builders,
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


def test_work_wave_filter_keeps_only_fold_owned_receipts() -> None:
    owned = _receipt_ref(
        node_id="features-fold_001",
        stage="features",
        fold="fold_001",
        horizon=None,
    )
    foreign = _receipt_ref(
        node_id="features-fold_002",
        stage="features",
        fold="fold_002",
        horizon=None,
    )
    shared = _receipt_ref(
        node_id="labels-h5",
        stage="labels",
        fold=None,
        horizon=5,
    )

    assert runtime._work_receipt_belongs_to_fold(owned, "fold_001")
    assert not runtime._work_receipt_belongs_to_fold(foreign, "fold_001")
    assert not runtime._work_receipt_belongs_to_fold(shared, "fold_001")


def test_canonical_bytes_dataclass_matches_asdict_form() -> None:
    identity = SuccessorRuntimeIdentity(
        code_version="successor-test-v1",
        dependency_fingerprint_sha256=_hex("dependency"),
        provider_runtime_fingerprint_sha256=_hex("provider"),
    )

    assert runtime._canonical_bytes(identity) == runtime._canonical_bytes(
        asdict(identity)
    )


def test_lookup_refs_consumes_fold_and_prior_gate_ownership() -> None:
    ref = _receipt_ref(
        node_id="owned-by-fold",
        stage="alignment",
        fold="fold_001",
        horizon=5,
    )
    execution = FoldExecution(
        fold="fold_001",
        config_raw_sha256=_hex("raw"),
        config_full_sha256=_hex("full"),
        g1_release_id=_hex("release"),
        g1_release_manifest_sha256=_hex("manifest"),
        snapshot_id=_hex("snapshot"),
        experiment_key=_hex("experiment"),
        work_identities=(
            WorkIdentity("fold_001", 5, _hex("work-5")),
            WorkIdentity("fold_001", 10, _hex("work-10")),
        ),
        receipts=(ref,),
    )
    gate = GateExecution(
        gate="acceptance",
        status="PASS",
        identity=_hex("acceptance"),
        receipt_refs=(ref,),
    )

    with pytest.raises(SuccessorRuntimeError) as error:
        _lookup_refs((execution,), (), gate)
    assert error.value.code == "SUCCESSOR_GATE_FAILED"

    prior = GateExecution(
        gate="summary",
        status="PASS",
        identity=_hex("summary"),
        receipt_refs=(ref,),
    )
    with pytest.raises(SuccessorRuntimeError) as error:
        _lookup_refs((), (prior,), gate)
    assert error.value.code == "SUCCESSOR_GATE_FAILED"


def test_lookup_refs_allows_exact_shared_receipt_between_two_folds() -> None:
    shared = _receipt_ref(
        node_id="shared-experiment",
        stage="experiment-identity",
        fold=None,
        horizon=None,
    )
    gate_ref = _receipt_ref(
        node_id="summary-gate",
        stage="research-summary",
        fold=None,
        horizon=5,
    )

    assert _lookup_refs(
        (
            _fold_execution(fold="fold_001", refs=(shared,)),
            _fold_execution(fold="fold_002", refs=(shared,)),
        ),
        (),
        _gate_execution(gate="summary", ref=gate_ref),
    ) == (gate_ref,)


def test_lookup_refs_rejects_same_node_with_different_ref() -> None:
    first = _receipt_ref(
        node_id="shared-different-ref",
        stage="experiment-identity",
        fold=None,
        horizon=None,
    )
    second = replace(first, sha256=_hex("different-bytes"))
    gate_ref = _receipt_ref(
        node_id="gate-different-ref",
        stage="research-summary",
        fold=None,
        horizon=5,
    )

    _assert_lookup_refs_rejected(
        (
            _fold_execution(fold="fold_001", refs=(first,)),
            _fold_execution(fold="fold_002", refs=(second,)),
        ),
        (),
        _gate_execution(gate="summary", ref=gate_ref),
    )


def test_lookup_refs_rejects_nonshared_stage_reuse_between_folds() -> None:
    ref = _receipt_ref(
        node_id="nonshared-stage",
        stage="alignment",
        fold=None,
        horizon=5,
    )
    gate_ref = _receipt_ref(
        node_id="gate-nonshared",
        stage="research-summary",
        fold=None,
        horizon=5,
    )

    _assert_lookup_refs_rejected(
        (
            _fold_execution(fold="fold_001", refs=(ref,)),
            _fold_execution(fold="fold_002", refs=(ref,)),
        ),
        (),
        _gate_execution(gate="summary", ref=gate_ref),
    )


def test_lookup_refs_rejects_same_fold_reuse() -> None:
    ref = _receipt_ref(
        node_id="same-fold",
        stage="experiment-identity",
        fold=None,
        horizon=None,
    )
    gate_ref = _receipt_ref(
        node_id="gate-same-fold",
        stage="research-summary",
        fold=None,
        horizon=5,
    )

    _assert_lookup_refs_rejected(
        (
            _fold_execution(fold="fold_001", refs=(ref,)),
            _fold_execution(fold="fold_001", refs=(ref,)),
        ),
        (),
        _gate_execution(gate="summary", ref=gate_ref),
    )


def test_lookup_refs_rejects_fold_gate_reuse() -> None:
    ref = _receipt_ref(
        node_id="fold-gate",
        stage="experiment-identity",
        fold=None,
        horizon=None,
    )

    _assert_lookup_refs_rejected(
        (_fold_execution(fold="fold_001", refs=(ref,)),),
        (),
        _gate_execution(gate="summary", ref=ref),
    )


def test_lookup_refs_rejects_prior_gate_current_gate_reuse() -> None:
    ref = _receipt_ref(
        node_id="prior-current-gate",
        stage="research-summary",
        fold=None,
        horizon=5,
    )

    _assert_lookup_refs_rejected(
        (),
        (_gate_execution(gate="summary", ref=ref),),
        _gate_execution(gate="reproducibility", ref=ref),
    )


def test_lookup_refs_rejects_gate_gate_reuse() -> None:
    ref = _receipt_ref(
        node_id="gate-gate",
        stage="research-summary",
        fold=None,
        horizon=5,
    )
    current_ref = _receipt_ref(
        node_id="current-gate",
        stage="acceptance",
        fold=None,
        horizon=None,
    )

    _assert_lookup_refs_rejected(
        (),
        (
            _gate_execution(gate="summary", ref=ref),
            _gate_execution(gate="reproducibility", ref=ref),
        ),
        _gate_execution(gate="acceptance", ref=current_ref),
    )


def test_unique_refs_rejects_distinct_node_physical_and_semantic_alias() -> None:
    first = StageReceiptRef(
        node_id="alias-a",
        stage="alignment",
        scope="WORK",
        scope_key=_hex("same-scope"),
        relative_path="receipts/alignment/shared.json",
        sha256=_hex("same-bytes"),
        fold="fold_001",
        horizon=5,
    )
    second = StageReceiptRef(
        node_id="alias-b",
        stage="alignment",
        scope="WORK",
        scope_key=_hex("same-scope"),
        relative_path="receipts/alignment/shared.json",
        sha256=_hex("same-bytes"),
        fold="fold_001",
        horizon=5,
    )

    with pytest.raises(SuccessorRuntimeError) as error:
        _unique_refs((first, second))
    assert error.value.code == "SUCCESSOR_TERMINAL_INVALID"


def _two_fold_executions() -> tuple[FoldExecution, ...]:
    shared_experiment = _hex("shared-experiment")
    return (
        FoldExecution(
            fold="fold_001",
            config_raw_sha256=_hex("raw-a"),
            config_full_sha256=_hex("full-a"),
            g1_release_id=_hex("release-a"),
            g1_release_manifest_sha256=_hex("manifest-a"),
            snapshot_id=_hex("snapshot-a"),
            experiment_key=shared_experiment,
            work_identities=(
                WorkIdentity("fold_001", 5, _hex("work-a-5")),
                WorkIdentity("fold_001", 10, _hex("work-a-10")),
            ),
            receipts=(
                _receipt_ref(
                    node_id="snap-a",
                    stage="snapshot",
                    fold=None,
                    horizon=None,
                ),
            ),
        ),
        FoldExecution(
            fold="fold_002",
            config_raw_sha256=_hex("raw-b"),
            config_full_sha256=_hex("full-b"),
            g1_release_id=_hex("release-b"),
            g1_release_manifest_sha256=_hex("manifest-b"),
            snapshot_id=_hex("snapshot-b"),
            experiment_key=shared_experiment,
            work_identities=(
                WorkIdentity("fold_002", 5, _hex("work-b-5")),
                WorkIdentity("fold_002", 10, _hex("work-b-10")),
            ),
            receipts=(
                _receipt_ref(
                    node_id="snap-b",
                    stage="snapshot",
                    fold=None,
                    horizon=None,
                ),
            ),
        ),
    )


def test_validate_gate_accepts_acceptance_key_distinct_from_identity() -> None:
    folds = _two_fold_executions()
    prior = (
        GateExecution(
            gate="summary",
            status="PASS",
            identity=_hex("summary-id"),
            receipt_refs=tuple(
                sorted(
                    (
                        StageReceiptRef(
                            node_id="summary-h5",
                            stage="research-summary",
                            scope="EXPERIMENT",
                            scope_key=folds[0].experiment_key,
                            relative_path="receipts/research-summary/summary-h5.json",
                            sha256=_hex("summary-h5"),
                            fold=None,
                            horizon=5,
                        ),
                        StageReceiptRef(
                            node_id="summary-h10",
                            stage="research-summary",
                            scope="EXPERIMENT",
                            scope_key=folds[0].experiment_key,
                            relative_path="receipts/research-summary/summary-h10.json",
                            sha256=_hex("summary-h10"),
                            fold=None,
                            horizon=10,
                        ),
                    ),
                    key=lambda item: item.node_id,
                )
            ),
        ),
        GateExecution(
            gate="reproducibility",
            status="PASS",
            identity=_hex("repro-id"),
            receipt_refs=tuple(
                sorted(
                    (
                        StageReceiptRef(
                            node_id=f"repro-{fold}-h{horizon}",
                            stage="reproducibility",
                            scope="REPRO",
                            scope_key=_hex(f"comparison:{fold}:{horizon}"),
                            relative_path=(
                                f"receipts/reproducibility/repro-{fold}-h{horizon}.json"
                            ),
                            sha256=_hex(f"repro:{fold}:{horizon}"),
                            fold=fold,
                            horizon=horizon,
                        )
                        for fold in ("fold_001", "fold_002")
                        for horizon in HORIZONS
                    ),
                    key=lambda item: item.node_id,
                )
            ),
        ),
        GateExecution(
            gate="readiness",
            status="PASS",
            identity=_hex("readiness-id"),
            receipt_refs=tuple(
                sorted(
                    (
                        StageReceiptRef(
                            node_id="readiness-fold_001",
                            stage="readiness-evidence",
                            scope="ACCEPTANCE",
                            scope_key=_hex("readiness:fold_001"),
                            relative_path=(
                                "receipts/readiness-evidence/readiness-fold_001.json"
                            ),
                            sha256=_hex("readiness-a"),
                            fold="fold_001",
                            horizon=None,
                        ),
                        StageReceiptRef(
                            node_id="readiness-fold_002",
                            stage="readiness-evidence",
                            scope="ACCEPTANCE",
                            scope_key=_hex("readiness:fold_002"),
                            relative_path=(
                                "receipts/readiness-evidence/readiness-fold_002.json"
                            ),
                            sha256=_hex("readiness-b"),
                            fold="fold_002",
                            horizon=None,
                        ),
                    ),
                    key=lambda item: item.node_id,
                )
            ),
        ),
    )
    identity = runtime.compute_successor_gate_identity(
        gate="acceptance",
        folds=folds,
        prior_gates=prior,
    )
    physical = _hex("acceptance-physical")
    assert physical != identity
    gate = GateExecution(
        gate="acceptance",
        status="PASS",
        identity=identity,
        receipt_refs=(
            StageReceiptRef(
                node_id="acceptance",
                stage="acceptance",
                scope="ACCEPTANCE",
                scope_key=physical,
                relative_path="receipts/acceptance/acceptance.json",
                sha256=_hex("acceptance-bytes"),
                fold=None,
                horizon=None,
            ),
        ),
    )
    _validate_gate_execution("acceptance", gate, executions=folds, known=prior)


def test_validate_gate_rejects_readiness_key_collision() -> None:
    folds = _two_fold_executions()
    collided = _hex("readiness:same")
    gate = GateExecution(
        gate="readiness",
        status="PASS",
        identity=runtime.compute_successor_gate_identity(
            gate="readiness",
            folds=folds,
            prior_gates=(),
        ),
        receipt_refs=(
            StageReceiptRef(
                node_id="readiness-fold_001",
                stage="readiness-evidence",
                scope="ACCEPTANCE",
                scope_key=collided,
                relative_path="receipts/readiness-evidence/a.json",
                sha256=_hex("readiness-a"),
                fold="fold_001",
                horizon=None,
            ),
            StageReceiptRef(
                node_id="readiness-fold_002",
                stage="readiness-evidence",
                scope="ACCEPTANCE",
                scope_key=collided,
                relative_path="receipts/readiness-evidence/b.json",
                sha256=_hex("readiness-b"),
                fold="fold_002",
                horizon=None,
            ),
        ),
    )
    with pytest.raises(SuccessorRuntimeError) as error:
        _validate_gate_execution("readiness", gate, executions=folds, known=())
    assert error.value.code == "SUCCESSOR_GATE_FAILED"


def test_validate_gate_rejects_duplicate_reproducibility_comparison_keys() -> None:
    folds = _two_fold_executions()
    shared = _hex("comparison:shared")
    refs = [
        StageReceiptRef(
            node_id=f"repro-{fold}-h{horizon}",
            stage="reproducibility",
            scope="REPRO",
            scope_key=shared,
            relative_path=f"receipts/reproducibility/{fold}-{horizon}.json",
            sha256=_hex(f"repro:{fold}:{horizon}"),
            fold=fold,
            horizon=horizon,
        )
        for fold in ("fold_001", "fold_002")
        for horizon in HORIZONS
    ]
    gate = GateExecution(
        gate="reproducibility",
        status="PASS",
        identity=runtime.compute_successor_gate_identity(
            gate="reproducibility",
            folds=folds,
            prior_gates=(),
        ),
        receipt_refs=tuple(sorted(refs, key=lambda item: item.node_id)),
    )
    with pytest.raises(SuccessorRuntimeError) as error:
        _validate_gate_execution("reproducibility", gate, executions=folds, known=())
    assert error.value.code == "SUCCESSOR_GATE_FAILED"


def test_compute_successor_gate_scope_key_is_not_exported() -> None:
    assert not hasattr(runtime, "compute_successor_gate_scope_key")
    assert "compute_successor_gate_scope_key" not in runtime.__all__


def test_artifact_roots_for_receipt_stage_are_exclusive() -> None:
    project = Path("C:/project")
    stage = Path("C:/project/output/stage")
    acceptance_roots = runtime._artifact_roots_for_receipt_stage(
        stage="acceptance",
        project_root=project,
        canonical_stage_root=stage,
    )
    other_roots = runtime._artifact_roots_for_receipt_stage(
        stage="reproducibility",
        project_root=project,
        canonical_stage_root=stage,
    )
    assert dict(acceptance_roots) == {"G8": stage}
    assert list(acceptance_roots.keys()) == ["G8"]
    assert dict(other_roots) == {"PROJECT": project}
    assert list(other_roots.keys()) == ["PROJECT"]


def _readiness_gate(
    *,
    folds: tuple[FoldExecution, ...],
    refs: tuple[StageReceiptRef, ...],
) -> GateExecution:
    return GateExecution(
        gate="readiness",
        status="PASS",
        identity=runtime.compute_successor_gate_identity(
            gate="readiness",
            folds=folds,
            prior_gates=(),
        ),
        receipt_refs=tuple(sorted(refs, key=lambda item: item.node_id)),
    )


def test_validate_gate_rejects_readiness_both_refs_same_fold() -> None:
    folds = _two_fold_executions()
    gate = _readiness_gate(
        folds=folds,
        refs=(
            StageReceiptRef(
                node_id="readiness-a",
                stage="readiness-evidence",
                scope="ACCEPTANCE",
                scope_key=_hex("readiness:a"),
                relative_path="receipts/readiness-evidence/a.json",
                sha256=_hex("readiness-a-bytes"),
                fold="fold_001",
                horizon=None,
            ),
            StageReceiptRef(
                node_id="readiness-b",
                stage="readiness-evidence",
                scope="ACCEPTANCE",
                scope_key=_hex("readiness:b"),
                relative_path="receipts/readiness-evidence/b.json",
                sha256=_hex("readiness-b-bytes"),
                fold="fold_001",
                horizon=None,
            ),
        ),
    )
    with pytest.raises(SuccessorRuntimeError) as error:
        _validate_gate_execution("readiness", gate, executions=folds, known=())
    assert error.value.code == "SUCCESSOR_GATE_FAILED"


def test_validate_gate_rejects_readiness_unknown_fold() -> None:
    folds = _two_fold_executions()
    gate = _readiness_gate(
        folds=folds,
        refs=(
            StageReceiptRef(
                node_id="readiness-a",
                stage="readiness-evidence",
                scope="ACCEPTANCE",
                scope_key=_hex("readiness:a"),
                relative_path="receipts/readiness-evidence/a.json",
                sha256=_hex("readiness-a-bytes"),
                fold="fold_001",
                horizon=None,
            ),
            StageReceiptRef(
                node_id="readiness-unknown",
                stage="readiness-evidence",
                scope="ACCEPTANCE",
                scope_key=_hex("readiness:unknown"),
                relative_path="receipts/readiness-evidence/unknown.json",
                sha256=_hex("readiness-unknown-bytes"),
                fold="fold_003",
                horizon=None,
            ),
        ),
    )
    with pytest.raises(SuccessorRuntimeError) as error:
        _validate_gate_execution("readiness", gate, executions=folds, known=())
    assert error.value.code == "SUCCESSOR_GATE_FAILED"


def test_validate_gate_rejects_readiness_missing_fold() -> None:
    folds = _two_fold_executions()
    gate = _readiness_gate(
        folds=folds,
        refs=(
            StageReceiptRef(
                node_id="readiness-only",
                stage="readiness-evidence",
                scope="ACCEPTANCE",
                scope_key=_hex("readiness:only"),
                relative_path="receipts/readiness-evidence/only.json",
                sha256=_hex("readiness-only-bytes"),
                fold="fold_001",
                horizon=None,
            ),
        ),
    )
    with pytest.raises(SuccessorRuntimeError) as error:
        _validate_gate_execution("readiness", gate, executions=folds, known=())
    assert error.value.code == "SUCCESSOR_GATE_FAILED"


def test_unique_refs_rejects_readiness_same_bytes_different_paths() -> None:
    shared_sha = _hex("identical-readiness-receipt-bytes")
    first = StageReceiptRef(
        node_id="gate-readiness-fold_001",
        stage="readiness-evidence",
        scope="ACCEPTANCE",
        scope_key=_hex("readiness:fold_001"),
        relative_path="receipts/readiness-evidence/fold_001.json",
        sha256=shared_sha,
        fold="fold_001",
        horizon=None,
    )
    second = StageReceiptRef(
        node_id="gate-readiness-fold_002",
        stage="readiness-evidence",
        scope="ACCEPTANCE",
        scope_key=_hex("readiness:fold_002"),
        relative_path="receipts/readiness-evidence/fold_002.json",
        sha256=shared_sha,
        fold="fold_002",
        horizon=None,
    )
    with pytest.raises(SuccessorRuntimeError) as error:
        _unique_refs((first, second))
    assert error.value.code == "SUCCESSOR_TERMINAL_INVALID"


def test_global_ownership_rejects_readiness_same_bytes_different_paths(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    first_path = project / "output/stage/receipts/readiness-evidence/fold_001.json"
    second_path = project / "output/stage/receipts/readiness-evidence/fold_002.json"
    first_path.parent.mkdir(parents=True)
    payload = b'{"stage":"readiness-evidence","identical":true}'
    first_path.write_bytes(payload)
    second_path.write_bytes(payload)
    shared_sha = hashlib.sha256(payload).hexdigest()
    first = StageReceiptRef(
        node_id="gate-readiness-fold_001",
        stage="readiness-evidence",
        scope="ACCEPTANCE",
        scope_key=_hex("readiness:fold_001"),
        relative_path="output/stage/receipts/readiness-evidence/fold_001.json",
        sha256=shared_sha,
        fold="fold_001",
        horizon=None,
    )
    second = StageReceiptRef(
        node_id="gate-readiness-fold_002",
        stage="readiness-evidence",
        scope="ACCEPTANCE",
        scope_key=_hex("readiness:fold_002"),
        relative_path="output/stage/receipts/readiness-evidence/fold_002.json",
        sha256=shared_sha,
        fold="fold_002",
        horizon=None,
    )
    gate = GateExecution(
        gate="readiness",
        status="PASS",
        identity=_hex("readiness-gate"),
        receipt_refs=tuple(sorted((first, second), key=lambda item: item.node_id)),
    )
    with pytest.raises(SuccessorRuntimeError) as error:
        runtime._validate_global_receipt_ownership(
            project_root=project,
            folds=(),
            gates=(gate,),
        )
    assert error.value.code == "SUCCESSOR_TERMINAL_INVALID"


def test_verify_receipts_rejects_acceptance_mixed_project_g8_alias(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    stage = project / "output" / "stage"
    stage.mkdir(parents=True)
    project_input = stage / "artifacts" / "mixed-input.bin"
    g8_output = stage / "artifacts" / "mixed-output.bin"
    project_input.parent.mkdir(parents=True, exist_ok=True)
    project_input.write_bytes(b"project-side")
    g8_output.write_bytes(b"g8-side")
    receipt_path = stage / "receipts" / "acceptance" / "mixed.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    scope_key = _hex("acceptance-mixed")
    publish_stage_receipt(
        receipt_path=receipt_path,
        stage="acceptance",
        scope="ACCEPTANCE",
        scope_key=scope_key,
        artifact_roots={"G8": stage, "PROJECT": project},
        inputs=(("PROJECT", project_input),),
        outputs=(("G8", g8_output),),
    )
    ref = StageReceiptRef(
        node_id="gate-acceptance",
        stage="acceptance",
        scope="ACCEPTANCE",
        scope_key=scope_key,
        relative_path="output/stage/receipts/acceptance/mixed.json",
        sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        fold=None,
        horizon=None,
    )
    with pytest.raises(SuccessorRuntimeError) as error:
        runtime._verify_receipts(
            project_root=project,
            controlled_output_root=stage,
            refs=(ref,),
            canonical_stage_root=stage,
        )
    assert error.value.code == "SUCCESSOR_TERMINAL_INVALID"
