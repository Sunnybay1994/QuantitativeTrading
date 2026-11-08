<!-- Split index for `M4_B1B2_TerminalSessionClosure独立初验报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md) · [第 3 卷](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md)

# M4-B1B2 Terminal Session Closure 独立初验报告
[↗](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#m4-b1b2-terminal-session-closure-%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A)
## 0. 裁决
[↗](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#0-%E8%A3%81%E5%86%B3)
## 1. 范围与只读证据
[↗](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#1-%E8%8C%83%E5%9B%B4%E4%B8%8E%E5%8F%AA%E8%AF%BB%E8%AF%81%E6%8D%AE)
## 2. 逐项静态核验矩阵
[↗](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#2-%E9%80%90%E9%A1%B9%E9%9D%99%E6%80%81%E6%A0%B8%E9%AA%8C%E7%9F%A9%E9%98%B5)
## 3. 实现者未使用的对抗性反例（本审查新增）
[↗](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#3-%E5%AE%9E%E7%8E%B0%E8%80%85%E6%9C%AA%E4%BD%BF%E7%94%A8%E7%9A%84%E5%AF%B9%E6%8A%97%E6%80%A7%E5%8F%8D%E4%BE%8B%E6%9C%AC%E5%AE%A1%E6%9F%A5%E6%96%B0%E5%A2%9E)
### AE-1 — CLOSED replay + `successor=None` 无法拒绝链篡改
### AE-2 — zero-command fallback 可写入与 soak 包不同域的 durable 身份
### AE-3 — 预锁 soak 快照 TOCTOU / partial-step orphan
### AE-4 — `transaction_under_terminal_child` + 错误 step_kind 域
### AE-5 — `object.__new__` / 反射（补充）
## 4. FAIL 条目（现象 — 根因 — 规则 — 最小复现 — 测试 — 通过条件）
[↗](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#4-fail-%E6%9D%A1%E7%9B%AE%E7%8E%B0%E8%B1%A1--%E6%A0%B9%E5%9B%A0--%E8%A7%84%E5%88%99--%E6%9C%80%E5%B0%8F%E5%A4%8D%E7%8E%B0--%E6%B5%8B%E8%AF%95--%E9%80%9A%E8%BF%87%E6%9D%A1%E4%BB%B6)
### F1 — CLOSED fresh replay 不验证 exact terminal successor（P0）
### F2 — zero-command ORDER closure 身份落在 soak_runtime 私有域（P1）
### F3 — `transaction_under_terminal_child` 步进域过宽（P1）
### F4 — soak evidence 预锁快照 TOCTOU / partial orphan（P1）
## 5. 非 FAIL 的正面观察（不抵消 F1–F4）
[↗](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#5-%E9%9D%9E-fail-%E7%9A%84%E6%AD%A3%E9%9D%A2%E8%A7%82%E5%AF%9F%E4%B8%8D%E6%8A%B5%E6%B6%88-f1f4)
## 6. 未运行边界（诚实）
[↗](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#6-%E6%9C%AA%E8%BF%90%E8%A1%8C%E8%BE%B9%E7%95%8C%E8%AF%9A%E5%AE%9E)
## 7. 返工最小集（给经理；审查者不改代码）
[↗](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#7-%E8%BF%94%E5%B7%A5%E6%9C%80%E5%B0%8F%E9%9B%86%E7%BB%99%E7%BB%8F%E7%90%86%E5%AE%A1%E6%9F%A5%E8%80%85%E4%B8%8D%E6%94%B9%E4%BB%A3%E7%A0%81)
## 8. 交接（初验历史；保留）
[↗](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#8-%E4%BA%A4%E6%8E%A5%E5%88%9D%E9%AA%8C%E5%8E%86%E5%8F%B2%E4%BF%9D%E7%95%99)
## 9. R1 复验（2026-08-26）
[↗](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#9-r1-%E5%A4%8D%E9%AA%8C2026-08-26)
### 9.0 范围与方法
### 9.1 裁决
### 9.2 F1–F4 复核矩阵
### 9.3 R1 新增对抗反例（实现者未用）
#### AE-R1-1 — legacy / 升级后 formal CLOSED 列 NULL
#### AE-R1-2 — row identity domain 混合
#### AE-R1-3 — 锁内 receipt 替换（F4）
#### AE-R1-4 — wrong-step 只读闸升级为写（F3）→ **FAIL**
#### AE-R1-5 — F2 成功身份 vs formal empty MISSING 闸（→ **FAIL**）
### 9.4 FAIL 条目（六要素）
#### R1-F2 — zero-command SSOT 与 formal empty MISSING 闸/测例未闭合（P0）
#### R1-F3 — inspect 只读闸可升级为持久写（P1）
### 9.5 已闭合的原 F1/F4（不抵消 R1-F2/F3）
### 9.6 未运行边界
### 9.7 返工最小集（审查者不改代码）
### 9.8 交接（R1 历史；保留）
## 10. R2 复验（2026-08-26）
[↗](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#10-r2-%E5%A4%8D%E9%AA%8C2026-08-26)
### 10.0 范围与方法
### 10.1 裁决
### 10.2 R1-F2 复核（行号证据）
### 10.3 R1-F3 复核（行号证据）
### 10.4 R2 新增对抗性反例（实现者未用）
#### AE-R2-1 — 私有 `_composition` 逃逸 vs 公开返回面
#### AE-R2-2 — 非零缺 ORDER 与真零的码面分离
### 10.5 诚实 STATIC_ONLY / Gate 边界
### 10.6 残留风险（不阻断本轮产品 PASS）
### 10.7 交接（R2 历史；保留）
## 11. ADOPTION_R2 复验（2026-08-26）
[↗](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#11-adoption_r2-%E5%A4%8D%E9%AA%8C2026-08-26)
### 11.0 范围与方法
### 11.1 裁决
### 11.2 采用者身份 / 角色（ provenance）
### 11.3 最终 SHA 表（审查者独立 `git hash-object`；与 §16.2 对照）
### 11.4 违约证据隔离与 provenance 边界
### 11.5 Scope / residue
### 11.6 诚实未运行 / Gate 边界
### 11.7 交接（ADOPTION_R2 历史；保留）
## 12. VALIDATION1_REWORK 复验（2026-08-26）
[↗](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#12-validation1_rework-%E5%A4%8D%E9%AA%8C2026-08-26)
### 12.0 范围与方法
### 12.1 裁决
### 12.2 VALIDATION1 证据核对
### 12.3 两项 fixture 修复（test-only）
### 12.4 两项 terminal 失败 → formal-clock @ step4
### 12.5 test-owned clock pin 与 public step trace（不绕过 machinery）
### 12.6 same-token / broker exact1 / CLOSING / orphan·tamper
### 12.7 新增对抗反例（本审查；实现者未用）
#### AE-V1-1 — 双时钟：只推进 `now=` 不 pin `_production_utc_now` 仍必败
#### AE-V1-2 — step trace 若替换为 no-op append 不能假绿
### 12.8 Scope / Gate 边界
### 12.9 交接
## 13. RUFF_REWORK 复验（2026-08-26）
[↗](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#13-ruff_rework-%E5%A4%8D%E9%AA%8C2026-08-26)
### 13.1 裁决
### 13.2 VALIDATION2 证据核对（只读磁盘；未重跑工具）
### 13.3 Ruff 失败位点 → 当前字节（精确 diff/行号）
### 13.4 production / 其他路径冻结
### 13.5 Scope / Gate 边界
### 13.6 交接
## 14. TYPE_ANNOTATION 复验（2026-08-26）
[↗](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#14-type_annotation-%E5%A4%8D%E9%AA%8C2026-08-26)
### 14.1 裁决
### 14.2 VALIDATION3 证据核对（只读磁盘；未重跑工具）
### 14.3 本轮 diff（精确行号）
### 14.4 runtime / schema / lock / escape / 禁止项
### 14.5 其他 exact33 冻结与 SHA 台账残差
### 14.6 Scope / Gate 边界
### 14.7 交接
## 15. EVIDENCE_REVIEW（2026-08-26）
[↗](M4_B1B2_TerminalSessionClosure%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md#15-evidence_review2026-08-26)
### 15.1 裁决
### 15.2 VALIDATION1–4 关键 SHA / exit（磁盘核对）
### 15.3 scope-close1–5
### 15.4 actual19 ⊆ exact33 / cached0 / diff / residue（当前 WT）
### 15.5 F-chain 与审查史保全
### 15.6 Gate / 过度声明核对
### 15.7 本审查边界
### 15.8 交接
