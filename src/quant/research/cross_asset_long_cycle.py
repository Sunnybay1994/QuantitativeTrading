"""Extend original B13/B16 rules to audited long history at personal capital."""
import argparse
import copy
import datetime as dt
import hashlib
import json
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

from quant.data.etf_paper_inputs import etf_session_states
from quant.research.classic_monthly_baseline import replay
from quant.research.etf_measurement import account_attribution
from quant.research.joint_account_report import measure
from quant.research.monthly_etf import monthly_targets, completed_month_prices
from quant.strategies.monthly_etf import MonthlyEtfStrategy
from quant.strategies.inverse_volatility import InverseVolatilityStrategy


def stats(r):
    return {**measure(r), "cagr": float(np.expm1(np.log1p(r).sum() * 252 / len(r))),
            "annualized_volatility": float(r.std(ddof=1) * np.sqrt(252))}


def build_targets(frames, spec, original, inverse):
    symbols = tuple(original["universe"]["symbols"])
    common_months = completed_month_prices(frames["prices"], frames["calendar"])
    counts = common_months.filter(pl.col("trade_date") < spec["start"]).group_by("symbol").len()
    if set(counts["symbol"]) != set(symbols) or counts["len"].min() != 13:
        raise ValueError("Start must follow the first 13 completed common month prices")
    s = original["strategy"]
    dual = MonthlyEtfStrategy(symbols, s["kind"], s["lookback_months"], s["skip_months"],
        s["top_k"], name="dual_momentum", absolute_momentum_filter=s["absolute_momentum_filter"])
    iv = InverseVolatilityStrategy(symbols, inverse["strategy"]["lookback_sessions"], name="inverse_volatility")
    return {name: monthly_targets(frames["prices"], frames["calendar"], start=spec["start"], end=spec["end"],
                candidates=symbols, name=name, strategy=strategy)
            for name, strategy in [("dual_momentum", dual), ("equal_weight", None), ("inverse_volatility", iv)]}


