
| Command | Required identity args | Stop stage |
|---|---|---|
| `readiness` | `--g1-release-id` | readiness；不生成 snapshot |
| `snapshot` | `--g1-release-id` | snapshot；输出 snapshot ID，不生成 provider |
| `train` | `--snapshot-id --fold --horizon` | 自动验真/生成 provider/shared/features，止于 train |
| `evaluate` | `--snapshot-id --fold --horizon` | 止于 evaluation |
| `backtest` | `--snapshot-id --fold --horizon [--no-resume]` | 止于 backtest，不登记 MLflow |
| `tracking` | `--snapshot-id --fold --horizon [--no-resume]` | fresh 验真既有 evaluation/backtest，止于单 work tracking |
| `run-all` | `--g1-release-id` 或 `--snapshot-id` 二选一 | 所有 work 止于 tracking |
| `verify-reproducibility` | `--snapshot-id --fold --horizon` | 两个冷启动 attempt 与 comparison receipt |
| `acceptance-audit` | `--snapshot-id` | 重算 provider/experiment identity，执行固定质量命令与 G0–G9 审计；只在全通过时发布 acceptance receipt |

当前 G8C CLI 按最小职责拆为串行 C0/C1/C2：C0 仅从 `project_root + loaded config + snapshot_id + fold + horizon`
按具名 identity/path 调用 public verifier，重建 formal backtest wave 所需的 process-local verified values 与 fresh
context；它零写入、禁止扫描目录、禁止生成任何缺失 stage。C1 把 public `backtest` 接到
`load_m3_config` → `resolve_formal_backtest_cli_inputs` → `run_formal_backtest_stage`，仅新增
`--no-resume`，成功输出一行 canonical JSON（`reused`/`work_key`/`stop_stage=backtest`），失败走
`CommandSummary` 稳定码。C1 的 Windows honest 300 最终 revision 已完成同一次首发与 completed resume。
C2 新增窄 `tracking` 命令：只在完整本地 fresh resolution 成功后从 config 的 canonical URI 惰性创建 production
MLflow client，再调用 actual G8D-F1 StageRunner；caller 不能传 URI/client/path/capability。`train`、`evaluate`、
`run-all`、`verify-reproducibility` 仍为 `M3_COMMAND_HANDLER_UNAVAILABLE`；`acceptance-audit` 已接 production
read-only tracking verifier。任何跨进程执行都必须在新进程内重新 resolve，禁止 pickle 或传递 verified capability。

提供 snapshot ID 时只验真/复用已有 snapshot，不回退 G1 构建；提供 G1 release 时按分段计划生成或复用。
stdout 只输出一份规范 JSON，所有 warning/log 写 stderr。退出码：0 成功或验真复用；2 参数/配置/契约；
3 readiness/G1/snapshot 数据门禁；4 Qlib/LightGBM/MLflow 等依赖不可用；5 本地 stage/receipt；6 tracking；
7 冷启动比较；8 质量或最终验收。同一命令有多类失败时 summary 全列，进程取最小非零 code；code 2
在执行前返回且不写产物。

`params` 和 `tags` 的安全检查必须递归遍历 Mapping/Sequence，检查所有嵌套键和字符串值；
`token,password,secret,api_key,apikey`、Bearer/token 内容和绝对本机路径在任意嵌套层级都必须
被拒绝。依赖版本、模型参数等结构化值可记录，但不得把未筛选的整份项目配置传入
tracking 层。artifact 路径必须在打开 MLflow run 前全部校验存在，避免留下部分记录。

`run_m3` 是薄编排器，不包含因子、标签、训练或回测算法。运行身份分成三层；Qlib provider 是 snapshot
的确定性派生产物，使用独立 `provider_key`，不向不可变 snapshot 目录追加文件：

```text
snapshot_dir  = artifacts/research/m3/snapshots/<snapshot_id>/
provider_key   = compute_provider_key(...)
provider_dir   = artifacts/research/m3/providers/<provider_key>/
experiment_key = compute_experiment_key(...)
experiment_dir = artifacts/research/m3/runs/<experiment_key>/
work_key       = compute_work_key(...)
work_dir       = <experiment_dir>/work/fold=<fold>/horizon=<horizon>/
```

