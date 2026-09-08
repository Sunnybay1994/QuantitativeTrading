# M3-G8F-R2G Formal G1 Release Input 任务书

日期：2026-08-28<br>
状态：`FROZEN / STATIC_ONLY / CENTRAL_READ_ONLY_GRANT_REQUIRED`

## 1. 身份与目标

- task id：`M3-G8F-R2G-FORMAL-G1-RELEASE-INPUT`
- exact base / HEAD：`10af1582845fbffd8356fa987d0c5ce2d6783ed4`
- branch：`codex/m3-g8f-r2g-formal-g1-release-input`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2g-formal-g1-release-input`
- 目标：冻结public G1 run/verify合同、唯一非LOCKED候选release路径及future fresh验证/必要重建合同；本包不读取真实release。

tracked文档证明2026-08-09曾对一个Windows正式release做磁盘fresh验真，但release bytes/manifest不在Git，且当前状态未知。
因此该历史报告只能提供exact候选，不能直接关闭A15。中央批准单一路径只读fresh检查前保持`MISSING`。

## 2. exact3 与角色

1. `docs/framework/tasks/M3_G8F_R2G_FormalG1ReleaseInput任务书.md`（经理唯一写）
2. `docs/framework/deliveries/M3_G8F_R2G_FormalG1ReleaseInput交付报告.md`（后续唯一审计 Worker 写）
3. `docs/framework/reviews/M3_G8F_R2G_FormalG1ReleaseInput独立初验报告.md`（不同 reviewer 写）

当前只批准路径1。中央复核前不得派Worker/reviewer，不得进入`data/clean`或任何runtime/retained root。

## 3. public合同与tracked锚点

| 输入 | Git blob / SHA-256 | 合同 |
|---|---|---|
| `src/quant/data/m3_release.py` | `1e02a243...` / `8ad4b07f3309cd92ef2f93fd1e321a0652065a42b33ac5da384a8fd149c9b463` | `G1Release`、`VerifiedG1Release`、`verify_g1_release(release=...)`唯一fresh verifier |
| `src/quant/research/m3/run_g1.py` | `f17642c7...` / `4cc638ad108199f841aed80d49e398e282ffb1a78cffed0325f509d8f7e54d1e` | public CLI：`--config`、`--project-root`与status/index/history/reference/prepare/publish/run-all |
| `src/quant/research/m3/g1_workflow.py` | `befc8524...` / `60d1f1f1c0d4a04385ecada5e424233eaf81a8ff3a7e47d0b0886bc81a6a5008` | no-clobber workflow与`data/clean/m3_g1/releases`布局 |
| `src/quant/research/m3/successor_bridge.py` | `09d8b3b2...` / `64474646d671164435bddd572a9cbd9d626943d1a7242382d05bd32d8d98ea69` | exact relative path/id、fresh verifier与manifest closure |
| Windows disk report | blob `2f8d4a26...` / `434fbc7d82f5d181031323a8018bdc102c7e2ddf2901df11d160abd99786b387` | 历史证据；不含Git-tracked release bytes |

public fresh检查必须从exact `G1Release(root, release_id, manifest_path, quality_path)`调用`verify_g1_release`，并闭合
manifest、quality及exact artifact set；不得从报告字段、目录名或“最新”推断Verified对象。

## 4. 唯一候选与中央只读授权请求

历史报告给出的唯一非LOCKED候选：

- release id：`08eb9b31ab4d8c8473c0a7bb612df83009a68b761b8a35816653b2ce07807359`
- project-relative path：`data/clean/m3_g1/releases/08eb9b31ab4d8c8473c0a7bb612df83009a68b761b8a35816653b2ce07807359`
- historical manifest SHA-256：`d3923fa1143fbc5c4ff352f7b4d0cf5baeb197d2bb161ead34255bd7375f99c4`
- historical quality SHA-256：`00400e218be202aa705b01739873ae65f0eec9174e072f1e93dcb6e7132086b2`
- historical primary candidate key：`f51655b078255760e8925534ac1dac3161a3ec874c88e47e592cb5afe5845036`

后续只读检查必须由中央逐字授权上述单一路径；只允许non-follow检查exact ancestors/root、读取manifest/quality与manifest声明的
exact artifact paths并调用public verifier。禁止列举parent、glob、latest、读取sibling、旧release、ignored config或任何LOCKED retained。
候选缺失、identity/SHA/quality/artifact漂移即`FORMAL_G1_CANDIDATE_INVALID`，不得寻找替代品。

## 5. 若候选不可用：future G1 run冻结框架

若exact候选不存在或fresh verify失败，本包只记录future run合同，不执行：

1. 用户/研究owner提供正式tracked config与数据窗口；中央冻结source snapshot、exact project root、raw/journal/release roots、解释器、资源和network权限。
2. 新run使用public `quant.research.m3.run_g1`，exact config/project-root，先status再按index→history→reference→prepare→publish；不得私调workflow或改root flags。
3. release parent必须预先核验、输出no-clobber；不得扫描或adopt旧release。每阶段持久化stdout/stderr/exit、输入identity和资源状态。
4. 真实网络、source token、rate limit、max attempts、data writer与CPU均须独立授权；本任务书不授予。
5. CLI进入后任一失败保留journal/staging/release/evidence原状并标`G1_RUN_PARTIAL_LOCKED`，不自动清理、继续或重跑。
6. publish成功后仍必须由独立进程从exact release path调用public verifier；只有fresh闭合才能提供A15输入。

## 6. 对抗与失败语义

- 历史报告SHA正确但当前bytes未fresh读取：A15保持MISSING。
- exact candidate缺失时不得扫描parent或采用旧`3c9bda84...`。
- 候选与LOCKED retained有任何路径/identity/hardlink/reparse交集：`SCOPE_STOP`，不读取。
- manifest自述release id、root leaf、quality、artifact set或digest任一不一致：fail closed。
- public verifier需要Python/长I/O：等待中央资源grant；本轮不运行。
- 无可用fresh release时只冻结future run，不把历史PASS写成current READY。

## 7. 静态验收与边界

任务书阶段仅本文件dirty、cached0、`git diff --check` PASS、UTF-8无BOM、LF-only、TW0、single EOF LF。
本包不创建config/release/root/evidence，不运行Python/Qlib/network，不读取LOCKED，不关闭A15、actual successor、retained或M3 Gate。
