"""Static-contract tests for the package-owned successor boundary."""

from __future__ import annotations

import datetime as dt
import hashlib
import stat
from dataclasses import asdict, replace
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Literal

import pytest

import quant.research.m3.successor_runtime as runtime
from quant.data.m3_release import VerifiedG1Release
from quant.research.m3.config import LoadedM3Config
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


def _validation_config(*, raw: str, full: str, scientific: str) -> LoadedM3Config:
    config = object.__new__(LoadedM3Config)
    object.__setattr__(config, "document", {"tracking": {"artifact_root": "output/stage"}})
    object.__setattr__(config, "config_version", "unit-config-v1")
    object.__setattr__(config, "full_config_sha256", full)
    object.__setattr__(config, "g1_config_sha256", _hex(f"g1:{raw}"))
    object.__setattr__(config, "snapshot_config_sha256", _hex(f"snapshot:{raw}"))
    object.__setattr__(config, "provider_config_sha256", _hex(f"provider:{raw}"))
    object.__setattr__(config, "scientific_config_sha256", scientific)
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
    object.__setattr__(config, "canonical_tracking_uri", "file:///unit-test")
    object.__setattr__(config, "tracking_target_key", _hex(f"tracking:{raw}"))
    object.__setattr__(config, "raw_config_sha256", raw)
    return config


def _validation_release(*, project: Path, identity: str, suffix: str) -> VerifiedG1Release:
    root = project / "g1" / suffix
    root.mkdir(parents=True)
    release = SimpleNamespace(root=root, release_id=identity)
    manifest = SimpleNamespace(release_id=identity)
    verified = object.__new__(VerifiedG1Release)
    object.__setattr__(verified, "release", release)
    object.__setattr__(verified, "manifest", manifest)
    object.__setattr__(verified, "manifest_sha256", _hex(f"manifest:{suffix}"))
    object.__setattr__(verified, "quality", SimpleNamespace())
    object.__setattr__(verified, "quality_sha256", _hex(f"quality:{suffix}"))
    object.__setattr__(verified, "artifact_paths", ())
    return verified


def _validation_request(
    tmp_path: Path, *, duplicate_release: bool = False
) -> tuple[
    runtime.SuccessorRuntimeRequest,
    dict[Path, LoadedM3Config],
    dict[str, VerifiedG1Release],
]:
    project = tmp_path / "project"
    (project / "configs").mkdir(parents=True)
    (project / "output" / "stage").mkdir(parents=True)
    raw_bytes = b"shared-config"
    raw = hashlib.sha256(raw_bytes).hexdigest()
    config = _validation_config(
        raw=raw,
        full=_hex("full:shared"),
        scientific=_hex("scientific:shared"),
    )
    configs: dict[Path, LoadedM3Config] = {}
    releases: dict[str, VerifiedG1Release] = {}
    folds: list[runtime.SuccessorFoldRequest] = []
    shared_path = project / "configs" / "shared.toml"
    shared_path.write_bytes(raw_bytes)
    configs[shared_path.resolve()] = config
    (project / "configs" / "unbound.toml").write_bytes(b"unbound")
    for fold in ("fold_001", "fold_002"):
        release = _validation_release(
            project=project,
            identity=_hex(f"release:{fold}"),
            suffix=fold,
        )
        releases[release.release.release_id] = release
        folds.append(
            runtime.SuccessorFoldRequest(
                fold=fold,
                config=runtime.SuccessorConfigInput(
                    relative_path=PurePosixPath("configs/shared.toml"),
                    config=config,
                ),
                release=release,
            )
        )
    if duplicate_release:
        folds[1] = replace(folds[1], release=folds[0].release)
    request = runtime.SuccessorRuntimeRequest(
        project_root=project,
        controlled_output_root=project / "output" / "stage",
        folds=tuple(folds),
        runtime_identity=SuccessorRuntimeIdentity(
            code_version="unit-successor-v1",
            dependency_fingerprint_sha256=_hex("dependencies"),
            provider_runtime_fingerprint_sha256=_hex("provider-runtime"),
        ),
        now=dt.datetime(2026, 8, 23, 12, 0, tzinfo=dt.timezone.utc),
        toolchain=runtime.SuccessorToolchainBinding(
            python_executable=project / "python.exe",
            qlib_dump_tool_path=project / "dump_bin.py",
            timeout_seconds=30.0,
        ),
    )
    return request, configs, releases


