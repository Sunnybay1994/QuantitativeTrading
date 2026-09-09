"""Public Yahoo chart requests using the existing HTTP dependency."""

from typing import Any

import httpx


def fetch_chart(symbol: str, frequency: str) -> dict[str, Any]:
    ranges = {"1m": "7d", "5m": "60d", "60m": "730d", "1d": "2y"}
    if frequency not in ranges:
        raise ValueError("Unsupported Yahoo frequency")
    response = httpx.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"range": ranges[frequency], "interval": frequency,
                "includePrePost": "false", "events": "div,splits"},
        headers={"User-Agent": "Mozilla/5.0"}, timeout=40,
    )
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    if payload.get("chart", {}).get("error") or not payload.get("chart", {}).get("result"):
        raise ValueError("Yahoo returned no chart")
    return payload
