# M3 G9 共同类型层主 Agent 串行实现记录

日期：2026-08-13  
状态：共同不可变值类型完成；G9B subject resolver / EvidencePlan 仍等待 UA-M3-002，不宣称 G9B 完成

## 本轮范围

- 新增唯一 `acceptance.py`，集中定义 `GateName`、`EvidenceLocatorV1`、`AcceptanceIssueV1`、`GateResultV1`、`VerifiedRuntimeIdentity`、`RemoteTrackingObservationV1` 和 `AcceptanceDecisionV1`。
- 固定 G0→G9 顺序、PASS/FAIL 与 issue 的双向一致性、issue/evidence 稳定排序和唯一性、receipt 相对路径、SHA-256 与 tracking `FINISHED` 约束。
- 通过包级 lazy export 暴露共同类型，不加载 Qlib、LightGBM 或 MLflow。
- 未实现 `VerifiedAcceptanceSubject`、`AcceptanceEvidencePlanV1` 或 resolver/builder；它们缺失的 readiness receipt 与 comparison identity 来源已登记为 UA-M3-002。

## 开发检查

- `tests/unit/test_m3_acceptance_contracts.py`: `7 passed`。
- 定向 Ruff：通过。
- 定向 mypy：通过。
- cold import 与 scoped diff-check：通过。

## 边界

本轮仅建立后续 G9 checker 共享的严格值类型，未读取 artifact、未扫描目录、未发布 acceptance 结果，也不表示 G9 或 M3 Gate 通过。
