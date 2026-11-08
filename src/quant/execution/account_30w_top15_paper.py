"""A2: one cash ledger for a 40% Top15 limit sleeve and two 30% ETF sleeves."""

import argparse
import copy
import datetime as dt
import hashlib
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.backtest.costs import EtfCostModel
from quant.backtest.daily_account import advance, prepare_account_actions
from quant.data.account_30w_top15_inputs import (
    SYMBOLS,
    capture,
    instruments,
    read_capture,
    shared_actions,
)
from quant.data.refresh import SHANGHAI
from quant.data.stock_execution_inputs import stock_session_states
from quant.data.stock_paper_inputs import read_stock_paper_calendar, read_stock_paper_inputs
from quant.execution.q10_paper import load_forecast
from quant.execution.stock_paper import _controls, _write_snapshot
from quant.execution.top15_paper import limit_orders, load_book
from quant.portfolio.account_portfolio_top15 import Top15Allocation, joint_orders
from quant.research.account_portfolio_etf_baselines import market_states as etf_market_states

CONFIG = Path("configs/paper/account_30w_top15_v1_20261108.toml")
OUTPUT = Path("artifacts/paper/account_30w_top15_v1")
FIRST_SIGNAL = dt.date(2026, 11, 30)
ORDER_SCHEMA = {
    "as_of": pl.String,
    "execution_date": pl.String,
    "symbol": pl.String,
    "side": pl.String,
    "quantity": pl.Int64,
}


def validate(config, output):
    paper, portfolio = config["paper"], config["portfolio"]
    if (
        paper["auto_trade"] is not False
        or paper["initial_cash"] != 300000
        or paper.get("shadow") is not True
        or paper.get("observation_only") is not True
        or paper.get("counts_toward_account_limit") is not False
        or portfolio["fixed_weights"] != [0.4, 0.3, 0.3]
        or portfolio["etf_symbols"] != SYMBOLS
        or portfolio["quarter_months"] != [3, 6, 9, 12]
        or portfolio["stock_limit_offset"] != 0.01
        or portfolio["maximum_limit_sessions"] != 3
    ):
        raise ValueError("Require registered manual-only 300k 40/30/30 Top15 1% account")
    if "rehearsal" not in output.resolve().parts and paper["inception_date"] != FIRST_SIGNAL:
        raise ValueError("Formal A2 account starts at the registered November 30 signal")


def allocator(config, state):
    spec = dict(
        fixed_weights=config["portfolio"]["fixed_weights"],
        etfs={
            "dividend": dict(symbol=SYMBOLS[0], listing_date=dt.date(2019, 1, 18)),
            "treasury": dict(symbol=SYMBOLS[1], listing_date=dt.date(2013, 3, 25)),
        },
    )
    result = Top15Allocation(variant="fixed_40_30_30", spec=spec, returns=None, etf_prices=None)
    result.initialized = state.get("allocation_initialized", False)
    result.reserved = state.get("reserved_unlisted_cash", 0.0)
    return result


def forecast_for(config, day, following, supplied=None):
    folders = ([Path(supplied)] if supplied else []) + sorted(
        Path(config["model"]["forecast_root"]).glob("**/model/forecast")
    )
    for folder in folders:
        path = folder / "summary.json"
        if path.is_file() and json.loads(path.read_text(encoding="utf-8"))["as_of"] == str(day):
            return load_forecast(folder, day, Path(config["model"]["selection"]), following)
    raise ValueError(f"Missing prospective same-day monthly forecast: {day}")


def etf_inputs(config, day, now, *, data_root=Path("data")):
    folder = capture(date=day, settings=config["data"], data_root=data_root)
    observed = dt.datetime.now(SHANGHAI)
    bars, references, receipt = read_capture(folder, date=day, now=observed)
    actions, version = shared_actions(folder=folder, settings=config["data"], now=observed)
    actions = actions.filter(pl.col("ann_date") <= day)
    terms = tomllib.loads((folder / "corporate_actions.toml").read_text(encoding="utf-8"))["splits"]
    return dict(
        bars=bars,
        references=references,
        actions=actions,
        instruments=instruments(),
        splits=terms,
        capture=str(folder),
        actions_version=str(version),
        available_at=receipt["available_at"],
    )


