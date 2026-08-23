# M4-P6-R1：PAPER 操作 CLI 独立初验报告

日期：2026-08-02  
角色：未参与实现的独立初验 Agent  
结论：**FAIL**

## 结论摘要

六命令边界、PAPER-only 参数面、challenge 字段与 action 隔离、loader/evidence 重证、durable cancel 路径、
canonical 脱敏输出、退出码和已完成动作的幂等重放整体实现清晰，Windows 定向与合流测试也全部绿色。

但 `paper-submit` 的并发集合闭包违反冻结合同：确认后、exact claim 前新增的 PENDING 命令会留在库中，
CLI 仍派发原确认集合并返回 `0/SUBMIT_COMPLETE`。任务单明确规定集合新增、缺失、UNKNOWN 或 lease drift
均须非零退出，因此本轮独立初验不得通过。

## 合同逐项映射

| 合同 | 证据 | 结论 |
|---|---|---|
| exact 六命令；无 `live`、泛 `submit`、`--yes` | `cli.py` 的 `_COMMANDS` 与 exact argparse；未知命令/参数测试返回 2 | PASS |
| inspect / plan / approve fresh recovery 与输入重证 | `_recover`、`_fresh_plan`、`verify_target_load`、`verify_planning_load`；计划和审批挑战绑定 recovery、plan 与来源身份 | PASS |
| challenge exact 字段、expiry、action 隔离 | `_build_challenge` 只生成九个冻结字段，canonical SHA-256 覆盖全部字段；approve hash 用于 submit 返回 20 | PASS |
| 首次 challenge 零 mutation、零 gateway | approve/submit/cancel 在 `_confirm_or_emit` 前不调用 gateway `open` 或 service；现有测试验证无 submit/cancel crossing | PASS（建议补齐 plan/三类首次 challenge 的 DB 逐字节断言） |
| `paper-submit` exact allowlist | 仅调用 `ExecutionService.dispatch_commands(command_ids=command_ids)`；P4-R 原子 claim 会在选中成员缺失、UNKNOWN 或有效 lease 时写入前整体失败 | PASS |
| 确认后集合新增也必须非零 | CLI 仅核对 adapter 返回集合等于旧 `command_ids`，没有再次证明全局 pending 集合/`recovery_id` 未变化 | **FAIL** |
| cancel 只走 durable service | 只调用 `stage_cancel`、`dispatch_cancel`，未直接调用 cancel transport；完成重放不会再次跨 gateway | PASS |
| broker evidence 可信重证 | port 返回值经 `verify_broker_evidence` 重建证明，再由 `build_broker_snapshot` 建立正式 snapshot；普通异常被稳定 code 隔离 | PASS |
| canonical 脱敏输出与退出码 | stdout 为 canonical JSON，stderr 仅稳定 code；路径、TOKEN、broker text 和底层异常不进入输出 | PASS |
| 重复已完成确认零重复经济影响 | approve replay 不新增 command；submit already-complete 不再 submit；cancel already-completed 不再 cancel | PASS |

## 阻断问题

### P6-R1-01：确认后新增 PENDING 集合漂移被当作成功

- 现象：`tests/unit/test_execution_cli.py:275-299` 的并发插入场景在 service factory 中新增另一个 PENDING
  command；测试却断言确认调用返回 0，并允许新命令保持 PENDING。实际测试稳定复现这一行为。
- 根因：`src/quant/execution/cli.py:216-274` 在 confirmation fresh recovery 时冻结 `command_ids`，随后
  `dispatch_commands` 只精确 claim/派发该旧集合；返回后仅验证 `claimed_count` 与 result item IDs 等于旧集合，
  从未重新验证全局 pending 集合或 recovery closure。P4-R 的 exact allowlist 正确保护了“集合外命令不发送”，
  但它不能替 CLI 证明“已确认集合仍是完整待派发集合”。
