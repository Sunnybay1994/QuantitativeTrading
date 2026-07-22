from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import stat
import sys
import traceback
from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl
import pytest

import quant.data.m3_backfill as backfill
from quant.data.m3_backfill import (
    ENDPOINT_POLICIES_V1,
    TUSHARE_FIELDS,
    EndpointPolicy,
    M3BackfillError,
    TushareRequestBatch,
    TushareRequestSpec,
    execute_tushare_batch,
    plan_history_requests,
    plan_index_weight_requests,
    resolve_history_window,
    response_content_sha256,
    verify_tushare_receipt,
)
from quant.data.storage import RawStore


def _require_symlink(
    link: Path, target: Path, *, target_is_directory: bool = False
) -> None:
    """Create a symlink; skip only when Windows reports missing symlink privilege (1314)."""
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        if sys.platform == "win32" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows session lacks SeCreateSymbolicLinkPrivilege")
        raise


def _require_fifo(path: Path) -> None:
    """Create a FIFO; skip when the platform/filesystem cannot create one."""
    mkfifo = getattr(os, "mkfifo", None)
    if mkfifo is None:
        pytest.skip("filesystem does not support FIFO")
    try:
        mkfifo(path)
    except OSError:
        pytest.skip("filesystem does not support FIFO")


def _frame(endpoint: str, *, value: str = "x", rows: int = 1) -> pl.DataFrame:
    columns = TUSHARE_FIELDS[endpoint].split(",")
    return pl.DataFrame({name: [value] * rows for name in columns})


class FakeConnector:
    def __init__(self, frames: dict[str, pl.DataFrame] | None = None) -> None:
        self.frames = frames or {name: _frame(name) for name in TUSHARE_FIELDS}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.errors: list[BaseException] = []

    def _return(self, endpoint: str, values: dict[str, Any]) -> pl.DataFrame:
        self.calls.append((endpoint, values))
        if self.errors:
            raise self.errors.pop(0)
        return self.frames[endpoint].clone()

    def fetch_index_weight_raw(self, **values: Any) -> pl.DataFrame:
        return self._return("index_weight", values)

    def fetch_daily_raw(self, **values: Any) -> pl.DataFrame:
        return self._return("daily", values)

    def fetch_adj_factor_raw(self, **values: Any) -> pl.DataFrame:
        return self._return("adj_factor", values)

    def fetch_index_daily_raw(self, **values: Any) -> pl.DataFrame:
        return self._return("index_daily", values)

    def fetch_suspend_raw(self, **values: Any) -> pl.DataFrame:
        return self._return("suspend_d", values)

    def fetch_stk_limit_raw(self, **values: Any) -> pl.DataFrame:
        return self._return("stk_limit", values)

    def fetch_dividend_raw(self, **values: Any) -> pl.DataFrame:
        return self._return("dividend", values)


def _weight_batch() -> TushareRequestBatch:
    return plan_index_weight_requests(
        index_code="000300.SH",
        start=dt.date(2020, 2, 15),
        end=dt.date(2020, 2, 20),
        warmup_months=0,
    )


def _execute(
    tmp_path: Path,
    connector: FakeConnector,
    *,
    batch: TushareRequestBatch | None = None,
    monotonic: Any = __import__("time").monotonic,
    sleep: Any = __import__("time").sleep,
    classifier: Any = lambda error: "UNKNOWN",
    max_attempts: int = 3,
    retry_base_seconds: float = 1.0,
    max_new_requests: int | None = None,
) -> tuple[Any, ...]:
    result = execute_tushare_batch(
        batch=batch or _weight_batch(),
        connector=connector,  # type: ignore[arg-type]
        raw_store=RawStore(tmp_path / "raw"),
        journal_root=tmp_path / "journal",
        endpoint_policies=ENDPOINT_POLICIES_V1,
        request_rate_per_minute=60,
        max_attempts=max_attempts,
        retry_base_seconds=retry_base_seconds,
        monotonic=monotonic,
        sleep=sleep,
        classify_error=classifier,
        max_new_requests=max_new_requests,
    )
    return result.receipts


def test_fields_are_the_single_exact_request_contract() -> None:
    expected = {
        "index_weight": "index_code,con_code,trade_date,weight",
        "daily": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
        "adj_factor": "ts_code,trade_date,adj_factor",
        "index_daily": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
        "suspend_d": "ts_code,trade_date,suspend_timing,suspend_type",
        "stk_limit": "trade_date,ts_code,pre_close,up_limit,down_limit",
        "dividend": (
            "ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,"
            "cash_div,cash_div_tax,record_date,ex_date,pay_date,div_listdate,"
            "imp_ann_date,base_date,base_share"
        ),
    }
    assert dict(TUSHARE_FIELDS) == expected


@pytest.mark.parametrize(
    ("start", "end", "warmup", "expected"),
    [
        (
            dt.date(2016, 1, 15),
            dt.date(2016, 2, 10),
            1,
            [("20151201", "20151231"), ("20160101", "20160131"), ("20160201", "20160229")],
        ),
        (dt.date(2020, 2, 20), dt.date(2020, 2, 21), 0, [("20200201", "20200229")]),
    ],
)
def test_index_weight_plans_complete_calendar_months(
    start: dt.date,
    end: dt.date,
    warmup: int,
    expected: list[tuple[str, str]],
) -> None:
    batch = plan_index_weight_requests(
        index_code="000300.SH", start=start, end=end, warmup_months=warmup
    )
    ranges = sorted(
        (dict(spec.parameters)["start_date"], dict(spec.parameters)["end_date"])
        for spec in batch.requests
    )
    assert ranges == expected


def test_history_window_is_exact_and_rejects_alignment_or_short_calendar() -> None:
    dates = tuple(dt.date(2020, 1, 1) + dt.timedelta(days=index) for index in range(100))
    window = resolve_history_window(
        open_dates=dates,
        signal_start=dates[60],
        signal_end=dates[89],
        feature_warmup_sessions=60,
        label_tail_sessions=10,
    )
    assert window.start == dates[0]
    assert window.end == dates[99]
    with pytest.raises(ValueError, match="开市日"):
        resolve_history_window(
            open_dates=dates,
            signal_start=dt.date(2019, 12, 31),
            signal_end=dates[89],
            feature_warmup_sessions=60,
            label_tail_sessions=10,
        )
    with pytest.raises(ValueError, match="不足"):
        resolve_history_window(
            open_dates=dates,
            signal_start=dates[59],
            signal_end=dates[89],
            feature_warmup_sessions=60,
            label_tail_sessions=10,
        )


def test_history_plan_deduplicates_and_sorts_symbols_and_has_exact_counts() -> None:
    weight = _weight_batch()
    history = backfill.HistoryWindow(dt.date(2020, 1, 15), dt.date(2020, 3, 2))
    left = plan_history_requests(
        index_weight_batch=weight,
        symbols=["600000.SH", "000001.SZ", "600000.SH"],
        benchmark="H00300.CSI",
        history=history,
    )
    right = plan_history_requests(
        index_weight_batch=weight,
        symbols=["000001.SZ", "600000.SH"],
        benchmark="H00300.CSI",
        history=history,
    )
    assert left.plan_sha256 == right.plan_sha256
    assert len(left.history_batch.requests) == 11
    counts: dict[str, int] = {}
    for request in left.history_batch.requests:
        counts[request.endpoint] = counts.get(request.endpoint, 0) + 1
    assert counts == {
        "daily": 2,
        "adj_factor": 2,
        "stk_limit": 2,
        "dividend": 2,
        "suspend_d": 2,
        "index_daily": 1,
    }
    suspend_by_symbol = {
        dict(spec.parameters)["ts_code"]: dict(spec.parameters)
        for spec in left.history_batch.requests
        if spec.endpoint == "suspend_d"
    }
    assert set(suspend_by_symbol) == {"000001.SZ", "600000.SH"}
    for symbol, params in suspend_by_symbol.items():
        assert params == {
            "end_date": "20200302",
            "fields": TUSHARE_FIELDS["suspend_d"],
            "start_date": "20200115",
            "suspend_type": "S",
            "ts_code": symbol,
        }
    with pytest.raises(ValueError, match="六位"):
        plan_history_requests(
            index_weight_batch=weight,
            symbols=["1.SH"],
            benchmark="H00300.CSI",
            history=history,
        )


