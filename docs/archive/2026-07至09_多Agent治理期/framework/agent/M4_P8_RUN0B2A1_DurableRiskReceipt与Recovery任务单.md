# M4-P8-RUN-0B2A1：Durable Risk Receipt 与 Recovery 任务单

状态：R2 独立复验与主 Agent 最终工程验收 PASS；已解锁 B2A2  
冻结日期：2026-08-09  
前置：RUN-0A R3、RUN-0B1 R3 已通过主 Agent 工程验收；P4-P8 既有工程合同保持不变。

## 1. 背景与目标

现有 `ExecutionService.plan_and_stage()` 已在同一个 OMS SQLite `BEGIN IMMEDIATE` 事务中原子写入
daily risk counter、commands、aggregates、outbox、ledger context 与私有 `execution_stages`。但
`execution_stages` 只是 service 幂等 replay 格式：其 decoder 依赖调用方重新提供原 `OrderPlan`，
`RecoveryRows`/`RecoveryResult` 不读取它，`recovery_id` 也不绑定 pre-trade risk。P7 因而仍接受调用方另传
`risk_decisions`，存在非空 commands 配空 risk tuple 仍生成报告的缺口。

本包只完成第一步：在同一 OMS store 与同一下单/撤单 staging 事务中持久化版本化、canonical、可公开
fresh 解码的 risk transition receipt；recovery 在同一 snapshot 中读取、验证并纳入
`RecoveryResult`/`recovery_id`。订单与撤单共享 `risk_counter_scope:session_date` 的同一 counter 行，因此
transition journal 必须同时覆盖 ORDER 与 CANCEL；只记录订单会把“order → cancel → order”的真实 predecessor
错误判为断链。完成后，P7
才能在后续 B2A2 中移除 caller risk 输入并建立 command-risk exact completeness。

## 2. 明确非目标与信任边界

- 不改 `evaluate_pretrade` 的经济规则，不改变 planner、market、account、TradingConfig、订单或 cancel 语义。
- 不尝试在 recovery 中重新执行 `evaluate_pretrade`。当前系统未 durable 保留可 fresh 重放的完整
  `OrderPlan`、`AccountSnapshot`、`VerifiedMarketSnapshot`、`TradingConfig` 和输入 counter 来源；不得猜测补齐。
- 不把私有 `execution_stages` 升格或复制成公开合同；它继续仅服务原调用的 exact idempotent replay。
- 不新建第二个 SQLite 或文件 sidecar。risk 与 command 是同一 OMS 原子事实，拆库会新增双提交窗口。
- 本包的 hash chain 证明 canonical 结构、顺序、counter transition 与 command closure，不证明首次外部观察。
  持有整个 OMS root 离线写权限的主体仍可把一套语义合法的完整 closure 全部替换并重算自哈希；该威胁由
  后续 P8 独立 evidence/anchor 绑定最终 recovery/report，不得在本包报告中声称“不可伪造来源”。
- 不改 P7、soak、CLI、runner、scheduler、RUN-0A/B1，不创建或迁移 formal root，不注册或启动任务。
- 不认可或回填 legacy formal rows；v006 只建表，已有 command 若没有对应 receipt，formal recovery 必须
  fail closed。

## 3. 公共 receipt 合同

新增 `quant.execution.risk_wire`，至少公开 exact frozen/slots 类型
`DurableRiskTransitionReceipt`、稳定异常类型、严格 canonical encoder/decoder/verifier。名称可在实现前做等价的
最小调整，但不得隐藏为 service 私有函数。

receipt schema v1 至少绑定：

- `transition_kind` exact enum/string union，只允许 `ORDER` / `CANCEL`；
- `schema_version`；
- 全局严格递增 `sequence`、`previous_receipt_id`（genesis 使用唯一冻结 sentinel，不得用空白多义值）；
- `receipt_id`，等于除自身外全部 canonical 内容的 SHA-256 identity；
- `subject_id` 与按 kind 的 exact identity：ORDER 为 `plan_id`，CANCEL 为 `cancel_id`；两种 payload 的字段
  exact-set 必须互斥，禁止用空/null占位形成多种 canonical 表达；
