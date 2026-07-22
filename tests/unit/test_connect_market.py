import datetime as dt
from pathlib import Path

import pandera.errors
import polars as pl
import pytest

from quant.data.connect_market import (
    ConnectMarketPipeline,
    map_sse_events,
    map_sse_snapshot,
    map_szse_calendar,
    map_szse_events,
)
from quant.data.eligibility import (
    build_membership_intervals,
    eligible_symbols_on,
)
from quant.data.storage import CleanConnectEventStore, RawStore
from quant.domain import (
    ConnectCalendarSchema,
    ConnectEligibilityEventSchema,
    ConnectEligibilitySnapshotSchema,
)


def _sse_event_raw(
    *,
    adjust_types: list[str | None],
    codes: list[str] | None = None,
    dates: list[str] | None = None,
) -> pl.DataFrame:
    n = len(adjust_types)
    codes = codes or ["00700"] * n
    dates = dates or ["2026-07-10"] * n
    return pl.DataFrame(
        {
            "VALID_DATE": dates,
            "SECURITY_CODE": codes,
            "ADJUST_TYPE": adjust_types,
            "SECURITY_ABBR": ["腾讯控股"] * n,
            "ABBR_EN": ["TENCENT"] * n,
            "SECURITY_TYPE": ["股票"] * n,
            "FILE_DATE": ["2026-07-09"] * n,
        },
        schema_overrides={"ADJUST_TYPE": pl.String},
    )


def test_sse_snapshot_mapping_and_contract() -> None:
    raw = pl.DataFrame({
        "UPDATE_DATE": ["2026-07-10"], "SECURITY_CODE": ["00700"],
        "ABBR_CN": ["腾讯控股　"], "ABBR_EN": ["TENCENT"],
        "SECURITY_TYPE": ["股票"], "TRADE_FLAG": ["1"],
    })
    clean = map_sse_snapshot(raw)
    ConnectEligibilitySnapshotSchema.validate(clean)
    assert clean.row(0, named=True)["symbol"] == "00700.HK"


def test_sse_event_mapping_add_and_remove() -> None:
    raw = _sse_event_raw(
        adjust_types=["调进", "调出"],
        codes=["00700", "00941"],
        dates=["2026-07-10", "2026-07-11"],
    )
    clean = map_sse_events(raw)
    ConnectEligibilityEventSchema.validate(clean)
    assert clean.get_column("action").to_list() == ["ADD", "REMOVE"]
    assert clean.get_column("symbol").to_list() == ["00700.HK", "00941.HK"]


def test_sse_event_mapping_strips_whitespace() -> None:
    raw = _sse_event_raw(adjust_types=[" 调进 ", "\t调出\n"])
    clean = map_sse_events(raw)
    assert clean.get_column("action").to_list() == ["ADD", "REMOVE"]


def test_sse_event_mapping_mixed_legal_batch() -> None:
    raw = _sse_event_raw(
        adjust_types=["调进", "调出", " 调进", "调出 "],
        codes=["00700", "00941", "00388", "01299"],
        dates=["2026-07-10", "2026-07-11", "2026-07-12", "2026-07-13"],
    )
    clean = map_sse_events(raw)
    ConnectEligibilityEventSchema.validate(clean)
    assert clean.get_column("action").to_list() == [
        "ADD", "REMOVE", "ADD", "REMOVE",
    ]


@pytest.mark.parametrize(
    "invalid",
    [None, "", "01", "02", "ADD", "REMOVE", "调入", "未知"],
)
def test_sse_event_mapping_rejects_invalid_adjust_type(invalid: str | None) -> None:
    raw = _sse_event_raw(adjust_types=[invalid])
    with pytest.raises(ValueError, match="^SSE_EVENT_ADJUST_TYPE_INVALID$"):
        map_sse_events(raw)


def test_sse_event_mapping_rejects_legacy_01_even_in_mixed_batch() -> None:
    raw = _sse_event_raw(
        adjust_types=["调进", "01"],
        codes=["00700", "00941"],
        dates=["2026-07-10", "2026-07-11"],
    )
    with pytest.raises(ValueError, match="^SSE_EVENT_ADJUST_TYPE_INVALID$"):
        map_sse_events(raw)


