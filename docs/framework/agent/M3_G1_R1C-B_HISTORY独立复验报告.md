# M3 G1 R1C-B HISTORY 独立复验报告

角色：全新外部独立复验 Agent（代码与 data 只读）  
模型：`cursor-grok-4.5-high`  
日期：2026-07-17  
对照：成功路径条款仅作对照；**本次按失败态裁定**。

## 裁定

**独立复验确认 HISTORY 未通过**；质量截断硬阻塞（`TUSHARE_RESPONSE_MAY_BE_TRUNCATED`：响应行数 ≥ 冻结 `row_limit`）；停止边界合法；交付未夸大、INDEX evidence 未被破坏、未偷偷启动后续阶段。  
**可交主 Agent 裁定根因 / 是否授权返工。**  
不宣称 R1C-B / G1 / M3 或任一 Gate 完成；**不建议**放宽空响应或截断门禁作为“修复”。

## 1. 新进程零网络 `status`

实测（本复验新进程）：

```json
{"command":"status","completed_stages":["INDEX"],"error_code":null,"error_operation":null,"history_requests":2679,"history_symbols":637,"index_requests":127,"manifest_sha256":null,"outcome":"INCOMPLETE","primary_candidate_key":null,"reference_requests":0,"release_id":null,"schema_version":"m3-g1-cli-result-v1"}
```

| 核对项 | 结果 |
|---|---|
| `completed_stages` 精确 `[INDEX]` | 通过（无 `HISTORY`） |
| `history_symbols=637` | 通过 |
| `history_requests=2679` | 通过（计划数，非已完成） |
| 无 REFERENCE / release | 通过：`reference_requests=0`，`primary_candidate_key`/`release_id`/`manifest_sha256` 均为 `null` |
| 与交付事后 status | 字段一致 |

## 2. INDEX 127 `index_weight` evidence

- receipt=`127`，且各 journal 均含 `intent.json` + `candidate.json` + `receipt.json`；raw 路径可解析，坏样本=`0`。
- raw `index_weight`：dirs=`127`，files=`254`，bytes=`550526`（与交付一致）。
- **结论**：INDEX evidence 仍完整可恢复，未见 HISTORY 破坏。

## 3. HISTORY receipt / journal / 端点分布

| 项 | 复验 | 交付 |
|---|---|---|
| HISTORY 已提交 receipt | **119** | 119 |
| 分布 | daily 36 + adj_factor 28 + stk_limit 29 + dividend 21 + suspend_d 5 + index_daily **0** | 同左 |
| 未完成 journal | **1**：仅 `intent.json`，endpoint=`suspend_d`，无 candidate/receipt | 同左 |
| 该 incomplete 违规完成 receipt | **无**（同 `request_id` 他处完成数=0） | — |
| request_id 重复 | 0（intent 总数 247 = INDEX127 + HISTORY119 + incomplete1） | — |
| 未授权 HISTORY 端点 | 无 | — |
| raw↔receipt 目录数 | 六端点均精确匹配 | 汇总一致 |

## 4. 无 BaoStock / PREPARE / PUBLISH 产物

- `data/raw/m3_g1/baostock`、`data/run_state/m3_g1/baostock`、`data/releases`：**不存在**。
- run_state/raw 下 `prepare` / `publish` / `candidate`（阶段树）命中：**0**。
- 仅见既有 `data/legacy/reference`（非本阶段 BaoStock 写产物），不构成 REFERENCE 完成证据。
- `status` 无 REFERENCE/release 字段。

## 5. 截断合同与不宜盲目 resume

**合同（只读 `m3_backfill.py`）**：`frame.height >= policy.row_limit` → `M3BackfillError("TUSHARE_RESPONSE_MAY_BE_TRUNCATED")`。  
冻结 `suspend_d`：`row_limit=5000`，`empty_response=ALLOW`（空响应允许 ≠ 截断允许）。

**失败态证据链**：

1. 唯一未完成 intent：`suspend_d`，月窗 `20160301`–`20160331`，`suspend_type=S`；目录仅 `intent.json`（质量门禁在 commit 前打断）。
2. 已提交 `suspend_d` 最大行数已达 **4951 / 4872**（相对 limit 5000），证明同契约月窗响应可逼近/触及截断阈值。
3. 计划切分本身即为按月 `suspend_d`（源码计划器）；盲目 resume 会重试同一 identity/同一月窗，在不改分页/切分合同的前提下极可能再次触发 `>= row_limit` 硬失败。
4. 按 §8 / 外部运行授权：质量或合同失败 → **立即停止**，不得当网络瞬态连刷。

故：**不宜盲目 resume**；需主 Agent 裁定根因（分页 / `row_limit` / 请求切分合同）后再谈是否授权返工。不得建议放宽截断或空响应门禁。

## 6. 凭据扫描（不输出 secret）

- 扫描范围：`docs/agent`、`data/run_state/m3_g1`、`configs`（及先轮 `data/raw/m3_g1`）。
- **命中路径数：1**（`configs/tushare.local.toml`）；疑似 token 赋值类模式。不输出内容。

## 7. 对抗核对（交付未写）

1. **近限已提交 vs 未完成月窗**：已完成 `suspend_d` 行数已达 4951/4872，未完成窗为更早月 `201603`；结合“仅 intent、无 candidate”结构，独立支持“截断硬停于 commit 前”，而非交付夸大或中途放行。
2. **raw 目录数 ≡ receipt 数**（含 `index_daily=0`），无 orphan receipt、无 candidate-without-receipt，无超计划端点写入。
3. **缺口**：计划 2679 − 已提交 119 = **2560** 未完成；`completed_stages` 仍仅 `INDEX`，与失败态一致。

## 8. 与交付一致性

交付结论（HISTORY 未通过、`TUSHARE_RESPONSE_MAY_BE_TRUNCATED`、未启动后续阶段、保留 INDEX+部分 HISTORY）与本复验证据**一致**；停止合法。  
备注：交付将工作流 `cause_category` 记为 `NETWORK` 包装层——属映射说明，不改变底层质量截断硬阻塞定性，**不构成交付夸大 P0**。

## 结论

独立复验确认 HISTORY **未通过**；质量截断硬阻塞；可交主 Agent 裁定根因/是否授权返工。
