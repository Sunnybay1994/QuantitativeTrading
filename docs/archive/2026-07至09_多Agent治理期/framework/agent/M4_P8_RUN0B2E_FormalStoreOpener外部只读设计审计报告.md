# M4 P8 RUN-0B2E：Formal Durable Store Initializer/Opener 外部只读设计审计报告

日期：2026-08-12  
角色：外部 Cursor `auto` 只读设计审计 Agent（不参与实现）  
前置：RUN-0A R3、B2B、B2C、B2D R2 工程主验 PASS；用户已批准 formal account SSOT  
结论：**可冻结 RUN-0B2E 为「仅 formal broker store initializer/opener + 最小 runtime 物化契约补丁」；gateway factory/snapshot port 必须分包为 RUN-0B2F，不得与 B2E 合并**

---

## 0. 压缩结论

| 项 | 裁决 |
|---|---|
| 下一最小诚实工程包 | **RUN-0B2E**：formal broker durable store 的 initialize/open capability；fresh 消费 `VerifiedPaperRuntimeEnvironment` + `VerifiedFormalPaperBrokerPolicyBinding` + `VerifiedFormalPaperAccountDescriptor`；持久化 B2D stable `account_id` 与 genesis source identity |
| gateway factory / snapshot port | **必须分包（B2F）**；B1 已有 `DurablePaperGatewayFactory` / `DurablePaperBrokerSnapshotPort`，但仅绑定 development policy；依赖已打开 formal store + fill/fault/clock 装配，超出 store opener 最小面 |
| 阻塞性契约缺口 | **RUN-0A layout 要求五根 sibling 永久 absent**；B2E 首次 `mkdir broker_root` 后，现有 `verify_paper_runtime_environment` / B2C / B2D fresh 链会 **系统性失败** — B2E 任务书必须同步冻结「物化后 layout 验真」或等价 RUN-0A 补丁 |
| B1 policy | **不得放宽** `build_paper_broker_policy_descriptor`；新增 **parallel formal builder**（建议 `build_formal_paper_broker_policy_descriptor`，`classification="formal-paper-simulation"`，`schema_version` 新值或 v2）及 formal-only `_prove_*` 入口 |
| 平台 | Windows/DrvFS 开发兼容定向测试；**不得伪造 ext4 / WSL2 formal 运行证据** |
| Linux Gate | 本审计不宣称；留给后续 ext4 注册与 soak |

---

## 1. 当前工作树事实（B2D 后主验态）

### 1.1 已关闭 capability 链（只读，零 store I/O）

```text
load_paper_runtime_config
  → verify_paper_runtime_environment          [formal: WSL2/ext4/base 硬约束]
  → load_verified_paper_execution_policy      [selector 冻结 paper_a_share_v1]
  → bind_verified_formal_paper_broker_policy
  → load_verified_formal_paper_account_descriptor
       SSOT: formal_paper_a_share_v1 / FORMAL_PAPER_A_SHARE /
             2026-08-10T00:00:00Z / 500000.00 CNY
```

### 1.2 B1 durable store（development-only policy）

- 模块：`paper_broker_store.py`
- 公共：`initialize_paper_broker_store`、`open_verified_paper_broker_store`、`PaperBrokerStore`
- `_prove_policy` **硬拒绝** `classification != "development"`
- SQLite schema 固定 `_SCHEMA_SQL`（metadata/commands/operations/events/journal/checkpoint/…），**无版本迁移路径**；实例创建时一次性 `executescript`
- 物理产物：`store-instance.json`、`initial-account.json`、`sequence-anchors/`、相对文件名 DB

### 1.3 Gateway / CLI ports（未 formal 装车）

- `gateways/paper_durable.py`：`DurablePaperGatewayFactory`、`DurablePaperBrokerSnapshotPort` 已实现，消费 `PaperBrokerStore` + `PaperBrokerPolicyDescriptor`
- `cli_ports.py`：`PaperGatewayFactory`、`BrokerSnapshotPort`、`StoreOpener` 仅为 **Protocol**；无 formal 生产实现
- `service.py`：无 formal/paper_runtime 引用

### 1.4 Formal runtime 配置

- 仓库仅有 `configs/trading/paper_runtime.example.toml`（`development-example`）
- **无** checked-in `PAPER_REAL_TIME` formal runtime TOML；正式五根路径由部署时用户/运维提供，须满足 RUN-0A v2 合同

