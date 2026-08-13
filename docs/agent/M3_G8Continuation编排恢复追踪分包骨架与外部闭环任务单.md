# M3 G8 Continuation、编排、恢复与追踪分包骨架任务单

日期：2026-07-14  
状态：**设计冻结；可先用 fake handlers 实现 G8A–G8F，真实 Gate 等待 G1–G7 handlers 主验**  
环境：WSL Miniforge `base`；默认测试不联网、不启动真实 MLflow server  
设计 SSOT：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md) §4.9  
历史任务与审查：[`M3_G8编排与追踪实现初验任务单.md`](../archive/M3_G8编排与追踪实现初验任务单.md)、
[`M3_G8设计审查与修订记录.md`](M3_G8设计审查与修订记录.md)

> 本文取代旧 O1–O5 的执行颗粒度，补齐 verified continuation 输入、stage-owned 原子目录、handler 能力边界和
> G7 `backtest_plan`。本文不宣称 G8、G9、M3 或任何 Gate 已实现或通过。

> **开发并行轨边界（2026-07-31）：** G8A/G8B 可按
> [`M3_DevelopmentExampleRelease开发并行轨任务单.md`](M3_DevelopmentExampleRelease开发并行轨任务单.md)
> 使用 development example 验证 snapshot plan、首次发布、恢复和幂等执行。其节点名/receipt stage 与正式
> `snapshot` 分离，正式 runner 拒绝该节点；这些结果不代表真实 handlers、正式 G8 或任何 Gate 通过。

## 1. 六包拆分

| 包 | 唯一职责 | 前置 |
|---|---|---|
| **G8A** | StageSpec registry、StageNode 与五段 continuation plan | C0/E3、各 verified 类型 |
| **G8B** | stage-owned directory、StageRunner、恢复与并发发布 | G8A、E3 |
| **G8C** | CLI、停止点、失败隔离和规范 summary | G8A/G8B |
| **G8D** | tracking request journal、MLflow 幂等登记 | G8B/C0 |
| **G8E** | 两个 fresh process 冷启动复现 | G8B/G5/G6 |
| **G8F** | 2 folds×2 horizons fake 全 DAG 集成 | G8A–G8E |

真实 handler 未实现不阻止 fake 合同落地，但报告必须写明真实 G8 Gate 未关闭。

### 1.1 Identity-resolved waves 修订（2026-08-02）

五种用户可见 continuation 模式保持不变，但 `PROVIDER` 与 `EXPERIMENT` 各自由多个串行、可恢复、每次身份完全解析的 `RunPlan` wave 组成。禁止用 orchestration plan hash 代理 provider、provider-validation、experiment 或 label-reconciliation 的业务 identity。

- provider materialization 只有在 snapshot、dump tool、provider runtime fingerprint 与 code identity 均已验证后才能规划；provider-validation 必须等待 `VerifiedProviderArtifact` 及其 receipt。
- experiment identity 必须等待 verified provider、code/dependency identity；provider-validation PASS 是 dependency gate，不进入 experiment identity 内容输入。
- labels/folds 等待 `VerifiedExperimentIdentity`；label-reconciliation 等待对应 `VerifiedLabelArtifact`，不得预填未知 manifest hash。
- WORK 可在 verified experiment/folds/labels/reconciliation 闭包后一次性规划；features 按 fold 共享，work key 只使用规范 `compute_work_key`。
- verified continuation 的 receipt/path/digest 引用须由 verifier 产生的窄合同承载，调用方不得裸报 path/hash。

因此，G8A 首包只关闭 registry、SNAPSHOT、WORK 与 SUMMARY 计划合同；PROVIDER/EXPERIMENT waves 随正式 ExperimentIdentity/通用 static runner 合同补齐后关闭。该阶段状态不等于完整 G8A 或 G8 Gate。

## 2. G8A：registry 与 continuation plans

文件：新增 `src/quant/research/m3/orchestration.py`、计划单测与两份报告。

