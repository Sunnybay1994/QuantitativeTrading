"""A股/港股通个人量化投研交易系统。

架构原则(详见《A股港股通个人量化投研交易系统调研.md》):
- 研究与交易解耦,共享同一数据契约与 target_weight 接口。
- 券商 API 只允许出现在 execution 的 Gateway 适配层。
- 数据源 SDK 只允许出现在 data/connectors 内部。
"""

from __future__ import annotations

import os
import sys


def _is_quant_entrypoint() -> bool:
    """Return whether this process was started through a quant CLI entrypoint."""
    original_argv = getattr(sys, "orig_argv", ())
    for index, argument in enumerate(original_argv[:-1]):
        if argument == "-m":
            module = original_argv[index + 1]
            if module == "quant" or module.startswith("quant."):
                return True

    script = os.path.basename(sys.argv[0]).casefold() if sys.argv else ""
    return script in {"quant", "quant.exe", "quant-script.py"}


def _register_runtime_import_logger() -> None:
    try:
        if not _is_quant_entrypoint():
            return
        if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get(
            "QUANT_RUNTIME_IMPORTS_ROOT"
        ):
            return

        from quant.core.runtime_imports import register_runtime_import_logger

        register_runtime_import_logger()
    except BaseException:
        # Import logging is observational and must not affect CLI behavior.
        pass


_register_runtime_import_logger()

__version__ = "0.1.0"
