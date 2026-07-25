# M3 G1：公司行动 ledger↔evidence `event_id` 闭包外部独立初验报告

| 项 | 内容 |
|---|---|
| 角色 | 外部独立初验 Agent（全新会话，未参与本返工实现） |
| 模型 | `cursor-grok-4.5-high` |
| 权威任务 | [`M3_G1_公司行动ledger_evidence_event_id闭包返工任务单.md`](M3_G1_公司行动ledger_evidence_event_id闭包返工任务单.md) |
| 实现证据 | [`M3_G1_公司行动ledger_evidence_event_id闭包外部返工交付报告.md`](M3_G1_公司行动ledger_evidence_event_id闭包外部返工交付报告.md) |
| 诊断证据 | [`M3_G1_CANDIDATE_COMPONENT_INVALID_零网络组件级诊断记录.md`](M3_G1_CANDIDATE_COMPONENT_INVALID_零网络组件级诊断记录.md)；`artifacts/g1_component_diag_20260722/corp_action_enrichment.json` |
| 只读约束 | 生产代码与实现者测试严格只读；未联网、未调真实 API、未写正式 raw/journal/receipt、未进入 REFERENCE/PREPARE/PUBLISH |
| 唯一写入 | 本报告（对抗探针仅写 `/tmp`，不入仓库） |
| 初验结论 | **PASS**（冻结返工范围已闭合；定向证据充分） |
| Gate | **不得、亦不宣布** G1 / candidate / HISTORY Gate 通过 |

---

## 1. 范围与证据基线

已阅读任务单、交付报告、组件诊断记录与正式首败样本，并只读核对：

- `src/quant/data/m3_execution_facts.py` 中 `_assert_ledger_evidence_closure`（及 `_event_id_sha256` 调用）
- `tests/unit/test_m3_execution_facts.py` 新增两项与既有 dividend 选择/冲突/空窗用例
- `CorporateActionLedgerSchema`（`schemas.py`）：有意不含 `end_date`
- `artifacts/g1_component_diag_20260722/corp_action_enrichment.json`（正式首败 `600930.SH`）
- 诊断最小复现 `artifacts/g1_component_diag_20260722/min_repro_end_date_collision.py`

本轮仅复验任务单冻结的 `event_id` 闭包修复；**未**跑正式 full candidate、510300 五 identity、全量 pytest。

解释器：WSL Miniforge `base`（`/home/mabw/AI_Coding_win/QuantitativeTrading`）。未用 Windows 绿测冒充 Gate。

---

## 2. 合同要点核对（只读）

任务单推荐最小修复：以 **`event_id` 为键** 连接 ledger↔selected。

当前实现（`_assert_ledger_evidence_closure`）：

1. 保留 per-`economic_event_key` 的 `candidate_count` / rank 连续 / 唯一 rank1 selected 检查；
2. 对每个 selected 行，用既有 `_event_id_sha256(symbol, end_date, record_date, ex_date, cash, stock)` 得到 expected id；
3. selected expected id **禁止重复**；ledger `event_id` **禁止重复**；两集合必须相等（同高、无缺失）；
4. 对每个匹配对复核 symbol / ex_date / cash / stock / record_date / pay_date / stock_list_date。

与冻结方向一致。**未**向 `CorporateActionLedgerSchema` 加 `end_date`；**未**改 `_event_id_sha256` 哈希输入；diff 仅改闭包 join，符合“不得降级身份 / 不得静默去重”规则。

旧实现用 `(symbol, ex_date, cash, stock, record_date, pay_date, stock_list_date)` 建 map 并静默覆盖——正是诊断中的 `selected_map_key_collision` 根因；新实现已移除该键。

白名单：本返工相关代码/测试改动限于 `m3_execution_facts.py` 与 `test_m3_execution_facts.py`（外加交付报告）。工作区另有其他并行脏文件，**不纳入本初验归因**。

---

## 3. 任务书 §4 命令复跑

环境：WSL Miniforge `base`。本会话独立复跑结果：

```text
python -m pytest tests/unit/test_m3_execution_facts.py -q \
  -k "corporate_action or ledger or dividend" --durations=10
→ 7 passed, 39 deselected, 368 warnings in 2.52s

python -m ruff check src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py
→ All checks passed! (EXIT 0)

mypy src/quant/data/m3_execution_facts.py
→ Success: no issues found in 1 source file (EXIT 0)

git diff --check -- src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py
→ EXIT 0
```