def test_sse_event_state_machine_add_remove_readd_via_mapper() -> None:
    """当前成员经调出再调进；另证经调进后调出再调进；均须走 mapper，不得绕过。"""
    baseline = pl.DataFrame({
        "route": ["SH_CONNECT"],
        "snapshot_date": [dt.date(2026, 1, 1)],
        "symbol": ["00700.HK"],
        "name_cn": ["腾讯控股"],
        "name_en": ["TENCENT"],
        "security_type": ["STOCK"],
        "buy_eligible": [True],
        "source": ["sse"],
    })
    raw = _sse_event_raw(
        adjust_types=["调出", "调进", "调进", "调出", "调进"],
        codes=["00700", "00700", "00941", "00941", "00941"],
        dates=[
            "2026-01-03",
            "2026-01-06",
            "2026-01-02",
            "2026-01-04",
            "2026-01-07",
        ],
    )
    mapped = map_sse_events(raw)
    assert mapped.sort("effective_date", "symbol").get_column("action").to_list() == [
        "ADD",
        "REMOVE",
        "REMOVE",
        "ADD",
        "ADD",
    ]
    assert mapped.get_column("action").to_list() == [
        "REMOVE",
        "ADD",
        "ADD",
        "REMOVE",
        "ADD",
    ]

    intervals = build_membership_intervals(baseline, mapped, route="SH_CONNECT")
    assert eligible_symbols_on(
        intervals, route="SH_CONNECT", as_of=dt.date(2026, 1, 1)
    ) == ["00700.HK"]
    assert eligible_symbols_on(
        intervals, route="SH_CONNECT", as_of=dt.date(2026, 1, 3)
    ) == ["00941.HK"]
    assert eligible_symbols_on(
        intervals, route="SH_CONNECT", as_of=dt.date(2026, 1, 5)
    ) == []
    assert eligible_symbols_on(
        intervals, route="SH_CONNECT", as_of=dt.date(2026, 1, 7)
    ) == ["00700.HK", "00941.HK"]


def test_szse_calendar_mapping() -> None:
    raw = pl.DataFrame({
        "jyrq": ["2026-07-01", "2026-07-02", "2026-12-24"],
        "jybz": ["全日休市", "不休市", "下午休市"],
        "jjrmc": ["香港特别行政区成立纪念日（港）", None, "圣诞节"],
        "zrxh": ["3", "4", "4"],
    })
    clean = map_szse_calendar(raw)
    ConnectCalendarSchema.validate(clean)
    assert clean.get_column("is_open").to_list() == [False, True, True]
    assert clean.get_column("is_half_day").to_list() == [False, False, True]


def test_szse_event_mapping_uses_official_effective_date_field() -> None:
    raw = pl.DataFrame({
        "zqdm": ["00700"], "zqjc": ["腾讯控股"], "zqywjc": ["TENCENT"],
        "tznr": ["调入"], "sxrq": ["2026-07-10"], "_snapshot_date": [None],
    })
    clean = map_szse_events(raw)
    ConnectEligibilityEventSchema.validate(clean)
    assert clean.row(0, named=True)["effective_date"] == dt.date(2026, 7, 10)


def test_duplicate_snapshot_key_rejected() -> None:
    row = pl.DataFrame({
        "route": ["SH_CONNECT"], "snapshot_date": [dt.date(2026, 7, 10)],
        "symbol": ["00700.HK"], "name_cn": ["腾讯控股"], "name_en": ["TENCENT"],
        "security_type": ["STOCK"], "buy_eligible": [True], "source": ["sse"],
    })
    with pytest.raises(pandera.errors.SchemaError):
        ConnectEligibilitySnapshotSchema.validate(pl.concat([row, row]))


class _FakeSseEventsConnector:
    source = "sse"
    route = "SH_CONNECT"

    def __init__(self, frame: pl.DataFrame) -> None:
        self._frame = frame
        self.fetch_count = 0

    def fetch_eligibility_events(self) -> pl.DataFrame:
        self.fetch_count += 1
        return self._frame


class _RecordingEventStore:
    def __init__(self, inner: CleanConnectEventStore) -> None:
        self.inner = inner
        self.calls: list[str] = []

    def upsert(self, frame: pl.DataFrame) -> int:
        self.calls.append("upsert")
        return self.inner.upsert(frame)

    def replace_route(self, frame: pl.DataFrame) -> int:
        self.calls.append("replace_route")
        return self.inner.replace_route(frame)


