"""One frozen calendar hypothesis through the existing continuous ETF account."""
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
from quant.strategies.calendar_allocation import calendar_targets

RULES = ("calendar_bond", "static_calendar_exposure", "calendar_cash", "bond_only")
INPUTS = ("bars", "prices", "calendar", "instruments", "dividends")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def statistics(returns):
    return {**measure(returns), "cagr": float(np.expm1(np.log1p(returns).sum() * 252 / len(returns))),
            "annualized_volatility": float(returns.std(ddof=1) * np.sqrt(252))}


def paired_bootstrap(primary, control, *, samples, block_months, seed):
    """Paired circular calendar-month blocks; uncertainty, not new test data."""
    if not primary.index.equals(control.index) or len(primary) == 0:
        raise ValueError("Bootstrap requires aligned returns")
    excess = np.log1p(primary) - np.log1p(control)
    monthly = excess.groupby(excess.index.to_period("M")).agg(["sum", "count"])
    values = monthly.to_numpy()
    n = len(values)
    if n < 2 * block_months:
        raise ValueError("Insufficient blocks")
    rng = np.random.default_rng(seed)
    estimates = []
    for _ in range(samples):
        starts = rng.integers(0, n, size=int(np.ceil(n / block_months)))
        indices = ((starts[:, None] + np.arange(block_months)) % n).ravel()[:n]
        draw = values[indices]
        estimates.append(float(draw[:, 0].sum() * 252 / draw[:, 1].sum()))
    return dict(months=n, block_months=block_months, samples=samples, seed=seed,
                annualized_log_excess=float(excess.sum() * 252 / len(excess)),
                lower_95=float(np.quantile(estimates, .025)), upper_95=float(np.quantile(estimates, .975)),
                interpretation="Paired retrospective uncertainty, not multiple-testing-adjusted or independent OOS")


def validate_inputs(frames, spec):
    names = [spec["equity_symbol"], spec["bond_symbol"]]
    dates = frames["calendar"].filter((pl.col("market") == "SH") & pl.col("is_open")
        & pl.col("date").is_between(spec["start"], spec["end"]))["date"].sort().to_list()
    if not dates:
        raise ValueError("No research sessions")
    for kind, column in [("bars", "close"), ("prices", "adjusted_close")]:
        for symbol in names:
            part = frames[kind].filter((pl.col("symbol") == symbol)
                & pl.col("trade_date").is_between(spec["start"], spec["end"]))
            if sorted(part["trade_date"]) != dates or part[column].is_null().any() or not part[column].is_finite().all() or (part[column] <= 0).any():
                raise ValueError(f"Incomplete/nonpositive {kind} {symbol}")
    return dates


