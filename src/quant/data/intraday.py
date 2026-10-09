"""Capture completed-session minute data and retain append-only supplier responses."""

import argparse
import datetime as dt
import json
import time
import tomllib
import uuid
from pathlib import Path
from typing import Any, cast

import polars as pl

from quant.data.connectors.baostock import BaostockConnector
from quant.data.connectors.baostock_access import BaoStockAccessPaused
from quant.data.connectors.yahoo_intraday import fetch_chart
from quant.data.intraday_bars import TZ, normalize_baostock, normalize_yahoo, validate_bars
from quant.data.storage import RawStore


def _directory(data_root: Path, source: str, symbol: str, frequency: str) -> Path:
    return data_root / "clean/bar_intraday" / f"freq={frequency}" / f"source={source}" / f"symbol={symbol}"


def merge_bars(directory: Path, incoming: pl.DataFrame) -> int:
    """Clean may incorporate supplier revisions; original captures always remain available."""
    path = directory / "data.parquet"
    old = pl.read_parquet(path) if path.exists() else incoming.head(0)
    old_values = old.drop("session_complete") if "session_complete" in old.columns else old
    new_values = incoming.drop("session_complete") if "session_complete" in incoming.columns else incoming
    changed = new_values.join(old_values, on=list(new_values.columns), how="anti", nulls_equal=True).height
    result = pl.concat([old, incoming], how="diagonal_relaxed").unique(
        subset=["symbol", "bar_start"], keep="last", maintain_order=True,
    ).sort("bar_start")
    validate_bars(result)
    directory.mkdir(parents=True, exist_ok=True)
    if changed or not path.exists():
        temporary = path.with_name(f'.{uuid.uuid4().hex}.parquet')
        try:
            result.write_parquet(temporary)
            # Windows readers can briefly hold the destination without delete sharing.
            # Keep the previous clean file intact if the bounded retry is exhausted.
            for attempt in range(11):
                try:
                    temporary.replace(path)
                    break
                except PermissionError:
                    if attempt == 10:
                        raise
                    time.sleep(0.1)
        finally:
            temporary.unlink(missing_ok=True)
    return changed


def add_session_quality(frame: pl.DataFrame, data_root: Path, frequency: str, symbol: str) -> pl.DataFrame:
    market = symbol.split(".")[1]
    calendar = pl.read_parquet(data_root / f"clean/trade_calendar/market={market}/data.parquet")
    if market == "HK":
        half_days = tomllib.loads(Path("configs/calendars/hk_intraday_half_days.toml").read_text())["dates"]
        calendar = calendar.with_columns(
            (pl.col("is_half_day") | pl.col("date").is_in(half_days)).alias("is_half_day"))
    sessions = calendar.filter(pl.col("is_open")).select(pl.col("date").alias("trade_date"), "is_half_day")
    if frame.join(sessions, on="trade_date", how="anti").height:
        raise ValueError("Minute bars fall outside the available exchange calendar")
    hk = market == "HK"
    regular = (7 if hk else 5) if frequency == "60m" else (330 if hk else 240) // int(frequency[:-1])
    half = 3 if frequency == "60m" else 150 // int(frequency[:-1])
    expected = pl.when(pl.col("is_half_day") & hk).then(half).otherwise(regular)
    result = frame.join(sessions, on="trade_date", how="left").with_columns(
        (pl.len().over("trade_date") == expected).alias("session_complete")
    )
    if hk:
        result = result.with_columns(
            pl.when(pl.col("is_half_day")).then(pl.min_horizontal(
                "bar_end", pl.col("bar_end").dt.truncate("1d") + pl.duration(hours=12)
            )).otherwise(pl.col("bar_end")).alias("bar_end"))
    return result.drop("is_half_day")


def _complete_stock_dates(frame: pl.DataFrame) -> set[dt.date]:
    """Require valid bars on the exact two A-share five-minute session grids."""
    try:
        validate_bars(frame)
    except (ValueError, pl.exceptions.PolarsError):
        return set()  # A dirty partition is not completeness evidence.
    minute = pl.col('bar_start').dt.hour().cast(pl.Int32)*60 + pl.col('bar_start').dt.minute()
    valid_slot = (((minute >= 570) & (minute < 690)) | ((minute >= 780) & (minute < 900)))
    valid_slot = (valid_slot & (minute % 5 == 0)
                  & (pl.col('bar_start').dt.second() == 0)
                  & (pl.col('bar_start').dt.nanosecond() == 0)
                  & (pl.col('bar_start').dt.date() == pl.col('trade_date'))
                  & ((pl.col('bar_end')-pl.col('bar_start')) == pl.duration(minutes=5)))
    counts = frame.group_by('trade_date').agg(pl.len().alias('bars'), valid_slot.all().alias('valid'))
    return set(counts.filter((pl.col('bars') == 48) & pl.col('valid'))['trade_date'])


