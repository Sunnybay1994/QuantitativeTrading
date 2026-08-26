"""STATIC_ONLY contract tests for package-owned successor upstream wiring."""

from __future__ import annotations

import hashlib
from dataclasses import replace
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
) -> runtime.StageReceiptRef:
    return runtime.StageReceiptRef(
        node_id=node_id,
        stage=stage,
        scope="EXPERIMENT",
        scope_key=_hex(node_id),
        relative_path=f"receipts/{stage}/{node_id}.json",
        sha256=_hex(f"receipt:{node_id}"),
        fold=fold,
        horizon=horizon,
    )


def test_canonical_aliases_are_module_level_callables() -> None:
    assert upstream.CANONICAL_RUN_UPSTREAM_WAVE is upstream.run_successor_upstream_wave
    assert upstream.CANONICAL_RUN_SUMMARY_GATE is upstream.run_successor_formal_summary_gate
    assert callable(upstream.CANONICAL_RUN_UPSTREAM_WAVE)
    assert callable(upstream.CANONICAL_RUN_SUMMARY_GATE)


def test_upstream_wave_context_rejects_unsorted_or_duplicate_priors(
    tmp_path: Path,
) -> None:
    project = type(Path())(tmp_path / "proj")
    project.mkdir()
    (project / "output").mkdir()
    python = type(Path())(project / "python.exe")
    python.write_bytes(b"py")
    dump = type(Path())(project / DEFAULT_TARGET_PATH)
    dump.parent.mkdir(parents=True)
    dump.write_bytes(b"dump")

    fold_a = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_a, "fold", "fold_001")
    fold_b = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_b, "fold", "fold_002")
    request = object.__new__(runtime.SuccessorRuntimeRequest)
    object.__setattr__(request, "project_root", project)
    object.__setattr__(request, "controlled_output_root", project / "output")
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
            timeout_seconds=1.0,
        ),
    )
    context = object.__new__(runtime.SuccessorStageContext)
    object.__setattr__(context, "request", request)
    object.__setattr__(context, "fold", "fold_001")

    first = _ref(node_id="b-node", stage="snapshot")
    second = _ref(node_id="a-node", stage="provider")
    with pytest.raises(ValueError, match="uniquely sorted"):
        upstream.UpstreamWaveContext(
            request=request,
            stage_context=context,
            prior_refs=(first, second),
            transition_identity=_hex("transition"),
        )
    with pytest.raises(ValueError, match="uniquely sorted"):
        upstream.UpstreamWaveContext(
            request=request,
            stage_context=context,
            prior_refs=(first, first),
            transition_identity=_hex("transition"),
        )


