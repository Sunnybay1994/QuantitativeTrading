# M4 P8 RUN-0B2G-F0 R1 Formal OMS Store Capability 任务单

状态：主 Agent 串行实现与 Windows 开发检查完成；尚未执行 Linux/ext4 Gate，后续 service 组合仍待实现。

## 1. 目标

在 broker root/store/gateway 已 formal 化之后，安全 materialize `runtime_root`，exclusive 初始化现有 `ExecutionStore`，签发 stable OMS store identity 与 process-local capability，并返回与“broker + runtime 两根均已 materialized”状态一致的 fresh runtime/policy/binding/account/broker-store chain。

本包不实现 LedgerContextProvider、ServiceFactory、CLI、runner、schedule 或 soak。

## 2. 核心不变量

1. 路径只来自 exact `FormalPaperRuntimeConfig.runtime_root` 与 `oms_sqlite_filename`；caller 不得传 root、URI、filename 或 identity。
2. 输入为现有 exact broker store capability + environment/policy/binding/account；初始化前先 fresh 验证 broker chain。
3. 原子创建唯一 owned `runtime_root`，随后重新通过 public runtime/policy/binding/account API 构造两根 materialized chain，并用 public broker-store opener重签 broker capability；旧 broker-only capability从此自然 stale。
4. OMS DB leaf 先以 exclusive create 预留并绑定实体，再由 actual `ExecutionStore.open("sqlite:///<filename>", trusted_root=runtime_root)` 执行现有 migration；不得复制 schema/migration。
5. exclusive 写 `execution-store-instance.json`；store identity绑定 schema、runtime config、root/db物理身份、DB filename、ExecutionStore schema version、stable account id、formal B1 policy descriptor identity与gateway identity。SQLite WAL/SHM是允许的运行时 sidecar，不是独立身份来源。
6. capability持有同一打开的 `ExecutionStore`、fresh materialized chain与重签 broker capability；existing verifier重新验证所有实体、descriptor、schema和上游chain，成功返回同一对象。
7. 初始化失败只清理本次 owned、实体未漂移的 DB/sidecar/descriptor/空root；有未知文件或身份漂移则保留现场并返回 rollback-required，禁止递归删除。

## 3. Runtime 最小演进

formal layout 从“仅 broker 可 materialized”窄扩为“broker 与 runtime 可 materialized”；evidence/anchor/log仍必须 absent。已有 cold、broker-only语义与identity不变。任何放宽到其他root、链接/reparse或任意目录均禁止。

## 4. Public API

新增 `quant.execution.paper_formal_execution_store`：

- `FormalPaperExecutionStoreError`
- `VerifiedFormalPaperExecutionStoreCapability`
- `initialize_verified_formal_paper_execution_store(...)`
- `open_verified_formal_paper_execution_store(...)`
- `verify_existing_formal_paper_execution_store_capability(...)`

稳定错误族：`PAPER_FORMAL_EXECUTION_STORE_INVALID`、`..._ALREADY_EXISTS`、`..._NOT_FOUND`、`..._STALE`、`..._ROLLBACK_REQUIRED`。所有 public cause/context 为空。

## 5. 白名单与检查

- `src/quant/execution/paper_runtime.py`（只扩 exact runtime role）
- `src/quant/execution/paper_formal_execution_store.py`（新增）
- `src/quant/execution/__init__.py`
- `tests/unit/test_paper_formal_execution_store.py`（新增）
- `tests/unit/test_paper_runtime.py`（仅同步 exact materialized-role 回归）
- 本任务单与唯一交付报告

定向覆盖：cold→broker-only→broker+runtime正向、no-clobber、restart open、old broker capability stale/new capability fresh、closed/tampered/cross-chain、DB/descriptor/root replacement、unknown-file rollback保护、hostile exception脱敏、原runtime/broker/formal gateway邻接、Ruff/mypy/cold import。

若需要修改 `ExecutionStore` schema/migration、broker store、gateway、service、config或创建其他正式root，立即停止重冻。
