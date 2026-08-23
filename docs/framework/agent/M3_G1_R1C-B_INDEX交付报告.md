# M3 G1 R1C-B INDEX 交付报告

角色：外部真实运行 Agent（唯一数据写者）  
模型：`cursor-grok-4.5-high`  
日期：2026-07-17  
结论：**INDEX 未通过**；稳定失败 `G1_WORKFLOW_IDENTITY_MISMATCH`；未启动 HISTORY；不宣称 R1C-B / G1 / M3 Gate 完成。

## 1. 执行摘要

| 项 | 值 |
|---|---|
| 起 UTC | `2026-07-16T23:58:37Z` |
| 止 UTC | `2026-07-17T00:01:38Z` |
| `index` 退出码 | `3` |
| outcome | `FAILED` |
| error_operation | `INDEX` |
| error_code | `G1_WORKFLOW_IDENTITY_MISMATCH` |
| completed_stages | `[]` |
| CLI 计划 index_requests（失败返回） | `0`（失败态按契约回退；见下本地证据） |
| history_requests / history_symbols / reference_requests | `0` / `0` / `0` |
| primary_candidate_key / release_id / manifest_sha256 | 均为 `null` |

前置零网络 `status`（启动前）：`outcome=INCOMPLETE`，`completed_stages=[]`，`index_requests=127`，fresh。

INDEX 后新进程 `status`：`outcome=FAILED`，`error_operation=INSPECT`，`error_code=G1_WORKFLOW_IDENTITY_MISMATCH`，退出码 `3`，`completed_stages=[]`。

## 2. 本地证据汇总（相对逻辑范围）

| 范围 | 汇总 |
|---|---|
| `data/raw/m3_g1/tushare/` | 仅有 `index_weight` 端点目录 |
| raw `index_weight` request 目录数 | **127** |
| raw 文件数 / 字节 | **254** / **1,083,006** |
| run_state receipt 目录数 / `receipt.json` 数 | **127** / **127** |
| run_state 文件数 / 字节 | **382** / **845,757** |
| 合计字节（raw + run_state） | **1,928,763** |
| `.writer.lock` | 文件存在（非 active 写进程；本会话写阶段已退出） |

未发现 `daily` / `adj_factor` / `stk_limit` / `dividend` / `index_daily` / `suspend_d` 等 HISTORY 端点产物。

## 3. INDEX 后派生量

INDEX 阶段未 verified 完成，故：

- 真实历史成分并集 **S：未知 / 不可用**
- CLI/工作流给出的 `history_requests`：**0**（未派生）
- CLI/工作流给出的 `reference_requests`：**0**（未派生）
- 基于 60 requests/minute 的 HISTORY 纯限频理论下限：**不可计算**（依赖 S）

## 4. 未启动 HISTORY 证明

1. 本会话仅调用：`status` → `index` → `status`；从未调用 `history` / `reference` / `prepare` / `publish` / `run-all`。
2. `completed_stages` 始终为空；无 HISTORY 完成 marker。
3. raw 树仅含 `tushare/index_weight`，无七端点中其余 HISTORY 端点目录。

## 5. 失败与可恢复性

- **失败性质**：合同/身份类永久失败（`G1_WORKFLOW_IDENTITY_MISMATCH`），非网络/限频瞬态；按授权协议**立即停止、不重试、不改配置、不放宽空响应政策**。
- **可恢复程度**：本地保留 127 个 `index_weight` request 的 raw 与对应 journal receipt/intent/candidate 证据，可供电文复核；但当前 `status`/`INSPECT` 亦因同一稳定 code 失败，**不能**声称存在可直接 resume 至 INDEX SUCCESS 的 verified journal。需主 Agent 先裁定身份合同根因后再决定是否返工。
- **不通过**：本报告不宣称 INDEX、R1C-B、G1 或 M3 任一 Gate 完成。
