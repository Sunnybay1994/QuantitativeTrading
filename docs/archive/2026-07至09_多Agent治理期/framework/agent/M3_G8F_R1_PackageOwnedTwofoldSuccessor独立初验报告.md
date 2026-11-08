<!-- Split index for `M3_G8F_R1_PackageOwnedTwofoldSuccessor独立初验报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md) · [第 3 卷](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md)

# M3 G8F R1：Package-owned Two-fold Successor Runtime 独立初验报告
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#m3-g8f-r1package-owned-two-fold-successor-runtime-%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A)
## 1. 身份、范围与稳定性
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#1-%E8%BA%AB%E4%BB%BD%E8%8C%83%E5%9B%B4%E4%B8%8E%E7%A8%B3%E5%AE%9A%E6%80%A7)
## 2. 必须记录的终端事实
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#2-%E5%BF%85%E9%A1%BB%E8%AE%B0%E5%BD%95%E7%9A%84%E7%BB%88%E7%AB%AF%E4%BA%8B%E5%AE%9E)
## 3. 静态合同结论
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#3-%E9%9D%99%E6%80%81%E5%90%88%E5%90%8C%E7%BB%93%E8%AE%BA)
## 4. Findings
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#4-findings)
### F-1 [P1] 受控树只闭合普通文件，允许预先存在的空目录
### F-2 [P1] concrete production boundary 没有强制返回真实 PROJECT-only StageRunner
### F-3 [P1] fold/gate receipt 的关键 identity 没有由 package runtime 完整 join
### F-4 [P2] fresh gate verifier 收不到 terminal 的 fold/prior-gate 上下文
## 5. 覆盖与阻塞边界
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#5-%E8%A6%86%E7%9B%96%E4%B8%8E%E9%98%BB%E5%A1%9E%E8%BE%B9%E7%95%8C)
## 6. 压缩结论与 dispatch outcome
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#6-%E5%8E%8B%E7%BC%A9%E7%BB%93%E8%AE%BA%E4%B8%8E-dispatch-outcome)
## 7. REWORK2 corrected review（追加，不改写原 F1-F4 历史）
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#7-rework2-corrected-review%E8%BF%BD%E5%8A%A0%E4%B8%8D%E6%94%B9%E5%86%99%E5%8E%9F-f1-f4-%E5%8E%86%E5%8F%B2)
### 7.1 身份、稳定性与边界
### 7.2 F1：complete entry/directory closure
### 7.3 F2：真实 StageRunner、factory identity、PROJECT-only root 与 callback bypass
### 7.4 F3：scope_key join、_lookup_refs ownership 与物理 receipt reuse
### 7.5 F4：首次执行与 fresh replay 的 reconstructed context
### 7.6 四类新增测试是否到达实现路径
## 8. REWORK2 static review outcome
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#8-rework2-static-review-outcome)
## 9. REWORK3 corrected independent review
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#9-rework3-corrected-independent-review)
### 9.1 identity、稳定性与证据边界
### 9.2 REWORK3-F2：canonical public API binding 与 test substitution isolation
### 9.3 REWORK3-F3：deterministic Gate identity 与 scope joins
### 9.4 REWORK3-F3：global physical path、bytes digest、semantic owner 与 shared-node exception
### 9.5 reviewer-only 新对抗性反例（REWORK3-A1）
### 9.6 findings/evidence 压缩结论
## 10. REWORK3 static review outcome
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#10-rework3-static-review-outcome)
## 11. REWORK4 narrow static re-review：Path concrete subclass guard
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#11-rework4-narrow-static-re-reviewpath-concrete-subclass-guard)
### 11.1 identity、稳定性与静态证据边界
### 11.2 REWORK4-F1：concrete Path acceptance with exact root closure
### 11.3 new integration adversary reaches the implementation guard
### 11.4 validation evidence honesty
### 11.5 remaining gap and narrow outcome
## 12. REWORK4 DELIVERY_READY review path
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#12-rework4-delivery_ready-review-path)
## 13. REWORK5 DIAGNOSTIC2 narrow static re-review：fixture canonical labels route
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#13-rework5-diagnostic2-narrow-static-re-reviewfixture-canonical-labels-route)
### 13.1 identity、稳定性与范围
### 13.2 REWORK5-F1：fixture route 正确，但 adversarial proof 不足
### 13.3 taskbook/delivery traceability 与 unrun honesty
## 14. REWORK5 static review outcome
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#14-rework5-static-review-outcome)
## 15. REWORK6 独立静态复审：fixture callable lookup 闭环
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#15-rework6-%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E5%A4%8D%E5%AE%A1fixture-callable-lookup-%E9%97%AD%E7%8E%AF)
### 15.1 身份、范围与稳定性
### 15.2 R6-1：REWORK5 的 shared-marker/self-comparison 缺口已静态闭环
### 15.3 生产 binding、替代隔离与证据边界
### 15.4 REWORK6 静态结论
## 16. REWORK7 独立静态复审：horizon sentinel 缺省值闭环
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#16-rework7-%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E5%A4%8D%E5%AE%A1horizon-sentinel-%E7%BC%BA%E7%9C%81%E5%80%BC%E9%97%AD%E7%8E%AF)
### 16.1 身份、范围与稳定性
### 16.2 R7-1：`_effective_horizon` 的 `None` sentinel 语义
### 16.3 文档 traceability 与验证边界
### 16.4 REWORK7 静态结论
## 17. REWORK7 DELIVERY_READY
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#17-rework7-delivery_ready)
## 20. REWORK9 独立静态复审：regular-file link-count 平台守卫
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#20-rework9-%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E5%A4%8D%E5%AE%A1regular-file-link-count-%E5%B9%B3%E5%8F%B0%E5%AE%88%E5%8D%AB)
### 20.1 身份、范围与稳定性
### 20.2 R9-1：regular-file link-count 平台矩阵
### 20.3 R9-2：symlink/reparse 与 real-path second guard 未放宽
### 20.4 新增独立静态 adversarial counterexamples
### 20.5 文档证据与静态结论
### 20.6 REWORK9 静态结论
## 21. REWORK9 DELIVERY_READY
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#21-rework9-delivery_ready)
## 18. REWORK8 独立静态复审：exact shared receipt ownership 闭环
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#18-rework8-%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E5%A4%8D%E5%AE%A1exact-shared-receipt-ownership-%E9%97%AD%E7%8E%AF)
### 18.1 身份、范围与稳定性
### 18.2 R8-1：窄 shared ownership 例外及全部拒绝矩阵
### 18.3 新增独立静态 adversarial counterexample
### 18.4 global ownership 未被例外放宽与证据边界
### 18.5 REWORK8 静态结论
## 19. REWORK8 DELIVERY_READY
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md#19-rework8-delivery_ready)
## 22. REWORK10 独立静态复审：published attestation receipt tamper
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md#22-rework10-%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E5%A4%8D%E5%AE%A1published-attestation-receipt-tamper)
### 22.1 身份、范围与稳定性
### 22.2 R10-1：canonical published receipt 的唯一选择与 tamper 路径
### 22.3 R10-2：production verifier 的摘要、路径与错误闭包未被削弱
### 22.4 独立静态 adversarial counterexamples（当前 REWORK10 新增路径未覆盖）
### 22.5 文档证据边界与静态结论
### 22.6 REWORK10 静态结论
## 23. REWORK10 DELIVERY_READY
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md#23-rework10-delivery_ready)
## 24. REWORK11 独立静态复审：dependency typing 与 canonical bytes
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md#24-rework11-%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E5%A4%8D%E5%AE%A1dependency-typing-%E4%B8%8E-canonical-bytes)
### 24.1 身份、范围与稳定性
### 24.2 13 个 dependency 字段的类型与 fail-closed 守卫
### 24.3 字段顺序、固定 callback/run sequence 与 rename-only 变更
### 24.4 canonical bytes、schema 与新增测试路径
### 24.5 独立静态 adversarial counterexamples（实现者未使用）
### 24.6 文档证据边界与静态结论
### 24.7 REWORK11 静态结论
## 25. REWORK11 DELIVERY_READY
[↗](M3_G8F_R1_PackageOwnedTwofoldSuccessor%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md#25-rework11-delivery_ready)
