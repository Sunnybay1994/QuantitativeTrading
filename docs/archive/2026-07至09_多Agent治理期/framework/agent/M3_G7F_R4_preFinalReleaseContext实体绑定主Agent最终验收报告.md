# M3 G7F R4：pre-final Release/Context 实体绑定主 Agent 最终验收报告

日期：2026-08-10  
结论：**工程主验 PASS；仅解锁 G8 同步返工，不代表 Linux/ext4、G7F 真实全折或 M3 Gate 通过。**

R4 将 exact `VerifiedG1Release` 与构造时 root、manifest、quality、八张正式 market table 的物理实体快照绑定进
`BacktestArtifactFreshVerificationContext`。build、pre-final、final 入口在任何29-output读取/三场景回放/写入前
重验 nested exact 类型、caller release 与 context release 全字段一致、实体 snapshot 未漂移。R3 主验发现的
SimpleNamespace nested 与 public exact G1Release copied-root 同 context 两条逃逸均已关闭；新建另一 context 被准确
限定为新的验证请求，不声明跨请求持久来源证明。平台 inode 未进入 portable manifest/receipt/output。

证据：外部实现和全新外部独立初验在 Windows/WSL 各完成 targeted 1、G7F 12、邻接 128、fixed-order 4，
Ruff/mypy/cold/diff 全绿；独立对抗覆盖 copied-root、manifest/quality/market inode 替换、nested drift、context
release/private snapshot 篡改，`SUMMARY_BAD 0`。主 Agent 再跑 R4 targeted 1 passed（380.92s），Ruff/mypy PASS。

development 四路径与真实 receipt 保持不变；未改 G1/G7A/B/E/P0/G8。下一步必须单独同步 G8 的 context 构造、
21-input helper、pre/final closure 与测试，再走外部实现—全新外部初验—主验闭环。
