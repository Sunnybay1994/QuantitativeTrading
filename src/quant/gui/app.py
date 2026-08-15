"""Streamlit view for the read-only Quant research workbench."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

from quant.gui.launcher import ARTIFACT_ROOT_ENV
from quant.gui.research_runs import (
    ResearchRunCatalog,
    ResearchRunSummary,
    conclusion_counts,
    discover_research_runs,
    load_nav_projection,
    verify_research_run,
)


def main() -> None:
    """Render the G0 read-only research cockpit."""
    st = importlib.import_module("streamlit")
    st.set_page_config(page_title="Quant 投研工作台", layout="wide")
    st.title("Quant 投研工作台")
    st.caption("G0 只读研究驾驶舱 · 无 PAPER/LIVE 权限 · 不运行或修改研究产物")

    artifact_root = Path(
        os.environ.get(ARTIFACT_ROOT_ENV, str(Path.cwd() / "artifacts"))
    ).absolute()
    catalog = discover_research_runs(artifact_root)

    page = st.sidebar.radio("页面", ("运行总览", "运行详情"))
    st.sidebar.caption("所有内容来自固定 research/runs 目录；页面不接受任意路径。")
    if page == "运行详情":
        _render_detail(st, catalog)
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
        use_container_width=True,
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
        use_container_width=True,
        hide_index=True,
    )
    st.markdown("#### 聚合指标")
    st.dataframe(
        [{"metric": name, "value": value} for name, value in manifest.aggregate_metrics],
        use_container_width=True,
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
            use_container_width=True,
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
            use_container_width=True,
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
    st.dataframe(nav.frame.tail(100), use_container_width=True, hide_index=True)


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
            use_container_width=True,
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