- `risk_counter_key`；
- `predecessor_counter_identity` 与 `projected_counter_identity`；genesis predecessor 必须绑定 canonical
  zero counter identity，而不是任意 caller sentinel；
- ORDER：完整 canonical `RiskDecision`：`accepted`、严格有序且唯一的 `rule_results`、严格有序且唯一的
  `approved_intent_ids`、严格有序且唯一的 `command_ids`、`projected_counters`、
  `requires_manual_approval`；
- CANCEL：完整 canonical `CancelRiskDecision` 与 target closure：`accepted`、`cancel_id`、`command_id`、
  `code`、`policy_identity`、`projected_counters`；只持久化实际 accepted/staged cancel，limit-exceeded 事务不得
  改 counter 或留下 receipt；
- 可证明 exact replay 所需的 decision payload digest；不得只保存调用方自报摘要。

codec/verifier 必须：

- 只接受 exact runtime type、exact key set、canonical UTF-8 JSON bytes；未知字段、重复 JSON key、NaN、
  非 canonical Decimal/date/bool/int、乱序、重复 ID 全部拒绝；
- fresh 重建 `DailyRiskCounters`、ORDER 的 `RiskRuleResult`/decision 或 CANCEL 的 `CancelRiskDecision` 与
  receipt identity，重新编码必须逐 byte 相同；
- `plan_id`、command/intent/receipt/counter identities 均使用现有 64-hex 合同；文本必须 non-empty、trimmed，
  不把 `detail` 放入日志或错误；
- 不导出 signer、通用 arbitrary builder 或模块级可读 secret。builder 只能由 service 在 fresh
  `RiskDecision`、当前 counter row 与已生成 commands 的边界使用；development fixture 若需构造，通过窄测试
  helper，不形成 formal capability；
- 任意未知异常在离开 active `except` 后映射稳定码，`__cause__`/`__context__` 均为 `None`，traceback、repr、
  日志不含 path、SQL、TOKEN、rule detail。

## 4. v006 store 与事务不变量

新增 migration v006 `risk_transition_receipts`。表至少具有：

- `sequence` 唯一且严格递增；`transition_kind + subject_id` 唯一；ORDER `plan_id` 唯一、CANCEL `cancel_id`
  唯一；`receipt_id` 唯一；
- `previous_receipt_id`、`risk_counter_key`、两个 counter identity、canonical payload bytes；
- 必要 CHECK/UNIQUE/FOREIGN KEY 约束，但 canonical 业务验证仍由公开 codec fresh 执行；
- migration 只创建新表/索引，不 backfill 旧 `execution_stages`，不修改既有行。

store/repository 新增窄 `put/get/list`：

- insert only；同 `plan_id`/sequence 的 exact same receipt 是幂等，异 bytes/identity 为稳定 conflict；
- next sequence 与 previous receipt 必须在当前 `BEGIN IMMEDIATE` 写事务内从 store fresh 读取并校验，禁止在
  事务外预计算后盲写；
- `read_recovery_rows()` 在同一事务 snapshot 中按 sequence 读取全部 receipts，并保留原始 bytes/identity/
  chain 字段；任一 orphan/duplicate/FK 漂移 fail closed；
- sqlite busy/transaction failure 保持现有可重试 store/service 语义，不得误译成 identity drift。

## 5. service 原子 staging 与 replay

`plan_and_stage()` 在现有单一事务内执行：

1. fresh 读取 predecessor counter、receipt tail 与 existing stage/receipt；
2. 运行现有 `evaluate_pretrade`，得到 `RiskDecision`；
3. 由 current counter row、projected counter、plan 与 commands 构建 canonical receipt；
4. counter CAS、commands/aggregate/outbox/ledger context、receipt、private stage 全部在同一事务提交。

任一处在 commit 前失败必须全部回滚；commit 后 recovery 必须看到全套 closure。对同 `plan_id` 的 exact replay：

- private stage、receipt、commands、counter identities 与 payload 必须全部 exact；
- exact 时返回既有 staged result且不追加 receipt/sequence；
- receipt 缺失、额外、bytes/identity/counter/command 任何不一致均稳定 fail closed，不把 legacy stage 静默升级；
- same plan different receipt、同 predecessor 并发分叉、receipt-only/command-only 均拒绝。

