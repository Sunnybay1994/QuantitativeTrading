<!-- Split index for `M3_G7F_R1正式A股三场景回测Artifact任务单.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md) · [第 2 卷](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-02.md)

# M3 G7F R1：正式 A 股三场景回测 Artifact 任务单
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#m3-g7f-r1%E6%AD%A3%E5%BC%8F-a-%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8B-artifact-%E4%BB%BB%E5%8A%A1%E5%8D%95)
## 1. 目标、硬前置与唯一职责
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#1-%E7%9B%AE%E6%A0%87%E7%A1%AC%E5%89%8D%E7%BD%AE%E4%B8%8E%E5%94%AF%E4%B8%80%E8%81%8C%E8%B4%A3)
## 2. Development reporting 三个已知缺口
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#2-development-reporting-%E4%B8%89%E4%B8%AA%E5%B7%B2%E7%9F%A5%E7%BC%BA%E5%8F%A3)
## 3. 冻结 public API、fresh context 与稳定错误
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#3-%E5%86%BB%E7%BB%93-public-apifresh-context-%E4%B8%8E%E7%A8%B3%E5%AE%9A%E9%94%99%E8%AF%AF)
## 4. Builder fresh 链与三次 actual G7E
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#4-builder-fresh-%E9%93%BE%E4%B8%8E%E4%B8%89%E6%AC%A1-actual-g7e)
## 5. 成本日程与 canonical cost hash
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#5-%E6%88%90%E6%9C%AC%E6%97%A5%E7%A8%8B%E4%B8%8E-canonical-cost-hash)
## 6. Strict metrics：统一 Decimal 后单向 float 投影
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#6-strict-metrics%E7%BB%9F%E4%B8%80-decimal-%E5%90%8E%E5%8D%95%E5%90%91-float-%E6%8A%95%E5%BD%B1)
## 7. Terminal estimated 1× exit cost
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#7-terminal-estimated-1-exit-cost)
## 8. 精确目录、文件、manifest 与 root bundle
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#8-%E7%B2%BE%E7%A1%AE%E7%9B%AE%E5%BD%95%E6%96%87%E4%BB%B6manifest-%E4%B8%8E-root-bundle)
## 9. Formal verifier、whole-rehash 与 hostile tree
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#9-formal-verifierwhole-rehash-%E4%B8%8E-hostile-tree)
## 10. Exact backtest receipt 闭包
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#10-exact-backtest-receipt-%E9%97%AD%E5%8C%85)
## 11. 文件白名单
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#11-%E6%96%87%E4%BB%B6%E7%99%BD%E5%90%8D%E5%8D%95)
## 12. 必测反例
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#12-%E5%BF%85%E6%B5%8B%E5%8F%8D%E4%BE%8B)
## 13. 双平台验证
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#13-%E5%8F%8C%E5%B9%B3%E5%8F%B0%E9%AA%8C%E8%AF%81)
## 14. 停止条件与外部闭环
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#14-%E5%81%9C%E6%AD%A2%E6%9D%A1%E4%BB%B6%E4%B8%8E%E5%A4%96%E9%83%A8%E9%97%AD%E7%8E%AF)
## 15. Formal 测试的模块化来源边界裁决（2026-08-10）
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#15-formal-%E6%B5%8B%E8%AF%95%E7%9A%84%E6%A8%A1%E5%9D%97%E5%8C%96%E6%9D%A5%E6%BA%90%E8%BE%B9%E7%95%8C%E8%A3%81%E5%86%B32026-08-10)
## 16. R1 独立初验 reload 顺序污染 R2 返工（2026-08-10）
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#16-r1-%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C-reload-%E9%A1%BA%E5%BA%8F%E6%B1%A1%E6%9F%93-r2-%E8%BF%94%E5%B7%A52026-08-10)
### 16.1 现象、根因与裁决
### 16.2 白名单、测试与通过条件
## 17. R3：正式 G1 `quality.json` 来源闭包与路径类型分离
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#17-r3%E6%AD%A3%E5%BC%8F-g1-qualityjson-%E6%9D%A5%E6%BA%90%E9%97%AD%E5%8C%85%E4%B8%8E%E8%B7%AF%E5%BE%84%E7%B1%BB%E5%9E%8B%E5%88%86%E7%A6%BB)
### 17.1 现象、根因和权威规则
### 17.2 冻结公共类型与 21-input
### 17.3 必测与兼容边界
### 17.4 本轮白名单与验证
## 18. R4：pre-final G1 Release 来源与实体绑定
[↗](M3_G7F_R1%E6%AD%A3%E5%BC%8FA%E8%82%A1%E4%B8%89%E5%9C%BA%E6%99%AF%E5%9B%9E%E6%B5%8BArtifact%E4%BB%BB%E5%8A%A1%E5%8D%95.part-01.md#18-r4pre-final-g1-release-%E6%9D%A5%E6%BA%90%E4%B8%8E%E5%AE%9E%E4%BD%93%E7%BB%91%E5%AE%9A)
### 18.1 现象—根因—规则—最小复现
### 18.2 精确实现合同
### 18.3 白名单与验证
