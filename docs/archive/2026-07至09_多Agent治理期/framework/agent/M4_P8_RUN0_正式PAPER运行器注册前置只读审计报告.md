# M4 P8 RUN-0：正式 PAPER 运行器注册前置只读审计报告

日期：2026-08-09  
审计角色：P8 R4 工程复验完成后的独立只读前置审计  
结论：**当前不得注册、不得启动正式 PAPER runner，不得创建正式 P8 root/journal**

## 1. 审计边界

本轮完整核对了 P8 runbook、P4-P8 任务/验收边界、PAPER CLI 与依赖端口、
SQLite store、内存 Paper Gateway、恢复/对账、EOD report、soak evidence API、trading config、
clean calendar 入口、路线图以及 M1 U0C 现有 Windows Task Scheduler 约定。

本轮没有修改生产代码或测试，没有读写正式 data/G1/P8 产物，没有网络或
broker 请求，没有创建 runtime root/journal，没有生成或注册计划任务。除本报告外所有文件只读。

## 2. 当前裁定

P4-P8 已完成的是可测、可注入的工程合同；仓库中尚无一条能由操作系统直接
启动的正式、无实盘、可恢复 PAPER runtime capability。直接注册任务只会得到以下
两类错误结果之一：

1. 首次唤起时因生产依赖、identity、源、日历或路径未装配而失败；
2. 用测试 fixture、内存 fake 或 development capability 补空，生成外观类似正式但没有
   真实 PAPER 证据闭包的产物。

第 2 类做法明确禁止。`VerifiedDevelopmentSoakEvidence`、development example target、
`InMemory*Repository`、FakeGateway、FixtureLedgerContextProvider、MutableClock 及单元测试自报
identity 都不得进入正式 `PAPER_REAL_TIME` 装配。

## 3. 逐项证据

### 3.1 尚无可执行生产 CLI 装配

- `src/quant/execution/cli.py` 的入口是
  `main(argv, *, dependencies: CliDependencies)`，要求调用方注入七类端口。文件没有
  `if __name__ == "__main__"` 或无参数生产组装。
- `pyproject.toml` 没有 PAPER/soak console script；`scripts/` 中没有 M4 runner wrapper。
- 全仓只有 `tests/unit/test_execution_cli.py` 构造 `CliDependencies`，其中使用
  `FakeGateway`、`FixtureLedgerContextProvider`、`MutableClock`、`ValueLoader` 和测试
  `BrokerPort`。
- `src/quant/execution/soak.py` 只有 `build/append/verify/decide` API，尚无任务书允许的
  `python -m quant.execution.soak run-session|verify|status` 运行器。

### 3.2 Paper Gateway 不是可恢复的正式 broker 端

- `src/quant/execution/gateways/paper.py` 自述为 deterministic, in-memory adapter。
- 它的 clock、fill policy、fault plan、cost schedule 和 FX 全由外部注入；仓库中无正式
  `PaperGatewayFactory` 实现。
- 它只能恢复 `recovered_commands`，没有独立 durable broker request/result journal、
  sent/unknown fence、broker account projection 或 EOD snapshot store。
- 仓库中无正式 `BrokerSnapshotPort`。如果直接从 OMS SQLite 投影 broker snapshot，
  P5 reconcile 只是同源自比，不是独立对账证据。

### 3.3 Store 可打开，但没有正式 store capability

- `ExecutionStore.open(uri, trusted_root=...)` 具备受信根、物理路径边界、WAL 与 migration；
  这是可复用的底层能力。
- 但 `configs/trading/example.toml` 只给出 example URI
  `sqlite:///artifacts/trading/execution.db`，没有正式 trusted root 裁定、`StoreOpener`
  或不可混淆的 store-instance identity。
- P8 仅检查调用方提交的 `store_identity` 是 64 位 hex 且与 manifest 相等，
  并不自行证明该 id 确实属于当前 SQLite 实例。

### 3.4 稳定身份缺口

P8 manifest 需要跨 28 日不变的 source/config/gateway/store/account identity，但当前：

