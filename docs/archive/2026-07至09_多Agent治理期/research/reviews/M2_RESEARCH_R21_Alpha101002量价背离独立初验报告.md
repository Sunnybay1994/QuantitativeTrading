<!-- Split index for `M2_RESEARCH_R21_Alpha101002量价背离独立初验报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M2_RESEARCH_R21_Alpha101002%E9%87%8F%E4%BB%B7%E8%83%8C%E7%A6%BB%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M2_RESEARCH_R21_Alpha101002%E9%87%8F%E4%BB%B7%E8%83%8C%E7%A6%BB%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md)

# M2 Research R21 Alpha101 #002 量价背离独立初验报告
[↗](M2_RESEARCH_R21_Alpha101002%E9%87%8F%E4%BB%B7%E8%83%8C%E7%A6%BB%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#m2-research-r21-alpha101-002-%E9%87%8F%E4%BB%B7%E8%83%8C%E7%A6%BB%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A)
## 结论
[↗](M2_RESEARCH_R21_Alpha101002%E9%87%8F%E4%BB%B7%E8%83%8C%E7%A6%BB%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#%E7%BB%93%E8%AE%BA)
## 审查边界与 exact4 现场
[↗](M2_RESEARCH_R21_Alpha101002%E9%87%8F%E4%BB%B7%E8%83%8C%E7%A6%BB%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#%E5%AE%A1%E6%9F%A5%E8%BE%B9%E7%95%8C%E4%B8%8E-exact4-%E7%8E%B0%E5%9C%BA)
## P1 发现
[↗](M2_RESEARCH_R21_Alpha101002%E9%87%8F%E4%BB%B7%E8%83%8C%E7%A6%BB%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#p1-%E5%8F%91%E7%8E%B0)
### P1-1：首个 exact8 测试 fixture 必然产生零方差 volume rank，却断言三项 finite
### P1-2：第 12 节要求的核心对抗矩阵没有被测试文件逐项覆盖
## 逐项静态判定
[↗](M2_RESEARCH_R21_Alpha101002%E9%87%8F%E4%BB%B7%E8%83%8C%E7%A6%BB%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#%E9%80%90%E9%A1%B9%E9%9D%99%E6%80%81%E5%88%A4%E5%AE%9A)
## 独立新增静态对抗反例（实现者未使用）
[↗](M2_RESEARCH_R21_Alpha101002%E9%87%8F%E4%BB%B7%E8%83%8C%E7%A6%BB%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#%E7%8B%AC%E7%AB%8B%E6%96%B0%E5%A2%9E%E9%9D%99%E6%80%81%E5%AF%B9%E6%8A%97%E5%8F%8D%E4%BE%8B%E5%AE%9E%E7%8E%B0%E8%80%85%E6%9C%AA%E4%BD%BF%E7%94%A8)
## 最终判定
[↗](M2_RESEARCH_R21_Alpha101002%E9%87%8F%E4%BB%B7%E8%83%8C%E7%A6%BB%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#%E6%9C%80%E7%BB%88%E5%88%A4%E5%AE%9A)
## 补充静态裁定（同一 review 上下文）
[↗](M2_RESEARCH_R21_Alpha101002%E9%87%8F%E4%BB%B7%E8%83%8C%E7%A6%BB%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#%E8%A1%A5%E5%85%85%E9%9D%99%E6%80%81%E8%A3%81%E5%AE%9A%E5%90%8C%E4%B8%80-review-%E4%B8%8A%E4%B8%8B%E6%96%87)
### P1-3：intraday return 的 alias 绑定范围不满足确定的输出列合同
### 对 P1-1 的措辞修正
## STATIC_REWORK 独立复验（同一 reviewer，返工后）
[↗](M2_RESEARCH_R21_Alpha101002%E9%87%8F%E4%BB%B7%E8%83%8C%E7%A6%BB%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#static_rework-%E7%8B%AC%E7%AB%8B%E5%A4%8D%E9%AA%8C%E5%90%8C%E4%B8%80-reviewer%E8%BF%94%E5%B7%A5%E5%90%8E)
### 复验边界与 exact3
### 已闭合项
### P1-4：内部缺 bar 测试的行数断言与输出 key 合同矛盾
### P2-1：仍有少量合同矩阵仅由实现源码而非行为测试锁定
### 复验结论
## FINAL_STATIC_REVIEW_PASS（同一 reviewer，最终返工复验）
[↗](M2_RESEARCH_R21_Alpha101002%E9%87%8F%E4%BB%B7%E8%83%8C%E7%A6%BB%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#final_static_review_pass%E5%90%8C%E4%B8%80-reviewer%E6%9C%80%E7%BB%88%E8%BF%94%E5%B7%A5%E5%A4%8D%E9%AA%8C)
### 绑定证据与边界
### P1/P2 闭合
### 最终判定
## Validation2 后 §15 新独立静态复验
[↗](M2_RESEARCH_R21_Alpha101002%E9%87%8F%E4%BB%B7%E8%83%8C%E7%A6%BB%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#validation2-%E5%90%8E-15-%E6%96%B0%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E5%A4%8D%E9%AA%8C)
### 输入身份、范围与证据强度
### 已静态闭合的修正
### P1-§15-MATRIX：只核 A 的输出 rank，不满足冻结的全部中间值合同
### 另一独立边界挑战：lag1 零成交量不等于缺 bar
### 本轮最终裁定
## §15.1 MATRIX 同一独立 reviewer 定向复验 PASS
[↗](M2_RESEARCH_R21_Alpha101002%E9%87%8F%E4%BB%B7%E8%83%8C%E7%A6%BB%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#151-matrix-%E5%90%8C%E4%B8%80%E7%8B%AC%E7%AB%8B-reviewer-%E5%AE%9A%E5%90%91%E5%A4%8D%E9%AA%8C-pass)
### 唯一 P1 的逐项闭合
### 最终结论与执行边界
## Validation3–5 evidence-only 独立收口
[↗](M2_RESEARCH_R21_Alpha101002%E9%87%8F%E4%BB%B7%E8%83%8C%E7%A6%BB%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#validation35-evidence-only-%E7%8B%AC%E7%AB%8B%E6%94%B6%E5%8F%A3)
### 独立读取的 authority 与可见性
### 实际命令偏差、cache与保留边界
### 前后身份及历史不混用
### 独立对抗裁判
### 最终状态上限
