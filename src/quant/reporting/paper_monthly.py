"""Compare an existing PAPER NAV snapshot with one selected backtest NAV series."""

import argparse
import json
import math
from pathlib import Path
from typing import Any

import polars as pl


def read_nav(path: Path, filters: list[str]) -> pl.DataFrame:
    """Read CSV/Parquet artifacts and require one unambiguous account series."""
    frame = pl.read_parquet(path) if path.suffix == ".parquet" else pl.read_csv(path)
    for item in filters:
        key, separator, value = item.partition("=")
        if not separator or key not in frame.columns:
            raise ValueError(f"Invalid filter: {item}")
        frame = frame.filter(pl.col(key) == pl.lit(value).cast(frame.schema[key]))
    for key in ("strategy", "fold", "period", "comparison", "cost_multiplier"):
        if key in frame.columns and frame[key].n_unique() > 1:
            raise ValueError(f"Select one {key} with a filter before comparing NAV")
    return _nav(frame)


def _nav(frame: pl.DataFrame) -> pl.DataFrame:
    if not {"date", "unit_nav"}.issubset(frame.columns):
        raise ValueError("NAV requires date and unit_nav columns")
    frame = frame.select(pl.col("date").cast(pl.String).str.to_date("%Y-%m-%d"),
                         pl.col("unit_nav").cast(pl.Float64)).sort("date")
    if frame.is_empty():
        raise ValueError("No NAV observations yet; no monthly returns can be reported")
    if frame.null_count().row(0) != (0, 0):
        raise ValueError("NAV contains null dates or values")
    if frame["date"].n_unique() != frame.height:
        raise ValueError("NAV dates must be unique; select a single backtest series")
    if any(not math.isfinite(x) or x <= 0 for x in frame["unit_nav"]):
        raise ValueError("NAV values must be finite and positive")
    return frame


