import json

import pytest

from quant.core.gpu import DeviceReport, detect_device, lightgbm_params
from quant.core.paths import project_paths
from quant.core.settings import load_runtime_settings


@pytest.fixture(autouse=True)
def _clear_paths(monkeypatch, tmp_path):
    (tmp_path / "src" / "quant").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='quant'\n")
    monkeypatch.setenv("QUANT_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_ARTIFACTS_ROOT", str(tmp_path / "artifacts"))
    project_paths.cache_clear()
    yield
    project_paths.cache_clear()


def test_runtime_defaults_to_cpu(monkeypatch, tmp_path):
    monkeypatch.delenv("QUANT_DEVICE", raising=False)
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "runtime.toml").write_text("[runtime]\ndevice='cpu'\n")
    settings = load_runtime_settings(tmp_path / "configs" / "runtime.toml")
    assert settings.device == "cpu"
    monkeypatch.setattr("quant.core.gpu.probe_hardware", lambda refresh=False: {
        "gpu_name": "GTX 1070", "driver": "582", "lightgbm_gpu": True,
        "lightgbm_cuda": False, "probed_at": 0,
    })
    report = detect_device(settings)
    assert report.resolved == "cpu"
    assert lightgbm_params({"num_leaves": 31}, settings=settings) == {"num_leaves": 31}


def test_gpu_auto_injects_device_type(monkeypatch):
    monkeypatch.setenv("QUANT_DEVICE", "auto")
    monkeypatch.setattr("quant.core.gpu.probe_hardware", lambda refresh=False: {
        "gpu_name": "GTX 1070", "driver": "582", "lightgbm_gpu": True,
        "lightgbm_cuda": False, "probed_at": 0,
    })
    settings = load_runtime_settings()
    assert detect_device(settings).resolved == "gpu"
    params = lightgbm_params({"learning_rate": 0.05}, settings=settings)
    assert params["device_type"] == "gpu"


def test_explicit_device_type_is_not_overwritten(monkeypatch):
    monkeypatch.setenv("QUANT_DEVICE", "gpu")
    monkeypatch.setattr("quant.core.gpu.probe_hardware", lambda refresh=False: {
        "gpu_name": "GTX 1070", "driver": "582", "lightgbm_gpu": True,
        "lightgbm_cuda": False, "probed_at": 0,
    })
    params = lightgbm_params({"device_type": "cpu"})
    assert params == {"device_type": "cpu"}


def test_device_report_serializes():
    report = DeviceReport("cpu", "cpu", None, None, False, False, "test")
    assert json.loads(json.dumps(report.to_dict()))["resolved"] == "cpu"
