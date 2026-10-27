"""S2 few-holdings books. The ETF pool and Top15 cap are frozen in toml."""

from __future__ import annotations

import datetime as dt
import json
import tomllib
from decimal import Decimal
from pathlib import Path

import polars as pl

DEFAULT_CONFIG = Path("configs/research/few_holdings_v1.toml")


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    spec = tomllib.loads(path.read_text(encoding="utf-8"))
    if spec.get("auto_trade") is not False:
        raise ValueError("few_holdings requires auto_trade=false")
    if int(spec["top_k"]) != 15 or float(spec["single_name_cap"]) != 0.08:
        raise ValueError("S2a Top15 and 8% cap are frozen")
    if len(spec["s2b"]["pool"]) != 12 or int(spec["s2b"]["top_k"]) != 3:
        raise ValueError("S2b pool and Top3 are frozen")
    return spec


def _planner():
    from quant.backtest.a_share_execution import build_a_share_rule_config
    from quant.backtest.connect_execution import build_connect_rule_config
    from quant.backtest.costs import ExecutionCostPeriod, build_execution_cost_schedule
    from quant.backtest.fx import FxRate, build_fx_snapshot
    from quant.domain.enums import ConnectRoute, Currency, Market
    from quant.execution.config import load_trading_config
    from quant.execution.contracts import build_money_amount
    from quant.portfolio.order_planner import build_order_planner_config

    trading = load_trading_config(Path("configs/trading/example.toml"))
    schedule = build_execution_cost_schedule(
        selector="a_share_research_cost_schedule_v1",
        periods=tuple(
            ExecutionCostPeriod(
                market=market, effective_from=dt.date(2018, 1, 1), effective_to=dt.date(2026, 12, 31),
                commission_rate=Decimal("0.00025"), commission_min=Decimal("5"),
                stamp_tax_sell=Decimal("0.0005"), transfer_fee=Decimal("0.00001"),
                settlement_currency=Currency.CNY,
            )
            for market in (Market.SH, Market.SZ)
        ),
    )
    return build_order_planner_config(
        trading_config=trading,
        a_share_rule_config=build_a_share_rule_config(
            selector="a_share_execution_rules_v1", effective_from=dt.date(2020, 8, 24), effective_to=None,
        ),
        connect_rule_configs=tuple(
            build_connect_rule_config(
                selector="hk_connect_execution_rules_v1", route=route,
                effective_from=dt.date(2018, 1, 1), effective_to=dt.date(2026, 12, 31),
            )
            for route in (ConnectRoute.SH_CONNECT, ConnectRoute.SZ_CONNECT)
        ),
        execution_cost_schedule=schedule,
        fx_snapshot=build_fx_snapshot(
            selector="cny_hkd_fx_schedule_v1", session_date=dt.date(2026, 8, 31),
            observed_at=dt.datetime(2026, 8, 31, 1, tzinfo=dt.UTC),
            expires_at=dt.datetime(2026, 8, 31, 8, tzinfo=dt.UTC),
            rates=(FxRate(Currency.HKD, Currency.CNY, Decimal("0.9")),),
        ),
        minimum_order_notionals=(build_money_amount(Currency.CNY, Decimal("1")),),
    )


