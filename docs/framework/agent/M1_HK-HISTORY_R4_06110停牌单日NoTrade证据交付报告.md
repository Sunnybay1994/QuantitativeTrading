# M1 HK-HISTORY R4：06110.HK 2026-06-25 停牌单日 No-Trade 证据交付报告

日期：2026-08-15（Asia/Shanghai）
实现模型：`cursor-grok-4.6-high`（如实记录；非底层模型名猜测）
角色：外部实现 Agent
状态：**R4 实现与 Windows 定向自测完成；待全新外部独立复验。** R1 阻断、R2 正向 exact 与 R3 UA-M1-005 反向绑定见下文历史章节。未宣称独立初验或 HK60 Gate。

## R1 结果（历史；已关闭）

- 按任务单停止条件与 `AGENTS.md` §11：发现任务单与现行 API/Schema 冲突，且修复必须修改禁区，**立即停止扩大实现**，不自行扩包、不伪 capability。
- 未修改 `src/quant/data/hk_history_backfill.py`、`tests/unit/test_hk_history_backfill.py` 或任何禁区文件。
- 未联网、未读取 token、未 add/commit/push、未写正式 `data/` / `artifacts`、未真实回填。
- 本会话只写入：本报告 + 任务单状态行。

## 冲突（现象—根因—规则—最小复现—通过条件）

**现象：** 任务单 §5/§6 要求 canonical UA-M1-005 经 **public** `load_hk_no_trade_evidence` PASS，且 v2 plan 只扣除 `06110.HK@2026-06-25`。在不改 `schemas.py` 的前提下，该正向路径不可达。

**根因：** `load_hk_no_trade_evidence` 在构造 `HKNoTradeEvidence` 后必须调用 `_verify_evidence_projection`，末尾无条件执行 `HKNoTradeEvidenceSchema.validate(...)`。`HKNoTradeEvidenceSchema.user_approved_consensus_is_exactly_scoped` 只允许两条 exact 例外：

- `01065.HK` / `2026-05-05` / `UA-M1-001` / `ua-m1-001-01065-2026-05-05.record`
- `02402.HK` / 13 个开市日 / `UA-M1-004` / `ua-m1-004-02402-2026-04-01-to-2026-05-04.record`

`source=USER_APPROVED_MULTI_SOURCE_CONSENSUS` 的 `06110.HK@2026-06-25` / `UA-M1-005` 使该 dataframe check 为假，Pandera 抛 `SchemaError`，loader 稳定映射为 `HK_HISTORY_REFERENCE_INVALID`。

另有白名单内第二道门（**可**按任务扩展，但不足以让 loader PASS）：`HKNoTradeEvidence.__post_init__` → `_user_approved_no_trade_is_exact` 目前只认 UA-M1-001/004。

**应遵循规则：**

- 任务单 §4/§7：生产改动只允许 `hk_history_backfill.py`；**禁止修改** `src/quant/domain/schemas.py`。
- 任务单停止条件：actual API 与任务单冲突、必须修改禁区、或必须伪 capability → 停止并提交证据，不自行扩包。
- `AGENTS.md` §11：不得迁就已知错误的任务书；先改权威契约再返工。
- 任务单 §2：不得把该记录标作 `HKEX_DAILY_QUOTATIONS`；不得泛化停牌规则。因此不能靠换 source 或放宽 Schema 通配来绕过。

**最小复现（Windows，无生产改动，未联网）：**

```text
D:\Miniforge3\python.exe -c "<HKNoTradeEvidenceSchema.validate UA-M1-001 vs UA-M1-005>"
```

| 输入 | 结果 |
| --- | --- |
| UA-M1-001 合法行 | schema PASS |
| UA-M1-005 任务单身份行（`06110.HK` / `2026-06-25` / `UA-M1-005` / 指定 selector） | `SchemaError`：`Check user_approved_consensus_is_exactly_scoped` |

调用链：`load_hk_no_trade_evidence` → `_verify_evidence_projection` → `HKNoTradeEvidenceSchema.validate`。绕过 Schema.validate、改 seal/registry、或 `object.__new__` 构造正向 evidence 均为任务单禁止的伪 capability。

**通过条件（需主 Agent 重冻，不由本会话执行）：**

1. 将 `src/quant/domain/schemas.py`（及若需同步的 `tests/unit/test_schemas.py` 定向节点）纳入实现白名单；**或** 明确取消「loader 必须 Schema.validate 同一 dataframe check」的现行契约。
2. Schema 只增加第三条 **exact** 或支：`06110.HK` ∧ `2026-06-25` ∧ `UA-M1-005` ∧ `user-approved-consensus/ua-m1-005-06110-2026-06-25.record`。禁止通配证券/日期，禁止改字段集合。
3. 然后才允许在 `hk_history_backfill.py` 扩展 `_user_approved_no_trade_is_exact` / `_verify_user_approved_no_trade_raw` 并补 §6 测试。

