# M4 P8 RUN-0B2A2：P7 Durable Risk Exact Completeness 任务单

日期：2026-08-09  
状态：主 Agent 最终验收通过（仅 development 工程合同；正式 PAPER/28 日/ext4 Gate 仍开放）

## 1. 目标

把 P7 `ExecutionReport` 的风控来源从调用方临时传入的 `tuple[RiskDecision, ...]` 收缩为 P5
`RecoveryResult.risk_receipts` 中已经持久化、fresh 解码并纳入 `recovery_id` 的
`DurableRiskTransitionReceipt`。完成后：

- `build_execution_report` 不再接受 `risk_decisions` 参数；
- 报告层不得自行打开 OMS store、读取 sidecar 或再次执行风控；
- 每个 recovery order command 必须由且只能由一个 durable ORDER receipt 精确拥有；
- cancel transition 继续由 recovery 的完整 receipt closure 证明，但 P7 不把 cancel policy 伪装成原有
  pre-trade rule event；
- 调用方不能通过空 tuple、删减 tuple、替换同 plan decision 或另造运行期 `RiskDecision` 绕过报告闭包。

本包只关闭 development 工程合同。它不组装正式 PAPER runner，不创建 formal root，不注册 scheduler，不启动
真实 soak，也不关闭 ext4 或 M4 Gate。

## 2. 权威前置与不变量

1. P5/P7 原合同以 `M4_P7_R1_EOD执行报告任务单.md` 为基线；本任务只替换 risk 输入来源和完整性规则。
2. durable wire、ORDER/CANCEL chain、counter transition 与 command/cancel exact owner 以
   `M4_P8_RUN0B2A1_DurableRiskReceipt与Recovery任务单.md` 及其 R2 为权威。
3. B2A1 的公共 `verify_risk_receipt_semantic_closure` 是 command/cancel 与 receipt ownership 的唯一公共
   语义 verifier；P7 不复制另一套 chain/counter/ownership 算法。
4. `RecoveryResult` 必须 exact type，并由构造器 fresh 重建。重建时必须透传 `risk_receipts`；漏传导致固定
   `EXECUTION_REPORT_INVALID`，不得为了兼容旧 fixture 默认为空。
5. `reconciliation.local_recovery_id == recovery.recovery_id`、UTC `as_of`、aggregate/event/ledger reducer、
   Gate false、canonical report identity 与脱敏规则保持不变。

若 B2A1 R2 最终未通过，停止本包，不在 P7 内补偿 B2A1 缺陷。

## 3. 公共接口

冻结为：

```python
def build_execution_report(
    *,
    recovery: RecoveryResult,
    reconciliation: ReconciliationResult,
    as_of: datetime,
) -> ExecutionReport: ...
```

删除 `risk_decisions` 参数，不保留可选参数、兼容 overload、`**kwargs` 或旧入口。调用旧签名必须由 Python
稳定拒绝；不得静默忽略 caller risk。

`ExecutionReport` wire/schema/字段不演进；`risk_events` 仍为排序后的 `ExecutionRiskLine`，以避免无关 P8
retained report schema 迁移。现有 `encode_execution_report` 公共接口保持不变。

## 4. Fresh recovery 闭包

`execution_report._verify_recovery` 必须：

1. 要求 exact `RecoveryResult`；
2. 用全部现有字段加 `risk_receipts=value.risk_receipts` fresh 构造新的 `RecoveryResult`；
3. 不捕获并透出下游异常；失败在 public builder 外层统一变成
   `ExecutionReportError("EXECUTION_REPORT_INVALID") from None`；
4. 不对 receipt 做 object identity 或进程内来源假设，只信 exact canonical durable 内容与 B2A1 公共 verifier。

`RecoveryResult.__post_init__` 与 B2A1 公共 verifier 已负责全量 command/cancel ownership。P7 仍必须在生成
risk lines 前再次调用同一公共 verifier，原因是报告边界必须 fresh 证明其直接依赖，且不能依赖一个被低层
`object.__new__`/`object.__setattr__` 构造的表面对象。

## 5. Risk line 唯一投影

P7 只从 `recovery.risk_receipts` 中 `transition_kind == "ORDER"` 且 exact decision type 为
`DurableOrderRiskDecision` 的记录生成 risk lines：

- 每个 receipt 的 `plan_id`、ordered `command_ids`、ordered `approved_intent_ids` 已由公共 verifier 与
  recovery commands 精确闭合；P7 不再接收或重建裸 `RiskDecision`；
- 每个 `RiskRuleResult` 映射为既有 `ExecutionRiskLine(plan_id, rule, accepted, code,
  subject_identity)`；`detail` 永不进入对象、repr 或 canonical bytes；
- 行排序沿用现有冻结主键，receipt 或 caller 容器顺序不得产生平台差异；
- CANCEL receipt 不产生 pre-trade rule line。它仍必须参与 recovery exact closure、`recovery_id` 和 P8 retained
  facts，因此不能删掉后仍生成报告；
- 非空 recovery commands 配空 receipts、少一个/多一个/重复 command owner、跨 plan、跨 kind、乱序 chain、
  receipt 决策与 command intent 顺序不一致，一律在 metrics/totals/report identity 前拒绝；
- 合法零 command/零 cancel/零 receipt 可生成零 risk event 报告；不得凭空要求运行期 risk tuple。

不新增“平均”“推断”或降级规则。特别禁止按 command 的 `plan_id` 猜测 risk rule，禁止从日志、private
`execution_stages` 或 planner 输入恢复 detail。

