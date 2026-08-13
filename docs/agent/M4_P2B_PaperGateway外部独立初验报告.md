# M4-P2B PaperGateway 外部独立初验报告

- 角色：未参与实现的全新外部独立初验 Agent（`cursor-grok-4.5-high`）
- 日期：2026-08-11
- 工作区：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8ab-prereq`
- 合同：[`M4_P2B_PaperGateway任务单.md`](M4_P2B_PaperGateway任务单.md)
- 实现报告：[`M4_P2B_PaperGateway实现报告.md`](M4_P2B_PaperGateway实现报告.md)
- 结论：**EXTERNAL PRELIMINARY PASS**（初验通过，可交主 Agent 终验）
- 明确非结论：不宣布 P2/M4 Gate 通过；不替代主验；WSL 证据为 **DrvFS `/mnt/f`**，非 ext4 Gate

## 1. 范围与只读约束

已读：根 `AGENTS.md`、`.ai/README.md`、任务单、实现报告、
`src/quant/execution/gateways/{paper,__init__}.py`（并核对 P2A `contracts` / 共享 OMS / B3 cost 邻接只读）、
`tests/unit/test_paper_gateway.py`。

本会话仅写入本报告；未改生产代码、未改实现者测试、未改任务/交付文档、未联网、未 `git add/commit`、未跑全量。

交付提交白名单核对（`983827d`）：生产/测试仅
`gateways/paper.py`、`gateways/__init__.py`、`tests/unit/test_paper_gateway.py`；未见 contracts/OMS/store/domain/B1-B3 被本交付修改。

## 2. 合同逐项映射

| 成功标准 | 证据 | 判定 |
|---|---|---|
| 无 IO/网络/随机/系统时钟；时间/policy/fault/cost/FX 注入 | `paper.py` 无 `open`/`socket`/`random`/`datetime.now`/`time.time`；构造注入 clock/policy/fault/cost；冷导入与 submit 路径无仓库文件 open | 通过 |
| 同时实现 submit/cancel transport；回报仅为 `ExecutionEvent` | `isinstance` 协议面 + `verify_gateway_*`；回调经 `build_execution_event` | 通过 |
| `NOT_SENT/UNKNOWN` callbacks 为空；UNKNOWN 实例内终态；NOT_SENT 可重连 SENT | 实现者 `test_non_sent_*` / `test_unknown_is_sticky_*`；`_fence_certainty` | 通过 |
| broker/event/fee 身份不依赖 attempt；重启重放一致 | 实现者 restart/replay；本初验 A4 attempt=1 vs 99 回调全等，`broker=PAPER-{command_id}` | 通过 |
| submit：`REJECTED` 或 `ACCEPTED→PARTIAL*→FILL?`；cancel：`CANCEL_ACCEPTED→late fill*→CANCELLED/FILL`；满成交赢竞态 | 实现者序列/竞态；本初验 A3 partial→CANCELLED 与 full-fill 无 CANCELLED | 通过 |
| `CANCELLED` 后 fill 由共享 OMS 拒绝 | 实现者 `test_late_fill_after_cancelled_*`；本初验 A3 终态后再 FILL → `OmsError` | 通过 |
| 每笔 fill 调 `calculate_execution_cost`；不复制 OMS/verifier | import/`_fees`/`_prove_sequence`/`verify_gateway_*`；邻接定向测绿 | 通过 |
| PAPER 拒单仅 `{PAPER_RULE_REJECT}`；未知码 fail closed 且不回显 | `_PAPER_REJECT_CODES` + 构造/`__post_init__` 再验；实现者 hostile 集 + 本初验扩展码 | 通过 |
| adapter 错误稳定脱敏、异常链空 | `PaperGatewayError(code)` + `raise ...` 路径吞异常无 `from`；本初验递归/环图 | 通过 |

## 3. 实现者未使用的对抗性反例（内存探针）

探针位于 `%TEMP%\p2b-indep-adversarial\adversarial_p2b.py`（不入库）。实现者已覆盖路径/TOKEN/控制字符/部分未知码、ACCEPTED 同 id 异载荷、基础 cancel 竞态与简单 `__cause__/__context__`；**本初验新增**：

1. **未知/hostile reject_code**：`""`、空白、大小写漂移、首尾空格、`\x00`/`\t`、中文、路径穿越、`Bearer TOKEN_*`、以及冻结后把 `reject_code` 篡改为 `int` → 一律 `PAPER_POLICY_INVALID`，无输入回显、无 cause/context。
2. **同 id 异载荷**：FILL 后篡改 `last_price`；PARTIAL 应用前篡改 qty → 共享 OMS `identity`/`terminal` fail closed（非 PAPER 静默接受）。
3. **cancel→late partial→CANCELLED** 后再造 late FILL；以及 **late full fill 赢得竞态**（无 `CANCELLED`，OMS→`FILLED`）。
4. **attempt/broker/session/timezone 漂移**：attempt 1/99 身份稳定；broker 仅 `PAPER-{command_id}`；`session_date` 改变 → 新 command_id/新 broker；naive / UTC+8 clock → `PAPER_CLOCK_INVALID`。
5. **subclass/duck**：`PaperFill`/`PaperSubmitPlan`/`PaperCancelPlan` 子类与 duck plan → `PAPER_POLICY_INVALID`（`type(...) is` 闭包）。
6. **递归/环状异常图脱敏**：policy/fault 抛带 `__cause__` 环与 context 的 `TOKEN_RECURSIVE_SECRET_LEAK` → 对外仅稳定 code，格式化 traceback 不含密文，cause/context 均为 `None`。
7. **零 IO / cold import / P2A·OMS 邻接**：subprocess 冷导入无仓库 open；submit 路径无 open；源码含 `verify_gateway_*`/`reduce_order`/`calculate_execution_cost`，无 store/sqlite。

结果：`ALL_ADVERSARIAL_OK`

## 4. 定向验证命令与结果

Windows `D:\Miniforge3\python.exe`：

- `ruff check` `paper.py` + `gateways/__init__.py` + `test_paper_gateway.py` → **All checks passed!**
- `mypy --no-incremental` `paper.py` → **Success: no issues found in 1 source file**
- `pytest -q` `test_paper_gateway.py` + `test_gateway_transport_contracts.py` + `test_execution_oms.py` + `test_m4_costs_fx.py` → **133 passed**

WSL Miniforge `base`，路径 `/mnt/f/...`（`df -T` → **drvfs**，非 ext4）：

- 同组 ruff → **All checks passed!**
- `mypy --no-incremental --cache-dir /tmp/mypy-p2b-indep` → **Success**
- 同组 pytest → **133 passed**（3.19s）

## 5. 初验结论与移交

- 初验：**通过**；冻结合同、白名单、双平台定向证据与新增对抗探针一致，未发现需返工的违约。
- 未验证/非本包：DurablePaperGateway/store、真实 PAPER soak、WSL/ext4 正式 Gate、P2/M4 关闭。
- 下一步：主 Agent 终验（SSOT/跨模块不变量/未公开反例/必要回归）。**不得**将本报告表述为 Gate 已关闭。
