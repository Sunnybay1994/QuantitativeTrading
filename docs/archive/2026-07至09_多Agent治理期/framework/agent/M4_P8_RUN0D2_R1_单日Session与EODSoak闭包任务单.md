# M4-P8 RUN-0D2 R1：单日 Session / EOD Soak 闭包任务单

状态：实现与定向开发检查完成，主 Agent 已接收并形成独立安全提交；待统筹合流；仅 Windows non-formal PAPER soak 工程闭包，不启动真实 PAPER/订单，不关闭 formal Gate
分支：`codex/m4-windows-soak-runtime`
基线：`bd97212e6d474f3fe92f6cbf4400a86fe27505bf`

## 1. 目标与边界

在既有 formal PAPER capability chain、`VerifiedFormalPaperSoakSchedule` 和 RUN-0W Windows soak 证据合同之上，
增加一个最小的单交易日关闭入口。入口只完成：指定 session 的 exact EOD broker finality、OMS recovery、统一
reconciliation、由注入端口生成 P7 报告、append-only soak session、fresh evidence 与当前 Gate decision。

本包不实现 fault drill、Task Scheduler、跨日循环、通用编排平台、报告模块迁移、真实候选/opening source、
自动确认、自动提交或真实 PAPER 启动。Windows 证据仍为 `formal_gate_eligible=false`；本包单独运行只能产生
`WAITING_FOR_SOAK_EVIDENCE` 或 `BLOCKED`，绝不能产生 formal `PASS`。

## 2. 公开接口

新增 `src/quant/execution/soak_runtime.py`：

```python
class SessionReportPort(Protocol):
    def build(
        self,
        *,
        recovery: RecoveryResult,
        reconciliation: ReconciliationResult,
        as_of: datetime,
    ) -> object: ...

def close_formal_paper_soak_session(
    *,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    composition: VerifiedFormalPaperServiceComposition,
    schedule: VerifiedFormalPaperSoakSchedule,
    session_date: date,
    now: datetime,
    report_port: SessionReportPort,
) -> FormalPaperSoakSessionResult: ...
```

`close_formal_paper_soak_session` 是 RUN-0D2 唯一新增 public 业务边界；broker EOD 写/读 helper 保持模块私有，
不能被任意 64-hex identity 直接包装成“formal verified”能力。`SessionReportPort` 是 execution/reporting 之间唯一
新增协议边界。`quant.execution` 不 import `quant.reporting`；端口
返回的对象由既有 `append_soak_session` 重新验真 exact `ExecutionReport`，非法或伪造报告统一 fail-closed。
结果对象绑定 manifest、session receipt、fresh verified evidence、fresh decision 和 `replayed` 标志。

## 3. 冻结执行顺序与不变量

1. 在访问任何 capability property/path 前先做 public 入参 exact-type guard；随后只读调用
   `verify_existing_paper_runtime_preflight`，先验明 `log_root` 是已获授权的受控 lock target。若严格先建锁后验
   capability，伪造 exact dataclass 可诱导任意路径写入，故该 path-authority 检查必须先于 lock 文件创建。
2. 在 `log_root/paper-soak-session.lock` 取得 anchored、no-follow/reparse、非阻塞进程级单写锁；锁冲突、根或锁
   文件实体漂移均拒绝。锁内重新 fresh 验证 runtime、policy、composition、schedule，并要求：
   - runtime mode 为 `PAPER_REAL_TIME_WINDOWS`；
   - policy、composition、ledger provider、schedule 和五个身份完全闭合；
   - `session_date == policy.session_date`，且是 schedule 当前已存在或下一个缺失 session；不得跳日。
3. 用 schedule 身份、runtime config、gateway、store、account 和完整 expected sessions 构造或 exact reopen 同一个
   Windows soak manifest。manifest 的 `started_at` 绑定已进入 schedule stable identity 的
   `schedule.readiness_completed_at`，其语义是 Windows soak schedule readiness anchor；每个 session receipt 的
   invocation 时间才表示实际运行时间。process-local `schedule.verified_at` 不参与 run identity，因此跨进程 remint
   仍 exact reopen 同一 run。Linux formal `PAPER_REAL_TIME` 新 manifest 继续保留 5 分钟 production wall-clock 门禁；
   Windows non-formal kind 不凭 readiness anchor 声称 formal 持续时长或 `PASS`。
4. 已存在该 session receipt 时只 fresh 重验 evidence/decision 并返回 exact replay；不使用新时间重写 finality 或
   receipt。
5. 新 session 先取得只读 recovery snapshot，并重验本 session ORDER semantic closure；随后对 broker store 写入
   或复用**指定 session**的 exact finality，再按该 session finality 行读取 EOD evidence；禁止用 latest command
   日期推断 finality。broker snapshot 仍覆盖 store 的完整 retained state，供既有全局 reconciliation 使用，不把
   历史 command 错删成“单日快照”。零 broker order 也必须能读取指定 session 的 EOD 事实。
6. recovery 必须证明本 session 存在非空 staged commands，并由 exact durable `ORDER`
   `DurableRiskTransitionReceipt` semantic closure 唯一覆盖；完全空 plan/无 command 日拒绝。随后执行统一
   `reconcile`。在 report/append 前再次从 live OMS store 执行 `recover_local_state`，要求 `recovery_id` 与 exact-session
   closure identity 均未漂移；漂移时零 report、零 append。通过后才调用 report port、`append_soak_session`、fresh
   `verify_soak_evidence` 和 `decide_soak_gate`。
