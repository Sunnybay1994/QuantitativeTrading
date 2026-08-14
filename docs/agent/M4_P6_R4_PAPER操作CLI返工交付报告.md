# M4 P6 R4：PAPER 操作 CLI 返工交付报告

日期：2026-08-08  
状态：实现与主 Agent 定向验证通过；等待全新独立复验

## 返工闭包

R3 独立复验发现：全局 pending 集合已经验真后，SQLite trigger 导致的 claim 写失败仍被 store 误报为
`OUTBOX_DELIVERY_EXACT_SET_DRIFT`，进而让 service/CLI 返回确认漂移。根因是 exact wrapper 捕获了
`claim_selected_outbox_deliveries` 的全部异常并统一改写。

R4 将失败语义分为两类：只有 `OUTBOX_DELIVERY_SELECTED_UNCLAIMABLE` 和
`OUTBOX_DELIVERY_CLAIM_CONFLICT` 这两个可证明的集合/fence 变化映射为 exact-set drift；SQLite 查询、
claim、rollback、事务及其他写失败统一保持非 `DRIFT` 的稳定 store code，由 service 映射为
`SERVICE_EXACT_PENDING_WRITE_FAILED`，CLI 映射 exit 50 / `EXECUTION_RETRY_REQUIRED`。转换后的稳定异常在
active handler 外抛出，`cause/context` 为空。

新增三层真实 SQLite `BEFORE UPDATE ... RAISE(ABORT)` 回归：store 原子回滚、service gateway 零调用、CLI
exit 50，且 delivery 保持 `PENDING/attempt_count=0`。原有新增/缺失/未来 PENDING、LEASED/UNKNOWN、双
worker 与旧 allowlist 测试保持。

## 验证

- Windows 五文件扩展定向回归：`297 passed, 5 skipped`。
- WSL Miniforge base、`/mnt/f` 对应回归：`301 passed, 1 skipped`。
- 两平台定向 Ruff：PASS；mypy 三个生产文件：PASS。

WSL 结果位于 DrvFS，只是兼容性验证，不关闭 ext4、P8 soak 或 M4 Gate。未执行网络/broker 调用，未
git add/commit。

