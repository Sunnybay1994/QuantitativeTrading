"""clean 交易日历驱动的数据更新门禁。"""

import datetime as dt
from pathlib import Path

import polars as pl


def expected_open_dates(
    data_root: Path,
    symbols: list[str],
    start: dt.date,
    end: dt.date,
) -> set[dt.date]:
    """返回涉及市场的共同开市日，并要求各 clean 日历完整覆盖自然日区间。"""
    if start > end:
        raise ValueError("start 不得晚于 end")
    symbol_markets = {symbol.rsplit(".", maxsplit=1)[-1] for symbol in symbols}
    unsupported = symbol_markets - {"SH", "SZ", "HK"}
    if unsupported:
        raise RuntimeError(f"尚无可用的市场日历: {sorted(unsupported)}")
    if not symbol_markets:
        raise ValueError("symbols 不能为空")

    expected_days = (end - start).days + 1
    open_dates_by_market: dict[str, set[dt.date]] = {}
    for market in sorted(symbol_markets):
        path = data_root / "clean" / "trade_calendar" / f"market={market}" / "data.parquet"
        if not path.exists():
            raise RuntimeError(f"缺少 {market} clean 交易日历，请先运行 quant.data.update_calendar")
        calendar = pl.read_parquet(path).filter(pl.col("date").is_between(start, end))
        if calendar.height != expected_days:
            raise RuntimeError(
                f"{market} 交易日历未完整覆盖 {start} 至 {end}: "
                f"expected={expected_days}, actual={calendar.height}"
            )
        open_dates_by_market[market] = set(
            calendar.filter(pl.col("is_open")).get_column("date").to_list()
        )

    mainland = [open_dates_by_market[m] for m in ("SH", "SZ") if m in open_dates_by_market]
    if len(mainland) == 2 and mainland[0] != mainland[1]:
        raise RuntimeError(f"沪深开市日不一致: {open_dates_by_market}")
    return set.intersection(*open_dates_by_market.values())
