# M3-G8F-R2D Actual Successor Run Input Inventory 独立初验报告

日期：2026-08-28
task id：`M3-G8F-R2D-ACTUAL-SUCCESSOR-RUN-INPUT-INVENTORY`
角色：未参与 manager/taskbook 与 Worker/delivery 的唯一独立 reviewer
资源级别：`STATIC_ONLY / CPU NONE`

- exact base / HEAD：`f448f9e7501edd4f2299aff3b2b9eaabd8af0da7`
- branch：`codex/m3-g8f-r2d-actual-successor-run-input-inventory`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2d-actual-successor-run-input-inventory`
- 唯一写入：`docs/framework/reviews/M3_G8F_R2D_ActualSuccessorRunInputInventory独立初验报告.md`
- 独立初验结论：`REVIEW_PASS`
- inventory 上限：`INPUT_INVENTORY_FROZEN`
- actual-run 准入终态：`CONTRACT_STOP / INPUT_INVENTORY_INCOMPLETE`

## 1. Answer-first 结论

Worker 交付对 A1–A22 的状态重建与任务书、exact HEAD tracked Git 对象及 package-owned source 一致。独立复核
没有发现把 source API、example config、tracked dump bytes 或 WSL py312 历史证据错误提升为正式运行输入的情况。

正式 two-fold config、正式 G1 release bytes/manifest、Windows native Python 3.12 + Qlib 0.9.7 executable 均没有
获批 tracked 证据。因此 `A14/A15/A17` 必须保持 `MISSING`，其依赖 `A11/A12/A13/A16/A19` 也必须保持
`MISSING`。`A20` 保持 `USER_CHOICE`；未来 request/root/path/time/code version/LOCKED 隔离/执行租约保持
`CENTRAL_RESOURCE`。

本 `REVIEW_PASS` 只确认 inventory 诚实、状态分类正确、停止边界完整；不构成 `READY`，不批准 request、controlled
root、evidence、Qlib/worker 执行，也不关闭 actual successor、retained、M3 Gate 或 Linux Gate。

## 2. 冻结身份与 exact scope

| 核对项 | 独立结果 |
|---|---|
| HEAD | `f448f9e7501edd4f2299aff3b2b9eaabd8af0da7`，与冻结值逐字一致 |
| branch | `codex/m3-g8f-r2d-actual-successor-run-input-inventory`，与冻结值逐字一致 |
| taskbook SHA-256 | `c6ff6f2f1780c4c54334a1988dc5d984cb74574e330c4350a7420050ad38d0a8`，与中央复核值一致 |
| delivery SHA-256 | `12ca1bae14e016c8319d1c4c72e25d6b82e73406ec5937638cfbb411a9936bc3` |
| cached | `0` |
| review 写入前 actual scope | 仅 taskbook、delivery 两个批准的 untracked 文件 |
| review 写入后目标 scope | taskbook、delivery、review exact3；不得出现第四路径 |

任务书列出的 10 个 tracked anchor 与 R2C task/delivery/review 均由 `git ls-files` 命中。独立取得的 Git blob、
working SHA-256 与 bytes 全部逐项匹配 delivery §2.2；其中 dump tool 为 blob
`cb8ed72dabbbd990edb7c5ec14d34356124b7580`、SHA-256
`b8f34c57ce1ef4b1772f3909735e66058f21b25bd7ab8a5f16318822401fe53f`、`21847` bytes。

## 3. A1–A22 独立重建

`AVAILABLE_VERIFIED` 仅表示 tracked 常量或源码锚点已验证，不表示完整 request 可运行。

| ID | 独立状态 | 独立证据与边界 |
|---|---|---|
| A1 | `AVAILABLE_VERIFIED` | HEAD/source identity 与冻结 commit 一致；未来 actual-run 仍须由中央重冻届时 clean main。 |
| A2 | `CENTRAL_RESOURCE` | 当前没有获批 request 生成者/runner 租约；只能由中央分配。 |
| A3 | `CENTRAL_RESOURCE` | CLI 接受 exact request path，但当前不得命名或创建 future ignored no-clobber path。 |
| A4 | `MISSING` | `_load_canonical_request_object` / `_canonical_json_bytes` 合同存在，但 A2/A3 与字段未闭合，故无合法 canonical bytes/size/SHA。 |
| A5 | `AVAILABLE_VERIFIED` | `REQUEST_SCHEMA_ID` exact `m3-successor-bridge-request-v1`。 |
| A6 | `CENTRAL_RESOURCE` | `_parse_absolute_path_text` + `_require_real_directory` 可验证类型/路径合同；future project root 尚未由中央批准。 |
| A7 | `CENTRAL_RESOURCE` | R2C A→B→C 生命周期要求中央批准 relative/name/resolved absolute 与单次 mkdir；当前未创建或 probe。 |
| A8 | `AVAILABLE_VERIFIED` | 第一次真跑合同固定 exact bool `false`；源码拒绝非 bool，但当前未生成 request。 |
| A9 | `CENTRAL_RESOURCE` | `_parse_canonical_utc` 仅冻结格式；execution-time UTC 微秒 `Z` 由 future runner 在授权窗口生成。 |
| A10 | `CENTRAL_RESOURCE` | `_parse_runtime_identity` 只验证非空无控制字符；exact `code_version` 语义值仍由中央冻结。 |
| A11 | `MISSING` | 只有 dependency fingerprint hex64 字段合同，没有获批 Windows runtime fingerprint 证据；受 A17 阻塞。 |
| A12 | `MISSING` | 只有 provider runtime fingerprint 合同；正式 provider/G1 identity 缺失，受 A15/A17 阻塞。 |
| A13 | `MISSING` | `_FOLD_RE`、排序/唯一/恰好 two-fold 合同可定位，但没有两份正式 config 证明具体 fold 实例。 |
| A14 | `MISSING` | tracked `configs/research/m3*.toml` 只返回 `m3_qlib_example.toml`；example 不得升级为正式 two-fold config。 |
| A15 | `MISSING` | package-owned `verify_g1_release` 存在，但批准的 tracked release/manifest 查询为空；没有 current formal release bytes 可 fresh verify。 |
| A16 | `MISSING` | bridge 从两份 fold config 调用 `build_qlib_dump_tool_spec`，并要求 `len(specs)==2` 且 `specs[0]==specs[1]`；A14 缺失，无法构造正式双 spec。 |
| A17 | `MISSING` | tracked py312 文档仅证明 WSL `/home/mabw/miniforge3/envs/py312`、Python 3.12.13、pyqlib 0.9.7/manylinux；不是 Windows native executable。 |
| A18 | `AVAILABLE_VERIFIED` | tracked relative path、blob、SHA-256、`21847` bytes 全部闭合；未执行/下载/替换 dump tool。 |
| A19 | `MISSING` | A18 只证明文件侧；A14/A16 未闭合，无法证明该 size/SHA 与正式两个 tool specs 一致。 |
| A20 | `USER_CHOICE` | bridge/runtime 仅要求 exact positive finite `float`；tracked SSOT 没有业务 timeout 值，须由用户/中央冻结。 |
| A21 | `CENTRAL_RESOURCE` | LOCKED retained 隔离须在 future path 冻结后由中央做 non-follow/containment/hardlink/reparse 元数据审计；本审查未进入 LOCKED tree。 |
| A22 | `CENTRAL_RESOURCE` | unique worker、CPU/threads/cwd/PYTHONPATH/evidence/max window 尚无中央串行租约。 |

状态计数：`AVAILABLE_VERIFIED=4`（A1/A5/A8/A18），`MISSING=9`
（A4/A11/A12/A13/A14/A15/A16/A17/A19），`USER_CHOICE=1`（A20），`CENTRAL_RESOURCE=8`
（A2/A3/A6/A7/A9/A10/A21/A22）；合计 22 项，与 taskbook/delivery 一致。

## 4. 指定对抗验证

### 4.1 tracked dump 正确仍不能关闭 A16/A19

独立命令确认：

1. `data/external/qlib/v0.9.7/dump_bin.py` 为 tracked blob
   `cb8ed72dabbbd990edb7c5ec14d34356124b7580`，SHA-256 为
   `b8f34c57ce1ef4b1772f3909735e66058f21b25bd7ab8a5f16318822401fe53f`，size 为 `21847`。
2. tracked M3 config 只有 `configs/research/m3_qlib_example.toml`；其 example 字段恰写相同 SHA/bytes，但文件名与
   任务书均明确它只是 example。
3. `successor_bridge._parse_toolchain` 从正式 `fold_configs` 逐一调用 `build_qlib_dump_tool_spec`，随后要求恰有两个
   spec 且二者完全相等。没有正式 two-fold config 时，不存在可供该闭包验证的两个正式 spec。

因此仅 A18 可为 `AVAILABLE_VERIFIED`；A14/A16/A19 必须保持 `MISSING`。把 example 的相同 SHA/bytes 用作
正式配置证据会违反 taskbook 的禁止推断条款。

### 4.2 WSL py312 验收不能替代 Windows native executable

tracked 验收文档明确环境位于 `/home/mabw/miniforge3/envs/py312`，记录 Python 3.12.13、pyqlib 0.9.7 与
cp312 manylinux wheel。该证据只覆盖 WSL/POSIX 环境。`successor_bridge._parse_toolchain` 会接收并校验一个 absolute
`python_executable`，但源码不会替中央选择 Windows executable，也不会把 POSIX path 转换成 Windows native identity。

本 inventory 没有获批的 Windows native executable path、其 bytes/环境依赖指纹或 Qlib 身份证据。因此 A17 仍为
`MISSING`，并继续阻塞 A11/A12 及完整 runtime closure。“暂不执行 Linux”不等于 Windows 环境已验证。

## 5. 其他反例与 future Gate

| 反例 | 审查裁定 |
|---|---|
| 旧文档/commit 提到 G1 | public verifier API 不能替代 current formal tracked release bytes/manifest；A15 不升级。 |
| `fold_001/fold_002` 符合 regex | 名称形状不能替代两份正式 config 身份；A13/A14 不升级。 |
| controlled root 名称看似合理 | 未经中央 exact relative/resolved absolute 与单次 mkdir 授权，A7 保持 `CENTRAL_RESOURCE`。 |
| source schema 与 CLI 均存在 | 只能证明解析入口；不能合成 A2–A4、A6–A7、A9–A22 的具体运行输入。 |
| 需 Python/Qlib/probe 才能补证 | 本包保持对应 `MISSING`/`CENTRAL_RESOURCE`，不得越权运行。 |

合法推进仍须依序关闭：正式 two-fold config（A14）→ current formal G1 release（A15）→ Windows native py312/Qlib
identity（A17）→ 重建 A11/A12/A13/A16/A19 → 冻结 A20 与所有中央资源项。未全部闭合前不得创建 actual-run package
中的 request/root/evidence，更不得运行 successor。

## 6. 禁止现场与审查卫生

本 reviewer 仅使用 taskbook 允许的 tracked-only 只读命令：`git ls-files/rev-parse/hash-object/diff/status`、`rg`、
`Get-Content/Get-Item/Get-FileHash`。本 reviewer：

- 未运行 Python、pytest、Ruff、mypy、cold import、Qlib、worker、network 或 browser；
- 未创建或读取 candidate request、controlled root、evidence、config、release、runtime/temp 文件；
- 未读取 ignored/local config、真实 data/root、secret 或外部环境；
- 未进入、扫描、hash 或读取 detached LOCKED `c9f2f36cf0cd76721fe62e6a8de7566ae8dd6d79` tree；
- 未修改 taskbook、delivery、production、tests、config、roadmap、governance/UA/Gate SSOT；
- 未 stage、commit、merge、cleanup 或退休任何 branch/worktree/evidence。

对 Worker 的禁止现场核对依据为：delivery 列出的实际命令族均在批准只读集合内，delivery 自报禁止项均为
`UNRUN/未读取/未创建`，且当前 Git actual scope 只有批准的 taskbook/delivery（写入本报告后应为 exact3）。由于本包
明确禁止扫描 ignored/真实/LOCKED 现场，本审查不以越界读取来反向“证明不存在”；Git scope 只能证明没有额外
tracked/untracked 写入，不能伪造进程历史证明。

## 7. 审查终态

结论：`REVIEW_PASS`。

通过对象仅为 A1–A22 tracked-only inventory 与 STOP 边界。正式输入仍不完整，必须保留：

`INPUT_INVENTORY_FROZEN / CONTRACT_STOP / INPUT_INVENTORY_INCOMPLETE`

不得写 `READY`，不得据此关闭 actual worker、真实 Qlib、new controlled root、retained、M3 Gate 或 Linux Gate。