- config 可通过 `trading_config_identity` 对一份已验真文档求身份，但还未包含
  runtime/platform/root/source-plan 选择；
- gateway identity 只有端口和测试自报 id，没有生产建造者；
- store identity 只有 P8 传入字符串，没有实例 descriptor；
- source identity 没有绑定正式 target/market/calendar receipt 的 source-plan manifest；
- `build_account_snapshot_identity` 绑定某个会随成交变化的账户状态快照，不能代替跨运行
  稳定的 PAPER account identity。仓库中无正式初始现金/持仓/account descriptor。

### 3.5 target、market、calendar、rule/cost/FX 尚未生产装配

- P6 需要 receipt-backed `TargetLoader`。当前工作树只有 G7A development target 阶段报告，
  没有可供正式 PAPER runner 消费的正式 target loader。
- `ValidatedCleanMarketDataRepository` 是组合 injected strict reader 的生产外壳，但仓库中无本轮
  所需的正式 market/account reader 和 `PlanningLoader`。
- `expected_open_dates` 可以对 clean Parquet 区间覆盖和共同开市日做门禁，但返回的只是
  `set[date]`；它没有生成绑定 calendar receipt/source manifest 的 verified capability。
  P8 `expected_schedule_identity` 也只是对调用方日期 tuple 求哈希。
- `configs/trading/example.toml` 的 A/HK rule、fee、FX selector 在仓库中没有正式
  registry/loader。`ExecutionCostSchedule` 和 `FxSnapshot` 只有纯 builder，无正式版本化输入。

### 3.6 EOD 报告还有运行时恢复断点

- `ExecutionService` 需要生产 `LedgerContextProvider`、worker id、lease duration 和 risk scope；
  当前没有装配。
- P7 `build_execution_report` 需要当日 `RiskDecision` tuple，但 P5 `RecoveryResult` 不包含 risk，
  也没有公开 durable risk receipt/reader。
- P7 当前不强制“有 command 则必须有对应 risk decision”，因此正式 runner 若盲目传
  空 tuple，会得到形式可验但风控审计不完整的报告。此路径必须 fail closed。

### 3.7 平台与调度边界未满足

- 当前 WSL 项目路径落在 `/mnt/f` DrvFS（WSL1），不是 ext4。P8 Windows/DrvFS 绿测
  是开发兼容证据，不是项目规定的 Linux/ext4 正式 Gate。
- 当前 P8 manifest 没有独立 platform-track 字段。如果在 Windows/DrvFS 直接建立
  `PAPER_REAL_TIME`，底层 decision 未必能区分“Windows 真实 soak”与“M4 正式 Gate”，
  存在严重表述混淆风险。
- M1 U0C 已冻结的 Task Scheduler 约定可复用：一次性显式日期任务、`IgnoreNew`、
  `StartWhenAvailable`、`WakeToRun`、有限 `ExecutionTimeLimit`、无 repetition/自动 restart、
  独占脱敏日志。但 M4 目前没有 wrapper/XML/hash/运行锁。

### 3.8 凭据裁定

M4 PAPER runtime 不应访问实盘 broker，不应需要实盘账号、broker token 或下单权限；
每日 runner 也应只消费已验真的本地 source capability，不在 runner 内访问 Tushare/BaoStock。

所以当前缺少的不是 broker 凭据，而是非秘密的 runtime/account/source/store/gateway descriptor、
安全路径、生产 adapter 和持久化审计闭包。如任何 RUN-0 设计要求实盘凭据或网络下单，
应视为越出 M4 边界。Task Scheduler 未来只使用本机用户执行上下文；不将凭据
写入 XML、log、config 或 receipt。

## 4. 最小前置工程包分解

RUN-0 应分成以下可独立验收的小包；前一包 PASS 后才进入下一包。任何一包通过
都不自动授权注册或启动。

### RUN-0A：路径、平台与五类身份

1. 新增 strict `PaperRuntimeManifest/VerifiedPaperRuntime`，使 source/config/gateway/store/account
   identity 都由公开 builder 根据已验真输入生成，不接受裸 64hex 自报。
