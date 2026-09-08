# M3 G1 P0I：停牌除权复牌日因子延迟闭包返工交付报告

状态：**外部实现已交付，待外部独立初验**（自测 ≠ 独立初验 ≠ Gate）

日期：2026-07-28（Asia/Shanghai）
实现基线：`a9936001a6db19747ad66e54dbc2d3762e926f52`
任务书：`docs/framework/agent/M3_G1_P0I_停牌除权复牌日因子延迟闭包返工任务单.md`

## 1. 修复摘要

1. `reconcile_g1_corporate_actions` 在精确 `ex_date` 入表后，按严格门控将事件延迟到连续 `FULL_DAY` 之后的首个非停牌 SH 交易日；精确日优先与既有 NO_MARKET_REFERENCE/正常交易日语义不变。
2. 延迟门控四条件同时成立才允许：`FULL_DAY`、无 daily、精确日因子稳定（`1±rtol`）、declared 无法在 rtol 内解释；禁止把一般对账失败宽泛重试到未来日期。
3. 延迟目标解析要求：ex_date→目标前每个 SH 交易日均为 `FULL_DAY` 且有因子观测；目标日必须在 history/factor scope 内并具备因子、bar、daily；无目标或不满足则 `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`。
4. 同一停牌窗多事件聚合到同一复牌日；复牌日精确事件与延迟事件合并，按 `event_id` 排序与 `math.fsum` 聚合一次。
5. `G1_CORPORATE_ACTION_RECONCILIATION_VERSION` 精确升级为 `tushare_factor_daily_preclose_suspension_resume_v6`。
6. 未改 Schema/connector/CLI/配置/raw/journal/正式 data；零网络。

## 2. 现象—根因—规则—最小复现—新增测试—通过条件

### P0I-1：停牌除权在精确 ex_date 稳定、复牌日才跳变

- **现象**：正式 candidate 首错 `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`；600717.SH ex_date=2026-06-18 因子稳定，首复牌 2026-06-23 才体现除权跃迁。
- **根因**：ledger 事件只绑定精确 `ex_date`，在停牌日用 `actual=1.0` 强制解释完整分红失败，复牌日真实跃迁又落入无事件分支。
- **规则**：仅当精确日 FULL_DAY+无 daily+稳定+declared 不可解释时，延迟到首个非 FULL_DAY 复牌日对账；中间稳定日保持 `NO_EVENT_STABLE_FACTOR`。
- **最小复现**：D2/D3 FULL_DAY、因子稳定、D4 跳变且 market/declared 在 rtol 内；修复前 UNEXPLAINED，修复后事件仅绑定 D4。
- **新增/修订测试**：`test_p0i_*` 覆盖 600717 形状、多事件聚合、复牌日合并、精确日可解释不延迟、P0E 不回退、非 FULL_DAY 不延迟、无复牌/缺因子/缺 daily/稳定超差/超限、不可跨越中间非停牌日、tamper、顺序无关、版本常量；candidate 版本身份断言改 v6。
- **通过条件**：白名单定向 pytest/ruff/mypy/diff check 全绿；不得自称 Gate/REFERENCE/PREPARE/PUBLISH 通过。

## 3. 白名单变更

| 路径 | 变更 |
|---|---|
| `src/quant/data/m3_execution_facts.py` | 延迟闭包分配/目标解析；recon version → `…_suspension_resume_v6` |
| `tests/unit/test_m3_execution_facts.py` | P0I fixture 与反例；版本断言 |
| `tests/unit/test_m3_g1_candidate.py` | recon version / candidate 身份断言 → v6；补 `_rebuild_suspend_inputs` 缺失的 `calendars=`（验收命令必要回归） |
| `docs/framework/agent/M3_G1_P0I_停牌除权复牌日因子延迟闭包返工交付报告.md` | 本报告 |

## 4. 验证命令与退出码

解释器：`D:\Miniforge3\python.exe`（Windows 原生反馈环）。

| 命令 | 退出码 |
|---|---|
| `pytest tests/unit/test_m3_execution_facts.py tests/unit/test_m3_g1_candidate.py -q` | 0（172 passed） |
| `ruff check src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py tests/unit/test_m3_g1_candidate.py` | 0 |
| `mypy src/quant/data/m3_execution_facts.py` | 0 |
| `git diff --check a9936001a6db19747ad66e54dbc2d3762e926f52 -- <白名单>` | 0 |

未运行：全量 pytest、全量 Ruff/mypy、正式网络、正式 status/HISTORY/REFERENCE/PREPARE/PUBLISH、WSL Gate。上述属外部独立初验 / 主 Agent 终验。

## 5. 版本漂移与身份

- 旧 recon version `tushare_factor_daily_preclose_v5` 不可再声称等价。
- 新版本 `tushare_factor_daily_preclose_suspension_resume_v6` 改变对账时点语义，将自然触发 build code version、candidate key、REFERENCE 抽样及下游 release 身份变化。
- 旧 REFERENCE/PREPARE/PUBLISH 身份不得复用。

## 6. 残留风险

- 正式 receipts 的零网络 production-equivalent candidate build / `status` 尚未由本会话执行；需独立初验与主 Agent 确认 600717 及同类停牌除权闭包后的下一真实状态。
- 白名单外仍有硬编码 `…_preclose_v5` 的测试（如 planning/reference）未改；不在本任务验收命令内，主验合流时需同步。
- 本交付仅为外部实现自测；不得宣称独立初验、G1 Gate、REFERENCE、PREPARE、PUBLISH 或 Linux publish Gate 通过。
