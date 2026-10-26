"""Code-frozen LLM tariff. Callers pass a path so tests never touch this file."""

from __future__ import annotations

import tomllib
from pathlib import Path

DEFAULT_PRICING = Path("configs/llm/pricing.toml")


def load_pricing(path: Path | None = None) -> dict[str, float]:
    tariff = path or DEFAULT_PRICING
    payload = tomllib.loads(tariff.read_text(encoding="utf-8"))
    rates = {}
    for key in ("input_usd_per_million", "output_usd_per_million"):
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"{key} must be a positive number")
        rates[key] = float(value)
    return rates
