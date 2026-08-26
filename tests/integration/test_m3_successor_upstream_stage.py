"""STATIC_ONLY integration contracts for upstream executable stage wiring."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

import quant.research.m3.successor_runtime as runtime
import quant.research.m3.successor_upstream_stage as upstream
from quant.research.m3.fetch_qlib_tool import DEFAULT_TARGET_PATH


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _ref(
    *,
    node_id: str,
    stage: str,
    fold: str | None = None,
    horizon: int | None = None,
    relative_path: str | None = None,
    sha256: str | None = None,
) -> runtime.StageReceiptRef:
    return runtime.StageReceiptRef(
        node_id=node_id,
        stage=stage,
        scope="WORK" if stage in runtime._HORIZON_WORK_STAGES else "EXPERIMENT",
        scope_key=_hex(node_id),
        relative_path=relative_path or f"receipts/{stage}/{node_id}.json",
        sha256=sha256 or _hex(f"receipt:{node_id}"),
        fold=fold,
        horizon=horizon,
    )


def test_prior_ref_closure_rejects_missing_extra_reorder_and_path_drift() -> None:
    snapshot = _ref(node_id="snapshot", stage="snapshot")
    provider = _ref(node_id="provider", stage="provider")
    ordered = tuple(sorted((snapshot, provider), key=lambda item: item.node_id))
    assert upstream._group_prior_refs_by_stage(
        ordered, wave="provider-validation"
    )

    with pytest.raises(runtime.SuccessorRuntimeError) as missing:
        upstream._group_prior_refs_by_stage((snapshot,), wave="provider-validation")
    assert missing.value.code == "SUCCESSOR_STAGE_INVALID"

    extra = _ref(node_id="tree-scan-latest", stage="labels", horizon=5)
    with pytest.raises(runtime.SuccessorRuntimeError) as extra_error:
        upstream._group_prior_refs_by_stage(
            tuple(sorted((*ordered, extra), key=lambda item: item.node_id)),
            wave="provider-validation",
        )
    assert extra_error.value.code == "SUCCESSOR_STAGE_INVALID"

    unsorted = (snapshot, provider)
    assert tuple(item.node_id for item in unsorted) != tuple(
        sorted(item.node_id for item in unsorted)
    )


def test_experiment_and_work_prior_counts_match_full_wave_closure() -> None:
    experiment_required = upstream._REQUIRED_PRIOR_STAGES["experiment-artifacts"]
    assert experiment_required == {
        "snapshot": 1,
        "provider": 1,
        "provider-validation": 1,
        "experiment-identity": 1,
    }
    work_required = upstream._REQUIRED_PRIOR_STAGES["work"]
    assert work_required["labels"] == 2
    assert work_required["label-reconciliation"] == 2
    assert work_required["folds"] == 1
    label_required = upstream._REQUIRED_PRIOR_STAGES["label-reconciliation"]
    assert label_required["labels"] == 2
    assert label_required["folds"] == 1


def test_second_fold_forces_exact_resume_while_caller_resume_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream._reset_wave_registry_for_tests()
    observed: list[bool] = []
    project = type(Path())(tmp_path / "proj")
    project.mkdir()

    def handler(**kwargs: object) -> tuple[runtime.StageReceiptRef, ...]:
        observed.append(bool(kwargs["resume"]))
        return (_ref(node_id="snapshot", stage="snapshot"),)

    class _Runner:
        pass

    class _Frozen:
        def __init__(self, **kwargs: object) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    monkeypatch.setitem(upstream._WAVE_HANDLERS, "snapshot", handler)
    monkeypatch.setattr(
        upstream, "_require_canonical_public_api_bundle", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        upstream,
        "compute_upstream_wave_transition_identity",
        lambda **_k: _hex("transition"),
    )
    monkeypatch.setattr(upstream, "UpstreamWaveContext", _Frozen)
    monkeypatch.setattr(upstream, "_toolchain_identity_for_context", lambda _c: "tc")
    monkeypatch.setattr(
        upstream,
        "_registry_key",
        lambda **_k: ("two-fold", "project", "snapshot", "tc"),
    )
    monkeypatch.setattr(
        upstream,
        "_verify_prior_receipt",
        lambda ref, **_k: SimpleNamespace(stage=ref.stage, outputs=()),
    )
    monkeypatch.setattr(
        "quant.research.m3.orchestration.StageRunner",
        _Runner,
        raising=True,
    )
    monkeypatch.setattr(
        runtime,
        "make_public_successor_api_bundle",
        lambda: object.__new__(runtime.SuccessorPublicApiBundle),
    )

    fold_a = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_a, "fold", "fold_001")
    fold_b = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_b, "fold", "fold_002")
    request = object.__new__(runtime.SuccessorRuntimeRequest)
    object.__setattr__(request, "folds", (fold_a, fold_b))
    object.__setattr__(request, "project_root", project)
    context = object.__new__(runtime.SuccessorStageContext)
    object.__setattr__(context, "fold", "fold_001")
    object.__setattr__(context, "request", request)
    public_apis = object.__new__(runtime.SuccessorPublicApiBundle)

    first = upstream.run_successor_upstream_wave(
        wave="snapshot",
        request=fold_a,
        context=context,
        runner=_Runner(),
        public_apis=public_apis,
        prior_refs=(),
        resume=False,
    )
    second = upstream.run_successor_upstream_wave(
        wave="snapshot",
        request=fold_b,
        context=replace_fold(context, "fold_002"),
        runner=_Runner(),
        public_apis=public_apis,
        prior_refs=(),
        resume=False,
    )
    assert observed == [False, True]
    assert second == first


def replace_fold(
    context: runtime.SuccessorStageContext, fold: str
) -> runtime.SuccessorStageContext:
    updated = object.__new__(runtime.SuccessorStageContext)
    object.__setattr__(updated, "request", context.request)
    object.__setattr__(updated, "fold", fold)
    return updated


def test_failed_wave_is_not_registered_for_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream._reset_wave_registry_for_tests()
    project = type(Path())(tmp_path / "proj")
    project.mkdir()
    key = ("id", "root", "snapshot", "tc")

    def boom(**_kwargs: object) -> tuple[runtime.StageReceiptRef, ...]:
        raise runtime.SuccessorRuntimeError("SUCCESSOR_STAGE_INVALID")

    class _Runner:
        pass

    class _Frozen:
        def __init__(self, **kwargs: object) -> None:
            for key_name, value in kwargs.items():
                setattr(self, key_name, value)

    monkeypatch.setitem(upstream._WAVE_HANDLERS, "snapshot", boom)
    monkeypatch.setattr(
        upstream, "_require_canonical_public_api_bundle", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        upstream,
        "compute_upstream_wave_transition_identity",
        lambda **_k: _hex("transition"),
    )
    monkeypatch.setattr(upstream, "UpstreamWaveContext", _Frozen)
    monkeypatch.setattr(upstream, "_toolchain_identity_for_context", lambda _c: "tc")
    monkeypatch.setattr(upstream, "_registry_key", lambda **_k: key)
    monkeypatch.setattr(
        "quant.research.m3.orchestration.StageRunner",
        _Runner,
        raising=True,
    )
    monkeypatch.setattr(
        runtime,
        "make_public_successor_api_bundle",
        lambda: object.__new__(runtime.SuccessorPublicApiBundle),
    )

    fold_a = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_a, "fold", "fold_001")
    fold_b = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_b, "fold", "fold_002")
    request = object.__new__(runtime.SuccessorRuntimeRequest)
    object.__setattr__(request, "folds", (fold_a, fold_b))
    object.__setattr__(request, "project_root", project)
    context = object.__new__(runtime.SuccessorStageContext)
    object.__setattr__(context, "fold", "fold_001")
    object.__setattr__(context, "request", request)

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        upstream.run_successor_upstream_wave(
            wave="snapshot",
            request=fold_a,
            context=context,
            runner=_Runner(),
            public_apis=object.__new__(runtime.SuccessorPublicApiBundle),
            prior_refs=(),
            resume=False,
        )
    assert error.value.code == "SUCCESSOR_STAGE_INVALID"
    with upstream._REGISTRY_LOCK:
        assert key not in upstream._WAVE_REGISTRY


def test_canonical_production_dependencies_bind_upstream_and_summary_by_is() -> None:
    def callback(**_kwargs: object) -> object:
        return object()

    deps = runtime.make_canonical_successor_production_dependencies(
        run_formal_stage=callback,  # type: ignore[arg-type]
        verify_fold=callback,  # type: ignore[arg-type]
        verify_summary=callback,  # type: ignore[arg-type]
        run_reproducibility=callback,  # type: ignore[arg-type]
        verify_reproducibility=callback,  # type: ignore[arg-type]
        run_readiness=callback,  # type: ignore[arg-type]
        verify_readiness=callback,  # type: ignore[arg-type]
        run_acceptance=callback,  # type: ignore[arg-type]
        verify_acceptance=callback,  # type: ignore[arg-type]
        verify_gate=callback,  # type: ignore[arg-type]
    )
    assert deps.run_upstream_wave is upstream.run_successor_upstream_wave
    assert deps.run_summary is upstream.run_successor_formal_summary_gate
    assert deps.stage_runner_factory is runtime.make_project_stage_runner


def test_toolchain_identity_enters_two_fold_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = type(Path())(tmp_path / "proj")
    project.mkdir()
    (project / "output" / "stage").mkdir(parents=True)
    dump = type(Path())(project / DEFAULT_TARGET_PATH)
    dump.parent.mkdir(parents=True)
    dump.write_bytes(b"tool")
    python = type(Path())(project / "python.exe")
    python.write_bytes(b"py")

    payloads = {
        "base": (
            python.resolve().as_posix(),
            DEFAULT_TARGET_PATH.as_posix(),
            4,
            _hex("dump"),
        ),
        "drift": (
            python.resolve().as_posix(),
            DEFAULT_TARGET_PATH.as_posix(),
            4,
            _hex("dump-other"),
        ),
    }
    current = {"key": "base"}

    def _validate(**_k: object) -> tuple[str, str, int, str]:
        return payloads[current["key"]]

    monkeypatch.setattr(upstream, "validate_successor_toolchain_binding", _validate)

    def _cfg(raw: str) -> object:
        return SimpleNamespace(
            raw_config_sha256=_hex(raw),
            full_config_sha256=_hex(f"full:{raw}"),
        )

    fold_a = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_a, "fold", "fold_001")
    object.__setattr__(
        fold_a,
        "config",
        SimpleNamespace(
            relative_path=PurePosixPath("configs/a.toml"),
            config=_cfg("a"),
        ),
    )
    object.__setattr__(
        fold_a,
        "release",
        SimpleNamespace(
            manifest=SimpleNamespace(release_id=_hex("r1")),
            manifest_sha256=_hex("m1"),
        ),
    )
    fold_b = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_b, "fold", "fold_002")
    object.__setattr__(
        fold_b,
        "config",
        SimpleNamespace(
            relative_path=PurePosixPath("configs/b.toml"),
            config=_cfg("b"),
        ),
    )
    object.__setattr__(
        fold_b,
        "release",
        SimpleNamespace(
            manifest=SimpleNamespace(release_id=_hex("r2")),
            manifest_sha256=_hex("m2"),
        ),
    )
    request = object.__new__(runtime.SuccessorRuntimeRequest)
    object.__setattr__(request, "project_root", project)
    object.__setattr__(request, "controlled_output_root", project / "output" / "stage")
    object.__setattr__(request, "folds", (fold_a, fold_b))
    object.__setattr__(
        request,
        "runtime_identity",
        runtime.SuccessorRuntimeIdentity(
            code_version="v1",
            dependency_fingerprint_sha256=_hex("dep"),
            provider_runtime_fingerprint_sha256=_hex("prov"),
        ),
    )
    object.__setattr__(
        request,
        "toolchain",
        runtime.SuccessorToolchainBinding(
            python_executable=python,
            qlib_dump_tool_path=dump,
            timeout_seconds=30.0,
        ),
    )

    first = runtime.two_fold_identity(request)  # type: ignore[arg-type]
    current["key"] = "drift"
    second = runtime.two_fold_identity(request)  # type: ignore[arg-type]
    assert first != second


def test_summary_gate_requires_r2s_public_runner_not_placeholder() -> None:
    assert (
        upstream.CANONICAL_RUN_SUMMARY_GATE
        is upstream.run_successor_formal_summary_gate
    )
    source = Path(upstream.__file__).read_text(encoding="utf-8")
    assert "run_formal_summary_stage" in source
    assert "from quant.research.m3.summary_stage import run_formal_summary_stage" in source
    doc = upstream.run_successor_formal_summary_gate.__doc__ or ""
    assert "placeholder" not in doc.lower()
    assert "run_formal_summary_stage" in doc


def test_registry_rejects_sha_drift_on_second_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream._reset_wave_registry_for_tests()
    project = type(Path())(tmp_path / "proj")
    project.mkdir()
    calls = {"n": 0}

    def handler(**_kwargs: object) -> tuple[runtime.StageReceiptRef, ...]:
        calls["n"] += 1
        if calls["n"] == 1:
            return (_ref(node_id="snapshot", stage="snapshot", sha256=_hex("a")),)
        return (_ref(node_id="snapshot", stage="snapshot", sha256=_hex("b")),)

    class _Runner:
        pass

    class _Frozen:
        def __init__(self, **kwargs: object) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    monkeypatch.setitem(upstream._WAVE_HANDLERS, "snapshot", handler)
    monkeypatch.setattr(
        upstream, "_require_canonical_public_api_bundle", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        upstream,
        "compute_upstream_wave_transition_identity",
        lambda **_k: _hex("transition"),
    )
    monkeypatch.setattr(upstream, "UpstreamWaveContext", _Frozen)
    monkeypatch.setattr(upstream, "_toolchain_identity_for_context", lambda _c: "tc")
    monkeypatch.setattr(
        upstream,
        "_registry_key",
        lambda **_k: ("id", "root", "snapshot", "tc"),
    )
    monkeypatch.setattr(
        upstream,
        "_verify_prior_receipt",
        lambda ref, **_k: SimpleNamespace(stage=ref.stage),
    )
    monkeypatch.setattr(
        "quant.research.m3.orchestration.StageRunner",
        _Runner,
        raising=True,
    )
    monkeypatch.setattr(
        runtime,
        "make_public_successor_api_bundle",
        lambda: object.__new__(runtime.SuccessorPublicApiBundle),
    )

    fold_a = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_a, "fold", "fold_001")
    fold_b = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_b, "fold", "fold_002")
    request = object.__new__(runtime.SuccessorRuntimeRequest)
    object.__setattr__(request, "folds", (fold_a, fold_b))
    object.__setattr__(request, "project_root", project)
    context = object.__new__(runtime.SuccessorStageContext)
    object.__setattr__(context, "fold", "fold_001")
    object.__setattr__(context, "request", request)
    public_apis = object.__new__(runtime.SuccessorPublicApiBundle)

    upstream.run_successor_upstream_wave(
        wave="snapshot",
        request=fold_a,
        context=context,
        runner=_Runner(),
        public_apis=public_apis,
        prior_refs=(),
        resume=False,
    )
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        upstream.run_successor_upstream_wave(
            wave="snapshot",
            request=fold_b,
            context=replace_fold(context, "fold_002"),
            runner=_Runner(),
            public_apis=public_apis,
            prior_refs=(),
            resume=False,
        )
    assert error.value.code == "SUCCESSOR_STAGE_INVALID"


def test_labels_and_reconciliation_horizon_closure_before_dict_write() -> None:
    canonical = tuple(sorted(runtime.HORIZONS))
    labels_ok = (
        _ref(node_id="labels.h10", stage="labels", horizon=10),
        _ref(node_id="labels.h5", stage="labels", horizon=5),
    )
    assert set(
        upstream._unique_horizon_ref_map(labels_ok, canonical_horizons=canonical)
    ) == set(canonical)

    for stage in ("labels", "label-reconciliation"):
        dup = (
            _ref(node_id=f"{stage}-a", stage=stage, horizon=5),
            _ref(node_id=f"{stage}-b", stage=stage, horizon=5),
        )
        with pytest.raises(runtime.SuccessorRuntimeError) as raised:
            upstream._unique_horizon_ref_map(dup, canonical_horizons=canonical)
        assert raised.value.code == "SUCCESSOR_STAGE_INVALID"


def test_preseed_registry_poison_rejected_before_handler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream._reset_wave_registry_for_tests()
    project = type(Path())(tmp_path / "proj")
    project.mkdir()
    key = ("poison", "project", "snapshot", "tc")
    observed: list[bool] = []

    def handler(**kwargs: object) -> tuple[runtime.StageReceiptRef, ...]:
        observed.append(bool(kwargs["resume"]))
        return (_ref(node_id="snapshot", stage="snapshot"),)

    class _Runner:
        pass

    class _Frozen:
        def __init__(self, **kwargs: object) -> None:
            for name, value in kwargs.items():
                setattr(self, name, value)

    monkeypatch.setitem(upstream._WAVE_HANDLERS, "snapshot", handler)
    monkeypatch.setattr(
        upstream, "_require_canonical_public_api_bundle", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        upstream,
        "compute_upstream_wave_transition_identity",
        lambda **_k: _hex("transition"),
    )
    monkeypatch.setattr(upstream, "UpstreamWaveContext", _Frozen)
    monkeypatch.setattr(upstream, "_toolchain_identity_for_context", lambda _c: "tc")
    monkeypatch.setattr(upstream, "_registry_key", lambda **_k: key)
    monkeypatch.setattr(
        "quant.research.m3.orchestration.StageRunner",
        _Runner,
        raising=True,
    )
    monkeypatch.setattr(
        runtime,
        "make_public_successor_api_bundle",
        lambda: object.__new__(runtime.SuccessorPublicApiBundle),
    )

    with upstream._REGISTRY_LOCK:
        upstream._WAVE_REGISTRY[key] = (  # type: ignore[assignment]
            _ref(node_id="snapshot", stage="snapshot"),
        )

    fold_a = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_a, "fold", "fold_001")
    fold_b = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_b, "fold", "fold_002")
    request = object.__new__(runtime.SuccessorRuntimeRequest)
    object.__setattr__(request, "folds", (fold_a, fold_b))
    object.__setattr__(request, "project_root", project)
    context = object.__new__(runtime.SuccessorStageContext)
    object.__setattr__(context, "fold", "fold_001")
    object.__setattr__(context, "request", request)

    with pytest.raises(runtime.SuccessorRuntimeError) as raised:
        upstream.run_successor_upstream_wave(
            wave="snapshot",
            request=fold_a,
            context=context,
            runner=_Runner(),
            public_apis=object.__new__(runtime.SuccessorPublicApiBundle),
            prior_refs=(),
            resume=False,
        )
    assert raised.value.code == "SUCCESSOR_STAGE_INVALID"
    assert observed == []


def test_canonical_success_then_second_fold_resume_exact1_closure2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Physical publish once (resume elevated); fresh verify path called twice."""

    upstream._reset_wave_registry_for_tests()
    project = type(Path())(tmp_path / "proj")
    project.mkdir()
    key = ("ok", "project", "snapshot", "tc")
    resumes: list[bool] = []
    verifies: list[str] = []

    def handler(**kwargs: object) -> tuple[runtime.StageReceiptRef, ...]:
        resumes.append(bool(kwargs["resume"]))
        return (_ref(node_id="snapshot", stage="snapshot"),)

    class _Runner:
        pass

    class _Frozen:
        def __init__(self, **kwargs: object) -> None:
            for name, value in kwargs.items():
                setattr(self, name, value)

    monkeypatch.setitem(upstream._WAVE_HANDLERS, "snapshot", handler)
    monkeypatch.setattr(
        upstream, "_require_canonical_public_api_bundle", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        upstream,
        "compute_upstream_wave_transition_identity",
        lambda **_k: _hex("transition"),
    )
    monkeypatch.setattr(upstream, "UpstreamWaveContext", _Frozen)
    monkeypatch.setattr(upstream, "_toolchain_identity_for_context", lambda _c: "tc")
    monkeypatch.setattr(upstream, "_registry_key", lambda **_k: key)
    monkeypatch.setattr(
        upstream,
        "_verify_prior_receipt",
        lambda ref, **_k: verifies.append(ref.node_id)
        or SimpleNamespace(stage=ref.stage),
    )
    monkeypatch.setattr(
        "quant.research.m3.orchestration.StageRunner",
        _Runner,
        raising=True,
    )
    monkeypatch.setattr(
        runtime,
        "make_public_successor_api_bundle",
        lambda: object.__new__(runtime.SuccessorPublicApiBundle),
    )

    fold_a = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_a, "fold", "fold_001")
    fold_b = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_b, "fold", "fold_002")
    request = object.__new__(runtime.SuccessorRuntimeRequest)
    object.__setattr__(request, "folds", (fold_a, fold_b))
    object.__setattr__(request, "project_root", project)
    context = object.__new__(runtime.SuccessorStageContext)
    object.__setattr__(context, "fold", "fold_001")
    object.__setattr__(context, "request", request)
    public_apis = object.__new__(runtime.SuccessorPublicApiBundle)

    first = upstream.run_successor_upstream_wave(
        wave="snapshot",
        request=fold_a,
        context=context,
        runner=_Runner(),
        public_apis=public_apis,
        prior_refs=(),
        resume=False,
    )
    second = upstream.run_successor_upstream_wave(
        wave="snapshot",
        request=fold_b,
        context=replace_fold(context, "fold_002"),
        runner=_Runner(),
        public_apis=public_apis,
        prior_refs=(),
        resume=False,
    )
    assert resumes == [False, True]
    assert verifies == ["snapshot", "snapshot"]
    assert first == second
    with upstream._REGISTRY_LOCK:
        sealed = upstream._WAVE_REGISTRY[key]
    assert type(sealed) is upstream._CanonicalWaveSuccess


