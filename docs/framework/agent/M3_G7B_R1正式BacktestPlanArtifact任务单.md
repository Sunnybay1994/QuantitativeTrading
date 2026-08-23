# M3 G7B R1：正式 BacktestPlanArtifact 任务单

日期：2026-08-09  
状态：R2 正式 G1 quality 来源闭包工程主验 PASS；G7F 同类返工已解锁；真实全折与 Linux/ext4 Gate 仍开放  
性质：formal 工程合同；不是完整真实 work、成本事实或 M3/ext4 Gate

## 1. 目标与前置

把 G7A `VerifiedTargetArtifact` 映射为严格下一 SH session 执行的正式 A股回测计划，发布四文件
`VerifiedBacktestPlanArtifact`，并 fresh 绑定 G1日历、fold、experiment、scientific config、成本日程与
19-input/4-output receipt。

前置条件是 G7A R2 独立复验与主验 PASS；若 G7A 再次 FAIL，本任务只保留设计，不启动实现。

现有 `a_share_plan.py` 只实现 development example，读取后存在 `.sort()` 规范化，且骨架 public 签名不足以
调用 G7A 的完整 public fresh verifier。不得把 development capability cast/复制成 formal，也不得只校验 caller
dataclass 字段或私有 token。

## 2. Formal 类型与 Fresh Context

在 `quant.research.m3.contracts` 新增并安全导出 exact formal 类型：

```python
@dataclass(frozen=True)
class VerifiedBacktestPlanArtifact:
    root: Path
    scheduled_targets: pl.DataFrame
    manifest: BacktestPlanManifestV1
    manifest_sha256: str
    plan_receipt_sha256: str
```

不得带 `release_kind/example_id/formal_gate_eligible`；development verified 类型保持完全独立。

在 `a_share_plan.py` 新增不可序列化的：

```python
@dataclass(frozen=True)
class BacktestPlanFreshVerificationContext:
    snapshot: VerifiedSnapshotArtifact
    snapshot_spec: SnapshotBuildSpec
    provider: VerifiedProviderArtifact
    provider_spec: ProviderBuildSpec
    experiment_spec: ExperimentIdentitySpec
    fold_spec: FoldPlanBuildSpec
    feature: VerifiedFeatureArtifact
    feature_spec: FeatureBuildSpec
    label: VerifiedLabelArtifact
    label_spec: LabelBuildSpec
    alignment: VerifiedAlignmentArtifact
    alignment_spec: AlignmentBuildSpec
    model: VerifiedModelArtifact
    model_spec: LightgbmTrainingSpec
    prediction: VerifiedPredictionArtifact
    prediction_spec: PredictionBuildSpec
    target_spec: TargetBuildSpec
    target_upstream_paths: TargetUpstreamPaths
    target_receipt_path: Path
```

`__post_init__` 对 exact type/path 做窄校验；该 context 不进入 manifest/receipt，不得序列化。外层显式
release/experiment/folds/config/target 必须与 context 的完整链 exact identity 一致。

## 3. 公共接口

```python
def build_backtest_plan_artifact(
    *,
    target: VerifiedTargetArtifact,
    release: VerifiedG1Release,
    folds: VerifiedFoldPlanArtifact,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    fresh_context: BacktestPlanFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
    output_root: Path,
) -> BacktestPlanManifestV1: ...

def verify_backtest_plan_artifact(
    *,
    root: Path,
    receipt_path: Path,
    target: VerifiedTargetArtifact,
    release: VerifiedG1Release,
    folds: VerifiedFoldPlanArtifact,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    fresh_context: BacktestPlanFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> VerifiedBacktestPlanArtifact: ...
```

保留共用 `read_backtest_plan_manifest`；development public API、stage、identity和测试不得改变。

builder/verifier 各自精确一次调用 public `verify_target_artifact`，传入 target root/receipt、outer release/folds/
experiment/config 以及 context 的完整 G1→G7A 参数和 `artifact_roots`。返回值必须逐字段 exact：绝对 root、两个
DataFrame、manifest、manifest hash、receipt hash；禁止通过 dataclass 的模糊 DataFrame `==` 代替显式比较。

formal/dev类型混配及轻量路径预检必须在任何输出前失败。builder 的 public fresh call 必须位于 output root lease
内部，使整个长验证窗口绑定同一 root实体。

## 4. SH session 调度与物理顺序

- 从 fresh G1 `trade_calendar.parquet` 读取 `market=SH,is_open=True` 子序列；不得 `.sort()` 修复。物理序列必须
  非空、唯一、严格递增。
