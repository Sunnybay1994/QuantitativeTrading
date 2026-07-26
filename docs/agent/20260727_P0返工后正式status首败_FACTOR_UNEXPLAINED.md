# 2026-07-27：P0 返工后正式 status 首败证据

> **不宣称** Codex 终验 / Linux Gate / 新 VerifiedG1Release。  
> 旧 Windows release `3c9bda84…` 仍仅诊断，禁止作 G2A 输入。

## 正式命令

```text
run_g1 status  →  outcome=FAILED
error_code=G1_WORKFLOW_QUALITY_FAILED
error_operation=INSPECT
日志：artifacts/g1_component_diag_20260722/formal_status_p0_v1.out.log
```

## 组件根因（零网络复现）

直接调用 `_build_candidate_body`（避免 `build_g1_candidate` 的 `from None` 吞因）：

```text
M3G1ExecutionFactError: G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED
位置：reconcile_g1_corporate_actions → _no_event_evidence_row
证据：artifacts/.../p0_status_first_failure_v2.json
```

即：无 dividend 事件日存在 `abs(actual_factor_ratio-1)>rtol` 的因子跳变；P0 返工 A 恢复的 B2C §9.2 fail-closed **按合同拒绝**，不再伪装 `NO_EVENT_STABLE_FACTOR`。

方法版本（已 bump）：price-limit / CA selection / CA reconciliation 均为 `*_v2`。

## 处置（按冻结任务书）

1. **保留本首败证据**；不启动 REFERENCE / PREPARE / PUBLISH。
2. **停止扩大实现**：不新增配股/增发等资本事件源（属需重新冻结的设计）。
3. P0 代码与独立初验闭包仍有效；正式 CSI300 闭合需后续设计裁定后再开返工。

## 会话映射（本轮）

| 角色 | 会话 | 结果 |
|---|---|---|
| 实现 | d952cc9 / 交付报告 | A/B/C 完成 |
| 独立初验 | 2db378c / 初验报告 | 通过（≠ 终验） |
| 正式 status | formal_status_p0_v1 | **QUALITY_FAILED**（预期类 fail-closed） |
