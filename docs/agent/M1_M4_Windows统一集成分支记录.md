# M1–M4 Windows 统一集成分支记录

日期：2026-08-13

## 1. 集成范围

- 分支：`codex/m1-m4-windows-integration`
- 工作树：`artifacts/dev_worktrees/m1-m4-windows-integration`
- 基线：`main@2afd57c`
- M1 合流：`a5dc734`，来源 `codex/m1-hkex-02983`
- M4 合流：`7f76793`，来源 `codex/m3-g8ab-prereq`
- M3 合流：`e62d2ec`，来源 `codex/m3-g4-formal`
- M2 分支没有超出 `main` 的待合流提交；M2 工程闭环已由现有代码和路线图承载。

三个来源分支均已成为当前集成分支祖先。未 push、未创建 PR。

## 2. 关键冲突与处理

M1 typed formal risk counter 与历史 M4 service 都曾使用 SQLite schema v3 的
`daily_risk_counters` 表名，但列结构和语义不同。集成时保留 M4 v3–v6 迁移顺序，并新增 v7 统一迁移：

- 旧 scoped v3 表重命名为 `scoped_daily_risk_counters`，再创建 typed `daily_risk_counters`；
- 已是 typed v3 时保留原表，并补建 scoped 表；
- service/recovery 只调用显式 `*_scoped_daily_risk_counters` API；
- formal typed API 保持按 session date 的既有签名；
- 两种历史 v3 方向均有迁移回归。

M3 合流后发现工作树创建时 `.gitattributes` 尚未生效，Qlib 官方 `dump_bin.py` 被物理展开为 CRLF，
与冻结 manifest 字节不一致。文件已恢复为索引中的 LF 原始字节；没有形成内容提交，也没有修改冻结 SHA。

M4 B2E 的 formal policy descriptor 只能由 exact policy+binding builder 签发。当前实现以进程内弱引用登记
验证来源，拒绝 development descriptor 改 classification 后重签 digest，也拒绝同值 clone。

## 3. 正常开发检查

- M1 backfill/history/corporate-action/HKEX daily/total-return/scheduler：`302 passed, 6 skipped`。
- 集成后的 store/risk/service：`209 passed, 5 skipped`。
- 加入 M4 formal broker store 邻接：`300 passed, 5 skipped`；Ruff、mypy、冷导入通过。
- M3 非重型 G8/G9 组：`53 passed`；formal 首节点与缓存末节点分别通过；关键源文件 Ruff、mypy、冷导入通过。
- M3 合并长组超过 10 分钟承载窗口，子进程自然结束后摘要不可回收，因此不计作通过证据，也未机械重跑。

这些结果是合流过程中的正常开发反馈，不是独立初验或 Windows/Linux Gate 声明。

## 4. 尚未完成

- M1：HK licensed provenance、`01065.HK` 权威无交易事实以及自然调度窗口仍开放。
- M3：honest public CLI 长运行等待 `UA-M3-001`；G9B 输入闭包等待 `UA-M3-002`；G9C–G9G 未完成。
- M4：formal gateway dispatch 语义等待 `UA-M4-003`；service/runner/28 日 soak 尚未完成。
- Linux/ext4 当前按用户指示不纳入本阶段实施或完成判定。

因此本记录只证明 Windows 开发分支已形成统一可继续演进的集成基线，不宣称 M1、M3、M4 或总项目完成。