两个 store connection 对同一 predecessor 并发时，只允许一个基于旧 predecessor 成功；另一个返回既有稳定
busy/CAS/conflict，或在重新 fresh 读取后以新 predecessor 形成下一条合法 receipt，绝不丢计数或分叉。

`stage_cancel()` 必须在它现有的同一事务内，对实际 accepted cancel 同步写一条 CANCEL transition receipt：

- predecessor 是该事务 fresh 读取的同一 counter row identity，projected 是 `CancelRiskDecision` counter；
- receipt 与 counter CAS、cancel command、cancel delivery 同事务；任一失败全回滚；
- exact cancel replay 必须要求既有 cancel row、receipt、counter/policy/target command 全部 exact，不追加
  sequence；legacy cancel row 缺 receipt fail closed；
- limit exceeded 不写 receipt；ORDER 与 CANCEL 对同一 predecessor 并发时同样最多一个成功，另一个必须
  fresh retry，绝不允许各自产生同 predecessor 的分叉。

## 6. RecoveryRows / RecoveryResult 演进

`RecoveryRows` 增加按 sequence 排序的 opaque stored risk receipt tuple。`recover_local_state()` 必须在读取
commands/events/ledger 的同一 SQLite snapshot 内读取 receipts，离开事务后仅从该 retained snapshot 解码：

- chain 从 genesis 到 tail 连续，sequence 不跳号，`previous_receipt_id` exact；
- 每条 projected counter identity 等于 fresh canonical counter；同 `risk_counter_key` 的下一条 predecessor
  exact 等于上一 projected；第一条 predecessor 等于该 session/scope 的 canonical zero counter；跨 counter key
  可以各自独立 genesis，但全局 receipt sequence/previous chain仍唯一；
- ORDER receipt 的 command IDs 全部存在且 command payload fresh valid；每个 command 的
  `command.intent.plan_id == receipt.plan_id`，command intent id 按序对应 approved IDs；同 receipt 内不得重复；
- CANCEL receipt 的 cancel row/target command 必须存在且 fresh valid，`cancel_id`、target `command_id`、
  `risk_counter_key`、`policy_identity` 与 receipt exact；每个 staged cancel 恰有一条 receipt；
- accepted/manual/commands/approved/counter 的现有 stage不变量继续成立；receipt 不依赖 private decoder；
- 有 command 但缺 receipt、receipt 指向不存在/跨 plan command、counter chain/identity 漂移，均返回稳定
  recovery invalid/manual-required 边界，不产生看似健康的 `RecoveryResult`。

`RecoveryResult` 新增 exact verified receipt/decision tuple（优先保留 verified receipt，而非仅裸
`RiskDecision`），`__post_init__` fresh 校验 exact type/order/identity；`_recovery_identity()` 必须绑定每条 canonical
receipt identity与内容。旧 caller 伪造 `recovery_id`、增删换序/whole-rehash receipt但保留旧 recovery outer identity
均拒绝。

formal recovery 的底线是：每个存量 command 必须能唯一归属于一条 ORDER receipt，每个存量 cancel 必须唯一
归属于一条 CANCEL receipt，且同一 counter key 的 ORDER/CANCEL 混合 transition chain 完整；不能出现非空
commands/cancels + 对应 receipt 空。本包暂不改变 P7 的公开调用签名；完整 P7 API 移除 caller tuple、拒绝重复
消费与 exact union 在 B2A2 冻结。

## 7. 稳定失败语义

可新增窄码 `RISK_RECEIPT_INVALID`、`RECOVERY_RISK_CLOSURE_INVALID`，store/service 使用所属层现有命名风格。
必须区分：

- canonical/identity/closure 不成立：不可重试、stable invalid；
- SQLite busy、事务/写失败：保留 retryable store/service 边界；
- legacy command/stage 缺 receipt：formal recovery fail closed，不能自动 backfill；
- hostile codec/store/callback 异常：固定公开码、cause/context None，零 path/SQL/TOKEN/detail 泄露。

