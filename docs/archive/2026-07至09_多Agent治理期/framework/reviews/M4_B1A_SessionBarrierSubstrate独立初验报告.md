<!-- Split index for `M4_B1A_SessionBarrierSubstrate独立初验报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M4_B1A_SessionBarrierSubstrate%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M4_B1A_SessionBarrierSubstrate%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md) · [第 3 卷](M4_B1A_SessionBarrierSubstrate%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md)

# M4-B1A Session Barrier Substrate 独立初验报告
[↗](M4_B1A_SessionBarrierSubstrate%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#m4-b1a-session-barrier-substrate-%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A)
## A. 初验历史（REVIEW_FAIL，保留）
[↗](M4_B1A_SessionBarrierSubstrate%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#a-%E5%88%9D%E9%AA%8C%E5%8E%86%E5%8F%B2review_fail%E4%BF%9D%E7%95%99)
### A.0 审查范围与方法（初验）
### A.1 初验裁决
### A.2 初验 Findings（按严重性）
#### [P0] `_HeldBarrierLock` 为 frozen，释放路径赋值必然崩溃 — `src/quant/execution/session_barrier.py:231-240,1237-1257`
#### [P1] 状态迁移路径「先 BEGIN 后持 barrier lock」— `store.py` + `session_barrier.py`
#### [P1] §8.6 lock 对抗面测试意图不完整 — `tests/unit/test_session_barrier.py`
#### [P1] §8.12 broker「所有写方法」未逐一证明 — `tests/unit/test_paper_broker_store.py`
#### [P2] `ExecutionStore.close` 不持 `_write_lock`，可与活跃 barrier 事务并发撕 handle/连接 — `store.py`
### A.3 初验对抗性反例（跨线程 close-vs-writer）
### A.4 初验 REVIEW_READY 摘要
## B. RE-REVIEW 历史（F1–F5 返工后，REVIEW_FAIL，保留）
[↗](M4_B1A_SessionBarrierSubstrate%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#b-re-review-%E5%8E%86%E5%8F%B2f1f5-%E8%BF%94%E5%B7%A5%E5%90%8Ereview_fail%E4%BF%9D%E7%95%99)
### B.1 复验裁决（历史）
### B.2 历史 Findings
#### [P0] 同线程活跃事务内 `store.close()` 自死锁 — `store.py`（当时）
### B.3 历史对抗反例
### B.4 历史 REVIEW_READY
## C. RE-RE-REVIEW（F5b 修复后，本轮第三名独立静态初验）
[↗](M4_B1A_SessionBarrierSubstrate%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#c-re-re-reviewf5b-%E4%BF%AE%E5%A4%8D%E5%90%8E%E6%9C%AC%E8%BD%AE%E7%AC%AC%E4%B8%89%E5%90%8D%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E5%88%9D%E9%AA%8C)
### C.0 范围与方法
### C.1 本轮裁决
### C.2 F5b 对抗复核（本轮重点）
#### C.2.1 同线程活跃 TX 内 `close()` → `CLOSE_DURING_TX`
#### C.2.2 跨线程 close 等 TX 完成再失效 handle
#### C.2.3 `_write_lock_owner` 登记 / 清除 / 无逃逸
### C.3 F1–F5 回归快扫（无新增回归）
### C.4 本轮 Findings
### C.5 本轮新增对抗性反例（实现者与前两轮初验均未使用）
### C.6 其他不变量（快扫，无新增 P0/P1）
### C.7 残留风险（不构成 FAIL）
### C.8 未运行检查清单
### C.9 REVIEW_READY（历史保留）
## D. VALIDATION1 Path 返工复验（第四名独立静态初验，本轮）
[↗](M4_B1A_SessionBarrierSubstrate%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#d-validation1-path-%E8%BF%94%E5%B7%A5%E5%A4%8D%E9%AA%8C%E7%AC%AC%E5%9B%9B%E5%90%8D%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E5%88%9D%E9%AA%8C%E6%9C%AC%E8%BD%AE)
### D.0 范围与方法
### D.1 VALIDATION1 证据绑定（20 failed / 1 skipped）
### D.2 本轮裁决
### D.3 Path guard 合同复核
### D.4 非 Path 面无漂移快扫
### D.5 本轮 Findings
### D.6 本轮新增对抗性反例（实现者未覆盖）
### D.7 残留风险（不构成 FAIL）
### D.8 未运行检查清单
### D.9 REVIEW_READY
## E. VALIDATION2 F1–F4 返工复验（第五名独立静态初验，本轮）
[↗](M4_B1A_SessionBarrierSubstrate%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#e-validation2-f1f4-%E8%BF%94%E5%B7%A5%E5%A4%8D%E9%AA%8C%E7%AC%AC%E4%BA%94%E5%90%8D%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E5%88%9D%E9%AA%8C%E6%9C%AC%E8%BD%AE)
### E.0 范围与方法
### E.1 VALIDATION2 证据绑定（4 failed）
### E.2 本轮范围 / 字节不变
### E.3 本轮裁决
### E.4 V2-F1 / F2 / F3 合同复核（通过）
### E.5 本轮 Findings
#### [P1] writer `ready` 前失败仍被 5s `wait` 超时掩盖；join 不断言线程退出；cleanup 二次异常可再掩盖 — `tests/unit/test_session_barrier.py:595-638`
### E.6 本轮新增对抗性反例（实现者未覆盖）
### E.7 残留风险（不构成额外 FAIL 项）
### E.8 未运行检查清单
### E.9 REVIEW_READY
## F. VALIDATION2-F5 返工复验（第六名独立静态初验，本轮）
[↗](M4_B1A_SessionBarrierSubstrate%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#f-validation2-f5-%E8%BF%94%E5%B7%A5%E5%A4%8D%E9%AA%8C%E7%AC%AC%E5%85%AD%E5%90%8D%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E5%88%9D%E9%AA%8C%E6%9C%AC%E8%BD%AE)
### F.0 范围与方法
### F.1 本轮范围 / 字节不变
### F.2 本轮裁决
### F.3 §E P1 合同闭合复核（通过）
### F.4 本轮 Findings
#### [P1] 三 pre-ready「无泄漏」反例用实例赋值替换原生 `Connection.close`，重演只读 native 方法风险 — `tests/unit/test_session_barrier.py:736-740,804-808,866-870`
### F.5 本轮新增对抗性反例（实现者未覆盖）
### F.6 残留风险（不构成额外 FAIL）
### F.7 未运行检查清单
### F.8 REVIEW_READY
## G. VALIDATION2-F6 返工复验（第六名独立静态续验，本轮）
[↗](M4_B1A_SessionBarrierSubstrate%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#g-validation2-f6-%E8%BF%94%E5%B7%A5%E5%A4%8D%E9%AA%8C%E7%AC%AC%E5%85%AD%E5%90%8D%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E7%BB%AD%E9%AA%8C%E6%9C%AC%E8%BD%AE)
### G.0 范围与方法
### G.1 本轮范围 / 字节不变
### G.2 本轮裁决
### G.3 §F P1 / V2-F6 合同复核
### G.4 本轮 Findings
### G.5 敌意核对（用户指定两点）
#### G.5.1 BEGIN：体先 close，finally 再 close — `closed` 证据是否充分？
#### G.5.2 issue 失败：`handle2 is None`，close 证明是否仍成立？
### G.6 本轮新增对抗性反例（实现者断言已覆盖、本轮核过）
### G.7 残留风险（不构成 FAIL）
### G.8 未运行检查清单
### G.9 REVIEW_READY
## H. VALIDATION3 返工复验（第六名独立静态续验，本轮）
[↗](M4_B1A_SessionBarrierSubstrate%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#h-validation3-%E8%BF%94%E5%B7%A5%E5%A4%8D%E9%AA%8C%E7%AC%AC%E5%85%AD%E5%90%8D%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E7%BB%AD%E9%AA%8C%E6%9C%AC%E8%BD%AE)
### H.0 范围与方法
### H.1 VALIDATION3 证据与文档绑定
### H.2 本轮范围 / 字节不变
### H.3 本轮裁决
### H.4 合同复核
### H.5 本轮 Findings
### H.6 本轮新增对抗性反例（实现者未单独成用例，静态捕获器已在）
### H.7 残留风险（不构成 FAIL）
### H.8 未运行检查清单
### H.9 REVIEW_READY
## I. VALIDATION4 production reentrancy 复验（第六名独立静态续验，本轮）
[↗](M4_B1A_SessionBarrierSubstrate%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#i-validation4-production-reentrancy-%E5%A4%8D%E9%AA%8C%E7%AC%AC%E5%85%AD%E5%90%8D%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E7%BB%AD%E9%AA%8C%E6%9C%AC%E8%BD%AE)
### I.0 范围与方法
### I.1 VALIDATION4 证据与文档绑定
### I.2 本轮范围 / 字节
### I.3 本轮裁决
### I.4 合同复核
### I.5 本轮 Findings
### I.6 本轮新增对抗性反例（实现者未单独成用例）
### I.7 残留风险（不构成 FAIL）
### I.8 未运行检查清单
### I.9 REVIEW_READY
## J. VALIDATION5-FIXTURE 复验（第六名独立静态续验，本轮）
[↗](M4_B1A_SessionBarrierSubstrate%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md#j-validation5-fixture-%E5%A4%8D%E9%AA%8C%E7%AC%AC%E5%85%AD%E5%90%8D%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E7%BB%AD%E9%AA%8C%E6%9C%AC%E8%BD%AE)
### J.0 范围与方法
### J.1 VALIDATION5 证据与文档绑定
### J.2 本轮范围 / 字节
### J.3 本轮裁决
### J.4 合同复核
### J.5 本轮 Findings
### J.6 本轮新增对抗性反例（实现者未单独成用例）
### J.7 残留风险（不构成 FAIL）
### J.8 未运行检查清单
### J.9 REVIEW_READY
## K. VALIDATION6-TYPE 复验（第六名独立静态续验，本轮）
[↗](M4_B1A_SessionBarrierSubstrate%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md#k-validation6-type-%E5%A4%8D%E9%AA%8C%E7%AC%AC%E5%85%AD%E5%90%8D%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E7%BB%AD%E9%AA%8C%E6%9C%AC%E8%BD%AE)
### K.0 范围与方法
### K.1 VALIDATION6 证据与文档绑定
### K.2 本轮范围 / 字节
### K.3 本轮裁决
### K.4 合同复核
### K.5 本轮 Findings
### K.6 本轮新增对抗性反例（实现者未单独成用例）
### K.7 残留风险（不构成 FAIL）
### K.8 未运行检查清单
### K.9 REVIEW_READY
## L. EVIDENCE_REVIEW（第六名独立静态续验，本轮）
[↗](M4_B1A_SessionBarrierSubstrate%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md#l-evidence_review%E7%AC%AC%E5%85%AD%E5%90%8D%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E7%BB%AD%E9%AA%8C%E6%9C%AC%E8%BD%AE)
### L.0 范围与方法
### L.1 文档 SHA 绑定
### L.2 VALIDATION6（中央接受组合）
### L.3 POSTFIX VALIDATION7
### L.4 exact11 scope 与 ignored evidence
### L.5 终态边界
### L.6 本轮裁决
### L.7 Findings
### L.8 未运行检查清单
### L.9 REVIEW_READY
## M. DOC_NORMALIZATION_REVIEW_ONLY（第六名独立静态续验，本轮）
[↗](M4_B1A_SessionBarrierSubstrate%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md#m-doc_normalization_review_only%E7%AC%AC%E5%85%AD%E5%90%8D%E7%8B%AC%E7%AB%8B%E9%9D%99%E6%80%81%E7%BB%AD%E9%AA%8C%E6%9C%AC%E8%BD%AE)
### M.0 范围与方法
### M.1 行尾空白 / 硬换行 / EOF
### M.2 文档 SHA 与证据
### M.3 裁决