实现者声明的两项新测试均在套件内绿：

| 测试 | 映射 |
|---|---|
| `test_dividend_distinct_end_dates_same_ex_fields_pass_closure` | 对抗复现：双 `end_date` 碰撞通过，两 `event_id` 不同 |
| `test_ledger_evidence_closure_rejects_tampered_event_id_or_fields` | 篡改 ledger `event_id` / selected `pay_date` → `G1_CORPORATE_ACTION_RESULT_INVALID` |
| 既有 empty/out-of-window / selection conflict / unimplemented | 版本选择 / 冲突 / 空窗不回退 |

诊断脚本 `min_repro_end_date_collision.py`（仍以旧 bug 抛错为 exit 0 条件）现输出 `assert_raised: false` 且 EXIT 1，与“修复后闭包应通过”一致。

---

## 4. 实现者未使用的对抗反例（本会话新增）

探针仅运行于 `/tmp/g1_adv_600930.py`（零网络、不改仓库代码/测试、不写正式 data）。

实现者测试使用合成 `600000.SH` + `end_date∈{20241231,20251231}`，且负面用例仅篡改 `pay_date` / ledger `event_id`。本会话额外覆盖正式首败形态与哈希外字段：

| ID | 反例 | 期望 | 结果 |
|---|---|---|---|
| R1 | **正式失败形状零网络 select**：`600930.SH`，`ex_date=2026-02-11`，`cash=0.03`，`stock=0`，`record=2026-02-10`，`pay=2026-02-11`，双 `end_date∈{2026-01-08,2025-09-30}`（取自 `corp_action_enrichment.json`） | `select_g1_corporate_actions` + `verify` 通过；ledger 高=2；两 `event_id` 不同且等于按各自 `end_date` 重算值 | **PASS** |
| R2 | 在 R1 结果上篡改一条 selected `end_date`，使重算 expected id 离开 ledger 集合 | `CorporateActionSelectionResult` → `G1_CORPORATE_ACTION_RESULT_INVALID` | **PASS** |
| R3 | 送转路径篡改 selected `stock_list_date`（不在 `event_id` 哈希内；实现者仅测了 `pay_date`） | 字段一致性路径仍 `G1_CORPORATE_ACTION_RESULT_INVALID` | **PASS** |
| R4 | 直接调用 `_assert_ledger_evidence_closure` 于 R1 的 ledger/evidence | 修复后不再抛错 | **PASS** |

对抗小计：**4/4 PASS**（均非实现者测试用例的直接复述）。

---

## 5. 逐项证据映射

| 任务通过条件 / 合同点 | 证据 | 状态 |
|---|---|---|
| 闭包以 `event_id` 连接（含 `end_date`） | `_assert_ledger_evidence_closure` diff；旧 `(ex/cash/…)` map 已删除 | PASS |
| 双 `end_date` 同 ex/cash/stock 字段 → 选择/闭包通过且两 id 不同 | 实现者 `test_dividend_distinct_end_dates…` + 本会话 R1 | PASS |
| 篡改 ledger `event_id` 或 selected 哈希外字段仍拒 | 实现者 `test_ledger_evidence_closure_rejects…` + 本会话 R2/R3 | PASS |
| 版本选择 / 冲突 / 空窗不回退 | 定向套件既有用例绿（7 passed） | PASS |
| 不改 Schema / 不降级哈希 / 不写正式数据 | Schema 只读确认；diff 范围；探针 `network=false` | PASS |
| §4 pytest / ruff / mypy / `git diff --check` | 本会话 WSL base 复跑全部 EXIT 0 / 绿 | PASS |

---

## 6. 结论与剩余风险

**外部独立初验 PASS。** 冻结根因（闭包 join 漏 `end_date`）已按 `event_id` 身份连接闭合；正式首败形状（`600930.SH` 双 `end_date`）在零网络 select 路径下通过；fail-closed 负面路径未回退。

仍属任务单明确未做、不得由本初验宣布完成的事项：

- 正式 full candidate / `G1_CORPORATE_ACTION_RESULT_INVALID` 在真实装载路径上的复跑；
- HISTORY / REFERENCE / PREPARE / PUBLISH；
- 510300 五 identity 与全量 Gate。

交回协调 / 主 Agent 做契约与跨模块终验；**本报告不宣布 G1 Gate 通过**。
