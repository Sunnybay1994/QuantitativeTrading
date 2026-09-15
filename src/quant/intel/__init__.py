"""扫描 arXiv / GitHub / RSS，提炼可评估因子表达式并写入夜间队列。"""

from __future__ import annotations

from quant.intel.pipeline import run_intel, main

__all__ = ["run_intel", "main"]