def report(output, spec, frames):
    rows, assets, verifications, periods, blocks, state_rows = [], [], [], [], [], []
    navs = {}
    for cost in spec["cost_multipliers"]:
        for rule in RULES:
            folder = output / f"{rule}_{cost:g}"
            nav, attribution, daily, error = account_attribution(folder, frames["bars"], frames["dividends"],
                spec["start"], spec["end"], spec["capital"])
            navs[rule, cost] = nav
            pd.DataFrame(daily).to_csv(folder / "daily_attribution.csv", index=False)
            assets.extend(dict(rule=rule, cost=cost, **x) for x in attribution)
            fills = pl.read_parquet(folder / "trades.parquet").to_pandas()
            rejects = pl.read_parquet(folder / "rejections.parquet")
            previous = nav.equity.shift(1).fillna(spec["capital"])
            nav["one_way_turnover"] = fills.groupby("date").notional.sum().reindex(nav.index, fill_value=0.) / previous / 2
            full_years = [y for y in sorted(set(nav.index.year)) if
                          dt.date(y, 1, 1) >= spec["start"] and dt.date(y, 12, 31) <= spec["end"]]
            annual_turnover = nav.groupby(nav.index.year).one_way_turnover.sum()
            rows.append(dict(rule=rule, cost=cost, **statistics(nav["return"]),
                annualized_one_way_turnover=float(nav.one_way_turnover.sum() * 252 / len(nav)),
                median_full_year_turnover=float(annual_turnover.loc[full_years].median()),
                fees=float(fills.fee.sum()), slippage=float(fills.slippage_cost.sum()),
                orders=len(fills), rejected_orders=rejects.height,
                mean_cash_weight=float((nav.cash / nav.equity).mean())))
            verifications.append(dict(rule=rule, cost=cost, sessions=len(nav),
                accounting_error_cny=error, nonnegative_cash=bool((nav.cash >= 0).all()),
                integer_lots=bool((fills.quantity % 100 == 0).all())))
    market_path = Path("artifacts/research/market_indicators_20260922_02/market_states.parquet")
    market = pl.read_parquet(market_path).to_pandas().set_index("effective_date").market_state
    benchmarks = {}
    for symbol in [spec["equity_symbol"], spec["bond_symbol"]]:
        b = frames["bars"].filter(pl.col("symbol") == symbol).to_pandas().set_index("trade_date").sort_index()
        p = frames["prices"].filter(pl.col("symbol") == symbol).to_pandas().set_index("trade_date").sort_index()
        p = p.loc[p.index >= pd.Timestamp(spec["start"])]
        p = p.loc[p.index <= pd.Timestamp(spec["end"]), "adjusted_close"]
        opening = float(p.iloc[0] * b.loc[p.index[0], "open"] / b.loc[p.index[0], "close"])
        benchmarks[symbol] = p / np.r_[opening, p.to_numpy()[:-1]] - 1
    benchmark_rows = [dict(symbol=s, **statistics(r)) for s, r in benchmarks.items()]
    comparison = []
    for row in rows:
        rule, cost = row["rule"], row["cost"]
        nav = navs[rule, cost]
        control = navs["static_calendar_exposure", cost]
        cm = statistics(control["return"])
        comparison.append(dict(rule=rule, cost=cost, cagr_excess_pp=100 * (row["cagr"] - cm["cagr"]),
            sharpe_rf2_difference=row["sharpe_rf2"] - cm["sharpe_rf2"],
            drawdown_difference_pp=100 * (row["max_drawdown"] - cm["max_drawdown"])))
        for kind, labels in [("year", nav.index.strftime("%Y")), ("month", nav.index.strftime("%Y-%m"))]:
            for period, part in nav.groupby(labels):
                metric = measure(part["return"])
                cr = measure(control.loc[part.index, "return"])["net_return"]
                eq = measure(benchmarks[spec["equity_symbol"]].loc[part.index])["net_return"]
                bd = measure(benchmarks[spec["bond_symbol"]].loc[part.index])["net_return"]
                periods.append(dict(rule=rule, cost=cost, kind=kind, period=period, **metric,
                    benchmark_return=cr, excess_pp=100 * (metric["net_return"] - cr),
                    equity_total_return=eq, bond_total_return=bd,
                    equity_excess_pp=100 * (metric["net_return"] - eq),
                    bond_excess_pp=100 * (metric["net_return"] - bd),
                    one_way_turnover=float(part.one_way_turnover.sum())))
        begin = spec["start"]
        for end in spec["diagnostic"]["subperiod_ends"]:
            part = nav.loc[str(begin):str(end)]
            metric = statistics(part["return"])
            cm = statistics(control.loc[part.index, "return"])
            blocks.append(dict(rule=rule, cost=cost, start=str(begin), end=str(end), **metric,
                static_cagr=cm["cagr"], cagr_excess_pp=100 * (metric["cagr"] - cm["cagr"])))
            begin = end + dt.timedelta(days=1)
        states = market.reindex(nav.index).fillna("unknown")
        for _, segment in states.groupby(states.ne(states.shift()).cumsum()):
            part = nav.loc[segment.index]
            applicable = bool((part.market_value > 0).any())
            state_rows.append(dict(rule=rule, cost=cost, state=segment.iloc[0],
                start=str(segment.index[0].date()), end=str(segment.index[-1].date()),
                applicable=applicable, **(measure(part["return"]) if applicable else
                dict(net_return=None, sharpe_rf0=None, sharpe_rf2=None, max_drawdown=None, sessions=len(part))),
                interpretation="descriptive only; states never select allocation"))
    p = next(r for r in rows if r["rule"] == "calendar_bond" and r["cost"] == 2)
    delta = next(r for r in comparison if r["rule"] == "calendar_bond" and r["cost"] == 2)
    wins = sum(r["cagr_excess_pp"] > 0 for r in blocks if r["rule"] == "calendar_bond" and r["cost"] == 2)
    bootstrap = paired_bootstrap(navs["calendar_bond", 2]["return"], navs["static_calendar_exposure", 2]["return"],
        samples=spec["diagnostic"]["bootstrap_samples"], block_months=spec["diagnostic"]["bootstrap_block_months"],
        seed=spec["diagnostic"]["bootstrap_seed"])
    checks = dict(positive_stressed_increment=delta["cagr_excess_pp"] > 0,
        higher_stressed_sharpe=delta["sharpe_rf2_difference"] > 0,
        at_least_two_blocks=wins >= 2, bootstrap_lower_positive=bootstrap["lower_95"] > 0)
    checks = {key: bool(value) for key, value in checks.items()}
    decision = "CONTINUE_RESEARCH_NOT_ADMISSION" if all(checks.values()) else "STOP_THIS_FIXED_CALENDAR_HYPOTHESIS"
    result = dict(hypothesis=spec["hypothesis_id"], auto_trade=False, classification="RESEARCH_ONLY",
        start=str(spec["start"]), end=str(spec["end"]), capital=spec["capital"], results=rows,
        comparison=comparison, checks=checks, decision=decision, bootstrap=bootstrap,
        source_limitations=spec["source_limitations"], historical_status=spec["historical_status"],
        benchmark_definition="total-return indices normalized at first execution open; no integer-lot account used as index",
        benchmarks=benchmark_rows, formal_admission="NOT_EVALUATED; no paper-account creation",
        calendar_assumption=spec["calendar_assumption"], cost_policy=spec["cost_policy"])
    (output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "verification.json").write_text(json.dumps(verifications, indent=2), encoding="utf-8")
    for filename, items in [("comparison", comparison), ("asset_attribution", assets),
                             ("annual_monthly", periods), ("chronological_blocks", blocks),
                             ("continuous_market_events", state_rows), ("benchmarks", benchmark_rows)]:
        pd.DataFrame(items).to_csv(output / f"{filename}.csv", index=False)
    table = pd.DataFrame(rows)[["rule", "cost", "cagr", "sharpe_rf2", "max_drawdown", "median_full_year_turnover"]]
    text = "# 固定月末/月初 ETF 配置研究\n\n机器生成；10万元、最低佣金1元、三档成本，2013-11-01至2026-08-31连续账户。\n\n"
    text += table.to_markdown(index=False) + "\n\n研究决定：" + decision + "\n\n"
    text += json.dumps(checks, ensure_ascii=False, indent=2) + "\n\n"
    text += "## 机制与对照\n\n月末最后一日开盘至下月第四个交易日开盘，25%配置510300，其余511010；其他日期全配511010。"
    text += "calendar_cash在窗口外只留75%国债与25%现金，分离资金停泊贡献；static_calendar_exposure按当月交易日数固定约5%权益，匹配目标时间暴露，不声称波动匹配。bond_only为国债买入持有账户。\n\n"
    text += "论文原规则是收盘到收盘收益，本实验事前固定为下一开盘执行的可交易改写，不能称严格复现。"
    text += "文献发现并不证明工资或资金流是原因；这里只测试日历相关收益能否覆盖成本。\n\n"
    text += "## 完整性与限制\n\n信号不读取价格；2020年春节临时延长休市已按1月27日公告时点处理，不能在1月23日提前买入。1月静态对照也按当时预定的17个交易日计算。其他历史公告版本未穷尽独立核验。"
    text += "年度/月度、三段固定时期、全部连续行情事件、实际持仓收益贡献及逐笔订单分别保存在同目录CSV/Parquet。"
    text += "收益指数含现金分红，账户含整手、未成交、费用和分红应收；rf2为固定年有效2%的敏感性，不是历史实际无风险利率。"
    text += "最初建仓前没有人为现金前缀，之后全部日期保留；事件切片是描述，不用于择时。\n\n"
    text += "已见历史不是新样本外；早期国债ETF日线尚缺独立报价交叉验证；每日开盘价模型不证明人工延迟可成交。"
    text += "区块重抽样保持成对12个月片段，不校正整个项目的多重搜索。无正式准入或新模拟账户，不改旧实验与门槛。\n\n"
    text += "研究停止条件及冻结参数见config.toml；若不通过，不扩大日期、仓位或行情阈值搜索。\n\n"
    text += "## 原始研究\n\n" + "\n".join("- " + url for url in spec["sources"]) + "\n"
    (output / "report.md").write_text(text, encoding="utf-8")
    return result