---

## 2. 为何 gateway factory 必须分包

| 理由 | 说明 |
|---|---|
| 主验边界 | B2D R2 主验明确：**下一包单独冻结 formal store opener** |
| 依赖方向 | Factory 需要已打开 `PaperBrokerStore` + `PaperFillPolicy`/`PaperFaultPlan`/`PaperClock` + `ExecutionCostSchedule`；属于 **transport 装配**，不是 store 身份/Genesis 绑定 |
| 政策合同 | B1 factory 用 development policy builder；formal 需 **新 formal policy descriptor** 与 binding 版本字段 exact 对齐 |
| 测试诚实 | Store opener 可在 **无 dispatch、无 market snapshot、无 service** 下验收；合并会引入 P2B/P4 回归面 |
| 现有代码 | 修改 `paper_durable.py` 为 formal 入口 ≠ store opener；两者白名单文件应互斥 |

**B2F（建议名）**：formal `DurablePaperGatewayFactory` / `DurablePaperBrokerSnapshotPort` wrapper，输入 formal store capability + binding/policy，输出 `VerifiedPaperGateway` / `VerifiedBrokerEvidence`。

---

## 3. RUN-0B2E 建议 exact public API

新模块建议：`src/quant/execution/paper_formal_broker_store.py`（名可微调，但必须与 B1 文件互斥职责）

```python
# __all__ exact 四项 + 能力类型 + 错误类型（与 B2D 模式对齐）
FormalPaperBrokerStoreError
VerifiedFormalPaperBrokerStoreCapability   # process-local; 不可 pickle
initialize_verified_formal_paper_broker_store
open_verified_formal_paper_broker_store
# existing verifier（可选第五项，强烈建议与 B2D 对称）
verify_existing_formal_paper_broker_store_capability
```

### 3.1 `initialize_verified_formal_paper_broker_store`

```python
def initialize_verified_formal_paper_broker_store(
    *,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    binding: VerifiedFormalPaperBrokerPolicyBinding,
    account: VerifiedFormalPaperAccountDescriptor,
    now: datetime,
) -> VerifiedFormalPaperBrokerStoreCapability: ...
```

**语义**：在 `environment.config.broker_root` **首次物化** broker durable 实例；调用 B1 `initialize_paper_broker_store` 内核，但仅通过 formal 窄入口。

### 3.2 `open_verified_formal_paper_broker_store`

```python
def open_verified_formal_paper_broker_store(
    *,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    binding: VerifiedFormalPaperBrokerPolicyBinding,
    account: VerifiedFormalPaperAccountDescriptor,
    now: datetime,
) -> VerifiedFormalPaperBrokerStoreCapability: ...
```

**语义**：在已物化、identity 匹配的 root 上 fresh-open；调用 B1 `open_verified_paper_broker_store`。

### 3.3 `verify_existing_formal_paper_broker_store_capability`

与 B2D 相同模式：exact type + attestation → 全链 fresh 重建 → 逐字段比较 → 返回同一对象。

---

## 4. Capability / descriptor identity 绑定

### 4.1 `VerifiedFormalPaperBrokerStoreCapability` 至少绑定

| 字段 | 来源 |
|---|---|
| `schema_version` | 新常量，如 `formal-paper-broker-store-v1` |
| `classification` | exact `"formal-paper-simulation"` |
| `session_date` | 来自 binding/policy |
| `runtime_environment_identity` | environment.verification_identity |
| `runtime_config_identity` | environment.config.config_identity |
| `execution_policy_identity` | policy.policy_identity |
| `broker_binding_identity` | binding.binding_identity |
| `account_verification_identity` | account.verification_identity |
| `account_id` | account.account_id（stable，跨日） |
| `genesis_source_file_identity` | account.source_file_identity |
| `genesis_raw_sha256` | account.raw_sha256 |
| `formal_policy_descriptor_identity` | 新 formal policy builder 输出 |
| `store_descriptor_identity` | B1 `PaperBrokerStoreDescriptor.descriptor_identity` |
| `gateway_identity` | B1 `PaperBrokerStore.gateway_identity` |
| `broker_root_identity` | 物化后目录 identity（device/inode/mode；**不得**写入 stable account_id） |
| `database_filename` | environment.config.broker_sqlite_filename |
| `oms_separation_proof` | 绑定 `runtime_root` + `oms_sqlite_filename` 的 resolved 路径 identity（证明非祖先） |
| `capability_identity` / `verified_at` | SHA-256 payload + UTC |
| `_attestation` | process-local HMAC；closure 规则同 B2D R2 |

