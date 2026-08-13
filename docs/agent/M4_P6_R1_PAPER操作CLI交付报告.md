# M4-P6-R1：PAPER 操作 CLI 交付报告

## R2 返工补充（2026-08-02）

初验发现“确认 A 后、原子 claim 前并发新增 PENDING B”仍会发送 A 并返回成功。根因是原有
`dispatch_commands` 正确实现的是选中 allowlist，并不证明该 allowlist 仍等于全局 pending 集合。

本轮保留原接口和语义不变，新增：

- `ExecutionRepository.claim_exact_pending_outbox_deliveries`：在同一 `BEGIN IMMEDIATE`
  中验证完整、排序、唯一的全局 PENDING 集合，并完成全体 claim；
- `ExecutionService.dispatch_exact_pending_commands`：只组合上述原子 claim 与既有
  `_dispatch_claimed` 单一路径；
- `paper-submit` 确认调用改用新接口。新增、缺失、未来 PENDING、LEASED、UNKNOWN 或 claim
  漂移均返回 `CONFIRMATION_DRIFT`（exit 20），且 gateway 调用为零。

Windows 原生定向验证（`D:\Miniforge3\python.exe`，`PYTHONPATH=src`）：

- store/service/CLI：`260 passed, 5 skipped`；
- P4/P5/P6/P7 合流扩展回归：`359 passed, 5 skipped`；
- Ruff（3 个源文件和 3 个测试文件）：PASS；
- mypy（store/service/CLI）：PASS。

本补充只表示 Windows 开发合同返工自验通过；独立复验和 WSL base 仍待完成，P8、Linux Gate
和 M4 里程碑均保持开放。

## R3 busy 分类返工补充（2026-08-08）

R2 独立复验确认 exact-set 漂移已关闭，但发现 SQLite 独立 writer lock 的 `TX_BUSY` 被误译为
`SERVICE_EXACT_PENDING_SET_DRIFT`，使 CLI 错误返回 exit 20。R3 只收窄异常分类：只有 store 的
`OUTBOX_DELIVERY_EXACT_SET_DRIFT` 映射确认漂移；busy/事务写失败映射
`SERVICE_EXACT_PENDING_WRITE_FAILED`，CLI 据既有 `WRITE` 合同返回 exit 50
`EXECUTION_RETRY_REQUIRED`。两类失败均 gateway 零调用、无部分 claim。

- Windows P4/P5/P6/P7 合流：`361 passed, 5 skipped`；
- Windows Ruff/mypy：PASS；
- WSL Miniforge base（`/mnt/f` worktree）store/service/CLI：`266 passed, 1 skipped`。

WSL 结果证明 Linux 解释器兼容性，但 worktree 位于 DrvFS，不冒充 ext4 Gate；R3 仍等待新的独立复验。

日期：2026-08-02  
角色：内部实现 Agent  
状态：Windows 工程实现与定向自验通过；等待独立初验与 WSL base 对应验证

## 交付范围

- 新增 `quant.execution.cli.main(argv, *, dependencies) -> int`，唯一命令集合为
  `inspect`、`plan`、`approve`、`paper-submit`、`cancel`、`reconcile`。
- 新增严格依赖端口与可重证输入：receipt-backed target、market/account/planner config、PAPER gateway identity、
  broker retained evidence 均在 CLI 信任边界内重新校验；broker 普通 JSON/dataclass 不是可信入口。
- `approve`、`paper-submit`、`cancel` 使用 canonical JSON + SHA-256 challenge；首次调用不打开 gateway、不调用
  submit/cancel/query，确认调用 fresh recovery/reload 后才执行。
- `paper-submit` 只调用 `ExecutionService.dispatch_commands(command_ids=exact_set)`；确认后新增的命令保持 PENDING，
  不进入 adapter。`cancel` 只调用 P4-C `stage_cancel`/`dispatch_cancel`，不直接调用 cancel transport。
- 输出只包含稳定 schema/action/status/code、公开内容身份和计数；broker order id 在 challenge 中只保留 SHA-256，
  loader/gateway/broker 异常正文、路径、token、账户正文不会进入 stdout/stderr。
- 已完成 approve stage replay、submit 已完成只读重放和 cancel 完成重放，均保持零重复经济影响。

## 关键失败语义

- `2`：exact argparse/用法错误；不存在 `live`、泛化 `submit`、`--yes`。
- `10`：输入、loader/gateway/broker evidence 身份无效。
- `20`：首次 confirmation required，或 fresh challenge 漂移。
- `30`：UNKNOWN、lease/query、intraday reconciliation。
- `40`：recovery/manual/risk Gate blocked。
- `50`：store/dispatch 可重试失败。
- `70`：稳定脱敏内部失败。

旧 confirmation 在 store/source 变化后会按 fresh-recompute 规则返回 drift；操作员重新获取 fresh challenge 后，
已完成 approve/cancel 由 durable service replay 返回成功，已完成 submit 返回只读 `SUBMIT_ALREADY_COMPLETE`。

## Windows 验证

解释器：`D:\Miniforge3\python.exe`，`PYTHONPATH=src`。

1. CLI 定向测试：

   `python -m pytest tests/unit/test_execution_cli.py -q --basetemp .pytest-p6-r1-final2`

   结果：`9 passed`。

2. P4-R/P4-C/P5/P6 合流定向回归：

   `python -m pytest tests/unit/test_execution_store.py tests/unit/test_execution_wire.py tests/unit/test_pretrade_risk.py tests/unit/test_execution_service.py tests/unit/test_reconcile.py tests/unit/test_execution_cli.py -q --basetemp .pytest-p6-r1-expanded2`

   结果：`339 passed, 5 skipped`。

3. 静态检查：

   `python -m ruff check src/quant/execution/cli.py src/quant/execution/cli_ports.py tests/unit/test_execution_cli.py`

   结果：PASS。

   `python -m mypy src/quant/execution/cli.py src/quant/execution/cli_ports.py`

   结果：PASS。

pytest 仅报告工作区 `.pytest_cache` 的 Windows 权限 warning；唯一 basetemp 内的测试及断言均通过。

## 未执行与边界

- 当前会话的 WSL 启动/提权额度受外部权限窗口阻塞，未重复尝试；未取得 WSL Miniforge base 证据。
- 未执行真实 broker、网络或实盘调用；所有外部动作仍固定 PAPER。
- 未修改 store/service/risk/reconcile，也未 git add/commit。
- 本报告只表示 Windows 开发契约通过，不关闭 Linux Gate、P8 四周 PAPER/SHADOW soak、broker live 或 M4 里程碑。
