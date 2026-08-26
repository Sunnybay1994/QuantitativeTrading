# M3-G8F-R2B Rebuilt Production Successor Bridge / CLI 任务书

状态：`R2B_BRIDGE_CLI_WINDOWS_ENGINEERING_VALIDATED`（组合 Windows 工程证据闭合；**不**表示单轮全绿洗白；actual worker / 真实 Qlib / network / new root / retained / Linux / M3 Gate 仍 **OPEN**）

## 1. 身份与目标

- task id：`M3-G8F-R2B-REBUILT-PRODUCTION-SUCCESSOR-BRIDGE-CLI`
- exact base：`9cc5b56d176a18aa468386b369d550be73051edb`
- branch：`codex/m3-g8f-r2b-production-successor-bridge-cli-rebuilt`
- worktree：`artifacts/dev_worktrees/m3-g8f-r2b-production-successor-bridge-cli-rebuilt`
- 目标：为已合流的 package-owned two-fold successor 提供唯一 production bridge 与窄 CLI，使显式 request 可在不复制 stage/fold/Gate 序列的前提下进入 `run_production_two_fold_successor`。
- 退出状态上限：`R2B_BRIDGE_CLI_WINDOWS_ENGINEERING_VALIDATED`（本文件 §14 组合证据；**不**关闭 M3 Gate）。

本包不运行 actual worker、真实 Qlib、network、新 controlled root、retained resume 或真实 M3 Gate；不得据此关闭 M3。

旧 `m3-g8f-r2b-production-successor-bridge-cli` 为 `CONTRACT_STOP` 事故现场，只读保留。其缺失的 package-owned formal/Gate wiring 已由 R2W 合流关闭；不得继承旧产物、旧验证或 placeholder。

## 2. exact9 与职责

1. `src/quant/research/m3/successor_bridge.py`（new）
2. `src/quant/research/m3/run_successor.py`（new）
3. `tests/unit/test_m3_successor_bridge.py`（new）
4. `tests/integration/test_m3_successor_bridge.py`（new）
5. `tests/unit/test_m3_run_successor.py`（new）
6. `tests/integration/test_m3_run_successor.py`（new）
7. `docs/framework/tasks/M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI任务书.md`
8. `docs/framework/deliveries/M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI交付报告.md`
9. `docs/framework/reviews/M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI独立初验报告.md`

经理唯一写 7；外部实现者只写 1–6、8；不同全新外部 reviewer 只写 9。`successor_runtime.py`、`successor_upstream_stage.py`、`successor_downstream.py`、`summary_stage.py`、orchestration/formal/Gate 模块、`__init__.py`、config、roadmap 与共享 SSOT 全部只读。

## 3. 唯一调用边界

1. bridge 只能：读取并验证 request；fresh 重建 release/config/toolchain；构造现有 `SuccessorRuntimeRequest`；调用零参数 canonical dependency factory；调用 `run_production_two_fold_successor`。
2. runtime 继续唯一拥有双 fold、upstream/formal/summary 与四 Gate 顺序。bridge/CLI 不得枚举、选择、包装或复制任何 stage/fold/Gate 序列。
3. R2P/R2S/R2A/R2W public callable 必须保持现有 `is` identity。caller/request/CLI 不得注入 handler、verifier、bundle、StageRunner factory、dependency factory 或 runtime entrypoint。
4. `public_apis` 只能省略使用 canonical bundle，或由 package-owned factory内部取得 exact canonical object；不得来自 request/caller。
5. 成功返回原生 `SuccessorRunResult`。CLI 序列化使用窄、确定、无路径泄露的结果投影，但不得丢失 terminal identity、receipt refs 或失败状态。

## 4. canonical request

新增唯一版本化 canonical JSON schema，固定 schema id `m3-successor-bridge-request-v1`。只接受 caller 显式给出的当前平台 exact concrete absolute `Path`；拒绝 subclass、PurePath、relative、symlink/reparse、非普通文件、未知/缺失字段、重复语义、非 canonical bytes及读取前后漂移。

request 至少绑定：

- `project_root` 与 `controlled_output_root`；后者必须满足现有 PROJECT-only topology，任何输入失败须在创建/写入 controlled root 前发生；
- 两个 fold 的稳定顺序、两份显式 config path、两份显式 G1 release path及各自预期 identity；
- `SuccessorRuntimeIdentity` 所需显式身份与 canonical UTC `now`；
- `SuccessorToolchainBinding` 的 exact Python executable、`DEFAULT_TARGET_PATH` dump tool、dump size/SHA、exact finite positive float timeout；
- exact bool `resume`，不得由环境、目录、wall clock 或 retained 状态推导。

