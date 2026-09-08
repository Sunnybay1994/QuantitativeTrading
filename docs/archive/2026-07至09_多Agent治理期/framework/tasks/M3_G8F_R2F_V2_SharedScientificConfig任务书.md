# M3-G8F-R2F-V2 Shared Scientific Config 任务书

## 1. 身份与状态

- task id：`M3-G8F-R2F-V2-SHARED-SCIENTIFIC-CONFIG`
- exact base/head：`fbf783ef40d9a73136ff1979409c4d369580c220`
- branch：`codex/m3-g8f-r2f-v2-shared-scientific-config`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2f-v2-shared-scientific-config`
- resource：`STATIC_ONLY / CPU NONE`；任何Python/pytest/Ruff/mypy/cold另行申请
- 当前状态：`R2F_V2_WINDOWS_ENGINEERING_VALIDATED / EVIDENCE_UPDATE_READY`
- 退出状态上限：`SHARED_SCIENTIFIC_CONFIG_CONTRACT_VALIDATED`

本包只修复successor runtime把两条fold错误绑定为“两份raw/full config必须互异”的身份填充合同，并同时补齐两个G1 release
identity必须互异的现有门禁缺口。它不创建formal config、request、root或release，不运行actual successor/Qlib，不关闭A14/A15/A17、
retained、M3 Gate或Linux Gate。

## 2. exact6与职责

| # | 路径 | owner / 写权限 |
|---|---|---|
| 1 | `src/quant/research/m3/successor_runtime.py` | 唯一实现者 |
| 2 | `tests/unit/test_m3_successor_runtime.py` | 唯一实现者 |
| 3 | `tests/integration/test_m3_successor_runtime.py` | 唯一实现者 |
| 4 | `docs/framework/tasks/M3_G8F_R2F_V2_SharedScientificConfig任务书.md` | 框架经理，Worker只读 |
| 5 | `docs/framework/deliveries/M3_G8F_R2F_V2_SharedScientificConfig交付报告.md` | 唯一实现者 |
| 6 | `docs/framework/reviews/M3_G8F_R2F_V2_SharedScientificConfig独立初验报告.md` | 不同独立reviewer |

实现与review必须使用不同隔离上下文。同一任务只允许一个实现者；不得创建第二writer或第二worktree。`successor_bridge.py`、config schema、
G1 API、terminal schema、orchestration、upstream/downstream stage、CLI、roadmap与governance全部只读。任何白名单不足必须写delivery并STOP。

## 3. 现象、根因与架构裁定

### 3.1 现象

已合流R2F/R2F-V1证明：

1. `successor_bridge`已把fold identity冻结为request-side exact two、stable-sorted、distinct `fold_[0-9]{3}`，并逐fold绑定
   `config_path/raw/full SHA`及G1 release identity；config schema本身没有fold字段。
2. `successor_runtime._validate_request`对每个fold已fresh读取request-bound config path，校验raw bytes SHA、full/raw identity与
   `load_m3_config`结果，并要求两个fold的scientific identity exact相同。
3. 该函数随后仍要求raw identity set与full identity set的size均为2，迫使owner为两个fold制造非科学差异。
4. R2F-V1的148/148字段审计只找到三个有条件候选：G1 request rate、retry attempts、retry backoff。它们只有在两条真实G1 lane
   存在不同配额、失败预算或退避政策且有对应release policy证据时才业务正当。当前没有这组事实；任意选择两个数只是identity padding。
5. 同一函数把两个release identity放入list后只检查长度2；两条完全相同的`(release_id, manifest_sha256)`仍可越过该门禁。

### 3.2 被破坏的不变量

- fold/lane身份应来自request-side fold、config binding、release binding与执行闭包，不应通过篡改科学无关字段制造。
- 同一经济/scientific config用于两个fold时不应被拒绝；每fold仍必须独立fresh验证其显式输入。
- two-fold必须消费两个不同的G1 release identity；list长度不能替代distinct closure。
- fail-closed必须针对真实身份漂移，而不是要求没有业务含义的hash差异。

### 3.3 中央架构裁定

`ARCHITECTURE_APPROVED`：删除raw/full config identities必须互异的人工门禁；保留每fold全部fresh校验与scientific exact1；把G1 release
identity强化为exact2且distinct。这是一个行为合同变更：共享config由拒绝改为允许，重复release由历史可穿透改为拒绝。不得写成“行为完全不变”。

## 4. production冻结合同

### 4.1 每fold config fresh closure保持

`_validate_request`遍历每个`SuccessorFoldRequest`时必须继续逐项证明：

1. `item.config.relative_path`经project root定位到request-bound exact file；不得glob/latest/scan/fallback。
2. `_read_regular_file`fresh读取ordinary/non-reparse受控文件；raw bytes SHA exact等于loaded config的`raw_config_sha256`。
3. raw/full/scientific identity保持canonical lowercase 64-hex既有检查。
4. `load_m3_config(raw_path)`的fresh对象必须exact等于request中已绑定`LoadedM3Config`。
5. config的canonical G8 stage root、tool spec及后续fold execution/terminal config fields继续按既有公开合同闭合。

不得因允许共享config而缓存一次读取结果、跳过第二fold fresh read、信任对象identity/bool或只比较path。两个fold即使引用同一physical file，仍须分别完成
当前循环的fresh read/load/compare；任一fold期间发生bytes/path/config drift都必须`SUCCESSOR_INPUT_INVALID`。

### 4.2 raw/full distinct门禁删除

删除仅用于下述集合size判断的`config_identities`、`full_config_identities`收集与：

```python
if len(config_identities) != 2 or len(full_config_identities) != 2:
    raise ValueError