def test_history_suspend_symbol_and_window_bind_request_identity() -> None:
    weight = _weight_batch()
    base = backfill.HistoryWindow(dt.date(2020, 1, 15), dt.date(2020, 3, 2))
    shifted = backfill.HistoryWindow(dt.date(2020, 1, 15), dt.date(2020, 3, 3))
    first = plan_history_requests(
        index_weight_batch=weight,
        symbols=["000001.SZ"],
        benchmark="H00300.CSI",
        history=base,
    )
    window_changed = plan_history_requests(
        index_weight_batch=weight,
        symbols=["000001.SZ"],
        benchmark="H00300.CSI",
        history=shifted,
    )
    symbol_changed = plan_history_requests(
        index_weight_batch=weight,
        symbols=["000002.SZ"],
        benchmark="H00300.CSI",
        history=base,
    )
    assert first.plan_sha256 != window_changed.plan_sha256
    assert first.plan_sha256 != symbol_changed.plan_sha256
    first_suspend = next(
        spec for spec in first.history_batch.requests if spec.endpoint == "suspend_d"
    )
    window_suspend = next(
        spec
        for spec in window_changed.history_batch.requests
        if spec.endpoint == "suspend_d"
    )
    symbol_suspend = next(
        spec
        for spec in symbol_changed.history_batch.requests
        if spec.endpoint == "suspend_d"
    )
    assert first_suspend.request_id != window_suspend.request_id
    assert first_suspend.request_id != symbol_suspend.request_id
    daily_ids = {
        plan.plan_sha256: next(
            spec.request_id
            for spec in plan.history_batch.requests
            if spec.endpoint == "daily"
        )
        for plan in (first, window_changed, symbol_changed)
    }
    assert daily_ids[first.plan_sha256] != daily_ids[window_changed.plan_sha256]
    assert daily_ids[first.plan_sha256] != daily_ids[symbol_changed.plan_sha256]


def test_legacy_monthly_suspend_spec_fails_before_sdk(tmp_path: Path) -> None:
    legacy = TushareRequestSpec.create(
        endpoint="suspend_d",
        parameters={
            "fields": TUSHARE_FIELDS["suspend_d"],
            "start_date": "20200101",
            "end_date": "20200131",
            "suspend_type": "S",
        },
    )
    connector = FakeConnector()
    with pytest.raises(ValueError, match="参数字段集合"):
        TushareRequestBatch(
            "m3-g1-tushare-request-batch-v1",
            "HISTORY",
            (legacy,),
            backfill._batch_hash("HISTORY", (legacy,)),
        )
    assert not connector.calls
    assert not (tmp_path / "journal").exists()
    with pytest.raises(KeyError):
        backfill._fetch(connector, legacy)  # type: ignore[arg-type]
    assert not connector.calls


def test_suspend_fetch_passes_symbol_and_honors_empty_allow(tmp_path: Path) -> None:
    parameters = {
        "fields": TUSHARE_FIELDS["suspend_d"],
        "ts_code": "000001.SZ",
        "start_date": "20200115",
        "end_date": "20200302",
        "suspend_type": "S",
    }
    spec = TushareRequestSpec.create(endpoint="suspend_d", parameters=parameters)
    batch = TushareRequestBatch(
        "m3-g1-tushare-request-batch-v1",
        "HISTORY",
        (spec,),
        backfill._batch_hash("HISTORY", (spec,)),
    )
    connector = FakeConnector()
    connector.frames["suspend_d"] = pl.DataFrame(
        schema={name: pl.String for name in TUSHARE_FIELDS["suspend_d"].split(",")}
    )
    _execute(tmp_path, connector, batch=batch)
    assert connector.calls == [
        (
            "suspend_d",
            {
                "symbol": "000001.SZ",
                "start": dt.date(2020, 1, 15),
                "end": dt.date(2020, 3, 2),
                "fields": TUSHARE_FIELDS["suspend_d"],
            },
        )
    ]


def test_forged_request_and_batch_fail_before_io(tmp_path: Path) -> None:
    spec = _weight_batch().requests[0]
    with pytest.raises(ValueError, match="request_id"):
        replace(spec, request_id="0" * 64)
    with pytest.raises(ValueError, match="batch_sha256"):
        replace(_weight_batch(), batch_sha256="0" * 64)
    assert not (tmp_path / "journal").exists()
    assert not (tmp_path / "raw").exists()


def test_noncanonical_endpoint_parameters_fail_before_io(tmp_path: Path) -> None:
    spec = TushareRequestSpec.create(
        endpoint="daily", parameters={"fields": TUSHARE_FIELDS["daily"], "marker": "x"}
    )
    with pytest.raises(ValueError, match="参数字段集合"):
        TushareRequestBatch(
            "m3-g1-tushare-request-batch-v1",
            "HISTORY",
            (spec,),
            backfill._batch_hash("HISTORY", (spec,)),
        )
    assert not (tmp_path / "journal").exists()

    original = dict(_weight_batch().requests[0].parameters)
    changed = {**original, "fields": original["fields"] + ",extra"}
    changed_spec = TushareRequestSpec.create(endpoint="index_weight", parameters=changed)
    assert changed_spec.request_id != _weight_batch().requests[0].request_id


def test_direct_batch_and_plan_revalidate_nested_contracts() -> None:
    bad_spec = TushareRequestSpec.create(
        endpoint="daily", parameters={"fields": TUSHARE_FIELDS["daily"], "marker": "x"}
    )
    with pytest.raises(ValueError, match="参数字段集合"):
        TushareRequestBatch(
            "m3-g1-tushare-request-batch-v1",
            "HISTORY",
            (bad_spec,),
            backfill._batch_hash("HISTORY", (bad_spec,)),
        )

    with pytest.raises(ValueError, match="不能为空"):
        TushareRequestBatch(
            "m3-g1-tushare-request-batch-v1",
            "HISTORY",
            (),
            backfill._batch_hash("HISTORY", ()),
        )

    plan = plan_history_requests(
        index_weight_batch=_weight_batch(),
        symbols=["000001.SZ"],
        benchmark="H00300.CSI",
        history=backfill.HistoryWindow(dt.date(2020, 1, 1), dt.date(2020, 1, 31)),
    )
    object.__setattr__(plan.history_batch, "batch_sha256", "0" * 64)
    with pytest.raises(ValueError, match="batch_sha256"):
        backfill.G1RequestPlan(
            "m3-g1-request-plan-v1",
            plan.index_weight_batch,
            plan.history_batch,
            backfill._plan_hash(plan.index_weight_batch, plan.history_batch),
        )


def test_executor_passes_fields_and_reuses_valid_receipt_without_clock_or_api(
    tmp_path: Path,
) -> None:
    connector = FakeConnector()
    first = _execute(tmp_path, connector)
    assert connector.calls[0][1]["fields"] == TUSHARE_FIELDS["index_weight"]
    connector.calls.clear()

    def forbidden(*_: Any) -> Any:
        raise AssertionError("cache hit must not call clock/sleep")

    second = _execute(tmp_path, connector, monotonic=forbidden, sleep=forbidden)
    assert not connector.calls
    assert second == first


def test_verified_response_recomputes_receipt_bytes_and_frame_content(tmp_path: Path) -> None:
    _execute(tmp_path, FakeConnector())
    spec = _weight_batch().requests[0]
    verified = verify_tushare_receipt(
        spec=spec,
        receipt_path=tmp_path / "journal" / spec.request_id / "receipt.json",
        raw_root=tmp_path / "raw",
        journal_root=tmp_path / "journal",
        policy=ENDPOINT_POLICIES_V1["index_weight"],
    )
    with pytest.raises(ValueError, match="receipt_sha256"):
        backfill.VerifiedRawResponse(
            verified.spec, verified.receipt, "0" * 64, verified.frame
        )
    changed = verified.frame.with_columns(pl.lit("changed").alias("weight"))
    with pytest.raises(ValueError, match="content digest"):
        backfill.VerifiedRawResponse(
            verified.spec, verified.receipt, verified.receipt_sha256, changed
        )


