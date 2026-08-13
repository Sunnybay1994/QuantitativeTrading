# M4-P8-RUN-0B1：独立 Durable PAPER Broker 交付报告

日期：2026-08-09

角色：实现 Agent

状态：实现与自测完成，待全新上下文独立初验和主 Agent 终验

## 1. 交付范围

本次只在冻结白名单内新增独立 durable PAPER broker；未修改 P4-P8 已验收 CLI/service/OMS store，未创建
正式 runtime/evidence/anchor 根，未注册任务、启动 soak、联网或访问正式 journal。

新增：

- `src/quant/execution/paper_broker_store.py`
  - 稳定 `PaperAccountDescriptor` 与 source-neutral `PaperBrokerPolicyDescriptor`；
  - caller-selected absolute trusted root、独立 SQLite 和 `store-instance.json`；
  - root/DB/account/descriptor 物理身份、nonce、descriptor/account/policy identity 闭包；
  - Windows no-share-delete handle、POSIX no-follow fd identity anchor；
  - canonical command/cancel/event/account/result codec 复用或 fresh 重证；
  - `BEGIN IMMEDIATE` 原子 operation/state/event/journal/checkpoint 更新；
  - append-only hash chain、whole-state checkpoint digest、restart fresh reopen；
  - 显式 `finalize_session`：只有 session operation 与 broker order 均 terminal 且时间闭合后才追加 EOD
    checkpoint；之后拒绝该 session 新 operation。
- `src/quant/execution/gateways/paper_durable.py`
  - 实现既有 `PaperGatewayFactory` 和 `BrokerSnapshotPort` 形态；
  - 复用现有 `PaperGateway` 的纯确定性 callback 计算，所有 crossing result 在返回前持久化；
  - exact retry retained result、attempt fence、UNKNOWN 跨 restart 保留；
  - duplicate callback bytes retained 但账户只记账一次；
  - broker evidence 只从 broker DB fresh 重建，不读取 OMS store；
  - public unexpected failure 统一映射为固定脱敏错误。
- 两个定向测试文件，覆盖 identity/reopen/copy/tamper、Windows replacement guard、busy、exact retry、UNKNOWN、
  duplicate callback、partial fill、cancel late fill/final cancel、pre-commit rollback、post-commit lost return、显式 EOD
  finality 和 fresh restart evidence。

未修改 `gateways/__init__.py`：本包可由明确模块路径导入，不为 convenience export 扩大循环导入面。

## 2. 关键设计选择

1. broker store 与 OMS store 必须由 caller 同时提供独立绝对路径；相同或祖先关系在首次写入前拒绝。
2. `account_id` 绑定一次性 descriptor，而每日 `AccountSnapshot.snapshot_id` 继续按现有领域 builder 计算；二者不混用。
3. SQLite 不依赖 rename 发布；operation、callbacks、account state、journal 和 checkpoint 在同一 immediate transaction
   内提交。busy 单独返回，不伪装 identity drift。
4. journal 不只验证自身 hash chain，还验证 operation request/result、callback ordinal/event wire、所有 mutable state row
   的 checkpoint digest；DB/descriptor/account/file identity 任一漂移均 fresh fail closed。
5. `END_OF_DAY` 不由“当前看起来 terminal”自动推断；必须显式调用 `finalize_session` 追加 session finality journal。
   UNKNOWN、partial/non-terminal、事件时间晚于 finalized_at 均拒绝。
6. 本包 policy 默认 `development`；正式 policy 数值与配置 loader 仍留给 RUN-0B2。本包没有签发 runtime 或 formal
   environment capability。

## 3. 实际验证

Windows 原生 Miniforge：

- `pytest tests/unit/test_paper_broker_store.py tests/unit/test_paper_durable_gateway.py -q`：`16 passed`；
- 对两个生产文件和两个测试文件运行 Ruff：PASS；
- 对两个生产文件运行 mypy：PASS。

WSL Miniforge base，当前 `/mnt/f`：

- 同组 pytest：`16 passed`；
- 同范围 Ruff：PASS；
- 两个生产文件 mypy：PASS；
- fresh process 导入 `quant.execution.gateways.paper_durable`：PASS。

当前 WSL 是 WSL1/DrvFS；以上只证明双平台开发合同兼容，不是 WSL2/ext4 Gate。

## 4. 未关闭与风险

- 尚待未参与实现的全新上下文独立初验和主 Agent 终验；
- RUN-0B2 仍需生产 Target/Planning loader、正式 policy 配置 loader、retained verified RiskDecision 与 ledger context
  闭包；
- RUN-0C/D 仍需 actual WSL2/ext4 environment capability、verified schedule 与 runner 装配；
- 未创建或修改任何正式 PAPER root，未注册/启动 28 天 soak；M4 状态继续
  `WAITING_FOR_SOAK_EVIDENCE`；
- 当前自动测试覆盖事务提交前回滚和提交后 lost-return 两个关键 crash 语义；真实进程 kill / power-loss 与 actual
  ext4 durability 仍属于后续平台 Gate/故障演练证据，未在 DrvFS 上宣称通过。

## 5. 范围检查

- 本实现写入仅限任务书列出的两个生产文件、两个测试文件和本报告；
- `git diff --check` 通过；工作树中其他既有脏文件和历史测试目录均保持未动；
- 未执行 `git add`、`git commit` 或任何正式数据写入。
