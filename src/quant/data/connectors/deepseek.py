"""DeepSeek chat completions transport, without implicit SDK retries."""
from __future__ import annotations

import os
from pathlib import Path
import tomllib

import httpx

from quant.factors.forecast_text_score import messages, strict_json

ENDPOINT = "https://api.deepseek.com/chat/completions"


class RequestFailure(Exception):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def load_key(project_root: Path) -> str:
    value = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not value:
        path = project_root / "configs/deepseek.local.toml"
        if path.is_file():
            if not path.resolve().is_relative_to(project_root.resolve()):
                raise ValueError("Key configuration must stay within this project")
            # Fixed project-local path only; never search other workspaces.
            try:
                value = tomllib.loads(path.read_text(encoding="utf-8"))["deepseek"]["api_key"]
            except (ValueError, KeyError):
                raise ValueError("Invalid configs/deepseek.local.toml") from None
    if not isinstance(value, str) or not value.strip() or value.startswith("YOUR_"):
        raise ValueError("Fill configs/deepseek.local.toml [deepseek].api_key or DEEPSEEK_API_KEY")
    return value.strip()


class DeepSeekClient:
    def __init__(self, key: str, *, timeout: float = 60,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.client = httpx.Client(
            headers={"Authorization": f"Bearer {key}"}, timeout=timeout,
            follow_redirects=False, trust_env=False, transport=transport,
        )

    def close(self) -> None:
        self.client.close()

    def complete(self, reason: str, settings: dict) -> dict:
        return self.complete_messages(messages(reason), settings)

    def complete_messages(self, prompt_messages: list[dict[str, str]], settings: dict) -> dict:
        try:
            response = self.client.post(ENDPOINT, json={
                "model": settings["model"], "messages": prompt_messages,
                "thinking": {"type": "disabled"}, "temperature": 0,
                "response_format": {"type": "json_object"},
                "max_tokens": settings["max_tokens"], "stream": False,
            })
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise RequestFailure("connect_failed", retryable=True) from None
        except httpx.HTTPError:
            # A timeout after request submission can already have incurred a charge.
            raise RequestFailure("transport_outcome_unknown") from None
        if response.status_code != 200:
            status = response.status_code
            raise RequestFailure(f"http_{status}", retryable=status in {429, 500, 502, 503})
        try:
            return strict_json(response.text)
        except ValueError:
            raise RequestFailure("invalid_response_envelope") from None
