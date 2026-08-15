"""Public-chain fixtures for mixed HK availability query tests.

Capability objects are produced only through ``finalize_hk_history`` plus
``load_verified_hk_bar_bundle``. Tests must not construct bundles via
``object.__new__`` or monkeypatch seal/registry/attestation internals.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

import quant.data.hkex_daily_quotations as hkex_daily_quotations
from quant.data.hk_history_backfill import (
    HK_DAILY_FIELDS,
    HKHistoryPlan,
    HKHistorySeed,
    HKNoTradeEvidenceSet,
    VerifiedHkBarBundle,
    build_hk_history_plan_v2,
    execute_next_hk_history_request,
    finalize_hk_history,
    load_hk_no_trade_evidence,
    load_verified_hk_bar_bundle,
    write_or_verify_plan,
)
from quant.data.storage import RawStore

UTC = dt.timezone.utc
AS_OF = dt.date(2026, 7, 10)
WINDOW_START = dt.date(2026, 4, 14)
UA_M1_004_DATES = (
    dt.date(2026, 4, 14),
    dt.date(2026, 4, 15),
    dt.date(2026, 4, 16),
    dt.date(2026, 4, 17),
    dt.date(2026, 4, 20),
    dt.date(2026, 4, 21),
    dt.date(2026, 4, 22),
    dt.date(2026, 4, 23),
    dt.date(2026, 4, 24),
    dt.date(2026, 4, 27),
    dt.date(2026, 4, 28),
    dt.date(2026, 4, 29),
    dt.date(2026, 4, 30),
)


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


@dataclass(frozen=True)
class PublishedHkV3Fixture:
    plan: HKHistoryPlan
    plan_path: Path
    data_root: Path
    raw_root: Path
    journal_root: Path
    clean_root: Path
    observed_at: dt.datetime
    verification_as_of: dt.datetime
    bundle: VerifiedHkBarBundle


class FakeConnector:
    def __init__(self, frame: pl.DataFrame) -> None:
        self.frame = frame
        self.calls: list[dict[str, object]] = []

    def fetch_hk_daily_batch_raw(self, **kwargs: object) -> pl.DataFrame:
        self.calls.append(kwargs)
        return self.frame


def raw_frame(symbol_dates: dict[str, list[dt.date]]) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol, dates in symbol_dates.items():
        for index, date in enumerate(dates, start=1):
            price = 10.0 + index
            rows.append(
                {
                    "ts_code": symbol,
                    "trade_date": date.strftime("%Y%m%d"),
                    "open": price,
                    "high": price + 1,
                    "low": price - 1,
                    "close": price + 0.5,
                    "pre_close": price - 0.5,
                    "change": 1.0,
                    "pct_chg": 1.0,
                    "vol": 100.0,
                    "amount": 1000.0,
                }
            )
    return pl.DataFrame(rows).select(HK_DAILY_FIELDS.split(","))


def write_seed(root: Path, expected: dict[str, list[dt.date]]) -> tuple[HKHistorySeed, dt.datetime]:
    fetched_at = dt.datetime(2026, 7, 18, 10, tzinfo=UTC)
    snapshot = RawStore(root).write(
        source="tushare",
        table="hk_daily_multi_symbol_probe",
        frame=raw_frame(expected),
        parameters={"probe": "seed"},
        fetched_at=fetched_at,
    )
    return (
        HKHistorySeed(
            snapshot.data_path.relative_to(root).as_posix(),
            tuple(sorted(expected)),
            snapshot.checksum_sha256,
            hashlib.sha256(snapshot.metadata_path.read_bytes()).hexdigest(),
        ),
        fetched_at,
    )


def write_synthetic_no_trade(
    root: Path, *, symbol: str, trade_date: dt.date
) -> HKNoTradeEvidenceSet:
    selector = "hkex/daily/d260710e.html"
    raw_path = root / selector
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_payload = b"SYNTHETIC HKEX DAILY QUOTATIONS FIXTURE"
    raw_path.write_bytes(raw_payload)
    base = {
        "schema_version": "hk-no-trade-evidence-v1",
        "symbol": symbol,
        "trade_date": trade_date.isoformat(),
        "market": "HK",
        "reason": "NO_DAILY_TRADING_V1",
        "source": "HKEX_DAILY_QUOTATIONS",
        "source_record_id": "synthetic-fixture-record",
        "source_as_of": "2026-07-31T00:00:00+00:00",
        "raw_selector": selector,
        "raw_file_sha256": hashlib.sha256(raw_payload).hexdigest(),
        "raw_metadata_sha256": "0" * 64,
    }
    metadata = {
        "schema_version": "hk-no-trade-raw-metadata-v1",
        "source": base["source"],
        "source_record_id": base["source_record_id"],
        "source_as_of": base["source_as_of"],
        "raw_selector": selector,
        "raw_file_sha256": base["raw_file_sha256"],
    }
    metadata_payload = canonical_json(metadata)
    raw_path.with_suffix(".json").write_bytes(metadata_payload)
    base["raw_metadata_sha256"] = hashlib.sha256(metadata_payload).hexdigest()
    base["evidence_sha256"] = hashlib.sha256(canonical_json(base)).hexdigest()
    payload = {
        "schema_version": "hk-no-trade-evidence-set-v1",
        "evidences": [base],
        "evidence_set_sha256": hashlib.sha256(canonical_json([base])).hexdigest(),
    }
    path = root / "evidence.json"
    path.write_bytes(canonical_json(payload))
    return load_hk_no_trade_evidence(path, raw_root=root)


def write_ua_m1_001(root: Path) -> dict[str, object]:
    selector = "user-approved-consensus/ua-m1-001-01065-2026-05-05.record"
    raw_path = root / selector
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw = {
        "approval_id": "UA-M1-001",
        "approved_on": "2026-08-15",
        "decision": "NO_DAILY_TRADING_V1",
        "evidence": [
            {
                "observation": "NO_DAILY_TRADING",
                "source_kind": "USER_SECURITIES_SOFTWARE",
            },
            {
                "observation": "ZERO_ROWS_ON_TARGETED_RETRY",
                "source_kind": "TUSHARE_HK_DAILY",
            },
        ],
        "impact_assessment": {
            "changes_cash": False,
            "changes_corporate_actions": False,
            "changes_positions": False,
            "changes_real_orders": False,
            "changes_strategy_signal": False,
        },
        "schema_version": "hk-no-trade-user-approved-consensus-v1",
        "symbol": "01065.HK",
        "trade_date": "2026-05-05",
    }
    raw_payload = canonical_json(raw)
    raw_path.write_bytes(raw_payload)
    base = {
        "schema_version": "hk-no-trade-evidence-v1",
        "symbol": "01065.HK",
        "trade_date": "2026-05-05",
        "market": "HK",
        "reason": "NO_DAILY_TRADING_V1",
        "source": "USER_APPROVED_MULTI_SOURCE_CONSENSUS",
        "source_record_id": "UA-M1-001",
        "source_as_of": "2026-08-15T00:00:00+00:00",
        "raw_selector": selector,
        "raw_file_sha256": hashlib.sha256(raw_payload).hexdigest(),
        "raw_metadata_sha256": "0" * 64,
    }
    metadata = {
        "schema_version": "hk-no-trade-raw-metadata-v1",
        "source": base["source"],
        "source_record_id": base["source_record_id"],
        "source_as_of": base["source_as_of"],
        "raw_selector": selector,
        "raw_file_sha256": base["raw_file_sha256"],
    }
    metadata_payload = canonical_json(metadata)
    raw_path.with_suffix(".json").write_bytes(metadata_payload)
    base["raw_metadata_sha256"] = hashlib.sha256(metadata_payload).hexdigest()
    base["evidence_sha256"] = hashlib.sha256(canonical_json(base)).hexdigest()
    return base


def write_ua_m1_004(root: Path) -> list[dict[str, object]]:
    selector = "user-approved-consensus/ua-m1-004-02402-2026-04-01-to-2026-05-04.record"
    raw_path = root / selector
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw = {
        "approval_id": "UA-M1-004",
        "no_trade_dates": [item.isoformat() for item in UA_M1_004_DATES],
        "observations": [
            {
                "observation": "H_SHARES_SUSPENDED_FROM_2026-04-01T01:00:00+00:00",
                "source_kind": "HKEX_NEWS",
                "url": (
                    "https://www.hkexnews.hk/listedco/listconews/sehk/2026/0401/2026040100185.htm"
                ),
            },
            {
                "observation": "H_SHARES_RESUMED_FROM_2026-05-04T01:00:00+00:00",
                "source_kind": "HKEX_NEWS",
                "url": (
                    "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0504/2026050400135.htm"
                ),
            },
            {
                "observation": "RETAINED_ZERO_ROW",
                "source_kind": "TUSHARE_HK_DAILY",
            },
        ],
        "resumption_at": "2026-05-04T01:00:00+00:00",
        "schema_version": "hk-no-trade-user-approved-suspension-range-v1",
        "suspension_at": "2026-04-01T01:00:00+00:00",
        "symbol": "02402.HK",
    }
    raw_payload = canonical_json(raw)
    raw_path.write_bytes(raw_payload)
    shared = {
        "schema_version": "hk-no-trade-evidence-v1",
        "market": "HK",
        "reason": "NO_DAILY_TRADING_V1",
        "source": "USER_APPROVED_MULTI_SOURCE_CONSENSUS",
        "source_record_id": "UA-M1-004",
        "source_as_of": "2026-08-15T00:00:00+00:00",
        "raw_selector": selector,
        "raw_file_sha256": hashlib.sha256(raw_payload).hexdigest(),
        "raw_metadata_sha256": "0" * 64,
    }
    metadata = {
        "schema_version": "hk-no-trade-raw-metadata-v1",
        "source": shared["source"],
        "source_record_id": shared["source_record_id"],
        "source_as_of": shared["source_as_of"],
        "raw_selector": selector,
        "raw_file_sha256": shared["raw_file_sha256"],
    }
    metadata_payload = canonical_json(metadata)
    raw_path.with_suffix(".json").write_bytes(metadata_payload)
    metadata_sha256 = hashlib.sha256(metadata_payload).hexdigest()
    evidences = []
    for trade_date in UA_M1_004_DATES:
        item = {
            **shared,
            "symbol": "02402.HK",
            "trade_date": trade_date.isoformat(),
            "raw_metadata_sha256": metadata_sha256,
        }
        item["evidence_sha256"] = hashlib.sha256(canonical_json(item)).hexdigest()
        evidences.append(item)
    return evidences


def load_combined_evidence(root: Path, *, include_ua_m1_004: bool) -> HKNoTradeEvidenceSet:
    evidences = [write_ua_m1_001(root)]
    if include_ua_m1_004:
        evidences.extend(write_ua_m1_004(root))
    evidences = sorted(evidences, key=lambda item: (item["symbol"], item["trade_date"]))
    payload = {
        "schema_version": "hk-no-trade-evidence-set-v1",
        "evidences": evidences,
        "evidence_set_sha256": hashlib.sha256(canonical_json(evidences)).hexdigest(),
    }
    path = root / "combined-no-trade-evidence.json"
    path.write_bytes(canonical_json(payload))
    return load_hk_no_trade_evidence(path, raw_root=root)


def _verified_hkex(raw: bytes) -> SimpleNamespace:
    return SimpleNamespace(
        evidence_id="e" * 64,
        evidence=SimpleNamespace(
            symbol="02983.HK",
            trade_date=dt.date(2026, 7, 10),
            open=Decimal("16.53"),
            high=Decimal("16.59"),
            low=Decimal("16.38"),
            close=Decimal("16.46"),
            sales_volume=2_640_331,
            sales_turnover=Decimal("43420387.430"),
            raw_sha256=hashlib.sha256(raw).hexdigest(),
            source_record_id="HKEX_DAILY_QUOTATIONS:2026-07-10:2983",
        ),
    )


def retained_hkex_bundle(monkeypatch: pytest.MonkeyPatch, raw: bytes, *, observed_at: dt.datetime):
    monkeypatch.setattr(
        hkex_daily_quotations,
        "verify_hkex_daily_quotation",
        lambda *_args, **_kwargs: _verified_hkex(raw),
    )
    base = {
        "schema_version": "hkex-daily-quotation-retained-metadata-v1",
        "source": "HKEX_DAILY_QUOTATIONS",
        "source_record_id": "HKEX_DAILY_QUOTATIONS:2026-07-10:2983",
        "report_trade_date": "2026-07-10",
        "market": "HK",
        "source_observed_at": observed_at.isoformat(),
        "raw_file_sha256": hashlib.sha256(raw).hexdigest(),
    }
    base["metadata_identity"] = hkex_daily_quotations._identity(
        "HKEXDailyQuotationRetainedMetadata", base
    )
    return hkex_daily_quotations.verify_hkex_daily_quotation_retained(
        raw,
        canonical_json(base),
        source_url=hkex_daily_quotations.SOURCE_URL,
        expected_raw_sha256=hkex_daily_quotations.EXPECTED_RAW_SHA256,
    )


def publish_minimal_v3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    seed_dates: dict[str, list[dt.date]] | None = None,
    request_dates: dict[str, list[dt.date]] | None = None,
    evidence: HKNoTradeEvidenceSet | None = None,
    extra_expected: dict[str, list[dt.date]] | None = None,
    evidence_mode: str = "synthetic",
) -> PublishedHkV3Fixture:
    data_root = tmp_path / "data"
    raw_root = data_root / "raw"
    journal_root = tmp_path / "journal"
    clean_root = data_root / "clean" / "bar_1d"
    seed_dates = seed_dates or {"00001.HK": [AS_OF]}
    request_dates = request_dates or {"00002.HK": [AS_OF]}
    seed, seed_time = write_seed(raw_root, seed_dates)
    if evidence is None:
        if evidence_mode == "ua-v2b":
            evidence = load_combined_evidence(raw_root, include_ua_m1_004=True)
        elif evidence_mode == "ua-001":
            evidence = load_combined_evidence(raw_root, include_ua_m1_004=False)
        else:
            evidence = write_synthetic_no_trade(raw_root, symbol="01065.HK", trade_date=AS_OF)
    expected = {
        **seed_dates,
        **request_dates,
        "02983.HK": [AS_OF],
    }
    if "01065.HK" not in expected:
        expected["01065.HK"] = [AS_OF]
    if extra_expected:
        expected.update(extra_expected)
    plan = build_hk_history_plan_v2(
        expected_dates=expected,
        seed=seed,
        unresolved={"02983.HK": [AS_OF]},
        evidence=evidence,
        as_of=AS_OF,
        window_start=WINDOW_START,
    )
    plan_path = tmp_path / "plan.json"
    write_or_verify_plan(plan_path, plan)
    execute_next_hk_history_request(
        plan=plan,
        connector=FakeConnector(raw_frame(request_dates)),  # type: ignore[arg-type]
        raw_store=RawStore(raw_root),
        journal_root=journal_root,
        seed_raw_root=raw_root,
        now=lambda: seed_time + dt.timedelta(seconds=3601),
    )
    observed_at = dt.datetime(2026, 8, 15, 12, tzinfo=UTC)
    hkex_bundle = retained_hkex_bundle(
        monkeypatch, b"SYNTHETIC RETAINED HKEX V3", observed_at=observed_at
    )
    written = finalize_hk_history(
        plan=plan,
        raw_store=RawStore(raw_root),
        journal_root=journal_root,
        seed_raw_root=raw_root,
        clean_root=clean_root,
        hkex_retained_bundle=hkex_bundle,
    )
    del written
    verification_as_of = observed_at + dt.timedelta(days=1)
    bundle = load_verified_hk_bar_bundle(
        plan=plan,
        journal_root=journal_root,
        seed_raw_root=raw_root,
        raw_store=RawStore(raw_root),
        clean_root=clean_root,
        as_of=verification_as_of,
    )
    return PublishedHkV3Fixture(
        plan=plan,
        plan_path=plan_path,
        data_root=data_root,
        raw_root=raw_root,
        journal_root=journal_root,
        clean_root=clean_root,
        observed_at=observed_at,
        verification_as_of=verification_as_of,
        bundle=bundle,
    )
