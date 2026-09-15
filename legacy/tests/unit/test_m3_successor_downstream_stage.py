"""STATIC contract tests for package-owned successor downstream wiring."""

from __future__ import annotations

import ast
import functools
import hashlib
import inspect
from dataclasses import fields
from pathlib import Path

import pytest

import quant.research.m3.successor_downstream_stage as downstream
import quant.research.m3.successor_runtime as runtime
import quant.research.m3.successor_upstream_stage as upstream


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def test_zero_arg_canonical_dependencies_bind_ten_downstream_by_is() -> None:
    deps = runtime.make_canonical_successor_production_dependencies()
    assert deps.run_upstream_wave is upstream.run_successor_upstream_wave
    assert deps.run_summary is upstream.run_successor_formal_summary_gate
    assert deps.run_formal_stage is downstream.run_successor_formal_stage
    assert deps.verify_fold is downstream.verify_successor_fold
    assert deps.verify_summary is downstream.verify_successor_summary_gate
    assert deps.run_reproducibility is downstream.run_successor_reproducibility_gate
    assert deps.verify_reproducibility is downstream.verify_successor_reproducibility_gate
    assert deps.run_readiness is downstream.run_successor_readiness_gate
    assert deps.verify_readiness is downstream.verify_successor_readiness_gate
    assert deps.run_acceptance is downstream.run_successor_acceptance_gate
    assert deps.verify_acceptance is downstream.verify_successor_acceptance_gate
    assert deps.verify_gate is downstream.verify_successor_terminal_gate


def test_adapter_accepts_exact_canonical_dependencies() -> None:
    deps = runtime.make_canonical_successor_production_dependencies()
    adapter = runtime.make_production_successor_stage_adapter(dependencies=deps)
    assert adapter.dependencies is deps


def test_adapter_rejects_lambda_wrapper_partial_on_each_downstream_slot() -> None:
    canonical = runtime.make_canonical_successor_production_dependencies()

    def wrapper(**_kwargs: object) -> object:
        return object()

    partial = functools.partial(downstream.run_successor_formal_stage)
    replacements = {
        "run_formal_stage": (lambda **_k: None, wrapper, partial),
        "verify_fold": (wrapper,),
        "verify_summary": (wrapper,),
        "run_reproducibility": (wrapper,),
        "verify_reproducibility": (wrapper,),
        "run_readiness": (wrapper,),
        "verify_readiness": (wrapper,),
        "run_acceptance": (wrapper,),
        "verify_acceptance": (wrapper,),
        "verify_gate": (wrapper,),
    }
    for field, values in replacements.items():
        for value in values:
            from dataclasses import replace

            deps = replace(canonical, **{field: value})
            with pytest.raises(runtime.SuccessorRuntimeError) as error:
                runtime.make_production_successor_stage_adapter(dependencies=deps)
            assert error.value.code == "SUCCESSOR_INPUT_INVALID"


def test_formal_stage_protocol_requires_prior_refs() -> None:
    params = inspect.signature(runtime.SuccessorProductionFormalStageRunner.__call__).parameters
    assert "prior_refs" in params
    source = Path(runtime.__file__).read_text(encoding="utf-8")
    assert "prior_refs=tuple(" in source
    assert "sorted(refs, key=lambda item: item.node_id)" in source


def test_formal_stage_rejects_unsorted_prior_refs() -> None:
    refs = (
        runtime.StageReceiptRef(
            node_id="z-last",
            stage="targets",
            scope="WORK",
            scope_key=_hex("work"),
            relative_path="receipts/targets/z.json",
            sha256=_hex("z"),
            fold="fold_001",
            horizon=5,
        ),
        runtime.StageReceiptRef(
            node_id="a-first",
            stage="backtest_plan",
            scope="WORK",
            scope_key=_hex("work"),
            relative_path="receipts/backtest_plan/a.json",
            sha256=_hex("a"),
            fold="fold_001",
            horizon=5,
        ),
    )
    assert tuple(item.node_id for item in refs) != tuple(
        sorted(item.node_id for item in refs)
    )
    request = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(request, "fold", "fold_001")
    context = object.__new__(runtime.SuccessorStageContext)
    object.__setattr__(context, "fold", "fold_001")
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        downstream.run_successor_formal_stage(
            stage="backtest",
            horizon=5,
            request=request,
            context=context,
            runner=object(),
            public_apis=object.__new__(runtime.SuccessorPublicApiBundle),
            prior_refs=refs,
            resume=True,
        )
    assert error.value.code == "SUCCESSOR_STAGE_INVALID"


