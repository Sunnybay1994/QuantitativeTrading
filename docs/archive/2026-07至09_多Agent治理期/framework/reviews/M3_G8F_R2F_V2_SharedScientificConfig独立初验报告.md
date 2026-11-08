<!-- Split index for `M3_G8F_R2F_V2_SharedScientificConfig独立初验报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M3_G8F_R2F_V2_SharedScientificConfig%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M3_G8F_R2F_V2_SharedScientificConfig%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md)

# M3-G8F-R2F-V2 Shared Scientific Config 独立初验报告
[↗](M3_G8F_R2F_V2_SharedScientificConfig%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#m3-g8f-r2f-v2-shared-scientific-config-%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A)
## 1. 审查身份、输入与边界
[↗](M3_G8F_R2F_V2_SharedScientificConfig%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#1-%E5%AE%A1%E6%9F%A5%E8%BA%AB%E4%BB%BD%E8%BE%93%E5%85%A5%E4%B8%8E%E8%BE%B9%E7%95%8C)
## 2. 任务合同逐项映射
[↗](M3_G8F_R2F_V2_SharedScientificConfig%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#2-%E4%BB%BB%E5%8A%A1%E5%90%88%E5%90%8C%E9%80%90%E9%A1%B9%E6%98%A0%E5%B0%84)
## 3. P1 发现（现象—根因—应遵循规则—最小复现—新增测试—通过条件）
[↗](M3_G8F_R2F_V2_SharedScientificConfig%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#3-p1-%E5%8F%91%E7%8E%B0%E7%8E%B0%E8%B1%A1%E6%A0%B9%E5%9B%A0%E5%BA%94%E9%81%B5%E5%BE%AA%E8%A7%84%E5%88%99%E6%9C%80%E5%B0%8F%E5%A4%8D%E7%8E%B0%E6%96%B0%E5%A2%9E%E6%B5%8B%E8%AF%95%E9%80%9A%E8%BF%87%E6%9D%A1%E4%BB%B6)
### P1-F1：same physical config 的第二 fold fresh read/load 没有测试证据
### P1-F2：same-config 下 work/gate/terminal 分离的强制集成断言缺失
## 4. 实现者未使用的对抗审查
[↗](M3_G8F_R2F_V2_SharedScientificConfig%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#4-%E5%AE%9E%E7%8E%B0%E8%80%85%E6%9C%AA%E4%BD%BF%E7%94%A8%E7%9A%84%E5%AF%B9%E6%8A%97%E5%AE%A1%E6%9F%A5)
## 5. 范围、字节与证据边界
[↗](M3_G8F_R2F_V2_SharedScientificConfig%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#5-%E8%8C%83%E5%9B%B4%E5%AD%97%E8%8A%82%E4%B8%8E%E8%AF%81%E6%8D%AE%E8%BE%B9%E7%95%8C)
## 6. 结论与返工闭环
[↗](M3_G8F_R2F_V2_SharedScientificConfig%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#6-%E7%BB%93%E8%AE%BA%E4%B8%8E%E8%BF%94%E5%B7%A5%E9%97%AD%E7%8E%AF)
## 7. STATIC_REWORK1 复验
[↗](M3_G8F_R2F_V2_SharedScientificConfig%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#7-static_rework1-%E5%A4%8D%E9%AA%8C)
### 7.1 P1-F1 复验：same physical fresh closure
### 7.2 P1-F2 复验：same-config 完整 closure
### 7.3 新发现 P1-F3：integration fresh-call count 与完整运行控制流矛盾
## 8. STATIC_REWORK1 结论
[↗](M3_G8F_R2F_V2_SharedScientificConfig%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#8-static_rework1-%E7%BB%93%E8%AE%BA)
## 9. STATIC_REWORK2 复验
[↗](M3_G8F_R2F_V2_SharedScientificConfig%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#9-static_rework2-%E5%A4%8D%E9%AA%8C)
### 9.1 §10 闭包复验
### 9.2 新发现 P1-F4：`all_read_calls` 不是完整原始读取序列，且其顺序断言与 production 控制流冲突
## 10. STATIC_REWORK2 结论
[↗](M3_G8F_R2F_V2_SharedScientificConfig%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#10-static_rework2-%E7%BB%93%E8%AE%BA)
## 11. STATIC_REWORK3 复验
[↗](M3_G8F_R2F_V2_SharedScientificConfig%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#11-static_rework3-%E5%A4%8D%E9%AA%8C)
### 11.1 §12 正确观测域与两轮 fresh closure
### 11.2 §10 其余闭包与对抗反例
### 11.3 结论与证据边界
## 12. STATIC_REWORK4 复验
[↗](M3_G8F_R2F_V2_SharedScientificConfig%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#12-static_rework4-%E5%A4%8D%E9%AA%8C)
### 12.1 replay prefix/suffix 行为等价
### 12.2 §10/§12 既有闭包与冻结复核
### 12.3 结论与证据边界
## 13. EVIDENCE_REVIEW
[↗](M3_G8F_R2F_V2_SharedScientificConfig%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#13-evidence_review)
### 13.1 V1–V5 证据逐项对账
### 13.2 组合范围与证据根边界
### 13.3 结论与剩余边界
