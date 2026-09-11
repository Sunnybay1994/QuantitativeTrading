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
from quant.data.factor_benchmark import refresh_factor_benchmark
from quant.data.intraday import refresh_intraday
from quant.data.industry_history import refresh_daily as refresh_industry
from quant.data.mappers import TushareCalendarMapper
from quant.data.refresh_etf_prices import refresh as refresh_etfs
from quant.data.refresh_stocks import refresh as refresh_stocks
from quant.data.storage import CleanCalendarStore, RawStore
from quant.data.update_disclosed_financials import refresh_daily as refresh_disclosed_financials

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
    now: dt.datetime | None = None, intraday: bool = True,
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
    minute_options: dict[str, Any] = {}
    minute_days = settings.get('intraday', {}).get('stock_lookback_days')
    if minute_days is not None:
        if type(minute_days) is not int or minute_days < 1:
            raise ValueError('Stock minute lookback must be a positive number of calendar days')
        minute_options['stock_from'] = through - dt.timedelta(days=minute_days-1)
    minutes = refresh_intraday(data_root=data_root, end=through, **minute_options) if intraday else {}
    benchmark = (refresh_factor_benchmark(data_root=data_root, config=config, end=end)
                 if settings.get("factor_benchmark_snapshot") else {"new_rows": 0})
    financials = {"message": "disabled", "new_rows": 0}
    if settings.get('financials', {}).get('enabled', False):
        with contextlib.redirect_stdout(io.StringIO()):
            financials = refresh_disclosed_financials(end=through, config=config, data_root=data_root,
                artifact_root=artifact_root, lookback_days=settings['financials']['lookback_days'])
    factors = {"years": [], "message": "disabled"}
    industry: dict[str, Any] = {'message': 'disabled', 'new_intervals': 0}
    if settings.get('industry', {}).get('enabled', False):
        with contextlib.redirect_stdout(io.StringIO()):
            industry = refresh_industry(data_root=data_root, end=end)
    if settings.get("factors", {}).get("enabled", False):
        if minutes.get("errors"):
            factors["message"] = "skipped: intraday input refresh failed"
        else:
            factors = refresh_factors(data_root=data_root, artifact_root=artifact_root,
                                      config=config, end=end, settings=settings["factors"],
                                      minute_start=(minute_options.get('stock_from', dt.date(2020, 1, 1))
                                                    if minutes.get('stock_changed_rows', 0) else None),
                                      industry_start=(dt.date.fromisoformat(industry['rebuild_from'])
                                                      if industry['new_intervals'] else None))
    quality: dict[str, Any] = {"errors": [], "message": "disabled"}
    if settings.get('quality', {}).get('enabled', False):
        from quant.data.daily_input_quality import run_quality
        from quant.factors.library import load_library

        definitions = load_library(Path(settings['factors']['library']), settings['factors'].get('selected', 'all'))
        battery = tomllib.loads(Path(settings['quality']['battery_config']).read_text(encoding='utf-8'))
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        quality = run_quality(data_root=data_root, config=config, end=end,
            factors=[{'id': row.id, 'family': row.family} for row in definitions], financials=financials,
            output=artifact_root/'data'/'input_quality'/stamp,
            lookback_sessions=settings['quality'].get('lookback_sessions', 5), minimum_symbols=battery['minimum_symbols'])
    changed = (stocks["new_dates"] or etfs["new_rows"] or etfs["new_bar_rows"] or limit_rows
               or minutes.get("changed_rows", 0) or benchmark["new_rows"] or factors["years"]
               or financials['new_rows'] or industry['new_intervals'])
    message = "partial" if minutes.get("errors") or quality['errors'] else "updated" if changed else "no-op"
    return {"latest_session": str(end), "message": message,
            "stock_new_dates": stocks["new_dates"], "stock_new_rows": stocks["new_rows"],
            "etf_price_new_rows": etfs["new_rows"], "etf_bar_new_rows": etfs["new_bar_rows"],
            "etf_limit_new_rows": limit_rows,
            "intraday_changed_rows": minutes.get("changed_rows", 0),
            "intraday_errors": minutes.get("errors", []),
            "factor_benchmark_new_rows": benchmark["new_rows"],
            "factor_benchmark_snapshot": benchmark.get("snapshot"),
            "factors": factors,
            "financials": financials,
            "industry": industry,
            "input_quality": quality,
            "stock_artifact": stocks.get("artifact_path"), "etf_artifact": etfs.get("artifact_path")}


def refresh_factors(*, data_root: Path, artifact_root: Path, config: Path,
                    end: dt.date, settings: dict[str, Any],
                    minute_start: dt.date | None = None,
                    industry_start: dt.date | None = None) -> dict[str, Any]:
    """Reuse the factor engine's incremental coverage, including unfinished labels."""
    # compute uses the completed-session date helpers in this module.
    from quant.factors.compute import run
    from quant.factors.library import load_library
    from quant.research.factor_intraday import minute_input_names

    with contextlib.redirect_stdout(io.StringIO()):
        result = run(data_root=data_root, refresh_config=config,
                     library=Path(settings["library"]), selected=settings.get("selected", "all"),
                     start=dt.date.fromisoformat(str(settings["start"])), end=end,
                     artifact_root=artifact_root)
        minute_rebuild = None
        industry_rebuild = None
        if minute_start is not None and minute_start <= end:
            definitions = load_library(Path(settings['library']), settings.get('selected', 'all'))
            selected = ','.join(row.id for row in definitions if minute_input_names((row.expr,)))
            if selected:
                minute_rebuild = run(data_root=data_root, refresh_config=config,
                    library=Path(settings['library']), selected=selected, rebuild=True,
                    start=max(minute_start, dt.date.fromisoformat(str(settings['start']))), end=end,
                    artifact_root=artifact_root)
        if industry_start is not None and industry_start <= end:
            definitions = load_library(Path(settings['library']), settings.get('selected', 'all'))
            selected = ','.join(row.id for row in definitions if 'ind_neutralize' in row.expr)
            if selected:
                industry_rebuild = run(data_root=data_root, refresh_config=config,
                    library=Path(settings['library']), selected=selected, rebuild=True,
                    start=max(industry_start, dt.date.fromisoformat(str(settings['start']))), end=end,
                    artifact_root=artifact_root)
    return {"message": "updated" if result["years"] or minute_rebuild or industry_rebuild else "no-op",
            "years": result["years"], "factor_count": result["factor_count"],
            "output": result["output"], "minute_rebuild": minute_rebuild, "industry_rebuild": industry_rebuild}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", default="today")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument("--config", type=Path, default=Path("configs/data/refresh.toml"))
    parser.add_argument("--intraday", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    result = run_refresh(to=args.to, data_root=args.data_root, artifact_root=args.artifact_root,
                         config=args.config, intraday=args.intraday)
    print(json.dumps(result, ensure_ascii=False))
    if result["intraday_errors"] or result['input_quality']['errors']:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
