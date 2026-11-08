<!-- Split index for `M3_G8F_R2S_FormalSummaryStagePublicationCompatibility任务书.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md) · [第 2 卷](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-02.md)

# M3-G8F-R2S Formal Summary Stage Publication Compatibility 任务书
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#m3-g8f-r2s-formal-summary-stage-publication-compatibility-%E4%BB%BB%E5%8A%A1%E4%B9%A6)
## 1. 背景与根因
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#1-%E8%83%8C%E6%99%AF%E4%B8%8E%E6%A0%B9%E5%9B%A0)
## 2. exact8 与角色
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#2-exact8-%E4%B8%8E%E8%A7%92%E8%89%B2)
## 3. 冻结 API 名称与职责
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#3-%E5%86%BB%E7%BB%93-api-%E5%90%8D%E7%A7%B0%E4%B8%8E%E8%81%8C%E8%B4%A3)
### 3.1 `evaluate.py`
### 3.2 `summary_stage.py`
## 4. Publication identity 与两阶段验证
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#4-publication-identity-%E4%B8%8E%E4%B8%A4%E9%98%B6%E6%AE%B5%E9%AA%8C%E8%AF%81)
## 5. 唯一 StageRunner wiring
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#5-%E5%94%AF%E4%B8%80-stagerunner-wiring)
## 6. 必须覆盖的反例
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#6-%E5%BF%85%E9%A1%BB%E8%A6%86%E7%9B%96%E7%9A%84%E5%8F%8D%E4%BE%8B)
## 7. 错误与禁止项
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#7-%E9%94%99%E8%AF%AF%E4%B8%8E%E7%A6%81%E6%AD%A2%E9%A1%B9)
## 8. 交付与验收
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#8-%E4%BA%A4%E4%BB%98%E4%B8%8E%E9%AA%8C%E6%94%B6)
## 9. STATIC_REWORK1：`evaluate.py` EOL 最小变更闭包
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#9-static_rework1evaluatepy-eol-%E6%9C%80%E5%B0%8F%E5%8F%98%E6%9B%B4%E9%97%AD%E5%8C%85)
## 10. ARCHITECTURE_STOP 与 CONTRACT_REFREEZE_B：三阶段 typed verification
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#10-architecture_stop-%E4%B8%8E-contract_refreeze_b%E4%B8%89%E9%98%B6%E6%AE%B5-typed-verification)
### 10.1 三个互斥强类型阶段
### 10.2 唯一 module-private closure dispatcher
### 10.3 执行顺序与反例
## 11. STATIC_REWORK2：EOL 误恢复后的语义重建
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#11-static_rework2eol-%E8%AF%AF%E6%81%A2%E5%A4%8D%E5%90%8E%E7%9A%84%E8%AF%AD%E4%B9%89%E9%87%8D%E5%BB%BA)
## 12. MANAGER_STATIC_REWORK3：preexisting final without receipt
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#12-manager_static_rework3preexisting-final-without-receipt)
## 13. REVIEW_FAIL → STATIC_REWORK4：temp leaf exact ownership 与 link/reparse 反例
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#13-review_fail--static_rework4temp-leaf-exact-ownership-%E4%B8%8E-linkreparse-%E5%8F%8D%E4%BE%8B)
## 14. REVIEW_FAIL → STATIC_REWORK5：dispatcher 原始叶身份闭包
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#14-review_fail--static_rework5dispatcher-%E5%8E%9F%E5%A7%8B%E5%8F%B6%E8%BA%AB%E4%BB%BD%E9%97%AD%E5%8C%85)
## 15. VALIDATION2 STOP 后的 STATIC_REWORK6：h10 fixture 字段归属
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#15-validation2-stop-%E5%90%8E%E7%9A%84-static_rework6h10-fixture-%E5%AD%97%E6%AE%B5%E5%BD%92%E5%B1%9E)
## 16. VALIDATION3 STOP 后的 STATIC_REWORK7：canonical summary plan fixture 闭包
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#16-validation3-stop-%E5%90%8E%E7%9A%84-static_rework7canonical-summary-plan-fixture-%E9%97%AD%E5%8C%85)
## 17. VALIDATION4 STOP 后的 STATIC_REWORK8：formal experiment publication fixture 闭包
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#17-validation4-stop-%E5%90%8E%E7%9A%84-static_rework8formal-experiment-publication-fixture-%E9%97%AD%E5%8C%85)
## 18. CONTRACT_STOP 后的 STATIC_REWORK9：public formal experiment publication fixture
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#18-contract_stop-%E5%90%8E%E7%9A%84-static_rework9public-formal-experiment-publication-fixture)
## 19. VALIDATION5 STOP 后的 STATIC_REWORK10：共享 worker monkeypatch 作用域隔离
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#19-validation5-stop-%E5%90%8E%E7%9A%84-static_rework10%E5%85%B1%E4%BA%AB-worker-monkeypatch-%E4%BD%9C%E7%94%A8%E5%9F%9F%E9%9A%94%E7%A6%BB)
## 20. VALIDATION6 CONTRACT_STOP 后的 STATIC_REWORK11：runtime identity 与 worker authority 分域
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-02.md#20-validation6-contract_stop-%E5%90%8E%E7%9A%84-static_rework11runtime-identity-%E4%B8%8E-worker-authority-%E5%88%86%E5%9F%9F)
## 21. VALIDATION7 STOP 后的 STATIC_REWORK12：测试真实身份与node选择闭包
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-02.md#21-validation7-stop-%E5%90%8E%E7%9A%84-static_rework12%E6%B5%8B%E8%AF%95%E7%9C%9F%E5%AE%9E%E8%BA%AB%E4%BB%BD%E4%B8%8Enode%E9%80%89%E6%8B%A9%E9%97%AD%E5%8C%85)
## 22. VALIDATION8 完整证据（Windows 工程验证闭合）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-02.md#22-validation8-%E5%AE%8C%E6%95%B4%E8%AF%81%E6%8D%AEwindows-%E5%B7%A5%E7%A8%8B%E9%AA%8C%E8%AF%81%E9%97%AD%E5%90%88)
### 22.1 证据根与阶段结果
### 22.2 阶段 stdout SHA-256
### 22.3 逐轮边界索引（不改写历史正文）
