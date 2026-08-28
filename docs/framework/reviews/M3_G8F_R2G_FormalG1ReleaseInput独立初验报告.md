# M3-G8F-R2G Formal G1 Release Input 独立初验报告

日期：2026-08-28<br>
task id：`M3-G8F-R2G-FORMAL-G1-RELEASE-INPUT`<br>
角色：未参与审计 Worker 的独立 reviewer<br>
模式：`TRACKED_ONLY / STATIC_ONLY / CPU NONE`<br>
结论：`REVIEW_PASS / CENTRAL_READ_ONLY_GRANT_REQUIRED / A15 MISSING`

## 1. 审查结论

任务书与交付报告在权限、事实和终态上闭合。独立复算确认五个 tracked 锚点的 Git blob、工作区 SHA-256 与 bytes 均与交付报告一致；定向源码审查确认，历史报告中的 release id、manifest SHA、quality SHA 与 primary candidate key 不能替代当前磁盘上的 public fresh verification。

本轮没有读取、列举或扫描 `data/clean`，没有构造 `G1Release`，没有调用 `verify_g1_release`，也没有访问 LOCKED、ignored、local 或真实 data。因此本报告只批准 tracked-only 输入盘点的静态结论，不批准或暗示候选当前存在、未漂移、可消费或已关闭 A15。

终态必须保持：

`CENTRAL_READ_ONLY_GRANT_REQUIRED / A15 MISSING`

下一步若继续，必须由中央另行冻结 exact 单一路径 non-follow 只读检查与独立 Python/真实 I/O 资源租约。任何缺失、reparse、physical identity、manifest、quality、artifact set、digest 或 release identity 漂移均应 `FORMAL_G1_CANDIDATE_INVALID`，不得扫描 parent、采用 sibling、猜 latest 或寻找替代 release。

## 2. 输入身份与范围

- exact base / HEAD：`10af1582845fbffd8356fa987d0c5ce2d6783ed4`
- branch：`codex/m3-g8f-r2g-formal-g1-release-input`
- taskbook SHA-256：`25fedd7d1891748e5711a5bf842b0c2920b70f3b5387604d53854ff5903183e9`
- delivery SHA-256：`56faa76465775cd863bde442875580aaf42aa105c24350ada93435d74a83bd7d`
- reviewer 唯一写入：`docs/framework/reviews/M3_G8F_R2G_FormalG1ReleaseInput独立初验报告.md`

审查开始时 cached=0，业务源码、测试、配置均无修改；仅任务书和交付报告为本任务 untracked 文档。审查没有修改任务书、交付报告、production、tests、config、roadmap 或 governance。

## 3. tracked 证据独立复算

| 路径 | bytes | Git blob | SHA-256 | 结果 |
|---|---:|---|---|---|
| `src/quant/data/m3_release.py` | 107553 | `1e02a243be9a6dbf71eaeec4054dbe7956568f57` | `8ad4b07f3309cd92ef2f93fd1e321a0652065a42b33ac5da384a8fd149c9b463` | 匹配 |
| `src/quant/research/m3/run_g1.py` | 33274 | `f17642c7c9724ebf2aeeb203f21ab1db4e163cbf` | `4cc638ad108199f841aed80d49e398e282ffb1a78cffed0325f509d8f7e54d1e` | 匹配 |
| `src/quant/research/m3/g1_workflow.py` | 89576 | `befc8524aac247992371780114e57990c4ebe286` | `60d1f1f1c0d4a04385ecada5e424233eaf81a8ff3a7e47d0b0886bc81a6a5008` | 匹配 |
| `src/quant/research/m3/successor_bridge.py` | 29699 | `09d8b3b267ea30fc0764d5734d4636722f5ed22b` | `64474646d671164435bddd572a9cbd9d626943d1a7242382d05bd32d8d98ea69` | 匹配 |
| `docs/framework/agent/20260809_M3_G1_Windows正式发布物磁盘复验报告.md` | 2149 | `2f8d4a263eb141c9794c239f4776d16085f19e17` | `434fbc7d82f5d181031323a8018bdc102c7e2ddf2901df11d160abd99786b387` | 匹配；仅历史证据 |

历史报告确实记录 exact release id `08eb9b31ab4d8c8473c0a7bb612df83009a68b761b8a35816653b2ce07807359`、manifest SHA、quality SHA、primary candidate key，以及当时 Windows public verifier 的 `17` artifacts PASS。报告同时明确 Linux/ext4 Gate 仍开放。以上事实只证明 tracked 报告内容未漂移，不证明 2026-08-28 当前磁盘状态。

## 4. public 合同独立映射

### 4.1 `G1Release` 与 fresh verifier

`G1Release` 要求 hex64 release id、`root.name == release_id`，并要求 `manifest.json` 与 `quality.json` 为 root 直属路径。`verify_g1_release` 进一步执行：

