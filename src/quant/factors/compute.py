"""Compute a library batch on full-market history, one calendar year at a time."""

from __future__ import annotations

import argparse
import ast
import bisect
import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.factor_panels import (
    available_sessions, check_definition, panel_complete, panel_ready, read_coverage, read_factor_inputs, read_factor_industry,
    write_panel,
    read_factor_financial_history,
)
from quant.data.refresh import SHANGHAI, completed_date
from quant.data.forecast_numeric import (
    attach_forecast_numeric, forecast_numeric_input_names, read_forecast_numeric_config,
)
from quant.factors.expressions import evaluate_expressions
from quant.factors.gp_materialized import materialized_plans, evaluate_materialized
from quant.research.gp_full_context import VERSION as GP_CONTEXT
from quant.factors.library import load_library
from quant.research.factor_labels import build_next_open_factor_labels
from quant.research.factor_financials import attach_financial_factors, financial_input_names
from quant.factors.pit_quality import PIT_QUALITY_FACTOR_NAMES
from quant.data.factor_intraday_inputs import read_factor_minute_inputs
from quant.research.factor_intraday import attach_minute_factors, minute_input_names
from quant.data.factor_benchmark import read_factor_benchmark, read_price_delay_market
from quant.factors.price_delay import PRICE_DELAY_NAMES
from quant.factors.return_seasonality import SEASONALITY_NAMES, CONTROL_NAMES
from quant.data.factor_seasonality_inputs import read_seasonality_returns
from quant.data.factor_turnover_reference_inputs import read_turnover_reference
from quant.factors.turnover_reference import NAMES as TURNOVER_NAMES, CONTROLS as TURNOVER_CONTROLS
from quant.data.factor_industry_information_inputs import read_industry_information
from quant.factors.industry_information import SIGNALS as INDUSTRY_NAMES, CONTROL as INDUSTRY_CONTROL
from quant.data.factor_control_receipts import pending_control_start, write_control_receipt
from quant.research.factor_market import attach_market_factors, market_input_names
from quant.research.factor_monthly import attach_monthly_factors, monthly_input_names
from quant.data.refresh_stocks import read_stock_data
from quant.research.factor_legacy_special import attach_legacy_special_factors, legacy_special_input_names
from quant.data.statement_event_inputs import read_statement_events, read_statement_market
from quant.factors.statement_event_reaction import NAMES as STATEMENT_NAMES, attach_statement_reactions, compute_statement_reactions


HORIZONS = (1, 5, 10, 20, 60)