7. 任一异常统一映射为无路径、无 SQL、无 token、无异常链的 `PAPER_SOAK_SESSION_INVALID`。

## 4. Human approval 证据边界

现有 durable ORDER risk receipt 只证明 formal OMS 已持久化一次 ORDER 风控/分阶段结果及 command 唯一 owner，
**不是独立的人机 challenge 审计凭证**。CLI `approve` 的 challenge 当前只在调用时校验，没有单独持久化的
human-approval receipt。本包不伪造该证据，也不扩白名单实现第二套 approval 系统。

该缺口登记为 RUN-0D2 延期债：真实 PAPER/无人值守启动前，必须由后续任务新增可审计的人机批准凭证，或由
上层受控 operator 入口提供并把该凭证绑定到 session closure；通过标准是可以从耐久产物证明“谁/何时/对哪个
plan identity 批准”，且不泄露人员或凭据原文。当前临时处置是 RUN-0D2 只做 non-formal Windows 工程闭包，
要求 durable ORDER receipt，并继续受人工操作入口与 UA-M4-002 前置控制。

## 5. Runtime、EOD 与恢复补口

- `paper_runtime.py`：formal layout 允许 evidence/anchor/log 与既有 runtime/broker 一样以普通、非
  link/reparse 目录预先物化并纳入物理身份；runner 不自行物化或替换这些根。
- `paper_broker_store.py`：新增指定 session finality 查询；`read_evidence_snapshot` 可显式传入 session，只按该
   session finality 行判定 EOD，但继续返回完整 retained broker state 供全局 reconciliation。零 broker order 使用
   单独 marker primitive，并绑定上层给出的 ORDER semantic-closure identity；marker 本身不是人工批准凭证。
   marker 的 `finalized_at` 只进入 durable journal/source identity 与 exact-session finality 判定，不推进 account/event
   经济快照的 `as_of`。
- `paper_formal_broker_snapshot.py`：新增仅供 runner 调用的私有 exact-session finalize/query helper；重启时复用已
  持久化 finality 时间，不用新 `now` 制造冲突；helper 自身不声称证明 ORDER receipt 来源，只有 runner 先从
  fresh recovery 重建 semantic closure、并将其与 marker identity 同时重验后才能形成 session result。
- `soak.py`：修复 exact persisted formal manifest 跨日 reopen；Linux formal 新 manifest 仍必须满足 production
  wall-clock，Windows non-formal manifest 使用 schedule readiness anchor 形成稳定 run identity；
   real-time session facts 缺失本 session durable ORDER receipt 时持久化为 `BLOCKED`，因此直接伪造 broker marker
   也不能形成通过的 soak evidence。

当前二次 recovery 比对仍不能让两个独立 SQLite store 与所有 OMS/broker writer 原子关闭同一 session。该残余竞态
登记为不可延期安全债 `DEBT-M4-SESSION-BARRIER`：任何真实 PAPER、真实 28 日 soak 计时或 formal Gate 前必须提供
所有 writer 共同遵守的 session-close barrier/close token，并证明 token 与 OMS recovery、ORDER closure、broker
finality 和 append receipt 同一身份闭包。RUN-0D2 的临时处置只允许 Windows non-formal 工程证据。

## 6. 白名单与禁止项

允许修改：

- `src/quant/execution/soak_runtime.py`（新）
- `src/quant/execution/paper_runtime.py`
- `src/quant/execution/paper_broker_store.py`
- `src/quant/execution/paper_formal_broker_snapshot.py`
- `src/quant/execution/soak.py`
- `tests/unit/test_paper_soak_runtime.py`（新）
- 上述四个既有模块的实际对应定向测试
- 唯一 `M4_P8_RUN0D2_*` 任务/交付文档
- session 总路线图中的 RUN-0D2 状态、债务和性能证据 exact hunk

禁止修改 `__init__.py`、CLI、runbook、config、reporting、项目级路线图或其他共享 SSOT；禁止新增 execution →
reporting import；禁止提前实现 fault drill/scheduler/通用 runner；禁止启动真实 PAPER 或订单。

## 7. 开发检查

检查均使用 Windows Miniforge、BelowNormal、CPU 8–11（`0xF00`）、threads <= 2 串行执行：

- 5 文件 focused pytest：`118 passed, 36 skipped, 1 failed`；唯一失败是 remint 测试夹具把 public `now` 推进后未
  同步 production clock，并非产品失败；同步夹具后只重跑该 node，`1 passed`。
- 白名单 10 个 Python 文件 Ruff：`All checks passed!`。
- 5 个生产模块 mypy：`Success: no issues found in 5 source files`。
- 5 个生产模块 cold import：`RUN0D2_COLD_IMPORT_OK`。首次承载误用了 `-I`，Python 按合同忽略 `PYTHONPATH`；
  去掉 `-I`、继续显式绑定本 worktree `PYTHONPATH` 后通过。

没有执行全量回归、真实 PAPER、订单发送、28 日计时或性能 profiling；这些结果不构成独立初验或 formal Gate。
