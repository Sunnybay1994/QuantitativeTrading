# M3 G1：正式 `G1_CANDIDATE_COMPONENT_INVALID` 零网络组件级诊断记录

- 任务单：[`M3_G1_CANDIDATE_COMPONENT_INVALID_零网络组件级诊断任务单.md`](M3_G1_CANDIDATE_COMPONENT_INVALID_零网络组件级诊断任务单.md)
- 返工任务：[`M3_G1_公司行动ledger_evidence_event_id闭包返工任务单.md`](M3_G1_公司行动ledger_evidence_event_id闭包返工任务单.md)
- 开始时间：2026-07-22（Asia/Shanghai）
- 状态：**续诊进行中**（event_id 闭包已修复并通过阶段验收；新首败为空腿 null 解析）

## 2. 执行进度

| 时间(UTC) | 事件 |
|---|---|
| 14:42 | 任务单冻结；记录创建 |
| 14:46–14:48 | 诊断脚本语法/导入修正（仅 `artifacts/`） |
| 14:48 | WSL base 正式装载开始 |
| 15:07 | `summary.json`：首败 `corporate_action_selection` / `G1_CORPORATE_ACTION_RESULT_INVALID` |
| 15:30 | enrich v1 在 `select` 的 `__post_init__` 抛错，未写出样本 |
| 15:53–16:02 | enrich v2 + 合成最小复现；正式首败样本落地 |

## 3. 约束复核

| 项 | 状态 |
|---|---|
| 零网络 | 是 |
| 不改正式 raw/journal/receipt | 是 |
| 不重复五个 510300 API | 是 |
| 不进入 REFERENCE/PREPARE/PUBLISH | 是 |
| 基金 mapper 已排除 | 是 |

## 4. 证据路径

- `artifacts/g1_component_diag_20260722/summary.json`
- `artifacts/g1_component_diag_20260722/min_repro_end_date_collision.json`
- `artifacts/g1_component_diag_20260722/corp_action_enrichment.json`
- 脚本：`diagnose_component_invalid.py` / `enrich_corp_action_v2.py` / `min_repro_end_date_collision.py`

## 5. 首个失败不变量（结论）

| 项 | 值 |
|---|---|
| stage | `corporate_action_selection` |
| 稳定码 | `G1_CORPORATE_ACTION_RESULT_INVALID` |
| 位置 | `m3_execution_facts.py::_assert_ledger_evidence_closure` |
| 正式首败证券 | `600930.SH`（checked_before_fail=90） |
| 分支 | `selected_map_key_collision` |
| 样本 | `ex_date=2026-02-11`，`cash=0.03`，`stock=0`，`record=2026-02-10`，`pay=2026-02-11`；两个不同 `end_date`：`2026-01-08` 与 `2025-09-30` |

### 根因

`event_id` / `economic_event_key` 含 `end_date`，但闭包 join 键漏掉 `end_date`，dict 覆盖后用错误 evidence 重算 `event_id`。合成复现独立证明同码失败。`CorporateActionLedgerSchema` 有意不含 `end_date`，故修复应改用 `event_id` 连接，而非降级身份或静默填充。

### 已排除的前置层

- daily/adj_factor 严格映射、`apply_adjustment_factors_strict`、stk_limit、suspend、benchmark、510300 mapper

## 6. 分流建议（已执行）

1. **event_id 闭包漏 end_date**：实现返工已完成并阶段验收（见闭包任务/初验/主验记录）。
2. **新首败**（修复后暴露）：`G1_EXECUTION_FACT_VALUE_INVALID` @ `_parse_strict_scalar`；正式样本 `000793.SZ` 实施行 `stk_div=1.2` 且 `cash_div_tax=null`。已冻结 [`M3_G1_分红实施行空腿解析返工任务单.md`](M3_G1_分红实施行空腿解析返工任务单.md)。

禁止改 receipt；不得宣称 candidate/HISTORY Gate 通过。
