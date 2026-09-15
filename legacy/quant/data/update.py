"""日线增量更新 CLI。

示例：
python -m quant.data.update --date 2026-07-10 --symbols 000001.SZ 00700.HK
"""

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Sequence

from quant.data.base import BaseConnector
from quant.data.calendar import expected_open_dates
from quant.data.connectors import AkshareConnector, BaostockConnector, TushareConnector
from quant.data.mappers import (
    AdjustmentFactorMapper,
    AkshareBarMapper,
    BaostockAdjustmentFactorMapper,
    BaostockBarMapper,
    BarMapper,
    TushareAdjustmentFactorMapper,
    TushareBarMapper,
)
from quant.data.pipeline import BarUpdatePipeline, BarUpdateResult
from quant.data.storage import CleanAdjustmentFactorStore, CleanBarStore, RawStore


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="更新 AKShare 日线 raw/clean 数据")
    parser.add_argument("--date", required=True, type=dt.date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("--symbols", required=True, nargs="+", help="标准证券代码列表")
    parser.add_argument(
        "--source",
        choices=["tushare", "akshare", "baostock"],
        default="tushare",
        help="原始数据源",
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument(
        "--skip-calendar-check",
        action="store_true",
        help="仅用于日历尚未建成的诊断；正常更新不得跳过",
    )
    parser.add_argument(
        "--without-adjustment-factors",
        action="store_true",
        help="显式仅保存不复权行情；不得用于需要复权收益的研究",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """执行指定交易日的 AKShare 日线更新。"""
    args = build_parser().parse_args(argv)
    if not args.skip_calendar_check:
        _require_open_a_share_date(args.data_root, args.symbols, args.date)
    pipeline = build_pipeline(
        args.source,
        args.data_root,
        args.artifact_root,
        use_adjustment_factors=not args.without_adjustment_factors,
    )
    result = pipeline.update(
        symbols=args.symbols,
        start=args.date,
        end=args.date,
        expected_dates={args.date},
    )
    _print_result(result)
    return 0


def build_pipeline(
    source: str,
    data_root: Path,
    artifact_root: Path,
    *,
    use_adjustment_factors: bool = True,
) -> BarUpdatePipeline:
    """按数据源构建日线更新 pipeline。"""
    connector: BaseConnector
    mapper: BarMapper
    factor_mapper: AdjustmentFactorMapper | None = None
    factor_store: CleanAdjustmentFactorStore | None = None
    if source == "akshare":
        connector = AkshareConnector()
        mapper = AkshareBarMapper()
    elif source == "baostock":
        connector = BaostockConnector()
        mapper = BaostockBarMapper()
        if use_adjustment_factors:
            factor_mapper = BaostockAdjustmentFactorMapper()
            factor_store = CleanAdjustmentFactorStore(data_root / "clean" / "adjust_factor")
    elif source == "tushare":
        connector = TushareConnector()
        mapper = TushareBarMapper()
        if use_adjustment_factors:
            factor_mapper = TushareAdjustmentFactorMapper()
            factor_store = CleanAdjustmentFactorStore(data_root / "clean" / "adjust_factor")
    else:
        raise ValueError(f"未知数据源: {source}")
    return BarUpdatePipeline(
        connector=connector,
        mapper=mapper,
        raw_store=RawStore(data_root / "raw"),
        clean_store=CleanBarStore(data_root / "clean" / "bar_1d"),
        quality_root=artifact_root / "data_quality" / "bar_1d",
        factor_mapper=factor_mapper,
        factor_store=factor_store,
    )


def _print_result(result: BarUpdateResult) -> None:
    """输出 BarUpdateResult；保持 CLI JSON 字段稳定。"""
    print(
        json.dumps(
            {
                "snapshot_id": result.raw_snapshot.snapshot_id,
                "raw_path": str(result.raw_snapshot.data_path),
                "clean_rows": result.clean_rows,
                "quality_passed": result.quality_report.passed,
                "factor_raw_path": (
                    str(result.factor_snapshot.data_path) if result.factor_snapshot else None
                ),
                "factor_rows": result.factor_rows,
            },
            ensure_ascii=False,
        )
    )


def _require_open_a_share_date(data_root: Path, symbols: list[str], date: dt.date) -> None:
    """日线更新前必须由涉及市场的 clean 基础日历确认共同开市。"""
    if date not in expected_open_dates(data_root, symbols, date, date):
        markets = sorted({symbol.rsplit(".", maxsplit=1)[-1] for symbol in symbols})
        raise RuntimeError(f"{markets} {date} 为休市日，拒绝日线更新")


if __name__ == "__main__":
    raise SystemExit(main())
