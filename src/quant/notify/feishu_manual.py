"""Feishu application transport; platform acceptance is not human receipt.

The caller owns durable inbox/outbox, authorization and retry policy. No broker
API, credentials discovery, implicit recipient or background sending lives here.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

import httpx


class FeishuTransportError(RuntimeError):
    """Sanitized transport failure (never embeds response bodies or credentials)."""


class FeishuManualTransport:
    def __init__(
        self, app_id: str, app_secret: str, allowed_chat_ids: Iterable[str],
        client: httpx.Client | None = None,
    ) -> None:
        if not app_id.strip() or not app_secret.strip():
            raise ValueError("Feishu application credentials required")
        if isinstance(allowed_chat_ids, str):
            raise ValueError("allowed_chat_ids must be a collection")
        self._allowed = frozenset(allowed_chat_ids)
        if not self._allowed or any(not isinstance(x, str) or not x.strip() for x in self._allowed):
            raise ValueError("explicit nonempty chat allowlist required")
        self._app_id, self._app_secret = app_id, app_secret
        self._owned_client = client is None
        self._client = client or httpx.Client(timeout=20, trust_env=False, follow_redirects=False)
        self._token = ""
        self._expires_at = 0.0

    def close(self) -> None:
        if self._owned_client:
            self._client.close()

    def _post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.post("https://open.feishu.cn/open-apis/" + path, **kwargs)
        except httpx.HTTPError:
            raise FeishuTransportError("Feishu network failure; acceptance unknown") from None
        if not 200 <= response.status_code < 300:
            raise FeishuTransportError(f"Feishu HTTP {response.status_code}; acceptance unconfirmed")
        try:
            body = response.json()
        except ValueError:
            raise FeishuTransportError("Feishu invalid JSON response") from None
        if not isinstance(body, dict) or type(body.get("code")) is not int:
            raise FeishuTransportError("Feishu missing business status")
        if body["code"] != 0:
            self._token = ""
            raise FeishuTransportError(f"Feishu business error {body['code']}")
        return body

    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._expires_at:
            return self._token
        body = self._post(
            "auth/v3/tenant_access_token/internal",
            json={"app_id": self._app_id, "app_secret": self._app_secret},
        )
        token, expires = body.get("tenant_access_token"), body.get("expire")
        if not isinstance(token, str) or not token or type(expires) is not int or expires <= 0:
            raise FeishuTransportError("Feishu invalid token response")
        self._token = token
        self._expires_at = time.monotonic() + max(0, expires - 60)
        return token

    def send_text(self, chat_id: str, text: str, uuid: str) -> dict[str, Any]:
        """Send once. Persist and reuse the same UUID for any caller retry."""
        if chat_id not in self._allowed:
            raise ValueError("recipient not allowed")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("nonempty text required")
        if not isinstance(uuid, str) or not uuid.strip() or len(uuid) > 50:
            raise ValueError("stable message uuid required (maximum 50 characters)")
        body = self._post(
            "im/v1/messages", params={"receive_id_type": "chat_id"},
            headers={"Authorization": "Bearer " + self._access_token()},
            json={"receive_id": chat_id, "msg_type": "text",
                  "content": json.dumps({"text": text}, ensure_ascii=False), "uuid": uuid},
        )
        data = body.get("data")
        message_id = data.get("message_id") if isinstance(data, dict) else None
        if not isinstance(message_id, str) or not message_id.strip():
            raise FeishuTransportError("Feishu acceptance missing message_id")
        return {"message_id": message_id, "provider_accepted": True}


def normalize_message_event(payload: dict[str, Any]) -> dict[str, str]:
    """Normalize authenticated SDK text events; caller must check both ID allowlists."""
    try:
        if payload["header"]["event_type"] != "im.message.receive_v1":
            raise ValueError
        event = payload["event"]
        message, sender = event["message"], event["sender"]
        if message["message_type"] != "text" or sender["sender_type"] != "user":
            raise ValueError
        content = json.loads(message["content"])
        result = {"message_id": message["message_id"],
                  "sender_id": sender["sender_id"]["open_id"],
                  "chat_id": message["chat_id"], "text": content["text"]}
        if any(not isinstance(v, str) or not v.strip() for v in result.values()):
            raise ValueError
        timestamp = message["create_time"]
        if not isinstance(timestamp, str) or not timestamp.isdecimal():
            raise ValueError
        result["source_timestamp"] = timestamp
        result["sent_at"] = datetime.fromtimestamp(int(timestamp) / 1000, timezone.utc).isoformat()
        result["received_at"] = datetime.now(timezone.utc).isoformat()
        return result
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        raise ValueError("unsupported or malformed Feishu user text event") from None


def run_long_connection(
    app_id: str, app_secret: str, callback: Callable[[dict[str, str]], None],
) -> None:
    """Block in the official SDK. Callback should durably enqueue before returning.

    Business processing belongs to another worker; callback exceptions propagate
    so an inbox persistence failure is not silently acknowledged.
    """
    if not app_id.strip() or not app_secret.strip():
        raise ValueError("Feishu application credentials required")
    try:
        import lark_oapi as lark
    except ImportError:
        raise RuntimeError("Feishu long connection requires lark-oapi") from None

    def receive(data: Any) -> None:
        try:
            normalized = normalize_message_event(json.loads(lark.JSON.marshal(data)))
        except ValueError:
            return  # Non-text/unsupported messages never enter the trading protocol.
        callback(normalized)

    handler = lark.EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(receive).build()
    connection = lark.ws.Client(
        app_id, app_secret, event_handler=handler, log_level=lark.LogLevel.ERROR,
    )
    connection.start()
