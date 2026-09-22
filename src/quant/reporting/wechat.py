"""Small wxauto4 text transport for human-operated trading notifications.

Run from an unlocked Windows desktop. No broker or order execution is connected.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass
import io
import json
import importlib.util
from pathlib import Path
import sys
from typing import Any


@dataclass(frozen=True)
class ChatMessage:
    content: str
    kind: str
    source: str


class WeChatNotifier:
    """Bind one explicitly configured group; never retry ambiguous sends."""

    def __init__(self, backend: Any, group: str) -> None:
        if not group.strip():
            raise ValueError("群名不能为空")
        self.backend = backend
        self.group = group

    def _check_group(self) -> None:
        info = self.backend.ChatInfo()
        if not isinstance(info, dict) or info.get("chat_name") != self.group:
            raise RuntimeError("当前群名未通过精确校验，已停止操作")
        if info.get("chat_type") != "group":
            raise RuntimeError("目标不是群聊，已停止操作")

    def select(self) -> None:
        self.backend.ChatWith(self.group, exact=True)
        self._check_group()

    def read(self) -> list[ChatMessage]:
        self._check_group()
        messages = self.backend.GetAllMessage()
        self._check_group()
        return [
            ChatMessage(
                content=str(getattr(message, "content", "")),
                kind=str(getattr(message, "type", "")),
                source=str(getattr(message, "attr", "unknown")),
            )
            for message in messages
        ]

    def send(self, text: str) -> dict[str, object]:
        if not text.strip() or len(text) > 2000:
            raise ValueError("消息应为 1 至 2000 字符的非空文本")
        self._check_group()
        # Send to the verified current group, avoiding a second fuzzy search.
        # An exception may occur AFTER sending; callers must inspect before retrying.
        result = self.backend.SendMsg(text)
        if not isinstance(result, dict) or result.get("status") != "成功":
            raise RuntimeError("wxauto 未确认发送成功；请检查群聊后再决定是否重试")
        return {"group": self.group, "submitted": True, "recipient_acknowledged": False}


def connect(group: str) -> WeChatNotifier:
    if importlib.util.find_spec('wxauto4') is None:
        from quant.core.paths import project_paths

        runtime = project_paths().artifacts / 'wechat/runtime'
        if not (runtime / 'wxauto4/__init__.py').is_file():
            raise RuntimeError('未找到 wxauto4；请配置微信运行环境后再测试')
        sys.path.insert(0, str(runtime))
    from wxauto4 import WeChat, WxParam  # type: ignore[import-not-found]

    WxParam.ENABLE_FILE_LOGGER = False
    WxParam.TELEMETRY_ENABLED = False
    # wxauto prints the account nickname during startup; keep it out of CLI logs.
    with redirect_stdout(io.StringIO()):
        backend = WeChat(resize=False, ads=False)
    return WeChatNotifier(backend, group)


def main() -> int:
    parser = argparse.ArgumentParser(description="微信指定群文本收发（人工交易通知）")
    parser.add_argument("--group", required=True)
    parser.add_argument("--select", action="store_true", help="先精确切换到指定群")
    sub = parser.add_subparsers(dest="action", required=True)
    read = sub.add_parser("read", help="读取当前可见消息，不导出历史数据库")
    read.add_argument("--contains", default="", help="仅输出包含指定测试编号的消息")
    send = sub.add_parser("send", help="默认只预览；--execute 才发送")
    send.add_argument("--text-file", type=Path, required=True)
    send.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    text = args.text_file.read_text(encoding="utf-8-sig") if args.action == "send" else ""
    if args.action == "send" and not args.execute:
        print(json.dumps({"group": args.group, "preview": text}, ensure_ascii=False))
        return 0
    client = connect(args.group)
    if args.select:
        client.select()
    if args.action == "send":
        output: object = client.send(text)
    else:
        output = [asdict(m) for m in client.read() if args.contains in m.content]
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
