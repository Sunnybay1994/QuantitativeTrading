# M3-G8F-R2D Actual Successor Run Input Inventory 交付报告

日期：2026-08-28
task id：`M3-G8F-R2D-ACTUAL-SUCCESSOR-RUN-INPUT-INVENTORY`
角色：唯一 Luna 审计 Worker
资源级别：`STATIC_ONLY / CPU NONE`

- exact base / HEAD：`f448f9e7501edd4f2299aff3b2b9eaabd8af0da7`
- branch：`codex/m3-g8f-r2d-actual-successor-run-input-inventory`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2d-actual-successor-run-input-inventory`
- 唯一写入：`docs/framework/deliveries/M3_G8F_R2D_ActualSuccessorRunInputInventory交付报告.md`
- 盘点结论：`INPUT_INVENTORY_FROZEN`
- 运行准入终态：`CONTRACT_STOP / INPUT_INVENTORY_INCOMPLETE`

## 1. 结论

已仅用 exact HEAD 的 tracked 文件、Git 对象和任务书批准的公开文档静态重建 A1–A22。源码入口、request
schema、`resume=false`、package-owned dump 相对路径及其 tracked bytes 可以验证；但是正式 two-fold config、
正式 G1 release bytes/manifest、Windows native Python 3.12 + Qlib 环境身份均没有获批 tracked 证据。

因此 `A14/A15/A17` 保持 `MISSING`，并连带 `A11/A12/A13/A16/A19` 保持 `MISSING`。`A20` 仍是
`USER_CHOICE`；执行者、request/root/path/时间/code version/LOCKED 隔离/执行租约仍是
`CENTRAL_RESOURCE`。本交付没有用 example config、历史 WSL 环境或旧文档补齐正式输入，也没有把 tracked dump
文件侧正确性升级成正式双 config tool-spec 闭包。

本包不是 actual-run 包，不能生成 `READY`，不能进入 A→B→C 运行生命周期。唯一合法推进是由任务书列明的
owner/中央依赖序关闭缺口后，另建 actual-run package。

## 2. 身份、输入与锚点复核

### 2.1 初始现场

- `git rev-parse HEAD`：`f448f9e7501edd4f2299aff3b2b9eaabd8af0da7`。
- `git rev-parse --abbrev-ref HEAD`：`codex/m3-g8f-r2d-actual-successor-run-input-inventory`。
- 写入前 `git status --short`：仅本任务书为 untracked；没有 production/tests/config/roadmap/governance 改动。
- `git diff --cached --name-only`：空，`cached=0`。
- 任务书 SHA-256：`c6ff6f2f1780c4c54334a1988dc5d984cb74574e330c4350a7420050ad38d0a8`，与中央复核值一致。

### 2.2 source identity 代号

下表全部 working-file SHA-256 与同路径 tracked Git blob 对应；共同 source commit 为
`f448f9e7501edd4f2299aff3b2b9eaabd8af0da7`。

| 代号 | tracked source | Git blob | working SHA-256 | bytes |
|---|---|---|---|---:|
| S1 | `src/quant/research/m3/successor_bridge.py` | `09d8b3b267ea30fc0764d5734d4636722f5ed22b` | `64474646d671164435bddd572a9cbd9d626943d1a7242382d05bd32d8d98ea69` | 29699 |
| S2 | `src/quant/research/m3/run_successor.py` | `f3d6702e173fb8515d9107e04f753514cd2d5dce` | `1fec7b7333dadcc2fd56d271b7a5d9837b4a6f2c7b1748b3c088fc0dd4c47c2b` | 2813 |
| S3 | `src/quant/research/m3/successor_runtime.py` | `59212daf87a3b8f44052e27f1a68abe1cef8f5c9` | `272c42f63612e2ce4e927460c1885e95cdab9c17e3d13f52bd82d9734caf608b` | 116899 |
| S4 | `src/quant/research/m3/successor_upstream_stage.py` | `1edab597dfeb144e23ae125dcd4a30ecd8caa98d` | `2adb24f040cf191ea7f28855b8d4b56e35350c69cd455f387aacc0f16be5a51c` | 163215 |
| S5 | `src/quant/research/m3/fetch_qlib_tool.py` | `608f35238858cc054d0f3ecb444f7cd73177f332` | `33342e5f487fab59fd760dd01fcde961df88f04e58e0e73c8a47ca26e59a15c3` | 4237 |
| S6 | `src/quant/research/m3/config.py` | `6d60d8827a803453bb26868208929d3c31960dbd` | `7338ab6a6b959f3a8556bf8011aa6898580df434f920ae167dc8d27f966fedfa` | 45905 |
| S7 | `src/quant/data/m3_release.py` | `1e02a243be9a6dbf71eaeec4054dbe7956568f57` | `8ad4b07f3309cd92ef2f93fd1e321a0652065a42b33ac5da384a8fd149c9b463` | 107553 |
| S8 | `data/external/qlib/v0.9.7/dump_bin.py` | `cb8ed72dabbbd990edb7c5ec14d34356124b7580` | `b8f34c57ce1ef4b1772f3909735e66058f21b25bd7ab8a5f16318822401fe53f` | 21847 |
| S9 | `configs/research/m3_qlib_example.toml` | `74d2caae67fc0ec86669fd25f6d973e521405c87` | `fee781d4dab59d2de6fe55eff223cd761b9f7c7f0b87a233da3615e4cddf3892` | 7181 |
| S10 | `docs/framework/agent/M3_G0_py312环境创建与兼容探针主Agent最终验收报告.md` | `7173ecc41245fd8d81a5140a81c1fd0459c667ca` | `3f603a9f35f6f2261532827fdf8a7d0a3792e5ebdb894f50ced16f6f9c7e2601` | 4535 |
| R2C-T | `docs/framework/tasks/M3_G8F_R2C_ActualSuccessorRunAdmission任务书.md` | `1f1ae222a3290cd6e27140952c3d592fcf2d7558` | `95925d6296faf63db511309173142aa66beda86ff939d254b3158184b8d83d33` | 11593 |
| R2C-D | `docs/framework/deliveries/M3_G8F_R2C_ActualSuccessorRunAdmission交付报告.md` | `d251af76e5a014848ac694fcb15c03ebabc446d7` | `3ab8efe9b3efd2c59ba4e2e34ce200062c313b2bc5b007ef6e9357f81a46144f` | 26295 |
| R2C-R | `docs/framework/reviews/M3_G8F_R2C_ActualSuccessorRunAdmission独立初验报告.md` | `60ab167acb191143901279a782737a26f6482378` | `519159b98100ddfe475d59cb462db80cb5c47c56c199b120c44896a5c4e28165` | 16974 |

### 2.3 tracked-only negative inventory

- `git ls-files -- 'configs/research/m3*.toml'` 只返回
  `configs/research/m3_qlib_example.toml`。它的文件名与内容均只构成 example，不构成正式 fold config。
- `git ls-files -- 'data/**/manifest.json' 'data/**/quality.json' 'data/**/g1/**' 'data/**/release/**' 'data/**/releases/**'`
  无输出；只证明本 HEAD 的 tracked main 没有该类正式 G1 release bytes/manifest，不声称 ignored、外部或真实
  data 现场不存在。
- S9 的 dump size/SHA 恰与 S8 一致，只可说明 example 与 tracked dump 文件侧常量相同；禁止用它推断正式
  fold、G1、runtime identity 或实际运行参数。
- S10 明确验收的是 WSL `/home/mabw/miniforge3/envs/py312`（Python 3.12.13 / pyqlib 0.9.7）；它不是
  Windows native executable 证据，也没有被转换、复制或替代为 Windows 候选。

## 3. A1–A22 独立重建矩阵

“source identity”中的 `H` 均指共同 source commit
`f448f9e7501edd4f2299aff3b2b9eaabd8af0da7`；S/R2C 代号的 blob、SHA-256 与 bytes 见 §2.2。
`AVAILABLE_VERIFIED` 只证明 tracked 常量/源码锚点，不表示完整 request 可运行。

| ID | required field | candidate path / API | source identity | 状态 | 冲突与 future Gate / 唯一决策主体 |
|---|---|---|---|---|---|
| A1 | source Git SHA | current exact main tree | `H` | `AVAILABLE_VERIFIED` | 当前 source identity 已匹配；真正建包时由中央重冻届时 latest clean main，漂移即新任务。 |
| A2 | request 生成者身份 | future run package 唯一角色 | `H + R2C-T`（§5.1/§5.5） | `CENTRAL_RESOURCE` | 当前无生成者租约；中央分配唯一生成者/runner，经理或临时脚本不得冒充。 |
| A3 | request resolved absolute path | future run worktree 内 ignored no-clobber path；S2 `--request` → S1 `run_production_successor_bridge` | `H + S1 + S2` | `CENTRAL_RESOURCE` | 当前不得命名或创建；中央批准 exact resolved path。 |
| A4 | request canonical bytes / size / lowercase SHA-256 | S1 `_load_canonical_request_object` / `_canonical_json_bytes` | `H + S1` | `MISSING` | A2/A3及全部字段未冻结，故没有合法 canonical request；future 生成后还须调用前 stable/fresh 双读。 |
| A5 | schema id | S1 `REQUEST_SCHEMA_ID` | `H + S1`；exact `m3-successor-bridge-request-v1` | `AVAILABLE_VERIFIED` | 固定源码常量，不是用户选择，不代表 request bytes 已存在。 |
| A6 | absolute `project_root` | future actual-run worktree root；S1 `_parse_absolute_path_text` + `_require_real_directory` | `H + S1 + R2C-T` | `CENTRAL_RESOURCE` | 当前 inventory worktree不是 future actual-run root且会退休；中央批准 exact native real directory。 |
| A7 | controlled relative + resolved absolute | PROJECT ignored 区；A 不存在→B 单次 mkdir→C existing empty；S1 `_require_project_relative` / `_require_real_directory` | `H + S1 + R2C-T`（§5.2） | `CENTRAL_RESOURCE` | 中央批准 parent/name/一次 mkdir 与旁路 absolute identity；当前不得创建。B 后失败保留 partial 只读，不 adopt/清空/换根。 |
| A8 | `resume` | request exact bool `false` | `H + S1 + R2C-T`（§5.2） | `AVAILABLE_VERIFIED` | 首次真跑固定 `false`；不得复用旧 terminal/retained。S1 还拒绝非 bool。 |
| A9 | canonical `now` | execution-time UTC 微秒 `Z`；S1 `_parse_canonical_utc` | `H + S1` | `CENTRAL_RESOURCE` | runner 在授权执行窗口生成；任务书不能预填虚假时间。 |
| A10 | runtime `code_version` | future frozen source identity string；S1 `_parse_runtime_identity` | `H + S1 + S3` | `CENTRAL_RESOURCE` | 源码只冻结非空、无控制字符类型合同；中央须冻结精确语义值，不能用当前短 SHA 猜测。 |
| A11 | dependency fingerprint SHA-256 | approved runtime environment fingerprint | `H + S1 + S3 + S4` | `MISSING` | 只有 hex64 字段合同，无获批 Windows runtime 的公开生成/验证证据；受 A17 阻塞。runtime environment owner 提供，中央复核。 |
| A12 | provider runtime fingerprint SHA-256 | formal provider/G1 runtime identity | `H + S1 + S4 + S7` | `MISSING` | 正式 G1/provider 环境缺失，受 A15/A17 阻塞；G1/provider owner 提供，中央复核。 |
| A13 | exact two fold ids | two-item canonical sorted list；形状 `fold_[0-9]{3}` | `H + S1 + S3 + R2C-T` | `MISSING` | 源码只证明格式、恰好两个、唯一和排序；`fold_001/fold_002` 只是合同形状候选，没有两份正式 config 证明具体实例。正式 config owner 冻结。 |
| A14 | 每 fold config path / raw SHA / full SHA | `configs/` 下正式 two-fold configs；S1 `_parse_fold` / `_fresh_load_config`；S6 `load_m3_config` | `H + S1 + S6`；tracked main 仅 S9 example | `MISSING` | 无正式双 config；框架/研究 config owner 产生并审查 tracked 正式配置。禁止复制/提升 S9 或 retained/local config。 |
| A15 | 每 fold G1 path / id / manifest SHA | S1 `_fresh_verify_release` → S7 `verify_g1_release` | `H + S1 + S7`；tracked release query 为空 | `MISSING` | 无 tracked formal release bytes/manifest；G1 owner 指定唯一当前 formal release，须能由 public verifier fresh 重建。禁止旧文档/LOCKED/ignored 候选。 |
| A16 | 两 fold exact 相同 Qlib dump tool spec | S5 `build_qlib_dump_tool_spec(config)`；S1 `_parse_toolchain` | `H + S1 + S5` | `MISSING` | A14 缺失，无法构造两份正式 spec 或证明 `specs[0] == specs[1]`；S9 example 不得替代。config owner 先闭 A14。 |
| A17 | exact native py312 executable | Windows Python 3.12 + Qlib 0.9.7 environment | `H + S1 + S10` | `MISSING` | S10 仅是 WSL POSIX executable 环境；Windows-only actual run 不得采用。环境 owner 另建或证明 exact Windows native executable，中央授权。 |
| A18 | Qlib dump relative path | `data/external/qlib/v0.9.7/dump_bin.py`；S5 `DEFAULT_TARGET_PATH` | `H + S5 + S8`；blob `cb8ed72dabbbd990edb7c5ec14d34356124b7580` / SHA `b8f34c57ce1ef4b1772f3909735e66058f21b25bd7ab8a5f16318822401fe53f` / 21847 bytes | `AVAILABLE_VERIFIED` | tracked path与bytes闭合；不得调用 S5 下载/替换逻辑。此项不关闭 A19。 |
| A19 | dump size/SHA 与正式双 spec 一致 | candidate `21847` / `b8f34c57ce1ef4b1772f3909735e66058f21b25bd7ab8a5f16318822401fe53f` | `H + S1 + S5 + S8`；S9 仅反例旁证 | `MISSING` | 文件侧正确，但 A14/A16 缺失，无法证明正式双 spec closure；禁止把 example 的相同值升级为正式证据。 |
| A20 | positive exact float timeout | S1 `_parse_toolchain`; S3/S4 `SuccessorToolchainBinding` / validation | `H + S1 + S3 + S4` | `USER_CHOICE` | 只有 strict positive finite exact `float` 类型合同，无业务值 SSOT。用户/中央冻结运行窗口与 exact float；不能用 int/env/default。 |
| A21 | LOCKED retained 隔离证明 | worktree registry 的 detached locked identity，仅允许元数据审计 | `H + R2C-T`（§5.3）；LOCKED commit `c9f2f36cf0cd76721fe62e6a8de7566ae8dd6d79` 未进入 | `CENTRAL_RESOURCE` | 中央在 path 冻结后执行 non-follow/containment/hardlink/reparse 审计；本包未进入、扫描、hash或读取 LOCKED tree。 |
| A22 | actual execution lease | unique worker / CPU / threads / cwd / PYTHONPATH / evidence / max window | `H + R2C-T`（§5.5） | `CENTRAL_RESOURCE` | 中央串行授权；默认 network 禁止，首失败 STOP 并保留 root/evidence。本包 `STATIC_ONLY / CPU NONE`。 |

## 4. 缺口依赖与唯一推进顺序

当前不是“只差 CPU”：

1. framework/research config owner 提供并审查两份正式 tracked config，关闭 A14。
2. G1 owner 指定一个 current formal release，提供 tracked/public bytes与manifest，允许 S7 fresh verify，关闭 A15。
3. Windows runtime environment owner 建立或证明 exact native Python 3.12 + Qlib 0.9.7 identity；中央授权，关闭 A17。
4. 仅在 1–3 后重建 A11/A12/A13/A16/A19，证明 config/G1/environment/tool spec 为同一 fresh identity closure。
5. 用户/中央冻结 A20；中央冻结 A2/A3/A6/A7/A9/A10/A21/A22。
6. 只有 A1–A22 全部具体、fresh 可验证且无冲突，才允许另建 actual-run package；本 inventory 不能被直接执行。

任何 owner 都不得用 S9 example、S10 WSL 路径、旧 commit/archive 文本、ignored/local config、真实 data/root 或
LOCKED retained 填空。缺口未闭合即维持 `CONTRACT_STOP / INPUT_INVENTORY_INCOMPLETE`。

## 5. 对抗盘点结果

| 反例 | 静态结果 |
|---|---|
| S9 的 dump SHA/bytes 恰与 S8 相同 | A14/A16 仍 `MISSING`；example 不是正式 fold config。 |
| S10 报告 py312/Qlib PASS | A17 仍 `MISSING`；WSL `/home/...` 不能作为 Windows native executable。 |
| S8 tracked file路径、SHA、size 全部正确 | A18 可 `AVAILABLE_VERIFIED`，但 A19 因无正式双 spec 仍 `MISSING`。 |
| 旧文档/commit 提及 G1 release | 没有 tracked release bytes/manifest + current S7 fresh verify，A15 不升级。 |
| controlled root 名称看似合理 | 未获中央 exact path/mkdir 授权，A7 保持 `CENTRAL_RESOURCE`，当前没有创建/probe。 |
| 候选可能解析到 LOCKED/旧 worktree/ignored/local/真实 data | 不读取、不生成候选；由 A21 future central audit 处理。 |
| 某结论需要 Python/Qlib/probe | 对应项保持 `MISSING`/`CENTRAL_RESOURCE`；本包不运行命令补证。 |

## 6. 实际只读命令与结果摘要

所有命令均在本 worktree 执行；没有 Python/Qlib/网络/运行现场命令。

| 目的 | 命令族 | 结果摘要 |
|---|---|---|
| identity/cached | `git rev-parse HEAD`; `git rev-parse --abbrev-ref HEAD`; `git status --short`; `git diff --cached --name-only` | HEAD/branch exact；写入前仅 taskbook untracked；cached=0。 |
| tracked scope | `git -c core.quotePath=false ls-files -- <exact patterns>` | 10锚点、R2C exact3 均 tracked；M3 config只返回 S9；G1 manifest/quality/release模式无输出。 |
| Git/working bytes | `git hash-object -- <exact file>`; `Get-FileHash -Algorithm SHA256`; `Get-Item` | §2.2 全部 blob/SHA/size匹配；S8=21847 bytes。 |
| 文档读取 | `Get-Content -Raw` 根 `AGENTS.md`、本 taskbook、R2C task/delivery/review；定向读取 S1/S2/S5/S10 | 冻结合同、历史STOP/F1修正、公开环境边界已映射。 |
| 源码定位 | `rg -n <exact field/function patterns>` S1–S7 | schema/path/fold/runtime/toolchain/release/type guards 均定位到 package-owned source。 |
| negative inventory | `git ls-files` 对 `configs/research/m3*.toml` 与 G1 release patterns | 只作 tracked-main 范围内的 absent 证明，未扫描 ignored/真实 data。 |

## 7. 禁止现场与未运行边界

| 项 | 本 Worker 状态 |
|---|---|
| Python / pytest / Ruff / mypy / cold import | `UNRUN` |
| Qlib / dump tool execution或下载 | `UNRUN` |
| actual worker / network / browser | `UNRUN` |
| request 生成或读取本地 candidate request | `UNRUN / 未创建` |
| controlled root / evidence / runtime file / temp directory | `未创建 / 未 probe` |
| ignored/local config、真实 data/root、secret、外部 runtime environment | `未读取` |
| detached LOCKED `c9f2f36cf0cd76721fe62e6a8de7566ae8dd6d79` tree | `未进入 / 未扫描 / 未 hash / 未读取` |
| taskbook/production/tests/config/roadmap/governance 修改 | `未修改` |
| stage / commit / merge / cleanup / retirement | `未执行` |
| actual Qlib、new root、retained、M3 Gate、Linux Gate | `OPEN` |

## 8. 交付终态

本报告只冻结 inventory 事实：`INPUT_INVENTORY_FROZEN`。

由于 A14/A15/A17 及其依赖仍缺失，执行准入终态必须是：

`CONTRACT_STOP / INPUT_INVENTORY_INCOMPLETE`

不得解释为 `READY`，不得据此创建 request/root/evidence 或运行 successor。后续仅交由未参与本 Worker 的唯一独立
reviewer 静态复核；review 通过也只能确认本 inventory 的诚实性，不能关闭 actual-run 或 M3 Gate。
