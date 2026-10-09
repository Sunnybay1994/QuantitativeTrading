"""Daily stock observations for the two fixed B32 forward accounts."""

import datetime as dt
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.mappers import TushareInstrumentMapper
from quant.data.refresh_stocks import read_stock_data
from quant.data.stock_execution_inputs import resolve_same_day_dividends
from quant.data.storage import RawStore

DIVIDEND_SCHEMA = {
    "symbol": pl.String,
    "ann_date": pl.Date,
    "record_date": pl.Date,
    "ex_date": pl.Date,
    "pay_date": pl.Date,
    "share_list_date": pl.Date,
    "div_cash": pl.Float64,
    "share_ratio": pl.Float64,
}

# The stock paper accounts consume mainland SH/SZ A shares. B-share settlement
# dates and currencies follow different rules and must not enter this mapper.
_A_SHARE_SYMBOL = r"^(?:6\d{5}\.SH|[03]\d{5}\.SZ)$"


@dataclass
class StockPaperInputs:
    bars: pl.DataFrame
    daily_basic: pl.DataFrame
    calendar: pl.DataFrame
    names: pl.DataFrame
    instruments: pl.DataFrame
    limits: pl.DataFrame
    suspensions: pl.DataFrame
    dividends: pl.DataFrame


def read_stock_paper_calendar(data_root: Path) -> pl.DataFrame:
    return pl.concat(
        [
            pl.read_parquet(data_root / f"clean/trade_calendar/market={market}/data.parquet")
            for market in ("SH", "SZ")
        ]
    ).sort("date", "market")


def read_stock_paper_freeze(data_root: Path, config: dict[str, Any]) -> pl.DataFrame:
    universe = config["universe"]
    return read_stock_data(
        data_root=data_root,
        config=Path(config["data"]["refresh_config"]),
        table="bar_1d",
        start=universe["freeze_start"],
        end=universe["freeze_end"],
    )


def map_day_dividends(raw: pl.DataFrame, date: dt.date) -> pl.DataFrame:
    if raw.is_empty():
        return pl.DataFrame(schema=DIVIDEND_SCHEMA)
    if raw.height >= 2000:
        raise ValueError("Possibly truncated daily dividend response")
    frame = (
        raw.filter(
            (pl.col("div_proc") == "实施")
            & pl.col("ts_code").str.contains(_A_SHARE_SYMBOL)
            & (pl.col("ex_date").cast(pl.String) == date.strftime("%Y%m%d"))
        )
        .select(
            pl.col("ts_code").alias("symbol"),
            pl.col("imp_ann_date").cast(pl.String).str.to_date("%Y%m%d").alias("ann_date"),
            pl.col("record_date").cast(pl.String).str.to_date("%Y%m%d"),
            pl.col("ex_date").cast(pl.String).str.to_date("%Y%m%d"),
            pl.col("pay_date").cast(pl.String).str.to_date("%Y%m%d"),
            pl.col("div_listdate").cast(pl.String).str.to_date("%Y%m%d").alias("share_list_date"),
            pl.col("cash_div_tax").cast(pl.Float64).fill_null(0.0).alias("div_cash"),
            pl.col("stk_div").cast(pl.Float64).fill_null(0.0).alias("share_ratio"),
        )
    )
    frame = resolve_same_day_dividends(frame)
    checks = {
        "missing_implementation_announcement": pl.col("ann_date").is_null(),
        "future_implementation_announcement": pl.col("ann_date") > date,
        "missing_record_date": pl.col("record_date").is_null(),
        "announcement_after_record_date": pl.col("ann_date") > pl.col("record_date"),
        "record_date_not_before_ex_date": pl.col("record_date") >= pl.col("ex_date"),
        "missing_or_early_cash_payment": (
            (pl.col("div_cash") > 0)
            & (pl.col("pay_date").is_null() | (pl.col("pay_date") < date))
        ),
        "missing_or_early_share_listing": (
            (pl.col("share_ratio") > 0)
            & (pl.col("share_list_date").is_null() | (pl.col("share_list_date") < date))
        ),
    }
    invalid = frame.with_columns(
        *[expr.fill_null(False).alias(name) for name, expr in checks.items()]
    ).filter(pl.any_horizontal(*[pl.col(name) for name in checks]))
    if invalid.height:
        examples = [
            {
                **{name: row[name] for name in DIVIDEND_SCHEMA},
                "reasons": [name for name in checks if row[name]],
            }
            for row in invalid.head(5).iter_rows(named=True)
        ]
        raise ValueError(
            f"Incomplete or future stock dividend implementation ({invalid.height}): "
            + json.dumps(examples, default=str, ensure_ascii=False)
        )
    return frame