## 未做的实现（故意）

未新增 UA-M1-005 常量、verifier 分支、fixture 或测试。只扩白名单内 verifier 会让 dataclass 过门、Schema.validate 仍失败，形成「实现过半但 public loader 必红」的假进度。

## 验证

| 命令或检查 | 结果 | 摘要 |
| --- | --- | --- |
| 定向阅读任务单 / UA-M1-001/004 实现与测试 | 完成 | 冲突定位到 Schema dataframe check |
| Schema 探针（UA-M1-001 vs UA-M1-005） | 冲突成立 | 005 被 `user_approved_consensus_is_exactly_scoped` 拒绝 |
| 定向 pytest / Ruff / mypy / 真实回填 | 未运行 | 无实现可测；禁止伪绿 |
| 联网 / token / git add-commit-push | 未执行 | 遵守任务单 |

## 残余风险与交接

- 主 Agent 必须先改权威契约（白名单 + Schema 第三条 exact 或支），再开新的外部实现会话。本报告**不是**独立初验入口。
- R3 已证明第三条 user-approved 例外必须同时改 `hk_history_backfill.py` 与 `HKNoTradeEvidenceSchema`；R4 任务单漏掉后者。
- 正式 raw/metadata/plan/journal 物化与 HK60 恢复仍按任务单 §9，本会话未触碰。
- 下一步（当时）：主 Agent 重冻 → 全新外部实现会话按修订后白名单实现 → 另一全新会话独立初验。R2 已执行该实现步。

---

## R2 实现（关闭 R1 阻断）

日期：2026-08-15（Asia/Shanghai）
实现模型：`cursor-grok-4.6-high`（如实记录；非底层模型名猜测）
角色：外部实现 Agent（全新 R2 会话；不复用 R1 上下文）
状态：**R2 实现与 Windows 定向自测完成；待全新外部独立初验。** 不宣称独立初验、真实 plan/journal 物化或 HK60 Gate。

R1 阻断已关闭：主 Agent 已把 `HKNoTradeEvidenceSchema` exact 析取纳入白名单。R2 只增加第三条 exact 或支
`06110.HK ∧ 2026-06-25 ∧ UA-M1-005 ∧ user-approved-consensus/ua-m1-005-06110-2026-06-25.record`，
公共 `load_hk_no_trade_evidence` / `build_hk_history_plan_v2` 正向经 Schema.validate，未使用
`object.__new__`、私有 seal 或绕过 loader。

### 修改文件

| 文件 | 目的 |
| --- | --- |
| `src/quant/domain/schemas.py` | `user_approved_consensus_is_exactly_scoped` 增加 UA-M1-005 exact 析取；列/dtype/source/reason 未改。 |
| `src/quant/data/hk_history_backfill.py` | 新增 UA-M1-005 常量、exact 判定与 canonical halt payload 逐字段/逐字节 verifier。 |
| `tests/unit/test_hk_history_backfill.py` | §6 正向、plan 只减 06-25、request raw closure fixture、漂移/impact/单字节、001/004 identity、hostile。 |
| `tests/unit/test_schemas.py` | UA-M1-005 exact 正向；symbol/date/record/selector 漂移拒绝；001/004 回归。 |
| 本报告 | 追加 R2；保留 R1 为设计纠错证据。 |
| 任务单状态 | 改为待全新外部独立初验。 |

未修改：query、connector、clean store、配置、README、路线图、正式 `data/` / `artifacts`、DailyBasic 或其他 Schema。未联网、未真实回填、未 add/commit/push。

### 冻结的 UA-M1-005 合同

- `source_record_id=UA-M1-005`
- `raw_selector=user-approved-consensus/ua-m1-005-06110-2026-06-25.record`
- `schema_version=hk-no-trade-user-approved-trading-halt-v1`
- exact key：`06110.HK@2026-06-25`；06-24/06-26 及其他证券拒绝
- canonical observations 顺序固定：HKEX_NEWS `TRADING_HALTED_FROM_09_00` + 指定 HKEX URL；Tushare `RETAINED_ZERO_ROW`；独立来源 `LISTED_AS_SUSPENDED` + 指定 etnet URL
- `impact_assessment` 五字段全部 `false`
- UA-M1-001/004 payload、selector、record、identity 公式未改

### 验证（Windows；`PYTHONPATH` 指向本 worktree `src`）

主仓 editable `quant` 指向 `F:\AI_Coding\QuantitativeTrading\src`，定向命令必须覆盖 worktree，否则会测到未含 UA-M1-005 的主树。

