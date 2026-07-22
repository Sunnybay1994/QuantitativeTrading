import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.data.mappers import HkexEtpInstrumentMapper
from quant.data.pipeline import HkexEtpInstrumentUpdatePipeline
from quant.data.storage import CleanInstrumentStore, RawStore
from quant.domain import InstrumentSchema

DAY = dt.date(2026, 7, 10)
TARGETS = ("02800.HK", "03489.HK")


def _epoch(day: dt.date) -> int:
    return int(dt.datetime.combine(day, dt.time(), tzinfo=dt.timezone.utc).timestamp() * 1000)


def _row(
    symbol: str,
    *,
    trade_date: dt.date = DAY,
    list_date: dt.date = dt.date(1999, 11, 12),
    lot: object = 500,
    currency: str = "HKD",
    category: str = "ETFs",
    name: str = "ETF",
) -> dict[str, object]:
    return {
        "_request_symbol": symbol,
        "trade_date": _epoch(trade_date),
        "first_trade_date": _epoch(list_date),
        "lot_size": lot,
        "name": name,
        "currency": currency,
        "product_sub_category": category,
    }


def _raw(*rows: dict[str, object]) -> pl.DataFrame:
    return pl.from_dicts(rows, infer_schema_length=None, strict=False)


def test_mapper_selects_latest_not_after_as_of_and_validates_schema() -> None:
    raw = _raw(
        _row("02800.HK", trade_date=dt.date(2026, 7, 9), lot=400),
        _row("02800.HK", lot=500, name="TRACKER FUND"),
        _row("02800.HK", trade_date=dt.date(2026, 7, 11), lot=999),
        _row(
            "03489.HK",
            list_date=dt.date(2025, 9, 26),
            lot=100,
            name="EFUND AI",
        ),
    )
    clean = HkexEtpInstrumentMapper(target_symbols=TARGETS, as_of=DAY).map(raw)
    InstrumentSchema.validate(clean)
    assert clean.get_column("symbol").to_list() == list(TARGETS)
    assert clean.get_column("board_lot").to_list() == [500, 100]
    assert clean.get_column("instrument_type").to_list() == ["ETF", "ETF"]


def test_identical_latest_duplicates_collapse_but_conflict_fails() -> None:
    base = _row("02800.HK")
    mapper = HkexEtpInstrumentMapper(target_symbols=("02800.HK",), as_of=DAY)
    assert mapper.map(_raw(base, dict(base))).height == 1
    conflict = dict(base)
    conflict["lot_size"] = 100
    with pytest.raises(ValueError, match="^HKEX_ETP_IDENTITY_CONFLICT$"):
        mapper.map(_raw(base, conflict))


@pytest.mark.parametrize(
    "row, code",
    [
        (_row("02800.HK", trade_date=dt.date(2026, 7, 11)), "HKEX_ETP_COVERAGE_INCOMPLETE"),
        (_row("02800.HK", currency="CNY"), "HKEX_ETP_ROW_INVALID"),
        (_row("02800.HK", category="L&I Products"), "HKEX_ETP_ROW_INVALID"),
        (_row("02800.HK", lot=0), "HKEX_ETP_ROW_INVALID"),
        (_row("02800.HK", lot=100.0), "HKEX_ETP_ROW_INVALID"),
    ],
)
def test_mapper_rejects_incomplete_or_invalid_rows(
    row: dict[str, object], code: str
) -> None:
    mapper = HkexEtpInstrumentMapper(target_symbols=("02800.HK",), as_of=DAY)
    with pytest.raises(ValueError, match=f"^{code}$"):
        mapper.map(_raw(row))


class _Connector:
    source = "hkex"

    def __init__(self, frame: pl.DataFrame) -> None:
        self.frame = frame

    def fetch_etp_instruments(
        self, *, target_symbols: tuple[str, ...], as_of: dt.date
    ) -> pl.DataFrame:
        return self.frame


def _stock() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["00700.HK"],
            "market": ["HK"],
            "name": ["TENCENT"],
            "instrument_type": ["STOCK"],
            "currency": ["HKD"],
            "list_date": [dt.date(2004, 6, 16)],
            "delist_date": [None],
            "board_lot": [100],
            "status": ["LISTED"],
        }
    ).with_columns(pl.col("delist_date").cast(pl.Date))


def test_pipeline_preserves_raw_before_mapper_failure_and_clean_bytes(
    tmp_path: Path,
) -> None:
    clean_store = CleanInstrumentStore(tmp_path / "clean" / "instrument")
    clean_store.upsert(_stock())
    clean_path = tmp_path / "clean" / "instrument" / "market=HK" / "data.parquet"
    before = clean_path.read_bytes()
    mapper = HkexEtpInstrumentMapper(target_symbols=("02800.HK",), as_of=DAY)
    pipeline = HkexEtpInstrumentUpdatePipeline(
        connector=_Connector(_raw(_row("02800.HK", currency="CNY"))),
        mapper=mapper,
        raw_store=RawStore(tmp_path / "raw"),
        clean_store=clean_store,
    )
    with pytest.raises(ValueError, match="^HKEX_ETP_ROW_INVALID$"):
        pipeline.update(target_symbols=("02800.HK",), as_of=DAY)
    assert list((tmp_path / "raw" / "hkex" / "instrument_etp").rglob("*.parquet"))
    assert clean_path.read_bytes() == before


def test_pipeline_upsert_keeps_existing_stock_and_binds_raw_metadata(tmp_path: Path) -> None:
    clean_store = CleanInstrumentStore(tmp_path / "clean" / "instrument")
    clean_store.upsert(_stock())
    mapper = HkexEtpInstrumentMapper(target_symbols=("02800.HK",), as_of=DAY)
    pipeline = HkexEtpInstrumentUpdatePipeline(
        connector=_Connector(_raw(_row("02800.HK", name="TRACKER FUND"))),
        mapper=mapper,
        raw_store=RawStore(tmp_path / "raw"),
        clean_store=clean_store,
    )
    result = pipeline.update(target_symbols=("02800.HK",), as_of=DAY)
    merged = pl.read_parquet(
        tmp_path / "clean" / "instrument" / "market=HK" / "data.parquet"
    )
    assert set(merged.get_column("symbol")) == {"00700.HK", "02800.HK"}
    metadata = result.raw_snapshot.metadata_path.read_text(encoding="utf-8")
    assert '"as_of": "2026-07-10"' in metadata
    assert "latest_trade_date_lte_as_of_v1" in metadata
    assert "token" not in metadata.lower()
