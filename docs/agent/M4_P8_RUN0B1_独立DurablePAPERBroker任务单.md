# M4-P8-RUN-0B1：独立 Durable PAPER Broker 任务单

日期：2026-08-09  
状态：**R3 实现、独立复验与主 Agent 验收 PASS；仅限 development durable broker 工程合同，B1 policy 不得放宽为 formal，B2D/formal store/gateway/service/runner 与 M4 Gate 保持开放**（见 [`M4_P8_RUN0B1_R3_独立DurablePAPERBroker主Agent最终验收报告.md`](M4_P8_RUN0B1_R3_独立DurablePAPERBroker主Agent最终验收报告.md)）  
性质：正式 runtime 前置工程合同；本包不注册、不启动 28 天 soak，不关闭 M4 Gate

## 1. 背景与目标

P4-P8 的服务、CLI、恢复、对账、报告和 soak evidence 已完成工程合同，但当前 `PaperGateway` 是确定性的
进程内 adapter。它只接受 `recovered_commands`，没有独立持久化的 broker 账户、订单、事件和 EOD snapshot。
若正式 runner 直接从 OMS store 构造“broker 证据”，reconciliation 会成为同源自比较，不能证明差异。

本包新增一个与 OMS store 物理、逻辑和身份均独立的 durable PAPER broker：

- 稳定、一次性、非秘密的 PAPER account descriptor；
- 独立 SQLite broker journal/state store；
- 实现现有 `PaperGatewayFactory` 与 `BrokerSnapshotPort` 的生产候选 adapter；
- crash/restart 后 exact idempotency、UNKNOWN/partial callback 恢复和 EOD finality；
- broker evidence fresh 由 broker store 重建，而不是从 OMS 投影。

## 2. 明确非目标

- 不实现 TargetLoader、PlanningLoader、正式 fee/FX/rules registry 或 LedgerContextProvider；
- 不改变 P4-P8 现有 CLI/service/store/recovery/reconciliation/report/soak 语义；
- 不实现真实券商、QMT/MiniQMT、网络、token、账号或下单；
- 不注册 Task Scheduler，不创建正式 P8 evidence/anchor/runtime roots；
- 不把 Windows/DrvFS 开发验证表述为 WSL base/ext4 Gate；
- 不执行故障演练、不生成 `PAPER_REAL_TIME` manifest 或 Gate PASS。

## 3. 不变量

1. broker store 与 OMS store 必须是不同 resolved file、不同 store-instance identity，且根目录互不为祖先；
2. broker state 只能由 broker adapter 的事务日志重建，不能读取 OMS commands/events/ledger；
3. 相同 operation + attempt + canonical payload exact retry 幂等返回相同结果；不同 payload/attempt 不得覆盖；
4. 跨进程重启不重发已确定 SENT 操作，不把 UNKNOWN 猜成 SENT/NOT_SENT；
5. broker callback、订单观察、账户和 snapshot identity 都由包内 canonical codec fresh 重建；
6. EOD evidence 只有在该 session 所有已知操作达到 terminal/finality 且事务完成后才能标记
   `END_OF_DAY`；否则为非 final，不得供 P7/P8 append PASS；
7. 任何 store/path/schema/descriptor/policy identity 漂移均 fail closed，不能续用旧 gateway identity；
8. 所有公开异常稳定脱敏，`cause/context is None`，日志和 traceback 不包含路径、SQL、TOKEN 或 payload。

## 4. 稳定账户描述

新增冻结 `PaperAccountDescriptor`，至少包含：

- `schema_version = paper-account-v1`；
- `account_id`：包内计算，不是 `AccountSnapshot.snapshot_id`；
- `account_label`：非秘密、严格字符集；
- `created_at`：aware UTC，一次性；
- `base_currency`；
- exact initial `AccountSnapshot`；
- `initial_snapshot_identity`；
- descriptor identity。

`account_id` 必须绑定 descriptor version、label、created_at、base currency 和 initial snapshot canonical wire。
每日变化的账户 snapshot id 不得冒充稳定 account id。descriptor 必须以 canonical JSON 独占创建，已存在时
只允许 bytes-exact verify；不允许 overwrite、rename replacement、symlink/reparse 或复制 root 后继续同一 identity。

