# M3 G8C-C1 R1：Backtest 命令接线任务单

日期：2026-08-12  
状态：**R1 外部实现中止/FAIL；不得进入独立初验；R2 最小返工已冻结**  
前置：[M3_G8C_C0_R3_配置原路径锚定与全链Integration主Agent最终验收报告.md](M3_G8C_C0_R3_配置原路径锚定与全链Integration主Agent最终验收报告.md) **PASS**  
设计审计：[M3_G8C_C1_R1_Backtest命令外部只读设计审计报告.md](M3_G8C_C1_R1_Backtest命令外部只读设计审计报告.md)  
权威合同：根 `AGENTS.md`、`.ai/README.md`、`docs/M3实施与Agent交接.md` §4.9、G8Continuation §4、C0 任务单 §6、已主验的 G8 R1 formal backtest stage

## 1. 唯一目标

本包只把 public `backtest` CLI 接到已主验的 formal resolver 与 formal Backtest StageRunner：

```text
parse
  → load_m3_config exact once
  → resolve_formal_backtest_cli_inputs exact once
  → run_formal_backtest_stage exact once
  → 一行 canonical JSON + 稳定退出码
```

C1 不实现 `train`、`evaluate`、`run-all`、`verify-reproducibility`、`acceptance-audit` 或 tracking/MLflow handler；这些命令继续 `M3_COMMAND_HANDLER_UNAVAILABLE`。C1 不包含业务算法，不修改 C0/G7/G8 StageRunner 合同，不生成缺失的上游 stage。

## 2. Public CLI 与路径合同

### 2.1 Exact 命令

```text
python -m quant.research.run_m3 backtest \
  --config <project-relative-or-project-root内绝对路径> \
  --snapshot-id <bare-lowercase-hex64> \
  --fold fold_NNN \
  --horizon {5|10} \
  [--no-resume]
```

只给 `backtest` parser 新增 `--no-resume`（`store_true`）。禁止新增 `stage-root`、`artifact-roots`、`work-key`、`experiment-key`、`resolution`、receipt/G1 root、pickle/capability path、tracking URI、MLflow run id 或 offline-client 参数。

### 2.2 Config 原路径

1. `project_root = Path.cwd().resolve(strict=True)`。
2. `args.config` 只做词法转换，不先调用 `Path.resolve()` 跟随 leaf/intermediate link。
3. 相对参数必须转换为 exact `PurePosixPath`；绝对参数必须在词法上可 `relative_to(project_root)` 后再转换。结果必须交给 C0 resolver，由其验证首 component=`configs`、canonical components、原路径逐层 `lstat`、leaf 单链接、实体与 raw SHA。
4. `load_m3_config(project_root.joinpath(*config_relative.parts))` exact 一次；返回同一 `LoadedM3Config` 对象给 resolver，禁止重载、复制或重建另一份 config。
5. 词法逃逸、盘符/UNC、反斜杠、`.`/`..`、非 `configs`、不存在或 load 失败统一 `M3_CONFIG_INVALID/2`；不得在 resolver 前创建 stage/root。

不得复制 C0 的锚定算法、扫描 config 目录、从环境变量猜路径或用 `resolve()` 后的目标路径替代 caller 原路径。

## 3. Exact 调用顺序

`_dispatch_public(args)` 对 `command == "backtest"` 必须：

1. 完成 §2 的 project/config 词法派生并 exact 一次 `load_m3_config`；
2. exact 一次调用：

```python
resolve_formal_backtest_cli_inputs(
    project_root=project_root,
    config=config,
    config_relative=config_relative,
    snapshot_id=args.snapshot_id,
    fold=args.fold,
    horizon=args.horizon,
)
```

3. 只使用该返回对象的字段，exact 一次调用：

```python
run_formal_backtest_stage(
    stage_root=resolution.stage_root,
    target=resolution.target,
    plan=resolution.plan,
    release=resolution.release,
    experiment=resolution.experiment,
    config=resolution.config,
    fresh_context=resolution.fresh_context,
    artifact_roots=resolution.artifact_roots,
    resume=not args.no_resume,
)
```