def lot_constraint_share(targets: pl.DataFrame, prices: pl.DataFrame, *, cash: float) -> dict:
    """Fraction of desired buys the order planner cannot place because of the board lot."""
    import hashlib

    from quant.domain.enums import Currency, Market
    from quant.execution.contracts import (
        build_account_snapshot, build_cash_balance, build_symbol_market_state, build_verified_market_snapshot,
    )
    from quant.portfolio.order_planner import OrderPlanTarget, build_order_plan

    config = _planner()
    requested = rejected = 0
    for day in targets["as_of"].unique().sort().to_list():
        batch = targets.filter((pl.col("as_of") == day) & (pl.col("weight") > 0))
        raw = [Decimal(str(row["weight"])) for row in batch.iter_rows(named=True)]
        if not raw:
            continue
        scale = Decimal(1) / sum(raw) if sum(raw) > 1 else Decimal(1)
        remaining = Decimal(1)
        states, plan_targets = [], []
        named = list(batch.iter_rows(named=True))
        for index, row in enumerate(named):
            price = prices.filter((pl.col("symbol") == row["symbol"]) & (pl.col("trade_date") == day))
            if price.height != 1:
                continue
            close = Decimal(str(round(float(price["close"][0]), 2)))
            if close <= 0:
                continue
            weight = (Decimal(str(row["weight"])) * scale).quantize(Decimal("0.000001"))
            if weight > remaining:
                weight = remaining
            remaining -= weight
            if weight <= 0:
                continue
            market = Market.SH if str(row["symbol"]).endswith(".SH") else Market.SZ
            states.append(build_symbol_market_state(
                symbol=row["symbol"], market=market, session_date=day, quote_currency=Currency.CNY,
                reference_price=close, limit_up=(close * Decimal("1.1")).quantize(Decimal("0.01")),
                limit_down=(close * Decimal("0.9")).quantize(Decimal("0.01")), suspended=False,
                board_lot=200 if str(row["symbol"]).startswith("688") else 100,
                tick_size=Decimal("0.01"), rule_version="a_share_execution_rules_v1",
            ))
            plan_targets.append(OrderPlanTarget(row["symbol"], market, None, weight))
        if not plan_targets:
            continue
        account = build_account_snapshot(
            as_of=dt.datetime(day.year, day.month, day.day, 7, tzinfo=dt.UTC), positions=(),
            cash=(build_cash_balance(currency=Currency.CNY, settled=Decimal(int(cash)),
                                     available=Decimal(int(cash)), receivable=Decimal(0), payable=Decimal(0)),),
        )
        market_snapshot = build_verified_market_snapshot(
            as_of=account.as_of, session_date=day, states=tuple(states), connect_contexts=(),
            calendar_identity=hashlib.sha256(b"calendar").hexdigest(),
            source_identity=hashlib.sha256(b"few-holdings").hexdigest(),
        )
        plan = build_order_plan(
            targets=plan_targets, target_identity="0" * 64, market=market_snapshot,
            account=account, config=config,
        )
        for decision in plan.decisions:
            if decision.requested_quantity <= 0:
                continue
            requested += 1
            if decision.accepted_quantity == 0:
                rejected += 1
    return {
        "lot_constraint": None if requested == 0 else rejected / requested,
        "requested": requested,
        "rejected": rejected,
    }


def momentum_book(closes: pl.DataFrame, *, pool: list[str], cash_symbol: str, top_k: int) -> pl.DataFrame:
    frame = closes.filter(pl.col("symbol").is_in(pool)).sort("trade_date")
    dates = frame.filter(pl.col("symbol") == "510300.SH").get_column("trade_date").to_list()
    rows = []
    for index, day in enumerate(dates):
        nxt = dates[index + 1] if index + 1 < len(dates) else None
        if nxt is None or nxt.month == day.month or index < 252:
            continue
        scores = []
        for symbol in pool:
            series = frame.filter(pl.col("symbol") == symbol)
            aligned = {item["trade_date"]: item["close"] for item in series.iter_rows(named=True)}
            start, skip = dates[index - 252], dates[index - 21]
            if start not in aligned or skip not in aligned or aligned[start] <= 0:
                continue
            scores.append((aligned[skip] / aligned[start] - 1.0, symbol))
        scores.sort(reverse=True)
        picks = [(cash_symbol, 1.0)] if not scores or scores[0][0] <= 0 else [
            (symbol, 1.0 / top_k) for _, symbol in scores[:top_k]
        ]
        for symbol, weight in picks:
            rows.append({"as_of": day, "execution_date": nxt, "symbol": symbol, "weight": weight})
    return pl.DataFrame(rows)


def _read_nav(folder: Path) -> pl.DataFrame:
    files = sorted(folder.glob("*/nav.parquet"))
    return pl.concat([pl.read_parquet(path).select("date", "equity") for path in files]).sort("date")


def _monthly_return(nav: pl.DataFrame) -> pl.DataFrame:
    return (
        nav.with_columns(pl.col("date").dt.truncate("1mo").alias("month"))
        .group_by("month", maintain_order=True)
        .agg(pl.col("equity").last())
        .with_columns(pl.col("equity").pct_change().alias("ret"))
        .drop_nulls("ret")
    )


def _correlation(left: pl.DataFrame, right: pl.DataFrame) -> float | None:
    joined = left.join(right, on="month", suffix="_q10")
    if joined.height < 12:
        return None
    return float(joined.select(pl.corr("ret", "ret_q10")).item())


def _annotate(folder: Path, lines: list[str]) -> None:
    path = folder / "report.md"
    text = path.read_text(encoding="utf-8")
    addition = "\n".join(lines)
    if addition in text:
        return
    path.write_text(text + "\n" + addition + "\n", encoding="utf-8")


