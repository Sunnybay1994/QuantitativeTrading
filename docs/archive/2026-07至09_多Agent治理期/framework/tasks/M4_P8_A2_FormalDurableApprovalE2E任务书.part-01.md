# M4 P8 A2：Formal Durable Approval E2E 任务书

日期：2026-08-25<br>
状态：任务合同已冻结；等待外部实现 Agent<br>
exact base：`7fe836dcfbd841c5473057d3f6e222a6081ae3fa`<br>
branch：`codex/m4-a2-formal-approval-flow`<br>
worktree：`artifacts/dev_worktrees/m4-a2-formal-approval-flow`<br>
资源：`STATIC_ONLY`；Python、pytest、Ruff、mypy、cold import、SQLite probe 与真实 I/O 均须另行授权

## 1. 目标与非目标

本包把已合流的 A1 `HMAC_SHA256_CREDENTIAL_V1` receipt/store substrate 接入 formal PAPER operator：

1. operator 对 fresh `approve` challenge 确认后，由受控 credential capability 生成真实
   `VerifiedApprovalReceipt`；
2. service 在同一 `BEGIN IMMEDIATE` 事务内证明 pre-state recovery identity、先持久化 approval，再完成
   既有 risk/stage/command/outbox/ledger 闭包；
3. `manual_approval=true` 只有 exact verified approval 才允许 PAPER command；无 approval 继续零 command；
4. approved zero-intent/no-command 仍形成 durable approval + ORDER risk/stage closure，exact retry 不产生第二次经济影响。

本包只 stage，不 submit；不启动真实 PAPER，不接 scheduler/soak，不实现 shared session-close barrier、credential
store、外部 key registry、环境变量读取、PAPER_CANDIDATE/opening-facts 生成、A2 之后的 submit 或 28 日计时。
不声称关闭 UA-M4-006/007、正式 PAPER Gate 或 Linux Gate。

## 2. 权威前置与不变量

- A1 权威 API：`quant.execution.approval` 的 canonical receipt、credential 验签、
  `VerifiedApprovalReceipt` 与唯一 store hand-off；`ExecutionRepository.put_verified_approval_receipt`
  是唯一持久化入口。
- 当前 challenge SSOT：`quant.execution.cli` 的 `m4-paper-cli-challenge-v1`。
- 当前 recovery SSOT：`quant.execution.reconcile.RecoveryResult` 与其唯一 canonical identity 算法。
- 当前 risk/stage SSOT：`evaluate_pretrade`、`ExecutionService.plan_and_stage` 及既有 ORDER risk receipt、
  execution stage、outbox、ledger closure。
- `manual_approval=true`、`auto_trade=false` 保持正式策略配置；禁止通过改配置或 caller bool 绕过。
- approval receipt 不进入 `RecoveryResult.recovery_id`，本包不得改变这一既有身份语义。
- secret 不得进入 Git、配置、CLI 文本、composition、SQLite、receipt wire、repr、日志、异常或报告。

## 3. 唯一写白名单

实现 Agent 只可写以下 15 个路径：

1. `src/quant/execution/approval_flow.py`（新）
2. `src/quant/execution/cli_ports.py`
3. `src/quant/execution/cli.py`
4. `src/quant/execution/reconcile.py`
5. `src/quant/execution/service.py`
6. `src/quant/execution/risk.py`
7. `src/quant/execution/paper_formal_daily.py`
8. `tests/unit/test_approval_flow.py`（新）
9. `tests/unit/test_execution_cli.py`
10. `tests/unit/test_reconcile.py`
11. `tests/unit/test_execution_service.py`
12. `tests/unit/test_pretrade_risk.py`
13. `tests/unit/test_paper_formal_daily.py`
14. `docs/framework/tasks/M4_P8_A2_FormalDurableApprovalE2E任务书.md`（本文件）
15. `docs/framework/deliveries/M4_P8_A2_FormalDurableApprovalE2E交付报告.md`（新）

独立初验 Agent 只读以上 implementation 路径，唯一可写：
`docs/framework/reviews/M4_P8_A2_FormalDurableApprovalE2E独立初验报告.md`。

禁止修改 `approval.py`、`store.py`、migration、config、任何 `__init__.py`、roadmap、README、共享
SSOT、soak/runtime、broker/gateway 实现。若 A1 public API 或现有事务不能闭包，立即 STOP 申请扩围，不用
private store/SQLite 旁路。

