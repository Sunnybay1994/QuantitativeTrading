# M3 G8D-F1 R1：正式 Tracking StageRunner 单 WORK Wave 任务单

日期：2026-08-10

状态：**R2 工程主验 PASS；formal Tracking StageRunner 单 WORK wave 已闭合；真实 MLflow、Linux ext4、G8 后续包与 M3 Gate 仍开放**

## 1. 唯一目标与前置

本包只闭合一个已拥有 formal `VerifiedEvaluationArtifact` 与 `VerifiedBacktestArtifact` 的 work 尾波：构造 strict、无秘密的 `TrackingRequestV1`，使用显式 fake-friendly tracking client 做远端幂等登记，在 StageRunner 分配的临时目录内生成 exact 两叶，并发布 `tracking` WORK receipt。

前置已满足：G8 R1 formal backtest StageRunner、G8A registry、G8B StageRunner、G6A formal evaluation、G7F formal backtest artifact 和 development tracking journal 均已有工程验收。Linux ext4、真实 G1、真实 MLflow、public CLI、G8E/G8F 不是本包工程实现前置，仍是后续 Gate。

本包禁止实现 CLI、`run-all`、summary、reproducibility、G8F、G9 或真实 MLflow 集成；禁止把多个 G8 高风险边界合包。

## 2. 权威 API

在 `quant.research.m3.tracking` 新增：

```python
@dataclass(frozen=True)
class FormalTrackingFreshVerificationContext:
    evaluation_context: EvaluationFreshVerificationContext
    evaluation_receipt_path: Path
    target: VerifiedTargetArtifact
    plan: VerifiedBacktestPlanArtifact
    release: VerifiedG1Release
    experiment: VerifiedExperimentIdentity
    backtest_context: BacktestArtifactFreshVerificationContext
    backtest_receipt_path: Path

def formal_tracking_input_paths(
    *, evaluation: VerifiedEvaluationArtifact,
    backtest: VerifiedBacktestArtifact,
    fresh_context: FormalTrackingFreshVerificationContext,
) -> tuple[Path, ...]: ...

def formal_tracking_upload_paths(
    *, evaluation: VerifiedEvaluationArtifact,
    backtest: VerifiedBacktestArtifact,
) -> tuple[Path, ...]: ...

def build_formal_tracking_request(
    *, evaluation: VerifiedEvaluationArtifact,
    backtest: VerifiedBacktestArtifact,
    config: LoadedM3Config,
    fresh_context: FormalTrackingFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> TrackingRequestV1: ...

def register_remote_tracking_run(
    *, request: TrackingRequestV1,
    request_sha256: str,
    tracking_uri: str,
    experiment_name: str,
    artifact_roots: Mapping[str, Path],
    lock_root: Path,
    client: TrackingClientProtocol | None = None,
) -> TrackingMarkerV1: ...
```

`FormalTrackingFreshVerificationContext.__post_init__` 必须 exact-type 校验全部值，两个 receipt path 必须为 `Path`，并拒绝 pickle。不得存储 URI、client、caller digest 或输出路径。

`register_tracking_request` 保持现有 public 行为兼容；内部可复用无本地文件写入的远端登记核心。其默认锁语义保持 development 测试绿色。不得删除/改名现有 API。

新增 `quant.research.m3.tracking_stage`：

```python
@dataclass(frozen=True)
class FormalTrackingStageResult:
    final_root: Path
    receipt_path: Path
    request: TrackingRequestV1
    marker: TrackingMarkerV1
    receipt: StageReceipt
    reused: bool

def make_formal_tracking_run_plan(
    *, evaluation: VerifiedEvaluationArtifact,
    backtest: VerifiedBacktestArtifact,
    config: LoadedM3Config,
    fresh_context: FormalTrackingFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> RunPlan: ...

def run_formal_tracking_stage(
    *, stage_root: Path,
    evaluation: VerifiedEvaluationArtifact,
    backtest: VerifiedBacktestArtifact,
    config: LoadedM3Config,
    fresh_context: FormalTrackingFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
    client: TrackingClientProtocol,
    resume: bool = True,
) -> FormalTrackingStageResult: ...
```

formal `run_*` 必须显式传入 client，不得在本包隐式创建真实 MLflow client或联网。未来 CLI 可显式调用现有 lazy adapter 后传入。

## 3. Fresh 验真与身份闭包

`build_formal_tracking_request` 与每次 `run_formal_tracking_stage` 入口必须：