初始账户仅是本地 PAPER 资金/持仓，不含真实账号、凭据或 broker identifier。初始 snapshot 必须通过现有
`AccountSnapshot` 构造和 `build_account_snapshot_identity` fresh 重证。

## 5. Broker store

新增 `src/quant/execution/paper_broker_store.py`，建议公共类型：

- `PaperBrokerStoreError`；
- `PaperBrokerStoreDescriptor`；
- `PaperBrokerStore`；
- `build_paper_account_descriptor(...)`；
- `initialize_paper_broker_store(...)`；
- `open_verified_paper_broker_store(...)`。

### 5.1 路径与实例身份

- API 只接受 caller-selected absolute trusted root 与 relative SQLite filename；无 repo 内默认值；
- root 必须是 caller-created、真实目录；拒绝 symlink/reparse、文件替换和 root identity 漂移；
- SQLite file 与 canonical `store-instance.json` 独占创建；descriptor 绑定 resolved root identity、relative DB name、
  schema version、account id、policy identity、created_at、随机 instance nonce 和 descriptor digest；
- nonce 只用于区分物理实例，必须持久化；复制完整 root 后 resolved root identity 不同，fresh open 拒绝；
- 禁止 DB/descriptor 位于 repo `data/`、`data/legacy/`、G1 release/candidate/journal、OMS store、P8 evidence/
  anchor root。正式路径完整裁定留给 RUN-0C；本包测试使用系统临时目录。

Windows 必须拒绝 reparse point/共享 delete replacement；POSIX 必须使用 no-follow/dir-fd 或等价身份锚。
长事务前、首次写前和 commit 后 fresh 核对 root/file identity。

### 5.2 最小表与 canonical codec

SQLite 至少保存：

- schema/store/account/policy descriptor；
- submit/cancel operation 与 dispatch attempt、canonical request digest、certainty、状态；
- canonical command/cancel wire；
- canonical callback event wire 与严格 ordinal；
- broker order observation；
- cash/position/account snapshot state；
- session finality/checkpoint；
- append-only broker transaction sequence/hash chain。

不得 pickle、任意 import、任意 SQL payload 或 Python repr。所有 domain wire 采用 strict exact-key JSON codec，
decode 后必须调用现有领域构造器和 identity builder fresh 重证。未知字段、enum、Decimal、datetime、顺序、重复
或非 canonical bytes 均拒绝。

每个写事务必须 `BEGIN IMMEDIATE`、原子更新 state + append journal + checkpoint；commit/rollback/busy 被稳定
区分。不得将 transaction busy/failure 改写成 identity drift。SQLite durability 设置和锁语义需 Windows/Linux
兼容并测试；不依赖文件系统 rename 原子性发布 DB。

## 6. Durable gateway 与独立 snapshot port

新增 `src/quant/execution/gateways/paper_durable.py`：

- `DurablePaperGatewayFactory` 实现现有 `PaperGatewayFactory`；
- `DurablePaperGateway` 实现 submit/cancel transport；
- `DurablePaperBrokerSnapshotPort` 实现现有 `BrokerSnapshotPort`。

### 6.1 复用边界

允许复用当前 `PaperGateway` 的确定性 fill/cancel callback 计算核心，但必须把 operation fence、canonical
request、certainty、callbacks、broker state 与 transaction 先持久化，再向调用方返回 crossing 结果。不能先让
进程内 gateway 产生可见副作用，随后才 best-effort 写 DB。

factory `identity()` 只读 fresh 验证 store/account/policy descriptor并返回稳定 gateway identity；`open()` 返回
现有 `VerifiedPaperGateway`，其 verification identity 必须绑定 fresh store proof。调用方不能用任意 64hex 自报。

### 6.2 idempotency 与故障边界

- exact retry 相同 operation/attempt/payload：读取 retained result，不重复改变账户或生成新 event；
- 同 operation 同 attempt 不同 payload：terminal conflict；
- 旧 attempt：stale；未来 attempt 只能按现有 dispatch fence 规则处理；
- crash 点覆盖 intent 持久化前后、certainty 后、callbacks/state 后、commit 前后、返回前；
- UNKNOWN 必须 retained，重启后保持 UNKNOWN 且不重发；人工/恢复路径决定后才能产生新状态；
- callback event ids/order bytes-exact retained；duplicate callback 只返回同一 event，不二次记账；
- cancel late fill 与 final cancel 顺序遵循现有 `PaperGateway` 合同。

