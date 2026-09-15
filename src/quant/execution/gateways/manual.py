"""人工执行网关：把订单清单推给 notify，不接触任何券商 API。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from quant.notify import send


@runtime_checkable
class BrokerGateway(Protocol):
    """未来实盘适配器与当前人工通道共用的最小协议。"""

    name: str

    def notify_orders(self, *, title: str, body: str) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ManualGateway:
    """默认网关：邮件/企微/飞书/微信把订单发给人。"""

    name: str = "manual"

    def notify_orders(self, *, title: str, body: str) -> dict[str, Any]:
        results = send(title, body)
        return {
            "gateway": self.name,
            "submitted": False,
            "notified": any(item.ok for item in results),
            "channels": [item.channel for item in results if item.ok],
        }


def format_orders(path: Path, *, limit: int = 20) -> str:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    head = lines[: limit + 1]
    extra = max(0, len(lines) - len(head))
    body = "\n".join(head)
    if extra:
        body += f"\n... 其余 {extra} 行见 {path}"
    return body