- fold test signal dates 必须 exact 等于 target `as_of` 域，且每个 signal 本身是 SH open session。
- execution date 是 signal 在 verified SH sessions 中的严格 index+1。尾部没有 next session立即失败，不静默
  丢最后 batch，不按自然日加一。
- G7A target物理顺序 exact `(as_of,symbol)`；formal reader只能验证，不排序。scheduled按构造自然形成
  `(execution_date,as_of,symbol)`；diagnostics物理 `(as_of)`。
- `session_lag=1` 表示一个 verified session，不是一个自然日。
- window的signals/executions exact；first execution是首个执行open，terminal valuation是最后execution close，
  `force_liquidation=False`。每fold×horizon独立初始账户，不跨fold继承。

四文件 exact：

```text
scheduled_targets.parquet
schedule_diagnostics.parquet
cost_schedule.json
manifest.json
```

scheduled列/dtype沿现有六列；diagnostics沿现有五列。每日 `total_target_weight` 用
`sum(Decimal(str(weight)))` 后投影，禁止 float tolerance或隐式改权重。

## 5. 成本、配置与身份

复用现有 `cost_schedule.json` 结构与 `BacktestPlanManifestV1`，不建平行 schema/hash。

- base periods使用 `Decimal(str(value))`；自然日闭区间连续、无重叠，`None` 只允许末段；每个 execution date
  必须命中唯一 period，早于首段/落入gap失败。
- multipliers 必须从 `config.backtest.a_share.friction_multipliers` fresh重建并 exact 等于
  `Decimal("0.5"), Decimal("1"), Decimal("2")`，不得仅模块硬编码。
- 只缩放 commission_rate、commission_min、slippage；stamp_tax_sell、transfer_fee不缩放；
  `costs.scaled_components` exact 为这三个字段。
- 复核边界至少覆盖2022-04-28/29、2023-08-27/28；开放末段仍只是研究成本假设。
- `scientific_config_sha256`必须绑定并fresh重验：
  `BUY_CEIL_SELL_FLOOR_TICK_V1`、`EACH_COMPONENT_HALF_UP_CENT_V1`、
  `HALF_UP_CENT_V1`、`annualization_sessions=252`。
- 日期ISO，Decimal为无指数canonical string；cost schedule/version/order quantity rule均进入manifest/receipt。

G9仍须按届时有效期重核真实成本事实；G7B不得宣称真实券商费用Gate。

## 6. Receipt 闭包

formal receipt固定：

```text
stage = "backtest-plan"
scope = "WORK"
scope_key = target.manifest.work_key
inputs = exact 19 paths
outputs = exact 4 paths
```

19 inputs为 G7A冻结14项并集 target四项与G1日历：

1. G1 manifest；2. G1 quality；3. eligible_keys；
4. feature manifest；5. feature receipt；6. feature coverage；7. feature test；
8. prediction manifest；9. prediction receipt；10. prediction parquet；
11. folds manifest；12. folds receipt；13. experiment manifest；14. experiment receipt；
15. target manifest；16. target receipt；17. target weights；18. target daily；19. trade calendar。

exact无重复、无alias；通用 receipt 验真后仍须由 root selectors 重建 physical path集合。same bytes不同root、路径
alias、少/多/重复、漏target_daily或calendar均失败。不得加入未实际读取的label内容或未知文件。

## 7. 发布与异常合同

复用唯一 `ArtifactPublication`，不复制 writer：

- output root 必须caller-created空plain目录；preflight后立即进入lease；
- fresh target、日历读取、调度和全部数学均在lease内；四文件先在内存生成；
- exclusive stream、flush/fsync、readback后最后commit exact set；no-clobber；
- root在fresh期间rename+空目录替换必须首字节前失败；并发占同名不得覆盖或删除竞争文件；
- rollback只删除本调用owned identity；rollback失败独立稳定码。

公开稳定错误：

```text
M3_BACKTEST_PLAN_ARTIFACT_INVALID
M3_BACKTEST_PLAN_ROLLBACK_FAILED
```

上游、Polars、JSON、IO、hostile ValueError/RuntimeError均须离开active except后翻译，cause/context为None，
traceback/repr不得泄露path/TOKEN/raw/SQL。verifier需pre/post root实体连续、拒绝symlink/junction/reparse、exact tree
和stable reads；whole-root替换即使same bytes也拒绝。

## 8. 必测反例

