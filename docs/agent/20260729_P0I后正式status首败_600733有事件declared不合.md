# 2026-07-29：P0I 后正式 status 首败证据（600733 有事件 declared 不合）

> **不宣称** Codex 终验 / Linux Gate / 新 VerifiedG1Release。  
> 旧 release `3c9bda84…` 仍禁止作 G2A 输入。  
> P0I 独立初验已通过；本文件只冻结 **P0I 之后** 正式 `status` 首败，不启动实现扩大。

## 正式命令

```text
run_g1 status（P0I / recon v6 后）→ outcome=FAILED
error_code=G1_WORKFLOW_QUALITY_FAILED
error_operation=INSPECT
日志：artifacts/g1_component_diag_20260722/formal_status_p0i_v1.out.log
```

## 零网络首败样本

`artifacts/g1_component_diag_20260722/p0i_status_first_failure_v2.json`  
（`recon=tushare_factor_daily_preclose_suspension_resume_v6`；抛出点 `m3_execution_facts.py` L1231）

| 字段 | 值 |
|---|---|
| 分支 | **有事件**；`daily_row is None`；`in_full_day=True`；`declared_error > rtol` |
| symbol | `600733.SH` |
| previous → effective | `2018-09-18` → `2018-09-19` |
| prev_close / prev_close_date | `52.69` / `2018-02-01`（有效日前有长间隔） |
| event_count / types | 2 × `DIVIDEND_DISTRIBUTION`（同日 `ex_date=2018-09-19`） |
| cash / stock / rights | `0` / `5.0` / `0` |
| actual_factor_ratio | `≈3.50085` |
| declared_dividend_factor_ratio | `6.0` |
| declared_error | `≈0.4165`（`rtol=0.001`） |
| code | `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED` |

说明：v1 探针只包了 `_no_event_evidence_row`，`first_hit=null`；本首败在 **事件分支** 的「缺 daily + FULL_DAY + declared 超 rtol」路径，与 P0I 诊断时的 `600717.SH` 形状不同。

快照中的 `market` / `market_error` / `status=MATCHED_EVENT_MARKET_REFERENCE` 来自循环残留局部变量，**不可作为本行失败依据**（本行 `daily_row=None`，未走 market 闭合）。

## 处置

1. **保留本首败证据**；不启动 REFERENCE / PREPARE / PUBLISH。  
2. 不放宽 `rtol`，不把本样本伪装成 `NO_EVENT`。  
3. 下一轮若返工：须先冻结任务书，明确是否处理「停牌窗内复牌日多事件 stock 聚合 vs actual」或「缺 daily 时 FULL_DAY 仅靠 declared」合同；**不得**擅自新增事件类型。
