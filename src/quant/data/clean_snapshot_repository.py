"""Bounded read access to immutable Tushare clean snapshots."""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import duckdb
import polars as pl

from quant.data.publish_tushare_bulk_clean import (
    TushareBulkCleanSnapshot,
    verify_tushare_bulk_clean_snapshot,
)
from quant.domain import Bar1dSchema

_SYMBOL = re.compile(r"^\d{6}\.(SH|SZ)$")


class TushareBulkCleanReadError(ValueError):
    """Stable error for an invalid or unstable clean-snapshot read."""

    def __init__(self) -> None:
        super().__init__("TUSHARE_BULK_CLEAN_READ_INVALID")


@dataclass(frozen=True, slots=True)
class TushareBulkStockBarQuery:
    """Canonical bounded query against one immutable stock-bar snapshot."""

    snapshot_id: str
    start_date: dt.date
    end_date: dt.date
    symbols: tuple[str, ...] | None = None
    threads: int = 2

    def __post_init__(self) -> None:
        _validate_query(self)


@dataclass(frozen=True, slots=True)
class TushareBulkFundBarQuery:
    """Canonical bounded query against one immutable fund-bar snapshot."""

    snapshot_id: str
    start_date: dt.date
    end_date: dt.date
    symbols: tuple[str, ...] | None = None
    threads: int = 2

    def __post_init__(self) -> None:
        _validate_query(self)


def read_tushare_bulk_clean_stock_bars(
    *, data_root: Path, query: TushareBulkStockBarQuery
) -> pl.DataFrame:
    """Verify, read, and re-verify a bounded stock-bar projection."""
    try:
        if not isinstance(data_root, Path) or type(query) is not TushareBulkStockBarQuery:
            raise ValueError
        return _read_bars(data_root=data_root, query=query, asset="stock")
    except Exception:
        pass
    raise TushareBulkCleanReadError() from None


def read_tushare_bulk_clean_fund_bars(
    *, data_root: Path, query: TushareBulkFundBarQuery
) -> pl.DataFrame:
    """Verify, read, and re-verify a bounded fund-bar projection."""
    try:
        if not isinstance(data_root, Path) or type(query) is not TushareBulkFundBarQuery:
            raise ValueError
        return _read_bars(data_root=data_root, query=query, asset="fund")
    except Exception:
        pass
    raise TushareBulkCleanReadError() from None


def _read_bars(
    *,
    data_root: Path,
    query: TushareBulkStockBarQuery | TushareBulkFundBarQuery,
    asset: str,
) -> pl.DataFrame:
    before = verify_tushare_bulk_clean_snapshot(
        data_root=data_root, snapshot_id=query.snapshot_id
    )
    paths = _selected_bar_paths(before, query=query, asset=asset)
    frame = _query_parquet(paths=paths, query=query)
    after = verify_tushare_bulk_clean_snapshot(
        data_root=data_root, snapshot_id=query.snapshot_id
    )
    if before != after:
        raise ValueError
    validated = Bar1dSchema.validate(frame)
    if (
        validated.is_empty()
        or validated.columns
        != [
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "adj_factor",
            "source",
        ]
        or not validated.equals(validated.sort("symbol", "trade_date", "source"))
    ):
        raise ValueError
    return validated


def _selected_stock_paths(
    snapshot: TushareBulkCleanSnapshot, *, query: TushareBulkStockBarQuery
) -> tuple[Path, ...]:
    return _selected_bar_paths(snapshot, query=query, asset="stock")


def _selected_bar_paths(
    snapshot: TushareBulkCleanSnapshot,
    *,
    query: TushareBulkStockBarQuery | TushareBulkFundBarQuery,
    asset: str,
) -> tuple[Path, ...]:
    if asset not in {"stock", "fund"}:
        raise ValueError
    manifest_path = snapshot.root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError
    manifest = json.loads(manifest_path.read_bytes())
    files = manifest.get("files") if type(manifest) is dict else None
    if type(files) is not list:
        raise ValueError
    selected: list[Path] = []
    for raw in files:
        if type(raw) is not dict:
            raise ValueError
        relative = raw.get("relative_path")
        if type(relative) is not str or not relative.startswith(
            f"bar_1d/asset={asset}/"
        ):
            continue
        minimum = dt.date.fromisoformat(cast(str, raw.get("min_date")))
        maximum = dt.date.fromisoformat(cast(str, raw.get("max_date")))
        if maximum < query.start_date or minimum > query.end_date:
            continue
        path = snapshot.root / Path(relative)
        if path.is_symlink() or not path.is_file():
            raise ValueError
        selected.append(path)
    if not selected:
        raise ValueError
    return tuple(selected)


def _query_parquet(
    *,
    paths: tuple[Path, ...],
    query: TushareBulkStockBarQuery | TushareBulkFundBarQuery,
) -> pl.DataFrame:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(f"SET threads={query.threads}")
        connection.execute("SET enable_progress_bar=false")
        connection.execute("SET preserve_insertion_order=false")
        sql = """
            SELECT symbol, trade_date, open, high, low, close,
                   volume, amount, adj_factor, source
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


def _hex64(value: object) -> bool:
    return (
        type(value) is str
        and len(cast(str, value)) == 64
        and set(cast(str, value)) <= set("0123456789abcdef")
    )


def _validate_query(
    query: TushareBulkStockBarQuery | TushareBulkFundBarQuery,
) -> None:
    if (
        not _hex64(query.snapshot_id)
        or type(query.start_date) is not dt.date
        or type(query.end_date) is not dt.date
        or query.end_date < query.start_date
        or type(query.threads) is not int
        or not 1 <= query.threads <= 4
    ):
        raise TushareBulkCleanReadError() from None
    if query.symbols is not None and (
        type(query.symbols) is not tuple
        or not query.symbols
        or query.symbols != tuple(sorted(query.symbols))
        or len(query.symbols) != len(set(query.symbols))
        or any(_SYMBOL.fullmatch(symbol) is None for symbol in query.symbols)
    ):
        raise TushareBulkCleanReadError() from None


__all__ = [
    "TushareBulkCleanReadError",
    "TushareBulkFundBarQuery",
    "TushareBulkStockBarQuery",
    "read_tushare_bulk_clean_fund_bars",
    "read_tushare_bulk_clean_stock_bars",
]