PROJECT 内成员使用 PROJECT-relative canonical path；项目外 Python executable 仍须 exact concrete absolute regular file fresh验证。禁止 glob/latest/tree scan、PATH 查找、默认 `sys.executable`、env/config发现或 fallback。

## 5. release、config 与 toolchain

1. G1 release 只从 request 显式路径 fresh 重建并调用现有 public verifier；不得由 caller 提供已验证对象。
2. 两份 config 只通过现有 public parser/verifier读取；不得复制 schema、默认值或 Qlib spec。
3. toolchain 必须消费 `build_qlib_dump_tool_spec` 与 `fetch_qlib_tool.DEFAULT_TARGET_PATH`；两 fold spec exact 相同。
4. request/config/release/tool bytes、size、SHA、identity、路径或读取前后漂移统一在 worker/StageRunner/publish 前 fail closed。
5. bridge 不得 ensure/download，不得启动网络或真实 Qlib。

## 6. 错误与 CLI

- bridge 在唯一边界把输入/identity错误归一为稳定输入错误码，把 runtime/Gate错误归一为另一稳定错误族；不得 broad catch 后伪成功、重试或泄露绝对路径/配置内容。
- `run_successor.main(argv: Sequence[str] | None = None) -> int` 只接受 `--request <absolute-path>`。
- `--help` 零 request IO、零目录创建。
- 成功 stdout 仅一行 canonical JSON；失败 stderr 仅稳定脱敏码。成功 exit 0；输入错误与 runtime错误使用两个固定非零值，并在 delivery 冻结。
- CLI 不读取 env、wall clock、retained或目录内容，不包含研究、Gate或运行时业务逻辑。

## 7. 必测反例

至少覆盖：

1. request unknown/missing/duplicate/noncanonical字段，Path subclass/PurePath/relative/symlink/reparse、读取前后漂移；
2. project/controlled root nested、wrong alias/identity；失败后 controlled root仍不存在；
3. fold少/多/重复/乱序，config/release path、bytes、SHA、fold/scope/key错配，未显式引用的后置文件不得被发现；
4. wrong dump target、两 fold spec漂移、dump bytes/size/SHA漂移、Python path漂移、timeout bool/int/0/nonfinite；
5. canonical dependency factory、runtime入口或 package-owned callable 被 wrapper/lambda/monkeypatch替换时拒绝；
6. resume=false拒绝旧 terminal；resume=true仅按现有 exact identity复用；request/toolchain任一漂移拒绝旧 terminal；
7. CLI help零 IO，成功 JSON稳定，输入/runtime失败码稳定且无路径泄露；
8. fixture下完整 bridge 可达两 fold，但不 actual worker、不真实 Qlib、不 network；canonical dependency factory与production入口各 exact1调用。

reviewer 必须增加实现者未用对抗，优先挑战 canonical bytes TOCTOU、失败前零副作用、callable identity替换与 CLI 脱敏。

## 8. 实现、验证与 STOP

STATIC_ONLY 阶段禁止 Python/pytest/Ruff/mypy/cold、真实 Qlib、worker、network、new root、retained、stage/commit。实现者在 delivery 记录逐路径变化、全部 UNRUN 项，以及每个问题的“现象—根因—应遵循规则—最小复现—新增测试—通过条件”。

静态完成后由未参与实现的全新外部 reviewer 只读 1–8、唯一写 9。REVIEW_PASS 后另申请 Windows 资源，建议顺序：identity → unit exact2 bridge/CLI → integration exact2 → Ruff exact6 Python → mypy production2 → cold production2 → exact9 scope/diff/temp/process。

以下任一立即 STOP：exact9不足；需要修改 runtime/orchestration/formal/Gate/config/`__init__`；public API仍不能构造 canonical dependencies/request；base/branch/worktree漂移；第二 writer；白名单外 dirty。不得自行扩围或用 wrapper/private字段绕过。

## 9. STATIC_REWORK1：独立初验 F1–F4 与对抗闭包

首轮独立初验结论为 `REVIEW_FAIL`。批准同一原实现者在 exact9 内 STATIC_ONLY 返工；review 报告在交付前只读，完成后交回同一 reviewer 复验。不得运行 Python 或修改只读模块。

### F1 — symlink/reparse 强制反例名实一致