def attach_expression_inputs(
    panel: pl.DataFrame, bars: pl.DataFrame, *, expressions: tuple[str, ...],
    data_root: Path, refresh_config: Path, read_start: dt.date, read_end: dt.date,
    sessions: tuple[dt.date, ...],
) -> pl.DataFrame:
    """Share exactly the same intrinsic inputs between N3 and full-context GP."""
    if any("ind_neutralize" in expr for expr in expressions):
        panel = read_factor_industry(data_root, panel)
    financial_names = financial_input_names(expressions)
    if financial_names:
        histories = read_factor_financial_history(data_root, refresh_config, panel,
            expanded=bool(set(financial_names) - set(PIT_QUALITY_FACTOR_NAMES)),
            share_changes="pit_annual_fscore" in financial_names)
        panel = attach_financial_factors(panel, histories, financial_names)
    minute_names = minute_input_names(expressions)
    if minute_names:
        panel = attach_minute_factors(panel, read_factor_minute_inputs(data_root, bars),
            tuple(day for day in sessions if read_start <= day <= read_end), minute_names)
    market_names = market_input_names(expressions)
    if market_names:
        panel = attach_market_factors(panel, bars,
            read_factor_benchmark(data_root, refresh_config, read_start, read_end),
            tuple(day for day in sessions if read_start <= day <= read_end), market_names)
    monthly_names = monthly_input_names(expressions)
    special_names = legacy_special_input_names(expressions)
    basic = pl.DataFrame()
    if monthly_names or set(special_names) - {"alpha101_007_cny_amount_gate"}:
        basic = read_stock_data(data_root=data_root, config=refresh_config, table="daily_basic",
            start=read_start, end=read_end)
    if monthly_names:
        calendar = available_sessions(data_root, read_end + dt.timedelta(days=40))
        extra = {}
        if set(monthly_names) & set(PRICE_DELAY_NAMES):
            extra['price_delay_market'] = read_price_delay_market(data_root, refresh_config, read_start, read_end)
        if set(monthly_names) & set(SEASONALITY_NAMES):
            extra['seasonality_returns'] = read_seasonality_returns(data_root=data_root,
                refresh_config=refresh_config,calendar=calendar,start=read_start,end=read_end)
        if set(monthly_names) & set((*TURNOVER_NAMES, *TURNOVER_CONTROLS)):
            extra['turnover_reference_values'] = read_turnover_reference(data_root=data_root,
                refresh_config=refresh_config, calendar=calendar, start=read_start, end=read_end)
        if set(monthly_names) & set((*INDUSTRY_NAMES, INDUSTRY_CONTROL)):
            extra['industry_information_values'], _, _ = read_industry_information(data_root=data_root,
                refresh_config=refresh_config, calendar=calendar, start=read_start, end=read_end)
        panel = attach_monthly_factors(panel, bars, basic, calendar, monthly_names, **extra)
    if special_names:
        panel = attach_legacy_special_factors(panel, bars, basic,
            tuple(day for day in sessions if read_start <= day <= read_end), special_names)
    numeric_names = forecast_numeric_input_names(expressions)
    if numeric_names:
        events = read_forecast_numeric_config(data_root, refresh_config)
        numeric = attach_forecast_numeric(panel.select("symbol", "trade_date"), events)
        panel = panel.join(numeric.select("symbol", "trade_date", *numeric_names),
                           on=["symbol", "trade_date"], how="left", validate="1:1")
    fields = {node.id for expr in expressions for node in ast.walk(ast.parse(expr)) if isinstance(node, ast.Name)}
    statement_names = [name for name in STATEMENT_NAMES if name in fields]
    if statement_names:
        calendar = available_sessions(data_root, read_end + dt.timedelta(days=40))
        events = read_statement_events(data_root, refresh_config, read_start, read_end)
        reactions = compute_statement_reactions(events, panel,
            read_statement_market(data_root, refresh_config, read_start, read_end), sessions=calendar)
        values = attach_statement_reactions(panel.select('symbol', 'trade_date'), reactions)
        panel = panel.join(values.select('symbol', 'trade_date', *statement_names),
            on=['symbol', 'trade_date'], how='left', validate='1:1')
    return panel


