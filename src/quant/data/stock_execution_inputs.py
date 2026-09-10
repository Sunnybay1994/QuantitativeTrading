"""Capture the stock execution facts needed by a concrete monthly backtest."""

import datetime as dt
import json
import time
from pathlib import Path

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.mappers import TushareInstrumentMapper
from quant.data.storage import RawStore


def resolve_same_day_dividends(frame: pl.DataFrame) -> pl.DataFrame:
    """Resolve observed vendor ambiguities using issuer implementation notices."""
    # Sources and rationale: docs/research/同日分红数据修正_20260909.md.
    # Values are per-share cash for ordinary circulating shareholders.
    resolutions = {
        ("002352.SZ", dt.date(2024, 11, 7)): ([0.4, 1.0, 1.4], 1.4, 0.0),
        ("300760.SZ", dt.date(2025, 5, 29)): ([0.56, 1.41], 1.97, 0.0),
        ("300760.SZ", dt.date(2026, 5, 28)): ([0.31, 1.25], 1.56, 0.0),
        ("600188.SH", dt.date(2023, 7, 17)): ([1.23, 3.07], 4.3, 0.5),
        ("600188.SH", dt.date(2022, 7, 14)): ([0.4, 2.0], 2.0, 0.0),
        ("601601.SH", dt.date(2021, 6, 30)): ([0.1, 1.3], 1.3, 0.0),
        ("600600.SH", dt.date(2023, 7, 14)): ([0.5, 1.8], 1.8, 0.0),
        ("600720.SH", dt.date(2024, 6, 13)): ([0.1104, 0.257], 0.3674, 0.0),
        ("600989.SH", dt.date(2024, 7, 24)): ([0.265, 0.3158], 0.3158, 0.0),
        ("603259.SH", dt.date(2025, 5, 21)): ([0.35, 0.98169], 1.33169, 0.0),
    }
    frame = frame.unique()
    duplicates = frame.group_by("symbol", "ex_date").len().filter(pl.col("len") > 1)
    for symbol, ex_date, _ in duplicates.iter_rows():
        match = (pl.col("symbol") == symbol) & (pl.col("ex_date") == ex_date)
        group = frame.filter(match)
        if (symbol, ex_date) == ("300014.SZ", dt.date(2020, 6, 9)):
            # Company notice 2020-086 was published on June 2; the vendor
            # repeats the same final distribution under June 3 as well.
            expected = {
                "ann_date": [dt.date(2020, 6, 2), dt.date(2020, 6, 3)],
                "record_date": [dt.date(2020, 6, 8)], "pay_date": [ex_date],
                "share_list_date": [ex_date], "div_cash": [.170165], "share_ratio": [.9008738],
            }
            if group.height != 2 or any(sorted(group[c].unique().to_list()) != values
                                       for c, values in expected.items()):
                raise ValueError(f"Unexpected dividend implementation details: {symbol} {ex_date}")
            frame = pl.concat([frame.filter(~match), group.sort("ann_date").head(1)])
            continue
        if (symbol, ex_date) == ("003001.SZ", dt.date(2025, 7, 7)):
            # 2025-057 revises the same plan after record date but before ex-date.
            # Vendor backfills final amounts into both implementation-notice rows.
            expected = {
                "ann_date": [dt.date(2025, 6, 30), dt.date(2025, 7, 5)],
                "record_date": [dt.date(2025, 7, 4)], "pay_date": [ex_date],
                "share_list_date": [ex_date], "div_cash": [.2814904], "share_ratio": [.3992772],
            }
            if group.height != 2 or any(sorted(group[c].unique().to_list()) != values
                                       for c, values in expected.items()):
                raise ValueError(f"Unexpected dividend implementation details: {symbol} {ex_date}")
            frame = pl.concat([frame.filter(~match), group.sort("ann_date").tail(1)])
            continue
        resolution = resolutions.get((symbol, ex_date))
        if resolution is None:
            raise ValueError(f"Conflicting stock dividend implementations: {symbol} {ex_date}")
        amounts, cash, shares = resolution
        if (sorted(group["div_cash"].to_list()) != amounts
            or group.select("ann_date", "record_date", "pay_date").unique().height != 1
            or group["share_ratio"].sum() != shares):
            raise ValueError(f"Unexpected dividend implementation details: {symbol} {ex_date}")
        combined = group.sort("share_ratio", descending=True).head(1).with_columns(
            pl.lit(cash).alias("div_cash"), pl.lit(shares).alias("share_ratio"))
        frame = pl.concat([frame.filter(~match), combined])
    return frame.sort("symbol", "ex_date")