`scientific_config_hash` 只覆盖 4.0 冻结的精确 selector：`runtime.qlib.version`、完整 `data`、`features`、
`labels`、`walk_forward`、`model.lightgbm`、`evaluation`、`portfolio`、`backtest.a_share`、`costs`；排除 tracking URI、
dump tool URL/hash/bytes、supported-python policy、artifact 物理根路径、validation/验收阈值和注释。配置解析器拒绝这些子树内的未知键、缺失必需键和错误类型。snapshot manifest
只记录 4.0 的 narrow `snapshot_config_sha256`；`provider_config_hash` 只覆盖 market/frequency/provider
fields/format。Qlib version、实际 runtime fingerprint 与 dump tool hash 作为独立 provider-key 字段加入，
不重复放入 provider config hash。改变 tracking URI 不改变任何科学 identity；改变费用只改变 experiment/
work；改变 provider 字段、Qlib version、runtime 或 dump tool 改变 provider/experiment，但不伪造新的 snapshot。
`code_version` 优先使用可验证的 Git
commit + dirty tree hash；仓库元数据不可用时，退化为本次运行涉及的 `src/quant` 与版本化配置文件的
“相对路径 + 文件 SHA-256”规范化集合 hash，禁止写固定的 `unavailable` 造成缓存碰撞。

readiness 同时发布 provider 子集和完整 dependency fingerprint。provider subset 至少包含 Python、NumPy、
pandas、PyArrow、Qlib、Fire、tqdm、Loguru 的实际版本，进入 provider key；其中任一变化必须重建
provider。完整 `dependency_fingerprint_sha256` 另包含平台、`pyproject.toml` hash、Polars、SciPy、
scikit-learn、LightGBM 等所有参与研究/回测的版本或明确 `NOT_INSTALLED`，进入 experiment/work。只改
LightGBM 可复用 provider、不能复用 experiment；改 NumPy/pandas/Qlib 两层都必须变化。MLflow 另记录
可读依赖清单，但 identity 只使用稳定 hash。

snapshot 是内容寻址产物，因此编排使用显式 continuation，不能在上游身份尚未发布时伪造下游计划。
第一段负责产生 `snapshot_id`：以
`snapshot_request_key=compute_snapshot_request_key(...)`
在 `snapshot-builds/<snapshot_request_key>/` 执行 readiness/staging；manifest 验真后才计算 `snapshot_id`，
再把完整 staging 目录原子发布到 `snapshots/<snapshot_id>/`，并写不可变
`snapshot-requests/<snapshot_request_key>.json` 映射。第二段读取已验真的 snapshot manifest，计算
`provider_key` 并执行 provider；再以 provider receipt、`provider_validation_config_sha256`、runtime/code 形成独立
provider-validation key 并发布 probe 证据。第三段要求 provider-validation PASS 后继续，但只由已验真的
snapshot/provider receipts 与科学身份计算并发布 experiment identity；随后发布 labels、G3 reconciliation 与
folds shared evidence，其中 reconciliation 独立绑定 provider-validation receipt。第四段读取 folds receipt，构造每-fold shared
features 与 fold×horizon work；第五段只在所需 evaluation receipts 完整后构造 research summary。
请求映射已存在时，必须验真目标 snapshot 后复用；
映射或目标损坏时 fail-closed，不重指向另一个 snapshot。

snapshot 发布是 StageRunner 唯一受控的内容寻址特例：先目录级 no-clobber 发布完整 snapshot，再
no-clobber 发布 strict request record，最后发布 `stage="snapshot"/scope="SNAPSHOT"` receipt。receipt inputs
精确为 G1 manifest 与实际读取的 bar/membership/calendar，outputs 精确为 request record、snapshot manifest、
session calendar 与全部 staging 文件。中间崩溃只允许在完整内容逐字节相同时认领；任何冲突不得覆盖。

- 每一步只读取声明依赖的已发布产物，写入本 stage 的临时目录，校验后以原子 rename 发布；最后写
  `<stage>.complete.json`，其中列出输入/输出相对路径及 SHA-256。完成标记不得先于产物出现。
- 重跑遇到完成标记时必须重新校验所有 hash；全部一致才复用，缺失或不一致立即失败，不静默覆盖。
- 未完成标记对应的临时文件可清理后重算。若崩溃发生在产物 rename 后、receipt 发布前，重算结果与
  orphan 产物逐字节一致时可补发 receipt；任何内容冲突都必须失败，不得覆盖。已发布且 hash 不符的文件
  不可就地修补，必须通过改变
  snapshot/config/code 形成新的 snapshot/experiment/work key。