def run(
    *, data_root: Path, refresh_config: Path, library: Path, selected: str,
    start: dt.date, end: dt.date, artifact_root: Path, rebuild: bool = False,
) -> dict[str, Any]:
    definitions = load_library(library, selected)
    sessions = available_sessions(data_root, end)
    if not sessions or start > end:
        raise ValueError("Invalid factor computation range")
    end = min(end, sessions[-1])
    lookback = max(row.lookback for row in definitions)
    for row in definitions:
        check_definition(data_root, row.id, asdict(row))
    return_definition = {
        "horizons": list(HORIZONS), "entry": "open(t+1)", "exit": "open(t+1+h)",
        "price": "open * Tushare adj_factor", "missing_session": "null",
        "costs": "gross labels; executable cost simulation belongs to battery/models",
    }
    check_definition(data_root, "forward_returns", return_definition)
    results = []
    gp_context = materialized_plans(definitions)
    seasonality_definitions = [row for row in definitions if row.id in SEASONALITY_NAMES]
    turnover_definitions = [row for row in definitions if row.id in TURNOVER_NAMES]
    industry_definitions = [row for row in definitions if row.id in INDUSTRY_NAMES]
    for year in range(start.year, end.year + 1):
        low, high = max(start, dt.date(year, 1, 1)), min(end, dt.date(year, 12, 31))
        target_sessions = [day for day in sessions if low <= day <= high]
        if not target_sessions:
            continue
        pending = [row for row in definitions if rebuild or not panel_ready(
            data_root, row.id, year, low, high,
            calculation=GP_CONTEXT if row.id in gp_context else None)]
        gp_plans = {name: plan for name, plan in gp_context.items() if name in {row.id for row in pending}}
        last_index = bisect.bisect_right(sessions, high) - 1
        read_end = sessions[min(len(sessions) - 1, last_index + max(HORIZONS) + 1)]
        return_coverage = read_coverage(data_root, "forward_returns", year)
        return_ready = (not rebuild and panel_complete(data_root, "forward_returns", year, low, high)
                        and (return_coverage.get("known_through") or "") >= str(read_end))
        control_path = artifact_root/'seasonality_controls'/f'year={year}.parquet'
        control_start = None
        if seasonality_definitions:
            control_start = low if rebuild else pending_control_start(
                control_path, start=low, end=high, columns=CONTROL_NAMES)
        turnover_control_path = artifact_root/'turnover_reference_controls'/f'year={year}.parquet'
        turnover_control_start = None
        if turnover_definitions:
            turnover_control_start = low if rebuild else pending_control_start(
                turnover_control_path, start=low, end=high, columns=TURNOVER_CONTROLS)
        industry_control_path = artifact_root/'industry_information_controls'/f'year={year}.parquet'
        industry_control_start = None
        if industry_definitions:
            industry_control_start = low if rebuild else pending_control_start(
                industry_control_path, start=low, end=high, columns=(INDUSTRY_CONTROL,))
        if not pending and return_ready and control_start is None and turnover_control_start is None and industry_control_start is None:
            continue
        factor_starts = {}
        for row in pending:
            coverage = read_coverage(data_root, row.id, year)
            stale_gp = row.id in gp_context and coverage.get("calculation") != GP_CONTEXT
            factor_starts[row.id] = (
                max(low, dt.date.fromisoformat(coverage["end"]) + dt.timedelta(days=1))
                if not rebuild and not stale_gp and coverage and coverage["start"] <= str(low) else low
            )
        label_start = low
        if not rebuild and return_coverage and return_coverage["start"] <= str(low):
            known = dt.date.fromisoformat(return_coverage["known_through"])
            # Earlier labels are final; only the trailing h+1 signal sessions
            # can acquire a newly observed entry or exit price.
            tail_index = max(0, bisect.bisect_right(sessions, known) - max(HORIZONS) - 1)
            label_start = max(low, sessions[tail_index])
        intervals = list(factor_starts.values()) + ([] if return_ready else [label_start])
        if control_start is not None:
            intervals.append(control_start)
        if turnover_control_start is not None:
            intervals.append(turnover_control_start)
        if industry_control_start is not None:
            intervals.append(industry_control_start)
        first_index = bisect.bisect_left(sessions, min(intervals))
        read_start = sessions[max(0, first_index - lookback)]
        panel, bars = read_factor_inputs(data_root, refresh_config, read_start, read_end, sessions)
        expression_definitions = ([row for row in pending if row.id not in gp_plans]
            + (seasonality_definitions if control_start is not None else [])
            + (turnover_definitions if turnover_control_start is not None else [])
            + (industry_definitions if industry_control_start is not None else []))
        panel = attach_expression_inputs(panel, bars, expressions=tuple(dict.fromkeys(row.expr for row in expression_definitions)),
            data_root=data_root, refresh_config=refresh_config, read_start=read_start,
            read_end=read_end, sessions=sessions)
        keys = bars.filter(pl.col("trade_date").is_between(low, high)).select("symbol", "trade_date")
        if control_start is not None:
            calendar = available_sessions(data_root, read_end + dt.timedelta(days=40))
            ends=[a for a,b in zip(calendar,calendar[1:]) if (a.year,a.month)!=(b.year,b.month)]
            controls=panel.filter(pl.col('trade_date').is_between(control_start,high) & pl.col('trade_date').is_in(ends))
            controls=controls.select('symbol','trade_date',*CONTROL_NAMES).join(keys,on=['symbol','trade_date'],how='semi')
            write_control_receipt(control_path, controls, start=control_start, end=high, columns=CONTROL_NAMES)
        if turnover_control_start is not None:
            calendar = available_sessions(data_root, read_end + dt.timedelta(days=40))
            ends = [a for a, b in zip(calendar, calendar[1:]) if (a.year, a.month) != (b.year, b.month)]
            controls = panel.filter(pl.col('trade_date').is_between(turnover_control_start, high)
                & pl.col('trade_date').is_in(ends)).select('symbol', 'trade_date', *TURNOVER_CONTROLS)
            controls = controls.join(keys, on=['symbol', 'trade_date'], how='semi')
            write_control_receipt(turnover_control_path, controls, start=turnover_control_start,
                end=high, columns=TURNOVER_CONTROLS)
        if industry_control_start is not None:
            calendar = available_sessions(data_root, read_end + dt.timedelta(days=40))
            ends = [a for a,b in zip(calendar,calendar[1:]) if (a.year,a.month)!=(b.year,b.month)]
            controls = panel.filter(pl.col('trade_date').is_between(industry_control_start,high)
                & pl.col('trade_date').is_in(ends)).select('symbol','trade_date',INDUSTRY_CONTROL)
            controls = controls.join(keys,on=['symbol','trade_date'],how='semi')
            write_control_receipt(industry_control_path,controls,start=industry_control_start,end=high,columns=(INDUSTRY_CONTROL,))
        row_counts = {}
        if pending:
            values = evaluate_expressions(panel, {row.id: row.expr for row in pending if row.id not in gp_plans})
            if gp_plans:
                materialized = evaluate_materialized(panel, gp_plans, data_root=data_root,
                    refresh_config=refresh_config, artifact_root=artifact_root)
                values = values.join(materialized, on=['symbol', 'trade_date'], how='left', validate='1:1')
            values = values.join(keys, on=["symbol", "trade_date"], how="semi")
            for row in pending:
                output = values.filter(pl.col("trade_date") >= factor_starts[row.id]).select(
                    "trade_date", pl.col("symbol").alias("ts_code"), pl.col(row.id).alias("value"))
                row_counts[row.id] = {"rows": output.height, "valid": output["value"].count()}
                write_panel(data_root, row.id, year, output, factor_starts[row.id], high,
                            calculation=GP_CONTEXT if row.id in gp_context else None)
        if not return_ready:
            labels = build_next_open_factor_labels(
                factor_values=keys.filter(pl.col("trade_date") >= label_start), bars=bars,
                sessions=tuple(day for day in sessions if read_start <= day <= read_end),
                horizons=HORIZONS,
            ).select(
                "trade_date", pl.col("symbol").alias("ts_code"),
                *[column for h in HORIZONS for column in
                  (f"label_{h}", f"execution_date_{h}", f"exit_date_{h}")],
            )
            write_panel(data_root, "forward_returns", year, labels, label_start, high,
                        known_through=read_end)
        results.append({"year": year, "symbols": keys["symbol"].n_unique(),
                        "stock_days": keys.height, "factors": row_counts})
        print(json.dumps({"year": year, "stock_days": keys.height, "factors_written": len(pending)}), flush=True)
    summary = {"start": str(start), "end": str(end), "factor_count": len(definitions),
               "scope": "all historical SH/SZ A-share symbols; no liquidity-pool selection",
               "lookback_sessions": lookback, "years": results}
    folder = artifact_root / "factors" / "compute" / dt.datetime.now(SHANGHAI).strftime("%Y%m%dT%H%M%S%f")
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {**summary, "output": str(folder)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factors", default="all")
    parser.add_argument("--from", dest="start", default="2010-01-01")
    parser.add_argument("--to", default="today")
    parser.add_argument("--rebuild", action="store_true", help="Recompute the requested clean panels")
    parser.add_argument("--library", type=Path, default=Path("configs/factors/library"))
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--refresh-config", type=Path, default=Path("configs/data/refresh.toml"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    print(json.dumps(run(
        data_root=args.data_root, refresh_config=args.refresh_config, library=args.library,
        selected=args.factors, start=dt.date.fromisoformat(args.start),
        end=completed_date(args.to, dt.datetime.now(SHANGHAI)), artifact_root=args.artifact_root,
        rebuild=args.rebuild,
    )))


if __name__ == "__main__":
    main()
