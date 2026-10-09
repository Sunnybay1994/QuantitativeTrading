"""统一命令门面：``python -m quant <组> <命令>``。旧 ``-m quant.x.y`` 入口保持可用。"""

from __future__ import annotations

import argparse
import json
import runpy
import sys
from typing import Any

from quant.core.gpu import detect_device
from quant.core.paths import project_paths
from quant.core.settings import load_runtime_settings
from quant.llm.budget import month_spend_usd, remaining_budget_usd

# 组、命令 → 现有 __main__ 模块。未知参数原样转交。
_DELEGATE: dict[tuple[str, str], str] = {
    ("data", "refresh"): "quant.data.refresh",
    ("data", "realtime"): "quant.data.realtime",
    ("data", "market-snapshot"): "quant.data.market_snapshot",
    ("research", "factor-family-states"): "quant.research.factor_family_states",
    ("research", "market-mechanism"): "quant.research.market_mechanism",
    ("research", "value-family-holdings"): "quant.research.value_family_holdings",
    ("research", "net-payout-feasibility"): "quant.research.net_payout_feasibility",
    ("research", "statement-event-family"): "quant.research.statement_event_family",
    ("research", "turnover-reference-family"): "quant.research.turnover_reference_family",
    ("research", "turnover-reference-verify"): "quant.research.turnover_reference_verify",
    ("research", "suspension-execution-audit"): "quant.research.suspension_execution_audit",
    ("data", "stock-execution-open"): "quant.data.publish_stock_open_inputs",
    ("data", "monthly-execution-open"): "quant.research.monthly_open_activation",
    ("research", "monthly-execution-open-verify"): "quant.research.monthly_open_verify",
    ("research", "industry-information-coverage"): "quant.research.industry_information_coverage",
    ("research", "industry-information-verify"): "quant.research.industry_information_verify",
    ("research", "joint-account"): "quant.research.joint_account",
    ("research", "joint-integer"): "quant.research.joint_integer",
    ("research", "personal-top5"): "quant.research.personal_top5",
    ("research", "admitted-model-pair"): "quant.research.admitted_model_pair",
    ("research", "residual-momentum"): "quant.research.residual_momentum_research",
    ("research", "pead-event-inputs"): "quant.research.pead_event_inputs",
    ("research", "pead-event-market-inputs"): "quant.research.pead_event_market_inputs",
    ("research", "pead-account"): "quant.research.pead_account",
    ("research", "benchmark-repair"): "quant.research.benchmark_corporate_repair",
    ("research", "benchmark-repair-evaluate"): "quant.research.benchmark_repair_evaluation",
    ("research", "etf-measurement"): "quant.research.etf_measurement",
    ("research", "etf-history-extension"): "quant.research.etf_history_extension",
    ("research", "calendar-allocation"): "quant.research.calendar_allocation",
    ("research", "cross-asset-long-cycle"): "quant.research.cross_asset_long_cycle",
    ("research", "etf-delayed-replay"): "quant.research.etf_delayed_replay",
    ("research", "etf-envelope-report"): "quant.research.etf_envelope_report",
    ("data", "latency"): "quant.data.market_latency",
    ("research", "intraday-afternoon"): "quant.research.intraday_afternoon",
    ("research", "minutes"): "quant.research.minute_pipeline",
    ("research", "mechanisms"): "quant.research.independent_mechanisms",
    ("research", "allocation-attribution"): "quant.research.etf_allocation_attribution",
    ("research", "market-indicators"): "quant.research.market_indicators_run",
    ("research", "mechanism-detail"): "quant.research.mechanism_followthrough",
    ("research", "etf-manual-init"): "quant.execution.etf_manual_bootstrap",
    ("research", "etf-execution-stress"): "quant.research.etf_execution_stress",
    ("data", "minutes"): "quant.data.recent_minutes",
    ("data", "minute-history"): "quant.data.minute_history",
    ("data", "minute-factors"): "quant.data.refresh_minute_factors",
    ("data", "baostock-history"): "quant.data.baostock_history",
    ("factors", "compute"): "quant.factors.compute",
    ("research", "daily"): "quant.research.scheduled_observation",
    ("research", "nightly"): "quant.research.nightly",
    ("research", "feedback"): "quant.research.research_feedback",
    ("research", "reversal-readiness"): "quant.research.pressure_reversal_readiness",
    ("research", "predictive-inputs"): "quant.research.predictive_priority_inputs",
    ("research", "batch-diagnosis"): "quant.research.batch_failure_diagnostics",
    ("research", "mining"): "quant.research.continuous_mining",
    ("research", "recovery-audit"): "quant.research.mining_recovery_audit",
    ("research", "cycle"): "quant.research.run_research_cycle",
    ("research", "gp"): "quant.research.run_genetic_factor_search",
    ("paper", "q10"): "quant.execution.q10_paper",
    ("paper", "orders"): "quant.execution.manual_orders",
    ("paper", "manual"): "quant.execution.manual_session_cli",
    ("paper", "b16-forward"): "quant.execution.b16_forward_service",
    ("report", "leaderboard"): "quant.reporting.leaderboard",
    ("report", "review"): "quant.reporting.strategy_review",
    ("report", "periods"): "quant.reporting.registered_periods",
    ("report", "dashboard"): "quant.reporting.research_dashboard",
    ("report", "q10-rolling"): "quant.reporting.q10_rolling_reassess",
    ("report", "q10-forward-demo"): "quant.reporting.q10_forward_rules_demo",
}