def test_readiness_gate_source_emits_single_global_receipt() -> None:
    source = Path(downstream.__file__).read_text(encoding="utf-8")
    assert 'gate="readiness"' in source
    assert "receipt_refs=(ref,)" in source
    assert "fold=None" in source
    assert "readiness_key" in source
    assert "apis.summary_verifier(" in source
    assert "rehydrate_successor_summary_horizon_verify_inputs" in source
    assert "verify_stage_receipt_with_bytes" not in source.split(
        "def verify_successor_summary_gate"
    )[1].split("def run_successor_reproducibility_gate")[0]


def test_upstream_exposes_formal_rehydrate_without_shared_upstream() -> None:
    """Public rehydrate APIs stay callable; private _SharedUpstream remains in module."""

    assert callable(upstream.rehydrate_successor_formal_backtest_inputs)
    assert callable(upstream.rehydrate_successor_formal_tracking_inputs)
    assert callable(upstream.rehydrate_successor_summary_horizon_verify_inputs)
    source = Path(upstream.__file__).read_text(encoding="utf-8")
    assert "class SuccessorFormalBacktestInputs" in source
    assert "class SuccessorSummaryHorizonVerifyInputs" in source
    assert "_SharedUpstream" in source  # private stays private


_PUBLIC_REHYDRATE_RETURN_TYPES: tuple[tuple[str, str], ...] = (
    ("rehydrate_successor_formal_backtest_inputs", "SuccessorFormalBacktestInputs"),
    ("rehydrate_successor_formal_tracking_inputs", "SuccessorFormalTrackingInputs"),
    (
        "rehydrate_successor_summary_horizon_verify_inputs",
        "SuccessorSummaryHorizonVerifyInputs",
    ),
)


def _module_function_defs(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }


