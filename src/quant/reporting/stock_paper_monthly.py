"""B32 observed monthly returns beside frozen historical monthly distributions."""

import argparse
import json
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.stock_paper_inputs import read_stock_paper_calendar
from quant.reporting.paper_monthly import compare_monthly

ACCOUNTS = ("b32_cv20_buffer75", "b32_paired_three_factor")
BACKTESTS = (
    ("9f181d7b2d92a6ef59608076b663e050812025ee4fcd2f392dcaefa6c052ef00", "top50"),
    ("7ab730dd8390a94337d9b5b4f9f304f5cb7a81b50eb0b718b80bbcf1bf0da054", "three_factor"),
)


def historical_months(nav: pl.DataFrame, calendar: pl.DataFrame) -> pl.DataFrame:
    """Reset initial NAV at each frozen fold and omit incomplete closing months."""
    last_sessions = dict(
        calendar.filter("is_open")
        .with_columns(pl.col("date").dt.strftime("%Y-%m").alias("month"))
        .group_by("month")
        .agg(pl.col("date").max())
        .iter_rows()
    )
    rows: list[dict[str, Any]] = []
    for (fold,), frame in nav.partition_by("fold", as_dict=True).items():
        frame = frame.sort("date").with_columns(pl.col("date").dt.strftime("%Y-%m").alias("month"))
        base = 1.0
        for (month,), group in frame.partition_by(
            "month", as_dict=True, maintain_order=True
        ).items():
            end = group["date"][-1]
            value = group["unit_nav"][-1]
            if end == last_sessions.get(month):
                rows.append(
                    {"fold": fold, "month": month, "end_date": end, "return": value / base - 1}
                )
            base = value
    if not rows:
        raise ValueError("No complete historical months")
    return pl.DataFrame(rows).sort("month")


def run(
    *, ledger_root: Path, data_root: Path, artifact_root: Path, output: Path | None = None
) -> dict[str, Any]:
    snapshots = []
    for account in ACCOUNTS:
        paths = sorted((ledger_root / account).glob("????-??-??/state.json"))
        if not paths:
            raise ValueError("Initialize both B32 accounts before monthly reporting")
        snapshots.append(paths[-1].parent)
    if snapshots[0].name != snapshots[1].name:
        raise ValueError("Complete both account dates before monthly reporting")
    output = output or ledger_root / "monthly" / snapshots[0].name
    if (output / "summary.json").is_file():
        return {"action": "no-op", "output": str(output)}
    calendar = read_stock_paper_calendar(data_root)
    histories: list[pl.DataFrame] = []
    summaries: list[dict[str, Any]] = []
    for account, (run_id, comparison) in zip(ACCOUNTS, BACKTESTS):
        source = artifact_root / "research/runs" / run_id / "nav.parquet"
        nav = pl.read_parquet(source).filter(
            (pl.col("comparison") == comparison) & (pl.col("cost_multiplier") == 1.0)
        )
        months = historical_months(nav, calendar).with_columns(pl.lit(account).alias("account"))
        histories.append(months)
        summaries.append(
            {
                "account": account,
                "frozen_source": str(source),
                "comparison": comparison,
                "cost_multiplier": 1.0,
                "complete_historical_months": months.height,
                "historical_monthly_mean": months["return"].mean(),
                "historical_monthly_median": months["return"].median(),
                "historical_monthly_min": months["return"].min(),
                "historical_monthly_max": months["return"].max(),
            }
        )
    paper = [pl.read_csv(snapshot / "nav.csv") for snapshot in snapshots]
    if paper[0].height != paper[1].height:
        raise ValueError("Forward accounts have unequal observed NAV counts")
    observed = pl.DataFrame(
        schema={
            "month": pl.String,
            "paper_return": pl.Float64,
            "benchmark_return": pl.Float64,
            "return_difference_pp": pl.Float64,
        }
    )
    if paper[0].height:
        observed, _ = compare_monthly(paper[0], paper[1])
    output.mkdir(parents=True, exist_ok=True)
    observed.write_csv(output / "forward_monthly.csv")
    pl.concat(histories).write_csv(output / "frozen_backtest_monthly.csv")
    summary = {
        "as_of": snapshots[0].name,
        "observed_nav_sessions": paper[0].height,
        "observed_months": observed.height,
        "conclusion": "RESEARCH_ONLY",
        "backtests": summaries,
    }
    lines = [
        "# B32 月度前向观察与冻结回测期望",
        "",
        f"截至 {snapshots[0].name}，实际净值 {paper[0].height} 日；结论保持 RESEARCH_ONLY。",
        "",
        "|账户|历史完整月份|月收益均值|中位数|最差月|最好月|",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            f"|{row['account']}|{row['complete_historical_months']}|{row['historical_monthly_mean']:.2%}|"
            f"{row['historical_monthly_median']:.2%}|{row['historical_monthly_min']:.2%}|{row['historical_monthly_max']:.2%}|"
        )
    lines += ["", "冻结回测采用各折初始净值 1、1× 成本；末尾未完整的月份剔除，保留首次买入成本。"]
    if observed.is_empty():
        lines += ["", "尚无前向净值，月度实际收益留空；首个计划成交日为 2026-09-10。"]
    else:
        lines += [
            "",
            "|前向月份|CV20缓冲|三因子|差异pp|CV20距历史月均pp|三因子距历史月均pp|边界|",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
        for row in observed.iter_rows(named=True):
            lines.append(
                f"|{row['month']}|{row['paper_return']:.2%}|{row['benchmark_return']:.2%}|"
                f"{row['return_difference_pp']:+.2f}|{100 * (row['paper_return'] - summaries[0]['historical_monthly_mean']):+.2f}|"
                f"{100 * (row['benchmark_return'] - summaries[1]['historical_monthly_mean']):+.2f}|{row['coverage_note']}|"
            )
    lines += [
        "",
        "历史月度分布仅供比较，部分前向月份不与完整历史月份作通过/失败判定。",
        "",
        *[
            f"来源：`{row['frozen_source']}`，comparison={row['comparison']}，cost_multiplier=1。"
            for row in summaries
        ],
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {**summary, "output": str(output)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger-root", type=Path, default=Path("artifacts/paper/b32_stock_observation")
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                ledger_root=args.ledger_root,
                data_root=args.data_root,
                artifact_root=args.artifact_root,
                output=args.output,
            )
        )
    )


if __name__ == "__main__":
    main()