def reference_orders(state, book, following, config, controls):
    stock = limit_orders(state, book, following, config, controls)
    stock = stock.with_columns(
        pl.lit("STOCK").alias("asset_type"), pl.lit("LIMIT").alias("order_type")
    )
    rows = []
    fees = EtfCostModel(**config["costs"]["etf"])
    cash = stock["cash_after"][-1] if stock.height else state["cash"]
    for order in sorted(
        state.get("pending_etf_orders", []), key=lambda x: (x["side"] != "SELL", x["symbol"])
    ):
        if controls["halt"] or controls["sell_only"] and order["side"] == "BUY":
            continue
        price = state["signal_closes"][order["symbol"]]
        notional = order["quantity"] * price
        fee = fees.fee(notional, following)
        cash += notional - fee if order["side"] == "SELL" else -(notional + fee)
        rows.append(
            {
                **order,
                "board_lot": 100,
                "reference_price": price,
                "estimated_fill_price": price,
                "estimated_notional": notional,
                "estimated_fee": fee,
                "cash_after": cash,
                "limit_price": None,
                "attempts_remaining": 1,
                "asset_type": "ETF",
                "order_type": "MARKET",
            }
        )
    if rows:
        stock = pl.concat([stock, pl.from_dicts(rows)], how="diagonal_relaxed")
    return stock.with_columns(
        pl.lit(str(following) + "T" + config["notify"]["planned_submit_time"]).alias(
            "planned_submit_at"
        )
    )


