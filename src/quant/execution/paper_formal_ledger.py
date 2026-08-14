"""Formal A-share ledger contexts derived from a fresh G1 v5 calendar."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import io
import os
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn, SupportsIndex

import polars as pl

from quant.backtest.ledger import build_settlement_rule
from quant.backtest.ledger_adapter import (
    ExecutionLedgerContext,
    build_execution_ledger_context,
)
from quant.data.m3_release import G1ManifestV5, VerifiedG1Release, verify_g1_release
from quant.domain.canonical_wire import canonical_json_bytes, utc_datetime_text
from quant.domain.enums import Currency, Market
from quant.domain.schemas import TradeCalendarSchema
from quant.execution.contracts import OrderCommand
from quant.execution.paper_formal_execution_store import (
    VerifiedFormalPaperExecutionStoreCapability,
    verify_existing_formal_paper_execution_store_capability,
)

_SCHEMA = "formal-paper-ledger-context-provider-v1"
_CALENDAR = "trade_calendar.parquet"
_SOURCE_SELECTOR = "formal_source_v1"


class FormalPaperLedgerContextError(ValueError):
    """Stable, sanitized formal ledger-context failure."""

    def __init__(self) -> None:
        self.code = "PAPER_FORMAL_LEDGER_CONTEXT_INVALID"
        super().__init__(self.code)

    @property
    def __context__(self) -> None:
        return None

    @__context__.setter
    def __context__(self, value: BaseException | None) -> None:
        del value


@dataclass(frozen=True, slots=True)
class _Attestation:
    token: bytes = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal PAPER ledger provider is process-local")


@dataclass(frozen=True, slots=True)
class VerifiedFormalPaperLedgerContextProvider:
    """Process-local provider bound to one OMS chain and G1 calendar."""

    schema_version: str
    provider_identity: str
    release_id: str
    release_manifest_sha256: str
    calendar_source_identity: str
    open_sessions: tuple[dt.date, ...]
    verified_at: dt.datetime
    _execution_store: VerifiedFormalPaperExecutionStoreCapability = field(
        repr=False, compare=False
    )
    _release: VerifiedG1Release = field(repr=False, compare=False)
    _calendar_path: Path = field(repr=False, compare=False)
    _calendar_object_identity: tuple[int, int] = field(repr=False, compare=False)
    _calendar_sha256: str = field(repr=False, compare=False)
    _attestation: _Attestation = field(repr=False, compare=False)

    def context_for(self, command: OrderCommand) -> ExecutionLedgerContext:
        """Fresh-build the immutable context for one exact A-share command."""
        return _context_for(self, command)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal PAPER ledger provider is process-local")


class _Failure(Exception):
    pass


def _create_api():  # type: ignore[no-untyped-def]
    key = secrets.token_bytes(32)

    def token(value: VerifiedFormalPaperLedgerContextProvider) -> bytes:
        return hmac.new(
            key, canonical_json_bytes(_payload(value)), hashlib.sha256
        ).digest()

    def valid(value: VerifiedFormalPaperLedgerContextProvider) -> bool:
        try:
            return type(value._attestation) is _Attestation and hmac.compare_digest(
                value._attestation.token, token(value)
            )
        except Exception:
            return False

    def load_verified_formal_paper_ledger_context_provider(
        *,
        execution_store: VerifiedFormalPaperExecutionStoreCapability,
        release: VerifiedG1Release,
        now: dt.datetime,
    ) -> VerifiedFormalPaperLedgerContextProvider:
        try:
            timestamp = _utc(now)
            store = verify_existing_formal_paper_execution_store_capability(
                capability=execution_store, now=timestamp
            )
            if store is not execution_store:
                raise _Failure
            fresh = _fresh_release(release)
            if execution_store.environment.config.source_selector != _SOURCE_SELECTOR:
                raise _Failure
            path, object_identity, raw_sha256, sessions, source_identity = _calendar(
                fresh
            )
            stable = {
                "schema_version": _SCHEMA,
                "execution_store_identity": execution_store.store_identity,
                "policy_identity": execution_store.policy.policy_identity,
                "account_id": execution_store.account_id,
                "release_id": fresh.release.release_id,
                "release_manifest_sha256": fresh.manifest_sha256,
                "calendar_source_identity": source_identity,
                "open_sessions": [item.isoformat() for item in sessions],
            }
            value = VerifiedFormalPaperLedgerContextProvider(
                schema_version=_SCHEMA,
                provider_identity=_digest(stable),
                release_id=fresh.release.release_id,
                release_manifest_sha256=fresh.manifest_sha256,
                calendar_source_identity=source_identity,
                open_sessions=sessions,
                verified_at=timestamp,
                _execution_store=execution_store,
                _release=fresh,
                _calendar_path=path,
                _calendar_object_identity=object_identity,
                _calendar_sha256=raw_sha256,
                _attestation=_Attestation(b""),
            )
            object.__setattr__(value, "_attestation", _Attestation(token(value)))
            if not valid(value):
                raise _Failure
            return value
        except Exception:
            pass
        raise FormalPaperLedgerContextError() from None

    def verify_existing_formal_paper_ledger_context_provider(
        *, provider: VerifiedFormalPaperLedgerContextProvider, now: dt.datetime
    ) -> VerifiedFormalPaperLedgerContextProvider:
        try:
            timestamp = _utc(now)
            if (
                type(provider) is not VerifiedFormalPaperLedgerContextProvider
                or not valid(provider)
                or timestamp < provider.verified_at
            ):
                raise _Failure
            store = verify_existing_formal_paper_execution_store_capability(
                capability=provider._execution_store, now=timestamp
            )
            if store is not provider._execution_store:
                raise _Failure
            fresh = _fresh_release(provider._release)
            path, object_identity, raw_sha256, sessions, source_identity = _calendar(
                fresh
            )
            if (
                path != provider._calendar_path
                or object_identity != provider._calendar_object_identity
                or raw_sha256 != provider._calendar_sha256
                or sessions != provider.open_sessions
                or source_identity != provider.calendar_source_identity
                or fresh.release.release_id != provider.release_id
                or fresh.manifest_sha256 != provider.release_manifest_sha256
                or provider.provider_identity != _digest(_stable_payload(provider))
            ):
                raise _Failure
            return provider
        except Exception:
            pass
        raise FormalPaperLedgerContextError() from None

    def context_for(
        provider: VerifiedFormalPaperLedgerContextProvider, command: OrderCommand
    ) -> ExecutionLedgerContext:
        try:
            if type(command) is not OrderCommand:
                raise _Failure
            verified = verify_existing_formal_paper_ledger_context_provider(
                provider=provider, now=provider.verified_at
            )
            if command.intent.market not in {Market.SH, Market.SZ}:
                raise _Failure
            if (
                command.intent.quote_currency is not Currency.CNY
                or command.intent.session_date not in verified.open_sessions
            ):
                raise _Failure
            rule = build_settlement_rule(
                selector=verified._execution_store.policy.a_share_rule_selector,
                market=command.intent.market,
                quote_currency=Currency.CNY,
                settlement_currency=Currency.CNY,
                effective_from=verified.open_sessions[0],
                effective_to=verified.open_sessions[-1],
                trading_sessions=verified.open_sessions,
                settlement_sessions=verified.open_sessions,
                trading_calendar_source_identity=verified.calendar_source_identity,
                settlement_calendar_source_identity=verified.calendar_source_identity,
                settlement_lag_sessions=0,
                sellable_lag_sessions=1,
                reuse_sell_receivables=False,
            )
            return build_execution_ledger_context(
                command=command, settlement_rule=rule, fx_snapshot=None
            )
        except Exception:
            pass
        raise FormalPaperLedgerContextError() from None

    return (
        load_verified_formal_paper_ledger_context_provider,
        verify_existing_formal_paper_ledger_context_provider,
        context_for,
    )


(
    load_verified_formal_paper_ledger_context_provider,
    verify_existing_formal_paper_ledger_context_provider,
    _context_for,
) = _create_api()
del _create_api


def _fresh_release(release: VerifiedG1Release) -> VerifiedG1Release:
    if type(release) is not VerifiedG1Release or type(release.manifest) is not G1ManifestV5:
        raise _Failure
    fresh = verify_g1_release(release=release.release)
    if (
        type(fresh) is not VerifiedG1Release
        or type(fresh.manifest) is not G1ManifestV5
        or fresh != release
    ):
        raise _Failure
    return fresh


def _calendar(
    release: VerifiedG1Release,
) -> tuple[Path, tuple[int, int], str, tuple[dt.date, ...], str]:
    path = dict(release.artifact_paths)[_CALENDAR]
    before = _file_identity(path)
    raw = path.read_bytes()
    if path.read_bytes() != raw or _file_identity(path) != before:
        raise _Failure
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    entry = next(item for item in release.manifest.files if item.path == _CALENDAR)
    if raw_sha256 != entry.sha256 or len(raw) != entry.size_bytes:
        raise _Failure
    frame = pl.read_parquet(io.BytesIO(raw))
    checked = TradeCalendarSchema.validate(frame)
    if not checked.equals(frame):
        raise _Failure
    expected_order = frame.sort(["market", "date"])
    if not frame.equals(expected_order) or frame.select(["market", "date"]).n_unique() != frame.height:
        raise _Failure
    selected = frame.filter(
        pl.col("market").is_in([Market.SH.value, Market.SZ.value])
        & pl.col("is_open")
    )
    sh = tuple(selected.filter(pl.col("market") == Market.SH.value)["date"].to_list())
    sz = tuple(selected.filter(pl.col("market") == Market.SZ.value)["date"].to_list())
    if not sh or sh != sz or sh != tuple(sorted(set(sh))):
        raise _Failure
    source_identity = _digest(
        {
            "schema_version": "formal-paper-calendar-source-v1",
            "release_id": release.release.release_id,
            "manifest_sha256": release.manifest_sha256,
            "calendar_sha256": raw_sha256,
            "calendar_content_sha256": entry.content_sha256,
            "sessions": [item.isoformat() for item in sh],
        }
    )
    return path, before, raw_sha256, sh, source_identity


def _file_identity(path: Path) -> tuple[int, int]:
    value = os.lstat(path)
    if not stat.S_ISREG(value.st_mode) or stat.S_ISLNK(value.st_mode) or value.st_nlink != 1:
        raise _Failure
    return value.st_dev, value.st_ino


def _payload(value: VerifiedFormalPaperLedgerContextProvider) -> dict[str, object]:
    return {**_stable_payload(value), "verified_at": utc_datetime_text(value.verified_at)}


def _stable_payload(value: VerifiedFormalPaperLedgerContextProvider) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "execution_store_identity": value._execution_store.store_identity,
        "policy_identity": value._execution_store.policy.policy_identity,
        "account_id": value._execution_store.account_id,
        "release_id": value.release_id,
        "release_manifest_sha256": value.release_manifest_sha256,
        "calendar_source_identity": value.calendar_source_identity,
        "open_sessions": [item.isoformat() for item in value.open_sessions],
    }


def _digest(value: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _utc(value: dt.datetime) -> dt.datetime:
    if type(value) is not dt.datetime or value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise _Failure
    return value


__all__ = [
    "FormalPaperLedgerContextError",
    "VerifiedFormalPaperLedgerContextProvider",
    "load_verified_formal_paper_ledger_context_provider",
    "verify_existing_formal_paper_ledger_context_provider",
]