def _stock_job(args: tuple[str, str, str, list[dt.date]], *,
               start_date: dt.date | None = None,
               daily_reference: pl.DataFrame | None = None) -> dict[str, Any]:
    from quant.data.realtime import single_writer
    with single_writer(Path(args[0])/'clean/bar_intraday/freq=5m/source=baostock'/f'symbol={args[1]}'/'writer.lock'):
        return _stock_job_locked(args, start_date=start_date, daily_reference=daily_reference)


def _stock_job_locked(args: tuple[str, str, str, list[dt.date]], *,
                      start_date: dt.date | None = None,
                      daily_reference: pl.DataFrame | None = None) -> dict[str, Any]:
    data_root_text, symbol, end_text, expected_dates = args
    data_root, end = Path(data_root_text), dt.date.fromisoformat(end_text)
    directory = _directory(data_root, "baostock", symbol, "5m")
    if start_date is not None and start_date > end:
        raise ValueError("Stock capture start must not exceed end")
    expected_dates = [day for day in expected_dates if day <= end and (start_date is None or day >= start_date)]
    coverage = directory / ("recent_coverage.json" if start_date is not None else "coverage.json")
    prior = json.loads(coverage.read_text()) if coverage.exists() else {}
    existing_path = directory / "data.parquet"
    existing = None
    if existing_path.exists():
        scan = pl.scan_parquet(existing_path)
        if start_date is not None:
            scan = scan.filter(pl.col('trade_date').is_between(start_date, end))
        existing = scan.collect()
    if existing is not None and existing.filter(pl.col('symbol') != symbol).height:
        raise ValueError('Foreign symbol in intraday partition; cannot establish coverage')
    missing = set(expected_dates) - (_complete_stock_dates(existing) if existing is not None else set())
    fallback_dates = []
    if missing and daily_reference is not None:
        from quant.data.factor_intraday_inputs import read_factor_minute_inputs

        reference = daily_reference.filter(pl.col('trade_date').is_in(sorted(missing)))
        for frame in read_factor_minute_inputs(data_root, reference):
            accepted = _complete_stock_dates(frame.filter(pl.col('daily_reconciled').fill_null(False)))
            fallback_dates.extend(sorted(accepted & missing))
            missing.difference_update(accepted)
        if not missing:
            return {'symbol': symbol, 'changed_rows': 0,
                    'validated_alternate_dates': [str(day) for day in fallback_dates]}
    if expected_dates and existing is not None and not missing:
        return {"symbol": symbol, "changed_rows": 0}
    start = min(missing) if missing else start_date or dt.date(2020, 1, 1)
    began = time.monotonic()
    changed, returned, raw_paths = 0, 0, []
    complete_through = min(prior.get("through", str(start - dt.timedelta(days=1))),
                           str(start - dt.timedelta(days=1)))
    if missing:
        complete_through = min(complete_through, str(min(missing) - dt.timedelta(days=1)))
    while start <= end:
        chunk_end = min(end, dt.date(start.year, 12, 31))
        for attempt in range(3):
            try:
                raw = BaostockConnector().fetch_intraday(symbol, start, chunk_end)
                snapshot = RawStore(data_root / "raw").write(
                    source="baostock_intraday", table=symbol, frame=raw,
                    parameters={"symbol": symbol, "frequency": "5m", "start": str(start), "end": str(chunk_end)},
                )
                frame = normalize_baostock(raw, symbol).filter(pl.col("trade_date").is_between(start, chunk_end))
                break
            except BaoStockAccessPaused:
                # A shared lock/budget/latch pause is source-wide, not a bad
                # symbol. Repeating it for thousands of members cannot recover.
                raise
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        frame = add_session_quality(frame, data_root, "5m", symbol)
        changed += merge_bars(directory, frame)
        # Supplier response alone cannot certify a merged partition containing
        # old invalid/extra timestamps. Recheck what was actually published.
        published = pl.read_parquet(directory / 'data.parquet')
        missing.difference_update(_complete_stock_dates(published))
        unresolved = sorted(day for day in missing if day <= chunk_end)
        if expected_dates and not unresolved:
            complete_through = str(chunk_end)
        returned += frame.height
        raw_paths.append(str(snapshot.data_path))
        status = {"through": complete_through, "attempted_through": str(chunk_end),
                  "coverage_verified": bool(expected_dates) and not missing,
                  "missing_traded_dates": [str(day) for day in unresolved], "raw": str(snapshot.data_path),
                  "returned_rows": returned, "changed_rows": changed,
                  "incomplete_days": frame.filter(~pl.col("session_complete"))["trade_date"].n_unique(),
                  "seconds": round(time.monotonic() - began, 2)}
        if start_date is not None:
            status["from"] = str(start_date)
        coverage.write_text(json.dumps(status), encoding="utf-8")
        start = chunk_end + dt.timedelta(days=1)
    if missing:
        raise ValueError(f"BaoStock {symbol} missing complete bars for {len(missing)} known traded days; first {min(missing)}; "
                         f"available bars preserved through {end}")
    return {"symbol": symbol, **status, "raw_paths": raw_paths,
            "validated_alternate_dates": [str(day) for day in fallback_dates]}



