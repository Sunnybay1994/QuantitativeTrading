<!-- Split index for `M3_G8F_R2P_OrchestrationWaveCompatibility独立初验报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M3_G8F_R2P_OrchestrationWaveCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M3_G8F_R2P_OrchestrationWaveCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md)

# M3-G8F-R2P Orchestration Wave Compatibility 独立初验报告
[↗](M3_G8F_R2P_OrchestrationWaveCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#m3-g8f-r2p-orchestration-wave-compatibility-%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A)
## 0. 审查边界
[↗](M3_G8F_R2P_OrchestrationWaveCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#0-%E5%AE%A1%E6%9F%A5%E8%BE%B9%E7%95%8C)
## 1. 中央合同逐项敌意核对
[↗](M3_G8F_R2P_OrchestrationWaveCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#1-%E4%B8%AD%E5%A4%AE%E5%90%88%E5%90%8C%E9%80%90%E9%A1%B9%E6%95%8C%E6%84%8F%E6%A0%B8%E5%AF%B9)
## 2. 发现分级
[↗](M3_G8F_R2P_OrchestrationWaveCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#2-%E5%8F%91%E7%8E%B0%E5%88%86%E7%BA%A7)
### [P0] wave cache 仅按 wave 名缓存，跨 request/resume 可复用错误 identity — `src/quant/research/m3/successor_runtime.py`
### [P1] 六 builder legacy bytes/identity「逐字回归」证据不闭合 — 测试面
### 无其他 P0/P1（在「同 adapter ≡ 同 request」前提下）
## 3. 实现者未使用的对抗反例（新增）
[↗](M3_G8F_R2P_OrchestrationWaveCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#3-%E5%AE%9E%E7%8E%B0%E8%80%85%E6%9C%AA%E4%BD%BF%E7%94%A8%E7%9A%84%E5%AF%B9%E6%8A%97%E5%8F%8D%E4%BE%8B%E6%96%B0%E5%A2%9E)
### 反例 W1（wave cache × 跨 request × resume；实现者未覆盖）
### 反例 W2（补充：六 builder legacy 全覆盖；实现者未覆盖）
## 4. 失败项（现象—根因—规则—最小复现—通过条件）
[↗](M3_G8F_R2P_OrchestrationWaveCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#4-%E5%A4%B1%E8%B4%A5%E9%A1%B9%E7%8E%B0%E8%B1%A1%E6%A0%B9%E5%9B%A0%E8%A7%84%E5%88%99%E6%9C%80%E5%B0%8F%E5%A4%8D%E7%8E%B0%E9%80%9A%E8%BF%87%E6%9D%A1%E4%BB%B6)
### F1 — wave cache 跨 request/resume 错误 identity
### F2 — 六 builder legacy 逐字回归证据缺口
## 5. 未运行边界（强制）
[↗](M3_G8F_R2P_OrchestrationWaveCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#5-%E6%9C%AA%E8%BF%90%E8%A1%8C%E8%BE%B9%E7%95%8C%E5%BC%BA%E5%88%B6)
## 6. 总判
[↗](M3_G8F_R2P_OrchestrationWaveCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#6-%E6%80%BB%E5%88%A4)
## 7. 第 2 轮静态复验（返工后 · 2026-08-25）
[↗](M3_G8F_R2P_OrchestrationWaveCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#7-%E7%AC%AC-2-%E8%BD%AE%E9%9D%99%E6%80%81%E5%A4%8D%E9%AA%8C%E8%BF%94%E5%B7%A5%E5%90%8E--2026-08-25)
### 7.1 F1 复验 — wave session 绑定与 cache
### 7.2 F2 复验 — 六 builder legacy omitted ≡ None
### 7.3 快速回扫（非夸大）
### 7.4 实现者未覆盖的对抗反例（本轮新增）
#### 反例 W3（同 project · identity 漂移 · 失败中途消费；实现者未单测）
### 7.5 历史 FAIL 映射
### 7.6 第 2 轮未运行边界
### 7.7 第 2 轮总判
## 8. 第 3 轮静态复验（VALIDATION1-FIXTURE / F3 · 2026-08-25）
[↗](M3_G8F_R2P_OrchestrationWaveCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#8-%E7%AC%AC-3-%E8%BD%AE%E9%9D%99%E6%80%81%E5%A4%8D%E9%AA%8Cvalidation1-fixture--f3--2026-08-25)
### 8.1 本轮写面（F3）
### 8.2 F3 — 两失败测 stub 与断言
### 8.3 W3 动态覆盖核对（中央要求）
### 8.4 第 3 轮未运行边界
### 8.5 第 3 轮总判
## 9. 第 4 轮静态复验（VALIDATION2-F4 · 2026-08-25）
[↗](M3_G8F_R2P_OrchestrationWaveCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#9-%E7%AC%AC-4-%E8%BD%AE%E9%9D%99%E6%80%81%E5%A4%8D%E9%AA%8Cvalidation2-f4--2026-08-25)
### 9.1 写面与证据绑定
### 9.2 失败语义与 bytes/控制流
### 9.3 实现者未使用的对抗检查（本轮新增）
### 9.4 第 4 轮未运行边界
### 9.5 第 4 轮总判
## 10. 第 5 轮静态复验（VALIDATION3-F5 · 2026-08-25）
[↗](M3_G8F_R2P_OrchestrationWaveCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#10-%E7%AC%AC-5-%E8%BD%AE%E9%9D%99%E6%80%81%E5%A4%8D%E9%AA%8Cvalidation3-f5--2026-08-25)
### 10.1 证据与写面
### 10.2 `_WaveReceiptKey` 与集合统一
### 10.3 实现者未使用的对抗检查（本轮新增）
### 10.4 第 5 轮未运行边界
### 10.5 第 5 轮总判
## 11. 组合证据终核（EVIDENCE_REVIEW · 2026-08-25）
[↗](M3_G8F_R2P_OrchestrationWaveCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#11-%E7%BB%84%E5%90%88%E8%AF%81%E6%8D%AE%E7%BB%88%E6%A0%B8evidence_review--2026-08-25)
### 11.1 VALIDATION2 focused `13+15+5+36` PASS
### 11.2 POSTFIX VALIDATION4 全 PASS
### 11.3 exact10 scope
### 11.4 终态边界诚实性
### 11.5 本轮未运行 / 未改
### 11.6 证据审查总判
## 12. DOC_REVIEW（文档规范化 · 2026-08-25）
[↗](M3_G8F_R2P_OrchestrationWaveCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#12-doc_review%E6%96%87%E6%A1%A3%E8%A7%84%E8%8C%83%E5%8C%96--2026-08-25)
### 12.1 规范化动作
### 12.2 三文档静态核对（未漂移）
### 12.3 DOC_REVIEW 总判