### 4.2 与 B1 descriptor 关系

- B1 `store-instance.json` 继续 authoritative 物理实例身份
- Formal capability 是 **process-local 证明层**，附加 genesis + upstream capability 闭包
- `gateway_identity` 仍由 B1 公式计算；formal capability 必须 **exact 引用** 打开后的值，不得另算

### 4.3 Formal policy descriptor（新增，不修改 development builder）

建议新类型或扩展 `PaperBrokerPolicyDescriptor`：

```text
schema_version = paper-broker-policy-formal-v1   # 或 v2
classification = formal-paper-simulation
adapter/fill/fault/finality 版本 = binding 内 exact 字符串
cost_schedule_identity = policy.cost_schedule_identity
fx_snapshot_identity = None（与 B2B/B2C 一致）
descriptor_identity = canonical digest
```

B1 `_prove_policy` **保持 development-only**；formal opener 内新增 `_prove_formal_policy`，仅 formal 公共 API 可达。

---

## 5. Fresh 调用链（initialize）

```text
1. exact public inputs + UTC(now) ≥ 各 upstream verified_at
2. verify_existing_paper_runtime_preflight(environment)   ← 见 §8 物化契约补丁
3. verify_existing_paper_execution_policy(policy, environment)
4. verify_existing_formal_paper_broker_policy_binding(binding, environment, policy)
5. verify_existing_formal_paper_account_descriptor(account, environment, policy, binding)
6. selector/path 派生：
     broker_root = environment.config.broker_root
     db_name     = environment.config.broker_sqlite_filename
     oms_path    = environment.config.runtime_root / environment.config.oms_sqlite_filename
7. 物化前 layout 断言：broker_root 不存在（initialize）或存在且 identity 匹配（open）
8. build_formal_paper_broker_policy_descriptor(policy, binding) → formal policy
9. prove account.account_descriptor == B1 build 结果（exact PaperAccountDescriptor）
10. prove genesis: account.initial_snapshot.as_of == 2026-08-10T00:00:00Z；金额 SSOT
11. mkdir broker_root（mode 0700，无 symlink/reparse）— **本包首次允许的正根 mkdir**
12. B1 initialize_paper_broker_store(
       root=broker_root,
       database_filename=db_name,
       oms_store_path=oms_path,          # 允许 OMS 尚不存在；须 prove 非祖先
       account=account.account_descriptor,
       policy=formal_policy_descriptor,
       created_at=genesis_as_of,
    )
13. 打开 PaperBrokerStore → verify_fresh()
14. 二次 upstream fresh + store verify_fresh
15. mint VerifiedFormalPaperBrokerStoreCapability + HMAC attestation
```

**Open 路径**：步骤 7 改为 root 已存在 + `store-instance.json` identity 与 capability 期望一致；步骤 11 跳过；调用 `open_verified_paper_broker_store`。

---

## 6. Root / filename 来源（禁止 caller 覆写）

| 参数 | 唯一来源 |
|---|---|
| `broker_root` | `environment.config.broker_root`（FormalPaperRuntimeConfig） |
| `database_filename` | `environment.config.broker_sqlite_filename` |
| OMS 分离证明路径 | `environment.config.runtime_root / environment.config.oms_sqlite_filename` |
| `account` descriptor | `account.account_descriptor`（B2D nested exact 对象） |
| `created_at` | genesis `2026-08-10T00:00:00Z`（必须等于 account genesis，不得用 `now`） |
| policy 版本字段 | binding/policy capability 内 frozen 字符串 |

**禁止**：caller 传入 path、hash、account_id、policy_identity、64hex gateway id、任意 `classification`。

Formal v1 建议冻结 `broker_sqlite_filename` exact 值（与 B2B 对 `oms.sqlite3` 对齐方式相同），例如任务书指定 `paper-broker.sqlite3` 或 `broker.sqlite3` 之一并在 formal runtime TOML 验收。

---

## 7. Genesis 绑定