def generate_report(output, spec, frames):
    results, assets, verifications, periods, blocks, events = [], [], [], [], [], []
    navs = {}
    for cost in spec["cost_multipliers"]:
        for rule in spec["rules"]:
            folder = output / f"{rule}_{cost:g}"
            nav, attribution, daily, error = account_attribution(folder, frames["bars"], frames["dividends"],
                spec["start"], spec["end"], spec["capital"])
            if nav.market_value.iloc[0] <= 0:
                raise ValueError("Cash prefix requires aligned actual-holding-period measurement; do not score it as strategy history")
            navs[rule, cost] = nav
            pd.DataFrame(daily).to_csv(folder / "daily_attribution.csv", index=False)
            trades = pl.read_parquet(folder / "trades.parquet").to_pandas()
            previous = nav.equity.shift(1).fillna(spec["capital"])
            nav["turnover"] = trades.groupby("date").notional.sum().reindex(nav.index, fill_value=0.) / previous / 2
            full = nav.groupby(nav.index.year).turnover.sum().loc[2015:2025]
            results.append(dict(rule=rule, cost=cost, **stats(nav["return"]),
                annualized_one_way_turnover=float(nav.turnover.sum() * 252 / len(nav)),
                median_full_year_turnover=float(full.median()), fees=float(trades.fee.sum()),
                slippage=float(trades.slippage_cost.sum()), orders=len(trades),
                rejections=pl.read_parquet(folder / "rejections.parquet").height,
                mean_cash_weight=float((nav.cash / nav.equity).mean())))
            assets.extend(dict(rule=rule, cost=cost, **row) for row in attribution)
            verifications.append(dict(rule=rule, cost=cost, accounting_error=error,
                nonnegative_cash=bool((nav.cash >= 0).all()),
                all_fills_in_lots=bool((trades.quantity % 100 == 0).all())))
    market = pl.read_parquet("artifacts/research/market_indicators_20260922_02/market_states.parquet").to_pandas().set_index("effective_date").market_state
    comparisons = []
    for row in results:
        rule, cost = row["rule"], row["cost"]
        nav = navs[rule, cost]
        control = navs["equal_weight", cost]
        b = stats(control["return"])
        comparisons.append(dict(rule=rule, cost=cost, equal_weight_cagr_excess_pp=100*(row["cagr"]-b["cagr"]),
            equal_weight_sharpe_difference=float(row["sharpe_rf2"]-b["sharpe_rf2"])))
        for kind, labels in [("year", nav.index.strftime("%Y")), ("month", nav.index.strftime("%Y-%m"))]:
            for period, part in nav.groupby(labels):
                metric = measure(part["return"])
                baseline = measure(control.loc[part.index, "return"])["net_return"]
                periods.append(dict(rule=rule, cost=cost, kind=kind, period=period, **metric,
                    benchmark_return=baseline, excess_pp=100*(metric["net_return"]-baseline)))
        start = spec["start"]
        for end in spec["subperiod_ends"]:
            part = nav.loc[str(start):str(end)]
            metric = stats(part["return"])
            base = stats(control.loc[part.index, "return"])
            blocks.append(dict(rule=rule, cost=cost, start=str(start), end=str(end), **metric,
                benchmark_cagr=base["cagr"], excess_pp=100*(metric["cagr"]-base["cagr"])))
            start = end + dt.timedelta(days=1)
        state = market.reindex(nav.index).fillna("unknown")
        for _, segment in state.groupby(state.ne(state.shift()).cumsum()):
            part = nav.loc[segment.index]
            applicable = bool((part.market_value > 0).any())
            events.append(dict(rule=rule, cost=cost, state=segment.iloc[0],
                start=str(segment.index[0].date()), end=str(segment.index[-1].date()), applicable=applicable,
                **(measure(part["return"]) if applicable else dict(net_return=None, max_drawdown=None, sessions=len(part)))))
    stressed = next(r for r in results if r["rule"] == "dual_momentum" and r["cost"] == 2)
    comparator = next(r for r in results if r["rule"] == "equal_weight" and r["cost"] == 2)
    diagnostic = dict(stressed_higher_cagr=bool(stressed["cagr"] > comparator["cagr"]),
        stressed_higher_sharpe=bool(stressed["sharpe_rf2"] > comparator["sharpe_rf2"]),
        stressed_better_drawdown=bool(stressed["max_drawdown"] >= comparator["max_drawdown"]),
        all_fixed_blocks_positive_excess=bool(all(r["excess_pp"] > 0 for r in blocks if r["rule"] == "dual_momentum" and r["cost"] == 2)))
    result = dict(auto_trade=False, classification="RESEARCH_ONLY", start=str(spec["start"]), end=str(spec["end"]),
        capital=spec["capital"], results=results, comparison=comparisons, descriptive_diagnostics=diagnostic,
        original_admission_unchanged=True, interpretation=spec["interpretation"],
        limitations=["Early bond/gold quotes not independently validated", "Daily-open model, not manual-delay execution validation",
                     "Cash-flow and three-asset universe known retrospectively; no new OOS", "Net equal-weight account is a mechanism control, not a formal admission return-index benchmark"])
    (output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, rows in [("asset_attribution", assets), ("annual_monthly", periods), ("chronological_blocks", blocks), ("continuous_market_events", events), ("comparison", comparisons)]:
        pd.DataFrame(rows).to_csv(output / f"{name}.csv", index=False)
    (output / "verification.json").write_text(json.dumps(verifications, indent=2))
    columns = ["rule", "cost", "cagr", "sharpe_rf2", "max_drawdown", "median_full_year_turnover"]
    text = "# 原双动量与逆波动规则的长周期检验\n\n机器生成；同一10万元、1元最低佣金和三档成本；2014-08-01至2026-08-31，连续账户。\n\n"
    text += pd.DataFrame(results)[columns].to_markdown(index=False) + "\n\n"
    text += "B13原规则：每月从沪深300、国债、黄金ETF中选择过去12个月总回报最高者，收益必须大于零，否则持现金；不换参数。B16原规则：60日收益波动倒数配置同三只ETF。等权账户为同资金同成本机制对照。\n\n"
    text += "权益、国债和黄金的实际权重及净收益贡献见asset_attribution.csv；全部年度/月度、固定三段时期、连续行情事件见对应CSV。rf2为固定年有效2%，收益年化按252日。市场状态只作描述，不决定配置。\n\n"
    text += "仅补充历史检验：不改原短历史负面结论，不将已见历史称新样本外，不用更高年化替代夏普/回撤。等权账户不是准入收益指数；未自动判准入，未新建模拟盘。早期债/金价格独立验证及人工执行仍不足。\n\n"
    text += "描述性对照：\n\n" + json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n"
    (output / "report.md").write_text(text, encoding="utf-8")
    return result


def run(config, output):
    spec = tomllib.loads(config.read_text(encoding="utf-8"))
    if spec["auto_trade"] is not False or spec["capital"] != 100000 or spec["cost_multipliers"] != [.5, 1., 2.]:
        raise ValueError("Require manual 100k three-cost comparison")
    original = tomllib.loads(Path(spec["source_config"]).read_text())
    inverse = tomllib.loads(Path(spec["inverse_volatility_config"]).read_text())
    output.mkdir(parents=True, exist_ok=False)
    (output / "config.toml").write_bytes(config.read_bytes())
    paths = [config, Path(spec["source_config"]), Path(spec["inverse_volatility_config"]), Path(__file__),
        *(Path(spec["inputs"]) / (name + ".parquet") for name in ["bars", "prices", "calendar", "instruments", "dividends"]),
        Path(spec["inputs"]) / "receipt.json",
        *(Path("src/quant") / name for name in ["research/monthly_etf.py", "research/classic_monthly_baseline.py",
          "research/etf_measurement.py", "research/joint_account_report.py", "strategies/monthly_etf.py", "strategies/inverse_volatility.py",
          "backtest/daily_account.py", "backtest/daily_simulator.py", "backtest/costs.py", "data/etf_paper_inputs.py"]),
        Path("artifacts/research/market_indicators_20260922_02/market_states.parquet")]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (output / "freeze.json").write_text(json.dumps(dict(created_at=dt.datetime.now(dt.timezone.utc).isoformat(), hashes=hashes, before_returns=True), indent=2))
    frames = {name: pl.read_parquet(Path(spec["inputs"]) / f"{name}.parquet") for name in ["bars", "prices", "calendar", "instruments", "dividends"]}
    sessions = frames["calendar"].filter((pl.col("market") == "SH") & pl.col("is_open") & pl.col("date").is_between(spec["start"], spec["end"]))["date"].sort().to_list()
    for kind in ["bars", "prices"]:
        for symbol in original["universe"]["symbols"]:
            frame = frames[kind].filter((pl.col("symbol") == symbol) & pl.col("trade_date").is_between(spec["start"], spec["end"]))
            if sorted(frame["trade_date"]) != sessions:
                raise ValueError("Incomplete common history")
    targets = build_targets(frames, spec, original, inverse)
    for cost in spec["cost_multipliers"]:
        scenario = copy.deepcopy(original)
        scenario["portfolio"]["initial_cash"] = spec["capital"]
        scenario["costs"]["etf"]["commission_min"] = spec["commission_min"]
        scenario["costs"]["etf"]["effective_from"] = frames["bars"]["trade_date"].min()
        for field in ["commission_rate", "commission_min", "slippage", "slippage_per_share"]:
            scenario["costs"]["etf"][field] *= cost
        states = etf_session_states(frames["bars"], frames["dividends"], slippage_per_share=.001*cost)
        for name in spec["rules"]:
            folder = output / f"{name}_{cost:g}"
            folder.mkdir()
            nav, fills, rejects = replay(bars=frames["bars"], calendar=frames["calendar"], instruments=frames["instruments"],
                targets=targets[name], dividends=frames["dividends"], market_states=states, config=scenario,
                sessions=sessions, name=name, validate_once=True)
            for label, frame in [("nav", nav), ("trades", fills), ("rejections", rejects), ("targets", targets[name])]:
                frame.write_parquet(folder / f"{label}.parquet")
            print(f"complete {name} {cost:g}x", flush=True)
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items())
    result = generate_report(output, spec, frames)
    (output / "manifest.json").write_text(json.dumps({str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest() for p in output.rglob("*") if p.is_file()}, indent=2))
    print(json.dumps(result["descriptive_diagnostics"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/research/cross_asset_long_cycle_v1.toml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.config, args.output)
