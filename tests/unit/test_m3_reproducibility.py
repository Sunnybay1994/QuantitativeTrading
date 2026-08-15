from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from quant.research.m3 import reproducibility as subject
from quant.research.m3.config import load_m3_config
from quant.research.m3.orchestration import M3StageRunnerError, StageRunner


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(subject._canonical_bytes(value))


_CODE_VERSION = "test-code"
_DEPENDENCY_SHA = "d" * 64
_PYTHON_SHA = "e" * 64


def _attempt(
    root: Path,
    number: int,
    *,
    score_delta: float = 0.0,
    python_sha: str = _PYTHON_SHA,
) -> None:
    attempt = root / f"attempt={number}"
    attempt.mkdir(parents=True)
    predictions = pl.DataFrame(
        {
            "as_of": pl.Series([date(2024, 1, 2), date(2024, 1, 2)], dtype=pl.Date),
            "symbol": ["000001.SZ", "600000.SH"],
            "score": [0.2 + score_delta, 0.1],
            "rank": pl.Series([1, 2], dtype=pl.Int64),
        }
    )
    predictions.write_parquet(attempt / "predictions.parquet")
    pl.DataFrame({"as_of": [date(2024, 1, 2)], "rank_ic": [0.5]}).write_parquet(
        attempt / "daily_ic.parquet"
    )
    _write_json(attempt / "model.metadata.json", {"attempt": number})
    (attempt / "model.txt").write_text(f"model-{number}", encoding="utf-8")
    _write_json(attempt / "prediction_manifest.json", {"attempt": number})
    _write_json(
        attempt / "metrics.json",
        {"metric": 0.5 + score_delta, "not_computable": None, "status": "OK"},
    )
    _write_json(
        attempt / "read_audit.json",
        {
            "schema_version": subject._AUDIT_SCHEMA,
            "worker_protocol_version": subject._WORKER_PROTOCOL,
            "attempt": number,
            "fresh_process": True,
            "work_key": "a" * 64,
            "code_version": _CODE_VERSION,
            "dependency_fingerprint_sha256": _DEPENDENCY_SHA,
            "python_implementation": "CPython",
            "python_version": "3.12.0",
            "python_executable_sha256": python_sha,
            "read_paths_sha256": "b" * 64,
            "normal_work_outputs_read": False,
            "other_attempt_read": False,
        },
    )


def _tree(tmp_path: Path, *, score_delta: float = 0.0) -> tuple[Path, str]:
    root = tmp_path / "comparison"
    root.mkdir(parents=True)
    _attempt(root, 1)
    _attempt(root, 2, score_delta=score_delta)
    key = "c" * 64
    subject._write_comparison(
        root=root,
        comparison_key=key,
        score_atol=1e-12,
        metric_atol=1e-12,
        code_version=_CODE_VERSION,
        dependency_fingerprint_sha256=_DEPENDENCY_SHA,
        python_executable_sha256=_PYTHON_SHA,
    )
    return root, key


def test_comparison_recomputes_rows_scores_metrics_and_strict_tree(
    tmp_path: Path,
) -> None:
    root, key = _tree(tmp_path)

    subject._verify_comparison_tree(
        root=root,
        comparison_key=key,
        score_atol=1e-12,
        metric_atol=1e-12,
        code_version=_CODE_VERSION,
        dependency_fingerprint_sha256=_DEPENDENCY_SHA,
        python_executable_sha256=_PYTHON_SHA,
    )
    report = json.loads((root / "reproducibility.json").read_text("utf-8"))
    assert report["passed"] is True
    assert report["prediction_row_count"] == 2
    assert report["attempt_output_sha256"][0] != report["attempt_output_sha256"][1]