def _patch_request_validation(
    monkeypatch: pytest.MonkeyPatch,
    configs: dict[Path, LoadedM3Config],
    releases: dict[str, VerifiedG1Release],
    load_calls: list[Path],
    release_calls: list[str],
) -> None:
    import quant.research.m3.successor_upstream_stage as upstream

    def load(path: Path) -> LoadedM3Config:
        load_calls.append(path.resolve())
        return configs[path.resolve()]

    def verify(release: object) -> VerifiedG1Release:
        assert isinstance(release, SimpleNamespace)
        release_calls.append(release.release_id)
        return releases[release.release_id]

    monkeypatch.setattr(runtime, "load_m3_config", load)
    monkeypatch.setattr(runtime, "verify_g1_release", verify)
    monkeypatch.setattr(
        runtime,
        "_resolve_canonical_g8_stage_root",
        lambda candidate: candidate.controlled_output_root,
    )
    monkeypatch.setattr(
        upstream,
        "validate_successor_toolchain_binding",
        lambda **_kwargs: (
            "/unit/python",
            "data/external/qlib/v0.9.7/dump_bin.py",
            4,
            _hex("dump-bytes"),
        ),
    )


def test_validate_request_allows_shared_config_with_two_fresh_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, configs, releases = _validation_request(tmp_path)
    load_calls: list[Path] = []
    release_calls: list[str] = []
    _patch_request_validation(
        monkeypatch, configs, releases, load_calls, release_calls
    )

    runtime._validate_request(request)

    assert tuple(item.config.relative_path for item in request.folds) == (
        PurePosixPath("configs/shared.toml"),
        PurePosixPath("configs/shared.toml"),
    )
    assert (
        request.folds[0].release.manifest.release_id
        != request.folds[1].release.manifest.release_id
    )
    assert load_calls == [
        (request.project_root / "configs" / "shared.toml").resolve(),
        (request.project_root / "configs" / "shared.toml").resolve(),
    ]
    assert len(release_calls) == 2


def test_validate_request_rejects_duplicate_release_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, configs, releases = _validation_request(tmp_path, duplicate_release=True)
    load_calls: list[Path] = []
    release_calls: list[str] = []
    _patch_request_validation(
        monkeypatch, configs, releases, load_calls, release_calls
    )

    with pytest.raises(SuccessorRuntimeError) as error:
        runtime._validate_request(request)

    assert error.value.code == "SUCCESSOR_INPUT_INVALID"
    assert len(load_calls) == 2
    assert len(release_calls) == 2


def test_validate_request_rejects_second_shared_load_config_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, configs, releases = _validation_request(tmp_path)
    shared_path = (request.project_root / "configs" / "shared.toml").resolve()
    load_calls: list[Path] = []
    read_calls: list[Path] = []
    release_calls: list[str] = []
    original_config = configs[shared_path]
    drifted_config = _validation_config(
        raw=original_config.raw_config_sha256 or "",
        full=_hex("full:drift"),
        scientific=original_config.scientific_config_sha256,
    )

    def load(path: Path) -> LoadedM3Config:
        load_calls.append(path.resolve())
        return original_config if len(load_calls) == 1 else drifted_config

    monkeypatch.setattr(runtime, "load_m3_config", load)
    original_read = runtime._read_regular_file

    def read(path: Path) -> bytes:
        read_calls.append(path.resolve())
        return original_read(path)

    monkeypatch.setattr(runtime, "_read_regular_file", read)
    monkeypatch.setattr(
        runtime,
        "verify_g1_release",
        lambda release: (
            release_calls.append(release.release_id),
            releases[release.release_id],
        )[1],
    )
    monkeypatch.setattr(
        runtime,
        "_resolve_canonical_g8_stage_root",
        lambda candidate: candidate.controlled_output_root,
    )
    import quant.research.m3.successor_upstream_stage as upstream

    monkeypatch.setattr(
        upstream,
        "validate_successor_toolchain_binding",
        lambda **_kwargs: (
            "/unit/python",
            "data/external/qlib/v0.9.7/dump_bin.py",
            4,
            _hex("dump-bytes"),
        ),
    )

    with pytest.raises(SuccessorRuntimeError) as error:
        runtime._validate_request(request)

    assert error.value.code == "SUCCESSOR_INPUT_INVALID"
    assert read_calls == [shared_path, shared_path]
    assert load_calls == [shared_path, shared_path]
    assert len(release_calls) == 1


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
            receipt_refs=(
                StageReceiptRef(
                    node_id="readiness-global",
                    stage="readiness-evidence",
                    scope="ACCEPTANCE",
                    scope_key=_hex("readiness:global"),
                    relative_path="receipts/readiness-evidence/global.json",
                    sha256=_hex("readiness-a"),
                    fold=None,
                    horizon=None,
                ),
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


def test_validate_gate_rejects_readiness_cardinality_two() -> None:
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
                node_id="readiness-a",
                stage="readiness-evidence",
                scope="ACCEPTANCE",
                scope_key=collided,
                relative_path="receipts/readiness-evidence/a.json",
                sha256=_hex("readiness-a"),
                fold=None,
                horizon=None,
            ),
            StageReceiptRef(
                node_id="readiness-b",
                stage="readiness-evidence",
                scope="ACCEPTANCE",
                scope_key=_hex("readiness:other"),
                relative_path="receipts/readiness-evidence/b.json",
                sha256=_hex("readiness-b"),
                fold=None,
                horizon=None,
            ),
        ),
    )
    with pytest.raises(SuccessorRuntimeError) as error:
        _validate_gate_execution("readiness", gate, executions=folds, known=())
    assert error.value.code == "SUCCESSOR_GATE_FAILED"