1. 精确一次调用 public `verify_evaluation_artifact`，参数来自 `evaluation_context`、outer `config`、`evaluation_receipt_path` 与 `artifact_roots`；
2. 精确一次调用 public `verify_backtest_artifact`，参数来自 `target/plan/release/experiment/backtest_context`、outer `config`、`backtest_receipt_path` 与 `artifact_roots`；
3. fresh evaluation 必须与 outer evaluation 的 resolved root、`daily.equals`、metrics、manifest、manifest SHA、receipt SHA 全字段相等；fresh backtest 必须与 outer backtest 的 resolved root、metrics、manifest、manifest SHA、receipt SHA 全字段相等；
4. 两个 fresh artifact 的 `work_key/experiment_key/scientific_config_sha256/fold/horizon/model lineage` 必须形成唯一一致链；evaluation context 的 release/experiment/config identity 必须与 backtest context及 outer config exact 一致；
5. 后续只使用 fresh 返回值构造 request。formal/development 混配、copied root、同 hash 自报或合法另一 work 的整套 capability 均拒绝。

`make_formal_tracking_run_plan` 只做 exact 类型/身份与物理 34-input digest 解析，不重复调用两个 verifier。StageRunner handler、local closure 与 final local verifier也不得再次调用两个上游 verifier或缓存 caller capability。每次独立 `run_*` 调用重新执行入口各一次。

## 4. Exact 34-input receipt 与两叶输出

`formal_tracking_input_paths` 的物理集合必须精确为 34 个唯一 regular files：

- evaluation root：`daily_ic.parquet`、`evaluation_manifest.json`、`metrics.json`；
- `evaluation_receipt_path`；
- backtest root：`backtest_artifact_output_relative_paths()` 的全部 29 leaves；
- `backtest_receipt_path`。

按 `(root_alias,relative_path)` canonical 排序形成 34 个 `ExternalInput`，且物理 `(st_dev,st_ino)` 唯一。路径必须属于唯一不嵌套 artifact root；symlink/junction/reparse/hardlink、少/多/alias、同字节换 inode、调用中替换均 `STAGE_INPUT_INVALID`。experiment manifest、TOML、URI 文件不进入 receipt；其 identity 已由 fresh manifests/config 内存值绑定。

formal plan 恰一个节点：

- continuation=`WORK`；node id=`tracking.<fold>.h<horizon>`；spec=`TRACKING_STAGE_SPEC`；scope=`WORK`；scope key=`work_key`；dependencies=空 tuple；
- publication=`work/<work_key>/tracking`；receipt=`receipts/tracking/<work_key>.json`；
- outputs exact sorted `tracking_marker.json`,`tracking_request.json`。

不得修改 `TRACKING_STAGE_SPEC`、receipt schema、StageRunner publish primitive或 G8 R1 formal first wave。

## 5. TrackingRequestV1 精确内容

request 顶层 `tracking_target_key` 只取 `config.tracking_target_key`，并必须等于对 `config.canonical_tracking_uri` 与 tracking section `experiment_name` 调用 `canonical_tracking_target_key` 的结果；顶层 `work_key` 取唯一 work。request 及公开错误不得记录 URI 明文。

`params` exact 22 keys，值统一为稳定 string、按 key 排序：

```text
backtest_manifest_sha256
backtest_plan_manifest_sha256
backtest_receipt_sha256
eligible_keys_sha256
evaluation_dates_sha256
evaluation_manifest_sha256
evaluation_receipt_sha256
experiment_key
feature_manifest_sha256
fold
fold_plan_manifest_sha256
g1_release_id
g1_release_manifest_sha256
horizon_sessions
label_manifest_sha256
model
model_version
prediction_manifest_sha256
scenario_count
scientific_config_sha256
target_manifest_sha256
work_key
```

`scenario_count` exact `"3"`。`tags` exact为 `formal_gate_eligible="true"` 与 `release_kind="formal"`；禁止 `example_id`、development值、protected tags或caller扩展。

`metrics`：

- `evaluation.<field>` 包含 `EvaluationMetricsV1` 的全部 finite int/float 字段；nullable字段仅非空时上传；不把 `status_counts`、schema或字符串转成 numeric metric；
- `backtest.<scenario>.<field>` 对 `0p5x/1p0x/2p0x` 按冻结顺序提取各 `AShareScenarioMetricsV1` 全部 finite int/float字段，nullable仅非空时上传；
- 所有 key canonical 排序，NaN/Infinity/Decimal ambient漂移均拒绝。

`request.artifacts` 是 MLflow 上传 allowlist，不等于 34-input receipt。exact 11 files：evaluation 三叶；backtest root 两个 JSON；三个 scenario 各 `metrics.json` 与 `manifest.json`。其余 18 个 scenario Parquet 只进入34，不上传。每项 `ArtifactDigest` 必须按真实 artifact root alias/relative path、size、SHA重建并排序；禁止合成 `evaluation`/`backtest` 虚假 alias、绝对路径或 caller digest。

