# M3 G1：分红实施行缺 `ex_date` 窗外跳过返工任务单

- 冻结时间：2026-07-23（Asia/Shanghai）
- 前置：event_id 闭包、空腿 null 解析均已阶段验收
- 诊断：
  - `summary.json`：`G1_CORPORATE_ACTION_EVENT_INVALID` @ `_parse_optional_date8`
  - `artifacts/g1_component_diag_20260722/event_invalid_enrichment.json`

## 1. 现象—根因—规则—最小复现—通过条件

| 项 | 内容 |
|---|---|
| 现象 | `corporate_action_selection` 因实施行 `ex_date=null` 在必填解析处失败 |
| 正式样本 | `600176.SH`（checked=163）：`实施`，`ex_date=null`，`end_date=20140319`，`record_date=20140418`，`div_listdate=20140820`，`stk_div=0.1106`；history=`2015-10-09..2026-07-10` |
| 根因类别 | **实现合同缺口**：窗外残缺实施行在能证明不可入账前就必填失败，阻塞整证券选择 |
| 根因 | 代码对所有 `实施` 行立即 `ex_date` required；无法先用其他日期证明该行完全落在 history 窗外并跳过；禁止发明 `ex_date` |
| 应遵循规则 | 不发明除权日；不静默填日期。若残缺行可证明与 history 无交集则 **skip**；若可能落入窗内则 **fail closed** |
| 最小复现 | 合成：实施 + null ex_date + record/list/end 均 `< history.start` → 整响应其他有效实施仍可通过；实施 + null ex_date + list/record 落在窗内 → 仍 `G1_CORPORATE_ACTION_EVENT_INVALID` |
| 通过条件 | §4 |

## 2. 冻结修复方向

在 `select_g1_corporate_actions` 处理 `实施` 且 `ex_date is None` 时：

1. 尝试解析 `end_date` / `record_date` / `pay_date` / `div_listdate` 中**已存在**的日期（非法格式仍 fail closed）；
2. 若至少有一个可解析日期，且**所有**可解析日期均 `< history.start` 或均 `> history.end`，则 `continue`（跳过该行）；
3. 若没有任何可解析日期，或可解析日期与窗口可能相交（跨越/落入），则 `G1_CORPORATE_ACTION_EVENT_INVALID`；
4. `ex_date` 非 null 时保持既有必填解析与窗口过滤。

禁止：用 list/record 冒充 ex_date 写入 ledger；改正式 raw；削弱 event_id/空腿合同；REFERENCE/PREPARE/PUBLISH；510300 重请求。

## 3. 白名单

- `src/quant/data/m3_execution_facts.py`
- `tests/unit/test_m3_execution_facts.py`
- `docs/framework/agent/M3_G1_分红缺ex_date窗外跳过外部返工交付报告.md`

## 4. 验收（WSL base）

```bash
/home/mabw/miniforge3/bin/conda run -n base --no-capture-output python -m pytest \
  tests/unit/test_m3_execution_facts.py -q -k "corporate_action or ledger or dividend" --durations=10
/home/mabw/miniforge3/bin/conda run -n base --no-capture-output python -m ruff check \
  src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py
/home/mabw/miniforge3/bin/conda run -n base --no-capture-output mypy src/quant/data/m3_execution_facts.py
git diff --check -- src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py
```

新增测试：窗外 null ex_date 跳过；窗内/相交 null ex_date 拒绝；既有空腿/闭包/冲突不回退。
