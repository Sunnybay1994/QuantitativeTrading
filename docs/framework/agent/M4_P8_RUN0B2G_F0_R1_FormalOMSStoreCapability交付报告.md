# M4 P8 RUN-0B2G-F0 R1 Formal OMS Store Capability 交付报告

## 1. 结论

主 Agent 已按任务单串行完成 formal OMS `ExecutionStore` 初始化、重启打开与现存 capability 验真。该包只关闭 broker-only runtime 向 broker+runtime materialized 状态的过渡，不宣称 formal service、runner、soak 或 Linux/ext4 Gate 完成。

## 2. 实现

- 新增 `paper_formal_execution_store.py`，提供 initialize/open/verify-existing 三个入口及 process-local capability。
- capability 持有实际打开的 `ExecutionStore`，并绑定 fresh runtime、policy、binding、account 与重新打开的 broker-store capability。
- runtime formal layout 仅将允许 materialized 的角色从 broker 扩为 runtime 与 broker；evidence、anchor、log 继续 fail closed。
- 初始化使用配置派生的 runtime root 与 OMS SQLite 文件名，exclusive 预留 DB 和 canonical `execution-store-instance.json`，复用现有 `ExecutionStore` migration。
- store identity 绑定 runtime config、root/DB 物理实体、schema version、account、policy descriptor 与 gateway identity。
- descriptor 使用双读及前后实体身份检查；普通文件拒绝多硬链接。目录不错误要求 `st_nlink == 1`，以保留未来 ext4 兼容性。
- 失败补偿只处理本次 owned 的 descriptor、DB/WAL/SHM 与空 root；未知文件或实体漂移返回 rollback-required，不递归删除。

## 3. 正常开发检查

- `test_paper_runtime.py`：31 passed、35 skipped。
- formal broker store + formal gateway + formal execution store：15 passed。
- focused formal execution store：包含初始化、restart open、no-clobber、closed capability、hostile verifier rollback 等节点。
- Ruff：通过。
- mypy：3 个生产文件通过。
- cold import/public exports：`RUN0B2G_F0_COLD_IMPORT_PASS`。
- scoped `git diff --check`：通过，仅有既有 Windows LF/CRLF 提示。

首次未指定 basetemp 的 pytest 因系统临时目录历史项权限产生 setup errors；工作树内 basetemp 又被 runtime 的“正式根不得位于项目内”规则正确拒绝。最终使用独立系统临时目录并关闭 pytest cache 后取得上述有效结果，未把两次环境失败计为产品证据。

## 4. 剩余边界

- 尚无 formal `LedgerContextProvider` 与 `ExecutionService` composition root；不能用裸路径、伪造 schedule/source identity 或测试 fixture 代替。
- Linux/ext4 不在本轮用户要求范围内，未执行对应 Gate。
- 未联网、未 add/commit/push、未创建正式运行根或正式 SQLite 产物。