- snapshot 作用域固定为 `readiness -> snapshot`，随后在独立 provider_dir 执行
  `provider -> provider_validation`；experiment 共享作用域为每个 horizon 独立的 `labels[h]` 与 `folds`；
  folds receipt 发布后，每个 fold 只有一个 experiment-scoped `features[fold]`，由该 fold 的 h=5/h=10
  work 共享；work 作用域固定为
  `alignment -> train -> predictions -> evaluation -> targets -> backtest_plan -> backtest -> tracking`。全部 work evaluation
  完成后可构造 `research_summary[h]`，只聚合不重叠 test daily IC。子命令可以止于某
  stage，但不能跳过依赖、跨作用域偷读未声明文件或伪造完成标记。
- `features.<fold>` 的 provider-validation receipt 只作 DAG dependency gate，不进入 feature handler 内容输入；
  它使用 `EXPERIMENT/experiment_key`，由 node id/fold 区分，同 fold 两 horizon 必须引用同一 receipt。fold 的
  signal window 只从 snapshot request/manifest 继承，prediction/evaluation/summary 只接受 G4–G6 冻结的 strict
  manifests/metrics 和精确 receipt 闭包，不接受 caller 自报 selector hash 或宽松 Mapping。
- `run-all` 先验证共享作用域，再按 `(fold name ASC,horizon ASC)` 枚举 work unit。某 work 失败后跳过其
  下游，但继续其他独立 work；`folds` 失败阻止全部 work，某个 `labels[h]` 失败只阻止该 horizon 的 work。
  命令返回非零并输出结构化失败清单，重跑只恢复未完成 work。
- MLflow 是每个 work 的最后登记步骤。本地产物及 hash 全部验证后才打开 run；成功 run ID 写入本地
  marker。每个 work 的 tracking 文件位于 `work/<work_key>/tracking/`，精确为
  `tracking_request.json` 与 `tracking_marker.json`；receipt 位于 `receipts/tracking/<work_key>.json`。其中
  `tracking_target_key` 只能由 C0 `canonical_tracking_target_key` 计算；request 只记录 target key，不记录
  原始 URI 或凭据。这样切换 MLflow server 不改变科学 experiment/work identity，但也不会误复用旧 server
  的 marker。`request.json` 必须包含 work key、过滤后的 params/tags/metrics 与所有 artifact digest；
  `tracking_key` 只能由 `compute_tracking_key(work_key=...,request_sha256=...)` 的规范 JSON 数组编码计算；
  以该 key 查询 MLflow：0 个匹配才新建；1 个 `FINISHED`
  且 request/artifact hash 完全匹配才恢复 marker；`RUNNING`、`FAILED`、`KILLED`、内容不符或多于 1 个
  都 fail-closed，禁止用同一 tracking key 创建第二条记录。创建 run 时必须通过 `start_run(tags=...)` 或
  等价 create API 在首个服务端写操作中附带 `quant_tracking_key`，不能先创建再 set_tag。个人单机版还需
  对 `(tracking_target_key,tracking_key)` 使用 WSL `flock` 互斥，锁目录位于 stage root 的
  `.tracking-locks/`，不得进入上述两文件发布树，避免两个本地进程同时观察到 0 个匹配；
  跨主机并发不在 M3 保证范围并须在报告披露。只重试 tracking，不重新训练。

`verify_stage_receipt` 只能返回两种成功状态：receipt 不存在返回 `None`；receipt 存在且每个输入输出
hash 均一致时返回对象。receipt 存在但 JSON 非法、路径越界、文件缺失、大小或 hash 不一致时必须
抛出错误，不得把损坏状态解释为“尚未运行”。每个 digest 以 `root_alias + relative_path` 定位；alias
必须存在于调用方显式传入的 `artifact_roots`，路径必须是该 root 内相对 POSIX 路径。每个 root 必须存在、
为目录且自身非 symlink；root 到文件的任一组件出现 symlink 均拒绝，即使最终仍在 root 内。另拒绝未知 alias、
`..`、绝对路径、重复 `(alias,path)` 及 inputs/outputs 交叉重复。这样 work receipt 可以审计 snapshot/provider/
experiment 输入，又不复制大文件或把上级路径写成本机绝对路径。receipt 自身永远不列入自身 outputs。

