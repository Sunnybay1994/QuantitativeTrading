# M4 P8 RUN-0B2E R1：Formal Durable Store Initializer / Opener 任务单

日期：2026-08-12  
状态：**R2 主 Agent 串行返工与 Windows 工程主验 PASS；允许进入 RUN-0B2F 设计/实现；Linux/ext4 Gate 仍开放**  
前置：RUN-0A R3、B2B、B2C、B2D R2、B2E-F0 R1 均已工程主验 PASS

## 1. 唯一目标

新增 formal PAPER broker durable store 的首次初始化、fresh reopen 与 existing capability 验真。入口只消费 exact formal runtime、execution policy、broker policy binding 与 account genesis capability；root、SQLite 文件名、OMS 分离路径、account、policy identity 均从这些 capability 派生，caller 不得提供 path、classification、identity 或 descriptor。

本包只做 store。gateway factory、snapshot port、service、CLI、soak、scheduler、正式 root 注册均不在范围内。

## 2. 冻结 public API

新模块 `src/quant/execution/paper_formal_broker_store.py` exact 导出：

- `FormalPaperBrokerStoreError`
- `VerifiedFormalPaperBrokerStoreCapability`
- `initialize_verified_formal_paper_broker_store`
- `open_verified_formal_paper_broker_store`
- `verify_existing_formal_paper_broker_store_capability`

三入口共同输入：

```python
environment: VerifiedPaperRuntimeEnvironment
policy: VerifiedPaperExecutionPolicy
binding: VerifiedFormalPaperBrokerPolicyBinding
account: VerifiedFormalPaperAccountDescriptor
now: datetime  # exact aware UTC
```

`VerifiedFormalPaperBrokerStoreCapability` 是 process-local、不可 pickle、不可由 public constructor / `object.__new__` / subclass / clone 消费的 exact capability。它封装实际已打开且未关闭的 `PaperBrokerStore`（不持久保存 SQLite connection）；后续 B2F 只从该 capability 取得受控 store，不再接受 caller path reopen。能力至少绑定：schema/classification/session、materialized runtime/config identity、policy/binding/account verification identity、stable account_id、genesis source identity/raw hash、formal policy descriptor identity、store descriptor/gateway identity、broker root identity、database filename、OMS separation proof、capability identity、verified_at 与私有 attestation。

## 3. Cold initialize 严格时序

1. exact type/UTC 与 `now >= verified_at` 预检；broker root 必须 cold absent。
2. 分别 fresh 验证 cold environment、policy、binding、account，返回必须 exact type/value；不得缓存 caller 自报字段。
3. root 与文件名只取 `environment.config.broker_root`、`broker_sqlite_filename`；OMS 路径只取 `runtime_root / oms_sqlite_filename`，必须非同一路径且互不为祖先。
4. 以独占 no-clobber `mkdir(mode=0o700)` 创建 broker root，立即记录真实 root dev/inode/mode/parent identity；并发已存在稳定拒绝。
5. **旧 cold capability 至此失效，不得继续消费。** 从同一 config public 重新签发 broker-materialized environment，再依次 fresh load policy、bind formal broker policy、load formal account；新链的业务值必须与 cold 输入逐项 exact 相等，但 runtime/layout/verification identity 必须反映 materialized root。
6. 构造 formal broker policy descriptor，调用唯一 B1 `initialize_paper_broker_store` 初始化 JSON/SQLite/anchors；`created_at` exact 等于 B2D genesis，不得使用 `now`。
7. `store.verify_fresh()`，交叉验证 store account descriptor、initial snapshot/account_id、formal policy identity、root/db实体与 materialized chain。
8. 再 fresh materialized 四 capability 与 store，最后一步才 mint formal store capability。

## 4. Open / existing

- `open` 只接受 broker-materialized environment；fresh 四 capability 后调用 B1 `open_verified_paper_broker_store`，逐项交叉验证并 mint 新 capability。
- `existing` 先验 exact type、attestation、同一未关闭 store，再执行 `store.verify_fresh()` 与完整 materialized upstream fresh 重建，逐字段 exact compare；成功返回传入同一对象。
- copied root、same-bytes inode/root replacement、descriptor/account/policy/database/journal drift、closed store、cross-session/env/policy/binding/account 混配均 fail closed。

## 5. B1 policy descriptor 最小演进

只在 `paper_broker_store.py` 做必要兼容：

- `PaperBrokerPolicyDescriptor.classification` 精确收窄为 `Literal["development", "formal-paper-simulation"]`；
- 现有 `build_paper_broker_policy_descriptor`、development schema/identity/行为逐字保持；
- 新增 `build_formal_paper_broker_policy_descriptor`，只接受 exact `VerifiedPaperExecutionPolicy + VerifiedFormalPaperBrokerPolicyBinding`（或等价窄字段输入但 caller 不得传 classification/identity），版本、cost/fx 必须逐项 exact；
- `_prove_policy` 按 exact classification 验证各自 canonical schema/identity，拒绝任意其他字符串与手工 replace；
- B1 SQLite schema、journal、gateway identity、store descriptor 不复制、不迁移、不放宽。

