"""M1 daily-run receipt, replay and drift tests."""

from __future__ import annotations

import datetime as dt
import json
import os
from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from quant.data._journal_lock import hold_journal_writer_lock
from quant.data.base import BaseConnector
from quant.data.daily_run import (
    M1DailyRunError,
    build_daily_run_spec,
    execute_daily_run,
    verify_daily_receipt,
)
from quant.data.mappers import AkshareBarMapper, BaostockAdjustmentFactorMapper
from quant.data.pipeline import BarUpdatePipeline, BarUpdateResult
from quant.data.storage import CleanAdjustmentFactorStore, CleanBarStore, RawStore

DAY = dt.date(2026, 7, 10)


class CountingConnector(BaseConnector):
    source = "akshare"

    def __init__(self) -> None:
        self.bar_calls = 0
        self.factor_calls = 0

    def fetch_instruments(self, market: str) -> pl.DataFrame:
        raise NotImplementedError

    def fetch_trade_calendar(
        self, market: str, start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        raise NotImplementedError

    def fetch_bar_1d(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        self.bar_calls += 1
        return _raw_bars(symbols)

    def fetch_corporate_actions(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        raise NotImplementedError

    def fetch_adjust_factors(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        self.factor_calls += 1
        return pl.DataFrame(
            {
                "_request_symbol": symbols,
                "dividOperateDate": [DAY.isoformat()] * len(symbols),
                "backAdjustFactor": ["2.0"] * len(symbols),
            }
        )


class TestBarMapper(AkshareBarMapper):
    source = "akshare"


class TestFactorMapper(BaostockAdjustmentFactorMapper):
    source = "akshare"


def test_completed_spec_replays_without_update_call(tmp_path: Path) -> None:
    data_root, artifact_root = _roots(tmp_path)
    spec = _spec(data_root, symbols=["000001.SZ", "600000.SH", "000001.SZ"])
    connector = CountingConnector()
    update = _pipeline_update(
        connector=connector,
        spec=spec,
        data_root=data_root,
        artifact_root=artifact_root,
    )

    first = execute_daily_run(
        spec=spec, data_root=data_root, artifact_root=artifact_root, update=update
    )
    second = execute_daily_run(
        spec=spec,
        data_root=data_root,
        artifact_root=artifact_root,
        update=lambda: pytest.fail("completed receipt must not execute update"),
    )

    assert first.status == "SUCCESS"
    assert second.status == "ALREADY_COMPLETE"
    assert connector.bar_calls == 1
    assert connector.factor_calls == 0
    assert first.run_id == second.run_id == spec.run_id


def test_manifest_only_crash_state_publishes_receipt_without_update(tmp_path: Path) -> None:
    data_root, artifact_root = _roots(tmp_path)
    spec = _spec(data_root)
    connector = CountingConnector()
    execute_daily_run(
        spec=spec,
        data_root=data_root,
        artifact_root=artifact_root,
        update=_pipeline_update(
            connector=connector,
            spec=spec,
            data_root=data_root,
            artifact_root=artifact_root,
        ),
    )
    receipt = data_root / "run_state" / "m1_daily" / spec.run_id / "receipt.json"
    receipt.unlink()

    recovered = execute_daily_run(
        spec=spec,
        data_root=data_root,
        artifact_root=artifact_root,
        update=lambda: pytest.fail("valid manifest recovery must not execute update"),
    )

    assert recovered.status == "SUCCESS"
    assert connector.bar_calls == 1
    assert receipt.is_file()


def test_irrelevant_clean_append_is_allowed_but_target_change_is_drift(
    tmp_path: Path,
) -> None:
    data_root, artifact_root = _roots(tmp_path)
    spec = _spec(data_root)
    connector = CountingConnector()
    execute_daily_run(
        spec=spec,
        data_root=data_root,
        artifact_root=artifact_root,
        update=_pipeline_update(
            connector=connector,
            spec=spec,
            data_root=data_root,
            artifact_root=artifact_root,
        ),
    )
    clean_path = data_root / "clean" / "bar_1d" / f"date={DAY}" / "data.parquet"
    clean = pl.read_parquet(clean_path)
    irrelevant = clean.head(1).with_columns(pl.lit("000002.SZ").alias("symbol"))
    pl.concat([clean, irrelevant]).sort(["symbol", "trade_date", "source"]).write_parquet(
        clean_path
    )
    assert verify_daily_receipt(
        spec=spec, data_root=data_root, artifact_root=artifact_root
    ).status == "ALREADY_COMPLETE"

    changed = pl.read_parquet(clean_path).with_columns(
        pl.when(pl.col("symbol") == "000001.SZ")
        .then(pl.col("close") + 1.0)
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when(pl.col("symbol") == "000001.SZ")
        .then(pl.col("high") + 1.0)
        .otherwise(pl.col("high"))
        .alias("high"),
    )
    changed.write_parquet(clean_path)
    with pytest.raises(M1DailyRunError, match="M1_DAILY_CLEAN_DRIFT"):
        verify_daily_receipt(spec=spec, data_root=data_root, artifact_root=artifact_root)


@pytest.mark.parametrize("artifact", ["intent", "manifest", "receipt", "raw", "quality"])
def test_completed_artifact_tamper_fails_without_update(
    tmp_path: Path, artifact: str
) -> None:
    data_root, artifact_root = _roots(tmp_path)
    spec = _spec(data_root)
    connector = CountingConnector()
    execute_daily_run(
        spec=spec,
        data_root=data_root,
        artifact_root=artifact_root,
        update=_pipeline_update(
            connector=connector,
            spec=spec,
            data_root=data_root,
            artifact_root=artifact_root,
        ),
    )
    run_dir = data_root / "run_state" / "m1_daily" / spec.run_id
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    targets = {
        "intent": run_dir / "intent.json",
        "manifest": run_dir / "manifest.json",
        "receipt": run_dir / "receipt.json",
        "raw": data_root / Path(manifest["bar_raw"]["metadata_selector"]),
        "quality": artifact_root / Path(manifest["quality_selector"]),
    }
    targets[artifact].write_bytes(b"{}")

    with pytest.raises(M1DailyRunError):
        execute_daily_run(
            spec=spec,
            data_root=data_root,
            artifact_root=artifact_root,
            update=lambda: pytest.fail("tampered completed run must not execute update"),
        )
    assert connector.bar_calls == 1


def test_run_id_canonicalizes_symbols_and_binds_semantics(tmp_path: Path) -> None:
    data_root, _ = _roots(tmp_path)
    first = _spec(
        data_root,
        symbols=["600000.SH", "000001.SZ", "600000.SH"],
        use_adjustment_factors=True,
    )
    reordered = _spec(
        data_root,
        symbols=["000001.SZ", "600000.SH"],
        use_adjustment_factors=True,
    )
    no_factor = _spec(
        data_root,
        symbols=["000001.SZ", "600000.SH"],
        use_adjustment_factors=False,
    )
    other_source = build_daily_run_spec(
        data_root=data_root,
        session_date=DAY,
        source="baostock",
        symbols=["000001.SZ", "600000.SH"],
        use_adjustment_factors=True,
    )

    assert first.run_id == reordered.run_id
    assert first.run_id != no_factor.run_id
    assert first.run_id != other_source.run_id
    assert first.symbols == ("000001.SZ", "600000.SH")


def test_factor_projection_ignores_future_event_but_detects_bound_history_drift(
    tmp_path: Path,
) -> None:
    data_root, artifact_root = _roots(tmp_path)
    spec = _spec(data_root, use_adjustment_factors=True)
    connector = CountingConnector()
    execute_daily_run(
        spec=spec,
        data_root=data_root,
        artifact_root=artifact_root,
        update=_pipeline_update(
            connector=connector,
            spec=spec,
            data_root=data_root,
            artifact_root=artifact_root,
        ),
    )
    factor_path = data_root / "clean" / "adjust_factor" / "source=akshare" / "data.parquet"
    factors = pl.read_parquet(factor_path)
    future = factors.head(1).with_columns(
        pl.lit(DAY + dt.timedelta(days=1)).alias("effective_date"),
        pl.lit(3.0).alias("adj_factor"),
    )
    pl.concat([factors, future]).sort(["symbol", "effective_date"]).write_parquet(factor_path)
    assert verify_daily_receipt(
        spec=spec, data_root=data_root, artifact_root=artifact_root
    ).status == "ALREADY_COMPLETE"

    changed = pl.read_parquet(factor_path).with_columns(
        pl.when(pl.col("effective_date") <= DAY)
        .then(pl.col("adj_factor") + 0.25)
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    changed.write_parquet(factor_path)
    with pytest.raises(M1DailyRunError, match="M1_DAILY_CLEAN_DRIFT"):
        verify_daily_receipt(spec=spec, data_root=data_root, artifact_root=artifact_root)


def test_calendar_drift_rejects_replay_before_update(tmp_path: Path) -> None:
    data_root, artifact_root = _roots(tmp_path)
    spec = _spec(data_root)
    connector = CountingConnector()
    execute_daily_run(
        spec=spec,
        data_root=data_root,
        artifact_root=artifact_root,
        update=_pipeline_update(
            connector=connector,
            spec=spec,
            data_root=data_root,
            artifact_root=artifact_root,
        ),
    )
    calendar_path = data_root / "clean" / "trade_calendar" / "market=SZ" / "data.parquet"
    pl.read_parquet(calendar_path).with_columns(
        pl.lit(True).alias("is_half_day")
    ).write_parquet(calendar_path)
    with pytest.raises(M1DailyRunError, match="M1_DAILY_CALENDAR_INVALID"):
        execute_daily_run(
            spec=spec,
            data_root=data_root,
            artifact_root=artifact_root,
            update=lambda: pytest.fail("calendar drift must fail before update"),
        )


def test_update_failure_leaves_only_intent_and_sanitized_error(tmp_path: Path) -> None:
    data_root, artifact_root = _roots(tmp_path)
    spec = _spec(data_root)

    def fail() -> BarUpdateResult:
        raise RuntimeError("secret C:\\private /home/private")

    with pytest.raises(M1DailyRunError, match="^M1_DAILY_UPDATE_FAILED$"):
        execute_daily_run(
            spec=spec,
            data_root=data_root,
            artifact_root=artifact_root,
            update=fail,
        )
    run_dir = data_root / "run_state" / "m1_daily" / spec.run_id
    assert sorted(path.name for path in run_dir.iterdir()) == ["intent.json"]


@pytest.mark.parametrize(
    "payload",
    [
        b"\xef\xbb\xbf{}",
        b'{"run_id":"x","run_id":"y"}',
        b"{}\r\n",
    ],
)
def test_noncanonical_receipt_is_rejected_without_update(
    tmp_path: Path, payload: bytes
) -> None:
    data_root, artifact_root = _roots(tmp_path)
    spec = _spec(data_root)
    connector = CountingConnector()
    execute_daily_run(
        spec=spec,
        data_root=data_root,
        artifact_root=artifact_root,
        update=_pipeline_update(
            connector=connector,
            spec=spec,
            data_root=data_root,
            artifact_root=artifact_root,
        ),
    )
    receipt = data_root / "run_state" / "m1_daily" / spec.run_id / "receipt.json"
    receipt.write_bytes(payload)
    with pytest.raises(M1DailyRunError, match="M1_DAILY_RECEIPT_INVALID"):
        execute_daily_run(
            spec=spec,
            data_root=data_root,
            artifact_root=artifact_root,
            update=lambda: pytest.fail("invalid receipt must not execute update"),
        )
    assert connector.bar_calls == 1


def test_hardlink_alias_of_receipt_is_rejected(tmp_path: Path) -> None:
    data_root, artifact_root = _roots(tmp_path)
    spec = _spec(data_root)
    connector = CountingConnector()
    execute_daily_run(
        spec=spec,
        data_root=data_root,
        artifact_root=artifact_root,
        update=_pipeline_update(
            connector=connector,
            spec=spec,
            data_root=data_root,
            artifact_root=artifact_root,
        ),
    )
    receipt = data_root / "run_state" / "m1_daily" / spec.run_id / "receipt.json"
    alias = tmp_path / "receipt-alias.json"
    os.link(receipt, alias)
    with pytest.raises(M1DailyRunError, match="M1_DAILY_RECEIPT_INVALID"):
        verify_daily_receipt(spec=spec, data_root=data_root, artifact_root=artifact_root)


def test_closed_or_missing_calendar_fails_before_any_update(tmp_path: Path) -> None:
    data_root, _ = _roots(tmp_path, is_open=False)
    with pytest.raises(M1DailyRunError, match="M1_DAILY_CALENDAR_INVALID"):
        _spec(data_root)


def test_second_writer_gets_stable_error_without_update(tmp_path: Path) -> None:
    data_root, artifact_root = _roots(tmp_path)
    spec = _spec(data_root)
    journal_root = (data_root / "run_state" / "m1_daily").resolve()
    journal_root.mkdir(parents=True)
    with hold_journal_writer_lock(journal_root=journal_root):
        with pytest.raises(M1DailyRunError, match="M1_DAILY_WRITER_ACTIVE"):
            execute_daily_run(
                spec=spec,
                data_root=data_root,
                artifact_root=artifact_root,
                update=lambda: pytest.fail("contended writer must not execute update"),
            )


def _roots(tmp_path: Path, *, is_open: bool = True) -> tuple[Path, Path]:
    data_root = tmp_path / "data"
    artifact_root = tmp_path / "artifacts"
    for market in ("SH", "SZ"):
        calendar_path = (
            data_root / "clean" / "trade_calendar" / f"market={market}" / "data.parquet"
        )
        calendar_path.parent.mkdir(parents=True)
        pl.DataFrame(
            {
                "market": [market],
                "date": [DAY],
                "is_open": [is_open],
                "is_connect_open": [False],
                "is_half_day": [False],
            }
        ).write_parquet(calendar_path)
    return data_root, artifact_root


def _spec(
    data_root: Path,
    *,
    symbols: list[str] | None = None,
    use_adjustment_factors: bool = False,
):
    return build_daily_run_spec(
        data_root=data_root,
        session_date=DAY,
        source="akshare",
        symbols=symbols or ["000001.SZ"],
        use_adjustment_factors=use_adjustment_factors,
    )


def _pipeline_update(
    *,
    connector: CountingConnector,
    spec,
    data_root: Path,
    artifact_root: Path,
) -> Callable[[], BarUpdateResult]:
    def run() -> BarUpdateResult:
        factor_mapper = TestFactorMapper() if spec.use_adjustment_factors else None
        factor_store = (
            CleanAdjustmentFactorStore(data_root / "clean" / "adjust_factor")
            if spec.use_adjustment_factors
            else None
        )
        pipeline = BarUpdatePipeline(
            connector=connector,
            mapper=TestBarMapper(),
            raw_store=RawStore(data_root / "raw"),
            clean_store=CleanBarStore(data_root / "clean" / "bar_1d"),
            quality_root=artifact_root / "data_quality" / "bar_1d",
            factor_mapper=factor_mapper,
            factor_store=factor_store,
        )
        return pipeline.update(
            symbols=list(spec.symbols),
            start=spec.session_date,
            end=spec.session_date,
            expected_dates={spec.session_date},
        )

    return run


def _raw_bars(symbols: list[str]) -> pl.DataFrame:
    count = len(symbols)
    return pl.DataFrame(
        {
            "_request_symbol": symbols,
            "日期": [DAY] * count,
            "开盘": [10.0] * count,
            "最高": [11.0] * count,
            "最低": [9.0] * count,
            "收盘": [10.5] * count,
            "成交量": [1000] * count,
            "成交额": [10500.0] * count,
        }
    )