def _annotation_source(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ast.unparse(node)


def test_public_rehydrate_ast_return_annotations_are_strong_public_types() -> None:
    """AST-scope only the three public rehydrate defs; private may return _SharedUpstream."""

    source = Path(upstream.__file__).read_text(encoding="utf-8")
    defs = _module_function_defs(ast.parse(source))
    for name, expected in _PUBLIC_REHYDRATE_RETURN_TYPES:
        node = defs[name]
        ann = _annotation_source(node.returns)
        assert ann == expected
        assert ann != "_SharedUpstream"
        assert "_SharedUpstream" not in ann
    private = defs["_reconstruct_shared_upstream"]
    assert _annotation_source(private.returns) == "_SharedUpstream"


def test_public_rehydrate_signature_return_annotations_match_public_inputs() -> None:
    for name, expected in _PUBLIC_REHYDRATE_RETURN_TYPES:
        fn = getattr(upstream, name)
        ret = inspect.signature(fn).return_annotation
        if isinstance(ret, type):
            assert ret is getattr(upstream, expected)
            assert ret.__name__ == expected
        else:
            assert ret == expected
        assert "_SharedUpstream" not in str(ret)


def test_public_rehydrate_return_types_exact_and_do_not_leak_shared_upstream() -> None:
    public_types = (
        upstream.SuccessorFormalBacktestInputs,
        upstream.SuccessorFormalTrackingInputs,
        upstream.SuccessorSummaryHorizonVerifyInputs,
    )
    shared = upstream._SharedUpstream
    for cls in public_types:
        assert cls is not shared
        assert type(cls) is type
        for field in fields(cls):
            type_text = str(field.type)
            assert "_SharedUpstream" not in type_text
            assert field.name != "_SharedUpstream"
            assert not field.name.startswith("_shared")


def test_caller_cannot_inject_shared_upstream_into_public_rehydrate_apis() -> None:
    shared = upstream._SharedUpstream
    for name, _expected in _PUBLIC_REHYDRATE_RETURN_TYPES:
        fn = getattr(upstream, name)
        params = inspect.signature(fn).parameters
        assert "shared" not in params
        assert "_SharedUpstream" not in params
        assert all("_SharedUpstream" not in pname for pname in params)
        with pytest.raises(TypeError):
            fn(**{"shared": shared})
        with pytest.raises(TypeError):
            fn(**{"_SharedUpstream": shared})


def test_bundle_binds_stage_summary_verifier_not_legacy_horizon_leaf() -> None:
    from quant.research.m3.evaluate import (
        verify_research_summary_artifact,
        verify_research_summary_stage_artifact,
    )

    bundle = runtime.make_public_successor_api_bundle()
    assert bundle.summary_verifier is verify_research_summary_stage_artifact
    assert bundle.summary_verifier is not verify_research_summary_artifact


def _two_folds_same_experiment() -> tuple[runtime.FoldExecution, ...]:
    experiment_key = _hex("exp-shared")

    def one(fold: str) -> runtime.FoldExecution:
        return runtime.FoldExecution(
            fold=fold,
            config_raw_sha256=_hex(f"raw:{fold}"),
            config_full_sha256=_hex(f"full:{fold}"),
            g1_release_id=_hex(f"rel:{fold}"),
            g1_release_manifest_sha256=_hex(f"man:{fold}"),
            snapshot_id=_hex("snap"),
            experiment_key=experiment_key,
            work_identities=tuple(
                runtime.WorkIdentity(
                    fold=fold,
                    horizon=horizon,
                    work_key=_hex(f"work:{fold}:{horizon}"),
                )
                for horizon in runtime.HORIZONS
            ),
            receipts=(),
        )

    return (one("fold_001"), one("fold_002"))


def _summary_gate(
    folds: tuple[runtime.FoldExecution, ...],
) -> runtime.GateExecution:
    experiment_key = folds[0].experiment_key
    refs = tuple(
        sorted(
            (
                runtime.StageReceiptRef(
                    node_id=f"summary-h{horizon}",
                    stage="research-summary",
                    scope="EXPERIMENT",
                    scope_key=experiment_key,
                    relative_path=f"receipts/research-summary/h{horizon}.json",
                    sha256=_hex(f"summary-bytes:{horizon}"),
                    fold=None,
                    horizon=horizon,
                )
                for horizon in runtime.HORIZONS
            ),
            key=lambda item: item.node_id,
        )
    )
    return runtime.GateExecution(
        gate="summary",
        status="PASS",
        identity=runtime.compute_successor_gate_identity(
            gate="summary", folds=folds, prior_gates=(),
        ),
        receipt_refs=refs,
    )


def test_verify_summary_calls_summary_verifier_exact_once_per_horizon(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from quant.research.m3.contracts import VerifiedResearchSummaryArtifact

    folds = _two_folds_same_experiment()
    gate = _summary_gate(folds)
    context = object.__new__(runtime.SuccessorStageContext)
    calls: list[int] = []

    def fake_rehydrate(
        *,
        folds: object,
        context: object,
        summary_ref: runtime.StageReceiptRef,
    ) -> SimpleNamespace:
        del folds, context
        root = type(Path())(tmp_path / f"summary-h{summary_ref.horizon}")
        root.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            identity=object(),
            root=root,
            receipt_path=type(Path())(tmp_path / summary_ref.relative_path),
            evaluations=(),
            evaluation_contexts=(),
            experiment=object(),
            config=object(),
            upstream_paths=object(),
            artifact_roots={},
        )

    def fake_verifier(**kwargs: object) -> object:
        identity = kwargs["identity"]
        root = kwargs["root"]
        del identity
        assert isinstance(root, Path)
        horizon = int(root.name.removeprefix("summary-h"))
        calls.append(horizon)
        verified = object.__new__(VerifiedResearchSummaryArtifact)
        object.__setattr__(verified, "summary_receipt_sha256", _hex(f"summary-bytes:{horizon}"))
        object.__setattr__(
            verified,
            "manifest",
            SimpleNamespace(
                experiment_key=folds[0].experiment_key,
                horizon_sessions=horizon,
            ),
        )
        object.__setattr__(verified, "root", root)
        return verified

    monkeypatch.setattr(
        upstream,
        "rehydrate_successor_summary_horizon_verify_inputs",
        fake_rehydrate,
    )
    monkeypatch.setattr(
        "quant.research.m3.evaluate.verify_research_summary_stage_artifact",
        fake_verifier,
    )

    result = downstream.verify_successor_summary_gate(
        gate=gate,
        folds=folds,
        prior_gates=(),
        context=context,
        runner=object(),
        public_apis=runtime.make_public_successor_api_bundle(),
    )
    assert result.gate == "summary"
    assert result.identity == gate.identity
    assert sorted(calls) == [5, 10]
    assert len(calls) == 2


def test_verify_summary_rejects_wrapper_summary_verifier() -> None:
    folds = _two_folds_same_experiment()
    gate = _summary_gate(folds)
    context = object.__new__(runtime.SuccessorStageContext)
    canonical = runtime.make_public_successor_api_bundle()

    def wrapper(**_kwargs: object) -> object:
        return object()

    from dataclasses import replace

    wrapped = replace(canonical, summary_verifier=wrapper)
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        downstream.verify_successor_summary_gate(
            gate=gate,
            folds=folds,
            prior_gates=(),
            context=context,
            runner=object(),
            public_apis=wrapped,
        )
    assert error.value.code == "SUCCESSOR_INPUT_INVALID"


def test_verify_summary_rejects_wrong_artifact_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from quant.research.m3.contracts import VerifiedResearchSummaryArtifact

    folds = _two_folds_same_experiment()
    gate = _summary_gate(folds)
    context = object.__new__(runtime.SuccessorStageContext)

    def fake_rehydrate(
        *,
        folds: object,
        context: object,
        summary_ref: runtime.StageReceiptRef,
    ) -> SimpleNamespace:
        del folds, context
        root = type(Path())(tmp_path / f"summary-h{summary_ref.horizon}")
        root.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            identity=object(),
            root=root,
            receipt_path=type(Path())(tmp_path / "r.json"),
            evaluations=(),
            evaluation_contexts=(),
            experiment=object(),
            config=object(),
            upstream_paths=object(),
            artifact_roots={},
        )

    def wrong_identity(**kwargs: object) -> object:
        root = kwargs["root"]
        assert isinstance(root, Path)
        verified = object.__new__(VerifiedResearchSummaryArtifact)
        object.__setattr__(verified, "summary_receipt_sha256", _hex("wrong-receipt"))
        object.__setattr__(
            verified,
            "manifest",
            SimpleNamespace(
                experiment_key=folds[0].experiment_key,
                horizon_sessions=5,
            ),
        )
        object.__setattr__(verified, "root", root)
        return verified

    monkeypatch.setattr(
        upstream,
        "rehydrate_successor_summary_horizon_verify_inputs",
        fake_rehydrate,
    )
    monkeypatch.setattr(
        "quant.research.m3.evaluate.verify_research_summary_stage_artifact",
        wrong_identity,
    )
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        downstream.verify_successor_summary_gate(
            gate=gate,
            folds=folds,
            prior_gates=(),
            context=context,
            runner=object(),
            public_apis=runtime.make_public_successor_api_bundle(),
        )
    assert error.value.code == "SUCCESSOR_GATE_FAILED"