def test_comparison_rejects_score_metric_nullable_and_tree_drift(
    tmp_path: Path,
) -> None:
    root, key = _tree(tmp_path / "score")
    score_path = root / "attempt=2" / "predictions.parquet"
    pl.read_parquet(score_path).with_columns(
        (pl.col("score") + 2e-12).alias("score")
    ).write_parquet(score_path)
    with pytest.raises(ValueError):
        subject._verify_comparison_tree(
            root=root,
            comparison_key=key,
            score_atol=1e-12,
            metric_atol=1e-12,
            code_version=_CODE_VERSION,
            dependency_fingerprint_sha256=_DEPENDENCY_SHA,
            python_executable_sha256=_PYTHON_SHA,
        )

    root, key = _tree(tmp_path / "nullable")
    _write_json(
        root / "attempt=2" / "metrics.json",
        {"metric": 0.5, "not_computable": 0.0, "status": "OK"},
    )
    with pytest.raises(ValueError):
        subject._comparison_payload(
            root=root,
            comparison_key=key,
            score_atol=1e-12,
            metric_atol=1e-12,
            code_version=_CODE_VERSION,
            dependency_fingerprint_sha256=_DEPENDENCY_SHA,
            python_executable_sha256=_PYTHON_SHA,
        )

    root, key = _tree(tmp_path / "tree")
    (root / "attempt=1" / "extra.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(ValueError):
        subject._verify_comparison_tree(
            root=root,
            comparison_key=key,
            score_atol=1e-12,
            metric_atol=1e-12,
            code_version=_CODE_VERSION,
            dependency_fingerprint_sha256=_DEPENDENCY_SHA,
            python_executable_sha256=_PYTHON_SHA,
        )


def test_worker_environment_is_deterministic_and_private(tmp_path: Path) -> None:
    first = subject._worker_environment(tmp_path / "one")
    second = subject._worker_environment(tmp_path / "two")

    assert first["PYTHONHASHSEED"] == second["PYTHONHASHSEED"] == "0"
    assert first["OMP_NUM_THREADS"] == second["OMP_NUM_THREADS"] == "1"
    assert first["TEMP"] != second["TEMP"]
    assert "PYTHONPATH" not in first


def test_public_failure_is_redacted_and_does_not_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subject,
        "_run_stage",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("TOKEN=/secret/path")),
    )
    with pytest.raises(subject.M3ReproducibilityError) as caught:
        subject.run_formal_reproducibility_stage(
            project_root=tmp_path,
            config=object(),  # type: ignore[arg-type]
            config_relative=subject.PurePosixPath("config.toml"),
            snapshot_id="a" * 64,
            fold="fold_000",
            horizon=5,
            python_executable=tmp_path / "python",
        )
    assert str(caught.value) == "M3_REPRODUCIBILITY_INVALID"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_worker_protocol_rejects_incomplete_request_without_output() -> None:
    assert subject._worker_entry(("too", "short")) == 1


