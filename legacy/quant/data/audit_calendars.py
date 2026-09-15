"""交易所基础日历与沪/深港股通服务日历一致性审计。"""

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Sequence

import polars as pl


def audit_calendar_frames(
    sh_connect: pl.DataFrame,
    sz_connect: pl.DataFrame,
    sh_market: pl.DataFrame,
    sz_market: pl.DataFrame,
    hk_market: pl.DataFrame,
) -> dict[str, int]:
    """返回路由差异和“服务开通但任一基础市场休市”的违规计数。"""
    route_join = sh_connect.select(
        "date", pl.col("is_open").alias("sh_open"), pl.col("is_half_day").alias("sh_half")
    ).join(
        sz_connect.select(
            "date", pl.col("is_open").alias("sz_open"), pl.col("is_half_day").alias("sz_half")
        ),
        on="date",
        how="full",
        coalesce=True,
    )
    missing_route_dates = route_join.filter(
        pl.col("sh_open").is_null() | pl.col("sz_open").is_null()
    ).height
    route_status_differences = route_join.filter(
        (pl.col("sh_open") != pl.col("sz_open"))
        | (pl.col("sh_half") != pl.col("sz_half"))
    ).height

    def violations(connect: pl.DataFrame, mainland: pl.DataFrame) -> int:
        joined = connect.select("date", pl.col("is_open").alias("connect_open")).join(
            mainland.select("date", pl.col("is_open").alias("mainland_open")),
            on="date", how="left",
        ).join(
            hk_market.select("date", pl.col("is_open").alias("hk_open")),
            on="date", how="left",
        )
        return joined.filter(
            pl.col("connect_open")
            & (
                ~pl.col("mainland_open").fill_null(False)
                | ~pl.col("hk_open").fill_null(False)
            )
        ).height

    return {
        "dates": route_join.height,
        "missing_route_dates": missing_route_dates,
        "route_status_differences": route_status_differences,
        "sh_connect_market_violations": violations(sh_connect, sh_market),
        "sz_connect_market_violations": violations(sz_connect, sz_market),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="审计双路由港股通日历")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    args = parser.parse_args(argv)
    start, end = dt.date(args.year, 1, 1), dt.date(args.year, 12, 31)

    def read(path: Path) -> pl.DataFrame:
        if not path.exists():
            raise FileNotFoundError(path)
        return pl.read_parquet(path).filter(
            pl.col("date").is_between(start, end, closed="both")
        )

    clean = args.data_root / "clean"
    report = audit_calendar_frames(
        read(clean / "connect_calendar/route=SH_CONNECT/data.parquet"),
        read(clean / "connect_calendar/route=SZ_CONNECT/data.parquet"),
        read(clean / "trade_calendar/market=SH/data.parquet"),
        read(clean / "trade_calendar/market=SZ/data.parquet"),
        read(clean / "trade_calendar/market=HK/data.parquet"),
    )
    output = args.artifact_root / "data_quality/calendar" / f"{args.year}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp.json")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"report_path": str(output), **report}, ensure_ascii=False))
    return 1 if any(value for key, value in report.items() if key != "dates") else 0


if __name__ == "__main__":
    raise SystemExit(main())

