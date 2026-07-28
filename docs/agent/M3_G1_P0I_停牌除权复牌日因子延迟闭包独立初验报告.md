# M3 G1 P0I：停牌除权复牌日因子延迟闭包独立初验报告

状态：**独立初验通过**（≠ Codex 终验 ≠ G1/Linux Gate）

日期：2026-07-28（Asia/Shanghai）  
初验模型：`cursor-grok-4.5-high`（全新外部会话，未参与 P0I 实现）  
审查基线：`e2a3afbeb40a934ebdd6cf4749791b7d47749bbd`（`Fix G1 suspension-resume factor delay closure.`）  
分支：`cursor/g1-p0-rework-20260726`  
任务书：`docs/agent/M3_G1_P0I_停牌除权复牌日因子延迟闭包返工任务单.md`  
交付报告：`docs/agent/M3_G1_P0I_停牌除权复牌日因子延迟闭包返工交付报告.md`  
解释器：`D:\Miniforge3\python.exe`  
本报告为唯一写入路径；未改生产/测试代码、未 reset/checkout、未触碰 raw/receipt/release。

## 1. 结论

**通过。**

对照任务书 §2 冻结合同审查 `e2a3afb`：精确日优先、四条件延迟门控、复牌目标、多事件聚合、版本身份 `tushare_factor_daily_preclose_suspension_resume_v6`、无事件 fail-closed / `_supported_ratio` 未放松，均与合同一致。定向 pytest 全绿；三组实现者未使用的内存对抗探针均通过。本结论仅为外部独立初验，不得宣称 Codex 终验、G1 Gate、REFERENCE/PREPARE/PUBLISH 或 Linux publish Gate。

返工项：**无。**

## 2. 冻结合同对照（§2）

审查对象：`src/quant/data/m3_execution_facts.py` 中
`_eligible_for_suspension_resume_delay`、`_resolve_suspension_resume_date`、
`_assign_events_with_suspension_resume_delay`，以及 `reconcile_g1_corporate_actions`
在精确日入表后的调用点。

| 合同项 | 判定 | 证据摘要 |
|---|---|---|
| §2.1 精确日优先 | 通过 | 非延迟事件仍 `assigned[(symbol, ex_date)]`；非 `FULL_DAY` 门控直接 False；精确日可解释跃迁 / declared 在 rtol 内走既有 NO_MARKET_REFERENCE，不进入延迟 |
| §2.2 四条件延迟门控 | 通过 | 同时要求 FULL_DAY、精确日无 daily、`abs(actual-1)≤rtol`、declared 无法在 rtol 内解释（`declared is None` 或相对误差 `> rtol`）；非宽泛失败重试 |
| §2.3 延迟目标=首个非 FULL_DAY | 通过 | 自 `ex_date` 起逐 SH 交易日：中间 FULL_DAY 必须有因子；首个非 FULL_DAY 必须有因子+bar+daily 且在 history 内；否则 `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED` |
| §2.4 多事件聚合/闭包 | 通过 | 同目标 `setdefault(...).extend(events)`；复牌日精确事件与延迟事件合并；对账仍按 `event_id` 排序与 `math.fsum`；无目标/超差仍 UNEXPLAINED |
| §2.5 版本 v6 | 通过 | `G1_CORPORATE_ACTION_RECONCILIATION_VERSION == "tushare_factor_daily_preclose_suspension_resume_v6"`；candidate 测试断言同步为 v6 |
| 无事件 fail-closed / supported_ratio 未放松 | 通过 | `_no_event_evidence_row` 仍在 `abs(actual-1)>rtol` 时 UNEXPLAINED；`_supported_ratio` 仍为 `value>1` 或 `1±rtol`；事件分支失败不回落到无事件稳定 |

白名单外未发现本 commit 改动；交付报告所述 Schema/connector/CLI/配置/raw/journal 未改，与 `git show --stat` 一致。

## 3. 定向 pytest

命令：

```text
set PYTHONPATH=F:\AI_Coding\QuantitativeTrading\src
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_execution_facts.py tests/unit/test_m3_g1_candidate.py -q --tb=line
```

| 项 | 结果 |
|---|---|
| 退出码 | 0 |
| 摘要 | **172 passed**, 614103 warnings in 1642.54s |
| 失败 | 无 |

说明：大量 DeprecationWarning 来自 pandera/polars（既有噪音），不影响本初验判定。未运行全量 pytest、正式 status、网络或 Gate。

## 4. 对抗探针（实现者未用构造）

探针目录：`artifacts/g1_component_diag_20260722/`（诊断产物，非生产身份）。

| 探针 | 构造要点（相对实现者测试的差异） | 期望 | 结果 |
|---|---|---|---|
| `p0i_indep_probe_a_boundary_no_delay.py` | 符号 `601398.SH`；精确日因子微漂移 `10.0→10.004`（非精确 1.0）；现金 `0.016`/`prev=20` 使 declared 误差≈4e-4&lt;rtol；后续日保持平坦作错误延迟诱饵 | 事件仍绑精确日 D2，`MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE`，不得延迟 | **PASS**（exit 0） |
| `p0i_indep_probe_b_no_cross_window.py` | 符号 `600519.SH`；高价现金 `cash=12.5`/`prev=1800`；仅 D2 FULL_DAY；D3 为结构完备的非停牌平坦日；D4 工程化完美 declared/market 闭包陷阱 | 首个非 FULL_DAY 无法解释 → `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`，不得跨窗绑到 D4 | **PASS**（exit 0） |
| `p0i_indep_probe_c_600717_shape.py` | 符号 `600717.SH` + 任务书数值（4.31/0.102/34.8547→35.6826/4.21）；断言稳定日集合与复牌唯一绑定；并追加空 ledger 同跳变 → 无事件 fail-closed | 事件仅 D4；D1/D2/D3=`NO_EVENT_STABLE_FACTOR`；无事件跳变仍 UNEXPLAINED | **PASS**（exit 0） |

对抗结论：延迟门控未把「declared 可在 rtol 内解释」误延迟；中间非 FULL_DAY 不可跨越；600717 形状闭包正确；无事件/`supported_ratio` 语义未放松。

## 5. 范围与非声称

- 本会话只写本报告与上述探针脚本；未修改白名单生产/测试代码。
- 未执行正式 receipts 零网络 candidate build / `status`、WSL Gate、REFERENCE/PREPARE/PUBLISH。
- **通过 ≠ Codex 终验**；下一状态由主 Agent 终验确认。

## 6. 返回协调者摘要

- **通过与否：通过**
- **pytest：172 passed / exit 0**（约 27m22s；pandera/polars DeprecationWarning 噪音）
- **对抗探针：A/B/C 三组全部 PASS**
- **报告路径：`docs/agent/M3_G1_P0I_停牌除权复牌日因子延迟闭包独立初验报告.md`**
- **返工项：无**
