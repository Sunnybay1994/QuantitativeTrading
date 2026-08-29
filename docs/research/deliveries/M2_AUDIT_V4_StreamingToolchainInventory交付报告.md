# M2-AUDIT-V4 Streaming Toolchain Inventory 交付报告

> task id：`M2-AUDIT-V4-STREAMING-TOOLCHAIN-INVENTORY`
> worker：唯一 read-only audit Worker
> 状态：`DELIVERY_READY / STATIC_CANDIDATE_MATRIX_FROZEN`
> 审计 worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-audit-v4-streaming-toolchain-inventory`
> worktree HEAD（审计起点）：`708e759eaea38ec0c417774505738ea130d618cb`
> C4 frozen base：`4176d19f4c6b884952109c013c767a48ef0b1fe7`

## 1. 结论

在任务书冻结的 literal path 集合中，C1A 和 C1B 达到
`STATICALLY_ELIGIBLE_PENDING_PROBE`；C2、C3、C4 未达到，分别为固定路径缺失或没有声明。
因此本次 inventory 为 `TOOLCHAIN_INVENTORY_COMPLETE / STATIC_CANDIDATE_MATRIX_FROZEN`。

这不是 capability、compile、load、single-pass、bounded-memory 或 fixture PASS。C1A/C1B 只能另立独立
capability fixture taskbook，并针对各自 exact identity 申请 probe/CPU 授权；不得读取大输入、创建原 fixture
root 或恢复原 fixture 授权。

上游终态保持不变：`STREAMING_TOOL_MISSING / CPU0 / INPUT_UNREAD / R3_ROOT_UNCHANGED`。原 Codex runtime
候选的“原生 preflight 报 ReparsePoint、随后同一路径只读观察为 Directory/non-reparse”矛盾作为历史对抗反例
保留；没有用后一次观察升级、覆盖或重加该候选。

## 2. 状态矩阵

| candidate | subcandidate | status | all literal paths | presence | leaf/ancestor/link shape | bytes | SHA256 | versions | license/provenance | resolver/config/deps closure | streaming API evidence | by-ref-like consequence | bounded-memory inference | compile/load unknowns | STOP reason | next authorization |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C1 | C1A `DOTNET_SHARED_FRAMEWORK_STJ` / `.NET 6.0.11` | `STATICALLY_ELIGIBLE_PENDING_PROBE` | `C:\Program Files\dotnet\dotnet.exe`; `C:\Program Files\dotnet\LICENSE.txt`; `C:\Program Files\dotnet\ThirdPartyNotices.txt`; `C:\Program Files\dotnet\host\fxr\6.0.11\hostfxr.dll`; `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\6.0.11\Microsoft.NETCore.App.runtimeconfig.json`; `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\6.0.11\Microsoft.NETCore.App.deps.json`; `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\6.0.11\System.Text.Json.dll` | all 7 leaves exist at both observations; all required ancestors exist | all leaves `System.IO.FileInfo`, no `LinkType`/target, `Archive`; ancestors `System.IO.DirectoryInfo`, no `LinkType`/target; no path-kind/hash/size drift | `142096`; `9519`; `79954`; `374912`; `159`; `32962`; `1483944` (path order as above) | `B9EACE03C8471717E3F98873527005DBD9A92367B954F8C48484D2B7B78EFBAC`; `7F6839A61CE892B79C6549E2DC5A81FDBD240A0B260F8881216B45B7FDA8B45D`; `D5DB0ED54363E40717AE09E746DEC99AD5B09223CC1273BB870703176DD226B7`; `FCDA3326ACCCA6858AA1F624E18C8A50A43F530170D7EBC10872935709840642`; `1B7AA545D9D3216979A9EFE8D72967F6E559A9C6A22288D14444D6C5C4C15738`; `029CE3A3875A59FEE27344D07DACEA4D7CDA914C6D8FDAB67A28FBA4B2A16B8B`; `31DC23CE7F5CD043CFD4C035717BFDC4FE5D4DB4F54C4BCD797446275243BB69` | `dotnet.exe` product `8.0.0 @ Commit: 5535e31a712343a63f5d7d796cd874e563e5ac14` (file `8,0,23,53103`); `hostfxr.dll` product `6.0.11 @ Commit: 943474ca16db7c65ba6cff4a89c3ebd219dde3e5`; STJ assembly `System.Text.Json, 6.0.0.0`, file `6.0.1122.52304`, product `6.0.11+943474ca16db7c65ba6cff4a89c3ebd219dde3e5`; runtimeconfig `tfm=net6.0`; deps targets `.NETCoreApp,Version=v6.0` and `.NETCoreApp,Version=v6.0/win-x64`, runtime target library `Microsoft.NETCore.App.Runtime.win-x64/6.0.11` | root `LICENSE.txt` is Microsoft .NET Library terms; `ThirdPartyNotices.txt` identifies .NET Runtime third-party notices including Apache 2.0 ASP.NET notice; provenance is exact installed `C:\Program Files\dotnet` path only | static PE export table of exact `hostfxr.dll` contains `hostfxr_initialize_for_runtime_config`, `hostfxr_get_runtime_delegate`, `hostfxr_close`, `hostfxr_run_app`, `hostfxr_set_error_writer`; exact config/deps agree on net6.0/v6.0 and 6.0.11 runtime asset; no fallback directory used | metadata TypeDef `System.Text.Json.Utf8JsonReader` is public and has `System.Runtime.CompilerServices.IsByRefLikeAttribute`; public `Read` returns Boolean; public properties include `BytesConsumed`, `CurrentState`, `CurrentDepth`, `TokenType`, `ValueSpan`, `ValueSequence`; public constructors have signatures resolving to `ReadOnlySpan<byte>`/`ReadOnlySequence<byte>`, `Boolean`, and `JsonReaderState`; `JsonReaderOptions`/`JsonReaderState` are public metadata types | `Utf8JsonReader` is ref-struct/by-ref-like; it cannot be directly held/boxed by a PowerShell script. A separate compiled narrow wrapper is required | span/sequence constructors plus `JsonReaderState`, `Read`, and `BytesConsumed`/state members support a static incremental-design inference only; no execution proves one-pass or memory bound | no wrapper source, compiler output, load, host initialization, or runtime probe was executed; all remain unknown | no static identity failure; probe deliberately not authorized by this read-only task | independent fixture taskbook for this exact C1A identity, with compiler/wrapper/output/temp roots and CPU/probe authorization frozen separately |
| C1 | C1B `DOTNET_SHARED_FRAMEWORK_STJ` / `.NET 8.0.0` | `STATICALLY_ELIGIBLE_PENDING_PROBE` | `C:\Program Files\dotnet\dotnet.exe`; `C:\Program Files\dotnet\LICENSE.txt`; `C:\Program Files\dotnet\ThirdPartyNotices.txt`; `C:\Program Files\dotnet\host\fxr\8.0.0\hostfxr.dll`; `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\8.0.0\Microsoft.NETCore.App.runtimeconfig.json`; `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\8.0.0\Microsoft.NETCore.App.deps.json`; `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\8.0.0\System.Text.Json.dll` | all 7 leaves exist at both observations; all required ancestors exist | all leaves `System.IO.FileInfo`, no `LinkType`/target, `Archive`; ancestors `System.IO.DirectoryInfo`, no `LinkType`/target; no path-kind/hash/size drift | `142096`; `9519`; `79954`; `351008`; `53`; `28336`; `1497368` (path order as above) | `B9EACE03C8471717E3F98873527005DBD9A92367B954F8C48484D2B7B78EFBAC`; `7F6839A61CE892B79C6549E2DC5A81FDBD240A0B260F8881216B45B7FDA8B45D`; `D5DB0ED54363E40717AE09E746DEC99AD5B09223CC1273BB870703176DD226B7`; `5AA15C6119B971742A7F824609739198A3C7C499370ED8B8DF5A5942F69D9303`; `AC377253F9F7CF9D6127D684369DE36DA123D992CDC2E17950E3C8BF9688DF76`; `D23C5BDA88B2DA4D023E664B9A88404B7638D1802728DDC4E243C5B595B5E641`; `7B6BB3BE1521F4F2F4CF480BFBC1D22002408DAEBC7FCCA7D727AD86938CDFFD3` | `dotnet.exe` product `8.0.0 @ Commit: 5535e31a712343a63f5d7d796cd874e563e5ac14` (file `8,0,23,53103`); `hostfxr.dll` product `8.0.0 @ Commit: 5535e31a712343a63f5d7d796cd874e563e5ac14`; STJ assembly `System.Text.Json, 8.0.0.0`, file `8.0.23.53103`, product `8.0.0+5535e31a712343a63f5d7d796cd874e563e5ac14`; runtimeconfig `tfm=net8.0`; deps targets `.NETCoreApp,Version=v8.0` and `.NETCoreApp,Version=v8.0/win-x64`, runtime target library `Microsoft.NETCore.App.Runtime.win-x64/8.0.0` | same exact root license and third-party notice as C1A; provenance is exact installed `C:\Program Files\dotnet` path only | static PE export table of exact `hostfxr.dll` contains `hostfxr_initialize_for_runtime_config`, `hostfxr_get_runtime_delegate`, `hostfxr_close`, `hostfxr_run_app`, `hostfxr_set_error_writer`; exact config/deps agree on net8.0/v8.0 and 8.0.0 runtime asset; no fallback directory used | metadata TypeDef `System.Text.Json.Utf8JsonReader` is public and has `System.Runtime.CompilerServices.IsByRefLikeAttribute`; public `Read` returns Boolean; public properties include `BytesConsumed`, `CurrentState`, `CurrentDepth`, `TokenType`, `ValueSpan`, `ValueSequence`; public constructors have signatures resolving to `ReadOnlySpan<byte>`/`ReadOnlySequence<byte>`, `Boolean`, and `JsonReaderState`; `JsonReaderOptions`/`JsonReaderState` are public metadata types | same ref-struct consequence; direct PowerShell use is not asserted, and a compiled narrow wrapper is required | same static incremental-design inference only; no execution proves one-pass or memory bound | no wrapper source, compiler output, load, host initialization, or runtime probe was executed; all remain unknown | no static identity failure; probe deliberately not authorized by this read-only task | independent fixture taskbook for this exact C1B identity, with compiler/wrapper/output/temp roots and CPU/probe authorization frozen separately |
| C2 | `PROGRAM_FILES_POWERSHELL7_STJ` | `ABSENT` | `C:\Program Files\PowerShell\7\pwsh.exe`; `C:\Program Files\PowerShell\7\pwsh.runtimeconfig.json`; `C:\Program Files\PowerShell\7\pwsh.deps.json`; `C:\Program Files\PowerShell\7\System.Text.Json.dll`; `C:\Program Files\PowerShell\7\LICENSE.txt`; `C:\Program Files\PowerShell\7\ThirdPartyNotices.txt` | all 6 leaves absent; `C:\Program Files\PowerShell` and `C:\Program Files\PowerShell\7` ancestors absent | no leaf or ancestor identity to inspect | n/a | n/a | n/a | no installed identity; no license/provenance closure | n/a | n/a | n/a | n/a | n/a | fixed literal paths absent; no PATH/cache/other PowerShell discovery allowed | none; remains ABSENT under frozen scope |
| C3 | `MINIFORGE_JQ` | `ABSENT` | `D:\Miniforge3\Library\bin\jq.exe` | leaf absent; ancestors `D:\`, `D:\Miniforge3`, `D:\Miniforge3\Library`, `D:\Miniforge3\Library\bin` exist | existing ancestors are `System.IO.DirectoryInfo`, no `LinkType`/target; no leaf identity | n/a | n/a | n/a | no installed identity; no license/provenance closure | n/a | n/a | n/a | n/a | n/a | fixed literal leaf absent; no PATH/conda-meta/cache/other jq discovery allowed | none; remains ABSENT under frozen scope |
| C4 | `REPO_TRACKED_DECLARATION` | `ABSENT` | `F:\AI_Coding\QuantitativeTrading\pyproject.toml`; frozen lock names: `uv.lock`, `poetry.lock`, `pdm.lock`, `requirements.txt`, `requirements.lock`, `Pipfile.lock`, `conda-lock.yml`, `environment.yml` | `pyproject.toml` is tracked at frozen base blob `8f7060757e9e5ac959c25a6e0441a95d42f52164`; no listed lock name is tracked | Git blob is ordinary tracked file; no filesystem replacement/lock discovery performed | blob size not used as installed identity; no candidate binary | blob SHA above | no streaming JSON dependency/tool declaration; text includes ordinary `polars`, `pyarrow`, `duckdb`, `pandera[polars]` and `streamlit`, none is a declaration of a streaming JSON parser/tool | repository declaration only; no install/provenance inferred | no installed resolver/config/deps closure | no API evidence may be inferred from ordinary dependencies | n/a | ordinary dataframe/JSON-adjacent dependencies do not establish streaming single-pass capability | no install/import/environment inspection performed | required streaming declaration absent; no tracked lockfile, and no lockfile absence is treated as install authorization | none; remains ABSENT under frozen scope |

## 3. Static API and closure evidence

The following was obtained from the exact STJ DLL bytes through in-memory PE/ECMA-335 metadata inspection; no assembly
was loaded and no candidate was invoked.

### C1A, STJ 6.0.11

- Assembly identity: `System.Text.Json`, version `6.0.0.0`, public-key flag present.
- TypeDef rows: `#48 System.Text.Json.JsonReaderOptions`, `#49 System.Text.Json.JsonReaderState`,
  `#50 System.Text.Json.Utf8JsonReader`; all have public visibility metadata (`0x00100109`).
