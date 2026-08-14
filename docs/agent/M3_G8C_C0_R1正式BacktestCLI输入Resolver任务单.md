# M3 G8C-C0 R1：正式 Backtest CLI 输入 Resolver 任务单

日期：2026-08-10

状态：**主 Agent 最终验收 PASS（2026-08-12）；C0 工程合同已关闭，允许冻结并实施 C1；不代表 G8C/M3/Linux·ext4 Gate PASS。见 [主验报告](M3_G8C_C0_R3_配置原路径锚定与全链Integration主Agent最终验收报告.md)**

## 1. 唯一目标与前置

本包只新增一个零写入、process-local resolver：从 `project_root`、已加载配置、配置相对路径、`snapshot_id`、`fold`、`horizon` 出发，禁止扫描目录，按唯一具名 key/path 对已发布 formal artifacts 逐层调用 public verifier，返回未来 C1 调用 `run_formal_backtest_stage` 所需的完整 verified values 与 fresh context。

G8 R1 formal backtest wave、G8D-F1 R2 tracking wave及其上游G1–G7工程合同均已主验。C0 不接 `run_m3.py`，不运行 StageRunner，不创建/修改任何 artifact、receipt、root或lock，不实现 train/evaluate/backtest/run-all/tracking，不导入或创建MLflow client，不联网。缺任一已有产物即fail-closed，绝不补生成。

## 2. Public API

新增 `quant.research.m3.formal_cli_resolve`：

```python
class FormalCliResolveError(ValueError):
    code: str
    exit_code: int

@dataclass(frozen=True)
class FormalBacktestCliResolution:
    stage_root: Path
    artifact_roots: Mapping[str, Path]
    config: LoadedM3Config
    release: VerifiedG1Release
    experiment: VerifiedExperimentIdentity
    target: VerifiedTargetArtifact
    plan: VerifiedBacktestPlanArtifact
    fresh_context: BacktestArtifactFreshVerificationContext
    work_key: str

def resolve_formal_backtest_cli_inputs(
    *, project_root: Path, config: LoadedM3Config,
    config_relative: PurePosixPath,
    snapshot_id: str, fold: str, horizon: int,
) -> FormalBacktestCliResolution: ...
```

`config_relative` 必须 exact `PurePosixPath`、非空规范相对路径，拒绝绝对路径、`.`/`..`、反斜杠、drive、重复或空 component；只用于绑定已加载配置的来源身份，caller不能另传config digest。`snapshot_id` exact bare lowercase hex64；`fold` exact `fold_[0-9]{3}`；`horizon` exact `5|10`且拒绝bool。`project_root`/`stage_root`必须existing real directory、无symlink/reparse；config必须exact `LoadedM3Config`且`raw_config_sha256`非空。所有字段exact type/value校验；resolution不可pickle。它是普通只读传输值，不是可由caller提交给formal入口的authority：未来C1必须在自己的public命令调用栈内直接调用resolver，不得增加caller-supplied resolution参数或公开恢复器/signer。

成功返回的 `config` 必须与输入同一对象；`work_key == target.manifest.work_key == plan.manifest.work_key == compute_work_key(experiment_key, fold, horizon)`。artifact roots必须是resolver从config/project root派生并验真的规范Mapping，caller没有roots/path/digest入口。

## 3. 唯一路径与禁止扫描

`stage_root = project_root / config.section("tracking")["artifact_root"]`，沿现有CLI安全规则解析，禁止绝对逃逸。G8路径只允许由下列key派生：

- `snapshots/<snapshot_id>/`、`snapshot-requests/<snapshot_request_key>.json`、`receipts/snapshot/<snapshot_request_key>.json`；
- `providers/<provider_key>/`、`receipts/provider/<provider_key>.json`；
- `provider-validations/<provider_validation_key>/`、`receipts/provider-validation/<provider_validation_key>.json`；
- `runs/<experiment_key>/`、`receipts/experiment-identity/<experiment_key>.json`；
- `labels/<experiment_key>/h<horizon>/`、`receipts/labels/<experiment_key>-h<horizon>.json`；
- `folds/<experiment_key>/`、`receipts/folds/<experiment_key>.json`；
- `features/<experiment_key>/<fold>/`、`receipts/features/<experiment_key>.<fold>.json`；
- `work/<work_key>/{alignment,train,predictions,targets,backtest_plan}/`及各自`receipts/<stage>/<work_key>.json`。

