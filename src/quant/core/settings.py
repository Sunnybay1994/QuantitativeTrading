"""运行时设置：``configs/runtime.toml`` + 环境变量覆盖。

密钥不放这里。Tushare token 仍走 ``quant.settings.load_tushare_settings``；
DeepSeek / SMTP / Webhook 密钥一律走环境变量（见 ``quant.llm`` 与 ``quant.notify``）。

优先级：显式参数 > 环境变量 ``QUANT_*`` > ``configs/runtime.toml`` > 默认值。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from quant.core.paths import project_paths
from quant.settings import TushareSettings, load_tushare_settings, resolve_data_root  # noqa: F401  re-export

Device = Literal["auto", "gpu", "cpu"]
DEFAULT_RUNTIME_CONFIG = Path("configs/runtime.toml")


@dataclass(frozen=True)
class RuntimeSettings:
    """所有模块共用的少量运行参数。"""

    device: Device = "cpu"
    """``cpu``（默认，结果可复现）、``gpu``（LightGBM OpenCL）、``auto``（探测到 GPU 才用）。"""
    polars_threads: int = 4
    lightgbm_threads: int = 4
    llm_monthly_budget_usd: float = 30.0
    llm_model: str = "deepseek-chat"
    notify_config: Path = Path("configs/notify.toml")
    timezone: str = "Asia/Shanghai"
    extra: dict[str, Any] = field(default_factory=dict, repr=False)


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as stream:
        return tomllib.load(stream)


def load_runtime_settings(path: Path | None = None) -> RuntimeSettings:
    root = project_paths().root
    config_path = path or Path(os.environ.get("QUANT_RUNTIME_CONFIG", DEFAULT_RUNTIME_CONFIG))
    if not config_path.is_absolute():
        config_path = root / config_path
    payload = _read_toml(config_path)
    runtime = dict(payload.get("runtime", {}))
    llm = dict(payload.get("llm", {}))

    device = str(os.environ.get("QUANT_DEVICE", runtime.get("device", "cpu"))).lower()
    if device not in ("auto", "gpu", "cpu"):
        raise ValueError(f"QUANT_DEVICE/runtime.device 非法: {device!r}，允许 auto|gpu|cpu")
    return RuntimeSettings(
        device=device,  # type: ignore[arg-type]
        polars_threads=int(os.environ.get("POLARS_MAX_THREADS", runtime.get("polars_threads", 4))),
        lightgbm_threads=int(os.environ.get("QUANT_LGBM_THREADS", runtime.get("lightgbm_threads", 4))),
        llm_monthly_budget_usd=float(os.environ.get("QUANT_LLM_BUDGET_USD", llm.get("monthly_budget_usd", 30.0))),
        llm_model=str(os.environ.get("QUANT_LLM_MODEL", llm.get("model", "deepseek-chat"))),
        notify_config=Path(runtime.get("notify_config", "configs/notify.toml")),
        timezone=str(runtime.get("timezone", "Asia/Shanghai")),
        extra={k: v for k, v in payload.items() if k not in ("runtime", "llm")},
    )
