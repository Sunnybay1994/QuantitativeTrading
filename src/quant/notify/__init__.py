"""人工交易通知：邮件 / 企业微信 / 飞书 / wxauto。密钥只走环境变量。

未配置任何通道时写入 ``artifacts/notify/outbox.jsonl``，不视为失败——本机可以先跑通。
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import tomllib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from quant.core.paths import project_paths
from quant.core.settings import load_runtime_settings

__all__ = ["SendResult", "load_notify_config", "send", "main"]


@dataclass(frozen=True)
class SendResult:
    channel: str
    ok: bool
    detail: str


def load_notify_config(path: Path | None = None) -> dict[str, Any]:
    runtime = load_runtime_settings()
    config_path = path or runtime.notify_config
    if not config_path.is_absolute():
        config_path = project_paths().root / config_path
    if not config_path.exists():
        return {"notify": {"enabled": True, "channels": []}}
    with config_path.open("rb") as stream:
        return tomllib.load(stream)


def _outbox_path() -> Path:
    path = project_paths().artifacts / "notify" / "outbox.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _write_outbox(title: str, body: str, channels: list[str]) -> SendResult:
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "body": body,
        "channels": channels,
    }
    path = _outbox_path()
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return SendResult("outbox", True, str(path))


def _send_email(title: str, body: str, config: dict[str, Any]) -> SendResult:
    section = dict(config.get("email") or {})
    host = str(section.get("smtp_host") or os.environ.get("SMTP_HOST") or "").strip()
    port = int(section.get("smtp_port") or os.environ.get("SMTP_PORT") or 587)
    sender = str(section.get("from_addr") or os.environ.get("SMTP_FROM") or "").strip()
    recipients = list(section.get("to_addrs") or [])
    if os.environ.get("SMTP_TO"):
        recipients = [item.strip() for item in os.environ["SMTP_TO"].split(",") if item.strip()]
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    user = str(section.get("username") or os.environ.get("SMTP_USERNAME") or sender).strip()
    if not host or not sender or not recipients:
        return SendResult("email", False, "缺少 SMTP_HOST / from / to")
    message = EmailMessage()
    message["Subject"] = title
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(body)
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.starttls()
        if password:
            smtp.login(user, password)
        smtp.send_message(message)
    return SendResult("email", True, f"to={len(recipients)}")


def _post_webhook(channel: str, url: str, payload: dict[str, Any]) -> SendResult:
    parsed = urlparse(url)
    if parsed.scheme not in {"https"} or not parsed.netloc:
        return SendResult(channel, False, "webhook 必须是 https URL")
    response = httpx.post(url, json=payload, timeout=20, trust_env=False)
    if response.status_code >= 300:
        return SendResult(channel, False, f"http_{response.status_code}")
    return SendResult(channel, True, f"http_{response.status_code}")


def _send_wecom(title: str, body: str) -> SendResult:
    url = os.environ.get("WECOM_WEBHOOK", "").strip()
    if not url:
        return SendResult("wecom", False, "未设置 WECOM_WEBHOOK")
    text = f"{title}\n{body}"[:2000]
    return _post_webhook("wecom", url, {"msgtype": "text", "text": {"content": text}})


def _send_feishu(title: str, body: str) -> SendResult:
    url = os.environ.get("FEISHU_WEBHOOK", "").strip()
    if not url:
        return SendResult("feishu", False, "未设置 FEISHU_WEBHOOK")
    return _post_webhook(
        "feishu",
        url,
        {"msg_type": "text", "content": {"text": f"{title}\n{body}"[:2000]}},
    )


def _send_wxauto(title: str, body: str, config: dict[str, Any]) -> SendResult:
    group = str((config.get("wxauto") or {}).get("group") or os.environ.get("WXAUTO_GROUP") or "")
    if not group.strip():
        return SendResult("wxauto", False, "未设置群名")
    from quant.reporting.wechat import connect

    text = f"{title}\n{body}"
    if len(text) > 2000:
        text = text[:1997] + "..."
    client = connect(group)
    client.select()
    client.send(text)
    return SendResult("wxauto", True, group)


_SENDERS = {
    "email": lambda title, body, config: _send_email(title, body, config),
    "wecom": lambda title, body, config: _send_wecom(title, body),
    "feishu": lambda title, body, config: _send_feishu(title, body),
    "wxauto": lambda title, body, config: _send_wxauto(title, body, config),
}


def send(
    title: str,
    body: str,
    *,
    channels: list[str] | None = None,
    config_path: Path | None = None,
    dry_run: bool = False,
) -> list[SendResult]:
    if not title.strip() or not body.strip():
        raise ValueError("title/body 不能为空")
    config = load_notify_config(config_path)
    notify = dict(config.get("notify") or {})
    chosen = list(channels or notify.get("channels") or [])
    if dry_run or not notify.get("enabled", True) or not chosen:
        return [_write_outbox(title, body, chosen)]
    results = []
    for name in chosen:
        sender = _SENDERS.get(name)
        if sender is None:
            results.append(SendResult(name, False, "未知通道"))
            continue
        try:
            results.append(sender(title, body, config))
        except Exception as exc:  # noqa: BLE001 — 通道失败不影响其他通道
            results.append(SendResult(name, False, type(exc).__name__))
    if not any(item.ok for item in results):
        results.append(_write_outbox(title, body, chosen))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quant notify", description="向人工通道发送一条通知")
    parser.add_argument("action", choices=["test", "send"])
    parser.add_argument("--title", default="QuantitativeTrading")
    parser.add_argument("--body", default="")
    parser.add_argument("--body-file", type=Path)
    parser.add_argument("--channel", action="append", dest="channels")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    body = args.body
    if args.body_file:
        body = args.body_file.read_text(encoding="utf-8")
    if args.action == "test" and not body:
        body = "notify test"
    results = send(args.title, body, channels=args.channels, dry_run=args.dry_run)
    print(json.dumps([asdict(item) for item in results], ensure_ascii=False))
    return 0 if any(item.ok for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