- 现象：测试名声称覆盖 symlink，但仅覆盖 Path subclass、PurePath、relative。
- 规则：至少对 request 叶和一个成员文件构造真实 symlink；Windows reparse/junction不可稳定创建时，可对非跟随 `lstat` 结果做最窄注入。两类均须归一为 `SUCCESSOR_BRIDGE_INPUT_INVALID`，不得跟随目标。
- 保持 production 的 leaf 与 mid-path 非跟随门禁；测试不得 patch 掉被测 guard。

### F2 — duplicate fold 必须真实构造

- 构造两个元素均为 `fold_001` 的 canonical request；必须在 factory/entry前 INPUT fail，controlled tree相对调用前零写。
- 原乱序、arity少/多、未引用 sibling 不发现反例继续保留。

### F3 — 两 fold tool spec 漂移

- 两份真实 config 仅令 dump script SHA/size或等价 spec字段不同，其余合法；`build_qlib_dump_tool_spec` 两结果不等时 INPUT fail，factory/entry调用0。
- 不得用直接 monkeypatch `specs` 列表或伪造 bridge 内部对象绕过 public config/spec构造。

### F4 — CLI 裸异常错误族

- delivery 已冻结未预期异常为 runtime族。`run_successor.main` 捕获非 `SuccessorBridgeError` 的异常时必须 stderr 单行 `SUCCESSOR_BRIDGE_RUNTIME_FAILED`、exit 3，无原异常消息/绝对路径。
- 不改已冻结的输入族 exit 2 与成功 exit 0。

### F5 — tool/config 文件 TOCTOU

- request文件已有双读+mtime闭包。dump/config等关键文件必须达到等价的“读前非跟随stat → read → 读后stat/mtime → 二次read bytes一致”或消费现有public等价fresh原语。
- 增加同inode同size内容置换/mtime漂移反例；必须 INPUT fail且runtime入口调用0。禁止扫描或重试。

### F6 — canonical callable真身不可被双侧替换

- 现有单侧 `is` 门禁保持。补“双侧同一 impostor”反例：同时替换 bridge冻结别名与runtime模块属性也必须拒绝，不能因对象彼此 `is` 相同而通过。
- canonical identity必须绑定模块import时不可由测试/caller重写的package-owned真身或现有等价不可变authority；不得靠 `__wrapped__`、名称或bool。
- exact1调用证据不能通过拆除真身门禁获得；可用不改真身的窄观察或源码合同证明。

### F7 — resume identity漂移与失败零副作用

- `resume=true` 已有terminal时，单独改变 request runtime identity（例如 code version）必须拒绝旧terminal；另保留toolchain size/SHA漂移。
- controlled root已存在但config artifact-root/identity错配时，调用前后文件集合/tree digest不变；不得写receipt、completion或temp。

### F8 — 文档与测试映射

delivery 必须纠正首轮过声明，并对 F1–F7逐项记录“现象—根因—应遵循规则—最小复现—新增测试—通过条件”。全部运行检查继续 `UNRUN`。返工后由原独立reviewer复验；无 P0/P1/P2 后才可申请 Windows验证。

## 10. STATIC_REWORK2：delivery canonical authority 描述漂移

REWORK1 reviewer确认 F1–F7 代码/测试已静态闭合；唯一 P2 为 delivery §3.4 仍描述已删除的 `_CANONICAL_FACTORY` / `_CANONICAL_ENTRY`，与当前 closure authority 实现矛盾。

批准同一原实现者仅修改 delivery：删除陈旧字段/门禁表述，逐字描述当前 import-time closure authority、双侧 impostor 拒绝与 exact1 证据的真实实现。不得修改 production/tests/taskbook/review，不得运行 Python。原 reviewer仅复核文档与当前源码一致；不得继承 REWORK1 FAIL 为通过。

## 11. STATIC_REWORK3：VALIDATION1 test-only carrier/fixture 修正

VALIDATION1 的 identity 已通过；unit exact2 为 `18 passed / 1 skipped / 2 failed`，integration、Ruff、mypy、cold、scope 均 `UNRUN`。两项首失败均发生在测试承载或夹具，不能写成 production 红灯，也不能写成整包通过。授权同一原实现者仅修改 `tests/unit/test_m3_successor_bridge.py` 与既有 delivery；production、其余 tests、taskbook、review 字节冻结，零 Python、零 stage/commit。

### F9 — 非有限 timeout 必须到达 bridge 输入边界