2. account identity 绑定一次性 exclusive PAPER account descriptor、初始资金/持仓快照和
   runtime mode；日常会变的 account snapshot id 另行保留。
3. store identity 绑定 trusted root、relative SQLite URI、schema version 和 exclusive
   store-instance descriptor。
4. gateway identity 绑定 adapter/policy 版本、独立 broker-store 实例、fee/FX/rule selection。
5. source identity 绑定正式 target receipt、正式 market/calendar source plan 与 reader/adapter 版本；
   日常 receipt 可更新，但必须落在同一不可变 source plan 内。
6. config identity 绑定 TradingConfig 与 runtime/platform/root/schedule policy。
7. 正式 preflight 必须在任何 root/manifest 创建前证明 WSL Miniforge base + ext4。
   Windows/DrvFS 只做无写开发反馈，不创建 `PAPER_REAL_TIME`。

### RUN-0B：正式本地 PAPER 生产 adapter

1. `VerifiedTargetArtifact` 到 receipt-backed `TargetLoader` 的窄 adapter，严格拒绝 development
   target、手写 target 和扫描目录发现。
2. 正式 G1/日更 clean receipt 到 `Market/PlanningLoader` 的窄 reader，必须检查 PIT、
   quality、calendar、source 与精确标的覆盖。
3. 版本化 rule/fee/FX loader，数值仅来自 `configs/`，selector 未知、过期或日期断层时
   fail closed。
4. 生产 `LedgerContextProvider`、`StoreOpener`、`ServiceFactory`、UTC clock 与固定
   worker/lease/risk scope。
5. 独立 durable `PaperBrokerStore` + `PaperGatewayFactory` + `BrokerSnapshotPort`；
   gateway request/result/fence/account projection 不与 OMS store 共用同一事实源。
6. 新增 durable risk receipt/reader。实际存在 command 时，P7 必须证明每个 command 有
   exact RiskDecision 闭包；不得向 P7 传空 tuple 规避风控报告。

### RUN-0C：verified expected schedule

1. 从已验真 calendar receipt/manifest 生成 `VerifiedSoakSchedule`，绑定目标市场集合、
   完整自然日覆盖、source receipt 和 exact ordered sessions。
2. 直接调用 `expected_schedule_identity(tuple(dates))` 只能是最后一步，不能代替
   calendar provenance 验真。
3. 首 session 只能是全部 readiness 完成后的下一个已验真开市日；最后一个
   session 必须使真实 invocation span 安全大于 28 日，建议冻结不少于
   35 个自然日的窗口。
4. 期间所有预期交易 session 必须在 manifest 中。错日、漏日、闭市日或次日补跑
   都在 gateway 前失败。

### RUN-0D：每日 runner 与 EOD 证据闭包

1. 唯一模块入口保持任务书冻结的
   `python -m quant.execution.soak run-session|verify|status`；依赖由 strict runtime config
   装配，默认零网络。
2. `run-session` 次序固定为：全局 exclusive runtime lock → fresh 双根/五类 identity/
   schedule/date → P6 inspect/plan → 按 P6 原合同完成 approve/submit/cancel → 独立
   broker EOD evidence → recover/reconcile → 完整 risk report → append session → fresh verify。
3. `manual_approval=true`、`auto_trade=false` 保持不变。approve/submit/cancel 仍使用
   P6 十分钟 content-addressed challenge 的人工二次确认；scheduler 不生成、重放或
   伪造 confirmation hash。
4. 正式 manifest 只能在全部 preflight 通过且首个真实 session 开始时幂等创建。
   前置失败不得留下半正式 root。
5. broker 非 `END_OF_DAY`、UNKNOWN/LEASED、对账差异、风控断链、market/account/target
   过期都不能 append Gate-pass session，更不能自动重发。
6. 每日仅一份 exclusive 单行脱敏 log，只含 schema/date/UTC start/end/status/
   run id/relative receipt/exit code/stable code，不含绝对路径、账户原文、底层异常或 env。

### RUN-0E：正式故障演练调度

