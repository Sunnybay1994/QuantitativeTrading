<!-- Split index for `M4_P8_A2_FormalDurableApprovalE2E独立初验报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md)

# M4 P8 A2：Formal Durable Approval E2E 独立初验报告
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#m4-p8-a2formal-durable-approval-e2e-%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A)
## 0. 审查边界
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#0-%E5%AE%A1%E6%9F%A5%E8%BE%B9%E7%95%8C)
## 1. 中央合同逐项证据
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#1-%E4%B8%AD%E5%A4%AE%E5%90%88%E5%90%8C%E9%80%90%E9%A1%B9%E8%AF%81%E6%8D%AE)
## 2. REWORK1 F1–F5 对抗核对
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#2-rework1-f1f5-%E5%AF%B9%E6%8A%97%E6%A0%B8%E5%AF%B9)
## 3. 发现分级
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#3-%E5%8F%91%E7%8E%B0%E5%88%86%E7%BA%A7)
### 无 P0 / P1
### [P2] 合法 capability 的字段级 `object.__new__` 克隆仍可通过 unpack — `src/quant/execution/approval_flow.py`
### [P3] capability 相等性忽略 `_secret`/`_proof`
## 4. 实现者未使用的静态对抗反例（至少一例）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#4-%E5%AE%9E%E7%8E%B0%E8%80%85%E6%9C%AA%E4%BD%BF%E7%94%A8%E7%9A%84%E9%9D%99%E6%80%81%E5%AF%B9%E6%8A%97%E5%8F%8D%E4%BE%8B%E8%87%B3%E5%B0%91%E4%B8%80%E4%BE%8B)
## 5. 未运行边界（强制）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#5-%E6%9C%AA%E8%BF%90%E8%A1%8C%E8%BE%B9%E7%95%8C%E5%BC%BA%E5%88%B6)
## 6. 结论
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#6-%E7%BB%93%E8%AE%BA)
## 7. 报告 SHA256（DOC-WHITESPACE 规范化后重签）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#7-%E6%8A%A5%E5%91%8A-sha256doc-whitespace-%E8%A7%84%E8%8C%83%E5%8C%96%E5%90%8E%E9%87%8D%E7%AD%BE)
## 8. REWORK2/3 静态复验（追加；不改写 §0–§7）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#8-rework23-%E9%9D%99%E6%80%81%E5%A4%8D%E9%AA%8C%E8%BF%BD%E5%8A%A0%E4%B8%8D%E6%94%B9%E5%86%99-07)
### 8.1 exact17 边界
### 8.2 中央 §14 + F6–F13 对抗核对
### 8.3 发现分级（REWORK2/3）
### 无 P0 / P1
### 既有 [P2]/[P3]（复核保留，非本轮新开）
### 8.4 实现者未使用的静态对抗反例（本轮新增）
### 8.5 未运行边界（强制）
### 8.6 复验结论
## 9. REWORK2/3 复验报告 SHA256（DOC-WHITESPACE 规范化后重签）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#9-rework23-%E5%A4%8D%E9%AA%8C%E6%8A%A5%E5%91%8A-sha256doc-whitespace-%E8%A7%84%E8%8C%83%E5%8C%96%E5%90%8E%E9%87%8D%E7%AD%BE)
## 10. REWORK4 静态复验（追加；不改写 §0–§9）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#10-rework4-%E9%9D%99%E6%80%81%E5%A4%8D%E9%AA%8C%E8%BF%BD%E5%8A%A0%E4%B8%8D%E6%94%B9%E5%86%99-09)
### 10.1 本轮变更边界（生产字节）
### 10.2 F14–F17 对抗证据映射
### 10.3 发现分级（REWORK4）
### 无 P0 / P1
### 既有 [P2]/[P3] / review E（复核保留，非本轮新开）
### 10.4 实现者未使用的静态对抗反例（本轮新增）
### 10.5 未运行边界（强制）
### 10.6 复验结论
## 11. REWORK4 复验报告 SHA256（前置说明；DOC-WHITESPACE 规范化后重签）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#11-rework4-%E5%A4%8D%E9%AA%8C%E6%8A%A5%E5%91%8A-sha256%E5%89%8D%E7%BD%AE%E8%AF%B4%E6%98%8Edoc-whitespace-%E8%A7%84%E8%8C%83%E5%8C%96%E5%90%8E%E9%87%8D%E7%AD%BE)
## 12. REWORK5 / F19 静态复验（追加；不改写 §0–§11）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#12-rework5--f19-%E9%9D%99%E6%80%81%E5%A4%8D%E9%AA%8C%E8%BF%BD%E5%8A%A0%E4%B8%8D%E6%94%B9%E5%86%99-011)
### 12.1 F19 合同逐项证据
### 12.2 发现分级（REWORK5）
### 无 P0 / P1
### 既有 [P2]/[P3] / review E（复核保留，非本轮新开）
### [P3] 外部改写 `.code` 后 `args`/`str` 仍保留构造期稳定码 — `src/quant/execution/reconcile.py`
### 12.3 实现者未使用的静态对抗反例（本轮新增）
### 12.4 未运行边界（强制）
### 12.5 复验结论
## 13. REWORK5 复验报告 SHA256（前置说明；DOC-WHITESPACE 规范化后重签）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#13-rework5-%E5%A4%8D%E9%AA%8C%E6%8A%A5%E5%91%8A-sha256%E5%89%8D%E7%BD%AE%E8%AF%B4%E6%98%8Edoc-whitespace-%E8%A7%84%E8%8C%83%E5%8C%96%E5%90%8E%E9%87%8D%E7%AD%BE)
## 14. VALIDATION5/6 独立证据复核（追加；不改写 §0–§13）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#14-validation56-%E7%8B%AC%E7%AB%8B%E8%AF%81%E6%8D%AE%E5%A4%8D%E6%A0%B8%E8%BF%BD%E5%8A%A0%E4%B8%8D%E6%94%B9%E5%86%99-013)
### 14.1 逐根 exit / stdout / stderr / summary 与声称 SHA
### 14.2 Cache STOP 诚实性（不掩盖产品失败）
### 14.3 P2 / P3 / review E / H / I 诚实性
### 14.4 执行者未使用的证据对抗检查（本轮新增）
### 14.5 逐文件 SHA 抽查（补充）
### 14.6 未运行边界（本复核强制）
### 14.7 发现分级与结论
### 无 P0 / P1
### 无证据矛盾
## 15. VALIDATION5/6 证据复核报告 SHA256（前置说明；DOC-WHITESPACE 规范化后重签）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#15-validation56-%E8%AF%81%E6%8D%AE%E5%A4%8D%E6%A0%B8%E6%8A%A5%E5%91%8A-sha256%E5%89%8D%E7%BD%AE%E8%AF%B4%E6%98%8Edoc-whitespace-%E8%A7%84%E8%8C%83%E5%8C%96%E5%90%8E%E9%87%8D%E7%AD%BE)
## 16. DOC-WHITESPACE 独立复核（追加；不改写 §0–§15 业务结论）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#16-doc-whitespace-%E7%8B%AC%E7%AB%8B%E5%A4%8D%E6%A0%B8%E8%BF%BD%E5%8A%A0%E4%B8%8D%E6%94%B9%E5%86%99-015-%E4%B8%9A%E5%8A%A1%E7%BB%93%E8%AE%BA)
### 16.1 三文档行尾空白
### 16.2 格式语义与写集
### 16.3 `git diff --check` 预期与 untracked 说明
### 16.4 业务结论复核（未改）
## 17. DOC-WHITESPACE 复核报告 SHA256（前置说明）
[↗](M4_P8_A2_FormalDurableApprovalE2E%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#17-doc-whitespace-%E5%A4%8D%E6%A0%B8%E6%8A%A5%E5%91%8A-sha256%E5%89%8D%E7%BD%AE%E8%AF%B4%E6%98%8E)