def test_verify_summary_rejects_one_horizon_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from quant.research.m3.contracts import VerifiedResearchSummaryArtifact

    folds = _two_folds_same_experiment()
    gate = _summary_gate(folds)
    context = object.__new__(runtime.SuccessorStageContext)
    seen: list[int] = []

    def fake_rehydrate(
        *,
        folds: object,
        context: object,
        summary_ref: runtime.StageReceiptRef,
    ) -> SimpleNamespace:
        del folds, context
        if summary_ref.horizon == 10:
            raise runtime.SuccessorRuntimeError("SUCCESSOR_GATE_FAILED")
        root = type(Path())(tmp_path / f"summary-h{summary_ref.horizon}")
        root.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            identity=object(),
            root=root,
            receipt_path=type(Path())(tmp_path / "r.json"),
            evaluations=(),
            evaluation_contexts=(),
            experiment=object(),
            config=object(),
            upstream_paths=object(),
            artifact_roots={},
        )

    def fake_verifier(**kwargs: object) -> object:
        root = kwargs["root"]
        assert isinstance(root, Path)
        horizon = int(root.name.removeprefix("summary-h"))
        seen.append(horizon)
        verified = object.__new__(VerifiedResearchSummaryArtifact)
        object.__setattr__(verified, "summary_receipt_sha256", _hex(f"summary-bytes:{horizon}"))
        object.__setattr__(
            verified,
            "manifest",
            SimpleNamespace(
                experiment_key=folds[0].experiment_key,
                horizon_sessions=horizon,
            ),
        )
        object.__setattr__(verified, "root", root)
        return verified

    monkeypatch.setattr(
        upstream,
        "rehydrate_successor_summary_horizon_verify_inputs",
        fake_rehydrate,
    )
    monkeypatch.setattr(
        "quant.research.m3.evaluate.verify_research_summary_stage_artifact",
        fake_verifier,
    )
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        downstream.verify_successor_summary_gate(
            gate=gate,
            folds=folds,
            prior_gates=(),
            context=context,
            runner=object(),
            public_apis=runtime.make_public_successor_api_bundle(),
        )
    assert error.value.code == "SUCCESSOR_GATE_FAILED"
    assert len(seen) <= 1


