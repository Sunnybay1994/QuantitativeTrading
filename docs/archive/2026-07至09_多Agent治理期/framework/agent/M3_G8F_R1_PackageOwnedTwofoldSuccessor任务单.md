<!-- Split index for `M3_G8F_R1_PackageOwnedTwofoldSuccessor任务单.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md) · [第 2 卷](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-02.md)

# M3 G8F R1：Package-owned Two-fold Successor Runtime 与 Durable Terminal 任务单
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#m3-g8f-r1package-owned-two-fold-successor-runtime-%E4%B8%8E-durable-terminal-%E4%BB%BB%E5%8A%A1%E5%8D%95)
## 1. 目标
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#1-%E7%9B%AE%E6%A0%87)
## 2. 唯一写白名单
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#2-%E5%94%AF%E4%B8%80%E5%86%99%E7%99%BD%E5%90%8D%E5%8D%95)
## 3. 冻结合同
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#3-%E5%86%BB%E7%BB%93%E5%90%88%E5%90%8C)
### 3.1 输入与根边界
### 3.2 编排
### 3.3 durable terminal attestation
## 4. 必须覆盖的反例
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#4-%E5%BF%85%E9%A1%BB%E8%A6%86%E7%9B%96%E7%9A%84%E5%8F%8D%E4%BE%8B)
## 5. 实现与验证方式
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#5-%E5%AE%9E%E7%8E%B0%E4%B8%8E%E9%AA%8C%E8%AF%81%E6%96%B9%E5%BC%8F)
## 6. 通过与停止条件
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#6-%E9%80%9A%E8%BF%87%E4%B8%8E%E5%81%9C%E6%AD%A2%E6%9D%A1%E4%BB%B6)
## 7. REWORK1 问题闭环（F1-F4）
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#7-rework1-%E9%97%AE%E9%A2%98%E9%97%AD%E7%8E%AFf1-f4)
### F1：受控树的目录闭包
### F2：真实 StageRunner 与 PROJECT-only 拓扑
### F3：scope_key 与 execution/work 完整 join
### F4：fresh verifier 的 attestation context
## 8. REWORK2 问题闭环（F2-F3）
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#8-rework2-%E9%97%AE%E9%A2%98%E9%97%AD%E7%8E%AFf2-f3)
### F2：production public API binding
### F3：Gate scope join 与全局 receipt ownership
## 9. REWORK3 问题闭环（Path 类型守卫）
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#9-rework3-%E9%97%AE%E9%A2%98%E9%97%AD%E7%8E%AFpath-%E7%B1%BB%E5%9E%8B%E5%AE%88%E5%8D%AB)
### Path concrete subclass acceptance
### REWORK3 validation STOP evidence
## 10. REWORK5 DIAGNOSTIC2 闭环（fixture-only）
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#10-rework5-diagnostic2-%E9%97%AD%E7%8E%AFfixture-only)
### labels builder route
## 11. REWORK6 fixture callable lookup 闭环
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#11-rework6-fixture-callable-lookup-%E9%97%AD%E7%8E%AF)
### folds 与 label-reconciliation 的独立 callable
## 12. REWORK7 VALIDATION3 horizon sentinel 闭环
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#12-rework7-validation3-horizon-sentinel-%E9%97%AD%E7%8E%AF)
### `_effective_horizon` 的 None 语义
## 13. REWORK8 VALIDATION4 shared receipt ownership 闭环
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#13-rework8-validation4-shared-receipt-ownership-%E9%97%AD%E7%8E%AF)
### fold 间 exact shared receipt
## 14. REWORK9 DIAGNOSTIC5 regular-file link-count 闭环
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#14-rework9-diagnostic5-regular-file-link-count-%E9%97%AD%E7%8E%AF)
### 现象、根因与平台规则
### 最小复现、新测试与通过条件
### REWORK9 验证边界
## 15. REWORK10 VALIDATION7 attestation-bound receipt tamper 闭环
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#15-rework10-validation7-attestation-bound-receipt-tamper-%E9%97%AD%E7%8E%AF)
### 现象、根因与规则
### 最小复现、新测试与通过条件
### REWORK10 验证边界
## 16. REWORK11 VALIDATION8 dependency typing 与 canonical bytes 闭环
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E4%BB%BB%E5%8A%A1%E5%8D%95.part-02.md#16-rework11-validation8-dependency-typing-%E4%B8%8E-canonical-bytes-%E9%97%AD%E7%8E%AF)
### 现象、根因与类型规则
### 最小复现、新测试与通过条件
### REWORK11 验证边界
