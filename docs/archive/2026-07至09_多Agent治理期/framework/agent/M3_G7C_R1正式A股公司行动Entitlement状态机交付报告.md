# M3 G7C R1 正式 A 股公司行动 Entitlement 状态机交付报告

日期：2026-08-09  
角色：实现 Agent  
结论：**冻结白名单内实现与双平台定向自测完成；等待独立初验，不宣称主验或 M3 Gate 通过**

## 1. 实现摘要

- 在既有 development corporate-action primitive 旁新增只消费 exact
  `VerifiedAShareMarketFacts` 的 formal replay API；未另建 facts capability、artifact、receipt 或恢复入口。
- 新增 `PRE_OPEN -> RECORD_CLOSE -> next PRE_OPEN/COMPLETE` 的 process-local replay，状态绑定
  `input_market_facts_sha256`，并用 canonical `record_quantities` 覆盖每个 processed event，支持对 position
  存在性、数量、经济字段、日期、due session 和 leg state 的双向复算。
- replay 采用进程内对象身份登记和逐字段 fingerprint；公开 dataclass 构造、`replace`、删 position、改 quantity、
  换 facts identity 或重放旧 phase 都不能作为 formal replay 继续推进。
- record close 使用总 quantity；零持仓只记 processed；RIGHTS 正持仓稳定失败，零持仓不建 position/posting。
  根据重冻补丁，权威 RIGHTS `stock_list_date` 仅保留为市场事实元数据，不进入 entitlement settlement。
- DIVIDEND 与 SHARE_CONSIDERATION 支持 cash/stock 双 leg。CAPTURE 每 event/position 一条且金额、股数、delta
  均为零；盘前严格先完成全部 recognize，再按 event/cash-before-stock 完成 exact due-session settle。
- cash capture/recognize 保持税前 CNY gross；formal 乘法使用私有 50 位、Inexact/Rounded trap context，settle
  仅一次 `HALF_UP` 到分并记录 rounding delta；stock 必须 exact integer。
- formal transition 对 posting 的日期、before/after、金额、股数、rounding、聚合 delta 和事件唯一性做闭包校验；
  唯一公开稳定错误为 `M3_A_SHARE_ENTITLEMENT_INVALID`，异常无 cause/context 且不泄漏输入内容。
- `EntitlementPosition` 仅增加带兼容默认值的 `action_type`；原 development API 和既有测试保持通过。

## 2. 冻结期间发现并回写的合同问题

1. 原任务同时要求 mixed event 每 leg 一条 CAPTURE，又要求 `(date,event_id,posting_type)` 唯一；经主 Agent
   重冻为每 event/position exact 一条 CAPTURE，同时表达两 leg。
2. 仅有 processed IDs 无法区分真实零 quantity 与被伪删的正 quantity position；经重冻增加 canonical
   `record_quantities`。
3. 权威 `CorporateActionLedgerSchema` 强制 RIGHTS `stock_list_date` 非空，而通用“零 leg due 为空”文字与其冲突；
   经重冻明确 RIGHTS 特例仅作市场事实元数据，零-leg due 规则只约束实际 entitlement action。

## 3. 文件范围

- `src/quant/backtest/corporate_actions.py`
- `src/quant/backtest/__init__.py`（仅 formal API 安全导出）
- `tests/unit/test_m3_formal_corporate_actions.py`
- `docs/framework/agent/M3_G7C_R1正式A股公司行动Entitlement状态机任务单.md`（仅状态和主 Agent 重冻补丁）
- 本报告

未修改 G7D-F0/G7E/G1、配置、domain schema/enum 或正式 artifact/journal；未联网、未 add/commit。

## 4. 验证证据

所有命令均显式绑定本 worktree `src`。

Windows 原生 `D:\Miniforge3\python.exe`：

- formal + development 邻接 pytest：`24 passed`；
- G7D-F0 + G7E development + M4 ledger 邻接 pytest：`46 passed`；
- 补强 transition posting 防伪后 formal pytest：`4 passed`；新增 forged-transition 节点复核：`1 passed`；
- 定向 Ruff：PASS；定向 mypy：`Success: no issues found in 1 source file`；
- cold import：PASS，未加载 `qlib`。

WSL Miniforge base，绝对 worktree `PYTHONPATH`：

- formal + development 邻接 pytest：`24 passed`；
- 定向 Ruff：PASS；定向 mypy：`Success: no issues found in 1 source file`；
- cold import：PASS，未加载 `qlib`。

一次最初的 WSL 合并命令被 PowerShell 提前展开 `$PWD`，5.9 秒无输出，未计作证据；随后使用绝对 WSL
路径完整重跑。第一次 WSL cold-import 也因嵌套引号出现 `SyntaxError`，仅重跑该探针后 PASS。当前 WSL 路径为
`/mnt/f` DrvFS，并非 ext4；以上仅为双平台兼容证据。

## 5. 剩余边界

- 本报告是实现者自测，不替代未参与实现者独立初验和主 Agent 最终验收。
- formal G7C 是纯内存状态转移；完整账户循环、真实 full-work 性能、G7D remaining、G7E/G7F、Linux/ext4 与
  M3 Gate 仍开放。
- worktree 存在大量既有 G4-G7 并行脏文件和只读缓存告警，均保持原样；`.pytest_cache` 权限告警不影响测试结论。
