# M3 G1：分红缺 `ex_date` 窗外跳过外部返工交付报告

- 角色：外部返工实现 Agent（全新会话，`cursor-grok-4.5-high`）
- 任务单：[`M3_G1_分红缺ex_date窗外跳过返工任务单.md`](M3_G1_分红缺ex_date窗外跳过返工任务单.md)
- 诊断证据：`artifacts/g1_component_diag_20260722/event_invalid_enrichment.json`（`600176.SH`，`实施`，`ex_date=null`，`end/record/list` 均在 history 前）
- 白名单：`src/quant/data/m3_execution_facts.py`；`tests/unit/test_m3_execution_facts.py`；本报告
- 状态：返工已落地并自测；**不宣布 G1/Gate 通过**；独立初验由另一全新会话执行

## 1. 改动摘要

在 `select_g1_corporate_actions` 处理 `实施` 且 `ex_date is None` 时：

1. 解析已存在的 `end_date` / `record_date` / `pay_date` / `div_listdate`（非法格式仍 fail closed）；
2. 至少一个可解析日期，且**全部** `< history.start` 或**全部** `> history.end` → `continue`（跳过，不入账）；
3. 无任何可解析日期，或日期落入/跨越窗口 → `G1_CORPORATE_ACTION_EVENT_INVALID`；
4. `ex_date` 非 null 时保持既有必填解析与窗口过滤。

禁止项未触碰：不发明 `ex_date`、不改正式 raw、不削弱 event_id/空腿合同、无 510300/网络。

辅助函数：`_null_ex_date_fully_outside_history`。

## 2. 新增测试

| 测试 | 覆盖 |
|---|---|
| `test_dividend_null_ex_date_fully_before_window_skipped` | 正式形状窗外残缺行跳过；同响应有效实施仍选中 |
| `test_dividend_null_ex_date_fully_after_window_skipped` | 全部支持日 `> history.end` → 跳过 |
| `test_dividend_null_ex_date_in_window_or_spanning_rejected` | 窗内 / 跨越 / 无支持日 / 非法格式 → 仍 `EVENT_INVALID` |
| 既有空腿 / event_id 闭包 / 冲突 | 定向套件内不回退 |

## 3. 验证记录

环境：WSL Miniforge `base`（`/home/mabw/AI_Coding_win/QuantitativeTrading`）。零网络；未用 Windows 绿测冒充 Gate。

### 3.1 定向 pytest

```text
python -m pytest tests/unit/test_m3_execution_facts.py -q \
  -k "corporate_action or ledger or dividend" --durations=10
→ 13 passed, 39 deselected, 560 warnings in 2.49s
```

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
- 实现者自测不能代替独立初验；初验应至少复跑任务书 §4，并对抗确认：窗外 null ex_date 跳过、窗内/跨越拒绝、空腿/闭包/冲突不回退。
