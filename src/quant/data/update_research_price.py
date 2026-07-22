"""更新 ETF 后复权研究价格；不进入账户核算路径。"""

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Sequence

from quant.data.calendar import expected_open_dates
from quant.data.connectors import AkshareConnector
from quant.data.mappers import AkshareResearchPriceMapper
from quant.data.research_price import ResearchPriceUpdatePipeline
from quant.data.storage import CleanResearchPriceStore, RawStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="更新 AKShare ETF 后复权研究价格")
    parser.add_argument("--start", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--end", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dates = expected_open_dates(args.data_root, args.symbols, args.start, args.end)
    if not dates:
        raise RuntimeError("指定区间没有开市日")
    pipeline = ResearchPriceUpdatePipeline(
        connector=AkshareConnector(),
        mapper=AkshareResearchPriceMapper(),
        raw_store=RawStore(args.data_root / "raw"),
        clean_store=CleanResearchPriceStore(
            args.data_root / "clean" / "research_price_1d"
        ),
        quality_root=args.artifact_root / "data_quality" / "research_price_1d",
    )
    result = pipeline.update(
        symbols=args.symbols,
        start=args.start,
        end=args.end,
        expected_dates=dates,
    )
    print(json.dumps({
        "raw_path": str(result.raw_snapshot.data_path),
        "clean_rows": result.clean_rows,
        "quality_passed": result.quality_report.passed,
        "adjustment": "HFQ",
        "usage": "research_only",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
