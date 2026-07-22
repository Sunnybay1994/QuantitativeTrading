"""Fail-closed placeholder for licensed HKEX ETP reference-data access.

HKEX's public website terms prohibit programmatic/scripted access and systematic
retrieval without written permission.  The former website/JSONP implementation
is therefore deliberately disabled.  A future implementation must use a
separately licensed HKEX product/API and retain its entitlement evidence.
"""

from __future__ import annotations

import datetime as dt
import re

import httpx
import polars as pl

HKEX_ETP_SELECTION_RULE = "latest_trade_date_lte_as_of_v1"

_SYMBOL = re.compile(r"^\d{5}\.HK$")


class HkexEtpConnector:
    """Reject public-website collection until a licensed adapter is configured."""

    source = "hkex"

    def __init__(self, client: httpx.Client | None = None) -> None:
        # Keep the narrow constructor compatible with existing dependency
        # injection, but never call the client from this disabled adapter.
        self._client = client

    def fetch_etp_instruments(
        self, *, target_symbols: tuple[str, ...], as_of: dt.date
    ) -> pl.DataFrame:
        """Fail closed instead of accessing HKEX's public website mechanically."""
        _normalize_targets(target_symbols)
        if type(as_of) is not dt.date:
            raise ValueError("HKEX_ETP_TARGETS_INVALID")
        raise ValueError("HKEX_ETP_LICENSE_REQUIRED")


def _normalize_targets(symbols: tuple[str, ...]) -> tuple[str, ...]:
    if (
        not symbols
        or any(type(symbol) is not str or not _SYMBOL.fullmatch(symbol) for symbol in symbols)
        or len(set(symbols)) != len(symbols)
        or tuple(sorted(symbols)) != symbols
    ):
        raise ValueError("HKEX_ETP_TARGETS_INVALID")
    return symbols
