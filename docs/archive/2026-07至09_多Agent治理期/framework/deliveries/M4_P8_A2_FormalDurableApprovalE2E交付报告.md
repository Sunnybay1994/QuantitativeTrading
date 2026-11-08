<!-- Split index for `M4_P8_A2_FormalDurableApprovalE2E交付报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md)

# M4 P8 A2：Formal Durable Approval E2E 交付报告
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#m4-p8-a2formal-durable-approval-e2e-%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A)
## 1. 结果摘要
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#1-%E7%BB%93%E6%9E%9C%E6%91%98%E8%A6%81)
## 2. exact15 变更路径
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#2-exact15-%E5%8F%98%E6%9B%B4%E8%B7%AF%E5%BE%84)
## 3. 关键设计
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#3-%E5%85%B3%E9%94%AE%E8%AE%BE%E8%AE%A1)
## 4. 合同/边界说明
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#4-%E5%90%88%E5%90%8C%E8%BE%B9%E7%95%8C%E8%AF%B4%E6%98%8E)
## 5. 未运行项（强制 STATIC_ONLY）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#5-%E6%9C%AA%E8%BF%90%E8%A1%8C%E9%A1%B9%E5%BC%BA%E5%88%B6-static_only)
## 16. VALIDATION6 final-scope cache STOP（主 Agent 追加）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#16-validation6-final-scope-cache-stop%E4%B8%BB-agent-%E8%BF%BD%E5%8A%A0)
## 17. VALIDATION6 final-scope-1 cache STOP（主 Agent 追加）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#17-validation6-final-scope-1-cache-stop%E4%B8%BB-agent-%E8%BF%BD%E5%8A%A0)
## 18. VALIDATION6 residue close PASS（主 Agent 追加）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#18-validation6-residue-close-pass%E4%B8%BB-agent-%E8%BF%BD%E5%8A%A0)
## 10. VALIDATION2 运行证据收口（主 Agent 追加）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#10-validation2-%E8%BF%90%E8%A1%8C%E8%AF%81%E6%8D%AE%E6%94%B6%E5%8F%A3%E4%B8%BB-agent-%E8%BF%BD%E5%8A%A0)
## 11. VALIDATION3 carrier 解析失败收口（主 Agent 追加）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#11-validation3-carrier-%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%E6%94%B6%E5%8F%A3%E4%B8%BB-agent-%E8%BF%BD%E5%8A%A0)
## 12. VALIDATION4 focused STOP（主 Agent 追加）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#12-validation4-focused-stop%E4%B8%BB-agent-%E8%BF%BD%E5%8A%A0)
## 14. VALIDATION5 mypy STOP（主 Agent 追加）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#14-validation5-mypy-stop%E4%B8%BB-agent-%E8%BF%BD%E5%8A%A0)
## 7. REWORK1 问题闭环（追加；不改写首轮历史）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#7-rework1-%E9%97%AE%E9%A2%98%E9%97%AD%E7%8E%AF%E8%BF%BD%E5%8A%A0%E4%B8%8D%E6%94%B9%E5%86%99%E9%A6%96%E8%BD%AE%E5%8E%86%E5%8F%B2)
### F1：approve source identity 被弱化
### F2：fresh post-completion approve 丢失既有幂等 replay
### F3：existing receipt 的 command/outbox/ledger 闭包不完整
### F4：强制 no-op、rollback 与 formal composition 证据缺失
### F5：最小变更与时钟一致性
### REWORK1 未运行项 / 阻塞
## 8. REWORK2 问题闭环（追加；不改写首轮/REWORK1 历史）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#8-rework2-%E9%97%AE%E9%A2%98%E9%97%AD%E7%8E%AF%E8%BF%BD%E5%8A%A0%E4%B8%8D%E6%94%B9%E5%86%99%E9%A6%96%E8%BD%AErework1-%E5%8E%86%E5%8F%B2)
### 8.1 VALIDATION1 原生阶段结果（经理授权 focused 运行证据摘要）
### 8.2 exact17 扩围理由
### 8.3 F6–F10 六段证据
#### F6：capability Guard 与 source drift
#### F7：orphan 注入与 WAL bytes
#### F8：zero-command ORDER 与 semantic verifier
#### F9：pretrade source fixture
#### F10：资源 carrier
### 8.4 §14 中央合同实现要点
### 8.5 Reviewer P2/P3 残留边界（明确保留）
### 8.6 REWORK2 未运行项 / 阻塞
## 9. REWORK3 问题闭环（追加；不改写首轮/REWORK1/REWORK2 历史）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#9-rework3-%E9%97%AE%E9%A2%98%E9%97%AD%E7%8E%AF%E8%BF%BD%E5%8A%A0%E4%B8%8D%E6%94%B9%E5%86%99%E9%A6%96%E8%BD%AErework1rework2-%E5%8E%86%E5%8F%B2)
### 9.1 F11–F13 六段证据
#### F11：service 中央反例矩阵隔离覆盖
#### F12：reconcile approval/stage drift 反例
#### F13：RecoveryResult allow-set 身份边界诚实复核
### 9.2 REWORK3 未运行项 / 阻塞
## 13. REWORK4 问题闭环（追加；不改写首轮/REWORK1–3 / VALIDATION4 历史）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#13-rework4-%E9%97%AE%E9%A2%98%E9%97%AD%E7%8E%AF%E8%BF%BD%E5%8A%A0%E4%B8%8D%E6%94%B9%E5%86%99%E9%A6%96%E8%BD%AErework13--validation4-%E5%8E%86%E5%8F%B2)
### 13.1 F14–F17 六段证据
#### F14：approval raw 篡改保持 BLOB
#### F15：approval 专属读取失败映射 risk closure
#### F16：delivery orphan 使用真实 schema
#### F17：pretrade source fixture 真实、排序、值唯一
### 13.2 Reviewer P2/P3 / review E 残留边界（明确保留）
### 13.3 REWORK4 未运行项 / 阻塞
### 13.4 F14 合同漏项（主 Agent 发现；追加；不改写 §13.1 CAST 历史）
## 15. REWORK5 问题闭环（追加；不改写首轮/REWORK1–4 / VALIDATION5 历史）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md#15-rework5-%E9%97%AE%E9%A2%98%E9%97%AD%E7%8E%AF%E8%BF%BD%E5%8A%A0%E4%B8%8D%E6%94%B9%E5%86%99%E9%A6%96%E8%BD%AErework14--validation5-%E5%8E%86%E5%8F%B2)
### 15.1 F19 六段证据
#### F19：RecoveryError 暴露稳定 code
### 15.2 构造点静态核对（只读）
### 15.3 REWORK5 未运行项 / 阻塞
## 16. DOC-WHITESPACE 记录
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md#16-doc-whitespace-%E8%AE%B0%E5%BD%95)