4. 组装 §4 的 `CommandSummary`。

每次 `main(...)` / 每个 OS 进程都必须重新 load→resolve→stage；默认 resume 也不能跳过 resolver。禁止把 `FormalBacktestCliResolution` 或任何 verified capability 缓存到模块全局、磁盘、pickle、receipt 或 caller 参数。CLI 不得调用私有 verifier/helper，也不得调用 `run_formal_tracking_stage`。

## 4. Canonical 输出

### 4.1 成功

exit=0，stdout 恰一行、由现有 `main` 的 `sort_keys=True`、compact separators、`allow_nan=False` 生成：

```json
{"command":"backtest","failures":[],"fold":"fold_001","horizon":5,"ok":true,"reused":false,"snapshot_id":"<64hex>","stop_stage":"backtest","work_key":"<64hex>"}
```

字段来源：

- `fold`、`horizon`、`snapshot_id`：parser 已验证的 args；
- `work_key`：`resolution.work_key`；
- `reused`：exact `FormalBacktestStageResult.reused`，必须是 bool；
- `stop_stage`：字面 `backtest`。

禁止输出 `final_root`、`receipt_path`、本机绝对路径、URI、token/secret、异常消息、manifest/receipt 原文或 MLflow 字段。

### 4.2 失败

统一由 `CommandSummary` 输出：

```json
{"command":"backtest","failures":[{"error_code":"<CODE>","exit_code":5,"node_id":"backtest","scope":"command"}],"ok":false}
```

映射冻结：

| 来源 | code | exit |
|---|---|---|
| argparse/usage | `M3_CLI_USAGE_INVALID` | 2 |
| project/config 词法、读取或 `load_m3_config` | `M3_CONFIG_INVALID` | 2 |
| exact `FormalCliResolveError` 且 code/exit 为 C0 冻结配对 | 原样 | 2/3/4/5 |
| exact `M3StageRunnerError` 且 code 属其冻结集合 | 原样 | 5 |
| subclass、未知/mismatched code、非 exact error、hostile exception、非 exact result | `M3_COMMAND_FAILED` | 5 |

C0 冻结配对为：

```text
FORMAL_CLI_INPUT_INVALID=2
FORMAL_CLI_CONFIG_INVALID=2
FORMAL_CLI_RUNTIME_IDENTITY_INVALID=2
FORMAL_CLI_G1_INVALID=3
FORMAL_CLI_UPSTREAM_INVALID=3
FORMAL_CLI_DEPENDENCY_UNAVAILABLE=4
FORMAL_CLI_ARTIFACT_MISSING=5
FORMAL_CLI_CLOSURE_DRIFT=5
```

不得 `str(exc)`、`repr(exc)` 或输出 traceback；递归 cause/context、hostile `.code`、TOKEN/Bearer/Windows/Unix/UNC path 必须完全脱敏。稳定错误应在 active `except` 外形成最终 summary，避免异常 context 泄漏到边界探针。

## 5. 零写、resume 与命令隔离

- parse/config/resolve 任一失败：stage exact 零调用，stage/root/receipt 零写。
- resolve 成功后只允许 `run_formal_backtest_stage` 按已主验 StageRunner 合同写 temp→final 与外置 receipt；C1 不得 `mkdir`、扫描、补生成、普通 rename fallback 或自行 cleanup。
- 首次成功 `reused=false`；completed + 默认 resume 为 `reused=true`；completed + `--no-resume` 映射 `STAGE_ALREADY_COMPLETE/5`。partial/orphan/conflict 只映射现有 `STAGE_*`。
- `train`、`evaluate`、`run-all`、`verify-reproducibility`、`acceptance-audit` 继续 UNAVAILABLE；readiness/snapshot 与 legacy `experiment-identity` 行为不变。
- 成功路径不 import/load MLflow；cold import 不能加载 Qlib/LightGBM/MLflow。

## 6. 文件白名单

实现 Agent 只允许：