def capture_yahoo(data_root: Path, member: dict[str, Any], frequency: str, end: dt.date) -> dict[str, Any]:
    symbol = member["symbol"]
    directory = _directory(data_root, "yahoo", symbol, frequency)
    coverage = directory / "coverage.json"
    prior = json.loads(coverage.read_text()) if coverage.exists() else {}
    if prior.get("through", "") >= str(end) and (directory / "data.parquet").exists():
        return {"symbol": symbol, "frequency": frequency, "changed_rows": 0}
    payload = fetch_chart(member["yahoo_symbol"], frequency)
    now = dt.datetime.now(TZ)
    raw_dir = data_root / "raw/yahoo_intraday" / symbol / frequency / f"date={now.date()}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / (now.strftime("%H%M%S%f") + ".json")
    with raw_path.open("x", encoding="utf-8") as output:
        json.dump(payload, output)
    frame = normalize_yahoo(payload, symbol, frequency, now).filter(pl.col("trade_date") <= end)
    if frame.is_empty():
        raise ValueError(f"No completed Yahoo bars for {symbol} {frequency}")
    market = symbol.split(".")[1]
    calendar = pl.read_parquet(data_root / f"clean/trade_calendar/market={market}/data.parquet")
    last_session = cast(dt.date, calendar.filter(pl.col("is_open") & (pl.col("date") <= end))["date"].max())
    if cast(dt.date, frame["trade_date"].max()) < last_session:
        raise ValueError(f"Yahoo latest session missing for {symbol} {frequency}")
    frame = add_session_quality(frame, data_root, frequency, symbol)
    changed = merge_bars(directory, frame)
    status = {"through": str(end), "raw": str(raw_path), "changed_rows": changed,
              "first_date": str(frame["trade_date"].min()), "last_date": str(frame["trade_date"].max()),
              "returned_rows": frame.height,
              "incomplete_days": frame.filter(~pl.col("session_complete"))["trade_date"].n_unique()}
    coverage.write_text(json.dumps(status), encoding="utf-8")
    return {"symbol": symbol, "frequency": frequency, **status}


