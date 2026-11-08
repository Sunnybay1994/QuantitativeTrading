<!-- Split index for `M4_UA006_R2_FormalBootstrapOperatorCLI独立初验报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md)

# M4-UA006-R2 Formal Bootstrap Operator CLI 独立初验报告
[↗](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#m4-ua006-r2-formal-bootstrap-operator-cli-%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A)
## 0. 审查边界
[↗](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#0-%E5%AE%A1%E6%9F%A5%E8%BE%B9%E7%95%8C)
## 1. 裁决
[↗](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#1-%E8%A3%81%E5%86%B3)
## 2. 合同核对矩阵（静态）
[↗](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#2-%E5%90%88%E5%90%8C%E6%A0%B8%E5%AF%B9%E7%9F%A9%E9%98%B5%E9%9D%99%E6%80%81)
## 3. 发现分级
[↗](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#3-%E5%8F%91%E7%8E%B0%E5%88%86%E7%BA%A7)
### [P1] P1-1 — 业务路径 `SystemExit` 绕过红acted exit 归一 — `run_paper_formal_bootstrap.py:262-267` vs `:269-314`
### [P1] P1-2 — `FormalPaperBootstrapError.code` 控制字符消毒不完整 — `run_paper_formal_bootstrap.py:302-308`
### [P2] P2-1 — 已存在的 `\n` code 闸无回归测
### 无 P0
## 4. 实现者未使用的静态对抗反例
[↗](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#4-%E5%AE%9E%E7%8E%B0%E8%80%85%E6%9C%AA%E4%BD%BF%E7%94%A8%E7%9A%84%E9%9D%99%E6%80%81%E5%AF%B9%E6%8A%97%E5%8F%8D%E4%BE%8B)
### AE-1 — 业务段 `SystemExit` 路径型 code（优先：argparse/SystemExit 泄漏族）
### AE-2 — hostile `error.code` 含 `\r` + 路径（优先：hostile control text）
## 5. 五项专项挑战结论
[↗](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#5-%E4%BA%94%E9%A1%B9%E4%B8%93%E9%A1%B9%E6%8C%91%E6%88%98%E7%BB%93%E8%AE%BA)
## 6. 只读 SHA / scope
[↗](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#6-%E5%8F%AA%E8%AF%BB-sha--scope)
## 7. 未运行边界（强制）
[↗](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#7-%E6%9C%AA%E8%BF%90%E8%A1%8C%E8%BE%B9%E7%95%8C%E5%BC%BA%E5%88%B6)
## 8. 最小返工建议（审查者不改代码）
[↗](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#8-%E6%9C%80%E5%B0%8F%E8%BF%94%E5%B7%A5%E5%BB%BA%E8%AE%AE%E5%AE%A1%E6%9F%A5%E8%80%85%E4%B8%8D%E6%94%B9%E4%BB%A3%E7%A0%81)
## 9. 结论
[↗](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#9-%E7%BB%93%E8%AE%BA)
## 10. REWORK1_REVIEW（相对 §1–§9 `REVIEW_FAIL`）
[↗](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#10-rework1_review%E7%9B%B8%E5%AF%B9-19-review_fail)
### 10.0 裁决
### 10.1 F1 — 业务段 `SystemExit` → runtime/3
### 10.2 F2 — stable token verbatim；否则整码 runtime
### 10.3 保持项复核（未放宽）
### 10.4 本轮现场 SHA（只读核）
### 10.5 未运行 / 不超宣称
### 10.6 收口
## 11. REWORK2_REVIEW（VALIDATION1 unit fixture；相对 §10 `REWORK1_REVIEW_PASS`）
[↗](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#11-rework2_reviewvalidation1-unit-fixture%E7%9B%B8%E5%AF%B9-10-rework1_review_pass)
### 11.0 裁决
### 11.1 Fixture 修正核对
### 11.2 冻结范围与 delivery 诚实性
### 11.3 VALIDATION1 历史边界（强制保留）
### 11.4 未运行 / 不超宣称
### 11.5 收口
## 12. REWORK3_REVIEW（VALIDATION2 integration identity；相对 §11 `REWORK2_REVIEW_PASS`）
[↗](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#12-rework3_reviewvalidation2-integration-identity%E7%9B%B8%E5%AF%B9-11-rework2_review_pass)
### 12.0 裁决
### 12.1 合同核对
### 12.2 冻结范围与 delivery 诚实性
### 12.3 VALIDATION2 历史边界（强制保留）
### 12.4 未运行 / 不超宣称
### 12.5 收口
## 13. REWORK4_REVIEW（VALIDATION3 完整 TIME_BOUND/DURABLE 分组；相对 §12 `REWORK3_REVIEW_PASS`）
[↗](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#13-rework4_reviewvalidation3-%E5%AE%8C%E6%95%B4-time_bounddurable-%E5%88%86%E7%BB%84%E7%9B%B8%E5%AF%B9-12-rework3_review_pass)
### 13.0 裁决
### 13.1 互斥分区核对
### 13.2 四次 fresh 样本与字段语义
### 13.3 冻结范围与 delivery 诚实性
### 13.4 VALIDATION3 历史边界（强制保留）
### 13.5 未运行 / 不超宣称
### 13.6 收口
## 14. REWORK5_REVIEW（VALIDATION4 callable 类型收敛；相对 §13 `REWORK4_REVIEW_PASS`）
[↗](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#14-rework5_reviewvalidation4-callable-%E7%B1%BB%E5%9E%8B%E6%94%B6%E6%95%9B%E7%9B%B8%E5%AF%B9-13-rework4_review_pass)
### 14.0 裁决
### 14.1 变更面核对
### 14.2 冻结 SHA 与写集
### 14.3 VALIDATION4 诚实边界（强制保留）
### 14.4 POSTFIX VALIDATION5 复用裁定
### 14.5 未运行 / 不超宣称
### 14.6 收口
## 15. EVIDENCE_REVIEW（任务书 §15 / delivery §13；FINAL）
[↗](M4_UA006_R2_FormalBootstrapOperatorCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#15-evidence_review%E4%BB%BB%E5%8A%A1%E4%B9%A6-15--delivery-13final)
### 15.0 裁决
### 15.1 POSTFIX VALIDATION5 证据根与 summary SHA
### 15.2 exact6 / cached0 / diff-check / residue
### 15.3 冻结字节（相对 §14.2 REWORK5）
### 15.4 V1–V4 首失败 / UNRUN 诚实性（只读核对磁盘）
### 15.5 组合闭包与状态上限（不超宣称）
### 15.6 收口