- `Utf8JsonReader` has `IsByRefLikeAttribute` and public `Read` signature `20-00-02` (Boolean return).
- Required public properties are present: `BytesConsumed`, `CurrentState`, `CurrentDepth`, `TokenType`, `ValueSpan`,
  `ValueSequence`.
- Constructor signature blobs resolve through the assembly TypeDef/TypeRef tables to:
  `ReadOnlySpan<byte>` + `JsonReaderState`, `ReadOnlySpan<byte>` + `Boolean` + `JsonReaderState`,
  `ReadOnlySequence<byte>` + `JsonReaderState`, and `ReadOnlySequence<byte>` + `Boolean` + `JsonReaderState`.
  The corresponding raw signatures are retained here as
  `20-02-01-15-11-1D-01-05-11-80-C0`,
  `20-03-01-15-11-1D-01-05-02-11-80-C4`,
  `20-02-01-15-11-80-C5-01-05-11-80-C0`, and
  `20-03-01-15-11-80-C5-01-05-02-11-80-C4`.

### C1B, STJ 8.0.0

- Assembly identity: `System.Text.Json`, version `8.0.0.0`, public-key flag present.
- TypeDef rows: `#53 System.Text.Json.JsonReaderOptions`, `#54 System.Text.Json.JsonReaderState`,
  `#55 System.Text.Json.Utf8JsonReader`; all have public visibility metadata (`0x00100109`).
