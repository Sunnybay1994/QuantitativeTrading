# M3-G8F-R2G Formal G1 Release Input 交付报告

日期：2026-08-28<br>
task id：`M3-G8F-R2G-FORMAL-G1-RELEASE-INPUT`<br>
角色：唯一 Luna 审计 Worker<br>
资源：`TRACKED_ONLY / STATIC_ONLY / CPU NONE`

- exact base / HEAD：`10af1582845fbffd8356fa987d0c5ce2d6783ed4`
- branch：`codex/m3-g8f-r2g-formal-g1-release-input`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2g-formal-g1-release-input`
- 唯一写入：`docs/framework/deliveries/M3_G8F_R2G_FormalG1ReleaseInput交付报告.md`
- 终态：`CENTRAL_READ_ONLY_GRANT_REQUIRED / A15 MISSING`

## 1. 结论

已仅用 exact HEAD 中的 tracked 历史报告、Git 对象和 public source 完成静态审计。历史 Windows 磁盘复验报告的 Git blob、working SHA-256 与任务书一致，其确实记录了一个 exact release id、manifest SHA、quality SHA 和 primary candidate key。

但该报告只是 2026-08-09 的历史证据：本轮没有读取当前 `data/clean` release bytes，没有构造 `G1Release`，也没有调用 `verify_g1_release` fresh 重建 `VerifiedG1Release`。因此历史 PASS 不能升级为当前 A15 输入，结论必须保持：

`CENTRAL_READ_ONLY_GRANT_REQUIRED / A15 MISSING`

后续唯一允许的快进路径是：中央另行授权任务书列明的 exact 单一路径 non-follow 读取与 public fresh verify。候选不存在或任一 identity/bytes/artifact 闭包失败时，必须停在 `FORMAL_G1_CANDIDATE_INVALID`，不得扫描 parent 或寻找替代 release。

## 2. 身份与 tracked 证据

### 2.1 源码与报告锚点

| 路径 | bytes | Git blob | working SHA-256 | 审计结果 |
|---|---:|---|---|---|
| `src/quant/data/m3_release.py` | 107553 | `1e02a243be9a6dbf71eaeec4054dbe7956568f57` | `8ad4b07f3309cd92ef2f93fd1e321a0652065a42b33ac5da384a8fd149c9b463` | 匹配 |
| `src/quant/research/m3/run_g1.py` | 33274 | `f17642c7c9724ebf2aeeb203f21ab1db4e163cbf` | `4cc638ad108199f841aed80d49e398e282ffb1a78cffed0325f509d8f7e54d1e` | 匹配 |
| `src/quant/research/m3/g1_workflow.py` | 89576 | `befc8524aac247992371780114e57990c4ebe286` | `60d1f1f1c0d4a04385ecada5e424233eaf81a8ff3a7e47d0b0886bc81a6a5008` | 匹配 |
| `src/quant/research/m3/successor_bridge.py` | 29699 | `09d8b3b267ea30fc0764d5734d4636722f5ed22b` | `64474646d671164435bddd572a9cbd9d626943d1a7242382d05bd32d8d98ea69` | 匹配 |
| `docs/framework/agent/20260809_M3_G1_Windows正式发布物磁盘复验报告.md` | 2149 | `2f8d4a263eb141c9794c239f4776d16085f19e17` | `434fbc7d82f5d181031323a8018bdc102c7e2ddf2901df11d160abd99786b387` | 匹配；仅历史证据 |

开始审计时 HEAD/branch 分别为上述 exact 值；cached=0；只有经理任务书为 untracked，无 production/tests/config/review 改动。

### 2.2 历史唯一候选

tracked 报告记录：

- release id：`08eb9b31ab4d8c8473c0a7bb612df83009a68b761b8a35816653b2ce07807359`
- project-relative path：`data/clean/m3_g1/releases/08eb9b31ab4d8c8473c0a7bb612df83009a68b761b8a35816653b2ce07807359`
- manifest SHA-256：`d3923fa1143fbc5c4ff352f7b4d0cf5baeb197d2bb161ead34255bd7375f99c4`
- quality SHA-256：`00400e218be202aa705b01739873ae65f0eec9174e072f1e93dcb6e7132086b2`
- primary candidate key：`f51655b078255760e8925534ac1dac3161a3ec874c88e47e592cb5afe5845036`
- 历史结果：Windows `verify_g1_release` 报告 `17` 个 exact artifacts；Linux/ext4 Gate 仍开放。

本轮没有将上述文本解释为当前磁盘存在性或 fresh verification 证据，也没有触及报告中的旧 release。

## 3. public 合同重建

### 3.1 `G1Release` 与 fresh verifier

`G1Release` 强制 release id 为 hex64，`root.name == release_id`，且 `manifest.json` / `quality.json` 必须是 root 直属文件。`verify_g1_release` 的公开合同不是只核对报告 SHA，而是 fresh 闭合：

1. 拒绝 ancestor symlink，快照 ancestor/root/file physical identity；
2. 要求 final directory entry set exact，所有项为 regular single-link files；
3. 读取并验证 canonical manifest/quality/summary bytes；
4. 重算 manifest 声明的每个 artifact SHA、size、schema、row/content identity；
5. 重建 quality、cross-source、price-limit coverage、primary candidate 与 release id；
6. 返回 exact type `VerifiedG1Release` 前再验 physical identity 未漂移。

因此 release id/manifest SHA/quality SHA 的历史文本无法代替 public verifier。

### 3.2 successor 消费边界

`successor_bridge._parse_fold` 从 request 获取 project-relative `g1_release_path`、`g1_release_id` 和 manifest SHA；先要求 exact project member directory 与 leaf id 一致，然后构造 `G1Release` 并调用 public verifier。只有 `VerifiedG1Release` exact type、manifest release id 和 request manifest SHA 均闭合，才能进入 `SuccessorFoldRequest`。

所以本 tracked-only 盘点不能提供 successor 所需 A15，也不能生成 request/root/CLI 准入。

### 3.3 future G1 run 公共入口

`quant.research.m3.run_g1` 的 public CLI 强制 `--config`，支持显式 `--project-root`，命令集合为 `status/index/history/reference/prepare/publish/run-all`。`run-all` 也是通过同一 workflow 次序调用 index→history→reference→prepare→publish；`prepare` 不是 durable 阶段。`g1_workflow` 的 release root 唯一布局是 project root 下 `data/clean/m3_g1/releases`，publish 由 package workflow 与 `m3_release` 完成。

因此若候选不可用，future run 必须另行冻结 exact config/project root/source snapshot/network/data writer/CPU/no-clobber/evidence，并通过 public CLI 进入；不得私调 workflow、扫描旧 release 或在失败后自动清理/重试。

## 4. 单一路径后续授权合同

只有中央另行逐字授权后，才可对 §2.2 exact path 做下列操作：

1. non-follow 检查 exact ancestors 与 release root，拒绝 symlink/reparse/hardlink/identity 漂移；
2. 只读 exact `manifest.json`、`quality.json` 和 manifest 声明的 exact artifact paths；
3. 在独立 Python/真实 I/O 资源租约下构造 exact `G1Release` 并调用 `verify_g1_release`；
4. 核对 fresh manifest SHA、quality SHA、release id、primary candidate 及 artifact set；
5. 任一失败即 `FORMAL_G1_CANDIDATE_INVALID`，禁止 parent listing/glob/latest/sibling/old release/替代候选。

本报告没有执行上述任一步，也不授予后续角色该权限。

## 5. 对抗结果

| 反例 | 静态裁定 |
|---|---|
| 历史报告 blob/SHA 与候选字段全部正确 | 只证明 tracked 报告未漂移；A15 仍 `MISSING`。 |
| 报告记录 Windows fresh PASS/17 artifacts | 不证明 2026-08-28 磁盘 bytes 存在或未漂移。 |
| exact candidate 缺失 | 不得扫描 parent；不得采用历史旧 release。 |
| manifest 自述与 root leaf/request id 相同 | 仍必须 fresh 重算 quality/artifact/primary/release identity。 |
| 任一路径与 LOCKED retained 存在交集可能 | 本轮不进入、不扫描、不验真；后续应 `SCOPE_STOP`。 |
| public verifier 需要 Python/长 I/O | 本轮不运行；等待中央独立资源 grant。 |
| 候选无法 fresh 闭合 | 只可冻结 future G1 run，不得宣称 `READY`。 |

## 6. 实际命令与验收

所有命令均在 exact worktree 执行，且只读 tracked 文件/Git 对象：

| 目的 | 命令族 | 结果 |
|---|---|---|
| 规则/任务合同 | `Get-Content -Raw` 读 `AGENTS.md`、`.ai/*` 必要规则与任务书 | 完整读取；写白名单仅 delivery。 |
| Git/source identity | `git rev-parse`; `git hash-object`; `Get-FileHash`; `Get-Item` | HEAD/branch exact；§2.1 blob/SHA/bytes 全匹配。 |
| public API 定位 | `rg -n` + `Get-Content` 定向读取四个 production source | G1/run/workflow/successor 合同与§3一致。 |
| scope/hygiene | `git status --short`; `git diff --cached --name-only`; `git diff --check` | 写入前 taskbook-only/cached0/diff-check PASS。 |

### 明确未运行/未访问

- Python / pytest / Ruff / mypy / cold import / public verifier：`UNRUN`
- Qlib / network / actual worker / release publication：`UNRUN`
- `data/clean` actual release/root/parent/sibling：`NOT READ / NOT LISTED / NOT SCANNED`
- LOCKED retained / ignored / local config / secret / 真实 data：`NOT ACCESSED`
- config/root/release/evidence/temp：`NOT CREATED`
- taskbook/review/production/tests/config/roadmap/governance：`NOT MODIFIED`
- stage / commit / merge / cleanup / retirement：`UNRUN`

## 7. 交付边界

本交付仅证明 tracked 历史报告和 public 合同的静态一致性，不证明候选当前存在、未漂移或可消费。所以终态不得超过：

`CENTRAL_READ_ONLY_GRANT_REQUIRED / A15 MISSING`

后续只能由未参与本 Worker 的唯一独立 reviewer 审查本报告。即使 review PASS，也不关闭 A15、actual successor、Qlib/new root/retained、Windows 真实运行或 M3/Linux Gate。
