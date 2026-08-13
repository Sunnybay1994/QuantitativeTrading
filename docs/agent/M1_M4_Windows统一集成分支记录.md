# M1–M4 Windows 统一集成分支记录

日期：2026-08-13

## 1. 集成范围

- 分支：`codex/m1-m4-windows-integration`
- 工作树：`artifacts/dev_worktrees/m1-m4-windows-integration`
- 基线：`main@2afd57c`
- M1 合流：`a5dc734`，来源 `codex/m1-hkex-02983`
- M4 合流：`7f76793`，来源 `codex/m3-g8ab-prereq`
- M3 合流：`e62d2ec`，来源 `codex/m3-g4-formal`
- M2 研究快线合流：`b6d652d`，来源 `codex/m2-strategy-fastlane`
- M3 G9G 增量合流：`55b3ac7`，来源 `codex/m3-g4-formal`

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

M2 合流暴露两个只在组合分支可见的问题，并已形成最小修正：

- `quant.portfolio` 的订单规划导出与 `quant.backtest.event_simulator` 形成循环导入；集成层将 replay 三项
  包级导出改为按属性惰性加载，保留原 public 名称，研究选择入口不再加载 M4/event replay 重链；
- 候选来源配置绑定 Git LF 字节，但 Windows checkout 为 CRLF；两个身份敏感 TOML 现由
  `.gitattributes` 固定 `eol=lf`，前向观察 verifier 同时按 UTF-8 canonical LF 计算来源 SHA，避免同一提交
  因平台换行自拒绝，内容变化仍会改变 SHA。

## 3. 正常开发检查

- M1 backfill/history/corporate-action/HKEX daily/total-return/scheduler：`302 passed, 6 skipped`。
- 集成后的 store/risk/service：`209 passed, 5 skipped`。
- 加入 M4 formal broker store 邻接：`300 passed, 5 skipped`；Ruff、mypy、冷导入通过。
- M3 非重型 G8/G9 组：`53 passed`；formal 首节点与缓存末节点分别通过；关键源文件 Ruff、mypy、冷导入通过。
- M3 合并长组超过 10 分钟承载窗口，子进程自然结束后摘要不可回收，因此不计作通过证据，也未机械重跑。
- M2 合流及 M3/M4 公共导出邻接：`82 passed`；Ruff、mypy、惰性导出冷启动通过。
- M3 G9G 增量合流的 acceptance contracts/decision/readiness：`23 passed`；40 个相关源文件 mypy、Ruff、
  M2/M3 同进程冷导入通过。完整 G9A–G9G `68 passed, 1 skipped` 的来源分支证据仍由 G9G 报告承载，
  合流时未在 honest 300 后台任务旁机械重复长组。

这些结果是合流过程中的正常开发反馈，不是独立初验或 Windows/Linux Gate 声明。

## 4. 尚未完成

- M1：A 股/ETF 主闭环已完成；五日自然调度已取得 4/5，等待 2026-08-14 自然运行后终审。HK licensed
  provenance 与 `01065.HK` 权威无交易事实仍等待外部合规材料。
- M2：投研框架 MVP 与研究快线已完成并合入；策略开发已拆到独立 `codex/m2-strategy-research`
  worktree，当前仍无 `PAPER_CANDIDATE`。
- M3：G9A–G9G Windows fake 工程闭包已完成。honest 300 的 R1/R2 首发业务 CLI 均成功；R1 误计持久
  advisory lock，R2 又把 Windows 反斜杠相对路径误当成非 canonical 产物。两项都只属于验收 helper，未改
  StageRunner、receipt 或经济计算。R3 已把相对路径统一为 POSIX `/`，快速回归、Ruff 和 diff-check 通过，
  固定 revision `706ab2c`；2026-08-14 00:27:43 起按 `UA-M3-001` 的资源上限重新执行完整首发与
  completed resume。终态前不能关闭 G8/G9 honest Gate，也不能拼接 R1/R2 局部成功。
- M4：formal gateway dispatch 语义等待 `UA-M4-003`；service/runner/28 日 soak 尚未完成。
- Linux/ext4 当前按用户指示不纳入本阶段实施或完成判定。

因此本记录只证明 Windows 开发分支已形成统一可继续演进的集成基线，不宣称 M1、M3、M4 或总项目完成。