- `Utf8JsonReader` has `IsByRefLikeAttribute` and public `Read` signature `20-00-02` (Boolean return).
- Required public properties are present: `BytesConsumed`, `CurrentState`, `CurrentDepth`, `TokenType`, `ValueSpan`,
  `ValueSequence`.
- Constructor signature blobs resolve to the same four overload shapes as C1A. The corresponding raw signatures are
  `20-02-01-15-11-09-01-05-11-80-D4`,
  `20-03-01-15-11-09-01-05-02-11-80-D8`,
  `20-02-01-15-11-80-D9-01-05-11-80-D4`, and
  `20-03-01-15-11-80-D9-01-05-02-11-80-D8`.

### Host and config closure

For both exact hostfxr DLLs, the static PE export table contains
`hostfxr_initialize_for_runtime_config`, `hostfxr_get_runtime_delegate`, `hostfxr_close`, `hostfxr_run_app`, and
`hostfxr_set_error_writer`. The exact runtimeconfig/deps pairs are internally aligned as follows:

| subcandidate | runtimeconfig | deps runtime target | deps runtime asset |
|---|---|---|---|
| C1A | `tfm=net6.0` | `.NETCoreApp,Version=v6.0/win-x64` (also portable `v6.0`) | `Microsoft.NETCore.App.Runtime.win-x64/6.0.11` |
| C1B | `tfm=net8.0` | `.NETCoreApp,Version=v8.0/win-x64` (also portable `v8.0`) | `Microsoft.NETCore.App.Runtime.win-x64/8.0.0` |