def run_s2a(spec: dict, output: Path, data_root: Path) -> list[dict]:
    from quant.research.q10_sizing import run_cell

    scores = pl.read_parquet(Path(spec["predictions"]) / "monthly_predictions.parquet")
    books = []
    for cash in spec["capitals"]:
        label = "100k" if float(cash) < 500_000 else "1m"
        cell_id = f"s2a_top15_{label}"
        saved = output / cell_id / "cell_result.json"
        if saved.is_file():
            result = json.loads(saved.read_text(encoding="utf-8"))
        else:
            result = run_cell(
                spec=spec,
                cell={"cell_id": cell_id, "budget": float(spec["budget"]), "top_k": int(spec["top_k"]),
                      "size_neutral": False},
                output=output,
                data_root=data_root,
                resume=True,
                score_frame=scores,
                research_id=f"few_holdings_{cell_id}",
                initial_cash=float(cash),
            )
        books.append({"id": cell_id, "cash": float(cash), "holdings": int(spec["top_k"]), **result})
    return books


def _closes(pool: list[str], data_root: Path) -> pl.DataFrame:
    frames = []
    for symbol in pool:
        market = symbol.rsplit(".", 1)[-1]
        path = data_root / f"clean/bar_1d_tdx/source=tdx/market={market}/symbol={symbol}/data.parquet"
        frames.append(pl.read_parquet(path).select("symbol", "trade_date", "close"))
    return pl.concat(frames)


def run_s2b(spec: dict, output: Path, data_root: Path, q10_monthly: pl.DataFrame) -> dict:
    from quant.reporting.experiment_registry import register_run

    rules = spec["s2b"]
    closes = _closes(rules["pool"], data_root)
    weights = momentum_book(
        closes, pool=list(rules["pool"]), cash_symbol=rules["cash_symbol"], top_k=int(rules["top_k"]),
    )
    folder = output / "s2b_etf_momentum"
    folder.mkdir(parents=True, exist_ok=True)
    weights.write_parquet(folder / "weights.parquet")
    price = closes.sort("symbol", "trade_date").with_columns(
        (pl.col("close") / pl.col("close").shift(1).over("symbol") - 1).alias("ret")
    )
    # Hold the latest signal from the next session until the following signal.
    signals = weights.select("execution_date", "symbol", "weight").rename({"execution_date": "trade_date"})
    daily = price.join(signals, on=["symbol", "trade_date"], how="left")
    # Forward-fill weights within symbol after the first execution date.
    daily = daily.sort("symbol", "trade_date").with_columns(pl.col("weight").forward_fill().over("symbol"))
    rows = []
    navs = {}
    for multiplier in rules["cost_multipliers"]:
        book = (
            daily.drop_nulls("weight")
            .group_by("trade_date", maintain_order=True)
            .agg((pl.col("weight") * pl.col("ret")).sum().alias("gross"),
                 pl.col("weight").sum().alias("invested"))
            .sort("trade_date")
        )
        # Charge the frozen one-way cost when the weight vector changes.
        changes = []
        previous: dict[str, float] = {}
        for day in weights["execution_date"].unique().sort().to_list():
            current = {
                row["symbol"]: float(row["weight"])
                for row in weights.filter(pl.col("execution_date") == day).iter_rows(named=True)
            }
            names = set(previous) | set(current)
            traded = sum(abs(current.get(name, 0.0) - previous.get(name, 0.0)) for name in names) / 2
            changes.append({"trade_date": day, "turnover_proxy": traded})
            previous = current
        changes = pl.DataFrame(changes)
        book = book.join(changes, on="trade_date", how="left")
        cost = float(rules["one_way_cost"]) * float(multiplier)
        book = book.with_columns(
            (pl.col("gross") - pl.col("turnover_proxy").fill_null(0) * cost).alias("net")
        )
        equity = (1 + book["net"]).cum_prod()
        nav = book.select("trade_date", equity.alias("equity")).rename({"trade_date": "date"})
        navs[multiplier] = nav
        start, end = nav["date"][0], nav["date"][-1]
        years = max((end - start).days / 365.25, 1 / 12)
        cagr = float(nav["equity"][-1]) ** (1 / years) - 1
        peak = nav["equity"].cum_max()
        mdd = float((nav["equity"] / peak - 1).min())
        mean, std = float(book["net"].mean()), float(book["net"].std())
        sharpe = 0.0 if std == 0 else mean / std * (252 ** 0.5)
        turnover = float(book["turnover_proxy"].fill_null(0).sum()) / years
        rows.append({
            "variant": "budgeted", "cost_multiplier": float(multiplier), "cagr": cagr, "sharpe": sharpe,
            "max_drawdown": mdd, "annualized_one_way_turnover": turnover,
            "active_start": str(start), "report_end": str(end),
        })
    conclusion = "RESEARCH_ONLY"
    if rows[2]["cagr"] <= 0 or rows[1]["sharpe"] < 0.6 or rows[1]["annualized_one_way_turnover"] > 3:
        conclusion = "REJECTED" if rows[2]["cagr"] <= 0 else "RESEARCH_ONLY"
    assessment = {
        "rows": rows,
        "assessments": {"budgeted": {"conclusion": conclusion, "net_cagr_excess": None}},
        "benchmark_comparisons": [],
        "measurement": "etf_price_return_12_1_top3",
    }
    (folder / "assessment.json").write_text(json.dumps(assessment, indent=2), encoding="utf-8")
    (folder / "config.toml").write_text(
        f'[research]\nid = "few_holdings_s2b_etf_momentum"\n', encoding="utf-8",
    )
    holdings = int(weights.group_by("as_of").len()["len"].median())
    orders = holdings
    corr = _correlation(_monthly_return(navs[1.0].rename({"date": "date"})), q10_monthly)
    report = "\n".join([
        "# S2b ETF 12-1",
        "",
        f"持仓数中位 {holdings}；月订单数约 {orders}；与 Q10 月收益相关 {corr}；结论 {conclusion}。",
        "现金腿：最佳 12-1 动量不为正时只持 511010.SH。",
        "",
    ])
    (folder / "report.md").write_text(report, encoding="utf-8")
    register_run(folder)
    return {"id": "s2b_etf_momentum", "holdings": holdings, "monthly_orders": orders,
            "q10_corr": corr, "conclusion": conclusion}


