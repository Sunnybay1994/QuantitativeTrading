# M3 G1-P4B 独立初验一次返工交付报告

日期：2026-07-15  
角色：原外部实现 Agent（非独立复验）  
实际模型标识：`cursor-grok-4.5-high`  
返工任务单：[`M3_G1_P4B独立初验返工任务单.md`](M3_G1_P4B独立初验返工任务单.md)  
独立初验：[`M3_G1_P4B跨源证据独立初验报告.md`](M3_G1_P4B跨源证据独立初验报告.md)  
实现交付：[`M3_G1_P4B跨源证据阻塞解除后交付报告.md`](M3_G1_P4B跨源证据阻塞解除后交付报告.md)  
状态：**待独立复验/待主验**（不得视为 B4 / G1 / M3 / Gate 通过）

## 1. 范围

仅修改：

- `src/quant/data/m3_reference.py`
- `tests/unit/test_m3_reference.py`
- 本报告

未改 connector、P4A、RawStore、上游测试、配置、路线图或任何历史报告。

## 2. F1：同一 detail 上可伪造 summary/issues

| 项 | 内容 |
|---|---|
| 现象 | mismatch detail 可配自洽全绿 summary/hash/`issues=()`/`passed=True`（ADV5） |
| 根因 | 构造器只重建 caller summary 并验 hash，未从 detail 派生 stats/issues/passed |
| 规则 | 任务书 §7.8：bundle 从 detail 重算 digest/stats/summary digest/issues/passed |
| 最小复现 | 独立初验 ADV5 |
| 修复 | 新增 `_derive_cross_source_from_detail`；`reconcile_cross_source` 与 `CrossSourceReconciliationBundle` 共用；构造器逐项与派生结果比较 |
| 新增测试 | `test_adv5_bundle_rejects_lying_green_summary_on_mismatch_detail`；`test_adv5_variants_reject_forged_stats_missing_rate_issues_passed`；`test_adv5_detail_schema_and_key_drifts_reject_with_stable_valueerror` |
| 通过条件 | ADV5 必拒；stats/missing/rate/issue/passed 伪造必拒；detail schema/key 非法只抛稳定 `ValueError` |

## 3. F2：跨源 issue 可使用 WARNING

| 项 | 内容 |
|---|---|
| 现象 | `severity="WARNING"` 的跨源 issue 可进入 bundle（ADV9） |
| 根因 | 构造器只验 code，未强制 ERROR |
| 规则 | 任务书 §7.9：两码均为 ERROR |
| 最小复现 | 独立初验 ADV9 |
| 修复 | bundle 对每个 issue 要求 `severity == "ERROR"`，再与 detail 派生 issues 精确相等 |
| 新增测试 | `test_adv9_bundle_rejects_warning_severity_for_both_cross_source_codes` |
| 通过条件 | 两码 WARNING 均拒；ERROR 正常；未知码仍拒 |

## 4. F3：bundle 可见闭包缺口

| 项 | 内容 |
|---|---|
| 现象 | 删一 `reference_receipts` 曾被构造器接受；sample/digest 闭包未显式校验 |
| 根因 | 构造器未要求恰好 30 个 receipt，也未闭合 sample key / digests / detail_sha |
| 规则 | 返工任务单 §4；不夸大 primary_receipt_digests 的自包含能力 |
| 修复 | 强制 30 receipts；`primary_candidate_key`/`sample_plan_sha256` 与 sample_plan 相等；`reference_receipt_digests == sorted(unique(stable_response_sha256))`；`summary.detail_sha256 == bundle.detail_sha256`；守恒 30/20/600/5/3000 |
| 新增/修正测试 | `test_f3_bundle_rejects_sample_plan_and_reference_receipt_closure_drifts`；`test_f3_summary_reference_digests_must_match_receipt_projections`；修正 `test_bundle_constructor_rejects_wholesale_and_field_drift` 中删 receipt 预期为拒绝 |

## 5. 验证结果（WSL Miniforge `base`）

| 命令 | 结果 |
|---|---|
| 返工定向 `-k "adv5 or adv9 or f3 or bundle_constructor"` | **7 passed** |
| 定向 `test_m3_reference.py` + `test_baostock_connector.py` | **116 passed** |
| 定向 `test_m3_g1_candidate.py` | **33 passed** |
| 全量 `pytest -q` | **752 passed** |
| `ruff check src tests` | **All checks passed** |
| `mypy src` | **78 source files，0 issues** |

未联网、未读 token、未访问 `_old/`。

## 6. 交付声明

F1–F3 已修复并自测；状态：**待独立复验/待主验**。  
请未参与本轮返工的全新会话重放 ADV5/ADV9，并至少增加两个针对 F3 或 detail schema 的新反例。  
不宣称 B4 / G1 / M3 / 任一 Gate 通过。
