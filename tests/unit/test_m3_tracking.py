"""D7: MLflow 薄适配器（含返工 R5 递归安全扫描）。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from quant.research.m3.tracking import log_m3_run


def test_log_m3_run_records_required_fields(tmp_path: Path) -> None:
    artifact = tmp_path / "pred.parquet"
    artifact.write_bytes(b"parquet-bytes")

    fake_run = MagicMock()
    fake_run.info.run_id = "run-abc"
    fake_cm = MagicMock()
    fake_cm.__enter__.return_value = fake_run
    fake_cm.__exit__.return_value = False

    fake_mlflow = MagicMock()
    fake_mlflow.start_run.return_value = fake_cm

    with patch.dict("sys.modules", {"mlflow": fake_mlflow}):
        run_id = log_m3_run(
            tracking_uri="sqlite:///tmp/mlflow.db",
            experiment_name="m3_alpha158_lightgbm",
            params={
                "config_hash": "sha256:cfg",
                "snapshot_id": "sha256:snap",
                "fold": "fold_001",
                "horizon_sessions": 5,
                "seed": 20260712,
            },
            metrics={"test_rank_ic": 0.12, "test_rank_icir": 0.8},
            artifacts=[artifact],
            tags={"code_version": "unavailable", "model_version": "alpha158_lgb_v1"},
        )

    assert run_id == "run-abc"
    fake_mlflow.set_tracking_uri.assert_called_once_with("sqlite:///tmp/mlflow.db")
    fake_mlflow.log_params.assert_called_once()
    fake_mlflow.log_metrics.assert_called_once()
    fake_mlflow.log_artifact.assert_called_once_with(str(artifact))


def test_rejects_token_keys() -> None:
    with pytest.raises(ValueError, match="敏感键"):
        log_m3_run(
            tracking_uri="sqlite:///tmp/mlflow.db",
            experiment_name="m3",
            params={"tushare_token": "secret"},
            metrics={},
            artifacts=[],
            tags={},
        )


def test_rejects_absolute_paths_in_tags() -> None:
    with pytest.raises(ValueError, match="绝对本机路径"):
        log_m3_run(
            tracking_uri="sqlite:///tmp/mlflow.db",
            experiment_name="m3",
            params={"snapshot_id": "sha256:x"},
            metrics={},
            artifacts=[],
            tags={"workdir": "/home/mabw/win/Cursor/quant"},
        )


def test_r5_rejects_nested_token_mapping() -> None:
    with pytest.raises(ValueError, match="敏感键"):
        log_m3_run(
            tracking_uri="sqlite:///tmp/mlflow.db",
            experiment_name="m3",
            params={"nested": {"tushare_token": "secret-value"}},
            metrics={},
            artifacts=[],
            tags={},
        )


def test_r5_rejects_nested_sequence_secrets() -> None:
    with pytest.raises(ValueError, match="敏感键"):
        log_m3_run(
            tracking_uri="sqlite:///tmp/mlflow.db",
            experiment_name="m3",
            params={"items": [{"password": "x"}]},
            metrics={},
            artifacts=[],
            tags={},
        )
    with pytest.raises(ValueError, match="敏感键"):
        log_m3_run(
            tracking_uri="sqlite:///tmp/mlflow.db",
            experiment_name="m3",
            params={"items": ({"api_secret": "x"},)},
            metrics={},
            artifacts=[],
            tags={},
        )


def test_r5_rejects_nested_unix_and_windows_paths() -> None:
    with pytest.raises(ValueError, match="绝对本机路径"):
        log_m3_run(
            tracking_uri="sqlite:///tmp/mlflow.db",
            experiment_name="m3",
            params={"meta": {"path": "/var/data/file.parquet"}},
            metrics={},
            artifacts=[],
            tags={},
        )
    with pytest.raises(ValueError, match="绝对本机路径"):
        log_m3_run(
            tracking_uri="sqlite:///tmp/mlflow.db",
            experiment_name="m3",
            params={"meta": {"path": r"C:\Users\data\file.parquet"}},
            metrics={},
            artifacts=[],
            tags={},
        )


def test_r5_cycle_reference_does_not_recurse_forever() -> None:
    cyclic: dict[str, object] = {"a": 1}
    cyclic["self"] = cyclic
    with pytest.raises(ValueError, match="循环引用"):
        log_m3_run(
            tracking_uri="sqlite:///tmp/mlflow.db",
            experiment_name="m3",
            params=cyclic,
            metrics={},
            artifacts=[],
            tags={},
        )


def test_r5_missing_artifact_checked_before_start_run(tmp_path: Path) -> None:
    fake_mlflow = MagicMock()
    with patch.dict("sys.modules", {"mlflow": fake_mlflow}):
        with pytest.raises(FileNotFoundError):
            log_m3_run(
                tracking_uri="sqlite:///tmp/mlflow.db",
                experiment_name="m3",
                params={"snapshot_id": "sha256:x"},
                metrics={},
                artifacts=[tmp_path / "missing.parquet"],
                tags={},
            )
    fake_mlflow.start_run.assert_not_called()


def test_f6_rejects_absolute_path_keys() -> None:
    with pytest.raises(ValueError, match="绝对本机路径"):
        log_m3_run(
            tracking_uri="sqlite:///tmp/mlflow.db",
            experiment_name="m3",
            params={"/home/user/private": "ok"},
            metrics={},
            artifacts=[],
            tags={},
        )
    with pytest.raises(ValueError, match="绝对本机路径"):
        log_m3_run(
            tracking_uri="sqlite:///tmp/mlflow.db",
            experiment_name="m3",
            params={r"C:\Users\data\file.parquet": "ok"},
            metrics={},
            artifacts=[],
            tags={},
        )
    with pytest.raises(ValueError, match="绝对本机路径"):
        log_m3_run(
            tracking_uri="sqlite:///tmp/mlflow.db",
            experiment_name="m3",
            params={"C:/Users/data/file.parquet": "ok"},
            metrics={},
            artifacts=[],
            tags={},
        )


def test_f6_rejects_credential_fragment_keys() -> None:
    with pytest.raises(ValueError, match="凭据|敏感"):
        log_m3_run(
            tracking_uri="sqlite:///tmp/mlflow.db",
            experiment_name="m3",
            params={"Bearer abc": "ok"},
            metrics={},
            artifacts=[],
            tags={},
        )
    with pytest.raises(ValueError, match="凭据|敏感"):
        log_m3_run(
            tracking_uri="sqlite:///tmp/mlflow.db",
            experiment_name="m3",
            params={"token=xyz": "ok"},
            metrics={},
            artifacts=[],
            tags={},
        )
