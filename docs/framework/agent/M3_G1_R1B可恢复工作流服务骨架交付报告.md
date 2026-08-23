# M3 G1-R1B 可恢复工作流服务骨架交付报告

日期：2026-07-16
包号：**R1B**
实现模型：`cursor-grok-4.5-high`
状态：**待独立复验**（**未通过任何 Gate**；未关闭 B4/G1/M3 Gate）

> 任务书路径写为 `docs/M3_G1_R1B…交付报告.md`；按 docs 治理放在 `docs/agent/`，本文件即该交付报告。

## 1. 冻结输入 / 输出摘要

### 输入（只读依赖）

- R1A：`build_g1_static_plan` / `derive_g1_history_plan`
- B2A：`execute_tushare_batch` / `verify_tushare_receipt` / `VerifiedRawResponse`
- P2/P3：`build_g1_candidate` / `verify_g1_candidate` / `audit_g1_candidate`
- P4B：`execute_baostock_reference_plan` / `reconcile_cross_source` / `VerifiedReferenceResponse`
- P4C：`prepare_g1_release` / `publish_g1_release` / `verify_g1_release` / `platform_supports_renameat2_noreplace`
- Connector 薄适配器：`TushareConnector` / `BaostockConnector`（仅显式注入）

### 输出（本包新增）

五段可恢复服务 API：

`INDEX → HISTORY → REFERENCE → PREPARE → PUBLISH`

公开符号：`inspect_g1_workflow`、`run_g1_index_stage`、`run_g1_history_stage`、`run_g1_reference_stage`、`prepare_g1_workflow`、`publish_g1_workflow`，以及 `Stage` / `Operation` / `CauseCategory` / `G1WorkflowCountsV1` / `VerifiedG1WorkflowStateV1` / `M3G1WorkflowError`。

## 2. 修改文件列表

| 路径 | 说明 |
|---|---|
| `src/quant/research/m3/g1_workflow.py` | 新建：R1B 工作流服务骨架 |
| `src/quant/research/m3/__init__.py` | 仅增量导出 R1B 公共符号 |
| `tests/unit/test_m3_g1_workflow.py` | 新建：fake 集成 / 状态机 / 反例 |
| `docs/framework/agent/M3_G1_R1B可恢复工作流服务骨架交付报告.md` | 本交付报告 |

未改：connector、RawStore、B2A/P2/P3/P4 算法、R1A、C0、配置、路线图、`data/` 产物。

## 3. 自测命令与摘要

环境：`/home/mabw/miniforge3/bin/conda run -n base …`（WSL Miniforge `base`，未用 Windows Python / `py312`）。

| 命令 | 结果摘要 |
|---|---|
| `python -m pytest -q tests/unit/test_m3_g1_workflow.py` | **15 passed**（约 50m；含完整五段 fake publish） |
| `python -m pytest -q` | 全量回归进行中 / 见终验前最新跑次 |
| `python -m ruff check src tests` | **All checks passed** |
| `python -m mypy src` | **Success: no issues found in 82 source files** |

## 4. Fake 与真实网络

- **使用 fake**：注入 `TushareConnector(pro_client=…)`、`BaostockConnector(client=…)`；默认测试零网络。
- **未做真实网络**：无真实 Tushare token / BaoStock 登录回补；无 2016–2026 全量跑数。
- **publish**：WSL1 上 `platform_supports_renameat2_noreplace()` 常为 false；测试对支持分支 monkeypatch `_renameat2_noreplace`，并单独覆盖 `G1_WORKFLOW_PUBLISH_UNSUPPORTED` 零 staging。

## 5. 已知限制

1. HISTORY 计划在短 signal 窗口下仍约 1205 个 Tushare 请求；定向五段测试耗时长（I/O + candidate 重建）。
2. WSL1 内核常不支持 `renameat2(RENAME_NOREPLACE)` → 生产路径会稳定 `G1_WORKFLOW_PUBLISH_UNSUPPORTED`，直至宿主支持或后续 R1C/运维环境具备该能力。
3. R1B 不含 argparse CLI、不含完整真实回补；Gate 关闭属后续 R1C / 主验职责。
4. `counts` 为当前 verified plan 的计划总数，不是已完成 receipt 数；进度只看 `completed_stages`。
5. 普通 `inspect` 在未发布时不声称 `PREPARE`；`PREPARE` 是 `prepare_g1_workflow` 瞬时返回态；已发布可闭包到 `PUBLISH`。

## 6. Gate 声明

- 本交付状态：**待独立复验**。
- **未宣称** Gate / M3 / G1 / B4 通过。
- **未勾选** `项目实施路线图.md`。
- 实现者自测 **不能** 代替独立初验或主 Agent 终验。

## 7. 返工（§9.1 operation 伪报 INSPECT）

日期：2026-07-16
返工模型：`cursor-grok-4.5-high`（非 fast；未用 GPT/Terra）

### 现象

`run_g1_history_stage`（及 INDEX 等经 `_inspect(operation=…)` 的入口）在项目根 exit identity 校验失败时，公开异常 `operation` 为 `INSPECT`，`str(error)=="INSPECT:G1_WORKFLOW_PROJECT_ROOT_INVALID"`。

### 根因

`_assert_root_unchanged` / `_assert_calendar_slice` 写死 `operation="INSPECT"`，忽略 `_inspect` 传入的公开动作。

### 修复

- `_assert_root_unchanged(layout, *, operation: Operation)`、`_assert_calendar_slice(..., operation=...)` 透传调用方 `operation`。
- `_inspect` / `_make_build_inputs` 传入当前公开动作；仅 `inspect_g1_workflow` 使用 `INSPECT`。
- 硬编码 `operation="INSPECT"` 仅剩 `inspect_g1_workflow` 入口。

### 新测试

- `test_history_entry_root_identity_failure_reports_history_operation`
- `test_index_entry_root_identity_failure_reports_index_operation`
- `test_inspect_root_identity_failure_still_reports_inspect`

### 命令摘要（返工自测）

| 命令 | 结果摘要 |
|---|---|
| `pytest -q … -k "history_entry_root_identity_failure or index_entry_root_identity or inspect_root_identity"` | **3 passed**（~2s；仅 PATH/operation） |
| `ruff check src tests` | **All checks passed** |
| `mypy src` | **Success: no issues found in 82 source files** |

**本返工仅定向**：未跑 `test_m3_g1_workflow.py` 五段长测、未跑全量 `pytest -q`。全量回归留给主 Agent 终验；包级初验已跑过基线。**未关闭 Gate**；可交独立复验。
