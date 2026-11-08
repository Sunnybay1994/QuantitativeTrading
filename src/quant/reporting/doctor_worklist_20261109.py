"""Current worklist receipts; future natural observations remain unverified."""

import datetime as dt
import json

import polars as pl

from quant.reporting.doctor_worklist import _registry

REQUIRED = {
    "account_portfolio_v1": ("fixed_40_30_30", "inverse_volatility60"),
    "account_portfolio_top15_v1": ("fixed_40_30_30", "inverse_volatility60"),
    "top15_pessimistic_fill_v1": ("pessimistic_1pct",),
    "top15_turnover_budget_v1": ("turnover7_1pct",),
}
RUNS = {
    "account_portfolio_a1_q10_20261108_01",
    "account_portfolio_a1_top15_20261108_01",
    "top15_pessimistic_fill_20261108_01",
    "top15_turnover_budget_20261108_01",
}


def _read(root, path):
    source = root / path
    return json.loads(source.read_text(encoding="utf-8"))


def collect(root, clock, *, history=None):
    if clock.tzinfo is None:
        raise ValueError("Worklist observation requires timezone-aware clock")
    try:
        registry = _registry(
            root,
            clock,
            required=REQUIRED,
            optional={},
            run_names=RUNS,
            since=dt.datetime(2026, 11, 8, tzinfo=clock.tzinfo),
        )
    except (OSError, ValueError, KeyError, TypeError, pl.exceptions.PolarsError) as exc:
        registry = dict(required_results=6, verified_results=[], issues=[str(exc)])
    a1 = []
    for name in sorted(r for r in RUNS if r.startswith("account_")):
        try:
            base = "artifacts/research/" + name + "/"
            summary = _read(root, base + "summary.json")
            legacy = _read(root, base + "legacy_jump_comparison.json")["rows"]
            costs = {r["cost_multiplier"] for r in legacy}
            verified = (
                costs == {0.5, 1.0, 2.0}
                and len(legacy) == 3
                and all(
                    r["date"] == "2021-10-22"
                    and r["prior_nav_and_flows_identical"] is True
                    and r["legacy_guard_rejected"] is True
                    and r["new_guard"]["passed"] is True
                    for r in legacy
                )
            )
            a1.append(
                dict(
                    run=name,
                    status=summary["status"],
                    completed_ledgers=len(summary["completed"]),
                    legacy_counterexample_verified=verified,
                )
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            a1.append(dict(run=name, issue=str(exc)))
    a2 = {"formal_status": "not_observed", "rehearsal_status": "not_observed"}
    base = "artifacts/paper/account_30w_top15_v1/"
    try:
        validation = _read(root, base + "rehearsal/20261108_real_inputs_01/validation.json")
        a2.update(
            rehearsal_status=validation["status"],
            rehearsal=validation["actual_summary"],
            protected_sha_unchanged=validation["protected_sha_unchanged"],
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        a2["rehearsal_issue"] = str(exc)
    if (root / base / "latest_summary.json").is_file():
        try:
            latest = _read(root, base + "latest_summary.json")
            a2.update(
                formal_status="observed"
                if latest.get("rehearsal") is False and latest.get("auto_trade") is False
                else "invalid_formal_receipt",
                formal=latest,
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            a2["formal_issue"] = str(exc)
    research = {}
    for name, path in {
        "R5": "artifacts/research/r5_preliminary_20261108_03/summary.json",
        "R6": "artifacts/research/event_family_r6_20261108_02/summary.json",
    }.items():
        try:
            research[name] = dict(path=path, receipt=_read(root, path))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            research[name] = dict(path=path, issue=str(exc))
    from quant.reporting.worklist_dated_observations import evaluate
    return dict(
        enabled=True,
        worklist_date="2026-11-09",
        observed_at=clock.isoformat(),
        midterm_date="2026-11-20",
        final_date="2026-12-01",
        midterm_date_reached=clock.date() >= dt.date(2026, 11, 20),
        final_date_reached=clock.date() >= dt.date(2026, 12, 1),
        registry=registry,
        a1=a1,
        a2=a2,
        research=research,
        acceptance_verified=False,
        dated_observations=evaluate(root,clock,history),
        scope="Current receipts only. K2 natural month-end orders, A2 December fills/daily runs, "
        "D2 five real trading days, R5/R6 batteries and the second real monthly report remain to verify.",
    )


def markdown(result):
    registry = result["registry"]
    lines = [
        "",
        "## 工作清单 2026-11-09：实际产物",
        "",
        f"观测时刻：{result['observed_at']}；中期 {result['midterm_date']}；终验 {result['final_date']}。",
        f"- 本轮指定六项注册结果已核对 {len(registry['verified_results'])} 项；"
        f"缺少 {registry.get('missing_required', [])}。",
        "|实验|版本|正式结论|",
        "|---|---|---|",
    ]
    for row in registry["verified_results"]:
        lines.append(f"|{row['experiment_id']}|{row['variant']}|{row['conclusion']}|")
    for row in result["a1"]:
        lines.append(
            f"- A1 {row['run']}：{row.get('status', row.get('issue'))}；"
            f"账本 {row.get('completed_ledgers')}；旧跳变反例核验 {row.get('legacy_counterexample_verified')}。"
        )
    a2 = result["a2"]
    lines.append(f"- A2 正式账户：{a2['formal_status']}；隔离预演：{a2['rehearsal_status']}。")
    if a2.get("rehearsal"):
        row = a2["rehearsal"]
        lines.append(
            f"- A2 预演数据截至 {row['as_of']}：股票 {row['stock_orders']} 笔、ETF {row['etf_orders']} 笔，"
            f"估算 {row['estimated_notional']:.2f} 元；正式账户 SHA 不变：{a2['protected_sha_unchanged']}。"
        )
    for name, row in result["research"].items():
        receipt = row.get("receipt", {})
        state = receipt.get('status') or ('统计验收未完成' if receipt.get('acceptance_complete') is False
            else row.get('issue','待核对'))
        lines.append(
            f"- {name}：{state}；机器回执 `{row['path']}`。"
        )
    lines.extend("- 待核对：" + issue for issue in registry["issues"])
    for name,row in result.get('dated_observations',{}).items():
        lines.append(f"- 自然运行 {name}（{row['target_date']}）：{row['status']}"
            +(f"；{row['issue']}" if row.get('issue') else '')+'。')
    lines.append("\n当前不宣告清单验收完成。" + result["scope"])
    return lines