禁止用一个宽 `except` 把真实 write/busy 误译为 drift；错误翻译必须在离开 active except 后完成。

## 8. 写入白名单

生产：

- NEW `src/quant/execution/risk_wire.py`
- NEW `src/quant/execution/migrations/v006_risk_receipt.py`
- `src/quant/execution/migrations/__init__.py`
- `src/quant/execution/store.py`
- `src/quant/execution/service.py`
- `src/quant/execution/reconcile.py`
- `src/quant/execution/__init__.py` 仅在确需安全公开新 receipt/recovery 类型时最小导出

测试：

- NEW `tests/unit/test_risk_wire.py`
- `tests/unit/test_execution_store.py`
- `tests/unit/test_execution_service.py`
- `tests/unit/test_reconcile.py`

文档：唯一实现交付报告、后续唯一独立初验报告及本任务单状态/返工追加。禁止修改
`reporting/execution_report.py`、`soak.py`、CLI/runner、broker/runtime、P8 evidence、正式 artifacts/journal、
配置与其他里程碑文件。

## 9. 必测反例

至少覆盖：

1. receipt JSON 未知/缺字段、重复 key、非 canonical bytes、identity/sequence/previous/counter/plan/command
   任一增删改、重复/乱序/orphan/cross-plan；
2. command 非空 + ORDER receipt 空，legacy private stage + command 但无 v006 receipt；cancel 非空 + CANCEL
   receipt 空；
3. exact replay 不追加；同 plan 异 receipt/异 command/异 counter 冲突；
4. receipt 前后、counter CAS 前后、commands/stage 后、commit 前注入失败：commit 前零残留；commit 后 recovery
   exact；
5. order/order、cancel/cancel、order/cancel 两连接同 predecessor 并发：旧 predecessor 最多一个成功；
   busy/stale 后 fresh retry不分叉、不丢 counter；
6. recovery receipt增删换序、duplicate、断链、projected/predecessor漂移、command/intent/plan或
   cancel/target/policy不闭合；显式覆盖 `order R1 → cancel C1 → order R2` 同 key 三段链；
7. 合法另一 receipt closure whole-rehash但保留旧 recovery identity拒绝；报告明确同库全链协调替换不在本包
   信任模型内；
8. hostile JSON/Decimal/date/enum/sqlite/codec异常，递归异常图、repr、traceback均无 marker/path/SQL/TOKEN；
9. Windows 与 WSL base 同组；冷启动 import 不产生循环依赖。DrvFS证据不得写成ext4 Gate。

独立初验必须新增实现者未使用的至少一个并发/crash反例和一个 canonical whole-rehash 反例；只读生产/实现测试，
仅写自己的报告。

## 10. 验证

Windows 原生 `D:\Miniforge3\python.exe`：

- 定向 pytest：上述四个测试文件，加直接依赖的既有 service/recovery 回归；
- Ruff：白名单生产与测试；
- mypy：白名单生产文件。

WSL Miniforge base `/mnt/f` 对应同组定向 pytest/Ruff/mypy，并记录 `findmnt` 文件系统类型。WSL1/DrvFS 只算
跨平台工程证据，不是 Linux/ext4 Gate。不得机械运行全仓测试；若公共 `RecoveryResult` 演进导致直接消费者
fixture 必须适配，先报告精确文件和原因，由主 Agent 扩白名单。

## 11. 停止条件与通过条件

出现以下任一情况立即停止并回主 Agent 重冻：

- 必须改变 risk 经济规则、planner/market/account/domain schema；
- 必须认可或迁移 legacy formal rows；
- 需要创建 formal root/独立 anchor、注册/启动 soak；
- 需求变成 fresh 重跑 `evaluate_pretrade`，但完整 provenance 尚未另行冻结；
- 要求本包抵御整套合法 SQLite closure 协调替换，却没有独立物理 trust anchor 合同。

通过条件：实现自测绿、全新独立初验明确 PASS、主 Agent 复核 atomic staging、recovery identity、legacy fail-closed
和异常边界后，才解锁 B2A2。即使通过，仍只是 development 工程合同；RUN-0B2 生产装配、P7 exact completeness、
WSL2/ext4、正式 runner/scheduler 与 28 天 soak 均保持开放，M4 状态继续 `WAITING_FOR_SOAK_EVIDENCE`。