def capture_stock_paper_day(data_root: Path, date: dt.date) -> Path:
    """One dated capture, reused by both accounts; later days refresh mutable facts."""
    output = data_root / "clean/stock_paper_inputs" / f"date={date}"
    filenames = ("instruments", "names", "limits", "suspensions", "dividends")
    if all((output / f"{name}.parquet").is_file() for name in filenames):
        return output
    connector = TushareConnector(config_path=Path("configs/tushare.local.toml"))
    raw_store = RawStore(data_root / "raw")
    sources = []

    def request(api: str, **params: str) -> pl.DataFrame:
        for attempt in range(3):
            try:
                frame = connector.query_raw(api, **params)
                break
            except Exception:
                if attempt == 2:
                    raise RuntimeError(f"Tushare {api} daily stock input failed") from None
                time.sleep(attempt + 1)
        path = raw_store.write(
            source="tushare", table=api, frame=frame, parameters=params
        ).data_path
        sources.append(str(path))
        time.sleep(1.0)
        return frame

    basic = pl.concat(
        [
            request(
                "stock_basic", list_status=status, fields="ts_code,name,list_date,delist_date"
            ).with_columns(pl.lit(status).alias("_request_list_status"))
            for status in ("L", "D", "P")
        ],
        how="diagonal_relaxed",
    )
    instruments = pl.concat([TushareInstrumentMapper(market).map(basic) for market in ("SH", "SZ")])
    if instruments["symbol"].n_unique() != instruments.height:
        raise ValueError("Duplicate stock instruments")
    names_raw, offset = [], 0
    while True:
        page = request("namechange", limit="5000", offset=str(offset))
        if page.is_empty():
            break
        names_raw.append(page)
        offset += page.height
        if page.height < 5000:
            break
        if offset > 100000:
            raise ValueError("Unexpected name history pagination")
    if not names_raw:
        raise ValueError("Missing stock name history")
    names = (
        pl.concat(names_raw, how="diagonal_relaxed")
        .unique()
        .select(
            pl.col("ts_code").alias("symbol"),
            "name",
            pl.col("start_date").str.to_date("%Y%m%d"),
            pl.col("end_date").str.to_date("%Y%m%d"),
            pl.col("ann_date").str.to_date("%Y%m%d", strict=False),
        )
        .filter(pl.col("start_date") <= date)
    )
    raw_limits = request("stk_limit", trade_date=date.strftime("%Y%m%d"))
    if raw_limits.is_empty() or raw_limits.height >= 5800:
        raise ValueError("Missing or truncated stock price bands")
    limits = raw_limits.select(
        pl.col("ts_code").alias("symbol"),
        pl.col("trade_date").str.to_date("%Y%m%d"),
        pl.col("up_limit").cast(pl.Float64),
        pl.col("down_limit").cast(pl.Float64),
    )
    if limits["trade_date"].unique().to_list() != [date]:
        raise ValueError("Wrong-date stock price bands")
    raw_suspensions = request("suspend_d", trade_date=date.strftime("%Y%m%d"))
    suspensions = (
        pl.DataFrame(schema={"symbol": pl.String, "trade_date": pl.Date})
        if raw_suspensions.is_empty()
        else raw_suspensions.filter(pl.col("suspend_type") == "S")
        .select(pl.col("ts_code").alias("symbol"), pl.col("trade_date").str.to_date("%Y%m%d"))
        .unique()
    )
    dividends = map_day_dividends(request("dividend", ex_date=date.strftime("%Y%m%d")), date)
    output.mkdir(parents=True, exist_ok=True)
    for name, frame in (
        ("instruments", instruments),
        ("names", names),
        ("limits", limits),
        ("suspensions", suspensions),
        ("dividends", dividends),
    ):
        frame.write_parquet(output / f"{name}.parquet")
    (output / "sources.json").write_text(
        json.dumps({"as_of": str(date), "raw": sources}, indent=2), encoding="utf-8"
    )
    return output


def read_stock_paper_inputs(
    data_root: Path,
    config: dict[str, Any],
    symbols: list[str],
    date: dt.date,
) -> StockPaperInputs:
    path = capture_stock_paper_day(data_root, date)
    bars = read_stock_data(
        data_root=data_root,
        config=Path(config["data"]["refresh_config"]),
        table="bar_1d",
        start=config["data"]["warmup_start"],
        end=date,
        symbols=symbols,
    )
    basic = read_stock_data(
        data_root=data_root,
        config=Path(config["data"]["refresh_config"]),
        table="daily_basic",
        start=config["data"]["warmup_start"],
        end=date,
        symbols=symbols,
    )
    minimum = config["universe"]["minimum_daily_symbols"]
    if (
        bars.filter(pl.col("trade_date") == date).height < minimum
        or basic.filter(pl.col("trade_date") == date).height < minimum
    ):
        raise ValueError(f"Incomplete current daily bars/basic: {date}; refresh stock data first")
    frames = {
        name: pl.read_parquet(path / f"{name}.parquet").filter(pl.col("symbol").is_in(symbols))
        for name in ("names", "instruments", "limits", "suspensions", "dividends")
    }
    if frames["instruments"].height != len(symbols):
        raise ValueError("Frozen stock instrument coverage missing")
    frames["dividends"] = frames["dividends"].with_columns(
        (pl.col("div_cash") * (1 - config["portfolio"]["stock_dividend_withholding"])).alias(
            "div_cash"
        )
    )
    return StockPaperInputs(bars, basic, read_stock_paper_calendar(data_root), **frames)
