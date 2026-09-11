"""Capture the stock execution facts needed by a concrete monthly backtest."""

import datetime as dt
import json
import time
from pathlib import Path

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.mappers import TushareInstrumentMapper
from quant.data.storage import RawStore


def deduplicate_dividend_notices(frame: pl.DataFrame) -> pl.DataFrame:
    """Same reporting period and identical terms are one implemented plan.

    Keep the latest implementation notice; do not move revised terms earlier.
    Different periods or economic terms still require explicit resolution.
    """
    # The downstream mapper already treats absent cash in share-only plans as zero.
    frame = frame.with_columns(*[pl.col(c).fill_null(0.0) for c in ("cash_div", "cash_div_tax") if c in frame.columns])
    keys = [column for column in frame.columns if column not in {"ann_date", "imp_ann_date"}]
    return frame.sort("imp_ann_date", nulls_last=True).unique(subset=keys, keep="last", maintain_order=True)


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
        ("601088.SH", dt.date(2017, 7, 10)): ([2.51, 2.97], 2.97, 0.0),
        ("601966.SH", dt.date(2025, 7, 10)): ([0.014, 0.07], 0.084, 0.0),
        ("601966.SH", dt.date(2024, 6, 14)): ([0.091, 0.286], 0.377, 0.0),
        ("600317.SH", dt.date(2014, 6, 16)): ([0.329, 0.529], 0.529, 2.0),
        ("002043.SZ", dt.date(2026, 6, 1)): ([0.132, 0.18], 0.312, 0.0),
        ("000738.SZ", dt.date(2013, 6, 14)): ([0.021, 0.041], 0.062, 0.0),
        ("600741.SH", dt.date(2010, 6, 18)): ([0.0491, 0.275], 0.3241, 0.0),
        ("301039.SZ", dt.date(2026, 7, 6)): ([0.14, 0.21], 0.35, 0.0),
        ("301308.SZ", dt.date(2026, 6, 2)): ([0.3467605, 0.6439837], 0.9907442, 0.0),
    }
    frame = frame.unique()
    duplicates = frame.group_by("symbol", "ex_date").len().filter(pl.col("len") > 1)
    for symbol, ex_date, _ in duplicates.iter_rows():
        match = (pl.col("symbol") == symbol) & (pl.col("ex_date") == ex_date)
        group = frame.filter(match)
        if (symbol, ex_date) == ("600462.SH", dt.date(2012,11,2)):
            if (group.height != 2 or group["share_ratio"].to_list() != [.3,.3]
                or sorted(group["share_list_date"].to_list()) != [dt.date(2012,11,5),dt.date(2012,11,19)]
                or group["ann_date"].unique().to_list() != [dt.date(2012,10,31)]
                or group["record_date"].unique().to_list() != [dt.date(2012,10,25)]
                or group["div_cash"].to_list() != [0.,0.]
                or group.drop("share_list_date").unique().height != 1):
                raise ValueError("Unexpected Shixian restructuring distribution")
            # Ordinary holders surrender 20% of existing shares; the 30%
            # capital expansion belongs entirely to investors/creditors.
            # Recognize on the session after the Oct 29 completion notice.
            corrected = group.head(1).with_columns(
                pl.lit(dt.date(2012,10,30)).alias("ann_date"),
                pl.lit(dt.date(2012,10,30)).alias("ex_date"),
                pl.lit(dt.date(2012,2,8)).alias("record_date"),
                pl.lit(None, dtype=pl.Date).alias("share_list_date"),
                pl.lit(-.2).alias("share_ratio"))
            frame = pl.concat([frame.filter(~match), corrected])
            continue
        restructuring = {
            ("000818.SZ", dt.date(2011,1,25)): ([.4,1.],.4),
            ("000615.SZ", dt.date(2025,12,29)): ([.1,1.34278],.1),
        }.get((symbol, ex_date))
        if restructuring is not None:
            # Total capital expansion differs from ordinary shareholders' entitlement.
            ratios, ordinary_ratio = restructuring
            if (sorted(group["share_ratio"].to_list()) != ratios
                or group["div_cash"].to_list() != [0.,0.]
                or group.drop("share_ratio").unique().height != 1):
                raise ValueError(f"Unexpected restructuring distribution: {symbol} {ex_date}")
            frame = pl.concat([frame.filter(~match), group.filter(pl.col("share_ratio") == ordinary_ratio)])
            continue
        if (symbol, ex_date) == ("600211.SH", dt.date(2010,9,7)):
            if (group.height != 2 or group["share_ratio"].to_list() != [.1,.1]
                or sorted(group["ann_date"].to_list()) != [dt.date(2010,6,24),dt.date(2010,9,1)]
                or sorted(group["share_list_date"].to_list()) != [ex_date,dt.date(2010,9,8)]
                or group.drop("ann_date","share_list_date").unique().height != 1):
                raise ValueError(f"Unexpected share reform distribution: {symbol} {ex_date}")
            selected = group.filter(pl.col("ann_date") == dt.date(2010,9,1))
            if selected["share_list_date"].item() != dt.date(2010,9,8):
                raise ValueError("Unexpected share reform listing date")
            frame = pl.concat([frame.filter(~match), selected])
            continue
        if (symbol, ex_date) == ("000033.SZ", dt.date(2016,4,15)):
            if (sorted(group["share_ratio"].to_list()) != [.3045457,.30454572]
                or sorted(group["share_list_date"].to_list()) != [ex_date,dt.date(2017,5,24)]
                or group.drop("share_ratio","share_list_date").unique().height != 1):
                raise ValueError(f"Unexpected restructuring distribution: {symbol} {ex_date}")
            # Initial notice keeps new shares non-tradable while listing is suspended.
            selected = group.filter(pl.col("share_list_date") == dt.date(2017,5,24))
            if selected["share_ratio"].item() != .3045457:
                raise ValueError("Unexpected new-share ratio")
            frame = pl.concat([frame.filter(~match), selected])
            continue
        if (symbol, ex_date) == ("300325.SZ", dt.date(2016, 6, 16)):
            # Share issuance changed the implemented cash from .04 to .03937.
            if (sorted(group["div_cash"].to_list()) != [.03937,.04]
                or sorted(group["ann_date"].to_list()) != [dt.date(2016,6,7),dt.date(2016,6,8)]
                or group["share_ratio"].to_list() != [0.,0.]
                or group.drop("ann_date","div_cash").unique().height != 1):
                raise ValueError(f"Unexpected dividend implementation details: {symbol} {ex_date}")
            frame = pl.concat([frame.filter(~match), group.filter(pl.col("div_cash") == .03937)])
            continue
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


