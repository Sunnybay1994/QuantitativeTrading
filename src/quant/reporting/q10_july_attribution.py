"""Build A1 2026-07 attribution package from frozen R3 + Q10 backtest artifacts."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import polars as pl

from quant.data.equal_weight_index import load_return_benchmarks
from quant.data.refresh_stocks import read_stock_data

STYLES = [
    "size", "value", "momentum", "volatility", "liquidity",
    "profitability", "growth", "leverage", "beta", "reversal",
]
OUT = Path("artifacts/risk/q10_2026_07_attribution_20261009")
R3 = Path("artifacts/risk/r3_lightweight_20260914_03")
Q10 = Path("artifacts/models/q10_sue_v2_turnover_budget_05_20260912_01/budgeted/cost_1")
BENCH_CFG = Path("configs/data/p8_return_benchmarks_20260912.toml")
REFRESH = Path("configs/data/refresh.toml")


def month_return(nav: pl.DataFrame, start: dt.date, end: dt.date) -> float:
    """Capital-linked month return using last equity before start and last equity on/before end."""
    prior = nav.filter(pl.col("date") < start).sort("date").tail(1)
    last = nav.filter(pl.col("date") <= end).sort("date").tail(1)
    if prior.is_empty() or last.is_empty():
        raise ValueError(f"missing nav around {start}..{end}")
    return float(last["equity"][0] / prior["equity"][0] - 1)


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"output exists: {OUT}")
    OUT.mkdir(parents=True)

    monthly = pl.read_csv(R3 / "monthly_attribution.csv").filter(
        (pl.col("portfolio") == "q10") & (pl.col("month") == "2026-07")
    )
    if monthly.height != 1:
        raise SystemExit("expected one 2026-07 q10 monthly attribution row")
    row = monthly.to_dicts()[0]
    industry_cols = [c for c in monthly.columns if c.startswith("industry:")]
    style_contrib = {s: float(row[s]) for s in STYLES}
    industry_by_name = {c.removeprefix("industry:"): float(row[c]) for c in industry_cols if abs(float(row[c])) > 1e-6}
    industry_total = sum(float(row[c]) for c in industry_cols)
    other_styles = sum(style_contrib[s] for s in STYLES if s != "size")

    # Daily exposures averaged over July (active style exposure levels)
    expo = pl.read_parquet(R3 / "daily_exposures.parquet").filter(
        (pl.col("portfolio") == "q10")
        & (pl.col("date") >= pl.date(2026, 7, 1))
        & (pl.col("date") <= pl.date(2026, 7, 31))
    )
    mean_expo = {s: float(expo[s].mean()) for s in STYLES}
    mean_industry = {
        c.removeprefix("industry:"): float(expo[c].mean())
        for c in expo.columns if c.startswith("industry:") and abs(float(expo[c].mean())) > 0.005
    }

    # Security contributions over July
    sec = pl.read_parquet(R3 / "q10_security_daily.parquet").filter(
        (pl.col("date") >= pl.date(2026, 7, 1)) & (pl.col("date") <= pl.date(2026, 7, 31))
    )
    by_symbol = (
        sec.group_by("symbol")
        .agg(
            pl.col("contribution").sum().alias("contribution"),
            pl.col("prior_weight").mean().alias("mean_prior_weight"),
            pl.col("close_quote_missing").sum().alias("missing_quote_days"),
            pl.len().alias("days"),
        )
        .sort("contribution", descending=True)
    )
    top10 = by_symbol.head(10)
    bottom5 = by_symbol.tail(5)
    top10_share = float(top10["contribution"].sum() / abs(row["return"])) if row["return"] else None
    positive = by_symbol.filter(pl.col("contribution") > 0)
    top10_of_positive = float(top10["contribution"].sum() / positive["contribution"].sum()) if positive.height else None

    # Holdings on first July session (post June month-end rebalance)
    first = sec["date"].min()
    hold0 = sec.filter(pl.col("date") == first).filter(pl.col("prior_weight") > 1e-6).sort("prior_weight", descending=True)
    n_names = hold0.height
    invested = float(hold0["prior_weight"].sum())

    # Rejections / OPEN_UNKNOWN in July for Q10 cost_1
    rej = pl.read_parquet(Q10 / "2026/rejections.parquet")
    rej_jul = rej.filter((pl.col("date") >= pl.date(2026, 7, 1)) & (pl.col("date") <= pl.date(2026, 7, 31)))
    if rej_jul.height:
        rej_jul = rej_jul.with_columns(
            (pl.col("rejected_quantity").abs() * pl.col("reference_price").fill_null(0.0)).alias("notional")
        )
        rej_summary = rej_jul.group_by("reason").agg(
            pl.len().alias("n"), pl.col("notional").sum().alias("notional")
        ).sort("n", descending=True)
    else:
        rej_summary = pl.DataFrame({"reason": [], "n": pl.Series([], dtype=pl.UInt32), "notional": pl.Series([], dtype=pl.Float64)})

    # Bar quality for top contributors: suspension / limit-ish / missing
    symbols = top10["symbol"].to_list() + bottom5["symbol"].to_list()
    bars = read_stock_data(
        data_root=Path("data"),
        config=REFRESH,
        table="bar_1d",
        start=dt.date(2026, 6, 30),
        end=dt.date(2026, 7, 31),
    ).filter(pl.col("symbol").is_in(symbols))
    # Infer suspension / limit from typical columns if present
    bar_cols = set(bars.columns)
    quality_rows = []
    for sym in symbols:
        b = bars.filter(
            (pl.col("symbol") == sym)
            & (pl.col("trade_date") >= pl.date(2026, 7, 1))
            & (pl.col("trade_date") <= pl.date(2026, 7, 31))
        )
        row_q = {
            "symbol": sym,
            "bar_days": b.height,
            "zero_volume_days": int((b["volume"] == 0).sum()) if "volume" in bar_cols else None,
        }
        if "is_suspended" in bar_cols:
            row_q["suspended_days"] = int(b["is_suspended"].fill_null(False).sum())
        if "limit_status" in bar_cols:
            row_q["limit_days"] = int(b.filter(pl.col("limit_status").is_in(["U", "D", "up", "down"])).height)
        quality_rows.append(row_q)
    quality = pl.DataFrame(quality_rows)

    # Benchmark returns July 2026
    benches = load_return_benchmarks(
        config=BENCH_CFG,
        data_root=Path("data"),
        start=dt.date(2026, 6, 1),
        end=dt.date(2026, 7, 31),
        names=["all_market_equal_weight", "csi800_equal_weight", "510300"],
    )
    bench_rets = {}
    for name, frame in benches.items():
        # unit_nav monthly return
        prior = frame.filter(pl.col("date") < pl.date(2026, 7, 1)).sort("date").tail(1)
        last = frame.filter(pl.col("date") <= pl.date(2026, 7, 31)).sort("date").tail(1)
        bench_rets[name] = float(last["unit_nav"][0] / prior["unit_nav"][0] - 1)

    # Equal-weight index diagnostics for July
    ew_folder = Path("data/clean/equal_weight_indexes/battery_monthly_gross_20260912")
    bench_check: dict = {"benchmark_returns_2026_07": bench_rets}
    # Try selections / events for missing_quote
    data_parquet = ew_folder / "data.parquet"
    events_parquet = ew_folder / "events.parquet"
    for name in ("all_market_equal_weight", "csi800_equal_weight"):
        info: dict = {}
        sel_path = ew_folder / f"{name}_selections.parquet"
        if sel_path.exists():
            sel = pl.read_parquet(sel_path)
            date_col = "date" if "date" in sel.columns else ("trade_date" if "trade_date" in sel.columns else None)
            if date_col:
                sel = sel.filter((pl.col(date_col) >= pl.date(2026, 7, 1)) & (pl.col(date_col) <= pl.date(2026, 7, 31)))
            info["selection_rows"] = sel.height
            info["selection_cols"] = sel.columns
            for col in ("n_members", "member_count", "n_selected"):
                if col in sel.columns:
                    info["mean_n_members"] = float(sel[col].mean())
                    info["min_n_members"] = int(sel[col].min())
                    info["max_n_members"] = int(sel[col].max())
                    break
        if data_parquet.exists():
            df = pl.read_parquet(data_parquet)
            name_col = next((c for c in ("index_name", "name", "index") if c in df.columns), None)
            date_col = next((c for c in ("trade_date", "date") if c in df.columns), None)
            if name_col:
                df = df.filter(pl.col(name_col) == name)
            if date_col is None:
                raise ValueError(f"no date column in {data_parquet}: {df.columns}")
            jul = df.filter((pl.col(date_col) >= pl.date(2026, 7, 1)) & (pl.col(date_col) <= pl.date(2026, 7, 31)))
            info["daily_rows"] = jul.height
            info["daily_cols"] = jul.columns
            if "missing_quote_weight" in jul.columns and jul.height:
                info["max_missing_quote_weight"] = float(jul["missing_quote_weight"].max())
                info["mean_missing_quote_weight"] = float(jul["missing_quote_weight"].mean())
            if "constituents" in jul.columns and jul.height:
                info["mean_constituents"] = float(jul["constituents"].mean())
                info["min_constituents"] = int(jul["constituents"].min())
                info["max_constituents"] = int(jul["constituents"].max())
            if "rebalance" in jul.columns and jul.height:
                info["rebalance_days"] = int(jul["rebalance"].fill_null(False).sum())
            if "index_level" in jul.columns and jul.height >= 2:
                sorted_jul = jul.sort(date_col)
                info["index_level_start"] = float(sorted_jul["index_level"][0])
                info["index_level_end"] = float(sorted_jul["index_level"][-1])
        if events_parquet.exists():
            evt = pl.read_parquet(events_parquet)
            name_col = next((c for c in ("index_name", "name", "index") if c in evt.columns), None)
            date_col = next((c for c in ("trade_date", "date") if c in evt.columns), None)
            if name_col:
                evt = evt.filter(pl.col(name_col) == name)
            if date_col:
                evt = evt.filter((pl.col(date_col) >= pl.date(2026, 7, 1)) & (pl.col(date_col) <= pl.date(2026, 7, 31)))
            info["event_rows"] = evt.height
            if "kind" in evt.columns and evt.height:
                info["events_by_kind"] = {str(k): int(c) for k, c in evt.group_by("kind").len().iter_rows()}
        bench_check[name] = info

    q10_ret = float(row["return"])
    ew_ret = bench_rets["all_market_equal_weight"]
    excess = q10_ret - ew_ret

    # Strategy nav check
    nav = pl.read_parquet(Q10 / "2026/nav.parquet")
    nav_ret = month_return(nav, dt.date(2026, 7, 1), dt.date(2026, 7, 31))

    # Dominant style drivers
    ranked_styles = sorted(style_contrib.items(), key=lambda kv: abs(kv[1]), reverse=True)
    ranked_industry = sorted(industry_by_name.items(), key=lambda kv: abs(kv[1]), reverse=True)[:8]

    # Decision tree for four-way conclusion
    # 1) Data/benchmark issue if missing_quote extreme or nav mismatch or rejection notional large
    data_issue = False
    data_reasons = []
    mq = bench_check.get("all_market_equal_weight", {}).get("max_missing_quote_weight_daily") or bench_check.get(
        "all_market_equal_weight", {}
    ).get("max_missing_quote_weight")
    if mq is not None and mq > 0.02:
        data_issue = True
        data_reasons.append(f"all_market missing_quote_weight max={mq:.2%}")
    if abs(nav_ret - q10_ret) > 0.002:
        data_issue = True
        data_reasons.append(f"nav vs attribution return gap {nav_ret-q10_ret:.2%}")
    # Cross-check: if EW collapsed vs CSI800/510300 abnormally
    if abs(ew_ret - bench_rets["csi800_equal_weight"]) > 0.15 and abs(ew_ret) > 0.05:
        # large gap alone is not necessarily data error (microcap), but flag for review
        data_reasons.append(
            f"EW vs CSI800 gap={(ew_ret-bench_rets['csi800_equal_weight']):.2%} (may be microcap, not auto-data-fail)"
        )

    few_stocks = top10_of_positive is not None and top10_of_positive >= 0.50 and top10["contribution"].sum() > 0.5 * excess
    # Style/size/beta: size+beta absolute contribution vs industry active?
    # Industry total includes market; active industry = industry - market proxy.
    # Use style |contrib| excluding industry as "style story"
    size_beta = abs(style_contrib["size"]) + abs(style_contrib["beta"])
    style_abs = sum(abs(v) for v in style_contrib.values())
    # Market-embedded industry is large when market crashes; active style offset is the key
    if data_issue and mq is not None and mq > 0.02:
        conclusion = "数据或基准问题"
        rationale = "; ".join(data_reasons)
    elif few_stocks:
        conclusion = "少数个股"
        rationale = f"Top10 占正贡献 {top10_of_positive:.0%}，合计 {top10['contribution'].sum():.2%}"
    elif size_beta >= 0.4 * style_abs and (abs(style_contrib["size"]) > 0.01 or abs(style_contrib["beta"]) > 0.01):
        conclusion = "规模或 Beta 暴露"
        rationale = f"size={style_contrib['size']:.2%}, beta={style_contrib['beta']:.2%}, style_abs={style_abs:.2%}"
    elif abs(industry_total) > abs(other_styles) and abs(industry_total) > 0.03:
        # If industry (incl market) dominates AND styles don't offset — industry exposure
        # But when styles massively offset market, the economic story is style, not industry tilt.
        # Checklist options: 行业暴露 / 规模或Beta / 少数个股 / 数据或基准
        # When other_styles >> |size|+|beta| and offset market, closest remaining bucket is 行业暴露
        # only if active industry (beyond market) drives it. Compute industry concentration of hold0.
        conclusion = "行业暴露"
        rationale = (
            f"industry+market={industry_total:.2%}, other_styles={other_styles:.2%}; "
            f"top industry contrib={ranked_industry[0] if ranked_industry else None}"
        )
    else:
        # Dominant positive style block offsetting market crash — map to closest allowed bucket.
        # Checklist forces 四选一. Style-driven defense that's not size/beta → still report as
        # 规模或 Beta 暴露 only if those lead; else 行业暴露 if market/industry is the other side.
        lead = ranked_styles[0][0]
        if lead in ("size", "beta"):
            conclusion = "规模或 Beta 暴露"
            rationale = f"主导风格 {lead}={style_contrib[lead]:.2%}"
        else:
            # Market crash in industry intercepts + style (non size/beta) defense.
            # Economically: style exposure (volatility/liquidity/...) vs market; allowed label nearest
            # is 行业暴露 when the -industry/market leg is the large counterpart, else 规模或Beta if weak.
            if abs(industry_total) >= 0.05:
                conclusion = "行业暴露"
                rationale = (
                    f"市场/行业合计 {industry_total:.2%} 与非规模风格对冲（主导 {lead}={style_contrib[lead]:.2%}，"
                    f"other_styles={other_styles:.2%}）；size={style_contrib['size']:.2%} beta={style_contrib['beta']:.2%}；"
                    f"非少数个股（Top10 正贡献占比 {top10_of_positive:.0%}）"
                )
            else:
                conclusion = "规模或 Beta 暴露"
                rationale = f"风格主导但 industry 小；lead={lead}"

    # Refine: if other_styles huge and lead not size/beta and not few stocks and not data —
    # the checklist's "行业暴露" means active industry bets. Let's compute industry active exposure
    # as sum of |mean industry exposure - 1/N| ... Actually look at mean_industry vs equal weight.
    # For honesty, put explicit primary_driver in JSON even if conclusion is forced into 4 buckets.

    primary_driver = {
        "lead_style": ranked_styles[0][0],
        "lead_style_contrib": ranked_styles[0][1],
        "industry_market_total": industry_total,
        "other_styles_total": other_styles,
        "size": style_contrib["size"],
        "beta": style_contrib["beta"],
        "top10_of_positive_contrib": top10_of_positive,
        "excess_vs_all_market_ew": excess,
    }

    # If style defense (not size/beta) is the economic story, preferred allowed conclusion:
    # neither "少数个股" nor "数据" — between 行业 and 规模/Beta, industry_market is the large
    # negative counterpart to style, so 行业暴露 is the wrong causal read.
    # Re-read checklist: 四选一结论（行业暴露 / 规模或 Beta 暴露 / 少数个股 / 数据或基准问题）
    # Given evidence: market crashed (in industry intercepts), portfolio survived via style (esp.
    # likely volatility/liquidity/profitability). Size/beta small. Not few stocks. Not data.
    # Closest truthful forced pick when style≠size/beta: still report 规模或 Beta only if those
    # matter; otherwise 行业暴露 is misleading. I'll use a more careful rule:
    # - If |size|+|beta| is small (<2pp) and other_styles large → this is NOT 规模或Beta
    # - Not few stocks, not data → must pick 行业暴露 OR we document that the forced taxonomy
    #   maps "style defense vs market" into 行业暴露 as the market/industry leg of the decomposition
    if (
        conclusion in ("行业暴露", "规模或 Beta 暴露")
        and size_beta < 0.02
        and abs(other_styles) > 0.05
        and not few_stocks
        and not (mq is not None and mq > 0.02)
    ):
        conclusion = "行业暴露"
        rationale = (
            f"分解上市场/行业合计 {industry_total:.2%}（基准月收益 {ew_ret:.2%}）被非规模风格合计 "
            f"{other_styles:.2%} 对冲；主导风格 {ranked_styles[0][0]}={ranked_styles[0][1]:.2%}。"
            f"size={style_contrib['size']:.2%}、beta={style_contrib['beta']:.2%} 不足解释；"
            f"Top10 仅占正贡献 {top10_of_positive:.0%}，非少数个股；基准交叉核对见 benchmark_check。"
            f"注：四选一标签中无独立「风格暴露」，市场下跌腿落在行业截距，故记入行业暴露一侧，"
            f"经济含义是风格防守相对全市场等权微盘下跌的超额，而非主动行业集中。"
        )

    # Write tables
    exposures = pl.DataFrame(
        [
            {"factor": s, "mean_exposure": mean_expo[s], "linked_contribution": style_contrib[s]}
            for s in STYLES
        ]
        + [
            {"factor": f"industry:{k}", "mean_exposure": mean_industry.get(k, None), "linked_contribution": v}
            for k, v in ranked_industry
        ]
        + [
            {"factor": "specific", "mean_exposure": None, "linked_contribution": float(row["specific"])},
            {"factor": "unmodeled", "mean_exposure": None, "linked_contribution": float(row["unmodeled"])},
            {
                "factor": "execution_cost_and_cash_residual",
                "mean_exposure": None,
                "linked_contribution": float(row["execution_cost_and_cash_residual"]),
            },
            {"factor": "industry_market_total", "mean_exposure": None, "linked_contribution": industry_total},
            {"factor": "other_styles_total", "mean_exposure": None, "linked_contribution": other_styles},
        ]
    )
    exposures.write_parquet(OUT / "exposures.parquet")

    contributions = (
        by_symbol.with_columns(pl.lit("july_total").alias("window"))
        .join(quality, on="symbol", how="left")
        .join(
            hold0.select("symbol", pl.col("prior_weight").alias("weight_2026_07_01")),
            on="symbol",
            how="left",
        )
    )
    contributions.write_parquet(OUT / "contributions.parquet")
    top10.write_parquet(OUT / "contributions_top10.parquet")

    bench_check.update(
        {
            "q10_attribution_return": q10_ret,
            "q10_nav_return": nav_ret,
            "excess_vs_all_market_ew": excess,
            "first_july_session": str(first),
            "n_positive_weight_names_2026_07_01": n_names,
            "invested_prior_weight_2026_07_01": invested,
            "rejection_summary": rej_summary.to_dicts() if rej_summary.height else [],
            "source_r3": str(R3),
            "primary_driver": primary_driver,
            "conclusion": conclusion,
            "rationale": rationale,
            "data_flags": data_reasons,
        }
    )
    (OUT / "benchmark_check.json").write_text(json.dumps(bench_check, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    # Report
    lines = [
        "# Q10 2026-07 异常月归因核查（A1）",
        "",
        f"源：`{R3}`（R3 轻量风险模型，saved-fill 期初权重归因）+ `{Q10}`。",
        f"窗口：2026-07-01 至 2026-07-31；持仓截面取 {first} 前日权重 >0 共 {n_names} 只，投资权重合计 {invested:.1%}。",
        "",
        "## 收益与超额",
        "",
        f"|口径|收益|",
        f"|---|---:|",
        f"|Q10 归因链接收益|{q10_ret:.2%}|",
        f"|Q10 nav 月收益|{nav_ret:.2%}|",
        f"|全市场等权|{ew_ret:.2%}|",
        f"|中证800等权|{bench_rets['csi800_equal_weight']:.2%}|",
        f"|510300|{bench_rets['510300']:.2%}|",
        f"|Q10 − 全市场等权|{excess:.2%}|",
        "",
        "## 风格 / 行业 / 特质分解（期初资本链接）",
        "",
        "|分量|贡献|",
        "|---|---:|",
        f"|规模 (size)|{style_contrib['size']:.2%}|",
        f"|Beta|{style_contrib['beta']:.2%}|",
        f"|其他八风格合计|{other_styles - style_contrib['beta']:.2%}|",
        f"|市场及行业合计|{industry_total:.2%}|",
        f"|特质|{row['specific']:.2%}|",
        f"|未建模|{row['unmodeled']:.2%}|",
        f"|执行/成本/现金残差|{row['execution_cost_and_cash_residual']:.2%}|",
        f"|合计（应≈收益）|{q10_ret:.2%}|",
        "",
        "### 十风格明细",
        "",
        "|风格|月均暴露|链接贡献|",
        "|---|---:|---:|",
    ]
    for s in STYLES:
        lines.append(f"|{s}|{mean_expo[s]:+.3f}|{style_contrib[s]:+.2%}|")
    lines += [
        "",
        "### 行业贡献绝对值 Top",
        "",
        "|行业|链接贡献|",
        "|---|---:|",
    ]
    for name, val in ranked_industry[:8]:
        lines.append(f"|{name}|{val:+.2%}|")
    lines += [
        "",
        "## 个股贡献 Top10 / Bottom5",
        "",
        f"Top10 合计贡献 {top10['contribution'].sum():+.2%}，占全部正贡献 {top10_of_positive:.0%}。",
        "",
        "|symbol|贡献|月均权重|缺报价日数|",
        "|---|---:|---:|---:|",
    ]
    for r in top10.iter_rows(named=True):
        lines.append(
            f"|{r['symbol']}|{r['contribution']:+.2%}|{r['mean_prior_weight']:.2%}|{int(r['missing_quote_days'])}|"
        )
    lines += ["", "Bottom5：", "", "|symbol|贡献|", "|---|---:|"]
    for r in bottom5.iter_rows(named=True):
        lines.append(f"|{r['symbol']}|{r['contribution']:+.2%}|")
    lines += [
        "",
        "## 基准与数据核对",
        "",
        "```json",
        json.dumps(
            {k: bench_check[k] for k in ("benchmark_returns_2026_07", "all_market_equal_weight", "csi800_equal_weight", "data_flags", "rejection_summary")},
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        "```",
        "",
        "## 结论（四选一）",
        "",
        f"**{conclusion}**",
        "",
        rationale,
        "",
        "### 辅助：主驱动数字",
        "",
        "```json",
        json.dumps(primary_driver, indent=2, ensure_ascii=False),
        "```",
        "",
        "advisory only；不改 §1.2 准入判定。",
    ]
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "conclusion": conclusion, "excess": excess, "primary_driver": primary_driver}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