## 4. Credential 与签发合同

`approval_flow.py` 提供最小具体 capability 与窄 factory/request API：

- factory 只接受 caller 显式提供的 bytes-like secret、opaque credential id、trusted expected operator id 与
  exact session date；返回的 capability 必须是 exact 内部受控类型，不能由 Protocol、bool、raw
  `ApprovalReceipt` 或普通 dataclass 冒充；
- capability 的 secret 字段不参与 repr/equality，任何错误都只返回稳定脱敏 code；
- receipt 签发只接受 exact canonical approve challenge：schema/action/mode、唯一 plan subject、
  `store_recovery_id`、排序 source identities、issued/expires 均须重新证明；
- session date 由 formal daily 的既有 `session_date` 参数提供，并与
  `planning.market.session_date`、trusted expected session date 交叉验证；不得从 wall clock 或 receipt
  自述推导；
- trusted expected operator id 必须与 capability 内 operator identity 一致，不能把 caller 临时 label 当信任锚；
- confirm 成功前不得调用 capability、派生 nonce 或产生 receipt；
- `issued_at` 精确取 challenge issued-at；nonce 使用 credential 私有 HMAC，绑定独立 domain 与 canonical
  challenge identity。exact challenge + exact credential 必须确定性生成同一 canonical receipt，支持 exact retry；
- 当前时间必须位于 challenge 的 UTC issued/expires 窗口，wrong bucket、过期、future 或非 canonical 时间拒绝。

诚实边界：A2 没有 credential store 或外部 key registry。首次注入的 capability 本身就是本次 credential
authority，系统不能独立判断“首次 secret 是否是预期 secret”。wrong-secret 反例只适用于已有 receipt 的重新验签、
同 business key 冲突或与另一 trusted capability 的不一致；不得虚构首次 key 真实性 Gate。

## 5. CLI / formal daily 合同

- `CliDependencies` 增加可缺省的 approval capability、trusted expected operator id 和 trusted expected
  session date；非 approve 动作保持既有构造与行为。
- `approve` 仍先执行 fresh recovery、target/planning load、plan 与 challenge；只有 exact confirmation
  通过后才调用 capability。
- fresh source identities 必须与 challenge 及 receipt 的 canonical digest 一致；plan、source、recovery、
  operator、session、challenge 或 time bucket 漂移，在 approval/risk/command/ledger 写入前 fail closed。
- `paper_formal_daily` 只传入显式 capability 与 trusted operator/session，不读取 secret，不从 config/env/store
  恢复 authority。inspect/plan/reconcile 等无需 capability；approve 缺 capability 必须稳定失败。
- successful approve 输出只引用 receipt/plan 等非敏感 identity；不得输出 secret、tag 以外的派生 key 材料或
  capability repr。

## 6. 唯一 recovery 与原子事务合同

在 `reconcile.py` 提炼唯一公开窄入口：

`recover_repository_state(repo: ExecutionRepository) -> RecoveryResult`

- 该入口消费调用方已开启事务的 repository，不自行 begin/commit/rollback；
- `recover_local_state(store)` 保持公共行为、wire/identity 与失败 code 不变，只作为 transaction wrapper 调用
  新入口；
- 禁止复制、重写或旁路第二套 recovery digest；现有 approval rows 仍不进入 RecoveryResult identity。

`ExecutionService.plan_and_stage(..., approval: VerifiedApprovalReceipt | None = None)` 保持缺省兼容。带 approval
时必须在其现有唯一 `BEGIN IMMEDIATE` 事务内按以下顺序：

1. fresh build plan，并验证 approval exact type/module proof、plan id、session date、challenge/source binding；
2. 调用 `recover_repository_state(repo)` 得到 current economic recovery；
3. 首次应用只接受
   `current.recovery_id == receipt.store_recovery_identity`，且不存在同 plan/session/action business-key receipt；
4. 先调用唯一 `put_verified_approval_receipt`，再执行既有 risk、ORDER receipt、counter、stage、command、
   outbox 与 ledger 写；
5. 任一异常必须回滚整个事务，不能残留孤立 approval；
6. 若 exact receipt 已存在，只能在 raw canonical bytes与全部 indexes exact 相等，且 execution stage、ORDER risk
   receipt、counter、command/outbox/ledger closure 全部经既有 verifier 证明完整时返回 `replayed=True`；
