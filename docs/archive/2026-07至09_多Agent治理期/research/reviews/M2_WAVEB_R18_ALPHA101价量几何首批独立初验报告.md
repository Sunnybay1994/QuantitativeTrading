<!-- Split index for `M2_WAVEB_R18_ALPHA101价量几何首批独立初验报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M2_WAVEB_R18_ALPHA101%E4%BB%B7%E9%87%8F%E5%87%A0%E4%BD%95%E9%A6%96%E6%89%B9%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M2_WAVEB_R18_ALPHA101%E4%BB%B7%E9%87%8F%E5%87%A0%E4%BD%95%E9%A6%96%E6%89%B9%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md)

# REVIEW_FAIL / STATIC_ONLY
[↗](M2_WAVEB_R18_ALPHA101%E4%BB%B7%E9%87%8F%E5%87%A0%E4%BD%95%E9%A6%96%E6%89%B9%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#review_fail--static_only)
## 审查身份与边界
[↗](M2_WAVEB_R18_ALPHA101%E4%BB%B7%E9%87%8F%E5%87%A0%E4%BD%95%E9%A6%96%E6%89%B9%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#%E5%AE%A1%E6%9F%A5%E8%BA%AB%E4%BB%BD%E4%B8%8E%E8%BE%B9%E7%95%8C)
## 结论
[↗](M2_WAVEB_R18_ALPHA101%E4%BB%B7%E9%87%8F%E5%87%A0%E4%BD%95%E9%A6%96%E6%89%B9%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#%E7%BB%93%E8%AE%BA)
## P1-001：负 absolute RankCorr 可漏过 redundancy admission
[↗](M2_WAVEB_R18_ALPHA101%E4%BB%B7%E9%87%8F%E5%87%A0%E4%BD%95%E9%A6%96%E6%89%B9%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#p1-001%E8%B4%9F-absolute-rankcorr-%E5%8F%AF%E6%BC%8F%E8%BF%87-redundancy-admission)
### 现象
### 根因
### 应遵循规则
### 最小复现
### 新增的独立静态对抗反例/测试要求
### 通过条件
## 逐项静态核对
[↗](M2_WAVEB_R18_ALPHA101%E4%BB%B7%E9%87%8F%E5%87%A0%E4%BD%95%E9%A6%96%E6%89%B9%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#%E9%80%90%E9%A1%B9%E9%9D%99%E6%80%81%E6%A0%B8%E5%AF%B9)
### 1. Alpha101 公式、单位、strict exchange-session gap、窗口/null 与 fail-closed
### 2. Bar1dSchema、wide schema、ordered columns/dtypes/keys/sorting、有限值和无 cross-sectional rank
### 3. config raw bytes、strict parse/raw SHA、cost semantic identity 与 artifact 前 fail-closed
### 4. trial identity、snapshot/universe/fold/horizon/signal/next-open/close/cost identity
### 5. R17 对称 redundancy、incident pair/duplicate/coverage、RankIC/direction/2x cost 与只降级不升级
### 6. shared panel/folds/cost/schedule 与 cost input
### 7. mocked orchestration exact 13 outputs、恢复历史与 DELIVERED STATIC_ONLY 表述
## exact8 稳定性、未运行边界与剩余风险
[↗](M2_WAVEB_R18_ALPHA101%E4%BB%B7%E9%87%8F%E5%87%A0%E4%BD%95%E9%A6%96%E6%89%B9%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#exact8-%E7%A8%B3%E5%AE%9A%E6%80%A7%E6%9C%AA%E8%BF%90%E8%A1%8C%E8%BE%B9%E7%95%8C%E4%B8%8E%E5%89%A9%E4%BD%99%E9%A3%8E%E9%99%A9)
### exact8 输入
### 未运行
### 剩余风险
## 审查终态
[↗](M2_WAVEB_R18_ALPHA101%E4%BB%B7%E9%87%8F%E5%87%A0%E4%BD%95%E9%A6%96%E6%89%B9%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#%E5%AE%A1%E6%9F%A5%E7%BB%88%E6%80%81)
## P1-001 RE-REVIEW（STATIC_ONLY）
[↗](M2_WAVEB_R18_ALPHA101%E4%BB%B7%E9%87%8F%E5%87%A0%E4%BD%95%E9%A6%96%E6%89%B9%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#p1-001-re-reviewstatic_only)
### 复验结论
### P1-001 本轮记录（保留原始历史）
### 修复静态证据
### 既有语义回归静态核对
### exact8 与交付状态稳定性
## P1-001 STATIC_REVIEW_RECHECK（RECHECK_PASS / STATIC_ONLY）
[↗](M2_WAVEB_R18_ALPHA101%E4%BB%B7%E9%87%8F%E5%87%A0%E4%BD%95%E9%A6%96%E6%89%B9%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#p1-001-static_review_recheckrecheck_pass--static_only)
### 复验范围与结论
### P1-001 修复证据
### 实现者未使用反例与既有语义
### 三路径变更边界与交付状态
## VALIDATION3 P1 RECHECK — RECHECK_PASS / STATIC_ONLY
[↗](M2_WAVEB_R18_ALPHA101%E4%BB%B7%E9%87%8F%E5%87%A0%E4%BD%95%E9%A6%96%E6%89%B9%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#validation3-p1-recheck--recheck_pass--static_only)
### 身份、范围与结论
### 冻结修复核对
### 对抗测试与 fail-closed 边界
### 交付证据、写入边界与未运行声明
### Validation3 通过条件
## Validation3 P1 RECHECK — RECHECK_PASS / STATIC_ONLY
[↗](M2_WAVEB_R18_ALPHA101%E4%BB%B7%E9%87%8F%E5%87%A0%E4%BD%95%E9%A6%96%E6%89%B9%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#validation3-p1-recheck--recheck_pass--static_only-1)
### 身份、范围与结论
### Validation3 P1 修复核对
### 对抗测试与 fail-closed 证据
### 交付证据、写入边界与未运行声明
### Validation3 通过条件
## VALIDATION5 F401 RECHECK — RECHECK_PASS / STATIC_ONLY
[↗](M2_WAVEB_R18_ALPHA101%E4%BB%B7%E9%87%8F%E5%87%A0%E4%BD%95%E9%A6%96%E6%89%B9%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#validation5-f401-recheck--recheck_pass--static_only)
### 1. 身份、范围与结论
### 2. F401 direct-import 核对
### 3. 权威 identity 与测试逻辑/输出断言
### 4. Delivery Validation5 证据映射
### 5. Git 实际 scope 核对
### 6. 未运行边界与通过条件
## VALIDATION7 TYPE REWORK REVIEW_PASS / STATIC_ONLY
[↗](M2_WAVEB_R18_ALPHA101%E4%BB%B7%E9%87%8F%E5%87%A0%E4%BD%95%E9%A6%96%E6%89%B9%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#validation7-type-rework-review_pass--static_only)
### 1. 身份、输入与结论
### 2. `_is_exact_float` 类型收窄与数值合同
### 3. Delivery 证据与历史边界
### 4. Git 实际 scope 与未运行边界
### 5. 通过条件与后续
## R18 ECONOMIC POLICY AND EVIDENCE REVIEW_PASS / STATIC_ONLY
[↗](M2_WAVEB_R18_ALPHA101%E4%BB%B7%E9%87%8F%E5%87%A0%E4%BD%95%E9%A6%96%E6%89%B9%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#r18-economic-policy-and-evidence-review_pass--static_only)
### 1. 身份、输入与结论
### 2. chosen-outcome Gate 与经济政策
### 3. 权威终态、候选状态与 trial ledger
### 4. V8/V9/real-run/diagnostic 原生证据与 SHA
### 5. Git scope、历史保留与终态边界
### 6. 通过条件与后续
