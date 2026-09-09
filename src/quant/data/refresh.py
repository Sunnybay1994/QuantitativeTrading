"""One command to refresh completed-session stock and ETF data."""

import argparse
import contextlib
import datetime as dt
import io
import json
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.calendar import expected_open_dates
from quant.data.connectors.tushare import TushareConnector
from quant.data.etf_limits import refresh_limits
from quant.data.mappers import TushareCalendarMapper
from quant.data.refresh_etf_prices import refresh as refresh_etfs
from quant.data.refresh_stocks import refresh as refresh_stocks
from quant.data.storage import CleanCalendarStore, RawStore

SHANGHAI = dt.timezone(dt.timedelta(hours=8))


def completed_date(requested: str, now: dt.datetime) -> dt.date:
    """Do not consume an unfinished daily close or the daily-basic update window."""
    local = now.astimezone(SHANGHAI)
    requested_date = local.date() if requested == "today" else dt.date.fromisoformat(requested)
    if requested_date > local.date():
        raise ValueError("Requested date is in the future")
    if requested_date == local.date() and local.hour < 17:
        return requested_date - dt.timedelta(days=1)
    return requested_date


def latest_session(*, data_root: Path, through: dt.date) -> dt.date:
    start = through - dt.timedelta(days=40)
    for market in ("SH", "SZ"):
        path = data_root / "clean/trade_calendar" / f"market={market}/data.parquet"
        existing = pl.read_parquet(path) if path.exists() else pl.DataFrame()
        covered = (not existing.is_empty()
                   and existing.filter(pl.col("date").is_between(start, through)).height
                   == (through - start).days + 1)
        if not covered:
            connector = TushareConnector(config_path=Path("configs/tushare.local.toml"))
            raw = connector.fetch_trade_calendar(market, start, through)
            RawStore(data_root / "raw").write(
                source="tushare", table="trade_calendar", frame=raw,
                parameters={"market": market, "start": str(start), "end": str(through)},
            )
            CleanCalendarStore(data_root / "clean/trade_calendar").upsert(
                TushareCalendarMapper(market).map(raw)
            )
    return max(expected_open_dates(data_root, ["000001.SZ", "600000.SH"], start, through))


def run_refresh(
    *, to: str, data_root: Path, artifact_root: Path, config: Path,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    through = completed_date(to, now or dt.datetime.now(SHANGHAI))
    end = latest_session(data_root=data_root, through=through)
    settings = tomllib.loads(config.read_text(encoding="utf-8"))
    # A failed stage raises immediately; the next invocation reuses complete daily partitions.
    with contextlib.redirect_stdout(io.StringIO()):
        stocks = refresh_stocks(end=end, data_root=data_root, artifact_root=artifact_root, config=config)
        etfs = refresh_etfs(end=end, data_root=data_root, artifact_root=artifact_root,
                            config=Path(settings["etf_config"]))
    universe = tomllib.loads(Path(settings["etf_config"]).read_text(encoding="utf-8"))["universe"]
    symbols = sorted({s for value in universe.values() if isinstance(value, list) for s in value})
    limit_rows = refresh_limits(data_root=data_root, symbols=symbols, end=end)
    changed = stocks["new_dates"] or etfs["new_rows"] or etfs["new_bar_rows"] or limit_rows
    return {"latest_session": str(end), "message": "updated" if changed else "no-op",
            "stock_new_dates": stocks["new_dates"], "stock_new_rows": stocks["new_rows"],
            "etf_price_new_rows": etfs["new_rows"], "etf_bar_new_rows": etfs["new_bar_rows"],
            "etf_limit_new_rows": limit_rows,
            "stock_artifact": stocks.get("artifact_path"), "etf_artifact": etfs.get("artifact_path")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", default="today")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument("--config", type=Path, default=Path("configs/data/refresh.toml"))
    args = parser.parse_args()
    print(json.dumps(run_refresh(to=args.to, data_root=args.data_root,
                                  artifact_root=args.artifact_root, config=args.config),
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
