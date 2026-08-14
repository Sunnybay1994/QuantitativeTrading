# M4-P6-R4：PAPER 操作 CLI 独立复验报告

日期：2026-08-08  
角色：未参与 R4 实现的独立复验 Agent  
结论：**PASS**

## 结论摘要

R4 已关闭 R3 的阻断项。`claim_exact_pending_outbox_deliveries` 只把明确的
`OUTBOX_DELIVERY_SELECTED_UNCLAIMABLE` 和 `OUTBOX_DELIVERY_CLAIM_CONFLICT` 翻译为 exact-set
drift；SQLite 查询、claim 写入、savepoint rollback 及外层 transaction commit 失败均保留非
`DRIFT` 稳定边界。service 统一返回 `SERVICE_EXACT_PENDING_WRITE_FAILED`，CLI 稳定返回
exit 50 / `EXECUTION_RETRY_REQUIRED`；所有路径 gateway 零调用、无部分 claim，且对外异常
`cause/context` 均为 `None`。

独立反例同时确认：确认后新增、缺失、未来可用 PENDING，以及全局 LEASED、UNKNOWN 和
claim rowcount fence 冲突仍为 exit 20 / `CONFIRMATION_DRIFT`，gateway 零调用。旧
`dispatch_commands` allowlist 仍只派发选中成员，未选成员保持 PENDING。

## 合同逐项映射

| 合同 | 独立证据 | 结论 |
|---|---|---|
| SQLite query 失败不得冒充集合漂移 | 在 fresh recovery 后用 SQLite authorizer 拒绝 exact query；direct service 返回 `SERVICE_EXACT_PENDING_WRITE_FAILED`，CLI 返回 `50/EXECUTION_RETRY_REQUIRED` | PASS |
| claim 写入失败整体回滚 | `BEFORE UPDATE ... RAISE(ABORT)` 后 delivery 仍为 `PENDING/0`，gateway 0，service/CLI 分别为 retry/exit 50 | PASS |
| savepoint rollback 失败不得冒充 drift | claim trigger 与 authorizer 拒绝 `ROLLBACK SAVEPOINT` 组合注入；外层 transaction 仍整体 rollback，公开语义为 retry/exit 50 | PASS |
| transaction commit 失败不得先 crossing | authorizer 只拒绝 `COMMIT`；事务回滚后仍 `PENDING/0`，service retry、CLI exit 50、gateway 0 | PASS |
| 错误链与内部 sentinel 脱敏 | 上述四类 direct service 异常的 `__cause__`/`__context__` 均为 `None`；CLI stdout 空，stderr 仅稳定 code | PASS |
| 真实集合变化仍是 confirmation drift | 新增、删除、未来 PENDING、LEASED、UNKNOWN 五类 post-confirmation 反例均返回 `20/CONFIRMATION_DRIFT`，gateway 0 | PASS |
| 明确 claim fence 冲突仍是 drift | SQLite trigger `RAISE(IGNORE)` 制造 rowcount 0；CLI 返回 exit 20，delivery 仍 `PENDING/0`，gateway 0 | PASS |
| 旧 allowlist 契约不变 | A/B 均 PENDING 时调用旧 API 只选 A；结果为一项 `SENT/1`、一项 `PENDING/0`，gateway 仅 1 次 | PASS |

## 独立对抗证据

实现者回归主要覆盖 writer busy 和 claim trigger。本轮另外用 SQLite authorizer 注入了 query、
rollback 和 commit 失败，并逐类穿过 direct service 与真实 CLI confirmation 路径：

```text
query    -> SERVICE_EXACT_PENDING_WRITE_FAILED, cause/context none, CLI 50, gateway 0, PENDING/0
claim    -> SERVICE_EXACT_PENDING_WRITE_FAILED, cause/context none, CLI 50, gateway 0, PENDING/0
rollback -> SERVICE_EXACT_PENDING_WRITE_FAILED, cause/context none, CLI 50, gateway 0, PENDING/0
commit   -> SERVICE_EXACT_PENDING_WRITE_FAILED, cause/context none, CLI 50, gateway 0, PENDING/0
```

另一组 post-confirmation 状态变化和 fence 反例：

```text
EXTRA / MISSING / FUTURE / LEASED / UNKNOWN / CLAIM_FENCE
-> exit 20, CONFIRMATION_DRIFT, gateway 0
```

这两组证据证明 retry 与经济集合漂移没有被双向泛化；发送仍只发生在 exact claim 事务
成功提交之后。

## 验证命令与结果

环境均无网络、无 broker，每次 pytest 使用唯一 basetemp。

1. Windows 原生 `D:\Miniforge3\python.exe`，`PYTHONPATH=src`：
   - `pytest tests/unit/test_execution_store.py tests/unit/test_execution_service.py tests/unit/test_execution_cli.py -q -p no:cacheprovider --basetemp .pytest-p6-r4-independent-20260808`
   - 结果：`265 passed, 5 skipped in 16.84s`。
2. Windows 定向 Ruff：store/service/CLI 与三份对应测试，结果 PASS。
3. Windows 定向 mypy：首次 mypy 2.3.0 默认缓存运行报工具内部错误；用唯一缓存目录重跑后
   `Success: no issues found in 3 source files`。
4. WSL Miniforge base，`/mnt/f/.../m3-g8ab-prereq`：
   - 对应 pytest：`270 passed in 21.06s`；
   - 定向 Ruff：PASS；
   - 定向 mypy：`Success: no issues found in 3 source files`。

## 范围与 Gate 边界

- 本轮仅写入本独立复验报告；未修改任何生产代码或实现者测试，未执行 git add/commit。
- WSL 证据来自 `/mnt/f` DrvFS，只证明 WSL base 解释器与当前路径的定向兼容性，不等于
  ext4/Linux 平台 Gate。
- 本 PASS 只关闭 P6 R4 工程合同的独立复验；P8 四周 PAPER/SHADOW soak、broker live、ext4 Gate
  及 M4 里程碑仍保持开放。