def test_intent_only_retry_and_raw_duplicate_rows_are_preserved(tmp_path: Path) -> None:
    connector = FakeConnector()
    connector.errors = [PermissionError("denied")]
    with pytest.raises(M3BackfillError, match="PERMANENT"):
        _execute(tmp_path, connector, classifier=lambda _: "PERMISSION")
    spec = _weight_batch().requests[0]
    request_dir = tmp_path / "journal" / spec.request_id
    assert (request_dir / "intent.json").exists()
    assert not (request_dir / "candidate.json").exists()

    connector.frames["index_weight"] = pl.concat(
        [_frame("index_weight", value="same"), _frame("index_weight", value="same")]
    )
    _execute(tmp_path, connector)
    raw = pl.read_parquet(
        tmp_path
        / "raw"
        / "tushare"
        / "index_weight"
        / f"request={spec.request_id}"
        / "data.parquet"
    )
    assert raw.height == 2


@pytest.mark.parametrize(
    ("point", "recoverable"),
    [
        ("after_data", False),
        ("after_metadata", True),
        ("after_candidate", True),
        ("before_receipt", True),
    ],
)
def test_fault_injection_recovery_is_zero_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str, recoverable: bool
) -> None:
    connector = FakeConnector()
    fired = False

    def crash(name: str) -> None:
        nonlocal fired
        if name == point and not fired:
            fired = True
            raise RuntimeError("simulated crash")

    monkeypatch.setattr(backfill, "_fault_point", crash)
    with pytest.raises(RuntimeError, match="simulated"):
        _execute(tmp_path, connector)
    assert len(connector.calls) == 1
    monkeypatch.setattr(backfill, "_fault_point", lambda _: None)
    if recoverable:
        _execute(tmp_path, connector)
        assert len(connector.calls) == 1
    else:
        with pytest.raises(M3BackfillError, match="RAW_ORPHAN"):
            _execute(tmp_path, connector)
        assert len(connector.calls) == 1


def test_corrupt_receipt_and_extra_candidate_like_file_fail_without_api(tmp_path: Path) -> None:
    connector = FakeConnector()
    _execute(tmp_path, connector)
    spec = _weight_batch().requests[0]
    receipt = tmp_path / "journal" / spec.request_id / "receipt.json"
    receipt.write_text('{"schema_version":"bad"}', encoding="utf-8")
    connector.calls.clear()
    with pytest.raises(M3BackfillError, match="RECEIPT_INVALID"):
        _execute(tmp_path, connector)
    assert not connector.calls

    receipt.unlink()
    (receipt.parent / "candidate-2.json").write_text("{}", encoding="utf-8")
    with pytest.raises(M3BackfillError, match="JOURNAL_"):
        _execute(tmp_path, connector)
    assert not connector.calls


@pytest.mark.parametrize(
    "payload",
    [
        b'{"schema_version":"x","schema_version":"y"}',
        b"\xff\xfe",
        b'{"raw_size_bytes":"1"}',
        b'{"unknown":1}',
        b'{"raw_size_bytes":NaN}',
    ],
)
def test_receipt_json_is_strict_and_never_refetches(tmp_path: Path, payload: bytes) -> None:
    connector = FakeConnector()
    _execute(tmp_path, connector)
    spec = _weight_batch().requests[0]
    receipt = tmp_path / "journal" / spec.request_id / "receipt.json"
    receipt.write_bytes(payload)
    connector.calls.clear()
    with pytest.raises(M3BackfillError, match="RECEIPT_INVALID"):
        _execute(tmp_path, connector)
    assert connector.calls == []


def test_existing_writer_lock_file_is_ignored_and_run_succeeds(tmp_path: Path) -> None:
    journal = tmp_path / "journal"
    journal.mkdir()
    lock_path = journal / ".writer.lock"
    lock_path.write_text("active", encoding="utf-8")
    connector = FakeConnector()
    receipts = _execute(tmp_path, connector)
    assert receipts
    assert connector.calls
    assert lock_path.exists()
    assert stat.S_ISREG(os.lstat(lock_path).st_mode)


def test_active_flock_fails_before_request_io(tmp_path: Path) -> None:
    from quant.data._journal_lock import hold_journal_writer_lock

    journal = (tmp_path / "journal").resolve()
    journal.mkdir()
    connector = FakeConnector()
    with hold_journal_writer_lock(journal_root=journal):
        with pytest.raises(M3BackfillError, match="WRITER_ACTIVE") as caught:
            _execute(tmp_path, connector)
    assert not connector.calls
    assert str(tmp_path) not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("root_kind", ["raw_root", "raw_parent", "journal_parent", "raw_file"])