def ordinary_holder_distributions(frame: pl.DataFrame) -> pl.DataFrame:
    """Exclude verified restructuring shares that ordinary shareholders do not receive."""
    for symbol, date, ratio in (
        ("000035.SZ", dt.date(2012, 12, 3), .2596),
        ("000155.SZ", dt.date(2016, 12, 14), 1.7021276),
        ("000520.SZ", dt.date(2014, 7, 31), .5),
        ("000912.SZ", dt.date(2018, 7, 30), 1.6803419),
        ("000972.SZ", dt.date(2013, 2, 25), .6),
        ("002260.SZ", dt.date(2020, 9, 25), 1.1),
        ("300362.SZ", dt.date(2021, 6, 15), 2.5502742),
        ("002219.SZ", dt.date(2022, 6, 23), .75),
        ("002309.SZ", dt.date(2024, 12, 24), 2.45),
        ("000793.SZ", dt.date(2026, 6, 22), 1.2),
    ):
        match = (pl.col("symbol") == symbol) & (pl.col("ex_date") == date)
        event = frame.filter(match)
        if event.height and (event.height != 1 or event["share_ratio"].item() != ratio
                             or event["div_cash"].item() != 0.0):
            raise ValueError(f"Unexpected restructuring distribution: {symbol} {date}")
        frame = frame.with_columns(pl.when(match).then(0.0).otherwise(pl.col("share_ratio")).alias("share_ratio"))
    match = (pl.col("symbol") == "300116.SZ") & (pl.col("ex_date") == dt.date(2020, 4, 1))
    event = frame.filter(match)
    if event.height:
        if (event.height != 1 or event["share_ratio"].item() != .85
                or event["div_cash"].item() != 0.0
                or event["record_date"].item() != dt.date(2020, 3, 31)):
            raise ValueError("Unexpected Jianrui restructuring distribution")
        # Ordinary holders receive 0.5 per 10, not the estate's 8.5 per 10.
        # June 5 confirms completion; conservatively release next session.
        frame = frame.with_columns(
            pl.when(match).then(.05).otherwise(pl.col("share_ratio")).alias("share_ratio"),
            pl.when(match).then(dt.date(2020, 6, 8)).otherwise(pl.col("share_list_date")).alias("share_list_date"),
        )
    return frame.with_columns((~match).alias("adjust_share_price"))


