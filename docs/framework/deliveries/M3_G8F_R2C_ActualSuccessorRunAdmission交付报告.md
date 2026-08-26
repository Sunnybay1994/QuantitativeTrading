# M3-G8F-R2C Actual Successor Run Admission 交付报告

日期：2026-08-26
task id：`M3-G8F-R2C-ACTUAL-SUCCESSOR-RUN-ADMISSION`
角色：implementation（Cursor Grok 4.5 High，全新会话）
exact base：`27d42840c08d883d08c9578b3c2802b4630bd0f8`
branch / worktree：`codex/m3-g8f-r2c-actual-successor-run-admission` /
`artifacts/dev_worktrees/m3-g8f-r2c-actual-successor-run-admission`
资源级别：`STATIC_ONLY`（零 Python / Qlib / worker / network / request / root / retained 读取 / stage / commit）

状态：`CONTRACT_STOP`

## 1. 结论

本任务未能冻结一份可执行、无猜测、且与权威源码同时自洽的「第一次 package-owned production successor 真跑准入合同」。

根因不是入口缺失，而是任务书 §5.2 / §6.2 对 controlled root 的**存在性与落点**要求，与已合流权威源码
`successor_bridge.py` / `successor_runtime.project_stage_root` 的 **PROJECT-only、调用时必须已是真实目录** 合同直接冲突。按任务书与派发指令，遇范围矛盾必须 STOP，不得发明第二套 mkdir/拓扑语义，也不得填写猜测路径或宣称 READY。

唯一允许写入的本交付路径已落盘；taskbook / review / production / tests / config / retained / ignored evidence 均未改动。

## 2. 权威入口与 request schema 源码定位（只读）

| 合同面 | 权威位置 | 冻结事实（不复制第二套 parser） |
|---|---|---|
| CLI 唯一入口 | `src/quant/research/m3/run_successor.py` | `python -m quant.research.m3.run_successor --request <exact-absolute-request-path>`；仅接受 `--request`；调用 `run_production_successor_bridge` |
| Bridge 唯一入口 | `src/quant/research/m3/successor_bridge.py` → `run_production_successor_bridge` | 验 request → fresh config/release/toolchain → 零参 `make_canonical_successor_production_dependencies()` → `run_production_two_fold_successor(..., public_apis=None, resume=...)` |
| Request schema id | `successor_bridge.REQUEST_SCHEMA_ID` | exact `m3-successor-bridge-request-v1` |
| 根键精确集合 | `_REQUEST_KEYS` | `schema_id`, `project_root`, `controlled_output_root`, `folds`, `runtime_identity`, `now`, `toolchain`, `resume` |
| Fold / identity / toolchain 键 | `_FOLD_KEYS` / `_RUNTIME_IDENTITY_KEYS` / `_TOOLCHAIN_KEYS` | 见源码 frozenset；未知键/缺键/重复键 fail-closed |
| Canonical JSON | `_load_canonical_request_object` / `_canonical_json_bytes` | `sort_keys=True`, `separators=(",",":")`, `ensure_ascii=True`, `allow_nan=False`；文件 bytes 必须等于 re-encode；`object_pairs_hook` 拒重复键 |
| UTC `now` | `_parse_canonical_utc` | 必须以 `Z` 结尾的微秒 canonical UTC 文本 |
| Dump tool 相对路径 | `fetch_qlib_tool.DEFAULT_TARGET_PATH` + bridge `_parse_toolchain` | exact `data/external/qlib/v0.9.7/dump_bin.py`（posix 相对）；size/SHA 与两 fold `build_qlib_dump_tool_spec` 及磁盘双读一致 |
| Canonical callable 身份 | `_require_canonical_entrypoints` + `_require_canonical_dependencies` | import-time closure 真身；拒 wrapper/`__wrapped__`；deps 槽位 `is` 绑定 package-owned upstream/downstream / `make_project_stage_runner` |
| Stage / Gate 顺序 | `successor_runtime` / `successor_upstream_stage` / `successor_downstream_stage` | bridge/CLI **不**枚举、复制或注入；由 package-owned runtime 拥有 |
| G1 fresh verify | `_fresh_verify_release` → `verify_g1_release` → `VerifiedG1Release` | 非当前 public verifier 的 exact 有效返回 → INPUT STOP |
| py312 用途证据（只读文档，非本任务 READY） | `docs/framework/agent/M3_G0_py312环境创建与兼容探针主Agent最终验收报告.md` | 环境用途与 Python 3.12 线已验收；**本任务不挑选也不宣称当前 executable READY** |

