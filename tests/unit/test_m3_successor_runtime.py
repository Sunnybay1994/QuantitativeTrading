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