| 不变量 | 规则 |
|---|---|
| Stable account_id | 仅由 label + genesis UTC + CNY 初始 snapshot 决定；与 B2D 已验一致 |
| Store `initial-account.json` | bytes-exact 等于 B1 wire(account_descriptor)；`created_at` = genesis UTC |
| SQLite `account_state` 初始行 | 等于 genesis snapshot（500000.00 settled/available） |
| Daily snapshot_id | **不得**冒充 account_id；store 内后续变更不影响 stable account_id |
| Genesis source identity | capability 必须绑定 `source_file_identity` + `raw_sha256`；防同 bytes 换 inode |
| Broker `source_identity`（journal） | 来自 store checkpoint；**不同于** genesis source；reconcile 用 broker 侧 |

---

## 8. 阻塞：RUN-0A layout 与物化后 fresh（必须在 B2E 冻结）

当前 `paper_runtime.py`：

- `_build_layout` / `_verify_retained_layout` 要求五根 `runtime/broker/evidence/anchor/log` **均不存在**
- `verify_existing_paper_runtime_preflight` 会 **完整重跑** `verify_paper_runtime_environment`

因此 **initialize 一旦创建 `broker_root`，步骤 2 及所有 B2C/B2D 现有 verifier 永久失败**。

### 8.1 B2E 必须三选一（由主 Agent 冻结，不可留给实现者猜测）

**选项 A（推荐）**：RUN-0A 增量补丁 — 新增 `verify_materialized_formal_paper_runtime_preflight` 或扩展 layout verifier：

- Cold：`roots absent`（现状）
- Materialized：`roots` 存在且 directory identity 匹配 **预计算的 absent-root identity 物化扩展**（新 hash 类型 `materialized-paper-runtime-root-v1`）
- Formal store / 后续 capability 只接受 Materialized 路径

**选项 B**：broker store 物理根 **不在** 五根 sibling 内（**与现有 runtime config SSOT 冲突**，不推荐）

**选项 C**：声明 environment capability 单次有效、物化后禁止 refresh（**破坏 B2D existing verifier 语义**，不推荐）

**审计裁决**：B2E 白名单必须包含 **最小 RUN-0A 物化验真补丁** + formal store opener；否则包不诚实。

---

## 9. SQLite / 迁移 / -store 不变量

| 项 | B2E 范围 |
|---|---|
| Broker SQLite schema | **复用 B1 `_SCHEMA_SQL`**；B2E 不新增 migration |
| 初始化 | 仅 `initialize` 路径执行 `executescript`；`open` 禁止建表 |
| OMS store | B2E **不打开** OMS `ExecutionStore`；仅用路径做祖先隔离证明 |
| WAL/FK/sync | 继承 B1 PRAGMA |
| Journal/CAS | 继承 B1；formal opener 不写入业务 operation |
| Metadata | `store_descriptor_identity`、`policy_identity` 必须绑定 formal policy descriptor |
| Identity drift | 任何 root/device/inode/descriptor 漂移 → fail closed |

---

## 10. No-clobber / reopen / recovery / 错误码

### 10.1 No-clobber

- Initialize：`broker_root` 下 **任一** 预期产物已存在 → 稳定错误（映射 B1 `PAPER_BROKER_ALREADY_EXISTS` 或 formal 包装码）
- B1 `_exclusive_write` / `O_EXCL` 保持；禁止 truncate 已有 DB

### 10.2 Reopen

- 必须 **同一** resolved broker_root + 同一 `database_filename`
- Fresh `verify_fresh()` + upstream capability 全链
- 复制 root → `PAPER_BROKER_IDENTITY_DRIFT`（B1 已有）

### 10.3 Recovery

- B2E **不实现** dispatch recovery；仅保证 open 后 `read_evidence_snapshot` / journal replay 与 B1 一致
- 业务 recovery 留在 P5 + 后续 formal service 包

### 10.4 建议 stable formal 错误码