| 命令 | 结果 | 摘要 |
| --- | --- | --- |
| pytest `test_hk_history_backfill.py` + Schema 两节点 | 通过 | 135 passed, 2 skipped |
| `ruff check` 四白名单文件 | 通过 | All checks passed |
| `mypy` 两生产文件 | 通过 | no issues found in 2 source files |
| cold import loader/plan/Schema | 通过 | 模块路径位于本 worktree |

未运行 Linux/WSL Gate、全量 pytest、真实回填或联网。

### 风险与交接

- 本实现只改变 expected-key 证据闭包；不改 raw/mapper/OHLC/策略/现金/公司行动/订单语义。
- 正式 raw/metadata、UA-M1-001 ∪ 004 ∪ 005 的新 v2 plan、journal 与 HK60 恢复仍按任务单 §9，由主 Agent 合流后执行；不得改写 v2b。
- 下一步：未参与本 R2 实现的全新外部独立初验；PASS 后主 Agent 再物化业务产物。

---

## R3 实现（关闭 R2 独立初验反向来源绑定缺口）

日期：2026-08-15（Asia/Shanghai）
实现模型：`cursor-grok-4.6-high`（如实记录；非底层模型名猜测）
角色：外部实现 Agent（全新 R3 会话；不复用 R1/R2 上下文）
状态：**R3 实现与 Windows 定向自测完成；待全新外部独立复验。** 不宣称独立初验、真实 plan/journal 物化或 HK60 Gate。

R2 正向 exact 保留：canonical `USER_APPROVED_MULTI_SOURCE_CONSENSUS` + UA-M1-005 仍经公共 loader / Schema.validate。本轮只补身份反向约束：`source_record_id=UA-M1-005` 或 exact selector 出现时，source 必须是 `USER_APPROVED_MULTI_SOURCE_CONSENSUS`，且 symbol/date/record/selector 构成唯一 exact key。未泛化 UA-M1-001/004，未收紧普通 HKEX quotations 通道。

### 修改文件

| 文件 | 目的 |
| --- | --- |
| `src/quant/data/hk_history_backfill.py` | `HKNoTradeEvidence.__post_init__` 对 UA-M1-005 record/selector 强制 USER_APPROVED source。 |
| `src/quant/domain/schemas.py` | 新增 `ua_m1_005_identity_binds_user_approved_source`；列/dtype/001/004 析取未改。 |
| `tests/unit/test_hk_history_backfill.py` | HKEX 伪组合（canonical/garbage/record-only/selector-only）、record/selector 漂移、001/004 与普通 HKEX 控制组。 |
| `tests/unit/test_schemas.py` | Schema 直接拒绝相同伪组合；ordinary HKEX `06110@06-25` 控制组仍通过。 |
| 本报告 | 追加 R3；保留 R1/R2 为设计纠错与正向实现证据。 |
| 任务单状态 | 改为待全新外部独立复验。 |

未修改：query、connector、clean store、配置、README、路线图、正式 `data/` / `artifacts`、R2 独立复验报告。未联网、未真实回填、未 add/commit/push。

### 原因

R2 只在 `source==USER_APPROVED` 时进入 exact/raw verifier；Schema 以“非 USER_APPROVED 或任一 exact 或支”为析取。因此 `HKEX_DAILY_QUOTATIONS` + UA-M1-005 identity（含 garbage raw）可跳过 halt payload 绑定。UA-M1-005 是用户批准共识身份，不是 HKEX daily quotations 证据。

### 验证（Windows；`PYTHONPATH` 指向本 worktree `src`）

解释器：`D:\Miniforge3\python.exe`。主仓 editable `quant` 指向主树，定向命令必须覆盖 worktree。

| 命令 | 结果 | 摘要 |
| --- | --- | --- |
| focused：反向绑定 loader + Schema 节点 | 通过 | 2 passed |
| pytest `test_hk_history_backfill.py` + Schema 两 HKNoTrade 节点 | 通过 | 136 passed, 2 skipped |
| `ruff check` 四白名单文件 | 通过 | All checks passed |
| `mypy` 两生产文件 | 通过 | no issues found in 2 source files |
| cold import loader/plan/Schema | 通过 | 模块路径位于本 worktree |

未运行 Linux/WSL Gate、全量 pytest、真实回填或联网。本会话自测不是独立复验。

### 风险与交接

- 反向约束仅绑定 UA-M1-005 record/selector；普通 HKEX（含 `06110.HK@2026-06-25` 且非 UA-M1-005 身份）与 UA-M1-001/004 行为保持原样。
- 正式 raw/metadata、新 v2 plan、journal 与 HK60 恢复仍按任务单 §9，由主 Agent 在独立复验与主验通过后执行。
- 下一步：未参与本 R3 实现的全新外部独立复验。