- 现象：测试把 `float("nan")` / `float("inf")` 交给 `_write_request`；该 helper 使用 `allow_nan=False`，在调用 bridge 前即由 canonical JSON writer 抛出 `ValueError`。
- 规则：测试不得要求 canonical serializer 生成其合同禁止的非有限 JSON。若要验证 bridge 对非有限 token 的 fail-closed，须由 test-owned raw bytes 明确写入 JSON 的 `NaN` / `Infinity` 非标准 token，或使用不会在 helper 层提前失败的等价最窄输入；断言 bridge 稳定返回 `SUCCESSOR_BRIDGE_INPUT_INVALID`、canonical factory/runtime entry 调用0、controlled root零写。
- 禁止修改 canonical serializer、允许 `allow_nan=True` 进入生产 helper、把 NaN 转成字符串、弱化 bool/int/0/负值反例或在 bridge 外把失败冒充 bridge 结果。

### F10 — dump TOCTOU 不得替换 canonical authority

- 现象：same-size dump swap 节点为计数而 monkeypatch `_require_canonical_entrypoints`，先触发 canonical entrypoint identity门禁，未到达目标文件 TOCTOU guard。
- 规则：保持所有 canonical factory/entry/package-owned callable 原对象不变；只在已批准的 test seam 上注入文件 read/stat 时序，使第一次读取后发生同 size 内容替换或 mtime漂移。断言 bridge 在 runtime entry前以 INPUT fail、controlled root零写。
- 运行入口0次只能通过不替换 canonical authority 的窄观察或既有可观测 fake canonical dependency证明；不得双侧替换、wrapper/lambda、关闭 identity guard、修改 production 增加测试后门。

delivery 必须记录 F9/F10 的现象—根因—应遵循规则—最小复现—修正测试—通过条件，并绑定 VALIDATION1 evidence root与 summary SHA；保留18绿/1skip/2失败及后续UNRUN边界。完成后交同一原独立reviewer只读复验，确认 production SHA不变、失败确实进入目标 bridge guard且零副作用。REVIEW_PASS 后申请新的完整 VALIDATION2：identity → unit exact2 → integration exact2 → Ruff exact6 → mypy production2 → cold production2 → exact9 scope/diff/temp/process；不得沿用失败轮替代重跑。

## 12. STATIC_REWORK4：非有限 request 数值稳定归入输入错误族

REWORK3 独立复验结论为 `REWORK3_REVIEW_FAIL / P1 F9′`；F10 已静态通过并冻结。中央确认不变量：raw JSON 中 `NaN` / `Infinity` / `-Infinity` 等非有限数必须在 request loader 边界稳定归为 `SUCCESSOR_BRIDGE_INPUT_INVALID`，CLI 为 exit 2，不得以裸 `ValueError` 流入 runtime 族 exit 3。

授权同一原实现者在原 exact9 内 STATIC_ONLY 最小返工，仅允许修改：

- `src/quant/research/m3/successor_bridge.py`；
- `tests/unit/test_m3_successor_bridge.py`；
- `tests/unit/test_m3_run_successor.py`（仅用于锁 CLI 输入族、exit 2 与脱敏）；
- 本任务书与既有 delivery。

其余 production、integration tests、review 字节冻结；F10 不得重写。冻结规则：

1. `_load_canonical_request_object` 对 parsed object 的 canonical re-encode若抛 `ValueError` 或等价 canonical-value错误，必须立即 `_fail_input()`；不得 broad catch runtime错误，不得改变后续异常分类。
2. 保持 `_canonical_json_bytes(..., allow_nan=False)`、duplicate key、exact canonical bytes、unknown/missing key、UTF-8与路径门禁全部不变；禁止把 `allow_nan` 放宽为 true、字符串化非有限数或修改 serializer SSOT。
3. raw `NaN`、`Infinity`、`-Infinity` 三类 direct bridge 均断言 `SuccessorBridgeError.code == SUCCESSOR_BRIDGE_INPUT_INVALID`；canonical factory/runtime entry调用0，controlled root零写。
4. CLI 至少一个 raw 非有限 request 必须稳定 stderr单行输入码、exit 2，不泄露绝对路径或原异常；不得改成功0/runtime3既有合同。
5. 本包选择在 loader 的 canonical re-encode边界直接拒绝，因此不要求这些非标准 token继续到达 `_parse_toolchain.math.isfinite`；稳定INPUT与零副作用是权威不变量。

delivery 追加 F9′ 的现象—根因—应遵循规则—最小复现—修复—新增测试—通过条件，并保留 VALIDATION1 与 REWORK3 REVIEW_FAIL 历史。完成后由同一原独立reviewer复验；只有无 P0/P1/P2 才可重新申请完整 VALIDATION2。全程零 Python/pytest/Ruff/mypy/cold/Qlib/network/worker、零 stage/commit。

## 13. STATIC_REWORK5：entrypoint authority 返回类型收窄