1. ancestor symlink 拒绝与 ancestor/root physical identity 快照；
2. final directory entry set exact；每个 entry 必须是单 link regular file，且物理 identity 不重复；
3. canonical manifest、quality、summary bytes 读取与重编码等价；
4. manifest 声明的每个 artifact bytes、size、schema、row/content identity 重算；
5. quality、cross-source、price-limit coverage、primary candidate 与 release id 重建；
6. 返回 `VerifiedG1Release` 前再次确认 root、files 与 ancestor physical identity 未漂移。

这组检查明确排除了“只凭历史 SHA 文本构造可信对象”的路径。

### 4.2 successor 消费边界

`successor_bridge` 从 request 取得 project-relative release path、release id 与 manifest SHA；要求 exact project member directory 和 leaf id 一致，然后 fresh 构造 `G1Release` 并调用 public verifier。只有 exact `VerifiedG1Release`、manifest release id 与 request manifest SHA 同时闭合，才构造 successor fold request。

所以 tracked-only 审计不能生成 successor 可消费的 A15，也不能把 historical PASS 升级为 request/root/CLI 准入。

### 4.3 future run 边界

`run_g1` 的 public CLI要求显式 `--config`，支持显式 `--project-root`，公开 stage 为 `status/index/history/reference/prepare/publish/run-all`；`run-all` 仍沿相同 stage 次序，且 `prepare` 不是 durable stage。`g1_workflow` 的 release root 布局固定在 project root 下 `data/clean/m3_g1/releases`。

因此候选不可用时只能另立 future G1 run 合同，冻结正式 config、snapshot、root、资源、network、no-clobber 与失败保留；本包无权执行或私调 workflow。

## 5. 独立对抗性反例

实现 Worker 已论证历史报告不等于 current bytes。本 reviewer 追加未使用的时间漂移/路径替换反例：

1. tracked 报告 blob、release id、manifest SHA、quality SHA 全部保持原值；
2. 报告生成后，exact lexical release leaf 被删除、替换为另一目录，或变成指向内容相同目标的 symlink/junction/reparse；
3. 仅复读报告仍会得到同一组“正确”字段，但当前 leaf/ancestor physical identity、entry type 或 artifact bytes 已不再由报告证明；
4. public verifier 的 non-follow、physical identity 与 fresh bytes 闭包会拒绝相应漂移，而 tracked-only 审计无法执行这些检查。

裁定：该反例进一步证明历史 exact evidence 不能关闭当前 A15。即使替换目标暂时含有相同 manifest/quality 文本，也不能跳过 exact path、entry type、artifact set 与 end-to-end identity 重验。后续授权不得通过 parent listing 或 sibling 搜索“补救”候选缺失。

## 6. 交付陈述核对

| 交付陈述 | 独立结果 |
|---|---|
| tracked report/source identity 匹配 | PASS；五个锚点独立复算一致。 |
| 历史 PASS 不能关闭 current A15 | PASS；public verifier需要当前物理与字节闭包。 |
| 单一路径后续检查必须另行中央授权 | PASS；本轮没有真实 I/O/Python 权限。 |
| 候选失败不得扫描 parent/寻找替代品 | PASS；符合 fail-closed 与 exact scope。 |
| future run 只冻结合同、不执行 | PASS；没有创建 config/root/release/evidence。 |
| 不过度声明 Gate | PASS；明确保持 A15/M3/Linux 等开放。 |

未发现 P0/P1/P2 阻断。报告中的静态事实、失败语义和未验证边界与源码及任务书一致。

## 7. 实际验证与明确未执行项

已执行的只读命令族：

- `Get-Content -Raw`：AGENTS、taskbook、delivery、tracked 历史报告；
- `git rev-parse`、`git branch --show-current`、`git hash-object`、`git status --short`、`git diff --cached --name-only`、`git diff --check`；
- `Get-FileHash`、`Get-Item`：tracked source/report 与 task/delivery identity；
- `rg -n` 与定向 `Get-Content`：只读 public G1/run/workflow/successor 合同。

明确未执行/未访问：

- Python、pytest、Ruff、mypy、cold import、public verifier、Qlib、network：`UNRUN`；
- `data/clean` actual release/root/parent/sibling：`NOT READ / NOT LISTED / NOT SCANNED`；
- LOCKED retained、ignored、local config、secret、真实 data：`NOT ACCESSED`；
- config/root/release/evidence/temp：`NOT CREATED`；
- stage、commit、merge、cleanup、retirement：`UNRUN`。

## 8. 最终裁定

`REVIEW_PASS / CENTRAL_READ_ONLY_GRANT_REQUIRED / A15 MISSING`

本 PASS 只认可 tracked-only 输入盘点与后续 fail-closed 合同。它不证明 exact candidate 当前存在或可消费，不关闭 A15、actual successor、Windows真实运行、Qlib/new root/retained、M3 Gate 或 Linux/ext4 Gate。
