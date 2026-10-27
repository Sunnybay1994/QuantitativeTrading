"""Declared 1-minute stores. Callers open bars through here instead of hardcoding a source."""

from __future__ import annotations

import tomllib
from pathlib import Path

DEFAULT_CONFIG = Path("configs/data/intraday_sources.toml")


def minute_bars_path(
    root: Path,
    symbol: str,
    *,
    role: str = "primary",
    config: Path = DEFAULT_CONFIG,
) -> Path:
    if symbol.endswith(".HK"):
        market = "hk"
    elif symbol.endswith(".US"):
        market = "us"
    elif symbol.endswith((".SH", ".SZ")):
        market = "cn"
    else:
        raise ValueError(f"No intraday source for {symbol}")
    if role not in {"primary", "history"}:
        raise ValueError("role must be primary or history")
    table = tomllib.loads(config.read_text(encoding="utf-8"))[market]
    source = table[role]
    if not isinstance(source, str) or not source:
        raise ValueError(f"Missing {market} {role} source")
    return root / "clean/bar_intraday/freq=1m" / f"source={source}" / f"symbol={symbol}" / "data.parquet"
