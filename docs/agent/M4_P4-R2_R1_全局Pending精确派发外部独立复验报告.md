# M4 P4-R2 R1：全局 PENDING 精确派发外部独立复验报告

日期：2026-08-11  
角色：未参与 P4-R2 实现或交付的全新外部独立复验 Agent（`cursor-grok-4.5-high`）  
结论：**PASS，可交主 Agent 终验**  
范围：关闭原子 pending 精确派发子合同；**不**关闭 P4 / P6 / P8 / PAPER soak / Linux Gate / M4。

## 前置核对

| 前置 | 证据 | 结论 |
|---|---|---|
| P4-C R2 durable cancel 独立复验 | `docs/agent/M4_P4-C_R2_durableCancel独立复验报告.md` 明确 **PASS** | 满足任务单“等待 P4-C R2 独立复验结束后实现”的入口条件 |

## 契约映射（只读核对）

对照 `docs/agent/M4_P4-R2_R1_全局Pending精确派发任务单.md` 与交付报告：

1. **保留** `dispatch_commands` allowlist；**新增**  
   `claim_exact_pending_outbox_deliveries` / `dispatch_exact_pending_commands`。  
2. store 在调用方 `BEGIN IMMEDIATE` 事务内：canonical sorted unique 非空 id → 全表 typed delivery closure → 禁止任意 `LEASED`/`UNKNOWN` → pending 集合精确等于输入 → 含未来 `available_at` 视为漂移 → 再委托 `claim_selected_outbox_deliveries`；rowcount/identity/payload fence 冲突映射 `OUTBOX_DELIVERY_EXACT_SET_DRIFT`。  
3. service 只组合原子 claim + 既有 `_dispatch_claimed`；仅  
   `OUTBOX_DELIVERY_EXACT_SET_DRIFT` → `SERVICE_EXACT_PENDING_SET_DRIFT`，其余写/事务失败 → `SERVICE_EXACT_PENDING_WRITE_FAILED`；异常 cause/context 断开。  
4. CLI `paper-submit` 确认后走 exact API；漂移 → exit 20 `CONFIRMATION_DRIFT`；写失败 → exit 50。  
5. 既有 SENT 可并存；allowlist 在 B pending 时仍可只发 A（实现者测试 + 本轮对抗均覆盖）。

生产/实现测试/任务/交付均只读；本文件为唯一写入。

## 实现者已覆盖（抽查）

- 完整集合成功；EXTRA/MISSING/FUTURE；全局 LEASED/UNKNOWN；双 worker 至多一胜。  
- writer busy / claim trigger → `WRITE_FAILED` / CLI 50，非漂移。  
- 确认后并发插入 → CLI 20、gateway 0、两 delivery 仍 PENDING。  
- 原 allowlist `dispatch_commands((A,))` 合同保留。

## 实现者未用的对抗（本轮独立补齐）

临时脚本（仓外，未改仓库）：`%TEMP%\p4r2_adversarial_probe.py`  
结果：**32 PASS / 0 FAIL**。

| 对抗项 | 现象与判定 |
|---|---|
| 跨 account/session pending 集合 | 同 store 内 A 子集 / B 子集 exact claim 均 `OUTBOX_DELIVERY_EXACT_SET_DRIFT`、attempt=0；仅全局并集可 claim |
| claim/lease/attempt fencing | 首次 exact 后 attempt=1/owner 固定；并发第二 worker、甚至 lease 过期后的 exact 仍漂移（exact 禁止任何 LEASED，不走 allowlist reclaim） |
| NOT_SENT vs UNKNOWN retry | NOT_SENT 保持 LEASED，exact 不可重试；lease 过期后 **allowlist** 可 reclaim 并 SENT。UNKNOWN 落 durable UNKNOWN，exact 与 allowlist 均不可自动重试 |
| cancel 与 submit 混合 | 并存 cancel PENDING 不阻挡 submit exact；cancel delivery 仍 PENDING/attempt=0 |
| 同 id 异 payload | command/outbox payload 不一致 → exact drift，零副作用 |
| 集合少/多/重复/顺序 | fewer/more → `SET_DRIFT`；duplicate/unsorted → `SELECTION_INVALID`；gateway 0。既有 SENT + 剩余 pending exact 成功；allowlist 仍可单发 |
| hostile 递归异常脱敏 | 注入带嵌套 cause/context 密钥的 `OUTBOX_DELIVERY_EXACT_SET_DRIFT` → service 仅稳定码、`__cause__`/`__context__` 空、无密钥泄漏、gateway 0 |
| zero side effects / cold import | cold import store/service/cli 无需开库；未来 PENDING / 子集漂移后 state=PENDING、attempt=0、gateway 0 |

## 定向验证

### Windows（`D:\Miniforge3\python.exe`，`PYTHONPATH=src`）

- `ruff check` store/service/cli + 三测试文件 → **PASS**  
- `mypy --no-incremental` 上述三源文件 → **PASS**  
- `pytest` 三文件，独立 basetemp → **276 passed, 5 skipped**

### WSL Miniforge `base`（DrvFS `/mnt/f/...`）

- 同上 ruff/mypy → **PASS**  
- 同上 pytest → **281 passed**  
- `df -T`：`drvfs`（**不等于** ext4 Gate）

未跑全量、未联网、未改代码/add/commit。

## 剩余风险（非本子合同阻断）

- exact 路径对任意 `LEASED`（含过期）一律漂移；NOT_SENT 残留需 allowlist reclaim 或人工处理，不能指望 exact 自愈——符合冻结“禁止 LEASED/UNKNOWN”，但操作手册需明示。  
- DrvFS 绿测不替代 WSL ext4 / Linux Gate。  
- 本报告不关闭 P4 整体、P6 终态、P8 soak 或 M4 Gate。

## 结论

原子全局 PENDING 精确派发子合同独立复验 **PASS**，可交主 Agent 做最终契约与文档一致性验收。