7. existing receipt 但 stage 缺失、部分闭包、identity/index/payload 漂移，一律 fail closed，不得“补完”孤儿；
8. same plan/session/action 的不同 receipt、nonce 冲突或另一个 credential/operator receipt 均拒绝。

## 7. Risk 与 no-op 合同

- `evaluate_pretrade(..., approval: VerifiedApprovalReceipt | None = None)` 保持原调用默认语义。
- `manual_approval=true` 且 PAPER 时，只有 A1 真实 verified hand-off 且 exact plan/session 匹配才可把既有
  approved intents 转换为 PAPER commands；不得接受 bool、raw receipt、caller verified 标志或 fake subclass。
- 无 approval 继续 `MANUAL_APPROVAL_REQUIRED` 且零 command；SHADOW 即使有 receipt 也永远零 command。
- `auto_trade`、sell-only、frozen、snapshot/data gate、仓位/金额/频率/费用等既有规则不放宽；approval 只能
  解锁 manual gate，不能把被其他规则拒绝的 intent 变成 command。
- zero-intent/no-command approval 仍持久化 approval，并形成既有 ORDER risk receipt 与 execution stage
  semantic closure；gateway call 为 0。exact receipt replay 不新增 receipt、counter、ledger、outbox 或经济影响。
- 带 command 只 stage/outbox，绝不 submit；`paper-submit` 仍需独立 challenge。

## 8. 必须新增的反例

至少覆盖：

1. fake capability、bool、raw `ApprovalReceipt`、伪 Protocol/subclass/object-new hand-off 拒绝；
2. operator/session/plan/source/challenge/bucket/expiry 漂移；
3. confirm 前配置 fail-on-call capability，证明未调用；
4. challenge 后、service 事务前的 recovery drift，approval/risk/command/ledger 零残留；
5. same plan 的不同 receipt、不同 operator/credential/nonce business conflict；
6. exact receipt 已存在但 stage、ORDER risk、counter、command/outbox 或 ledger 任一缺失/篡改；
7. risk/stage 中途失败后事务 rollback，不残留 approval；
8. manual true 无 receipt 继续零命令；SHADOW + receipt 仍零命令；
9. zero-command 首次闭包与 exact replay；gateway 调用始终为 0；
10. 带命令 approval 只 stage、不 submit；其他 risk rule 拒绝不被 approval 覆盖；
11. `recover_local_state` 与 `recover_repository_state` 对同一 fixture 的 RecoveryResult/identity 等价；
12. 首次 capability authority 的诚实边界，以及已有 receipt wrong-secret reverify/conflict。

独立初验必须增加实现者未使用的对抗反例，至少挑战：孤儿 exact approval、copy/deepcopy/pickle/replace
capability、transaction drift、no-op replay 与 secret 泄漏面。

## 9. 失败语义

沿用现有稳定错误映射；新增内部错误必须脱敏、确定且能区分：

- credential/capability invalid；
- challenge/confirmation/source/plan/session/recovery drift；
- approval business/idempotency conflict；
- orphan/partial stage closure；
- risk blocked；
- retryable store busy/write failure。

不得在错误文本中包含 secret、HMAC key material、完整 capability repr 或 SQLite raw row。CLI 继续把 drift
映射为 confirmation drift、risk 为 risk blocked、busy/write 为 retry required；未知内部异常 fail closed。

## 10. 实现、初验与验证流程

1. 主 Agent 冻结本任务书。
2. 全新外部 Cursor 实现会话只按 exact15 静态实现，模型使用项目规则规定的
   `cursor-grok-4.5-high`；当前不得运行 Python/pytest/Ruff/mypy/cold/SQLite/network/PAPER，也不得提交。
3. 经理只读核 exact15/scope/diff/合同；发现 P0/P1 交回同一实现会话最小返工。
4. 另一个全新外部 Cursor 会话独立静态初验，只写唯一 review 报告；不修改实现。
5. 初验通过后，经理向中央申请 CPU8–11/0xF00，按 focused approval-flow → CLI/service/risk/reconcile/formal
   daily → Ruff exact production/tests → mypy production → cold imports → exact15/scope/temp/process residue
   串行验证。Windows 为开发验收，不冒充 Linux Gate。