## 6. Owned rollback / no-clobber

初始化失败时，只能清理本次调用明确创建且仍处于同一 recorded root dev/inode 下的 exact owned 产物：broker DB及本次 SQLite sidecar、`store-instance.json`、`initial-account.json`、空 `sequence-anchors/`，最后仅当 root 为空且 identity 未漂移时移除 root。

出现未知文件/目录、root/parent identity 漂移、并发写入、无法证明产物为本次创建、store 无法安全 close 或补偿失败时，立即停止清理并返回稳定 rollback-required 错误，保留现场；严禁递归删除、通配删除或触碰外来内容。B1 initializer 应跟踪本次创建的产物并精确补偿；formal wrapper只负责其 owned 空根。

## 7. 稳定错误

- `PAPER_FORMAL_STORE_ENVIRONMENT_INVALID`
- `PAPER_FORMAL_STORE_POLICY_BINDING_INVALID`
- `PAPER_FORMAL_STORE_ACCOUNT_INVALID`
- `PAPER_FORMAL_STORE_LAYOUT_INVALID`
- `PAPER_FORMAL_STORE_ALREADY_EXISTS`
- `PAPER_FORMAL_STORE_NOT_FOUND`
- `PAPER_FORMAL_STORE_POLICY_INVALID`
- `PAPER_FORMAL_STORE_SEPARATION_INVALID`
- `PAPER_FORMAL_STORE_GENESIS_MISMATCH`
- `PAPER_FORMAL_STORE_ROLLBACK_REQUIRED`
- `PAPER_FORMAL_STORE_STALE`
- `PAPER_FORMAL_STORE_INVALID`

所有 public 失败 cause/context 为 `None`，不得泄露 path、inode、金额、SQL、raw 或 hostile marker。

## 8. I/O 边界

允许：fresh 上游读取其唯一配置；首次创建 broker root；B1 创建唯一 broker JSON/SQLite/anchor tree；open/verify 只读/验真 broker store。禁止：打开 OMS store、创建 runtime/evidence/anchor/log 四根、network/socket、业务 dispatch、log、wall-clock、data/legacy、正式运行或自动交易。

## 9. 必测反例

1. cold initialize → materialized 四 capability → store → formal capability 正向；旧 cold capability失效。
2. materialized open / existing 返回同一对象；capability 内 store可安全消费且 closed 后拒绝。
3. development、fake/subclass/duck/object.__new__/pickle/reload、cross capability/session拒绝。
4. caller 无 path/classification/id入口；OMS与broker同路径/祖先拒绝。
5. broker 已存在 initialize拒绝；未初始化 open拒绝；任何现有文件不覆盖。
6. genesis as_of/CNY/500000.00/account_id/source identity 任一漂移拒绝；daily snapshot_id 不得冒充 account_id。
7. formal policy descriptor versions/cost/fx 与 policy+binding exact；development builder回归不变。
8. root/parent/db/descriptor/account/policy/journal replacement或whole-rehash拒绝。
9. 每个 mkdir/write/SQLite/schema/descriptor/fresh/mint 阶段 fault injection；只删 owned exact 产物；未知并发文件导致保留现场与 rollback-required。
10. public callable closure 无 raw mint/generic signer；constructor/new/clone字段漂移拒绝。
11. hostile recursive exception脱敏；除唯一 broker tree 外零额外 I/O。
12. cold import不加载 gateway/service/CLI/soak/reporting/backtest重依赖。

## 10. 白名单

允许修改：

- 新 `src/quant/execution/paper_formal_broker_store.py`
- `src/quant/execution/paper_broker_store.py`（formal policy builder/prover + owned 初始化补偿的最小改动）
- `src/quant/execution/__init__.py`（必要安全导出）
- 新 `tests/unit/test_paper_formal_broker_store.py`
- `tests/unit/test_paper_broker_store.py`（仅 B1 formal policy/rollback 回归）
- 本任务状态、唯一交付报告、独立初验报告、主验报告

禁止修改 runtime/F0、policy、binding、account、gateway、service、CLI、soak、config、schema/enums、正式 roots/data/journal。

## 11. 验证与通过条件

当前用户暂不考虑 Linux 实现/Gate。Windows Miniforge 运行：新 focused tests；runtime+policy+binding+account+broker-store 邻接；Ruff；mypy；cold import；scoped diff-check。不得把 Windows/DrvFS 绿测写成 ext4 或正式 Gate。

通过条件：actual cold→owned materialization→materialized fresh四链→B1 store→formal capability完整闭环；store/genesis/policy/identity exact；rollback无误删；全部反例绿色。若必须修改 F0/B2B/B2C/B2D、复制 B1 schema、接受 caller path/裸 descriptor、实现 gateway/service/soak，立即停止并重冻。