```

同时删除或改正“Full/raw config identities remain distinct per lane”误导注释。不得替换为`size in {1,2}`之类仍暗示集合是权威的冗余门禁；
每fold逐项fresh closure已经是权威。允许：

- 两fold引用同一canonical config path与same bytes/object value；
- 两fold引用不同canonical paths，但文件bytes、raw/full/scientific identity及loaded config value exact相同；
- future确有业务证据时，两fold使用raw/full不同但scientific相同的合法config。

本包不生成或鼓励重复config文件，也不选择任何scientific/non-scientific字段值。

### 4.3 scientific identity exact1保持

`scientific_identities`必须继续只接受exact一个identity。日期/window、minimum train sessions、全部walk-forward、model/provider/scientific字段任一
fold漂移仍拒绝。不得把“允许共享config”错误实现为允许两个scientific identities，亦不得对scientific payload做cast/normalization绕过。

### 4.4 G1 release exact2/distinct强化

每fold继续调用public `verify_g1_release` fresh验证，并闭合release root、manifest release id与request-bound verified object。两个fold收集到的
canonical identity为：

```text
(manifest.release_id, manifest_sha256)
```

最终必须同时满足list arity exact2与`set` cardinality exact2。相同对象、不同wrapper、不同path alias但相同tuple、相同release id/manifest SHA
均拒绝。不得仅按object identity、path或list length判断；不得放宽G1 verifier。

### 4.5 two-fold与terminal身份保持

现有two-fold identity继续绑定stable fold order、每fold config relative path/raw/full SHA、G1 release id/manifest SHA、toolchain/runtime identity。
共享config不能合并fold execution、receipt ownership、work/gate scope或cache consumption：

- fold仍exact2、distinct、stable-sorted；
- 每fold execution的`fold`与G1 release identity必须不同且与request item exact对应；
- work/gate identity继续包含fold，不得跨fold复用非shared node；
- terminal/replay schema与bytes不变；same request exact replay可复用，任一fold/release/path/bytes漂移拒绝。

本包不得修改two-fold identity version、terminal schema、receipt schema、stage顺序或Gate顺序。

## 5. 失败语义

所有本包新增或保留的request/config/release闭包失败继续稳定归一为`SUCCESSOR_INPUT_INVALID`，且必须发生在controlled root、stage、worker、terminal
写入前。禁止新增错误码、泄露path/native detail或把duplicate release包装成stage failure。

若实现发现相同config无法在不改public schema/bridge/config/terminal的情况下闭合，必须`CONTRACT_STOP / SHARED_CONFIG_ARCHITECTURE_MISMATCH`并给出
精确源码证据，不得恢复hash padding或扩大白名单。

## 6. 必须覆盖的反例与正向

### 6.1 unit

1. 两fold引用同一exact config input/path/raw/full/scientific value，request validation正向；fresh loader必须被逐fold调用exact两次。
2. 两个不同config paths含exact相同bytes并加载为equal config value，正向；不得扫描第三文件。
3. raw SHA、full SHA、fresh bytes或loaded config任一fold漂移，逐项拒绝。
4. scientific identity不同，即使raw/full各自合法也拒绝。
5. 两fold使用相同`(release_id, manifest_sha256)`，包括不同wrapper/object或path alias，均拒绝；controlled write count=0。
6. 两个distinct release identities正向保持；verify必须逐foldfresh调用。
7. duplicate/unsorted fold、wrong config relative path及tool spec/root drift的既有反例不得削弱。

### 6.2 integration

1. 以现有`_request` fixture的最小参数化/窄helper构造same-config双fold，完整two-fold runtime执行通过；两个fold execution仍distinct。
2. same-config下experiment/work/gates及terminal identity按fold/release闭合，不发生cross-fold cache/receipt alias。
3. exact replay返回同terminal且无第二经济/physical publication影响；第二fold前config bytes tamper仍fresh拒绝。
4. same-config + duplicate release在任何stage handler/public runner调用前拒绝。
5. 保持现有different raw/full + same scientific正向，证明本包不是强制config必须相同。

不得为测试修改bridge、生产verifier或创建test-only public hook；允许既有monkeypatch seam，但必须记录真实调用次数与零controlled-write断言。

## 7. STATIC实现与独立review

中央准入后，一个唯一非Spark Luna隔离实现者只写1–3与delivery，完整读取本任务书；STATIC_ONLY阶段禁止Python/pytest/Ruff/mypy/cold、真实data/Qlib、
root/request/release/evidence、stage/commit。实现者先记录IN_PROGRESS，完成后delivery写DELIVERY_READY或精确STOP。

不同独立reviewer只读production/tests/task/delivery且唯一写review。review至少补一个实现者未使用对抗，优先挑战：

- different wrapper/path但same release tuple是否仍被拒绝；
- same physical config第二fold是否真的fresh reload，而非第一个fold结果缓存；
- terminal identity是否仍含两个fold及两个distinct releases。

review输出`STATIC_REVIEW_PASS/FAIL`，不得把静态PASS写成Windows运行通过。

## 8. 后续Windows验证申请

只有review PASS后另申请CPU8–11/0xF00唯一租约。建议顺序：

1. identity：`quant`与`successor_runtime`来自exact worktree；
2. focused `tests/unit/test_m3_successor_runtime.py`；
3. focused `tests/integration/test_m3_successor_runtime.py`；
4. Ruff exact production1 + tests2；
5. mypy `src/quant/research/m3/successor_runtime.py`；
6. cold import exact production；
7. exact6 scope/cached0/diff/temp/cache/process residue。

使用`D:\Miniforge3\python.exe`、exact cwd/PYTHONPATH、BelowNormal/0xF00、threads<=2、fresh basetemp与no-clobber evidence；每阶段
stdout/stderr/exit，首失败STOP、不重试扩围。禁止actual successor/Qlib/network/new root/retained/acceptance真实运行。

## 9. 交付报告必填

delivery按“现象—根因—应遵循规则—最小复现—新增测试—通过条件”记录：

- R2F/R2F-V1为何不能用三个条件字段随意制造hash；
- 删除的exact raw/full distinct门禁与保留的per-fold fresh closure；
- duplicate release历史缺口与新增exact2/distinct规则；
- production/test实际diff及STATIC/UNRUN边界；
- review与后续Windows evidence的路径/SHA；
- 剩余A14 scientific config values、controlled root、A15、A17与真实运行边界。

禁止声明formal config ready、A14/A15/A17关闭、actual successor/Qlib/new root/retained/M3 Gate完成。

## 10. STATIC_REVIEW_FAIL与STATIC_REWORK1冻结

同一独立reviewer完成STATIC_ONLY初验，结论：

`STATIC_REVIEW_FAIL / P1-F1 + P1-F2`

review确认production最小方向正确：raw/full artificial-distinct门禁已删除，scientific exact1、每fold fresh closure及release tuple
exact2/distinct均保持；本轮不得修改production。两项阻断均为任务书原定强制测试证据未闭合。

### 10.1 P1-F1：same physical config fresh exact2

现有新增测试仍把两个fold绑定到`configs/fold_001.toml`与`configs/fold_002.toml`两个physical files，只能证明每个路径读取一次，不能证明
同一physical file在第二fold仍fresh read/load。

返工必须补：

1. 两个stable-sorted fold requests的`SuccessorConfigInput.relative_path`均exact绑定同一
   `PurePosixPath("configs/shared.toml")`，request-bound config value相等，G1 releases distinct。
2. unit正向记录同一resolved path的`load_m3_config`调用序列exact `[shared, shared]`，计数exact2；同时证明只读取显式shared path，
   不扫描unbound third file。
3. unit负向使用既有internal read/loader monkeypatch seam，在同一physical path第二次fresh read或load时制造raw bytes/config drift；必须
   `SUCCESSOR_INPUT_INVALID`。不得新增production hook、cache开关或public API。
4. integration必须以同一physical path运行same-config双fold。第二fold漂移反例可在既有fresh loader seam第一次调用成功后篡改该test-owned
   physical file，使第二fold `_read_regular_file` fresh观察到漂移；必须在任何stage/public runner/terminal写入前拒绝。

正向与漂移测试须分别记录read/load调用次数，不能仅断言最终PASS/FAIL。

### 10.2 P1-F2：same-config完整fold closure

扩展同一physical config的integration正向，逐项锁定：

1. 两个`FoldExecution`的fold exact `fold_001/fold_002`；各自两个`WorkIdentity`的`(fold,horizon,work_key)`按
   `compute_work_key`重算且两fold集合互斥。
2. receipt ownership：只有既有shared-stage allowlist且`fold is None`的exact shared nodes可以复用；所有non-shared receipt的
   node/path/sha/semantic owner不得跨fold alias。不得复制第二套allowlist，测试应消费runtime既有公开/模块内冻结集合或由receipt stage/fold形状裁决。
3. 四Gate顺序exact `summary -> reproducibility -> readiness -> acceptance`；每个identity使用既有
   `compute_successor_gate_identity`按result folds与prior gates重算，refs/receipt ownership保持既有闭包。
4. attestation/terminal恰有两个fold bindings；每个binding的fold、config raw/full、release id/manifest SHA与request item exact对应；
   `two_fold_identity`使用既有public/internal canonical helper重算一致，不在test复制serialization。
5. exact replay返回同terminal/two-fold identity且不产生第二physical publication；same config不能触发cross-fold cache/receipt alias。
6. 保持默认different raw/full + same scientific durable/replay正向，不把本包误改为强制config相同。

若现有result/public helpers不足以在exact6内观察这些既有事实，必须`CONTRACT_STOP / TEST_OBSERVABILITY_MISMATCH`并列精确缺口；不得修改
terminal schema、production API或扩大白名单只为测试。

### 10.3 REWORK1职责与freeze

同一原implementer仅可修改：

```text
tests/unit/test_m3_successor_runtime.py
tests/integration/test_m3_successor_runtime.py
docs/framework/deliveries/M3_G8F_R2F_V2_SharedScientificConfig交付报告.md
```

冻结：

```text
production SHA256=cd5a33492b399419389d5a8e93808ad4e918f3388ee5f87479fa4c5a531323be
unit pre-rework SHA256=2e120707ffb75df2cc3363bf87ec6f8a7e47f929b7a18cd95b40445809eb37fa
integration pre-rework SHA256=935c825b21653b9b627cfe9d181e87ba71809e5e372ea085507b85ac53fa463d
delivery pre-rework SHA256=fd579c552c644b23d6db24e371c99019d5f10ee510993f1c6296b3f64860be80
review SHA256=5cee5a1ea9fbcf312c70c2e7d1f12fd8c94082b698f923199b12cbabf33b8a17
```

review在实现交付前只读。仍为STATIC_ONLY：零Python/pytest/Ruff/mypy/cold/Qlib/data/root/evidence/stage/commit。delivery追加两项
“现象—根因—规则—最小复现—新增测试—通过条件”及原review引用；不得把未运行测试写成PASS。完成后交回同一原reviewer只写review复验；
review PASS前不得申请Windows validation。

## 11. STATIC_REWORK1_REVIEW_FAIL与STATIC_REWORK2冻结

同一独立reviewer完成REWORK1复验，确认§10的P1-F1/P1-F2已在测试结构中闭合，但新增一个确定性test-only阻断：

`STATIC_REWORK1_REVIEW_FAIL / P1-F3`

review SHA256=`e92ad3465960c00675fb3438d1fb1dba85658fdbded1eeaeda1543c39890c8c0`。production方向继续静态通过，
本轮不得修改production或unit。

### 11.1 P1-F3现象与根因

完整成功路径不是只验证request一次：

1. `run_two_fold_successor`在任何stage前调用`_validate_request(request)`；
2. fresh terminal发布后调用`verify_terminal_attestation`；
3. terminal verifier再次调用`_validate_request(request)`，随后用`_read_regular_file`读取canonical terminal。

当前same-physical integration正向在完整`_run`后却断言`load_calls == [shared, shared]`、`read_calls == load_calls`、
`len(release_calls) == 2`。这只符合第一轮request validation，与实际完整控制流不相容；若照现有代码运行，该测试必然把
terminal fresh verification的第二轮闭包误判为额外调用。该问题是测试计数合同错误，不得通过删除terminal fresh verification、修改production、
放宽为`>=2`或停止记录来迁就。

### 11.2 REWORK2唯一修正

同一原implementer仅修改：

```text
tests/integration/test_m3_successor_runtime.py
docs/framework/deliveries/M3_G8F_R2F_V2_SharedScientificConfig交付报告.md
```

冻结production、unit、taskbook与review。integration必须把same-physical完整正向的调用序列改为与实际控制流逐项exact闭合：

1. `load_calls` exact为`[shared, shared, shared, shared]`，前两项属于pre-stage validation，后两项属于post-publish terminal fresh verification；
2. `release_calls` exact为stable-sorted两个release id重复两轮，顺序为`[fold_001_release, fold_002_release, fold_001_release, fold_002_release]`；
3. `read_calls` exact前四项为同一shared config，最后一项为canonical terminal `completion.json`；不得接受额外config、unbound file、
   parent/sibling/latest或不确定集合；若实际既有helper导致除此之外的明确public receipt fresh read，必须`CONTRACT_STOP`提交精确调用图，
   不得猜计数；
4. 保持§10.2全部work/receipt/gate/attestation/two-fold/replay断言及different-path正向，不删除任何已闭合反例；
5. 不新增production hook、test-only public API、cache开关或第二套验证序列。

### 11.3 冻结SHA、文档与通过条件

REWORK2前冻结：

```text
production SHA256=cd5a33492b399419389d5a8e93808ad4e918f3388ee5f87479fa4c5a531323be
unit SHA256=4d2cddc93e03486c98be4734f19bc93db16c82edf96be4c19a9570089a108ddc
integration pre-rework2 SHA256=8c040c593239c2d3427490fd411adc2ee62d675c395970e29fba2a4fef3271d4
delivery pre-rework2 SHA256=8233497420a385d67458cf5c5660ea62420d3eb59a7b8a5aff8b2a657102bcb0
review SHA256=e92ad3465960c00675fb3438d1fb1dba85658fdbded1eeaeda1543c39890c8c0
```

delivery追加P1-F3“现象—根因—应遵循规则—最小复现—修正测试—通过条件”，保留两轮review历史并明确所有运行检查UNRUN。
完成后交回同一原reviewer，仅写review复验调用图与§10其余闭包未漂移。仍为`STATIC_ONLY / CPU NONE`：零Python、pytest、Ruff、
mypy、cold、Qlib、data、root、evidence、stage或commit；review PASS前不得申请Windows validation。

## 12. STATIC_REWORK2_REVIEW_FAIL与STATIC_REWORK3合同更正

同一独立reviewer完成REWORK2复验，结论：

`STATIC_REWORK2_REVIEW_FAIL / P1-F4`

review SHA256=`302515463b4ffd09fb57253ada5ad53f3364a18b6c4d21aa7ff32ad33c2eee22`。P1-F4同时暴露§11.2-3的经理合同缺陷：
`runtime._read_regular_file`只覆盖runtime模块的窄读取，不覆盖`verify_stage_receipt_with_bytes`内部
`_read_stable_regular_bytes`；因此不得把该monkeypatch日志命名或解释为“全部底层I/O”。此外，fresh publish在第二轮request validation前
已发生controlled-tree读取，所以“全局前四项均shared、最后一项completion”与真实调用图不能同时成立。此前这两项冻结要求由本节明确
supersede，不得继续要求实现者用过滤、去重或重排制造表面序列。

### 12.1 正确观测域

本包真正需要证明的事实是：完整成功路径发生exact两次`_validate_request`，且每一轮内部都对两个fold的同一physical config执行
fresh read/load与两条distinct release fresh verify。STATIC_REWORK3必须使用test-owned窄wrapper包裹现有`runtime._validate_request`：

1. monkeypatch前保存exact原函数；wrapper每次调用前记录`runtime._read_regular_file`、`load_m3_config`、`verify_g1_release`三个现有计数列表
   的起始index，调用原`_validate_request`，成功返回后只保存本轮slice；不得吞异常、改变request、跳过原函数或缓存结果；
2. 完整`_run`后断言validation round exact2；每轮slice分别为：read `[shared, shared]`、load `[shared, shared]`、release
   `[fold_001_release, fold_002_release]`；两轮顺序相同；
3. `runtime._read_regular_file`的全局日志只能诚实名为`runtime_read_calls`或等价窄名，明确它不是public receipt verifier内部全部I/O；
   不得再使用`all_read_calls`、`tracked_read_paths`、`dedupe_read_paths`构造过滤/去重视图；
4. 对round之外的runtime读取仅要求：不含unbound config，全部位于exact controlled output root，且canonical terminal至少被fresh读取一次；
   不冻结completion为全局最后一次读取，也不要求receipt/artifact verifier的内部read出现在该窄日志；
5. public receipt/artifact freshness继续由现有真实`verify_stage_receipt_with_bytes`调用、terminal verifier与§10 receipt/tree tamper反例证明；
   不新增第二套raw file reader，不monkeypatch或复制`run_state.py`内部读取算法，只为计数扩大观测面。

### 12.2 最小写集与禁止项

同一原implementer仅修改：

```text
tests/integration/test_m3_successor_runtime.py
docs/framework/deliveries/M3_G8F_R2F_V2_SharedScientificConfig交付报告.md
```

必须删除REWORK2为聚焦视图新增的`all_read_calls`、`tracked_read_paths`、`dedupe_read_paths` helper参数及分支，恢复一个无过滤的
runtime read recorder；不得修改production、unit、taskbook、review，不得新增production hook/public API或改变terminal/receipt验证。
§10的work/receipt/gate/attestation/two-fold/replay与drift反例全部保持。

### 12.3 冻结SHA与通过条件

REWORK3前冻结：

```text
production SHA256=cd5a33492b399419389d5a8e93808ad4e918f3388ee5f87479fa4c5a531323be
unit SHA256=4d2cddc93e03486c98be4734f19bc93db16c82edf96be4c19a9570089a108ddc
integration pre-rework3 SHA256=f161c237cbd40e3bb3e8bdfbb7e0cb114b48dc8f9fadbea77aa34151fb22321e
delivery pre-rework3 SHA256=148b6b156bef9b0c335b697bff3338fecd6158e0d02bbc9f871e895bd0ac90b2
review SHA256=302515463b4ffd09fb57253ada5ad53f3364a18b6c4d21aa7ff32ad33c2eee22
```

delivery必须承认§11全局raw-sequence合同错误并记录P1-F4“现象—根因—正确观测域—最小复现—修正测试—通过条件”，不得把
STATIC结构写成运行PASS。完成后同一原reviewer只写review复验：round wrapper不改变控制流、每轮delta exact、无过滤/重排、§10其余闭包
不漂移。仍为`STATIC_ONLY / CPU NONE`，零Python/pytest/Ruff/mypy/cold/Qlib/data/root/evidence/stage/commit；review PASS后才申请完整Windows验证。

## 13. VALIDATION3产品反馈与STATIC_REWORK4冻结

VALIDATION1/2均在Python0-call的carrier边界停止；VALIDATION3使用独立Parser preflight后形成可信产品证据：

```text
identity PASS
unit test_m3_successor_runtime.py PASS
integration 29 passed / 1 failed
Ruff/mypy/cold/scope UNRUN
```

evidence root=`artifacts/agent_runs/m3-r2f-v2-validation3-20260828T121638Z`；summary SHA256=
`3bc22a591a7d64d9479cd3cef5de112f65691561d1835f46d582ce39604f418f`；unit stdout SHA256=
`7f0c60897d815a9e0d812a5ec768f0de50134fbdb41671316b2a62c2d511a2e6`；integration stdout SHA256=
`ad36fc0e781bb7bcd8a2210d2dc17d727013f390a9fe6166e3a33a5e518e569f`。basetemp/cache/Python/0xF00 residue均已清零。

### 13.1 唯一失败的现象与根因

失败节点：`test_same_config_replay_is_exact_and_second_fold_tamper_fails_fresh`。首次成功后`public_api_calls`为31，exact replay后为35。
新增四次不是第二次publication或stage work，而是`verify_terminal_attestation`对summary、reproducibility、readiness、acceptance四个Gate
逐项调用既有public verifier。replay安全合同要求fresh verification，不能把“无第二次经济/physical publication”错误收紧为“任何public
verification调用均为0”。production不得为测试断言而删除fresh verifier。

### 13.2 STATIC_REWORK4唯一修正

同一原implementer仅修改：

```text
tests/integration/test_m3_successor_runtime.py
docs/framework/deliveries/M3_G8F_R2F_V2_SharedScientificConfig交付报告.md
```

冻结规则：

1. 首次运行后保存完整`public_api_calls`前缀；exact replay后断言前缀逐字不变，新增suffix exact为：
   `summary-public-verify`、`reproducibility-public-verify`、`readiness-public-verify`、`acceptance-public-verify`；
2. suffix不得包含任何`public-run`、`run-plan`、upstream/formal wave、publication或其他stage执行调用；不得只断言长度`+4`；
3. replay仍断言`reused is True`、attestation/terminal/two-fold identity exact不变，并保持无第二physical publication的既有事实；
4. 保存`calls_after_replay = len(public_api_calls)`；随后篡改shared config并重试，必须`SUCCESSOR_INPUT_INVALID`且调用数保持
   `calls_after_replay`，证明drift在任何新增public verifier/stage/publication前拒绝；
5. 不修改production、unit、其他integration反例、terminal verifier或错误码，不增加test-only public hook。

### 13.3 冻结SHA与后续验证

REWORK4前冻结：

```text
production SHA256=cd5a33492b399419389d5a8e93808ad4e918f3388ee5f87479fa4c5a531323be
unit SHA256=4d2cddc93e03486c98be4734f19bc93db16c82edf96be4c19a9570089a108ddc
integration pre-rework4 SHA256=53498bc6be6c6aa8fdef34342a2df8e22e9a20a487fa8227a68ca580562519d6
delivery pre-rework4 SHA256=01beb50b78d9685ee5e61421c5f1348a44b182ba55f9b5d5734dd8152006c571
review SHA256=92c88ad0a51f12bbb513a4c3a2f2ed56d3432d30ccf62ffa35131fb7aaa63a9a
```

delivery追加V1-V3真实边界及本轮“现象—根因—fresh verification规则—最小复现—修正测试—通过条件”，不得把29绿/1失败写成整包PASS。
同一原reviewer复验仅是行为等价测试修正后，可申请post-fix验证：identity轻量→该单一integration节点→Ruff exact3→mypy production→cold→
exact6 scope/diff/temp/process。VALIDATION3已绿的完整unit与其余integration 29项不机械重复，除非review发现超出上述局部断言变化。
当前仍STATIC_ONLY/CPU NONE，零Python、pytest、Ruff、mypy、cold、Qlib、data、root、evidence、stage、commit。

## 14. Windows组合验证终态与提交前证据闭环

STATIC_REWORK4 reviewer结论=`STATIC_REWORK4_REVIEW_PASS`，review SHA256=
`4becfdd9b27366775c35e065812741f824b63b9f15add22d12a3ecc5381d5162`。其后未再修改production或unit。

### 14.1 VALIDATION1–5真实边界

| 轮次 | 真实结论 | 可采用证据 | 不得采用/未运行 |
| --- | --- | --- | --- |
| V1 | `CARRIER_SYNTAX_INVALID_BEFORE_PRODUCT_EVIDENCE` | Python0-call、资源未取得、summary SHA `47755ef671684c5f915629ddba624552c7a84d65c2a083ac620e36a1cbf537b8` | 所有产品阶段UNRUN |
| V2 | `CARRIER_PREFLIGHT_WRAPPER_INVALID_BEFORE_PRODUCT_EVIDENCE` | Parser errors0；Python0-call；summary SHA `60501198f959b2db4383b5c71098a7f1f507eec9b9db16d1c3236313755c633b` | 所有产品阶段UNRUN |
| V3 | 可信产品首失败 | identity PASS；unit full PASS；integration `29 passed / 1 failed`；失败为§13 test-only replay计数；summary SHA `3bc22a591a7d64d9479cd3cef5de112f65691561d1835f46d582ce39604f418f` | Ruff/mypy/cold/scope UNRUN |
| V4 | post-fix产品全部PASS；scope carrier STOP | identity PASS；原失败节点`1 passed`；Ruff exact3 PASS；mypy production PASS；cold PASS；summary SHA `0165770cda42407a1eb9257d85a3e7748c23cd412a70806748906472111c4468` | scope三件套不完整，不能据此宣称scope PASS |
| V5 | scope-only PASS | exact6 count6、cached0、`git diff --check` exit0；stderr仅三条LF→CRLF warning；temp/cache/Python/0xF00清零；summary SHA `d52f14f869ddcfc3840ad0f6ae72738a5a3a549d8079e795022f9dc36d2c60de` | 未重复任何产品阶段 |

V3 unit stdout SHA256=`7f0c60897d815a9e0d812a5ec768f0de50134fbdb41671316b2a62c2d511a2e6`；V3 integration stdout SHA256=
`ad36fc0e781bb7bcd8a2210d2dc17d727013f390a9fe6166e3a33a5e518e569f`。V4 replay node stdout SHA256=
`27b93b41fc7fe0209fb0edde525c85c2884ce93570c953f81487fc13e272dd56`；Ruff stdout SHA256=
`af352a86840ad0af3d37ea0d9197f868363a6dac6b1c2ef5d2722f6b41d2d9af`；mypy stdout SHA256=
`94594db09076fe305d51b50210d0bc5e9d275fb814f8b42c1ed4cf3368392f9a`。

### 14.2 组合结论与剩余边界

以下组合闭合本包Windows工程验证：V3完整unit与integration其余29项 + V4修正节点/Ruff/mypy/cold + V5 exact6/scope/residue。
它不是伪造单轮全绿，也不洗白V1/V2 carrier失败、V3测试失败或V4 scope carrier STOP。状态上限为
`R2F_V2_WINDOWS_ENGINEERING_VALIDATED / SHARED_SCIENTIFIC_CONFIG_CONTRACT_VALIDATED`。

仍未关闭：正式scientific config数值与controlled root（A14）、formal G1 release（A15）、Windows py312/Qlib环境（A17）、actual successor、
真实Qlib、new root、retained resume、acceptance真实运行与M3 Gate。Linux不在当前目标范围，但也不得声明其Gate通过。

### 14.3 提交前职责

1. 同一原implementer仅更新delivery，逐轮记录V1–V5、关键evidence SHA、组合范围与剩余边界；production/tests/review只读，零Python。
2. 同一原reviewer仅更新review，复核evidence root/关键SHA、V3+V4+V5组合、exact6及未验证边界，输出`EVIDENCE_REVIEW_PASS/FAIL`。
3. 只有`EVIDENCE_REVIEW_PASS`后才申请SAFE_COMMIT；ignored evidence不得stage。提交、merge、archive-first退休统一由中央另行裁定。