### 6.3 broker evidence

`query_and_verify(gateway_identity=...)` 必须在一个一致只读事务中从 broker DB fresh 重建：

- current `AccountSnapshot`；
- all relevant `BrokerOrderObservation`；
- canonical `ExecutionEvent`；
- `as_of`、`source_identity`、gateway identity；
- `BrokerSnapshotFinality`。

返回现有 `VerifiedBrokerEvidence`，verification identity 由现有 builder/fresh verifier计算；不能读取 OMS store。
hostile/损坏 DB、缺 journal link、账户与事件不闭合、hash-chain 漂移、非 terminal EOD 均 fail closed。

## 7. Policy identity

本包不冻结正式业务数值，但必须定义 `PaperBrokerPolicyDescriptor`，绑定：

- adapter/fill/fault policy version；
- `ExecutionCostSchedule` identity；
- `FxSnapshot` identity 或明确 none；
- deterministic clock/finality policy version；
- canonical descriptor digest。

开发 fixture 可以通过显式对象创建该 descriptor；正式 RUN-0B2 必须由版本化配置 loader 产生。未知/example/
development policy 不能被标为 formal。PAPER runtime 绝不需要 broker credential。

## 8. 风险与账本边界

本包只建立独立 broker state，不补 `RiskDecision` durable recovery 或生产 `LedgerContextProvider`。但 broker
store 不得声称风险已验真，也不得把 broker journal 当作 OMS ledger。RUN-0B2 必须单独补齐“每个实际 command
都有 retained verified RiskDecision”的闭包后，才可组装正式 runner。

## 9. 写入白名单

```text
src/quant/execution/paper_broker_store.py
src/quant/execution/gateways/paper_durable.py
src/quant/execution/gateways/__init__.py       # 仅安全惰性导出，必要时
tests/unit/test_paper_broker_store.py
tests/unit/test_paper_durable_gateway.py
docs/agent/M4_P8_RUN0B1_独立DurablePAPERBroker交付报告.md
```

若确需复用/提取 `paper.py` 的纯 callback 计算核心，必须先回报具体最小 diff 并由主 Agent 扩白名单；不得直接
重构已验收 P4-P8 路径。禁止改 `cli.py/cli_ports.py/service.py/store.py/reconcile.py/reporting/soak.py`、配置、
scripts、正式 artifacts/journal。

## 10. 必测反例

至少包括：

1. broker root 与 OMS root 相同/祖先、repo data/G1/P8 root、相对路径、symlink/reparse；
2. account/store/policy descriptor bytes、nonce、root identity、DB inode/file-id 漂移；
3. 完整 root 复制到另一物理路径后 fresh open；
4. 同 command exact retry，callback/event/account bytes 与首次完全相同且只记账一次；
5. 同 operation 同 attempt 不同 canonical payload；
6. UNKNOWN 跨重启不重发；
7. duplicate callback、partial fill、cancel late fill、final cancel；
8. 每个事务 crash 点和 independent SQLite writer lock；busy 保持 retry，真实 drift 才报 drift；
9. journal entry/state/checkpoint/account/event 任一增删改、whole-rehash、重复/乱序；
10. broker snapshot 与 OMS 无关：给出语义相反的 OMS fixture，不影响 broker evidence；
11. 非 terminal session 请求 END_OF_DAY；
12. hostile codec/SQLite/path异常固定错误、空 cause/context、traceback 无 marker；
13. Windows 与 WSL base 重启后 reopen/query smoke；
14. fresh process `import quant.execution.gateways.paper_durable` 无循环导入。

## 11. 验证

Windows：

```powershell
$env:PYTHONPATH='src'
D:\Miniforge3\python.exe -m pytest tests/unit/test_paper_broker_store.py tests/unit/test_paper_durable_gateway.py -q
D:\Miniforge3\python.exe -m ruff check <改动文件>
D:\Miniforge3\python.exe -m mypy <改动生产文件>
```

WSL base 对应定向 pytest/Ruff/mypy，并做 fresh process reopen。当前 `/mnt/f` 为 DrvFS，只是开发合同；正式
PAPER runtime 仍要求 WSL base + ext4，后续 RUN-0C 在任何正式 root 写入前强制探针。

## 12. 通过条件