6. 主验问题重新进入同一“实现返工 → 独立复验”闭环；全绿后 exact paths 安全提交，由中央合流/回归/退休。

## 11. 通过与停止条件

通过条件：

- exact15 无越界，任务/交付/初验记录诚实；
- receipt authority、事务 pre-state fence、approval-first atomicity、manual gate、zero-command 与 exact replay
  均有 focused 测试和独立对抗证据；
- A1/store/schema/config/submit/soak/shared barrier 未被越界修改；
- 定向 pytest、Ruff、mypy、cold、scope/diff/temp/process 检查实际通过；
- 无 secret 泄漏、真实 PAPER、broker submit、网络或未授权产物。

立即停止：

- 需要修改 `approval.py`、`store.py`、migration/schema/config/`__init__` 或任何白名单外路径；
- 无法在同一 transaction 复用唯一 recovery 算法；
- 必须用 raw SQLite/private store helper、caller bool 或 `manual_approval=false` 才能工作；
- 需要 credential store/key registry、真实 secret、PAPER/submit/soak/network；
- exact base/branch/worktree 漂移、出现第二 writer 或共享资源冲突；
- 首个获批 focused 检查失败时按资源合同 STOP，不自行扩围或重复。

## 12. REWORK1：来源闭包、CLI replay 与孤儿闭包返工

状态：经理静态核对未通过；独立初验尚未派发。<br>
返工仍限 exact15，保持 `STATIC_ONLY`，不得运行 Python 或修改 review 报告。

### F1：approve source identity 被弱化

- **现象：** 首轮实现把 approve challenge 从既有 `_planning_sources(targets, planning)` 改成只含
  plan 可推导字段的新集合，删除了 `target_receipt_identity` 与 `target_verification_identity`。
- **根因：** 为方便 service 内复算 source digest，错误地用较弱的新来源集合替换了既有 CLI challenge 语义。
- **规则：** approve 必须保留既有 canonical planning-source 集合，尤其是 target receipt 与 target verifier
  identity。service 可新增显式 `approval_source_identities` 参数：必须与 receipt digest exact 一致，并对
  account/market/planner/trading 等可推导子集逐项复算；不得静默删除 service 不能自行推导的已验 target 来源。
- **最小复现：** 同一 target values/plan，但替换 target receipt 或 verification identity；challenge 与 receipt
  必须漂移，旧实现不会漂移。
- **测试：** CLI challenge 明确断言完整既有 source keys；分别漂移 target receipt 与 target verification；
  service 拒绝 source mapping/digest/可推导子集不一致。
- **通过条件：** `plan` 与 `approve` 的既有 planning-source 语义不退化；receipt/service exact closure
  同时成立。

### F2：fresh post-completion approve 丢失既有幂等 replay

- **现象：** 首轮实现把原测试的 fresh post-completion approve 从
  `APPROVAL_STAGED_REPLAY`/exit 0 改成 `CONFIRMATION_DRIFT`/exit 20。
- **根因：** 每次 fresh challenge 都按新 recovery identity 签发不同 receipt，却没有在已存在 business receipt
  时用当前 credential 对 stored canonical payload 重新验签并交给 service 的 exact-receipt replay 分支。
- **规则：** old confirmation 在状态变化后仍须 drift；但 operator 对 fresh post-state challenge 再确认时，
  CLI 应查询 plan/session 的唯一 stored raw approval，用同一 capability 重新 HMAC 验签、交叉验证
  operator/session/source，再把该 exact `VerifiedApprovalReceipt` 交给 service。不得仅凭 decode/store row
  恢复信任；不得新签第二 receipt。
- **最小复现：** 首次 approve 成功后重新获取 fresh challenge 并确认；必须 exit 0、同 receipt id、
  `APPROVAL_STAGED_REPLAY`、无第二 command/counter/risk/ledger/outbox 影响。
- **测试：** 恢复原 CLI/formal-daily fresh replay 断言；wrong capability 对 stored receipt 重新验签失败；
  stored raw/index/source/operator/session tamper fail closed。
- **通过条件：** 既有 CLI 幂等行为恢复，同时 exact stored receipt 必须经 credential fresh reverify。

### F3：existing receipt 的 command/outbox/ledger 闭包不完整