既有 R2P / R2S / R2A / R2I / R2W rebuilt / R2B rebuilt 的 task/delivery/review 仅作合流入口与 OPEN 边界旁证；本任务不重开其工程结论，也不据此关闭 M3 Gate。

## 3. CONTRACT_STOP：范围矛盾（不可由 implementation 猜测调和）

### 3.1 Controlled root 存在性

| 来源 | 要求 |
|---|---|
| 任务书 §5.2 | controlled output root「调用前不存在」；输入/身份校验失败后仍不存在；本任务不得 mkdir |
| 任务书 §6.2 反例 2 / 9 | future execution admission 前：root「已存在」必须 STOP；admission 失败后不得出现 controlled root / receipt / temp / completion / partial publication |
| 权威源码 `successor_bridge._build_runtime_request` | 注释与实现：`Controlled root must already exist and match both configs' artifact_root`；经 `_require_real_directory` 要求真实目录；bridge **永不**创建该目录 |
| 权威源码 `successor_runtime.project_stage_root` | 解析 `tracking.artifact_root` 时亦要求该目录已是 real directory |

矛盾：若按任务书字面，admission/调用前 root 不得存在；若按已合流 bridge，成功路径在进入 canonical factory/entry 前 **必须** 已存在并对齐两 fold `artifact_root`。谁在何时、以何种授权创建空目录，任务书未冻结；implementation 不得发明第二套生命周期。

### 3.2 Controlled root 落点

| 来源 | 要求 |
|---|---|
| 任务书 §5.2 | root 不得位于「旧 worktree、retained root、legacy/data root、system temp、用户 home **或项目源码树内**」；并描述为中央批准的 exact **absolute** path |
| 权威源码 | `controlled_output_root` 为 **PROJECT-relative** posix 字符串；必须落在 `project_root` 之下且 ≠ `project_root`；并与两 fold `project_stage_root` 单根相等（PROJECT-only topology，R2B 已冻结） |

矛盾：字面「不得位于项目源码树内」与 PROJECT-only（controlled 必须在 `project_root` 下）冲突。若把「源码树」窄读成 `src/` 等包路径，属对未决设计的猜测；本角色禁止猜测。

### 3.3 STOP 动作

- 不冻结可执行 admission checklist 为 `ACTUAL_SUCCESSOR_RUN_ADMISSION_CONTRACT_FROZEN`。
- 不选择、不创建、不 probe request / controlled root / G1 / config / tool / python 路径。
- 不读取 LOCKED retained（`c9f2f36cf0cd76721fe62e6a8de7566ae8dd6d79`）或其 session/产物。
- 不运行 Python / Qlib / worker / network；不 stage / commit。
- 后续仅可回经理/统筹：先修订任务书 §5.2/§6 与源码权威对齐，或显式冻结「授权 mkdir 阶段」与「源码树」精确定义后，再开新 STATIC_ONLY 准入包。

## 4. 若矛盾消除后，待未来 run package 填入的 exact identity / evidence 清单（占位，不填猜测值）

以下字段全部留空；任何具体 path / SHA / release id / executable 均属中央与未来 run package 选择，本交付 **未** 填写、**未** 宣称 READY。