- 独立 durable broker 在双平台开发测试下通过 exact idempotency、crash/restart、root identity、journal closure；
- `PaperGatewayFactory` 与 `BrokerSnapshotPort` 使用现有公共 ports，未建平行 CLI；
- broker evidence 不读取 OMS store并可暴露真实差异；
- 实现交付、全新上下文独立初验、主 Agent 终验均通过；
- 通过只解锁 RUN-0B2/C/D 生产装配，仍不得注册或启动 28 天 soak，状态保持
  `WAITING_FOR_SOAK_EVIDENCE`。

## 13. R2：formal 来源收缩、账户重放与并发 predecessor 闭包（2026-08-09）

R1 独立初验报告：`M4_P8_RUN0B1_独立DurablePAPERBroker独立初验报告.md`。结论 FAIL；既有双平台
16 项测试和 multi-session EOD 状态机通过，但不覆盖下列三个 P1 阻断。

### 13.1 失败闭环

1. **caller 自签 formal policy/gateway。** public builder 接受 `classification="formal"` 与任意
   `example-*` 版本；factory 又接受只提供同名属性/方法的 fake store，最终把 caller 指定的 64hex 变成
   `VerifiedPaperGateway`。根因是 development value builder 同时承担 formal capability 签发，factory 没有
   exact verified store proof。
2. **账户 whole-rehash 被接受。** 修改 canonical `account_state`，再用实现自身 `_state_digest()` 重算 DB 内
   checkpoint，fresh verify/evidence 均通过；资金变化没有 operation/event 支撑。根因是只验证 mutable rows 的
   自哈希，没有从 immutable initial snapshot 与严格有序 terminal callbacks 重放唯一账户/订单状态，也没有
   DB 外独立 retained append anchor。
3. **并发陈旧 predecessor 丢失更新。** 两个 submit 在写事务外读取同一账户，各自计算新账户后串行 commit；
   最终 retained 2 orders 但只有 1 position，fresh verify 仍通过。根因是 `BEGIN IMMEDIATE` 没覆盖 predecessor
   验证/状态 transition，也没有 checkpoint CAS。

上述分别违反 §6.1/§7 的 formal 来源边界、§3.5/§5.2/§6.3 的 evidence replay closure，以及 §5.2/§6.2
的原子 state transition。

### 13.2 R2 架构裁定

#### A. RUN-0B1 不签 formal policy

- public policy builder 只能返回 exact development policy value；删除 caller 的 `classification="formal"`
  分支，unknown/example/development 版本均不能产生任何 formal capability。
- RUN-0B1 不提供 generic formal policy signer。正式 policy exact capability 由 RUN-0B2 的版本化 config loader
  在 fresh 验证配置、cost/FX/rule effective date 后唯一产生；B1 测试不得用“formal”字符串冒充该前置。
- `DurablePaperGatewayFactory`、snapshot port 和 store opener 必须要求 exact `PaperBrokerStore` 实例，fresh 验证
  root/DB/account/policy/store descriptor 后从实际 store 重算 gateway identity；subclass、duck/fake、普通
  dataclass clone、caller 64hex 均拒绝。development store 可以返回现有 verified gateway 工程值，但不得被
  `VerifiedPaperRuntimeEnvironment` 或未来 formal runtime manifest 接受。

#### B. replay 为账户/订单 SSOT，并增加独立 retained anchor

- `initial-account.json` 保持 immutable。fresh verifier 必须从该 initial snapshot 起，按 canonical journal
  sequence 重建每个 command/cancel、callback/event、order terminal state、现金与持仓；重放结果必须与 retained
  `account_state`、orders、events bytes/identity exact 相等。账户不得作为独立可改写真值。
- 每次成功 state transition 还必须产生 DB 外、位于已锚 broker root 下的 append-only sequence anchor（固定
  relative 目录和十进制/定宽 sequence 名），以 exclusive create 绑定 predecessor anchor、operation identity、
  journal/state digest 与 store identity。exact retry复用同一 anchor；缺失可由同一已提交 transition精确补锚，
  不同 bytes、增删换序、跳号、复制 root、symlink/reparse 均拒绝。
- DB commit 与 anchor create 的 crash window必须显式恢复：commit 前失败无新状态/anchor；commit 后 anchor 前失败
  只允许从 DB 中唯一已提交 transition 补同一 anchor，不能重放 transport或二次记账。anchor 不冒充外部数字签名，
  但必须关闭任务冻结的同 root 下 DB whole-rehash/账户自哈希旁路。

