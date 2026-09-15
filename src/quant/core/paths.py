"""项目路径解析：仓库根、数据湖、artifacts、configs。

约定：所有相对路径相对于仓库根（含 ``pyproject.toml`` 的目录）。环境变量
``QUANT_PROJECT_ROOT`` / ``QUANT_DATA_ROOT`` / ``QUANT_ARTIFACTS_ROOT`` 可覆盖。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _find_project_root(start: Path | None = None) -> Path:
    env = os.environ.get("QUANT_PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    here = (start or Path(__file__)).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "src" / "quant").is_dir():
            return candidate
    return Path.cwd().resolve()


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    data: Path
    artifacts: Path
    configs: Path
    docs: Path

    def artifact(self, *parts: str) -> Path:
        return self.artifacts.joinpath(*parts)

    def config(self, *parts: str) -> Path:
        return self.configs.joinpath(*parts)


@lru_cache(maxsize=1)
def project_paths() -> ProjectPaths:
    root = _find_project_root()
    data = Path(os.environ.get("QUANT_DATA_ROOT", root / "data"))
    artifacts = Path(os.environ.get("QUANT_ARTIFACTS_ROOT", root / "artifacts"))
    return ProjectPaths(
        root=root,
        data=data if data.is_absolute() else root / data,
        artifacts=artifacts if artifacts.is_absolute() else root / artifacts,
        configs=root / "configs",
        docs=root / "docs",
    )
