# M3 G1：公司行动 ledger↔evidence `event_id` 闭包外部返工交付报告

- 角色：外部返工实现 Agent（全新会话，`cursor-grok-4.5-high`）
- 任务单：[`M3_G1_公司行动ledger_evidence_event_id闭包返工任务单.md`](M3_G1_公司行动ledger_evidence_event_id闭包返工任务单.md)
- 诊断证据：[`M3_G1_CANDIDATE_COMPONENT_INVALID_零网络组件级诊断记录.md`](M3_G1_CANDIDATE_COMPONENT_INVALID_零网络组件级诊断记录.md)
- 白名单：`src/quant/data/m3_execution_facts.py`；`tests/unit/test_m3_execution_facts.py`；本报告
- 状态：返工已落地并自测；**不宣布 G1/Gate 通过**；独立初验由另一全新会话执行

## 1. 改动摘要

重写 `_assert_ledger_evidence_closure` 的 ledger↔selected 连接，以 **`event_id` 为键**：

1. 对每个 `selected` evidence 行，用既有 `_event_id_sha256(symbol, end_date, record_date, ex_date, cash, stock)` 得到 expected id；
2. expected id 集合与 `ledger.event_id` 集合必须一一对应（同高、无重复、无缺失）；
3. 对每个匹配对，复核 symbol/ex_date/cash/stock/record_date/pay_date/stock_list_date 一致；
4. 保留既有 per-`economic_event_key` 的 candidate_count / rank / 唯一 rank1 selected 检查。

未改：`CorporateActionLedgerSchema`、`event_id` 哈希输入、正式 raw/journal/receipt、510300 五请求。

## 2. 新增测试

| 测试 | 覆盖 |
|---|---|
| `test_dividend_distinct_end_dates_same_ex_fields_pass_closure` | 对抗复现：两经济事件不同 `end_date`、其余匹配字段相同 → 选择/闭包通过，两 `event_id` 不同 |
| `test_ledger_evidence_closure_rejects_tampered_event_id_or_fields` | 篡改 ledger `event_id`，或篡改 selected `pay_date`（不在 event_id 哈希内）→ 仍 `G1_CORPORATE_ACTION_RESULT_INVALID` |
| 既有 `test_dividend_empty_and_out_of_window_ignored` / `test_dividend_selection_order_duplicate_and_conflict` 等 | 版本选择 / 冲突 / 空窗不回退（定向套件内绿） |

## 3. 验证记录

环境：WSL Miniforge `base`（`/home/mabw/AI_Coding_win/QuantitativeTrading`）。未用 Windows 绿测冒充 Gate。

### 3.1 定向 pytest

```text
python -m pytest tests/unit/test_m3_execution_facts.py -q \
  -k "corporate_action or ledger or dividend" --durations=10
→ 7 passed, 39 deselected, 368 warnings in 4.12s
```

含新增两项与既有 dividend 选择/冲突/空窗相关用例。

诊断脚本 `artifacts/g1_component_diag_20260722/min_repro_end_date_collision.py`
（仍期望旧 bug 抛错，故 exit 1）修复后输出 `assert_raised: false`，与单元对抗复现一致。

### 3.2 静态

```text
python -m ruff check src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py
→ All checks passed!

mypy src/quant/data/m3_execution_facts.py
→ Success: no issues found in 1 source file

git diff --check -- src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py
→ EXIT 0
```

## 4. 未做 / 剩余风险

- 未跑正式 full candidate / HISTORY / REFERENCE / PREPARE / PUBLISH。
- 未重复 510300 五 identity；未改正式数据。
- 未跑全量 pytest。
- 实现者自测不能代替独立初验；初验应至少复跑任务书 §4 命令，并对抗确认：双 `end_date` 碰撞通过、篡改仍拒、既有冲突/空窗不回退。
