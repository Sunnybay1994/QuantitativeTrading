# M3 G8C-C0 R2：configRelative 与 G7F R4 同步交付报告

日期：2026-08-11  
角色：外部实现 Agent（cursor-grok-4.5-high，全新会话）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
任务单：[`M3_G8C_C0_R1正式BacktestCLI输入Resolver任务单.md`](M3_G8C_C0_R1正式BacktestCLI输入Resolver任务单.md) §10  
R1 停止：[`M3_G8C_C0_R1正式BacktestCLI输入Resolver交付报告.md`](M3_G8C_C0_R1正式BacktestCLI输入Resolver交付报告.md)  
结论：**生产 resolver 已按 §10 落地；输入/脱敏/零写/cold 矩阵绿；13 层 public 全链 happy-path 按 §9 停止，申请单一 integration 文件**

## 1. 白名单改动

| 路径 | 说明 |
|---|---|
| `src/quant/research/m3/formal_cli_resolve.py` | 新增零写 resolver |
| `src/quant/research/m3/__init__.py` | 仅惰性导出 `FormalCliResolveError` / `FormalBacktestCliResolution` / `resolve_formal_backtest_cli_inputs` |
| `tests/unit/test_m3_g8c_c0_formal_cli_resolve.py` | 输入矩阵、cold、零写、脱敏、无 roots/digest 入口 |
| 任务单状态 | 更新为 R2 交付/待 integration |
| 本报告 | 唯一交付报告 |

未改：`run_m3`、orchestration/StageRunner、上游 verifier/contracts/configs、既有 tests/docs、正式 artifacts。未联网/add/commit。

## 2. §10 合同落地摘要

- API：`config_relative: PurePosixPath`；锚定 `project_root/config_relative` 真实普通文件（拒 symlink/reparse/`st_nlink!=1`），sha256 exact=`raw_config_sha256`；exact 一次 `compute_m3_runtime_identity(..., config_paths=(config_relative,), frozen_config_digests=(M3SourceDigestV1(...),))`。
- G1：bootstrap 只读 snapshot manifest/request 取 `g1_release_id`/`g1_release_manifest_sha256` → 派生 `data/clean/m3_g1/releases/<id>/` → public `G1Release` + `verify_g1_release`；无 `receipt.json`、无扫描 releases、无 fake receipt。
- 13 层 public verifier 由 resolver 直接按依赖序各调用一次；BuildSpec/UpstreamPaths 仅用 public constructor + fresh manifest/config + 具名 receipt path。
- Fresh context：`FormalBacktestArtifactUpstreamPaths(target, plan, experiment)` + `BacktestArtifactFreshVerificationContext(..., release=release)`（G7F R4 current）；不调用 G7F final / G7E / StageRunner / tracking；不加载 MLflow。
- 失败：`FormalCliResolveError`，`__cause__`/`__context__` 清空；消息无绝对 path/hash/TOKEN。

## 3. 验证证据

| 平台 | 命令 | 结果 |
|---|---|---|
| Windows Miniforge | `pytest tests/unit/test_m3_g8c_c0_formal_cli_resolve.py` | **13 passed** |
| Windows | Ruff（实现/测试/`__init__`） | PASS |
| Windows | mypy（实现+测试） | Success: 2 files |
| Windows | cold import（无新增 mlflow/qlib/lightgbm） | PASS |
| WSL base / DrvFS | 同上 focused pytest | **13 passed** |
| WSL base | Ruff / mypy / cold | PASS |

（WSL1/DrvFS 仅兼容证据，非 ext4 Gate。）

## 4. §9 停止：申请单一 integration

### 现象
unit 白名单内无法诚实最小构造「已发布 formal G1→backtest_plan」完整 stage 树，因而无法在不 monkeypatch verifier、不复制千行伪 formal 链的前提下覆盖：13 verifier 各 once、happy-path 绑定 `run_formal_backtest_stage` 签名。

### 根因
真实全链依赖 G1 release + EXTERNAL_QLIB dump tool + 多 stage receipt/artifact 实体闭包；既有 G4–G7F unit fixture 使用简化 alias/`common` 布局与伪造 code_version，不能直接充当 G8 stage 具名路径合同；复制/改编将命中「大型伪 formal 链」停止条件。

### 应遵循规则
任务单 §7.3 / §9 / §10.3：真实 public 全链只能在 integration fixture 诚实构造时，停止并申请新增**单一** integration 文件，不得自行添加。

### 申请
允许新增唯一：

`tests/integration/test_m3_g8c_c0_formal_cli_resolve.py`

用于：最小诚实 formal 链（或复用已主验 capability 的窄 fixture）覆盖 13 verifier once + resolution 字段可绑定 `run_formal_backtest_stage`（不真跑 StageRunner）。

### 通过条件（批准后下一实现轮）
- integration happy-path 绿；resolver 直接调用 13 public verifier 各一次且顺序正确
- 仍零写、不加载 MLflow、不改上游 production
- Windows + WSL base focused 绿

## 5. 未决 / 非声明

- 未宣称独立初验、主验、G8C-C0 工程合同 PASS、Gate/ext4/C1 解锁
- `label_build_code_version` 取 runtime `code_version`（身份连续）；若历史产物用其他字面量，verify 会 fail-closed
- provider/validation key 派生同样依赖当前 runtime fingerprint 与 code_version 连续

## 6. 下一步

1. 主 Agent 批准或驳回单一 integration 文件申请  
2. 批准后：新外部实现会话补 integration → 另一全新外部独立初验 → 主验  
3. 独立初验报告路径（只读）：`docs/agent/M3_G8C_C0_R2_configRelative与G7FR4同步独立复验报告.md`
