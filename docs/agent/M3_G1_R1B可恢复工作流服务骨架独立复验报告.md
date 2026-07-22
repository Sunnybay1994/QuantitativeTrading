# M3 G1-R1B 可恢复工作流服务骨架独立复验报告

日期：2026-07-16  
复验模型：`cursor-grok-4.5-high`（非 fast；未使用 GPT/Terra）  
身份：外部独立复验 Agent（未参与 R1B 实现与返工）  
结论：**通过**（可交主 Agent 终验；**未关闭**任何 Gate；**未勾选**路线图；不宣称 M3/G1/B4 通过）

环境：`cwd=/home/mabw/win/Cursor/quant`；命令前缀 `/home/mabw/miniforge3/bin/conda run -n base …`。  
只读生产代码/测试；**仅写入本报告**。未改代码；未 `git init`；未跑全量 pytest / 五段长测。

---

## 1. 复验范围（窄）

| 项 | 处理 |
|---|---|
| 原不通过 | 初验报告 §5 问题 #1（§9.1 operation 伪报 `INSPECT`） |
| 返工自述 | 交付报告 §7（不作证据，仅对照） |
| 任务书 | §9.1 — 同一上游异常须反映公开函数当前动作；inspect 前置用 `INSPECT` |
| 只读 | `g1_workflow.py`：`_assert_root_unchanged` / `_assert_calendar_slice` / 调用链；`test_m3_g1_workflow.py` PATH 用例 |
| 命令 | 定向 `root_identity_failure`、`ruff check src tests`、`mypy src`；可选 `/tmp` 对抗 |

---

## 2. 源码核对（问题 #1）

| 检查点 | 证据 | 判定 |
|---|---|---|
| `_assert_root_unchanged(layout, *, operation: Operation)` 透传 | `g1_workflow.py`：raise 使用入参 `operation`，无写死 `INSPECT` | 通过 |
| `_assert_calendar_slice(..., operation=...)` 透传 | 同上，切片失败路径使用入参 | 通过 |
| `_inspect` / `_make_build_inputs` 传入当前公开动作 | `_inspect(..., operation=operation)` 末尾 `_assert_root_unchanged(layout, operation=operation)`；`_make_build_inputs` → `_assert_calendar_slice(..., operation=operation)` | 通过 |
| 硬编码 `operation="INSPECT"` 仅剩 inspect 入口 | 全文件仅 `inspect_g1_workflow` → `_inspect(..., operation="INSPECT")` 一处字面量 | 通过 |
| INDEX/HISTORY/… 入口 | `run_g1_*` / `prepare_*` / `publish_*` 设本段 `operation` 并传入 `_inspect` | 通过 |

---

## 3. 测试与对抗

### 3.1 仓库 PATH 用例（只读确认存在）

- `test_history_entry_root_identity_failure_reports_history_operation` → `HISTORY:G1_WORKFLOW_PROJECT_ROOT_INVALID`
- `test_index_entry_root_identity_failure_reports_index_operation` → `INDEX:…`
- `test_inspect_root_identity_failure_still_reports_inspect` → `INSPECT:…`

### 3.2 定向命令摘要（复验自跑）

| 命令 | 摘要 |
|---|---|
| `pytest -q -k "root_identity_failure" tests/unit/test_m3_g1_workflow.py` | **3 passed**, 15 deselected，~2.22s（pandera DeprecationWarning 若干） |
| `ruff check src tests` | **All checks passed**（exit 0） |
| `mypy src` | **Success: no issues found in 82 source files**（exit 0） |

### 3.3 可选 `/tmp` 对抗（不入库）

一次性脚本 `/tmp/r1b_reverify_op_bug.py`：`run_g1_history_stage` + flaky `_dir_identity` →  
`operation=HISTORY`，`str=HISTORY:G1_WORKFLOW_PROJECT_ROOT_INVALID` → **PASS**。  
未改仓库测试。

---

## 4. 问题 #1 关闭判定

相对初验通过条件：

1. 路径助手透传 `operation`，不再写死 `INSPECT` → **满足**  
2. 新 PATH 测 + 定向 pytest / ruff / mypy 绿 → **满足**  
3. 普通 `inspect_g1_workflow` 失败仍报 `INSPECT` → **满足**（定向用例 + 源码入口）

→ **问题 #1 关闭**。

---

## 5. 结论

**通过**（可交主 Agent 终验；**未关闭** Gate；不宣称 M3/G1/B4 通过）。

本复验仅验证 §9.1 PATH/日历助手 operation 归属返工；五段长测与全量回归仍留给主 Agent 终验。