Receipt 的严格语言与发布语义进一步冻结如下：读取端必须拒绝任意层级 duplicate JSON key、未知或缺失字段、
NaN/Infinity、bool 冒充整数、字符串数字和非规范 JSON 字节；合法 receipt 的原始字节必须恰等于以
`sort_keys=true,separators=(",",":"),ensure_ascii=true,allow_nan=false` 重编码的结果。`ArtifactDigest` 与
`StageReceipt` 直接构造也必须执行同一套值对象校验，不能只在文件 parser 中校验；`inputs/outputs` 必须
是 exact tuple 且元素必须是 `ArtifactDigest`。值对象只验证版本、scope、identity、类型、排序和逻辑重复；
root、文件存在性、物理身份与内容 hash 由 publish/verify 的上下文校验负责。输入、输出分别按
`(root_alias,relative_path)` 严格升序且唯一；同一物理 root 不得用两个 alias 重复注册，root 自身及从已有
文件系统锚点到 root、从 root 到 artifact/receipt 的任一已有组件均不得是 symlink。相对路径必须是未
规范化前后完全一致的 POSIX 表示，拒绝 `.`、`..`、空段、反斜杠、盘符/UNC、控制字符和 `:`。
不同 root 允许按真实目录布局嵌套，但 verifier 必须以普通文件的稳定物理身份补充去重，拒绝同一现有文件
借由“父 root 相对路径/子 root 相对路径”或 hard-link 同时/重复进入 digest 集合。`receipt_path` 必须位于
至少一个显式 artifact root 内，其父目录必须已经存在且通过同一 no-symlink 目录校验；publish 不负责创建
任意未声明父目录。receipt 自引用在 inputs 与 outputs 任一侧都拒绝，并按物理文件身份判断，不能只比较
路径字符串。完整 `artifact_roots` 必须在读取任一 digest 前全部验真，不能只检查实际被引用的 root。

规范读取算法固定为 `read_bytes -> strict UTF-8 decode -> duplicate-aware JSON parse（parse_constant 拒绝）
-> strict object construction -> canonical encode -> 原始 bytes 精确比较`；BOM、CRLF、尾随换行和仅字段顺序
不同均非法。物理文件身份使用 `lstat` 后的 `(st_dev,st_ino)` 或 `os.path.samestat` 等价语义；不能用
`resolve()` 或内容 hash 冒充 hard-link 身份，无法可靠取得时 fail-closed。verify 必须先验证 root registry、
receipt containment、parent 与 leaf 的 lstat；只有 leaf 真正 ENOENT 才返回 `None`，dangling symlink 不是缺失。

消费者同时需要 parsed receipt 与 receipt hash 时，必须使用共享
`verify_stage_receipt_with_bytes`，不得在下游复制第二套 verifier。该入口对 receipt 使用同一
打开文件描述符完成读取、parse 和 hash，并复用本节完整 root registry 和 digest 物理身份契约。
嵌套 roots 从路径反推 alias 时选择包含该路径的最具体子 root；同一物理 root 的重复 alias
仍在任何 digest 读取前失败。

发布端不得以 `os.replace` 覆盖并发进程刚发布的 immutable receipt。固定流程为：同目录临时普通文件写入
并 `fsync`，再次验真声明 artifact，以 Linux/WSL 的原子 no-clobber 创建（例如同文件系统 `os.link`），
并发目标已存在时只允许“规范字节相同且现有 receipt 全量验真通过”复用，否则冲突失败；最后清理临时文件
并尽力 `fsync` 父目录。禁止回退到覆盖式 replace。单个 receipt 原子发布不等于多 artifact 跨文件事务，
artifact 在验真后被外部修改的 TOCTOU 仍由再次验真 fail-closed 暴露，交付报告不得夸大保证。
`os.link` 只有 `FileExistsError` 可进入并发复用分支；其他错误必须脱敏失败且不得 fallback。临时文件清理
失败不能覆盖主异常。父目录 fsync 只可忽略 `EINVAL/ENOTSUP/EOPNOTSUPP` 这类明确“不支持”错误；其他错误
以稳定消息失败。若 receipt 已原子创建后目录 fsync 才失败，文件保持原状，重试必须重新验真后复用。

编排骨架使用显式静态 DAG，不允许根据目录中“看起来存在”的文件动态猜依赖：