VALIDATION2 已取得 unit `21 passed / 1 skipped`、integration `6 passed` 与 Ruff exact6 PASS；mypy production2 的唯一首失败为 `successor_bridge.py:184: "object" not callable [operator]`，cold/scope `UNRUN`。中央确认其根因仅为 `_build_entrypoint_authority` 的返回注解过宽：真实唯一返回值是内部无参 callable。

授权同一原实现者 STATIC_ONLY 仅修改 `src/quant/research/m3/successor_bridge.py`、本任务书与既有 delivery：

1. 从 `collections.abc` 显式导入 `Callable`；
2. 将 `_build_entrypoint_authority(...) -> object` 精确收窄为 `-> Callable[[], None]`；
3. 参数仍为 `object`，函数体、closure 捕获、`is` / `__code__` / `__wrapped__` 门禁、调用位置、错误分类、canonical bytes与运行分支全部不变；
4. 禁止 `Any`、`cast`、`type: ignore`、Protocol、wrapper或向外扩散 raw callable；tests 字节冻结。

delivery 记录现象—根因—类型规则—最小复现—修复—通过条件，并绑定 VALIDATION2 evidence root与 mypy SHA；保留已绿测试/Ruff及 cold/scope UNRUN边界。完成后由同一原 reviewer只读复验，确认 production逆向diff仅有 import+返回注解。REVIEW_PASS 后只申请窄 postfix：identity → Ruff `successor_bridge.py` → mypy production2 → cold production2 → exact9 scope/diff/temp/process；不重复已绿 unit/integration/Ruff其余路径。

## 14. EVIDENCE_UPDATE：组合 Windows 工程证据（不伪造单轮全绿）

授权：原实现者 **STATIC_ONLY**、零 Python；**仅**更新本任务书与 delivery；production / tests / review **冻结只读**；零 stage/commit。下列各轮原文保留，不得洗白为首轮全绿。

| 轮次 | evidence root / 绑定 | 结果（原生；保留） |
|---|---|---|
| VALIDATION1 | （历史；fixture 返工轮） | identity **PASS**；unit exact2 `18 passed / 1 skipped / 2 failed`（NaN canonical 输入承载 + dump TOCTOU fixture）；integration / Ruff / mypy / cold / scope **UNRUN** |
| REWORK3 | test-only F9/F10 | 独立复验 → `REWORK3_REVIEW_FAIL` / P1 F9′（raw 非有限未稳定 INPUT）；F10 静态通过冻结 |
| REWORK4 | production loader `_fail_input` + 三 token / CLI exit 2 | 独立复验 → `REWORK4_REVIEW_PASS`（F9′ 闭合） |
| VALIDATION2 | `artifacts/agent_runs/m3-r2b-rebuilt-validation2-20260826T201000Z`；summary SHA `90CE3B52EA88278F32A3F4A59ED2B871C496672C3C317AEEE8F295B339FF5E8B`；mypy stdout SHA `9E3C7ACCDE7EC9DCE0EBA991FD07676A30D4BA9779C294B30663F56B345BC40A` | identity **PASS**；unit `21 passed / 1 skipped`；integration `6 passed`；Ruff exact6 **PASS**；mypy production2 **首失败** `successor_bridge.py:184: "object" not callable [operator]`；cold / scope **UNRUN** |
| REWORK5 | `Callable` import + `-> Callable[[], None]` 仅 | 独立复验 → `REWORK5_REVIEW_PASS` |
| POSTFIX VALIDATION3 | `artifacts/agent_runs/m3-r2b-rebuilt-postfix-validation3-20260826T202000Z`；summary SHA `7F9A7DA9FA3DD4E5B2E136193E4DDBDF96AC8C5F92A4B2A286A7EC571DB8C65E` | identity / Ruff `successor_bridge.py` / mypy production2 / cold production2 / exact9 scope / cached0 / diff / temp / process **全部 PASS**；`0xF00` released |

**组合口径（强制）：** 本包 Windows 工程验证以 VALIDATION2 已绿段（unit/integration/Ruff）+ REWORK5 后 POSTFIX VALIDATION3（identity/Ruff 单文件/mypy/cold/scope）组合闭合。VALIDATION1 的 `18/1/2`、VALIDATION2 的 mypy STOP、各 REWORK 复验 FAIL/PASS **全部保留为历史**，不得改写为“单轮全绿”。

**状态上限：** `R2B_BRIDGE_CLI_WINDOWS_ENGINEERING_VALIDATED`。

**仍 OPEN（不得虚称关闭）：** actual worker / 真实 Qlib / network / new controlled root / retained resume / Linux Gate / 真实 M3 Gate。