- **现象：** 首轮 replay 只调用 stage decode、risk-chain/counter 与 ledger context/checkpoint；没有逐 command
  证明 order aggregate、outbox raw 与 outbox delivery 的 exact identity/payload/link。
- **根因：** 复用了既有 replay helpers，但未补齐本任务书明确要求的完整 stage/risk/counter/command/
  aggregate/outbox/delivery/ledger join。
- **规则：** exact approval replay 必须逐 stage command 证明 command row、aggregate、outbox、delivery、
  ledger context；全局 checkpoint、ORDER receipt 与 projected counter 也必须 exact。delivery 可以处于既有合法
  状态，但 key/command/identity/payload 必须一致。任一缺失或篡改都是 orphan/partial closure，不能补完。
- **最小复现：** 保留 exact approval 与 stage，分别删除/篡改 ORDER receipt、counter、command、aggregate、
  outbox、delivery、ledger context 或 checkpoint；每项都必须在任何新写前 fail closed。
- **测试：** 参数化至少覆盖上述各类；验证失败后 store bytes/row counts 不变。
- **通过条件：** existing receipt 只有完整 economic/storage closure 才返回 replay。

### F4：强制 no-op、rollback 与 formal composition 证据缺失

- **现象：** 首轮只有带 command 的首次/replay 测试；没有 approved zero-intent/no-command durable closure，
  没有 approval insert 后 stage failure 的整事务 rollback；所谓 fail-on-call 测试直接调用 issue API，不能证明
  CLI confirm 前不碰 capability；formal-daily 也没有证明新参数实际透传。
- **规则：**
  1. approved zero-intent/no-command 必须写 approval + ORDER risk/stage + checkpoint/counter，command/outbox/
     gateway 为零，并支持 same receipt exact replay；
  2. 在 approval insert 之后注入 ledger/risk/stage failure，事务结束后 approval/stage/risk/counter/ledger/
     command/outbox 均不得残留；
  3. CLI 无 confirm 时使用 fail-on-call capability 并证明 untouched；confirm 后才允许触发 capability；
  4. formal daily builder/operator 必须把 capability、trusted operator、trusted session exact 传给
     `CliDependencies`，session mismatch fail closed。
- **测试：** 为上述四项分别新增行为测试；不得以宽泛 `raises(Exception)` 代替稳定错误/状态断言。
- **通过条件：** no-op/replay/rollback/confirm-order/formal forwarding 均有明确、窄且可执行的断言。

### F5：最小变更与时钟一致性

- 恢复首轮在 `test_pretrade_risk.py` 删除的两个既有尾部表达式，避免本任务顺手清理无关历史字节。
- CLI 一次 approve 调用只读取一次 trusted clock，并将同一 `now` 用于 challenge 与 capability issuance，
  禁止边界跨越由多次 clock read 造成不可解释漂移。
- 交付报告追加 REWORK1 的“现象—根因—规则—最小复现—新增测试—通过条件”；不得改写首轮历史。

## 13. VALIDATION1 STOP 与 REWORK2

状态：identity preflight 通过；focused 六文件测试 `200 passed / 12 failed` 后按资源合同 STOP；Ruff、mypy、
cold import 未运行。fresh basetemp 与空 `.tmp` 已清理，未见 0xF00 Python 残留。独立初验此前的
`REVIEW_PASS` 仅为静态结论，已被本次运行证据推翻，返工后必须重新独立复验。

返工保持原实现/测试/任务/交付路径 `STATIC_ONLY`；下述 F8 涉及现有 `risk_wire.py` 公共语义，当前不在
exact15，必须先由中央裁定是否扩白名单，未经批准不得修改。

### F6：capability Guard 与 source drift 稳定错误测试不符合真实边界

- **现象：** `test_confirm_gate_fail_on_call_capability_is_unused_until_issue` 期望错误类型 Guard 的
  `__getattr__` 被访问，但生产入口在 exact-type guard 即拒绝，因此 `touched` 正确保持 `False`；source
  receipt 漂移测试实际返回 A1 的 `APPROVAL_SOURCE_IDENTITIES_INVALID`，而测试期待
  `APPROVAL_SOURCE_DRIFT`。
- **根因：** 前者混淆“确认前不得触碰 capability”和“issue API 必须触碰伪 capability”；后者没有在
  A2 reverify 边界把底层 source canonical/signature 错误归一为业务 source drift。
