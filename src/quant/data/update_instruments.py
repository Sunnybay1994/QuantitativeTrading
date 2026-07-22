"""沪深股票/ETF 证券主表更新 CLI。"""

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Sequence

from quant.data.connectors import BaostockConnector, HkexEtpConnector, TushareConnector
from quant.data.mappers import (
    BaostockInstrumentMapper,
    HkexEtpInstrumentMapper,
    TushareInstrumentMapper,
)
from quant.data.pipeline import HkexEtpInstrumentUpdatePipeline, InstrumentUpdatePipeline
from quant.data.pipeline import HkexTemporaryInstrumentUpdatePipeline
from quant.data.storage import CleanInstrumentStore, RawStore
from quant.data.temporary_instruments import load_hkex_temporary_counter_notice


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="更新交易所证券主表")
    parser.add_argument("--market", choices=["SH", "SZ", "HK"], required=True)
    parser.add_argument(
        "--source",
        choices=["tushare", "baostock", "hkex-etp", "hkex-notice"],
        default="tushare",
    )
    parser.add_argument("--as-of", type=dt.date.fromisoformat)
    parser.add_argument("--symbols", nargs="+")
    parser.add_argument("--notice-config", type=Path)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.source in {"hkex-etp", "hkex-notice"}:
        if args.market != "HK" or args.as_of is None or not args.symbols:
            raise ValueError(
                "HKEX_ETP_TARGETS_INVALID"
                if args.source == "hkex-etp"
                else "HK_TEMPORARY_TARGETS_INVALID"
            )
        targets = tuple(sorted(args.symbols))
        if len(targets) != len(args.symbols):
            raise ValueError(
                "HKEX_ETP_TARGETS_INVALID"
                if args.source == "hkex-etp"
                else "HK_TEMPORARY_TARGETS_INVALID"
            )
    if args.source == "hkex-etp":
        if args.notice_config is not None:
            raise ValueError("HKEX_ETP_TARGETS_INVALID")
        hkex_mapper = HkexEtpInstrumentMapper(target_symbols=targets, as_of=args.as_of)
        hkex_pipeline = HkexEtpInstrumentUpdatePipeline(
            connector=HkexEtpConnector(),
            mapper=hkex_mapper,
            raw_store=RawStore(args.data_root / "raw"),
            clean_store=CleanInstrumentStore(args.data_root / "clean" / "instrument"),
        )
        result = hkex_pipeline.update(target_symbols=targets, as_of=args.as_of)
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
    if args.source == "hkex-notice":
        if args.notice_config is None:
            raise ValueError("HK_TEMPORARY_NOTICE_INVALID")
        notice = load_hkex_temporary_counter_notice(args.notice_config)
        notice_pipeline = HkexTemporaryInstrumentUpdatePipeline(
            raw_store=RawStore(args.data_root / "raw"),
            clean_store=CleanInstrumentStore(args.data_root / "clean" / "instrument"),
        )
        result = notice_pipeline.update(
            notice=notice, target_symbols=targets, as_of=args.as_of
        )
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
    if args.as_of is not None or args.symbols is not None or args.notice_config is not None:
        raise ValueError("HKEX_ETP_TARGETS_INVALID")
    if args.source == "baostock" and args.market == "HK":
        raise ValueError("BaoStock 不支持港股证券主表")
    connector = TushareConnector() if args.source == "tushare" else BaostockConnector()
    mapper = (
        TushareInstrumentMapper(args.market)
        if args.source == "tushare"
        else BaostockInstrumentMapper(args.market)
    )
    pipeline = InstrumentUpdatePipeline(
        connector=connector,
        mapper=mapper,
        raw_store=RawStore(args.data_root / "raw"),
        clean_store=CleanInstrumentStore(args.data_root / "clean" / "instrument"),
    )
    result = pipeline.update(market=args.market)
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
