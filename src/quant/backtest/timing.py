"""信号可知日到最早可成交日的时间对齐。"""

import polars as pl

from quant.domain import TargetWeightSchema, TradeCalendarSchema


def schedule_next_trading_day(
    targets: pl.DataFrame, calendars: pl.DataFrame
) -> pl.DataFrame:
    """按证券所属市场把收盘后目标安排到下一开市日。

    没有后续开市日的尾部信号会被丢弃，绝不退化为 ``as_of`` 当日成交。
    """
    clean_targets = TargetWeightSchema.validate(targets)
    clean_calendars = TradeCalendarSchema.validate(calendars)
    open_dates = {
        market: sorted(frame.filter(pl.col("is_open")).get_column("date").to_list())
        for (market,), frame in clean_calendars.partition_by(
            "market", as_dict=True, maintain_order=True
        ).items()
    }
    rows: list[dict[str, object]] = []
    for row in clean_targets.iter_rows(named=True):
        market = row["symbol"].rsplit(".", maxsplit=1)[-1]
        execution_date = next(
            (date for date in open_dates.get(market, []) if date > row["as_of"]),
            None,
        )
        if execution_date is not None:
            rows.append({**row, "execution_date": execution_date})
    if not rows:
        return pl.DataFrame(
            schema={
                "as_of": pl.Date,
                "strategy": pl.String,
                "strategy_version": pl.String,
                "symbol": pl.String,
                "weight": pl.Float64,
                "execution_date": pl.Date,
            }
        )
    return pl.DataFrame(rows).sort(["execution_date", "symbol"])
