import datetime as dt
import json
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from quant.data.pipeline import HkexTemporaryInstrumentUpdatePipeline
from quant.data.storage import CleanInstrumentStore, RawStore
from quant.data.temporary_instruments import (
    load_hkex_temporary_counter_notice,
    project_temporary_instruments,
    temporary_counter_raw_frame,
)
from quant.domain import InstrumentSchema

CONFIG = Path("configs/instruments/hk_temporary_counters_2026.toml")


def test_real_notice_projects_closed_interval_and_delisted_afterward() -> None:
    notice = load_hkex_temporary_counter_notice(CONFIG)
    for day in (dt.date(2026, 7, 10), dt.date(2026, 8, 13)):
        row = project_temporary_instruments(
            notice, target_symbols=("02983.HK",), as_of=day
        ).row(0, named=True)
        assert row == {
            "symbol": "02983.HK",
            "market": "HK",
            "name": "HESAI-W",
            "instrument_type": "STOCK",
            "currency": "HKD",
            "list_date": dt.date(2026, 7, 10),
            "delist_date": dt.date(2026, 8, 13),
            "board_lot": 160,
            "status": "LISTED",
        }
    after = project_temporary_instruments(
        notice, target_symbols=("02983.HK",), as_of=dt.date(2026, 8, 14)
    )
    assert after.row(0, named=True)["status"] == "DELISTED"
    with pytest.raises(ValueError, match="^HK_TEMPORARY_COVERAGE_INCOMPLETE$"):
        project_temporary_instruments(
            notice,
            target_symbols=("02983.HK",),
            as_of=dt.date(2026, 7, 9),
        )


def test_notice_separates_trading_end_from_certificate_and_ccass_dates() -> None:
    notice = load_hkex_temporary_counter_notice(CONFIG)
    counter = notice.counters[0]
    bad = replace(notice, counters=(replace(counter, delist_date=dt.date(2026, 8, 17)),))
    with pytest.raises(ValueError, match="^HK_TEMPORARY_NOTICE_INVALID$"):
        temporary_counter_raw_frame(bad)
    bad = replace(
        notice,
        counters=(replace(counter, parallel_trading_end=dt.date(2026, 8, 24)),),
    )
    with pytest.raises(ValueError, match="^HK_TEMPORARY_NOTICE_INVALID$"):
        temporary_counter_raw_frame(bad)


def test_notice_requires_roles_and_valid_hash(tmp_path: Path) -> None:
    text = CONFIG.read_text(encoding="utf-8")
    missing_role = tmp_path / "missing_role.toml"
    missing_role.write_text(
        text.replace('role = "FINAL_EFFECTIVE"', 'role = "TRADING_SCHEDULE"'),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="^HK_TEMPORARY_NOTICE_INVALID$"):
        load_hkex_temporary_counter_notice(missing_role)
    bad_hash = tmp_path / "bad_hash.toml"
    bad_hash.write_text(
        text.replace(
            "1905a5ae2f494cbeefb1c83ba1f05a614d1a099b47e3f94060fa8201bdac5531",
            "not-a-hash",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="^HK_TEMPORARY_NOTICE_INVALID$"):
        load_hkex_temporary_counter_notice(bad_hash)


def test_reused_symbol_lifecycles_must_not_overlap() -> None:
    notice = load_hkex_temporary_counter_notice(CONFIG)
    current = notice.counters[0]
    prior = replace(
        current,
        name="PRIOR TEMP",
        list_date=dt.date(2025, 7, 1),
        parallel_trading_end=dt.date(2025, 7, 31),
        delist_date=dt.date(2025, 7, 31),
        certificate_delivery_end=dt.date(2025, 8, 1),
        ccass_conversion_end=dt.date(2025, 8, 2),
        board_lot=100,
    )
    reusable = replace(notice, counters=(prior, current))
    selected = project_temporary_instruments(
        reusable,
        target_symbols=("02983.HK",),
        as_of=dt.date(2025, 7, 15),
    )
    assert selected.row(0, named=True)["name"] == "PRIOR TEMP"
    overlap = replace(
        prior,
        list_date=dt.date(2026, 7, 1),
        parallel_trading_end=dt.date(2026, 7, 20),
        delist_date=dt.date(2026, 7, 20),
        certificate_delivery_end=dt.date(2026, 7, 21),
        ccass_conversion_end=dt.date(2026, 7, 22),
    )
    conflicted = replace(notice, counters=(overlap, current))
    with pytest.raises(ValueError, match="^HK_TEMPORARY_LIFECYCLE_CONFLICT$"):
        temporary_counter_raw_frame(conflicted)


def _existing_etf() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["02800.HK"],
            "market": ["HK"],
            "name": ["TRACKER FUND"],
            "instrument_type": ["ETF"],
            "currency": ["HKD"],
            "list_date": [dt.date(1999, 11, 12)],
            "delist_date": [None],
            "board_lot": [500],
            "status": ["LISTED"],
        }
    ).with_columns(pl.col("delist_date").cast(pl.Date))


def test_pipeline_preserves_notice_raw_and_existing_instruments(tmp_path: Path) -> None:
    notice = load_hkex_temporary_counter_notice(CONFIG)
    clean_store = CleanInstrumentStore(tmp_path / "clean" / "instrument")
    clean_store.upsert(_existing_etf())
    pipeline = HkexTemporaryInstrumentUpdatePipeline(
        raw_store=RawStore(tmp_path / "raw"), clean_store=clean_store
    )
    result = pipeline.update(
        notice=notice,
        target_symbols=("02983.HK",),
        as_of=dt.date(2026, 7, 10),
    )
    merged = pl.read_parquet(
        tmp_path / "clean" / "instrument" / "market=HK" / "data.parquet"
    )
    InstrumentSchema.validate(merged)
    assert set(merged.get_column("symbol")) == {"02800.HK", "02983.HK"}
    metadata = json.loads(result.raw_snapshot.metadata_path.read_text(encoding="utf-8"))
    assert metadata["parameters"]["selection_rule"] == (
        "temporary_counter_lifecycle_as_of_v1"
    )
    assert len(metadata["parameters"]["evidence_sha256"]) == 2
    raw = pl.read_parquet(result.raw_snapshot.data_path)
    assert raw.row(0, named=True)["related_symbol"] == "02525.HK"
    assert "PT/NIS/CCASS/209/2026" in raw.row(0, named=True)["evidence_json"]
