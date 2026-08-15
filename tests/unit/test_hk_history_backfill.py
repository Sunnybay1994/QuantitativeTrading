from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import stat
import traceback
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

import quant.data.backfill_hk_history as backfill_hk_history_cli
import quant.data.hk_history_backfill as hk_history_backfill
import quant.data.hkex_daily_quotations as hkex_daily_quotations
from quant.data.hk_history_backfill import (
    HK_DAILY_FIELDS,
    HK_HISTORY_RAW_TABLE,
    HKHistoryBackfillError,
    HKHistorySeed,
    HKNoTradeEvidence,
    build_hk_history_plan_v2,
    build_hk_history_plan,
    execute_next_hk_history_request,
    finalize_hk_history,
    load_hk_history_plan,
    load_verified_hkex_retained_bundle_for_finalize,
    load_hk_no_trade_evidence,
    load_verified_hk_bar_bundle,
    recover_existing_hk_history_requests,
    verify_hk_bar_bundle,
    write_or_verify_plan,
)
from quant.data.storage import RawStore

UTC = dt.timezone.utc


def _assert_sanitized_exception(error: BaseException, marker: str) -> None:
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        assert marker not in str(current)
        assert marker not in repr(current)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert marker not in "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _evidence(root: Path, *, symbol: str, trade_date: dt.date):
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
    metadata_payload = _canonical(metadata)
    raw_path.with_suffix(".json").write_bytes(metadata_payload)
    base["raw_metadata_sha256"] = hashlib.sha256(metadata_payload).hexdigest()
    base["evidence_sha256"] = hashlib.sha256(_canonical(base)).hexdigest()
    evidences = [base]
    value = {
        "schema_version": "hk-no-trade-evidence-set-v1",
        "evidences": evidences,
        "evidence_set_sha256": hashlib.sha256(_canonical(evidences)).hexdigest(),
    }
    path = root / "evidence.json"
    path.write_bytes(_canonical(value))
    return load_hk_no_trade_evidence(path, raw_root=root), path, raw_path


