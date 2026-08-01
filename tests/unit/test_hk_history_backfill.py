from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path

import polars as pl
import pytest

from quant.data.hk_history_backfill import (
    HK_DAILY_FIELDS,
    HK_HISTORY_RAW_TABLE,
    HKHistoryBackfillError,
    HKHistorySeed,
    build_hk_history_plan_v2,
    build_hk_history_plan,
    execute_next_hk_history_request,
    finalize_hk_history,
    load_hk_history_plan,
    load_hk_no_trade_evidence,
    recover_existing_hk_history_requests,
    write_or_verify_plan,
)
from quant.data.storage import RawStore

UTC = dt.timezone.utc


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


class FakeConnector:
    def __init__(self, frame: pl.DataFrame | BaseException) -> None:
        self.frame = frame
        self.calls: list[dict[str, object]] = []

    def fetch_hk_daily_batch_raw(self, **kwargs: object) -> pl.DataFrame:
        self.calls.append(kwargs)
        if isinstance(self.frame, BaseException):
            raise self.frame
        return self.frame


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
