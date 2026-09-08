# M2-AUDIT-V4 Streaming Toolchain Inventory 独立初验报告

## 结论

- `REVIEW_READY`
- 审查结论：`REVIEW_PASS`
- P0：0；P1：0；P2：0
- 结论上限：`TOOLCHAIN_INVENTORY_COMPLETE / STATIC_CANDIDATE_MATRIX_FROZEN`

本审查仅确认冻结 literal scope 内的静态 inventory 记录与状态分类。`C1A`、`C1B` 的
`STATICALLY_ELIGIBLE_PENDING_PROBE` 不表示 host 初始化、加载、编译、single-pass、bounded-memory 或
fixture 已验证；本审查未运行任一候选、parser、Python、compiler、`dotnet`、`pwsh`、`jq` 或 hostfxr。

## 审查边界与 exact3

- taskbook：
  `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-audit-v4-streaming-toolchain-inventory\docs\research\tasks\M2_AUDIT_V4_StreamingToolchainInventory任务书.md`
- delivery：
  `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-audit-v4-streaming-toolchain-inventory\docs\research\deliveries\M2_AUDIT_V4_StreamingToolchainInventory交付报告.md`
- review（本文件）：
  `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-audit-v4-streaming-toolchain-inventory\docs\research\reviews\M2_AUDIT_V4_StreamingToolchainInventory独立初验报告.md`
- exact3 仅为上述 taskbook、delivery、review；未扩大候选集合或读取 REAL_AUDIT3、data、fixture、large-input、cache、ignored、vendor 或下载目录。
- 写入本文件前，taskbook 为 `11920` bytes / SHA256
  `4FD3B96E92304495E0159D8DF9EE6C0048B928440286D158D4264665F4FF3D49`；delivery 为 `17189` bytes / SHA256
  `0E2DCE250F828A1823F319793AD22E962098ACBC5DC5EEDC055DF7DDC46A8F66`。两者在静态读取期间未漂移。
- cached：`NONE`。未读取或创建 cache、ignored artifact、temp、evidence root。
- diff：reviewer 未修改 taskbook、delivery、生产代码、测试、配置、环境或外部状态；delivery 的既有未跟踪状态属于
  audit Worker 的交付变更，不是 reviewer 越界写。reviewer 仅写入本文件，未 stage/commit。

## 独立静态复核证据

### C1B `.NET 8.0.0` literal 与祖先链

只按 taskbook literal paths 重新读取 C1B 的 7 个 leaf。当前结果与 delivery 一致：

| leaf | bytes | SHA256 |
|---|---:|---|
| `C:\Program Files\dotnet\dotnet.exe` | 142096 | `B9EACE03C8471717E3F98873527005DBD9A92367B954F8C48484D2B7B78EFBAC` |
| `C:\Program Files\dotnet\LICENSE.txt` | 9519 | `7F6839A61CE892B79C6549E2DC5A81FDBD240A0B260F8881216B45B7FDA8B45D` |
| `C:\Program Files\dotnet\ThirdPartyNotices.txt` | 79954 | `D5DB0ED54363E40717AE09E746DEC99AD5B09223CC1273BB870703176DD226B7` |
| `C:\Program Files\dotnet\host\fxr\8.0.0\hostfxr.dll` | 351008 | `5AA15C6119B971742A7F824609739198A3C7C499370ED8B8DF5A5942F69D9303` |
| `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\8.0.0\Microsoft.NETCore.App.runtimeconfig.json` | 53 | `AC377253F9F7CF9D6127D684369DE36DA123D992CDC2E17950E3C8BF9688DF76` |
| `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\8.0.0\Microsoft.NETCore.App.deps.json` | 28336 | `D23C5BDA88B2DA4D023E664B9A88404B7638D1802728DDC4E243C5B595B5E641` |
| `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\8.0.0\System.Text.Json.dll` | 1497368 | `7B6BB3BE1521F4F2F4CF480BFBC1D22002408DAEBC7FCCA7D727AD86938CDFFD3` |