def restore_historical_instruments(instruments: pl.DataFrame) -> pl.DataFrame:
    """Restore old trading codes omitted from the vendor's current master."""
    for old, current, name, changed in (
        ("000022.SZ", "001872.SZ", "深赤湾A", dt.date(2018, 12, 26)),
        ("000043.SZ", "001914.SZ", "中航善达", dt.date(2019, 12, 16)),
        ("300114.SZ", "302132.SZ", "中航电测", dt.date(2025, 2, 17)),
    ):
        if old in instruments["symbol"]:
            continue
        successor = instruments.filter(pl.col("symbol") == current)
        if successor.height == 1:
            historical = successor.with_columns(
                pl.lit(old).alias("symbol"), pl.lit(name).alias("name"),
                pl.lit(changed).alias("delist_date"), pl.lit("DELISTED").alias("status"),
            )
            instruments = pl.concat([instruments, historical])
    return instruments


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
    dividend_raw = pl.concat(dividends, how="diagonal_relaxed").filter(
        (pl.col("div_proc") == "实施") & pl.col("ex_date").is_not_null()
    )
    dividend_frame = deduplicate_dividend_notices(dividend_raw).select(
        pl.col("ts_code").alias("symbol"),
        pl.col("imp_ann_date").str.to_date("%Y%m%d").alias("ann_date"),
        pl.col("record_date").str.to_date("%Y%m%d"),
        pl.col("ex_date").str.to_date("%Y%m%d"),
        pl.col("pay_date").str.to_date("%Y%m%d"),
        pl.col("div_listdate").str.to_date("%Y%m%d").alias("share_list_date"),
        pl.col("cash_div_tax").cast(pl.Float64).fill_null(0.0).alias("div_cash"),
        pl.col("stk_div").cast(pl.Float64).fill_null(0.0).alias("share_ratio"),
    ).filter(pl.col("ex_date").is_between(start, end) | (
        (pl.col("symbol") == "600462.SH") & (pl.col("ex_date") == dt.date(2012,11,2))
        & pl.lit(start <= dt.date(2012,10,30) <= end)
    )).unique()
    dividend_frame = resolve_same_day_dividends(dividend_frame).filter(pl.col("ex_date").is_between(start, end))
    dividend_frame = ordinary_holder_distributions(dividend_frame)
    invalid_dates = dividend_frame.filter(
        pl.col("ann_date").is_null() | pl.col("record_date").is_null()
        # Final implementation terms can be adjusted during the weekend between
        # record and ex-date. The account consumes them only on ex-date.
        | (pl.col("ann_date") > pl.col("ex_date"))
        | (pl.col("record_date") >= pl.col("ex_date"))
        | ((pl.col("div_cash") > 0) & (pl.col("pay_date").is_null() | (pl.col("pay_date") < pl.col("ex_date"))))
        | ((pl.col("share_ratio") > 0) & (pl.col("share_list_date").is_null() | (pl.col("share_list_date") < pl.col("ex_date"))))
    )
    if invalid_dates.height:
        examples = invalid_dates.select("symbol", "ex_date").head(5).to_dicts()
        raise ValueError(f"Incomplete stock dividend dates: {examples}")
    basic = pl.concat([
        request("stock_basic", list_status=status, fields="ts_code,name,list_date,delist_date")
        .with_columns(pl.lit(status).alias("_request_list_status"))
        for status in ("L", "D", "P")
    ], how="diagonal_relaxed")
    instruments = restore_historical_instruments(pl.concat([
        TushareInstrumentMapper(m).map(basic) for m in ("SH", "SZ")])).filter(
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
