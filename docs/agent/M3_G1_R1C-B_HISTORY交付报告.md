# M3 G1 R1C-B HISTORY 交付报告

角色：外部真实运行 Agent（唯一数据写者）  
模型：`cursor-grok-4.5-high`  
日期：2026-07-17  
结论：**HISTORY 未通过**；稳定 outcome `FAILED` / `G1_WORKFLOW_EXECUTION_FAILED`；底层稳定 backfill code `TUSHARE_RESPONSE_MAY_BE_TRUNCATED`（质量/截断门禁）；未启动 REFERENCE/PREPARE/PUBLISH；不宣称 R1C-B / G1 / M3 Gate 完成。

## 1. 执行摘要

| 项 | 值 |
|---|---|
| 起 UTC（首次 `history`） | `2026-07-17T04:35:58Z` |
| 止 UTC（末次 `history` 退出） | `2026-07-17T04:42:35Z` |
| 新进程 `status` UTC | `2026-07-17T04:45:48Z` → `2026-07-17T04:46:38Z` |
| `history` 退出码（两次正式 CLI） | `4` / `4` |
| outcome | `FAILED` |
| error_operation | `HISTORY` |
| error_code | `G1_WORKFLOW_EXECUTION_FAILED` |
| 底层稳定 code（诊断，非 CLI JSON 字段） | `TUSHARE_RESPONSE_MAY_BE_TRUNCATED` |
| cause_category（工作流映射） | `NETWORK`（包装层；实际为响应截断质量门禁） |
| completed_stages（失败返回与事后 status） | `["INDEX"]` |
| 计划 history_requests | **2679** |
| 已提交 HISTORY receipt 数 | **119**（未达 2679） |
| history_symbols | **637**（未变） |
| index_requests | **127** |
| reference_requests | **0** |
| primary_candidate_key / release_id / manifest_sha256 | 均为 `null` |

### 启动前零网络 `status`（继续条件已满足）

```json
{"command":"status","completed_stages":["INDEX"],"error_code":null,"error_operation":null,"history_requests":2679,"history_symbols":637,"index_requests":127,"manifest_sha256":null,"outcome":"INCOMPLETE","primary_candidate_key":null,"reference_requests":0,"release_id":null,"schema_version":"m3-g1-cli-result-v1"}
```

### HISTORY 后新进程 `status`（完整脱敏 JSON）

```json
{"command":"status","completed_stages":["INDEX"],"error_code":null,"error_operation":null,"history_requests":2679,"history_symbols":637,"index_requests":127,"manifest_sha256":null,"outcome":"INCOMPLETE","primary_candidate_key":null,"reference_requests":0,"release_id":null,"schema_version":"m3-g1-cli-result-v1"}
```

## 2. 运行轨迹（压缩）

1. 确认无其他 R1C 写阶段进程；未删除 evidence、未改配置/限频/空响应政策、未打印 token。
2. 仅运行：`python -m quant.research.m3.run_g1 --config configs/research/m3_qlib_example.toml history`。
3. 首次约 3.5 分钟失败（exit 4）；当时仅见 CLI `G1_WORKFLOW_EXECUTION_FAILED`，按协议对疑似网络/限频瞬态做**一次**断点恢复（不删 evidence）。
4. 恢复再次约 2 分钟失败（exit 4）；进度未增加。诊断得到稳定底层 code `TUSHARE_RESPONSE_MAY_BE_TRUNCATED` → 判定为**质量/合同类**，立即停止，不再恢复。
5. 新进程 `status` 后停止；未调用 `reference` / `prepare` / `publish` / `run-all` / `index`。

## 3. 本地 raw/journal 汇总（相对逻辑范围）

| 范围 | 汇总 |
|---|---|
| HISTORY 已提交 receipt | **119** = daily 36 + adj_factor 28 + stk_limit 29 + dividend 21 + suspend_d 5 + index_daily **0** |
| INDEX 既有 receipt | **127**（`index_weight`，未改动合同） |
| 未完成 journal | **1**（仅 `intent.json`，endpoint=`suspend_d`，无 candidate/receipt） |
| raw `daily` | dirs=36，files=72，bytes=2,751,684 |
| raw `adj_factor` | dirs=28，files=56，bytes=157,854 |
| raw `stk_limit` | dirs=29，files=58，bytes=650,538 |
| raw `dividend` | dirs=21，files=42，bytes=158,991 |
| raw `suspend_d` | dirs=5，files=10，bytes=23,774 |
| raw `index_daily` | dirs=0 |
| raw `index_weight` | dirs=127，files=254，bytes=550,526 |
| HISTORY 行数合计（已提交 receipt） | daily 85,446；adj_factor 68,388；stk_limit 67,404；dividend 860；suspend_d 12,264 |

## 4. 未启动 REFERENCE / PREPARE / PUBLISH 证明

1. 本会话命令序列仅为：`status` → `history`（×2 CLI + 一次只读诊断）→ `status`；从未调用 `reference` / `prepare` / `publish` / `run-all`。
2. 事后 `status`：`completed_stages=["INDEX"]`，`reference_requests=0`，无 primary/release/manifest。
3. 路径检查：`data/raw/m3_g1/baostock`、`data/run_state/m3_g1/baostock`、prepare/publish 状态树、`data/releases` 均不存在。

## 5. 失败与可恢复性

- **失败性质**：质量/截断门禁 `TUSHARE_RESPONSE_MAY_BE_TRUNCATED`（响应行数 ≥ 冻结 `row_limit`）；**不是**可继续盲目重试的网络/限频瞬态。按授权协议：权限/永久端点/质量或合同失败 → **立即停止**；未放宽空响应、未改配置、未删 evidence。
- **可恢复程度**：已保留 INDEX 全量 + HISTORY 部分（119 receipt + 1 未完成 `suspend_d` intent）证据，可供主 Agent/复验只读核对；**当前不能**声称 HISTORY 可通过简单 resume 完成。需主 Agent 裁定截断根因（分页/row_limit/请求切分合同）后再决定是否授权返工。
- **完成请求数**：计划 2679；已提交 HISTORY receipt **119**；阶段未完成。
- **不通过**：本报告不宣称 HISTORY、R1C-B、G1 或 M3 任一 Gate 完成。
