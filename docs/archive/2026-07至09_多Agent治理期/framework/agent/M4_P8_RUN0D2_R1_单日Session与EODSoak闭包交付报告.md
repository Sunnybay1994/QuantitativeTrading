# M4-P8 RUN-0D2 R1：单日 Session / EOD Soak 闭包交付报告

状态：实现与普通定向开发检查完成，主 Agent 已核对并形成独立安全提交；待统筹合流，未启动真实 PAPER/订单/28 日计时
分支：`codex/m4-windows-soak-runtime`
基线：`bd97212e6d474f3fe92f6cbf4400a86fe27505bf`
工作树：`artifacts/dev_worktrees/m4-windows-soak-runtime`

## 1. 交付结果

新增唯一 public 业务入口 `close_formal_paper_soak_session`，完成 Windows non-formal PAPER 的最小单日
session/EOD 闭包：受控全局锁、fresh capability chain、稳定 manifest exact reopen、指定 session 的 broker EOD、
OMS recovery 与 durable ORDER semantic closure、统一 reconciliation、窄 report port、append-only session evidence、
fresh verify 与当前 decision。Windows evidence 始终 `formal_gate_eligible=false`，runner 显式拒绝 `PASS`。

没有新增 execution → reporting import。broker EOD 写/读 helper 与 ORDER closure helper 均保持模块私有且不在
`__all__`；低层零 broker-command marker 不能独立形成 session result，伪 marker、空 recovery 和旧 session receipt
均 fail-closed。

## 2. 关键合同与实现

- 入口先 exact-type guard，再用 read-only runtime preflight 授权 `log_root`，随后取得 anchored、no-follow/reparse、
  非阻塞单写锁；锁内重新 fresh 验证完整 runtime/policy/composition/schedule 身份链。
- Windows manifest 的 `started_at` 绑定 schedule stable identity 中的 `readiness_completed_at`，定义为 schedule
  readiness anchor；实际运行时间只来自 session invocation timestamps。process-local schedule remint 不改变 run_id。
  Linux formal `PAPER_REAL_TIME` 新 manifest 的 5 分钟墙钟门禁保持不变。
- broker store 支持指定 session finality 与零 broker-command 低层 marker。marker 绑定 runner 从 durable OMS ORDER
  receipts 重建的 semantic-closure identity；marker 时间独立重验，不推进 account/event 经济快照 `as_of`。
- runner 在 broker EOD 与 reconciliation 后、report/append 前再次读取 live OMS recovery，要求 `recovery_id` 与
  exact-session closure identity 均未漂移；漂移时零 report、零 append。
- durable ORDER risk receipt 不是独立 human-approval receipt。本交付不伪造审批，也不解锁真实 PAPER。

## 3. 修改范围

生产代码：

- 新 `src/quant/execution/soak_runtime.py`
- `src/quant/execution/paper_runtime.py`
- `src/quant/execution/paper_broker_store.py`
- `src/quant/execution/paper_formal_broker_snapshot.py`
- `src/quant/execution/soak.py`

测试：

- 新 `tests/unit/test_paper_soak_runtime.py`
- `tests/unit/test_paper_runtime.py`
- `tests/unit/test_paper_broker_store.py`
- `tests/unit/test_paper_formal_broker_store.py`
- `tests/unit/test_execution_soak.py`

文档：本任务单、本交付报告，以及 session 总路线图中的 RUN-0D2 exact hunk。未修改任何 `__init__.py`、CLI、
runbook、config、reporting、`pyproject.toml` 或共享项目级 SSOT。

## 4. 开发检查

所有 Python 检查均使用 Windows Miniforge、BelowNormal、CPU affinity `0xF00`（CPU 8–11）、线程上限 2，严格
串行运行；pytest 的 basetemp 位于项目外的显式系统 TEMP 归属目录并在每次结束后精确清理。

- focused pytest（新 runner + 4 个直接模块既有测试）：`118 passed, 36 skipped, 1 failed in 48.91s`。唯一失败是
  remint 测试把 public `now` 推进 1 分钟但未同步 production-clock 夹具，真实拒绝发生在 `_fresh_decision` 的
  wall-clock 检查；同步夹具后只重跑该 node：`1 passed in 3.72s`。
- 白名单 10 个 Python 文件 Ruff：`All checks passed!`。
- 5 个生产模块 mypy：`Success: no issues found in 5 source files`。
- 5 个生产模块 cold import：`RUN0D2_COLD_IMPORT_OK`。首次命令误用 Python `-I`，导致解释器按合同忽略显式
  `PYTHONPATH`；去掉 `-I` 后仅重跑 cold import 并通过，该承载失败不是产品 import 失败。

没有运行全量回归、Linux/ext4 Gate、真实 broker/账户、订单发送、28 日 soak 或性能 profiling。以上是主 Agent
暂停外部 Agent 期间的普通开发反馈，不是独立初验，也不构成 formal Gate 证据。

## 5. 未决风险与退出条件

- `DEBT-PAPER-APPROVAL-001`：真实 PAPER/无人值守启动前仍需 durable、可重验且脱敏的 human-approval receipt，
  或由受控 operator 入口提供等价凭证并绑定 plan/session/closure identity。
- `DEBT-M4-SESSION-BARRIER`：二次 OMS recovery 比对只能缩小、不能消除独立 OMS/broker SQLite 与其他 writer
  之间的竞态。任何真实 PAPER、真实 28 日 soak 计时或 formal Gate 前，必须实现所有 writer 共同遵守的 durable
  session-close barrier/close token，并把 token 与 recovery、ORDER closure、broker finality、reconciliation 和
  append receipt 形成同一身份闭包。
- RUN-0D2 不提前实现跨日 capability rotation、fault drill、scheduler 或通用编排；这些仍属于后续独立任务。

主 Agent 已核对精确 diff，并随本报告形成 `bd97212` 之后的独立安全提交；当前退出条件只剩由统筹决定合流。

## 6. 工作树卫生

最终 `git diff --check` 无 whitespace error（仅 Windows checkout 的 LF→CRLF 提示）。本次检查创建的 worktree 内
`run0d2-*` 临时目录与项目外 `quant-m4-run0d2-*` basetemp 均已精确清理，残留计数均为 0；CPU 8–11 上没有
RUN-0D2 Python 进程。CPU 串行槽已释放给统筹；本报告随精确白名单 diff 一并提交。
