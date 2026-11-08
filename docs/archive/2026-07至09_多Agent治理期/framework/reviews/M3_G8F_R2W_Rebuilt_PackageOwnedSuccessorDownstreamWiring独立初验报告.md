<!-- Split index for `M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring独立初验报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md) · [第 3 卷](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md)

# M3-G8F-R2W Rebuilt Package-Owned Successor Downstream Wiring 独立初验报告
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#m3-g8f-r2w-rebuilt-package-owned-successor-downstream-wiring-%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A)
## 0. 审查边界
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#0-%E5%AE%A1%E6%9F%A5%E8%BE%B9%E7%95%8C)
## 1. 合同逐项静态核对
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#1-%E5%90%88%E5%90%8C%E9%80%90%E9%A1%B9%E9%9D%99%E6%80%81%E6%A0%B8%E5%AF%B9)
## 2. 发现分级
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#2-%E5%8F%91%E7%8E%B0%E5%88%86%E7%BA%A7)
### [P1] summary Gate fresh verifier 跳过 public R2S `summary_verifier` — `successor_downstream_stage.py:264-326`
### [P1] 任务书 §7.2 tracking↔backtest 强制反例未落地 — 测试面
### 无 P0；其余主路径未见可演示的 R2I 回退
## 3. 实现者未使用的对抗反例（新增）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#3-%E5%AE%9E%E7%8E%B0%E8%80%85%E6%9C%AA%E4%BD%BF%E7%94%A8%E7%9A%84%E5%AF%B9%E6%8A%97%E5%8F%8D%E4%BE%8B%E6%96%B0%E5%A2%9E)
### 反例 R1 — readiness 物理 `scope_key` 伪装成 aggregate `gate.identity`（physical-vs-aggregate）
### 反例 R2 — 同 bytes、异 semantic-owner 的跨 stage 别名（same-bytes-different-owner）
## 4. 失败项（现象—根因—规则—最小复现—新增测试—通过条件）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#4-%E5%A4%B1%E8%B4%A5%E9%A1%B9%E7%8E%B0%E8%B1%A1%E6%A0%B9%E5%9B%A0%E8%A7%84%E5%88%99%E6%9C%80%E5%B0%8F%E5%A4%8D%E7%8E%B0%E6%96%B0%E5%A2%9E%E6%B5%8B%E8%AF%95%E9%80%9A%E8%BF%87%E6%9D%A1%E4%BB%B6)
### F1 — summary fresh verifier 跳过 public API
### F2 — §7.2 tracking↔backtest 强制反例缺失
## 5. 已通过项（压缩）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#5-%E5%B7%B2%E9%80%9A%E8%BF%87%E9%A1%B9%E5%8E%8B%E7%BC%A9)
## 6. 未运行与未关闭边界（强制）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#6-%E6%9C%AA%E8%BF%90%E8%A1%8C%E4%B8%8E%E6%9C%AA%E5%85%B3%E9%97%AD%E8%BE%B9%E7%95%8C%E5%BC%BA%E5%88%B6)
## 7. 结论（首轮）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#7-%E7%BB%93%E8%AE%BA%E9%A6%96%E8%BD%AE)
## 8. STATIC_REWORK1 复验（对照 taskbook §10）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#8-static_rework1-%E5%A4%8D%E9%AA%8C%E5%AF%B9%E7%85%A7-taskbook-10)
### 8.1 F1 — Summary 每 horizon fresh rehydrate + exact public stage verifier
### 8.2 F2 — Tracking prior closure 行为拒绝（public tracking/client 前）
### 8.3 F3 — Readiness physical-vs-aggregate；R2I 未回退
### 8.4 发现分级（REWORK1）
### 8.5 未运行与 Gate 边界（强制保留）
### 8.6 REWORK1 结论
## 9. VALIDATION1_F4_REVIEW（对照 taskbook §11）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#9-validation1_f4_review%E5%AF%B9%E7%85%A7-taskbook-11)
### 9.1 VALIDATION1 证据复述（未重跑，与 delivery 一致）
### 9.2 F4 合同逐项静态核对
### 9.3 Production 字节冻结（F4 轮次）
### 9.4 发现分级（F4）
### 9.5 Gate / 验证边界（强制保留）
### 9.6 F4 结论
## 10. VALIDATION2_F5_REVIEW（对照 taskbook §12）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#10-validation2_f5_review%E5%AF%B9%E7%85%A7-taskbook-12)
### 10.1 写范围核对
### 10.2 VALIDATION2 证据复述（未重跑；只读核对 stdout）
### 10.3 F5 合同逐项静态核对
### 10.4 发现分级（F5）
### 10.5 Gate / 验证边界（强制保留）
### 10.6 F5 结论
## 11. VALIDATION3_F6_REVIEW（对照 taskbook §13）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#11-validation3_f6_review%E5%AF%B9%E7%85%A7-taskbook-13)
### 11.1 写范围核对
### 11.2 VALIDATION3 证据复述（未重跑；只读核对日志）
### 11.3 F6 authority 合同逐项静态核对
### 11.4 发现分级（F6）
### 11.5 Gate / 验证边界（强制保留）
### 11.6 F6 结论
## 12. VALIDATION4_F7_REVIEW（对照 taskbook §14）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#12-validation4_f7_review%E5%AF%B9%E7%85%A7-taskbook-14)
### 12.1 写范围核对
### 12.2 VALIDATION4 证据复述（未重跑；只读核对日志）
### 12.3 F7 合同逐项静态核对
### 12.4 发现分级（F7）
### 12.5 Gate / 验证边界（强制保留）
### 12.6 F7 结论
## 13. VALIDATION8_F8_REVIEW（对照 taskbook §15）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#13-validation8_f8_review%E5%AF%B9%E7%85%A7-taskbook-15)
### 13.1 写范围与证据边界
### 13.2 Feature-worker seam（两 unit 节点）— 实现面通过
### 13.3 发现分级
### [P1] 无 §15 依据移除 `verify_target_artifact` 窄 stub — 使 PROJECT-only 正测可预见撞上 legacy root-alias 漂移
### 无 P0；seam 主修复方向正确
### 13.4 失败项六段式（F8）
### 13.5 Gate / 验证边界（强制保留）
### 13.6 F8 结论
## 14. F8_P1_REVIEW（对照 taskbook §16）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#14-f8_p1_review%E5%AF%B9%E7%85%A7-taskbook-16)
### 14.1 写范围与冻结
### 14.2 合同逐项静态核对
### 14.3 发现分级
### 14.4 六段式（本轮闭合记录）
### 14.5 Gate / 验证边界（强制保留）
### 14.6 F8_P1 结论
## 15. VALIDATION9_F10_REVIEW（对照 taskbook §17）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#15-validation9_f10_review%E5%AF%B9%E7%85%A7-taskbook-17)
### 15.1 写范围与证据边界
### 15.2 合同逐项静态核对
### 15.3 发现分级
### 15.4 六段式（本轮闭合记录）
### 15.5 Gate / 验证边界（强制保留）
### 15.6 F10 结论
## 16. VALIDATION10_F11_REVIEW（对照 taskbook §18）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#16-validation10_f11_review%E5%AF%B9%E7%85%A7-taskbook-18)
### 16.1 写范围、指纹与 VALIDATION10 证据边界
### 16.2 合同逐项静态核对
### 16.3 审查者新增对抗性静态反例（实现者未专测）
### 16.4 发现分级
### 16.5 六段式（本轮闭合记录）
### 16.6 Gate / 验证边界（强制保留）
### 16.7 F11 结论
## 17. VALIDATION11_F12_REVIEW（对照 taskbook §19）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#17-validation11_f12_review%E5%AF%B9%E7%85%A7-taskbook-19)
### 17.1 写范围、指纹与 VALIDATION11 证据边界
### 17.2 合同逐项静态核对
### 17.3 审查者新增对抗性静态反例
### 17.4 发现分级
### 17.5 六段式（本轮闭合记录）
### 17.6 Gate / 验证边界（强制保留）
### 17.7 F12 结论
## 18. EVIDENCE_REVIEW（对照 taskbook §20 / delivery §18）
[↗](M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-03.md#18-evidence_review%E5%AF%B9%E7%85%A7-taskbook-20--delivery-18)
### 18.1 证据根存在性与组合口径
### 18.2 精确 SHA 核对（只读重算）
#### VALIDATION10
#### VALIDATION11
#### VALIDATION12
### 18.3 exact12 scope / dirty / residue（对照 V12 scope + 当前只读 git）
### 18.4 越权声明检查
### 18.5 发现分级
### 18.6 EVIDENCE_REVIEW 结论