def save(output, state, book, orders, result, controls, observed_at):
    state.update(
        auto_trade=False,
        shadow=True,
        observation_only=True,
        counts_toward_account_limit=False,
        research_conclusion="RESEARCH_ONLY",
        limit_book=copy.deepcopy(book.__dict__),
        controls_at_snapshot=dict(controls),
        recorded_at=observed_at.isoformat(),
    )
    _write_snapshot(output / state["date"], state, orders, result, None)
    if result is None and not (output / state["date"] / "fills.csv").exists():
        from quant.backtest.daily_simulator import _validate_or_empty_trades

        _validate_or_empty_trades([]).write_csv(output / state["date"] / "fills.csv")
    orders.write_csv(output / "latest_orders.csv")
    rows = orders.to_dicts()
    lines = [
        "# 30万元账户组合：仅观察",
        "",
        f"记录日 {state['date']}；权益 {state['nav'][-1]['equity']:.2f}元；净值 {state['nav'][-1]['unit_nav']:.6f}。",
        "Top15股票40%：原1%预挂限价，最多3个交易日；红利低波512890与国债511010各30%，季度再平衡。",
        "auto_trade=false；不连接券商。股票与ETF共用实际现金，买入金额以卖出实际成交和可用现金为准。",
        "ETF估算金额使用信号收盘价，开盘成交价可能不同；清单不保证全部成交。",
        "",
        "|预计挂单时间|证券|类型|方向|股数|股票限价|估算金额|",
        "|---|---|---|---|---:|---:|---:|",
    ]
    for row in rows:
        limit = f"{row['limit_price']:.2f}" if row["limit_price"] is not None else "开盘市价"
        lines.append(
            f"|{row['planned_submit_at']}|{row['symbol']}|{row['asset_type']}|{row['side']}|"
            f"{row['quantity']}|{limit}|{row['estimated_notional']:.2f}|"
        )
    if not rows:
        lines.append("\n没有待执行的模拟委托。")
    text = "\n".join(lines) + "\n"
    for path in [
        output / "latest_orders.md",
        output / "report.md",
        output / state["date"] / "orders.md",
    ]:
        path.write_text(text, encoding="utf-8")
    summary = dict(
        status="complete",
        as_of=state["date"],
        recorded_at=observed_at.isoformat(),
        shadow=True,
        observation_only=True,
        auto_trade=False,
        conclusion="RESEARCH_ONLY",
        equity=state["nav"][-1]["equity"],
        cash=state["cash"],
        positions=len(state["holdings"]),
        stock_orders=sum(r["asset_type"] == "STOCK" for r in rows),
        etf_orders=sum(r["asset_type"] == "ETF" for r in rows),
        reference_orders=len(rows),
        estimated_notional=sum(r["estimated_notional"] for r in rows),
        rehearsal=bool(state.get("rehearsal")),
        output=str(output),
    )
    (output / "latest_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _run(
    *,
    config_path=CONFIG,
    data_root=Path("data"),
    output=OUTPUT,
    end,
    forecast=None,
    as_month_end=False,
    now=None,
    etf_reader=None,
    stock_reader=None,
    calendar=None,
    before_publish=None,
):
    now = now or dt.datetime.now(SHANGHAI)
    if now.tzinfo is None or end > now.date():
        raise ValueError("Require actual observation clock and no future dates")
    output = Path(output)
    payload = Path(config_path).read_bytes()
    config = tomllib.loads(payload.decode("utf-8"))
    validate(config, output)
    first = config["paper"]["inception_date"]
    if end < first:
        return dict(status="not_started", inception=str(first), as_of=str(end), auto_trade=False)
    if end == now.date() and now.hour < 21:
        raise ValueError("Wait for completed execution inputs after 21:00 Shanghai")
    if as_month_end and "rehearsal" not in output.resolve().parts:
        raise ValueError("Forced month-end requires isolated rehearsal output")
    output.mkdir(parents=True, exist_ok=True)
    frozen = output / "config.toml"
    if frozen.exists() and frozen.read_bytes() != payload:
        raise ValueError("Frozen account configuration changed")
    if not frozen.exists():
        frozen.write_bytes(payload)
    controls = _controls(output, config["paper"], None, None)
    config["paper"].update(enabled=not controls["halt"], sell_only=controls["sell_only"])
    calendar = calendar if calendar is not None else read_stock_paper_calendar(data_root)
    sessions = sorted(calendar.filter(pl.col("is_open"))["date"].unique().to_list())
    if first not in sessions or end not in sessions:
        raise ValueError("Observation dates require actual open exchange sessions")
    snapshots = sorted(output.glob("????-??-??/state.json"))
    if snapshots:
        state = json.loads(snapshots[-1].read_text(encoding="utf-8"))
    else:
        prior = max(d for d in sessions if d < first)
        # Internal empty-book anchor only; never publish it as a prior observation.
        state = dict(
            date=str(prior),
            inception_date=str(first),
            started_with_cash=True,
            cash=300000.0,
            holdings={},
            pending=[],
            receivables=[],
            restricted_shares=[],
            cumulative_fees=0.0,
            nav=[],
            previous_targets=[],
            pending_etf_orders=[],
            signal_closes={},
        )
    last = dt.date.fromisoformat(state["date"])
    if end < last:
        raise ValueError("Cannot rewind the account")
    if snapshots and end == last and state.get("controls_at_snapshot") == controls:
        summary = json.loads((output / "latest_summary.json").read_text(encoding="utf-8"))
        if summary["as_of"] != str(end):
            raise ValueError("Latest summary does not match the completed account state")
        return summary
    book = load_book(state)
    allocate = allocator(config, state)
    stock_reader = stock_reader or read_stock_paper_inputs
    etf_reader = etf_reader or (lambda c, d, n: etf_inputs(c, d, n, data_root=data_root))
    result = None
    for day in [d for d in sessions if max(last, first - dt.timedelta(days=1)) < d <= end]:
        following = next(d for d in sessions if d > day)
        due = day == first or day.month != following.month or as_month_end and day == end
        scores = forecast_for(config, day, following, forecast) if due else None
        symbols = (
            set(state["holdings"])
            | {o["symbol"] for o in book.orders if o["status"] == "pending"}
            | {r["symbol"] for r in state["receivables"]}
        ) - set(SYMBOLS)
        if scores is not None:
            symbols |= set(scores["symbol"])
        gross = copy.deepcopy(config)
        gross["portfolio"]["stock_dividend_withholding"] = 0.0
        stocks = stock_reader(data_root, gross, sorted(symbols), day) if symbols else None
        etfs = etf_reader(config, day, now)
        stock_actions = stocks.dividends if stocks is not None else etfs["actions"].clear()
        book.apply_actions(day, stock_actions)
        actions = pl.concat(
            [
                stock_actions.with_columns(
                    (
                        pl.col("div_cash") * (1 - config["portfolio"]["stock_dividend_withholding"])
                    ).alias("div_cash")
                ),
                etfs["actions"],
            ],
            how="diagonal_relaxed",
        )
        bars = (
            etfs["bars"]
            if stocks is None
            else pl.concat([stocks.bars, etfs["bars"]], how="diagonal_relaxed")
        )
        assets = (
            etfs["instruments"]
            if stocks is None
            else pl.concat([stocks.instruments, etfs["instruments"]], how="diagonal_relaxed")
        )
        states = etf_market_states(etfs["bars"], etfs["references"], etfs.get("splits", []), 1.0)
        if stocks is not None:
            states.update(
                stock_session_states(
                    bars=stocks.bars,
                    limits=stocks.limits,
                    suspensions=stocks.suspensions,
                    sessions=[day],
                    symbols=sorted(symbols),
                    execution_dates=[day]
                    if any(o["status"] == "pending" for o in book.orders)
                    else [],
                    slippage=config["costs"]["a_share"]["slippage"],
                )
            )
        prepared = prepare_account_actions(
            date=day, state=state, calendar=calendar, dividends=actions
        )
        fixed, limits = book.attempt(day, holdings=prepared["holdings"])
        etf_orders = pl.from_dicts(state.get("pending_etf_orders", []), schema=ORDER_SCHEMA)
        joint, limits = joint_orders(fixed, limits, etf_orders)
        selected = state["previous_targets"]
        old_orders = state.get("pending_etf_orders", [])
        state["pending"] = []
        state, result = advance(
            date=day,
            state=state,
            bars=bars,
            calendar=calendar,
            instruments=assets,
            market_states=states,
            dividends=actions,
            config=config,
            scheduled_orders=joint,
            preposted_limits=limits,
        )
        book.settle(result.trades.filter(~pl.col("symbol").is_in(SYMBOLS)))
        state.update(
            previous_targets=selected,
            pending_etf_orders=[],
            signal_closes={},
            etf_attempts=[
                dict(
                    orders=old_orders,
                    filled=json.loads(
                        result.trades.filter(pl.col("symbol").is_in(SYMBOLS)).write_json()
                    ),
                )
            ],
        )
        if scores is not None:
            closes = dict(
                bars.filter(pl.col("trade_date") == day).select("symbol", "close").iter_rows()
            )
            for symbol, holding in state["holdings"].items():
                closes.setdefault(symbol, holding["mark_price"])
            target, selected, etf_orders, info = allocate.plan(
                scores=scores,
                previous=selected,
                closes=closes,
                state=state,
                execution_date=following,
            )
            stock_holdings = {s: h for s, h in state["holdings"].items() if s not in SYMBOLS}
            book.replace(
                signal=day,
                targets=target,
                holdings=stock_holdings,
                equity=info["stock_equity_before_allocation"],
                closes=closes,
                offset=0.01,
            )
            state.update(
                previous_targets=selected,
                pending_etf_orders=etf_orders.to_dicts(),
                signal_closes=closes,
                allocation=info,
            )
        state.update(
            allocation_initialized=allocate.initialized,
            reserved_unlisted_cash=allocate.reserved,
            inputs=dict(
                etf_capture=etfs.get("capture"), actions_version=etfs.get("actions_version")
            ),
            rehearsal="rehearsal" in output.resolve().parts
            or as_month_end
            or bool(state.get("rehearsal")),
        )
        orders = reference_orders(state, book, following, config, controls)
        if before_publish:
            before_publish()
        save(output, state, book, orders, result, controls, dt.datetime.now(SHANGHAI))
    following = next(d for d in sessions if d > dt.date.fromisoformat(state["date"]))
    if before_publish:
        before_publish()
    return save(
        output,
        state,
        book,
        reference_orders(state, book, following, config, controls),
        result,
        controls,
        dt.datetime.now(SHANGHAI),
    )