至少覆盖：

1. target物理乱序（development旧reader会sort）、缺/多/重复batch；
2. signal非SH open、tail无next、自然日周末/休市不能+1；
3. copied target root、formal/dev混配、跨work/fold/horizon/experiment；
4. hostile target verifier ValueError/RuntimeError及返回非exact fresh capability；
5. 19-input每项少/多/alias/错root；receipt stage/scope/key错误；
6. cost边界、gap/overlap/reverse/closed tail、三multiplier、税/过户不缩放；
7. rounding/annualization/scientific config漂移；
8. 四输出逐个篡改/乱序/noncanonical/whole-resign；
9. 另一work整套plan改manifest/hash并合法重签receipt仍被fresh重算拒绝；
10. root非空/link/junction、fresh窗口root替换、四writer/flush/fsync、并发占名、rollback失败；
11. hostile label/account/network入口零调用；cold import不加载Qlib/LightGBM/MLflow。

## 9. 白名单与验证

- `src/quant/backtest/a_share_plan.py`
- `src/quant/backtest/__init__.py`仅必要安全导出
- `src/quant/research/m3/contracts.py`仅新增formal verified class
- `src/quant/research/m3/__init__.py`仅安全导出
- 新 `tests/unit/test_m3_formal_backtest_plan_artifact.py`
- 本任务、交付、独立复验、主验报告

禁止改config、G7A、G1-G6、development测试/语义、正式artifacts/journal或联网。

Windows与WSL base运行 formal plan + formal target + development plan + config定向pytest、Ruff、mypy、cold
import与diff；必须隔离worktree `PYTHONPATH`/basetemp。WSL若为wslfs/DrvFS只算定向兼容，不是ext4/Linux Gate，
也不是正式真实全fold或成本Gate。

## 10. R2：正式 G1 `quality.json` 来源闭包返工

### 10.1 问题与权威规则

G7B 当前 formal 19-input 构造和 upstream bytes 校验仍引用不存在的正式 G1 `receipt.json` 与不存在的
`VerifiedG1Release.receipt_sha256` 语义，导致真实 G1 exact tree 无法进入计划发布。根因与 G7A R3 相同：把
development stage receipt 错复制到正式 G1 release。权威规则以 `docs/framework/M3实施与Agent交接.md` §4.8 和已主验
G7A R3 为准：正式 G1 使用 public fresh verifier + manifest + quality + selected artifacts；不得补造 receipt。

### 10.2 精确变更

1. formal 19-input 的第 2 项改为 exact `release.release.quality_path`，绑定 `release.quality_sha256`；顺序、总数、
   后续 target 四项与 trade calendar 不变。
2. formal upstream stable-bytes、receipt expected path/digest set、builder/verifier exact-set 重建都必须同步；
   可以复用窄的 formal G1 quality path validator，但不得 import G7A 私有 helper。
3. development `_receipt_inputs` 与其真实 `receipt.json` 保持不变；不得改 G7A、G1、公共 API、manifest、调度、
   Decimal/成本、publication 或错误码。
4. formal 测试 fixture 不得在 G1 root 创建正向所需的 fake receipt。必须覆盖：19 paths 中 manifest→quality→eligible；
   missing/drift quality；quality 与任一输入 samefile/hardlink alias；伪 receipt 整包合法重签仍拒绝；旧 formal
   plan receipt 不可复用；development 邻接继续通过；hostile 异常 cause/context 脱敏。
5. 若 actual G7A R3 public interface 或现有 plan verifier 无法在本白名单内满足以上合同，立即停止并回报，
   不得放宽上游 fresh 或修改 G1 final tree。

### 10.3 本轮白名单与验证

- `src/quant/backtest/a_share_plan.py`
- `tests/unit/test_m3_formal_backtest_plan_artifact.py`
- 本任务单状态
- 唯一交付报告 `docs/framework/agent/M3_G7B_R2_正式G1Quality来源闭包返工交付报告.md`
- 唯一独立复验报告 `docs/framework/agent/M3_G7B_R2_正式G1Quality来源闭包独立复验报告.md`

Windows/WSL base 至少运行 formal G7B + formal G7A R3 + development plan 邻接、Ruff、mypy、cold import、
scoped diff-check。WSL `/mnt/f` 仅 DrvFS 兼容。外部实现完成后必须由另一全新外部 Agent 只读初验并增加
实现者未用反例；独立 PASS 后方可进入主验，主验 PASS 后才解锁 G7F 同类返工。
