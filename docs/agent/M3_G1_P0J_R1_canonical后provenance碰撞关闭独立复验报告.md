# M3 G1 P0J-R1：canonical 后 provenance 碰撞关闭 — 独立复验报告

日期：2026-07-29（Asia/Shanghai）  
角色：未参与 `247d6d7` 实现的外部独立复验 Agent（生产代码与实现者测试只读）  
实现提交：`247d6d7d5ad0e10cf3a237f388f590991602d3a1`  
返工基线 / 上游 FAIL：`af76cee`  
任务书：[`M3_G1_P0J_R1_canonical后provenance碰撞关闭返工任务单.md`](M3_G1_P0J_R1_canonical后provenance碰撞关闭返工任务单.md)  
交付报告：[`M3_G1_P0J_R1_canonical后provenance碰撞关闭返工交付报告.md`](M3_G1_P0J_R1_canonical后provenance碰撞关闭返工交付报告.md)  
上游合同：[`M3_G1_P0J_Tushare分红跨end_date精确重复折叠返工任务单.md`](M3_G1_P0J_Tushare分红跨end_date精确重复折叠返工任务单.md)

## 1. 结论

**独立复验 PASS。** 不宣称主验、正式 full status、Gate 或正式下一首败裁定。

`247d6d7` 仅三白名单文件：cross-end exact fold 输出携带复用自 `_dividend_cross_end_exact_identity` 的 `exact_identity`；`_fold_identical_candidates` 仅在 version rank + decision fields + exact identity 全同时累加 `raw_row_count`，同 rank 下任一差异稳定抛 `G1_CORPORATE_ACTION_VERSION_CONFLICT`。A1+A2+B 不再静默合并；实现者未覆盖的 `base_date` / `cash_div` 同 rank/decision 碰撞同样 fail-closed；同 end 完全 exact duplicate 仍累计；600733/600930/null≠0/输入顺序/v6 不退化。

本轮唯一写入并提交的文件为本报告；工作区既有其他 modified docs 保留且未暂存。零网络；未跑 formal full status。

## 2. 核对范围与命令

| 项 | 结果 |
| --- | --- |
| 规则 | 已读 `AGENTS.md`、`.ai/README.md`、`review_checklist.md`、`workflows/multi_agent_delivery.md`、`workflows/high_risk_change.md` |
| Diff 白名单 | `247d6d7` 仅三文件：`m3_execution_facts.py` / `test_m3_execution_facts.py` / R1 交付报告 |
| Selection version | 生产常量仍为 `..._cross_end_exact_fold_v6`；`test_version_constants` 钉扎 v6 且 `!= v5`；本轮未升级 v7 |
| Schema / 哈希标签 / 公开字段 | 无 Schema、event/candidate/economic-key 标签或公开 digest 改动；`exact_identity` 仅内部 wrapper |
| `pytest … -k "dividend or corporate_action_selection or reconciliation or version_constants" -q` | `26 passed, 107 deselected`（Windows `D:\Miniforge3\python.exe`） |
| `ruff check` 两白名单代码文件 | All checks passed |
| `mypy src/quant/data/m3_execution_facts.py` | Success |
| `git diff --check af76cee 247d6d7`（实现三文件） | 通过 |
| 正式 full status / 网络 | 未运行 |

## 3. R1 §2 / §7 合同映射

| 合同点 | 复验判断 |
| --- | --- |
| A1+A2+B 精确 `G1_CORPORATE_ACTION_VERSION_CONFLICT`，不静默 `raw_row_count=3` | PASS：实现者测试 + 临时探针三输入顺序复跑 |
| 仅 A1+A2 仍折一事件，canonical max，`raw_row_count=2` | PASS |
| 同 end、同 rank/decision、仅 provenance 不同 → 同一冲突码 | PASS（`base_share` 实现者用例 + 下方新反例） |
| 同 end 完全 exact duplicate 仍累加 `raw_row_count` | PASS；provenance 不同不得计入同一成功 `raw_row_count` |
| 输入顺序反转冲突码不变 | PASS |
| exact identity 复用 `_dividend_cross_end_exact_identity`，不进 Schema | PASS（diff 核对） |
| 600733 / 600930 / null≠0 / v6 | PASS（定向集 + 探针调用既有用例） |
| 实现者未用反例：`base_date` 或 `cash_div` 制造 canonical 后同 rank/decision 碰撞 | PASS：见 §4 |

## 4. 未公开反例（系统临时文件）

探针：`%TEMP%\p0j_r1_adversarial_probe.py`（不入库，跑后删除）。解释器：`D:\Miniforge3\python.exe`。

说明：决策腿 `cash` 来自 `cash_div_tax`，故可在保持 rank/decision 不变的前提下单独改 `cash_div`；`base_date` 亦不在 decision fields 中。实现者 R1 测试仅钉扎 `base_share` 碰撞。

| 反例 | 结果 |
| --- | --- |
| A1+A2+B（`base_share` 100/100/101）及三种输入顺序 | 精确 `G1_CORPORATE_ACTION_VERSION_CONFLICT` |
| 同 end exact duplicate 两行 | `ledger=1`，`raw_row_count=2` |
| **NEW：A1+A2+B，仅 `base_date` 不同（20251231 vs 20241231），同 rank/decision** | **`G1_CORPORATE_ACTION_VERSION_CONFLICT`** |
| **NEW：A1+A2+B，仅 `cash_div` 0.09 vs 0.19（`cash_div_tax` 不变）** | **`G1_CORPORATE_ACTION_VERSION_CONFLICT`** |
| 同 end 仅 `base_date` 不同 | 冲突，不累加成功 `raw_row_count` |
| null≠0 stock-only 跨 end（`cash_div_tax` None vs `0.0`） | `ledger=2` |
| 600733 shape / 600930 双 `ann_date` / order / v6 钉扎 | OK |

## 5. 机制核对摘要

- `_fold_dividend_cross_end_exact_duplicates` 桶项增加 `exact_identity`，canonical 改写 `end_date` 后身份仍可比较。
- `_fold_identical_candidates`：`fold_key = rank_key + decision + (exact_identity,)`；同 `rank_key` 且 `fold_key` 不同即 `VERSION_CONFLICT`（覆盖 decision 差异与 exact 差异）。
- 未新建第二套 selector；未读正式诊断产物或硬编码扫描计数。

## 6. 范围与交接

- 未改生产代码、实现者测试、任务书或其他 docs。
- 已知未验证：WSL base 终验、正式 637-response 零网络 selection/status、主 Agent 终验与下一正式首败裁定。
- 下一步：主 Agent 吸收本复验后执行 Windows/WSL 定向测试与正式零网络 selection/status；本报告不代替主验。