```python
@dataclass(frozen=True)
class OutputSpec:
    relative_path: str
    kind: Literal["FILE", "TREE"]
    closure_manifest: str | None

@dataclass(frozen=True)
class StageSpec:
    name: str
    scope: Scope
    dependencies: tuple[str, ...]
    outputs: tuple[OutputSpec, ...]

@dataclass(frozen=True)
class StaticDirectoryPublication:
    final_directory: str

@dataclass(frozen=True)
class SnapshotContentPublication:
    content_directory_parent: Literal["snapshots"]
    request_record_path: str
    manifest_relative_path: Literal["manifest.json"]
    content_id_field: Literal["snapshot_id"]

PublicationSpec = StaticDirectoryPublication | SnapshotContentPublication

@dataclass(frozen=True)
class ExternalInput:
    artifact: ArtifactDigest

@dataclass(frozen=True)
class StageOutputInput:
    producer_node_id: str
    root_alias: str
    relative_path: str

InputSpec = ExternalInput | StageOutputInput

@dataclass(frozen=True)
class StageNode:
    node_id: str
    spec_name: str
    scope: Scope
    scope_key: str
    fold: str | None
    horizon: int | None
    dependencies: tuple[str, ...]
    inputs: tuple[InputSpec, ...]
    publication: PublicationSpec
    output_specs: tuple[OutputSpec, ...]
    receipt_path: str

@dataclass(frozen=True)
class RunPlan:
    continuation: Literal["SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "SUMMARY"]
    nodes: tuple[StageNode, ...]
```

plan builder 只接收 `LoadedM3Config` 与前一 continuation 已验真的 bundles，不接裸 Mapping、expected fold、
caller path/hash。例如 work plan 接 `VerifiedExperimentIdentity`、`VerifiedFoldPlanArtifact` 和对应 verified
label bundles，并在 plan 内产生 fold-shared feature nodes；不得扫描目录或执行 handler。continuation 边界外输入必须是 `ExternalInput` 且携带已验真
digest；同一 plan 内尚未产生的输入必须是 `StageOutputInput`，runner 只能从对应 producer 的已验真 receipt
解析实际 digest。禁止 builder 预填未知 hash、让调用者自报 hash，或让 handler 自行寻址上游文件。

五段固定：snapshot request→content snapshot；snapshot→provider+validation；verified provider→experiment
identity+labels/reconciliation/folds；verified folds→fold-shared features+work；verified evaluations→summary。
同 experiment 3 folds×2 horizons 只有一个 experiment key、六个 work key。stage registry 增加 G7
`backtest_plan`，work 顺序为 alignment→train→predictions→evaluation→targets→backtest_plan→backtest→tracking。

snapshot request/manifest 必须携带从 G1 继承的 `signal_start/signal_end`；fold node 只能从该 verified snapshot
窗口和 scientific selector 构造计划。provider-validation receipt 是 feature node 的 dependency gate，但不是
feature handler 的内容 input；receipt input 闭包不得因此把它混进 feature identity。`features.<fold>` 使用
`scope="EXPERIMENT"`、`scope_key=experiment_key`，由 node id/fold 字段区分；h=5/h=10 work 必须引用同一
feature receipt。prediction/evaluation/summary 的 strict metrics 与 input/output 闭包以
[`M3_G4_G6研究链分包骨架与外部闭环任务单.md`](M3_G4_G6研究链分包骨架与外部闭环任务单.md) §9.1 为准。

每个 static node 的 final directory 独占且互不嵌套；`node_id` 只允许小写 ASCII 字母、数字、点、下划线和连字符，
不得含路径分隔符。receipt 位于 output directory 之外的同 scope `receipts/` 目录。plan 构造时检查 node ID、
receipt、output path 无冲突，DAG 无环，fold/horizon 排序稳定。每个 `StageOutputInput.producer_node_id` 必须在
dependencies 中，且 relative path 必须被 producer 的 output spec 覆盖。TREE 必须指定 strict closure manifest
或固定树 verifier，不能用目录 hash 代替逐文件闭包。receipt 不属于业务 output。

只有 snapshot node 使用 `SnapshotContentPublication`：plan 时只知道 `snapshot_request_key`，不知道内容
`snapshot_id`，不得把 request key 冒充 final ID。其 `request_record_path` 精确为
`snapshot-requests/<snapshot_request_key>.json`；temp manifest 严格验真后读取 `snapshot_id`，final 才解析为
`snapshots/<snapshot_id>/`。其他全部 node 必须使用 `StaticDirectoryPublication`，禁止 handler 返回任意 final path。

## 3. G8B：StageRunner 与原子目录恢复

文件：继续 `orchestration.py`，新增 runner 单测和两份报告。

```python
@dataclass(frozen=True)
class ResolvedInput:
    digest: ArtifactDigest
    path: Path

@dataclass(frozen=True)
class StageContext:
    node: StageNode
    inputs: tuple[ResolvedInput, ...]
    temp_output_root: Path
    config: LoadedM3Config

@dataclass(frozen=True)
class StageBuildReport:
    output_relative_paths: tuple[str, ...]

StageHandler = Callable[[StageContext], StageBuildReport]
```

