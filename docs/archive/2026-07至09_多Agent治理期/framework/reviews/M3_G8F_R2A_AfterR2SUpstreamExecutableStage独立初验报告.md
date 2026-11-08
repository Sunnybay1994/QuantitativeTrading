<!-- Split index for `M3_G8F_R2A_AfterR2SUpstreamExecutableStage独立初验报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md)

# M3-G8F-R2A After-R2S Upstream Executable Stage 独立初验报告
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#m3-g8f-r2a-after-r2s-upstream-executable-stage-%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A)
## 0. 审查边界
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#0-%E5%AE%A1%E6%9F%A5%E8%BE%B9%E7%95%8C)
## 1. 中央合同逐项静态核
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#1-%E4%B8%AD%E5%A4%AE%E5%90%88%E5%90%8C%E9%80%90%E9%A1%B9%E9%9D%99%E6%80%81%E6%A0%B8)
## 2. 发现分级
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#2-%E5%8F%91%E7%8E%B0%E5%88%86%E7%BA%A7)
### [P1] 多 horizon prior 允许重复 horizon 静默覆盖 — `successor_upstream_stage.py:459-471,700-730,777-823`
### [P1] 进程内 `_WAVE_REGISTRY` 仅凭键存在强制 `effective_resume=True` — `successor_upstream_stage.py:1616-1621,1650-1664`
### [P1] 任务书强制的 toolchain symlink/reparse 反例未落地 — 测试面
### [P2] 失败 wave 部分物理 publish 的定向对抗不足 — 测试面
### 无其他 P0
## 3. 实现者未使用的对抗反例（新增）
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#3-%E5%AE%9E%E7%8E%B0%E8%80%85%E6%9C%AA%E4%BD%BF%E7%94%A8%E7%9A%84%E5%AF%B9%E6%8A%97%E5%8F%8D%E4%BE%8B%E6%96%B0%E5%A2%9E)
### 反例 R1 — 进程内 registry poison × caller `resume=False` × 盘面旧产物
### 反例 R2 — sorted prior 跨 stage 表面合法、重复 horizon 歧义
### 反例 R3 — toolchain python/dump symlink（或 Windows reparse）
## 4. 失败项（现象—根因—规则—最小复现—测试—通过条件）
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#4-%E5%A4%B1%E8%B4%A5%E9%A1%B9%E7%8E%B0%E8%B1%A1%E6%A0%B9%E5%9B%A0%E8%A7%84%E5%88%99%E6%9C%80%E5%B0%8F%E5%A4%8D%E7%8E%B0%E6%B5%8B%E8%AF%95%E9%80%9A%E8%BF%87%E6%9D%A1%E4%BB%B6)
### F1 — 重复 horizon prior 未 fail closed
### F2 — registry poison 可迫使跨进程旧产物 resume
### F3 — symlink/reparse toolchain 强制反例缺失
## 5. 快速回扫（未构成独立 FAIL 的通过项）
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#5-%E5%BF%AB%E9%80%9F%E5%9B%9E%E6%89%AB%E6%9C%AA%E6%9E%84%E6%88%90%E7%8B%AC%E7%AB%8B-fail-%E7%9A%84%E9%80%9A%E8%BF%87%E9%A1%B9)
## 6. 未运行边界（强制）
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#6-%E6%9C%AA%E8%BF%90%E8%A1%8C%E8%BE%B9%E7%95%8C%E5%BC%BA%E5%88%B6)
## 7. 总判
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#7-%E6%80%BB%E5%88%A4)
## R1 复验（2026-08-26）— 另一全新独立 reviewer
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#r1-%E5%A4%8D%E9%AA%8C2026-08-26-%E5%8F%A6%E4%B8%80%E5%85%A8%E6%96%B0%E7%8B%AC%E7%AB%8B-reviewer)
### R1.0 审查边界
### R1.1 F1–F3 闭合核（现行证据）
### R1.2 实现者未使用的新对抗反例（复验新增）
#### 反例 R4 — 伪造 sealed marker（无 canonical publish）
#### 反例 R5 — 同进程跨 request registry 键碰撞
#### 反例 R6 — 多 node 部分 publish 后 registry / resume
### R1.3 未运行边界（强制）
### R1.4 R1 总判
## VALIDATION1 fixture 复验（2026-08-26）— 同一独立 reviewer
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#validation1-fixture-%E5%A4%8D%E9%AA%8C2026-08-26-%E5%90%8C%E4%B8%80%E7%8B%AC%E7%AB%8B-reviewer)
### F.0 审查边界
### F.1 逐项静态核
### F.2 未运行 / 非宣称
### F.3 总判
## VALIDATION2 Ruff-only 复验（2026-08-26）— 同一独立 reviewer
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#validation2-ruff-only-%E5%A4%8D%E9%AA%8C2026-08-26-%E5%90%8C%E4%B8%80%E7%8B%AC%E7%AB%8B-reviewer)
### R.0 边界
### R.1 语义 diff 核（仅 import/binding 收敛）
### R.2 未运行 / Gate 边界
### R.3 总判
## VALIDATION3 type-contract 复验（2026-08-26）— 同一独立 reviewer
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#validation3-type-contract-%E5%A4%8D%E9%AA%8C2026-08-26-%E5%90%8C%E4%B8%80%E7%8B%AC%E7%AB%8B-reviewer)
### T.0 边界
### T.1 三项真实 API（生产 SSOT / 现行行号）
### T.2 bundle / Literal / Optional / summary / 禁令
### T.3 §12.4 测试真实调用边界 — **FAIL**
#### 失败项 F-TC1（六要素）
### T.4 新对抗反例 R7 — 源码子串伪装 × 无正路径实调
### T.5 未运行 / Gate 边界
### T.6 总判
## §13 真实调用返工复验（2026-08-26）— 同一独立 reviewer
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#13-%E7%9C%9F%E5%AE%9E%E8%B0%83%E7%94%A8%E8%BF%94%E5%B7%A5%E5%A4%8D%E9%AA%8C2026-08-26-%E5%90%8C%E4%B8%80%E7%8B%AC%E7%AB%8B-reviewer)
### C.0 边界与 production 字节冻结
### C.1 正向 unmocked 实调
### C.2 负例 fail-closed（与正路径分离）
### C.3 残余（不阻断）
### C.4 未运行 / Gate
### C.5 总判
## VALIDATION4 fixture 父目录复验（2026-08-26）— 同一独立 reviewer
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#validation4-fixture-%E7%88%B6%E7%9B%AE%E5%BD%95%E5%A4%8D%E9%AA%8C2026-08-26-%E5%90%8C%E4%B8%80%E7%8B%AC%E7%AB%8B-reviewer)
### P.0 写集与 production 字节
### P.1 fixture 父目录修正
### P.2 真实 API 正/负合同仍可达
### P.3 证据 / 非宣称
### P.4 总判
## VALIDATION5 monkeypatch authority 隔离复验（2026-08-26）— 同一独立 reviewer
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#validation5-monkeypatch-authority-%E9%9A%94%E7%A6%BB%E5%A4%8D%E9%AA%8C2026-08-26-%E5%90%8C%E4%B8%80%E7%8B%AC%E7%AB%8B-reviewer)
### M.0 写集与 production 字节
### M.1 双独立 `MonkeyPatch.context()` 生命周期
### M.2 正/负合同未弱化；未改回 mock/源码替代
### M.3 verifier / 最终结果
### M.4 证据 / 非宣称
### M.5 总判
## VALIDATION7 只读节点协议复验（2026-08-26）— 同一独立 reviewer
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#validation7-%E5%8F%AA%E8%AF%BB%E8%8A%82%E7%82%B9%E5%8D%8F%E8%AE%AE%E5%A4%8D%E9%AA%8C2026-08-26-%E5%90%8C%E4%B8%80%E7%8B%AC%E7%AB%8B-reviewer)
### N.0 写集范围
### N.1 `_ReceiptNodeView` 只读 `@property`
### N.2 runtime / schema / identity 零变化
### N.3 VALIDATION7 证据与边界调和
### N.4 总判
## EVIDENCE_REVIEW（2026-08-26）— 同一独立 reviewer · 任务书 §17
[↗](M3_G8F_R2A_AfterR2SUpstreamExecutableStage%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#evidence_review2026-08-26-%E5%90%8C%E4%B8%80%E7%8B%AC%E7%AB%8B-reviewer--%E4%BB%BB%E5%8A%A1%E4%B9%A6-17)
### E.0 审查边界
### E.1 VALIDATION7 ⊕ VALIDATION8 组合闭合
### E.2 actual8 ⊆ exact9 / cached0 / residue
### E.3 VALIDATION1–8 历史失败 / UNRUN（不改写）
### E.4 非宣称 / 终态上限
### E.5 总判
