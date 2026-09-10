"""Daily financial quality columns, recalculated when a statement becomes known."""

import datetime as dt

import polars as pl

from quant.factors.pit_quality import PIT_QUALITY_FACTOR_NAMES
from quant.research.pit_quality_research import build_pit_quality_signal_values


def attach_quality_factors(panel: pl.DataFrame, histories: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Carry even invalid new observations; never fill through a later null score.

    The existing selector owns report revision conflicts and quarter chains.
    Its strict-before announcement rule also applies to daily close signals.
    """
    dates = tuple(panel["trade_date"].unique().sort().to_list())
    symbols = tuple(panel["symbol"].unique().sort().to_list())
    if not dates or not symbols:
        raise ValueError("Financial factors require a nonempty daily panel")
    structural = ["symbol", "ann_date", "f_ann_date", "available_date", "end_date",
                  "report_type", "comp_type", "update_flag", "source"]
    required = {"income": ["n_income", "n_income_attr_p"],
                "balancesheet": ["total_assets", "total_hldr_eqy_exc_min_int"],
                "cashflow": ["n_cashflow_act"]}
    # Revision identity must use this family's fields, not unrelated columns
    # added by another financial consumer sharing the input scan.
    frames = {name: histories[name].filter(pl.col("symbol").is_in(symbols)).select(
        *structural, *columns) for name, columns in required.items()}
    publications = pl.concat([frame.select("symbol", "available_date")
                              for frame in frames.values()]).unique()

    def snapshot(date: dt.date, changed: tuple[str, ...]) -> pl.DataFrame:
        selected = {name: frame.filter(pl.col("symbol").is_in(changed))
                    for name, frame in frames.items()}
        return build_pit_quality_signal_values(
            income_history=selected["income"], balance_history=selected["balancesheet"],
            cash_history=selected["cashflow"], signal_dates=(date,),
            candidate_symbols=changed, allowed_report_types=("1",),
        ).factors.select("symbol", "trade_date", *PIT_QUALITY_FACTOR_NAMES)

    updates = [snapshot(dates[0], symbols)]
    for previous, date in zip(dates, dates[1:]):
        changed = tuple(publications.filter(
            (pl.col("available_date") >= previous) & (pl.col("available_date") < date)
        )["symbol"].unique().sort().to_list())
        if changed:
            updates.append(snapshot(date, changed))
    events = pl.concat(updates).rename({"trade_date": "_financial_event_date"}).sort(
        "_financial_event_date", "symbol")
    return panel.sort("trade_date", "symbol").join_asof(
        events, left_on="trade_date", right_on="_financial_event_date", by="symbol",
        strategy="backward", check_sortedness=False,
    ).drop("_financial_event_date").with_columns(
        pl.when(pl.col("close").is_finite().fill_null(False)).then(pl.col(name))
        .otherwise(None).alias(name) for name in PIT_QUALITY_FACTOR_NAMES
    ).sort("symbol", "trade_date")
