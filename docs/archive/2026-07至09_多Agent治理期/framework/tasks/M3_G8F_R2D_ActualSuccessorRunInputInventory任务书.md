# M3-G8F-R2D Actual Successor Run Input Inventory 任务书

日期：2026-08-28<br>
状态：`FROZEN / STATIC_ONLY / INPUT_INVENTORY_INCOMPLETE`

## 1. 身份与目标

- task id：`M3-G8F-R2D-ACTUAL-SUCCESSOR-RUN-INPUT-INVENTORY`
- exact base / HEAD：`f448f9e7501edd4f2299aff3b2b9eaabd8af0da7`
- branch：`codex/m3-g8f-r2d-actual-successor-run-input-inventory`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2d-actual-successor-run-input-inventory`
- 目标：仅从 latest-main tracked 文件、Git 对象和公开文档重建 R2C A1–A22 输入矩阵，区分已验证常量、缺失正式输入、用户选择与中央资源，不创建或运行 actual successor。

本包不是 actual-run 包，不生成 request，不创建 controlled root，不运行 Qlib、Python、worker 或网络。结论上限为
`INPUT_INVENTORY_FROZEN`；由于正式 two-fold config、正式 G1 release 与 Windows py312 运行身份均无 tracked 证据，
当前必须保持 `INPUT_INVENTORY_INCOMPLETE`，不得写 `READY`。

## 2. exact3 与角色

1. `docs/framework/tasks/M3_G8F_R2D_ActualSuccessorRunInputInventory任务书.md`（经理唯一写）
2. `docs/framework/deliveries/M3_G8F_R2D_ActualSuccessorRunInputInventory交付报告.md`（唯一审计 Worker 写）
3. `docs/framework/reviews/M3_G8F_R2D_ActualSuccessorRunInputInventory独立初验报告.md`（不同独立 reviewer 写）

当前只批准路径 1。中央复核任务书前不得派 Worker/reviewer。后续若批准，Worker 只写路径 2，reviewer 只写路径 3；
不得修改 production、tests、config、roadmap、governance/UA/Gate SSOT、R2C 文档或任何运行现场。

## 3. 允许与禁止的只读输入

允许：

- `git ls-files`、`git rev-parse`、`git hash-object`、`git show`、`git diff`、`git status`；
- `rg`、`Get-Content`、`Get-Item`、`Get-FileHash` 读取本 worktree 内 tracked 文件；
- R2C task/delivery/review、当前 AGENTS、py312 已合流验收文档；
- 下表列出的 package-owned source、tracked example config 与 tracked dump tool。

禁止：

- Python、pytest、Ruff、mypy、cold import、Qlib、worker、网络、browser；
- 创建 request、controlled root、evidence、config、release、临时目录或任何 runtime 文件；
- 读取 ignored/local config、真实 data/root、secret、外部环境或未跟踪 artifact；
- 进入、扫描、hash 或读取 detached `c9f2f36cf0cd76721fe62e6a8de7566ae8dd6d79` LOCKED retained；
- 从 `configs/research/m3_qlib_example.toml` 推断正式 fold、G1、runtime identity 或运行参数；
- stage、commit、merge、删除、迁移、清理或退休任何 worktree/branch/evidence。

## 4. tracked 权威锚点

| tracked 输入 | Git blob | SHA-256 | 作用与边界 |
|---|---|---|---|
| `src/quant/research/m3/successor_bridge.py` | `09d8b3b267ea30fc0764d5734d4636722f5ed22b` | `64474646d671164435bddd572a9cbd9d626943d1a7242382d05bd32d8d98ea69` | request schema、fresh config/release/toolchain、入口 |
| `src/quant/research/m3/run_successor.py` | `f3d6702e173fb8515d9107e04f753514cd2d5dce` | `1fec7b7333dadcc2fd56d271b7a5d9837b4a6f2c7b1748b3c088fc0dd4c47c2b` | 唯一 CLI |
| `src/quant/research/m3/successor_runtime.py` | `59212daf87a3b8f44052e27f1a68abe1cef8f5c9` | `272c42f63612e2ce4e927460c1885e95cdab9c17e3d13f52bd82d9734caf608b` | request/runtime/fold/root identity |
| `src/quant/research/m3/successor_upstream_stage.py` | `1edab597dfeb144e23ae125dcd4a30ecd8caa98d` | `2adb24f040cf191ea7f28855b8d4b56e35350c69cd455f387aacc0f16be5a51c` | toolchain与wave fresh closure |
| `src/quant/research/m3/fetch_qlib_tool.py` | `608f35238858cc054d0f3ecb444f7cd73177f332` | `33342e5f487fab59fd760dd01fcde961df88f04e58e0e73c8a47ca26e59a15c3` | `DEFAULT_TARGET_PATH`与tool spec SSOT |
| `src/quant/research/m3/config.py` | `6d60d8827a803453bb26868208929d3c31960dbd` | `7338ab6a6b959f3a8556bf8011aa6898580df434f920ae167dc8d27f966fedfa` | `load_m3_config` |
| `src/quant/data/m3_release.py` | `1e02a243be9a6dbf71eaeec4054dbe7956568f57` | `8ad4b07f3309cd92ef2f93fd1e321a0652065a42b33ac5da384a8fd149c9b463` | `verify_g1_release` |
| `data/external/qlib/v0.9.7/dump_bin.py` | `cb8ed72dabbbd990edb7c5ec14d34356124b7580` | `b8f34c57ce1ef4b1772f3909735e66058f21b25bd7ab8a5f16318822401fe53f` | tracked dump candidate；size `21847`，仍须与正式双config spec闭合 |
| `configs/research/m3_qlib_example.toml` | `74d2caae67fc0ec86669fd25f6d973e521405c87` | `fee781d4dab59d2de6fe55eff223cd761b9f7c7f0b87a233da3615e4cddf3892` | 仅示例；不是正式两折配置 |
| `docs/framework/agent/M3_G0_py312环境创建与兼容探针主Agent最终验收报告.md` | `7173ecc41245fd8d81a5140a81c1fd0459c667ca` | `3f603a9f35f6f2261532827fdf8a7d0a3792e5ebdb894f50ced16f6f9c7e2601` | 只证明 WSL `/home/mabw/miniforge3/envs/py312`；当前 Windows-only 目标不得采用 |

`git ls-files` 的盘点事实：tracked M3 config 只有 `configs/research/m3_qlib_example.toml`；没有 tracked formal
two-fold config，也没有 tracked G1 release 目录或 manifest。该“未找到”只覆盖 Git tracked main，不声称外部或
ignored 现场不存在；本包禁止读取那些现场。

## 5. A1–A22 冻结矩阵

状态值仅允许 `AVAILABLE_VERIFIED`、`MISSING`、`USER_CHOICE`、`CENTRAL_RESOURCE`。其中
`AVAILABLE_VERIFIED` 只证明 tracked 常量或源码锚点，不自动证明完整 request 可运行。

| ID | required field | candidate path / API | tracked source identity | 状态 | 决策主体与 future Gate |
|---|---|---|---|---|---|
| A1 | source Git SHA | current exact main tree | commit `f448f9e7501edd4f2299aff3b2b9eaabd8af0da7` | `AVAILABLE_VERIFIED` | 中央在真正建包时须重冻届时 latest clean main；漂移即新任务 |
| A2 | request 生成者身份 | future run package唯一角色 | R2C §5.1/§8 | `CENTRAL_RESOURCE` | 中央分配唯一生成者/runner，禁止经理或临时脚本冒充 |
| A3 | request resolved absolute path | future run worktree 内 ignored no-clobber path | bridge `main --request` | `CENTRAL_RESOURCE` | 中央批准 exact path；当前不得命名或创建 |
| A4 | request canonical bytes/size/SHA | bridge `_load_canonical_request_object` | `successor_bridge.py` blob `09d8b3b...` | `MISSING` | A2/A3与全部字段冻结后生成；调用前fresh双读 |
| A5 | schema id | `REQUEST_SCHEMA_ID` | `m3-successor-bridge-request-v1`，源码行30–31 | `AVAILABLE_VERIFIED` | 固定常量，不是用户选择 |
| A6 | absolute `project_root` | future actual-run worktree root | bridge `_parse_absolute_path_text` + `_require_real_directory` | `CENTRAL_RESOURCE` | 当前inventory worktree会退休，不能充当未来运行root |
| A7 | controlled relative+resolved absolute | PROJECT ignored运行区，A不存在→B单次mkdir→C existing empty | R2C §5.2；bridge行310–384 | `CENTRAL_RESOURCE` | 中央批准parent/name/一次mkdir；失败后partial只读保留 |
| A8 | `resume` | exact bool `false` | R2C §5.2；bridge行317–319 | `AVAILABLE_VERIFIED` | 首次真跑固定false；不得采用旧terminal |
| A9 | canonical `now` | execution-time UTC微秒Z | bridge `_parse_canonical_utc` | `CENTRAL_RESOURCE` | runner在授权窗口生成；任务书不得预填虚假时间 |
| A10 | runtime `code_version` | future frozen source identity字符串 | bridge行442–460 | `CENTRAL_RESOURCE` | 中央冻结精确值；不得仅凭当前短SHA猜语义 |
| A11 | dependency fingerprint SHA | approved runtime environment fingerprint | `SuccessorRuntimeIdentity` / bridge行452–459 | `MISSING` | 需实际获批Windows环境的公开生成/验证证据 |
| A12 | provider runtime fingerprint SHA | formal provider/G1 runtime identity | 同上及G1 public verifier | `MISSING` | 受A15及正式provider环境阻塞 |
| A13 | exact two fold ids | contract candidate `fold_001`,`fold_002` | `_FOLD_RE`与R2C two-fold合同 | `MISSING` | 名称形状已知，但没有两份正式config证明具体fold实例 |
| A14 | 每fold config path/raw/full SHA | `configs/`下正式two-fold configs | `load_m3_config`；tracked main仅example | `MISSING` | 需框架/研究owner产生并审查正式配置；禁止复制example或retained config |
| A15 | 每fold G1 path/id/manifest SHA | public `verify_g1_release` | `m3_release.py` blob `1e02a24...`；无tracked release | `MISSING` | 需唯一当前formal release；不得读/采用LOCKED或ignored候选 |
| A16 | 两fold exact相同tool spec | `build_qlib_dump_tool_spec(config)` | `fetch_qlib_tool.py` blob `608f352...` | `MISSING` | A14缺失，故无法证明两fold spec相等 |
| A17 | exact native py312 executable | Windows Python 3.12/Qlib环境 | tracked验收仅WSL `/home/mabw/.../py312` | `MISSING` | 当前目标暂不考虑Linux；须另建或证明Windows py312/Qlib环境并由中央授权 |
| A18 | Qlib dump relative path | `data/external/qlib/v0.9.7/dump_bin.py` | blob `cb8ed72...` / SHA `b8f34c57...` / size `21847` | `AVAILABLE_VERIFIED` | 路径与tracked bytes已闭合；仍不得下载/替换 |
| A19 | dump size/SHA与双spec一致 | candidate size `21847`, SHA `b8f34c57...` | tracked file + example配置同值 | `MISSING` | 文件侧已验证，但A14/A16缺失，无法证明正式双spec closure |
| A20 | positive exact float timeout | bridge行485–491 | 类型合同已验证，无业务值SSOT | `USER_CHOICE` | 用户/中央须冻结运行窗口与timeout exact float；不得用默认/int |
| A21 | LOCKED retained隔离证明 | worktree registry中的detached locked identity，仅元数据 | R2C §5.3 | `CENTRAL_RESOURCE` | 中央在路径选择后做non-follow/containment/hardlink/reparse审计；本包不进入LOCKED树 |
| A22 | actual execution lease | unique worker/CPU/threads/cwd/PYTHONPATH/evidence/max window | R2C §5.5 | `CENTRAL_RESOURCE` | 中央串行授权；默认network禁止，首失败STOP并保留root/evidence |

## 6. 当前缺口与唯一推进顺序

当前不是“只差CPU”的状态。按依赖顺序必须先关闭：

1. `A14`：由正式配置 owner 提供两份受审查的 tracked two-fold config；不能从 example 或 retained 复制。
2. `A15`：由 G1 owner 指定一个可被 current public verifier fresh 重建的正式 release；本包不扫描真实 data/root。
3. `A17`：在 Windows-only 范围内冻结 exact native Python 3.12 + Qlib 0.9.7 环境；现有 WSL证据不能替代。
4. 在 1–3 后重建 `A11/A12/A13/A16/A19`，确认 config/G1/environment/tool spec同一身份闭包。
5. 用户/中央选择 `A20`，中央冻结 `A2/A3/A6/A7/A9/A10/A21/A22`。
6. 只有A1–A22全部为具体、fresh可验证且无冲突时，才允许另建 actual-run package，先离线preflight，再按R2C
   A→B→C 生命周期生成request、单次mkdir并运行CLI。

任一正式输入缺失时，本包最终必须写 `CONTRACT_STOP / INPUT_INVENTORY_INCOMPLETE`；不得以“source API存在”、
example config、tracked dump bytes或历史py312文档合成 `READY`。

## 7. 对抗反例与失败语义

审计 Worker 与 reviewer 至少覆盖：

1. `m3_qlib_example.toml` 的dump SHA恰与tracked tool相等，但它仍不是正式fold config；A14/A16保持MISSING。
2. WSL py312文档显示Qlib PASS，但Windows-only actual run不能采用POSIX executable path；A17保持MISSING。
3. tracked dump file存在且SHA/size正确，但没有双fold spec时A19不得升级为AVAILABLE_VERIFIED。
4. 某commit/archive或旧运行文档提到G1 release，但没有tracked release bytes与current public fresh verify；A15不得升级。
5. controlled root名称看似合理，但未获中央exact path/mkdir授权；A7保持CENTRAL_RESOURCE且目录不存在。
6. 任何候选解析到LOCKED retained、旧worktree、ignored/local config或真实data/root；立即`SCOPE_STOP`，不读取内容。
7. inventory结论需要Python/probe才能确认；标记对应字段MISSING/CENTRAL_RESOURCE，不运行命令补证。

稳定停止码：

- `SCOPE_STOP`：触及禁止输入、出现exact3外写入或需要读取LOCKED/ignored/真实root。
- `STATE_DRIFT_STOP`：HEAD/base/branch、tracked source blob/SHA或已冻结常量漂移。
- `INPUT_INVENTORY_INCOMPLETE`：正式输入或选择未闭合；这是预期的诚实终态，不是运行失败。

## 8. Worker交付与独立审查

若中央批准唯一审计 Worker：

- 只写delivery，逐项重建A1–A22，记录实际命令、source commit/blob/SHA、状态、冲突与future Gate；
- 必须保留所有MISSING/USER_CHOICE/CENTRAL_RESOURCE，不得自行解决或生成候选；
- 状态只能是 `INPUT_INVENTORY_FROZEN`、`CONTRACT_STOP / INPUT_INVENTORY_INCOMPLETE` 或精确STOP。

独立 reviewer 必须重新执行至少一个对抗盘点，优先选择“tracked dump bytes正确但正式双config缺失”或
“WSL py312已验收但Windows executable仍缺失”，并核对未读取禁止现场。reviewer不修改task/delivery。

## 9. 静态验收

零Python、零真实I/O。任务书阶段：actual只允许本taskbook、cached0、`git diff --check` PASS、UTF-8无BOM、
LF-only、trailing whitespace 0、single EOF LF。完整任务阶段按taskbook→delivery→review形成exact3，无额外路径。

本包不关闭 actual worker、真实Qlib、new controlled root、retained、M3 Gate或Linux Gate；Linux按当前用户目标不执行，
但“不执行Linux”也不能把缺失的Windows py312/Qlib身份写成已验证。