| # | 证明字段 | 权威约束（摘要） | 未来填入值 |
|---|---|---|---|
| A1 | source Git SHA（调用所依据的 main/合流树） | 与入口模块一致；生成者记录 | `<UNRESOLVED>` |
| A2 | request 生成者身份 | 独立 future run package；非本任务 | `<UNRESOLVED>` |
| A3 | request resolved absolute path | exact concrete `Path`；非相对、非 subclass | `<UNRESOLVED>` |
| A4 | request canonical bytes / size / lowercase SHA-256 | 服从 bridge loader；调用前 fresh 双读逐字相等 | `<UNRESOLVED>` |
| A5 | `schema_id` | exact `m3-successor-bridge-request-v1` | （常量，非选择） |
| A6 | `project_root` absolute | real directory；无 symlink/reparse；不得解析到 LOCKED retained | `<UNRESOLVED>` |
| A7 | `controlled_output_root`（request 内相对）+ 中央批准的 resolved absolute | **待经理消除 §3 矛盾后** 才能定义「批准时不存在 / 调用时已存在」的合法时序 | `<BLOCKED_BY_CONTRACT_STOP>` |
| A8 | `resume` | 任务书要求第一次真跑 exact `false`；类型 exact bool | `false`（合同意图；未生成 request） |
| A9 | `now` | canonical UTC 微秒 `...Z` | `<UNRESOLVED>` |
| A10 | `runtime_identity.code_version` | 非空、无控制字符 | `<UNRESOLVED>` |
| A11 | `runtime_identity.dependency_fingerprint_sha256` | lowercase hex64 | `<UNRESOLVED>` |
| A12 | `runtime_identity.provider_runtime_fingerprint_sha256` | lowercase hex64 | `<UNRESOLVED>` |
| A13 | fold ids（恰好 2） | `^fold_[0-9]{3}$`；唯一；升序 canonical | `<UNRESOLVED>` |
| A14 | 每 fold：`config_path` / `config_raw_sha256` / `config_full_sha256` | `configs/` 前缀；双读稳定；fresh `load_m3_config` | `<UNRESOLVED>` |
| A15 | 每 fold：`g1_release_path` / `g1_release_id` / `g1_release_manifest_sha256` | 目录名 = release_id；`verify_g1_release` → `VerifiedG1Release` | `<UNRESOLVED>` |
| A16 | 两 fold public Qlib dump tool spec | `build_qlib_dump_tool_spec` 完全一致 | `<UNRESOLVED>` |
| A17 | `toolchain.python_executable` | 获批 py312 exact native absolute regular file；禁 `sys.executable` / PATH discovery | `<UNRESOLVED>` |
| A18 | `toolchain.qlib_dump_tool_path` | exact `DEFAULT_TARGET_PATH` 相对；成员文件双读 size/SHA | `<UNRESOLVED>` |
| A19 | `toolchain.qlib_dump_tool_size_bytes` / `sha256` | 与 spec 与磁盘一致；positive int / hex64 | `<UNRESOLVED>` |
| A20 | `toolchain.timeout_seconds` | exact finite positive `float`（非 bool/int/NaN/Inf） | `<UNRESOLVED>` |
| A21 | LOCKED retained 隔离证明 | 任何 project/controlled/G1/config/tool/receipt/resume 输入不得解析到 `c9f2f36cf0cd76721fe62e6a8de7566ae8dd6d79` 工作树/子孙/硬链/reparse/冻结 session | `<UNRESOLVED_ATTESTATION>` |
| A22 | 真实执行资源租约 | 唯一 actual worker、CPU/affinity/线程、cwd/PYTHONPATH、evidence root、stdout/stderr/exit、最长窗口、首失败 STOP；默认禁 network | `<UNRESOLVED>` |

## 5. 九类反例 → 源码 fail-closed guard（静态映射，未运行探针）

| # | 反例（任务书 §6） | 主要 guard（源码） | 失败码族（bridge/CLI） |
|---|---|---|---|
| 1 | `resume=true` 或缺失/非 bool | `_build_runtime_request`：`type(resume) is not bool` → INPUT；第一次真跑另受任务书约束必须为 `false`；runtime 在 `resume=false` 且 terminal 已存在 → `SUCCESSOR_TERMINAL_ALREADY_COMPLETE` → bridge RUNTIME | INPUT / RUNTIME |
| 2 | controlled 已存在于错误落点，或路径为 symlink/reparse | `_require_real_directory` / `_is_link_or_reparse` / PROJECT-relative 校验；**但「已存在即 STOP」与成功路径「必须已存在」冲突，见 §3.1** | INPUT（源码侧）/ **合同未冻结** |
| 3 | G1 非 public fresh verifier 有效 `VerifiedG1Release` | `_fresh_verify_release` | INPUT |
| 4 | fold 缺失/重复/乱序或两 fold tool spec 不同 | preflight fold 名排序与唯一；`_parse_toolchain` `specs[0] != specs[1]` | INPUT |
| 5 | config/tool/request 校验期 same-size bytes 替换 | `_read_stable_regular_file_bytes`；dump TOCTOU 双读；config raw 前后 SHA | INPUT |
| 6 | python/dump path、size、SHA、timeout、code version 漂移 | toolchain 解析 + `validate_successor_toolchain_binding`；runtime identity 绑定 | INPUT / RUNTIME |
| 7 | package-owned callable 被单侧或双侧 impostor 替换 | `_require_canonical_entrypoints`（closure `is` / `__code__` / `__wrapped__`）+ `_require_canonical_dependencies` | INPUT |
| 8 | request 使用 LOCKED retained 路径或 identity | 任务书 §5.3 隔离；源码通过 real-path / member 解析拒绝 link/reparse，但 **本任务未读 retained，不声称已有自动化路径前缀拒绝表** | 合同要求 STOP；实现映射不完整 |
| 9 | admission 失败后出现 root/receipt/temp/completion/partial | bridge 不 mkdir；错配已存在树零写（R2B 测合同）；**与 §3.1 时序未对齐前，不得宣布 admission 零写合同已冻结** | **合同未冻结** |