def _tracking_request_context(
    tmp_path: Path,
    *,
    request_fold: str = "fold_001",
) -> tuple[runtime.SuccessorFoldRequest, runtime.SuccessorStageContext]:
    project = type(Path())(tmp_path / "proj")
    project.mkdir(parents=True, exist_ok=True)
    fold_a = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_a, "fold", "fold_001")
    fold_b = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_b, "fold", "fold_002")
    request = object.__new__(runtime.SuccessorRuntimeRequest)
    object.__setattr__(request, "folds", (fold_a, fold_b))
    object.__setattr__(request, "project_root", project)
    fold_request = fold_a if request_fold == "fold_001" else fold_b
    context = object.__new__(runtime.SuccessorStageContext)
    object.__setattr__(context, "fold", request_fold)
    object.__setattr__(context, "request", request)
    return fold_request, context


def _backtest_ref(
    *,
    fold: str,
    horizon: int,
    node_id: str | None = None,
) -> runtime.StageReceiptRef:
    nid = node_id or f"backtest.{fold}.h{horizon}"
    return runtime.StageReceiptRef(
        node_id=nid,
        stage="backtest",
        scope="WORK",
        scope_key=_hex(f"work:{fold}:{horizon}"),
        relative_path=f"receipts/backtest/{nid}.json",
        sha256=_hex(f"bt:{nid}"),
        fold=fold,
        horizon=horizon,
    )


def test_tracking_rehydrate_rejects_missing_backtest_prior(
    tmp_path: Path,
) -> None:
    fold_request, context = _tracking_request_context(tmp_path)
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        upstream.rehydrate_successor_formal_tracking_inputs(
            prior_refs=(),
            request=fold_request,
            context=context,
            horizon=5,
        )
    assert error.value.code == "SUCCESSOR_STAGE_INVALID"


def test_tracking_rehydrate_rejects_cross_horizon_backtest_prior(
    tmp_path: Path,
) -> None:
    fold_request, context = _tracking_request_context(tmp_path)
    refs = (_backtest_ref(fold="fold_001", horizon=10),)
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        upstream.rehydrate_successor_formal_tracking_inputs(
            prior_refs=refs,
            request=fold_request,
            context=context,
            horizon=5,
        )
    assert error.value.code == "SUCCESSOR_STAGE_INVALID"


def test_tracking_rehydrate_rejects_cross_fold_backtest_prior(
    tmp_path: Path,
) -> None:
    fold_request, context = _tracking_request_context(tmp_path)
    refs = (_backtest_ref(fold="fold_002", horizon=5),)
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        upstream.rehydrate_successor_formal_tracking_inputs(
            prior_refs=refs,
            request=fold_request,
            context=context,
            horizon=5,
        )
    assert error.value.code == "SUCCESSOR_STAGE_INVALID"


def test_tracking_rehydrate_rejects_cross_request_fold(
    tmp_path: Path,
) -> None:
    _fold_a, context = _tracking_request_context(tmp_path, request_fold="fold_001")
    foreign = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(foreign, "fold", "fold_003")
    refs = (_backtest_ref(fold="fold_003", horizon=5),)
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        upstream.rehydrate_successor_formal_tracking_inputs(
            prior_refs=refs,
            request=foreign,
            context=context,
            horizon=5,
        )
    assert error.value.code == "SUCCESSOR_STAGE_INVALID"