def test_validate_gate_accepts_single_global_readiness() -> None:
    folds = _two_fold_executions()
    gate = _readiness_gate(
        folds=folds,
        refs=(
            StageReceiptRef(
                node_id="readiness-global",
                stage="readiness-evidence",
                scope="ACCEPTANCE",
                scope_key=_hex("readiness:global"),
                relative_path="receipts/readiness-evidence/global.json",
                sha256=_hex("readiness-bytes"),
                fold=None,
                horizon=None,
            ),
        ),
    )
    _validate_gate_execution("readiness", gate, executions=folds, known=())


def test_validate_gate_rejects_readiness_fold_bound_ref() -> None:
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
        ),
    )
    with pytest.raises(SuccessorRuntimeError) as error:
        _validate_gate_execution("readiness", gate, executions=folds, known=())
    assert error.value.code == "SUCCESSOR_GATE_FAILED"


def test_validate_gate_rejects_readiness_with_horizon() -> None:
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
                fold=None,
                horizon=5,
            ),
        ),
    )
    with pytest.raises(SuccessorRuntimeError) as error:
        _validate_gate_execution("readiness", gate, executions=folds, known=())
    assert error.value.code == "SUCCESSOR_GATE_FAILED"


def test_validate_gate_rejects_readiness_missing() -> None:
    folds = _two_fold_executions()
    # GateExecution itself rejects empty receipt_refs; use wrong stage instead.
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
                node_id="not-readiness",
                stage="acceptance",
                scope="ACCEPTANCE",
                scope_key=_hex("readiness:only"),
                relative_path="receipts/acceptance/only.json",
                sha256=_hex("readiness-only-bytes"),
                fold=None,
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
        node_id="gate-readiness-a",
        stage="readiness-evidence",
        scope="ACCEPTANCE",
        scope_key=_hex("readiness:a"),
        relative_path="receipts/readiness-evidence/a.json",
        sha256=shared_sha,
        fold=None,
        horizon=None,
    )
    second = StageReceiptRef(
        node_id="gate-readiness-b",
        stage="readiness-evidence",
        scope="ACCEPTANCE",
        scope_key=_hex("readiness:b"),
        relative_path="receipts/readiness-evidence/b.json",
        sha256=shared_sha,
        fold=None,
        horizon=None,
    )
    with pytest.raises(SuccessorRuntimeError) as error:
        _unique_refs((first, second))
    assert error.value.code == "SUCCESSOR_TERMINAL_INVALID"


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


