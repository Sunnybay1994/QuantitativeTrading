# M3 G8 ExperimentIdentity 最小闭环任务单

## 1. 目标与边界

本任务只补齐正式 G8 第三 continuation 所需的 ExperimentIdentity 最小工程闭环，不执行正式数据发布，
不修改 G1/G2 bytes、journal 或正式候选目录，也不扩展到 labels、folds、work、tracking 或完整 G8 DAG。

权威契约来自 [`docs/framework/M3实施与Agent交接.md`](../M3实施与Agent交接.md)、
[`M3_G8Continuation编排恢复追踪分包骨架与外部闭环任务单.md`](M3_G8Continuation编排恢复追踪分包骨架与外部闭环任务单.md)
及当前 `contracts.py`、`run_state.py`、`labels.py` 的严格消费者实现。若历史占位设计与当前实现冲突，
以这些当前契约和本任务冻结的更小范围为准。

## 2. 审计结论

- 已有 `ExperimentIdentitySpec`、`ExperimentIdentityManifestV1`、`compute_experiment_key` 和
  `verify_experiment_identity`，但没有正式 manifest producer。
- `orchestration.py` 虽定义 `StaticDirectoryPublication`，当前 runner 只执行 snapshot；没有
  experiment-identity StageSpec、plan builder 或 static publication 执行路径。
- 当前没有 M3 通用 code identity 或完整 dependency fingerprint。G1 runtime identity 和 provider runtime
  fingerprint 均为各自窄域身份，不能替代 experiment/work 所需的完整身份。
- 当前没有 `quant.research.run_m3` 薄 CLI。
- 已验证的 provider-validation PASS 是进入本 stage 的依赖 Gate，但不是内容身份；不得进入 experiment
  receipt 的 `inputs`。

## 3. 冻结身份与发布契约

### 3.1 运行身份

- code identity 首选 `Git commit + dirty content identity`。dirty identity 必须基于受控文件内容而非仅状态文本；
  clean 与 dirty 必须可区分，文件内容变化必须改变 identity。
- 只有 Git metadata 不可用时，才退化为 `src/quant` 与版本化配置的规范化
  `relative path + SHA-256` 集合 hash；禁止固定 `unavailable`。
- full dependency fingerprint 必须包含 Python/platform、`pyproject.toml` hash，以及参与研究/回测的包版本；
  未安装包稳定记录为 `NOT_INSTALLED`。至少覆盖 NumPy、pandas、PyArrow、Polars、DuckDB、Pandera、
  SciPy、scikit-learn、LightGBM、Qlib、MLflow、QuantStats。
- source/config、Git 状态、`pyproject.toml`、platform/dependency probe 在返回前复核；漂移一律 fail-closed。

### 3.2 ExperimentIdentity

`experiment_key` 只由以下字段决定：

1. verified `snapshot_id`；
2. canonical provider receipt SHA-256；
3. `LoadedM3Config.scientific_config_sha256`；
4. full `dependency_fingerprint_sha256`；
5. 当前 `code_version`。

输出目录严格只有 `experiment_manifest.json`。正式稳定布局为：

```text
<artifact-root>/runs/<experiment_key>/experiment_manifest.json
<artifact-root>/receipts/experiment-identity/<experiment_key>.json
```

receipt 固定 `stage=experiment-identity`、`scope=EXPERIMENT`、`scope_key=<experiment_key>`；内容输入精确为：

1. canonical snapshot receipt；
2. snapshot manifest；
3. canonical provider receipt；
4. provider manifest。

输出精确为 `experiment_manifest.json`。provider-validation receipt 只作为执行前 Gate 参数验证，不进入上述
四项内容输入。

### 3.3 发布与恢复

- runner 仅增加 experiment-identity 专用 static-directory 路径，不在本任务泛化全部 static stages。
- handler 只能写 runner 分配的独占 temp；runner 校验精确单文件闭包后 no-clobber 原子提交目录，再发布目录外 receipt。
- 已有 final/receipt 的重复执行必须完整复验并返回既有结果；任一缺失、篡改、错 scope/key、非普通文件、
  symlink/reparse 或内容冲突都 fail-closed。
- provider-validation 必须先由严格 verifier 证明 PASS；runner 不把其 receipt 传给 handler，也不把它加入
  receipt 内容输入。

## 4. 验收范围

- fixture/fake 覆盖 deterministic identity、Git dirty content、fallback、`NOT_INSTALLED`、首尾漂移；
- manifest/key/四输入一输出闭包；provider-validation 仅 Gate；no-clobber、重复执行、orphan/recovery、篡改；
- CLI 只做 config/verified bundle/runtime identity/runner 依赖注入，输出规范 JSON，错误不泄露绝对路径或凭据；
- Windows 定向 Ruff/mypy/pytest；WSL base 与 py312 对应定向验证；
- 本任务不运行正式 ExperimentIdentity 发布，不宣称完整 G8 或 Linux/ext4 Gate 通过。
