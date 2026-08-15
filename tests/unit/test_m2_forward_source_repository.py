import datetime as dt
import hashlib
import json
import os
from pathlib import Path

import polars as pl
import pytest

import quant.data.m2_forward_source_repository as repository_module
from quant.data.m2_forward_source_repository import (
    M2ForwardSourceError,
    load_m2_forward_source_slice,
)
from quant.research.lightweight_run import canonical_json_bytes, dataframe_input_digest

SYMBOLS = ("159919.SZ", "510300.SH")
AS_OF = dt.date(2026, 8, 31)
DATA_START = dt.date(2026, 8, 28)


def _prices(date: dt.date) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": list(SYMBOLS),
            "trade_date": [date, date],
            "adjusted_close": [1.2, 4.1],
            "adjustment_method": ["TOTAL_RETURN_DIVIDEND"] * 2,
            "source": ["fixture"] * 2,
        }
    )


def _calendar(market: str) -> pl.DataFrame:
    dates = [
        dt.date(2026, 8, 1) + dt.timedelta(days=offset)
        for offset in range(32)
    ]
    return pl.DataFrame(
        {
            "market": [market] * len(dates),
            "date": dates,
            "is_open": [date.weekday() < 5 for date in dates],
            "is_connect_open": [False] * len(dates),
            "is_half_day": [False] * len(dates),
        }
    )


def _data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    for date in (DATA_START, AS_OF):
        partition = root / "clean" / "research_price_1d" / f"date={date.isoformat()}"
        partition.mkdir(parents=True)
        _prices(date).write_parquet(partition / "data.parquet")
    for market in ("SH", "SZ", "HK"):
        partition = root / "clean" / "trade_calendar" / f"market={market}"
        partition.mkdir(parents=True)
        _calendar(market).write_parquet(partition / "data.parquet")
    return root


def _assert_source_invalid(callable_) -> None:
    with pytest.raises(
        M2ForwardSourceError, match="^M2_FORWARD_SOURCE_INVALID$"
    ) as caught:
        callable_()
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_repository_returns_canonical_receipt_and_matching_logical_inputs(
    tmp_path: Path,
) -> None:
    data_root = _data_root(tmp_path)
    source = load_m2_forward_source_slice(
        data_root=data_root,
        candidate_symbols=SYMBOLS,
        data_start=DATA_START,
        as_of=AS_OF,
    )

    receipt = json.loads(source.source_receipt)
    assert source.source_receipt == canonical_json_bytes(receipt)
    assert receipt["schema_version"] == "m2-forward-source-receipt-v1"
    assert receipt["source_snapshot_id"] == source.source_snapshot_id
    body = dict(receipt)
    body.pop("source_snapshot_id")
    assert source.source_snapshot_id == hashlib.sha256(
        canonical_json_bytes(["m2-forward-source-snapshot-id-v1", body])
    ).hexdigest()
    assert receipt["query"] == {
        "adjustment_method": "TOTAL_RETURN_DIVIDEND",
        "as_of": "2026-08-31",
        "calendar_markets": ["SH", "SZ"],
        "candidate_symbols": list(SYMBOLS),
        "data_start": "2026-08-28",
    }
    assert [item["relative_path"] for item in receipt["files"]] == sorted(
        item["relative_path"] for item in receipt["files"]
    )
    assert all(not Path(item["relative_path"]).is_absolute() for item in receipt["files"])
    for item in receipt["files"]:
        payload = (data_root / item["relative_path"]).read_bytes()
        assert item["size_bytes"] == len(payload)
        assert item["sha256"] == hashlib.sha256(payload).hexdigest()

    expected = [
        dataframe_input_digest(
            name="calendars",
            frame=source.calendars,
            sort_by=("market", "date"),
            date_column="date",
        ),
        dataframe_input_digest(
            name="research-prices",
            frame=source.prices,
            sort_by=("trade_date", "symbol"),
            date_column="trade_date",
        ),
    ]
    assert receipt["logical_inputs"] == [
        {
            "content_sha256": item.content_sha256,
            "max_date": item.max_date.isoformat(),
            "min_date": item.min_date.isoformat(),
            "name": item.name,
            "rows": item.rows,
        }
        for item in expected
    ]


@pytest.mark.parametrize("mutation", ["hardlink", "symlink"])
def test_repository_rejects_linked_or_aliased_source_files(
    tmp_path: Path, mutation: str
) -> None:
    data_root = _data_root(tmp_path)
    target = data_root / "clean" / "trade_calendar" / "market=SZ" / "data.parquet"
    source = data_root / "clean" / "trade_calendar" / "market=SH" / "data.parquet"
    target.unlink()
    try:
        if mutation == "hardlink":
            os.link(source, target)
        else:
            target.symlink_to(source)
    except OSError as error:
        pytest.skip(f"host cannot create {mutation}: {error.__class__.__name__}")

    _assert_source_invalid(
        lambda: load_m2_forward_source_slice(
            data_root=data_root,
            candidate_symbols=SYMBOLS,
            data_start=DATA_START,
            as_of=AS_OF,
        )
    )


def test_repository_rejects_inventory_drift_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = _data_root(tmp_path)
    original = repository_module._read_stable_file
    mutated = False

    def mutate_after_first_read(path: Path, *, expected):
        nonlocal mutated
        result = original(path, expected=expected)
        if not mutated:
            mutated = True
            extra = (
                data_root
                / "clean"
                / "research_price_1d"
                / "date=2026-08-30"
            )
            extra.mkdir()
            _prices(dt.date(2026, 8, 30)).write_parquet(extra / "data.parquet")
        return result

    monkeypatch.setattr(repository_module, "_read_stable_file", mutate_after_first_read)
    _assert_source_invalid(
        lambda: load_m2_forward_source_slice(
            data_root=data_root,
            candidate_symbols=SYMBOLS,
            data_start=DATA_START,
            as_of=AS_OF,
        )
    )


@pytest.mark.parametrize(
    ("symbols", "data_start", "as_of"),
    [
        (("510300.SH", "159919.SZ"), DATA_START, AS_OF),
        (("510300.SH", "510300.SH"), DATA_START, AS_OF),
        (SYMBOLS, AS_OF, DATA_START),
    ],
)
def test_repository_rejects_noncanonical_query(
    tmp_path: Path,
    symbols: tuple[str, ...],
    data_start: dt.date,
    as_of: dt.date,
) -> None:
    data_root = _data_root(tmp_path)
    before = sorted(path.relative_to(data_root) for path in data_root.rglob("*"))
    _assert_source_invalid(
        lambda: load_m2_forward_source_slice(
            data_root=data_root,
            candidate_symbols=symbols,
            data_start=data_start,
            as_of=as_of,
        )
    )
    assert sorted(path.relative_to(data_root) for path in data_root.rglob("*")) == before


def test_repository_rejects_missing_candidate_as_of_without_writes(
    tmp_path: Path,
) -> None:
    data_root = _data_root(tmp_path)
    partition = data_root / "clean" / "research_price_1d" / "date=2026-08-31"
    _prices(AS_OF).filter(pl.col("symbol") != SYMBOLS[0]).write_parquet(
        partition / "data.parquet"
    )
    before = {
        path.relative_to(data_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in data_root.rglob("*")
        if path.is_file()
    }
    _assert_source_invalid(
        lambda: load_m2_forward_source_slice(
            data_root=data_root,
            candidate_symbols=SYMBOLS,
            data_start=DATA_START,
            as_of=AS_OF,
        )
    )
    after = {
        path.relative_to(data_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in data_root.rglob("*")
        if path.is_file()
    }
    assert after == before