def run(*, config: Path = DEFAULT_CONFIG, output: Path | None = None, data_root: Path = Path("data")) -> dict:
    spec = load_config(config)
    root = output or Path(f"artifacts/research/few_holdings_v1_{dt.date.today():%Y%m%d}")
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_bytes(config.read_bytes())
    books = run_s2a(spec, root, data_root)
    q10 = _monthly_return(_read_nav(Path(spec["q10_nav"])))
    hundred = next(book for book in books if book["cash"] < 500_000)
    targets = pl.concat([
        pl.read_parquet(path) for path in (root / hundred["id"]).glob("budgeted/cost_1/*/budget_targets.parquet")
    ])
    symbols = targets["symbol"].unique().to_list()
    prices = _closes(symbols, data_root)
    lots = lot_constraint_share(targets, prices, cash=hundred["cash"])
    _annotate(root / hundred["id"], [
        f"lot_constraint 拒绝占比 = {lots['lot_constraint']} ({lots['rejected']}/{lots['requested']})",
    ])
    etf = run_s2b(spec, root, data_root, q10)
    lines = ["# 少持仓", "", "|假设|持仓数|月订单数|与 Q10 月收益相关|结论|", "|---|---:|---:|---:|---|"]
    for book in books:
        nav = _read_nav(root / book["id"] / "budgeted" / "cost_1")
        corr = _correlation(_monthly_return(nav), q10)
        trades = pl.concat([
            pl.read_parquet(path) for path in (root / book["id"]).glob("budgeted/cost_1/*/trades.parquet")
        ])
        months = max(trades["date"].dt.truncate("1mo").n_unique(), 1) if trades.height else 1
        orders = trades.height / months
        lines.append(f"|{book['id']}|{book['holdings']}|{orders:.1f}|{corr}|{book.get('conclusion')}|")
        book["q10_corr"] = corr
        book["monthly_orders"] = orders
    lines.append(
        f"|{etf['id']}|{etf['holdings']}|{etf['monthly_orders']}|{etf['q10_corr']}|{etf['conclusion']}|"
    )
    lines += ["", "对照是 Q10 Top50 预算账户，不是新的参数扫描。", ""]
    (root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {"output": str(root), "lot_constraint": lots, "books": books, "etf": etf}
    (root / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()
    print(json.dumps(run(config=args.config, output=args.output, data_root=args.data_root),
                     ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
