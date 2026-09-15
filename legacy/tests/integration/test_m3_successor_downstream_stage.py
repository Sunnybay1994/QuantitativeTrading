"""Integration-facing static contracts for successor downstream wiring."""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import replace
from pathlib import Path

import pytest

import quant.research.m3.successor_downstream_stage as downstream
import quant.research.m3.successor_runtime as runtime
import quant.research.m3.successor_upstream_stage as upstream


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _minimal_folds() -> tuple[runtime.FoldExecution, ...]:
    shared_snap = runtime.StageReceiptRef(
        node_id="snap-shared",
        stage="snapshot",
        scope="SNAPSHOT",
        scope_key=_hex("snap"),
        relative_path="receipts/snapshot/snap-shared.json",
        sha256=_hex("snap-bytes"),
        fold=None,
        horizon=None,
    )

    def one(fold: str) -> runtime.FoldExecution:
        return runtime.FoldExecution(
            fold=fold,
            config_raw_sha256=_hex(f"raw:{fold}"),
            config_full_sha256=_hex(f"full:{fold}"),
            g1_release_id=_hex(f"rel:{fold}"),
            g1_release_manifest_sha256=_hex(f"man:{fold}"),
            snapshot_id=_hex("snap"),
            experiment_key=_hex("exp"),
            work_identities=tuple(
                runtime.WorkIdentity(
                    fold=fold,
                    horizon=horizon,
                    work_key=_hex(f"work:{fold}:{horizon}"),
                )
                for horizon in runtime.HORIZONS
            ),
            receipts=(shared_snap,),
        )

    return (one("fold_001"), one("fold_002"))


def test_canonical_factory_and_adapter_round_trip_identity() -> None:
    deps = runtime.make_canonical_successor_production_dependencies()
    adapter = runtime.make_production_successor_stage_adapter(dependencies=deps)
    assert adapter.dependencies.run_formal_stage is downstream.run_successor_formal_stage
    assert adapter.dependencies.run_readiness is downstream.run_successor_readiness_gate
    assert adapter.dependencies.verify_gate is downstream.verify_successor_terminal_gate
    assert adapter.dependencies.run_upstream_wave is upstream.run_successor_upstream_wave


def test_replacing_any_canonical_downstream_callable_fails_closed() -> None:
    deps = runtime.make_canonical_successor_production_dependencies()

    def impostor(**_kwargs: object) -> object:
        return object()

    for field in (
        "run_formal_stage",
        "verify_fold",
        "verify_summary",
        "run_reproducibility",
        "verify_reproducibility",
        "run_readiness",
        "verify_readiness",
        "run_acceptance",
        "verify_acceptance",
        "verify_gate",
    ):
        with pytest.raises(runtime.SuccessorRuntimeError) as error:
            runtime.make_production_successor_stage_adapter(
                dependencies=replace(deps, **{field: impostor}),
            )
        assert error.value.code == "SUCCESSOR_INPUT_INVALID"


def test_readiness_validate_rejects_two_and_fold_bound_accepts_global() -> None:
    folds = _minimal_folds()
    identity = runtime.compute_successor_gate_identity(
        gate="readiness", folds=folds, prior_gates=(),
    )
    two = runtime.GateExecution(
        gate="readiness",
        status="PASS",
        identity=identity,
        receipt_refs=tuple(
            sorted(
                (
                    runtime.StageReceiptRef(
                        node_id="r1",
                        stage="readiness-evidence",
                        scope="ACCEPTANCE",
                        scope_key=_hex("r1"),
                        relative_path="receipts/readiness-evidence/r1.json",
                        sha256=_hex("b1"),
                        fold=None,
                        horizon=None,
                    ),
                    runtime.StageReceiptRef(
                        node_id="r2",
                        stage="readiness-evidence",
                        scope="ACCEPTANCE",
                        scope_key=_hex("r2"),
                        relative_path="receipts/readiness-evidence/r2.json",
                        sha256=_hex("b2"),
                        fold=None,
                        horizon=None,
                    ),
                ),
                key=lambda item: item.node_id,
            )
        ),
    )
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        runtime._validate_gate_execution("readiness", two, executions=folds, known=())
    assert error.value.code == "SUCCESSOR_GATE_FAILED"

    fold_bound = runtime.GateExecution(
        gate="readiness",
        status="PASS",
        identity=identity,
        receipt_refs=(
            runtime.StageReceiptRef(
                node_id="r-fold",
                stage="readiness-evidence",
                scope="ACCEPTANCE",
                scope_key=_hex("r-fold"),
                relative_path="receipts/readiness-evidence/r-fold.json",
                sha256=_hex("bf"),
                fold="fold_001",
                horizon=None,
            ),
        ),
    )
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        runtime._validate_gate_execution(
            "readiness", fold_bound, executions=folds, known=(),
        )
    assert error.value.code == "SUCCESSOR_GATE_FAILED"

    good = runtime.GateExecution(
        gate="readiness",
        status="PASS",
        identity=identity,
        receipt_refs=(
            runtime.StageReceiptRef(
                node_id="r-global",
                stage="readiness-evidence",
                scope="ACCEPTANCE",
                scope_key=_hex("r-global"),
                relative_path="receipts/readiness-evidence/r-global.json",
                sha256=_hex("bg"),
                fold=None,
                horizon=None,
            ),
        ),
    )
    runtime._validate_gate_execution("readiness", good, executions=folds, known=())


def test_formal_runner_builds_tracking_client_from_canonical_uri_only() -> None:
    text = Path(downstream.__file__).read_text(encoding="utf-8")
    assert "rehydrate_successor_formal_tracking_inputs" in text
    assert "create_mlflow_tracking_client" in text
    assert "tracking_uri=tracking.tracking_uri" in text
    assert "apis.summary_verifier(" in text
    assert "rehydrate_successor_summary_horizon_verify_inputs" in text
    assert "verify_research_summary_stage_artifact" in Path(
        runtime.__file__
    ).read_text(encoding="utf-8")
    upstream_text = Path(upstream.__file__).read_text(encoding="utf-8")
    assert "def rehydrate_successor_summary_horizon_verify_inputs" in upstream_text
    assert "_one_fold_horizon_ref(" in upstream_text
    assert 'stage="backtest"' in upstream_text
    params = inspect.signature(downstream.run_successor_formal_stage).parameters
    assert "client" not in params
    assert "prior_refs" in params
