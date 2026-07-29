# M3 G1 P0J：Tushare 分红跨 end_date 精确重复折叠 — 独立初验报告

日期：2026-07-29（Asia/Shanghai）  
角色：未参与 P0J 实现的外部独立初验 Agent（生产代码与实现者测试只读）  
实现提交：`f467c1ade53ebcae104d35ac74ca4f8a0975cf89`  
任务书：[`M3_G1_P0J_Tushare分红跨end_date精确重复折叠返工任务单.md`](M3_G1_P0J_Tushare分红跨end_date精确重复折叠返工任务单.md)  
交付报告：[`M3_G1_P0J_Tushare分红跨end_date精确重复折叠返工交付报告.md`](M3_G1_P0J_Tushare分红跨end_date精确重复折叠返工交付报告.md)

## 1. 结论

**独立初验 FAIL，退回返工。** 不宣称主验、Gate 或正式 status 通过。

定向 pytest / ruff / mypy / `git diff --check` 均绿；§8 已覆盖的 600733/600930/三端点/provenance 阻断/对账/v6 钉扎在实现者测试内成立。但未公开反例证明：精确簇 A 经 `end_date=max` canonical 后，与同 max `end_date`、仅 `base_share` 不同且 rank/decision 相同的 B **静默合并**为一事件（`ledger=1`，`raw_row_count=3`），既未区分也未 fail-closed，违反任务书 §2.3 / §3。

本轮唯一写入并提交的文件为本报告；工作区既有其他 modified docs 保留且未暂存。零网络；未跑 formal full status。

## 2. 核对范围与命令

| 项 | 结果 |
| --- | --- |
| 规则 | 已读 `AGENTS.md`、`.ai/README.md`、`review_checklist.md`、`workflows/multi_agent_delivery.md`、`workflows/high_risk_change.md` |
| Diff 白名单 | `f467c1a` 仅三文件：`m3_execution_facts.py` / `test_m3_execution_facts.py` / 交付报告 |
| Selection version | 生产常量为 `..._cross_end_exact_fold_v6`；测试正向钉扎 v6 且 `!= v5`；生产无当前值回退 v5 |
| `pytest … -k "dividend or corporate_action_selection or reconciliation or version_constants" -q` | `21 passed, 107 deselected`（Windows `D:\Miniforge3\python.exe`） |
| `ruff check` 两白名单代码文件 | All checks passed |
| `mypy src/quant/data/m3_execution_facts.py` | Success |
| `git diff --check`（实现三文件） | 通过 |
| 正式 full status / 网络 | 未运行 |

## 3. §2 / §3 / §5 / §8 映射摘要

| 合同点 | 初验判断 |
| --- | --- |
| §2 600733 仅 end 不同折一事件、max end、`raw_row_count` | 实现者测试 + 机制核对：PASS 本轮 |
| §2/§3 600930 不同 `ann_date` 双事件 | 实现者测试 + 未公开双 `ann_date` 反例：PASS 本轮 |
| §3 身份含全部正式字段唯独排除 `end_date`；`null≠0` | helper 字段闭包核对；未公开 null/0 反例：PASS 本轮 |
| §3/`§2.3` 任一非 end 字段不同不得进 exact 聚合后须区分或冲突 fail-closed | **FAIL**：见 §4 P0-1（canonical 后同组静默合并） |
| §5 selection version → v6，哈希标签不变 | PASS 本轮 |
| §8 所列实现者测试面 | 定向集 21 passed；**未覆盖** A∪B canonical 碰撞 |

## 4. 未公开反例（系统临时文件）

探针：`%TEMP%\p0j_adversarial_probe.py`（不入库）。解释器：`D:\Miniforge3\python.exe`。