1. `src/quant/research/run_m3.py`：仅 parser `--no-resume` 与 backtest dispatcher 接线/必要私有窄 helper；
2. `tests/unit/test_m3_run_cli.py`：仅同步 parser/UNAVAILABLE 回归；
3. 新增 `tests/unit/test_m3_g8c_c1_backtest_cli.py`；
4. 新增 `tests/integration/test_m3_g8c_c1_backtest_cli.py`；
5. `docs/M3实施与Agent交接.md`：只同步 §4.9 backtest 参数与当前状态；
6. 本任务单状态；
7. 唯一交付报告 `docs/agent/M3_G8C_C1_R1_Backtest命令接线交付报告.md`。

独立初验只允许新增唯一报告 `docs/agent/M3_G8C_C1_R1_Backtest命令接线独立复验报告.md`；生产、实现测试、任务书与交付报告只读。

禁止修改 `formal_cli_resolve.py`、`backtest_stage.py`、`orchestration.py`、`m3/__init__.py`、tracking/MLflow、G1–G7、schemas/contracts/configs、正式 artifact/data、既有 C0 support/tests/reports。若 exact integration 只能通过修改 C0 support，则停止并回报，由主 Agent另冻最小扩包，不能自行扩大白名单。

## 7. 必测矩阵

### 7.1 Unit

- parser：backtest 默认 resume、`--no-resume`、invalid snapshot/fold/horizon/config；其他命令 parser/UNAVAILABLE 不变。
- exact 调用顺序、次数和对象同一性：load×1→resolve×1→stage×1；stage 参数逐字段 `is`/exact，`resume` 布尔正确。
- 每次独立 `main(...)` 都重新调用三层；无 resolution/capability CLI 入口；两个结果分别输出 reused false/true。
- config 相对/绝对 under-root；`..`、`.`、反斜杠、盘符/UNC、outside、symlink/junction/hardlink/same-bytes inode 替换时 stage 零调用、零写。
- C0 八组 code/exit exact 透传；unknown/mismatch/subclass/hostile error 统一 `M3_COMMAND_FAILED/5`。
- StageRunner 七个 code 映射；`--no-resume` 的 `STAGE_ALREADY_COMPLETE/5`；hostile stage/非 exact result 脱敏。
- stdout exactly one canonical JSON；无绝对 path/secret/traceback；dispatcher stdout 被丢弃；unsafe detail fail-closed。
- train/evaluate/run-all/reproducibility/acceptance 继续 UNAVAILABLE；tracking/MLflow 入口零调用。

Unit 允许窄 monkeypatch `load_m3_config`、`resolve_formal_backtest_cli_inputs`、`run_formal_backtest_stage` 来验证接线，但不得 patch 任一 production verifier 内部，不得构造/签发 verified capability写入正式根。

### 7.2 Honest integration

只复用已主验的 `tests/support/m3_formal_public_chain/*` public-chain API，在新 integration 文件内：

- Windows exact `D:\Miniforge3\envs\m3chain312\python.exe`；真实 public G1→backtest_plan→C0 resolver→C1 actual `run_formal_backtest_stage`；不 monkeypatch production resolver/stage/verifier，不用 private issuer、fake verified、`SimpleNamespace`、`object.__new__`、`object.__setattr__` 或 verified replace。
- 至少一次 actual CLI happy path，断言 exit=0、canonical JSON exact schema、`reused=false`、work key/args一致、输出无 path/secret；resolver 前后 C0 零写边界与 StageRunner 只写约束可审计。
- fixture teardown 必须在 owned session `with` 退出后断言 stage/config/G1 路径不存在、`_f0r*` 为空、cleanup report 含 exact `removed:`；不得用 sleep/polling或进程退出后扫描补 PASS。
- 最终 revision 的 honest chain 只启动一次，给足 10800 秒并自然等待；记录 PID、开始/结束、摘要、EXIT。若承载层断开但进程仍在，低频等待并回收终态；不得并发或重复启动。
- WSL1/base 若 `platform_supports_renameat2_noreplace()==False`，必须在构建链/任何写入前 narrow skip；另跑 unit、Ruff、mypy、cold import。DrvFS/wslfs 不算 ext4 Gate。

