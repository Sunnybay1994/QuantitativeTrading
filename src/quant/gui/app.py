"""Streamlit view for the read-only Quant research workbench."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

from quant.gui.launcher import ARTIFACT_ROOT_ENV
from quant.gui.research_runs import (
    ResearchRunCatalog,
    ResearchRunComparisonDiagnosis,
    ResearchRunSummary,
    conclusion_counts,
    diagnose_research_run_comparison,
    discover_research_runs,
    load_comparison_nav_projection,
    load_nav_projection,
    verify_research_run,
    verify_research_run_comparison,
)


def main() -> None:
    """Render the read-only research cockpit."""
    st = importlib.import_module("streamlit")
    st.set_page_config(page_title="Quant 投研工作台", layout="wide")
    st.title("Quant 投研工作台")
    st.caption("G1 只读研究驾驶舱 · 无 PAPER/LIVE 权限 · 不运行或修改研究产物")

    artifact_root = Path(
        os.environ.get(ARTIFACT_ROOT_ENV, str(Path.cwd() / "artifacts"))
    ).absolute()
    catalog = discover_research_runs(artifact_root)

    page = st.sidebar.radio("页面", ("运行总览", "运行详情", "运行比较"))
    st.sidebar.caption("所有内容来自固定 research/runs 目录；页面不接受任意路径。")
    if page == "运行详情":
        _render_detail(st, catalog)
    elif page == "运行比较":
        _render_comparison(st, catalog)
    else:
        _render_overview(st, catalog)


def _render_overview(st: Any, catalog: ResearchRunCatalog) -> None:
    counts = conclusion_counts(catalog.runs)
    latest = max((run.manifest.data_end for run in catalog.runs), default=None)
    columns = st.columns(6)
    columns[0].metric("可读运行", len(catalog.runs))
    columns[1].metric("RESEARCH_ONLY", counts["RESEARCH_ONLY"])
    columns[2].metric("REJECTED", counts["REJECTED"])
    columns[3].metric("PAPER_CANDIDATE", counts["PAPER_CANDIDATE"])
    columns[4].metric("异常条目", len(catalog.issues))
    columns[5].metric("最大 data_end", latest.isoformat() if latest is not None else "—")
    st.caption(
        "统计口径：仅计规范 JSON、完整 V1 合同与 run identity 自洽的清单；"
        "尚未自动验证输出完整性。"
    )
    _render_issues(st, catalog)

    all_conclusions = ("REJECTED", "RESEARCH_ONLY", "PAPER_CANDIDATE")
    all_strategies = tuple(sorted({run.manifest.strategy_name for run in catalog.runs}))
    selected_conclusions = st.sidebar.multiselect(
        "结论",
        all_conclusions,
        default=all_conclusions,
    )
    selected_strategies = st.sidebar.multiselect(
        "策略",
        all_strategies,
        default=all_strategies,
    )
    filtered = tuple(
        run
        for run in catalog.runs
        if run.manifest.conclusion in selected_conclusions
        and run.manifest.strategy_name in selected_strategies
    )
    st.subheader("研究运行")
    if not filtered:
        st.info("当前固定目录与筛选条件下没有可展示的自洽运行。")
        return
    st.dataframe(
        [_summary_row(run) for run in filtered],
        width="stretch",
        hide_index=True,
    )


def _render_detail(st: Any, catalog: ResearchRunCatalog) -> None:
    _render_issues(st, catalog)
    if not catalog.runs:
        st.info("没有可进入详情页的自洽运行。先处理总览中显示的路径或清单问题。")
        return
    by_id = {run.manifest.run_id: run for run in catalog.runs}
    selected_id = st.selectbox(
        "运行 ID",
        tuple(by_id),
        format_func=lambda run_id: _run_label(by_id[run_id]),
    )
    run = by_id[selected_id]
    manifest = run.manifest

    st.subheader(manifest.hypothesis_id)
    st.write(manifest.hypothesis)
    st.code(manifest.run_id, language=None)
    columns = st.columns(4)
    columns[0].metric("研究结论", manifest.conclusion)
    columns[1].metric("策略", f"{manifest.strategy_name} {manifest.strategy_version}")
    columns[2].metric("数据窗口", f"{manifest.data_start} → {manifest.data_end}")
    columns[3].metric("Universe", manifest.universe_name)
    st.warning(
        "清单自洽不等于输出完整、formal 或 PAPER 准入；本页不会修改结论或发起交易。"
    )

    st.markdown("#### 时间语义与实验设计")
    st.table(
        [
            {
                "signal": manifest.signal_timing,
                "execution": manifest.execution_timing,
                "valuation": manifest.valuation_timing,
                "universe_frozen_as_of": manifest.universe_frozen_as_of.isoformat(),
                "cost_multipliers": ", ".join(map(str, manifest.cost_multipliers)),
                "selection_metric": manifest.selection_metric,
            }
        ]
    )
    st.markdown("#### Walk-forward folds")
    st.dataframe(
        [
            {
                "fold": fold.fold,
                "train": f"{fold.train_start} → {fold.train_end}",
                "validation": f"{fold.validation_start} → {fold.validation_end}",
                "test": f"{fold.test_start} → {fold.test_end}",
            }
            for fold in manifest.folds
        ],
        width="stretch",
        hide_index=True,
    )
    st.markdown("#### 聚合指标")
    st.dataframe(
        [{"metric": name, "value": value} for name, value in manifest.aggregate_metrics],
        width="stretch",
        hide_index=True,
    )
    st.markdown("#### Caveats")
    if manifest.caveats:
        for caveat in manifest.caveats:
            st.markdown(f"- {caveat}")
    else:
        st.info("清单未列 caveat。")

    with st.expander("输入与输出证据", expanded=False):
        st.markdown("**Inputs**")
        st.dataframe(
            [
                {
                    "name": item.name,
                    "rows": item.rows,
                    "min_date": item.min_date,
                    "max_date": item.max_date,
                    "content_sha256": item.content_sha256,
                }
                for item in manifest.inputs
            ],
            width="stretch",
            hide_index=True,
        )
        st.markdown("**Outputs**")
        st.dataframe(
            [
                {
                    "relative_path": item.relative_path,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                }
                for item in manifest.outputs
            ],
            width="stretch",
            hide_index=True,
        )

    st.markdown("#### 输出完整性与 NAV")
    st.caption("显式校验是有界只读动作；G0 同步校验总量上限为 128 MiB。")
    if not st.button("校验不可变输出", type="primary"):
        st.info("输出尚未验证，NAV 保持锁定。")
        return
    with st.spinner("正在核对精确文件树、字节数与 SHA-256…"):
        integrity = verify_research_run(run)
    if integrity.status != "VERIFIED":
        issue = integrity.issue
        if issue is None:
            st.error("BLOCKED · 未提供可解释的完整性证据。")
        else:
            st.error(f"BLOCKED · {issue.code} · {issue.detail}")
        return
    st.success(f"输出完整性已验证：{integrity.checked_files} 个清单输出。")
    nav = load_nav_projection(integrity)
    if nav.status != "AVAILABLE" or nav.frame is None:
        issue = nav.issue
        if nav.status == "NOT_AVAILABLE":
            st.info(issue.detail if issue is not None else "清单未提供 NAV。")
        else:
            st.error(
                f"{issue.code} · {issue.detail}"
                if issue is not None
                else "NAV 投影被安全边界阻塞。"
            )
        return
    st.line_chart(nav.frame, x="date", y="unit_nav", color="series")
    st.dataframe(nav.frame.tail(100), width="stretch", hide_index=True)


def _render_comparison(st: Any, catalog: ResearchRunCatalog) -> None:
    _render_issues(st, catalog)
    st.subheader("运行比较")
    st.caption(
        "只允许 2–4 个同一数据、universe、时间、fold、成本、指标和输入口径的运行；"
        "比较不产生排名、差值、聚合指标或准入结论。"
    )
    if len(catalog.runs) < 2:
        st.info("至少需要两个自洽运行才能进入只读比较。")
        return

    by_id = {run.manifest.run_id: run for run in catalog.runs}
    selected_ids = st.multiselect(
        "选择 2–4 个运行",
        tuple(by_id),
        default=(),
        max_selections=4,
        format_func=lambda run_id: _run_label(by_id[run_id]),
    )
    if not 2 <= len(selected_ids) <= 4:
        st.info("请选择 2–4 个唯一运行；页面不会自动替研究员选择比较对象。")
        return

    selected = tuple(by_id[run_id] for run_id in selected_ids)
    st.warning(
        "清单自洽仍不足以比较。只有全部运行的身份、口径和输出完整性都闭合后，"
        "页面才会显示逐 run 证据与 NAV。"
    )
    if not st.button("校验输出并生成只读比较", type="primary"):
        st.info("尚未验证所选运行；比较证据和 NAV 保持锁定。")
        return

    diagnosis: ResearchRunComparisonDiagnosis | None = None
    with st.spinner("正在核对比较口径、精确输出树、字节数与 SHA-256…"):
        comparison = verify_research_run_comparison(selected)
        if (
            comparison.issue is not None
            and comparison.issue.code == "COMPARISON_CONTRACT_MISMATCH"
        ):
            diagnosis = diagnose_research_run_comparison(selected)
    if comparison.status != "VERIFIED" or comparison.issue is not None:
        issue = comparison.issue
        st.error(
            f"BLOCKED · {issue.code} · {issue.detail}"
            if issue is not None
            else "BLOCKED · 比较未提供完整、可解释的证据。"
        )
        if (
            issue is not None
            and issue.code == "COMPARISON_CONTRACT_MISMATCH"
            and diagnosis is not None
        ):
            _render_comparison_diagnosis(st, diagnosis)
        return

    st.success(f"{len(comparison.runs)} 个运行的比较口径与输出完整性已验证。")
    _render_comparison_evidence(st, comparison.runs)

    st.markdown("#### 已验证 1.0× NAV")
    st.caption(
        "仅拼接逐 run 已验证原始行并增加显示标签；不重采样、不归一化、不重算收益或风险指标。"
    )
    nav = load_comparison_nav_projection(comparison)
    if nav.status != "AVAILABLE" or nav.frame is None or nav.issue is not None:
        issue = nav.issue
        st.error(
            f"BLOCKED · {issue.code} · {issue.detail}"
            if issue is not None
            else "BLOCKED · 所选运行没有完整、同口径的 NAV 证据。"
        )
        return
    st.line_chart(nav.frame, x="date", y="unit_nav", color="comparison_series")
    st.dataframe(
        nav.frame.tail(200),
        width="stretch",
        hide_index=True,
    )


def _render_comparison_diagnosis(
    st: Any,
    diagnosis: ResearchRunComparisonDiagnosis,
) -> None:
    issue = diagnosis.issue
    if issue is None or issue.code != "COMPARISON_CONTRACT_MISMATCH":
        return

    rows: list[dict[str, object]] = []
    for field_relation in diagnosis.fields:
        if "DIFFERENT" not in field_relation.relations:
            continue
        row: dict[str, object] = {"field": field_relation.field}
        for order, (run, relation) in enumerate(
            zip(diagnosis.runs, field_relation.relations, strict=True),
            start=1,
        ):
            row[f"Run {order} · {run.manifest.run_id[:12]}"] = relation
        rows.append(row)
    if not rows:
        return

    st.markdown("#### 严格比较口径诊断")
    st.caption(
        "REFERENCE 仅表示用户本次选择顺序中的第一项，不代表基准、优胜或建议；"
        "关系只来自已发布 manifest，不能证明任何输出完整性。"
    )
    st.dataframe(rows, width="stretch", hide_index=True)


def _render_comparison_evidence(
    st: Any,
    runs: tuple[ResearchRunSummary, ...],
) -> None:
    reference = runs[0].manifest
    st.markdown("#### 已验证比较口径")
    st.table(
        [
            {
                "data_window": f"{reference.data_start} → {reference.data_end}",
                "universe": reference.universe_name,
                "universe_frozen_as_of": reference.universe_frozen_as_of,
                "timing": (
                    f"{reference.signal_timing} → {reference.execution_timing}"
                    f" → {reference.valuation_timing}"
                ),
                "folds": len(reference.folds),
                "cost_multipliers": ", ".join(map(str, reference.cost_multipliers)),
                "selection_metric": reference.selection_metric,
            }
        ]
    )

    metric_names = tuple(name for name, _ in reference.aggregate_metrics)
    st.markdown("#### 逐 run 清单指标")
    st.dataframe(
        [
            {
                "selection_order": order,
                "run_id": run.manifest.run_id,
                "hypothesis_id": run.manifest.hypothesis_id,
                "strategy": run.manifest.strategy_name,
                "strategy_version": run.manifest.strategy_version,
                "conclusion": run.manifest.conclusion,
                "random_seed": run.manifest.random_seed,
                "config_relative_path": run.manifest.config_relative_path,
                "config_sha256": run.manifest.config_sha256,
                "code_sha256": run.manifest.code_sha256,
                **{
                    f"metric · {name}": dict(run.manifest.aggregate_metrics)[name]
                    for name in metric_names
                },
            }
            for order, run in enumerate(runs, start=1)
        ],
        width="stretch",
        hide_index=True,
    )

    st.markdown("#### 假设与 caveats")
    st.dataframe(
        [
            {
                "selection_order": order,
                "run_id": run.manifest.run_id,
                "hypothesis": run.manifest.hypothesis,
                "caveats": "\n".join(run.manifest.caveats) or "—",
            }
            for order, run in enumerate(runs, start=1)
        ],
        width="stretch",
        hide_index=True,
    )

    with st.expander("逐 run 输入与输出证据", expanded=False):
        st.markdown("**Inputs**")
        st.dataframe(
            [
                {
                    "selection_order": order,
                    "run_id": run.manifest.run_id,
                    "name": item.name,
                    "rows": item.rows,
                    "min_date": item.min_date,
                    "max_date": item.max_date,
                    "content_sha256": item.content_sha256,
                }
                for order, run in enumerate(runs, start=1)
                for item in run.manifest.inputs
            ],
            width="stretch",
            hide_index=True,
        )
        st.markdown("**Outputs**")
        st.dataframe(
            [
                {
                    "selection_order": order,
                    "run_id": run.manifest.run_id,
                    "relative_path": item.relative_path,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                }
                for order, run in enumerate(runs, start=1)
                for item in run.manifest.outputs
            ],
            width="stretch",
            hide_index=True,
        )


def _render_issues(st: Any, catalog: ResearchRunCatalog) -> None:
    if not catalog.issues:
        return
    st.warning(f"发现 {len(catalog.issues)} 个被隔离的目录或清单问题。")
    with st.expander("查看结构化问题", expanded=not catalog.runs):
        st.dataframe(
            [
                {"code": issue.code, "entry": issue.entry, "detail": issue.detail}
                for issue in catalog.issues
            ],
            width="stretch",
            hide_index=True,
        )


def _summary_row(run: ResearchRunSummary) -> dict[str, object]:
    manifest = run.manifest
    metrics = dict(manifest.aggregate_metrics)
    return {
        "data_end": manifest.data_end,
        "conclusion": manifest.conclusion,
        "strategy": manifest.strategy_name,
        "strategy_version": manifest.strategy_version,
        "hypothesis_id": manifest.hypothesis_id,
        "selection_metric": manifest.selection_metric,
        "selection_value": metrics.get(manifest.selection_metric),
        "folds": len(manifest.folds),
        "run_id": manifest.run_id,
    }


def _run_label(run: ResearchRunSummary) -> str:
    manifest = run.manifest
    return (
        f"{manifest.data_end} · {manifest.strategy_name} · "
        f"{manifest.conclusion} · {manifest.run_id[:12]}"
    )


if __name__ == "__main__":
    main()