def refresh_intraday(*, data_root: Path, end: dt.date, stocks: bool = True,
                     yahoo: bool = True, workers: int = 1, limit: int | None = None,
                     stock_from: dt.date | None = None, progress=None,
                     refresh_config: Path = Path('configs/data/refresh.toml'),
                     required_stocks_only: bool = False) -> dict[str, Any]:
    if workers != 1 or (limit is not None and limit < 1):
        raise ValueError("BaoStock uses one connection; workers must be 1 and limit positive")
    if stock_from is not None and (not stocks or stock_from > end):
        raise ValueError("Stock start requires stocks enabled and a date at or before end")
    results, errors, deferred_symbols = [], [], []
    if stocks:
        from quant.data.refresh_stocks import read_stock_data

        from quant.data.market_universe import bao_members
        symbols = [row['symbol'] for row in bao_members(data_root)][:limit]
        daily = read_stock_data(data_root=data_root, config=refresh_config,
                                table="bar_1d", start=stock_from or dt.date(2020, 1, 1), end=end, symbols=symbols)
        expected = {symbol: group["trade_date"].to_list() for (symbol,), group in
                    daily.filter(pl.col("volume") > 0).group_by("symbol")}
        if required_stocks_only:
            symbols = [symbol for symbol in symbols if symbol in expected]
        references = (daily.partition_by('symbol', as_dict=True) if required_stocks_only else {})
        if progress:
            progress({'source': 'BaoStock', 'completed': 0, 'total': len(symbols), 'failed': 0})
        for index, symbol in enumerate(symbols, 1):
            try:
                result = _stock_job((str(data_root), symbol, str(end), expected.get(symbol, [])),
                                    start_date=stock_from,
                                    **({'daily_reference': references[(symbol,)]} if required_stocks_only else {}))
                results.append(result)
                print(f"BaoStock {index}/{len(symbols)} {symbol}: {result['changed_rows']} rows", flush=True)
            except Exception as exc:
                errors.append({"symbol": symbol, "error": str(exc)})
                print(f"BaoStock {index}/{len(symbols)} {symbol}: {exc}", flush=True)
                if isinstance(exc, BaoStockAccessPaused):
                    deferred_symbols = symbols[index:]
                    if progress:
                        progress({'source': 'BaoStock', 'completed': index, 'total': len(symbols),
                                  'failed': len(errors), 'deferred': len(deferred_symbols)})
                    break
            if progress:
                progress({'source': 'BaoStock', 'completed': index, 'total': len(symbols),
                          'failed': len(errors)})
    stock_changed_rows = sum(result['changed_rows'] for result in results)
    alternate_dates = [day for result in results for day in result.get('validated_alternate_dates', [])]
    if yahoo:
        members = []
        for name in ("t0_etf_pool_v1", "hk_connect_watch_v1", "daily_etf_execution_watch_v1"):
            members += tomllib.loads(Path(f"configs/universe/{name}.toml").read_text(encoding="utf-8"))["members"]
        yahoo_completed = 0
        yahoo_failed = 0
        if progress:
            progress({'source': 'Yahoo', 'completed': 0, 'total': 3*len(members[:limit]), 'failed': 0})
        for member in members[:limit]:
            for frequency in ("1m", "5m", "60m"):
                try:
                    result = capture_yahoo(data_root, member, frequency, end)
                    results.append(result)
                    print(f"Yahoo {member['symbol']} {frequency}: {result['changed_rows']} rows", flush=True)
                except Exception as exc:
                    errors.append({"symbol": member["symbol"], "frequency": frequency, "error": str(exc)})
                    yahoo_failed += 1
                yahoo_completed += 1
                if progress:
                    progress({'source': 'Yahoo', 'completed': yahoo_completed,
                              'total': 3*len(members[:limit]), 'failed': yahoo_failed})
                time.sleep(0.3)
    summary = {"through": str(end), "completed_requests": len(results),
               "required_stocks_only": required_stocks_only,
               "deferred_stock_symbols": deferred_symbols,
               "stock_alternate_from": min(alternate_dates) if alternate_dates else None,
               "stock_from": str(stock_from) if stock_from is not None else None,
               "stock_changed_rows": stock_changed_rows,
               "changed_rows": sum(r["changed_rows"] for r in results), "errors": errors, "results": results}
    output = Path("artifacts/data_quality/intraday")
    output.mkdir(parents=True, exist_ok=True)
    (output / (dt.datetime.now(TZ).strftime("%Y%m%dT%H%M%S%f") + ".json")).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    from quant.data.refresh import SHANGHAI, completed_date, latest_session

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", default="today")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--stocks", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--yahoo", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--stock-from", type=dt.date.fromisoformat,
                        help="Capture only this stock date range; preserve full-history gap tracking")
    args = parser.parse_args()
    end = latest_session(data_root=args.data_root, through=completed_date(args.to, dt.datetime.now(SHANGHAI)))
    result = refresh_intraday(data_root=args.data_root, end=end, stocks=args.stocks,
                              yahoo=args.yahoo, workers=args.workers, limit=args.limit, stock_from=args.stock_from)
    print(json.dumps({k: v for k, v in result.items() if k != "results"}, ensure_ascii=False))
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
