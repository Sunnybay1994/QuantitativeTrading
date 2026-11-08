<!-- Split index for `M4_B1B2_TerminalSessionClosure交付报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md) · [第 3 卷](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-03.md)

# M4-B1B2 Terminal Session Closure 交付报告
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#m4-b1b2-terminal-session-closure-%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A)
## 1. 实现摘要
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#1-%E5%AE%9E%E7%8E%B0%E6%91%98%E8%A6%81)
## 2. 修改文件清单（actual dirty ⊂ exact31）
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#2-%E4%BF%AE%E6%94%B9%E6%96%87%E4%BB%B6%E6%B8%85%E5%8D%95actual-dirty--exact31)
### Production（8）
### Tests（4）
### Docs（1，实现者独占）
## 3. Public / private capability 边界
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#3-public--private-capability-%E8%BE%B9%E7%95%8C)
## 4. Durable step schema / identity（无 migration）
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#4-durable-step-schema--identity%E6%97%A0-migration)
## 5. INFRA-007 闭合
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#5-infra-007-%E9%97%AD%E5%90%88)
## 6. 对抗性反例覆盖（测试映射）
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#6-%E5%AF%B9%E6%8A%97%E6%80%A7%E5%8F%8D%E4%BE%8B%E8%A6%86%E7%9B%96%E6%B5%8B%E8%AF%95%E6%98%A0%E5%B0%84)
## 7. 设计备注 / 审查焦点（非 STOP，需 reviewer 挑战）
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#7-%E8%AE%BE%E8%AE%A1%E5%A4%87%E6%B3%A8--%E5%AE%A1%E6%9F%A5%E7%84%A6%E7%82%B9%E9%9D%9E-stop%E9%9C%80-reviewer-%E6%8C%91%E6%88%98)
## 8. 未运行项（STATIC_ONLY）
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#8-%E6%9C%AA%E8%BF%90%E8%A1%8C%E9%A1%B9static_only)
## 9. 建议 Windows 验证顺序（经理申请资源后；当前不可启动）
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#9-%E5%BB%BA%E8%AE%AE-windows-%E9%AA%8C%E8%AF%81%E9%A1%BA%E5%BA%8F%E7%BB%8F%E7%90%86%E7%94%B3%E8%AF%B7%E8%B5%84%E6%BA%90%E5%90%8E%E5%BD%93%E5%89%8D%E4%B8%8D%E5%8F%AF%E5%90%AF%E5%8A%A8)
## 10. STOP 核对
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#10-stop-%E6%A0%B8%E5%AF%B9)
## 11. 交接
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#11-%E4%BA%A4%E6%8E%A5)
## 12. CONTRACT_DEVIATION_STOP / STATIC_ONLY_BREACH — 不可覆盖取证
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#12-contract_deviation_stop--static_only_breach--%E4%B8%8D%E5%8F%AF%E8%A6%86%E7%9B%96%E5%8F%96%E8%AF%81)
### 12.1 裁定与现象
### 12.2 执行者 / 子会话身份
### 12.3 解释器 / cwd / 时间
### 12.4 精确命令 / 文件 / 输出
### 12.5 影响范围判定
### 12.6 执行前后 scope / hash 证据
#### 本取证时刻 actual14 清单
### 12.7 冻结与禁止
### 12.8 交接状态
## 13. AUTHORIZED_REIMPLEMENTATION_ADOPTION
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#13-authorized_reimplementation_adoption)
### 13.1 采用身份与约束
### 13.2 逐文件采用 / 修正结论
### 13.3 Actual scope（采用完成时）
### 13.4 未运行边界（再次确认）
### 13.5 合同充分性
## 14. AUTHORIZED_REWORK_R1（exact33 / F1–F4）
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#14-authorized_rework_r1exact33--f1f4)
### 14.1 F1 — formal CLOSED 持久化 exact terminal successor
### 14.2 F2 — zero-command ORDER closure 回归 soak SSOT
### 14.3 F3 — terminal child 写集分域
### 14.4 F4 — soak evidence 锁内 fresh 闭包
### 14.5 Actual exact33 scope（R1 完成时）
### 14.6 未运行边界
### 14.7 交接
## 15. AUTHORIZED_REWORK_R2（exact33 / R1-F2 + R1-F3）
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-01.md#15-authorized_rework_r2exact33--r1-f2--r1-f3)
### 15.1 R1-F2 — true zero-command identity / Gate / 测例统一
### 15.2 R1-F3 — closure view 不暴露可 commit 的 OMS 面
### 15.3 Actual exact33 scope（R2 本轮触及）
### 15.4 未运行边界
### 15.5 交接
## 16. AUTHORIZED_REIMPLEMENTATION_ADOPTION_R2（2026-08-26）
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md#16-authorized_reimplementation_adoption_r22026-08-26)
### 16.1 采用身份与方法
### 16.2 逐文件采用结论（相对采用前 working-tree SHA；delta=0）
### 16.3 冻结合同映射（静态）
### 16.4 无效证据隔离（§12 + §15.4）
### 16.5 Actual scope / 边界（采用完成时）
### 16.6 未运行边界
### 16.7 交接
## 17. REWORK_AFTER_VALIDATION1（任务书 §12；2026-08-26）
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md#17-rework_after_validation1%E4%BB%BB%E5%8A%A1%E4%B9%A6-122026-08-26)
### 17.1 Fixture — v010 fresh 父目录
### 17.2 Fixture — barrier schema_version==10
### 17.3 Terminal — zero-command 首次链 `PAPER_SOAK_SESSION_INVALID`
### 17.4 Terminal — mid-sequence same-token retry `PAPER_SOAK_SESSION_INVALID`
### 17.5 逐步静态映射（公开窄接口）
### 17.6 Actual scope / 证据边界
### 17.7 交接
## 18. VALIDATION2 Ruff test-only 收敛（任务书 §13；2026-08-26）
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md#18-validation2-ruff-test-only-%E6%94%B6%E6%95%9B%E4%BB%BB%E5%8A%A1%E4%B9%A6-132026-08-26)
### 18.1 VALIDATION2 证据
### 18.2 六要素
### 18.3 Actual scope / 边界
### 18.4 交接
## 19. POSTFIX VALIDATION3 context-manager 类型合同（任务书 §14；2026-08-26）
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md#19-postfix-validation3-context-manager-%E7%B1%BB%E5%9E%8B%E5%90%88%E5%90%8C%E4%BB%BB%E5%8A%A1%E4%B9%A6-142026-08-26)
### 19.1 VALIDATION3 证据
### 19.2 六要素
### 19.3 Actual scope / 边界
### 19.4 交接
## 20. Windows 工程验证组合闭包（任务书 §15；2026-08-26）
[↗](M4_B1B2_TerminalSessionClosure%E4%BA%A4%E4%BB%98%E6%8A%A5%E5%91%8A.part-02.md#20-windows-%E5%B7%A5%E7%A8%8B%E9%AA%8C%E8%AF%81%E7%BB%84%E5%90%88%E9%97%AD%E5%8C%85%E4%BB%BB%E5%8A%A1%E4%B9%A6-152026-08-26)
### 20.1 组合边界（通过条件）
### 20.2 VALIDATION1–4 真实链（首失败与 UNRUN 不洗白）
### 20.3 scope-close1–5（首失败保留；5 PASS）
#### scope-close5 actual19 清单（⊆ exact33）
### 20.4 本闭合会话边界
### 20.5 交接
