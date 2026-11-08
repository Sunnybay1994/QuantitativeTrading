<!-- Split index for `M2_AUDIT_V4_FlowSemantics任务书.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md) · [第 2 卷](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-02.md) · [第 3 卷](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-03.md)

# M2-AUDIT-V4 财务累计流量语义审计任务书
[↗](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#m2-audit-v4-%E8%B4%A2%E5%8A%A1%E7%B4%AF%E8%AE%A1%E6%B5%81%E9%87%8F%E8%AF%AD%E4%B9%89%E5%AE%A1%E8%AE%A1%E4%BB%BB%E5%8A%A1%E4%B9%A6)
## 1. 已满足前置与目标
[↗](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#1-%E5%B7%B2%E6%BB%A1%E8%B6%B3%E5%89%8D%E7%BD%AE%E4%B8%8E%E7%9B%AE%E6%A0%87)
## 2. exact 8、角色与禁止项
[↗](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#2-exact-8%E8%A7%92%E8%89%B2%E4%B8%8E%E7%A6%81%E6%AD%A2%E9%A1%B9)
## 3. v4 顶层与短路
[↗](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#3-v4-%E9%A1%B6%E5%B1%82%E4%B8%8E%E7%9F%AD%E8%B7%AF)
## 4. 固定 12 bucket、字段与排序
[↗](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#4-%E5%9B%BA%E5%AE%9A-12-bucket%E5%AD%97%E6%AE%B5%E4%B8%8E%E6%8E%92%E5%BA%8F)
## 5. source schema/type provenance 与 safe normalized union
[↗](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#5-source-schematype-provenance-%E4%B8%8E-safe-normalized-union)
### 5.1 每文件 metadata identity
### 5.2 safe union
### 5.3 exact source type family
## 6. 单一 canonicalizer、VARCHAR grammar 与 conflict token
[↗](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#6-%E5%8D%95%E4%B8%80-canonicalizervarchar-grammar-%E4%B8%8E-conflict-token)
## 7. 唯一 selection/chain 漏斗
[↗](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#7-%E5%94%AF%E4%B8%80-selectionchain-%E6%BC%8F%E6%96%97)
## 8. Float64 cent resolution 与 Decimal mismatch
[↗](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#8-float64-cent-resolution-%E4%B8%8E-decimal-mismatch)
## 9. untokenizable source 的 BLOCKED 语义
[↗](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#9-untokenizable-source-%E7%9A%84-blocked-%E8%AF%AD%E4%B9%89)
## 10. 漏斗守恒、coverage 与 bucket status
[↗](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#10-%E6%BC%8F%E6%96%97%E5%AE%88%E6%81%92coverage-%E4%B8%8E-bucket-status)
## 11. publisher strict validation 与公共 audit identity
[↗](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#11-publisher-strict-validation-%E4%B8%8E%E5%85%AC%E5%85%B1-audit-identity)
## 12. 必测对抗反例
[↗](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#12-%E5%BF%85%E6%B5%8B%E5%AF%B9%E6%8A%97%E5%8F%8D%E4%BE%8B)
### 12.1 STATIC_REWORK5 冻结合同
### 12.2 STATIC_REWORK6 冻结合同
### 12.3 Validation1 STOP 与 STATIC_REWORK7（tests-only）
### 12.4 Validation3 STOP 与 STATIC_REWORK8（audit test style-only）
### 12.5 Validation4 STOP 与 STATIC_REWORK9（production type-only）
### 12.6 Validation5 STOP 与 STATIC_REWORK10（covariant read-only type closure）
### 12.7 Validation6–9 组合证据与最终 evidence-review 边界
## 13. 实现、验证和真实数据阶段
[↗](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-03.md#13-%E5%AE%9E%E7%8E%B0%E9%AA%8C%E8%AF%81%E5%92%8C%E7%9C%9F%E5%AE%9E%E6%95%B0%E6%8D%AE%E9%98%B6%E6%AE%B5)
### 13.1 STATIC_ONLY
### 13.2 独立初验
### 13.3 validation-only（另申请）
### 13.4 真实 audit-v4（实现合流后另冻）
## 14. 交付与完成边界
[↗](M2_AUDIT_V4_FlowSemantics%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-03.md#14-%E4%BA%A4%E4%BB%98%E4%B8%8E%E5%AE%8C%E6%88%90%E8%BE%B9%E7%95%8C)
