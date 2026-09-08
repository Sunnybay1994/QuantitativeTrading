# M3 HISTORY-PILOT10 主 Agent 直接验证报告

日期：2026-07-18  
验证角色：主 Agent  
执行报告：[`M3_HISTORY-PILOT10真实有界恢复执行报告.md`](M3_HISTORY-PILOT10真实有界恢复执行报告.md)  
状态：**PILOT10 验证通过**；HISTORY/G1/M3 Gate 仍未完成

## 1. 流程边界

用户在本任务中临时授权：自授权起 24 小时内，后续任务不调用外部 Agent，省略“外部实现 + 外部独立初验”，
由主 Agent 自行完成，可使用内部子 Agent 并行。因此本报告是主 Agent 直接验证，不冒充或声称外部独立验证。

内部只读 Agent 仅辅助复核路径、预算和停止条件；唯一真实网络命令及最终 receipt/status 验证均由主 Agent
直接控制。没有内部 Agent 执行第二次 HISTORY 命令。

## 2. 逐项验证

| 验证项 | 证据 | 结论 |
|---|---|---|
| 执行前 baseline | 3186 total / 114 verified / 3072 missing / `[INDEX]` / partial=0 | 通过 |
| 单次命令与预算 | `--max-new-requests 10` 只运行一次；CLI committed=10 | 通过 |
| 新增 identity | 执行前冻结的前 10 个缺失 id 均产生并通过 receipt | 通过 |
| 新增 endpoint | `suspend_d=10` | 通过 |
| receipt/raw 闭包 | 生产 `verify_tushare_receipt` 校验 spec、identity、digest、policy、raw bundle | 通过 |
| 计数守恒 | `124-114 = 10`；`3072-3062 = 10` | 通过 |
| partial 状态 | 计划内无 receipt partial 仍为 0 | 通过 |
| 旧历史证据 | 无 `ts_code` 月窗仍为 5 完整 + 1 不完整 | 通过 |
| 阶段边界 | 最终 status 仍 `[INDEX] / INCOMPLETE` | 通过 |
| API attempts | 精确次数不可由 receipt 独立证明；单命令和配置给出最多 50 的合同上限 | 如实保留 |

## 3. 结论与下一步约束

PILOT10 成功证明 H4 的 `--max-new-requests`、XP0 writer lock、Tushare `suspend_d`、raw/journal/receipt
发布与恢复路径可以在当前迁移后工作区完成一个真实有界批次。

仍不得声称 HISTORY、G1 或 M3 Gate 完成。下一批会把真实网络预算从已授权的 10 个 identity 扩大到新的范围；
在获得明确的新预算授权前，不执行第二次 `history` 命令。后续批次仍必须保持：固定 N、单次命令、失败即停、
执行后逐 receipt 验证、不得把已有 receipt 计入新额度。