```text
PAPER_FORMAL_STORE_ENVIRONMENT_INVALID
PAPER_FORMAL_STORE_POLICY_BINDING_INVALID
PAPER_FORMAL_STORE_ACCOUNT_INVALID
PAPER_FORMAL_STORE_LAYOUT_INVALID          # 含物化前后不匹配
PAPER_FORMAL_STORE_ALREADY_EXISTS
PAPER_FORMAL_STORE_NOT_FOUND
PAPER_FORMAL_STORE_POLICY_INVALID
PAPER_FORMAL_STORE_SEPARATION_INVALID      # OMS 路径祖先/同 inode
PAPER_FORMAL_STORE_GENESIS_MISMATCH
PAPER_FORMAL_STORE_STALE
PAPER_FORMAL_STORE_INVALID
```

包装 B1 码时：**不得**暴露 B1 异常 cause/context；formal 层统一脱敏。

---

## 11. 零额外 I/O 边界

**允许**：

- 读：已锚定的 upstream TOML（经 B2D/B2B 路径，不重复读 account 若 capability 已足够 — 但 fresh 必须 re-verify capability，不强制重读 TOML）
- 写：`broker_root` mkdir；B1 initialize 的 JSON/SQLite/anchor 目录
- SQLite：仅 broker DB；**禁止** OMS journal writer

**禁止**：

- network/socket、scheduler、log 文件、evidence/anchor/log root 写入
- 读取 `data/legacy/`、自动发现 repo 外路径
- 创建 runtime/evidence/anchor/log 四根（留给 RUN-0C/D/E）
- wall-clock（仅 caller `now`）

---

## 12. 威胁模型

| 威胁 | 缓解 |
|---|---|
| Development policy/descriptor 混入 formal | 独立 formal builder；public API 拒绝 development classification |
| OMS↔broker 同源/祖先 | B1 `_related` + formal `oms_separation_proof` 双重绑定 config 派生路径 |
| Genesis 替换/同 bytes 换 inode | B2D source identity 绑定 + store `initial-account.json` 与 capability cross-check |
| Symlink/junction/reparse | B1 + RUN-0A 同类 `lstat`/O_NOFOLLOW；Windows reparse 位 |
| 复制 broker root 冒充 | device/inode + instance_nonce + descriptor digest |
| Concurrent 双 initialize | `O_EXCL` + SQLite busy → fail closed |
| Caller 伪造 64hex gateway/store id | 不允许 caller 传入；只输出 mint 结果 |
| Pickle/closure mint | 同 B2D R2：attestation 仅 `_load_impl` 路径；closure 审计 |
| 离线篡改 journal | B1 hash chain 检测；**不声称**防 offline root 替换（同 B2A1 边界） |
| DrvFS 冒充 ext4 Gate | 测试报告只称 Windows 开发兼容 |

---

## 13. 反例矩阵（B2E 验收最小集）

| # | 反例 | 期望 |
|---|---|---|
| 1 | 缺/伪造 B2D account capability | `PAPER_FORMAL_STORE_ACCOUNT_INVALID` |
| 2 | development policy descriptor 初始化 | `PAPER_FORMAL_STORE_POLICY_INVALID` |
| 3 | `replace(policy, classification="formal")` 直传 B1 | 拒绝（B1 已有测试模式） |
| 4 | OMS 路径为 broker 子目录或同路径 | `PAPER_FORMAL_STORE_SEPARATION_INVALID` |
| 5 | broker_root 已存在仍 initialize | `PAPER_FORMAL_STORE_ALREADY_EXISTS` |
| 6 | 未 initialize 即 open | `PAPER_FORMAL_STORE_NOT_FOUND` |
| 7 | genesis 金额或 as_of 与 SSOT 不符 | `PAPER_FORMAL_STORE_GENESIS_MISMATCH` |
| 8 | 篡改 `store-instance.json` 后 open | B1 drift → formal 包装 |
| 9 | 物化 broker_root 后用 **未补丁** runtime preflight 刷新 B2D | 必须失败 → 证明需 §8 补丁 |
| 10 | cross-session 拼接 environment + 他人 store root | layout/config identity 不匹配 |
| 11 | monkeypatch 额外 mkdir/open/sqlite/socket | 零非白名单 I/O |
| 12 | hostile 递归异常 | 稳定码；cause/context None |
| 13 | capability pickle/subclass/duck | TypeError / `PAPER_FORMAL_STORE_INVALID` |
| 14 | cold import 无 mint signer 泄漏 | exact `__all__` |

---

## 14. Windows 验证（不冒充 Linux Gate）

