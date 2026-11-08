<!-- Split index for `M3_G8F_R2S_FormalSummaryStagePublicationCompatibility独立初验报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md)

# M3-G8F-R2S Formal Summary Stage Publication Compatibility 独立初验报告
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#m3-g8f-r2s-formal-summary-stage-publication-compatibility-%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A)
## 0. 审查边界
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#0-%E5%AE%A1%E6%9F%A5%E8%BE%B9%E7%95%8C)
## 1. 合同逐项静态核对
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#1-%E5%90%88%E5%90%8C%E9%80%90%E9%A1%B9%E9%9D%99%E6%80%81%E6%A0%B8%E5%AF%B9)
## 2. 发现分级
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#2-%E5%8F%91%E7%8E%B0%E5%88%86%E7%BA%A7)
### [P1] temp leaf 用 `startswith(node_id)` 无法闭合 dotted sibling node — `src/quant/research/m3/evaluate.py`（`_require_stage_temp_output_root`）
### [P1] 任务书强制的 symlink/reparse 反例缺失 — 测试面
### 无其他 P0
## 3. 实现者未使用的对抗反例（新增）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#3-%E5%AE%9E%E7%8E%B0%E8%80%85%E6%9C%AA%E4%BD%BF%E7%94%A8%E7%9A%84%E5%AF%B9%E6%8A%97%E5%8F%8D%E4%BE%8B%E6%96%B0%E5%A2%9E)
### 反例 R1（temp node_id 前缀吞噬；实现者未覆盖）
### 反例 R2（final→temp junction / reparse TOCTOU；实现者未覆盖）
## 4. 失败项（现象—根因—规则—最小复现—通过条件）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#4-%E5%A4%B1%E8%B4%A5%E9%A1%B9%E7%8E%B0%E8%B1%A1%E6%A0%B9%E5%9B%A0%E8%A7%84%E5%88%99%E6%9C%80%E5%B0%8F%E5%A4%8D%E7%8E%B0%E9%80%9A%E8%BF%87%E6%9D%A1%E4%BB%B6)
### F1 — temp `node_id` 前缀闭合不严
### F2 — symlink/reparse / TOCTOU 强制反例缺失
## 5. 未运行边界（强制）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#5-%E6%9C%AA%E8%BF%90%E8%A1%8C%E8%BE%B9%E7%95%8C%E5%BC%BA%E5%88%B6)
## 6. 总判
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#6-%E6%80%BB%E5%88%A4)
## 7. STATIC_REWORK4 复验（任务书 §13 · 2026-08-26）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#7-static_rework4-%E5%A4%8D%E9%AA%8C%E4%BB%BB%E5%8A%A1%E4%B9%A6-13--2026-08-26)
### 7.0 复验边界
### 7.1 首轮 FAIL 闭合核对
### 7.2 本轮发现
### [P1] dispatcher 先 `resolve` 再检查，削弱 final symlink/junction 拒绝 — `summary_stage.py`（`_make_summary_stage_closure_dispatcher`）
### 7.3 实现者未使用的新对抗反例（R3）
### 7.4 失败项
### 7.5 未运行边界
### 7.6 复验总判
## 8. STATIC_REWORK5 复验（任务书 §14 · R3 P1 · 2026-08-26）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#8-static_rework5-%E5%A4%8D%E9%AA%8C%E4%BB%BB%E5%8A%A1%E4%B9%A6-14--r3-p1--2026-08-26)
### 8.0 复验边界
### 8.1 §14 / R3 闭合核对
### 8.2 本轮发现
### 8.3 新增静态对抗（R4，实现者未用）
### 8.4 未运行边界
### 8.5 复验总判
## 9. STATIC_REWORK6 / F4 复验（任务书 §15 · VALIDATION2 · 2026-08-26）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#9-static_rework6--f4-%E5%A4%8D%E9%AA%8C%E4%BB%BB%E5%8A%A1%E4%B9%A6-15--validation2--2026-08-26)
### 9.0 复验边界
### 9.1 F4 范围与 production 冻结
### 9.2 分层字段归属
### 9.3 本轮发现
### 9.4 新增静态对抗（R5，实现者未用）
### 9.5 未运行边界
### 9.6 复验总判
## 10. STATIC_REWORK7 / F5 复验（任务书 §16 · VALIDATION3 · 2026-08-26）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#10-static_rework7--f5-%E5%A4%8D%E9%AA%8C%E4%BB%BB%E5%8A%A1%E4%B9%A6-16--validation3--2026-08-26)
### 10.0 复验边界
### 10.1 本轮冻结与范围
### 10.2 §16 合同逐项
### 10.3 本轮发现
### 10.4 新增静态对抗（R6，实现者未用）
### 10.5 未运行边界
### 10.6 复验总判
## 11. STATIC_REWORK9 复验（任务书 §18 · F6 STOP 后 · 2026-08-26）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#11-static_rework9-%E5%A4%8D%E9%AA%8C%E4%BB%BB%E5%8A%A1%E4%B9%A6-18--f6-stop-%E5%90%8E--2026-08-26)
### 11.0 复验边界与历史 STOP
### 11.1 本轮冻结
### 11.2 §18 公开链与 receipt 闭包
### 11.3 本轮发现
### 11.4 新增静态对抗（R7，实现者未用）
### 11.5 未运行边界
### 11.6 复验总判
## 12. STATIC_REWORK10 复验（任务书 §19 · VALIDATION5 · 2026-08-26）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#12-static_rework10-%E5%A4%8D%E9%AA%8C%E4%BB%BB%E5%8A%A1%E4%B9%A6-19--validation5--2026-08-26)
### 12.0 复验边界与 VALIDATION5
### 12.1 本轮冻结
### 12.2 §19 作用域隔离核对
### 12.3 本轮发现
### 12.4 新增静态对抗（R8，实现者未用）
### 12.5 未运行边界
### 12.6 复验总判
## 13. STATIC_REWORK11 复验（任务书 §20 · VALIDATION6 · 2026-08-26）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#13-static_rework11-%E5%A4%8D%E9%AA%8C%E4%BB%BB%E5%8A%A1%E4%B9%A6-20--validation6--2026-08-26)
### 13.0 复验边界与 VALIDATION6
### 13.1 本轮冻结
### 13.2 §20 authority 分域核对
### 13.3 本轮发现
### 13.4 新增静态对抗（R9，实现者未用）
### 13.5 未运行边界
### 13.6 复验总判
## 14. STATIC_REWORK12 复验（任务书 §21 · VALIDATION7 · 2026-08-26）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#14-static_rework12-%E5%A4%8D%E9%AA%8C%E4%BB%BB%E5%8A%A1%E4%B9%A6-21--validation7--2026-08-26)
### 14.0 复验边界与 VALIDATION7
### 14.1 本轮冻结
### 14.2 §21 两项 test-only 闭合
### 14.3 本轮发现
### 14.4 新增静态对抗（R10，实现者未用）
### 14.5 未运行边界
### 14.6 复验总判
## 15. 组合证据终核（EVIDENCE_REVIEW · VALIDATION8 · 2026-08-26）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#15-%E7%BB%84%E5%90%88%E8%AF%81%E6%8D%AE%E7%BB%88%E6%A0%B8evidence_review--validation8--2026-08-26)
### 15.1 VALIDATION8 原生阶段
### 15.2 exact8 / temp·cache / carrier-self 0xF00
### 15.3 历史 VALIDATION1–7 抽查（未改写）
### 15.4 状态与未闭合边界
### 15.5 本轮未运行 / 未改
### 15.6 行尾与自证明
### 15.7 证据审查总判
## 16. EOF_DOC_REVIEW（任务/交付末尾 LF 规范化 · 2026-08-26）
[↗](M3_G8F_R2S_FormalSummaryStagePublicationCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#16-eof_doc_review%E4%BB%BB%E5%8A%A1%E4%BA%A4%E4%BB%98%E6%9C%AB%E5%B0%BE-lf-%E8%A7%84%E8%8C%83%E5%8C%96--2026-08-26)
### 16.1 实现者声明核对
### 16.2 正文语义 / VALIDATION8 / 边界
### 16.3 本报告动作
### 16.4 EOF 总判