---

## R4 实现（关闭 user-approved 命名空间换源缺口）

日期：2026-08-15（Asia/Shanghai）
实现模型：`cursor-grok-4.6-high`（如实记录；非底层模型名猜测）
角色：外部实现 Agent（全新 R4 会话；不复用 R1/R2/R3 上下文）
状态：**R4 实现与 Windows 定向自测完成；待全新外部独立复验。** 不宣称独立初验、真实 plan/journal 物化或 HK60 Gate。

R3 已关闭 UA-M1-005 反向绑定。主验同型检查与 R3 残余确认：合法 UA-M1-001/004 identity 改标 `HKEX_DAILY_QUOTATIONS` 后，public loader 仍可接受（`UA001_SPOOF_ACCEPTED`）。本轮把 R3 的 005-only dataclass/Schema 反向约束提升为命名空间规则：任何 `source_record_id` 以 `UA-M1-` 开头，或 `raw_selector` 以 `user-approved-consensus/` 开头，只能使用 exact `USER_APPROVED_MULTI_SOURCE_CONSENSUS`；随后仍由既有 001/004/005 exact allowlist 限定。未改合法 001/004/005 字段、identity 公式或 canonical raw；未实现或猜测 HKEX HTML parser。

写生产代码前确认：现有普通 HKEX fixture 使用 `synthetic-fixture-record` 与 `hkex/...` selector，不落入该命名空间，无冲突。

### 修改文件

| 文件 | 目的 |
| --- | --- |
| `src/quant/data/hk_history_backfill.py` | `HKNoTradeEvidence.__post_init__` 对 `UA-M1-` record 与 `user-approved-consensus/` selector 强制 USER_APPROVED source。 |
| `src/quant/domain/schemas.py` | 将 `ua_m1_005_identity_binds_user_approved_source` 提升为 `user_approved_identity_namespace_binds_source`；列/dtype/001/004/005 析取未改。 |
| `tests/unit/test_hk_history_backfill.py` | 001/004/005 挂 HKEX：canonical/garbage/record-only/selector-only；普通 HKEX 三证券日控制组；001 helper 支持换源夹具。 |
| `tests/unit/test_schemas.py` | Schema 拒绝 001/004/005 与未知 `UA-M1-006` / 未知 user-approved selector 挂 HKEX/Tushare；ordinary HKEX 控制组仍通过。 |
| 本报告 | 追加 R4；保留 R1/R2/R3 为设计纠错与正向实现证据。 |
| 任务单状态 | 改为待全新外部独立复验。 |

未修改：query、connector、clean store、配置、README、路线图、正式 `data/` / `artifacts`、旧独立报告。未联网、未真实回填、未 add/commit/push。

### 原因

R3 反向约束只枚举 UA-M1-005。projection 对非 USER_APPROVED source 不调用 canonical user-approved raw verifier；Schema 的 exact 析取是 USER_APPROVED → exact 的单向约束。因此 `UA-M1-` record 或 `user-approved-consensus/` selector 可搭载 HKEX source。来源身份是整体合同，反向约束不得按最新记录逐条补丁。

### 验证（Windows；`PYTHONPATH` 指向本 worktree `src`）

解释器：`D:\Miniforge3\python.exe`。主仓 editable `quant` 指向主树，定向命令必须覆盖 worktree。

| 命令 | 结果 | 摘要 |
| --- | --- | --- |
| focused：命名空间 loader + Schema 节点 | 通过 | 4 passed |
| pytest `test_hk_history_backfill.py` + Schema 两 HKNoTrade 节点 | 通过 | 137 passed, 2 skipped（原 136 + 本轮 1 项） |
| `ruff check` 四白名单文件 | 通过 | All checks passed |
| `mypy` 两生产文件 | 通过 | no issues found in 2 source files |
| cold import loader/plan/Schema | 通过 | 模块路径位于本 worktree |

未运行 Linux/WSL Gate、全量 pytest、真实回填或联网。本会话自测不是独立复验。

### 风险与交接

- 命名空间规则覆盖未知 `UA-M1-*` 与未知 `user-approved-consensus/` selector；普通 HKEX（非 UA record、非 user-approved selector，含 01065/02402/06110 同日）仍通过，且仍不解析 quotations HTML。
- 正式 raw/metadata、新 v2 plan、journal 与 HK60 恢复仍按任务单 §9，由主 Agent 在独立复验与主验通过后执行。
- 下一步：未参与本 R4 实现的全新外部独立复验，须对 001/004/005 三条换源攻击独立复验。
