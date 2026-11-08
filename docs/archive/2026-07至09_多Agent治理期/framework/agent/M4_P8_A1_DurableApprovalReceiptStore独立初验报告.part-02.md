`REVIEW_PASS`（A1 development acceptance evidence chain 静态复核通过；无本轮执行、无新测试声明、无 Gate 或 A2/UA-M4-005 通过声明）。

## 14. REVIEW_REWORK4（同一原始独立审查身份；v3 fixture correction）

审查身份：`01a0322c-f932-7162-b6fb-9f630cf2471f`。本节追加且保留全部 prior findings/history；本轮仅复核 source commit `fb1a07b6f8354537ca26b5832662dc86acd088f4` 上的 REWORK4。严格 `STATIC_ONLY / zero Python`，未运行 Python、pytest、Ruff、mypy、cold import、SQLite、网络、浏览器、CPU、真实 I/O 或任何执行性检查，未提交。

### 14.1 变更边界与证据来源

- 当前 HEAD 是 `fb1a07b6f8354537ca26b5832662dc86acd088f4`，branch 为 `codex/m4-a1-durable-approval-store`；REWORK4 的 worktree diff 包含实现者对 delivery report 的对应记录、`tests/unit/test_execution_store.py` fixture 修复及本审查报告；排除文档后业务/source diff 只有该测试文件，没有 production、migration、schema、codec 或其他测试文件 diff。本 reviewer 未修改 delivery report。
- delivery §15 将 `229 passed / 5 skipped / 1 failed` 明确记为该 fixture 修复前的既有集成回归证据；本轮窄修复后的集成回归、Python、pytest、Ruff、mypy、cold 或 SQLite 均明确未运行。报告没有把这轮改动写成执行通过证据。
- delivery §15 也保留既有 focused `13+8`、Ruff、mypy、cold 等历史来源，不将其改写为 REWORK4 新结果；本复核只对源码/Git diff/文档叙述做静态判断。

### 14.2 v3 fixture 的严格升级修复

#### 现象

既有失败的 `test_v3_upgrade_adds_empty_ledger_tables_without_forging_context` 先用当前 v8 `_open()` 创建数据库，再删除 v4–v7 表并把 `schema_version` 改为 3，却保留 v8 才引入的 `approval_receipts`。重新打开时，严格 v008 `CREATE TABLE approval_receipts` 遇到已存在表而 fail closed，记录为 `MIGRATION_FAILED`。

#### 根因

历史 v3 fixture 的模拟数据库不完整：它保留了高于模拟版本的 approval 表。问题在测试 fixture 的历史库建模，不是 production migration 应该放宽建表约束。

#### 应遵循规则

模拟历史版本必须删除所有高于目标版本引入的表；production v008 必须继续使用严格 `CREATE TABLE approval_receipts`，不得添加 `IF NOT EXISTS` 来掩盖 schema drift、伪造历史上下文或改变 migration failure 语义。

#### 最小静态复现与当前结果

当前 v3 fixture 在 `schema_version = 3` 前额外执行 `DROP TABLE approval_receipts`；reopen 后从真实 `ExecutionStore` recovery path 读取并断言 `rows.approval_receipts == ()`。该路径静态上同时验证“升级后 approval substrate 存在但为空”和“既有 command/ledger recovery 断言保持”。

当前 `src/quant/execution/migrations/v008_approval_receipts.py` 仍是严格 `CREATE TABLE approval_receipts` 加索引定义，静态搜索没有 `IF NOT EXISTS`；该文件在 REWORK4 diff 中未变化。

### 14.3 其他合同未改变与诚实性

REWORK4 diff 未触及 approval codec/HMAC、Verified hand-off/proof、F1 唯一 persistence boundary、v008 schema/migration implementation 或其他测试行为；新增内容只有历史 fixture 的表删除和空 recovery 断言。没有依据这项 fixture 修复宣称新的 runtime result。

delivery §15 明确使用“既有失败现象 + 窄源码修复 + 后续验证待运行”的叙述，且没有把本轮写成执行证据。该叙述与当前 Git diff、严格 v008 源码和 exact8 范围一致。

### 14.4 结论

静态通过条件全部满足：REWORK4 仅修正 v3 fixture；升级后 recovery 明确要求 `approval_receipts == ()`；production v008 保持严格且无 `IF NOT EXISTS`；其他行为、schema、migration 与 proof-forgery/F1 合同未变。

本轮结论：`REVIEW_PASS`（仅 REWORK4 静态复核；不等于该轮测试执行、runtime、Gate、A2 或 UA-M4-005 closure）。
