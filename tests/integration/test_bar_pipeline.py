"""bar_1d raw→clean→DuckDB 离线纵切测试。"""

import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data import (
    AkshareBarMapper,
    BarQuery,
    BarUpdatePipeline,
    CleanBarStore,
    CleanAdjustmentFactorStore,
    RawStore,
)
from quant.data.adjustments import AdjustmentFactorCoverageError
from quant.data.base import BaseConnector
from quant.data.quality import QualityGateError
from quant.data.mappers import BaostockAdjustmentFactorMapper


class FixtureConnector(BaseConnector):
    """不依赖供应商 SDK 的换源演练连接器。"""

    source = "fixture"

    def __init__(self, bars: pl.DataFrame) -> None:
        self.bars = bars

    def fetch_instruments(self, market: str) -> pl.DataFrame:
        raise NotImplementedError

    def fetch_trade_calendar(
        self, market: str, start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        raise NotImplementedError

    def fetch_bar_1d(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        return self.bars.clone()

    def fetch_corporate_actions(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        raise NotImplementedError

    def fetch_adjust_factors(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        # 首日基线须覆盖最早 bar（2026-07-09），不得用晚于首 bar 的因子冒充合法覆盖
        return pl.DataFrame(
            {
                "_request_symbol": [symbol for symbol in symbols],
                "dividOperateDate": ["2026-07-09"] * len(symbols),
                "backAdjustFactor": ["2.0"] * len(symbols),
            }
        )


class FixtureMapper(AkshareBarMapper):
    source = "fixture"


class FixtureFactorMapper(BaostockAdjustmentFactorMapper):
    source = "fixture"


class EmptyFactorConnector(FixtureConnector):
    def fetch_adjust_factors(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        return pl.DataFrame(
            schema={
                "_request_symbol": pl.String,
                "dividOperateDate": pl.String,
                "backAdjustFactor": pl.String,
            }
        )


class CustomFactorConnector(FixtureConnector):
    """按证券返回可控 effective_date / 因子值的离线夹具。"""

    def __init__(
        self,
        bars: pl.DataFrame,
        factor_rows: dict[str, list[tuple[str, str]]],
    ) -> None:
        super().__init__(bars)
        self.factor_rows = factor_rows

    def fetch_adjust_factors(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        request_symbols: list[str] = []
        dates: list[str] = []
        values: list[str] = []
        for symbol in symbols:
            for effective_date, factor in self.factor_rows.get(symbol, []):
                request_symbols.append(symbol)
                dates.append(effective_date)
                values.append(factor)
        return pl.DataFrame(
            {
                "_request_symbol": request_symbols,
                "dividOperateDate": dates,
                "backAdjustFactor": values,
            }
        )


class CountingCleanBarStore(CleanBarStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.upsert_calls = 0

    def upsert(self, frame: pl.DataFrame) -> int:
        self.upsert_calls += 1
        return super().upsert(frame)


class CountingCleanAdjustmentFactorStore(CleanAdjustmentFactorStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.upsert_calls = 0

    def upsert(self, frame: pl.DataFrame) -> int:
        self.upsert_calls += 1
        return super().upsert(frame)


def make_raw_bars(*, bad_ohlc: bool = False) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "_request_symbol": ["000001.SZ", "000001.SZ", "00700.HK", "00700.HK"],
            "日期": [
                dt.date(2026, 7, 9),
                dt.date(2026, 7, 10),
                dt.date(2026, 7, 9),
                dt.date(2026, 7, 10),
            ],
            "开盘": [10.0, 10.2, 400.0, 402.0],
            "最高": [10.5, 9.0 if bad_ohlc else 10.6, 405.0, 406.0],
            "最低": [9.8, 10.0, 398.0, 400.0],
            "收盘": [10.2, 10.4, 402.0, 404.0],
            "成交量": [1000, 1200, 2000, 2200],
            "成交额": [10200.0, 12480.0, 804000.0, 888800.0],
        }
    )


def build_pipeline(tmp_path: Path, raw: pl.DataFrame) -> BarUpdatePipeline:
    return BarUpdatePipeline(
        connector=FixtureConnector(raw),
        mapper=FixtureMapper(),
        raw_store=RawStore(tmp_path / "data" / "raw"),
        clean_store=CleanBarStore(tmp_path / "data" / "clean" / "bar_1d"),
        quality_root=tmp_path / "artifacts" / "data_quality" / "bar_1d",
    )


def test_pipeline_archives_raw_and_upserts_clean_idempotently(tmp_path: Path):
    pipeline = build_pipeline(tmp_path, make_raw_bars())
    fetched_at = dt.datetime(2026, 7, 11, 4, 0, tzinfo=dt.timezone.utc)

    first = pipeline.update(
        symbols=["000001.SZ", "00700.HK"],
        start=dt.date(2026, 7, 9),
        end=dt.date(2026, 7, 10),
        fetched_at=fetched_at,
    )
    second = pipeline.update(
        symbols=["000001.SZ", "00700.HK"],
        start=dt.date(2026, 7, 9),
        end=dt.date(2026, 7, 10),
        fetched_at=fetched_at,
    )

    assert first.raw_snapshot.data_path == second.raw_snapshot.data_path
    assert first.raw_snapshot.data_path.exists()
    metadata = json.loads(first.raw_snapshot.metadata_path.read_text(encoding="utf-8"))
    assert metadata["source"] == "fixture"
    assert metadata["rows"] == 4
    clean = pl.read_parquet(tmp_path / "data" / "clean" / "bar_1d" / "date=*" / "data.parquet")
    assert clean.height == 4
    assert first.quality_report.passed


def test_bad_batch_keeps_raw_but_does_not_write_clean(tmp_path: Path):
    pipeline = build_pipeline(tmp_path, make_raw_bars(bad_ohlc=True))

    with pytest.raises(QualityGateError) as error:
        pipeline.update(
            symbols=["000001.SZ", "00700.HK"],
            start=dt.date(2026, 7, 9),
            end=dt.date(2026, 7, 10),
        )

    assert error.value.report.invalid_ohlc_rows == 1
    assert list((tmp_path / "data" / "raw").rglob("*.parquet"))
    assert not list((tmp_path / "data" / "clean").rglob("*.parquet"))
    reports = list((tmp_path / "artifacts" / "data_quality").rglob("*.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text(encoding="utf-8"))["passed"] is False


def test_bad_bar_quality_keeps_factor_raw_but_skips_both_clean_stores(
    tmp_path: Path,
) -> None:
    """合法因子不能在 bar quality 失败时提前发布到 clean。"""
    bar_store = CountingCleanBarStore(tmp_path / "data" / "clean" / "bar_1d")
    factor_store = CountingCleanAdjustmentFactorStore(
        tmp_path / "data" / "clean" / "adjust_factor"
    )
    pipeline = BarUpdatePipeline(
        connector=FixtureConnector(make_raw_bars()),
        mapper=FixtureMapper(),
        raw_store=RawStore(tmp_path / "data" / "raw"),
        clean_store=bar_store,
        quality_root=tmp_path / "artifacts" / "data_quality" / "bar_1d",
        factor_mapper=FixtureFactorMapper(),
        factor_store=factor_store,
    )

    with pytest.raises(QualityGateError):
        pipeline.update(
            symbols=["000001.SZ", "00700.HK"],
            start=dt.date(2026, 7, 9),
            end=dt.date(2026, 7, 10),
            expected_dates={
                dt.date(2026, 7, 9),
                dt.date(2026, 7, 10),
                dt.date(2026, 7, 11),
            },
        )

    raw_tables = {
        path.parent.parent.name
        for path in (tmp_path / "data" / "raw" / "fixture").rglob("*.parquet")
    }
    assert raw_tables == {"bar_1d", "adjust_factor"}
    assert bar_store.upsert_calls == 0
    assert factor_store.upsert_calls == 0
    assert not list((tmp_path / "data" / "clean").rglob("*.parquet"))


def test_quality_report_write_failure_skips_both_clean_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """质量证据未持久化时不得继续发布 bar 或 factor clean。"""
    bar_store = CountingCleanBarStore(tmp_path / "data" / "clean" / "bar_1d")
    factor_store = CountingCleanAdjustmentFactorStore(
        tmp_path / "data" / "clean" / "adjust_factor"
    )
    pipeline = BarUpdatePipeline(
        connector=FixtureConnector(make_raw_bars()),
        mapper=FixtureMapper(),
        raw_store=RawStore(tmp_path / "data" / "raw"),
        clean_store=bar_store,
        quality_root=tmp_path / "artifacts" / "data_quality" / "bar_1d",
        factor_mapper=FixtureFactorMapper(),
        factor_store=factor_store,
    )

    def fail_report(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected quality report write failure")

    monkeypatch.setattr("quant.data.pipeline.write_quality_report", fail_report)
    with pytest.raises(OSError, match="injected quality report write failure"):
        pipeline.update(
            symbols=["000001.SZ", "00700.HK"],
            start=dt.date(2026, 7, 9),
            end=dt.date(2026, 7, 10),
        )

    assert list((tmp_path / "data" / "raw").rglob("*.parquet"))
    assert bar_store.upsert_calls == 0
    assert factor_store.upsert_calls == 0
    assert not list((tmp_path / "data" / "clean").rglob("*.parquet"))


def test_duckdb_returns_recent_observations_per_symbol(tmp_path: Path):
    pipeline = build_pipeline(tmp_path, make_raw_bars())
    pipeline.update(
        symbols=["000001.SZ", "00700.HK"],
        start=dt.date(2026, 7, 9),
        end=dt.date(2026, 7, 10),
    )

    result = BarQuery(tmp_path / "data" / "clean" / "bar_1d").recent(
        as_of=dt.date(2026, 7, 10), observations=1
    )

    assert result.height == 2
    assert set(result["trade_date"].to_list()) == {dt.date(2026, 7, 10)}


def test_duckdb_filters_recent_bars_by_point_in_time_universe(tmp_path: Path):
    pipeline = build_pipeline(tmp_path, make_raw_bars())
    pipeline.update(
        symbols=["000001.SZ", "00700.HK"],
        start=dt.date(2026, 7, 9),
        end=dt.date(2026, 7, 10),
    )
    membership_path = tmp_path / "membership.parquet"
    pl.DataFrame({
        "universe": ["SH_CONNECT"], "symbol": ["00700.HK"],
        "effective_from": [dt.date(2026, 7, 10)], "effective_to": [None],
    }).write_parquet(membership_path)
    result = BarQuery(tmp_path / "data/clean/bar_1d").recent_for_universe(
        membership_path=membership_path,
        universe="SH_CONNECT",
        as_of=dt.date(2026, 7, 10),
        source="fixture",
        observations=60,
    )
    assert result.get_column("symbol").unique().to_list() == ["00700.HK"]
    assert result.get_column("trade_date").to_list() == [
        dt.date(2026, 7, 9),
        dt.date(2026, 7, 10),
    ]


def test_pipeline_archives_and_applies_adjustment_factors(tmp_path: Path):
    pipeline = BarUpdatePipeline(
        connector=FixtureConnector(make_raw_bars()),
        mapper=FixtureMapper(),
        raw_store=RawStore(tmp_path / "data" / "raw"),
        clean_store=CleanBarStore(tmp_path / "data" / "clean" / "bar_1d"),
        quality_root=tmp_path / "artifacts" / "data_quality" / "bar_1d",
        factor_mapper=FixtureFactorMapper(),
        factor_store=CleanAdjustmentFactorStore(
            tmp_path / "data" / "clean" / "adjust_factor"
        ),
    )

    result = pipeline.update(
        symbols=["000001.SZ", "00700.HK"],
        start=dt.date(2026, 7, 9),
        end=dt.date(2026, 7, 10),
    )

    assert result.factor_snapshot is not None
    assert result.factor_snapshot.data_path.exists()
    assert result.factor_rows == 2
    bars = pl.read_parquet(
        tmp_path / "data" / "clean" / "bar_1d" / "date=2026-07-10" / "data.parquet"
    )
    assert bars["adj_factor"].to_list() == [2.0, 2.0]


def test_requested_adjustment_factors_must_cover_every_symbol(tmp_path: Path):
    bar_store = CountingCleanBarStore(tmp_path / "data" / "clean" / "bar_1d")
    factor_store = CountingCleanAdjustmentFactorStore(
        tmp_path / "data" / "clean" / "adjust_factor"
    )
    pipeline = BarUpdatePipeline(
        connector=EmptyFactorConnector(make_raw_bars()),
        mapper=FixtureMapper(),
        raw_store=RawStore(tmp_path / "data" / "raw"),
        clean_store=bar_store,
        quality_root=tmp_path / "artifacts" / "data_quality" / "bar_1d",
        factor_mapper=FixtureFactorMapper(),
        factor_store=factor_store,
    )
    with pytest.raises(AdjustmentFactorCoverageError) as err:
        pipeline.update(
            symbols=["000001.SZ", "00700.HK"],
            start=dt.date(2026, 7, 9),
            end=dt.date(2026, 7, 10),
        )
    assert {i.reason for i in err.value.issues} == {"missing_symbol"}
    assert {i.symbol for i in err.value.issues} == {"000001.SZ", "00700.HK"}
    raw_parquets = list((tmp_path / "data" / "raw" / "fixture").rglob("*.parquet"))
    assert len(raw_parquets) >= 2  # bar_1d + adjust_factor raw 均保留
    assert bar_store.upsert_calls == 0
    assert factor_store.upsert_calls == 0
    assert not list((tmp_path / "data" / "clean" / "bar_1d").rglob("*.parquet"))
    assert not list((tmp_path / "data" / "clean" / "adjust_factor").rglob("*.parquet"))


def test_late_baseline_on_second_symbol_keeps_raw_and_skips_both_clean_stores(
    tmp_path: Path,
):
    """两证券中第二个首 factor 晚于首 bar：整体失败；两类 raw 保留；两 clean 写次数为 0。"""
    bar_store = CountingCleanBarStore(tmp_path / "data" / "clean" / "bar_1d")
    factor_store = CountingCleanAdjustmentFactorStore(
        tmp_path / "data" / "clean" / "adjust_factor"
    )
    pipeline = BarUpdatePipeline(
        connector=CustomFactorConnector(
            make_raw_bars(),
            {
                "000001.SZ": [("2026-07-09", "1.1")],
                "00700.HK": [("2026-07-10", "2.0")],  # 晚一日
            },
        ),
        mapper=FixtureMapper(),
        raw_store=RawStore(tmp_path / "data" / "raw"),
        clean_store=bar_store,
        quality_root=tmp_path / "artifacts" / "data_quality" / "bar_1d",
        factor_mapper=FixtureFactorMapper(),
        factor_store=factor_store,
    )
    with pytest.raises(AdjustmentFactorCoverageError) as err:
        pipeline.update(
            symbols=["000001.SZ", "00700.HK"],
            start=dt.date(2026, 7, 9),
            end=dt.date(2026, 7, 10),
        )
    assert [i.symbol for i in err.value.issues] == ["00700.HK"]
    assert err.value.issues[0].reason == "no_baseline_on_or_before_first_bar"
    raw_tables = {
        path.parent.parent.name
        for path in (tmp_path / "data" / "raw" / "fixture").rglob("*.parquet")
    }
    assert raw_tables == {"bar_1d", "adjust_factor"}
    assert bar_store.upsert_calls == 0
    assert factor_store.upsert_calls == 0
    assert not list((tmp_path / "data" / "clean").rglob("*.parquet"))


def test_explicit_no_factor_path_unaffected_by_coverage_gate(tmp_path: Path):
    """未启用 factors 时同样 bars 保持显式不复权行为，不被新门禁误伤。"""
    pipeline = build_pipeline(tmp_path, make_raw_bars())
    result = pipeline.update(
        symbols=["000001.SZ", "00700.HK"],
        start=dt.date(2026, 7, 9),
        end=dt.date(2026, 7, 10),
    )
    assert result.factor_snapshot is None
    assert result.factor_rows == 0
    bars = pl.read_parquet(
        tmp_path / "data" / "clean" / "bar_1d" / "date=*" / "data.parquet"
    )
    assert set(bars["adj_factor"].to_list()) == {1.0}
