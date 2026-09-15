"""港股通官方名单、调整事件与深港通交易日历更新 CLI。"""

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any, Sequence

import polars as pl

from quant.data.connect_market import ConnectMarketPipeline
from quant.data.connectors import SseConnectConnector, SzseConnectConnector
from quant.data.storage import (
    CleanConnectCalendarStore,
    CleanConnectEventStore,
    CleanConnectSnapshotStore,
    RawStore,
)
from quant.data.sse_connect_calendar import (
    build_sse_connect_calendar,
    load_calendar_notice,
    notice_rules_frame,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="更新港股通官方基础数据")
    parser.add_argument("--route", choices=["SH_CONNECT", "SZ_CONNECT"], required=True)
    parser.add_argument("--table", choices=["snapshot", "events", "calendar"], required=True)
    parser.add_argument("--start", type=dt.date.fromisoformat)
    parser.add_argument("--end", type=dt.date.fromisoformat)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--calendar-config", type=Path)
    parser.add_argument(
        "--replace-clean",
        action="store_true",
        help="仅 --table events：原子替换该 route 的 clean 事件（不 concat 旧行）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.replace_clean and args.table != "events":
        raise ValueError("--replace-clean 只允许与 --table events 同用")
    if args.table == "calendar" and (args.start is None or args.end is None):
        raise ValueError("calendar 必须提供 --start 和 --end")
    if args.table == "calendar" and args.route == "SH_CONNECT":
        sh_result = _update_sh_calendar(args)
        print(json.dumps(sh_result, ensure_ascii=False))
        return 0
    connector = SseConnectConnector() if args.route == "SH_CONNECT" else SzseConnectConnector()
    stores: dict[str, Any] = {
        "snapshot": CleanConnectSnapshotStore(args.data_root / "clean/connect_snapshot"),
        "events": CleanConnectEventStore(args.data_root / "clean/connect_event"),
        "calendar": CleanConnectCalendarStore(args.data_root / "clean/connect_calendar"),
    }
    pipeline = ConnectMarketPipeline(
        connector=connector, raw_store=RawStore(args.data_root / "raw"),
        clean_root=stores[args.table],
    )
    clean_mode = "REPLACE_ROUTE" if args.replace_clean else "UPSERT"
    if args.table == "snapshot":
        result = pipeline.update_snapshot()
    elif args.table == "events":
        result = pipeline.update_events(replace_clean=args.replace_clean)
    else:
        result = pipeline.update_calendar(args.start, args.end)
    print(
        json.dumps(
            {
                "raw_path": str(result.snapshot.data_path),
                "clean_rows": result.clean_rows,
                "clean_mode": clean_mode,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _update_sh_calendar(args: argparse.Namespace) -> dict[str, object]:
    assert args.start is not None and args.end is not None
    if args.start.year != args.end.year:
        raise ValueError("沪港通公告日历一次只构建一个自然年")
    config_path = args.calendar_config or Path(
        f"configs/calendars/sh_connect_{args.start.year}.toml"
    )
    notice = load_calendar_notice(config_path)
    base_path = args.data_root / "clean/trade_calendar/market=SH/data.parquet"
    if not base_path.exists():
        raise FileNotFoundError(f"缺少沪市基础日历: {base_path}")
    clean = build_sse_connect_calendar(
        pl.read_parquet(base_path), notice, start=args.start, end=args.end
    )
    raw_snapshot = RawStore(args.data_root / "raw").write(
        source="sse",
        table="connect_calendar_notice_rules",
        frame=notice_rules_frame(notice),
        parameters={
            "route": notice.route,
            "start": args.start,
            "end": args.end,
            "announcement_url": notice.announcement_url,
            "announcement_id": notice.announcement_id,
            "published_date": notice.published_date,
            "config_path": str(config_path),
        },
    )
    rows = CleanConnectCalendarStore(
        args.data_root / "clean/connect_calendar"
    ).upsert(clean)
    return {
        "raw_path": str(raw_snapshot.data_path),
        "clean_rows": rows,
        "clean_mode": "UPSERT",
    }


if __name__ == "__main__":
    raise SystemExit(main())