def test_toolchain_binding_rejects_non_float_timeout_and_path_subclasses(
    tmp_path: Path,
) -> None:
    python = type(Path())(tmp_path / "python.exe")
    dump = type(Path())(tmp_path / "dump_bin.py")
    with pytest.raises(ValueError):
        runtime.SuccessorToolchainBinding(
            python_executable=python,
            qlib_dump_tool_path=dump,
            timeout_seconds=1,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        runtime.SuccessorToolchainBinding(
            python_executable=python,
            qlib_dump_tool_path=dump,
            timeout_seconds=True,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        runtime.SuccessorToolchainBinding(
            python_executable=python,
            qlib_dump_tool_path=dump,
            timeout_seconds=0.0,
        )
    with pytest.raises(ValueError):
        runtime.SuccessorToolchainBinding(
            python_executable=python,
            qlib_dump_tool_path=dump,
            timeout_seconds=float("nan"),
        )
    with pytest.raises(ValueError):
        runtime.SuccessorToolchainBinding(
            python_executable=PurePosixPath("/x/python"),  # type: ignore[arg-type]
            qlib_dump_tool_path=dump,
            timeout_seconds=1.0,
        )


def test_validate_toolchain_rejects_relative_wrong_dump_and_spec_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant.research.m3.config import LoadedM3Config
    from quant.research.m3.contracts import QlibDumpToolSpec

    project = type(Path())(tmp_path / "project")
    project.mkdir()
    dump = type(Path())(project / DEFAULT_TARGET_PATH)
    dump.parent.mkdir(parents=True)
    payload = b"dump-bytes"
    dump.write_bytes(payload)
    python = type(Path())(tmp_path / "python.exe")
    python.write_bytes(b"py")
    digest = hashlib.sha256(payload).hexdigest()

    cfg_a = object.__new__(LoadedM3Config)
    cfg_b = object.__new__(LoadedM3Config)
    spec = QlibDumpToolSpec(
        url="https://example.test/dump_bin.py",
        sha256=digest,
        size_bytes=len(payload),
        qlib_version="0.9.7",
        command="dump_all",
    )
    monkeypatch.setattr(
        "quant.research.m3.fetch_qlib_tool.build_qlib_dump_tool_spec",
        lambda _config: spec,
    )
    binding = runtime.SuccessorToolchainBinding(
        python_executable=python,
        qlib_dump_tool_path=dump,
        timeout_seconds=1.5,
    )
    identity = upstream.validate_successor_toolchain_binding(
        project_root=project,
        toolchain=binding,
        fold_configs=(cfg_a, cfg_b),
    )
    assert identity[1] == DEFAULT_TARGET_PATH.as_posix()
    assert identity[2] == len(payload)
    assert identity[3] == digest

    relative_dump = type(Path())(DEFAULT_TARGET_PATH)
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        upstream.validate_successor_toolchain_binding(
            project_root=project,
            toolchain=replace(binding, qlib_dump_tool_path=relative_dump),
            fold_configs=(cfg_a, cfg_b),
        )
    assert error.value.code == "SUCCESSOR_INPUT_INVALID"

    wrong = type(Path())(project / "data" / "external" / "qlib" / "other.py")
    wrong.write_bytes(payload)
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        upstream.validate_successor_toolchain_binding(
            project_root=project,
            toolchain=replace(binding, qlib_dump_tool_path=wrong),
            fold_configs=(cfg_a, cfg_b),
        )
    assert error.value.code == "SUCCESSOR_INPUT_INVALID"

    dump.write_bytes(b"drifted-dump-bytes!!")
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        upstream.validate_successor_toolchain_binding(
            project_root=project,
            toolchain=binding,
            fold_configs=(cfg_a, cfg_b),
        )
    assert error.value.code == "SUCCESSOR_INPUT_INVALID"


def test_validate_toolchain_rejects_bool_int_timeout_at_validate_layer(
    tmp_path: Path,
) -> None:
    project = type(Path())(tmp_path / "project")
    project.mkdir()
    dump = type(Path())(project / DEFAULT_TARGET_PATH)
    dump.parent.mkdir(parents=True)
    dump.write_bytes(b"x")
    python = type(Path())(tmp_path / "python.exe")
    python.write_bytes(b"py")
    binding = object.__new__(runtime.SuccessorToolchainBinding)
    object.__setattr__(binding, "python_executable", python)
    object.__setattr__(binding, "qlib_dump_tool_path", dump)
    object.__setattr__(binding, "timeout_seconds", 1)
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        upstream.validate_successor_toolchain_binding(
            project_root=project,
            toolchain=binding,
            fold_configs=(object(), object()),  # type: ignore[arg-type]
        )
    assert error.value.code in {
        "SUCCESSOR_INPUT_INVALID",
        "SUCCESSOR_CONFIG_INVALID",
    }


def test_group_prior_refs_rejects_missing_extra_duplicate_and_scan_poison() -> None:
    good = (_ref(node_id="snapshot", stage="snapshot"),)
    grouped = upstream._group_prior_refs_by_stage(good, wave="provider")
    assert set(grouped) == {"snapshot"}

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        upstream._group_prior_refs_by_stage((), wave="provider")
    assert error.value.code == "SUCCESSOR_STAGE_INVALID"

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        upstream._group_prior_refs_by_stage(
            (
                *good,
                _ref(node_id="latest-fake", stage="provider-validation"),
            ),
            wave="provider",
        )
    assert error.value.code == "SUCCESSOR_STAGE_INVALID"

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        upstream._group_prior_refs_by_stage(
            (
                _ref(node_id="snapshot-a", stage="snapshot"),
                _ref(node_id="snapshot-b", stage="snapshot"),
            ),
            wave="provider",
        )
    assert error.value.code == "SUCCESSOR_STAGE_INVALID"


def test_adapter_rejects_wrapper_upstream_and_summary_callables(
    tmp_path: Path,
) -> None:
    def wrapper(**_kwargs: object) -> object:
        return ()

    def callback(**_kwargs: object) -> object:
        return object()

    dependencies = runtime.SuccessorProductionDependencies(
        stage_runner_factory=runtime.make_project_stage_runner,
        run_upstream_wave=wrapper,  # type: ignore[arg-type]
        run_formal_stage=callback,  # type: ignore[arg-type]
        verify_fold=callback,  # type: ignore[arg-type]
        run_summary=wrapper,  # type: ignore[arg-type]
        verify_summary=callback,  # type: ignore[arg-type]
        run_reproducibility=callback,  # type: ignore[arg-type]
        verify_reproducibility=callback,  # type: ignore[arg-type]
        run_readiness=callback,  # type: ignore[arg-type]
        verify_readiness=callback,  # type: ignore[arg-type]
        run_acceptance=callback,  # type: ignore[arg-type]
        verify_acceptance=callback,  # type: ignore[arg-type]
        verify_gate=callback,  # type: ignore[arg-type]
    )
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        runtime.make_production_successor_stage_adapter(dependencies=dependencies)
    assert error.value.code == "SUCCESSOR_INPUT_INVALID"


def test_work_pre_formal_stages_use_backtest_plan_underscore() -> None:
    assert "backtest_plan" in runtime._WORK_PRE_FORMAL_STAGES
    assert "backtest-plan" not in runtime._WORK_PRE_FORMAL_STAGES
    assert runtime._WORK_PRE_FORMAL_STAGES[-1] == "backtest_plan"
    assert "backtest_plan" in runtime._REQUIRED_HORIZON_STAGES


def test_run_wave_rejects_unsorted_prior_refs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream._reset_wave_registry_for_tests()
    project = type(Path())(tmp_path / "proj")
    project.mkdir()

    class _Runner:
        pass

    monkeypatch.setattr(
        upstream, "_require_canonical_public_api_bundle", lambda *_a, **_k: None
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

    fold_request = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_request, "fold", "fold_001")
    fold_b = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_b, "fold", "fold_002")
    request = object.__new__(runtime.SuccessorRuntimeRequest)
    object.__setattr__(request, "folds", (fold_request, fold_b))
    object.__setattr__(request, "project_root", project)
    context = object.__new__(runtime.SuccessorStageContext)
    object.__setattr__(context, "fold", "fold_001")
    object.__setattr__(context, "request", request)

    unsorted = (
        _ref(node_id="snapshot", stage="snapshot"),
        _ref(node_id="provider", stage="provider"),
    )
    assert tuple(item.node_id for item in unsorted) != tuple(
        sorted(item.node_id for item in unsorted)
    )
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        upstream.run_successor_upstream_wave(
            wave="provider-validation",
            request=fold_request,
            context=context,
            runner=_Runner(),
            public_apis=object.__new__(runtime.SuccessorPublicApiBundle),
            prior_refs=unsorted,
            resume=False,
        )
    assert error.value.code == "SUCCESSOR_STAGE_INVALID"


def test_adapter_run_fold_sorts_prior_refs_before_dispatch() -> None:
    source = Path(runtime.__file__).read_text(encoding="utf-8")
    assert "prior_refs=tuple(sorted(refs, key=lambda item: item.node_id))" in source
    assert "_wave_cache" not in source.split("class ProductionSuccessorStageAdapter")[1].split(
        "def verify_fold"
    )[0]


def test_same_process_registry_forces_resume_via_real_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise ``run_successor_upstream_wave`` effective_resume, not a local reimplementation."""

    upstream._reset_wave_registry_for_tests()
    observed: list[bool] = []
    project = type(Path())(tmp_path / "proj")
    project.mkdir()

    def handler(**kwargs: object) -> tuple[runtime.StageReceiptRef, ...]:
        observed.append(bool(kwargs["resume"]))
        return (_ref(node_id="snapshot", stage="snapshot"),)

    class _Runner:
        pass

    monkeypatch.setitem(upstream._WAVE_HANDLERS, "snapshot", handler)
    monkeypatch.setattr(
        upstream, "_require_canonical_public_api_bundle", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        upstream,
        "compute_upstream_wave_transition_identity",
        lambda **_k: _hex("transition"),
    )

    class _Frozen:
        def __init__(self, **kwargs: object) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    monkeypatch.setattr(upstream, "UpstreamWaveContext", _Frozen)
    monkeypatch.setattr(
        upstream, "_toolchain_identity_for_context", lambda _c: "toolchain"
    )
    monkeypatch.setattr(
        upstream,
        "_registry_key",
        lambda **_k: ("id", "root", "snapshot", "toolchain"),
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

    fold_request = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_request, "fold", "fold_001")
    fold_b = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_b, "fold", "fold_002")
    request = object.__new__(runtime.SuccessorRuntimeRequest)
    object.__setattr__(request, "folds", (fold_request, fold_b))
    object.__setattr__(request, "project_root", project)
    context = object.__new__(runtime.SuccessorStageContext)
    object.__setattr__(context, "fold", "fold_001")
    object.__setattr__(context, "request", request)

    public_apis = object.__new__(runtime.SuccessorPublicApiBundle)
    first = upstream.run_successor_upstream_wave(
        wave="snapshot",
        request=fold_request,
        context=context,
        runner=_Runner(),
        public_apis=public_apis,
        prior_refs=(),
        resume=False,
    )
    second = upstream.run_successor_upstream_wave(
        wave="snapshot",
        request=fold_request,
        context=context,
        runner=_Runner(),
        public_apis=public_apis,
        prior_refs=(),
        resume=False,
    )
    assert observed == [False, True]
    assert first == second
    assert first[0].sha256 == second[0].sha256


def test_unique_horizon_ref_map_rejects_duplicate_missing_extra() -> None:
    canonical = (5, 10)
    ok = (
        _ref(node_id="labels-h10", stage="labels", horizon=10),
        _ref(node_id="labels-h5", stage="labels", horizon=5),
    )
    mapping = upstream._unique_horizon_ref_map(ok, canonical_horizons=canonical)
    assert set(mapping) == {5, 10}
    assert mapping[5].node_id == "labels-h5"

    duplicate = (
        _ref(node_id="labels-a", stage="labels", horizon=5),
        _ref(node_id="labels-b", stage="labels", horizon=5),
    )
    with pytest.raises(runtime.SuccessorRuntimeError) as dup:
        upstream._unique_horizon_ref_map(duplicate, canonical_horizons=canonical)
    assert dup.value.code == "SUCCESSOR_STAGE_INVALID"

    missing = (_ref(node_id="labels-h5", stage="labels", horizon=5),)
    with pytest.raises(runtime.SuccessorRuntimeError) as miss:
        upstream._unique_horizon_ref_map(missing, canonical_horizons=canonical)
    assert miss.value.code == "SUCCESSOR_STAGE_INVALID"

    extra_h20 = object.__new__(runtime.StageReceiptRef)
    object.__setattr__(extra_h20, "node_id", "labels-h20")
    object.__setattr__(extra_h20, "stage", "labels")
    object.__setattr__(extra_h20, "scope", "EXPERIMENT")
    object.__setattr__(extra_h20, "scope_key", _hex("labels-h20"))
    object.__setattr__(extra_h20, "relative_path", "receipts/labels/labels-h20.json")
    object.__setattr__(extra_h20, "sha256", _hex("receipt:labels-h20"))
    object.__setattr__(extra_h20, "fold", None)
    object.__setattr__(extra_h20, "horizon", 20)
    extra = (
        _ref(node_id="labels-h5", stage="labels", horizon=5),
        _ref(node_id="labels-h10", stage="labels", horizon=10),
        extra_h20,
    )
    with pytest.raises(runtime.SuccessorRuntimeError) as ext:
        upstream._unique_horizon_ref_map(extra, canonical_horizons=canonical)
    assert ext.value.code == "SUCCESSOR_STAGE_INVALID"


def test_reconciliation_horizon_map_same_closure_rules() -> None:
    canonical = (5, 10)
    duplicate = (
        _ref(node_id="recon-a", stage="label-reconciliation", horizon=5),
        _ref(node_id="recon-b", stage="label-reconciliation", horizon=5),
    )
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        upstream._unique_horizon_ref_map(duplicate, canonical_horizons=canonical)
    assert error.value.code == "SUCCESSOR_STAGE_INVALID"


def test_registry_preseed_poison_does_not_elevate_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream._reset_wave_registry_for_tests()
    observed: list[bool] = []
    project = type(Path())(tmp_path / "proj")
    project.mkdir()
    key = ("id", "root", "snapshot", "toolchain")

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
    monkeypatch.setattr(
        upstream, "_toolchain_identity_for_context", lambda _c: "toolchain"
    )
    monkeypatch.setattr(upstream, "_registry_key", lambda **_k: key)
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

    # Pre-seed plain refs (forgeable poison) — must NOT authorize resume.
    with upstream._REGISTRY_LOCK:
        upstream._WAVE_REGISTRY[key] = (  # type: ignore[assignment]
            _ref(node_id="snapshot", stage="snapshot"),
        )

    fold_request = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_request, "fold", "fold_001")
    fold_b = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_b, "fold", "fold_002")
    request = object.__new__(runtime.SuccessorRuntimeRequest)
    object.__setattr__(request, "folds", (fold_request, fold_b))
    object.__setattr__(request, "project_root", project)
    context = object.__new__(runtime.SuccessorStageContext)
    object.__setattr__(context, "fold", "fold_001")
    object.__setattr__(context, "request", request)

    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        upstream.run_successor_upstream_wave(
            wave="snapshot",
            request=fold_request,
            context=context,
            runner=_Runner(),
            public_apis=object.__new__(runtime.SuccessorPublicApiBundle),
            prior_refs=(),
            resume=False,
        )
    assert error.value.code == "SUCCESSOR_STAGE_INVALID"
    assert observed == []


def test_partial_multi_node_failure_does_not_register_or_elevate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream._reset_wave_registry_for_tests()
    observed: list[bool] = []
    project = type(Path())(tmp_path / "proj")
    project.mkdir()
    key = ("id", "root", "experiment-artifacts", "toolchain")
    calls = {"n": 0}

    def handler(**kwargs: object) -> tuple[runtime.StageReceiptRef, ...]:
        observed.append(bool(kwargs["resume"]))
        calls["n"] += 1
        if calls["n"] == 1:
            # Simulate multi-node wave: first nodes "published" then fail before return.
            raise runtime.SuccessorRuntimeError("SUCCESSOR_STAGE_INVALID")
        return (
            _ref(node_id="folds", stage="folds"),
            _ref(node_id="labels.h10", stage="labels", horizon=10),
            _ref(node_id="labels.h5", stage="labels", horizon=5),
        )

    class _Runner:
        pass

    class _Frozen:
        def __init__(self, **kwargs: object) -> None:
            for name, value in kwargs.items():
                setattr(self, name, value)

    monkeypatch.setitem(upstream._WAVE_HANDLERS, "experiment-artifacts", handler)
    monkeypatch.setattr(
        upstream, "_require_canonical_public_api_bundle", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        upstream,
        "compute_upstream_wave_transition_identity",
        lambda **_k: _hex("transition"),
    )
    monkeypatch.setattr(upstream, "UpstreamWaveContext", _Frozen)
    monkeypatch.setattr(
        upstream, "_toolchain_identity_for_context", lambda _c: "toolchain"
    )
    monkeypatch.setattr(upstream, "_registry_key", lambda **_k: key)
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

    fold_request = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_request, "fold", "fold_001")
    fold_b = object.__new__(runtime.SuccessorFoldRequest)
    object.__setattr__(fold_b, "fold", "fold_002")
    request = object.__new__(runtime.SuccessorRuntimeRequest)
    object.__setattr__(request, "folds", (fold_request, fold_b))
    object.__setattr__(request, "project_root", project)
    context = object.__new__(runtime.SuccessorStageContext)
    object.__setattr__(context, "fold", "fold_001")
    object.__setattr__(context, "request", request)
    public_apis = object.__new__(runtime.SuccessorPublicApiBundle)

    with pytest.raises(runtime.SuccessorRuntimeError):
        upstream.run_successor_upstream_wave(
            wave="experiment-artifacts",
            request=fold_request,
            context=context,
            runner=_Runner(),
            public_apis=public_apis,
            prior_refs=(),
            resume=False,
        )
    with upstream._REGISTRY_LOCK:
        assert key not in upstream._WAVE_REGISTRY

    # Retry with resume=False must not be elevated by partial failure residue.
    second = upstream.run_successor_upstream_wave(
        wave="experiment-artifacts",
        request=fold_request,
        context=context,
        runner=_Runner(),
        public_apis=public_apis,
        prior_refs=(),
        resume=False,
    )
    assert observed == [False, False]
    assert len(second) == 3
    with upstream._REGISTRY_LOCK:
        sealed = upstream._WAVE_REGISTRY[key]
    assert type(sealed) is upstream._CanonicalWaveSuccess
    assert sealed.authorized()


def test_toolchain_rejects_python_and_dump_symlink_or_link_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant.research.m3.config import LoadedM3Config
    from quant.research.m3.contracts import QlibDumpToolSpec

    project = type(Path())(tmp_path / "project")
    project.mkdir()
    real_python = type(Path())(tmp_path / "real-python.exe")
    real_python.write_bytes(b"py")
    real_dump = type(Path())(project / DEFAULT_TARGET_PATH)
    real_dump.parent.mkdir(parents=True)
    payload = b"dump-bytes"
    real_dump.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(
        "quant.research.m3.fetch_qlib_tool.build_qlib_dump_tool_spec",
        lambda _config: QlibDumpToolSpec(
            url="https://example.test/dump_bin.py",
            sha256=digest,
            size_bytes=len(payload),
            qlib_version="0.9.7",
            command="dump_all",
        ),
    )
    cfg_a = object.__new__(LoadedM3Config)
    cfg_b = object.__new__(LoadedM3Config)

    def _reject_leaf(leaf: Path, *, as_python: bool) -> None:
        binding = runtime.SuccessorToolchainBinding(
            python_executable=leaf if as_python else real_python,
            qlib_dump_tool_path=real_dump if as_python else leaf,
            timeout_seconds=1.5,
        )
        with pytest.raises(runtime.SuccessorRuntimeError) as error:
            upstream.validate_successor_toolchain_binding(
                project_root=project,
                toolchain=binding,
                fold_configs=(cfg_a, cfg_b),
            )
        assert error.value.code == "SUCCESSOR_INPUT_INVALID"

    # Prefer real symlink leaves; if the host forbids creation, inject ISLNK via lstat.
    for label, real, as_python in (
        ("python", real_python, True),
        ("dump", real_dump, False),
    ):
        link = type(Path())(tmp_path / f"{label}-link")
        created = False
        try:
            link.symlink_to(real)
            created = True
        except OSError:
            created = False
        if created:
            _reject_leaf(link, as_python=as_python)
            continue
        real_lstat = upstream.os.lstat

        def marked_lstat(path: object, _real=real, _lstat=real_lstat):
            status = _lstat(path)
            if Path(path) == _real:
                values = {
                    name: getattr(status, name)
                    for name in dir(status)
                    if name.startswith("st_")
                }
                values["st_mode"] = (
                    getattr(status, "st_mode", 0) | __import__("stat").S_IFLNK
                )
                # Force ISLNK true while keeping other fields.
                import stat as stat_mod

                values["st_mode"] = stat_mod.S_IFLNK | 0o777
                return SimpleNamespace(**values)
            return status

        monkeypatch.setattr(upstream.os, "lstat", marked_lstat)
        _reject_leaf(real, as_python=as_python)
        monkeypatch.setattr(upstream.os, "lstat", real_lstat)


def test_toolchain_rejects_windows_reparse_attribute_injection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant.research.m3.config import LoadedM3Config
    from quant.research.m3.contracts import QlibDumpToolSpec

    project = type(Path())(tmp_path / "project")
    project.mkdir()
    python = type(Path())(tmp_path / "python.exe")
    python.write_bytes(b"py")
    dump = type(Path())(project / DEFAULT_TARGET_PATH)
    dump.parent.mkdir(parents=True)
    payload = b"dump"
    dump.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(
        "quant.research.m3.fetch_qlib_tool.build_qlib_dump_tool_spec",
        lambda _config: QlibDumpToolSpec(
            url="https://example.test/dump_bin.py",
            sha256=digest,
            size_bytes=len(payload),
            qlib_version="0.9.7",
            command="dump_all",
        ),
    )
    cfg_a = object.__new__(LoadedM3Config)
    cfg_b = object.__new__(LoadedM3Config)
    real_lstat = upstream.os.lstat

    for leaf in (python, dump):
        def marked_lstat(path: object, _leaf=leaf, _lstat=real_lstat):
            status = _lstat(path)
            if Path(path) == _leaf:
                values = {
                    name: getattr(status, name)
                    for name in dir(status)
                    if name.startswith("st_")
                }
                values["st_file_attributes"] = 0x400
                return SimpleNamespace(**values)
            return status

        monkeypatch.setattr(upstream.os, "lstat", marked_lstat)
        binding = runtime.SuccessorToolchainBinding(
            python_executable=python,
            qlib_dump_tool_path=dump,
            timeout_seconds=1.0,
        )
        with pytest.raises(runtime.SuccessorRuntimeError) as error:
            upstream.validate_successor_toolchain_binding(
                project_root=project,
                toolchain=binding,
                fold_configs=(cfg_a, cfg_b),
            )
        assert error.value.code == "SUCCESSOR_INPUT_INVALID"
        monkeypatch.setattr(upstream.os, "lstat", real_lstat)


def _load_sibling_test_module(filename: str, module_name: str) -> object:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        module_name, Path(__file__).with_name(filename),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plan_provider_probe_positive_real_call_with_valid_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unmocked plan_provider_probe with identity-closed formal fixtures + valid spec."""

    import inspect

    from quant.research.m3.contracts import (
        ProviderProbePlan,
        ProviderValidationSpec,
        VerifiedProviderArtifact,
        VerifiedSnapshotArtifact,
    )
    from quant.research.m3.provider_validation import plan_provider_probe
    from quant.research.m3.run_state import compute_provider_validation_key

    feature_support = _load_sibling_test_module(
        "test_m3_formal_feature_artifact.py",
        "upstream_formal_feature_support_for_probe",
    )
    common = tmp_path / "artifacts"
    common.mkdir()
    release = feature_support._verified_g1(common / "g1", monkeypatch)
    config = feature_support._formal_config(tmp_path, release)
    snapshot, _snapshot_spec, snapshot_request, snapshot_receipt = feature_support._snapshot(
        common, release, config,
    )
    provider, _provider_spec, _tool, _provider_receipt = feature_support._provider(
        common, snapshot, config, snapshot_request, snapshot_receipt, monkeypatch,
    )
    assert type(snapshot) is VerifiedSnapshotArtifact
    assert type(provider) is VerifiedProviderArtifact

    code_version = "successor-upstream-probe-boundary-v1"
    validation_spec = ProviderValidationSpec(
        provider_validation_key=compute_provider_validation_key(
            provider_key=provider.manifest.provider_key,
            provider_receipt_sha256=provider.provider_receipt_sha256,
            provider_validation_config_sha256=config.provider_validation_config_sha256,
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

    params = inspect.signature(plan_provider_probe).parameters
    assert "spec" in params and params["spec"].default is inspect.Parameter.empty
    source = Path(upstream.__file__).read_text(encoding="utf-8")
    assert "spec=validation_spec" in source

    plan = plan_provider_probe(
        snapshot=snapshot,
        provider=provider,
        config=config,
        spec=validation_spec,
    )
    assert type(plan) is ProviderProbePlan
    assert plan.provider_validation_key == validation_spec.provider_validation_key
    assert plan.provider_key == provider.manifest.provider_key
    assert plan.snapshot_id == snapshot.manifest.snapshot_id
    assert len(plan.selected_rows) == 60
    assert len({symbol for symbol, _day in plan.selected_rows}) == 3

    from quant.research.m3.provider_validation import M3ProviderValidationError

    drifted = replace(
        validation_spec,
        provider_validation_key=_hex("drifted-provider-validation-key"),
    )
    with pytest.raises(M3ProviderValidationError) as drift_error:
        plan_provider_probe(
            snapshot=snapshot,
            provider=provider,
            config=config,
            spec=drifted,
        )
    assert drift_error.value.code == "PROVIDER_VALIDATION_INPUT_INVALID"


def test_plan_provider_probe_rejects_missing_or_wrong_spec() -> None:
    from quant.research.m3.contracts import ProviderValidationSpec
    from quant.research.m3.provider_validation import (
        M3ProviderValidationError,
        plan_provider_probe,
    )

    with pytest.raises(M3ProviderValidationError) as missing:
        plan_provider_probe(
            snapshot=object(),
            provider=object(),
            config=object(),
        )
    assert missing.value.code == "PROVIDER_VALIDATION_INPUT_INVALID"

    wrong_spec = ProviderValidationSpec(
        provider_validation_key=_hex("wrong-validation-key"),
        provider_validation_config_sha256=_hex("wrong-validation-config"),
        code_version="wrong-spec-v1",
        qlib_version="0.9.7",
        sampling_policy_version="provider_market_stratified_hash_first_last_v1",
        worker_protocol_version="m3-qlib-worker-v1",
    )
    with pytest.raises(M3ProviderValidationError) as wrong:
        plan_provider_probe(
            snapshot=object(),
            provider=object(),
            config=object(),
            spec=wrong_spec,
        )
    assert wrong.value.code == "PROVIDER_VALIDATION_INPUT_INVALID"


def test_build_backtest_plan_artifact_positive_project_only_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unmocked build_backtest_plan_artifact with explicit PROJECT-only artifact_roots."""

    import inspect

    import quant.backtest.a_share_plan as plan_module
    from quant.backtest.a_share_plan import build_backtest_plan_artifact
    from quant.research.m3.contracts import BacktestPlanManifestV1

    plan_support = _load_sibling_test_module(
        "test_m3_formal_backtest_plan_artifact.py",
        "upstream_formal_plan_support_for_roots",
    )
    context = plan_support._context(tmp_path, monkeypatch)
    kwargs = dict(context["plan_kwargs"])
    project_root = type(Path())(context["common"])
    target = kwargs["target"]
    # Isolate PROJECT alias binding: fixture receipts use "root"; production
    # successor path is PROJECT-only. Stub only fresh target verify (not the builder).
    monkeypatch.setattr(plan_module, "verify_target_artifact", lambda **_: target)

    params = inspect.signature(build_backtest_plan_artifact).parameters
    assert "artifact_roots" in params
    assert params["artifact_roots"].default is inspect.Parameter.empty
    source = Path(upstream.__file__).read_text(encoding="utf-8")
    assert 'artifact_roots={"PROJECT": project_root}' in source

    output_root = project_root / "formal-plan-project-only"
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
    assert manifest.experiment_key == target.manifest.experiment_key
    assert (output_root / "manifest.json").is_file()
    assert (output_root / "scheduled_targets.parquet").is_file()


def test_build_backtest_plan_artifact_rejects_wrong_alias_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quant.backtest.a_share_plan import build_backtest_plan_artifact

    plan_support = _load_sibling_test_module(
        "test_m3_formal_backtest_plan_artifact.py",
        "upstream_formal_plan_support_for_wrong_alias",
    )
    context = plan_support._context(tmp_path, monkeypatch)
    kwargs = dict(context["plan_kwargs"])
    project_root = type(Path())(context["common"])
    output_root = project_root / "formal-plan-wrong-alias"
    output_root.mkdir()
    with pytest.raises(ValueError, match="^M3_BACKTEST_PLAN_ARTIFACT_INVALID$"):
        build_backtest_plan_artifact(
            target=kwargs["target"],
            release=kwargs["release"],
            folds=kwargs["folds"],
            experiment=kwargs["experiment"],
            config=kwargs["config"],
            fresh_context=kwargs["fresh_context"],
            artifact_roots={"EXTERNAL_QLIB": project_root},
            output_root=output_root,
        )
    assert not any(output_root.iterdir())


def test_backtest_plan_fresh_context_imports_from_a_share_plan_not_contracts() -> None:
    import importlib
    import quant.backtest.a_share_plan as a_share_plan
    import quant.research.m3.contracts as contracts

    loaded = importlib.import_module("quant.backtest.a_share_plan")
    assert hasattr(loaded, "BacktestPlanFreshVerificationContext")
    assert (
        loaded.BacktestPlanFreshVerificationContext
        is a_share_plan.BacktestPlanFreshVerificationContext
    )
    assert not hasattr(contracts, "BacktestPlanFreshVerificationContext")
    source = Path(upstream.__file__).read_text(encoding="utf-8")
    assert "from quant.backtest.a_share_plan import (" in source
    assert "BacktestPlanFreshVerificationContext," in source
    # Must not appear in any contracts import block of the production module.
    for block in source.split("from quant.research.m3.contracts import"):
        if block is source.split("from quant.research.m3.contracts import")[0]:
            continue
        head = block.split(")", 1)[0]
        assert "BacktestPlanFreshVerificationContext" not in head


def test_require_horizon_rejects_none_and_illegal_int() -> None:
    assert upstream._require_horizon(5) == 5
    assert upstream._require_horizon(10) == 10
    with pytest.raises(runtime.SuccessorRuntimeError) as none_error:
        upstream._require_horizon(None)
    assert none_error.value.code == "SUCCESSOR_STAGE_INVALID"
    with pytest.raises(runtime.SuccessorRuntimeError) as bad_error:
        upstream._require_horizon(7)
    assert bad_error.value.code == "SUCCESSOR_STAGE_INVALID"
    with pytest.raises(runtime.SuccessorRuntimeError) as bool_error:
        upstream._require_horizon(True)
    assert bool_error.value.code == "SUCCESSOR_STAGE_INVALID"


def test_require_path_rejects_none_for_optional_alignment_pattern() -> None:
    with pytest.raises(runtime.SuccessorRuntimeError) as error:
        upstream._require_path(None)
    assert error.value.code == "SUCCESSOR_STAGE_INVALID"
    concrete = type(Path())("C:/tmp/alignment_receipt.json")
    assert upstream._require_path(concrete) is concrete


def test_require_toolchain_and_frequency_reject_illegal_shapes() -> None:
    with pytest.raises(runtime.SuccessorRuntimeError) as missing:
        upstream._require_toolchain(None)
    assert missing.value.code == "SUCCESSOR_INPUT_INVALID"
    with pytest.raises(runtime.SuccessorRuntimeError) as bad_freq:
        upstream._require_frequency("week")
    assert bad_freq.value.code == "SUCCESSOR_STAGE_INVALID"
    assert upstream._require_frequency("day") == "day"
