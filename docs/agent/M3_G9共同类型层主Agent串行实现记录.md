# M3 G9 共同类型层主 Agent 串行实现记录

日期：2026-08-13  
状态：UA-M3-002 工程闭环已完成；G9B-F0 readiness evidence、subject resolver 与 EvidencePlan 已实现；真实 300 证券准入证据仍待 UA-M3-001 长运行

## 本轮范围

- 新增唯一 `acceptance.py`，集中定义 `GateName`、`EvidenceLocatorV1`、`AcceptanceIssueV1`、`GateResultV1`、`VerifiedRuntimeIdentity`、`RemoteTrackingObservationV1` 和 `AcceptanceDecisionV1`。
- 固定 G0→G9 顺序、PASS/FAIL 与 issue 的双向一致性、issue/evidence 稳定排序和唯一性、receipt 相对路径、SHA-256 与 tracking `FINISHED` 约束。
- 通过包级 lazy export 暴露共同类型，不加载 Qlib、LightGBM 或 MLflow。
- 新增 G9B-F0 `readiness-evidence` stage、verified artifact/receipt reader，并把唯一 stage registry 冻结为不可变公开视图。
- 实现 `VerifiedComparisonIdentityV1`、`VerifiedAcceptanceSubject`、`AcceptanceEvidencePlanV1`、`resolve_acceptance_subject` 与 `build_acceptance_evidence_plan`。
- resolver 只从当前 config、fresh formal resolver、readiness receipt、provider validation 与逐 fold×horizon reproducibility artifact 重建身份；EvidencePlan 只用 verified identities 与唯一 registry 构造定位，不扫描 artifact 目录。
- 尚未在真实 300 证券 public CLI 产物上运行 G9B；这属于 UA-M3-001 长运行及后续 G9C–G9G 的真实证据，不阻止当前工程接口完成。

## 开发检查

- `tests/unit/test_m3_acceptance_contracts.py` + `tests/unit/test_m3_readiness_evidence.py`: `14 passed`。
- 定向 Ruff：通过。
- 定向 mypy：通过。
- 包级 lazy export 已同步；最终 cold import 与 scoped diff-check 在本包收尾时执行。

## 边界

本轮完成 G9B 工程合同，但未运行真实 300 证券链、未发布最终 acceptance 结果，也不表示 G9 或 M3 Gate 通过。下一步按双轨路线先实施 UA-M3-001 资源受限性能改造并启动已批准长运行；长运行期间可继续策略研究快车道与文件互斥的工程工作。
