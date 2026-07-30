# M3 G1 P0K-A-R1 交付报告：release 闭包白名单修订

状态：**实现完成（未宣布 Gate / 终验）**

日期：2026-07-30（Asia/Shanghai）

实现模型：`cursor-grok-4.5-high`

上游停止报告保持历史不可变：
`docs/agent/M3_G1_P0K-A_CNINFO股改分红与股本变动raw-first全链交付报告.md`

实现基线（R2 任务单冻结）：`cf7821680ec097c50c0f4fcd7ced424e4c40308a`

## 1. 本轮相对 R1 合同的闭包

在 R1 修订白名单内完成：

1. `src/quant/data/m3_release.py::_consume_build_inputs` 重建 `G1BuildInputs` 时携带
   `cninfo_dividend_responses` / `cninfo_share_change_responses`。
2. `tests/unit/test_m3_g1_release.py`：所有直接 `G1BuildInputs(...)` 显式提供两新 tuple；
   新增 consume 精确重建、CA receipt/frame 篡改 fail-closed、PREPARE 投影保留断言。
3. `tests/unit/test_m3_backfill_requests.py`：plan 升级为 `m3-g1-request-plan-v3`，
   `_plan_hash` 含五个 batch；旧 v2 / 交换遗漏新 batch 拒绝或改 identity。
4. 上游 P0K-A connector / plan / workflow / candidate / reference 链一并落在同一提交范围
  （见 R2 报告复核表）。

## 2. 验证摘要（与 R2 共跑）

- 白名单 Ruff：通过
- 白名单源码 mypy：通过（6 files）
- `git diff --check`（白名单）：通过
- 定向 pytest：见 R2 交付报告分批摘要；`test_strict_json_readers` 单独与 release 全文件均通过

未运行：WSL Gate、正式网络 HISTORY、P0K-B、G1 Gate / Codex 终验。

## 3. 说明

本报告只覆盖 R1 白名单闭包；五阶段最小 fixture 与中断恢复细节见 R2 报告。
实现 Agent 不宣布主验或 Gate 通过。
