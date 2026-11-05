"""Daily financial quality columns, recalculated when a statement becomes known."""

import ast
import datetime as dt
from collections.abc import Callable

import polars as pl

from quant.factors.pit_quality import PIT_QUALITY_FACTOR_NAMES
from quant.factors.cash_yield import compute_cash_yield
from quant.factors.annual_zscore import compute_annual_zscore
from quant.factors.annual_profitability import COMPONENTS, rank_annual_profitability
from quant.research.pit_quality_research import build_pit_quality_signal_values
from quant.research.financial_observations import DIRECT, direct_snapshot, scoped_histories
from quant.research.financial_price_observations import (
    PROFITABILITY_NAMES, Z_COLUMNS, annual_profitability_snapshot, annual_z_snapshot, cash_flow_snapshot,
)
from quant.research.financial_ratio_observations import RATIO_FIELDS, ratio_histories, ratio_snapshot
from quant.research.monthly_annual_fscore import build_monthly_annual_fscore


def _known_names() -> set[str]:
    return (set(DIRECT) | set(PIT_QUALITY_FACTOR_NAMES) | set(PROFITABILITY_NAMES)
            | set(RATIO_FIELDS) | {"pit_cash_yield_ttm", "pit_annual_zscore", "pit_annual_fscore"})


def financial_input_names(expressions: tuple[str, ...]) -> tuple[str, ...]:
    """Find named financial inputs even inside a rank or composite expression."""
    known = _known_names()
    return tuple(sorted({node.id for expression in expressions
                         for node in ast.walk(ast.parse(expression, mode="eval"))
                         if isinstance(node, ast.Name) and node.id in known}))


def _carry_events(
    panel: pl.DataFrame, publications: pl.DataFrame,
    snapshot: Callable[[dt.date, tuple[str, ...]], pl.DataFrame],
    columns: tuple[str, ...], maximum_age_months: int | None = None,
) -> pl.DataFrame:
    dates = tuple(panel["trade_date"].unique().sort().to_list())
    symbols = tuple(panel["symbol"].unique().sort().to_list())
    if not dates or not symbols:
        raise ValueError("Financial factors require a nonempty daily panel")
    publications = publications.filter(pl.col("symbol").is_in(symbols))
    updates = [snapshot(dates[0], symbols)]
    for previous, date in zip(dates, dates[1:]):
        changed = tuple(publications.filter(
            (pl.col("available_date") >= previous) & (pl.col("available_date") < date)
        )["symbol"].unique().sort().to_list())
        if changed:
            updates.append(snapshot(date, changed))
    events = pl.concat(updates).rename({"trade_date": "_financial_event_date"}).sort(
        "_financial_event_date", "symbol")
    result = panel.sort("trade_date", "symbol").join_asof(
        events, left_on="trade_date", right_on="_financial_event_date", by="symbol",
        strategy="backward", check_sortedness=False,
    ).drop("_financial_event_date")
    valid = pl.col("close").is_finite().fill_null(False)
    if maximum_age_months is not None:
        valid = valid & (pl.col("financial_period_end") >= pl.col("trade_date").dt.offset_by(
            f"-{maximum_age_months}mo"))
    result = result.with_columns(pl.when(valid).then(pl.col(name)).otherwise(None).alias(name)
                                 for name in columns)
    if "financial_period_end" in events.columns:
        result = result.drop("financial_period_end")
    return result.sort("symbol", "trade_date")