G1 release路径必须从已验真snapshot request/manifest绑定的G1 identity派生并落在权威G1 release root；不得猜固定release id、扫描`releases/`选最新、接受caller path或从receipt摘要伪造capability。

组合key只能调用现有 `compute_snapshot_request_key`、`compute_provider_key`、`compute_provider_validation_key`、`compute_experiment_key`、`compute_work_key`；不得复制hash算法。若从给定六项输入无法通过public artifact内容与配置唯一求出任一key/path，立即命中停止条件。

## 4. Fresh verification链

每次resolver成功路径对下列public verifier各exact一次，按依赖顺序执行；失败到首个即停：

1. `verify_g1_release`；
2. snapshot；
3. provider；
4. provider validation；
5. experiment identity；
6. 当前horizon label；
7. folds；
8. 当前fold feature；
9. alignment；
10. model/train；
11. prediction；
12. target；
13. backtest plan。

必须使用实际public函数名与签名；实现前完整核对 `snapshot.py`、`provider.py`、`provider_validation.py`、`experiment_identity.py`/`labels.py`、`folds.py`、`features.py`、`alignment.py`、`model.py`、`predictions.py`、`targets.py`、`a_share_plan.py`。禁止import私有reader/builder/helper，禁止monkeypatch生产verifier，禁止把测试fixture capability带入生产。

所有BuildSpec/UpstreamPaths只能用public value object constructor、fresh已验真manifest/config与具名receipt path重建。最终组装 `BacktestPlanFreshVerificationContext`、`AShareMarketFactsFreshVerificationContext`、`FormalBacktestArtifactUpstreamPaths` 与 current `BacktestArtifactFreshVerificationContext(facts_fresh_context=..., upstream_paths=..., release=release)`；formal upstream paths精确三项，不得构造development四路径类型或G1 receipt。C0不得调用G7F final verifier、G7E simulation、G8 StageRunner或tracking。

## 5. 稳定失败与零副作用

所有public失败翻译为`FormalCliResolveError`，`__cause__`/`__context__`必须为空，消息不得包含绝对path、URI、TOKEN、PID、hash原文或hostile marker。`code`/`exit_code`只允许：

- CLI输入/配置/runtime identity错误：稳定code，exit 2；
- G1/snapshot/上游数据门禁：稳定code，exit 3；
- Qlib/LightGBM等依赖不可用：稳定code，exit 4；
- 缺失receipt/artifact、闭包漂移或stage input：稳定code，exit 5。

不得mkdir/write/fsync/open写模式/socket/network/log敏感信息/环境变更/wall-clock决策。允许锚定只读打开唯一派生文件；任一symlink/junction/reparse、same-bytes换inode、root替换、hardlink alias或跨root混配均fail-closed。

## 6. C1唯一消费方式

C0主验PASS后，C1只能在`backtest`命令调用栈内：先exact一次`load_m3_config`，再exact一次调用本resolver，然后把返回字段直接传入：

```python
run_formal_backtest_stage(
    stage_root=r.stage_root,
    target=r.target, plan=r.plan, release=r.release,
    experiment=r.experiment, config=r.config,
    fresh_context=r.fresh_context,
    artifact_roots=r.artifact_roots,
    resume=not no_resume,
)
```

C1不得接受caller resolution/capability/path/root，不得缓存到磁盘或pickle；fresh子进程必须重新resolve。C0期间`run_m3 backtest`仍保持`M3_COMMAND_HANDLER_UNAVAILABLE`。

## 7. 白名单

外部实现仅允许：

1. 新增`src/quant/research/m3/formal_cli_resolve.py`；
2. `src/quant/research/m3/__init__.py`仅惰性安全导出`FormalCliResolveError`、`FormalBacktestCliResolution`、`resolve_formal_backtest_cli_inputs`；
3. 新增`tests/unit/test_m3_g8c_c0_formal_cli_resolve.py`；若真实public全链只能在integration fixture诚实构造，可停止申请新增单一integration文件，不得自行复制千行伪fixture；
4. 本任务状态；
5. 唯一`docs/agent/M3_G8C_C0_R2_configRelative与G7FR4同步交付报告.md`。