1. 只允许 P8 冻结的十个 exact drill enum；禁止任意 import path、pickle、调用方 SQL
   文本、动态 Python 插件或底层 broker payload。
2. 为避免 callback conflict/UNKNOWN/manual-closed 状态污染后续正常 session，全部演练在
   最后一个正常 expected session 完成后串行执行。
3. 演练仍在同一个已验真 store/account/gateway identity 内，每项立即保存 exact
   before/after `RecoveryResult`、affected subjects、receipt 与 anchor。
4. 每项为显式一次性任务或人工监督步骤，无自动 retry。只有 exact evidence bytes
   已完整且缺 anchor 时才能补锚。

### RUN-0F：Task Scheduler 定义与离线审计

1. 复用 U0C 约定：每个 session/drill 显式一份一次性 XML，`wsl.exe` 只唤起 WSL
   Miniforge base 和 ext4 上的版本化 wrapper。
2. 设置 `IgnoreNew`、`StartWhenAvailable=true`、`WakeToRun=true`、有限
   `ExecutionTimeLimit`、无 repetition/自动 restart。`StartWhenAvailable` 唤起的错日任务
   由 runner 在任何 gateway/evidence 写前拒绝，不算补跑成功。
3. 注册前冻结 XML 和 SHA-256；注册后只读回查 action/trigger/settings/XML hash。
4. RUN-0F 完成只能表述为“已具备可注册定义”。真实注册是后续单独持久化副作用，
   需要主 Agent 复核与用户明确授权。

## 5. 建议白名单

详细任务书冻结后，RUN-0 可使用以下最小新增/定向修改范围：

- 新增 `src/quant/execution/paper_runtime.py`：runtime manifest、五类 identity 和生产组装；
- 新增 `src/quant/execution/paper_broker_store.py`：独立 durable PAPER broker journal/account projection；
- 新增 `src/quant/execution/soak_runtime.py`：daily session、EOD closure、drill 和 scheduler-safe result；
- `src/quant/execution/soak.py`：仅增加冻结 module CLI 的最小委派，不重写 R3/R4 主合同；
- 新增狭的 durable risk codec/reader 文件；若必须修改 store schema 或 P7 完整性合同，
  应拆成 RUN-0A 前置并单独复验，禁止 runner 私自解析 private `execution_stages` payload；
- 新增 `configs/trading/paper_runtime.example.toml` 及必要的版本化 fee/FX/rule example；
- 新增 `scripts/run_m4_paper_session.sh`；
- 对应的 `test_paper_runtime.py`、`test_paper_broker_store.py`、`test_execution_soak_cli.py`、
  `test_paper_scheduler.py` 和少量 integration tests；
- `docs/framework/runbooks/M4_PAPER_SOAK.md`、RUN-0 任务/交付/独立复验/主验报告。

禁止为方便 runner 修改 P4-P7 底层业务语义，禁止复制 OMS/ledger/reconcile 公式，
禁止引入实盘 Gateway 或网络凭据。

## 6. RUN-0 必测反例

1. development/fixture target、手写 target receipt、可直接构造的 fake verified 对象在 root 创建前拒绝。
2. example config、未知/过期 selector、缺 current market/account/calendar/target quality 证据时
   零 root、零 gateway、零 anchor。
3. Windows、WSL1/DrvFS、非 base 环境的 formal init 在 manifest 前拒绝。
4. evidence/anchor/store/broker/log root 相同、互为祖先、落在 repo/data/data-legacy/G1、
   经 symlink/junction/reparse 或整根复制时 fail closed。
5. source/config/gateway/store/account 任一 identity 漂移不能 append 旧 run，只能新建 run。
6. broker journal 与 OMS store 出现 cash/position/order/event 差异时 P5 Gate false；不得用一边回填另一边。
7. 实际 command 缺 exact durable RiskDecision 时 P7/session 失败；空 tuple 不能通过。
8. Task date 与 Asia/Shanghai 当日不一致、错过后次日唤起、日历修订为闭市时：
   零 gateway、零 session receipt、零 anchor。