def test_tracking_rehydrate_rejects_duplicate_and_unsorted_backtest_priors(
    tmp_path: Path,
) -> None:
    fold_request, context = _tracking_request_context(tmp_path)
    first = _backtest_ref(fold="fold_001", horizon=5, node_id="a-backtest")
    second = _backtest_ref(fold="fold_001", horizon=5, node_id="b-backtest")
    with pytest.raises(runtime.SuccessorRuntimeError) as dup_error:
        upstream.rehydrate_successor_formal_tracking_inputs(
            prior_refs=(first, second),
            request=fold_request,
            context=context,
            horizon=5,
        )
    assert dup_error.value.code == "SUCCESSOR_STAGE_INVALID"

    unsorted = (
        _backtest_ref(fold="fold_001", horizon=5, node_id="z-last"),
        _backtest_ref(fold="fold_001", horizon=10, node_id="a-first"),
    )
    assert tuple(item.node_id for item in unsorted) != tuple(
        sorted(item.node_id for item in unsorted)
    )
    with pytest.raises(runtime.SuccessorRuntimeError) as sort_error:
        upstream.rehydrate_successor_formal_tracking_inputs(
            prior_refs=unsorted,
            request=fold_request,
            context=context,
            horizon=5,
        )
    assert sort_error.value.code == "SUCCESSOR_STAGE_INVALID"


def test_tracking_formal_stage_rejects_before_public_tracking_apis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fold_request, context = _tracking_request_context(tmp_path)
    project = context.request.project_root
    pseudo = project / "latest" / "backtest" / "fold_001" / "h5"
    pseudo.mkdir(parents=True, exist_ok=True)
    (pseudo / "backtest_manifest.json").write_text("{}", encoding="utf-8")

    tracking_calls: list[str] = []

    def boom_tracking(**_kwargs: object) -> object:
        tracking_calls.append("formal_tracking_stage")
        raise AssertionError("public tracking must not run")

    def boom_plan(**_kwargs: object) -> object:
        tracking_calls.append("formal_tracking_run_plan")
        raise AssertionError("public tracking plan must not run")

    def boom_client(**_kwargs: object) -> object:
        tracking_calls.append("create_mlflow_tracking_client")
        raise AssertionError("tracking client must not be built")

    monkeypatch.setattr(
        "quant.research.m3.tracking_stage.run_formal_tracking_stage",
        boom_tracking,
    )
    monkeypatch.setattr(
        "quant.research.m3.tracking_stage.make_formal_tracking_run_plan",
        boom_plan,
    )
    monkeypatch.setattr(
        "quant.research.m3.tracking.create_mlflow_tracking_client",
        boom_client,
    )

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        downstream.run_successor_formal_stage(
            stage="tracking",
            horizon=5,
            request=fold_request,
            context=context,
            runner=object(),
            public_apis=runtime.make_public_successor_api_bundle(),
            prior_refs=(),
            resume=True,
        )
    assert error.value.code in {
        "SUCCESSOR_STAGE_INVALID",
        "SUCCESSOR_INPUT_INVALID",
    }
    assert tracking_calls == []
    assert pseudo.exists()