禁止修改`run_m3.py`、orchestration/run_state、backtest/tracking stage、任何G1–G7 verifier/contracts/schemas/config、既有tests/docs、正式artifacts。独立初验只写唯一`M3_G8C_C0_R2_configRelative与G7FR4同步独立复验报告.md`；主验另写唯一报告。

## 8. 必测矩阵

- happy path返回字段可直接绑定`run_formal_backtest_stage`签名但不真运行；13个public verifier各once，物理顺序正确；
- snapshot request中的snapshot id、G1/config/code identity任一漂移；错误fold/horizon；缺backtest_plan；跨work/root拼接；receipt少/多/alias/换inode；
- caller伪造path/roots/resolution没有public消费入口；cold import不加载Qlib/LightGBM/MLflow；resolver运行不加载MLflow；
- monkeypatch mkdir/open写/socket/network/time/log证明零副作用；hostile verifier递归异常图稳定脱敏；
- resolver前后工作树、stage root、receipt树零写；输入顺序/Mapping hostile不改变规范结果；
- Windows Miniforge与WSL base运行focused pytest、Ruff、mypy、cold import、diff；WSL1/DrvFS只算兼容，不是ext4 Gate。

独立初验必须新增：错误snapshot id零写、当前code/config与request key漂移、跨work整套合法重签、同字节root/file替换、fresh verifier返回另一合法对象、重载/旧resolution边界与无目录扫描证据。

## 9. 停止条件与完成声明

以下任一立即停止并提交证据：任一Spec/UpstreamPaths无法仅凭public API、fresh artifacts与具名key/path重建；需要扫描/`inspect`/私有helper；需要修改verifier签名、receipt schema、StageRunner或上游production；需要生成缺失stage；需要真实MLflow/网络/ext4/正式G1才能做最小工程验证；需要复制大型伪formal链或接受caller capability。原R1的`config_relative`缺口和伪G1 receipt张力已由§10重冻与G7A/B/F R3-R4关闭，不得再次兼容旧合同。

完成仍须“外部Cursor实现→另一全新外部Cursor独立初验→主Agent最终验收”。仅可声明G8C-C0 formal backtest CLI input resolver工程合同PASS；不解锁tracking/run-all/G8E/F或任何Gate。C0主验PASS后才可冻结C1。

## 10. R2 重冻：配置来源身份与 current G7F R4

### 10.1 runtime identity 唯一闭包

R1 停止证据成立：`LoadedM3Config` 不携带source path，五元输入无法唯一重建 `code_version`。R2 采用最小
方案，在public resolver增加 exact `config_relative: PurePosixPath`。resolver必须校验
`project_root / config_relative` 是project root内的唯一真实普通文件、无symlink/reparse/hardlink alias，稳定读取
sha256精确等于 `config.raw_config_sha256`；随后exact一次调用：

```python
compute_m3_runtime_identity(
    project_root=project_root,
    config_paths=(config_relative,),
    frozen_config_digests=(
        M3SourceDigestV1(config_relative.as_posix(), config.raw_config_sha256),
    ),
)
```

不得扫描config目录、接受caller digest、使用默认config paths、从环境变量猜路径或重算另一份配置语义。C1未来
必须从用户给定且已安全解析的同一config path派生`config_relative`，先exact一次`load_m3_config`，再exact一次调用
resolver；C0仍不修改C1。

### 10.2 G1与G7F current合同

G1 formal release没有StageRunner receipt。resolver只允许用public snapshot manifest/request所绑定的
`g1_release_id`和`g1_release_manifest_sha256`派生唯一release root，再构造public `G1Release`并调用
`verify_g1_release`；禁止`release.root/receipt.json`、扫描releases选最新或构造fake receipt。G7F fresh context精确使用
current三路径 `FormalBacktestArtifactUpstreamPaths(target, plan, experiment)`，并绑定同一个fresh
`VerifiedG1Release`；21-input的G1部分由manifest+quality+八表组成。