_UA_M1_004_DATES = (
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
_UA_M1_004_SELECTOR = (
    "user-approved-consensus/ua-m1-004-02402-2026-04-01-to-2026-05-04.record"
)
_UA_M1_004_SUSPENSION_URL = (
    "https://www.hkexnews.hk/listedco/listconews/sehk/2026/0401/2026040100185.htm"
)
_UA_M1_004_RESUMPTION_URL = (
    "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0504/2026050400135.htm"
)


def _user_approved_suspension_range_raw(
    *,
    no_trade_dates: tuple[str, ...] | None = None,
    observations: list[dict[str, str]] | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "approval_id": "UA-M1-004",
        "no_trade_dates": list(
            no_trade_dates
            if no_trade_dates is not None
            else (item.isoformat() for item in _UA_M1_004_DATES)
        ),
        "observations": observations
        if observations is not None
        else [
            {
                "observation": "H_SHARES_SUSPENDED_FROM_2026-04-01T01:00:00+00:00",
                "source_kind": "HKEX_NEWS",
                "url": _UA_M1_004_SUSPENSION_URL,
            },
            {
                "observation": "H_SHARES_RESUMED_FROM_2026-05-04T01:00:00+00:00",
                "source_kind": "HKEX_NEWS",
                "url": _UA_M1_004_RESUMPTION_URL,
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
    if extra:
        payload.update(extra)
    return payload


def _user_approved_suspension_range_evidence(
    root: Path,
    *,
    dates: tuple[dt.date, ...] = _UA_M1_004_DATES,
    symbol: str = "02402.HK",
    source: str = "USER_APPROVED_MULTI_SOURCE_CONSENSUS",
    source_record_id: str = "UA-M1-004",
    selector: str = _UA_M1_004_SELECTOR,
    raw: dict[str, object] | None = None,
    source_as_of: str = "2026-08-15T00:00:00+00:00",
):
    dates = tuple(sorted(dates))
    raw_path = root / selector
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_payload = _canonical(
        raw if raw is not None else _user_approved_suspension_range_raw()
    )
    raw_path.write_bytes(raw_payload)
    shared = {
        "schema_version": "hk-no-trade-evidence-v1",
        "market": "HK",
        "reason": "NO_DAILY_TRADING_V1",
        "source": source,
        "source_record_id": source_record_id,
        "source_as_of": source_as_of,
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
    metadata_payload = _canonical(metadata)
    raw_path.with_suffix(".json").write_bytes(metadata_payload)
    metadata_sha256 = hashlib.sha256(metadata_payload).hexdigest()
    evidences = []
    for trade_date in dates:
        item = {
            **shared,
            "symbol": symbol,
            "trade_date": trade_date.isoformat(),
            "raw_metadata_sha256": metadata_sha256,
        }
        item["evidence_sha256"] = hashlib.sha256(_canonical(item)).hexdigest()
        evidences.append(item)
    evidence_set = {
        "schema_version": "hk-no-trade-evidence-set-v1",
        "evidences": evidences,
        "evidence_set_sha256": hashlib.sha256(_canonical(evidences)).hexdigest(),
    }
    path = root / "user-approved-suspension-range-evidence.json"
    path.write_bytes(_canonical(evidence_set))
    return path, raw_path, evidences


_UA_M1_001_SELECTOR = (
    "user-approved-consensus/ua-m1-001-01065-2026-05-05.record"
)


def _user_approved_evidence(
    root: Path,
    *,
    symbol: str = "01065.HK",
    trade_date: dt.date = dt.date(2026, 5, 5),
    source: str = "USER_APPROVED_MULTI_SOURCE_CONSENSUS",
    source_record_id: str = "UA-M1-001",
    selector: str = _UA_M1_001_SELECTOR,
    raw: dict[str, object] | None = None,
):
    raw_path = root / selector
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if raw is None:
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
            "symbol": symbol,
            "trade_date": trade_date.isoformat(),
        }
    raw_payload = _canonical(raw)
    raw_path.write_bytes(raw_payload)
    base = {
        "schema_version": "hk-no-trade-evidence-v1",
        "symbol": symbol,
        "trade_date": trade_date.isoformat(),
        "market": "HK",
        "reason": "NO_DAILY_TRADING_V1",
        "source": source,
        "source_record_id": source_record_id,
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
    metadata_payload = _canonical(metadata)
    raw_path.with_suffix(".json").write_bytes(metadata_payload)
    base["raw_metadata_sha256"] = hashlib.sha256(metadata_payload).hexdigest()
    base["evidence_sha256"] = hashlib.sha256(_canonical(base)).hexdigest()
    evidence_set = {
        "schema_version": "hk-no-trade-evidence-set-v1",
        "evidences": [base],
        "evidence_set_sha256": hashlib.sha256(_canonical([base])).hexdigest(),
    }
    path = root / "user-approved-evidence.json"
    path.write_bytes(_canonical(evidence_set))
    return path, raw_path, base


_UA_M1_005_SELECTOR = (
    "user-approved-consensus/ua-m1-005-06110-2026-06-25.record"
)
_UA_M1_005_HKEX_URL = (
    "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0625/2026062500129.htm"
)
_UA_M1_005_INDEPENDENT_URL = (
    "https://www.etnet.com.hk/www/tc/news/news-article.php"
    "?category=latest&newsid=2026062568&section=categorized"
)
_UA_M1_005_OBSERVATIONS = (
    {
        "observation": "TRADING_HALTED_FROM_09_00",
        "source_kind": "HKEX_NEWS",
        "url": _UA_M1_005_HKEX_URL,
    },
    {
        "observation": "RETAINED_ZERO_ROW",
        "source_kind": "TUSHARE_HK_DAILY",
    },
    {
        "observation": "LISTED_AS_SUSPENDED",
        "source_kind": "INDEPENDENT_PUBLIC_MARKET_NEWS",
        "url": _UA_M1_005_INDEPENDENT_URL,
    },
)
_UA_M1_005_IMPACT = {
    "changes_cash": False,
    "changes_corporate_actions": False,
    "changes_positions": False,
    "changes_real_orders": False,
    "changes_strategy_signal": False,
}


def _user_approved_trading_halt_raw(
    *,
    observations: list[dict[str, str]] | None = None,
    impact_assessment: dict[str, bool] | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "approval_id": "UA-M1-005",
        "decision": "NO_DAILY_TRADING_V1",
        "impact_assessment": dict(
            impact_assessment if impact_assessment is not None else _UA_M1_005_IMPACT
        ),
        "observations": (
            observations
            if observations is not None
            else [dict(item) for item in _UA_M1_005_OBSERVATIONS]
        ),
        "schema_version": "hk-no-trade-user-approved-trading-halt-v1",
        "symbol": "06110.HK",
        "trade_date": "2026-06-25",
    }
    if extra:
        payload.update(extra)
    return payload


def _user_approved_trading_halt_evidence(
    root: Path,
    *,
    symbol: str = "06110.HK",
    trade_date: dt.date = dt.date(2026, 6, 25),
    source: str = "USER_APPROVED_MULTI_SOURCE_CONSENSUS",
    source_record_id: str = "UA-M1-005",
    selector: str = _UA_M1_005_SELECTOR,
    raw: dict[str, object] | None = None,
    source_as_of: str = "2026-08-15T00:00:00+00:00",
):
    raw_path = root / selector
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_payload = _canonical(
        raw if raw is not None else _user_approved_trading_halt_raw()
    )
    raw_path.write_bytes(raw_payload)
    base = {
        "schema_version": "hk-no-trade-evidence-v1",
        "symbol": symbol,
        "trade_date": trade_date.isoformat(),
        "market": "HK",
        "reason": "NO_DAILY_TRADING_V1",
        "source": source,
        "source_record_id": source_record_id,
        "source_as_of": source_as_of,
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
    metadata_payload = _canonical(metadata)
    raw_path.with_suffix(".json").write_bytes(metadata_payload)
    base["raw_metadata_sha256"] = hashlib.sha256(metadata_payload).hexdigest()
    base["evidence_sha256"] = hashlib.sha256(_canonical(base)).hexdigest()
    evidence_set = {
        "schema_version": "hk-no-trade-evidence-set-v1",
        "evidences": [base],
        "evidence_set_sha256": hashlib.sha256(_canonical([base])).hexdigest(),
    }
    path = root / "user-approved-trading-halt-evidence.json"
    path.write_bytes(_canonical(evidence_set))
    return path, raw_path, base


def _evidence_item_identity(item: object) -> str:
    payload = {
        "market": item.market,  # type: ignore[attr-defined]
        "raw_file_sha256": item.raw_file_sha256,  # type: ignore[attr-defined]
        "raw_metadata_sha256": item.raw_metadata_sha256,  # type: ignore[attr-defined]
        "raw_selector": item.raw_selector,  # type: ignore[attr-defined]
        "reason": item.reason,  # type: ignore[attr-defined]
        "schema_version": item.schema_version,  # type: ignore[attr-defined]
        "source": item.source,  # type: ignore[attr-defined]
        "source_as_of": item.source_as_of,  # type: ignore[attr-defined]
        "source_record_id": item.source_record_id,  # type: ignore[attr-defined]
        "symbol": item.symbol,  # type: ignore[attr-defined]
        "trade_date": item.trade_date,  # type: ignore[attr-defined]
    }
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _raw(symbol_dates: dict[str, list[dt.date]]) -> pl.DataFrame:
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


def _seed(root: Path, expected: dict[str, list[dt.date]]) -> tuple[HKHistorySeed, dt.datetime]:
    fetched_at = dt.datetime(2026, 7, 18, 10, tzinfo=UTC)
    snapshot = RawStore(root).write(
        source="tushare",
        table="hk_daily_multi_symbol_probe",
        frame=_raw(expected),
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


def _plan(root: Path, *, request_symbols: tuple[str, ...] = ("00002.HK",)):
    date = dt.date(2026, 7, 10)
    seed, fetched_at = _seed(root, {"00001.HK": [date]})
    expected = {"00001.HK": [date], **{symbol: [date] for symbol in request_symbols}}
    return (
        build_hk_history_plan(
            expected_dates=expected,
            seed=seed,
            unresolved={},
            as_of=date,
            window_start=dt.date(2026, 4, 14),
        ),
        fetched_at,
    )


def _supplement_plan(root: Path):
    date = dt.date(2026, 7, 10)
    seed, fetched_at = _seed(root, {"00001.HK": [date]})
    evidence, _, _ = _evidence(root, symbol="01065.HK", trade_date=date)
    return (
        build_hk_history_plan_v2(
            expected_dates={
                "00001.HK": [date],
                "00002.HK": [date],
                "01065.HK": [date],
                "02983.HK": [date],
            },
            seed=seed,
            unresolved={"02983.HK": [date]},
            evidence=evidence,
            as_of=date,
            window_start=dt.date(2026, 4, 14),
        ),
        fetched_at,
    )


def _verified_hkex(raw: bytes, *, evidence_id: str = "e" * 64) -> SimpleNamespace:
    return SimpleNamespace(
        evidence_id=evidence_id,
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


def _install_hkex_verifier(
    monkeypatch: pytest.MonkeyPatch,
    retained_raw: bytes,
    *,
    evidence_id: str = "e" * 64,
) -> None:
    def verify(raw: bytes, *, source_url: str, expected_raw_sha256: str) -> SimpleNamespace:
        assert source_url == hk_history_backfill.HKEX_02983_SOURCE_URL
        assert expected_raw_sha256 == hk_history_backfill.HKEX_02983_RAW_SHA256
        if raw != retained_raw:
            raise hk_history_backfill.HKEXDailyQuotationsError(
                "HKEX_DAILY_QUOTATIONS_RAW_SHA256_MISMATCH"
            )
        return _verified_hkex(raw, evidence_id=evidence_id)

    monkeypatch.setattr(hk_history_backfill, "verify_hkex_daily_quotation", verify)


def _retained_hkex_bundle(
    monkeypatch: pytest.MonkeyPatch,
    raw: bytes,
    *,
    observed_at: dt.datetime,
):
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
        _canonical(base),
        source_url=hkex_daily_quotations.SOURCE_URL,
        expected_raw_sha256=hkex_daily_quotations.EXPECTED_RAW_SHA256,
    )


class FakeConnector:
    def __init__(self, frame: pl.DataFrame | BaseException) -> None:
        self.frame = frame
        self.calls: list[dict[str, object]] = []

    def fetch_hk_daily_batch_raw(self, **kwargs: object) -> pl.DataFrame:
        self.calls.append(kwargs)
        if isinstance(self.frame, BaseException):
            raise self.frame
        return self.frame


def test_finalize_v3_loader_reads_each_input_once_and_returns_exact_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "retained.raw"
    metadata = tmp_path / "retained.metadata.json"
    raw.write_bytes(b"raw-fixture")
    metadata.write_bytes(b"metadata-fixture")
    result = object()
    reads: list[str] = []
    original = hk_history_backfill._DirectoryAnchor.read_bytes

    def counted(anchor: object, relative: str | Path) -> bytes:
        reads.append(str(relative))
        return original(anchor, relative)  # type: ignore[arg-type]

    monkeypatch.setattr(hk_history_backfill._DirectoryAnchor, "read_bytes", counted)
    monkeypatch.setattr(
        hk_history_backfill,
        "verify_hkex_daily_quotation_retained",
        lambda raw_bytes, metadata_bytes, **kwargs: result
        if (
            raw_bytes == b"raw-fixture"
            and metadata_bytes == b"metadata-fixture"
            and kwargs["source_url"] == hk_history_backfill.HKEX_02983_SOURCE_URL
            and kwargs["expected_raw_sha256"]
            == hk_history_backfill.HKEX_02983_RAW_SHA256
        )
        else (_ for _ in ()).throw(AssertionError("wrong verification inputs")),
    )
    assert load_verified_hkex_retained_bundle_for_finalize(raw, metadata) is result
    assert reads == [raw.name, metadata.name]


def test_finalize_v3_loader_rejects_alias_symlink_and_path_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "raw"
    metadata = tmp_path / "metadata"
    raw.write_bytes(b"raw")
    metadata.write_bytes(b"metadata")
    monkeypatch.setattr(
        hk_history_backfill,
        "verify_hkex_daily_quotation_retained",
        lambda *_args, **_kwargs: object(),
    )
    alias = tmp_path / "alias"
    try:
        os.link(raw, alias)
    except OSError:
        pytest.skip("hardlink unavailable")
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"):
        load_verified_hkex_retained_bundle_for_finalize(raw, alias)

    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"replacement")

    def replace_after_verify(*_args: object, **_kwargs: object) -> object:
        raw.unlink()
        replacement.replace(raw)
        return object()

    monkeypatch.setattr(
        hk_history_backfill,
        "verify_hkex_daily_quotation_retained",
        replace_after_verify,
    )
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"):
        load_verified_hkex_retained_bundle_for_finalize(raw, metadata)


def test_finalize_v3_loader_rejects_symlink_or_reparse_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "raw"
    metadata = tmp_path / "metadata"
    alias = tmp_path / "metadata-alias"
    raw.write_bytes(b"raw")
    metadata.write_bytes(b"metadata")
    try:
        alias.symlink_to(metadata)
    except OSError:
        pytest.skip("symlink unavailable")
    monkeypatch.setattr(
        hk_history_backfill,
        "verify_hkex_daily_quotation_retained",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("verifier")),
    )
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"):
        load_verified_hkex_retained_bundle_for_finalize(raw, alias)


def test_finalize_v3_loader_sanitizes_hostile_exception_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "raw"
    metadata = tmp_path / "metadata"
    raw.write_bytes(b"raw")
    metadata.write_bytes(b"metadata")
    marker = "HOSTILE_RETAINED_TOKEN"

    def fail(*_args: object, **_kwargs: object) -> object:
        try:
            raise ValueError(marker)
        except ValueError as inner:
            raise RuntimeError(marker) from inner

    monkeypatch.setattr(hk_history_backfill, "verify_hkex_daily_quotation_retained", fail)
    with pytest.raises(HKHistoryBackfillError) as caught:
        load_verified_hkex_retained_bundle_for_finalize(raw, metadata)
    _assert_sanitized_exception(caught.value, marker)


def _rewrite_same_file(path: Path, payload: bytes) -> None:
    with path.open("r+b") as stream:
        stream.seek(0)
        stream.truncate()
        stream.write(payload)
        stream.flush()


@pytest.mark.parametrize("target_name", ["raw", "metadata"])
def test_finalize_v3_loader_rejects_observable_same_instance_content_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_name: str,
) -> None:
    raw = tmp_path / "raw"
    metadata = tmp_path / "metadata"
    original_raw = b"initial-raw-content"
    original_metadata = b"initial-metadata-content"
    raw.write_bytes(original_raw)
    metadata.write_bytes(original_metadata)
    target = raw if target_name == "raw" else metadata
    identity = (target.stat().st_dev, target.stat().st_ino)

    def drift(raw_bytes: bytes, metadata_bytes: bytes, **_kwargs: object) -> object:
        assert raw_bytes == original_raw
        assert metadata_bytes == original_metadata
        _rewrite_same_file(target, f"drift-{target_name}".encode())
        assert (target.stat().st_dev, target.stat().st_ino) == identity
        return object()

    monkeypatch.setattr(hk_history_backfill, "verify_hkex_daily_quotation_retained", drift)
    with pytest.raises(HKHistoryBackfillError) as caught:
        load_verified_hkex_retained_bundle_for_finalize(raw, metadata)
    assert str(caught.value) == "HK_HISTORY_REFERENCE_INVALID"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    _rewrite_same_file(
        target, original_raw if target_name == "raw" else original_metadata
    )


@pytest.mark.parametrize("target_name", ["raw", "metadata"])
def test_finalize_v3_loader_true_aba_preserves_every_semantic_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_name: str,
) -> None:
    raw = tmp_path / "raw"
    metadata = tmp_path / "metadata"
    original_raw = b"initial-raw-content"
    original_metadata = b"initial-metadata-content"
    raw.write_bytes(original_raw)
    metadata.write_bytes(original_metadata)
    target = raw if target_name == "raw" else metadata
    original_target = original_raw if target_name == "raw" else original_metadata
    identity = (target.stat().st_dev, target.stat().st_ino)
    inputs: list[tuple[bytes, bytes]] = []
    bundle = SimpleNamespace(
        retained_raw=original_raw,
        retained_metadata=original_metadata,
    )

    def aba(raw_bytes: bytes, metadata_bytes: bytes, **_kwargs: object) -> object:
        inputs.append((raw_bytes, metadata_bytes))
        _rewrite_same_file(target, f"transient-{target_name}".encode())
        _rewrite_same_file(target, original_target)
        assert (target.stat().st_dev, target.stat().st_ino) == identity
        return bundle

    monkeypatch.setattr(hk_history_backfill, "verify_hkex_daily_quotation_retained", aba)
    assert load_verified_hkex_retained_bundle_for_finalize(raw, metadata) is bundle
    assert inputs == [(original_raw, original_metadata)]
    assert bundle.retained_raw == raw.read_bytes() == original_raw
    assert bundle.retained_metadata == metadata.read_bytes() == original_metadata


def test_finalize_v3_loader_cross_file_interleave_is_outside_quiescence_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = tmp_path / "raw"
    metadata = tmp_path / "metadata"
    original_raw = b"initial-raw-content"
    changed_raw = b"writer-violated-quiescence"
    original_metadata = b"initial-metadata-content"
    raw.write_bytes(original_raw)
    metadata.write_bytes(original_metadata)
    inputs: list[tuple[bytes, bytes]] = []
    bundle = SimpleNamespace(
        retained_raw=original_raw,
        retained_metadata=original_metadata,
    )

    def verify(raw_bytes: bytes, metadata_bytes: bytes, **_kwargs: object) -> object:
        inputs.append((raw_bytes, metadata_bytes))
        return bundle

    original_reread = hk_history_backfill._reread_held_file_content
    rereads = 0

    def interleave_after_raw_final_observation(anchor: object) -> tuple[int, bytes]:
        nonlocal rereads
        content = original_reread(anchor)  # type: ignore[arg-type]
        rereads += 1
        if rereads == 2:
            # This writer deliberately violates the trusted quiescence premise:
            # raw was already finally observed while metadata is being observed.
            _rewrite_same_file(raw, changed_raw)
        return content

    monkeypatch.setattr(hk_history_backfill, "verify_hkex_daily_quotation_retained", verify)
    monkeypatch.setattr(
        hk_history_backfill,
        "_reread_held_file_content",
        interleave_after_raw_final_observation,
    )

    assert load_verified_hkex_retained_bundle_for_finalize(raw, metadata) is bundle
    assert inputs == [(original_raw, original_metadata)]
    assert bundle.retained_raw == original_raw
    assert bundle.retained_metadata == original_metadata
    assert raw.read_bytes() == changed_raw
    assert metadata.read_bytes() == original_metadata


@pytest.mark.parametrize(
    ("helper_name", "failure_type"),
    [
        ("_held_file_current_offset", ValueError),
        ("_held_file_seek_start", RuntimeError),
        ("_held_file_read_all", ValueError),
        ("_held_file_restore_offset", RuntimeError),
    ],
)
def test_finalize_v3_loader_sanitizes_held_reread_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    helper_name: str,
    failure_type: type[Exception],
) -> None:
    raw = tmp_path / "raw"
    metadata = tmp_path / "metadata"
    raw.write_bytes(b"raw")
    metadata.write_bytes(b"metadata")
    marker = f"HOSTILE_{helper_name}_TOKEN"
    monkeypatch.setattr(
        hk_history_backfill,
        "verify_hkex_daily_quotation_retained",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        hk_history_backfill,
        helper_name,
        lambda *_args: (_ for _ in ()).throw(failure_type(marker)),
    )
    with pytest.raises(HKHistoryBackfillError) as caught:
        load_verified_hkex_retained_bundle_for_finalize(raw, metadata)
    _assert_sanitized_exception(caught.value, marker)


def test_finalize_v3_loader_reread_restores_offset_and_open_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "raw"
    metadata = tmp_path / "metadata"
    raw.write_bytes(b"raw-offset-proof")
    metadata.write_bytes(b"metadata-offset-proof")
    result = object()
    observed: list[tuple[int, int]] = []
    original_reread = hk_history_backfill._reread_held_file_content

    def inspect(anchor: object) -> tuple[int, bytes]:
        descriptor = hk_history_backfill._last_held_file_descriptor(anchor)  # type: ignore[arg-type]
        before = hk_history_backfill._held_file_current_offset(anchor)  # type: ignore[arg-type]
        if os.name == "nt":
            duplicate = anchor._held_handles[-1][1]  # type: ignore[attr-defined]
            assert hk_history_backfill._win_same_object_handle(descriptor, duplicate)
        else:
            duplicate = anchor._held_fds[-1][1]  # type: ignore[attr-defined]
            expected_flags = anchor._held_fds[-1][-1]  # type: ignore[attr-defined]
            hk_history_backfill._posix_assert_same_open_instance(
                descriptor, duplicate, expected_flags
            )
        content = original_reread(anchor)  # type: ignore[arg-type]
        after = hk_history_backfill._held_file_current_offset(anchor)  # type: ignore[arg-type]
        observed.append((before, after))
        return content

    monkeypatch.setattr(hk_history_backfill, "_reread_held_file_content", inspect)
    monkeypatch.setattr(
        hk_history_backfill,
        "verify_hkex_daily_quotation_retained",
        lambda *_args, **_kwargs: result,
    )
    assert load_verified_hkex_retained_bundle_for_finalize(raw, metadata) is result
    assert observed == [(len(b"raw-offset-proof"), len(b"raw-offset-proof")),
                        (len(b"metadata-offset-proof"), len(b"metadata-offset-proof"))]


def test_plan_is_stable_and_batches_at_eighty(tmp_path: Path) -> None:
    symbols = tuple(f"{number:05d}.HK" for number in range(2, 163))
    plan, _ = _plan(tmp_path / "raw", request_symbols=symbols)
    assert [len(request.symbols) for request in plan.requests] == [80, 80, 1]
    path = tmp_path / "plan.json"
    write_or_verify_plan(path, plan)
    assert load_hk_history_plan(path) == plan
    write_or_verify_plan(path, plan)


def test_plan_tracks_seed_unresolved_and_short_windows(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    seed, _ = _seed(raw_root, {"00005.HK": [dt.date(2026, 7, 9), dt.date(2026, 7, 10)]})
    plan = build_hk_history_plan(
        expected_dates={
            "00005.HK": [dt.date(2026, 7, 9), dt.date(2026, 7, 10)],
            "02983.HK": [dt.date(2026, 7, 10)],
            "00700.HK": [dt.date(2026, 7, 10)],
        },
        seed=seed,
        unresolved={"02983.HK": [dt.date(2026, 7, 10)]},
        as_of=dt.date(2026, 7, 10),
        window_start=dt.date(2026, 4, 14),
    )
    assert plan.requests[0].symbols == ("00700.HK",)
    assert dict(plan.unresolved)["02983.HK"] == ("2026-07-10",)


def test_v2_plan_binds_evidence_and_preserves_wire_identity(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    dates = [dt.date(2026, 7, 9), dt.date(2026, 7, 10)]
    seed, _ = _seed(raw_root, {"00001.HK": dates})
    evidence, _, _ = _evidence(
        raw_root, symbol="00002.HK", trade_date=dates[0]
    )
    expected = {"00001.HK": dates, "00002.HK": dates}
    v1 = build_hk_history_plan(
        expected_dates=expected,
        seed=seed,
        unresolved={},
        as_of=dates[-1],
        window_start=dt.date(2026, 4, 14),
    )
    v2 = build_hk_history_plan_v2(
        expected_dates=expected,
        seed=seed,
        unresolved={},
        evidence=evidence,
        as_of=dates[-1],
        window_start=dt.date(2026, 4, 14),
    )
    assert v2.requests[0].request_id == v1.requests[0].request_id
    assert dict(v2.requests[0].expected_dates)["00002.HK"] == (
        "2026-07-09",
        "2026-07-10",
    )
    assert dict(v2.requests[0].effective_expected_dates)["00002.HK"] == (
        "2026-07-10",
    )
    path = tmp_path / "v2.json"
    write_or_verify_plan(path, v2)
    assert load_hk_history_plan(path) == v2


def test_evidence_raw_or_identity_drift_fails_closed(tmp_path: Path) -> None:
    evidence, path, raw_path = _evidence(
        tmp_path / "evidence_raw",
        symbol="00002.HK",
        trade_date=dt.date(2026, 7, 9),
    )
    assert evidence.evidences[0].reason == "NO_DAILY_TRADING_V1"
    raw_path.write_bytes(b"drift")
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"):
        load_hk_no_trade_evidence(path, raw_root=tmp_path / "evidence_raw")


def test_v2_offline_recovery_writes_only_new_receipt_and_stops_at_absent(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    dates = [dt.date(2026, 7, 9), dt.date(2026, 7, 10)]
    seed, fetched_at = _seed(raw_root, {"00001.HK": dates})
    evidence, _, evidence_raw_path = _evidence(
        raw_root, symbol="00002.HK", trade_date=dates[0]
    )
    symbols = tuple(f"{number:05d}.HK" for number in range(2, 83))
    expected = {"00001.HK": dates, **{symbol: dates for symbol in symbols}}
    plan = build_hk_history_plan_v2(
        expected_dates=expected,
        seed=seed,
        unresolved={},
        evidence=evidence,
        as_of=dates[-1],
        window_start=dt.date(2026, 4, 14),
    )
    first = plan.requests[0]
    first_raw = {
        symbol: ([dates[-1]] if symbol == "00002.HK" else dates)
        for symbol in first.symbols
    }
    RawStore(raw_root).write_request(
        source="tushare",
        table=HK_HISTORY_RAW_TABLE,
        request_id=first.request_id,
        frame=_raw(first_raw),
        parameters=dict(first.parameters),
        fetched_at=fetched_at,
    )
    journal = tmp_path / "journal-v2"
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_INCOMPLETE$"):
        recover_existing_hk_history_requests(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
        )
    request_dir = journal / "requests" / first.request_id
    assert (request_dir / "receipt.json").exists()
    assert not (request_dir / "intent.json").exists()
    assert not (request_dir / "attempts").exists()
    assert not (request_dir / "failures").exists()
    assert not (journal / "finalize.json").exists()
    evidence_raw_path.write_bytes(b"evidence drift")
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"):
        recover_existing_hk_history_requests(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
        )


def test_v2_rejects_preexisting_unbound_journal(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    date = dt.date(2026, 7, 10)
    seed, _ = _seed(raw_root, {"00001.HK": [date]})
    evidence, _, _ = _evidence(raw_root, symbol="00002.HK", trade_date=date)
    plan = build_hk_history_plan_v2(
        expected_dates={"00001.HK": [date], "00002.HK": [date]},
        seed=seed,
        unresolved={},
        evidence=evidence,
        as_of=date,
        window_start=dt.date(2026, 4, 14),
    )
    journal = tmp_path / "old-journal"
    journal.mkdir()
    (journal / "legacy.json").write_text("{}", encoding="utf-8")
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_PLAN_CONFLICT$"):
        recover_existing_hk_history_requests(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
        )


def _v2_minimal_recover_parts(tmp_path: Path):
    raw_root = tmp_path / "raw"
    dates = [dt.date(2026, 7, 9), dt.date(2026, 7, 10)]
    seed, fetched_at = _seed(raw_root, {"00001.HK": dates})
    evidence, evidence_path, evidence_raw = _evidence(
        raw_root, symbol="00002.HK", trade_date=dates[0]
    )
    symbols = tuple(f"{number:05d}.HK" for number in range(2, 83))
    expected = {"00001.HK": dates, **{symbol: dates for symbol in symbols}}
    plan = build_hk_history_plan_v2(
        expected_dates=expected,
        seed=seed,
        unresolved={},
        evidence=evidence,
        as_of=dates[-1],
        window_start=dt.date(2026, 4, 14),
    )
    return plan, raw_root, fetched_at, evidence_path, evidence_raw


def _raise_hostile_graph(path: Path, marker: str = "HOSTILE_VENDOR_TOKEN") -> bytes:
    absolute = str(path.resolve())
    try:
        raise ValueError(marker)
    except ValueError as inner:
        raise RuntimeError(f"{marker} path={absolute}") from inner


def _first_request_complete_raw(
    plan: object, raw_root: Path, fetched_at: dt.datetime
) -> None:
    first = plan.requests[0]  # type: ignore[attr-defined]
    first_raw = {
        symbol: (
            [dt.date(2026, 7, 10)]
            if symbol == "00002.HK"
            else [dt.date(2026, 7, 9), dt.date(2026, 7, 10)]
        )
        for symbol in first.symbols
    }
    RawStore(raw_root).write_request(
        source="tushare",
        table=HK_HISTORY_RAW_TABLE,
        request_id=first.request_id,
        frame=_raw(first_raw),
        parameters=dict(first.parameters),
        fetched_at=fetched_at,
    )


def test_recover_sanitizes_hostile_anchored_read_exception_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, raw_root, _, _, _ = _v2_minimal_recover_parts(tmp_path)
    journal = tmp_path / "journal-v2"
    marker = "HOSTILE_VENDOR_TOKEN"
    absolute = str((raw_root / "hkex/daily/d260710e.html").resolve())

    def fail(path: Path, *, root: Path, anchor: object | None) -> bytes:
        del root, anchor
        return _raise_hostile_graph(path, marker)

    monkeypatch.setattr(hk_history_backfill, "_read_anchored_path", fail)
    with pytest.raises(HKHistoryBackfillError) as caught:
        recover_existing_hk_history_requests(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
        )
    assert str(caught.value) == "HK_HISTORY_REFERENCE_INVALID"
    _assert_sanitized_exception(caught.value, marker)
    _assert_sanitized_exception(caught.value, absolute)


@pytest.mark.parametrize(
    ("site", "expected_code"),
    [
        ("evidence", "HK_HISTORY_REFERENCE_INVALID"),
        ("seed", "HK_HISTORY_REFERENCE_INVALID"),
        ("binding", "HK_HISTORY_PLAN_CONFLICT"),
        ("receipt", "HK_HISTORY_RAW_INVALID"),
        ("raw", "HK_HISTORY_RAW_INVALID"),
    ],
)
def test_recover_hostile_sites_keep_error_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    site: str,
    expected_code: str,
) -> None:
    plan, raw_root, fetched_at, _, _ = _v2_minimal_recover_parts(tmp_path)
    journal = tmp_path / "journal-v2"
    marker = f"HOSTILE_{site.upper()}_TOKEN"
    absolute = str(tmp_path.resolve())
    original_read = hk_history_backfill._read_anchored_path

    def hostile_bytes(path: Path) -> bytes:
        return _raise_hostile_graph(path, marker)

    if site == "evidence":

        def fail_evidence(path: Path, *, root: Path, anchor: object | None) -> bytes:
            if "hkex" in path.as_posix():
                return hostile_bytes(path)
            return original_read(path, root=root, anchor=anchor)

        monkeypatch.setattr(hk_history_backfill, "_read_anchored_path", fail_evidence)
    elif site == "seed":

        def fail_seed(path: Path, *, root: Path, anchor: object | None) -> bytes:
            if path.suffix == ".parquet":
                return hostile_bytes(path)
            return original_read(path, root=root, anchor=anchor)

        monkeypatch.setattr(hk_history_backfill, "_read_anchored_path", fail_seed)
    elif site == "binding":

        def fail_bind_write(path: Path, value: dict, code: str) -> None:
            del path, value, code
            try:
                raise ValueError(marker)
            except ValueError as inner:
                raise RuntimeError(f"{marker} path={absolute}") from inner

        monkeypatch.setattr(hk_history_backfill, "_write_or_verify_json", fail_bind_write)
    elif site == "receipt":
        _first_request_complete_raw(plan, raw_root, fetched_at)
        with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_INCOMPLETE$"):
            recover_existing_hk_history_requests(
                plan=plan,
                raw_store=RawStore(raw_root),
                journal_root=journal,
                seed_raw_root=raw_root,
            )
        assert (
            journal / "requests" / plan.requests[0].request_id / "receipt.json"
        ).exists()

        def fail_receipt(path: Path, *, root: Path, anchor: object | None) -> bytes:
            if path.name == "receipt.json":
                return hostile_bytes(path)
            return original_read(path, root=root, anchor=anchor)

        monkeypatch.setattr(hk_history_backfill, "_read_anchored_path", fail_receipt)
    else:

        def fail_inspect(*_args: object, **_kwargs: object) -> str:
            try:
                raise ValueError(marker)
            except ValueError as inner:
                raise RuntimeError(f"{marker} path={absolute}") from inner

        monkeypatch.setattr(RawStore, "inspect_request_state", fail_inspect)

    with pytest.raises(HKHistoryBackfillError) as caught:
        recover_existing_hk_history_requests(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
        )
    assert str(caught.value) == expected_code
    _assert_sanitized_exception(caught.value, marker)
    _assert_sanitized_exception(caught.value, absolute)


@pytest.mark.parametrize("site", ["read", "json", "projection"])
def test_load_hk_no_trade_evidence_sanitizes_hostile_sites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, site: str
) -> None:
    _evidence_set, path, _ = _evidence(
        tmp_path / "evidence_raw",
        symbol="00002.HK",
        trade_date=dt.date(2026, 7, 9),
    )
    marker = f"HOSTILE_EVIDENCE_{site.upper()}_TOKEN"
    absolute = str(path.resolve())

    def hostile() -> None:
        try:
            raise ValueError(marker)
        except ValueError as inner:
            raise RuntimeError(f"{marker} path={absolute}") from inner

    if site == "read":
        original = Path.read_bytes

        def guarded(self: Path) -> bytes:
            if self == path:
                hostile()
            return original(self)

        monkeypatch.setattr(Path, "read_bytes", guarded)
    elif site == "json":
        monkeypatch.setattr(
            hk_history_backfill,
            "_strict_json",
            lambda _payload: hostile(),
        )
    else:
        monkeypatch.setattr(
            hk_history_backfill,
            "_verify_evidence_projection",
            lambda *_args, **_kwargs: hostile(),
        )
    with pytest.raises(HKHistoryBackfillError) as caught:
        load_hk_no_trade_evidence(path, raw_root=tmp_path / "evidence_raw")
    assert str(caught.value) == "HK_HISTORY_REFERENCE_INVALID"
    _assert_sanitized_exception(caught.value, marker)
    _assert_sanitized_exception(caught.value, absolute)


def test_user_approved_no_trade_evidence_is_exactly_scoped(tmp_path: Path) -> None:
    raw_root = tmp_path / "consensus"
    path, _, _ = _user_approved_evidence(raw_root)
    evidence = load_hk_no_trade_evidence(path, raw_root=raw_root)
    item = evidence.evidences[0]
    assert [(item.symbol, item.trade_date, item.source) for item in evidence.evidences] == [
        (
            "01065.HK",
            "2026-05-05",
            "USER_APPROVED_MULTI_SOURCE_CONSENSUS",
        )
    ]
    assert item.source_record_id == "UA-M1-001"
    assert item.raw_selector == (
        "user-approved-consensus/ua-m1-001-01065-2026-05-05.record"
    )
    assert item.evidence_sha256 == hashlib.sha256(
        _canonical(
            {
                "market": item.market,
                "raw_file_sha256": item.raw_file_sha256,
                "raw_metadata_sha256": item.raw_metadata_sha256,
                "raw_selector": item.raw_selector,
                "reason": item.reason,
                "schema_version": item.schema_version,
                "source": item.source,
                "source_as_of": item.source_as_of,
                "source_record_id": item.source_record_id,
                "symbol": item.symbol,
                "trade_date": item.trade_date,
            }
        )
    ).hexdigest()

    other_root = tmp_path / "other"
    other_path, _, _ = _user_approved_evidence(
        other_root, symbol="01066.HK", trade_date=dt.date(2026, 5, 5)
    )
    with pytest.raises(HKHistoryBackfillError, match="HK_HISTORY_REFERENCE_INVALID"):
        load_hk_no_trade_evidence(other_path, raw_root=other_root)

    seed, _ = _seed(raw_root, {"00001.HK": [dt.date(2026, 7, 10)]})
    plan = build_hk_history_plan_v2(
        expected_dates={
            "00001.HK": [dt.date(2026, 7, 10)],
            "01065.HK": [dt.date(2026, 5, 5), dt.date(2026, 7, 10)],
        },
        seed=seed,
        unresolved={},
        evidence=evidence,
        as_of=dt.date(2026, 7, 10),
        window_start=dt.date(2026, 4, 14),
    )
    assert dict(plan.effective_expected_dates)["01065.HK"] == ("2026-07-10",)
    assert dict(plan.expected_dates)["01065.HK"] == ("2026-05-05", "2026-07-10")


def test_ua_m1_004_shared_raw_subtracts_only_exact_thirteen_dates(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    path, raw_path, rows = _user_approved_suspension_range_evidence(raw_root)
    evidence = load_hk_no_trade_evidence(path, raw_root=raw_root)
    assert len(evidence.evidences) == 13
    assert {item.raw_file_sha256 for item in evidence.evidences} == {
        hashlib.sha256(raw_path.read_bytes()).hexdigest()
    }
    assert len({item.raw_metadata_sha256 for item in evidence.evidences}) == 1
    assert len({item.evidence_sha256 for item in evidence.evidences}) == 13
    assert [item.trade_date for item in evidence.evidences] == [
        item.isoformat() for item in _UA_M1_004_DATES
    ]
    assert {item.source_record_id for item in evidence.evidences} == {"UA-M1-004"}
    assert {item.raw_selector for item in evidence.evidences} == {_UA_M1_004_SELECTOR}
    assert rows[0]["evidence_sha256"] != rows[1]["evidence_sha256"]

    seed, _ = _seed(raw_root, {"00001.HK": [dt.date(2026, 7, 10)]})
    original_02402 = [
        *_UA_M1_004_DATES,
        dt.date(2026, 5, 4),
        dt.date(2026, 7, 10),
    ]
    plan = build_hk_history_plan_v2(
        expected_dates={
            "00001.HK": [dt.date(2026, 7, 10)],
            "02402.HK": original_02402,
        },
        seed=seed,
        unresolved={},
        evidence=evidence,
        as_of=dt.date(2026, 7, 10),
        window_start=dt.date(2026, 4, 14),
    )
    effective = dict(plan.effective_expected_dates)
    assert dict(plan.expected_dates)["02402.HK"] == tuple(
        item.isoformat() for item in original_02402
    )
    assert effective["02402.HK"] == ("2026-05-04", "2026-07-10")
    assert effective["00001.HK"] == ("2026-07-10",)


def test_ua_m1_004_rejects_scope_and_payload_drift(tmp_path: Path) -> None:
    raw_root = tmp_path / "ok"
    path, _, _ = _user_approved_suspension_range_evidence(raw_root)
    load_hk_no_trade_evidence(path, raw_root=raw_root)

    cases: list[tuple[str, object]] = [
        ("date-04-13", {"dates": (dt.date(2026, 4, 13), *_UA_M1_004_DATES[1:])}),
        ("date-05-04", {"dates": (*_UA_M1_004_DATES[:12], dt.date(2026, 5, 4))}),
        ("other-symbol", {"symbol": "02403.HK"}),
        ("other-record", {"source_record_id": "UA-M1-005"}),
        ("other-selector", {"selector": "user-approved-consensus/other.record"}),
        ("other-source", {"source": "TUSHARE_HK_DAILY"}),
        (
            "url-drift",
            {
                "raw": _user_approved_suspension_range_raw(
                    observations=[
                        {
                            "observation": (
                                "H_SHARES_SUSPENDED_FROM_2026-04-01T01:00:00+00:00"
                            ),
                            "source_kind": "HKEX_NEWS",
                            "url": _UA_M1_004_SUSPENSION_URL + "/drift",
                        },
                        {
                            "observation": (
                                "H_SHARES_RESUMED_FROM_2026-05-04T01:00:00+00:00"
                            ),
                            "source_kind": "HKEX_NEWS",
                            "url": _UA_M1_004_RESUMPTION_URL,
                        },
                        {
                            "observation": "RETAINED_ZERO_ROW",
                            "source_kind": "TUSHARE_HK_DAILY",
                        },
                    ]
                )
            },
        ),
        (
            "observation-drift",
            {
                "raw": _user_approved_suspension_range_raw(
                    extra={
                        "observations": [
                            {
                                "observation": "DRIFTED",
                                "source_kind": "HKEX_NEWS",
                                "url": _UA_M1_004_SUSPENSION_URL,
                            },
                            {
                                "observation": (
                                    "H_SHARES_RESUMED_FROM_2026-05-04T01:00:00+00:00"
                                ),
                                "source_kind": "HKEX_NEWS",
                                "url": _UA_M1_004_RESUMPTION_URL,
                            },
                            {
                                "observation": "RETAINED_ZERO_ROW",
                                "source_kind": "TUSHARE_HK_DAILY",
                            },
                        ]
                    }
                )
            },
        ),
        (
            "dates-added",
            {
                "raw": _user_approved_suspension_range_raw(
                    no_trade_dates=tuple(
                        item.isoformat() for item in (*_UA_M1_004_DATES, dt.date(2026, 5, 4))
                    )
                )
            },
        ),
        (
            "dates-removed",
            {
                "raw": _user_approved_suspension_range_raw(
                    no_trade_dates=tuple(
                        item.isoformat() for item in _UA_M1_004_DATES[:-1]
                    )
                )
            },
        ),
        (
            "dates-reordered",
            {
                "raw": _user_approved_suspension_range_raw(
                    no_trade_dates=tuple(
                        item.isoformat()
                        for item in (*_UA_M1_004_DATES[1:], _UA_M1_004_DATES[0])
                    )
                )
            },
        ),
    ]
    for name, kwargs in cases:
        case_root = tmp_path / name
        case_path, _, _ = _user_approved_suspension_range_evidence(
            case_root, **kwargs  # type: ignore[arg-type]
        )
        with pytest.raises(
            HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"
        ):
            load_hk_no_trade_evidence(case_path, raw_root=case_root)

    hash_root = tmp_path / "raw-hash"
    hash_path, hash_raw, _ = _user_approved_suspension_range_evidence(hash_root)
    hash_raw.write_bytes(hash_raw.read_bytes() + b"\n")
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"):
        load_hk_no_trade_evidence(hash_path, raw_root=hash_root)

    meta_root = tmp_path / "meta-hash"
    meta_path, meta_raw, _ = _user_approved_suspension_range_evidence(meta_root)
    meta_raw.with_suffix(".json").write_bytes(b'{"drift":true}')
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"):
        load_hk_no_trade_evidence(meta_path, raw_root=meta_root)


def test_ua_m1_004_count_drift_fails_loader_or_exact_projection(
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "missing"
    missing_dates = _UA_M1_004_DATES[:-1]
    missing_path, _, _ = _user_approved_suspension_range_evidence(
        missing_root, dates=missing_dates
    )
    missing = load_hk_no_trade_evidence(missing_path, raw_root=missing_root)
    seed, _ = _seed(missing_root, {"00001.HK": [dt.date(2026, 7, 10)]})
    plan = build_hk_history_plan_v2(
        expected_dates={
            "00001.HK": [dt.date(2026, 7, 10)],
            "02402.HK": [*_UA_M1_004_DATES, dt.date(2026, 7, 10)],
        },
        seed=seed,
        unresolved={},
        evidence=missing,
        as_of=dt.date(2026, 7, 10),
        window_start=dt.date(2026, 4, 14),
    )
    assert dict(plan.effective_expected_dates)["02402.HK"] == (
        _UA_M1_004_DATES[-1].isoformat(),
        "2026-07-10",
    )

    extra_root = tmp_path / "extra"
    extra_path, _, _ = _user_approved_suspension_range_evidence(
        extra_root, dates=(*_UA_M1_004_DATES, dt.date(2026, 5, 4))
    )
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"):
        load_hk_no_trade_evidence(extra_path, raw_root=extra_root)

    dup_root = tmp_path / "dup"
    dup_path, _, rows = _user_approved_suspension_range_evidence(dup_root)
    duplicated = [dict(rows[0]), *rows]
    duplicated[0]["evidence_sha256"] = "a" * 64
    payload = {
        "schema_version": "hk-no-trade-evidence-set-v1",
        "evidences": duplicated,
        "evidence_set_sha256": hashlib.sha256(_canonical(duplicated)).hexdigest(),
    }
    dup_path.write_bytes(_canonical(payload))
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"):
        load_hk_no_trade_evidence(dup_path, raw_root=dup_root)


def test_ua_m1_004_hostile_json_type_and_path_stay_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, raw_path, _ = _user_approved_suspension_range_evidence(tmp_path / "ok")
    marker = "HOSTILE_UA_M1_004_TOKEN"
    absolute = str(raw_path.resolve())

    def hostile() -> None:
        _raise_hostile_graph(raw_path, marker)

    monkeypatch.setattr(
        hk_history_backfill,
        "_strict_json",
        lambda _payload: hostile(),
    )
    with pytest.raises(HKHistoryBackfillError) as caught:
        load_hk_no_trade_evidence(path, raw_root=tmp_path / "ok")
    assert str(caught.value) == "HK_HISTORY_REFERENCE_INVALID"
    _assert_sanitized_exception(caught.value, marker)
    _assert_sanitized_exception(caught.value, absolute)

    type_root = tmp_path / "type"
    type_path, type_raw, type_rows = _user_approved_suspension_range_evidence(type_root)
    list_payload = b"[1,2,3]"
    type_raw.write_bytes(list_payload)
    metadata = json.loads(type_raw.with_suffix(".json").read_bytes())
    metadata["raw_file_sha256"] = hashlib.sha256(list_payload).hexdigest()
    metadata_payload = _canonical(metadata)
    type_raw.with_suffix(".json").write_bytes(metadata_payload)
    rebuilt = []
    for row in type_rows:
        item = dict(row)
        item["raw_file_sha256"] = metadata["raw_file_sha256"]
        item["raw_metadata_sha256"] = hashlib.sha256(metadata_payload).hexdigest()
        item.pop("evidence_sha256")
        item["evidence_sha256"] = hashlib.sha256(_canonical(item)).hexdigest()
        rebuilt.append(item)
    type_path.write_bytes(
        _canonical(
            {
                "schema_version": "hk-no-trade-evidence-set-v1",
                "evidences": rebuilt,
                "evidence_set_sha256": hashlib.sha256(_canonical(rebuilt)).hexdigest(),
            }
        )
    )
    with pytest.raises(HKHistoryBackfillError) as type_caught:
        load_hk_no_trade_evidence(type_path, raw_root=type_root)
    assert str(type_caught.value) == "HK_HISTORY_REFERENCE_INVALID"
    assert type_caught.value.__cause__ is None
    assert type_caught.value.__context__ is None
    assert "[" not in str(type_caught.value)


def test_ua_m1_005_canonical_loader_and_plan_subtract_only_halt_day(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "halt"
    path, raw_path, row = _user_approved_trading_halt_evidence(raw_root)
    evidence = load_hk_no_trade_evidence(path, raw_root=raw_root)
    item = evidence.evidences[0]
    assert len(evidence.evidences) == 1
    assert (item.symbol, item.trade_date, item.source_record_id) == (
        "06110.HK",
        "2026-06-25",
        "UA-M1-005",
    )
    assert item.raw_selector == _UA_M1_005_SELECTOR
    assert item.source == "USER_APPROVED_MULTI_SOURCE_CONSENSUS"
    assert item.reason == "NO_DAILY_TRADING_V1"
    assert item.raw_file_sha256 == hashlib.sha256(raw_path.read_bytes()).hexdigest()
    assert item.evidence_sha256 == _evidence_item_identity(item)
    assert item.evidence_sha256 == row["evidence_sha256"]
    assert json.loads(raw_path.read_bytes()) == _user_approved_trading_halt_raw()

    seed, fetched_at = _seed(raw_root, {"00001.HK": [dt.date(2026, 7, 10)]})
    original_06110 = [
        dt.date(2026, 6, 24),
        dt.date(2026, 6, 25),
        dt.date(2026, 6, 26),
    ]
    plan = build_hk_history_plan_v2(
        expected_dates={
            "00001.HK": [dt.date(2026, 7, 10)],
            "06110.HK": original_06110,
        },
        seed=seed,
        unresolved={},
        evidence=evidence,
        as_of=dt.date(2026, 7, 10),
        window_start=dt.date(2026, 4, 14),
    )
    assert dict(plan.expected_dates)["06110.HK"] == (
        "2026-06-24",
        "2026-06-25",
        "2026-06-26",
    )
    assert dict(plan.effective_expected_dates)["06110.HK"] == (
        "2026-06-24",
        "2026-06-26",
    )
    request = plan.requests[0]
    assert request.symbols == ("06110.HK",)
    assert dict(request.expected_dates)["06110.HK"] == (
        "2026-06-24",
        "2026-06-25",
        "2026-06-26",
    )
    assert dict(request.effective_expected_dates)["06110.HK"] == (
        "2026-06-24",
        "2026-06-26",
    )
    RawStore(raw_root).write_request(
        source="tushare",
        table=HK_HISTORY_RAW_TABLE,
        request_id=request.request_id,
        frame=_raw(
            {
                "06110.HK": [dt.date(2026, 6, 24), dt.date(2026, 6, 26)],
            }
        ),
        parameters=dict(request.parameters),
        fetched_at=fetched_at,
    )
    recovered = recover_existing_hk_history_requests(
        plan=plan,
        raw_store=RawStore(raw_root),
        journal_root=tmp_path / "journal-ua-m1-005",
        seed_raw_root=raw_root,
    )
    assert recovered.completed_requests == recovered.total_requests == 1
    assert recovered.is_complete is True
    assert recovered.network_requests == 0


def test_ua_m1_005_rejects_scope_payload_and_byte_drift(tmp_path: Path) -> None:
    raw_root = tmp_path / "ok"
    path, _, _ = _user_approved_trading_halt_evidence(raw_root)
    load_hk_no_trade_evidence(path, raw_root=raw_root)

    cases: list[tuple[str, object]] = [
        ("other-symbol", {"symbol": "06111.HK"}),
        ("date-06-24", {"trade_date": dt.date(2026, 6, 24)}),
        ("date-06-26", {"trade_date": dt.date(2026, 6, 26)}),
        ("other-selector", {"selector": "user-approved-consensus/other.record"}),
        ("other-approval", {"source_record_id": "UA-M1-001"}),
        (
            "observation-removed",
            {
                "raw": _user_approved_trading_halt_raw(
                    observations=[
                        dict(_UA_M1_005_OBSERVATIONS[0]),
                        dict(_UA_M1_005_OBSERVATIONS[1]),
                    ]
                )
            },
        ),
        (
            "observation-added",
            {
                "raw": _user_approved_trading_halt_raw(
                    observations=[
                        *[dict(item) for item in _UA_M1_005_OBSERVATIONS],
                        {
                            "observation": "EXTRA",
                            "source_kind": "HKEX_NEWS",
                            "url": _UA_M1_005_HKEX_URL,
                        },
                    ]
                )
            },
        ),
        (
            "observation-reordered",
            {
                "raw": _user_approved_trading_halt_raw(
                    observations=[
                        dict(_UA_M1_005_OBSERVATIONS[2]),
                        dict(_UA_M1_005_OBSERVATIONS[1]),
                        dict(_UA_M1_005_OBSERVATIONS[0]),
                    ]
                )
            },
        ),
        (
            "hkex-url-drift",
            {
                "raw": _user_approved_trading_halt_raw(
                    observations=[
                        {
                            **dict(_UA_M1_005_OBSERVATIONS[0]),
                            "url": _UA_M1_005_HKEX_URL + "/drift",
                        },
                        dict(_UA_M1_005_OBSERVATIONS[1]),
                        dict(_UA_M1_005_OBSERVATIONS[2]),
                    ]
                )
            },
        ),
        (
            "independent-url-drift",
            {
                "raw": _user_approved_trading_halt_raw(
                    observations=[
                        dict(_UA_M1_005_OBSERVATIONS[0]),
                        dict(_UA_M1_005_OBSERVATIONS[1]),
                        {
                            **dict(_UA_M1_005_OBSERVATIONS[2]),
                            "url": _UA_M1_005_INDEPENDENT_URL + "&drift=1",
                        },
                    ]
                )
            },
        ),
        (
            "tushare-zero-row-drift",
            {
                "raw": _user_approved_trading_halt_raw(
                    observations=[
                        dict(_UA_M1_005_OBSERVATIONS[0]),
                        {
                            "observation": "ZERO_ROWS_ON_TARGETED_RETRY",
                            "source_kind": "TUSHARE_HK_DAILY",
                        },
                        dict(_UA_M1_005_OBSERVATIONS[2]),
                    ]
                )
            },
        ),
        *(
            (
                f"impact-{field}",
                {
                    "raw": _user_approved_trading_halt_raw(
                        impact_assessment={**_UA_M1_005_IMPACT, field: True}
                    )
                },
            )
            for field in _UA_M1_005_IMPACT
        ),
        (
            "extra-field",
            {"raw": _user_approved_trading_halt_raw(extra={"note": "drift"})},
        ),
        (
            "schema-version-drift",
            {
                "raw": _user_approved_trading_halt_raw(
                    extra={
                        "schema_version": "hk-no-trade-user-approved-consensus-v1",
                    }
                )
            },
        ),
    ]
    for name, kwargs in cases:
        case_root = tmp_path / name
        case_path, _, _ = _user_approved_trading_halt_evidence(
            case_root, **kwargs  # type: ignore[arg-type]
        )
        with pytest.raises(
            HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"
        ) as caught:
            load_hk_no_trade_evidence(case_path, raw_root=case_root)
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None

    hash_root = tmp_path / "raw-hash"
    hash_path, hash_raw, _ = _user_approved_trading_halt_evidence(hash_root)
    hash_raw.write_bytes(hash_raw.read_bytes() + b"\n")
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"):
        load_hk_no_trade_evidence(hash_path, raw_root=hash_root)

    meta_root = tmp_path / "meta-hash"
    meta_path, meta_raw, _ = _user_approved_trading_halt_evidence(meta_root)
    meta_raw.with_suffix(".json").write_bytes(
        meta_raw.with_suffix(".json").read_bytes() + b" "
    )
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"):
        load_hk_no_trade_evidence(meta_path, raw_root=meta_root)


def test_ua_m1_005_does_not_drift_ua_m1_001_or_004_identity(tmp_path: Path) -> None:
    first_root = tmp_path / "001"
    first_path, _, _ = _user_approved_evidence(first_root)
    first = load_hk_no_trade_evidence(first_path, raw_root=first_root)
    first_identity = _evidence_item_identity(first.evidences[0])
    assert first.evidences[0].evidence_sha256 == first_identity

    range_root = tmp_path / "004"
    range_path, _, range_rows = _user_approved_suspension_range_evidence(range_root)
    ranged = load_hk_no_trade_evidence(range_path, raw_root=range_root)
    range_identities = tuple(_evidence_item_identity(item) for item in ranged.evidences)
    assert [item.evidence_sha256 for item in ranged.evidences] == list(range_identities)
    assert [row["evidence_sha256"] for row in range_rows] == list(range_identities)

    mix_root = tmp_path / "mix"
    mix_001_path, _, _ = _user_approved_evidence(mix_root)
    mix_004_path, _, _ = _user_approved_suspension_range_evidence(mix_root)
    mix_005_path, _, _ = _user_approved_trading_halt_evidence(mix_root)
    mixed_rows = [
        *json.loads(mix_001_path.read_bytes())["evidences"],
        *json.loads(mix_004_path.read_bytes())["evidences"],
        *json.loads(mix_005_path.read_bytes())["evidences"],
    ]
    mixed_path = mix_root / "mixed-evidence.json"
    mixed_path.write_bytes(
        _canonical(
            {
                "schema_version": "hk-no-trade-evidence-set-v1",
                "evidences": mixed_rows,
                "evidence_set_sha256": hashlib.sha256(
                    _canonical(mixed_rows)
                ).hexdigest(),
            }
        )
    )
    mixed = load_hk_no_trade_evidence(mixed_path, raw_root=mix_root)
    by_record = {item.source_record_id: item for item in mixed.evidences}
    assert _evidence_item_identity(by_record["UA-M1-001"]) == first_identity
    assert tuple(
        _evidence_item_identity(item)
        for item in mixed.evidences
        if item.source_record_id == "UA-M1-004"
    ) == range_identities
    halt = by_record["UA-M1-005"]
    assert (halt.symbol, halt.trade_date) == ("06110.HK", "2026-06-25")


def test_ua_m1_005_hostile_json_stays_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, raw_path, _ = _user_approved_trading_halt_evidence(tmp_path / "ok")
    marker = "HOSTILE_UA_M1_005_TOKEN"
    absolute = str(raw_path.resolve())

    def hostile() -> None:
        _raise_hostile_graph(raw_path, marker)

    monkeypatch.setattr(
        hk_history_backfill,
        "_strict_json",
        lambda _payload: hostile(),
    )
    with pytest.raises(HKHistoryBackfillError) as caught:
        load_hk_no_trade_evidence(path, raw_root=tmp_path / "ok")
    assert str(caught.value) == "HK_HISTORY_REFERENCE_INVALID"
    _assert_sanitized_exception(caught.value, marker)
    _assert_sanitized_exception(caught.value, absolute)

    type_root = tmp_path / "type"
    type_path, type_raw, type_row = _user_approved_trading_halt_evidence(type_root)
    list_payload = b"[1,2,3]"
    type_raw.write_bytes(list_payload)
    metadata = json.loads(type_raw.with_suffix(".json").read_bytes())
    metadata["raw_file_sha256"] = hashlib.sha256(list_payload).hexdigest()
    metadata_payload = _canonical(metadata)
    type_raw.with_suffix(".json").write_bytes(metadata_payload)
    item = dict(type_row)
    item["raw_file_sha256"] = metadata["raw_file_sha256"]
    item["raw_metadata_sha256"] = hashlib.sha256(metadata_payload).hexdigest()
    item.pop("evidence_sha256")
    item["evidence_sha256"] = hashlib.sha256(_canonical(item)).hexdigest()
    type_path.write_bytes(
        _canonical(
            {
                "schema_version": "hk-no-trade-evidence-set-v1",
                "evidences": [item],
                "evidence_set_sha256": hashlib.sha256(_canonical([item])).hexdigest(),
            }
        )
    )
    with pytest.raises(HKHistoryBackfillError) as type_caught:
        load_hk_no_trade_evidence(type_path, raw_root=type_root)
    assert str(type_caught.value) == "HK_HISTORY_REFERENCE_INVALID"
    assert type_caught.value.__cause__ is None
    assert type_caught.value.__context__ is None
    assert "[" not in str(type_caught.value)


def test_ua_m1_005_identity_cannot_ride_hkex_source(tmp_path: Path) -> None:
    canonical_root = tmp_path / "canonical"
    canonical_path, _, canonical_row = _user_approved_trading_halt_evidence(
        canonical_root
    )
    canonical = load_hk_no_trade_evidence(canonical_path, raw_root=canonical_root)
    assert canonical.evidences[0].source == "USER_APPROVED_MULTI_SOURCE_CONSENSUS"
    assert canonical.evidences[0].source_record_id == "UA-M1-005"

    impersonation_cases: list[tuple[str, dict[str, object]]] = [
        (
            "hkex-canonical-raw",
            {"source": "HKEX_DAILY_QUOTATIONS"},
        ),
        (
            "hkex-garbage-raw",
            {"source": "HKEX_DAILY_QUOTATIONS", "raw": {"not": "halt"}},
        ),
        (
            "hkex-record-only",
            {
                "source": "HKEX_DAILY_QUOTATIONS",
                "selector": "hkex/daily/d260625e.html",
            },
        ),
        (
            "hkex-selector-only",
            {
                "source": "HKEX_DAILY_QUOTATIONS",
                "source_record_id": "synthetic-fixture-record",
            },
        ),
        ("record-drift", {"source_record_id": "UA-M1-001"}),
        (
            "selector-drift",
            {"selector": "user-approved-consensus/ua-m1-001-01065-2026-05-05.record"},
        ),
    ]
    for name, kwargs in impersonation_cases:
        case_root = tmp_path / name
        case_path, _, case_row = _user_approved_trading_halt_evidence(
            case_root, **kwargs  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError, match="no-trade evidence contract invalid"):
            HKNoTradeEvidence(**case_row)
        with pytest.raises(
            HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"
        ) as caught:
            load_hk_no_trade_evidence(case_path, raw_root=case_root)
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None

    ordinary, _, _ = _evidence(
        tmp_path / "ordinary-hkex",
        symbol="06110.HK",
        trade_date=dt.date(2026, 6, 25),
    )
    ordinary_item = ordinary.evidences[0]
    assert ordinary_item.source == "HKEX_DAILY_QUOTATIONS"
    assert ordinary_item.source_record_id == "synthetic-fixture-record"
    assert ordinary_item.raw_selector != _UA_M1_005_SELECTOR

    first_path, _, _ = _user_approved_evidence(tmp_path / "ua-m1-001")
    first = load_hk_no_trade_evidence(first_path, raw_root=tmp_path / "ua-m1-001")
    assert first.evidences[0].source_record_id == "UA-M1-001"
    range_path, _, _ = _user_approved_suspension_range_evidence(tmp_path / "ua-m1-004")
    ranged = load_hk_no_trade_evidence(range_path, raw_root=tmp_path / "ua-m1-004")
    assert {item.source_record_id for item in ranged.evidences} == {"UA-M1-004"}


def test_user_approved_identity_namespace_cannot_ride_hkex_source(
    tmp_path: Path,
) -> None:
    families: tuple[
        tuple[str, str, str, object],
        ...,
    ] = (
        (
            "001",
            "UA-M1-001",
            "hkex/daily/d260505e.html",
            lambda root, **kwargs: _user_approved_evidence(root, **kwargs),
        ),
        (
            "004",
            "UA-M1-004",
            "hkex/daily/d260414e.html",
            lambda root, **kwargs: _user_approved_suspension_range_evidence(
                root, dates=(dt.date(2026, 4, 14),), **kwargs
            ),
        ),
        (
            "005",
            "UA-M1-005",
            "hkex/daily/d260625e.html",
            lambda root, **kwargs: _user_approved_trading_halt_evidence(
                root, **kwargs
            ),
        ),
    )
    impersonations: tuple[tuple[str, dict[str, object]], ...] = (
        ("hkex-canonical-raw", {"source": "HKEX_DAILY_QUOTATIONS"}),
        (
            "hkex-garbage-raw",
            {"source": "HKEX_DAILY_QUOTATIONS", "raw": {"not": "halt"}},
        ),
        ("hkex-record-only", {"source": "HKEX_DAILY_QUOTATIONS"}),
        (
            "hkex-selector-only",
            {
                "source": "HKEX_DAILY_QUOTATIONS",
                "source_record_id": "synthetic-fixture-record",
            },
        ),
    )
    for label, record, hkex_selector, builder in families:
        canonical_root = tmp_path / f"{label}-canonical"
        canonical_path, _, _ = builder(canonical_root)
        canonical = load_hk_no_trade_evidence(
            canonical_path, raw_root=canonical_root
        )
        assert {item.source for item in canonical.evidences} == {
            "USER_APPROVED_MULTI_SOURCE_CONSENSUS"
        }
        assert {item.source_record_id for item in canonical.evidences} == {record}
        assert tuple(item.evidence_sha256 for item in canonical.evidences) == tuple(
            _evidence_item_identity(item) for item in canonical.evidences
        )

        for name, kwargs in impersonations:
            case_kwargs = dict(kwargs)
            if name == "hkex-record-only":
                case_kwargs["selector"] = hkex_selector
            case_root = tmp_path / f"{label}-{name}"
            case_path, _, case_third = builder(case_root, **case_kwargs)
            case_row = case_third[0] if isinstance(case_third, list) else case_third
            with pytest.raises(ValueError, match="no-trade evidence contract invalid"):
                HKNoTradeEvidence(**case_row)
            with pytest.raises(
                HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"
            ) as caught:
                load_hk_no_trade_evidence(case_path, raw_root=case_root)
            assert caught.value.__cause__ is None
            assert caught.value.__context__ is None

    for symbol, trade_date in (
        ("01065.HK", dt.date(2026, 5, 5)),
        ("02402.HK", dt.date(2026, 4, 14)),
        ("06110.HK", dt.date(2026, 6, 25)),
    ):
        ordinary, _, _ = _evidence(
            tmp_path / f"ordinary-hkex-{symbol}",
            symbol=symbol,
            trade_date=trade_date,
        )
        ordinary_item = ordinary.evidences[0]
        assert ordinary_item.source == "HKEX_DAILY_QUOTATIONS"
        assert ordinary_item.source_record_id == "synthetic-fixture-record"
        assert not ordinary_item.raw_selector.startswith("user-approved-consensus/")
        assert not ordinary_item.source_record_id.startswith("UA-M1-")


def test_load_hk_history_plan_sanitizes_hostile_read_exception_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _ = _plan(tmp_path / "raw")
    path = tmp_path / "plan.json"
    write_or_verify_plan(path, plan)
    assert load_hk_history_plan(path) == plan
    marker = "HOSTILE_PLAN_LOAD_TOKEN"
    absolute = str(path.resolve())
    original = Path.read_bytes

    def guarded(self: Path) -> bytes:
        if self == path:
            return _raise_hostile_graph(self, marker)
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    with pytest.raises(HKHistoryBackfillError) as caught:
        load_hk_history_plan(path)
    assert str(caught.value) == "HK_HISTORY_PLAN_CONFLICT"
    _assert_sanitized_exception(caught.value, marker)
    _assert_sanitized_exception(caught.value, absolute)


def test_build_hk_history_plan_v2_sanitizes_hostile_normalize_exception_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_root = tmp_path / "raw"
    dates = [dt.date(2026, 7, 9), dt.date(2026, 7, 10)]
    seed, _ = _seed(raw_root, {"00001.HK": dates})
    evidence, _, _ = _evidence(raw_root, symbol="00002.HK", trade_date=dates[0])
    expected = {"00001.HK": dates, "00002.HK": dates}
    control = build_hk_history_plan_v2(
        expected_dates=expected,
        seed=seed,
        unresolved={},
        evidence=evidence,
        as_of=dates[-1],
        window_start=dt.date(2026, 4, 14),
    )
    assert control.schema_version == "hk-history-plan-v2"
    marker = "HOSTILE_PLAN_BUILD_TOKEN"
    absolute = str((tmp_path / "normalize").resolve())

    def fail_normalize(expected_dates: object) -> object:
        del expected_dates
        return _raise_hostile_graph(tmp_path / "normalize", marker)

    monkeypatch.setattr(hk_history_backfill, "_normalize_expected_dates", fail_normalize)
    with pytest.raises(HKHistoryBackfillError) as caught:
        build_hk_history_plan_v2(
            expected_dates=expected,
            seed=seed,
            unresolved={},
            evidence=evidence,
            as_of=dates[-1],
            window_start=dt.date(2026, 4, 14),
        )
    assert str(caught.value) == "HK_HISTORY_REFERENCE_INVALID"
    _assert_sanitized_exception(caught.value, marker)
    _assert_sanitized_exception(caught.value, absolute)


def test_write_or_verify_plan_sanitizes_hostile_read_exception_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _ = _plan(tmp_path / "raw")
    path = tmp_path / "plan.json"
    write_or_verify_plan(path, plan)
    write_or_verify_plan(path, plan)
    assert load_hk_history_plan(path) == plan
    marker = "HOSTILE_PLAN_WRITE_TOKEN"
    absolute = str(path.resolve())
    original = Path.read_bytes

    def guarded(self: Path) -> bytes:
        if self == path:
            return _raise_hostile_graph(self, marker)
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    with pytest.raises(HKHistoryBackfillError) as caught:
        write_or_verify_plan(path, plan)
    assert str(caught.value) == "HK_HISTORY_PLAN_CONFLICT"
    _assert_sanitized_exception(caught.value, marker)
    _assert_sanitized_exception(caught.value, absolute)


def test_recover_absent_replay_keeps_incomplete_and_zero_network_clean(
    tmp_path: Path,
) -> None:
    plan, raw_root, fetched_at, _, _ = _v2_minimal_recover_parts(tmp_path)
    _first_request_complete_raw(plan, raw_root, fetched_at)
    journal = tmp_path / "journal-v2"
    clean = tmp_path / "clean"
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_INCOMPLETE$"):
        recover_existing_hk_history_requests(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
        )
    first = plan.requests[0]
    receipt = journal / "requests" / first.request_id / "receipt.json"
    binding = journal / "binding.json"
    receipt_bytes = receipt.read_bytes()
    binding_bytes = binding.read_bytes()
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_INCOMPLETE$") as caught:
        recover_existing_hk_history_requests(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
        )
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert receipt.read_bytes() == receipt_bytes
    assert binding.read_bytes() == binding_bytes
    assert not (journal / "requests" / first.request_id / "intent.json").exists()
    assert not (journal / "requests" / first.request_id / "attempts").exists()
    assert not clean.exists()
    assert not (tmp_path / "clean" / "bar_1d").exists()


def test_recover_rejects_bar_intersection_with_no_trade_evidence(
    tmp_path: Path,
) -> None:
    plan, raw_root, fetched_at, _, _ = _v2_minimal_recover_parts(tmp_path)
    first = plan.requests[0]
    first_raw = {
        symbol: [dt.date(2026, 7, 9), dt.date(2026, 7, 10)] for symbol in first.symbols
    }
    RawStore(raw_root).write_request(
        source="tushare",
        table=HK_HISTORY_RAW_TABLE,
        request_id=first.request_id,
        frame=_raw(first_raw),
        parameters=dict(first.parameters),
        fetched_at=fetched_at,
    )
    journal = tmp_path / "journal-v2"
    clean = tmp_path / "clean"
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_RAW_INVALID$"):
        recover_existing_hk_history_requests(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
        )
    assert not (journal / "requests" / first.request_id / "receipt.json").exists()
    assert not clean.exists()


def test_recover_rejects_01065_without_licensed_evidence_when_raw_missing_row(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    date = dt.date(2026, 7, 10)
    seed, fetched_at = _seed(raw_root, {"00001.HK": [date]})
    evidence, _, _ = _evidence(raw_root, symbol="00002.HK", trade_date=date)
    plan = build_hk_history_plan_v2(
        expected_dates={
            "00001.HK": [date],
            "00002.HK": [date],
            "01065.HK": [date],
        },
        seed=seed,
        unresolved={},
        evidence=evidence,
        as_of=date,
        window_start=dt.date(2026, 4, 14),
    )
    request = plan.requests[0]
    RawStore(raw_root).write_request(
        source="tushare",
        table=HK_HISTORY_RAW_TABLE,
        request_id=request.request_id,
        frame=_raw({"00002.HK": [date]}),
        parameters=dict(request.parameters),
        fetched_at=fetched_at,
    )
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_RAW_INVALID$"):
        recover_existing_hk_history_requests(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=tmp_path / "journal-v2",
            seed_raw_root=raw_root,
        )


def test_recover_rejects_rehashed_evidence_closure_without_mutating_binding(
    tmp_path: Path,
) -> None:
    plan, raw_root, fetched_at, _, _ = _v2_minimal_recover_parts(tmp_path)
    _first_request_complete_raw(plan, raw_root, fetched_at)
    journal = tmp_path / "journal-v2"
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_INCOMPLETE$"):
        recover_existing_hk_history_requests(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
        )
    binding_bytes = (journal / "binding.json").read_bytes()
    first = plan.requests[0]
    receipt_bytes = (
        journal / "requests" / first.request_id / "receipt.json"
    ).read_bytes()
    dates = [dt.date(2026, 7, 9), dt.date(2026, 7, 10)]
    alt_evidence, _, _ = _evidence(raw_root, symbol="00003.HK", trade_date=dates[0])
    alt_seed, _ = _seed(raw_root, {"00001.HK": dates})
    symbols = tuple(f"{number:05d}.HK" for number in range(2, 83))
    alt_plan = build_hk_history_plan_v2(
        expected_dates={"00001.HK": dates, **{symbol: dates for symbol in symbols}},
        seed=alt_seed,
        unresolved={},
        evidence=alt_evidence,
        as_of=dates[-1],
        window_start=dt.date(2026, 4, 14),
    )
    assert alt_plan.plan_sha256 != plan.plan_sha256
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_PLAN_CONFLICT$"):
        recover_existing_hk_history_requests(
            plan=alt_plan,
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
        )
    assert (journal / "binding.json").read_bytes() == binding_bytes
    assert (
        journal / "requests" / first.request_id / "receipt.json"
    ).read_bytes() == receipt_bytes


def test_recover_binding_hardlink_alias_and_same_bytes_inode_replay(
    tmp_path: Path,
) -> None:
    plan, raw_root, fetched_at, _, _ = _v2_minimal_recover_parts(tmp_path)
    _first_request_complete_raw(plan, raw_root, fetched_at)
    journal = tmp_path / "journal-v2"
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_INCOMPLETE$"):
        recover_existing_hk_history_requests(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
        )
    binding = journal / "binding.json"
    original = binding.read_bytes()
    alias = journal / "binding-alias.json"
    try:
        os.link(binding, alias)
    except OSError:
        pytest.skip("hardlink unavailable")
    assert alias.read_bytes() == original
    replacement = journal / "binding-replaced.json"
    replacement.write_bytes(original)
    binding.unlink()
    replacement.rename(binding)
    assert binding.read_bytes() == original
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_INCOMPLETE$"):
        recover_existing_hk_history_requests(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
        )
    assert binding.read_bytes() == original
    assert alias.read_bytes() == original


def test_recover_rejects_preplanted_attempts_dirty_journal(tmp_path: Path) -> None:
    plan, raw_root, fetched_at, _, _ = _v2_minimal_recover_parts(tmp_path)
    _first_request_complete_raw(plan, raw_root, fetched_at)
    journal = tmp_path / "journal-v2"
    dirty = journal / "requests" / plan.requests[0].request_id / "attempts"
    dirty.mkdir(parents=True)
    (dirty / "preplant.json").write_text("{}", encoding="utf-8")
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_PLAN_CONFLICT$"):
        recover_existing_hk_history_requests(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
        )


def test_success_writes_intent_raw_then_receipt_and_never_refetches(tmp_path: Path) -> None:
    raw_root, journal = tmp_path / "raw", tmp_path / "journal"
    plan, seed_time = _plan(raw_root)
    connector = FakeConnector(_raw({"00002.HK": [dt.date(2026, 7, 10)]}))
    result = execute_next_hk_history_request(
        plan=plan,
        connector=connector,  # type: ignore[arg-type]
        raw_store=RawStore(raw_root),
        journal_root=journal,
        seed_raw_root=raw_root,
        now=lambda: seed_time + dt.timedelta(seconds=3601),
    )
    request = plan.requests[0]
    assert result.network_requests == 1
    assert (journal / "requests" / request.request_id / "intent.json").exists()
    assert RawStore(raw_root).inspect_request_state(
        source="tushare", table=HK_HISTORY_RAW_TABLE, request_id=request.request_id
    ) == "COMPLETE"
    assert (journal / "requests" / request.request_id / "receipt.json").exists()
    again = FakeConnector(AssertionError("must not call"))
    result2 = execute_next_hk_history_request(
        plan=plan,
        connector=again,  # type: ignore[arg-type]
        raw_store=RawStore(raw_root),
        journal_root=journal,
        seed_raw_root=raw_root,
        now=lambda: seed_time + dt.timedelta(seconds=7202),
    )
    assert result2.network_requests == 0 and not again.calls


def test_invalid_response_is_retained_raw_without_pass_receipt(tmp_path: Path) -> None:
    raw_root, journal = tmp_path / "raw", tmp_path / "journal"
    plan, seed_time = _plan(raw_root)
    invalid = _raw({"00002.HK": [dt.date(2026, 7, 9)]})
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_RAW_INVALID$"):
        execute_next_hk_history_request(
            plan=plan,
            connector=FakeConnector(invalid),  # type: ignore[arg-type]
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
            now=lambda: seed_time + dt.timedelta(seconds=3601),
        )
    request = plan.requests[0]
    assert RawStore(raw_root).inspect_request_state(
        source="tushare", table=HK_HISTORY_RAW_TABLE, request_id=request.request_id
    ) == "COMPLETE"
    assert not (journal / "requests" / request.request_id / "receipt.json").exists()


def test_cooldown_precedes_api_and_api_error_is_sanitized(tmp_path: Path) -> None:
    raw_root, journal = tmp_path / "raw", tmp_path / "journal"
    plan, seed_time = _plan(raw_root)
    connector = FakeConnector(RuntimeError("token=secret vendor message"))
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_COOLDOWN_ACTIVE$"):
        execute_next_hk_history_request(
            plan=plan,
            connector=connector,  # type: ignore[arg-type]
            raw_store=RawStore(raw_root), journal_root=journal, seed_raw_root=raw_root,
            now=lambda: seed_time + dt.timedelta(seconds=3599),
        )
    assert not connector.calls
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_API_FAILED$") as failure:
        execute_next_hk_history_request(
            plan=plan,
            connector=connector,  # type: ignore[arg-type]
            raw_store=RawStore(raw_root), journal_root=journal, seed_raw_root=raw_root,
            now=lambda: seed_time + dt.timedelta(seconds=3601),
        )
    assert "secret" not in str(failure.value)
    request_dir = journal / "requests" / plan.requests[0].request_id
    assert (request_dir / "intent.json").exists()
    assert len(list((request_dir / "attempts").glob("*.json"))) == 1

    recovered = FakeConnector(_raw({"00002.HK": [dt.date(2026, 7, 10)]}))
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_ATTEMPT_UNCERTAIN$"):
        execute_next_hk_history_request(
            plan=plan,
            connector=recovered,  # type: ignore[arg-type]
            raw_store=RawStore(raw_root), journal_root=journal, seed_raw_root=raw_root,
            now=lambda: seed_time + dt.timedelta(seconds=7202),
        )
    assert not recovered.calls
    result = execute_next_hk_history_request(
        plan=plan,
        connector=recovered,  # type: ignore[arg-type]
        raw_store=RawStore(raw_root), journal_root=journal, seed_raw_root=raw_root,
        now=lambda: seed_time + dt.timedelta(seconds=7203),
        confirm_uncertain_retry=True,
    )
    assert result.network_requests == 1 and len(recovered.calls) == 1


def test_uncertain_state_is_bound_to_first_pending_request(tmp_path: Path) -> None:
    raw_root, journal = tmp_path / "raw", tmp_path / "journal"
    symbols = tuple(f"{number:05d}.HK" for number in range(2, 83))
    plan, seed_time = _plan(raw_root, request_symbols=symbols)
    assert len(plan.requests) == 2
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_API_FAILED$"):
        execute_next_hk_history_request(
            plan=plan,
            connector=FakeConnector(RuntimeError("network")),  # type: ignore[arg-type]
            raw_store=RawStore(raw_root), journal_root=journal, seed_raw_root=raw_root,
            now=lambda: seed_time + dt.timedelta(seconds=3601),
        )
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_ATTEMPT_UNCERTAIN$"):
        execute_next_hk_history_request(
            plan=plan,
            connector=FakeConnector(AssertionError("must not call")),  # type: ignore[arg-type]
            raw_store=RawStore(raw_root), journal_root=journal, seed_raw_root=raw_root,
            now=lambda: seed_time + dt.timedelta(seconds=7202),
        )


def test_seed_content_and_metadata_are_bound_into_plan(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    plan, _ = _plan(raw_root)
    metadata = raw_root / plan.seed.selector
    metadata = metadata.with_suffix(".json")
    payload = metadata.read_text(encoding="utf-8").replace('"rows": 1', '"rows": 2')
    metadata.write_text(payload, encoding="utf-8")
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"):
        execute_next_hk_history_request(
            plan=plan,
            connector=FakeConnector(AssertionError("must not call")),  # type: ignore[arg-type]
            raw_store=RawStore(raw_root), journal_root=tmp_path / "journal",
            seed_raw_root=raw_root,
        )


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink creation needs privileges")
def test_preexisting_journal_request_symlink_is_rejected(tmp_path: Path) -> None:
    raw_root, journal = tmp_path / "raw", tmp_path / "journal"
    plan, seed_time = _plan(raw_root)
    outside = tmp_path / "outside"
    outside.mkdir()
    request_link = journal / "requests" / plan.requests[0].request_id
    request_link.parent.mkdir(parents=True)
    request_link.symlink_to(outside, target_is_directory=True)
    connector = FakeConnector(AssertionError("must not call"))
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"):
        execute_next_hk_history_request(
            plan=plan,
            connector=connector,  # type: ignore[arg-type]
            raw_store=RawStore(raw_root), journal_root=journal, seed_raw_root=raw_root,
            now=lambda: seed_time + dt.timedelta(seconds=3601),
        )
    assert not connector.calls


@pytest.mark.parametrize("case", ["duplicate", "extra_symbol", "extra_column", "row_limit"])
def test_strict_raw_shape_failures_are_retained(
    tmp_path: Path, case: str
) -> None:
    raw_root, journal = tmp_path / "raw", tmp_path / "journal"
    plan, seed_time = _plan(raw_root)
    valid = _raw({"00002.HK": [dt.date(2026, 7, 10)]})
    if case == "duplicate":
        invalid = pl.concat([valid, valid])
    elif case == "extra_symbol":
        invalid = pl.concat([valid, _raw({"00003.HK": [dt.date(2026, 7, 10)]})])
    elif case == "extra_column":
        invalid = valid.with_columns(pl.lit("drift").alias("unexpected"))
    else:
        invalid = pl.concat([valid] * 5000)
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_RAW_INVALID$"):
        execute_next_hk_history_request(
            plan=plan,
            connector=FakeConnector(invalid),  # type: ignore[arg-type]
            raw_store=RawStore(raw_root), journal_root=journal, seed_raw_root=raw_root,
            now=lambda: seed_time + dt.timedelta(seconds=3601),
        )
    request = plan.requests[0]
    assert RawStore(raw_root).inspect_request_state(
        source="tushare", table=HK_HISTORY_RAW_TABLE, request_id=request.request_id
    ) == "COMPLETE"
    assert not (journal / "requests" / request.request_id / "receipt.json").exists()


def test_finalize_requires_all_receipts_without_touching_clean(tmp_path: Path) -> None:
    raw_root, clean = tmp_path / "raw", tmp_path / "clean"
    plan, _ = _plan(raw_root)
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_INCOMPLETE$"):
        finalize_hk_history(
            plan=plan, raw_store=RawStore(raw_root), journal_root=tmp_path / "journal",
            seed_raw_root=raw_root, clean_root=clean,
        )
    assert not clean.exists()


def test_finalize_publishes_and_is_idempotent_but_rejects_existing_conflict(
    tmp_path: Path,
) -> None:
    raw_root, journal, clean = tmp_path / "raw", tmp_path / "journal", tmp_path / "clean"
    plan, seed_time = _plan(raw_root)
    execute_next_hk_history_request(
        plan=plan,
        connector=FakeConnector(_raw({"00002.HK": [dt.date(2026, 7, 10)]})),  # type: ignore[arg-type]
        raw_store=RawStore(raw_root), journal_root=journal, seed_raw_root=raw_root,
        now=lambda: seed_time + dt.timedelta(seconds=3601),
    )
    assert finalize_hk_history(
        plan=plan, raw_store=RawStore(raw_root), journal_root=journal,
        seed_raw_root=raw_root, clean_root=clean,
    ) == 2
    assert finalize_hk_history(
        plan=plan, raw_store=RawStore(raw_root), journal_root=journal,
        seed_raw_root=raw_root, clean_root=clean,
    ) == 2
    target = clean / "date=2026-07-10" / "data.parquet"
    changed = pl.read_parquet(target).with_columns(
        pl.when(pl.col("symbol") == "00002.HK")
        .then(pl.lit(99.0))
        .otherwise(pl.col("close"))
        .alias("close")
    )
    changed.write_parquet(target)
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_PUBLISH_CONFLICT$"):
        finalize_hk_history(
            plan=plan, raw_store=RawStore(raw_root), journal_root=journal,
            seed_raw_root=raw_root, clean_root=clean,
        )


def test_finalize_merges_verified_hkex_supplement_and_binds_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_root, journal, clean = tmp_path / "raw", tmp_path / "journal", tmp_path / "clean"
    retained_raw = b"SYNTHETIC RETAINED HKEX DAILY QUOTATIONS"
    _install_hkex_verifier(monkeypatch, retained_raw)
    plan, seed_time = _supplement_plan(raw_root)
    execute_next_hk_history_request(
        plan=plan,
        connector=FakeConnector(_raw({"00002.HK": [dt.date(2026, 7, 10)]})),  # type: ignore[arg-type]
        raw_store=RawStore(raw_root),
        journal_root=journal,
        seed_raw_root=raw_root,
        now=lambda: seed_time + dt.timedelta(seconds=3601),
    )

    assert finalize_hk_history(
        plan=plan,
        raw_store=RawStore(raw_root),
        journal_root=journal,
        seed_raw_root=raw_root,
        clean_root=clean,
        hkex_retained_raw=retained_raw,
    ) == 3
    target = clean / "date=2026-07-10" / "data.parquet"
    frame = pl.read_parquet(target).sort("symbol")
    assert frame.get_column("symbol").to_list() == ["00001.HK", "00002.HK", "02983.HK"]
    supplement = frame.filter(pl.col("symbol") == "02983.HK").row(0, named=True)
    assert supplement["source"] == "hkex"
    assert supplement["volume"] == 2_640_331.0
    assert supplement["amount"] == pytest.approx(43_420_387.43)
    assert supplement["adj_factor"] == 1.0

    receipt_path = journal / "finalize.json"
    first_receipt = receipt_path.read_bytes()
    receipt = json.loads(first_receipt)
    assert receipt["schema_version"] == "hk-history-finalize-v2"
    assert receipt["hkex_supplement"] == {
        "evidence_id": "e" * 64,
        "raw_sha256": hashlib.sha256(retained_raw).hexdigest(),
        "source_record_id": "HKEX_DAILY_QUOTATIONS:2026-07-10:2983",
        "supplement_content_sha256": receipt["hkex_supplement"][
            "supplement_content_sha256"
        ],
    }
    assert finalize_hk_history(
        plan=plan,
        raw_store=RawStore(raw_root),
        journal_root=journal,
        seed_raw_root=raw_root,
        clean_root=clean,
        hkex_retained_raw=retained_raw,
    ) == 3
    assert receipt_path.read_bytes() == first_receipt


def test_finalize_hkex_supplement_preconditions_fail_before_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    retained_raw = b"SYNTHETIC RETAINED HKEX DAILY QUOTATIONS"
    _install_hkex_verifier(monkeypatch, retained_raw)

    exact_root = tmp_path / "exact-raw"
    exact_plan, _ = _supplement_plan(exact_root)
    exact_journal, exact_clean = tmp_path / "exact-journal", tmp_path / "exact-clean"
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_INCOMPLETE$"):
        finalize_hk_history(
            plan=exact_plan,
            raw_store=RawStore(exact_root),
            journal_root=exact_journal,
            seed_raw_root=exact_root,
            clean_root=exact_clean,
        )
    assert not exact_journal.exists()
    assert not exact_clean.exists()

    v1_root = tmp_path / "v1-raw"
    date = dt.date(2026, 7, 10)
    v1_seed, _ = _seed(v1_root, {"00001.HK": [date]})
    v1_plan = build_hk_history_plan(
        expected_dates={"00001.HK": [date], "02983.HK": [date]},
        seed=v1_seed,
        unresolved={"02983.HK": [date]},
        as_of=date,
        window_start=dt.date(2026, 4, 14),
    )
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_PLAN_CONFLICT$"):
        finalize_hk_history(
            plan=v1_plan,
            raw_store=RawStore(v1_root),
            journal_root=tmp_path / "v1-journal",
            seed_raw_root=v1_root,
            clean_root=tmp_path / "v1-clean",
            hkex_retained_raw=retained_raw,
        )
    assert not (tmp_path / "v1-journal").exists()
    assert not (tmp_path / "v1-clean").exists()

    ordinary_root = tmp_path / "ordinary-raw"
    ordinary_plan, _ = _plan(ordinary_root, request_symbols=())
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_PLAN_CONFLICT$"):
        finalize_hk_history(
            plan=ordinary_plan,
            raw_store=RawStore(ordinary_root),
            journal_root=tmp_path / "ordinary-journal",
            seed_raw_root=ordinary_root,
            clean_root=tmp_path / "ordinary-clean",
            hkex_retained_raw=retained_raw,
        )

    multi_root = tmp_path / "multi-raw"
    seed, _ = _seed(multi_root, {"00001.HK": [date]})
    multi_plan = build_hk_history_plan(
        expected_dates={
            "00001.HK": [date],
            "01065.HK": [date],
            "02983.HK": [date],
        },
        seed=seed,
        unresolved={"01065.HK": [date], "02983.HK": [date]},
        as_of=date,
        window_start=dt.date(2026, 4, 14),
    )
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_PLAN_CONFLICT$"):
        finalize_hk_history(
            plan=multi_plan,
            raw_store=RawStore(multi_root),
            journal_root=tmp_path / "multi-journal",
            seed_raw_root=multi_root,
            clean_root=tmp_path / "multi-clean",
            hkex_retained_raw=retained_raw,
        )
    assert not (tmp_path / "multi-journal").exists()
    assert not (tmp_path / "multi-clean").exists()


def test_finalize_rejects_unverified_or_drifted_hkex_supplement_before_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_root = tmp_path / "raw"
    plan, _ = _supplement_plan(raw_root)
    retained_raw = b"SYNTHETIC RETAINED HKEX DAILY QUOTATIONS"
    _install_hkex_verifier(monkeypatch, retained_raw)

    for invalid in (pl.DataFrame(), SimpleNamespace()):
        journal = tmp_path / f"journal-{type(invalid).__name__}"
        clean = tmp_path / f"clean-{type(invalid).__name__}"
        with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"):
            finalize_hk_history(
                plan=plan,
                raw_store=RawStore(raw_root),
                journal_root=journal,
                seed_raw_root=raw_root,
                clean_root=clean,
                hkex_retained_raw=invalid,  # type: ignore[arg-type]
            )
        assert not journal.exists()
        assert not clean.exists()

    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_REFERENCE_INVALID$"):
        finalize_hk_history(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=tmp_path / "drift-journal",
            seed_raw_root=raw_root,
            clean_root=tmp_path / "drift-clean",
            hkex_retained_raw=retained_raw + b"DRIFT",
        )
    assert not (tmp_path / "drift-journal").exists()
    assert not (tmp_path / "drift-clean").exists()


def test_finalize_rejects_hkex_evidence_identity_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_root, journal, clean = tmp_path / "raw", tmp_path / "journal", tmp_path / "clean"
    retained_raw = b"SYNTHETIC RETAINED HKEX DAILY QUOTATIONS"
    plan, seed_time = _supplement_plan(raw_root)
    execute_next_hk_history_request(
        plan=plan,
        connector=FakeConnector(_raw({"00002.HK": [dt.date(2026, 7, 10)]})),  # type: ignore[arg-type]
        raw_store=RawStore(raw_root),
        journal_root=journal,
        seed_raw_root=raw_root,
        now=lambda: seed_time + dt.timedelta(seconds=3601),
    )
    _install_hkex_verifier(monkeypatch, retained_raw)
    finalize_hk_history(
        plan=plan,
        raw_store=RawStore(raw_root),
        journal_root=journal,
        seed_raw_root=raw_root,
        clean_root=clean,
        hkex_retained_raw=retained_raw,
    )
    original_clean = (clean / "date=2026-07-10" / "data.parquet").read_bytes()

    _install_hkex_verifier(monkeypatch, retained_raw, evidence_id="d" * 64)
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_PUBLISH_FAILED$"):
        finalize_hk_history(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
            clean_root=clean,
            hkex_retained_raw=retained_raw,
        )
    assert (clean / "date=2026-07-10" / "data.parquet").read_bytes() == original_clean


def test_finalize_rejects_hkex_supplement_duplicate_key_before_clean_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_root, journal, clean = tmp_path / "raw", tmp_path / "journal", tmp_path / "clean"
    retained_raw = b"SYNTHETIC RETAINED HKEX DAILY QUOTATIONS"
    _install_hkex_verifier(monkeypatch, retained_raw)
    plan, seed_time = _supplement_plan(raw_root)
    execute_next_hk_history_request(
        plan=plan,
        connector=FakeConnector(_raw({"00002.HK": [dt.date(2026, 7, 10)]})),  # type: ignore[arg-type]
        raw_store=RawStore(raw_root),
        journal_root=journal,
        seed_raw_root=raw_root,
        now=lambda: seed_time + dt.timedelta(seconds=3601),
    )
    original_load_seed = hk_history_backfill._load_seed

    def load_seed_with_duplicate(
        plan_arg: object, raw_root_arg: Path
    ) -> tuple[pl.DataFrame, dt.datetime]:
        frame, fetched_at = original_load_seed(plan_arg, raw_root_arg)  # type: ignore[arg-type]
        duplicate = frame.head(1).with_columns(
            pl.lit("02983.HK").alias("symbol"),
            pl.lit(dt.date(2026, 7, 10)).alias("trade_date"),
        )
        return pl.concat([frame, duplicate]), fetched_at

    monkeypatch.setattr(hk_history_backfill, "_load_seed", load_seed_with_duplicate)
    with pytest.raises(HKHistoryBackfillError, match="^HK_HISTORY_RAW_INVALID$"):
        finalize_hk_history(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
            clean_root=clean,
            hkex_retained_raw=retained_raw,
        )
    assert not clean.exists()
    assert not (journal / "finalize.json").exists()


def _published_v3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[object, Path, Path, Path, object, dt.datetime]:
    raw_root, journal, clean = tmp_path / "raw", tmp_path / "journal", tmp_path / "clean"
    plan, seed_time = _supplement_plan(raw_root)
    execute_next_hk_history_request(
        plan=plan,
        connector=FakeConnector(_raw({"00002.HK": [dt.date(2026, 7, 10)]})),  # type: ignore[arg-type]
        raw_store=RawStore(raw_root),
        journal_root=journal,
        seed_raw_root=raw_root,
        now=lambda: seed_time + dt.timedelta(seconds=3601),
    )
    observed_at = dt.datetime(2026, 7, 18, 12, tzinfo=UTC)
    bundle = _retained_hkex_bundle(
        monkeypatch, b"SYNTHETIC RETAINED HKEX V3", observed_at=observed_at
    )
    assert finalize_hk_history(
        plan=plan,
        raw_store=RawStore(raw_root),
        journal_root=journal,
        seed_raw_root=raw_root,
        clean_root=clean,
        hkex_retained_bundle=bundle,
    ) == 3
    return plan, raw_root, journal, clean, bundle, observed_at


def test_finalize_v3_public_cli_exact_retry_partial_and_conflict_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: object,
) -> None:
    data_root = tmp_path / "data"
    raw_root = data_root / "raw"
    clean_root = data_root / "clean" / "bar_1d"
    journal = tmp_path / "journal"
    plan_path = tmp_path / "plan.json"
    plan, seed_time = _supplement_plan(raw_root)
    write_or_verify_plan(plan_path, plan)
    execute_next_hk_history_request(
        plan=plan,
        connector=FakeConnector(_raw({"00002.HK": [dt.date(2026, 7, 10)]})),  # type: ignore[arg-type]
        raw_store=RawStore(raw_root),
        journal_root=journal,
        seed_raw_root=raw_root,
        now=lambda: seed_time + dt.timedelta(seconds=3601),
    )
    bundle = _retained_hkex_bundle(
        monkeypatch,
        b"SYNTHETIC RETAINED HKEX V3 CLI",
        observed_at=dt.datetime(2026, 7, 18, 12, tzinfo=UTC),
    )
    monkeypatch.setattr(
        backfill_hk_history_cli,
        "load_verified_hkex_retained_bundle_for_finalize",
        lambda *_args: bundle,
    )
    monkeypatch.setattr(
        backfill_hk_history_cli.TushareConnector,
        "__init__",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("connector")),
    )
    argv = [
        "--plan",
        str(plan_path),
        "--data-root",
        str(data_root),
        "--journal-root",
        str(journal),
        "--finalize-v3",
        "--hkex-retained-raw",
        str(tmp_path / "retained.raw"),
        "--hkex-retained-metadata",
        str(tmp_path / "retained.metadata.json"),
    ]
    assert backfill_hk_history_cli.main(argv) == 0
    first = capsys.readouterr()  # type: ignore[attr-defined]
    assert '"finalize_schema_version":"hk-history-finalize-v3"' in first.out
    names = (
        "availability.json",
        "finalize.json",
        "hkex-retained.raw",
        "hkex-retained.metadata.json",
    )
    original = {name: (journal / name).read_bytes() for name in names}
    assert backfill_hk_history_cli.main(argv) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert {name: (journal / name).read_bytes() for name in names} == original

    (journal / "hkex-retained.metadata.json").unlink()
    assert backfill_hk_history_cli.main(argv) == 1
    partial = capsys.readouterr()  # type: ignore[attr-defined]
    assert partial.err.strip() == "HK_HISTORY_FINALIZE_V3_INVALID"
    assert not (journal / "hkex-retained.metadata.json").exists()
    (journal / "hkex-retained.metadata.json").write_bytes(
        original["hkex-retained.metadata.json"]
    )
    hostile = b"different-fixture-publication"
    (journal / "availability.json").write_bytes(hostile)
    assert backfill_hk_history_cli.main(argv) == 1
    conflict = capsys.readouterr()  # type: ignore[attr-defined]
    assert conflict.err.strip() == "HK_HISTORY_FINALIZE_V3_INVALID"
    assert (journal / "availability.json").read_bytes() == hostile
    assert clean_root.exists()


def test_finalize_v3_and_fresh_capability_bind_exact_availability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, raw_root, journal, clean, retained_bundle, observed_at = _published_v3(
        tmp_path, monkeypatch
    )
    as_of = observed_at + dt.timedelta(days=1)
    capability = load_verified_hk_bar_bundle(
        plan=plan,  # type: ignore[arg-type]
        journal_root=journal,
        seed_raw_root=raw_root,
        raw_store=RawStore(raw_root),
        clean_root=clean,
        as_of=as_of,
    )
    assert capability.bars.height == 3
    assert capability.availability.get_column("availability_source_kind").to_list() == [
        "SEED_RAW",
        "REQUEST_RAW",
        "HKEX_SUPPLEMENT",
    ]
    assert set(path.name for path in journal.iterdir()) >= {
        "availability.json",
        "finalize.json",
        "hkex-retained.raw",
        "hkex-retained.metadata.json",
    }
    assert json.loads((journal / "finalize.json").read_bytes())["schema_version"] == (
        "hk-history-finalize-v3"
    )
    first = {
        name: (journal / name).read_bytes()
        for name in (
            "availability.json",
            "finalize.json",
            "hkex-retained.raw",
            "hkex-retained.metadata.json",
        )
    }
    assert finalize_hk_history(
        plan=plan,  # type: ignore[arg-type]
        raw_store=RawStore(raw_root),
        journal_root=journal,
        seed_raw_root=raw_root,
        clean_root=clean,
        hkex_retained_bundle=retained_bundle,  # type: ignore[arg-type]
    ) == 3
    assert all((journal / name).read_bytes() == payload for name, payload in first.items())
    verify_hk_bar_bundle(
        capability,
        plan=plan,  # type: ignore[arg-type]
        journal_root=journal,
        seed_raw_root=raw_root,
        raw_store=RawStore(raw_root),
        clean_root=clean,
        as_of=as_of,
    )


def test_v3_minimal_chain_covers_three_days_no_trade_and_hkex_supplement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_root, journal, clean = tmp_path / "raw", tmp_path / "journal", tmp_path / "clean"
    dates = [dt.date(2026, 7, day) for day in (8, 9, 10)]
    seed, seed_time = _seed(raw_root, {"00001.HK": dates})
    evidence, _, _ = _evidence(
        raw_root, symbol="01065.HK", trade_date=dt.date(2026, 7, 10)
    )
    plan = build_hk_history_plan_v2(
        expected_dates={
            "00001.HK": dates,
            "00002.HK": dates,
            "01065.HK": [dates[-1]],
            "02983.HK": [dates[-1]],
        },
        seed=seed,
        unresolved={"02983.HK": [dates[-1]]},
        evidence=evidence,
        as_of=dates[-1],
        window_start=dt.date(2026, 4, 14),
    )
    execute_next_hk_history_request(
        plan=plan,
        connector=FakeConnector(_raw({"00002.HK": dates})),  # type: ignore[arg-type]
        raw_store=RawStore(raw_root),
        journal_root=journal,
        seed_raw_root=raw_root,
        now=lambda: seed_time + dt.timedelta(seconds=3601),
    )
    observed = dt.datetime(2026, 7, 18, 12, tzinfo=UTC)
    bundle = _retained_hkex_bundle(
        monkeypatch, b"SYNTHETIC RETAINED HKEX V3", observed_at=observed
    )
    assert finalize_hk_history(
        plan=plan,
        raw_store=RawStore(raw_root),
        journal_root=journal,
        seed_raw_root=raw_root,
        clean_root=clean,
        hkex_retained_bundle=bundle,
    ) == 7
    verified = load_verified_hk_bar_bundle(
        plan=plan,
        journal_root=journal,
        seed_raw_root=raw_root,
        raw_store=RawStore(raw_root),
        clean_root=clean,
        as_of=observed + dt.timedelta(days=1),
    )
    assert verified.bars.height == verified.availability.height == 7
    assert verified.availability.group_by("availability_source_kind").len().sort(
        "availability_source_kind"
    ).rows() == [
        ("HKEX_SUPPLEMENT", 1),
        ("REQUEST_RAW", 3),
        ("SEED_RAW", 3),
    ]
    assert "01065.HK" not in verified.bars.get_column("symbol").to_list()


def test_capability_rejects_legacy_future_and_fresh_source_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, raw_root, journal, clean, _bundle, observed_at = _published_v3(
        tmp_path, monkeypatch
    )
    with pytest.raises(HKHistoryBackfillError, match="^HK_BAR_PUBLICATION_INVALID$"):
        load_verified_hk_bar_bundle(
            plan=plan,  # type: ignore[arg-type]
            journal_root=journal,
            seed_raw_root=raw_root,
            raw_store=RawStore(raw_root),
            clean_root=clean,
            as_of=observed_at - dt.timedelta(seconds=1),
        )

    request = plan.requests[0]  # type: ignore[union-attr]
    _, metadata_path = RawStore(raw_root).request_paths(
        source="tushare", table=HK_HISTORY_RAW_TABLE, request_id=request.request_id
    )
    original = metadata_path.read_bytes()
    metadata = json.loads(original)
    metadata["fetched_at"] = "2026-07-19T00:00:00+00:00"
    metadata_path.write_bytes(_canonical(metadata))
    with pytest.raises(HKHistoryBackfillError, match="^HK_BAR_VERIFY_FAILED$"):
        load_verified_hk_bar_bundle(
            plan=plan,  # type: ignore[arg-type]
            journal_root=journal,
            seed_raw_root=raw_root,
            raw_store=RawStore(raw_root),
            clean_root=clean,
            as_of=observed_at + dt.timedelta(days=2),
        )
    metadata_path.write_bytes(original)

    legacy_root = tmp_path / "legacy-raw"
    legacy_plan, legacy_seed_time = _plan(legacy_root)
    legacy_journal, legacy_clean = tmp_path / "legacy-journal", tmp_path / "legacy-clean"
    execute_next_hk_history_request(
        plan=legacy_plan,
        connector=FakeConnector(_raw({"00002.HK": [dt.date(2026, 7, 10)]})),  # type: ignore[arg-type]
        raw_store=RawStore(legacy_root), journal_root=legacy_journal,
        seed_raw_root=legacy_root,
        now=lambda: legacy_seed_time + dt.timedelta(seconds=3601),
    )
    finalize_hk_history(
        plan=legacy_plan, raw_store=RawStore(legacy_root), journal_root=legacy_journal,
        seed_raw_root=legacy_root, clean_root=legacy_clean,
    )
    with pytest.raises(
        HKHistoryBackfillError, match="^HK_HISTORY_AVAILABILITY_UNSUPPORTED$"
    ):
        load_verified_hk_bar_bundle(
            plan=legacy_plan,
            journal_root=legacy_journal,
            seed_raw_root=legacy_root,
            raw_store=RawStore(legacy_root),
            clean_root=legacy_clean,
            as_of=observed_at + dt.timedelta(days=2),
        )


def test_v3_rejects_whole_rehashed_clean_and_fabricated_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, raw_root, journal, clean, _bundle, observed_at = _published_v3(
        tmp_path, monkeypatch
    )
    with pytest.raises(HKHistoryBackfillError, match="^HK_BAR_VERIFY_FAILED$"):
        verify_hk_bar_bundle(
            SimpleNamespace(),  # type: ignore[arg-type]
            plan=plan,  # type: ignore[arg-type]
            journal_root=journal,
            seed_raw_root=raw_root,
            raw_store=RawStore(raw_root),
            clean_root=clean,
            as_of=observed_at + dt.timedelta(days=1),
        )
    target = clean / "date=2026-07-10" / "data.parquet"
    changed = pl.read_parquet(target).with_columns(
        pl.when(pl.col("symbol") == "00001.HK")
        .then(pl.col("close") + 0.01)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    changed.write_parquet(target)
    finalize_path = journal / "finalize.json"
    receipt = json.loads(finalize_path.read_bytes())
    receipt["clean_content_sha256"] = hk_history_backfill._frame_hash(
        changed.sort("symbol", "trade_date", "source")
    )
    finalize_path.write_bytes(_canonical(receipt))
    with pytest.raises(HKHistoryBackfillError, match="^HK_BAR_VERIFY_FAILED$"):
        load_verified_hk_bar_bundle(
            plan=plan,  # type: ignore[arg-type]
            journal_root=journal,
            seed_raw_root=raw_root,
            raw_store=RawStore(raw_root),
            clean_root=clean,
            as_of=observed_at + dt.timedelta(days=1),
        )


def test_capability_binds_physical_roots_and_rejects_copy_or_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, raw_root, journal, clean, _bundle, observed_at = _published_v3(
        tmp_path, monkeypatch
    )
    as_of = observed_at + dt.timedelta(days=1)
    capability = load_verified_hk_bar_bundle(
        plan=plan,  # type: ignore[arg-type]
        journal_root=journal,
        seed_raw_root=raw_root,
        raw_store=RawStore(raw_root),
        clean_root=clean,
        as_of=as_of,
    )
    copied_journal = tmp_path / "journal-copy"
    shutil.copytree(journal, copied_journal)
    with pytest.raises(HKHistoryBackfillError, match="^HK_BAR_VERIFY_FAILED$"):
        verify_hk_bar_bundle(
            capability,
            plan=plan,  # type: ignore[arg-type]
            journal_root=copied_journal,
            seed_raw_root=raw_root,
            raw_store=RawStore(raw_root),
            clean_root=clean,
            as_of=as_of,
        )
    original_clean = tmp_path / "clean-original"
    clean.rename(original_clean)
    shutil.copytree(original_clean, clean)
    with pytest.raises(HKHistoryBackfillError, match="^HK_BAR_VERIFY_FAILED$"):
        verify_hk_bar_bundle(
            capability,
            plan=plan,  # type: ignore[arg-type]
            journal_root=journal,
            seed_raw_root=raw_root,
            raw_store=RawStore(raw_root),
            clean_root=clean,
            as_of=as_of,
        )


@pytest.mark.parametrize("boundary", ["load", "verify"])
@pytest.mark.parametrize("root_kind", ["journal", "seed", "raw", "clean"])
def test_public_boundary_closes_in_window_root_aba(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    root_kind: str,
) -> None:
    plan, raw_root, journal, clean, _bundle, observed_at = _published_v3(
        tmp_path, monkeypatch
    )
    as_of = observed_at + dt.timedelta(days=1)
    capability = load_verified_hk_bar_bundle(
        plan=plan,  # type: ignore[arg-type]
        journal_root=journal,
        seed_raw_root=raw_root,
        raw_store=RawStore(raw_root),
        clean_root=clean,
        as_of=as_of,
    )
    original = hk_history_backfill._DirectoryAnchor.read_bytes
    attempted = False
    blocked = False
    swapped = False
    target = journal if root_kind == "journal" else clean if root_kind == "clean" else raw_root
    park = tmp_path / f"{root_kind}-{boundary}-park"

    def matches(anchor: object, relative: str | Path) -> bool:
        path = anchor.path  # type: ignore[attr-defined]
        text = str(relative).replace("\\", "/")
        if root_kind == "journal":
            return path == journal.absolute()
        if root_kind == "clean":
            return path == clean.absolute()
        if path != raw_root.absolute():
            return False
        return ("request=" in text) == (root_kind == "raw")

    def aba(anchor: object, relative: str | Path) -> bytes:
        nonlocal attempted, blocked, swapped
        if not attempted and matches(anchor, relative):
            attempted = True
            try:
                target.rename(park)
                shutil.copytree(park, target)
                swapped = True
            except OSError:
                blocked = True
        return original(anchor, relative)  # type: ignore[arg-type]

    monkeypatch.setattr(hk_history_backfill._DirectoryAnchor, "read_bytes", aba)
    try:
        try:
            if boundary == "load":
                load_verified_hk_bar_bundle(
                    plan=plan,  # type: ignore[arg-type]
                    journal_root=journal,
                    seed_raw_root=raw_root,
                    raw_store=RawStore(raw_root),
                    clean_root=clean,
                    as_of=as_of,
                )
            else:
                verify_hk_bar_bundle(
                    capability,
                    plan=plan,  # type: ignore[arg-type]
                    journal_root=journal,
                    seed_raw_root=raw_root,
                    raw_store=RawStore(raw_root),
                    clean_root=clean,
                    as_of=as_of,
                )
            assert blocked
        except HKHistoryBackfillError as error:
            assert str(error) == "HK_BAR_VERIFY_FAILED"
            assert swapped
    finally:
        if swapped:
            shutil.rmtree(target)
            park.rename(target)
    assert attempted


@pytest.mark.parametrize("boundary", ["load", "verify"])
@pytest.mark.parametrize("hostile", ["parquet", "json", "hkex", "root"])
@pytest.mark.parametrize("exception_type", [ValueError, RuntimeError])
def test_public_bar_boundaries_remove_complete_hostile_exception_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    hostile: str,
    exception_type: type[Exception],
) -> None:
    plan, raw_root, journal, clean, _bundle, observed_at = _published_v3(
        tmp_path, monkeypatch
    )
    as_of = observed_at + dt.timedelta(days=1)
    capability = load_verified_hk_bar_bundle(
        plan=plan,  # type: ignore[arg-type]
        journal_root=journal,
        seed_raw_root=raw_root,
        raw_store=RawStore(raw_root),
        clean_root=clean,
        as_of=as_of,
    )
    marker = f"TOKEN_{hostile.upper()}_{exception_type.__name__}_HOSTILE_MARKER"

    def fail(*_args: object, **_kwargs: object) -> None:
        raise exception_type(marker)

    if hostile == "parquet":
        monkeypatch.setattr(hk_history_backfill.pl, "read_parquet", fail)
    elif hostile == "json":
        monkeypatch.setattr(hk_history_backfill, "_strict_json", fail)
    elif hostile == "hkex":
        monkeypatch.setattr(
            hk_history_backfill, "verify_hkex_daily_quotation_retained", fail
        )
    else:
        monkeypatch.setattr(hk_history_backfill._DirectoryAnchor, "read_bytes", fail)
    expected_code = (
        "HK_HISTORY_FINALIZE_V3_INVALID"
        if exception_type is ValueError and hostile in {"json", "root"}
        else "HK_BAR_VERIFY_FAILED"
    )
    with pytest.raises(
        HKHistoryBackfillError, match=f"^{expected_code}$"
    ) as caught:
        if boundary == "load":
            load_verified_hk_bar_bundle(
                plan=plan,  # type: ignore[arg-type]
                journal_root=journal,
                seed_raw_root=raw_root,
                raw_store=RawStore(raw_root),
                clean_root=clean,
                as_of=as_of,
            )
        else:
            verify_hk_bar_bundle(
                capability,
                plan=plan,  # type: ignore[arg-type]
                journal_root=journal,
                seed_raw_root=raw_root,
                raw_store=RawStore(raw_root),
                clean_root=clean,
                as_of=as_of,
            )
    _assert_sanitized_exception(caught.value, marker)


@pytest.mark.parametrize("boundary", ["load", "verify"])
@pytest.mark.parametrize("closed", ["journal", "seed", "raw", "clean", "all"])
def test_capability_signing_rejects_closed_original_root_anchors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    closed: str,
) -> None:
    plan, raw_root, journal, clean, _bundle, observed_at = _published_v3(
        tmp_path, monkeypatch
    )
    as_of = observed_at + dt.timedelta(days=1)
    capability = load_verified_hk_bar_bundle(
        plan=plan,  # type: ignore[arg-type]
        journal_root=journal,
        seed_raw_root=raw_root,
        raw_store=RawStore(raw_root),
        clean_root=clean,
        as_of=as_of,
    )
    captured: list[object] = []
    original_init = hk_history_backfill._ReadAnchors.__init__
    original_attestation = hk_history_backfill._capability_attestation

    def capture(anchor_set: object, **kwargs: Path) -> None:
        original_init(anchor_set, **kwargs)  # type: ignore[arg-type]
        captured.append(anchor_set)

    def close_before_signing(**kwargs: object) -> str:
        anchor_set = captured[-1]
        if closed == "all":
            anchor_set.close()  # type: ignore[attr-defined]
        else:
            getattr(anchor_set, closed).close()
        return original_attestation(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(hk_history_backfill._ReadAnchors, "__init__", capture)
    monkeypatch.setattr(
        hk_history_backfill, "_capability_attestation", close_before_signing
    )
    with pytest.raises(HKHistoryBackfillError, match="^HK_BAR_VERIFY_FAILED$"):
        if boundary == "load":
            load_verified_hk_bar_bundle(
                plan=plan,  # type: ignore[arg-type]
                journal_root=journal,
                seed_raw_root=raw_root,
                raw_store=RawStore(raw_root),
                clean_root=clean,
                as_of=as_of,
            )
        else:
            verify_hk_bar_bundle(
                capability,
                plan=plan,  # type: ignore[arg-type]
                journal_root=journal,
                seed_raw_root=raw_root,
                raw_store=RawStore(raw_root),
                clean_root=clean,
                as_of=as_of,
            )


@pytest.mark.parametrize("boundary", ["load", "verify"])
@pytest.mark.parametrize("closed_kind", ["descendant", "file"])
def test_signing_rejects_closed_descendant_or_file_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    closed_kind: str,
) -> None:
    plan, raw_root, journal, clean, _bundle, observed_at = _published_v3(
        tmp_path, monkeypatch
    )
    as_of = observed_at + dt.timedelta(days=1)
    capability = load_verified_hk_bar_bundle(
        plan=plan,  # type: ignore[arg-type]
        journal_root=journal,
        seed_raw_root=raw_root,
        raw_store=RawStore(raw_root),
        clean_root=clean,
        as_of=as_of,
    )
    captured: list[object] = []
    original_init = hk_history_backfill._ReadAnchors.__init__
    original_attestation = hk_history_backfill._capability_attestation

    def capture(anchor_set: object, **kwargs: Path) -> None:
        original_init(anchor_set, **kwargs)  # type: ignore[arg-type]
        captured.append(anchor_set)

    def invalidate_held(**kwargs: object) -> str:
        anchor_set = captured[-1]
        anchors = (
            anchor_set.journal,  # type: ignore[attr-defined]
            anchor_set.seed,  # type: ignore[attr-defined]
            anchor_set.raw,  # type: ignore[attr-defined]
            anchor_set.clean,  # type: ignore[attr-defined]
        )
        if os.name == "nt":
            expected_directory = closed_kind == "descendant"
            selected = next(
                handle
                for anchor in anchors
                for handle, _duplicate, attributes, _volume, _index in anchor._held_handles
                if bool(attributes & 0x00000010) == expected_directory
            )
            hk_history_backfill._win_close_handle(selected)
        else:
            expected_type = stat.S_IFDIR if closed_kind == "descendant" else stat.S_IFREG
            selected = next(
                fd
                for anchor in anchors
                for fd, _duplicate, _dev, _ino, file_type, _flags in anchor._held_fds
                if file_type == expected_type
            )
            os.close(selected)
        return original_attestation(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(hk_history_backfill._ReadAnchors, "__init__", capture)
    monkeypatch.setattr(hk_history_backfill, "_capability_attestation", invalidate_held)
    with pytest.raises(HKHistoryBackfillError, match="^HK_BAR_VERIFY_FAILED$"):
        if boundary == "load":
            load_verified_hk_bar_bundle(
                plan=plan,  # type: ignore[arg-type]
                journal_root=journal,
                seed_raw_root=raw_root,
                raw_store=RawStore(raw_root),
                clean_root=clean,
                as_of=as_of,
            )
        else:
            verify_hk_bar_bundle(
                capability,
                plan=plan,  # type: ignore[arg-type]
                journal_root=journal,
                seed_raw_root=raw_root,
                raw_store=RawStore(raw_root),
                clean_root=clean,
                as_of=as_of,
            )


def test_directory_anchor_close_is_terminal_and_idempotent(tmp_path: Path) -> None:
    anchor = hk_history_backfill._DirectoryAnchor(tmp_path)
    anchor.close()
    anchor.close()
    with pytest.raises(hk_history_backfill._AnchorViolation):
        anchor.assert_namespace()
    with pytest.raises(hk_history_backfill._AnchorViolation):
        anchor.read_bytes("missing")


@pytest.mark.parametrize("boundary", ["load", "verify"])
def test_external_root_descriptor_close_or_reuse_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    plan, raw_root, journal, clean, _bundle, observed_at = _published_v3(
        tmp_path, monkeypatch
    )
    as_of = observed_at + dt.timedelta(days=1)
    capability = load_verified_hk_bar_bundle(
        plan=plan,  # type: ignore[arg-type]
        journal_root=journal,
        seed_raw_root=raw_root,
        raw_store=RawStore(raw_root),
        clean_root=clean,
        as_of=as_of,
    )
    other = tmp_path / "descriptor-reuse"
    other.mkdir()
    captured: list[object] = []
    replacement: int | None = None
    stale: int | None = None
    original_init = hk_history_backfill._ReadAnchors.__init__
    original_attestation = hk_history_backfill._capability_attestation

    def capture(anchor_set: object, **kwargs: Path) -> None:
        original_init(anchor_set, **kwargs)  # type: ignore[arg-type]
        captured.append(anchor_set)

    def invalidate(**kwargs: object) -> str:
        nonlocal replacement, stale
        anchor = captured[-1].raw  # type: ignore[attr-defined]
        if os.name == "nt":
            stale = anchor._handle
            hk_history_backfill._win_close_handle(stale)
            replacement, _identity = hk_history_backfill._win_open_directory(other)
        else:
            stale = anchor._fd
            os.close(stale)
            replacement = os.open(
                other,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
        return original_attestation(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(hk_history_backfill._ReadAnchors, "__init__", capture)
    monkeypatch.setattr(hk_history_backfill, "_capability_attestation", invalidate)
    try:
        with pytest.raises(HKHistoryBackfillError, match="^HK_BAR_VERIFY_FAILED$"):
            if boundary == "load":
                load_verified_hk_bar_bundle(
                    plan=plan,  # type: ignore[arg-type]
                    journal_root=journal,
                    seed_raw_root=raw_root,
                    raw_store=RawStore(raw_root),
                    clean_root=clean,
                    as_of=as_of,
                )
            else:
                verify_hk_bar_bundle(
                    capability,
                    plan=plan,  # type: ignore[arg-type]
                    journal_root=journal,
                    seed_raw_root=raw_root,
                    raw_store=RawStore(raw_root),
                    clean_root=clean,
                    as_of=as_of,
                )
    finally:
        if replacement is not None and replacement != stale:
            if os.name == "nt":
                hk_history_backfill._win_close_handle(replacement)
            else:
                os.close(replacement)


def _r4_descriptor_record(
    anchor: object, layer: str
) -> tuple[int, int, Path, bool]:
    if layer == "root":
        if os.name == "nt":
            return anchor._handle, anchor._handle_duplicate, anchor.path, True  # type: ignore[attr-defined]
        return anchor._fd, anchor._fd_duplicate, anchor.path, True  # type: ignore[attr-defined]
    directory = layer == "descendant"
    if os.name == "nt":
        record = next(
            value
            for value in anchor._held_handles  # type: ignore[attr-defined]
            if bool(value[2] & 0x00000010) == directory
        )
        expected = record[2:]
        for candidate in anchor.path.rglob("*"):  # type: ignore[attr-defined]
            if candidate.is_dir() != directory:
                continue
            probe = hk_history_backfill._win_create_handle(
                candidate, directory=directory
            )
            try:
                if hk_history_backfill._win_file_information(probe) == expected:
                    return record[0], record[1], candidate, directory
            finally:
                hk_history_backfill._win_close_handle(probe)
    else:
        expected_type = stat.S_IFDIR if directory else stat.S_IFREG
        record = next(
            value
            for value in anchor._held_fds  # type: ignore[attr-defined]
            if value[4] == expected_type
        )
        expected = record[2:5]
        for candidate in anchor.path.rglob("*"):  # type: ignore[attr-defined]
            info = candidate.stat()
            if (
                info.st_dev,
                info.st_ino,
                stat.S_IFMT(info.st_mode),
            ) == expected:
                return record[0], record[1], candidate, directory
    raise AssertionError("retained anchor record path not found")


def _r4_reopen(path: Path, *, directory: bool) -> int:
    if os.name == "nt":
        return hk_history_backfill._win_create_handle(path, directory=directory)
    return os.open(
        path,
        os.O_RDONLY
        | (getattr(os, "O_DIRECTORY", 0) if directory else 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )


@pytest.mark.parametrize("boundary", ["load", "verify"])
@pytest.mark.parametrize("layer", ["root", "descendant", "file"])
def test_same_object_original_descriptor_reuse_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    layer: str,
) -> None:
    plan, raw_root, journal, clean, _bundle, observed_at = _published_v3(
        tmp_path, monkeypatch
    )
    as_of = observed_at + dt.timedelta(days=1)
    capability = load_verified_hk_bar_bundle(
        plan=plan,  # type: ignore[arg-type]
        journal_root=journal,
        seed_raw_root=raw_root,
        raw_store=RawStore(raw_root),
        clean_root=clean,
        as_of=as_of,
    )
    captured: list[object] = []
    original_init = hk_history_backfill._ReadAnchors.__init__
    original_attestation = hk_history_backfill._capability_attestation

    def capture(anchor_set: object, **kwargs: Path) -> None:
        original_init(anchor_set, **kwargs)  # type: ignore[arg-type]
        captured.append(anchor_set)

    def replace_original(**kwargs: object) -> str:
        anchor = captured[-1].raw  # type: ignore[attr-defined]
        stale, _private, path, directory = _r4_descriptor_record(anchor, layer)
        if os.name == "nt":
            expected_identity = hk_history_backfill._win_file_information(stale)
            hk_history_backfill._win_close_handle(stale)
        else:
            expected_stat = os.fstat(stale)
            os.close(stale)
        replacement = _r4_reopen(path, directory=directory)
        assert replacement == stale
        if os.name == "nt":
            assert (
                hk_history_backfill._win_file_information(replacement)
                == expected_identity
            )
        else:
            replacement_stat = os.fstat(replacement)
            assert (replacement_stat.st_dev, replacement_stat.st_ino) == (
                expected_stat.st_dev,
                expected_stat.st_ino,
            )
        return original_attestation(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(hk_history_backfill._ReadAnchors, "__init__", capture)
    monkeypatch.setattr(
        hk_history_backfill, "_capability_attestation", replace_original
    )
    with pytest.raises(HKHistoryBackfillError, match="^HK_BAR_VERIFY_FAILED$"):
        if boundary == "load":
            load_verified_hk_bar_bundle(
                plan=plan,  # type: ignore[arg-type]
                journal_root=journal,
                seed_raw_root=raw_root,
                raw_store=RawStore(raw_root),
                clean_root=clean,
                as_of=as_of,
            )
        else:
            verify_hk_bar_bundle(
                capability,
                plan=plan,  # type: ignore[arg-type]
                journal_root=journal,
                seed_raw_root=raw_root,
                raw_store=RawStore(raw_root),
                clean_root=clean,
                as_of=as_of,
            )


@pytest.mark.parametrize("boundary", ["load", "verify"])
@pytest.mark.parametrize("layer", ["root", "descendant", "file"])
@pytest.mark.parametrize("replacement_kind", ["same", "different"])
def test_private_duplicate_reuse_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    layer: str,
    replacement_kind: str,
) -> None:
    plan, raw_root, journal, clean, _bundle, observed_at = _published_v3(
        tmp_path, monkeypatch
    )
    as_of = observed_at + dt.timedelta(days=1)
    capability = load_verified_hk_bar_bundle(
        plan=plan,  # type: ignore[arg-type]
        journal_root=journal,
        seed_raw_root=raw_root,
        raw_store=RawStore(raw_root),
        clean_root=clean,
        as_of=as_of,
    )
    captured: list[object] = []
    original_init = hk_history_backfill._ReadAnchors.__init__
    original_attestation = hk_history_backfill._capability_attestation

    def capture(anchor_set: object, **kwargs: Path) -> None:
        original_init(anchor_set, **kwargs)  # type: ignore[arg-type]
        captured.append(anchor_set)

    def replace_duplicate(**kwargs: object) -> str:
        anchor = captured[-1].raw  # type: ignore[attr-defined]
        _original, private, path, directory = _r4_descriptor_record(anchor, layer)
        if replacement_kind == "different":
            path = tmp_path / f"different-{boundary}-{layer}"
            if directory:
                path.mkdir()
            else:
                path.write_bytes(b"different")
        if os.name == "nt":
            hk_history_backfill._win_close_handle(private)
        else:
            os.close(private)
        replacement = _r4_reopen(path, directory=directory)
        assert replacement == private
        return original_attestation(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(hk_history_backfill._ReadAnchors, "__init__", capture)
    monkeypatch.setattr(
        hk_history_backfill, "_capability_attestation", replace_duplicate
    )
    with pytest.raises(HKHistoryBackfillError, match="^HK_BAR_VERIFY_FAILED$"):
        if boundary == "load":
            load_verified_hk_bar_bundle(
                plan=plan,  # type: ignore[arg-type]
                journal_root=journal,
                seed_raw_root=raw_root,
                raw_store=RawStore(raw_root),
                clean_root=clean,
                as_of=as_of,
            )
        else:
            verify_hk_bar_bundle(
                capability,
                plan=plan,  # type: ignore[arg-type]
                journal_root=journal,
                seed_raw_root=raw_root,
                raw_store=RawStore(raw_root),
                clean_root=clean,
                as_of=as_of,
            )


def test_open_instance_probe_and_cleanup_are_exact(tmp_path: Path) -> None:
    payload = b"open-instance-offset-proof"
    target = tmp_path / "payload.bin"
    target.write_bytes(payload)
    anchor = hk_history_backfill._DirectoryAnchor(tmp_path)
    assert anchor.read_bytes(target.name) == payload
    original, private, _path, _directory = _r4_descriptor_record(anchor, "file")
    if os.name == "nt":
        assert hk_history_backfill._win_same_object_handle(original, private)
        hk_history_backfill._win_close_handle(original)
        replacement = _r4_reopen(target, directory=False)
        assert replacement == original
        assert not hk_history_backfill._win_same_object_handle(replacement, private)
    else:
        fcntl = __import__("fcntl")
        expected_flags = int(fcntl.fcntl(original, fcntl.F_GETFL))
        offsets = (os.lseek(original, 0, os.SEEK_CUR), os.lseek(private, 0, os.SEEK_CUR))
        hk_history_backfill._posix_assert_same_open_instance(
            original, private, expected_flags
        )
        assert (
            int(fcntl.fcntl(original, fcntl.F_GETFL)),
            int(fcntl.fcntl(private, fcntl.F_GETFL)),
        ) == (expected_flags, expected_flags)
        assert (
            os.lseek(original, 0, os.SEEK_CUR),
            os.lseek(private, 0, os.SEEK_CUR),
        ) == offsets
        os.close(original)
        replacement = _r4_reopen(target, directory=False)
        assert replacement == original
        replacement_flags = int(fcntl.fcntl(replacement, fcntl.F_GETFL))
        toggled_flags = replacement_flags ^ os.O_NONBLOCK
        fcntl.fcntl(replacement, fcntl.F_SETFL, toggled_flags)
        try:
            assert int(fcntl.fcntl(private, fcntl.F_GETFL)) == expected_flags
            assert (
                int(fcntl.fcntl(replacement, fcntl.F_GETFL)) & os.O_NONBLOCK
            ) == (toggled_flags & os.O_NONBLOCK)
        finally:
            fcntl.fcntl(replacement, fcntl.F_SETFL, replacement_flags)
        with pytest.raises(hk_history_backfill._AnchorViolation):
            hk_history_backfill._posix_assert_same_open_instance(
                replacement, private, expected_flags
            )
    anchor.close()
    if os.name == "nt":
        with pytest.raises(OSError):
            hk_history_backfill._win_file_information(private)
    else:
        with pytest.raises(OSError):
            os.fstat(private)


def test_normal_anchor_close_releases_every_original_and_duplicate(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    target = nested / "payload.bin"
    target.write_bytes(b"cleanup-proof")
    anchor = hk_history_backfill._DirectoryAnchor(tmp_path)
    assert anchor.read_bytes(Path("nested") / target.name) == b"cleanup-proof"
    if os.name == "nt":
        descriptors = [anchor._handle, anchor._handle_duplicate]
        descriptors.extend(
            descriptor
            for record in anchor._held_handles
            for descriptor in record[:2]
        )
    else:
        descriptors = [anchor._fd, anchor._fd_duplicate]
        descriptors.extend(
            descriptor for record in anchor._held_fds for descriptor in record[:2]
        )
    assert all(descriptor is not None for descriptor in descriptors)
    assert len(descriptors) == len(set(descriptors))
    anchor.close()
    for descriptor in descriptors:
        assert descriptor is not None
        if os.name == "nt":
            with pytest.raises(OSError):
                hk_history_backfill._win_file_information(descriptor)
        else:
            with pytest.raises(OSError):
                os.fstat(descriptor)


@pytest.mark.parametrize("boundary", ["load", "verify"])
def test_anchor_close_failure_cannot_release_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    plan, raw_root, journal, clean, _bundle, observed_at = _published_v3(
        tmp_path, monkeypatch
    )
    as_of = observed_at + dt.timedelta(days=1)
    capability = load_verified_hk_bar_bundle(
        plan=plan,  # type: ignore[arg-type]
        journal_root=journal,
        seed_raw_root=raw_root,
        raw_store=RawStore(raw_root),
        clean_root=clean,
        as_of=as_of,
    )
    original_close = hk_history_backfill._ReadAnchors.close

    def fail_after_close(anchor_set: object) -> None:
        original_close(anchor_set)  # type: ignore[arg-type]
        raise OSError("HOSTILE_CLOSE_MARKER")

    monkeypatch.setattr(hk_history_backfill._ReadAnchors, "close", fail_after_close)
    with pytest.raises(HKHistoryBackfillError, match="^HK_BAR_VERIFY_FAILED$") as captured:
        if boundary == "load":
            load_verified_hk_bar_bundle(
                plan=plan,  # type: ignore[arg-type]
                journal_root=journal,
                seed_raw_root=raw_root,
                raw_store=RawStore(raw_root),
                clean_root=clean,
                as_of=as_of,
            )
        else:
            verify_hk_bar_bundle(
                capability,
                plan=plan,  # type: ignore[arg-type]
                journal_root=journal,
                seed_raw_root=raw_root,
                raw_store=RawStore(raw_root),
                clean_root=clean,
                as_of=as_of,
            )
    assert captured.value.__cause__ is None
    assert "HOSTILE_CLOSE_MARKER" not in str(captured.value)


def test_v3_finalize_file_set_rolls_back_on_interrupted_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_root, journal, clean = tmp_path / "raw", tmp_path / "journal", tmp_path / "clean"
    plan, seed_time = _supplement_plan(raw_root)
    execute_next_hk_history_request(
        plan=plan,
        connector=FakeConnector(_raw({"00002.HK": [dt.date(2026, 7, 10)]})),  # type: ignore[arg-type]
        raw_store=RawStore(raw_root), journal_root=journal, seed_raw_root=raw_root,
        now=lambda: seed_time + dt.timedelta(seconds=3601),
    )
    bundle = _retained_hkex_bundle(
        monkeypatch,
        b"SYNTHETIC RETAINED HKEX V3",
        observed_at=dt.datetime(2026, 7, 18, 12, tzinfo=UTC),
    )
    original = hk_history_backfill._write_v3_one
    calls = 0

    def interrupted(path: Path, payload: bytes) -> bool:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("HOSTILE_PATH_MARKER")
        return original(path, payload)

    monkeypatch.setattr(hk_history_backfill, "_write_v3_one", interrupted)
    with pytest.raises(
        HKHistoryBackfillError, match="^HK_HISTORY_FINALIZE_V3_INVALID$"
    ) as captured:
        finalize_hk_history(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
            clean_root=clean,
            hkex_retained_bundle=bundle,
        )
    assert captured.value.__cause__ is None
    assert "HOSTILE" not in str(captured.value)
    assert not any(
        (journal / name).exists()
        for name in (
            "availability.json",
            "finalize.json",
            "hkex-retained.raw",
            "hkex-retained.metadata.json",
        )
    )


def test_v3_rejects_cross_source_duplicate_before_clean_or_receipt_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_root, journal, clean = tmp_path / "raw", tmp_path / "journal", tmp_path / "clean"
    plan, seed_time = _supplement_plan(raw_root)
    execute_next_hk_history_request(
        plan=plan,
        connector=FakeConnector(_raw({"00002.HK": [dt.date(2026, 7, 10)]})),  # type: ignore[arg-type]
        raw_store=RawStore(raw_root), journal_root=journal, seed_raw_root=raw_root,
        now=lambda: seed_time + dt.timedelta(seconds=3601),
    )
    bundle = _retained_hkex_bundle(
        monkeypatch,
        b"SYNTHETIC RETAINED HKEX V3",
        observed_at=dt.datetime(2026, 7, 18, 12, tzinfo=UTC),
    )
    original_load_seed = hk_history_backfill._load_seed

    def duplicate_source(
        plan_arg: object, raw_root_arg: Path
    ) -> tuple[pl.DataFrame, dt.datetime]:
        frame, fetched_at = original_load_seed(plan_arg, raw_root_arg)  # type: ignore[arg-type]
        duplicate = frame.head(1).with_columns(
            pl.lit("02983.HK").alias("symbol"),
            pl.lit(dt.date(2026, 7, 10)).alias("trade_date"),
        )
        return pl.concat([frame, duplicate]), fetched_at

    monkeypatch.setattr(hk_history_backfill, "_load_seed", duplicate_source)
    with pytest.raises(
        HKHistoryBackfillError, match="^HK_HISTORY_AVAILABILITY_INVALID$"
    ):
        finalize_hk_history(
            plan=plan,
            raw_store=RawStore(raw_root),
            journal_root=journal,
            seed_raw_root=raw_root,
            clean_root=clean,
            hkex_retained_bundle=bundle,
        )
    assert not clean.exists()
    assert not (journal / "availability.json").exists()
    assert not (journal / "finalize.json").exists()