def test_public_stage_publishes_two_attempts_and_resumes_without_workers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_project = Path(__file__).resolve().parents[2]
    source_config = source_project / "configs/research/m3_qlib_example.toml"
    config = load_m3_config(source_config)
    project = tmp_path / "project"
    project.mkdir()
    config_relative = subject.PurePosixPath("configs/research/m3_qlib_example.toml")
    config_path = project.joinpath(*config_relative.parts)
    config_path.parent.mkdir(parents=True)
    config_path.write_bytes(source_config.read_bytes())
    (project / "pyproject.toml").write_bytes(
        (source_project / "pyproject.toml").read_bytes()
    )
    source_path = project / "src/quant/example.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("VALUE = 1\n", encoding="utf-8")

    stage_root = project / "artifacts/research/m3/stage"
    g1_root = project / "data/clean/m3_g1/releases/release"
    qlib_root = project / "data/external/qlib/v0.9.7"
    for directory in (stage_root, g1_root, qlib_root):
        directory.mkdir(parents=True)
    feature_root = stage_root / "features/example"
    label_root = stage_root / "labels/example"
    alignment_root = stage_root / "work/example/alignment"
    feature_receipt = stage_root / "receipts/features/example.json"
    label_receipt = stage_root / "receipts/labels/example.json"
    alignment_receipt = stage_root / "receipts/alignment/example.json"
    for path in (
        feature_root / "feature_manifest.json",
        label_root / "label_manifest.json",
        alignment_root / "alignment_manifest.json",
        feature_receipt,
        label_receipt,
        alignment_receipt,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.name.encode("ascii"))

    resolution = SimpleNamespace(
        stage_root=stage_root,
        artifact_roots={
            "G1_RELEASE": g1_root,
            "G8": stage_root,
            "EXTERNAL_QLIB": qlib_root,
        },
        runtime=SimpleNamespace(
            code_version=_CODE_VERSION,
            dependency_fingerprint_sha256=_DEPENDENCY_SHA,
            source_files=(SimpleNamespace(relative_path="src/quant/example.py"),),
        ),
        feature=SimpleNamespace(root=feature_root),
        feature_receipt_path=feature_receipt,
        label=SimpleNamespace(root=label_root),
        label_receipt_path=label_receipt,
        alignment=SimpleNamespace(root=alignment_root),
        alignment_receipt_path=alignment_receipt,
    )
    monkeypatch.setattr(
        subject, "resolve_formal_reproducibility_cli_inputs", lambda **_kwargs: resolution
    )
    monkeypatch.setattr(subject, "_comparison_key", lambda **_kwargs: "c" * 64)
    calls: list[int] = []

    def launch(**kwargs: object) -> None:
        attempt = kwargs["attempt"]
        attempt_root = kwargs["attempt_root"]
        assert type(attempt) is int and isinstance(attempt_root, Path)
        calls.append(attempt)
        _attempt(
            attempt_root.parent,
            attempt,
            python_sha=subject._python_executable_sha256(Path(sys.executable)),
        )

    monkeypatch.setattr(subject, "_launch_worker", launch)
    arguments = {
        "project_root": project,
        "config": config,
        "config_relative": config_relative,
        "snapshot_id": "a" * 64,
        "fold": "fold_000",
        "horizon": 5,
        "python_executable": Path(sys.executable),
    }

    with pytest.raises(M3StageRunnerError) as nested:
        StageRunner(
            stage_root=stage_root,
            artifact_roots={**resolution.artifact_roots, "PROJECT": project},
            config=config,
        )
    assert str(nested.value) == "STAGE_INPUT_INVALID"

    first = subject.run_formal_reproducibility_stage(**arguments)
    second = subject.run_formal_reproducibility_stage(**arguments)
    verified = subject.verify_formal_reproducibility_artifact(
        root=first.root,
        receipt_path=first.receipt_path,
        artifact_roots={"PROJECT": project},
        comparison_key=first.comparison_key,
        score_atol=1e-12,
        metric_atol=1e-12,
        code_version=_CODE_VERSION,
        dependency_fingerprint_sha256=_DEPENDENCY_SHA,
        python_executable_sha256=subject._python_executable_sha256(
            Path(sys.executable)
        ),
    )

    assert calls == [1, 2]
    assert first.reused is False
    assert second.reused is True
    assert first.receipt.inputs
    assert {item.root_alias for item in first.receipt.inputs} == {"PROJECT"}
    assert {item.root_alias for item in first.receipt.outputs} == {"PROJECT"}
    assert len(first.receipt.outputs) == 15
    assert first.root == second.root
    assert verified.root == first.root


def _windows_conda_hardlinked_python() -> Path | None:
    if os.name != "nt":
        return None
    executable = Path(sys.executable).resolve(strict=True)
    try:
        status = os.lstat(executable)
    except OSError:
        return None
    if not executable.is_absolute() or status.st_nlink < 2 or status.st_size <= 0:
        return None
    return executable


