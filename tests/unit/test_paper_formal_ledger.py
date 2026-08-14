from __future__ import annotations

import datetime as dt
import hashlib
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from quant.data.m3_release import G1ManifestV5, VerifiedG1Release
from quant.domain.enums import Currency, ExecutionMode, Market, OrderSide
from quant.execution.contracts import build_order_command, build_order_intent
from quant.execution.paper_formal_execution_store import (
    VerifiedFormalPaperExecutionStoreCapability,
)
from quant.execution import paper_formal_ledger as formal

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 8, 10, 1, tzinfo=UTC)
SESSIONS = (dt.date(2026, 8, 10), dt.date(2026, 8, 11))


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _release(path: Path) -> VerifiedG1Release:
    frame = pl.DataFrame(
        {
            "market": ["SH", "SH", "SH", "SZ", "SZ", "SZ"],
            "date": [SESSIONS[0], SESSIONS[1], dt.date(2026, 8, 12)] * 2,
            "is_open": [True, True, False] * 2,
            "is_connect_open": [False] * 6,
            "is_half_day": [False] * 6,
        },
        schema={
            "market": pl.String,
            "date": pl.Date,
            "is_open": pl.Boolean,
            "is_connect_open": pl.Boolean,
            "is_half_day": pl.Boolean,
        },
    )
    frame.write_parquet(path)
    raw = path.read_bytes()
    entry = SimpleNamespace(
        path="trade_calendar.parquet",
        sha256=hashlib.sha256(raw).hexdigest(),
        content_sha256=_hex("content"),
        size_bytes=len(raw),
    )
    manifest = object.__new__(G1ManifestV5)
    object.__setattr__(manifest, "files", (entry,))
    release_object = SimpleNamespace(release_id=_hex("release"))
    value = object.__new__(VerifiedG1Release)
    object.__setattr__(value, "release", release_object)
    object.__setattr__(value, "manifest", manifest)
    object.__setattr__(value, "manifest_sha256", _hex("manifest"))
    object.__setattr__(value, "quality", SimpleNamespace())
    object.__setattr__(value, "quality_sha256", _hex("quality"))
    object.__setattr__(
        value, "artifact_paths", (("trade_calendar.parquet", path.resolve()),)
    )
    return value


def _store() -> VerifiedFormalPaperExecutionStoreCapability:
    value = object.__new__(VerifiedFormalPaperExecutionStoreCapability)
    object.__setattr__(value, "store_identity", _hex("store"))
    object.__setattr__(value, "account_id", _hex("account"))
    object.__setattr__(
        value,
        "environment",
        SimpleNamespace(config=SimpleNamespace(source_selector="formal_source_v1")),
    )
    object.__setattr__(
        value,
        "policy",
        SimpleNamespace(
            policy_identity=_hex("policy"),
            a_share_rule_selector="a_share_execution_rules_v1",
        ),
    )
    return value


def _command(*, day: dt.date = SESSIONS[0], market: Market = Market.SH):
    intent = build_order_intent(
        plan_id=_hex("plan"),
        symbol="600000.SH" if market is Market.SH else "000001.SZ",
        market=market,
        side=OrderSide.BUY,
        quantity=100,
        limit_price=Decimal("10.00"),
        quote_currency=Currency.CNY,
        session_date=day,
        generated_at=NOW,
        target_identity=_hex("target"),
        market_snapshot_id=_hex("market"),
        account_snapshot_id=_hex("account-snapshot"),
        config_identity=_hex("config"),
        connect_route=None,
    )
    return build_order_command(intent=intent, mode=ExecutionMode.PAPER)


def test_load_verify_and_build_exact_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _release(tmp_path / "trade_calendar.parquet")
    store = _store()
    monkeypatch.setattr(formal, "verify_g1_release", lambda *, release: globals_release)
    monkeypatch.setattr(
        formal,
        "verify_existing_formal_paper_execution_store_capability",
        lambda *, capability, now: capability,
    )
    globals_release = release
    provider = formal.load_verified_formal_paper_ledger_context_provider(
        execution_store=store, release=release, now=NOW
    )
    assert provider.open_sessions == SESSIONS
    assert (
        formal.verify_existing_formal_paper_ledger_context_provider(
            provider=provider, now=NOW
        )
        is provider
    )
    context = provider.context_for(_command(market=Market.SZ))
    assert context.settlement_rule.trading_sessions == SESSIONS
    assert context.settlement_rule.sellable_lag_sessions == 1
    assert context.fx_snapshot is None


def test_closed_session_tamper_and_hostile_fresh_fail_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _release(tmp_path / "trade_calendar.parquet")
    store = _store()
    monkeypatch.setattr(formal, "verify_g1_release", lambda *, release: globals_release)
    monkeypatch.setattr(
        formal,
        "verify_existing_formal_paper_execution_store_capability",
        lambda *, capability, now: capability,
    )
    globals_release = release
    provider = formal.load_verified_formal_paper_ledger_context_provider(
        execution_store=store, release=release, now=NOW
    )
    with pytest.raises(formal.FormalPaperLedgerContextError) as caught:
        provider.context_for(_command(day=dt.date(2026, 8, 12)))
    assert caught.value.__cause__ is None and caught.value.__context__ is None

    (tmp_path / "trade_calendar.parquet").write_bytes(b"drift")
    with pytest.raises(formal.FormalPaperLedgerContextError):
        formal.verify_existing_formal_paper_ledger_context_provider(
            provider=provider, now=NOW
        )

    def hostile(**kwargs: object) -> object:
        del kwargs
        raise RuntimeError("TOKEN=/hostile/path")

    monkeypatch.setattr(formal, "verify_g1_release", hostile)
    with pytest.raises(formal.FormalPaperLedgerContextError) as hostile_error:
        formal.load_verified_formal_paper_ledger_context_provider(
            execution_store=store, release=release, now=NOW
        )
    assert str(hostile_error.value) == "PAPER_FORMAL_LEDGER_CONTEXT_INVALID"
    assert hostile_error.value.__context__ is None
