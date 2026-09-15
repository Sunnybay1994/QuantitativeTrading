"""沪深交易日历更新 CLI。"""

import argparse
import datetime as dt
import json
from functools import partial
from pathlib import Path
from typing import Callable, Sequence

import polars as pl

from quant.data.connectors import BaostockConnector, TushareConnector
from quant.data.hkex_calendar import apply_hkex_calendar_notice, load_hkex_calendar_notice
from quant.data.mappers import BaostockCalendarMapper, TushareCalendarMapper
from quant.data.pipeline import CalendarUpdatePipeline
from quant.data.storage import CleanCalendarStore, RawStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="更新交易所基础交易日历")
    parser.add_argument("--market", choices=["SH", "SZ", "HK"], required=True)
    parser.add_argument("--source", choices=["tushare", "baostock"], default="tushare")
    parser.add_argument("--start", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--end", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--hkex-notice", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.start > args.end:
        raise ValueError("start 不得晚于 end")
    if args.source == "baostock" and args.market == "HK":
        raise ValueError("BaoStock 不支持港股交易日历")
    if args.market == "HK" and args.start.year != args.end.year:
        raise ValueError("港股基础日历更新必须按自然年执行")
    connector = TushareConnector() if args.source == "tushare" else BaostockConnector()
    mapper = (
        TushareCalendarMapper(args.market)
        if args.source == "tushare"
        else BaostockCalendarMapper(args.market)
    )
    clean_transform: Callable[[pl.DataFrame], pl.DataFrame] | None = None
    if args.market == "HK":
        notice_path = args.hkex_notice or Path(
            f"configs/calendars/hk_market_{args.start.year}.toml"
        )
        notice = load_hkex_calendar_notice(notice_path)
        clean_transform = partial(apply_hkex_calendar_notice, notice=notice)
    pipeline = CalendarUpdatePipeline(
        connector=connector,
        mapper=mapper,
        raw_store=RawStore(args.data_root / "raw"),
        clean_store=CleanCalendarStore(args.data_root / "clean" / "trade_calendar"),
        clean_transform=clean_transform,
    )
    result = pipeline.update(market=args.market, start=args.start, end=args.end)
    print(
        json.dumps(
            {
                "snapshot_id": result.raw_snapshot.snapshot_id,
                "raw_path": str(result.raw_snapshot.data_path),
                "clean_rows": result.clean_rows,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