## 12. R2：RecoveryResult 语义闭包、replay scope 与 retry 边界

R1 实现的统一 ORDER/CANCEL transition journal 与完整双平台回归成立，但全新独立初验新增三个阻断。

### 12.1 失败闭环

1. **额外 receipt whole-rehash 被低层构造器接受。** 在合法 `RecoveryResult` 后追加一条 canonical extra ORDER
   receipt 并重算 outer `recovery_id`，`__post_init__` 只验证 receipt 自链，不验证与 commands/cancels 的
   exact ownership，结果从 1 条扩为 2 条仍构造成功。规则：公共 verified result 自身必须证明语义闭包，不能
   只依赖 `recover_local_state()` 的调用顺序。最小复现与新增测试必须断言 extra/missing/duplicate/cross-plan/
   cross-kind receipt 即使全量重算自哈希与 outer id也拒绝。
2. **ORDER exact replay 未绑定 counter scope。** 把既有 ORDER receipt 重签到 `other-scope:<session>`，保持
   decision/plan/command自洽，`plan_and_stage()` 仍返回 `replayed=True`；正式 recovery 稍后才失败。规则：服务
   replay 边界必须 fresh 绑定当前 `risk_counter_scope:session_date`，并验证 retained global/per-key chain 与当前
   counter tail，不能把错误留给后续恢复。CANCEL replay 同规则，必须一并覆盖。
3. **cancel staging 吞掉可重试 busy。** 独立 SQLite writer lock 触发 `TX_BUSY` 时，`stage_cancel()` 将其翻译为
   `CANCEL_STAGE_FAILED`。规则：SQLite busy/transaction failure 保持既有 retryable store/service边界，不得误译
   为不可重试 staging invalid。

### 12.2 最小返工

- 抽取无 IO 的 recovery receipt semantic verifier，供 `RecoveryResult.__post_init__` 与
  `recover_local_state()` 共用。它除 canonical/global sequence外，还必须验证 per-key predecessor/projected
  counter chain、ORDER command exact一次归属及 plan/intent有序闭包、CANCEL exact一次归属及 target command；
  空本地状态只能配空 receipt。构造器没有 stored counter row时不伪造 final-store证明，但必须完成其持有字段可
  证明的全部 exact closure。
- `plan_and_stage()` 在检查 existing stage前先派生 expected counter key；ORDER/CANCEL exact replay 均把
  expected key传入 receipt verifier。服务必须读取 retained receipt chain，fresh验证 global sequence、previous
  与每-key predecessor/projected连续性，并验证当前 daily counter row等于该 key最后 projected；target receipt
  不要求是全局/该key tail，因此旧plan在后续合法 transition后仍可 exact replay。
- same plan/cancel receipt 的 kind、subject、expected key、decision、commands/policy、private stage/cancel row
  必须 exact；异scope即使全量重签也在返回 replay前拒绝。
- 精确捕获 store busy/transaction retryable异常并在离开 active `except` 后保留原稳定 retry code；仅真实
  canonical/closure drift映射 invalid。不得用宽 `except` 将 `TX_BUSY` 改写为 `CANCEL_STAGE_FAILED`。

### 12.3 新增测试与通过条件

- `RecoveryResult` extra/missing/duplicate/swap/cross-plan/cross-kind receipt，完整重编码并重算 outer id仍拒绝；
- ORDER 与 CANCEL replay 分别做 wrong key whole-rehash、global/per-key chain断裂、target非tail但后续链合法；
- 当前 counter tail 漂移、legacy缺receipt、mixed `ORDER→CANCEL→ORDER` exact replay；
- 独立 SQLite writer lock 下 order/cancel direct service均保留 retry code，零新增receipt/counter/command/cancel；
- hostile verifier/store异常仍固定码、cause/context None，无path/SQL/TOKEN。

R2 只修改 B2A1 原白名单生产/测试及唯一R2交付报告；不改 P7/soak/CLI/broker/runtime。完成后必须由另一
全新独立上下文复验，R1 reviewer不得兼任实现者或R2 reviewer。