def _delegate(module: str, argv: list[str]) -> int:
    sys.argv = [module, *argv]
    try:
        runpy.run_module(module, run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        return 0 if code is None else int(code)
    return 0


def _status() -> dict[str, Any]:
    from pathlib import Path

    root = project_paths()
    runtime = load_runtime_settings()
    gpu = detect_device()
    daily = sorted((root.artifacts / "daily" / "scheduler").glob("*.log")) if (root.artifacts / "daily" / "scheduler").exists() else []
    mining = root.artifacts / "research" / "continuous" / "status.json"
    return {
        "root": str(root.root),
        "device": gpu.to_dict(),
        "llm_month_spend_usd": month_spend_usd(),
        "llm_remaining_usd": remaining_budget_usd(runtime.llm_monthly_budget_usd),
        "latest_scheduler_log": None if not daily else str(daily[-1]),
        "mining_status": json.loads(mining.read_text(encoding="utf-8")) if mining.exists() else None,
        "notify_config": str(Path(runtime.notify_config)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="quant",
        description="个人量化投研与交易系统",
    )
    sub = parser.add_subparsers(dest="group")

    gpu = sub.add_parser("gpu-check", help="探测 NVIDIA / LightGBM OpenCL")
    gpu.add_argument("--refresh", action="store_true")

    sub.add_parser("status", help="调度、预算、最近日更的只读快照")

    notify = sub.add_parser("notify", help="人工通道发消息")
    notify.add_argument("action", choices=["test", "send"], nargs="?", default="test")
    notify.add_argument("--title", default="QuantitativeTrading")
    notify.add_argument("--body", default="notify test")
    notify.add_argument("--dry-run", action="store_true")
    notify.add_argument("--channel", action="append", dest="channels")

    intel = sub.add_parser("intel", help="扫描论文/开源并写入因子队列")
    intel.add_argument("action", choices=["scan"], nargs="?", default="scan")
    intel.add_argument("--config")
    intel.add_argument("--no-extract", action="store_true")

    data = sub.add_parser("data", help="数据刷新")
    data.add_argument("command", choices=["refresh", "realtime", "market-snapshot", "minutes", "minute-history", "minute-factors", "baostock-history", "latency", "stock-execution-open", "monthly-execution-open"])
    factors = sub.add_parser("factors", help="因子计算")
    factors.add_argument("command", choices=["compute"])
    research = sub.add_parser("research", help="投研流水线")
    research.add_argument("command", choices=[
        "daily", "nightly", "mining", "cycle", "gp", "feedback", "recovery-audit", "personal-top5", "admitted-model-pair", "residual-momentum", "pead-event-inputs", "pead-event-market-inputs", "pead-account", "benchmark-repair", "benchmark-repair-evaluate",
        "reversal-readiness", "batch-diagnosis", "predictive-inputs", "intraday-afternoon", "minutes", "mechanisms", "statement-event-family", "suspension-execution-audit", "turnover-reference-family", "turnover-reference-verify", "monthly-execution-open-verify", "industry-information-coverage", "industry-information-verify",
        "allocation-attribution", "mechanism-detail", "etf-manual-init", "etf-execution-stress", "market-indicators", "factor-family-states", "market-mechanism", "value-family-holdings", "net-payout-feasibility", "joint-account", "joint-integer", "etf-measurement", "etf-history-extension", "calendar-allocation", "cross-asset-long-cycle", "etf-delayed-replay", "etf-envelope-report",
    ])
    paper = sub.add_parser("paper", help="模拟盘与人工订单")
    paper.add_argument("command", choices=["q10", "orders", "manual", "b16-forward"])
    report = sub.add_parser("report", help="机器报告")
    report.add_argument("command", choices=["leaderboard", "dashboard", "review", "periods"])

    args, rest = parser.parse_known_args(argv)
    if args.group is None:
        parser.print_help()
        return 0
    if args.group == "gpu-check":
        from quant.core.gpu import main as gpu_main
        return gpu_main(["--refresh"] if args.refresh else [])
    if args.group == "status":
        print(json.dumps(_status(), ensure_ascii=False, indent=2, default=str))
        return 0
    if args.group == "notify":
        from quant.notify import main as notify_main
        extra: list[str] = [args.action, "--title", args.title, "--body", args.body]
        if args.dry_run:
            extra.append("--dry-run")
        for channel in args.channels or []:
            extra.extend(["--channel", channel])
        return notify_main(extra)
    if args.group == "intel":
        from quant.intel.pipeline import main as intel_main
        extra = []
        if args.config:
            extra.extend(["--config", args.config])
        if args.no_extract:
            extra.append("--no-extract")
        return intel_main(extra)
    key = (args.group, args.command)
    module = _DELEGATE.get(key)
    if module is None:
        parser.error(f"未知命令: {args.group} {getattr(args, 'command', '')}")
    return _delegate(module, rest)


if __name__ == "__main__":
    raise SystemExit(main())