handler 不接 artifact roots、final root 或 receipt path，只能获得声明输入和一个空 temp。runner 在调用前验证
dependency receipt 和每个 input；调用后独立验证 output spec、Schema/strict manifest/普通文件闭包，不信 handler
自报 hash/PASS。

所有多文件 stage 必须写入独占目录，例如：

```text
work/<work_key>/train/{model.txt,model.metadata.json,validation_curve.parquet}
work/<work_key>/predictions/{predictions.parquet,prediction_manifest.json}
work/<work_key>/evaluation/{daily_ic.parquet,metrics.json,evaluation_manifest.json}
work/<work_key>/targets/{target_weights.parquet,target_daily.parquet,target_manifest.json}
work/<work_key>/backtest_plan/{scheduled_targets.parquet,...}
```

runner 对 `(scope,scope_key,node_id)` 使用 WSL `flock`，锁内重新验真；普通 stage 将非空 temp directory通过 Linux/WSL
`renameat2(RENAME_NOREPLACE)` 或语义等价的目录级原子 no-clobber primitive 发布为 final stage directory，
fsync parent，再发布 receipt。若运行时不支持则 fail-closed，禁止回退到 `os.rename`、逐文件 merge、
`os.replace` 或覆盖。单机并发受保证；跨主机不保证并须披露。

snapshot 是唯一两步内容寻址发布：closure verifier 返回已重算的 `SnapshotBuildResult` 与
`SnapshotRequestRecordV1`；runner 先 no-clobber 发布整个 temp 到 `snapshots/<snapshot_id>/`，fsync parent，
再以 E3 严格单文件 no-clobber 语义发布 request record，最后发布 receipt。snapshot receipt 的 inputs/outputs
必须精确等于 G2A 冻结集合。snapshot 目录已存在、mapping 缺失时只有逐文件 bytes 完全一致才补 mapping；
mapping 已存在但目标缺失/损坏、同 request 指向另一 ID、同 ID 内容不同全部 fail-closed。禁止把
`snapshot-builds/<request_key>` 当正式 snapshot 或让 handler直接写 final roots。

普通 stage 恢复状态：有效 receipt+闭包→reuse；无 receipt/无 final→build；无 receipt+完整 final→隔离重算并逐字节比较，
相同补 receipt，不同 fail；receipt 损坏或 final 部分/漂移→fail，不覆盖。原子目录意味着正式 stage 不应出现
“半套文件”；发现半套直接视为外部损坏。`--no-resume` 遇到任何有效完成 stage 以 code 5 失败且零变更。

shared/work 失败按依赖传播：某 label[h] 只阻断该 horizon；feature[fold] 阻断该 fold 两 work；某 work 阻断
自身下游，其他 work 继续。执行稳定串行，暂不预建并行 executor。

G7 runtime nodes 的精确闭包以
[`M3_G7目标到账户回测分包骨架与外部闭环任务单.md`](M3_G7目标到账户回测分包骨架与外部闭环任务单.md)
§9.1 为准：targets 三文件、backtest-plan 四文件、backtest 三个完整 scenario 目录加 root 两文件。G7P0 是
代码/配置合同前置，不是可被 DAG receipt 伪装通过的 runtime node。backtest handler 只能从 G1 八个已声明
market-facts inputs 构造一次 verified view，再独立运行三场景；runner 不接受 handler 自报 files/metrics 子集。
plan、三个 scenario 与 bundle 必须绑定同一个
`G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION`；科创板 200 股起报/1 股递增与主板、创业板 100 股整数倍不得由
runner 用 `board_lot` 统一改写。根 `BacktestMetricsV1` 的 scenario 顺序固定 `0p5x,1p0x,2p0x`。

## 4. G8C：CLI 与失败语义

文件：新增 `src/quant/research/run_m3.py`、CLI 单测和两份报告。CLI 只加载一次 config，解析 verified identity，
调用 plan/runner；不含业务算法。

八命令与停止点继续以主 SSOT 表为准。stdout 恰一份规范 JSON；warning/log 写 stderr。失败 summary 按
`scope,node_id,error_code` 稳定排序并列出所有失败，退出码取最小非零：2 参数/配置/契约，3 数据门禁，
4 依赖不可用，5 stage/receipt，6 tracking，7 reproducibility，8 acceptance。code 2 在任何产物前返回。

`train/evaluate/backtest` 的 snapshot/fold/horizon 必须与 verified folds/work identity 闭合；不能让 CLI 直接
拼路径。`run-all` 接 G1 release 或 snapshot 二选一，按 continuation 推进；shared 失败只阻断真实依赖。
参数/异常 message 统一脱敏，无 traceback、client repr、token 或绝对路径。

## 5. G8D：tracking journal 与 MLflow

