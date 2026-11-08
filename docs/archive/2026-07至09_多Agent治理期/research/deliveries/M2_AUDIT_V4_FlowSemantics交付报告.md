<!-- Split index for `M2_AUDIT_V4_FlowSemantics交付报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md) · [第 3 卷](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-03.md)

# M2-AUDIT-V4-FLOW-SEMANTICS 交付报告
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#m2-audit-v4-flow-semantics-%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A)
## 交付结论
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#%E4%BA%A4%E4%BB%98%E7%BB%93%E8%AE%BA)
## exact5 范围
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#exact5-%E8%8C%83%E5%9B%B4)
## exact 改动
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#exact-%E6%94%B9%E5%8A%A8)
### audit_tushare_financials.py
### publish_tushare_financials.py
### tests/unit/test_audit_tushare_financials.py 与 tests/unit/test_publish_tushare_financials.py
## 合同证据映射
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#%E5%90%88%E5%90%8C%E8%AF%81%E6%8D%AE%E6%98%A0%E5%B0%84)
## 未运行事项
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#%E6%9C%AA%E8%BF%90%E8%A1%8C%E4%BA%8B%E9%A1%B9)
## schema、I/O 与平台边界
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#schemaio-%E4%B8%8E%E5%B9%B3%E5%8F%B0%E8%BE%B9%E7%95%8C)
## 剩余风险与后续验收边界
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#%E5%89%A9%E4%BD%99%E9%A3%8E%E9%99%A9%E4%B8%8E%E5%90%8E%E7%BB%AD%E9%AA%8C%E6%94%B6%E8%BE%B9%E7%95%8C)
## STATIC_REWORK P0_SHORT_CIRCUIT_ORDER_TEST_CLOSURE（历史追加）
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#static_rework-p0_short_circuit_order_test_closure%E5%8E%86%E5%8F%B2%E8%BF%BD%E5%8A%A0)
### 现象
### 根因
### 应遵循规则
### 最小复现
### 新增测试
### 通过条件
## exact5 声明纠正
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#exact5-%E5%A3%B0%E6%98%8E%E7%BA%A0%E6%AD%A3)
## STATIC_REWORK2 P0_THREE_STAGE_AND_FIELD_DOMAIN（本次收束追加）
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#static_rework2-p0_three_stage_and_field_domain%E6%9C%AC%E6%AC%A1%E6%94%B6%E6%9D%9F%E8%BF%BD%E5%8A%A0)
### 现象
### 根因
### 应遵循规则
### 最小复现
### exact 改动
### 新增测试与通过条件
### 未运行事项与结论上限
## STATIC_REWORK3 P1_UNTOKENIZABLE_BLOCKING_AGGREGATION（本次收束追加）
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#static_rework3-p1_untokenizable_blocking_aggregation%E6%9C%AC%E6%AC%A1%E6%94%B6%E6%9D%9F%E8%BF%BD%E5%8A%A0)
### 现象
### 根因
### 应遵循规则
### 最小复现
### exact 改动
### 新增测试与通过条件
### 未运行事项与结论上限
## STATIC_REWORK4 P0_SHORT_CIRCUIT_AND_FIELD_DOMAIN（本次收束追加）
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#static_rework4-p0_short_circuit_and_field_domain%E6%9C%AC%E6%AC%A1%E6%94%B6%E6%9D%9F%E8%BF%BD%E5%8A%A0)
### 现象
### 根因
### 应遵循规则
### 最小复现
### exact 改动
### 新增测试与通过条件
### exact5 声明更正、未运行事项与结论上限
## MANAGER_SCOPE_REWORK4 P0_QUALITY_THREADS_AND_CURRENT_CONFLICT（本次收束追加）
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#manager_scope_rework4-p0_quality_threads_and_current_conflict%E6%9C%AC%E6%AC%A1%E6%94%B6%E6%9D%9F%E8%BF%BD%E5%8A%A0)
### 现象
### 根因
### 应遵循规则
### 最小复现
### exact 改动
### 新增测试与通过条件
### 对上一轮 premature fixed 声明的更正、未运行事项与结论上限
## STATIC_REWORK5 P0_THREE_STAGE_AND_FIELD_DOMAIN（§12.1 本次收束追加）
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md#static_rework5-p0_three_stage_and_field_domain121-%E6%9C%AC%E6%AC%A1%E6%94%B6%E6%9D%9F%E8%BF%BD%E5%8A%A0)
### 现象
### 根因
### 应遵循规则
### 最小复现
### exact 改动
### 新增测试与通过条件
### exact scope、未运行事项与结论上限
## STATIC_REWORK6
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md#static_rework6)
### 现象
### 根因
### 应遵循规则
### 最小复现
### 本轮 exact5 改动
### 新增测试与通过条件
### 未运行边界与结论
## STATIC_REWORK6_MANAGER_RETURN
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md#static_rework6_manager_return)
### 现象
### 根因
### 应遵循规则
### 最小复现
### 本轮改动与通过条件
### 未运行边界与结论
## STATIC_REWORK7
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md#static_rework7)
### 1. parameter-window A/B 双分支
### 2. physical-row-drift A/B 双分支
### 3. mixed safe projection 的 authoritative statement exact10 schema
### 4. source-evidence order fixture 的 exact required fields
### 5. public verifier import
### 6. required/extra nested fixture 的全部派生 identity 同步
### 本轮未运行边界与结论
## STATIC_REWORK8 — P0 exact4 E731 mechanical closure
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-03.md#static_rework8--p0-exact4-e731-mechanical-closure)
### 现象
### 根因
### 应遵循规则
### 最小复现
### 本轮改动与验证边界
### 结论
## STATIC_REWORK10 — P0 covariant read-only type closure
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-03.md#static_rework10--p0-covariant-read-only-type-closure)
### 现象
### 根因
### 应遵循规则
### 最小复现
### 修正
### 测试与未来通过条件
### 12.7 Validation6–9 组合证据与最终 evidence-review 边界
## STATIC_REWORK9 — P0 production type-only closure
[↗](M2_AUDIT_V4_FlowSemantics%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-03.md#static_rework9--p0-production-type-only-closure)
### 1. audit numeric-pair 联合容器注解
### 2. publisher source-evidence identifiers 先验证后收窄
### 3. publisher path 一次消费
### 4. manifest request_count stable local
### 本轮未运行边界与最高结论