## 6. 唯一未决资源 / 用户选择（在矛盾消除之后仍开放）

1. 经理/统筹如何修订 §5.2/§6，使 controlled root **存在时序**与 bridge「必须已存在」一致，并精确定义「项目源码树」与 PROJECT-only 的关系。
2. 中央显式批准：request 生成位置、controlled root 父目录与相对名、单一 `VerifiedG1Release`、exact two-fold config、py312 executable、dump tool bytes 身份、actual worker 与资源租约。
3. 是否授权任何 network（默认禁止）；若授权须单列 endpoint/用途/次数/凭据边界。

在上述未决关闭前，禁止生成 request、禁止 CLI 真跑、禁止宣称 Qlib/M3 Gate READY。

## 7. `UNRUN` 表

| 项 | 本任务状态 |
|---|---|
| Python | `UNRUN` |
| Qlib | `UNRUN` |
| actual worker | `UNRUN` |
| network | `UNRUN` |
| request 生成 | `UNRUN` |
| controlled root 创建/probe | `UNRUN` |
| LOCKED retained 读取 | `UNRUN`（且禁止） |
| M3 Gate / 真跑结果 | `UNRUN` / `OPEN` |

## 8. 边界保持（不得虚称关闭）

actual worker、真实 Qlib、new root、retained resume、Linux 终验、M3 Gate **全部 OPEN**。

本交付唯一结论：`CONTRACT_STOP` — 准入合同因 §3 范围矛盾未冻结；后续仅允许在合同修订后再申请新的 STATIC_ONLY 准入实现包，不得直接申请真实执行资源。

---

## 9. REFREEZE（经理重冻任务书 §5.2 A/B/C 后追加；不删除上方 CONTRACT_STOP 历史）

日期：2026-08-26
派发：`REFREEZE_CONTINUE M3-G8F-R2C`
终态状态：`ACTUAL_SUCCESSOR_RUN_ADMISSION_CONTRACT_FROZEN`

上方 §1–§8 为首轮对**旧**任务书字面的正确 `CONTRACT_STOP` 历史，不得删除、不得改写为误报、不得伪装成首轮已通过。本节在经理已 `REFROZEN` 任务书之后，把旧冲突映射到修订后的三阶段生命周期，并冻结可执行准入合同。本 REFREEZE **仍**不创建 request/root，不修改 bridge/runtime/production/tests，不宣布 Qlib/M3 Gate READY。

### 9.1 旧冲突 → 修订消解

| 首轮 STOP 点（§3） | 旧任务书问题 | REFROZEN 任务书消解 |
|---|---|---|
| §3.1 存在性 | 同时要求「调用前不存在」与 bridge「必须已存在」，且未冻结谁 mkdir | §5.2 拆成 A（尚不存在）/ B（授权单步 mkdir）/ C（CLI 前必须已是 B 验真 empty real dir）；与 `successor_bridge._require_real_directory` 对齐 |
| §3.2 落点 | 「不得位于项目源码树内」被读成禁止整个 PROJECT 树，与 PROJECT-only 冲突 | 允许 `project_root` 内 Git **ignored** 运行区（如未来中央批准的 `artifacts/...`）；禁止 tracked `src/`、`tests/`、`docs/`、`configs/`，以及旧 worktree / LOCKED retained / legacy/data / system temp / 用户 home |
| request 相对 vs 中央绝对 | 旧文把 controlled 描述成绝对 path 写入语义不清 | request 字段始终 PROJECT-relative canonical posix；中央在 future run package **另行记录** resolved exact absolute；二者解析同一对象；禁止把绝对路径写入 request 字段，禁止 cwd/env/latest/glob 推导 |

