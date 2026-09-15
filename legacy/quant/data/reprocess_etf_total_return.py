"""用已留档 BaoStock 不复权 ETF 价格和 AKShare 分红重建总回报价格。"""

import argparse
import datetime as dt
import importlib
import json
import time
from pathlib import Path
from typing import Any, Sequence

import polars as pl

from quant.data.calendar import expected_open_dates
from quant.data.mappers import AkshareResearchPriceMapper
from quant.data.research_price import ResearchPriceUpdatePipeline
from quant.data.storage import CleanResearchPriceStore, RawStore


class ArchivedEtfTotalReturnConnector:
    """组合既有不复权价格 raw 与新浪累计分红；不重新下载价格。"""

    source = "baostock_akshare"

    def __init__(self, raw_path: Path | list[Path], client: Any | None = None) -> None:
        self.raw_paths = [raw_path] if isinstance(raw_path, Path) else raw_path
        if not self.raw_paths:
            raise ValueError("raw_path 不能为空")
        self.client = client or importlib.import_module("akshare")
        path_sources = {
            source
            for path in self.raw_paths
            for source in ("akshare", "baostock")
            if source in path.parts
        }
        if path_sources == {"akshare", "baostock"}:
            self.source = "akshare_baostock"
        elif path_sources == {"akshare"}:
            self.source = "akshare_sina"

    def fetch_research_price_1d(
        self,
        symbols: list[str],
        start: dt.date,
        end: dt.date,
        *,
        adjustment: str = "hfq",
    ) -> pl.DataFrame:
        if adjustment != "hfq":
            raise ValueError("编排协议只允许请求 hfq；本连接器会透明生成总回报 fallback")
        raw_frames: list[pl.DataFrame] = []
        for path in self.raw_paths:
            frame = pl.read_parquet(path)
            normalized_date = (
                pl.col("date").str.to_date()
                if frame.schema["date"] == pl.String
                else pl.col("date").cast(pl.Date)
            )
            raw_frames.append(
                frame.with_columns(normalized_date.alias("_normalized_date"))
            )
        prices = pl.concat(raw_frames, how="diagonal_relaxed").filter(
            pl.col("_request_symbol").is_in(symbols)
            & pl.col("_normalized_date").is_between(start, end, closed="both")
        )
        if "tradestatus" in prices.columns:
            prices = prices.filter(
                pl.col("tradestatus").is_null() | (pl.col("tradestatus") == "1")
            )
        present = set(prices.get_column("_request_symbol").unique().to_list())
        missing = sorted(set(symbols) - present)
        if missing:
            raise ValueError("既有价格 raw 缺少证券: " + ", ".join(missing))
        frames: list[pl.DataFrame] = []
        for symbol in symbols:
            code, market = symbol.rsplit(".", maxsplit=1)
            events = _fetch_dividend_events(
                self.client, vendor_symbol=f"{market.lower()}{code}"
            )
            symbol_prices = prices.filter(
                pl.col("_request_symbol") == symbol
            ).with_columns(pl.col("_normalized_date").alias("日期"))
            frames.append(
                symbol_prices.join(
                    events.select("日期", "_cash_dividend"),
                    on="日期",
                    how="left",
                ).select(
                    "_request_symbol",
                    "日期",
                    pl.col("close").alias("收盘"),
                    pl.col("_cash_dividend").fill_null(0.0),
                    pl.lit("total_return_dividend").alias("_adjustment"),
                    pl.lit(f"{self.source}_raw+fund_etf_dividend_sina").alias(
                        "_endpoint"
                    ),
                    pl.lit(
                        json.dumps([str(path) for path in self.raw_paths], ensure_ascii=False)
                    ).alias("_price_raw_path"),
                )
            )
        return pl.concat(frames, how="vertical_relaxed")


def _fetch_dividend_events(client: Any, *, vendor_symbol: str) -> pl.DataFrame:
    errors: list[str] = []
    for attempt, delay in enumerate((0.0, 1.0, 3.0), start=1):
        if delay:
            time.sleep(delay)
        try:
            frame = client.fund_etf_dividend_sina(symbol=vendor_symbol)
            raw = frame if isinstance(frame, pl.DataFrame) else pl.from_pandas(frame)
        except Exception as exc:
            errors.append(f"attempt={attempt}:{type(exc).__name__}")
            continue
        if raw.is_empty():
            return pl.DataFrame(
                schema={"日期": pl.Date, "_cash_dividend": pl.Float64}
            )
        events = (
            raw.select(
                pl.col("日期").cast(pl.Date),
                pl.col("累计分红").cast(pl.Float64).alias("_cumulative_dividend"),
            )
            .sort("日期")
            .with_columns(
                pl.col("_cumulative_dividend")
                .diff()
                .fill_null(pl.col("_cumulative_dividend"))
                .alias("_cash_dividend")
            )
        )
        if events.filter(pl.col("_cash_dividend") < 0).height:
            raise ValueError(f"累计分红非单调: {vendor_symbol}")
        return events
    raise RuntimeError(
        f"ETF 分红事件请求失败: {vendor_symbol}; " + "; ".join(errors)
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从既有不复权 raw 重建 ETF 总回报研究价格")
    parser.add_argument("--raw-path", type=Path, nargs="+", required=True)
    parser.add_argument("--start", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--end", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    args = parser.parse_args(argv)
    missing_paths = [path for path in args.raw_path if not path.exists()]
    if missing_paths:
        raise FileNotFoundError(missing_paths[0])
    dates = expected_open_dates(args.data_root, args.symbols, args.start, args.end)
    connector = ArchivedEtfTotalReturnConnector(args.raw_path)
    pipeline = ResearchPriceUpdatePipeline(
        connector=connector,
        mapper=AkshareResearchPriceMapper(source=connector.source),
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
        "price_raw_paths": [str(path) for path in args.raw_path],
        "clean_rows": result.clean_rows,
        "quality_passed": result.quality_report.passed,
        "adjustment": "TOTAL_RETURN_DIVIDEND",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
