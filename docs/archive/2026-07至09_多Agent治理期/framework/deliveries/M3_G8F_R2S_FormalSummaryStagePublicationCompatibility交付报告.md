<!-- Split index for `M3_G8F_R2S_FormalSummaryStagePublicationCompatibility交付报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md)

# M3-G8F-R2S Formal Summary Stage Publication Compatibility 交付报告
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#m3-g8f-r2s-formal-summary-stage-publication-compatibility-%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A)
## 1. 现象—根因—规则—最小复现—新增测试—通过条件
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#1-%E7%8E%B0%E8%B1%A1%E6%A0%B9%E5%9B%A0%E8%A7%84%E5%88%99%E6%9C%80%E5%B0%8F%E5%A4%8D%E7%8E%B0%E6%96%B0%E5%A2%9E%E6%B5%8B%E8%AF%95%E9%80%9A%E8%BF%87%E6%9D%A1%E4%BB%B6)
## 2. exact diff（白名单 1–5、7）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#2-exact-diff%E7%99%BD%E5%90%8D%E5%8D%95-157)
## 3. 未运行边界（STATIC_ONLY）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#3-%E6%9C%AA%E8%BF%90%E8%A1%8C%E8%BE%B9%E7%95%8Cstatic_only)
## 4. 关键实现选择（合同内）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#4-%E5%85%B3%E9%94%AE%E5%AE%9E%E7%8E%B0%E9%80%89%E6%8B%A9%E5%90%88%E5%90%8C%E5%86%85)
## 5. STATIC_REWORK1：`evaluate.py` EOL 最小变更闭包
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#5-static_rework1evaluatepy-eol-%E6%9C%80%E5%B0%8F%E5%8F%98%E6%9B%B4%E9%97%AD%E5%8C%85)
## 6. ARCHITECTURE_STOP 与 CONTRACT_REFREEZE_B（任务书 §10）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#6-architecture_stop-%E4%B8%8E-contract_refreeze_b%E4%BB%BB%E5%8A%A1%E4%B9%A6-10)
## 7. STATIC_REWORK2：EOL 误恢复事故与语义重建（任务书 §11）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#7-static_rework2eol-%E8%AF%AF%E6%81%A2%E5%A4%8D%E4%BA%8B%E6%95%85%E4%B8%8E%E8%AF%AD%E4%B9%89%E9%87%8D%E5%BB%BA%E4%BB%BB%E5%8A%A1%E4%B9%A6-11)
## 8. MANAGER_STATIC_REWORK3：preexisting final without receipt（任务书 §12）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#8-manager_static_rework3preexisting-final-without-receipt%E4%BB%BB%E5%8A%A1%E4%B9%A6-12)
## 9. REVIEW_FAIL → STATIC_REWORK4：temp leaf exact ownership 与 link/reparse（任务书 §13）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#9-review_fail--static_rework4temp-leaf-exact-ownership-%E4%B8%8E-linkreparse%E4%BB%BB%E5%8A%A1%E4%B9%A6-13)
## 10. REVIEW_FAIL → STATIC_REWORK5：dispatcher 原始叶身份闭包（任务书 §14）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#10-review_fail--static_rework5dispatcher-%E5%8E%9F%E5%A7%8B%E5%8F%B6%E8%BA%AB%E4%BB%BD%E9%97%AD%E5%8C%85%E4%BB%BB%E5%8A%A1%E4%B9%A6-14)
## 11. VALIDATION2 STOP → STATIC_REWORK6：h10 fixture 字段归属（任务书 §15 / F4）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#11-validation2-stop--static_rework6h10-fixture-%E5%AD%97%E6%AE%B5%E5%BD%92%E5%B1%9E%E4%BB%BB%E5%8A%A1%E4%B9%A6-15--f4)
## 12. VALIDATION3 STOP → STATIC_REWORK7：canonical summary plan fixture（任务书 §16 / F5）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#12-validation3-stop--static_rework7canonical-summary-plan-fixture%E4%BB%BB%E5%8A%A1%E4%B9%A6-16--f5)
## 13. VALIDATION4 STOP → STATIC_REWORK8 / F6：`CONTRACT_STOP`（任务书 §17）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#13-validation4-stop--static_rework8--f6contract_stop%E4%BB%BB%E5%8A%A1%E4%B9%A6-17)
### F6 静态证据（未执行 Python；源码逐字）
## 14. STATIC_REWORK9 / §18：public formal experiment publication fixture
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#14-static_rework9--18public-formal-experiment-publication-fixture)
## 15. VALIDATION5 STOP → STATIC_REWORK10 / §19：共享 worker monkeypatch 作用域隔离
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#15-validation5-stop--static_rework10--19%E5%85%B1%E4%BA%AB-worker-monkeypatch-%E4%BD%9C%E7%94%A8%E5%9F%9F%E9%9A%94%E7%A6%BB)
## 16. VALIDATION6 STOP → STATIC_REWORK11 / §20：runtime identity 与 worker authority 分域
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#16-validation6-stop--static_rework11--20runtime-identity-%E4%B8%8E-worker-authority-%E5%88%86%E5%9F%9F)
## 17. VALIDATION7 STOP → STATIC_REWORK12 / §21：测试真实身份与 node 选择闭包
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#17-validation7-stop--static_rework12--21%E6%B5%8B%E8%AF%95%E7%9C%9F%E5%AE%9E%E8%BA%AB%E4%BB%BD%E4%B8%8E-node-%E9%80%89%E6%8B%A9%E9%97%AD%E5%8C%85)
## 18. VALIDATION8 完整证据（Windows 工程验证闭合）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md#18-validation8-%E5%AE%8C%E6%95%B4%E8%AF%81%E6%8D%AEwindows-%E5%B7%A5%E7%A8%8B%E9%AA%8C%E8%AF%81%E9%97%AD%E5%90%88)
### 18.1 证据根与阶段
### 18.2 阶段 stdout SHA-256
### 18.3 逐轮边界索引（历史不改写）
## 19. 终态声明
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md#19-%E7%BB%88%E6%80%81%E5%A3%B0%E6%98%8E)
