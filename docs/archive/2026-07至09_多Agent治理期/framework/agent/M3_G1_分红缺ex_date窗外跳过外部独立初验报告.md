# M3 G1：分红缺 `ex_date` 窗外跳过外部独立初验报告

- 角色：外部独立初验 Agent（全新会话，`cursor-grok-4.5-high`；非实现者）
- 任务单：[`M3_G1_分红缺ex_date窗外跳过返工任务单.md`](M3_G1_分红缺ex_date窗外跳过返工任务单.md)
- 交付报告：[`M3_G1_分红缺ex_date窗外跳过外部返工交付报告.md`](M3_G1_分红缺ex_date窗外跳过外部返工交付报告.md)
- 诊断：`artifacts/g1_component_diag_20260722/event_invalid_enrichment.json`
- 只写本报告；零网络；未改正式 raw / 生产代码
- **初验结论：PASS**（不宣布 G1/Gate 通过）

## 1. 契约核对

| 冻结项 | 证据 |
|---|---|
| `实施` + `ex_date is None` 先走支持日证明 | `select_g1_corporate_actions` → `_null_ex_date_fully_outside_history` |
| 支持字段 `end/record/pay/div_listdate`；非法格式 fail closed | 严格 `_parse_optional_date8`；空集返回 False |
| 全部 `< start` 或全部 `> end` → skip；相交/落入 → `EVENT_INVALID` | 实现与单测一致；不发明 `ex_date` 入 ledger |
| 非 null `ex_date` 路径未削弱 | 既有窗口过滤 / 空腿 / event_id 闭包 / 冲突测仍在定向套件内 |

白名单：生产+测试改动限于 `m3_execution_facts.py` / `test_m3_execution_facts.py`；交付报告 untracked。

## 2. §4 复跑（WSL Miniforge `base`）

```text
pytest ... -k "corporate_action or ledger or dividend"
→ 13 passed, 39 deselected, 560 warnings in 2.53s

ruff check → All checks passed!
mypy src/quant/data/m3_execution_facts.py → Success
git diff --check → EXIT 0
```

## 3. 对抗性反例（实现者未用正式 history 窗）

正式 history=`2015-10-09..2026-07-10`，symbol=`600176.SH`：

| 反例 | 期望 | 结果 |
|---|---|---|
| A1 正式形状：`ex_date=null`，`end=20140319`/`record=20140418`/`list=20140820` + 同响应窗内有效实施 | skip 残缺行；有效行入账；ledger 无 `stk_div=0.1106` | PASS |
| A2 相交窗：`record` 在窗外、`div_listdate=20160115` 在窗内 | `G1_CORPORATE_ACTION_EVENT_INVALID` | PASS |
| A3 边界：`record_date == history.start`（非严格 `<`） | fail closed | PASS |

## 4. 剩余风险（非初验阻塞）

- 未跑正式 full candidate / 510300 / REFERENCE/PREPARE/PUBLISH；未全量 pytest。
- 主 Agent 终验前仍须按里程碑流程复核。

## 5. 判决

**PASS** — 返工合同落地；§4 绿；正式形状窗外跳过与相交窗 fail closed 对抗成立。非 Gate 通过。