- 应遵循规则：任务单第 36-37 行规定 fresh recovery 后 exact command set、store recovery 和 gateway identity
  均匹配，且集合新增、缺失、UNKNOWN 或 lease drift 均非零退出；第 78 行进一步要求并发新增的集合外命令
  绝不发送。
- 最小复现：stage command A → 获取 `paper-submit` challenge → 在确认检查后、exact claim 前 stage command B →
  用旧 challenge 确认。当前结果为 A 被发送、B 保持 PENDING、CLI 返回 `0/SUBMIT_COMPLETE`。
- 新增测试：把现有 `test_submit_never_sends_command_inserted_after_confirmation_check` 的期望改成非零稳定退出，
  并断言 B 不发送；另补确认内成员被删除、改 UNKNOWN、被未过期 lease 的三个反例，均断言 gateway 零调用。
- 通过条件：CLI 在 adapter crossing 前重新证明 recovery/完整 pending 集合仍等于 challenge 冻结值，或由原子
  store/service 公共接口同时验证全局集合闭包；任一新增、缺失、UNKNOWN、lease 漂移均非零退出且不得发送
  错误命令。修复后上述四类反例、P6 定向测试及 P4-R/P4-C/P5/P6 合流回归全部通过。

## 独立对抗核对

- 集合缺失、UNKNOWN、有效 lease：P4-R `claim_selected_outbox_deliveries` 在首写前逐成员验证并整体失败，
  CLI 映射为 query/retry 类非零退出；代码路径未发现部分 claim。
- 集合新增：现有实现者测试本身即构成未公开合同冲突证据，复现为错误的成功退出，见 P6-R1-01。
- approval / submit / cancel challenge 互换：action、subject IDs、source identities 与 gateway identity 都在
  canonical hash 内；任一互换产生 `CONFIRMATION_DRIFT`，不会进入 service/gateway。
- 同 ID 改 payload：target payload 进入 `target_verification_identity`，planning payload由正式 identity builder 重证；
  即便外部 loader 重建同一公开 ID，payload 变化仍导致 challenge source identity 或 plan identity 漂移。
- 异常脱敏：loader、gateway、broker port 的异常均在离开 active exception 后翻译为稳定 code；公开 `main`
  不向调用方抛出带 cause/context 的底层异常。现有 TOKEN/路径正文测试通过。
- inspect / plan /首次 challenge：代码路径均只读 store/recovery 与 loaders；现有测试仅对 inspect 做数据库
  逐字节断言，建议返工测试补齐 plan、approve、paper-submit、cancel 首次调用。
- 重复完成：submit/cancel 的 replay 路径在 gateway 打开前返回；approve 由 durable service 重放，现有计数断言
  证明无重复命令和无重复 adapter crossing。

## 验证证据

Windows 原生解释器：`D:\Miniforge3\python.exe`；`PYTHONPATH=src`；使用独立 basetemp。

1. `python -m pytest tests/unit/test_execution_cli.py -q --basetemp .pytest-p6-independent`
   - 结果：`9 passed`；另有工作区 `.pytest_cache` WinError 5 warning，不影响独立 basetemp 断言。
2. `python -m pytest tests/unit/test_execution_store.py tests/unit/test_execution_wire.py tests/unit/test_pretrade_risk.py tests/unit/test_execution_service.py tests/unit/test_reconcile.py tests/unit/test_execution_cli.py -q --basetemp .pytest-p6-independent-expanded`
   - 结果：`339 passed, 5 skipped`；同一 cache warning。
3. `python -m ruff check src/quant/execution/cli.py src/quant/execution/cli_ports.py tests/unit/test_execution_cli.py`
   - 结果：PASS。
4. `python -m mypy src/quant/execution/cli.py src/quant/execution/cli_ports.py`
   - 结果：PASS，`Success: no issues found in 2 source files`。

当前会话的 WSL 启动/提权额度窗口仍阻塞，依约不重试；未取得 WSL Miniforge base 证据。Windows 绿测不替代
Linux Gate。本报告未修改生产代码或实现测试，未执行 git add/commit。
