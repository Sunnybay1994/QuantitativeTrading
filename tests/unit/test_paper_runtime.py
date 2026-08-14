from __future__ import annotations

import datetime as dt
import inspect
import os
import pickle
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from quant.execution import paper_runtime as runtime

UTC_NOW = dt.datetime(2026, 8, 9, 6, 30, tzinfo=dt.timezone.utc)


def _write_config(
    tmp_path: Path,
    *,
    mode: str = "development-example",
    schema: str = "paper-runtime-config-v2",
    project_root: Path | None = None,
    roots: tuple[Path, Path, Path, Path, Path] | None = None,
    extra: str = "",
) -> tuple[Path, tuple[Path, ...]]:
    config_parent = tmp_path / "config-parent"
    config_parent.mkdir(parents=True, exist_ok=True)
    root_parent = tmp_path / "paper-parent"
    root_parent.mkdir(parents=True, exist_ok=True)
    selected = roots or tuple(
        root_parent / name for name in ("runtime", "broker", "evidence", "anchor", "log")
    )
    actual_project = project_root or runtime._actual_project_root()
    selectors = (
        ("formal_account_v1", "formal_source_v1", "formal_policy_v1", "formal_schedule_v1")
        if mode == "PAPER_REAL_TIME"
        else ("development_account", "development_source", "development_policy", "development_schedule")
    )
    config = config_parent / "runtime.toml"
    config.write_text(
        f"""
[meta]
schema_version = "{schema}"
runtime_version = "paper_runtime_v2"
mode = "{mode}"

[paths]
runtime_root = "{selected[0].as_posix()}"
broker_root = "{selected[1].as_posix()}"
evidence_root = "{selected[2].as_posix()}"
anchor_root = "{selected[3].as_posix()}"
log_root = "{selected[4].as_posix()}"
project_root = "{actual_project.as_posix()}"
{extra}

[store]
oms_sqlite_filename = "oms.sqlite3"
broker_sqlite_filename = "broker.sqlite3"

[selectors]
account_selector = "{selectors[0]}"
source_selector = "{selectors[1]}"
policy_selector = "{selectors[2]}"
expected_schedule_selector = "{selectors[3]}"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return config, selected


def _assert_sanitized(exc: runtime.PaperRuntimeError, code: str) -> None:
    assert str(exc) == code
    assert exc.__cause__ is None
    assert exc.__context__ is None


def _public_formal_environment_for_nested_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, runtime.VerifiedPaperRuntimeEnvironment]:
    if sys.platform == "win32":
        pytest.skip("formal happy path requires the frozen WSL base interpreter")
    config_path, _ = _write_config(tmp_path, mode="PAPER_REAL_TIME")
    config = runtime.load_paper_runtime_config(config_path.resolve())
    assert type(config) is runtime.FormalPaperRuntimeConfig
    layout = runtime._build_layout(config, allow_system_temp=True)
    actual = runtime._probe_actual_runtime_platform(layout.parent, UTC_NOW)
    simulated = _rehash_platform(
        replace(actual, wsl_generation="2", filesystem_type="ext4", mount_root="/")
    )
    monkeypatch.setattr(runtime, "_probe_actual_runtime_platform", lambda parent, now: simulated)
    monkeypatch.setattr(runtime, "_system_temp_root", lambda: tmp_path / "other-temp")
    environment = runtime.verify_paper_runtime_environment(config=config, now=UTC_NOW)
    return config_path, environment


def _rehash_platform(proof: runtime.RuntimePlatformProof) -> runtime.RuntimePlatformProof:
    stable = runtime._stable_platform_projection(proof)
    environment_identity = runtime._sha256(stable)
    digest = runtime._sha256(
        {**stable, "probed_at": runtime._canonical_datetime(proof.probed_at)}
    )
    return replace(proof, environment_identity=environment_identity, proof_digest=digest)


def _broker_root(roots: tuple[Path, ...]) -> Path:
    return roots[1]


def _materialize_broker_root(roots: tuple[Path, ...]) -> Path:
    broker = _broker_root(roots)
    broker.mkdir()
    return broker


def _formal_config_and_roots(
    tmp_path: Path, *, mode: str = "PAPER_REAL_TIME"
) -> tuple[Path, runtime.PaperRuntimeConfig, tuple[Path, ...]]:
    config_path, roots = _write_config(tmp_path, mode=mode)
    config = runtime.load_paper_runtime_config(config_path.resolve())
    return config_path, config, roots


def _simulated_formal_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    materialize_broker: bool = False,
) -> tuple[Path, runtime.VerifiedPaperRuntimeEnvironment, tuple[Path, ...]]:
    config_path, config, roots = _formal_config_and_roots(tmp_path)
    assert type(config) is runtime.FormalPaperRuntimeConfig
    if materialize_broker:
        _materialize_broker_root(roots)
    layout = runtime._build_layout(config, allow_system_temp=True)
    actual = runtime._probe_actual_runtime_platform(layout.parent, UTC_NOW)
    simulated = _rehash_platform(
        replace(actual, wsl_generation="2", filesystem_type="ext4", mount_root="/")
    )
    monkeypatch.setattr(runtime, "_probe_actual_runtime_platform", lambda parent, now: simulated)
    monkeypatch.setattr(runtime, "_system_temp_root", lambda: tmp_path / "other-temp")
    environment = runtime.verify_paper_runtime_environment(config=config, now=UTC_NOW)
    return config_path, environment, roots


def test_r3_public_api_is_only_formal_mint_and_has_no_generic_signer() -> None:
    parameters = inspect.signature(runtime.verify_paper_runtime_environment).parameters
    assert tuple(parameters) == ("config", "now")
    assert not hasattr(runtime, "verify_paper_runtime_preflight")
    assert not hasattr(runtime, "_build_environment")
    assert not hasattr(runtime, "_sign_environment")
    assert not hasattr(runtime, "_create_formal_environment_api")
    assert not hasattr(runtime, "_environment_attestors")
    assert not any(type(value) is bytes and len(value) == 32 for value in vars(runtime).values())
    assert not hasattr(runtime, "PaperRuntimeComponentProof")
    assert not hasattr(runtime, "PaperRuntimeComponentRole")
    assert not hasattr(runtime, "_attest_runtime_component")
    assert not hasattr(runtime, "_COMPONENT_KEY")
    for value in vars(runtime).values():
        if not callable(value):
            continue
        try:
            candidate = inspect.signature(value)
        except (TypeError, ValueError):
            continue
        accepts_projection = {"config", "layout", "platform_proof"}.issubset(
            candidate.parameters
        )
        assert not (
            accepts_projection
            and candidate.return_annotation is runtime.VerifiedPaperRuntimeEnvironment
        )


def test_r2_windows_temp_reproduction_cannot_obtain_valid_formal_capability(
    tmp_path: Path,
) -> None:
    config_path, roots = _write_config(tmp_path, mode="PAPER_REAL_TIME")
    config = runtime.load_paper_runtime_config(config_path.resolve())
    assert type(config) is runtime.FormalPaperRuntimeConfig
    layout = runtime._build_layout(config, allow_system_temp=True)
    platform_proof = runtime._probe_actual_runtime_platform(layout.parent, UTC_NOW)
    assert type(layout) is runtime.PaperRuntimeLayout
    assert type(platform_proof) is runtime.RuntimePlatformProof
    with pytest.raises(runtime.PaperRuntimeError) as caught:
        runtime.verify_paper_runtime_environment(config=config, now=UTC_NOW)
    _assert_sanitized(caught.value, "PAPER_RUNTIME_PLATFORM_UNSUPPORTED")
    with pytest.raises(runtime.PaperRuntimeError) as development:
        runtime.verify_development_paper_runtime_preflight(config=config, now=UTC_NOW)
    _assert_sanitized(development.value, "PAPER_RUNTIME_MODE_INVALID")
    assert not any(root.exists() for root in roots)

    forged = runtime.VerifiedPaperRuntimeEnvironment(
        schema_version="paper-runtime-environment-v2",
        config=config,
        layout=layout,
        platform=platform_proof,
        verified_at=UTC_NOW,
        verification_identity="f" * 64,
        _attestation=runtime._EnvironmentAttestation(b"caller-token"),
    )
    with pytest.raises(runtime.PaperRuntimeError) as invalid:
        runtime.verify_existing_paper_runtime_preflight(
            forged, config_path=config_path.resolve(), now=UTC_NOW
        )
    _assert_sanitized(invalid.value, "PAPER_RUNTIME_PREFLIGHT_INVALID")


@pytest.mark.parametrize("hostile", [{}, object()])
def test_dict_object_and_object_new_cannot_pass_existing_verifier(
    tmp_path: Path, hostile: object
) -> None:
    config_path, _ = _write_config(tmp_path, mode="PAPER_REAL_TIME")
    values = (hostile, object.__new__(runtime.VerifiedPaperRuntimeEnvironment))
    for value in values:
        with pytest.raises(runtime.PaperRuntimeError) as caught:
            runtime.verify_existing_paper_runtime_preflight(
                value,  # type: ignore[arg-type]
                config_path=config_path.resolve(),
                now=UTC_NOW,
            )
        _assert_sanitized(caught.value, "PAPER_RUNTIME_PREFLIGHT_INVALID")


@pytest.mark.skipif(sys.platform == "win32", reason="formal happy path requires WSL base")
def test_simulated_ext4_happy_path_mints_only_through_public_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, environment = _public_formal_environment_for_nested_tests(
        tmp_path, monkeypatch
    )
    assert type(environment) is runtime.VerifiedPaperRuntimeEnvironment
    runtime._verify_environment_attestation(environment)
    runtime.verify_existing_paper_runtime_preflight(
        environment, config_path=config_path.resolve(), now=UTC_NOW
    )


def test_v2_loader_binds_file_parent_bytes_and_actual_project(tmp_path: Path) -> None:
    config_path, _ = _write_config(tmp_path)
    first = runtime.load_paper_runtime_config(config_path.resolve())
    assert type(first) is runtime.DevelopmentPaperRuntimeConfig
    assert first.schema_version == "paper-runtime-config-v2"
    assert first.project_root == runtime._actual_project_root()
    assert len(first.source_file_identity) == 64
    assert len(first.source_parent_identity) == 64

    config_path.write_text(config_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    second = runtime.load_paper_runtime_config(config_path.resolve())
    assert second.raw_sha256 != first.raw_sha256
    assert second.config_identity != first.config_identity


@pytest.mark.parametrize(
    ("schema", "mode", "expected"),
    [
        ("paper-runtime-config-v1", "development-example", "PAPER_RUNTIME_CONFIG_INVALID"),
        ("paper-runtime-config-v2", "fixture", "PAPER_RUNTIME_MODE_INVALID"),
    ],
)
def test_v1_and_unknown_mode_are_exactly_rejected(
    tmp_path: Path, schema: str, mode: str, expected: str
) -> None:
    config_path, _ = _write_config(tmp_path, schema=schema, mode=mode)
    with pytest.raises(runtime.PaperRuntimeError) as caught:
        runtime.load_paper_runtime_config(config_path.resolve())
    _assert_sanitized(caught.value, expected)


def test_project_root_self_report_and_protected_roots_path_are_rejected(tmp_path: Path) -> None:
    fake_project = tmp_path / "fake-project"
    fake_project.mkdir()
    config_path, _ = _write_config(tmp_path / "fake", project_root=fake_project)
    with pytest.raises(runtime.PaperRuntimeError, match="PAPER_RUNTIME_CONFIG_INVALID"):
        runtime.load_paper_runtime_config(config_path.resolve())

    extra_path, _ = _write_config(
        tmp_path / "protected",
        extra='protected_roots = ["/caller/can/no/longer/under-report"]',
    )
    with pytest.raises(runtime.PaperRuntimeError, match="PAPER_RUNTIME_CONFIG_INVALID"):
        runtime.load_paper_runtime_config(extra_path.resolve())


def test_actual_project_tree_is_unconditionally_protected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_project = tmp_path / "actual-project"
    target_parent = fake_project / "forbidden-runtime-parent"
    target_parent.mkdir(parents=True)
    roots = tuple(
        target_parent / name for name in ("runtime", "broker", "evidence", "anchor", "log")
    )
    monkeypatch.setattr(runtime, "_actual_project_root", lambda: fake_project)
    config_path, _ = _write_config(tmp_path / "project-boundary", roots=roots)
    config = runtime.load_paper_runtime_config(config_path.resolve())
    with pytest.raises(runtime.PaperRuntimeError, match="PAPER_RUNTIME_LAYOUT_INVALID"):
        runtime.verify_development_paper_runtime_preflight(config=config, now=UTC_NOW)


def test_config_symlink_is_rejected_when_supported(tmp_path: Path) -> None:
    config_path, _ = _write_config(tmp_path)
    linked = config_path.with_name("linked-runtime.toml")
    try:
        linked.symlink_to(config_path)
    except OSError:
        pytest.skip("file symlinks are unavailable")
    with pytest.raises(runtime.PaperRuntimeError, match="PAPER_RUNTIME_CONFIG_INVALID"):
        runtime.load_paper_runtime_config(linked.absolute())


def test_loader_rejects_same_bytes_file_aba_inside_read_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, _ = _write_config(tmp_path)
    original = config_path.read_bytes()

    def replace_after_read(path: Path) -> None:
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(original)
        os.replace(replacement, path)

    monkeypatch.setattr(runtime, "_after_config_read_hook", replace_after_read)
    with pytest.raises(runtime.PaperRuntimeError) as caught:
        runtime.load_paper_runtime_config(config_path.resolve())
    _assert_sanitized(caught.value, "PAPER_RUNTIME_CONFIG_INVALID")


def test_preflight_rejects_same_bytes_file_and_parent_replacement(
    tmp_path: Path,
) -> None:
    config_path, roots = _write_config(tmp_path, mode="PAPER_REAL_TIME")
    config = runtime.load_paper_runtime_config(config_path.resolve())
    original = config_path.read_bytes()
    replacement = config_path.with_suffix(".replacement")
    replacement.write_bytes(original)
    os.replace(replacement, config_path)
    with pytest.raises(runtime.PaperRuntimeError) as caught:
        runtime.verify_paper_runtime_environment(config=config, now=UTC_NOW)
    _assert_sanitized(caught.value, "PAPER_RUNTIME_CONFIG_INVALID")
    assert not any(root.exists() for root in roots)

    other_path, _ = _write_config(tmp_path / "parent", mode="PAPER_REAL_TIME")
    other = runtime.load_paper_runtime_config(other_path.resolve())
    config_parent = other_path.parent
    moved = config_parent.with_name("old-config-parent")
    config_parent.rename(moved)
    config_parent.mkdir()
    other_path.write_bytes((moved / other_path.name).read_bytes())
    with pytest.raises(runtime.PaperRuntimeError, match="PAPER_RUNTIME_CONFIG_INVALID"):
        runtime.verify_paper_runtime_environment(config=other, now=UTC_NOW)


def test_development_environment_is_read_only_and_formal_rejects_exact_type(
    tmp_path: Path,
) -> None:
    config_path, roots = _write_config(tmp_path)
    config = runtime.load_paper_runtime_config(config_path.resolve())
    before = set(tmp_path.rglob("*"))
    environment = runtime.verify_development_paper_runtime_preflight(
        config=config, now=UTC_NOW
    )
    assert type(environment) is runtime.DevelopmentPaperRuntimeEnvironment
    assert before == set(tmp_path.rglob("*"))
    assert not any(root.exists() for root in roots)
    with pytest.raises(runtime.PaperRuntimeError) as caught:
        runtime.verify_paper_runtime_environment(config=config, now=UTC_NOW)
    _assert_sanitized(caught.value, "PAPER_RUNTIME_MODE_INVALID")


def test_actual_formal_current_platform_rejects_before_leaf_write(tmp_path: Path) -> None:
    config_path, roots = _write_config(tmp_path, mode="PAPER_REAL_TIME")
    config = runtime.load_paper_runtime_config(config_path.resolve())
    with pytest.raises(runtime.PaperRuntimeError) as caught:
        runtime.verify_paper_runtime_environment(config=config, now=UTC_NOW)
    _assert_sanitized(caught.value, "PAPER_RUNTIME_PLATFORM_UNSUPPORTED")
    assert not any(root.exists() for root in roots)


def test_parent_replacement_between_probe_and_layout_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, roots = _write_config(tmp_path)
    config = runtime.load_paper_runtime_config(config_path.resolve())
    parent = roots[0].parent

    def replace_parent(probed_parent: Path) -> None:
        moved = probed_parent.with_name("old-paper-parent")
        probed_parent.rename(moved)
        probed_parent.mkdir()

    monkeypatch.setattr(runtime, "_after_platform_probe_hook", replace_parent)
    with pytest.raises(runtime.PaperRuntimeError) as caught:
        runtime.verify_development_paper_runtime_preflight(config=config, now=UTC_NOW)
    _assert_sanitized(caught.value, "PAPER_RUNTIME_LAYOUT_INVALID")
    assert not any(root.exists() for root in roots)
    assert parent.exists()


def test_parent_replacement_before_return_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, roots = _write_config(tmp_path)
    config = runtime.load_paper_runtime_config(config_path.resolve())

    def replace_parent(parent: Path) -> None:
        moved = parent.with_name("return-old-paper-parent")
        parent.rename(moved)
        parent.mkdir()

    monkeypatch.setattr(runtime, "_before_environment_return_hook", replace_parent)
    with pytest.raises(runtime.PaperRuntimeError) as caught:
        runtime.verify_development_paper_runtime_preflight(config=config, now=UTC_NOW)
    _assert_sanitized(caught.value, "PAPER_RUNTIME_LAYOUT_INVALID")
    assert not any(root.exists() for root in roots)


def test_platform_parent_identity_must_equal_layout_parent_identity(tmp_path: Path) -> None:
    config_path, _ = _write_config(tmp_path)
    config = runtime.load_paper_runtime_config(config_path.resolve())
    layout = runtime._build_layout(config, allow_system_temp=True)
    proof = runtime._probe_actual_runtime_platform(layout.parent, UTC_NOW)
    forged = _rehash_platform(replace(proof, parent_identity="f" * 64))
    with pytest.raises(Exception, match="PAPER_RUNTIME_LAYOUT_INVALID"):
        runtime._run_platform_layout_verifier(forged, layout)


def test_non_base_prefix_cannot_be_disguised_by_base_environment_name(tmp_path: Path) -> None:
    config_path, _ = _write_config(tmp_path)
    config = runtime.load_paper_runtime_config(config_path.resolve())
    layout = runtime._build_layout(config, allow_system_temp=True)
    proof = runtime._probe_actual_runtime_platform(layout.parent, UTC_NOW)
    forged = _rehash_platform(
        replace(
            proof,
            os_name="Linux",
            wsl_generation="2",
            filesystem_type="ext4",
            mount_root="/",
            python_prefix="/home/mabw/miniforge3/envs/py312",
            conda_prefix="/home/mabw/miniforge3/envs/py312",
            python_executable="/home/mabw/miniforge3/envs/py312/bin/python",
            conda_environment="base",
        )
    )
    with pytest.raises(Exception, match="PAPER_RUNTIME_PLATFORM_UNSUPPORTED"):
        runtime._run_formal_platform_verifier(forged, layout.parent)


@pytest.mark.skipif(sys.platform == "win32", reason="frozen WSL base exists only in WSL")
def test_actual_base_with_private_ext4_projection_passes_pure_platform_contract(
    tmp_path: Path,
) -> None:
    config_path, _ = _write_config(tmp_path)
    config = runtime.load_paper_runtime_config(config_path.resolve())
    layout = runtime._build_layout(config, allow_system_temp=True)
    actual = runtime._probe_actual_runtime_platform(layout.parent, UTC_NOW)
    simulated = _rehash_platform(
        replace(actual, wsl_generation="2", filesystem_type="ext4", mount_root="/")
    )
    runtime._run_formal_platform_verifier(simulated, layout.parent)


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("layout", "parent", Path("/nested/parent/drift")),
        ("layout", "parent_identity", "e" * 64),
        ("layout", "runtime_root", Path("/nested/root/drift")),
        ("layout", "broker_root", Path("/nested/broker/drift")),
        ("layout", "root_identities", ()),
        ("layout", "layout_identity", "c" * 64),
        ("platform", "os_name", "HostileOS"),
        ("platform", "kernel_release", "hostile-kernel"),
        ("platform", "wsl_generation", "hostile-generation"),
        ("platform", "python_executable", "/hostile/python"),
        ("platform", "python_executable_identity", "b" * 64),
        ("platform", "python_prefix", "/hostile/prefix"),
        ("platform", "python_prefix_identity", "a" * 64),
        ("platform", "conda_environment", "hostile-env"),
        ("platform", "conda_prefix", "/hostile/conda"),
        ("platform", "parent_identity", "9" * 64),
        ("platform", "mount_point", "/hostile/mount"),
        ("platform", "mount_root", "/hostile/root"),
        ("platform", "filesystem_type", "hostilefs"),
        ("platform", "device_identity", "hostile-device"),
        ("platform", "mount_options", ("rw", "hostile")),
        ("platform", "probed_at", UTC_NOW + dt.timedelta(seconds=1)),
        ("platform", "environment_identity", "8" * 64),
        ("platform", "proof_digest", "7" * 64),
    ],
)
def test_existing_verifier_rejects_nested_drift_with_retained_digest_and_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    field: str,
    value: object,
) -> None:
    config_path, environment = _public_formal_environment_for_nested_tests(
        tmp_path, monkeypatch
    )
    if target == "layout":
        forged = replace(environment, layout=replace(environment.layout, **{field: value}))
    else:
        forged = replace(environment, platform=replace(environment.platform, **{field: value}))
    with pytest.raises(runtime.PaperRuntimeError) as caught:
        runtime.verify_existing_paper_runtime_preflight(
            forged, config_path=config_path.resolve(), now=UTC_NOW
        )
    _assert_sanitized(caught.value, "PAPER_RUNTIME_PREFLIGHT_INVALID")


def test_existing_rejects_whole_rehash_without_environment_attestation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, environment = _public_formal_environment_for_nested_tests(
        tmp_path, monkeypatch
    )
    mutated_layout = replace(environment.layout, parent_identity="d" * 64)
    payload = runtime._environment_payload(
        environment.config, mutated_layout, environment.platform, environment.verified_at
    )
    forged = replace(
        environment,
        layout=mutated_layout,
        verification_identity=runtime._sha256(payload),
    )
    with pytest.raises(runtime.PaperRuntimeError) as caught:
        runtime.verify_existing_paper_runtime_preflight(
            forged, config_path=config_path.resolve(), now=UTC_NOW
        )
    _assert_sanitized(caught.value, "PAPER_RUNTIME_PREFLIGHT_INVALID")
    with pytest.raises(TypeError):
        pickle.dumps(environment)


def test_existing_rejects_same_bytes_config_file_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, environment = _public_formal_environment_for_nested_tests(
        tmp_path, monkeypatch
    )
    replacement = config_path.with_suffix(".same-bytes")
    replacement.write_bytes(config_path.read_bytes())
    os.replace(replacement, config_path)
    with pytest.raises(runtime.PaperRuntimeError) as caught:
        runtime.verify_existing_paper_runtime_preflight(
            environment, config_path=config_path.resolve(), now=UTC_NOW
        )
    _assert_sanitized(caught.value, "PAPER_RUNTIME_CONFIG_INVALID")


def test_hostile_probe_is_sanitized_and_zero_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, roots = _write_config(tmp_path, mode="PAPER_REAL_TIME")
    config = runtime.load_paper_runtime_config(config_path.resolve())

    def hostile(parent: Path, now: dt.datetime) -> runtime.RuntimePlatformProof:
        del parent, now
        raise RuntimeError("TOKEN-path-SQL-payload-marker")

    monkeypatch.setattr(runtime, "_probe_actual_runtime_platform", hostile)
    with pytest.raises(runtime.PaperRuntimeError) as caught:
        runtime.verify_paper_runtime_environment(config=config, now=UTC_NOW)
    _assert_sanitized(caught.value, "PAPER_RUNTIME_PLATFORM_UNSUPPORTED")
    assert "marker" not in repr(caught.value)
    assert not any(root.exists() for root in roots)


@pytest.mark.skipif(sys.platform == "win32", reason="formal closure requires WSL base")
def test_hostile_formal_closure_is_sanitized_before_mint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, roots = _write_config(tmp_path, mode="PAPER_REAL_TIME")
    config = runtime.load_paper_runtime_config(config_path.resolve())
    assert type(config) is runtime.FormalPaperRuntimeConfig
    layout = runtime._build_layout(config, allow_system_temp=True)
    actual = runtime._probe_actual_runtime_platform(layout.parent, UTC_NOW)
    simulated = _rehash_platform(
        replace(actual, wsl_generation="2", filesystem_type="ext4", mount_root="/")
    )

    def hostile(parent: Path) -> None:
        del parent
        raise RuntimeError("TOKEN-PATH-SQL-payload-closure-marker")

    monkeypatch.setattr(runtime, "_probe_actual_runtime_platform", lambda parent, now: simulated)
    monkeypatch.setattr(runtime, "_system_temp_root", lambda: tmp_path / "other-temp")
    monkeypatch.setattr(runtime, "_before_environment_return_hook", hostile)
    with pytest.raises(runtime.PaperRuntimeError) as caught:
        runtime.verify_paper_runtime_environment(config=config, now=UTC_NOW)
    _assert_sanitized(caught.value, "PAPER_RUNTIME_VERIFY_FAILED")
    assert "marker" not in repr(caught.value)
    assert not any(root.exists() for root in roots)


def test_fresh_import_has_no_heavy_execution_side_effects() -> None:
    code = (
        "import sys; import quant.execution.paper_runtime; "
        "assert 'quant.execution.soak' not in sys.modules; "
        "assert 'quant.reporting' not in sys.modules; "
        "assert 'quant.backtest' not in sys.modules; print('RUN0A_R2_IMPORT_PASS')"
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "src"
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "RUN0A_R2_IMPORT_PASS"


def test_formal_cold_layout_keeps_all_roots_absent(tmp_path: Path) -> None:
    _, config, roots = _formal_config_and_roots(tmp_path)
    assert type(config) is runtime.FormalPaperRuntimeConfig
    layout = runtime._build_layout(config, allow_system_temp=True)
    for name, root in zip(
        ("runtime", "broker", "evidence", "anchor", "log"), roots, strict=True
    ):
        assert dict(layout.root_identities)[name] == runtime._absent_root_identity(
            name, layout.parent_identity, root
        )
    assert not any(root.exists() for root in roots)


def test_formal_broker_materialized_empty_directory_issues_materialized_identity(
    tmp_path: Path,
) -> None:
    _, config, roots = _formal_config_and_roots(tmp_path)
    assert type(config) is runtime.FormalPaperRuntimeConfig
    _materialize_broker_root(roots)
    layout = runtime._build_layout(config, allow_system_temp=True)
    broker_identity = dict(layout.root_identities)["broker"]
    cold_broker_identity = runtime._absent_root_identity(
        "broker", layout.parent_identity, roots[1]
    )
    assert broker_identity != cold_broker_identity
    assert all(
        dict(layout.root_identities)[name] == runtime._absent_root_identity(name, layout.parent_identity, root)
        for name, root in zip(("runtime", "evidence", "anchor", "log"), (roots[0], roots[2], roots[3], roots[4]), strict=True)
    )


def test_formal_broker_materialized_internal_files_do_not_invalidate_runtime_capability(
    tmp_path: Path,
) -> None:
    _, config, roots = _formal_config_and_roots(tmp_path)
    broker = _materialize_broker_root(roots)
    (broker / "store.sqlite3").write_bytes(b"not-runtime-layer-proof")
    layout = runtime._build_layout(config, allow_system_temp=True)
    runtime._verify_retained_layout(config, layout)


def test_development_rejects_materialized_broker_root(tmp_path: Path) -> None:
    config_path, roots = _write_config(tmp_path)
    _materialize_broker_root(roots)
    config = runtime.load_paper_runtime_config(config_path.resolve())
    with pytest.raises(runtime.PaperRuntimeError) as caught:
        runtime.verify_development_paper_runtime_preflight(config=config, now=UTC_NOW)
    _assert_sanitized(caught.value, "PAPER_RUNTIME_LAYOUT_INVALID")


@pytest.mark.parametrize("index", [2, 3, 4])
def test_formal_rejects_non_broker_root_materialization(tmp_path: Path, index: int) -> None:
    _, config, roots = _formal_config_and_roots(tmp_path)
    roots[index].mkdir()
    with pytest.raises(Exception, match="PAPER_RUNTIME_LAYOUT_INVALID"):
        runtime._run_layout_builder(config, allow_system_temp=True)


@pytest.mark.parametrize("index", [0, 1])
def test_formal_accepts_only_runtime_or_broker_root_materialization(
    tmp_path: Path, index: int
) -> None:
    _, config, roots = _formal_config_and_roots(tmp_path)
    roots[index].mkdir()
    layout = runtime._run_layout_builder(config, allow_system_temp=True)
    role = "runtime" if index == 0 else "broker"
    assert dict(layout.root_identities)[role] == runtime._materialized_root_identity(
        role, layout.parent_identity, roots[index], os.lstat(roots[index])
    )


@pytest.mark.parametrize(
    "factory",
    [
        lambda broker: broker.write_bytes(b"regular-file"),
        lambda broker: broker.symlink_to(broker.parent / "runtime"),
    ],
    ids=["regular-file", "symlink"],
)
def test_formal_rejects_invalid_broker_root_types(
    tmp_path: Path, factory: object
) -> None:
    _, config, roots = _formal_config_and_roots(tmp_path)
    broker = _broker_root(roots)
    (broker.parent / "runtime").mkdir(exist_ok=True)
    try:
        cast(object, factory)(broker)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(Exception, match="PAPER_RUNTIME_LAYOUT_INVALID"):
        runtime._run_layout_builder(config, allow_system_temp=True)


@pytest.mark.skipif(sys.platform != "win32", reason="junction probe is Windows-specific")
def test_formal_rejects_broker_junction(tmp_path: Path) -> None:
    _, config, roots = _formal_config_and_roots(tmp_path)
    broker = _broker_root(roots)
    target = roots[0].parent / "junction-target"
    target.mkdir()
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(broker), str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        pytest.skip("junction creation unavailable")
    with pytest.raises(Exception, match="PAPER_RUNTIME_LAYOUT_INVALID"):
        runtime._run_layout_builder(config, allow_system_temp=True)


@pytest.mark.skipif(sys.platform == "win32", reason="formal mint requires simulated WSL base")
def test_cold_capability_invalidates_after_broker_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, cold_environment, roots = _simulated_formal_environment(
        tmp_path, monkeypatch, materialize_broker=False
    )
    cold_layout_identity = cold_environment.layout.layout_identity
    _materialize_broker_root(roots)
    with pytest.raises(runtime.PaperRuntimeError) as stale:
        runtime.verify_existing_paper_runtime_preflight(
            cold_environment, config_path=config_path.resolve(), now=UTC_NOW
        )
    _assert_sanitized(stale.value, "PAPER_RUNTIME_PREFLIGHT_INVALID")
    materialized = runtime.verify_paper_runtime_environment(
        config=cold_environment.config, now=UTC_NOW
    )
    assert materialized.layout.layout_identity != cold_layout_identity
    assert dict(materialized.layout.root_identities)["broker"] != dict(
        cold_environment.layout.root_identities
    )["broker"]


@pytest.mark.skipif(sys.platform == "win32", reason="formal mint requires simulated WSL base")
def test_materialized_capability_rejects_directory_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, environment, roots = _simulated_formal_environment(
        tmp_path, monkeypatch, materialize_broker=True
    )
    broker = _broker_root(roots)
    moved = broker.with_name("old-broker")
    broker.rename(moved)
    broker.mkdir()
    with pytest.raises(runtime.PaperRuntimeError) as caught:
        runtime.verify_existing_paper_runtime_preflight(
            environment, config_path=config_path.resolve(), now=UTC_NOW
        )
    _assert_sanitized(caught.value, "PAPER_RUNTIME_PREFLIGHT_INVALID")


@pytest.mark.skipif(sys.platform == "win32", reason="formal mint requires simulated WSL base")
def test_materialized_capability_rejects_parent_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, environment, roots = _simulated_formal_environment(
        tmp_path, monkeypatch, materialize_broker=True
    )
    parent = roots[0].parent
    moved = parent.with_name("old-paper-parent")
    parent.rename(moved)
    parent.mkdir()
    _broker_root(roots).mkdir()
    with pytest.raises(runtime.PaperRuntimeError) as caught:
        runtime.verify_existing_paper_runtime_preflight(
            environment, config_path=config_path.resolve(), now=UTC_NOW
        )
    _assert_sanitized(caught.value, "PAPER_RUNTIME_PREFLIGHT_INVALID")


@pytest.mark.skipif(sys.platform == "win32", reason="formal mint requires simulated WSL base")
def test_materialized_capability_rejects_broker_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, environment, roots = _simulated_formal_environment(
        tmp_path, monkeypatch, materialize_broker=True
    )
    broker = _broker_root(roots)
    target = broker.parent / "linked-broker-target"
    target.mkdir()
    broker.rename(broker.with_name("old-broker-dir"))
    try:
        broker.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")
    with pytest.raises(runtime.PaperRuntimeError) as caught:
        runtime.verify_existing_paper_runtime_preflight(
            environment, config_path=config_path.resolve(), now=UTC_NOW
        )
    _assert_sanitized(caught.value, "PAPER_RUNTIME_LAYOUT_INVALID")


def test_hostile_root_identity_probe_is_sanitized_and_zero_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, config, roots = _formal_config_and_roots(tmp_path)
    _materialize_broker_root(roots)
    before = set(tmp_path.rglob("*"))

    def hostile(role: str, root: Path, parent_identity: str, *, formal: bool) -> str:
        del role, root, parent_identity, formal
        raise RuntimeError("TOKEN-path-inode-hostile-marker")

    monkeypatch.setattr(runtime, "_probe_root_identity", hostile)
    with pytest.raises(Exception, match="PAPER_RUNTIME_LAYOUT_INVALID"):
        runtime._run_layout_builder(config, allow_system_temp=True)
    assert before == set(tmp_path.rglob("*"))
