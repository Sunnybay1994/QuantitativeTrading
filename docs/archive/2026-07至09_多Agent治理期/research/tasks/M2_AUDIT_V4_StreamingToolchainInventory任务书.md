# M2-AUDIT-V4 Streaming Toolchain Inventory 任务书

> 状态：`TASKBOOK_READY / CENTRAL_STATIC_ADMISSION_REQUIRED`
>
> task id：`M2-AUDIT-V4-STREAMING-TOOLCHAIN-INVENTORY`
>
> exact base/head：`4176d19f4c6b884952109c013c767a48ef0b1fe7`
>
> branch：`codex/m2-audit-v4-streaming-toolchain-inventory`
>
> worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-audit-v4-streaming-toolchain-inventory`
>
> 资源：`NONE`；本任务书不授权CPU、执行、parser、Python、compile、download或install

## 1. 目标、历史与结论上限

本任务只对四类、固定literal path的已安装或tracked声明做read-only静态inventory，判断是否存在一个可进入**另立的**
capability fixture包的streaming JSON候选。它不运行任何候选，不证明parser可用，不读取REAL_AUDIT3结果，也不生成生产工具。

上游fixture终态永久保留：

`STREAMING_TOOL_MISSING / CPU0 / INPUT_UNREAD / R3_ROOT_UNCHANGED`

其首失败为Codex runtime候选ancestor在原生preflight时报告ReparsePoint；中央稍后同一路径只读复核又观察到
Directory/non-reparse。该动态身份矛盾是本任务必须保留的对抗反例，不能用后一次观察撤销、覆盖或重试原fixture，也不能
把原Codex cache runtime重新加入候选集合。

本任务最高结论只允许：

- `TOOLCHAIN_INVENTORY_COMPLETE / STATIC_CANDIDATE_MATRIX_FROZEN`；或
- 若没有候选达到`STATICALLY_ELIGIBLE_PENDING_PROBE`：
  `TOOLCHAIN_INVENTORY_INCOMPLETE / USER_AUTHORIZATION_REQUIRED`。

即使存在静态eligible候选，也必须另立capability fixture任务；不得直接读取1.112GB JSON、创建large-input root或恢复原fixture。

## 2. exact3与owner

future exact3：

1. 经理：`docs/research/tasks/M2_AUDIT_V4_StreamingToolchainInventory任务书.md`；
2. 唯一read-only audit Worker：`docs/research/deliveries/M2_AUDIT_V4_StreamingToolchainInventory交付报告.md`；
3. 不同上下文独立reviewer：`docs/research/reviews/M2_AUDIT_V4_StreamingToolchainInventory独立初验报告.md`。

当前阶段经理只写taskbook exact1，不创建delivery/review。实现阶段Worker除delivery外零写；reviewer只写review。不得创建
evidence root、production tool、wrapper、fixture、cache、temp或ignored artifact；不得stage/commit，除非中央另授
SAFE_COMMIT。

## 3. 全局禁止项与审计方法

本包严格为`installed-only / read-only / no-execution / no-parser / no-Python / no-compile / no-network / no-install /
no-download`。禁止：

- 启动任一`dotnet.exe`、`pwsh.exe`、`jq.exe`、hostfxr、parser、`--version`、`--help`、capability probe或compile；
- Add-Type、csc、MSBuild、Roslyn、P/Invoke hostfxr、LoadLibrary、Assembly.Load、import或动态加载；
- PATH discovery、`Get-Command`、where、glob、递归/drive-wide/Program Files扫描、版本目录枚举或猜测替代路径；
- 读取venv、conda-meta、cache、ignored、vendor或下载目录；
- 打开、枚举、hash或stat REAL_AUDIT3 root/exact9、原fixture/large roots、`data/`、ledger、raw、clean、plan或catalog；
- 修改repo、环境、ACL、link、runtime、package、lockfile或任何外部状态。

审计只能逐项使用§4冻结的literal file paths以及它们逐component ancestor。每个允许存在的component都必须non-follow：
leaf为ordinary/non-reparse file；ancestor为real-directory/non-reparse。记录leaf exact path、path kind、reparse/symlink/junction/link
shape、size、SHA256、静态file/product/informational/assembly version、许可证与provenance；记录每级ancestor path kind和稳定身份。
同一component在审计前后复核；任一时点存在性、link shape、size、SHA、version或path kind漂移立即STOP，不用后一次观察修补
前一次。

静态single-pass/bounded-memory与ref-struct wrapper可执行性只能依据已安装官方metadata/API surface、runtimeconfig、deps、PE/
assembly metadata、host model及许可证文本。不得执行代码验证推论。存在只证明`INSTALLED`，绝不自动等于可用、可编译、可加载、
可持续低内存或capability PASS。

## 4. 唯一candidate集合与literal paths

除C1-C4外一律禁止检查、提名或推断候选。

### 4.1 C1 `DOTNET_SHARED_FRAMEWORK_STJ`

共用exact leaf：

- `C:\Program Files\dotnet\dotnet.exe`；
- `C:\Program Files\dotnet\LICENSE.txt`；
- `C:\Program Files\dotnet\ThirdPartyNotices.txt`。

C1A `.NET 6.0.11` exact resolver/config/parser：

- `C:\Program Files\dotnet\host\fxr\6.0.11\hostfxr.dll`；
- `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\6.0.11\Microsoft.NETCore.App.runtimeconfig.json`；
- `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\6.0.11\Microsoft.NETCore.App.deps.json`；
- `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\6.0.11\System.Text.Json.dll`。

C1B `.NET 8.0.0` exact resolver/config/parser：

- `C:\Program Files\dotnet\host\fxr\8.0.0\hostfxr.dll`；
- `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\8.0.0\Microsoft.NETCore.App.runtimeconfig.json`；
- `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\8.0.0\Microsoft.NETCore.App.deps.json`；
- `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\8.0.0\System.Text.Json.dll`。

以上11个leaf仅因中央literal旁证当前exists，不构成identity或capability PASS。禁止添加literal absent的
`C:\Program Files\dotnet\host\fxr\8.0.23`，禁止列举任何其他fxr/shared-framework版本。

shared framework resolution只允许静态核对冻结`hostfxr.dll`的公开export/PE metadata，以及对应exact runtimeconfig/deps中的
framework name/version/asset映射。不得调用hostfxr或dotnet，不得手拼、搜索或fallback到另一version directory。任一resolver/
config/deps/parser闭包不唯一或不自洽，则该subcandidate不能达到静态eligible。

对C1A与C1B分别核：`System.Text.Json.Utf8JsonReader`、`JsonReaderState`、`JsonReaderOptions`静态public API surface，
`Utf8JsonReader`的by-ref-like/ref-struct属性、增量span/sequence constructor、`Read/BytesConsumed/CurrentState/CurrentDepth/
TokenType/ValueSpan/ValueSequence`成员；再静态判断是否存在由独立窄wrapper承载的host model。不得把metadata presence解释成
wrapper已可编译或fixture已通过。

### 4.2 C2 `PROGRAM_FILES_POWERSHELL7_STJ`

唯一literal paths：

- `C:\Program Files\PowerShell\7\pwsh.exe`；
- `C:\Program Files\PowerShell\7\pwsh.runtimeconfig.json`；
- `C:\Program Files\PowerShell\7\pwsh.deps.json`；
- `C:\Program Files\PowerShell\7\System.Text.Json.dll`；
- `C:\Program Files\PowerShell\7\LICENSE.txt`；
- `C:\Program Files\PowerShell\7\ThirdPartyNotices.txt`。

中央literal存在性旁证当前均为false。Worker只可逐项记录`ABSENT`；若任一路径在正式审计时出现，属于时点漂移并立即STOP，
不得审计新文件、搜索其他PowerShell安装/cache路径或复用原Codex reparse候选。

### 4.3 C3 `MINIFORGE_JQ`

唯一literal path：

`D:\Miniforge3\Library\bin\jq.exe`

中央literal存在性旁证当前为false。Worker只记录`ABSENT`；若正式审计时出现则按时点漂移STOP。禁止查PATH、conda-meta、
`Scripts`、其他env或其他jq路径。

### 4.4 C4 `REPO_TRACKED_DECLARATION`

唯一允许读取的repo声明文件：

`F:\AI_Coding\QuantitativeTrading\pyproject.toml`

该文件必须tracked且来自exact base blob。只允许literal read与定向文本检索，判断是否逐字声明streaming JSON dependency/tool；
不得import、运行Python或读取环境。输出必须区分“声明存在”“installed identity”“capability”，不得从声明外推安装或可用。

exact tracked lock-file集合为空。以下名称均固定为`NO_TRACKED_LOCKFILE`：`uv.lock`、`poetry.lock`、`pdm.lock`、
`requirements.txt`、`requirements.lock`、`Pipfile.lock`、`conda-lock.yml`、`environment.yml`。只可用exact base Git tree确认这些
literal names未tracked；不得检查filesystem替代文件、搜索其他lock格式或扩展候选集合。

## 5. 每候选exact状态与证据矩阵

每个C1A、C1B、C2、C3、C4只能取以下一个状态：

1. `ABSENT`：固定literal leaf或必需closure component不存在；
2. `IDENTITY_INVALID`：存在但path kind/link shape/ancestor/version/SHA/license/provenance/runtime closure不唯一或漂移；
3. `INSTALLED_BUT_CAPABILITY_UNPROVEN`：installed identity闭合，但静态metadata不足以证明single-pass bounded-memory wrapper
   路径；
4. `STATICALLY_ELIGIBLE_PENDING_PROBE`：installed identity、official API surface、host/resolver/config/deps与许可证静态闭合，
   并存在明确窄wrapper模型，但仍未执行。

delivery矩阵exact columns：candidate、subcandidate、status、all literal paths、presence、leaf/ancestor/link shape、bytes、SHA256、
versions、license/provenance、resolver/config/deps closure、streaming API evidence、by-ref-like consequence、bounded-memory inference、
compile/load unknowns、STOP reason、next authorization。缺字段、把旁证写成PASS、使用第五类候选或跨时点修补均STOP。

`STATICALLY_ELIGIBLE_PENDING_PROBE`也只能进入另包capability fixture，不能继承原fixture授权、创建原root或读取大输入。

## 6. 反例与验收边界

至少锁以下反例：

- 同一路径一次显示reparse、稍后显示non-reparse：状态不得由后观测升级；必须记录动态identity矛盾并STOP；
- STJ DLL存在但hostfxr/runtimeconfig/deps不能唯一闭合：不得标静态eligible；
- `Utf8JsonReader` API存在但ref struct不能由PowerShell直接承载：不得声称直接调用可行，只能记录窄wrapper仍待probe；
- C2/C3固定path absent，但PATH或cache中可能另有工具：仍为ABSENT，禁止发现替代品；
- `pyproject.toml`出现`duckdb`或普通JSON能力：不等于streaming JSON declaration；无tracked lockfile不等于可现场install；
- 任一候选前后hash/path-kind漂移：保留两次证据并STOP，不取“较好”的一次。

独立reviewer不得只复述delivery，须逐候选映射literal allowlist、复核至少一个PE/assembly/runtimeconfig/deps静态推论，并加入
一个实现者未使用的对抗反例。review结论不得超过本任务状态上限。

## 7. 无静态eligible候选时的用户授权菜单

若C1A/C1B/C2/C3/C4均未达到`STATICALLY_ELIGIBLE_PENDING_PROBE`，必须以
`TOOLCHAIN_INVENTORY_INCOMPLETE / USER_AUTHORIZATION_REQUIRED`收口，并仅列出以下最小、互斥的未来选项，不自行选择：

1. 用户批准独立toolchain安装包：固定下载URL、vendor/version、license、artifact SHA、安装root、no-network-after-download、
   rollback与独立fixture；
2. 用户批准在已闭合C1 runtime上建立独立compile/toolchain包：冻结compiler authority、wrapper source、output root、temp、
   no-clobber与fixture；不得把inventory本身当compile授权；
3. 用户批准命名隔离环境中的streaming Python parser安装包：固定interpreter/env、package/version/wheel SHA/license/lockfile，
   先安装审计后capability fixture；不得修改项目默认环境。

如果某候选达到静态eligible，也只能请求针对该exact identity的独立fixture taskbook/CPU授权；不得自动执行上述菜单。

## 8. 执行与交付顺序

中央静态复核taskbook → SAFE_COMMIT → 唯一read-only audit Worker按§3-5写delivery → 不同上下文reviewer写review → 经理只读
验收 → 中央合流/归档。全程CPU NONE、Python0、parser0、compile0、R3 open0、data open0、外部状态写0。

Worker发现literal allowlist、host model、metadata字段或许可证不足时必须fail closed并在delivery记录现象—根因—规则—最小
复现—证据—通过条件；不得扩大路径或建议“先运行看看”。
