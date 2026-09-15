"""DeepSeek 调用的唯一门面。传输层仍在 ``quant.data.connectors.deepseek``。

新代码只从这里导入；研究循环、周候选、文本评分改为走本包，避免再散落密钥加载。
月度预算默认 US$30，超限直接拒绝，不发起请求。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quant.core.paths import project_paths
from quant.core.settings import load_runtime_settings
from quant.data.connectors.deepseek import DeepSeekClient, RequestFailure, load_key
from quant.llm.budget import month_spend_usd, remaining_budget_usd

__all__ = [
    "DeepSeekClient",
    "RequestFailure",
    "load_key",
    "load_api_key",
    "make_client",
    "complete_messages",
    "month_spend_usd",
    "remaining_budget_usd",
]


def load_api_key(project_root: Path | None = None) -> str:
    return load_key(project_root or project_paths().root)


def make_client(
    *,
    timeout: float = 60,
    transport: Any = None,
    project_root: Path | None = None,
) -> DeepSeekClient:
    return DeepSeekClient(load_api_key(project_root), timeout=timeout, transport=transport)


def complete_messages(
    messages: list[dict[str, str]],
    settings: dict[str, Any],
    *,
    client: DeepSeekClient | None = None,
    close: bool = True,
) -> dict[str, Any]:
    """发送一轮 chat completions。调用方负责缓存/记账；本函数只做预算预检。"""
    runtime = load_runtime_settings()
    remaining = remaining_budget_usd(runtime.llm_monthly_budget_usd)
    reserve = float(settings.get("reserve_usd") or settings.get("max_usd") or 0.5)
    if remaining < reserve:
        raise RequestFailure("monthly_budget_exhausted")
    owned = client is None
    session = client or make_client(timeout=float(settings.get("timeout", 60)))
    payload = dict(settings)
    payload.setdefault("model", runtime.llm_model)
    try:
        return session.complete_messages(messages, payload)
    finally:
        if owned and close:
            session.close()
