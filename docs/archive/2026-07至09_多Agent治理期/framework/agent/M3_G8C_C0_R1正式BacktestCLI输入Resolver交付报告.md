# M3 G8C-C0 R1：正式 Backtest CLI 输入 Resolver 交付报告

日期：2026-08-10  
角色：外部实现 Agent（cursor-grok-4.5-high）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
任务单：[`M3_G8C_C0_R1正式BacktestCLI输入Resolver任务单.md`](M3_G8C_C0_R1正式BacktestCLI输入Resolver任务单.md)  
结论：**停止待重冻**（可实现性审计未通过；未写入生产实现/测试）

## 1. 审计范围与白名单遵守

已完整阅读：

- `AGENTS.md` / `.ai/README.md`
- `docs/framework/M3实施与Agent交接.md` 当前 §4.9 / §6.9
- 本任务单冻结 API、13 层 verifier 顺序、零写/禁扫描/停止条件
- 实际 public verifier 签名：`verify_g1_release`、`verify_snapshot_artifact`、`verify_provider_artifact`、`verify_provider_validation_artifact`、`verify_experiment_identity`、`verify_label_artifact`、`verify_fold_plan_artifact`、`verify_feature_artifact`、`verify_alignment_artifact`、`verify_model_artifact`、`verify_prediction_artifact`、`verify_target_artifact`、`verify_backtest_plan_artifact`
- 组合 key：`compute_snapshot_request_key` / `compute_provider_key` / `compute_provider_validation_key` / `compute_experiment_key` / `compute_work_key`
- C1 消费签名：`run_formal_backtest_stage(...)`

本轮**未**新增/修改：

- `formal_cli_resolve.py`
- `m3/__init__.py`
- 任何 unit/integration 测试
- `run_m3` / orchestration / backtest / tracking / G1–G7 / contracts / schemas / config / 既有 docs

仅改动：本交付报告 + 任务单状态 → **停止待重冻**。

## 2. 首要缺口（命中停止条件）

### 2.1 现象

冻结五元组 `(project_root, LoadedM3Config, snapshot_id, fold, horizon)` **无法**在禁止目录扫描的前提下，通过 public API + 具名 key/path **唯一**派生：

1. `snapshot_request_key`
2. 因而也无法唯一派生 `snapshot-requests/<key>.json`、`receipts/snapshot/<key>.json`
3. 同依赖链上的 `provider_key`、`provider_validation_key`、`experiment_key`（均需要同一 `code_version`，experiment 另需 `dependency_fingerprint_sha256`）

没有这些 key，后续 13 层 public verifier 的路径/spec 无法按任务要求“只靠具名派生”组装。

### 2.2 根因

`compute_snapshot_request_key` 的权威签名（`run_state.py` / SSOT §4.9）为：

```text
SHA-256(JSON[g1_release_id, g1_release_manifest_sha256, snapshot_config_sha256, code_version])
```

| 分量 | 能否从五元组唯一得到 | 证据 |
|---|---|---|
| `snapshot_config_sha256` | 能 | `LoadedM3Config.snapshot_config_sha256` |
| `g1_release_id` / `g1_release_manifest_sha256` | 仅能从**未验真** snapshot manifest 引导 | public `read_snapshot_manifest(stage_root/snapshots/<snapshot_id>/manifest.json)`；`SnapshotManifestV1` **不含** `code_version` / `snapshot_request_key` |
| `code_version` | **不能** | 不在 `LoadedM3Config`；权威来源是 `compute_m3_runtime_identity(project_root, config_paths, frozen_config_digests)`（`runtime_identity.py`）。该函数需要 **config 相对路径**；`LoadedM3Config` 只有可选 `raw_config_sha256`，**没有** source path / relative path 字段 |

现有 CLI（`run_m3._dispatch_public`）在调用 runtime identity 前保留了：

```text
config_relative = PurePosixPath(config_path.relative_to(project_root))
```

但 C0 冻结签名故意不接收 `config_path` / `config_relative`，C1 合同也只写「`load_m3_config` 一次 → resolver 一次」，未把路径注入 resolver。

`snapshot-requests/` 只按 `snapshot_request_key` 命名；`snapshots/<snapshot_id>/` 树仅含 `manifest.json` / `session_calendar.parquet` / `staging/`，**无** request key 指针。要从 `snapshot_id` 反查 request 只能扫描 `snapshot-requests/`——任务明确禁止。

### 2.3 应遵循规则

- 任务单 §3：组合 key 只能调用现有 compute_*；无法唯一求出任一 key/path → **立即停止**
- 任务单 §9：需要扫描/私有 helper、修改 verifier/receipt/上游 production、接受 caller capability → **停止**
- SSOT §4.9：`code_version` 来自 Git/source-tree + 版本化配置路径集合；snapshot request 映射以 `snapshot_request_key` 为唯一文件名

### 2.4 最小复现（逻辑）

给定合法 `project_root`、任意 `--config` 加载得到的 `LoadedM3Config`、已发布 `snapshots/<snapshot_id>/manifest.json`：

1. 可读 g1 identity 与 `snapshot_config_sha256`
2. 仍缺少 `code_version`
3. 无法调用 `compute_snapshot_request_key` 得到唯一 key
4. 无法打开唯一 `snapshot-requests/<key>.json` / `receipts/snapshot/<key>.json`
5. 无法按依赖顺序调用 `verify_snapshot_artifact`（需要 `snapshot_request_path`、`snapshot_receipt_path`、`SnapshotBuildSpec.snapshot_request_key`）

### 2.5 最小 API 重冻建议（供主 Agent）

任选其一（推荐 A；保持零扫描）：

