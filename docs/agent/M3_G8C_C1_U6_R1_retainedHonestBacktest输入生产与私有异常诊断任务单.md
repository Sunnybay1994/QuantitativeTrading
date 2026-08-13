# M3 G8C-C1 U6 R1：retained honest backtest 输入生产与私有异常诊断任务单

日期：2026-08-12  
状态：**主 Agent 串行诊断终态；`INSUFFICIENT_INTERNAL_EVIDENCE`；三根 retained 输入已精确清理**  
前置：U4 唯一 Diagnostic 已终态；U5 为 `INSUFFICIENT_INTERNAL_EVIDENCE`

## 1. 目标与事实边界

获取 honest public chain 在 G7E 首个 0.5x 场景中被 public 脱敏层吞没前的 exact 私有异常、触发不变量与最小输入形状。只做诊断，不修改产品，不宣布 G7E/G7F/G8 Gate。

现有 U4 三个 owned roots 已精确清理；临时证据仅含 stdout/observer/脚本，没有可 fresh 验真的 target/plan/facts/context。禁止从少数 parquet/JSON、复制路径或重签 receipt 伪造 retained capability。

## 2. 唯一诚实方案

### A. retained producer（只执行一次）

- Windows `m3chain312` 使用现有 `public_formal_chain_session` 的真实 public G1→target→backtest-plan 链。
- 在 fixture yield 后、默认 teardown 前，以显式 diagnostic retain 开关保留 exact 原位置的 stage root、config 与 G1 release root；不得 copy/rebase/rename。
- 生成脱敏 locator：exclusive session id、三根 canonical path、lstat kind/dev/inode、tree SHA、创建时间、cleanup token；不写 secret/raw payload。
- 默认行为仍必须 cleanup；retain 仅本任务显式启用，单 writer、no link/reparse。
- 诚实预算约 44 分钟；超过 60 分钟无阶段进展即停止，不重复启动。

### B. backtest-only private probe

- 只从 retained locator 和 public resolver/loader 重建 exact target/plan/facts/fresh context；不重建 G1→G7B。
- 在系统临时脚本中仅包装 `_simulate_formal_a_share_scenario`，记录首个 raw exception 的 type、脱敏 message class、函数/行号、触发不变量与非秘密 shape，然后原样 re-raise；不得改输入、返回或控制流。
- 只调用首场景 `Decimal("0.5")`；不继续 metrics/publication/其他场景。
- 预算 5–30 分钟；超过 30 分钟或触及 stage rebuild 即停止。

### C. 精确清理

无论成功失败，按 cleanup token 重新核对三根 path/kind/dev/inode/tree ownership，只删除本次 owned 三根；身份漂移、外来文件、link/reparse 时停止并报告，不递归盲删。清理后逐根 absent 并写 cleanup receipt。

## 3. 允许与禁止

优先只写系统 temp producer/probe/evidence。若现有 support 无法在不修改 teardown 的情况下 retain，允许最小修改：

- `tests/support/m3_formal_public_chain/session.py`：新增默认 false 的 diagnostic retain 开关与精确 cleanup token；
- 新定向 diagnostic 测试（不得成为普通默认长测）；
- 本任务状态与唯一诊断报告。

禁止修改 production、config、正式 data/artifacts、G7E/G7F实现测试；禁止 fake capability、`object.__new__`、seal/HMAC/registry 绕过；禁止联网、完整 U4/G8 CLI 重跑、并行第二 producer。

## 4. 必须输出

- retained producer 每阶段时间与最终 exact roots/identity/tree SHA；
- private core 首个 exact exception/line/invariant/shape，或明确 `INSUFFICIENT_INTERNAL_EVIDENCE`；
- public `AShareSimulationError` 映射对照；
- 建议最小产品/测试白名单（仅在 raw cause 已证后）；
- 三根 cleanup receipt。

## 5. 停止条件

任一既有残留；root/token/SHA 漂移；必须 copy/rebase receipt；需要伪造 capability；producer 60 分钟无进展；probe 30 分钟未到 private core；raw异常包含敏感数据且无法脱敏；cleanup ownership 不确定。命中即停止，不猜、不盲修。

## 6. 执行终态（2026-08-13）

- honest producer 唯一一次成功：G1 `797.541s`，总链 `3316.134s`；retained locator 使用 cleanup token `ee5563b6f1014690a5bef75b198760d3`。
- backtest-only probe 在 `1534.5s` 得到 `AShareExecutionError`，栈为 `a_share_simulator.py:_simulate_formal_a_share_scenario:580` → `a_share_execution.py:execute_formal_a_share_session:4045`；输入 shape 为 300 target rows、300 scheduled rows、1 execution session，facts 为 300 instruments/bars/limits/reconciliation、1 calendar/benchmark、0 suspension/ledger。
- 该异常仍是 F2 public 脱敏层。加入只读 exception-event observer 的最后一次 probe 在 `1804.1s` 超时，未形成可计证据，按本任务 30 分钟停止条件不再重跑。
- cleanup 已按 locator 的 path/kind/dev/inode/tree SHA 移除 exact G1 release、stage root、config；receipt 中 `residual=[]`，事后 `_f0r*` 为 0、config absent、G1 releases 子项为 0。
- 因未取得 F2 脱敏前的原始异常/触发不变量，本任务结论保持 `INSUFFICIENT_INTERNAL_EVIDENCE`；禁止据此猜测或修改 G7E/F2 产品语义。