```python
@dataclass(frozen=True)
class OutputSpec:
    relative_path: str
    kind: Literal["FILE", "TREE"]
    closure_manifest: str | None

@dataclass(frozen=True)
class StageSpec:
    name: str
    scope: Literal[
        "SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "REPRO", "ACCEPTANCE"
    ]
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
    scope: Literal[
        "SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "REPRO", "ACCEPTANCE"
    ]
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

@dataclass(frozen=True)
class StageFailure:
    node_id: str
    scope: Literal[
        "SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "REPRO", "ACCEPTANCE"
    ]
    scope_key: str
    work_key: str | None
    fold: str | None
    horizon: int | None
    stage: str
    error_code: str
    message: str

@dataclass(frozen=True)
class RunSummary:
    snapshot_id: str | None
    provider_key: str | None
    experiment_key: str | None
    completed_node_ids: tuple[str, ...]
    reused_node_ids: tuple[str, ...]
    failures: tuple[StageFailure, ...]

def build_snapshot_plan(
    *, release: VerifiedG1Release, config: LoadedM3Config,
) -> RunPlan: ...

def build_provider_plan(
    *, snapshot: VerifiedSnapshotArtifact, config: LoadedM3Config,
) -> RunPlan: ...

def build_experiment_plan(
    *, snapshot: VerifiedSnapshotArtifact, provider: VerifiedProviderArtifact,
    provider_validation: VerifiedProviderValidationArtifact,
    config: LoadedM3Config,
) -> RunPlan: ...

def build_work_plan(
    *, experiment: VerifiedExperimentIdentity,
    folds: VerifiedFoldPlanArtifact,
    labels: Sequence[VerifiedLabelArtifact],
    config: LoadedM3Config,
) -> RunPlan: ...

def build_summary_plan(
    *, experiment: VerifiedExperimentIdentity,
    evaluations: Sequence[VerifiedEvaluationArtifact],
    config: LoadedM3Config,
) -> RunPlan: ...

def execute_m3_plan(
    *, plan: RunPlan, config: LoadedM3Config,
    handlers: Mapping[str, StageHandler],
    artifact_roots: Mapping[str, Path], resume: bool,
) -> RunSummary: ...
```

`StageSpec` 是唯一的 stage 类型 registry；`StageNode` 是完全解析后的执行实例。`node_id` 在整个 plan 内
唯一，依赖引用 node_id，fold/horizon 不得偷偷编码进 experiment key。计划构造时校验 DAG 无环、stage-owned
输出目录无嵌套/冲突、所有输入都有显式 producer 或受信外部 digest。continuation 边界外输入必须使用
`ExternalInput`；同一 plan 内尚未产生的输入使用 `StageOutputInput`，runner 执行时从 producer 的已验真
receipt 解析实际 digest，禁止 builder 或调用者预填未知 hash。handler 只接收解析后的 inputs 与空临时目录，
禁止自行扫描 artifact tree。`node_id` 只允许小写 ASCII 字母、数字、点、下划线和连字符；每个 producer
引用必须同时出现在 dependencies 中，且路径被 producer output spec 覆盖。receipt 固定在 output directory
外的同 scope `receipts/` 目录。目录型 output 在 plan 中解析到唯一受控目录；发布 receipt 时必须递归列出其中
每个普通文件，拒绝符号链接和未声明目录外产物，不能只对目录名做 hash。fold 定义只来自已验真的
`VerifiedFoldPlanArtifact`；experiment plan 只发布 labels/folds 共享证据，不枚举 work。只有 folds artifact
验真后才能构造 work plan。若解析结果与已发布文件不一致，必须因 receipt/input hash 冲突失败。计划构造函数是纯函数，
CLI 在构造任何 plan 前恰调用一次 `load_m3_config`；runner 与 handler 只接收同一个
`LoadedM3Config`/只读 section，不再打开配置路径。
不得调用 stage handler 或扫描目录，因此不存在把未发布对象当作规划前置的循环。

StageRunner 验证 receipt 时不仅复算 receipt 自报文件的 hash，还必须把 receipt 的 stage/scope/scope_key、
解析后的 inputs、逐文件 outputs 与对应 `StageNode` 的期望闭包逐项比较；合法 hash 但漏 required output、
换 scope key 或增加未声明输入同样失败。每个多文件 stage 独占最终目录；runner 持有
`(scope,scope_key,node_id)` 的 WSL `flock`，锁内复验后用 Linux/WSL
`renameat2(RENAME_NOREPLACE)` 或语义等价 primitive 原子发布整个目录，再 fsync parent、最后发布 receipt。
运行时不支持目录级 no-clobber 时 fail-closed；禁止回退到 `os.rename`、逐文件 merge 或覆盖式发布。