def test_global_ownership_rejects_readiness_same_bytes_different_paths(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    first_path = project / "output/stage/receipts/readiness-evidence/a.json"
    second_path = project / "output/stage/receipts/readiness-evidence/b.json"
    first_path.parent.mkdir(parents=True)
    payload = b'{"stage":"readiness-evidence","identical":true}'
    first_path.write_bytes(payload)
    second_path.write_bytes(payload)
    shared_sha = hashlib.sha256(payload).hexdigest()
    first = StageReceiptRef(
        node_id="gate-readiness-a",
        stage="readiness-evidence",
        scope="ACCEPTANCE",
        scope_key=_hex("readiness:a"),
        relative_path="output/stage/receipts/readiness-evidence/a.json",
        sha256=shared_sha,
        fold=None,
        horizon=None,
    )
    second = StageReceiptRef(
        node_id="gate-readiness-b",
        stage="readiness-evidence",
        scope="ACCEPTANCE",
        scope_key=_hex("readiness:b"),
        relative_path="output/stage/receipts/readiness-evidence/b.json",
        sha256=shared_sha,
        fold=None,
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


def test_public_api_bundle_seven_stage_return_annotations_are_canonical() -> None:
    """F11: only the seven result-producing callables carry canonical return types."""

    from quant.research.m3.acceptance import AcceptanceDecisionV1
    from quant.research.m3.acceptance_stage import (
        FormalAcceptanceStageResult,
        audit_formal_m3_acceptance,
        run_formal_acceptance_stage,
    )
    from quant.research.m3.backtest_stage import (
        FormalBacktestStageResult,
        run_formal_backtest_stage,
    )
    from quant.research.m3.readiness_evidence import (
        VerifiedReadinessEvidenceArtifact,
        run_readiness_evidence_stage,
        verify_readiness_evidence_artifact,
    )
    from quant.research.m3.reproducibility import (
        FormalReproducibilityResult,
        run_formal_reproducibility_stage,
    )
    from quant.research.m3.tracking_stage import (
        FormalTrackingStageResult,
        run_formal_tracking_stage,
    )

    expected = {
        "formal_backtest_stage": "FormalBacktestStageResult",
        "formal_tracking_stage": "FormalTrackingStageResult",
        "reproducibility_stage": "FormalReproducibilityResult",
        "readiness_stage": "VerifiedReadinessEvidenceArtifact",
        "readiness_verifier": "VerifiedReadinessEvidenceArtifact",
        "acceptance_stage": "FormalAcceptanceStageResult",
        "acceptance_audit": "AcceptanceDecisionV1",
    }
    annotations = runtime.SuccessorPublicApiBundle.__annotations__
    for name, type_name in expected.items():
        text = annotations[name]
        assert text.startswith("Callable[..., ")
        assert type_name in text
        assert "object" not in text
    for name in (
        "formal_backtest_run_plan",
        "formal_tracking_run_plan",
        "summary_builder",
        "summary_verifier",
        "reproducibility_verifier",
    ):
        assert annotations[name] == "Callable[..., object]"

    bundle = runtime.make_public_successor_api_bundle()
    assert bundle.formal_backtest_stage is run_formal_backtest_stage
    assert bundle.formal_tracking_stage is run_formal_tracking_stage
    assert bundle.reproducibility_stage is run_formal_reproducibility_stage
    assert bundle.readiness_stage is run_readiness_evidence_stage
    assert bundle.readiness_verifier is verify_readiness_evidence_artifact
    assert bundle.acceptance_stage is run_formal_acceptance_stage
    assert bundle.acceptance_audit is audit_formal_m3_acceptance
    assert run_formal_backtest_stage.__annotations__["return"] in {
        "FormalBacktestStageResult",
        FormalBacktestStageResult,
    }
    assert run_formal_tracking_stage.__annotations__["return"] in {
        "FormalTrackingStageResult",
        FormalTrackingStageResult,
    }
    assert run_formal_reproducibility_stage.__annotations__["return"] in {
        "FormalReproducibilityResult",
        FormalReproducibilityResult,
    }
    assert run_readiness_evidence_stage.__annotations__["return"] in {
        "VerifiedReadinessEvidenceArtifact",
        VerifiedReadinessEvidenceArtifact,
    }
    assert verify_readiness_evidence_artifact.__annotations__["return"] in {
        "VerifiedReadinessEvidenceArtifact",
        VerifiedReadinessEvidenceArtifact,
    }
    assert run_formal_acceptance_stage.__annotations__["return"] in {
        "FormalAcceptanceStageResult",
        FormalAcceptanceStageResult,
    }
    assert audit_formal_m3_acceptance.__annotations__["return"] in {
        "AcceptanceDecisionV1",
        AcceptanceDecisionV1,
    }
