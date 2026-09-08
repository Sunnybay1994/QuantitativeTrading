# M4-P5-P0C Ledger 持久化事务闭包任务单

日期：2026-08-02  
状态：返工实现、外部独立复验与主 Agent 最终验收均已通过；仅关闭 ledger 持久化事务闭包子合同  
权威设计：[`M4_P5-P0恢复与账本持久化前置设计.md`](M4_P5-P0恢复与账本持久化前置设计.md) §4

## 目标与冻结边界

在既有 P0A/P0B 上完成最小 schema v4 与 P4/B5 事务闭包：新增 immutable command ledger context、
单 store canonical checkpoint；扩展唯一 `RecoveryRows`；stage 在 command/outbox/delivery 同一事务写 context
并按首次 account 建 genesis checkpoint；SENT callback 在 event、aggregate、append-only entries、checkpoint
CAS、delivery SENT 同一事务提交。NOT_SENT/UNKNOWN 不写 ledger。

B5 计算只由新的 typed pure adapter 调用既有 `build_ledger_state` / `apply_execution_event` 与公共 wire，
service/store 不复制结算、FX、现金、持仓或 entry 算法。legacy v3 只增表升级；缺 context/checkpoint、旧 opaque
ledger bytes 均保留并在 typed 使用边界 fail closed。

## 接口与失败语义

- `RecoveryRows` 追加 `ledger_contexts`、`ledger_checkpoints`，仍只由
  `ExecutionRepository.read_recovery_rows()` 在单事务快照中读取。
- context keyed by command ID；checkpoint 使用固定版本 key，checkpoint row 额外闭合 `last_entry_id`。
- put context/entry 为 exact bytes 幂等，同 key 异 bytes conflict；checkpoint 使用 expected identity CAS。
- typed adapter 输入 verified checkpoint、command、callbacks、immutable context，输出 verified next state/entries；
  context、state、entry wire 必须 decode 后 identity 与 repository key 闭合。
- 失败只返回稳定 service/store/adapter code，不泄漏 SQL、路径、broker payload 或 traceback。

## 白名单

- `src/quant/execution/store.py`
- `src/quant/execution/migrations/__init__.py`
- `src/quant/execution/migrations/v004_ledger_persistence.py`
- `src/quant/execution/service.py`
- `src/quant/backtest/ledger_adapter.py`
- `tests/unit/test_execution_store.py`
- `tests/unit/test_execution_service.py`
- `tests/unit/test_ledger_adapter.py`
- 本任务单与对应交付报告

`src/quant/execution/__init__.py` 保持 stat-only，不读写；不触正式 G1/M3 数据、journal 或候选目录。

## 必须反例

- stage 缺 context/rule/FX 全事务回滚；genesis origin 冲突 fail closed。
- callback 第二个 entry 写失败时 event/aggregate/entries/checkpoint/SENT 全回滚。
- duplicate callback 不重复经济影响；同 entry ID 异 payload conflict；checkpoint CAS conflict。
- v3 pending row 升级后不伪造 context；缺 context/checkpoint fail closed。
- NOT_SENT/UNKNOWN 不写账；恢复快照原子包含 context/checkpoint；hostile row/legacy ledger wire fail closed。
- 同一 persisted context 重放得到同一 checkpoint identity。

## 验证

Windows 与 WSL Miniforge base 分别运行白名单 Ruff、mypy、定向 pytest；最后检查 git diff/status，保留
既有 `execution/__init__.py` 无关脏改。Windows/DrvFS 绿测不替代 Linux/ext4 或 M4 Gate。