| 反例 | 结果 |
| --- | --- |
| 不同 `ann_date` 双事件（跨 end） | `ledger=2`，两 `event_id`：OK |
| `cash_div_tax` null vs `0.0` | `ledger=2`：OK |
| `base_share` 篡改（100/100 fold vs 100/101）并比较 digest | clean 折 1；tampered 高=2；ledger/evidence SHA 均不同：OK |
| 未公开多端点乱序+重复计数（7 行） | digest 顺序无关，`raw_row_count=7`，max end：OK |
| **exact 簇 A=(end 2024+2025, base_share=100) + B=(end 2025, base_share=101, 同 rank/decision)** | **`silent_merge=True`，`ledger=1`，`candidates=1`，`raw_row_count=[3]`：FAIL** |

## 5. 返工项（现象—根因—规则—最小复现—新增测试—通过条件）

### P0-1：跨 end exact 折叠 canonical 后，与同 max end、仅 provenance 不同的行静默合并

- **现象**：输入三行——`end_date∈{20241231,20251231}` 且 `base_share=100`（可折为一簇），再加 `end_date=20251231` 且 `base_share=101`，其余 ann/imp/cash/stock/pay/list 相同。输出 `ledger.height==1`、`selection_evidence.height==1`、`raw_row_count==3`，无 `G1_CORPORATE_ACTION_VERSION_CONFLICT`。`base_share` 差异被吞掉，计数把非精确相同投影算进同一 candidate。
- **根因**：`_fold_dividend_cross_end_exact_duplicates` 正确因 `base_share` 把 A/B 分到不同 exact 桶，但 A canonical `end_date=max→2025-12-31` 后与 B 落入同一经济 `group_key=(symbol,end,record,ex)`。随后 `_fold_identical_candidates` 仅用 `_version_rank_key`+`_decision_fields`（不含 `base_share`/其他 exact 身份字段）判定相同并累加 `raw_row_count`。实现者 `test_dividend_cross_end_exact_fold_blocked_by_provenance_fields` 只覆盖“不同 end 仍保留两事件”的双侧不同 end 形状，未覆盖“一侧已被折到 max end 后与第三方同 end 碰撞”。
- **应遵循规则**（任务书 §2.3 / §3）：除 `end_date` 外任一正式字段不同不得进入同一精确重复聚合；之后必须走既有经济分组/版本排序，**区分不同事件或冲突 fail-closed**；不得按同 symbol/ex/cash/stock 宽松去重。canonical `end_date` 不得把本应阻断折叠的 provenance 差异重新洗成静默同一 candidate。
- **最小复现**（系统临时探针已复现）：

```text
rows = [
  dividend(end=20241231, base_share=100, …同决策字段…),
  dividend(end=20251231, base_share=100, …),
  dividend(end=20251231, base_share=101, …),
]
select_g1_corporate_actions(...)
# 当前：ledger=1, evidence=1, raw_row_count=3（静默合并）
# 合同：ledger>=2 且闭包通过，或 raise G1_CORPORATE_ACTION_VERSION_CONFLICT（fail-closed）
```

- **新增测试**：在 `tests/unit/test_m3_execution_facts.py` 增加上述 A∪B 形状；断言不得静默单事件。建议同时钉扎：仅 A 仍折 1 且 `raw_row_count=2`；仅同 end 的 base_share 冲突语义与返工选定方案一致（区分或 CONFLICT）。不得靠证券白名单或 factor 反选。
- **通过条件**：该反例稳定为“多事件区分”或“VERSION_CONFLICT fail-closed”；既有 600733 折叠、600930 双 `ann_date`、null≠0、§8 定向回归与 v6 钉扎仍通过；独立初验复跑本反例 PASS 后方可进入主验。

## 6. 范围与交接

- 未改生产代码、实现者测试、任务书或其他 docs。
- 已知未验证：WSL base 终验、正式 637-response 零网络 selection/status、下一正式首败裁定（初验 FAIL，不进入）。
- 下一步：主 Agent 按 P0-1 冻结返工语义（区分 vs fail-closed）→ 外部实现 → **另一**未参与该轮实现的外部独立初验复验。