## 6. 单一发布与远端幂等登记

现有 `register_tracking_request` 会写 request/marker，并在 `marker.parent/.tracking-locks` 建锁；直接用于 StageRunner temp 会污染 exact 两叶，禁止这样装配。

`register_remote_tracking_run` 必须不写 request/marker 文件：校验 request SHA 与 canonical request bytes、重验11个artifact bytes，在显式 `lock_root` 下持锁后执行现有 0/1/2 remote语义。formal handler顺序冻结为：

1. 在 temp 发布 canonical `tracking_request.json`，取得 request SHA；
2. 调 `register_remote_tracking_run`，lock root exact派生为 `stage_root/.tracking-locks/<tracking_target_key>/<tracking_key>`，不得在 temp/final树内；
3. 在 temp no-clobber发布 canonical `tracking_marker.json`；
4. 返回 exact两叶 `StageBuildReport`；
5. StageRunner负责 temp→final原子发布与34-input/两输出receipt。

远端语义保持：0匹配才create，首个remote write携带全部protected identity tags；1个仅FINISHED且全部tag/hash一致可复用；RUNNING/FAILED/KILLED、tag冲突、多匹配均fail-closed且不创建第二run。remote成功、marker前崩溃后重跑必须恢复同run id。跨主机并发不保证，但同stage root双writer由StageRunner锁与tracking key锁共同串行。

## 7. Local closure、恢复与调用次数

local closure只验 exact两叶、canonical bytes、request全字段、marker的target/tracking/request/artifact hash与预期一致、tree identity稳定；不得查询remote或重跑上游 verifier。final local verifier再验 `tracking`/`WORK`/work_key receipt exact34/2。

每次 public run 入口上游 verifier固定各1次。StageRunner路径：

- 首次：handler1，local closure2(temp/final)，final local verifier1；
- completed resume：handler0、remote调用0，closure1、final1；
- `resume=False` completed：handler0、remote0；按实际primitive可能closure1，然后`STAGE_ALREADY_COMPLETE`，final0；
- 完整orphan：closure(existing)1、handler1（remote查询恢复）、closure(temp/final)2、final1；
- partial/different/hostile路径到首个失败即停，不继续后续remote/closure/final。

有效receipt复用不重新查询remote；本地run directory是SSOT，G9另行连接当前tracking target验证remote current状态。

## 8. 稳定失败与零泄漏

formal public stage边界只返回 `M3StageRunnerError` 既有 codes：`STAGE_INPUT_INVALID`、`STAGE_LOCK_FAILED`、`STAGE_BUILD_FAILED`、`STAGE_OUTPUT_INVALID`、`STAGE_PUBLISH_FAILED`、`STAGE_RECOVERY_CONFLICT`、`STAGE_ALREADY_COMPLETE`。所有公开失败 `cause/context` 为空，不回显URI、路径、TOKEN、PID、client repr或remote原始异常。

tracking target/identity/fresh/34-input问题在创建runner/remote前映射 INPUT；remote冲突/异常映射 BUILD；temp两叶闭包映射 OUTPUT；final/receipt/resume漂移映射 RECOVERY。失败不得留下receipt或半套final；StageRunner拥有temp清理，formal wrapper不得越权删除foreign内容。

## 9. 文件白名单

外部实现 Agent只允许修改/新增：

1. `src/quant/research/m3/tracking.py`；
2. `src/quant/research/m3/tracking_stage.py`；
3. `src/quant/research/m3/__init__.py`，仅惰性安全导出；
4. `tests/unit/test_m3_g8d_f1_formal_tracking_stage.py`；
5. `tests/integration/test_m3_g8d_f1_formal_tracking_stage_golden.py`；
6. `docs/framework/agent/M3_G8D_F1_R1正式TrackingStageRunner交付报告.md`；
7. 本任务单仅由主 Agent 更新状态。

禁止修改 evaluation/backtest/G8 R1 production与tests、`orchestration.py`、`run_state.py`、StageRunner publish、contracts/schemas/config、`run_m3.py`、MLflow依赖、路线图、正式 artifacts及已同步SSOT。若真实接口要求扩大白名单，立即停止回报。

独立初验只允许新增 `docs/framework/agent/M3_G8D_F1_R1正式TrackingStageRunner独立初验报告.md`。主 Agent只新增最终验收报告。

## 10. 必测矩阵与独立反例

实现测试至少覆盖：