def test_windows_current_conda_python_nlink2_passes_executable_gate() -> None:
    executable = _windows_conda_hardlinked_python()
    if executable is None:
        pytest.skip("Windows conda hardlinked sys.executable (nlink>=2) required")

    resolved = subject._current_python_executable(executable)
    digest = subject._python_executable_sha256(executable)

    assert resolved == executable
    assert os.lstat(executable).st_nlink >= 2
    assert digest == hashlib.sha256(executable.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        subject._real_file(executable)
    with pytest.raises(ValueError):
        subject._file_sha256(executable)


def test_current_python_extra_hardlink_path_is_rejected() -> None:
    executable = Path(sys.executable).resolve(strict=True)
    baseline_nlink = os.lstat(executable).st_nlink
    alias = executable.parent / f".m3_g8e_r3_python_alias_{os.getpid()}.exe"
    if alias.exists():
        alias.unlink()
    try:
        os.link(executable, alias)
    except OSError:
        pytest.skip("platform cannot create a hardlink to sys.executable")
    try:
        assert alias.resolve(strict=True) != executable
        assert alias.samefile(executable)
        with pytest.raises(ValueError):
            subject._current_python_executable(alias)
        with pytest.raises(ValueError):
            subject._python_executable_sha256(alias)
    finally:
        alias.unlink(missing_ok=True)

    assert not alias.exists()
    assert os.lstat(executable).st_nlink == baseline_nlink


def test_current_python_symlink_leaf_is_rejected(tmp_path: Path) -> None:
    executable = Path(sys.executable).resolve(strict=True)
    alias = tmp_path / "python-symlink.exe"
    try:
        alias.symlink_to(executable)
    except OSError:
        pytest.skip("platform cannot create a symlink to sys.executable")

    with pytest.raises(ValueError):
        subject._current_python_executable(alias)
    with pytest.raises(ValueError):
        subject._python_executable_sha256(alias)


def test_ordinary_artifact_hardlink_remains_rejected(tmp_path: Path) -> None:
    original = tmp_path / "artifact.bin"
    original.write_bytes(b"artifact-payload")
    alias = tmp_path / "artifact-alias.bin"
    try:
        os.link(original, alias)
    except OSError:
        pytest.skip("platform cannot create an artifact hardlink")

    assert os.lstat(original).st_nlink == 2
    assert os.lstat(alias).st_nlink == 2
    with pytest.raises(ValueError):
        subject._real_file(original)
    with pytest.raises(ValueError):
        subject._file_sha256(original)
    with pytest.raises(ValueError):
        subject._digest_for_path(original, artifact_roots={"TEST": tmp_path})
    with pytest.raises(ValueError):
        subject._regular_files(tmp_path)


def test_windows_conda_nlink2_stage_reaches_mocked_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = _windows_conda_hardlinked_python()
    if executable is None:
        pytest.skip("Windows conda hardlinked sys.executable (nlink>=2) required")
    project = Path(__file__).resolve().parents[2]
    config = load_m3_config(project / "configs/research/m3_qlib_example.toml")
    reached = False

    def fake_resolve(**_kwargs: object) -> object:
        nonlocal reached
        reached = True
        raise RuntimeError("hostile-resolver")

    monkeypatch.setattr(
        subject, "resolve_formal_reproducibility_cli_inputs", fake_resolve
    )
    with pytest.raises(subject.M3ReproducibilityError) as caught:
        subject.run_formal_reproducibility_stage(
            project_root=project,
            config=config,
            config_relative=subject.PurePosixPath(
                "configs/research/m3_qlib_example.toml"
            ),
            snapshot_id="a" * 64,
            fold="fold_000",
            horizon=5,
            python_executable=executable,
        )

    assert reached is True
    assert str(caught.value) == "M3_REPRODUCIBILITY_INVALID"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_non_current_executable_maps_to_redacted_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Path(__file__).resolve().parents[2]
    config = load_m3_config(project / "configs/research/m3_qlib_example.toml")
    fake = tmp_path / "python.exe"
    fake.write_bytes(b"not-the-current-interpreter")
    resolver_called = False

    def unexpected_resolver(**_kwargs: object) -> object:
        nonlocal resolver_called
        resolver_called = True
        raise AssertionError("resolver must not be called")

    monkeypatch.setattr(
        subject, "resolve_formal_reproducibility_cli_inputs", unexpected_resolver
    )

    with pytest.raises(subject.M3ReproducibilityError) as caught:
        subject.run_formal_reproducibility_stage(
            project_root=project,
            config=config,
            config_relative=subject.PurePosixPath(
                "configs/research/m3_qlib_example.toml"
            ),
            snapshot_id="a" * 64,
            fold="fold_000",
            horizon=5,
            python_executable=fake,
        )

    assert resolver_called is False
    assert str(caught.value) == "M3_REPRODUCIBILITY_INVALID"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
