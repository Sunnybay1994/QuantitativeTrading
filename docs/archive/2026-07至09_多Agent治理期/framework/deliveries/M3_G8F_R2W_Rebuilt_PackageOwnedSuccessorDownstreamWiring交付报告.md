<!-- Split index for `M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring交付报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md)

# M3-G8F-R2W Rebuilt Package-Owned Successor Downstream Wiring 交付报告
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#m3-g8f-r2w-rebuilt-package-owned-successor-downstream-wiring-%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A)
## 1. 旧 STOP 如何被解除
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#1-%E6%97%A7-stop-%E5%A6%82%E4%BD%95%E8%A2%AB%E8%A7%A3%E9%99%A4)
## 2. 修改路径（exact12 内）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#2-%E4%BF%AE%E6%94%B9%E8%B7%AF%E5%BE%84exact12-%E5%86%85)
## 3. API 调用图（压缩）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#3-api-%E8%B0%83%E7%94%A8%E5%9B%BE%E5%8E%8B%E7%BC%A9)
## 4. 现象—根因—规则—最小复现—新增测试—通过条件（首轮）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#4-%E7%8E%B0%E8%B1%A1%E6%A0%B9%E5%9B%A0%E8%A7%84%E5%88%99%E6%9C%80%E5%B0%8F%E5%A4%8D%E7%8E%B0%E6%96%B0%E5%A2%9E%E6%B5%8B%E8%AF%95%E9%80%9A%E8%BF%87%E6%9D%A1%E4%BB%B6%E9%A6%96%E8%BD%AE)
## 5. 未运行边界（STATIC_ONLY）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#5-%E6%9C%AA%E8%BF%90%E8%A1%8C%E8%BE%B9%E7%95%8Cstatic_only)
## 6. 静态卫生
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#6-%E9%9D%99%E6%80%81%E5%8D%AB%E7%94%9F)
## 7. STATIC_REWORK1 闭环（对照 taskbook §10 / 独立初验 F1–F3）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#7-static_rework1-%E9%97%AD%E7%8E%AF%E5%AF%B9%E7%85%A7-taskbook-10--%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C-f1f3)
### F1 — Summary Gate 必须调用 R2S public fresh verifier
### F2 — Tracking 真实行为级 prior closure
### F3 — Readiness physical-vs-aggregate 对抗
## 8. REWORK1 退出
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#8-rework1-%E9%80%80%E5%87%BA)
## 9. VALIDATION1 证据与 F4 test-only 闭环（taskbook §11）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#9-validation1-%E8%AF%81%E6%8D%AE%E4%B8%8E-f4-test-only-%E9%97%AD%E7%8E%AFtaskbook-11)
### 9.1 VALIDATION1 有效证据（如实，未重跑）
### 9.2 F4 — public rehydrate 返回类型测试边界
### 9.3 本轮退出
## 10. VALIDATION2 证据与 F5 test-only 闭环（taskbook §12）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#10-validation2-%E8%AF%81%E6%8D%AE%E4%B8%8E-f5-test-only-%E9%97%AD%E7%8E%AFtaskbook-12)
### 10.1 VALIDATION2 有效证据（如实，未重跑）
### 10.2 F5 — downstream 同类 public 返回类型误检
### 10.3 本轮退出
## 11. VALIDATION3 证据与 F6 test-only 闭环（taskbook §13）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#11-validation3-%E8%AF%81%E6%8D%AE%E4%B8%8E-f6-test-only-%E9%97%AD%E7%8E%AFtaskbook-13)
### 11.1 VALIDATION3 有效证据（如实，未重跑）
### 11.2 F6 — integration fixture 共享 subprocess authority 恢复
### 11.3 本轮退出
## 12. VALIDATION4 证据与 F7 test-only 闭环（taskbook §14）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#12-validation4-%E8%AF%81%E6%8D%AE%E4%B8%8E-f7-test-only-%E9%97%AD%E7%8E%AFtaskbook-14)
### 12.1 VALIDATION4 有效证据（如实，未重跑）
### 12.2 F7 — Authority B 受控 feature worker ownership
### 12.3 本轮退出
## 13. VALIDATION8 证据与 F8 test-only 闭环（taskbook §15）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#13-validation8-%E8%AF%81%E6%8D%AE%E4%B8%8E-f8-test-only-%E9%97%AD%E7%8E%AFtaskbook-15)
### 13.1 VALIDATION8 有效证据（如实，未重跑）
### 13.2 F8 — unit Authority B feature-worker seam
### 13.3 本轮退出
## 14. F8 独立初验 P1 最小返工（taskbook §16）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#14-f8-%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C-p1-%E6%9C%80%E5%B0%8F%E8%BF%94%E5%B7%A5taskbook-16)
### 14.1 现象—根因—规则—最小复现—修正—通过条件
### 14.2 本轮退出
## 15. VALIDATION9 证据与 F10 test-only 闭环（taskbook §17）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#15-validation9-%E8%AF%81%E6%8D%AE%E4%B8%8E-f10-test-only-%E9%97%AD%E7%8E%AFtaskbook-17)
### 15.1 VALIDATION9 有效证据（如实，未重跑）
### 15.2 F10 — integration positive verifier seam
### 15.3 本轮退出
## 16. VALIDATION10 证据与 F11 类型/float 收窄（taskbook §18）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#16-validation10-%E8%AF%81%E6%8D%AE%E4%B8%8E-f11-%E7%B1%BB%E5%9E%8Bfloat-%E6%94%B6%E7%AA%84taskbook-18)
### 16.1 VALIDATION10 有效证据（如实，未重跑）
### 16.2 F11 — 七处 canonical 返回类型与 config float
### 16.3 本轮退出
## 17. VALIDATION11 证据与 F12 局部名分离（taskbook §19）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md#17-validation11-%E8%AF%81%E6%8D%AE%E4%B8%8E-f12-%E5%B1%80%E9%83%A8%E5%90%8D%E5%88%86%E7%A6%BBtaskbook-19)
### 17.1 VALIDATION11 有效证据（如实，未重跑）
### 17.2 F12 — backtest/tracking 结果局部名
### 17.3 本轮退出
## 18. VALIDATION12 终态与组合证据（taskbook §20）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md#18-validation12-%E7%BB%88%E6%80%81%E4%B8%8E%E7%BB%84%E5%90%88%E8%AF%81%E6%8D%AEtaskbook-20)
### 18.1 历史 STOP 保留（不得改写）
### 18.2 VALIDATION12 PASS（F12 后；组合口径）
### 18.3 终态边界
### 18.4 本轮退出（证据更新 only）