This is a static resolver/config/deps closure only. The explicit future wrapper model is a separately compiled, narrow
net6/net8 console wrapper that consumes bounded byte chunks, carries `JsonReaderState`, feeds the span/sequence
constructor, calls `Read`, and emits a small summary. Its compilation, host initialization, loading, and memory
behavior were not tested here.

## 4. Identity, timing, and adversarial controls

- Ancestor chain for C1A/C1B was checked component-by-component: `C:\`, `C:\Program Files`,
  `C:\Program Files\dotnet`, then the exact branch components `host`, `host\fxr`, `host\fxr\6.0.11` or
  `host\fxr\8.0.0`, and `shared`, `shared\Microsoft.NETCore.App`, `shared\Microsoft.NETCore.App\6.0.11` or
  `shared\Microsoft.NETCore.App\8.0.0`. Every component was `System.IO.DirectoryInfo` with `Directory` (root also
  had normal Windows `Hidden,System` attributes), empty `LinkType`/target, and no reparse indication.
- C2's exact ancestors `C:\Program Files\PowerShell` and `C:\Program Files\PowerShell\7` were absent. C3's
  exact ancestors `D:\`, `D:\Miniforge3`, `D:\Miniforge3\Library`, and `D:\Miniforge3\Library\bin` were
  present as ordinary `System.IO.DirectoryInfo` with empty `LinkType`/target; its leaf was absent.
- First and second observations used only the taskbook literal leaves and listed component ancestors. All existing C1
  leaves retained the same `FileInfo` kind, size, SHA256, and empty `LinkType`/target; all existing ancestors retained
  `DirectoryInfo` kind and empty `LinkType`/target. C2/C3 absence was unchanged.
- The first malformed recheck command produced only a PowerShell parameter-binding error before the clean second
  observation; it did not touch candidate state. The clean second observation matched the first hash/presence result.
- No `dotnet.exe`, `pwsh.exe`, `jq.exe`, hostfxr, parser, `--version`, `--help`, compiler, wrapper, import, dynamic load,
  network, install, download, PATH discovery, cache discovery, lockfile discovery, R3/data access, large-input access,
  fixture root, evidence root, temp/cache artifact, ACL/link mutation, stage, or commit was performed.
- The historical ReparsePoint/non-reparse contradiction remains a STOP-grade counterexample for the retired Codex
  runtime candidate; it is not evidence about the exact C1A/C1B files and does not authorize re-probing.

## 5. Exact scope / cached / diff

**Scope:** only C1A, C1B, C2, C3, C4 and their taskbook-listed literal paths/ancestors; C4 used only the frozen
`4176d19f...:pyproject.toml` blob and the eight exact tracked lock names. No fifth candidate or replacement path was
considered.

**Cached:** no cache, ignored directory, vendor/download directory, `conda-meta`, venv, `data/`, R3 root, original
fixture, large-input root, or generated artifact was read. No cache was created.

**Diff:** no production code, tests, configuration, environment, ACL, link, runtime, package, lockfile, or external
state changed. The only intended worktree change is this delivery report; no staging or commit was performed.

## 6. Delivery record

`DELIVERY_READY` — delivery path:
`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-audit-v4-streaming-toolchain-inventory\docs\research\deliveries\M2_AUDIT_V4_StreamingToolchainInventory交付报告.md`

The final report SHA256 and byte count must be recorded by the manager after this file is written; this worker does not
stage or commit it.