def test_controlled_roots_fail_before_any_side_effect(
    tmp_path: Path, root_kind: str
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    raw_root = tmp_path / "raw"
    journal_root = tmp_path / "journal"
    if root_kind == "raw_root":
        _require_symlink(raw_root, real, target_is_directory=True)
    elif root_kind == "raw_parent":
        parent = tmp_path / "raw-parent"
        _require_symlink(parent, real, target_is_directory=True)
        raw_root = parent / "raw"
    elif root_kind == "journal_parent":
        parent = tmp_path / "journal-parent"
        _require_symlink(parent, real, target_is_directory=True)
        journal_root = parent / "journal"
    else:
        raw_root.write_text("not a directory", encoding="utf-8")
    connector = FakeConnector()
    clock = FakeClock()
    with pytest.raises(M3BackfillError) as caught:
        execute_tushare_batch(
            batch=_weight_batch(),
            connector=connector,  # type: ignore[arg-type]
            raw_store=RawStore(raw_root),
            journal_root=journal_root,
            endpoint_policies=ENDPOINT_POLICIES_V1,
            request_rate_per_minute=60,
            max_attempts=1,
            retry_base_seconds=1.0,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            classify_error=lambda _: "UNKNOWN",
        )
    assert connector.calls == []
    assert clock.sleeps == [] and clock.now == 0.0
    rendered = "".join(traceback.format_exception(caught.value))
    assert str(tmp_path) not in rendered
    if root_kind in {"raw_root", "raw_parent", "raw_file"}:
        assert not journal_root.exists()
    assert list(real.iterdir()) == []


@pytest.mark.parametrize(
    "layout",
    [
        "data_only",
        "metadata_only",
        "request_symlink",
        "request_file",
        "unknown_directory",
        "directory_symlink",
        "file_symlink",
        "fifo",
        "unknown_file",
    ],
)
def test_raw_request_layout_is_strictly_checked_before_network(
    tmp_path: Path, layout: str
) -> None:
    spec = _weight_batch().requests[0]
    store = RawStore(tmp_path / "raw")
    data_path, _ = store.request_paths(
        source="tushare", table="index_weight", request_id=spec.request_id
    )
    request_dir = data_path.parent
    request_dir.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    if layout == "request_symlink":
        outside.mkdir()
        _require_symlink(request_dir, outside, target_is_directory=True)
    elif layout == "request_file":
        request_dir.write_text("not a directory", encoding="utf-8")
    else:
        request_dir.mkdir()
        entry = request_dir / "unknown"
        if layout == "data_only":
            _frame("index_weight").write_parquet(request_dir / "data.parquet")
        elif layout == "metadata_only":
            (request_dir / "metadata.json").write_text("{}", encoding="utf-8")
        elif layout == "unknown_directory":
            entry.mkdir()
        elif layout == "directory_symlink":
            outside.mkdir()
            _require_symlink(entry, outside, target_is_directory=True)
        elif layout == "file_symlink":
            outside.write_text("x", encoding="utf-8")
            _require_symlink(entry, outside)
        elif layout == "fifo":
            _require_fifo(entry)
        else:
            entry.write_text("unknown", encoding="utf-8")
    connector = FakeConnector()
    clock = FakeClock()
    raw_before = _regular_files(tmp_path / "raw")
    journal_before = _journal_payload_files(tmp_path / "journal")
    with pytest.raises(M3BackfillError, match="RAW_") as caught:
        _execute(
            tmp_path,
            connector,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
    assert connector.calls == []
    assert clock.now == 0.0 and clock.sleeps == []
    assert _regular_files(tmp_path / "raw") == raw_before
    assert _journal_payload_files(tmp_path / "journal") == journal_before
    _assert_sanitized(caught.value, str(tmp_path), "token-layout-secret")
    if layout == "request_symlink":
        assert list(outside.iterdir()) == []


def test_empty_real_raw_request_directory_allows_first_network_call(tmp_path: Path) -> None:
    spec = _weight_batch().requests[0]
    store = RawStore(tmp_path / "raw")
    data_path, _ = store.request_paths(
        source="tushare", table="index_weight", request_id=spec.request_id
    )
    data_path.parent.mkdir(parents=True)
    connector = FakeConnector()
    _execute(tmp_path, connector)
    assert len(connector.calls) == 1


def test_existing_valid_intent_with_empty_raw_directory_can_retry_network(tmp_path: Path) -> None:
    connector = FakeConnector()
    connector.errors = [PermissionError("denied")]
    with pytest.raises(M3BackfillError, match="PERMANENT"):
        _execute(tmp_path, connector, classifier=lambda _: "PERMISSION")
    spec = _weight_batch().requests[0]
    data_path, _ = RawStore(tmp_path / "raw").request_paths(
        source="tushare", table="index_weight", request_id=spec.request_id
    )
    data_path.parent.mkdir(parents=True)
    retry = FakeConnector()
    _execute(tmp_path, retry)
    assert len(retry.calls) == 1


@pytest.mark.parametrize(
    ("raw_state", "intent_exists", "candidate_exists", "mode"),
    [
        ("ABSENT", False, False, "NETWORK"),
        ("EMPTY", True, False, "NETWORK"),
        ("COMPLETE", True, False, "RECOVER"),
        ("COMPLETE", True, True, "RECOVER"),
    ],
)
def test_no_receipt_preflight_accepts_only_legal_internal_states(
    raw_state: Any,
    intent_exists: Any,
    candidate_exists: Any,
    mode: Any,
) -> None:
    assert backfill._NoReceiptPreflight(
        raw_state, intent_exists, candidate_exists, mode
    ).mode == mode


@pytest.mark.parametrize(
    ("raw_state", "intent_exists", "candidate_exists", "mode"),
    [
        ("BROKEN", False, False, "NETWORK"),
        ("ABSENT", 1, False, "NETWORK"),
        ("ABSENT", False, 0, "NETWORK"),
        ("ABSENT", False, False, "BROKEN"),
        ("COMPLETE", True, False, "NETWORK"),
        ("ABSENT", False, True, "NETWORK"),
        ("ABSENT", True, False, "RECOVER"),
        ("EMPTY", True, False, "RECOVER"),
        ("COMPLETE", False, False, "RECOVER"),
    ],
)
def test_no_receipt_preflight_rejects_illegal_internal_states(
    raw_state: Any,
    intent_exists: Any,
    candidate_exists: Any,
    mode: Any,
) -> None:
    with pytest.raises(ValueError, match="preflight"):
        backfill._NoReceiptPreflight(raw_state, intent_exists, candidate_exists, mode)


def test_network_preflight_detects_second_writer_before_candidate_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initial = FakeConnector()
    initial.errors = [PermissionError("denied")]
    with pytest.raises(M3BackfillError, match="PERMANENT"):
        _execute(tmp_path, initial, classifier=lambda _: "PERMISSION")

    spec = _weight_batch().requests[0]
    journal_before = _journal_payload_files(tmp_path / "journal")
    original_recover = backfill._recover_candidate

    def second_writer_then_recover(**kwargs: Any) -> Any:
        RawStore(tmp_path / "raw").write_request(
            source="tushare",
            table=spec.endpoint,
            request_id=spec.request_id,
            frame=_frame(spec.endpoint),
            parameters=dict(spec.parameters),
        )
        return original_recover(**kwargs)

    monkeypatch.setattr(backfill, "_recover_candidate", second_writer_then_recover)
    retry = FakeConnector()
    clock = FakeClock()
    with pytest.raises(M3BackfillError, match="REQUEST_EVIDENCE_CLOSURE_CHANGED"):
        _execute(
            tmp_path,
            retry,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
    assert retry.calls == [] and clock.now == 0.0 and clock.sleeps == []
    assert _journal_payload_files(tmp_path / "journal") == journal_before


def test_recover_preflight_detects_raw_regression_before_candidate_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initial = FakeConnector()
    initial.errors = [PermissionError("denied")]
    with pytest.raises(M3BackfillError, match="PERMANENT"):
        _execute(tmp_path, initial, classifier=lambda _: "PERMISSION")

    spec = _weight_batch().requests[0]
    store = RawStore(tmp_path / "raw")
    store.write_request(
        source="tushare",
        table=spec.endpoint,
        request_id=spec.request_id,
        frame=_frame(spec.endpoint),
        parameters=dict(spec.parameters),
    )
    data_path, metadata_path = store.request_paths(
        source="tushare", table=spec.endpoint, request_id=spec.request_id
    )
    journal_before = _journal_payload_files(tmp_path / "journal")
    original_recover = backfill._recover_candidate

    def second_writer_then_recover(**kwargs: Any) -> Any:
        data_path.unlink()
        metadata_path.unlink()
        return original_recover(**kwargs)

    monkeypatch.setattr(backfill, "_recover_candidate", second_writer_then_recover)
    retry = FakeConnector()
    clock = FakeClock()
    with pytest.raises(M3BackfillError, match="REQUEST_EVIDENCE_CLOSURE_CHANGED"):
        _execute(
            tmp_path,
            retry,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
    assert retry.calls == [] and clock.now == 0.0 and clock.sleeps == []
    assert _journal_payload_files(tmp_path / "journal") == journal_before


def test_recover_revalidates_same_raw_evidence_before_candidate_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initial = FakeConnector()
    initial.errors = [PermissionError("denied")]
    with pytest.raises(M3BackfillError, match="PERMANENT"):
        _execute(tmp_path, initial, classifier=lambda _: "PERMISSION")

    spec = _weight_batch().requests[0]
    store = RawStore(tmp_path / "raw")
    store.write_request(
        source="tushare",
        table=spec.endpoint,
        request_id=spec.request_id,
        frame=_frame(spec.endpoint, value="raw-a"),
        parameters=dict(spec.parameters),
    )
    data_path, metadata_path = store.request_paths(
        source="tushare", table=spec.endpoint, request_id=spec.request_id
    )
    request_dir = tmp_path / "journal" / spec.request_id
    original_inspect = RawStore.inspect_request_state
    inspect_calls = 0
    replacing = False

    def replace_before_final_inspect(
        self: RawStore, *, source: str, table: str, request_id: str
    ) -> Any:
        nonlocal inspect_calls, replacing
        if replacing:
            return original_inspect(
                self, source=source, table=table, request_id=request_id
            )
        inspect_calls += 1
        if inspect_calls == 4:
            replacing = True
            try:
                data_path.unlink()
                metadata_path.unlink()
                RawStore(self.root).write_request(
                    source=source,
                    table=table,
                    request_id=request_id,
                    frame=_frame(spec.endpoint, value="raw-b"),
                    parameters=dict(spec.parameters),
                )
            finally:
                replacing = False
        return original_inspect(
            self, source=source, table=table, request_id=request_id
        )

    monkeypatch.setattr(RawStore, "inspect_request_state", replace_before_final_inspect)
    retry = FakeConnector()
    clock = FakeClock()
    with pytest.raises(M3BackfillError) as caught:
        _execute(
            tmp_path,
            retry,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
    assert not (request_dir / "candidate.json").exists()
    assert not (request_dir / "receipt.json").exists()
    assert str(caught.value) == "CANDIDATE_RAW_EVIDENCE_MISMATCH"
    assert retry.calls == [] and clock.now == 0.0 and clock.sleeps == []


def _replace_request_raw_variant(
    data_path: Path,
    metadata_path: Path,
    endpoint: str,
    variant: str,
) -> None:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if variant == "metadata_only":
        metadata["fetched_at"] = "2026-07-14T00:00:00+00:00"
    elif variant == "bad_hash":
        metadata["checksum_sha256"] = "0" * 64
    else:
        frame = _frame(endpoint, value="raw-a")
        if variant == "physical":
            pass
        elif variant == "rows":
            frame = _frame(endpoint, value="raw-b", rows=2)
        elif variant == "columns":
            frame = frame.drop(frame.columns[-1])
        elif variant == "content":
            frame = _frame(endpoint, value="raw-b")
        else:
            raise AssertionError(f"unknown raw variant: {variant}")
        buffer = io.BytesIO()
        compression = "uncompressed" if variant == "physical" else "zstd"
        frame.write_parquet(buffer, compression=compression)
        payload = buffer.getvalue()
        data_path.write_bytes(payload)
        metadata["checksum_sha256"] = hashlib.sha256(payload).hexdigest()
        metadata["size_bytes"] = len(payload)
        metadata["rows"] = frame.height
        metadata["columns"] = frame.columns
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "variant", ["metadata_only", "physical", "bad_hash", "rows", "columns", "content"]
)
def test_commit_verifier_never_mixes_snapshot_and_frame_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    initial = FakeConnector()
    initial.errors = [PermissionError("denied")]
    with pytest.raises(M3BackfillError, match="PERMANENT"):
        _execute(tmp_path, initial, classifier=lambda _: "PERMISSION")

    spec = _weight_batch().requests[0]
    store = RawStore(tmp_path / "raw")
    store.write_request(
        source="tushare",
        table=spec.endpoint,
        request_id=spec.request_id,
        frame=_frame(spec.endpoint, value="raw-a"),
        parameters=dict(spec.parameters),
    )
    data_path, metadata_path = store.request_paths(
        source="tushare", table=spec.endpoint, request_id=spec.request_id
    )
    request_dir = tmp_path / "journal" / spec.request_id
    injected = False
    verify_calls = 0
    original_verify = RawStore.verify_request

    def verify_then_replace(self: RawStore, **kwargs: Any) -> Any:
        nonlocal injected, verify_calls
        result = original_verify(self, **kwargs)
        verify_calls += 1
        if verify_calls == 2:
            _replace_request_raw_variant(data_path, metadata_path, spec.endpoint, variant)
            injected = True
        return result

    monkeypatch.setattr(RawStore, "verify_request", verify_then_replace)
    original_bundle = getattr(RawStore, "verify_request_bundle", None)
    if original_bundle is not None:
        bundle_calls = 0

        def replace_then_verify_bundle(self: RawStore, **kwargs: Any) -> Any:
            nonlocal bundle_calls, injected
            bundle_calls += 1
            if bundle_calls == 2:
                _replace_request_raw_variant(data_path, metadata_path, spec.endpoint, variant)
                injected = True
            return original_bundle(self, **kwargs)

        monkeypatch.setattr(
            RawStore, "verify_request_bundle", replace_then_verify_bundle
        )

    retry = FakeConnector()
    clock = FakeClock()
    with pytest.raises(M3BackfillError):
        _execute(
            tmp_path,
            retry,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
    assert injected
    assert not (request_dir / "candidate.json").exists()
    assert not (request_dir / "receipt.json").exists()
    assert retry.calls == [] and clock.now == 0.0 and clock.sleeps == []


def test_recover_detects_candidate_appearance_since_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _execute(tmp_path, FakeConnector())
    spec = _weight_batch().requests[0]
    request_dir = tmp_path / "journal" / spec.request_id
    candidate_path = request_dir / "candidate.json"
    receipt_path = request_dir / "receipt.json"
    candidate_payload = candidate_path.read_bytes()
    candidate_path.unlink()
    receipt_path.unlink()
    original_recover = backfill._recover_candidate

    def publish_candidate_then_recover(**kwargs: Any) -> Any:
        candidate_path.write_bytes(candidate_payload)
        return original_recover(**kwargs)

    monkeypatch.setattr(backfill, "_recover_candidate", publish_candidate_then_recover)
    retry = FakeConnector()
    clock = FakeClock()
    with pytest.raises(M3BackfillError, match="^REQUEST_EVIDENCE_CLOSURE_CHANGED$"):
        _execute(
            tmp_path,
            retry,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
    assert candidate_path.read_bytes() == candidate_payload
    assert not receipt_path.exists()
    assert retry.calls == [] and clock.now == 0.0 and clock.sleeps == []


def test_recover_detects_candidate_disappearance_since_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _execute(tmp_path, FakeConnector())
    spec = _weight_batch().requests[0]
    request_dir = tmp_path / "journal" / spec.request_id
    candidate_path = request_dir / "candidate.json"
    receipt_path = request_dir / "receipt.json"
    receipt_path.unlink()
    original_recover = backfill._recover_candidate

    def remove_candidate_then_recover(**kwargs: Any) -> Any:
        candidate_path.unlink()
        return original_recover(**kwargs)

    monkeypatch.setattr(backfill, "_recover_candidate", remove_candidate_then_recover)
    retry = FakeConnector()
    clock = FakeClock()
    with pytest.raises(M3BackfillError, match="^REQUEST_EVIDENCE_CLOSURE_CHANGED$"):
        _execute(
            tmp_path,
            retry,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
    assert not candidate_path.exists()
    assert not receipt_path.exists()
    assert retry.calls == [] and clock.now == 0.0 and clock.sleeps == []


def test_existing_invalid_intent_fails_read_only_before_network(tmp_path: Path) -> None:
    spec = _weight_batch().requests[0]
    request_dir = tmp_path / "journal" / spec.request_id
    request_dir.mkdir(parents=True)
    (request_dir / "intent.json").write_text("{}", encoding="utf-8")
    before = _journal_payload_files(tmp_path / "journal")
    connector = FakeConnector()
    clock = FakeClock()
    with pytest.raises(M3BackfillError, match="INTENT_INVALID"):
        _execute(
            tmp_path,
            connector,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
    assert connector.calls == [] and clock.now == 0.0 and clock.sleeps == []
    assert _journal_payload_files(tmp_path / "journal") == before


def _regular_files(root: Path) -> set[str]:
    if not root.exists():
        return set()
    result: set[str] = set()
    for current, _, names in os.walk(root, followlinks=False):
        for name in names:
            path = Path(current) / name
            if stat.S_ISREG(os.lstat(path).st_mode):
                result.add(path.relative_to(root).as_posix())
    return result


def _journal_payload_files(root: Path) -> set[str]:
    """Journal business files; persistent advisory ``.writer.lock`` is not a mutation."""
    return {rel for rel in _regular_files(root) if Path(rel).name != ".writer.lock"}


def test_complete_raw_without_intent_fails_without_repairing_journal(tmp_path: Path) -> None:
    spec = _weight_batch().requests[0]
    RawStore(tmp_path / "raw").write_request(
        source="tushare",
        table="index_weight",
        request_id=spec.request_id,
        frame=_frame("index_weight"),
        parameters=dict(spec.parameters),
    )
    connector = FakeConnector()
    clock = FakeClock()
    journal_before = _journal_payload_files(tmp_path / "journal")
    with pytest.raises(M3BackfillError, match="CLOSURE"):
        _execute(
            tmp_path,
            connector,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
    assert connector.calls == [] and clock.now == 0.0 and clock.sleeps == []
    assert _journal_payload_files(tmp_path / "journal") == journal_before


def test_candidate_without_intent_fails_without_repairing_journal(tmp_path: Path) -> None:
    _execute(tmp_path, FakeConnector())
    spec = _weight_batch().requests[0]
    request_dir = tmp_path / "journal" / spec.request_id
    (request_dir / "receipt.json").unlink()
    (request_dir / "intent.json").unlink()
    before = _journal_payload_files(tmp_path / "journal")
    connector = FakeConnector()
    clock = FakeClock()
    with pytest.raises(M3BackfillError, match="CLOSURE"):
        _execute(
            tmp_path,
            connector,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
    assert connector.calls == [] and clock.now == 0.0 and clock.sleeps == []
    assert _journal_payload_files(tmp_path / "journal") == before


@pytest.mark.parametrize("raw_state", ["ABSENT", "EMPTY"])
def test_candidate_requires_complete_raw_without_new_evidence(
    tmp_path: Path, raw_state: str
) -> None:
    _execute(tmp_path, FakeConnector())
    spec = _weight_batch().requests[0]
    journal_dir = tmp_path / "journal" / spec.request_id
    (journal_dir / "receipt.json").unlink()
    raw_data, raw_metadata = RawStore(tmp_path / "raw").request_paths(
        source="tushare", table="index_weight", request_id=spec.request_id
    )
    raw_data.unlink()
    raw_metadata.unlink()
    if raw_state == "ABSENT":
        raw_data.parent.rmdir()
    before = _journal_payload_files(tmp_path / "journal")
    connector = FakeConnector()
    clock = FakeClock()
    with pytest.raises(M3BackfillError, match="CLOSURE"):
        _execute(
            tmp_path,
            connector,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
    assert connector.calls == [] and clock.now == 0.0 and clock.sleeps == []
    assert _journal_payload_files(tmp_path / "journal") == before


@pytest.mark.parametrize(
    "entry_kind", ["directory", "file_symlink", "directory_symlink", "legal_symlink", "fifo"]
)
def test_journal_rejects_every_non_regular_or_unknown_entry(
    tmp_path: Path, entry_kind: str
) -> None:
    connector = FakeConnector()
    _execute(tmp_path, connector)
    spec = _weight_batch().requests[0]
    request_dir = tmp_path / "journal" / spec.request_id
    entry = request_dir / "extra"
    outside = tmp_path / "outside"
    if entry_kind == "directory":
        entry.mkdir()
    elif entry_kind == "file_symlink":
        outside.write_text("x", encoding="utf-8")
        _require_symlink(entry, outside)
    elif entry_kind == "directory_symlink":
        outside.mkdir()
        _require_symlink(entry, outside, target_is_directory=True)
    elif entry_kind == "legal_symlink":
        outside.write_text("{}", encoding="utf-8")
        (request_dir / "receipt.json").unlink()
        _require_symlink(request_dir / "receipt.json", outside)
    else:
        _require_fifo(entry)
    connector.calls.clear()
    with pytest.raises(M3BackfillError, match="JOURNAL"):
        _execute(tmp_path, connector)
    assert connector.calls == []


def _assert_sanitized(error: BaseException, *secrets: str) -> None:
    rendered = "\n".join(
        [str(error), repr(error), "".join(traceback.format_exception(error))]
    )
    for secret in secrets:
        assert secret not in rendered


def test_journal_link_and_fsync_errors_are_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "token-LINK-SECRET"
    private = "/home/private/journal"

    def broken_link(*_: Any, **__: Any) -> None:
        raise OSError(f"{secret} {private}")

    monkeypatch.setattr(backfill.os, "link", broken_link)
    with pytest.raises(M3BackfillError) as caught:
        _execute(tmp_path, FakeConnector())
    _assert_sanitized(caught.value, secret, private)

    monkeypatch.undo()
    secret = "token-FSYNC-SECRET"
    private = "C:\\private\\journal"

    def broken_fsync(*_: Any, **__: Any) -> None:
        raise OSError(f"{secret} {private}")

    monkeypatch.setattr(backfill.os, "fsync", broken_fsync)
    with pytest.raises(M3BackfillError) as caught:
        _execute(tmp_path / "fsync", FakeConnector())
    _assert_sanitized(caught.value, secret, private)


@pytest.mark.parametrize("operation", ["mkdir", "open"])
def test_journal_mkdir_open_errors_are_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    secret = f"token-{operation.upper()}-SECRET"
    private = f"/home/private/{operation}"
    if operation == "mkdir":
        original_mkdir = Path.mkdir

        def broken_mkdir(path: Path, *args: Any, **kwargs: Any) -> None:
            if path == tmp_path / "journal":
                raise OSError(f"{secret} {private}")
            original_mkdir(path, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", broken_mkdir)
    else:
        import quant.data._journal_lock as journal_lock

        monkeypatch.setattr(
            journal_lock.os,
            "open",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError(f"{secret} {private}")),
        )
    connector = FakeConnector()
    with pytest.raises(M3BackfillError) as caught:
        _execute(tmp_path, connector)
    _assert_sanitized(caught.value, secret, private)
    assert connector.calls == []


def test_lock_release_does_not_mask_primary_and_is_sanitized_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno
    import sys

    import quant.data._journal_lock as journal_lock

    secret = "token-UNLOCK-SECRET"
    private = "C:\\private\\lock"
    if sys.platform == "win32":
        real_locking = journal_lock.msvcrt.locking

        def broken_unlock(fd: int, mode: int, nbytes: int) -> None:
            if mode == journal_lock.msvcrt.LK_UNLCK:
                raise OSError(errno.EBADF, f"{secret} {private}")
            real_locking(fd, mode, nbytes)

        monkeypatch.setattr(journal_lock.msvcrt, "locking", broken_unlock)
    else:
        real_flock = journal_lock.fcntl.flock

        def broken_unlock(fd: int, operation: int) -> None:
            if operation == journal_lock.fcntl.LOCK_UN:
                raise OSError(errno.EBADF, f"{secret} {private}")
            real_flock(fd, operation)

        monkeypatch.setattr(journal_lock.fcntl, "flock", broken_unlock)
    connector = FakeConnector()
    connector.errors = [PermissionError("provider-private")]
    with pytest.raises(M3BackfillError, match="PERMANENT") as primary:
        _execute(tmp_path / "primary", connector, classifier=lambda _: "PERMISSION")
    _assert_sanitized(primary.value, secret, private)

    with pytest.raises(M3BackfillError, match="CLEANUP") as cleanup:
        _execute(tmp_path / "cleanup", FakeConnector())
    _assert_sanitized(cleanup.value, secret, private)

def test_parquet_read_chained_error_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _execute(tmp_path, FakeConnector())
    spec = _weight_batch().requests[0]
    store = RawStore(tmp_path / "raw")
    snapshot = store.verify_request(
        source="tushare",
        table="index_weight",
        request_id=spec.request_id,
        parameters=dict(spec.parameters),
    )
    monkeypatch.setattr(RawStore, "verify_request", lambda *args, **kwargs: snapshot)
    secret = "token-PARQUET-SECRET"
    private = "/mnt/g/private/raw.parquet"

    def broken_read(*_: Any, **__: Any) -> pl.DataFrame:
        try:
            raise OSError(f"{secret} {private}")
        except OSError as cause:
            raise OSError("wrapper") from cause

    monkeypatch.setattr(backfill.pl, "read_parquet", broken_read)
    with pytest.raises(M3BackfillError) as caught:
        _execute(tmp_path, FakeConnector())
    _assert_sanitized(caught.value, secret, private)


@pytest.mark.parametrize("missing", ["intent.json", "candidate.json"])
def test_committed_receipt_requires_complete_journal_closure(
    tmp_path: Path, missing: str
) -> None:
    connector = FakeConnector()
    _execute(tmp_path, connector)
    spec = _weight_batch().requests[0]
    (tmp_path / "journal" / spec.request_id / missing).unlink()
    connector.calls.clear()
    with pytest.raises(M3BackfillError, match="COMMITTED_JOURNAL_INCOMPLETE"):
        _execute(tmp_path, connector)
    assert connector.calls == []


def test_receipt_path_escape_and_symlink_fail_closed(tmp_path: Path) -> None:
    connector = FakeConnector()
    receipt_value = _execute(tmp_path, connector)[0]
    spec = _weight_batch().requests[0]
    receipt_path = tmp_path / "journal" / spec.request_id / "receipt.json"
    value = json.loads(receipt_path.read_text(encoding="utf-8"))
    value["raw_data_path"] = "../escape.parquet"
    receipt_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(M3BackfillError, match="RECEIPT_INVALID"):
        verify_tushare_receipt(
            spec=spec,
            receipt_path=receipt_path,
            raw_root=tmp_path / "raw",
            journal_root=tmp_path / "journal",
            policy=ENDPOINT_POLICIES_V1["index_weight"],
        )
    assert receipt_value.request_id == spec.request_id


def test_content_and_stable_hash_semantics(tmp_path: Path) -> None:
    first = _execute(tmp_path / "a", FakeConnector())[0]
    second = _execute(tmp_path / "b", FakeConnector())[0]
    assert first.stable_response_sha256 == second.stable_response_sha256
    assert first.raw_metadata_sha256 != second.raw_metadata_sha256

    frame = _frame("index_weight", value="1")
    reversed_rows = pl.concat([frame, _frame("index_weight", value="2")]).reverse()
    forward_rows = reversed_rows.reverse()
    assert response_content_sha256(reversed_rows, "index_weight") == response_content_sha256(
        forward_rows, "index_weight"
    )
    changed = forward_rows.with_columns(pl.lit("3").alias("weight"))
    assert response_content_sha256(changed, "index_weight") != response_content_sha256(
        forward_rows, "index_weight"
    )
    casted = forward_rows.with_columns(pl.col("weight").cast(pl.Categorical))
    assert response_content_sha256(casted, "index_weight") != response_content_sha256(
        forward_rows, "index_weight"
    )
    reordered = forward_rows.select(list(reversed(forward_rows.columns)))
    assert response_content_sha256(reordered, "index_weight") != response_content_sha256(
        forward_rows, "index_weight"
    )


@pytest.mark.parametrize("endpoint", list(TUSHARE_FIELDS))
def test_empty_policy_for_all_endpoints(endpoint: str, tmp_path: Path) -> None:
    parameters = {
        "fields": TUSHARE_FIELDS[endpoint],
        **(
            {"index_code": "000300.SH"}
            if endpoint == "index_weight"
            else {"ts_code": "H00300.CSI"}
            if endpoint == "index_daily"
            else {"ts_code": "000001.SZ", "suspend_type": "S"}
            if endpoint == "suspend_d"
            else {"ts_code": "000001.SZ"}
        ),
        **(
            {"start_date": "20200101", "end_date": "20200131"}
            if endpoint != "dividend"
            else {}
        ),
    }
    spec = TushareRequestSpec.create(endpoint=endpoint, parameters=parameters)
    batch = TushareRequestBatch(
        "m3-g1-tushare-request-batch-v1",
        "INDEX_WEIGHT" if endpoint == "index_weight" else "HISTORY",
        (spec,),
        backfill._batch_hash("INDEX_WEIGHT" if endpoint == "index_weight" else "HISTORY", (spec,)),
    )
    connector = FakeConnector({name: _frame(name) for name in TUSHARE_FIELDS})
    connector.frames[endpoint] = pl.DataFrame(
        schema={name: pl.String for name in TUSHARE_FIELDS[endpoint].split(",")}
    )
    if ENDPOINT_POLICIES_V1[endpoint].empty_response == "ALLOW":
        _execute(tmp_path, connector, batch=batch)
    else:
        with pytest.raises(M3BackfillError, match="EMPTY"):
            _execute(tmp_path, connector, batch=batch)
    assert connector.calls[0][1]["fields"] == TUSHARE_FIELDS[endpoint]


@pytest.mark.parametrize("endpoint", list(TUSHARE_FIELDS))
@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_row_limit_guard_is_fail_closed(endpoint: str, delta: int, tmp_path: Path) -> None:
    count = ENDPOINT_POLICIES_V1[endpoint].row_limit + delta
    connector = FakeConnector({name: _frame(name) for name in TUSHARE_FIELDS})
    connector.frames[endpoint] = _frame(endpoint, rows=count)
    parameters = {
        "fields": TUSHARE_FIELDS[endpoint],
        **(
            {"index_code": "000300.SH"}
            if endpoint == "index_weight"
            else {"ts_code": "H00300.CSI"}
            if endpoint == "index_daily"
            else {"ts_code": "000001.SZ", "suspend_type": "S"}
            if endpoint == "suspend_d"
            else {"ts_code": "000001.SZ"}
        ),
        **(
            {"start_date": "20200101", "end_date": "20200131"}
            if endpoint != "dividend"
            else {}
        ),
    }
    spec = TushareRequestSpec.create(endpoint=endpoint, parameters=parameters)
    phase = "INDEX_WEIGHT" if endpoint == "index_weight" else "HISTORY"
    batch = TushareRequestBatch(
        "m3-g1-tushare-request-batch-v1",
        phase,
        (spec,),
        backfill._batch_hash(phase, (spec,)),
    )
    if delta == -1:
        _execute(tmp_path, connector, batch=batch)
    else:
        with pytest.raises(M3BackfillError, match="TRUNCATED"):
            _execute(tmp_path, connector, batch=batch)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.mark.parametrize("category", ["NETWORK", "RATE_LIMIT", "TRANSIENT_SERVER"])
def test_typed_transient_retry_uses_later_rate_or_backoff_deadline(
    category: str, tmp_path: Path
) -> None:
    connector = FakeConnector()
    connector.errors = [RuntimeError("transient")]
    clock = FakeClock()
    _execute(
        tmp_path,
        connector,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        classifier=lambda _: category,
        retry_base_seconds=2.0,
    )
    # rate deadline is t=1; exponential backoff deadline is t=2, so t=2 wins.
    assert clock.sleeps == [2.0]
    assert len(connector.calls) == 2


@pytest.mark.parametrize("category", ["PERMISSION", "CONTRACT", "UNKNOWN"])
def test_permanent_or_unknown_error_is_not_retried_and_is_sanitized(
    category: str, tmp_path: Path
) -> None:
    secret = "token-SUPER-SECRET"
    connector = FakeConnector()
    connector.errors = [RuntimeError(f"{secret} C:/private client={connector!r}")]
    with pytest.raises(M3BackfillError) as caught:
        _execute(tmp_path, connector, classifier=lambda _: category)
    rendered = "".join(traceback.format_exception(caught.value))
    assert len(connector.calls) == 1
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
    assert secret not in rendered
    assert "C:/private" not in rendered


def test_attempt_exhaustion_is_sanitized(tmp_path: Path) -> None:
    connector = FakeConnector()
    connector.errors = [RuntimeError("secret") for _ in range(3)]
    clock = FakeClock()
    with pytest.raises(M3BackfillError, match="ATTEMPTS_EXHAUSTED"):
        _execute(
            tmp_path,
            connector,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            classifier=lambda _: "NETWORK",
            max_attempts=3,
        )
    assert len(connector.calls) == 3


def test_two_transient_failures_keep_exact_exponential_deadlines(tmp_path: Path) -> None:
    connector = FakeConnector()
    connector.errors = [RuntimeError("one"), RuntimeError("two")]
    clock = FakeClock()
    _execute(
        tmp_path,
        connector,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        classifier=lambda _: "NETWORK",
        max_attempts=3,
        retry_base_seconds=2.0,
    )
    assert clock.sleeps == [2.0, 4.0]


def test_classifier_chained_sensitive_error_defaults_to_sanitized_permanent(
    tmp_path: Path,
) -> None:
    connector = FakeConnector()
    connector.errors = [RuntimeError("provider failure")]
    secret = "token-CLASSIFIER-SECRET"
    private = "/mnt/g/private/classifier"

    def broken_classifier(_: BaseException) -> str:
        try:
            raise OSError(f"{secret} {private}")
        except OSError as cause:
            raise RuntimeError("wrapper") from cause

    with pytest.raises(M3BackfillError, match="PERMANENT") as caught:
        _execute(tmp_path, connector, classifier=broken_classifier)
    _assert_sanitized(caught.value, secret, private)


def test_weekday_sessions_are_exact_and_duplicate_calendar_fails() -> None:
    dates: list[dt.date] = []
    cursor = dt.date(2020, 1, 1)
    while len(dates) < 100:
        if cursor.weekday() < 5:
            dates.append(cursor)
        cursor += dt.timedelta(days=1)
    window = resolve_history_window(
        open_dates=dates,
        signal_start=dates[60],
        signal_end=dates[89],
        feature_warmup_sessions=60,
        label_tail_sessions=10,
    )
    assert window == backfill.HistoryWindow(dates[0], dates[99])
    with pytest.raises(ValueError, match="严格递增"):
        resolve_history_window(
            open_dates=[*dates[:50], dates[49], *dates[50:]],
            signal_start=dates[60],
            signal_end=dates[89],
            feature_warmup_sessions=60,
            label_tail_sessions=10,
        )


def test_rate_limit_applies_between_two_network_requests(tmp_path: Path) -> None:
    batch = plan_index_weight_requests(
        index_code="000300.SH",
        start=dt.date(2020, 1, 1),
        end=dt.date(2020, 2, 1),
        warmup_months=0,
    )
    clock = FakeClock()
    connector = FakeConnector()
    _execute(
        tmp_path,
        connector,
        batch=batch,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert len(connector.calls) == 2
    assert clock.sleeps == [1.0]


def test_endpoint_policy_mapping_must_be_exact(tmp_path: Path) -> None:
    policies = dict(ENDPOINT_POLICIES_V1)
    policies["daily"] = EndpointPolicy(5999, "REJECT")
    with pytest.raises(ValueError, match="冻结值"):
        execute_tushare_batch(
            batch=_weight_batch(),
            connector=FakeConnector(),  # type: ignore[arg-type]
            raw_store=RawStore(tmp_path / "raw"),
            journal_root=tmp_path / "journal",
            endpoint_policies=policies,
            request_rate_per_minute=60,
            max_attempts=1,
            retry_base_seconds=1.0,
            classify_error=lambda _: "UNKNOWN",
        )
    assert not (tmp_path / "journal").exists()
    assert not (tmp_path / "raw").exists()


def test_data_layer_does_not_import_research() -> None:
    source = Path(backfill.__file__).read_text(encoding="utf-8")
    assert "quant.research" not in source


def _daily_batch(n: int) -> TushareRequestBatch:
    specs = [
        backfill._make_spec(
            "daily",
            ts_code=f"{i:06d}.SZ",
            start_date="20200102",
            end_date="20200103",
        )
        for i in range(n)
    ]
    return backfill._make_batch("HISTORY", specs)


def _execute_result(
    tmp_path: Path,
    connector: FakeConnector,
    *,
    batch: TushareRequestBatch,
    max_new_requests: int | None = None,
    max_attempts: int = 3,
    classifier: Any = lambda error: "NETWORK",
) -> Any:
    return execute_tushare_batch(
        batch=batch,
        connector=connector,  # type: ignore[arg-type]
        raw_store=RawStore(tmp_path / "raw"),
        journal_root=tmp_path / "journal",
        endpoint_policies=ENDPOINT_POLICIES_V1,
        request_rate_per_minute=600000,
        max_attempts=max_attempts,
        retry_base_seconds=0.0,
        classify_error=classifier,
        max_new_requests=max_new_requests,
    )


def test_max_new_requests_rejects_illegal_before_fs_or_api(tmp_path: Path) -> None:
    connector = FakeConnector()
    batch = _daily_batch(2)
    for bad in (True, 0, -1, 1.0, "1"):
        with pytest.raises(ValueError, match="max_new_requests"):
            execute_tushare_batch(
                batch=batch,
                connector=connector,  # type: ignore[arg-type]
                raw_store=RawStore(tmp_path / "raw"),
                journal_root=tmp_path / "journal",
                endpoint_policies=ENDPOINT_POLICIES_V1,
                request_rate_per_minute=60,
                max_attempts=1,
                retry_base_seconds=0.0,
                classify_error=lambda _: "UNKNOWN",
                max_new_requests=bad,  # type: ignore[arg-type]
            )
    assert connector.calls == []
    assert not (tmp_path / "journal").exists()
    assert not (tmp_path / "raw").exists()


def test_bounded_max_new_skips_existing_receipts_and_resumes(
    tmp_path: Path,
) -> None:
    batch = _daily_batch(116)
    connector = FakeConnector()
    first = _execute_result(tmp_path, connector, batch=batch, max_new_requests=114)
    assert first.new_requests_committed == 114
    assert len(connector.calls) == 114
    assert (
        sum(1 for p in (tmp_path / "journal").iterdir() if p.is_dir()) == 114
    )

    connector2 = FakeConnector()
    second = _execute_result(tmp_path, connector2, batch=batch, max_new_requests=2)
    assert second.new_requests_committed == 2
    assert len(connector2.calls) == 2
    assert (
        sum(1 for p in (tmp_path / "journal").iterdir() if p.is_dir()) == 116
    )

    connector3 = FakeConnector()
    third = _execute_result(tmp_path, connector3, batch=batch, max_new_requests=2)
    assert third.new_requests_committed == 0
    assert connector3.calls == []


def test_bounded_budget_next_missing_has_zero_journal_raw_delta(
    tmp_path: Path,
) -> None:
    batch = _daily_batch(4)
    connector = FakeConnector()
    _execute_result(tmp_path, connector, batch=batch, max_new_requests=2)
    journal = tmp_path / "journal"
    raw = tmp_path / "raw"
    dirs = {p.name for p in journal.iterdir() if p.is_dir()}
    assert len(dirs) == 2
    missing = [spec for spec in batch.requests if spec.request_id not in dirs]
    assert len(missing) == 2
    for spec in missing:
        assert not (journal / spec.request_id).exists()
        table_root = raw / "tushare" / spec.endpoint
        if table_root.exists():
            assert not any(spec.request_id in p.as_posix() for p in table_root.rglob("*"))


def test_bounded_resume_second_call_adds_two_new_not_repeat(
    tmp_path: Path,
) -> None:
    batch = _daily_batch(5)
    c1 = FakeConnector()
    r1 = _execute_result(tmp_path, c1, batch=batch, max_new_requests=2)
    assert r1.new_requests_committed == 2
    first_ids = {
        spec.request_id
        for spec in batch.requests
        if (tmp_path / "journal" / spec.request_id / "receipt.json").exists()
    }
    assert len(first_ids) == 2
    calls1 = list(c1.calls)

    c2 = FakeConnector()
    r2 = _execute_result(tmp_path, c2, batch=batch, max_new_requests=2)
    assert r2.new_requests_committed == 2
    second_ids = {
        spec.request_id
        for spec in batch.requests
        if (tmp_path / "journal" / spec.request_id / "receipt.json").exists()
    }
    assert len(second_ids) == 4
    assert first_ids.issubset(second_ids)
    new_call_codes = [params["symbol"] for _, params in c2.calls]
    old_call_codes = [params["symbol"] for _, params in calls1]
    assert set(new_call_codes).isdisjoint(set(old_call_codes))


def test_bounded_retry_counts_one_committed_identity(tmp_path: Path) -> None:
    batch = _daily_batch(1)
    connector = FakeConnector()
    connector.errors = [TimeoutError("t1"), TimeoutError("t2")]
    result = _execute_result(
        tmp_path,
        connector,
        batch=batch,
        max_new_requests=1,
        max_attempts=3,
        classifier=lambda _e: "NETWORK",
    )
    assert result.new_requests_committed == 1
    assert len(connector.calls) == 3


def test_bounded_permanent_failure_not_committed(tmp_path: Path) -> None:
    batch = _daily_batch(1)
    connector = FakeConnector()
    connector.errors = [RuntimeError("perm")]
    with pytest.raises(M3BackfillError, match="TUSHARE_REQUEST_PERMANENT_FAILURE"):
        _execute_result(
            tmp_path,
            connector,
            batch=batch,
            max_new_requests=1,
            max_attempts=3,
            classifier=lambda _e: "PERMANENT",
        )
    assert not (tmp_path / "journal" / batch.requests[0].request_id / "receipt.json").exists()
