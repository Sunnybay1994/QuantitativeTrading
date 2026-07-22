"""本地敏感配置加载；任何异常和 repr 均不得暴露凭据。"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_TUSHARE_CONFIG = Path("configs/tushare.local.toml")


@dataclass(frozen=True)
class TushareSettings:
    token: str = field(repr=False)


def load_tushare_settings(path: Path | None = None) -> TushareSettings:
    """从被 Git 排除的 TOML 读取 Token；环境变量仅用于覆盖配置路径。"""
    config_path = path or Path(os.environ.get("QUANT_TUSHARE_CONFIG", DEFAULT_TUSHARE_CONFIG))
    if not config_path.exists():
        raise FileNotFoundError(
            f"缺少 Tushare 本地配置 {config_path}；请复制 configs/tushare.example.toml"
        )
    with config_path.open("rb") as stream:
        payload = tomllib.load(stream)
    token = str(payload.get("tushare", {}).get("token", "")).strip()
    if not token:
        raise ValueError(f"Tushare Token 尚未填写: {config_path}")
    if any(character.isspace() for character in token):
        raise ValueError("Tushare Token 格式非法（包含空白字符）")
    return TushareSettings(token=token)