读取snapshot manifest/request只用于确定具名依赖路径和key，不能作为verified authority；resolver随后仍须按§4对
G1及13层public verifier各exact一次并逐字段比对。任何预读与fresh返回不一致、same-bytes换inode、root替换或
current runtime identity不等于request记录均在构造resolution前fail-closed。

### 10.3 R2新增反例与通过条件

- `config_relative`绝对/逃逸/非POSIX/错文件/同bytes换inode、raw hash空或不符；caller伪digest无入口；
- current code/config identity与snapshot request key漂移；旧五参数调用、development四路径、G1 receipt假文件均拒绝；
- exact current context必须可直接绑定`run_formal_backtest_stage`签名，但resolver全程零写且不调用StageRunner；
- focused Windows与WSL base pytest、Ruff、mypy、cold import、diff通过；真实全链fixture若无法在白名单内诚实最小
  构造，必须按§9停止申请单一integration文件，不得monkeypatch verifier或复制大型伪formal链。

R2外部实现与独立初验必须使用不同全新Cursor会话；只有R2主验PASS才允许冻结C1。

## 11. R3：配置原路径锚定返工与单一 integration 批准

### 11.1 主 Agent 审查发现的锚定缺口

R2 `_anchor_config_file` 先对 `project_root/config_relative` 调用 `resolve(strict=True)`，随后只对resolved target
执行`lstat`与ancestor检查。这样leaf symlink或中间symlink会先被消解；当目标是root内正常普通文件时，原始逻辑
可能接受链接路径，违反§5与§10.1的“唯一真实普通文件、无symlink/reparse”合同。现有unit输入矩阵未覆盖该路径。

最小返工：在任何`resolve`或文件读取前，从已锚定project root开始，按`config_relative.parts`逐component对
**原始路径**执行`lstat`；每个中间component必须exact目录且非symlink/reparse，leaf必须exact普通文件、非
symlink/reparse、`st_nlink == 1`。随后再确认resolved leaf仍在同一project root且实体未漂移，并用稳定打开前后实体
与sha256绑定`config.raw_config_sha256`。Windows junction/reparse与POSIX symlink均拒绝；same-bytes替换、hardlink
alias及检查后读取前替换fail-closed。不得通过`Path.resolve()`后的目标检查替代原路径检查。

新增unit至少覆盖leaf symlink、intermediate symlink/junction（平台支持时）、hardlink、检查后same-bytes换inode与
hostile异常脱敏；所有失败发生在`compute_m3_runtime_identity`及任一artifact verifier前，零写。

### 11.2 单一 integration 文件批准

批准新增且仅新增：

`tests/integration/test_m3_g8c_c0_formal_cli_resolve.py`

该文件只用于最小诚实的已发布formal链happy-path，验证resolver对13层public verifier各exact一次且顺序正确，返回
resolution可直接绑定`run_formal_backtest_stage`签名但不实际运行。优先复用已主验的public fixture/support与真实
artifact bytes；禁止monkeypatch任一production verifier、裸构造/替换verified capability、SimpleNamespace冒充formal、
复制千行伪链或生成缺失业务stage。若仓库仍无可复用诚实链，必须再次停止并给出精确缺口，不得把integration变成
权限绕过。

### 11.3 R3白名单与通过条件

- `src/quant/research/m3/formal_cli_resolve.py`仅修原路径/稳定实体锚定；
- `tests/unit/test_m3_g8c_c0_formal_cli_resolve.py`补链接、hardlink、替换与前置短路反例；
- 新增唯一`tests/integration/test_m3_g8c_c0_formal_cli_resolve.py`；
- 本任务状态；
- 唯一交付报告`docs/agent/M3_G8C_C0_R3_配置原路径锚定与全链Integration交付报告.md`；
- 独立初验只写唯一`docs/agent/M3_G8C_C0_R3_配置原路径锚定与全链Integration独立复验报告.md`。

禁止再改`m3/__init__.py`或其他production/tests/docs。Windows与WSL base focused unit+integration、Ruff、mypy、cold、
diff必须明确终态；WSL1/DrvFS仅兼容。R3外部实现与独立初验使用不同全新Cursor会话；R3主验PASS才解锁C1。
