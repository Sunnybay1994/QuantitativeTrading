# M3 G1：audit 对齐月频 PIT×退市生命周期（299 / 退市日缺 bar）

- 日期：2026-07-24
- 环境：Windows 原生
- **不宣称** Gate / Codex 终验

## 现象

正式 `run_g1 status` → `G1_WORKFLOW_QUALITY_FAILED`。  
`formal_audit_diag`：`AUDIT_FAILED`，`BAR_OR_SUSPENSION_MISSING`×1 + `MEMBERSHIP_COUNT_MISMATCH`×46。

## 根因（探针）

三键均为 **退市日 = eligible 日**，无 daily、无 suspend_d：

| symbol | day | delist_date |
|---|---|---|
| 600005.SH | 2017-02-14 | 2017-02-14 |
| 600837.SH | 2025-03-04 | 2025-03-04 |
| 601989.SH | 2025-09-05 | 2025-09-05 |

退市后至下月观测激活前，eligible 可临时 <300（`index_membership` 合同已写明；R1C-B 交付亦提示 candidate audit 硬 300 会误报）。

## 修订

1. `MEMBERSHIP_COUNT_MISMATCH`：由「必须恰 300」改为「必须 ∈[1,300]」，与 `_build_eligible_keys` 一致。
2. `BAR_OR_SUSPENSION_MISSING`：instrument 退市生命周期末日（`delist_date` 向前映射的最后 SH session）缺 bar 且无 FULL_DAY → 豁免。

## 证据

- `artifacts/g1_component_diag_20260722/formal_audit_diag.summary.json`
- `artifacts/g1_component_diag_20260722/audit_bar_gap_probe.json`
