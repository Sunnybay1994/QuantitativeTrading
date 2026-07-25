# M3 G1：PUBLISH 失败 `G1_WORKFLOW_JOURNAL_INVALID` 诊断与解阻

- 日期：2026-07-25
- 环境：Windows 原生
- **不宣称** Linux Gate / Codex 终验

## 现象

正式 `publish` v2（约 3h）失败：

```text
error_code=G1_WORKFLOW_JOURNAL_INVALID
error_operation=PREPARE
outcome=FAILED
completed_stages=[]
```

证据：`artifacts/g1_component_diag_20260722/formal_publish_win_v2.out.log`

## 快检（排除目录损坏）

| 检查 | 结果 |
|---|---|
| tushare journal 结构 | 3325 children，0 结构问题 |
| baostock journal 结构 | 30 dirs，均含 intent/candidate/receipt |
| baostock receipt 验真 | 30/30 OK |
| index/history verify | OK（`journals_ok_before_candidate`） |

## 根因

诊断重建（`diag_publish_journal_invalid_v1.out.json`）：

| 项 | 值 |
|---|---|
| PREPARE 时 `primary_candidate_key` | `c46aa26d6a1b4bfe…` |
| 当前重建 key | `cc50d836f465ea0d…` |
| key 是否一致 | **false** |
| audit | passed |
| baostock expected vs journal | **30 vs 30，交集为空** |

机制：

1. `compute_g1_runtime_identity` 对 **`src/quant/**/*.py` 全量** 做 `source_tree_sha256` → `build_code_version`
2. Windows PUBLISH 解阻改动了 `m3_release.py`（`MoveFileExW` / `O_BINARY` / dir-fsync）→ **code version 变化**
3. `primary_candidate_key` 含 `build_code_version` → key 漂移
4. `plan_cross_source_reconciliation` 用 key 作抽样种子 → **全新 30 个 baostock request_id**
5. `_validate_baostock_journal_root` 发现 journal 中旧 ID ∉ expected → `G1_WORKFLOW_JOURNAL_INVALID`

这是合同内的 fail-closed 行为，不是 journal 比特损坏。

## 解阻（Windows 轨）

1. **隔离**（不删）旧 baostock journal dirs（对齐旧 key `c46aa26d…`）到  
   `artifacts/g1_component_diag_20260722/baostock_journal_quarantine_key_c46aa26d/`
2. 正式 `reference`：按新 key `cc50d836…` 拉取 30 条 baostock（允许网络；非 510300）
3. 正式 `prepare` → `publish`
4. 落盘 Windows 轨 `VerifiedG1Release` 后再推进 G2A；**仍 ≠** Linux Gate

## 教训

任何进入 `src/quant` 的代码改动都会使 G1 identity/key 失效，从而要求 **REFERENCE 及之后阶段重跑**。PUBLISH 路径修补应在 REFERENCE 之前完成，或接受随后的 reference 重拉成本。