def run(
    *,
    config_path=CONFIG,
    data_root=Path("data"),
    output=OUTPUT,
    end,
    forecast=None,
    as_month_end=False,
    now=None,
    etf_reader=None,
    stock_reader=None,
    calendar=None,
    preflight=None,
    before_publish=None,
):
    clock = now or dt.datetime.now(SHANGHAI)
    config = tomllib.loads(Path(config_path).read_text(encoding="utf-8"))
    validate(config, Path(output))
    if clock.tzinfo is None or end > clock.date():
        raise ValueError("Require actual observation clock and no future dates")
    if end < config["paper"]["inception_date"]:
        return dict(
            status="not_started",
            inception=str(config["paper"]["inception_date"]),
            as_of=str(end),
            auto_trade=False,
        )
    from quant.execution.manual_session_service import instance_lock

    Path(output).mkdir(parents=True, exist_ok=True)
    with instance_lock(Path(output) / "writer.lock"):
        if preflight:
            preflight()
        return _run(
            config_path=config_path,
            data_root=data_root,
            output=output,
            end=end,
            forecast=forecast,
            as_month_end=as_month_end,
            now=clock,
            etf_reader=etf_reader,
            stock_reader=stock_reader,
            calendar=calendar,
            before_publish=before_publish,
        )


