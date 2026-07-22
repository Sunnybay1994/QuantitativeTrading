"""M4-D1 execution-facing data repository Protocols (no IO, no connector SDK)."""

from __future__ import annotations

import datetime as dt
from typing import Protocol, runtime_checkable

from quant.domain.enums import ConnectRoute
from quant.execution.contracts import (
    AccountSnapshot,
    VerifiedConnectMarketContext,
    VerifiedMarketSnapshot,
)


@runtime_checkable
class MarketDataRepository(Protocol):
    """Load a verified multi-symbol market snapshot by explicit keys and as_of."""

    def load_verified_market_snapshot(
        self,
        *,
        symbols: tuple[str, ...],
        session_date: dt.date,
        as_of: dt.datetime,
        connect_routes: tuple[ConnectRoute, ...],
    ) -> VerifiedMarketSnapshot: ...


@runtime_checkable
class AccountSnapshotRepository(Protocol):
    """Load a canonical account snapshot known at or before as_of."""

    def load_account_snapshot(self, *, as_of: dt.datetime) -> AccountSnapshot: ...


@runtime_checkable
class ConnectMarketContextRepository(Protocol):
    """Load verified route-level connect calendar/quota facts by explicit route.

    runtime_checkable only proves the method name exists. Adapters and callers must
    separately enforce: return is VerifiedConnectMarketContext with matching identity;
    returned route/session_date equal query keys; context.as_of <= query as_of.
    """

    def load_verified_connect_market_context(
        self,
        *,
        route: ConnectRoute,
        session_date: dt.date,
        as_of: dt.datetime,
    ) -> VerifiedConnectMarketContext: ...


__all__ = [
    "AccountSnapshotRepository",
    "ConnectMarketContextRepository",
    "MarketDataRepository",
]