文件：重构 `tracking.py`、新增恢复/并发单测和两份报告。仅本模块延迟 import MLflow。

```python
@dataclass(frozen=True)
class TrackingRequestV1:
    schema_version: Literal["m3-tracking-request-v1"]
    tracking_target_key: str
    work_key: str
    params: tuple[tuple[str, str], ...]
    tags: tuple[tuple[str, str], ...]
    metrics: tuple[tuple[str, float], ...]
    artifacts: tuple[ArtifactDigest, ...]

@dataclass(frozen=True)
class TrackingMarkerV1:
    schema_version: Literal["m3-tracking-marker-v1"]
    tracking_target_key: str
    tracking_key: str
    request_sha256: str
    mlflow_run_id: str
    artifact_digest_sha256: str
```

先从 verified work artifacts 构造 strict request，递归拒绝敏感键/值和绝对路径，再原子发布 request。URI 与
experiment name 只形成 C0 `tracking_target_key`，不写稳定明文；request hash+work key 通过唯一具名函数形成
tracking key。null scientific metrics 不上传为 MLflow numeric metric，完整 metrics JSON 仍作为 artifact；
上传 metrics 必须 finite。

持有 `(target,key)` flock 后查询精确 tag：0 个才创建；1 个只有 FINISHED 且 request/artifact hash 一致才恢复；
RUNNING/FAILED/KILLED、多匹配、内容冲突均失败且不创建第二个。创建 run 的首个 remote write 必须携带
`quant_tracking_key`。remote 成功、marker 前崩溃后重跑恢复同 run ID。artifact 上传保持相对层级。

fake 覆盖 0/1/2、四状态、崩溃点、双进程、切换 URI、同名 metrics 文件、嵌套 secrets 和异常 URI 脱敏。

## 6. G8E：fresh-process reproducibility

文件：新增 `reproducibility.py`、worker protocol、单测和两份报告。

父进程构造 comparison key，顺序启动两个全新 WSL base Python。attempt 只读 verified feature/alignment/label/
config/code/dependency，禁止读取正常 work model/prediction/evaluation 或另一 attempt。每次独占 cache/temp，
执行 train→predictions→evaluation，输出 stage-owned attempt tree 和 `read_audit.json`；PID 只由测试实时观察，
不持久化。

父进程从原始输出重算：prediction key/顺序精确一致；score max abs≤配置；metrics key 集一致、nullable 位置
一致、finite 值差≤配置。模型/Parquet bytes 可不同，不能只比 hash，也不能复制同一模型两份。任一 attempt
失败或缺文件不发布 comparison。根 `reproducibility.json` 和 REPRO receipt strict/no-clobber。

## 7. G8F：fake 全 DAG 集成

文件：`tests/integration/test_m3_orchestration.py` 与两份报告。严格 fake 跑 2 folds×2 horizons，至少证明：

1. shared 各一次、每 fold 一个 feature、四 work 独立，新增四个 `backtest_plan`；
2. 一个 prediction 失败不污染其他 work，resume 只运行未完成依赖；
3. 篡改完成 artifact/receipt、漏 output、多读路径、symlink/hardlink、错 scope/key 都 fail-closed；
4. snapshot→provider→experiment→work→summary continuation 无占位 identity 或目录扫描；
5. tracking URI、成本、LightGBM、provider runtime/字段、validation tolerance 分别只失效正确 identity 层；
6. stage 目录 publish 各故障点、orphan 相同/不同、两个 writer；snapshot 另覆盖 content dir 已发布但
   request record/receipt 前崩溃、record 指错 ID、同 request 冲突和同 content ID 复用；
7. stdout 单 JSON，summary/receipt/manifest 不含绝对路径或 secret；
8. domain/strategies/backtest import 不加载 Qlib/LightGBM/MLflow。

## 8. 外部闭环与顺序

```text
G8A → G8B → formal backtest WORK wave → formal tracking WORK wave → G8C CLI增量 → G8E → G8F → 真实 handlers continuation 主验
```

每包“外部实现自测 → 未参与实现的外部只读初验 → 返工迭代 → 主 Agent 终验”。G8A–G8F 均分别交付，
不得一次实现全部。固定报告名使用 `M3_G8A...交付报告/独立初验报告.md` 至 `M3_G8F...`，具体标题分别为
Stage计划、StageRunner、CLI、Tracking、冷启动复现、全DAG集成。

每包定向后运行 WSL base 全量 pytest、Ruff、mypy。fake 通过只证明框架；缺真实 G1–G7 handler、Qlib、
LightGBM 或 MLflow 时如实报告，不安装依赖、不造假 receipt、不更新路线图。