### 9.2 A / B / C 生命周期（本 R2C 只冻结，不执行）

#### A. STATIC admission（本包）

- `resume` exact `false`。
- exact controlled absolute path **必须不存在**；获批 parent 已存在、native real directory、无 symlink/junction/reparse、无未知 owner/冲突 sibling。
- 只冻结路径/身份/no-clobber/资源合同；零 mkdir、零 request、零 probe、零 Qlib/worker。
- 路径可位于 `project_root` 内 ignored 运行区；不得落入 §9.1 禁止区。
- A 任一失败后：exact controlled path **仍不存在**。

#### B. future run package 单步创建（非本包）

- 仅当全部可离线 request/config/release/toolchain/path/no-clobber/LOCKED 隔离检查 PASS，且中央已明确授权 exact resolved path 与创建动作后，才允许**一次**窄 mkdir。
- 创建后立即非跟随验真：exact path = native real directory、empty、非 symlink/junction/reparse；仍位于获批 PROJECT ignored 运行区；父目录与 device/volume 相对批准值未漂移。
- mkdir 竞争、路径已存在、创建后非空或 identity 漂移 → STOP；不得 adopt / 清空 / 重命名 / 改到另一 root。
- **B 创建前**失败：root 必须仍不存在。
- **B 成功创建后**任一失败：必须**保留** exact root，进入只读调查。

#### C. CLI / bridge 调用（非本包）

- 调用 `python -m quant.research.m3.run_successor --request <exact-absolute-request-path>` 前，controlled root 必须已是 B 验真的 exact existing empty real directory（与 A「尚不存在」为不同阶段）。
- bridge 再次 fresh：PROJECT-only 闭包；request 的 canonical PROJECT-relative `controlled_output_root` 解析到中央记录的 exact absolute root；两 fold `tracking.artifact_root` 分别经现有 `project_stage_root` 解析后形成唯一 `Path`，且该 `Path` 与 controlled root 相等（`successor_bridge._build_runtime_request`：`len(set(stage_roots)) == 1` 且 `stage_roots[0] == controlled`）。**不**保证 config 原始字符串与 request 字符串三方逐字/按字符相等；本包**不**虚构第二套字符串比较器。
- bridge 自身继续 fresh 验证 request、config、release、toolchain、canonical entrypoints；不得因 B 已通过而缓存或跳过生产门禁。
- C 进入后无论 fresh guard / Qlib / stage / Gate / terminal 哪步失败：保留 exact root 及其中任何 partial evidence；carrier/CLI/经理不得自动删除、回滚或声称 root 仍不存在。

> F1 更正注记（详见 §10）：上一版本条曾误写「两 fold `artifact_root` 与 request `controlled_output_root` 逐字相同」；该过述已按 REFROZEN 任务书 §5.2 C 与现有 bridge Path 相等合同改正。历史过述不作为准入依据。

### 9.3 PROJECT-relative request + 中央绝对路径记录

| 层 | 冻结规则 |
|---|---|
| request.`controlled_output_root` | PROJECT-relative canonical posix only（服从 `successor_bridge._require_project_relative`） |
| 中央 / future run package 旁路记录 | resolved exact absolute path；与相对字段解析同一文件系统对象 |
| 禁止 | 绝对路径写入 request 该字段；cwd / env / latest / glob 推导；把 LOCKED retained 或禁止区解析进来 |

§4 占位清单中 A7 在 REFREEZE 后语义更新为：相对字段 + 中央绝对记录双槽，值仍均为 `<UNRESOLVED>`（本包不挑选真实路径）。首轮表内 `<BLOCKED_BY_CONTRACT_STOP>` 作为历史单元格保留在上方；以本小节为准解除阻塞。

### 9.4 失败保留语义（pre-create vs post-create）