#### C. predecessor 必须处于写事务/CAS 边界

- 优先在同一 `BEGIN IMMEDIATE` 内读取 fresh predecessor、验证 operation fence、重放 callbacks并计算账户后提交。
  若保留 gateway 侧计算，只允许使用绑定 current checkpoint/state identity 的严格 CAS：事务内 fresh mismatch 时
  返回稳定 retry/busy，零写入；不得提交 caller 传入的陈旧完整 account。
- 两个独立 store handles/process 对不同 command 并发时，允许一个返回 retry/busy；其 exact retry必须基于新
  predecessor重算。最终两个 command/events/orders/positions/cash 各恰好一次，fresh replay与anchor全闭合。
- SQLite writer busy、CAS retry、semantic drift 使用不同稳定错误；不得把事务竞争伪装成 identity drift。

### 13.3 新增测试与通过条件

- R1 fake/duck store 与任意 64hex gateway 最小复现必须拒绝；public builder不能创建 formal policy，future
  RUN-0B2 capability 的位置用停止/待实现断言表达，不在 B1 私签。
- 单改 canonical account+checkpoint、initial snapshot 无事件资金变化，以及 operation/event/account/checkpoint
  协调 whole-rehash均拒绝；fresh evidence从initial+callbacks重放得到 exact retained account。
- anchor增删改、换序、跳号、错误 predecessor、同sequence异bytes、DB commit后补锚、补锚前重启、完整root复制、
  symlink/reparse均覆盖；exact retry不生成第二anchor。
- 两 writer 同旧 predecessor 的 barrier 反例：最多一个首次 commit；另一个稳定retry/busy，重试后两次经济影响
  均且仅出现一次。增加现金/持仓/订单/event四方一致断言。
- R1 全组、UNKNOWN restart、partial/cancel late fill、multi-session EOD、busy/crash、hostile exception、Windows
  与 WSL base/DrvFS pytest/Ruff/mypy全部回归绿色；DrvFS仍不是ext4 Gate。
- R2 必须由原实现上下文最小返工，再由未参与 R2 的全新上下文独立复验；PASS 后才进入主 Agent 终验。

## 14. R3：解释器 teardown 析构边界（2026-08-09）

R2 独立复验报告：`M4_P8_RUN0B1_R2_formal来源重放Anchor与并发CAS独立复验报告.md`。R1 F1–F3 已
确认关闭，但 R2 仍 FAIL。

### 14.1 失败闭环

Windows fresh 子进程保留 open `PaperBrokerStore` 到解释器退出。module teardown 期间
`PaperBrokerStore.__del__ → close → _guard_close` 动态 import `ctypes` 失败，Python 向 stderr 输出
`Exception ignored in: ...` traceback，并泄露 worktree/Miniforge 绝对路径。根因是析构路径复用了严格 public
close，却没有 destructor-only 的 best-effort/no-throw 边界；违反 §3.8/§10.12 的稳定脱敏与退出清洁要求。

### 14.2 最小返工与通过条件

- `__del__` 只能做 best-effort resource release，必须捕获包括 module teardown/import failure 在内的全部析构
  异常并静默返回；不得 print、log、warnings 或向 `sys.unraisablehook` 泄露对象/path/traceback。
- 显式 public `close()` 的严格语义保持：正常释放所有 handle/fd；真实 close failure仍由调用者得到冻结稳定错误，
  不因析构修复被吞掉。若缓存平台 close primitive，必须在模块正常初始化时建立且不暴露新 signer/状态接口。
- Windows fresh subprocess 创建/打开 store 后故意不显式 close，正常退出码、stdout/stderr均不含
  `Exception ignored`、traceback、worktree/Miniforge/TOKEN marker；同时覆盖 monkeypatch public close失败但
  `__del__` 不调用 unraisablehook。
- WSL fresh subprocess 对应 clean exit；R2 22 项、F1–F3 replay/anchor/CAS、Ruff/mypy全部继续通过。
- R3 只修改原 B1 白名单代码/测试与唯一R3报告，不改变policy/replay/anchor/CAS/EOD语义；完成后由未参与
  R3 的全新上下文复验。
