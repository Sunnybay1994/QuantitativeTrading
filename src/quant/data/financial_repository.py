"""Bounded reads from immutable Tushare financial clean snapshots."""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import duckdb
import polars as pl

from quant.data.financial_clean import FinancialFactorDataset
from quant.data.publish_tushare_financials import (
    TushareFinancialSnapshot,
    verify_tushare_financial_snapshot,
)

_STATEMENTS = frozenset({"balancesheet", "cashflow", "income"})
_ECONOMICS: dict[str, tuple[str, ...]] = {
    "balancesheet": ("total_assets", "total_hldr_eqy_exc_min_int"),
    "cashflow": ("n_cashflow_act",),
    "fina_indicator": (),
    "income": ("n_income", "n_income_attr_p"),
}
_SYMBOL = re.compile(r"^\d{6}\.(SH|SZ)$")


class TushareFinancialReadError(ValueError):
    """Stable failure for an invalid or unstable bounded financial read."""

    def __init__(self) -> None:
        super().__init__("TUSHARE_FINANCIAL_READ_INVALID")


@dataclass(frozen=True, slots=True)
class TushareFinancialHistoryQuery:
    """Canonical bounded revision-history query against one snapshot."""

    snapshot_id: str
    dataset: FinancialFactorDataset
    start_period: dt.date
    end_period: dt.date
    symbols: tuple[str, ...]
    threads: int = 2

    def __post_init__(self) -> None:
        _validate_query(self)


def read_tushare_financial_history(
    *, data_root: Path, query: TushareFinancialHistoryQuery
) -> pl.DataFrame:
    """Verify, read, and re-verify bounded revision history for PIT selection."""
    try:
        if not isinstance(data_root, Path) or type(query) is not TushareFinancialHistoryQuery:
            raise ValueError
        before = verify_tushare_financial_snapshot(
            data_root=data_root, snapshot_id=query.snapshot_id
        )
        paths = _selected_paths(before, query=query)
        frame = _query_parquet(paths=paths, query=query) if paths else _empty_frame(query.dataset)
        after = verify_tushare_financial_snapshot(
            data_root=data_root, snapshot_id=query.snapshot_id
        )
        if before != after:
            raise ValueError
        _validate_result(frame, query=query)
        return frame
    except Exception:
        pass
    raise TushareFinancialReadError() from None


def _selected_paths(
    snapshot: TushareFinancialSnapshot,
    *,
    query: TushareFinancialHistoryQuery,
) -> tuple[Path, ...]:
    manifest_path = snapshot.root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError
    manifest = json.loads(manifest_path.read_bytes())
    files = manifest.get("files") if type(manifest) is dict else None
    if type(files) is not list:
        raise ValueError
    years = set(range(query.start_period.year, query.end_period.year + 1))
    prefix = f"dataset={query.dataset}/year="
    selected: list[Path] = []
    for raw in files:
        if type(raw) is not dict:
            raise ValueError
        relative = raw.get("relative_path")
        if type(relative) is not str or not relative.startswith(prefix):
            continue
        parts = relative.split("/")
        if len(parts) != 2 or not parts[1].endswith(".parquet"):
            raise ValueError
        year_text = parts[1].removeprefix("year=").removesuffix(".parquet")
        if len(year_text) != 4 or not year_text.isdigit():
            raise ValueError
        if int(year_text) not in years:
            continue
        path = snapshot.root / Path(relative)
        if path.is_symlink() or not path.is_file():
            raise ValueError
        selected.append(path)
    return tuple(selected)


def _query_parquet(*, paths: tuple[Path, ...], query: TushareFinancialHistoryQuery) -> pl.DataFrame:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(f"SET threads={query.threads}")
        connection.execute("SET enable_progress_bar=false")
        connection.execute("SET preserve_insertion_order=false")
        columns = _columns(query.dataset)
        sql = (
            f"SELECT {','.join(columns)} FROM read_parquet(?) "
            "WHERE end_date BETWEEN ? AND ? "
            "AND symbol IN (SELECT UNNEST(?)) "
            f"ORDER BY {_order_sql(query.dataset)}"
        )
        return connection.execute(
            sql,
            [
                [str(path) for path in paths],
                query.start_period,
                query.end_period,
                list(query.symbols),
            ],
        ).pl()
    finally:
        connection.close()


def _empty_frame(dataset: str) -> pl.DataFrame:
    string = pl.String()
    date = pl.Date()
    number = pl.Float64()
    schema: dict[str, pl.DataType] = {
        "symbol": string,
        "ann_date": date,
    }
    if dataset in _STATEMENTS:
        schema |= {
            "f_ann_date": date,
            "available_date": date,
            "end_date": date,
            "report_type": string,
            "comp_type": string,
            "update_flag": string,
        }
    else:
        schema |= {"available_date": date, "end_date": date}
    schema |= {name: number for name in _ECONOMICS[dataset]}
    schema["source"] = string
    return pl.DataFrame(schema=schema)


def _columns(dataset: str) -> list[str]:
    result = ["symbol", "ann_date"]
    if dataset in _STATEMENTS:
        result.extend(
            [
                "f_ann_date",
                "available_date",
                "end_date",
                "report_type",
                "comp_type",
                "update_flag",
            ]
        )
    else:
        result.extend(["available_date", "end_date"])
    result.extend(_ECONOMICS[dataset])
    result.append("source")
    return result


def _order_sql(dataset: str) -> str:
    if dataset in _STATEMENTS:
        return "symbol,end_date,available_date,report_type,comp_type,update_flag,ann_date"
    return "symbol,end_date,available_date,ann_date"


def _validate_result(frame: pl.DataFrame, *, query: TushareFinancialHistoryQuery) -> None:
    expected = _empty_frame(query.dataset)
    if frame.columns != expected.columns or frame.schema != expected.schema:
        raise ValueError
    if frame.is_empty():
        return
    if frame.filter(
        ~pl.col("symbol").is_in(list(query.symbols))
        | ~pl.col("end_date").is_between(query.start_period, query.end_period, closed="both")
        | (pl.col("source") != "tushare")
    ).height:
        raise ValueError
    keys = _order_sql(query.dataset).split(",")
    if not frame.select(keys).equals(frame.select(keys).sort(keys)):
        raise ValueError


def _validate_query(query: TushareFinancialHistoryQuery) -> None:
    if (
        not _hex64(query.snapshot_id)
        or type(query.dataset) is not str
        or query.dataset not in _STATEMENTS
        or type(query.start_period) is not dt.date
        or type(query.end_period) is not dt.date
        or query.end_period < query.start_period
        or type(query.symbols) is not tuple
        or not query.symbols
        or query.symbols != tuple(sorted(query.symbols))
        or len(query.symbols) != len(set(query.symbols))
        or any(_SYMBOL.fullmatch(symbol) is None for symbol in query.symbols)
        or type(query.threads) is not int
        or not 1 <= query.threads <= 2
    ):
        raise TushareFinancialReadError() from None


def _hex64(value: object) -> bool:
    return (
        type(value) is str
        and len(cast(str, value)) == 64
        and set(cast(str, value)) <= set("0123456789abcdef")
    )


__all__ = [
    "TushareFinancialHistoryQuery",
    "TushareFinancialReadError",
    "read_tushare_financial_history",
]