| 阶段 | 失败后 root | 证据处置 |
|---|---|---|
| A（本包 static） | 必须不存在 | 零 mkdir / 零 partial |
| B 创建前（离线检查） | 必须不存在 | 不得抢先创建 |
| B 创建后（含验真失败、后续离线失败） | **保留** exact root | 只读调查；不 adopt/清空/改根 |
| C（CLI/bridge 任一失败） | **保留** exact root + partial evidence | 禁止自动删除或谎称「仍不存在」 |

### 9.5 十类反例 → guard（静态映射；相对 REFROZEN §6）

| # | 反例 | Guard / 合同锚点 |
|---|---|---|
| 1 | `resume=true` 或缺失/非 bool | bridge `type(resume) is not bool`；第一次真跑合同 exact `false`；`resume=false` + 已有 terminal → runtime `SUCCESSOR_TERMINAL_ALREADY_COMPLETE` |
| 2 | A 阶段 root 已存在，或拟议路径落入 tracked src/tests/docs/configs、retained/legacy/temp/home | A 合同：存在即 STOP；落点白名单/黑名单（任务书 §5.2 A）；bridge 另拒 symlink/reparse |
| 3 | B 结果非 empty native real dir、创建竞争、或 symlink/reparse | B 合同：单步 mkdir + 非跟随验真；竞争/已存在/非空/漂移 STOP，不 adopt |
| 4 | G1 非 public fresh `VerifiedG1Release` | `_fresh_verify_release` / `verify_g1_release` |
| 5 | fold 缺失/重复/乱序或两 fold tool spec 不同 | fold preflight；`_parse_toolchain` specs 相等 |
| 6 | config/tool/request same-size bytes 替换 | `_read_stable_regular_file_bytes`；dump TOCTOU；config 双读 |
| 7 | python/dump path、size、SHA、timeout、code version 漂移 | toolchain + `validate_successor_toolchain_binding`；runtime identity |
| 8 | package-owned callable 单侧/双侧 impostor | `_require_canonical_entrypoints` + `_require_canonical_dependencies` |
| 9 | request 使用 LOCKED retained 路径或 identity | §5.3；禁止解析到 `c9f2f36cf0cd76721fe62e6a8de7566ae8dd6d79` 工作树/子孙/硬链/reparse/冻结 session |
| 10 | C 失败后 carrier 自动删 root/partial，或声称 root 仍不存在 | §5.2 C / §9.4：失败保留；与 A「失败后不存在」不得混用 |

### 9.6 待填 identity 清单（仍不填猜测值）

沿用上方 §4 A1–A22 占位；A7 解除 `<BLOCKED_BY_CONTRACT_STOP>`，改为双槽 `<UNRESOLVED>`（request 相对 + 中央绝对）。本 REFREEZE 不新增、不挑选任何真实 path/SHA/executable/release。

### 9.7 唯一未决资源 / 用户选择（矛盾已消解后仍开放）

1. 中央批准：request 生成位置、controlled 相对名与 resolved absolute、parent、单一 `VerifiedG1Release`、exact two-fold config、py312 executable、dump tool bytes 身份。
2. 中央授权 B 的一次性 mkdir 与 C 的资源租约（唯一 actual worker、CPU/affinity/线程、cwd/PYTHONPATH、evidence root、stdout/stderr/exit、最长窗口、首失败 STOP）。
3. network 默认禁止；若未来需要须独立授权 endpoint/用途/次数/凭据边界。

### 9.8 `UNRUN` / OPEN（产品面；见 §9.9 过程违规例外）

| 项 | 状态 |
|---|---|
| Qlib | `UNRUN` |
| actual worker | `UNRUN` |
| network | `UNRUN` |
| request 生成 | `UNRUN` |
| controlled root 创建/probe（A/B/C 均未执行） | `UNRUN` |
| LOCKED retained 读取 | `UNRUN`（且禁止） |
| M3 Gate / 真跑结果 | `UNRUN` / `OPEN` |
| 产品验证用途的 Python / pytest / Ruff / mypy / cold import | `UNRUN` |

actual worker、真实 Qlib、new root、retained resume、Linux 终验、M3 Gate **全部 OPEN**。

### 9.9 过程记录更正：STATIC_ONLY Python 违规（撤回笼统「零 Python」主张）