```text
解释器：D:\Miniforge3\python.exe（或任务书指定 Windows Miniforge）
PYTHONPATH=src
pytest tests/unit/test_paper_formal_broker_store.py  # 新文件
合流：test_paper_runtime.py + test_paper_account.py + test_paper_broker_store.py 定向
ruff + mypy 仅白名单文件
```

- 使用 `tmp_path` / 用户态 temp；**不在** DrvFS 创建 `PAPER_REAL_TIME` 正式五根
- formal runtime 探针可 mock `verify_paper_runtime_environment` 产物，但集成测试须用 **development runtime + 测试专用 layout 补丁 hook** 或物化验真 API（任务书必须明确，禁止 silently 跳过 absent-root 不变量）
- WSL pytest 可选兼容证据；**不得**写「ext4 Gate PASS」

---

## 15. 后续依赖（B2E 通过后）

```text
RUN-0B2F  formal durable gateway factory + broker snapshot port
    → RUN-0B3? formal OMS StoreOpener（runtime_root + oms.sqlite3 + ExecutionStore.open）
    → formal LedgerContext / ServiceFactory 装配
    → RUN-0C VerifiedSoakSchedule
    → RUN-0D soak_runtime / module CLI
    → RUN-0E/0F drills + scheduler 定义
    → [用户授权] ext4 五根 + Task Scheduler 一次性注册
    → 真实 ≥28 日 soak
```

B2E **不解锁**：PAPER 正式运行、soak、M4 Gate、auto_trade、TargetLoader（仍待 M3 G7A）。

---

## 16. 严格白名单与停止条件

### 16.1 实现白名单（B2E）

**可写**：

- 新 `src/quant/execution/paper_formal_broker_store.py`（名冻结于任务书）
- **最小** `src/quant/execution/paper_runtime.py` 物化 layout 补丁（若采用 §8 选项 A）
- **最小** `src/quant/execution/paper_broker_store.py`：仅新增 formal policy builder + `_prove_formal_policy`（不得改 development builder 行为）
- 新 `tests/unit/test_paper_formal_broker_store.py`
- 本审计报告 + 实现交付 + 独立初验 + 主验报告

**禁止**：

- 修改 `paper_account.py` / `paper_policy.py` / `paper_broker_binding.py`（除非 RUN-0A 补丁经主 Agent 单独立项）
- 修改 `gateways/paper_durable.py`、`service.py`、CLI soak、P4–P8 语义
- 新增 formal runtime TOML 到 repo（部署侧）
- 放宽 B1 development policy、backfill journal、OMS migration

### 16.2 停止条件

- SSOT 四值未绑定或 genesis 变更未重新批准
- 试图在 B2E 实现 gateway dispatch / service plan / soak / scheduler
- 试图用 Windows 测试代替 ext4 Gate 声明
- 未解决 §8 layout 物化契约即开工
- 要求初始持仓、非 CNY、或放宽 OMS/broker 分离

### 16.3 验收通过条件

1. initialize/open 仅通过 formal 四 capability 输入
2. store 内 account_id / genesis snapshot 与 B2D exact 一致
3. formal policy descriptor 与 binding 版本字段 exact 一致
4. 物化后 upstream fresh 链在补丁 API 下可重建
5. 反例矩阵 §13 全绿；closure/attestation 同 B2D R2 标准
6. 无 ext4/soak/Gate 虚假声明

---

## 17. 参考文件索引

| 文件 | 职责 |
|---|---|
| `paper_runtime.py` | Formal config/layout/platform；**需物化补丁** |
| `paper_policy.py` | Formal execution policy capability |
| `paper_broker_binding.py` | Runtime+policy 绑定 |
| `paper_account.py` | Formal account genesis（B2D） |
| `paper_broker_store.py` | Durable broker 内核（development policy） |
| `gateways/paper_durable.py` | Gateway factory（B2F 前置） |
| `cli_ports.py` | CLI Protocol（未 formal 实现） |
| `configs/trading/accounts/formal_paper_a_share_v1.toml` | Account SSOT |
| `docs/agent/M4_P8_RUN0B2D_R2_*主Agent最终验收报告.md` | B2D 关闭证据 |

---

**审计状态：COMPLETE（只读）**  
**下一动作：主 Agent 依本报告冻结 RUN-0B2E 任务书（含 §8 物化契约裁决），再交外部实现 Cursor `auto`**