def run(config, output):
    spec = tomllib.loads(config.read_text(encoding="utf-8"))
    if spec["auto_trade"] is not False or spec["cost_multipliers"] != [.5, 1., 2.] or spec["include_last_session"] is not True:
        raise ValueError("Manual research and all three costs required")
    output.mkdir(parents=True, exist_ok=False)
    (output / "config.toml").write_bytes(config.read_bytes())
    source = Path(spec["inputs"])
    paths = [config, source / "receipt.json", *(source / f"{x}.parquet" for x in INPUTS),
        Path(__file__), Path("src/quant/strategies/calendar_allocation.py"),
        Path("src/quant/research/classic_monthly_baseline.py"), Path("src/quant/research/etf_measurement.py"),
        Path("src/quant/research/joint_account_report.py"), Path("src/quant/backtest/daily_account.py"),
        Path("src/quant/backtest/daily_simulator.py"), Path("src/quant/backtest/costs.py"),
        Path("src/quant/data/etf_paper_inputs.py"),
        Path("artifacts/research/market_indicators_20260922_02/market_states.parquet")]
    hashes = {str(path): digest(path) for path in paths}
    freeze = dict(frozen_at=dt.datetime.now(dt.timezone.utc).isoformat(), hashes=hashes,
                  auto_trade=False, stage="preregistered_before_return_computation")
    (output / "freeze.json").write_text(json.dumps(freeze, indent=2), encoding="utf-8")
    names = [spec["equity_symbol"], spec["bond_symbol"]]
    frames = {x: pl.read_parquet(source / f"{x}.parquet") for x in INPUTS}
    for name in ["bars", "prices", "instruments", "dividends"]:
        frames[name] = frames[name].filter(pl.col("symbol").is_in(names))
    sessions = validate_inputs(frames, spec)
    targets = {}
    for rule in RULES:
        target, schedule = calendar_targets(frames["calendar"], start=spec["start"], end=spec["end"],
            name=rule, equity_symbol=spec["equity_symbol"], bond_symbol=spec["bond_symbol"],
            sleeve=spec["equity_sleeve"], first_sessions=spec["first_sessions"],
            calendar_revisions=spec.get("calendar_revisions", []))
        targets[rule] = target
        schedule.write_csv(output / f"{rule}_schedule.csv")
    for cost in spec["cost_multipliers"]:
        settings = dict(portfolio=dict(initial_cash=spec["capital"]), costs=copy.deepcopy(spec["costs"]))
        for field in ["commission_rate", "commission_min", "slippage", "slippage_per_share"]:
            settings["costs"]["etf"][field] *= cost
        states = etf_session_states(frames["bars"], frames["dividends"], slippage_per_share=.001 * cost)
        for rule in RULES:
            folder = output / f"{rule}_{cost:g}"
            folder.mkdir()
            nav, trades, rejects = replay(bars=frames["bars"], calendar=frames["calendar"], instruments=frames["instruments"],
                targets=targets[rule], dividends=frames["dividends"], market_states=states,
                config=settings, sessions=sessions, name=rule, validate_once=True)
            for label, frame in [("nav", nav), ("trades", trades), ("rejections", rejects), ("targets", targets[rule])]:
                frame.write_parquet(folder / f"{label}.parquet")
            print(f"completed {rule} {cost:g}x", flush=True)
    if any(digest(path) != checksum for path, checksum in hashes.items()):
        raise ValueError("Frozen source/code changed during run")
    result = report(output, spec, frames)
    generated = {str(path.relative_to(output)): digest(path) for path in output.rglob("*") if path.is_file()}
    (output / "manifest.json").write_text(json.dumps(generated, indent=2), encoding="utf-8")
    print(json.dumps(dict(decision=result["decision"], checks=result["checks"])), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/research/calendar_allocation_v1.toml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.config, args.output)