**撤回**：上方文首「资源级别：`STATIC_ONLY`（零 Python / …）」以及 §3.3 / §7 中把本会话表述为完全未运行 Python 的**笼统主张**。该主张不准确；历史正文保留不删，以本小节为准更正。

本会话历史中确已执行 **两次** `python -c`（非产品验证、非 Qlib、非 worker）：

| # | 已知用途（exact） | 已知 cwd | 绝对解释器身份 | 执行时间戳 |
|---|---|---|---|---|
| 1 | 检查交付报告是否 CRLF、trailing whitespace、EOF LF、size，并查看 `git status` / `git diff --check` | worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2c-actual-successor-run-admission`（当时 Shell 会话 cwd） | `UNKNOWN`（既有历史未记录；本 REFREEZE **不**再探针发现） | `UNKNOWN`（既有历史未记录；不探针） |
| 2 | 将交付报告 CRLF 重写为 LF（并保持 single EOF LF、确认无 trailing WS） | 同上 worktree cwd | `UNKNOWN` | `UNKNOWN` |

声明：

- 上述两次命令**违反**本任务 `STATIC_ONLY`（任务书 §5.5：零 Python）。
- 对产品准入 / Qlib / Gate / request / root **零验证价值**；不得记入通过证据。
- 自本 REFREEZE 起：零 Python / Qlib / worker / network / root / request / stage / commit；交付正文仅用编辑器写入本文件。

### 9.10 REFREEZE 通过条件自检（implementation）

- 旧 `CONTRACT_STOP` §1–§8 完整保留。
- A/B/C、相对+绝对双记录、pre/post-create 保留语义、十类反例已映射。
- 未改 taskbook/review/production/tests；未读 retained；未生成 request/root。
- 终态：`ACTUAL_SUCCESSOR_RUN_ADMISSION_CONTRACT_FROZEN`。
- 独立 review 与三文档 UTF-8 LF / dirty exact3 / `REVIEW_PASS` 仍属后续角色；本包不代宣布 review 通过。

---

## 10. F1_REWORK（C 阶段 Path 相等合同；保留 §1–§9 全文）

派发：`F1_REWORK_CONTINUE`
终态仍为：`ACTUAL_SUCCESSOR_RUN_ADMISSION_CONTRACT_FROZEN`

§1–§8 `CONTRACT_STOP`、§9 REFREEZE（含 §9.9 Python 违规记录）全文保留。本节省短更正 §9.2 C 及任何「三方字符串逐字相等」过述。

### 10.1 现象与根因

- 现象：§9.2 C 曾写两 fold `tracking.artifact_root` 与 request `controlled_output_root`「逐字相同并解析到中央 exact absolute」。
- 根因：把中央旁路「request 相对 → 中央绝对」同一对象要求，错误扩展成 config 原始 `artifact_root` 字符串与 request 相对字符串的三方 byte/character 相等；超出现有 bridge 合同。
- 权威：REFROZEN 任务书 §5.2 C；`successor_bridge._build_runtime_request` 经 `project_stage_root` 收集 `stage_roots`，要求唯一 `Path` 且 `== controlled`。

### 10.2 冻结的 C 阶段路径合同（无第二套比较器）

bridge **保证**：

1. request 内 canonical PROJECT-relative `controlled_output_root` 解析到中央记录的 exact absolute controlled root（同一对象；绝对路径不写入 request 字段）。
2. 两个 config 的 `artifact_root` 各自经现有 `project_stage_root(project_root, config)` 解析后，形成唯一 `Path`，且该 `Path` 与 controlled root 相等。

bridge **不保证**、本包 **不发明**：

- config 原始 `artifact_root` 字符串与 request `controlled_output_root` 字符串三方逐字/按字符相等；
- 任何第二套字符串比较器、额外 normalize、或平行于 `project_stage_root` 的自研相等谓词。

§9.2 C 正文已按上表就地改正；§9.3（相对字段 + 中央绝对旁路记录）不涉及三方 config 字符串相等，无需改写。§9.5 反例与 Path/`_require_real_directory` 映射仍然有效。

### 10.3 范围确认

- 只写本 delivery；未改 taskbook / review / production / tests。
- 未运行 Python / Qlib / network；未创建 root / request；未 stage / commit。
- 产品面 `UNRUN` / Gate `OPEN` 不变；§9.9 过程违规记录不变。
