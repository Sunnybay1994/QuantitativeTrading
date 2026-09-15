"""GPU 探测与 LightGBM 设备参数注入。

本机实测（GTX 1070、LightGBM 4.6 pip 轮子）：``device_type="gpu"``（OpenCL）可用，
``cuda`` 未编译。20 万行 × 20 特征、50 轮：CPU 1.06 s，GPU 1.74 s——当前工作负载
太小，GPU 没有优势且会改变数值可复现性，所以默认 ``cpu``；把 ``QUANT_DEVICE=gpu``
或 ``configs/runtime.toml`` 的 ``runtime.device`` 设为 ``gpu``/``auto`` 即可切换。

探测结果缓存在 ``artifacts/runtime/gpu_probe.json``，避免每次训练前都试跑。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from quant.core.paths import project_paths
from quant.core.settings import RuntimeSettings, load_runtime_settings

PROBE_CACHE = Path("runtime/gpu_probe.json")
PROBE_TTL_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True)
class DeviceReport:
    requested: str
    resolved: str  # "gpu" | "cpu"
    gpu_name: str | None
    driver: str | None
    lightgbm_gpu: bool
    lightgbm_cuda: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _nvidia_smi() -> tuple[str | None, str | None]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None, None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout.strip().splitlines()
    except Exception:
        return None, None
    if not out:
        return None, None
    name, _, driver = out[0].partition(",")
    return name.strip() or None, driver.strip() or None


def _probe_lightgbm(device_type: str) -> bool:
    try:
        import numpy as np
        import lightgbm as lgb
    except Exception:
        return False
    try:
        x = np.random.default_rng(0).random((2000, 4))
        y = x.sum(axis=1)
        lgb.train(
            {"objective": "regression", "device_type": device_type, "verbose": -1, "num_threads": 1},
            lgb.Dataset(x, y), num_boost_round=2,
        )
        return True
    except Exception:
        return False


def _cache_path() -> Path:
    return project_paths().artifacts / PROBE_CACHE


def _load_cache() -> dict[str, Any] | None:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if time.time() - float(payload.get("probed_at", 0)) > PROBE_TTL_SECONDS:
        return None
    return payload


def probe_hardware(*, refresh: bool = False) -> dict[str, Any]:
    """返回 {gpu_name, driver, lightgbm_gpu, lightgbm_cuda, probed_at}，带一周缓存。"""
    if not refresh:
        cached = _load_cache()
        if cached:
            return cached
    name, driver = _nvidia_smi()
    payload = {
        "gpu_name": name,
        "driver": driver,
        "lightgbm_gpu": _probe_lightgbm("gpu") if name else False,
        "lightgbm_cuda": _probe_lightgbm("cuda") if name else False,
        "probed_at": time.time(),
    }
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    return payload


def detect_device(settings: RuntimeSettings | None = None, *, refresh: bool = False) -> DeviceReport:
    settings = settings or load_runtime_settings()
    hw = probe_hardware(refresh=refresh)
    requested = settings.device
    if requested == "cpu":
        return DeviceReport(requested, "cpu", hw["gpu_name"], hw["driver"], hw["lightgbm_gpu"], hw["lightgbm_cuda"],
                            "配置为 cpu（默认，保证可复现）")
    if hw["lightgbm_gpu"]:
        return DeviceReport(requested, "gpu", hw["gpu_name"], hw["driver"], True, hw["lightgbm_cuda"],
                            f"使用 {hw['gpu_name']} 的 OpenCL 后端")
    reason = "未检测到 GPU" if not hw["gpu_name"] else "LightGBM GPU 探测失败"
    if requested == "gpu":
        reason += "；已回退 cpu"
    return DeviceReport(requested, "cpu", hw["gpu_name"], hw["driver"], False, hw["lightgbm_cuda"], reason)


def lightgbm_params(params: dict[str, Any] | None = None, *, settings: RuntimeSettings | None = None) -> dict[str, Any]:
    """在配置给定的 LightGBM 参数上注入 ``device_type`` 与线程数。

    配置里显式写了 ``device_type`` 的以配置为准（研究配置冻结优先）。
    """
    merged = dict(params or {})
    settings = settings or load_runtime_settings()
    if "device_type" in merged or "device" in merged:
        return merged
    resolved = detect_device(settings).resolved
    if resolved != "cpu":
        # 只有真的切到 GPU 才写参数，cpu 路径保持与历史配置逐字节一致（复现优先）。
        merged["device_type"] = resolved
        merged.setdefault("num_threads", settings.lightgbm_threads)
    return merged


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="quant gpu-check", description="探测 GPU 与 LightGBM 后端")
    parser.add_argument("--refresh", action="store_true", help="忽略缓存重新探测")
    args = parser.parse_args(argv)
    report = detect_device(refresh=args.refresh)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