- **规则：** exact-type guard 应在不读取伪对象属性的情况下拒绝；CLI 无 confirm 的 fail-on-call 测试才是
  confirm 顺序证据。stored receipt 以不同 full source map 重验签时，对外必须稳定为
  `APPROVAL_SOURCE_DRIFT`，不得泄漏底层 codec 分类或落入 internal exit。
- **最小复现：** 传入实现 `__getattr__` 的伪 capability；以及把已签 payload 用另一个合法 exact6 source map
  重验签。
- **新增测试/通过条件：** Guard 保持 untouched 且稳定 capability error；source drift 稳定映射为
  `APPROVAL_SOURCE_DRIFT`，CLI 映射为 drift 类退出。

### F7：orphan 注入测试违反 SQLite FK/WAL 语义

- **现象：** command/outbox 删除受 FK 正确拒绝；其余删除后直接比较主数据库文件 bytes，在 WAL 模式下
  bytes 可能不变，造成 8 个参数化用例中的测试自身失败。
- **根因：** 把物理主文件 bytes 当作事务后逻辑状态，并用违反现有 FK 的删除方式制造孤儿。
- **规则：** 测试应通过不破坏 FK 的 payload/index 篡改，或按依赖顺序删除；以事务内 canonical row
  snapshot/count/payload 比较证明 replay 失败没有补写，不能依赖 WAL 主文件 bytes 变化。
- **最小复现：** `DELETE commands`/`DELETE outbox` 触发 FK；合法删除其他行后
  `database.read_bytes()` 前后仍相同。
- **新增测试/通过条件：** 每类孤儿注入先证明目标逻辑行确已缺失/篡改，再调用 replay，稳定 fail closed，
  失败后同一逻辑 snapshot exact 不变；不得关闭生产 FK 或放宽 store。

### F8：zero-command ORDER risk receipt 与既有全局 semantic verifier 冲突

- **现象：** zero-command 首次写入成功，但 exact replay 在 `_verify_replay_risk_chain` 调用既有
  `verify_risk_receipt_semantic_closure` 时返回 `SERVICE_RISK_RECEIPT_INVALID`。
- **根因：** `risk_wire.py` 当前明确拒绝“存在 ORDER receipt 但 command_ids 为空”，而 A2 中 approved
  no-command 又被中央合同要求持久化 ORDER risk/stage closure；这不是单纯测试问题。
- **规则：** 必须为受证明的 zero-command ORDER decision 定义窄、可重放的 semantic closure，同时保持
  sequence/previous receipt、counter predecessor/projected identity、decision bytes、plan/stage/approval join
  全部 fail closed；不得在 service 中复制第二套通用 risk-chain verifier，也不得放宽普通无主 receipt。
- **停止/扩围条件：** 优先申请把 `src/quant/execution/risk_wire.py` 与其既有定向测试文件加入白名单，扩展
  唯一 semantic verifier；中央未批准前不得用 skip `_verify_replay_risk_chain` 或私有复制绕过。
- **新增测试/通过条件：** zero-command approved ORDER receipt 首次与 exact replay 通过；无 approval/stage
  归属的空 command receipt、错误 counter/chain/decision 继续拒绝；既有 command/cancel closure 不回归。

### F9：pretrade 直测构造了非 canonical/值重复的 A1 source map

- **现象：** `test_verified_approval_unlocks_manual_gate_for_paper_only` 在 risk 调用前即被 A1
  `canonical_source_identities_digest` 拒绝。
- **根因：** fixture 使用未排序且可能值重复的 plan 派生 map；该测试只需构造真实
  `VerifiedApprovalReceipt`，不应伪造不满足 A1 canonical contract 的输入。
- **规则：** 使用排序、key/value 均合法且 value 唯一的最小 source map（或现有合法 helper）构造 receipt；
  不修改 A1 canonical 规则。
- **新增测试/通过条件：** PAPER manual+verified 解锁、manual 无 receipt 拒绝、SHADOW receipt 零命令及
  bool/raw 拒绝均进入 risk body 并按稳定断言通过。

### F10：资源 carrier 收口

- **现象：** finally 试图把短命验证 PowerShell 的 affinity 恢复为
  `0xFFFFFFFFFFFFFFFF`，Windows 对当前 CPU 拓扑返回参数错误；该 shell 随命令退出，未留下 Python，
  basetemp 已在异常前清理。
