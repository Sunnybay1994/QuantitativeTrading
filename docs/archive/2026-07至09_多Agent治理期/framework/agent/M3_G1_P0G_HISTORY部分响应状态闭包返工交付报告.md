# M3 G1 P0G：HISTORY 部分响应状态闭包返工交付报告

状态：**外部实现已交付，待外部独立初验**（自测 ≠ 独立初验 ≠ Gate）

日期：2026-07-28（Asia/Shanghai）
实现基线：`123c1c0`（Freeze G1 P0G partial history state closure）
任务书：`docs/framework/agent/M3_G1_P0G_HISTORY部分响应状态闭包返工任务单.md`

## 1. 修复摘要

1. `_inspect`：Tushare history 验证结果仅保存在局部 `verified_history`；仅当 CNINFO batch 亦 `complete` 并验证成功后，才一次性赋值 `history_responses` / `cninfo_responses` 并构建 candidate。
2. `_validate_workflow_state_closure`：INDEX / HISTORY 未完成分支强制 `cninfo_responses == ()`；HISTORY 完成核对 CNINFO request IDs 精确有序 tuple。
3. 未放宽 incomplete 闭包；未改 counts、CLI JSON、错误码、版本、connector、raw/journal、candidate/release。

## 2. 现象—根因—规则—最小复现—新增测试—通过条件

### P0G-1：HISTORY incomplete 泄漏部分 Tushare responses

- **现象**：Tushare complete、CNINFO missing/partial 时，`history_responses` 已写入最终 state，但 `completed_stages == ("INDEX",)`，`VerifiedG1WorkflowStateV1` 自证失败 → CLI `CLI_INTERNAL_ERROR` / exit 1。
- **根因**：在确认 CNINFO complete 之前把 verified Tushare history 赋给最终 state 字段。
- **规则**：stage 未完成不得暴露该 stage 部分产物；磁盘 raw/journal 可保留恢复，verified state 只暴露完成阶段闭包。
- **最小复现**：INDEX complete + `max_new_requests=tushare_n` 使 Tushare complete 且 CNINFO remaining=0；或再造 CNINFO request 目录无 receipt（partial）；调用真实 `_inspect` / `inspect_g1_workflow`。
- **新增测试**：
  - `test_p0g_tushare_complete_cninfo_missing_inspect_index_only`
  - `test_p0g_tushare_complete_cninfo_partial_inspect_index_only`
  - `test_p0g_status_partial_history_shape_socket_and_connector_poison`
- **通过条件**：inspect/status 成功返回 INDEX-only；`history_responses`/`cninfo_responses`/candidate/reference/prepared/published 为空；counts 仍为计划 totals；socket 阻断下零网络零写；CLI exit 0、`INCOMPLETE`。

### P0G-2：状态闭包遗漏 CNINFO response IDs

- **现象**：闭包在 incomplete 分支未检查 `cninfo_responses`；HISTORY complete 只核 Tushare IDs。
- **根因**：P0F 新增字段后闭包未覆盖全部生命周期分支。
- **规则**：HISTORY 是 Tushare+CNINFO 联合完成；state 必须绑定两批精确有序 request IDs。
- **最小复现**：对 fresh/index 注入 CNINFO stub；对 HISTORY-complete 删除/重排/替换 CNINFO responses。
- **新增测试**：`test_p0g_cninfo_response_closure_rejects_tampering`；两批 complete：`test_p0g_both_batches_complete_history_succeeds`。
- **通过条件**：上述篡改均 `ValueError`；两批 complete 时 HISTORY 正常完成且 IDs 有序匹配。

## 3. 白名单变更

| 路径 | 变更 |
|---|---|
| `src/quant/research/m3/g1_workflow.py` | 局部 verified history；闭包 CNINFO 生命周期 |
| `tests/unit/test_m3_g1_workflow.py` | P0G missing/partial/complete/tamper 测试 |
| `tests/unit/test_m3_run_g1.py` | status socket+connector poison INDEX-only |
| `docs/framework/agent/M3_G1_P0G_HISTORY部分响应状态闭包返工交付报告.md` | 本报告 |

## 4. 验证命令与退出码

解释器：`D:\Miniforge3\python.exe`（Windows 原生反馈环）。

| 命令 | 退出码 |
|---|---|
| `pytest -q`：P0G 四测 + bounded/unbounded history + fresh inspect + self-proof + CLI P0G status（共 9） | 0 |
| `pytest -q`：index idempotent / history requires index / max-new illegal / status incomplete / socket blocked / never construct connectors（共 6） | 0 |
| `ruff check` 上述三代码文件 | 0 |
| `mypy src/quant/research/m3/g1_workflow.py` | 0 |
| `git diff --check 123c1c0 -- <白名单代码>` | 0 |

未运行：five-stage 全文件、正式网络 CNINFO HISTORY、正式 Windows/WSL status 磁盘复现、全量 pytest/Ruff/mypy。正式 status 终验属主 Agent / 独立初验。

## 5. 残留风险

- 正式磁盘（INDEX + 旧 Tushare HISTORY、缺 CNINFO）尚未由本会话重跑 CLI status；需独立初验/主 Agent 确认 exit 0 INCOMPLETE。
- 本交付仅为外部实现自测；不得宣称独立初验或 G1 Gate 通过。
- P0G 通过前禁止正式 CNINFO 网络 HISTORY。
