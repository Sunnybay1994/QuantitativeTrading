# M3 G1：公司行动 ledger↔evidence `event_id` 闭包协调 Agent 阶段验收记录

- 角色：外部 Cursor **协调 Agent**
- 时间：2026-07-23（Asia/Shanghai）
- 任务单：[`M3_G1_公司行动ledger_evidence_event_id闭包返工任务单.md`](M3_G1_公司行动ledger_evidence_event_id闭包返工任务单.md)
- 实现交付：[`M3_G1_公司行动ledger_evidence_event_id闭包外部返工交付报告.md`](M3_G1_公司行动ledger_evidence_event_id闭包外部返工交付报告.md)
- 独立初验：[`M3_G1_公司行动ledger_evidence_event_id闭包外部独立初验报告.md`](M3_G1_公司行动ledger_evidence_event_id闭包外部独立初验报告.md) → **PASS**
- 诊断：正式首败 `600930.SH` / `selected_map_key_collision`；合成复现 `min_repro_end_date_collision.json`
- 本记录结论：**本返工子包阶段验收通过**；**不宣布** G1 / full candidate / HISTORY Gate 通过

## 1. 职责分离

| 角色 | 模型 | 白名单 |
|---|---|---|
| 实现 | `cursor-grok-4.5-high` 全新会话 | `m3_execution_facts.py`、`test_m3_execution_facts.py`、交付报告 |
| 独立初验 | 另一全新 `cursor-grok-4.5-high` | 仅初验报告；复跑 §4 + 正式失败形状对抗 |
| 协调主验 | 本会话 | 复跑 §4 + 本验收记录 |

## 2. 根因与修复

- 根因：闭包 join 漏 `end_date`，与 `event_id` 身份不同构。
- 修复：以 `event_id` 集合一一对应连接 ledger↔selected；Schema 未加 `end_date`。

## 3. 协调主验（WSL base）

```text
pytest tests/unit/test_m3_execution_facts.py -q -k "corporate_action or ledger or dividend"
→ 7 passed, 39 deselected in 2.44s

ruff check src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py
→ All checks passed!

mypy src/quant/data/m3_execution_facts.py
→ Success: no issues found in 1 source file

git diff --check -- src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py
→ EXIT 0
```

独立初验额外对抗：正式 `600930.SH` 双 `end_date` 形状零网络 select 通过；篡改 `end_date`/`stock_list_date` 仍拒——与主验一致，予以吸收。

## 4. 下一步（未关闭）

须在零网络下继续正式装载路径，确认 `corporate_action_selection` 之后是否还有新的首败层；在 full candidate / HISTORY stage 真正通过前，禁止 REFERENCE / PREPARE / PUBLISH。