def observe_from_daily(spec, *, end, data_root, forecast=None):
    try:
        return run(
            config_path=Path(spec["config"]),
            output=Path(spec["output"]),
            data_root=data_root,
            end=end,
            forecast=forecast,
        )
    except Exception as exc:
        return dict(status="failed", error=f"{type(exc).__name__}: {exc}")


def _notify_due(*, config_path=CONFIG, output=OUTPUT, now=None, sender=None):
    now = (now or dt.datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    config = tomllib.loads(Path(config_path).read_text(encoding="utf-8"))
    if now.date() != config["notify"]["manual_rehearsal_date"] or now.time() < dt.time(8, 30):
        return dict(status="not_due", auto_trade=False)
    output = Path(output)
    signal_root = output / str(FIRST_SIGNAL)
    order_path = signal_root / "orders.csv"
    orders = pl.read_csv(order_path)
    if (
        orders.is_empty()
        or set(orders["execution_date"]) != {str(now.date())}
        or set(orders["as_of"]) != {str(FIRST_SIGNAL)}
    ):
        raise ValueError(
            "Manual rehearsal notification requires actual November 30 orders for December 1"
        )
    state = json.loads((signal_root / "state.json").read_text(encoding="utf-8"))
    if (
        state.get("date") != str(FIRST_SIGNAL)
        or state.get("auto_trade") is not False
        or state.get("shadow") is not True
        or state.get("rehearsal") is not False
    ):
        raise ValueError("Require completed formal signal-day shadow state, not a rehearsal")
    digest = hashlib.sha256(order_path.read_bytes()).hexdigest()
    receipt_path = output / "manual_rehearsal_notification.json"
    if receipt_path.exists():
        previous = json.loads(receipt_path.read_text(encoding="utf-8"))
        if previous["orders_sha256"] == digest:
            return previous
        raise ValueError("Manual rehearsal order content changed after notification attempt")
    if sender is None:
        from quant.notify import send

        sender = send
    body = (signal_root / "orders.md").read_text(encoding="utf-8")
    attempt = dict(
        status="attempting",
        as_of=now.isoformat(),
        orders_sha256=digest,
        auto_trade=False,
        late=now.time() >= dt.time(9, 30),
    )
    receipt_path.write_text(json.dumps(attempt, indent=2), encoding="utf-8")
    try:
        results = sender("12月1日：30万元组合人工演练清单（仅模拟）", body)
        serialized = [vars(x) if hasattr(x, "__dict__") else x for x in results]
        attempt.update(
            status="submitted",
            results=serialized,
            transport_accepted=any(
                x.get("ok") and x.get("channel") != "outbox" for x in serialized
            ),
        )
    except Exception as exc:
        attempt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    receipt_path.write_text(json.dumps(attempt, ensure_ascii=False, indent=2), encoding="utf-8")
    return attempt


def notify_due(*, config_path=CONFIG, output=OUTPUT, now=None, sender=None):
    clock = now or dt.datetime.now(SHANGHAI)
    if clock.tzinfo is None:
        raise ValueError("Notification requires a timezone-aware clock")
    clock = clock.astimezone(SHANGHAI)
    config = tomllib.loads(Path(config_path).read_text(encoding="utf-8"))
    validate(config, Path(output))
    if clock.date() != config["notify"]["manual_rehearsal_date"] or clock.time() < dt.time(8, 30):
        return dict(status="not_due", auto_trade=False)
    from quant.execution.manual_session_service import instance_lock

    with instance_lock(Path(output) / "notification.lock"):
        return _notify_due(config_path=config_path, output=output, now=clock, sender=sender)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--to", type=dt.date.fromisoformat)
    parser.add_argument("--forecast", type=Path)
    parser.add_argument("--as-month-end", action="store_true")
    parser.add_argument("--notify-due", action="store_true")
    args = parser.parse_args()
    if args.notify_due:
        result = notify_due(config_path=args.config, output=args.output)
    else:
        if args.to is None:
            parser.error("--to is required for account observations")
        result = run(
            config_path=args.config,
            output=args.output,
            end=args.to,
            forecast=args.forecast,
            as_month_end=args.as_month_end,
        )
    print(json.dumps(result, ensure_ascii=False))
    if args.notify_due and result['status'] != 'not_due' and not result.get('transport_accepted'):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
