<!-- Split index for `M4_P8_A2_FormalDurableApprovalE2E任务书.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md) · [第 2 卷](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-02.md)

# M4 P8 A2：Formal Durable Approval E2E 任务书
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#m4-p8-a2formal-durable-approval-e2e-%E4%BB%BB%E5%8A%A1%E4%B9%A6)
## 1. 目标与非目标
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#1-%E7%9B%AE%E6%A0%87%E4%B8%8E%E9%9D%9E%E7%9B%AE%E6%A0%87)
## 2. 权威前置与不变量
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#2-%E6%9D%83%E5%A8%81%E5%89%8D%E7%BD%AE%E4%B8%8E%E4%B8%8D%E5%8F%98%E9%87%8F)
## 3. 唯一写白名单
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#3-%E5%94%AF%E4%B8%80%E5%86%99%E7%99%BD%E5%90%8D%E5%8D%95)
## 4. Credential 与签发合同
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#4-credential-%E4%B8%8E%E7%AD%BE%E5%8F%91%E5%90%88%E5%90%8C)
## 5. CLI / formal daily 合同
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#5-cli--formal-daily-%E5%90%88%E5%90%8C)
## 6. 唯一 recovery 与原子事务合同
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#6-%E5%94%AF%E4%B8%80-recovery-%E4%B8%8E%E5%8E%9F%E5%AD%90%E4%BA%8B%E5%8A%A1%E5%90%88%E5%90%8C)
## 7. Risk 与 no-op 合同
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#7-risk-%E4%B8%8E-no-op-%E5%90%88%E5%90%8C)
## 8. 必须新增的反例
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#8-%E5%BF%85%E9%A1%BB%E6%96%B0%E5%A2%9E%E7%9A%84%E5%8F%8D%E4%BE%8B)
## 9. 失败语义
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#9-%E5%A4%B1%E8%B4%A5%E8%AF%AD%E4%B9%89)
## 10. 实现、初验与验证流程
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#10-%E5%AE%9E%E7%8E%B0%E5%88%9D%E9%AA%8C%E4%B8%8E%E9%AA%8C%E8%AF%81%E6%B5%81%E7%A8%8B)
## 11. 通过与停止条件
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#11-%E9%80%9A%E8%BF%87%E4%B8%8E%E5%81%9C%E6%AD%A2%E6%9D%A1%E4%BB%B6)
## 12. REWORK1：来源闭包、CLI replay 与孤儿闭包返工
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#12-rework1%E6%9D%A5%E6%BA%90%E9%97%AD%E5%8C%85cli-replay-%E4%B8%8E%E5%AD%A4%E5%84%BF%E9%97%AD%E5%8C%85%E8%BF%94%E5%B7%A5)
### F1：approve source identity 被弱化
### F2：fresh post-completion approve 丢失既有幂等 replay
### F3：existing receipt 的 command/outbox/ledger 闭包不完整
### F4：强制 no-op、rollback 与 formal composition 证据缺失
### F5：最小变更与时钟一致性
## 13. VALIDATION1 STOP 与 REWORK2
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#13-validation1-stop-%E4%B8%8E-rework2)
### F6：capability Guard 与 source drift 稳定错误测试不符合真实边界
### F7：orphan 注入测试违反 SQLite FK/WAL 语义
### F8：zero-command ORDER risk receipt 与既有全局 semantic verifier 冲突
### F9：pretrade 直测构造了非 canonical/值重复的 A1 source map
### F10：资源 carrier 收口
## 14. REWORK2 中央裁定：唯一 stage codec 与审批归属的 zero ORDER
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-01.md#14-rework2-%E4%B8%AD%E5%A4%AE%E8%A3%81%E5%AE%9A%E5%94%AF%E4%B8%80-stage-codec-%E4%B8%8E%E5%AE%A1%E6%89%B9%E5%BD%92%E5%B1%9E%E7%9A%84-zero-order)
### 14.1 F6 / F7 / F9 冻结修复
### 14.2 唯一 canonical stage codec
### 14.3 唯一 risk semantic verifier 的 zero ORDER 合同
### 14.4 service / reconcile 上下文闭包
### 14.5 REWORK2 强制反例与通过条件
## 15. REWORK3：持久化结构篡改反例补齐
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-02.md#15-rework3%E6%8C%81%E4%B9%85%E5%8C%96%E7%BB%93%E6%9E%84%E7%AF%A1%E6%94%B9%E5%8F%8D%E4%BE%8B%E8%A1%A5%E9%BD%90)
### F11：service 只覆盖 stage payload 与 approval index，未完整覆盖中央反例矩阵
### F12：reconcile 只有正向结构闭包，缺少 approval/stage drift 反例
### F13：RecoveryResult 新增 allow-set 字段的身份边界必须诚实复核
## 16. REWORK4：VALIDATION4 focused 五项失败最小返工
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-02.md#16-rework4validation4-focused-%E4%BA%94%E9%A1%B9%E5%A4%B1%E8%B4%A5%E6%9C%80%E5%B0%8F%E8%BF%94%E5%B7%A5)
### F14：approval raw 篡改必须保持 SQLite BLOB 类型
### F15：approval index 解码失败必须归入 risk closure
### F16：delivery orphan 必须使用真实 schema
### F17：pretrade source fixture 必须同时真实、排序且值唯一
### F18：验证与复验条件
## 17. REWORK5：RecoveryError 稳定 code 类型合同
[↗](M4_P8_A2_FormalDurableApprovalE2E%E4%BB%BB%E5%8A%A1%E4%B9%A6.part-02.md#17-rework5recoveryerror-%E7%A8%B3%E5%AE%9A-code-%E7%B1%BB%E5%9E%8B%E5%90%88%E5%90%8C)
### F19：RecoveryError 的运行时与类型合同不一致
### F14 合同漏项（主 Agent 发现；REWORK4 追加；保留 CAST 历史）