def compare_monthly(
    paper: pl.DataFrame, benchmark: pl.DataFrame, *,
    paper_initial_nav: float = 1.0, benchmark_initial_nav: float = 1.0,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Use shared close dates; initial NAV is capital BEFORE first-session costs.

    First shared date must be the inception of both series, or both must have
    the same preceding close. This avoids silently rebasing away entry costs or
    comparing different initial return intervals. Slice a backtest fold explicitly.
    """
    for value in (paper_initial_nav, benchmark_initial_nav):
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Initial NAV must be finite and positive")
    paper, benchmark = _nav(paper), _nav(benchmark)
    p = dict(paper.iter_rows())
    b = dict(benchmark.iter_rows())
    dates = sorted(p.keys() & b.keys())
    if not dates:
        raise ValueError("PAPER and benchmark have no common dates")
    first = dates[0]
    p_before = max((d for d in p if d < first), default=None)
    b_before = max((d for d in b if d < first), default=None)
    if p_before != b_before:
        raise ValueError("Initial return intervals differ; supply series with matching inception")
    p_base = paper_initial_nav if p_before is None else p[p_before]
    b_base = benchmark_initial_nav if b_before is None else b[b_before]
    daily = pl.DataFrame({"date": dates, "paper_nav": [p[d] for d in dates],
        "benchmark_nav": [b[d] for d in dates],
        "paper_comparison_nav": [p[d] / p_base for d in dates],
        "benchmark_comparison_nav": [b[d] / b_base for d in dates]})
    daily = daily.with_columns(
        (pl.col("paper_comparison_nav") - pl.col("benchmark_comparison_nav"))
        .alias("nav_difference"))
    months = sorted({d.strftime("%Y-%m") for d in dates})
    month_numbers = [d.year * 12 + d.month for d in dates]
    if any(right - left > 1 for left, right in zip(month_numbers, month_numbers[1:])):
        raise ValueError("An entire month has no common dates; monthly returns cannot be aligned")
    rows: list[dict[str, Any]] = []
    previous = p_before
    for month in months:
        observed = [d for d in dates if d.strftime("%Y-%m") == month]
        end = observed[-1]
        union = {d for d in p.keys() | b.keys() if d.strftime("%Y-%m") == month}
        missing = len(union - set(observed))
        reasons = []
        if month == months[0]:
            reasons.append("opening_boundary")
        if month == months[-1]:
            reasons.append("closing_boundary")
        if missing:
            reasons.append("unmatched_dates")
        if previous is not None and any(
            previous < d < observed[0] for d in p.keys() | b.keys()
        ):
            reasons.append("unmatched_period_boundary")
        p_return, b_return = p[end] / p_base - 1, b[end] / b_base - 1
        rows.append({"month": month, "start_date": observed[0], "end_date": end,
            "base_date": previous, "common_dates": len(observed),
            "unmatched_dates": missing, "partial_month": bool(reasons),
            "coverage_note": ";".join(reasons) or "interior_observed_month",
            "paper_base_nav": p_base, "benchmark_base_nav": b_base,
            "paper_end_nav": p[end], "benchmark_end_nav": b[end],
            "paper_return": p_return, "benchmark_return": b_return,
            "return_difference_pp": 100 * (p_return - b_return)})
        previous, p_base, b_base = end, p[end], b[end]
    return pl.DataFrame(rows, schema_overrides={"base_date": pl.Date}), daily


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True, help="Existing snapshot nav.csv")
    parser.add_argument("--benchmark", type=Path, required=True, help="NAV CSV or Parquet")
    parser.add_argument("--ledger-filter", action="append", default=[])
    parser.add_argument("--benchmark-filter", action="append", default=[])
    parser.add_argument("--paper-initial-nav", type=float, default=1.0)
    parser.add_argument("--benchmark-initial-nav", type=float, default=1.0)
    parser.add_argument("--mode", choices=("paper", "rehearsal"), required=True)
    parser.add_argument("--benchmark-note", default="请核对两源策略、初始资本及成本口径。")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if "rehearsal" in args.ledger.parts and args.mode != "rehearsal":
        parser.error("A rehearsal ledger must be labelled --mode rehearsal")
    monthly, daily = compare_monthly(
        read_nav(args.ledger, args.ledger_filter),
        read_nav(args.benchmark, args.benchmark_filter),
        paper_initial_nav=args.paper_initial_nav,
        benchmark_initial_nav=args.benchmark_initial_nav,
    )
    args.output.mkdir(parents=True, exist_ok=False)
    monthly.write_csv(args.output / "monthly.csv")
    daily.write_csv(args.output / "common_nav.csv")
    title = "历史演练（非前向记录）" if args.mode == "rehearsal" else "PAPER 前向记录"
    lines = [f"# {title}：月度净值与回测对照", "",
        f"账本：`{args.ledger.resolve()}`", f"回测：`{args.benchmark.resolve()}`",
        f"账本筛选：`{args.ledger_filter}`；回测筛选：`{args.benchmark_filter}`。", "",
        f"对照口径：{args.benchmark_note}",
        f"初始净值：PAPER={args.paper_initial_nav}，回测={args.benchmark_initial_nav}。", "",
        "收益 = 本期最后共同日净值 / 上期最后共同日净值 − 1；首期用成交前初始净值，包含首日成本。",
        "仅使用实际共同日期，不填充行情。首尾月保守标为部分月；中间月份完整性仅按两源观测日期并集判断。",
        "共同日期净值文件同时保留原净值和按比较起点归一的净值。差异单位为百分点。", "",
        "| 月份 | 实际区间 | 共同日 | 未配对日 | 部分月 | PAPER | 回测 | 差异 pp |",
        "|---|---|---:|---:|---|---:|---:|---:|"]
    for row in monthly.iter_rows(named=True):
        lines.append(f"| {row['month']} | {row['start_date']} 至 {row['end_date']} | "
            f"{row['common_dates']} | {row['unmatched_dates']} | {row['coverage_note']} | "
            f"{row['paper_return']:.4%} | {row['benchmark_return']:.4%} | "
            f"{row['return_difference_pp']:+.4f} |")
    lines += ["", "下一步：累计实际前向账本后，使用同期同策略、同成本回测 NAV 重跑本命令。"]
    (args.output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "mode": args.mode,
                      "common_dates": daily.height, "months": monthly.height}))


if __name__ == "__main__":
    main()