def test_update_events_default_upsert_keeps_old_wrong_action(tmp_path: Path) -> None:
    store = CleanConnectEventStore(tmp_path / "clean")
    stale = pl.DataFrame({
        "route": ["SH_CONNECT"],
        "effective_date": [dt.date(2026, 7, 10)],
        "symbol": ["00700.HK"],
        "action": ["REMOVE"],
        "name_cn": ["腾讯控股"],
        "name_en": ["TENCENT"],
        "security_type": ["STOCK"],
        "published_date": [dt.date(2026, 7, 9)],
        "source": ["sse"],
    })
    store.upsert(stale)
    recorder = _RecordingEventStore(store)
    raw = _sse_event_raw(adjust_types=["调进"], codes=["00700"], dates=["2026-07-10"])
    pipeline = ConnectMarketPipeline(
        connector=_FakeSseEventsConnector(raw),
        raw_store=RawStore(tmp_path / "raw"),
        clean_root=recorder,
    )
    pipeline.update_events()
    assert recorder.calls == ["upsert"]
    written = pl.read_parquet(tmp_path / "clean" / "route=SH_CONNECT" / "data.parquet")
    assert sorted(written.get_column("action").to_list()) == ["ADD", "REMOVE"]


def test_update_events_replace_clean_true_uses_replace_route(tmp_path: Path) -> None:
    store = CleanConnectEventStore(tmp_path / "clean")
    stale = pl.DataFrame({
        "route": ["SH_CONNECT"],
        "effective_date": [dt.date(2026, 7, 10)],
        "symbol": ["00700.HK"],
        "action": ["REMOVE"],
        "name_cn": ["腾讯控股"],
        "name_en": ["TENCENT"],
        "security_type": ["STOCK"],
        "published_date": [dt.date(2026, 7, 9)],
        "source": ["sse"],
    })
    store.upsert(stale)
    recorder = _RecordingEventStore(store)
    raw = _sse_event_raw(adjust_types=["调进"], codes=["00700"], dates=["2026-07-10"])
    pipeline = ConnectMarketPipeline(
        connector=_FakeSseEventsConnector(raw),
        raw_store=RawStore(tmp_path / "raw"),
        clean_root=recorder,
    )
    result = pipeline.update_events(replace_clean=True)
    assert recorder.calls == ["replace_route"]
    assert result.clean_rows == 1
    written = pl.read_parquet(tmp_path / "clean" / "route=SH_CONNECT" / "data.parquet")
    assert written.get_column("action").to_list() == ["ADD"]
    assert written.height == 1


def test_update_events_replace_clean_type_boundary(tmp_path: Path) -> None:
    pipeline = ConnectMarketPipeline(
        connector=_FakeSseEventsConnector(_sse_event_raw(adjust_types=["调进"])),
        raw_store=RawStore(tmp_path / "raw"),
        clean_root=CleanConnectEventStore(tmp_path / "clean"),
    )
    pipeline.update_events(replace_clean=True)
    with pytest.raises(TypeError, match="严格 bool"):
        pipeline.update_events(replace_clean=1)  # type: ignore[arg-type]


def test_update_events_mapper_failure_keeps_raw_and_old_clean(tmp_path: Path) -> None:
    store = CleanConnectEventStore(tmp_path / "clean")
    stale = pl.DataFrame({
        "route": ["SH_CONNECT"],
        "effective_date": [dt.date(2026, 7, 10)],
        "symbol": ["00700.HK"],
        "action": ["REMOVE"],
        "name_cn": ["腾讯控股"],
        "name_en": ["TENCENT"],
        "security_type": ["STOCK"],
        "published_date": [dt.date(2026, 7, 9)],
        "source": ["sse"],
    })
    store.upsert(stale)
    clean_path = tmp_path / "clean" / "route=SH_CONNECT" / "data.parquet"
    before = clean_path.read_bytes()
    bad_raw = _sse_event_raw(adjust_types=["调进", "未知"], codes=["00700", "00941"])
    pipeline = ConnectMarketPipeline(
        connector=_FakeSseEventsConnector(bad_raw),
        raw_store=RawStore(tmp_path / "raw"),
        clean_root=store,
    )
    with pytest.raises(ValueError, match="^SSE_EVENT_ADJUST_TYPE_INVALID$"):
        pipeline.update_events(replace_clean=True)
    assert clean_path.read_bytes() == before
    raw_files = list((tmp_path / "raw").rglob("*.parquet"))
    assert raw_files, "mapper 失败后 raw 应已保留"