The exact ancestors `C:\`, `C:\Program Files`, `C:\Program Files\dotnet`, `host`, `host\fxr`, `host\fxr\8.0.0`,
`shared`, `shared\Microsoft.NETCore.App`, and `shared\Microsoft.NETCore.App\8.0.0` were each `DirectoryInfo`,
`Directory`, with empty `LinkType` and target. No link/reparse shape was observed.

Static file version metadata independently agrees with the delivery: `dotnet.exe` and `hostfxr.dll` are Microsoft
`.NET 8.0.0`, commit `5535e31a712343a63f5d7d796cd874e563e5ac14`, file `8,0,23,53103`; `System.Text.Json.dll` is
assembly/product `8.0.0`, file `8.0.23.53103`, same commit. `LICENSE.txt` begins with Microsoft .NET Library terms;
`ThirdPartyNotices.txt` contains the ASP.NET and Apache 2.0 notices. This establishes provenance text only, not a
license review beyond the literal notices.

### C1B resolver/config/deps and STJ static API chain

The exact runtimeconfig text declares `tfm=net8.0`. Literal text in the exact deps file contains both
`.NETCoreApp,Version=v8.0` and `.NETCoreApp,Version=v8.0/win-x64`, with runtime asset
`Microsoft.NETCore.App.Runtime.win-x64/8.0.0`. Thus the delivery's net8.0/v8.0 asset alignment is independently
reproduced without invoking the resolver.

Static raw metadata inspection of the exact STJ DLL retained occurrences for `Utf8JsonReader`, `JsonReaderState`,
`JsonReaderOptions`, `IsByRefLikeAttribute`, `Read`, `BytesConsumed`, `CurrentState`, `CurrentDepth`, `TokenType`,
`ValueSpan`, `ValueSequence`, `ReadOnlySpan`, and `ReadOnlySequence`. The delivery's ECMA-335 record additionally
binds these to public TypeDef/property/signature metadata and the four span/sequence constructor shapes. The exact
hostfxr bytes retain the five required export names: `hostfxr_initialize_for_runtime_config`,
`hostfxr_get_runtime_delegate`, `hostfxr_close`, `hostfxr_run_app`, and `hostfxr_set_error_writer`.

These are static metadata observations only. In particular, a by-ref-like `Utf8JsonReader` cannot be directly held or
boxed by PowerShell; a separately compiled narrow wrapper remains necessary. The span/sequence API and carried
`JsonReaderState` justify only an incremental-design inference. They do not prove wrapper compilation, host loading,
one-pass behavior, memory bounds, or parser correctness. This supports the delivery's C1B status and does not promote it.

The delivery's corresponding C1A record is consistent with the same exact rules: `.NET 6.0.11` hostfxr, net6.0
runtimeconfig/deps and STJ `6.0.0.0` assembly metadata remain a separate pending-probe identity. No C1A fallback or
other fxr/shared-framework version was inspected.

### C2/C3/C4 and ABSENT semantics

- C2: all six exact `C:\Program Files\PowerShell\7\...` leaves independently returned absent. The ruling is
  `ABSENT`; no PATH, alternate PowerShell root, cache, or replacement path was searched.
- C3: exact `D:\Miniforge3\Library\bin\jq.exe` independently returned absent. The ruling is `ABSENT`; existing
  ancestors do not establish a tool identity and no PATH, conda metadata, environment, or alternate jq path was inspected.
- C4: exact base `4176d19f4c6b884952109c013c767a48ef0b1fe7:pyproject.toml` is present at blob
  `8f7060757e9e5ac959c25a6e0441a95d42f52164`; each of the eight frozen lock names is `NO_TRACKED_LOCKFILE`.
  Frozen text mentions `polars`, `pyarrow`, `duckdb`, `pandera[polars]`, and `streamlit`, but no declared streaming
  JSON parser/tool. The ruling is `ABSENT`. A repository declaration is not installed identity or capability evidence.

## Required historical and contamination checks

- The delivery preserves the upstream `STREAMING_TOOL_MISSING / CPU0 / INPUT_UNREAD / R3_ROOT_UNCHANGED` state.
- It preserves the retired Codex runtime contradiction: an earlier native preflight reported `ReparsePoint`, while a
  later same-path read-only observation reported `Directory`/non-reparse. The later observation was not used to upgrade,
  overwrite, retry, or re-add that candidate.
- The delivery records that the first malformed recheck stopped at PowerShell parameter binding before the clean second
  observation. No candidate status is upgraded from that malformed attempt; the clean observation is the one whose exact
  literal evidence is recorded, and the historical identity contradiction remains STOP-grade.
- The two observations recorded by the Worker retain leaf presence, kind, size, SHA256 and ancestor link shape for C1A/C1B,
  while C2/C3 remain absent. No evidence in the delivery claims that a second observation repairs a first drift.

## Per-candidate ruling

| candidate | independent ruling | review disposition |
|---|---|---|
| C1A `.NET 6.0.11` | `STATICALLY_ELIGIBLE_PENDING_PROBE` | Pass as a static candidate only; future wrapper/compile/load/memory probe requires a new taskbook and authorization. |
| C1B `.NET 8.0.0` | `STATICALLY_ELIGIBLE_PENDING_PROBE` | Pass as a static candidate only; independently checked exact identity, ancestor shape, hash, versions, notices, config/deps and static API chain. |
| C2 PowerShell 7 | `ABSENT` | Pass; fixed-literal absence, with no alternative discovery. |
| C3 Miniforge jq | `ABSENT` | Pass; fixed-literal absence, with no alternative discovery. |
| C4 tracked declaration | `ABSENT` | Pass; no frozen streaming declaration and no tracked lockfile; no install inference. |

## 独立新增静态对抗反例（非 P0/P1/P2）

- **现象：** exact leaf 在第一次与第二次静态观察之间发生短暂的 junction/reparse replacement，随后在第二次观察前
  恢复为原文件；双次 kind/hash/size 比对会观察到“稳定”，但未来 wrapper 仍可能打开了不受 pin 保护的另一对象。
- **根因：** 两个离散快照只能证明这两个时点的身份一致，不能证明整个后续打开/读取窗口没有 TOCTOU 变化。
- **应遵循规则：** capability fixture 必须在其独立输出/输入根与 wrapper 契约中冻结 no-reparse、句柄/路径身份绑定、
  读取前后 identity 复验和 drift fail-closed 语义；不能把 inventory 的双次稳定误写成持续身份保证。
- **最小复现：** 在第一次静态 hash 后，将 exact shared-framework leaf 临时替换为同大小不同内容的 reparse target，
  在第二次 hash 前恢复原 leaf；inventory 两次结果仍可能相同，而 fixture 的打开对象与预期 identity 不一致。
- **新增测试：** capability fixture 增加“打开前后 exact path kind/link shape/hash 变化即拒绝且不发布 summary”的受控
  identity-drift case；本审查不执行该 case，也不创建 probe root。
- **通过条件：** 任一时点检测到 path/link/bytes identity 变化均停止并保留两次证据；只有独立 fixture 自己完成该
  fail-closed 证明后，才能讨论 executable capability，且不能回写本 inventory 的静态状态。

该反例不降低本轮静态矩阵，因为本任务明确禁止执行和 capability probe；它只约束下一包 fixture 的授权与验收。

## 最终判定

`REVIEW_READY / REVIEW_PASS`。delivery 已逐候选覆盖冻结 literal allowlist，保留 C1A/C1B 的静态与可执行性边界，
正确处理 C2/C3 `ABSENT`、C4 declaration-vs-installed 区分、malformed recheck contamination 与 retired Codex
reparse contradiction，并未扩大 scope、读取缓存或生成执行产物。最终结论严格封顶于
`TOOLCHAIN_INVENTORY_COMPLETE / STATIC_CANDIDATE_MATRIX_FROZEN`；不得据此宣称 capability、compile、load、
single-pass、bounded-memory、真实数据或任何 Gate 已通过。

## Review artifact identity

- path：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-audit-v4-streaming-toolchain-inventory\docs\research\reviews\M2_AUDIT_V4_StreamingToolchainInventory独立初验报告.md`
- pre-identity snapshot（本节追加前）：`10793` bytes；SHA256
  `85ADF8D92748DA928ACE0FB2CFC6236A4E372D0C2B202AE9F3705D0225EC512E`
- 本节只记录审查文件的可复核前置快照；最终文件 SHA/bytes 由经理在合流前重新计算。未 stage/commit。