def prepare_stock_execution_inputs(
    *, data_root: Path, symbols: list[str], execution_dates: list[dt.date],
    start: dt.date, end: dt.date, output: Path,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Keep raw requests, then publish dividends, price bands, suspensions and instruments."""
    output.mkdir(parents=True, exist_ok=True)
    connector = TushareConnector(config_path=Path("configs/tushare.local.toml"))
    store = RawStore(data_root / "raw")
    cache: dict[tuple[str, str], Path] = {}
    for api in ("dividend", "stk_limit", "suspend_d", "stock_basic"):
        for path in sorted((data_root / "raw/tushare" / api).glob("date=*/*.json")):
            meta = json.loads(path.read_text(encoding="utf-8"))
            key = (api, json.dumps(meta["parameters"], sort_keys=True))
            cache[key] = path.with_suffix(".parquet")
    used = []

    def request(api: str, **params: str) -> pl.DataFrame:
        key = (api, json.dumps(params, sort_keys=True))
        if key in cache:
            path = cache[key]
            frame = pl.read_parquet(path)
        else:
            for attempt in range(3):
                try:
                    frame = connector.query_raw(api, **params)
                    break
                except Exception:
                    if attempt == 2:
                        raise RuntimeError(f"Tushare {api} request failed") from None
                    time.sleep(attempt + 1)
            path = store.write(source="tushare", table=api, frame=frame, parameters=params).data_path
            cache[key] = path
            time.sleep(0.35)
        used.append(str(path))
        return frame

    limits, suspensions = [], []
    for date in execution_dates:
        raw = request("stk_limit", trade_date=date.strftime("%Y%m%d"))
        if raw.is_empty() or raw.height >= 5800:
            raise ValueError("Missing or truncated stock price bands")
        limits.append(raw)
        suspensions.append(request("suspend_d", trade_date=date.strftime("%Y%m%d")))
    limit_frame = pl.concat(limits, how="diagonal_relaxed").select(
        pl.col("ts_code").alias("symbol"), pl.col("trade_date").str.to_date("%Y%m%d"),
        pl.col("up_limit").cast(pl.Float64), pl.col("down_limit").cast(pl.Float64),
    ).filter(pl.col("symbol").is_in(symbols))
    if limit_frame.select("symbol", "trade_date").is_duplicated().any():
        raise ValueError("Duplicate stock price bands")
    suspend_frame = pl.concat(suspensions, how="diagonal_relaxed")
    if suspend_frame.is_empty():
        suspend_frame = pl.DataFrame(schema={"symbol": pl.String, "trade_date": pl.Date})
    else:
        suspend_frame = suspend_frame.filter(pl.col("suspend_type") == "S").select(
            pl.col("ts_code").alias("symbol"), pl.col("trade_date").str.to_date("%Y%m%d"),
        ).unique().filter(pl.col("symbol").is_in(symbols))
    dividends = []
    for index, symbol in enumerate(symbols):
        frame = request("dividend", ts_code=symbol)
        if frame.height >= 2000:
            raise ValueError("Truncated stock dividends")
        if not frame.is_empty():
            dividends.append(frame)
        if (index + 1) % 50 == 0:
            print(f"Captured dividends {index + 1}/{len(symbols)}", flush=True)
    dividend_frame = pl.concat(dividends, how="diagonal_relaxed").filter(
        (pl.col("div_proc") == "实施") & pl.col("ex_date").is_not_null()
    ).select(
        pl.col("ts_code").alias("symbol"),
        pl.col("imp_ann_date").str.to_date("%Y%m%d").alias("ann_date"),
        pl.col("record_date").str.to_date("%Y%m%d"),
        pl.col("ex_date").str.to_date("%Y%m%d"),
        pl.col("pay_date").str.to_date("%Y%m%d"),
        pl.col("div_listdate").str.to_date("%Y%m%d").alias("share_list_date"),
        pl.col("cash_div_tax").cast(pl.Float64).fill_null(0.0).alias("div_cash"),
        pl.col("stk_div").cast(pl.Float64).fill_null(0.0).alias("share_ratio"),
    ).filter(pl.col("ex_date").is_between(start, end)).unique()
    dividend_frame = resolve_same_day_dividends(dividend_frame)
    if dividend_frame.filter(
        pl.col("ann_date").is_null() | pl.col("record_date").is_null()
        # Final implementation terms can be adjusted during the weekend between
        # record and ex-date. The account consumes them only on ex-date.
        | (pl.col("ann_date") > pl.col("ex_date"))
        | (pl.col("record_date") >= pl.col("ex_date"))
        | ((pl.col("div_cash") > 0) & (pl.col("pay_date").is_null() | (pl.col("pay_date") < pl.col("ex_date"))))
        | ((pl.col("share_ratio") > 0) & (pl.col("share_list_date").is_null() | (pl.col("share_list_date") < pl.col("ex_date"))))
    ).height:
        raise ValueError("Incomplete stock dividend dates")
    # 000793 restructuring shares go to the administrator/investors/creditors,
    # not ordinary holders (company announcement 2026-038, SZSE 2026-06-22).
    dividend_frame = dividend_frame.with_columns(pl.when(
        (pl.col("symbol") == "000793.SZ") & (pl.col("ex_date") == dt.date(2026, 6, 22))
    ).then(0.0).otherwise(pl.col("share_ratio")).alias("share_ratio"))
    basic = pl.concat([
        request("stock_basic", list_status=status, fields="ts_code,name,list_date,delist_date")
        .with_columns(pl.lit(status).alias("_request_list_status"))
        for status in ("L", "D", "P")
    ], how="diagonal_relaxed")
    instruments = pl.concat([TushareInstrumentMapper(m).map(basic) for m in ("SH", "SZ")]).filter(
        pl.col("symbol").is_in(symbols)
    )
    if instruments.height != len(symbols):
        raise ValueError("Stock instrument coverage missing")
    for name, frame in (("limits", limit_frame), ("suspensions", suspend_frame),
                        ("dividends", dividend_frame), ("instruments", instruments)):
        frame.write_parquet(output / f"{name}.parquet")
    (output / "sources.json").write_text(json.dumps(used, indent=2), encoding="utf-8")
    return limit_frame, suspend_frame, dividend_frame, instruments


def stock_session_states(
    *, bars: pl.DataFrame, limits: pl.DataFrame, suspensions: pl.DataFrame,
    sessions: list[dt.date], symbols: list[str], execution_dates: list[dt.date],
    slippage: float,
):
    """Use vendor bands on order sessions; absent quotes cannot execute."""
    from quant.backtest.rules import DailyMarketState

    quotes = {(r["trade_date"], r["symbol"]): r for r in bars.iter_rows(named=True)}
    bands = {(r["trade_date"], r["symbol"]): r for r in limits.iter_rows(named=True)}
    stopped = set(suspensions.select("trade_date", "symbol").iter_rows())
    order_dates = set(execution_dates)
    states = {}
    for date in sessions:
        for symbol in symbols:
            key = (date, symbol)
            bar = quotes.get(key)
            if bar is None or bar["volume"] <= 0 or key in stopped:
                states[key] = DailyMarketState(suspended=True)
            elif date in order_dates:
                band = bands.get(key)
                if band is None or band["down_limit"] is None or band["up_limit"] is None:
                    raise ValueError(f"Missing stock price band: {symbol} {date}")
                states[key] = DailyMarketState(
                    at_upper_limit=bar["open"] * (1 + slippage) >= band["up_limit"] - 1e-9,
                    at_lower_limit=bar["open"] * (1 - slippage) <= band["down_limit"] + 1e-9,
                )
            else:
                states[key] = DailyMarketState()
    return states
