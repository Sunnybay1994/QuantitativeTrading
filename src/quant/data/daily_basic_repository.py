"""Bounded read access to immutable Tushare daily-basic clean snapshots."""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import duckdb
import polars as pl

from quant.data.publish_tushare_daily_basic import (
    TushareDailyBasicSnapshot,
    verify_tushare_daily_basic_snapshot,
)
from quant.domain import DailyBasic1dSchema

_SYMBOL = re.compile(r"^\d{6}\.(SH|SZ)$")


class TushareDailyBasicReadError(ValueError):
    """Stable error for an invalid or unstable bounded read."""

    def __init__(self) -> None:
        super().__init__("TUSHARE_DAILY_BASIC_READ_INVALID")


@dataclass(frozen=True, slots=True)
class TushareDailyBasicQuery:
    """Canonical bounded query against one immutable daily-basic snapshot."""

    snapshot_id: str
    start_date: dt.date
    end_date: dt.date
    symbols: tuple[str, ...] | None = None
    threads: int = 2

    def __post_init__(self) -> None:
        _validate_query(self)


def read_tushare_daily_basic(
    *, data_root: Path, query: TushareDailyBasicQuery
) -> pl.DataFrame:
    """Verify, read, and re-verify a bounded daily-basic projection."""
    try:
        if not isinstance(data_root, Path) or type(query) is not TushareDailyBasicQuery:
            raise ValueError
        before = verify_tushare_daily_basic_snapshot(
            data_root=data_root, snapshot_id=query.snapshot_id
        )
        paths = _selected_paths(before, query=query)
        frame = _query_parquet(paths=paths, query=query)
        after = verify_tushare_daily_basic_snapshot(
            data_root=data_root, snapshot_id=query.snapshot_id
        )
        if before != after:
            raise ValueError
        validated = DailyBasic1dSchema.validate(frame)
        if (
            validated.is_empty()
            or not validated.equals(
                validated.sort(["symbol", "trade_date", "source"])
            )
        ):
            raise ValueError
        return validated
    except Exception:
        pass
    raise TushareDailyBasicReadError() from None


def _selected_paths(
    snapshot: TushareDailyBasicSnapshot, *, query: TushareDailyBasicQuery
) -> tuple[Path, ...]:
    manifest_path = snapshot.root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError
    manifest = json.loads(manifest_path.read_bytes())
    files = manifest.get("files") if type(manifest) is dict else None
    if type(files) is not list:
        raise ValueError
    years = set(range(query.start_date.year, query.end_date.year + 1))
    selected: list[Path] = []
    for raw in files:
        if type(raw) is not dict:
            raise ValueError
        relative = raw.get("relative_path")
        if type(relative) is not str or not relative.startswith("year="):
            continue
        parts = relative.split("/")
        if len(parts) != 2 or parts[1] != "data.parquet":
            raise ValueError
        year_text = parts[0].removeprefix("year=")
        if len(year_text) != 4 or not year_text.isdigit():
            raise ValueError
        if int(year_text) not in years:
            continue
        path = snapshot.root / Path(relative)
        if path.is_symlink() or not path.is_file():
            raise ValueError
        selected.append(path)
    if not selected:
        raise ValueError
    return tuple(selected)


def _query_parquet(
    *, paths: tuple[Path, ...], query: TushareDailyBasicQuery
) -> pl.DataFrame:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(f"SET threads={query.threads}")
        connection.execute("SET enable_progress_bar=false")
        connection.execute("SET preserve_insertion_order=false")
        sql = """
            SELECT symbol, trade_date, close, turnover_rate,
              turnover_rate_free, volume_ratio, pe, pe_ttm, pb, ps, ps_ttm,
              dividend_yield, dividend_yield_ttm, total_shares, float_shares,
              free_float_shares, total_market_value,
              circulating_market_value, source
            FROM read_parquet(?)
            WHERE trade_date BETWEEN ? AND ?
        """
        parameters: list[object] = [
            [str(path) for path in paths],
            query.start_date,
            query.end_date,
        ]
        if query.symbols is not None:
            sql += " AND symbol IN (SELECT UNNEST(?))"
            parameters.append(list(query.symbols))
        sql += " ORDER BY symbol, trade_date, source"
        return connection.execute(sql, parameters).pl()
    finally:
        connection.close()


def _validate_query(query: TushareDailyBasicQuery) -> None:
    if (
        not _hex64(query.snapshot_id)
        or type(query.start_date) is not dt.date
        or type(query.end_date) is not dt.date
        or query.end_date < query.start_date
        or type(query.threads) is not int
        or not 1 <= query.threads <= 4
    ):
        raise TushareDailyBasicReadError() from None
    if query.symbols is not None and (
        type(query.symbols) is not tuple
        or not query.symbols
        or query.symbols != tuple(sorted(query.symbols))
        or len(query.symbols) != len(set(query.symbols))
        or any(_SYMBOL.fullmatch(symbol) is None for symbol in query.symbols)
    ):
        raise TushareDailyBasicReadError() from None


def _hex64(value: object) -> bool:
    return (
        type(value) is str
        and len(cast(str, value)) == 64
        and set(cast(str, value)) <= set("0123456789abcdef")
    )


__all__ = [
    "TushareDailyBasicQuery",
    "TushareDailyBasicReadError",
    "read_tushare_daily_basic",
]