- **规则：** 后续 carrier 只需在 `finally` 精确清理临时目录；短命 shell 自然退出即释放 affinity，或在启动
  前保存原 `ProcessorAffinity` 并恢复原值，禁止猜全核 bitmask。
- **通过条件：** 验证终态无 0xF00 Python、无本包 basetemp；carrier cleanup 不掩盖首个业务失败。

## 14. REWORK2 中央裁定：唯一 stage codec 与审批归属的 zero ORDER

状态：`REWORK2_APPROVED / STATIC_ONLY`。实现白名单由 exact15 精确扩为 exact17，新增：

16. `src/quant/execution/risk_wire.py`
17. `tests/unit/test_risk_wire.py`

独立初验仍只允许写原唯一 review 报告；禁止扩 `store.py`、schema、migration、config、`__init__.py` 或其他路径。

### 14.1 F6 / F7 / F9 冻结修复

- exact-type fake capability 必须在不触碰其 `__getattr__` 的情况下拒绝；CLI confirm 前 untouched 证据保持。
- A2 stored receipt 用不匹配 source map 重验签时，对外稳定归一为 `APPROVAL_SOURCE_DRIFT`。
- orphan/rollback 测试不得破坏 FK 或比较 WAL 主数据库文件 bytes；使用合法 payload/index tamper 与事务内
  logical snapshot，证明 replay 失败前后状态 exact 不变。
- risk 直测 source fixture 使用 stable-sorted keys 与 unique values，保持 A1 canonical contract 不变。

### 14.2 唯一 canonical stage codec

- `risk_wire.py` 新增唯一公共 canonical stage 编码入口，命名遵循现有风格；同时接受 `RiskDecision` 与
  `DurableOrderRiskDecision`，输出必须与当前 `service._encode_stage` 的
  `m4-execution-stage-v1` bytes 逐字节一致。
- `service._encode_stage` 必须委托该入口；禁止复制第三套 stage 编码或改变 schema、key、排序、数字语义。

### 14.3 唯一 risk semantic verifier 的 zero ORDER 合同

`verify_risk_receipt_semantic_closure` 新增 keyword-only：

`allowed_zero_order_subject_ids: frozenset[str] = frozenset()`。

默认空，所有既有 caller 行为不变。zero ORDER 仅在以下全部成立时允许：

1. `receipt.subject_id == decision.plan_id`，且 subject 位于显式 allow-set；
2. `decision.command_ids == ()`、`approved_intent_ids == ()`、`accepted is True`、
   `requires_manual_approval is False`；
3. 全局 sequence/previous、per-counter predecessor/projected identity、wire roundtrip 继续完整验证；
4. allow-set 必须与实际观察并合法消费的 zero subject 集合 exact equality；多余、遗漏或错误 subject 均拒绝。

普通无主 zero receipt 继续拒绝；nonzero ORDER 与 CANCEL 语义不得改变。

### 14.4 service / reconcile 上下文闭包

service 与 reconcile 构造 allow-set 前，对每个 zero receipt 必须逐项证明：

- approval row canonical raw/index/plan/session/action 闭合；reconcile 只证明持久化结构归属，不声称 HMAC
  credential 仍已验证；
- execution stage 存在，key/identity 正确，其 payload 与 receipt 中
  `DurableOrderRiskDecision` 经 §14.2 唯一 encoder 生成的 bytes 完全一致；
- zero receipt 的 subject/plan 闭合。

service live replay 还必须保持当前 `VerifiedApprovalReceipt` 与 stored approval 的逐字段/bytes exact 验证。
fresh zero-intent 可在同一事务中使用 live approval 与即将写入的 exact stage 建立闭包；approval/risk/stage
任一异常必须整事务 rollback。

formal approval service 持久化路径必须在任何 approval/risk/stage 写入前拒绝非 `PAPER` mode。独立
`evaluate_pretrade` 的 SHADOW + verified receipt 行为仍是零命令，但不得持久化 SHADOW zero ORDER receipt。
reporting/soak 等没有上下文 allow-set 的 caller 继续按默认空集合拒绝 zero receipt。

### 14.5 REWORK2 强制反例与通过条件

至少覆盖：

