# M3 G1：公司行动 ledger↔evidence `event_id` 闭包返工任务单

- 冻结时间：2026-07-22（Asia/Shanghai）
- 角色：协调 Agent 冻结；交给**全新**外部实现 Agent（`cursor-grok-4.5-high`）
- 诊断证据：
  - [`M3_G1_CANDIDATE_COMPONENT_INVALID_零网络组件级诊断记录.md`](M3_G1_CANDIDATE_COMPONENT_INVALID_零网络组件级诊断记录.md)
  - `artifacts/g1_component_diag_20260722/summary.json`
  - `artifacts/g1_component_diag_20260722/min_repro_end_date_collision.json`（合成最小复现）

## 1. 现象—根因—规则—最小复现—通过条件

| 项 | 内容 |
|---|---|
| 现象 | 正式 full candidate / 组件诊断在 `corporate_action_selection` 失败：`G1_CORPORATE_ACTION_RESULT_INVALID`，触发于 `m3_execution_facts.py::_assert_ledger_evidence_closure` |
| 根因类别 | **实现缺陷**（非正式 raw 损坏、非 SSOT 字段定义错误） |
| 根因 | `event_id` / `economic_event_key` 的哈希输入包含 `end_date`；但 `_assert_ledger_evidence_closure` 用 `(symbol, ex_date, cash, stock, record_date, pay_date, stock_list_date)` 建 `selected_map`，**漏掉 `end_date`**。当同一证券存在两个经济事件（不同 `end_date`）却共享其余匹配字段时，dict 覆盖导致用错误的 `evidence.end_date` 重算 `event_id`，与 ledger 不一致 |
| 应遵循规则 | 选择结果闭包必须用与 `event_id` 同构的身份连接 ledger 与 selected evidence；不得静默丢弃碰撞；`CorporateActionLedgerSchema` 有意不含 `end_date`（账户按除权日），不得为迁就错误 join 而降级 `event_id` 身份 |
| 最小复现 | `artifacts/g1_component_diag_20260722/min_repro_end_date_collision.py`：两行不同 `end_date`、其余经济字段相同 → 断言抛出 `G1_CORPORATE_ACTION_RESULT_INVALID` |
| 通过条件 | 见 §4 |

## 2. 冻结修复方向（不得猜测扩大）

**推荐最小修复**：重写 `_assert_ledger_evidence_closure` 的 ledger↔selected 连接，以 **`event_id` 为键**：

1. 对每个 `selected` evidence 行，用现有 `_event_id_sha256(symbol, end_date, record_date, ex_date, cash, stock)` 得到 expected id；
2. expected id 集合与 `ledger.event_id` 集合必须一一对应（同高、无重复、无缺失）；
3. 对每个匹配对，复核 symbol/ex_date/cash/stock/record_date/pay_date/stock_list_date 一致；
4. 保留既有 per-`economic_event_key` 的 candidate_count / rank / 唯一 rank1 selected 检查。

**明确不要求**（除非测试证明必须）：

- 向 `CorporateActionLedgerSchema` 新增 `end_date` 列（会扩散 candidate/release/schema 合同）；
- 修改正式 raw / journal / receipt；
- 弱化 `event_id` 哈希、静默去重或填充；
- 进入 REFERENCE / PREPARE / PUBLISH；
- 重复五个 510300 正式 API。

若实现中发现 Schema/SSOT 必须改才能保持不变量，**停止扩大实现**，把证据交回协调 Agent 先改权威合同。

## 3. 文件白名单

可写：

- `src/quant/data/m3_execution_facts.py`
- `tests/unit/test_m3_execution_facts.py`
- `docs/framework/agent/M3_G1_公司行动ledger_evidence_event_id闭包外部返工交付报告.md`

只读：其余 `src/`、正式 `data/`、配置、路线图、其他测试。禁止 reset/checkout、批量换行、输出 token。

## 4. 验收命令（WSL Miniforge base）

```bash
cd /home/mabw/AI_Coding_win/QuantitativeTrading
/home/mabw/miniforge3/bin/conda run -n base --no-capture-output python -m pytest \
  tests/unit/test_m3_execution_facts.py -q -k "corporate_action or ledger or dividend" --durations=10
/home/mabw/miniforge3/bin/conda run -n base --no-capture-output python -m ruff check \
  src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py
/home/mabw/miniforge3/bin/conda run -n base --no-capture-output mypy \
  src/quant/data/m3_execution_facts.py
git diff --check -- src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py
```

新增测试至少覆盖：

1. **对抗复现**：两经济事件不同 `end_date`、其余匹配字段相同 → 选择/闭包**通过**（修复后），且两 `event_id` 不同；
2. 既有版本选择 / 冲突 / 空窗行为不回退；
3. 故意篡改 ledger `event_id` 或 selected 字段 → 仍 `G1_CORPORATE_ACTION_RESULT_INVALID`。

实现者自测通过后写交付报告，**不得宣布 G1/Gate 通过**。独立初验由另一全新会话执行。

## 5. 禁止项

- 真实网络；重复 510300 五 identity；改正式 raw/journal/receipt
- 用 Windows 绿测冒充 WSL Gate
- 全量 pytest（除非定向无法排除回归且协调 Agent 另行授权）
- 实现与初验同一会话