## 6. P8 retained facts 适配

`soak.py` 只允许做因 `RecoveryResult` 新字段与 P7 签名变化必需的机械适配：

- `_prove_recovery`、recovery facts encode/decode 必须保留 exact `risk_receipts` canonical wire；
- decode 必须调用 B2A1 public strict codec，不复制 receipt parser；
- retained facts 的 recovery identity 必须继续由 `RecoveryResult` fresh 构造验证；
- 所有 `build_execution_report` 调用删除 caller risk 参数；
- P8 anchor、时间、Gate、session/fault、目录与 formal/development 语义不得改变。

若现有 P8 retained schema 必须新增 `risk_receipts` 字段，应做显式 schema 版本演进并 exact-set 解码；不得让旧
schema 在有 commands 时用空 receipts 冒充新闭包。development 旧 fixture 可在测试 builder 中产生合法 durable
receipt，不得在生产 decoder 中加兼容旁路。

## 7. 失败语义与脱敏

- public P7 失败唯一固定码仍为 `EXECUTION_REPORT_INVALID`；
- cause/context 均为 `None`，完整 traceback/repr/object graph 不含 receipt detail、risk detail、路径、SQL、TOKEN
  或 hostile marker；
- 不进行 I/O、网络、SQLite、日志写入、重试、下单或墙钟读取；
- hostile B2A1 verifier/codec 抛 `ValueError` 或非 `ValueError` 时，离开 active `except` 后统一抛稳定错误；
- 任一失败不得生成部分 report 或改变上游对象。

## 8. 白名单

生产：

- `src/quant/reporting/execution_report.py`
- `src/quant/execution/soak.py`（仅 §6 的必要适配）

测试：

- `tests/unit/test_execution_report.py`
- `tests/unit/test_execution_soak.py`（仅必要 fixture/wire/回归）
- 必要时 `tests/unit/test_risk_wire.py` 只增加公共 verifier 被 P7 fresh 调用的窄回归；不得修改其生产语义

文档：

- 本任务单
- 唯一实现交付报告
- 唯一独立复验报告
- 若 retained schema 演进，最小同步 `docs/framework/runbooks/M4_PAPER_SOAK.md`

禁止修改 B2A1 store/service/reconcile/risk wire/migration 生产文件来迁就 P7；若发现前置缺口，停止并回到
B2A1 新返工轮次。禁止修改 runner/CLI/broker/runtime/scheduler/G1/M1/M3/formal artifacts 或 journal。

## 9. 必测正例

1. 一个 ORDER receipt/一个 command，多条 rule result，报告 risk lines 与 detail 脱敏正确；
2. 两个 plan、多 commands、穿插合法 CANCEL transition，order risk lines 完整且 cancel 不伪装 rule line；
3. 合法零 command/零 receipt；
4. Gate true/false、checkpoint 有/无、fill 有/无保持原 P7 行为；
5. P8 session/fault retained recovery→report encode/decode fresh 往返，Windows/Linux canonical bytes 一致。

## 10. 必测反例

至少覆盖：

1. 非空 commands + 空 receipts；删除/增加/重复一个 ORDER receipt；同 command 双 owner；receipt 无 owner；
2. receipt ORDER/CANCEL kind 置换、跨 plan、command ids/approved intent ids 增删换序；
3. 完整重算 receipt 与 outer `recovery_id` 后，若 command/cancel exact closure 不成立仍拒绝；
4. 调用旧 `risk_decisions=` 参数拒绝；另造合法裸 `RiskDecision` 不再有注入入口；
5. `RecoveryResult` subclass、receipt/decision subclass、低层 frozen 字段漂移；
6. `_verify_recovery` 漏传 risk receipts 的历史 retained-copy 反例；
7. hostile公共 verifier/codec `ValueError`/`RuntimeError("...TOKEN...")`：固定码、cause/context None、traceback
   与 repr 无 marker；
8. `open`、`socket`、`sqlite3.connect`、墙钟被禁止的零 I/O 探针；
9. P8 facts risk receipt 增删/改字节、schema exact-set 漂移、whole-rehash 但 retained anchor 不变均拒绝；
10. 输入失败发生在 report totals/identity 构造前，不能得到部分对象。

独立初验必须补至少一个实现者未使用的“合法但不同 durable closure 整体替换”或 hostile exception 图反例，
并确认它被 recovery/P8 anchor 边界拒绝而非只因 JSON 语法损坏。

## 11. 验证

Windows 原生 Miniforge：定向 pytest（risk wire/reconcile/report/soak 直接合流）、Ruff、mypy。随后在 WSL
Miniforge base 对应执行；`/mnt/f` 的 DrvFS 结果只算双平台开发兼容，不算 ext4 Gate。

不得机械跑仓库全量测试。实现与独立初验使用不同全新上下文；初验生产与实现测试只读，只写唯一报告。通过
独立初验后才进入主 Agent 最终验收。

## 12. 完成条件

- B2A1 R2 已独立复验和主验通过；
- P7 无 caller risk 参数，唯一消费 recovery durable receipt；
- command/cancel/receipt exact closure、recovery identity、P7 risk projection 与 P8 retained wire 同时绿色；
- 双平台定向测试和静态检查通过，异常脱敏通过；
- 报告明确只是 development 工程合同，RUN-0B2 正式装配、真实 28 日、WSL2/ext4 与 M4 Gate 仍开放。