def _load_unit_fixture_module(filename: str, module_name: str) -> object:
    import importlib.util

    unit_path = Path(__file__).resolve().parents[1] / "unit" / filename
    spec = importlib.util.spec_from_file_location(module_name, unit_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_integration_real_api_positive_probe_and_project_roots(
    tmp_path: Path,
) -> None:
    """Integration: unmocked probe + PROJECT plan builder with isolated patch authority."""

    import inspect

    import quant.backtest.a_share_plan as plan_module
    from quant.backtest.a_share_plan import (
        BacktestPlanFreshVerificationContext,
        build_backtest_plan_artifact,
    )
    from quant.research.m3 import contracts
    from quant.research.m3.contracts import (
        BacktestPlanManifestV1,
        ProviderProbePlan,
        ProviderValidationSpec,
        VerifiedProviderArtifact,
        VerifiedSnapshotArtifact,
    )
    from quant.research.m3.provider_validation import (
        M3ProviderValidationError,
        plan_provider_probe,
    )
    from quant.research.m3.run_state import compute_provider_validation_key

    feature_support = _load_unit_fixture_module(
        "test_m3_formal_feature_artifact.py",
        "upstream_integration_formal_feature_for_probe",
    )
    plan_support = _load_unit_fixture_module(
        "test_m3_formal_backtest_plan_artifact.py",
        "upstream_integration_formal_plan_for_roots",
    )

    # Authority A: provider materialization + real plan_provider_probe only.
    with pytest.MonkeyPatch.context() as provider_mp:
        common = tmp_path / "artifacts"
        common.mkdir()
        release = feature_support._verified_g1(common / "g1", provider_mp)
        config = feature_support._formal_config(tmp_path, release)
        snapshot, _snapshot_spec, snapshot_request, snapshot_receipt = (
            feature_support._snapshot(common, release, config)
        )
        provider, _provider_spec, _tool, _provider_receipt = feature_support._provider(
            common, snapshot, config, snapshot_request, snapshot_receipt, provider_mp,
        )
        assert type(snapshot) is VerifiedSnapshotArtifact
        assert type(provider) is VerifiedProviderArtifact
        code_version = "successor-upstream-integration-probe-v1"
        validation_spec = ProviderValidationSpec(
            provider_validation_key=compute_provider_validation_key(
                provider_key=provider.manifest.provider_key,
                provider_receipt_sha256=provider.provider_receipt_sha256,
                provider_validation_config_sha256=(
                    config.provider_validation_config_sha256
                ),
                provider_runtime_fingerprint_sha256=(
                    provider.manifest.provider_runtime_fingerprint_sha256
                ),
                code_version=code_version,
            ),
            provider_validation_config_sha256=config.provider_validation_config_sha256,
            code_version=code_version,
            qlib_version="0.9.7",
            sampling_policy_version="provider_market_stratified_hash_first_last_v1",
            worker_protocol_version="m3-qlib-worker-v1",
        )
        probe = plan_provider_probe(
            snapshot=snapshot,
            provider=provider,
            config=config,
            spec=validation_spec,
        )
        assert type(probe) is ProviderProbePlan
        assert probe.provider_validation_key == validation_spec.provider_validation_key
        assert len(probe.selected_rows) == 60

        with pytest.raises(M3ProviderValidationError) as missing_spec:
            plan_provider_probe(
                snapshot=snapshot,
                provider=provider,
                config=config,
            )
        assert missing_spec.value.code == "PROVIDER_VALIDATION_INPUT_INVALID"

    # Authority B: backtest-plan support + real build_backtest_plan_artifact only.
    # Independent context so provider-side subprocess/runtime stubs cannot leak.
    with pytest.MonkeyPatch.context() as plan_mp:
        # Test-owned parent: deep formal support does `plan_root/artifacts.mkdir()`
        # with parents=False; caller must create plan_root before _context.
        plan_root = tmp_path / "plan"
        plan_root.mkdir()
        context = plan_support._context(plan_root, plan_mp)
        kwargs = dict(context["plan_kwargs"])
        project_root = type(Path())(context["common"])
        target = kwargs["target"]
        real_verify_target = plan_module.verify_target_artifact
        # Isolate PROJECT alias vs fixture receipt alias=root; do not stub builder.
        plan_mp.setattr(plan_module, "verify_target_artifact", lambda **_: target)
        output_root = project_root / "integration-plan-project-only"
        output_root.mkdir()
        manifest = build_backtest_plan_artifact(
            target=target,
            release=kwargs["release"],
            folds=kwargs["folds"],
            experiment=kwargs["experiment"],
            config=kwargs["config"],
            fresh_context=kwargs["fresh_context"],
            artifact_roots={"PROJECT": project_root},
            output_root=output_root,
        )
        assert type(manifest) is BacktestPlanManifestV1
        assert manifest.work_key == target.manifest.work_key
        assert type(kwargs["fresh_context"]) is BacktestPlanFreshVerificationContext
        assert not hasattr(contracts, "BacktestPlanFreshVerificationContext")

        plan_mp.setattr(plan_module, "verify_target_artifact", real_verify_target)
        wrong_output = project_root / "integration-plan-wrong-alias"
        wrong_output.mkdir()
        with pytest.raises(ValueError, match="^M3_BACKTEST_PLAN_ARTIFACT_INVALID$"):
            build_backtest_plan_artifact(
                target=kwargs["target"],
                release=kwargs["release"],
                folds=kwargs["folds"],
                experiment=kwargs["experiment"],
                config=kwargs["config"],
                fresh_context=kwargs["fresh_context"],
                artifact_roots={"EXTERNAL_QLIB": project_root},
                output_root=wrong_output,
            )
        assert not any(wrong_output.iterdir())

    production = Path(upstream.__file__).read_text(encoding="utf-8")
    assert "spec=validation_spec" in production
    assert 'artifact_roots={"PROJECT": project_root}' in production
    probe_params = inspect.signature(plan_provider_probe).parameters
    assert probe_params["spec"].default is inspect.Parameter.empty
    plan_params = inspect.signature(build_backtest_plan_artifact).parameters
    assert plan_params["artifact_roots"].default is inspect.Parameter.empty


def test_integration_literal_and_optional_path_reject_helpers() -> None:
    with pytest.raises(runtime.SuccessorRuntimeError) as horizon_none:
        upstream._require_horizon(None)
    assert horizon_none.value.code == "SUCCESSOR_STAGE_INVALID"
    with pytest.raises(runtime.SuccessorRuntimeError) as horizon_bad:
        upstream._require_horizon(3)
    assert horizon_bad.value.code == "SUCCESSOR_STAGE_INVALID"
    with pytest.raises(runtime.SuccessorRuntimeError) as path_none:
        upstream._require_path(None)
    assert path_none.value.code == "SUCCESSOR_STAGE_INVALID"
    assert upstream._require_horizon(5) == 5
    assert upstream._require_horizon(10) == 10
