<!-- Split index for `M2_AUDIT_V4_FlowSemantics独立初验报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md) · [第 3 卷](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md) · [第 4 卷](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-04.md)

# M2-AUDIT-V4-FLOW-SEMANTICS 独立初验报告
[↗](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#m2-audit-v4-flow-semantics-%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A)
## 结论
[↗](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#%E7%BB%93%E8%AE%BA)
## 审查边界与现场
[↗](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#%E5%AE%A1%E6%9F%A5%E8%BE%B9%E7%95%8C%E4%B8%8E%E7%8E%B0%E5%9C%BA)
## P0/P1 发现
[↗](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#p0p1-%E5%8F%91%E7%8E%B0)
### P0-1：B 阶段实际调用遗漏必需的 `threads` 参数
### P0-2：current latest conflict 会在 bucket 组装时解引用 `None`
### P1-1：safe normalized projection 没有实现任务书要求的 canonical/conflict projection 列
### P1-2：publisher strict validation 对顶层 counter 的 BOOLEAN 不 fail-closed
## §12 覆盖与 delivery 诚实性
[↗](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#12-%E8%A6%86%E7%9B%96%E4%B8%8E-delivery-%E8%AF%9A%E5%AE%9E%E6%80%A7)
## 独立新增静态对抗反例（实现者未使用）
[↗](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#%E7%8B%AC%E7%AB%8B%E6%96%B0%E5%A2%9E%E9%9D%99%E6%80%81%E5%AF%B9%E6%8A%97%E5%8F%8D%E4%BE%8B%E5%AE%9E%E7%8E%B0%E8%80%85%E6%9C%AA%E4%BD%BF%E7%94%A8)
## 结论边界
[↗](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#%E7%BB%93%E8%AE%BA%E8%BE%B9%E7%95%8C)
## REWORK4 FINAL STATIC RE-REVIEW（2026-08-28）
[↗](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#rework4-final-static-re-review2026-08-28)
### 结论与范围稳定性
### 首轮两项 P0 的 REWORK4 静态闭合
### 当前仍未闭合的 P1
#### P1-R4-1：publisher snapshot projection 仍对 raw economic columns 使用 `union_by_name=True`
#### P1-R4-2：B1 mixed-type 测试仍是 SQL 文本/伪 connection，不是实际 relation/row 行为证据
#### P1-R4-3：§12 的 source drift、BLOCKED 边界和 audit/manifest SHA 反例仍未由实现路径覆盖
#### P1-R4-4：publisher 把“非 required 的 nested/binary 列”错误升级为无效 source evidence
#### P1-R4-5：flow economic key 的 tuple 顺序不符合冻结的 exact identity
#### P1-R4-6：publisher 未校验 dataset `complete_rows` 与 quality `raw_rows` 的 v3 交叉一致性
### 其他合同项的静态核对结果
### REWORK4 独立新增静态对抗反例（实现者未使用）
### 最终判定
## STATIC_REWORK5_REVIEW_FAIL(P1)（2026-08-28）
[↗](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#static_rework5_review_failp12026-08-28)
### 结论与复验边界
### §12.1 六项静态复验
### P1-R5-1：publisher 未完整严格校验 quality schema/byte evidence 与 column-set 守恒
### P1-R5-2：`_verify_snapshot` 仍允许 manifest counter 的负值及 bool 等值混入
### P1-R5-3：§12.1 所要求的真实 mixed/publisher/nested 行为矩阵仍不完整
### P1-R5-4：publisher 新增边界测试的合法 audit fixture 静态缺少 fina_indicator dimension evidence
### P1-R5-5：exact economic-key 顺序已修生产代码但没有可区分的回归测试
### P1-R5-6：flow bucket strict validator 未拒绝不可能的派生计数
### 独立新增静态对抗反例
### delivery 与范围诚实性
### REWORK5 最终判定
## STATIC_REWORK6_REVIEW_PASS（2026-08-28）
[↗](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#static_rework6_review_pass2026-08-28)
### 结论与审查边界
### 绑定、稳定性与实际 diff
### §12.2 六项静态复验
### manager-return 控制流
### 独立新增静态对抗反例（实现者未使用，P2）
### delivery 诚实性与最终判定
## STATIC_REWORK7_REVIEW_PASS（2026-08-28）
[↗](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#static_rework7_review_pass2026-08-28)
### 结论与审查边界
### §12.3 六项静态复验
### 其余合同、冻结与 evidence honesty
### 本轮新增静态对抗反例（实现者未使用，P2；非 latest_previous_conflicts）
### STATIC_REWORK7 最终判定
## STATIC_REWORK8_REVIEW_PASS（2026-08-29）
[↗](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md#static_rework8_review_pass2026-08-29)
### 结论与审查边界
### §12.4 STATIC_REWORK8 六项静态复验
### 独立静态对抗反例（实现者未使用；非 P2 发现）
### STATIC_REWORK8 最终判定
## STATIC_REWORK9_REVIEW_PASS（2026-08-29）
[↗](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md#static_rework9_review_pass2026-08-29)
### 结论与审查边界
### 绑定证据与 scope/diff-check
### §12.5 四项 STATIC_REWORK9 静态复验
### 类型-only 范围与 delivery 诚实性
### 独立静态对抗反例（实现者未使用；非 P2 发现）
### STATIC_REWORK9 最终判定
## STATIC_REWORK10_REVIEW_PASS（2026-08-29）
[↗](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md#static_rework10_review_pass2026-08-29)
### 结论与审查边界
### 绑定证据与 scope/diff-check
### §12.6 STATIC_REWORK10 静态复验
### 独立静态对抗反例（实现者未使用；非 P2 发现）
### STATIC_REWORK10 最终判定
## FINAL_EVIDENCE_REVIEW_PASS（2026-08-29）
[↗](M2_AUDIT_V4_FlowSemantics%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-04.md#final_evidence_review_pass2026-08-29)
### 最终结论与边界
### 当前 exact7 与 review 写入前绑定
### 中央 grant 与原生 evidence 的逐项核对
### 独立静态对抗反例（实现者未使用；非 P2 发现）
### FINAL_EVIDENCE_REVIEW 最终判定
