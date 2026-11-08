<!-- Split index for `M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI独立初验报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md)

# M3-G8F-R2B Rebuilt Production Successor Bridge / CLI 独立初验报告
[↗](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#m3-g8f-r2b-rebuilt-production-successor-bridge--cli-%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A)
## 0. 审查边界
[↗](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#0-%E5%AE%A1%E6%9F%A5%E8%BE%B9%E7%95%8C)
## 1. 合同逐项静态核对
[↗](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#1-%E5%90%88%E5%90%8C%E9%80%90%E9%A1%B9%E9%9D%99%E6%80%81%E6%A0%B8%E5%AF%B9)
## 2. 发现分级
[↗](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#2-%E5%8F%91%E7%8E%B0%E5%88%86%E7%BA%A7)
### [P1] 任务书 §7.1 强制 symlink/reparse 反例未落地 — 测试面
### [P1] 任务书 §7.3 强制 fold「重复」反例未落地 — 测试面
### [P1] 任务书 §7.4 强制两 fold toolchain spec 漂移反例未落地 — 测试面
### [P2] CLI 未预期异常错误族与 delivery 冻结表冲突 — `run_successor.py:84-86`
### 无 P0
## 3. 实现者未使用的对抗反例（新增）
[↗](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#3-%E5%AE%9E%E7%8E%B0%E8%80%85%E6%9C%AA%E4%BD%BF%E7%94%A8%E7%9A%84%E5%AF%B9%E6%8A%97%E5%8F%8D%E4%BE%8B%E6%96%B0%E5%A2%9E)
### 反例 R1 — request 叶路径 symlink / Windows reparse（canonical path TOCTOU 前置）
### 反例 R2 — dump tool 同 size 内容置换 × 缺二次读 / 缺 mtime（tool bytes TOCTOU）
### 反例 R3 — 双槽同位 impostor（callable identity 替换）
### 反例 R4 — 两 fold `dump_script_sha256` / size 漂移（config/release/toolchain drift）
### 反例 R5 — `resume=true` + request identity 漂移拒旧 terminal
### 反例 R6 — 失败前零副作用：controlled 已存在但 identity 错配仍零写入
### 反例 R7 — CLI stderr 脱敏 × 裸异常族
### 反例 R8 — factory/entry exact1 在**未**替换 `_CANONICAL_*` 时计数
## 4. 失败项（现象—根因—规则—最小复现—新增测试—通过条件）
[↗](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#4-%E5%A4%B1%E8%B4%A5%E9%A1%B9%E7%8E%B0%E8%B1%A1%E6%A0%B9%E5%9B%A0%E8%A7%84%E5%88%99%E6%9C%80%E5%B0%8F%E5%A4%8D%E7%8E%B0%E6%96%B0%E5%A2%9E%E6%B5%8B%E8%AF%95%E9%80%9A%E8%BF%87%E6%9D%A1%E4%BB%B6)
### F1 — §7.1 symlink/reparse 强制反例缺失
### F2 — §7.3 fold 重复强制反例缺失
### F3 — §7.4 两 fold spec 漂移强制反例缺失
### F4 — CLI 未预期异常映射违反冻结表
## 5. 已通过项（压缩）
[↗](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#5-%E5%B7%B2%E9%80%9A%E8%BF%87%E9%A1%B9%E5%8E%8B%E7%BC%A9)
## 6. 未运行与未关闭边界（强制）
[↗](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#6-%E6%9C%AA%E8%BF%90%E8%A1%8C%E4%B8%8E%E6%9C%AA%E5%85%B3%E9%97%AD%E8%BE%B9%E7%95%8C%E5%BC%BA%E5%88%B6)
## 7. 结论（首轮）
[↗](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#7-%E7%BB%93%E8%AE%BA%E9%A6%96%E8%BD%AE)
## 8. STATIC_REWORK1 复验（对照任务书 §9 / 初验 F1–F8）
[↗](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#8-static_rework1-%E5%A4%8D%E9%AA%8C%E5%AF%B9%E7%85%A7%E4%BB%BB%E5%8A%A1%E4%B9%A6-9--%E5%88%9D%E9%AA%8C-f1f8)
### 8.1 F1–F8 逐项静态结论
### 8.2 发现分级（复验）
### [P2] 交付冻结合同 §3.4 仍描述已删除的 `_CANONICAL_*` 别名门禁 — delivery §3.4 vs `successor_bridge.py`
### 无 P0 / 无残留 P1
### 8.3 实现者本轮仍未使用的对抗反例（新增）
### 反例 R9 — 成员路径 reparse 注入（symlink skip 主机）
### 反例 R10 — 改写 authority 闭包 cell 后双侧 impostor
### 反例 R11 — config `load_m3_config` 窗口同 size 置换
### 反例 R12 — 裸异常来自投影/编码路径（非 bridge）
### 8.4 失败项（复验）
### F8′ — 冻结合同 §3.4 与 closure 真身实现不一致
### 8.5 已通过项（REWORK1 压缩）
### 8.6 未运行与未关闭边界（强制，复验后仍成立）
### 8.7 复验结论（REWORK1）
## 9. STATIC_REWORK2 复验（对照任务书 §10 / F8′）
[↗](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#9-static_rework2-%E5%A4%8D%E9%AA%8C%E5%AF%B9%E7%85%A7%E4%BB%BB%E5%8A%A1%E4%B9%A6-10--f8)
### 9.1 F8′ 核对清单
### 9.2 发现分级（REWORK2）
### 9.3 未运行与未关闭边界（强制）
### 9.4 复验结论（REWORK2）
## 10. STATIC_REWORK3 复验（对照任务书 §11 / F9–F10）
[↗](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#10-static_rework3-%E5%A4%8D%E9%AA%8C%E5%AF%B9%E7%85%A7%E4%BB%BB%E5%8A%A1%E4%B9%A6-11--f9f10)
### 10.1 范围与冻结
### 10.2 F9 / F10 逐项
### 10.3 发现分级
### [P1] F9 raw 非有限 token 无法稳定归一为 `SUCCESSOR_BRIDGE_INPUT_INVALID` — `successor_bridge.py:281-292` × `test_rejects_wrong_dump_target_and_timeout_types`
### 无 P0；F10 未见 P1/P2
### 10.4 实现者未使用的对抗反例（新增）
### 反例 R13 — raw `-Infinity` × 裸 `ValueError` 经 CLI 错族
### 10.5 失败项
### F9′ — raw 非有限 carrier 未闭合稳定 INPUT 码
### 10.6 未运行与未关闭边界（强制）
### 10.7 复验结论（REWORK3）
## 11. STATIC_REWORK4 复验（对照任务书 §12 / F9′）
[↗](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#11-static_rework4-%E5%A4%8D%E9%AA%8C%E5%AF%B9%E7%85%A7%E4%BB%BB%E5%8A%A1%E4%B9%A6-12--f9)
### 11.1 F9′ 合同核对
### 11.2 发现分级
### 11.3 对抗反例（本轮新增，非阻断）
### 反例 R14 — CLI 对 `NaN` / `-Infinity` 对称 exit 2
### 11.4 未运行与未关闭边界（强制）
### 11.5 复验结论（REWORK4）
## 12. STATIC_REWORK5 复验（对照任务书 §13 / mypy 返回注解）
[↗](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#12-static_rework5-%E5%A4%8D%E9%AA%8C%E5%AF%B9%E7%85%A7%E4%BB%BB%E5%8A%A1%E4%B9%A6-13--mypy-%E8%BF%94%E5%9B%9E%E6%B3%A8%E8%A7%A3)
### 12.1 逆向 diff 核对（相对 REWORK4 已审形态）
### 12.2 发现分级
### 12.3 未运行与未关闭边界（强制）
### 12.4 复验结论（REWORK5）
## 13. EVIDENCE_REVIEW（组合 Windows 工程证据）
[↗](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#13-evidence_review%E7%BB%84%E5%90%88-windows-%E5%B7%A5%E7%A8%8B%E8%AF%81%E6%8D%AE)
### 13.1 组合证据表（文档 ↔ 磁盘）
### 13.2 强制口径核对
### 13.3 记录 SHA（本复核实测）
### 13.4 发现分级
### 13.5 结论
## 14. DOC_REVIEW（文档规范化只读核对）
[↗](M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#14-doc_review%E6%96%87%E6%A1%A3%E8%A7%84%E8%8C%83%E5%8C%96%E5%8F%AA%E8%AF%BB%E6%A0%B8%E5%AF%B9)
### 14.1 格式门禁
### 14.2 证据语义相对 `EVIDENCE_REVIEW_PASS`
### 14.3 发现
### 14.4 结论
