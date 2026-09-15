"""横切基础设施：运行时设置、路径、GPU 探测、日志。

依赖方向：``quant.core`` 不依赖任何业务包；业务包可以依赖 ``quant.core``。
"""

from quant.core.settings import RuntimeSettings, load_runtime_settings
from quant.core.paths import ProjectPaths, project_paths
from quant.core.gpu import DeviceReport, detect_device, lightgbm_params

__all__ = [
    "RuntimeSettings",
    "load_runtime_settings",
    "ProjectPaths",
    "project_paths",
    "DeviceReport",
    "detect_device",
    "lightgbm_params",
]
