"""本地敏感配置加载；任何异常和 repr 均不得暴露凭据。"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_TUSHARE_CONFIG = Path("configs/tushare.local.toml")
DEFAULT_DATA_ROOT = Path("data")


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


def resolve_data_root(
    value: Path | None = None,
    *,
    base: Path | None = None,
) -> Path:
    """Resolve the explicit/shared research data root without copying it.

    ``--data-root`` wins over ``QUANT_DATA_ROOT``.  Relative paths remain
    relative to the caller supplied project/base directory; an absolute path is
    intentionally allowed so a Git worktree can consume the main shared data
    root.  The directory must already exist because research callers are
    read-only consumers.
    """
    configured = value
    if configured is None:
        environment = os.environ.get("QUANT_DATA_ROOT")
        configured = Path(environment) if environment else DEFAULT_DATA_ROOT
    anchor = (base or Path.cwd()).resolve(strict=True)
    candidate = configured if configured.is_absolute() else anchor / configured
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        raise NotADirectoryError(f"数据根目录不是实际目录: {resolved}")
    return resolved

