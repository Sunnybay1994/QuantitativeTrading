"""Pure, versioned FX conversion contracts for M4-B3."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from quant.domain.enums import Currency
from quant.execution.contracts import MoneyAmount, build_money_amount

_INPUT_INVALID = "FX_INPUT_INVALID"
_RATE_MISSING = "FX_RATE_MISSING"
_EXPIRED = "FX_SNAPSHOT_EXPIRED"
_HASH_VERSION = "m4-fx-snapshot-v1"
_CENT = Decimal("0.01")


class FxContractError(ValueError):
    """Stable M4 FX contract failure."""


@dataclass(frozen=True, slots=True)
class FxRate:
    source_currency: Currency
    settlement_currency: Currency
    rate: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.source_currency) is not Currency
            or type(self.settlement_currency) is not Currency
            or self.source_currency is self.settlement_currency
            or type(self.rate) is not Decimal
            or not self.rate.is_finite()
            or self.rate <= 0
        ):
            raise FxContractError(_INPUT_INVALID)


@dataclass(frozen=True, slots=True)
class FxSnapshot:
    snapshot_id: str
    selector: str
    session_date: dt.date
    observed_at: dt.datetime
    expires_at: dt.datetime
    rates: tuple[FxRate, ...]

    def __post_init__(self) -> None:
        pairs = tuple(
            (item.source_currency, item.settlement_currency) for item in self.rates
        )
        if (
            type(self.selector) is not str
            or not self.selector
            or any(char in "/\\:%" for char in self.selector)
            or any(ord(char) < 32 or ord(char) == 127 for char in self.selector)
            or type(self.session_date) is not dt.date
            or type(self.observed_at) is not dt.datetime
            or self.observed_at.tzinfo is not dt.UTC
            or type(self.expires_at) is not dt.datetime
            or self.expires_at.tzinfo is not dt.UTC
            or self.expires_at < self.observed_at
            or type(self.rates) is not tuple
            or not self.rates
            or any(type(item) is not FxRate for item in self.rates)
            or len(set(pairs)) != len(pairs)
            or pairs != tuple(sorted(pairs, key=lambda pair: (pair[0].value, pair[1].value)))
            or type(self.snapshot_id) is not str
            or self.snapshot_id != _snapshot_identity(
                selector=self.selector,
                session_date=self.session_date,
                observed_at=self.observed_at,
                expires_at=self.expires_at,
                rates=self.rates,
            )
        ):
            raise FxContractError(_INPUT_INVALID)


def _snapshot_identity(
    *,
    selector: str,
    session_date: dt.date,
    observed_at: dt.datetime,
    expires_at: dt.datetime,
    rates: tuple[FxRate, ...],
) -> str:
    payload = {
        "hash_version": _HASH_VERSION,
        "type": "FxSnapshot",
        "payload": {
            "selector": selector,
            "session_date": session_date.isoformat(),
            "observed_at": observed_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "rates": [
                {
                    "source_currency": item.source_currency.value,
                    "settlement_currency": item.settlement_currency.value,
                    "rate": format(item.rate, "f"),
                }
                for item in rates
            ],
        },
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_fx_snapshot(
    *,
    selector: str,
    session_date: dt.date,
    observed_at: dt.datetime,
    expires_at: dt.datetime,
    rates: tuple[FxRate, ...],
) -> FxSnapshot:
    """Build a canonical snapshot with package-computed identity."""
    try:
        canonical_rates = tuple(
            sorted(rates, key=lambda item: (item.source_currency.value, item.settlement_currency.value))
        )
        identity = _snapshot_identity(
            selector=selector,
            session_date=session_date,
            observed_at=observed_at,
            expires_at=expires_at,
            rates=canonical_rates,
        )
        return FxSnapshot(
            identity,
            selector,
            session_date,
            observed_at,
            expires_at,
            canonical_rates,
        )
    except Exception:
        raise FxContractError(_INPUT_INVALID) from None


def require_fx_snapshot_current(
    snapshot: FxSnapshot, *, session_date: dt.date, at: dt.datetime
) -> FxSnapshot:
    """Prove identity, session and freshness at an explicit decision time."""
    try:
        proven = build_fx_snapshot(
            selector=snapshot.selector,
            session_date=snapshot.session_date,
            observed_at=snapshot.observed_at,
            expires_at=snapshot.expires_at,
            rates=snapshot.rates,
        )
    except Exception:
        raise FxContractError(_INPUT_INVALID) from None
    if proven != snapshot:
        raise FxContractError(_INPUT_INVALID)
    if session_date != proven.session_date or at > proven.expires_at:
        raise FxContractError(_EXPIRED)
    if at < proven.observed_at:
        raise FxContractError(_INPUT_INVALID)
    return proven


def convert_money(
    amount: MoneyAmount,
    fx_snapshot: FxSnapshot,
    settlement_currency: Currency,
) -> MoneyAmount:
    """Convert using an explicit direct rate; inverse rates are never inferred."""
    try:
        if type(amount) is not MoneyAmount or type(settlement_currency) is not Currency:
            raise ValueError
        proven = build_money_amount(amount.currency, amount.amount)
        if proven != amount:
            raise ValueError
        snapshot = build_fx_snapshot(
            selector=fx_snapshot.selector,
            session_date=fx_snapshot.session_date,
            observed_at=fx_snapshot.observed_at,
            expires_at=fx_snapshot.expires_at,
            rates=fx_snapshot.rates,
        )
        if snapshot != fx_snapshot:
            raise ValueError
    except Exception:
        raise FxContractError(_INPUT_INVALID) from None
    if amount.currency is settlement_currency:
        return build_money_amount(
            settlement_currency, amount.amount.quantize(_CENT, rounding=ROUND_HALF_UP)
        )
    matches = tuple(
        item
        for item in snapshot.rates
        if item.source_currency is amount.currency
        and item.settlement_currency is settlement_currency
    )
    if len(matches) != 1:
        raise FxContractError(_RATE_MISSING)
    converted = (amount.amount * matches[0].rate).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )
    return build_money_amount(settlement_currency, converted)


__all__ = [
    "FxContractError",
    "FxRate",
    "FxSnapshot",
    "build_fx_snapshot",
    "convert_money",
    "require_fx_snapshot_current",
]