def test_readiness_verify_rejects_aggregate_identity_as_physical_scope_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    folds = _two_folds_same_experiment()
    prior = (
        runtime.GateExecution(
            gate="summary",
            status="PASS",
            identity=_hex("summary-id"),
            receipt_refs=tuple(
                sorted(
                    (
                        runtime.StageReceiptRef(
                            node_id=f"s{horizon}",
                            stage="research-summary",
                            scope="EXPERIMENT",
                            scope_key=folds[0].experiment_key,
                            relative_path=f"receipts/research-summary/h{horizon}.json",
                            sha256=_hex(f"s{horizon}"),
                            fold=None,
                            horizon=horizon,
                        )
                        for horizon in runtime.HORIZONS
                    ),
                    key=lambda item: item.node_id,
                )
            ),
        ),
        runtime.GateExecution(
            gate="reproducibility",
            status="PASS",
            identity=_hex("repro-id"),
            receipt_refs=tuple(
                sorted(
                    (
                        runtime.StageReceiptRef(
                            node_id=f"repro-{fold}-h{horizon}",
                            stage="reproducibility",
                            scope="REPRO",
                            scope_key=_hex(f"cmp:{fold}:{horizon}"),
                            relative_path=(
                                f"receipts/reproducibility/{fold}-h{horizon}.json"
                            ),
                            sha256=_hex(f"repro:{fold}:{horizon}"),
                            fold=fold,
                            horizon=horizon,
                        )
                        for fold in ("fold_001", "fold_002")
                        for horizon in runtime.HORIZONS
                    ),
                    key=lambda item: item.node_id,
                )
            ),
        ),
    )
    identity = runtime.compute_successor_gate_identity(
        gate="readiness", folds=folds, prior_gates=prior,
    )
    physical_key = _hex("readiness-physical")
    assert physical_key != identity
    gate = runtime.GateExecution(
        gate="readiness",
        status="PASS",
        identity=identity,
        receipt_refs=(
            runtime.StageReceiptRef(
                node_id="readiness-global",
                stage="readiness-evidence",
                scope="ACCEPTANCE",
                scope_key=identity,
                relative_path="receipts/readiness-evidence/masquerade.json",
                sha256=_hex("readiness-bytes"),
                fold=None,
                horizon=None,
            ),
        ),
    )
    runtime._validate_gate_execution(
        "readiness", gate, executions=folds, known=prior,
    )

    fold_req = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_req, "fold", "fold_001")
    object.__setattr__(
        fold_req,
        "config",
        SimpleNamespace(config=object(), relative_path="configs/a.toml"),
    )
    object.__setattr__(fold_req, "release", object())
    fold_b = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_b, "fold", "fold_002")
    project = type(Path())(tmp_path / "proj")
    project.mkdir(parents=True, exist_ok=True)
    runtime_request = object.__new__(runtime.SuccessorRuntimeRequest)
    object.__setattr__(runtime_request, "folds", (fold_req, fold_b))
    object.__setattr__(runtime_request, "project_root", project)
    context = object.__new__(runtime.SuccessorStageContext)
    object.__setattr__(context, "fold", None)
    object.__setattr__(context, "request", runtime_request)

    def fake_verifier(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            report=SimpleNamespace(readiness_key=physical_key),
        )

    class _Apis:
        readiness_verifier = staticmethod(fake_verifier)

    monkeypatch.setattr(
        downstream,
        "_require_canonical_public_apis",
        lambda _apis: _Apis(),
    )
    monkeypatch.setattr(
        downstream,
        "project_stage_root",
        lambda **_k: type(Path())(tmp_path / "stage"),
    )

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        downstream.verify_successor_readiness_gate(
            gate=gate,
            folds=folds,
            prior_gates=prior,
            context=context,
            runner=object(),
            public_apis=object.__new__(runtime.SuccessorPublicApiBundle),
        )
    assert error.value.code == "SUCCESSOR_GATE_FAILED"


def test_require_finite_config_float_accepts_exact_finite_rejects_invalid() -> None:
    assert downstream._require_finite_config_float(0.0) == 0.0
    assert downstream._require_finite_config_float(1.5e-3) == 1.5e-3
    for bad in (True, False, 1, "0.1", None, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(runtime.SuccessorRuntimeError) as error:
            downstream._require_finite_config_float(bad)
        assert error.value.code == "SUCCESSOR_GATE_FAILED"


def test_formal_backtest_rejects_marker_wrapper_wrong_return_types(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    fold_request, context = _tracking_request_context(tmp_path)
    prior = (
        runtime.StageReceiptRef(
            node_id="a-prior",
            stage="targets",
            scope="WORK",
            scope_key=_hex("work"),
            relative_path="receipts/targets/a.json",
            sha256=_hex("a"),
            fold="fold_001",
            horizon=5,
        ),
    )

    def fake_rehydrate(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            stage_root=type(Path())(tmp_path / "stage"),
            target=object(),
            plan=object(),
            release=object(),
            experiment=object(),
            config=object(),
            fresh_context=object(),
            artifact_roots={},
            fold="fold_001",
            horizon=5,
        )

    monkeypatch.setattr(
        upstream,
        "rehydrate_successor_formal_backtest_inputs",
        fake_rehydrate,
    )

    def marker(**_kwargs: object) -> object:
        return object()

    def wrapper(**_kwargs: object) -> object:
        return SimpleNamespace(receipt_path=object(), receipt=object())

    class _MarkerResult:
        pass

    def wrong_type(**_kwargs: object) -> object:
        return _MarkerResult()

    for stage_fn in (marker, wrapper, wrong_type):
        class _Apis:
            formal_backtest_run_plan = None
            formal_backtest_stage = staticmethod(stage_fn)

        monkeypatch.setattr(
            downstream,
            "_require_canonical_public_apis",
            lambda _apis: _Apis(),
        )
        with pytest.raises(runtime.SuccessorRuntimeError) as error:
            downstream.run_successor_formal_stage(
                stage="backtest",
                horizon=5,
                request=fold_request,
                context=context,
                runner=object(),
                public_apis=object.__new__(runtime.SuccessorPublicApiBundle),
                prior_refs=prior,
                resume=True,
            )
        assert error.value.code == "SUCCESSOR_STAGE_INVALID"
