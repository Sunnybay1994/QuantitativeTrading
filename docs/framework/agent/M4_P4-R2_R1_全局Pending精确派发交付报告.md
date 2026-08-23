# M4 P4-R2 R1：全局 PENDING 精确派发交付报告

日期：2026-08-02  
状态：Windows 实现与定向自验通过；等待独立复验和 WSL base

## 改动与理由

P4-R 的 `dispatch_commands` 是明确 allowlist 合同，不能承担 P6 操作员确认所需的“已确认集合
仍等于完整全局 pending 集合”证明。本轮没有改变该旧接口，而是增加原子 exact-set 路径：

- store 在同一写事务中读取并重建全部 delivery closure；既有 SENT 可保留，但任意 LEASED、
  UNKNOWN、未来 PENDING，或 pending 集合新增/缺失都稳定失败且不产生部分 claim；
- service 将失败翻译为无 cause/context 的 `SERVICE_EXACT_PENDING_SET_DRIFT`，成功时复用既有
  gateway/OMS/ledger 派发公式；
- P6 `paper-submit` 仅在确认 crossing 使用新路径，漂移映射为 exit 20 `CONFIRMATION_DRIFT`。

## 新增反例

- 完整集合匹配成功；新增、缺失和未来 PENDING 整体失败；
- 全局存在 LEASED 或 UNKNOWN 时整体失败；
- 双 worker 对同一 exact set 最多一个成功；
- 确认后并发插入命令时 CLI 返回 20、两个 delivery 均保持 PENDING、gateway 零调用；
- 原 allowlist 测试保留，证明 `dispatch_commands((A,))` 不受新合同影响。

## Windows 验证

解释器：`D:\Miniforge3\python.exe`，`PYTHONPATH=src`。

1. `pytest tests/unit/test_execution_store.py tests/unit/test_execution_service.py tests/unit/test_execution_cli.py -q -p no:cacheprovider --basetemp .pytest-p4r2-r2-20260802`
   → `260 passed, 5 skipped`。
2. `ruff check` 定向检查 store/service/CLI 及对应测试 → PASS。
3. `mypy` 定向检查 store/service/CLI → PASS。
4. P4/P5/P6/P7 合流扩展回归（store、wire、risk、service、reconcile、CLI、report）
   → `359 passed, 5 skipped`。

WSL 启动受当前外部权限额度窗口阻塞，本轮未重试，也没有形成 Linux Gate 证据。本报告不关闭
P6 独立复验、P8 soak、Linux Gate 或 M4。

## R3 错误分类补充（2026-08-08）

独立 R2 复验发现 writer lock 的 `TX_BUSY` 被过度翻译为集合漂移。现已将映射收窄为：只有
`OUTBOX_DELIVERY_EXACT_SET_DRIFT` 返回 `SERVICE_EXACT_PENDING_SET_DRIFT`；其余事务/写失败返回
`SERVICE_EXACT_PENDING_WRITE_FAILED`，由 CLI 映射 exit 50。新增真实独立 SQLite writer lock 的
service 与 CLI 回归，均断言 gateway 0、无经济影响、异常 cause/context 断开。

R3 Windows 合流 `361 passed, 5 skipped`，Ruff/mypy PASS；WSL base 在 `/mnt/f` worktree 对应定向
`266 passed, 1 skipped`。DrvFS 验证不等于 ext4 Gate。