def attach_quality_factors(panel: pl.DataFrame, histories: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Carry even invalid new observations; never fill through a later null score.

    The existing selector owns report revision conflicts and quarter chains.
    Its strict-before announcement rule also applies to daily close signals.
    """
    symbols = tuple(panel["symbol"].unique().sort().to_list())
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

    return _carry_events(panel, publications, snapshot, PIT_QUALITY_FACTOR_NAMES)


def attach_financial_factors(
    panel: pl.DataFrame, histories: dict[str, pl.DataFrame], names: tuple[str, ...],
    *, preliminary_history: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Attach registered financial families with announcement updates and daily expiry."""
    unknown = set(names) - _known_names()
    if unknown:
        raise ValueError(f"Unknown financial factors: {sorted(unknown)}")
    original = panel.columns
    requested = set(names)
    profitability = bool(requested & set(PROFITABILITY_NAMES))
    if set(names) & set(PIT_QUALITY_FACTOR_NAMES):
        panel = attach_quality_factors(panel, histories)
    for name in sorted(set(names) & set(DIRECT)):
        frames = scoped_histories(histories, DIRECT[name][1])
        publications = pl.concat([frame.select("symbol", "available_date")
                                  for frame in frames.values()]).unique()
        if name=='sue_prelim' and preliminary_history is not None:
            publications=pl.concat([publications,preliminary_history.select('symbol','available_date')]).unique()

        def snapshot(date: dt.date, symbols: tuple[str, ...], factor: str = name) -> pl.DataFrame:
            options={'preliminary_history':preliminary_history} if factor=='sue_prelim' else {}
            return direct_snapshot(factor, frames, date, symbols,**options)

        panel = _carry_events(panel, publications, snapshot, (name,), DIRECT[name][2])
    for name in sorted(requested & set(RATIO_FIELDS)):
        frames = ratio_histories(name, histories)
        publications = pl.concat([frame.select("symbol", "available_date")
                                  for frame in frames.values()]).unique()

        def ratio(date: dt.date, symbols: tuple[str, ...], factor: str = name) -> pl.DataFrame:
            return ratio_snapshot(factor, frames, date, symbols)

        panel = _carry_events(panel, publications, ratio, (name,))
    keys = ["symbol", "trade_date"]

    def publications_for(tables: tuple[str, ...]) -> pl.DataFrame:
        return pl.concat([histories[table].select("symbol", "available_date") for table in tables]).unique()

    if "pit_cash_yield_ttm" in requested:
        cached = _carry_events(panel, publications_for(("cashflow",)),
            lambda date, symbols: cash_flow_snapshot(histories, date, symbols), ("ocf_ttm",))
        values = compute_cash_yield(cached.select(*keys, "ocf_ttm"), panel)
        panel = panel.join(values.select(*keys, "pit_cash_yield_ttm"), on=keys, validate="1:1")
    if "pit_annual_zscore" in requested:
        cached = _carry_events(panel, publications_for(("income", "balancesheet")),
            lambda date, symbols: annual_z_snapshot(histories, date, symbols), Z_COLUMNS, 18)
        values = compute_annual_zscore(cached.select(*keys, *Z_COLUMNS), panel)
        panel = panel.join(values.select(*keys, "pit_annual_zscore"), on=keys, validate="1:1")
    if profitability:
        cached = _carry_events(panel, publications_for(("income", "balancesheet", "cashflow")),
            lambda date, symbols: annual_profitability_snapshot(histories, date, symbols), COMPONENTS, 18)
        ranked = cached.select(*keys, *COMPONENTS).group_by("trade_date").map_groups(rank_annual_profitability)
        values = ranked.select(*keys,
            *[pl.col(name).alias(f"pit_annual_{name}") for name in COMPONENTS if name != "cfoa"],
            "pit_annual_profitability")
        panel = panel.join(values, on=keys, validate="1:1")
    if "pit_annual_fscore" in requested:
        event_history = histories["share_change_events"]
        fscore_publications = [publications_for(("income", "balancesheet", "cashflow")),
            event_history.select("symbol", pl.col("ann_date").alias("available_date"))]
        if "notice_available_date" in event_history.columns:
            fscore_publications.append(event_history.select("symbol", pl.col("notice_available_date").alias("available_date")))

        def fscore(date: dt.date, symbols: tuple[str, ...]) -> pl.DataFrame:
            frames = {table: histories[table].filter(pl.col("symbol").is_in(symbols))
                      for table in ("income", "balancesheet", "cashflow", "share_change_events", "share_change_coverage")}
            return build_monthly_annual_fscore(income_history=frames["income"], cash_history=frames["cashflow"],
                balance_history=frames["balancesheet"], events=frames["share_change_events"],
                event_coverage=frames["share_change_coverage"], signal_dates=(date,), candidate_symbols=symbols
            ).factors.select(*keys, "financial_period_end", "pit_annual_fscore")

        panel = _carry_events(panel, pl.concat(fscore_publications).unique(), fscore, ("pit_annual_fscore",), 18)
    return panel.select(*original, *names).sort("symbol", "trade_date")