- exact 34 ExternalInputs、两叶输出、11 upload allowlist、22 params、2 tags和完整finite metrics；
- formal/development混配、eval/backtest不同work/fold/horizon/experiment/config、fresh返回合法另一对象；
- 34少/多/alias/同字节异inode、11少/多/误传29、hardlink/symlink/reparse/nested roots；
- remote 0、1 FINISHED、1四类非成功/冲突、2匹配；create首写protected tags；remote成功marker前崩溃恢复同ID；
- 首次/resume/no-resume/orphan/partial/different，逐路径上游 verifier、handler、remote、closure、final调用顺序与独立nonce；
- 双writer、request/marker writer故障、hostile client/Mapping/递归异常图、caller Decimal context；
- final tree不得出现`.tracking-locks`或extra目录；冷导入不得加载mlflow/Qlib/LightGBM。

独立初验必须增加实现者未用反例，重点：pre(final)后final前换marker、remote FINISHED但额外protected tag漂移、同字节request换inode、orphan tree合法重签但fresh request不同、两个不同stage root同target/key的边界说明，以及request artifact上传相对层级。

## 11. 双平台验证

Windows Miniforge先运行新unit/golden、既有`test_m3_tracking_journal.py`、G8 R1 unit/golden与StageRunner邻接；定向Ruff/mypy/cold import。WSL base同组。

actual StageRunner publication沿用G8 R1 §11：公开`platform_supports_renameat2_noreplace()`为false时只窄skip actual publish golden，其余tracking remote fake与合同测试必须PASS；为true必须完整执行。当前WSL1/DrvFS绿仅兼容证据，不是Linux ext4 Gate。不得运行真实MLflow、联网或安装依赖。

长测试只启动一次并低频等待；记录actual passed/skipped、耗时、warning、源码SHA。执行scoped diff、whitespace、白名单与临时文件清理。

## 12. 停止条件与完成声明

以下任一立即停止：无法在不改StageRunner/run_state下消除双写；必须接受caller digest/path list；必须在closure重复上游fresh；必须真实MLflow/网络/ext4/正式G1才能测试；需要改G7F/G6A/G8 R1/Schema/config；需要把CLI/G8E/F/G9并包；无法保持development API兼容或稳定异常脱敏。

完成闭环为外部Cursor实现 → 另一个全新外部Cursor独立初验 → 主Agent最终验收。完成时只可声明“G8D-F1 formal tracking StageRunner工程合同PASS”，解锁后续G8C CLI增量设计；不得声明真实tracking、G8、M3或ext4 Gate PASS。

## 13. R2：FINISHED 远端 run 全标签复用闭包返工

R1 独立初验报告判定 FAIL。现象：远端已有一个 `FINISHED` run，五个 protected identity tags/hash 与当前 request 一致，但 `formal_gate_eligible` 从 `"true"` 漂移为 `"false"` 时，`register_remote_tracking_run` 仍复用该 run。根因是 `_validate_remote_run` 只比较 protected tags 子集，没有比较创建时写入的 request tags。

应遵循 §5、§6：当前 formal request 的 tags exact 为 `formal_gate_eligible="true"`、`release_kind="formal"`；只有 `FINISHED` 且 create 首写的 request tags 与 protected identity tags 全部逐键逐值一致时才允许复用。不得把远端任意额外非保留标签纳入 exact-set 比较，也不得放宽 protected tag、status、多匹配或 development 行为。

R2 只允许最小修改 `tracking.py`、既有 G8D-F1 unit 测试、任务状态和唯一 R2 交付报告 `docs/framework/agent/M3_G8D_F1_R2_FINISHED远端Run全标签复用闭包交付报告.md`；`tracking_stage.py`、golden、`__init__.py` 与其他文件必须保持 SHA 不变，除非真实接口冲突并立即停止回报。R1 交付/初验报告保持历史只读。

新增正式回归至少覆盖：

- `formal_gate_eligible` 单独漂移拒绝；
- `release_kind` 单独漂移拒绝；
- 任一 request tag 缺失拒绝；
- request tags 与全部 protected tags 都一致时继续复用同一 run id；
- 额外普通远端标签不影响复用；额外/漂移 protected 标签仍按既有 fail-closed 语义处理；
- hostile mapping/异常仍稳定脱敏，remote 冲突不创建第二 run。

通过条件：上述回归、既有 G8D unit/golden、tracking journal 与 G8 R1 邻接在 Windows 和 WSL base 按 §11 通过；Ruff/mypy/cold/diff 通过。返工后必须交给未参与 R2 实现的全新外部 Cursor 独立复验，重点使用不同 tag 值与缺失组合再次攻击；主 Agent 不得直接修补后跳过复验。