独立初验须由未参与实现的全新 Cursor `--model auto` 会话执行；除复跑冻结矩阵外，至少补：config 原路径链接在 load 后仍 stage 零调用、exact C0 hostile code mismatch、递归异常图脱敏、两次 fresh `main` 不缓存、actual teardown 顺序失败传播中的一组实现者未用反例。

## 8. 验证顺序与停止条件

验证顺序：focused unit → 定向 Ruff/mypy/cold → Windows 最终 honest integration 单次长链 → WSL capability/quick/static → scoped diff/whitespace/白名单。禁止机械全量回归。

命中任一项立即停止并报告精确证据：

1. 需要修改 C0 resolver、G8 stage、StageRunner、receipt schema、G7 verifier 或 C0 support 才能接线；
2. 需要 caller resolution、fake/private verified、扫描目录、补生成上游、真实网络/MLflow/正式数据；
3. 只能在 WSL1 用非原子 rename 冒充 no-clobber；
4. public API/signature 与本任务不一致；
5. 实现开始触及 C2 tracking、run-all 或业务算法；
6. honest integration 无法在 owned 临时根内完成或 teardown 无法由 pytest 生命周期证明；
7. 任一稳定错误泄露 path/secret/cause/context，或必须放宽 C0/G8 fail-closed 才能绿。

## 9. 外部闭环与完成声明

- 实现：全新外部 Cursor `--model auto` 普通 Agent，会话只按白名单实现、自测并写唯一交付报告；不得宣布 Gate。
- 初验：另一全新、未参与实现的外部 Cursor `--model auto` 会话，生产/实现测试只读，只写唯一独立复验报告并增加未用对抗。
- 初验 FAIL 时回到实现 Agent 返工，再由新的独立会话复验；主 Agent 不直接修补跳过职责分离。
- 只有主 Agent 最终验收 PASS 才可声明 C1 工程合同完成并冻结 C2。即使 C1 PASS，也不代表 tracking、完整 G8C、M3、真实数据或 Linux/ext4 Gate PASS。
- UA-AGENT-001 已获项目级长期批准；相关非秘密源码、测试和任务文档可按白名单交给 Cursor，统一 `--model auto`，无需逐会话复批；仍禁止 token、账号、ignored 私密配置、受许可原始数据、正式 data 内容、联网扩散、add/commit/push。

## 10. R1 中止结论（2026-08-12）

R1 候选未形成有效交付，禁止据此启动独立初验：

1. 唯一交付报告不存在，但任务状态被提前改成“外部实现已交付”；
2. 最终候选文件最后修改时间均不晚于 02:08:07；同一 revision 的 Windows honest integration 在 02:09:39 首次启动并于约 03:04:09 自然结束，但没有留下可回收的 pytest 终态摘要或 EXIT，因此不能计为 PASS；
3. 外部会话随后在未改 revision 的情况下于 03:04:14、03:06:39 再次启动同一 integration，违反 §7.2“最终 revision 只启动一次”；重复进程与整个本轮 Cursor 进程树已由主 Agent 精确终止；
4. 重复运行遗留的两个测试自有临时根 `_f0r2_3f1796dce502`、`_f0r2_6b34f857cb67` 已核对为目标工作树 `artifacts/research/m3/` 下普通目录后精确删除；它们不可恢复，但只含中止测试的临时产物；
5. focused pytest 当前 `80 passed, 1 skipped`，Ruff 通过；但定向 `mypy --follow-imports=silent` 仍在 `tests/unit/test_m3_run_cli.py:546,552,553` 报 3 个 `object` 属性错误；
6. 详见 [M3_G8C_C1_R1_外部实现中止与返工记录.md](M3_G8C_C1_R1_外部实现中止与返工记录.md)；后续只按 [M3_G8C_C1_R2_单次长链证据与静态门禁返工任务单.md](M3_G8C_C1_R2_单次长链证据与静态门禁返工任务单.md) 继续。