**A. 扩展 resolver 输入（最小、与现有 CLI 一致）**

```python
def resolve_formal_backtest_cli_inputs(
    *,
    project_root: Path,
    config: LoadedM3Config,
    config_relative: PurePosixPath,  # 新增：相对 project_root 的配置 POSIX 路径
    snapshot_id: str,
    fold: str,
    horizon: int,
) -> FormalBacktestCliResolution: ...
```

C1 在 `load_m3_config(config_path)` 后传入同一 `config_relative`；resolver 内 exact 一次 `compute_m3_runtime_identity(..., config_paths=(config_relative,), frozen_config_digests=(M3SourceDigestV1(config_relative.as_posix(), config.raw_config_sha256),))`（要求 `raw_config_sha256` 非空），再派生全部 key。

**B. 把 config 相对路径冻入 `LoadedM3Config`（上游 config 合同变更）**  
由 `load_m3_config` 记录 relative path；C0 签名可不变，但超出本包白名单，需单独重冻 C0/config SSOT。

**C. 在 snapshot manifest/request 旁增加 `snapshot_id → snapshot_request_key` 具名只读指针**  
例如 `snapshots/<id>/request_key.json` 或把 key 写入 manifest；需改 snapshot 发布/验真合同，禁止 C0 自行发明。

不接受的迁就：扫描 `snapshot-requests/`、猜最新 G1、caller 传入 roots/capability/resolution、复制私有 helper、修改 verifier 签名。

### 2.6 通过条件（重冻后）

- 仅用重冻后的 public 输入 + 具名 path，可计算全部五类 key，且与已发布 request/receipt `scope_key` 一致
- 无需扫描目录即可定位 13 层 artifact/receipt
- 身份漂移（code/config/request）fail-closed 且稳定脱敏

## 3. 派生链其余部分（审计通过处，供重冻后实现）

在补齐 `code_version` / runtime identity 后，下列路径**可**唯一派生（证据摘要）：

| 步骤 | 派生 | Public 依据 |
|---|---|---|
| stage_root | `project_root / tracking.artifact_root`（相对 POSIX、禁逃逸） | 任务单 §3；`run_m3._prepare_stage_root` 同类规则 |
| G1 root | `project_root/data/clean/m3_g1/releases/<g1_release_id>/` | `run_m3._verify_requested_release`；`G1Release` 要求 `root.name == release_id` |
| artifact_roots | 至少 `G1_RELEASE`→release.root，`G8`→stage_root，`EXTERNAL_QLIB`→`project_root/data/external/qlib/v0.9.7` | SSOT §4.9 aliases；provider receipt 强制 `EXTERNAL_QLIB`/`dump_bin.py`；`DEFAULT_TARGET_PATH` |
| provider / validation / experiment / labels / folds / features / work/* | 由 compute_* key + 任务单具名模板 | 任务单 §3 |
| `ProviderBuildSpec` | verify 后由 config dump tool + live `build_provider_runtime_fingerprint` + manifest.code_version 重建 | `provider._verify_provider` |
| `ExperimentIdentitySpec` | runtime identity + `scientific_config_sha256` | contracts |
| `LightgbmTrainingSpec` | public `build_lightgbm_training_spec(config)` | `model.py` |
| UpstreamPaths 嵌套 | receipt/request/dump_tool 具名 path 组装 | `FoldPlanUpstreamPaths` 等 public constructors |
| `work_key` | `compute_work_key(experiment_key, fold, horizon)` | 与 target/plan manifest 对齐 |
| `BacktestArtifactFreshVerificationContext` | plan fresh context + `g1_receipt_path=release.root/"receipt.json"` | `a_share_reporting` 形式约束 |

13 层 verifier 实际 formal 签名与任务单顺序一致；`verify_provider_artifact` **不**接收 spec（内部重建），自 folds 起需要 caller 重建的 BuildSpec/UpstreamPaths。

## 4. 次要风险（非本轮停止主因，重冻时应一并裁定）

1. **Formal G1 无 `receipt.json`**：`verify_g1_release` 的 `_FINAL_ENTRY_NAMES` 不含 `receipt.json`，但 `BacktestArtifactUpstreamPaths.g1_receipt_path` 被 formal 校验钉死为 `release.root/receipt.json`。路径可派生，真实 formal G1 上该文件不存在 → C1 digest 21 输入时会 fail-closed。属 G1↔G7F/G8 既有张力，建议主 Agent 在 C0 重冻或 C1 前裁定，**不应**由 C0 伪造 receipt。
2. **`label_build_code_version`**：`LabelBuildSpec` 需要该字段；生产校验主要对齐 config `label_version` 与 experiment identity，未在 public 面提供独立 builder。重冻时应明确 = runtime `code_version` 或另给 public builder。
3. **全链单测成本**：真实 13 verifier once 很难在 unit 内诚实构造；任务已允许申请单一 integration。停止本轮不申请文件，待 API 重冻后再开。

## 5. 未执行项

- 未实现 `formal_cli_resolve.py` / 惰性导出 / 测试
- 未跑 focused pytest / Ruff / mypy / WSL（无实现可验）
- 未宣称任何 Gate/工程合同 PASS
- 未联网、未安装、未 add/commit、未写正式 artifact

## 6. 交接

| 项 | 值 |
|---|---|
| 状态 | **停止待重冻** |
| 阻塞 | 五元组缺少 `code_version` 所需的 config 相对路径（或等价具名 snapshot→request 指针） |
| 下一步 | 主 Agent 按 §2.5 重冻 API/SSOT → 新外部实现会话 → 另一全新外部独立初验 |
| 模型 | cursor-grok-4.5-high |
