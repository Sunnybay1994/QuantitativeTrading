# M1 HK-HISTORY R4：06110.HK 2026-06-25 停牌单日 No-Trade 证据交付报告

日期：2026-08-15（Asia/Shanghai）
实现模型：`cursor-grok-4.6-high`（如实记录；非底层模型名猜测）
角色：外部实现 Agent
状态：**阻塞 / 需要主 Agent 重新冻结任务**；未宣称实现完成、独立初验或 HK60 Gate。

## 结果

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
- 下一步：主 Agent 重冻 → 全新外部实现会话按修订后白名单实现 → 另一全新会话独立初验。
