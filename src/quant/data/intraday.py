"""Capture completed-session minute data and retain append-only supplier responses."""

import argparse
import datetime as dt
import json
import time
import tomllib
from pathlib import Path
from typing import Any, cast

import polars as pl

from quant.data.connectors.baostock import BaostockConnector
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
        result.write_parquet(path)
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


def _stock_job(args: tuple[str, str, str, list[dt.date]]) -> dict[str, Any]:
    data_root_text, symbol, end_text, expected_dates = args
    data_root, end = Path(data_root_text), dt.date.fromisoformat(end_text)
    directory = _directory(data_root, "baostock", symbol, "5m")
    coverage = directory / "coverage.json"
    prior = json.loads(coverage.read_text()) if coverage.exists() else {}
    existing_path = directory / "data.parquet"
    existing = pl.read_parquet(existing_path) if existing_path.exists() else None
    missing = set(expected_dates) - (set(existing["trade_date"]) if existing is not None else set())
    if prior.get("through", "") >= end_text and existing is not None and not missing:
        return {"symbol": symbol, "changed_rows": 0}
    start = dt.date.fromisoformat(prior["through"]) + dt.timedelta(days=1) if prior else dt.date(2020, 1, 1)
    if missing:
        start = min(start, min(missing))
        if existing is not None and not existing.is_empty():
            start = min(start, cast(dt.date, existing["trade_date"].max()))
    began = time.monotonic()
    changed, returned, raw_paths = 0, 0, []
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
                absent = {d for d in expected_dates if start <= d <= chunk_end} - set(frame["trade_date"])
                if absent:
                    raise ValueError(f"BaoStock {symbol} missing {len(absent)} known traded days; first {min(absent)}")
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        frame = add_session_quality(frame, data_root, "5m", symbol)
        changed += merge_bars(directory, frame)
        returned += frame.height
        raw_paths.append(str(snapshot.data_path))
        status = {"through": str(chunk_end), "raw": str(snapshot.data_path),
                  "returned_rows": returned, "changed_rows": changed,
                  "incomplete_days": frame.filter(~pl.col("session_complete"))["trade_date"].n_unique(),
                  "seconds": round(time.monotonic() - began, 2)}
        coverage.write_text(json.dumps(status), encoding="utf-8")
        start = chunk_end + dt.timedelta(days=1)
    return {"symbol": symbol, **status, "raw_paths": raw_paths}



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
                     yahoo: bool = True, workers: int = 1, limit: int | None = None) -> dict[str, Any]:
    if workers != 1 or (limit is not None and limit < 1):
        raise ValueError("BaoStock uses one connection; workers must be 1 and limit positive")
    results, errors = [], []
    if stocks:
        from quant.data.refresh_stocks import read_stock_data

        config = tomllib.loads(Path("configs/universe/stock_top800_5m.toml").read_text(encoding="utf-8"))
        symbols = config["symbols"][:limit]
        daily = read_stock_data(data_root=data_root, config=Path("configs/data/refresh.toml"),
                                table="bar_1d", start=dt.date(2020, 1, 1), end=end, symbols=symbols)
        expected = {symbol: group["trade_date"].to_list() for (symbol,), group in
                    daily.filter(pl.col("volume") > 0).group_by("symbol")}
        for index, symbol in enumerate(symbols, 1):
            try:
                result = _stock_job((str(data_root), symbol, str(end), expected.get(symbol, [])))
                results.append(result)
                print(f"BaoStock {index}/{len(symbols)} {symbol}: {result['changed_rows']} rows", flush=True)
            except Exception as exc:
                errors.append({"symbol": symbol, "error": str(exc)})
                print(f"BaoStock {index}/{len(symbols)} {symbol}: {exc}", flush=True)
    if yahoo:
        members = []
        for name in ("t0_etf_pool_v1", "hk_connect_watch_v1"):
            members += tomllib.loads(Path(f"configs/universe/{name}.toml").read_text(encoding="utf-8"))["members"]
        for member in members[:limit]:
            for frequency in ("1m", "5m", "60m"):
                try:
                    result = capture_yahoo(data_root, member, frequency, end)
                    results.append(result)
                    print(f"Yahoo {member['symbol']} {frequency}: {result['changed_rows']} rows", flush=True)
                except Exception as exc:
                    errors.append({"symbol": member["symbol"], "frequency": frequency, "error": str(exc)})
                time.sleep(0.3)
    summary = {"through": str(end), "completed_requests": len(results),
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
    args = parser.parse_args()
    end = latest_session(data_root=args.data_root, through=completed_date(args.to, dt.datetime.now(SHANGHAI)))
    result = refresh_intraday(data_root=args.data_root, end=end, stocks=args.stocks,
                              yahoo=args.yahoo, workers=args.workers, limit=args.limit)
    print(json.dumps({k: v for k, v in result.items() if k != "results"}, ensure_ascii=False))
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