9. 两个同日任务并发：只有一个 runtime writer；第二个稳定 busy/duplicate，不分叉。
10. 缺失、过期、跨 action 或状态漂移的 confirmation hash：零 economic crossing；旧 hash 不重放。
11. gateway `UNKNOWN`、malformed 或进程在 started 后退出：重启后只 QUERY，不自动重发。
12. broker evidence 为 `INTRADAY`、P5/P7 Gate false 或有未解释 issue：不 append Gate-pass session。
13. session facts/receipt 已完整但 anchor 前崩溃：相同 bytes 可补锚，任意改变均冲突。
14. drill 重复、跳号、错顺序、未冻结名称、任意 payload/SQL/import path 全部拒绝。
15. 向 source/broker/config/log 边界注入 path/TOKEN/account/broker marker：公开 stdout/stderr/log/
    exception/receipt 均不能恢复原文，cause/context 为空。
16. 少任一 expected session、真实 invocation span 小于 28 日、缺任一 drill、非 ext4 平台：
    都不得形成项目层 M4 Gate PASS。

## 7. 仍需主 Agent / 用户裁定

以下选择会改变 identity、数据范围或持久化外部状态，不应由实现者自行猜测：

1. **正式平台**：按项目现行规则，建议只在 WSL Miniforge base + WSL2/ext4 启动
   `PAPER_REAL_TIME`。若要先做 Windows 真实 soak，必须先冻结不可与 M4 正式 Gate 混淆的
   platform-track 语义；现有 P8 类型不足以自动做该区分。
2. **五个精确绝对路径**：OMS/runtime root、independent broker-store root、P8 evidence root、
   P8 anchor root、exclusive log root；它们必须在 ext4 上互不为祖先，且远离 repo/data/G1。
   还需裁定保留周期、容量、备份和权限。
3. **PAPER account descriptor**：稳定本地 account id、初始现金/持仓、币种、起始日与
   是否允许故障演练经济影响进入同一账本。不填任何真实券商账号。
4. **正式 target 源**：选择已主验的 M2 或 M3 `VerifiedTargetArtifact`，以及第一个
   A 股 PAPER 范围/证券集。当前 development target 不可使用。
5. **market/calendar source plan**：每日需要哪些已验真 clean/release receipt、覆盖哪些市场、
   日更截止时间与质量门禁。M4 runner 本身不负责网络采集。
6. **正式版本配置**：A 股 rule、fee schedule、FX 语义（若第一轮仅 A 股则明确为
   不需要 HK FX）、fill policy、fault policy、worker/lease/risk scope。
7. **操作模式**：每日 Task Scheduler 只做 EOD 审计/证据 append，还是同时负责唤起
   plan challenge；无论如何，approve/submit/cancel 的人工 content-addressed confirmation 不得取消。
8. **schedule 窗口**：只能在 RUN-0A-C 主验和当时 verified calendar 确认后选择首个
   session；不现在预写过期日期。
9. **注册授权**：创建 ext4 runtime roots 和注册 Windows Task Scheduler 任务都会产生持久
   外部状态。只有 RUN-0A-F 主验、冻结 XML/hash 和 preflight `READY` 后，才可以主 Agent
   提交精确任务名、日期、action、写入路径给用户批准。

## 8. 最终结论

P8 R4 工程合同已主验，但正式 PAPER runner 的生产装配、身份、独立 broker 证据、
verified target/market/calendar、完整 risk report、ext4 路径、每日 wrapper 和调度定义都尚未闭合。

因此当前状态必须保持：

```text
M4 P8 engineering contract: PASS
Formal PAPER runner readiness: NOT READY
Task Scheduler registration: PROHIBITED AT CURRENT STATE
Formal soak status: WAITING_FOR_SOAK_EVIDENCE
Linux/ext4 Gate: OPEN
```

下一步是由主 Agent 根据本报告冻结 RUN-0A 任务书并先关闭路径/平台/五类身份。
在 RUN-0A-F 全部完成且正式 preflight 返回 `READY` 之前，不注册、不启动、不创建正式
P8 root/journal，不使用任何 fixture/development capability 填空。
