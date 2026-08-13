from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from quant.research.m3 import reproducibility as subject
from quant.research.m3.config import load_m3_config


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
    project = Path(__file__).resolve().parents[2]
    config = load_m3_config(project / "configs/research/m3_qlib_example.toml")
    stage_root = tmp_path / "stage"
    stage_root.mkdir()
    resolution = SimpleNamespace(
        stage_root=stage_root,
        artifact_roots={"G8": stage_root},
        runtime=SimpleNamespace(
            code_version=_CODE_VERSION,
            dependency_fingerprint_sha256=_DEPENDENCY_SHA,
        ),
    )
    monkeypatch.setattr(
        subject, "resolve_formal_reproducibility_cli_inputs", lambda **_kwargs: resolution
    )
    monkeypatch.setattr(subject, "_external_inputs", lambda **_kwargs: ())
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
            python_sha=subject._file_sha256(Path(sys.executable)),
        )

    monkeypatch.setattr(subject, "_launch_worker", launch)
    arguments = {
        "project_root": project,
        "config": config,
        "config_relative": subject.PurePosixPath("configs/research/m3_qlib_example.toml"),
        "snapshot_id": "a" * 64,
        "fold": "fold_000",
        "horizon": 5,
        "python_executable": Path(sys.executable),
    }

    first = subject.run_formal_reproducibility_stage(**arguments)
    second = subject.run_formal_reproducibility_stage(**arguments)

    assert calls == [1, 2]
    assert first.reused is False
    assert second.reused is True
    assert first.receipt.inputs == ()
    assert len(first.receipt.outputs) == 15
    assert first.root == second.root
