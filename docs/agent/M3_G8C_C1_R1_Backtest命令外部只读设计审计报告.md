# M3 G8C-C1 R1：Backtest 命令外部只读设计审计报告

日期：2026-08-11  
角色：全新外部 Cursor **严格只读**设计审计 Agent（`cursor-grok-4.5-high`）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
前提：**G8C C0 F0 R3 正在独立初验，尚未主验；C0 整体主验未开；本报告只做可冻结任务设计，禁止实现 C1/C2**  
权威合同：根 `AGENTS.md`、`.ai/README.md`、`docs/M3实施与Agent交接.md` §4.9 CLI、G8Continuation §4、C0 任务单 §6、G8 R1 formal backtest、G8A/G8B/G8D 已主验边界

---

## 0. 审计结论（压缩）

| 项 | 结论 |
|---|---|
| C1 最小目标 | 仅接通 public `backtest`：`load_m3_config`×1 → `resolve_formal_backtest_cli_inputs`×1 → `run_formal_backtest_stage`×1 → 规范 JSON/退出码 |
| 可冻结性 | **设计可冻结**；**实现授权未解锁**（依赖 F0 R3 独立初验→主验→C0 整体主验 PASS） |
| 不得实现 | C2 tracking CLI；`train`/`evaluate`/`run-all`/`verify-reproducibility`/`acceptance-audit` 真实 handler；任何 MLflow production client |
| 本会话写入 | 仅本报告；生产/测试/既有文档只读；未跑长链、未联网、未 add/commit |

---

## 1. Actual 合同核对（只读证据）

### 1.1 `run_m3.py` parser / dispatcher（现状）

- Public 八命令已在 `build_parser()` 注册；`backtest` 已有 `--config`、`--snapshot-id`(hex64)、`--fold`(`fold_NNN`)、`--horizon∈{5,10}`，`stop_stage="backtest"`。
- **`--no-resume` 仅存在于内部 `experiment-identity`**；public `backtest` **尚未**暴露该开关。
- `_dispatch_public` 仅实现 `readiness`/`snapshot`；其余（含 `backtest`）固定：

```text
CommandFailure(scope="command", node_id=<cmd>,
               error_code="M3_COMMAND_HANDLER_UNAVAILABLE", exit_code=5)
```

- stdout 恰一份 `sort_keys`/`separators=(",",":")`/`allow_nan=False` JSON；dispatcher stdout 丢弃；任意非 `CommandSummary` 安全细节或异常 → `M3_COMMAND_FAILED/5`（**不信任**异常自带 `.code`，除非 dispatcher **内部**捕获并翻译为 `CommandSummary`）。
- 成功 details 禁止绝对路径、token/secret、非有限 float；`CommandSummary.exit_code` = failures 最小非零，无失败则为 0。

### 1.2 `formal_cli_resolve.py`（C0 actual public API）

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
    # __reduce__ → TypeError；不可 pickle

def resolve_formal_backtest_cli_inputs(
    *,
    project_root: Path,
    config: LoadedM3Config,
    config_relative: PurePosixPath,
    snapshot_id: str,
    fold: str,
    horizon: int,
) -> FormalBacktestCliResolution: ...
```

稳定 `code` / `exit_code`（actual）：

| code | exit |
|---|---|
| `FORMAL_CLI_INPUT_INVALID` | 2 |
| `FORMAL_CLI_CONFIG_INVALID` | 2 |
| `FORMAL_CLI_RUNTIME_IDENTITY_INVALID` | 2 |
| `FORMAL_CLI_G1_INVALID` | 3 |
| `FORMAL_CLI_UPSTREAM_INVALID` | 3 |
| `FORMAL_CLI_DEPENDENCY_UNAVAILABLE` | 4 |
| `FORMAL_CLI_ARTIFACT_MISSING` | 5 |
| `FORMAL_CLI_CLOSURE_DRIFT` | 5 |

Resolver：**零写**；13 层 public verifier；禁止 caller roots/path/digest/resolution 入口；`config` 返回同一 `LoadedM3Config` 对象。

### 1.3 `backtest_stage.py`（G8 R1 已主验）

```python
def run_formal_backtest_stage(
    *,
    stage_root: Path,
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    release: VerifiedG1Release,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    fresh_context: BacktestArtifactFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
    resume: bool = True,
) -> FormalBacktestStageResult: ...

@dataclass(frozen=True)
class FormalBacktestStageResult:
    final_root: Path
    receipt_path: Path
    verified: VerifiedBacktestArtifact
    receipt: StageReceipt
    reused: bool
    # __reduce__ → TypeError
```

- 单 WORK 节点 `node_id=f"backtest.{fold}.h{horizon}"`；21-input / 29-output；StageRunner no-clobber。
- `resume=True` completed → handler0 + reuse；`resume=False` completed → `STAGE_ALREADY_COMPLETE`。
- 公开失败为 `M3StageRunnerError`，codes：`STAGE_INPUT_INVALID` | `STAGE_LOCK_FAILED` | `STAGE_BUILD_FAILED` | `STAGE_OUTPUT_INVALID` | `STAGE_PUBLISH_FAILED` | `STAGE_RECOVERY_CONFLICT` | `STAGE_ALREADY_COMPLETE`。

### 1.4 G8A / G8B / G8D 已主验边界（C1 只消费，不重开）

| 包 | 对 C1 的约束 |
|---|---|
| **G8A** | plan/key 只从 verified 上游闭包；WORK 止于 tracking 的拓扑已存在，但 **C1 不得推进到 tracking** |
| **G8B** | `run_static` no-clobber、resume / no-resume / orphan / partial / conflict；C1 不得改 StageRunner primitive |
| **G8 R1** | formal backtest wave 已主验；C1 只接线，不改 `backtest_stage` / reporting verifier |
| **G8D-F1 R2** | formal tracking wave 已主验；**C1 禁止调用** `run_formal_tracking_stage` / MLflow；留给 C2 |

### 1.5 SSOT CLI 退出码（`docs/M3实施与Agent交接.md`）

0 成功/验真复用；2 参数/配置/契约；3 readiness/G1/snapshot 数据门禁；4 依赖；5 本地 stage/receipt；6 tracking；7 冷启动比较；8 质量/验收。  
C1 成功路径止于 backtest，**不得**产生 exit 6+。

---

## 2. 可冻结 C1 最小合同

### 2.1 Exact public CLI 表面

**命令**

```text
python -m quant.research.run_m3 backtest \
  --config <project-relative-or-under-root> \
  --snapshot-id <bare-hex64> \
  --fold fold_NNN \
  --horizon {5|10} \
  [--no-resume]
```

**新增 parser 冻结（仅 `backtest`）**

- 增加 `backtest.add_argument("--no-resume", action="store_true")`。
- **不**给 `train`/`evaluate`/`run-all`/… 加 handler 或 `--no-resume`（C1 最小）。
- 既有 identity 校验保持：非法 fold/horizon/双 source 等仍在 dispatcher 前 `M3_CLI_USAGE_INVALID/2`。

**禁止新增的 CLI 参数**

- 任何 `stage-root` / `artifact-roots` / `work-key` / `experiment-key` / `resolution` / `receipt` / `g1-release-root` / pickle path。
- tracking URI、MLflow run id、offline client 开关。

### 2.2 Exact 调用顺序与 fresh / 零写边界

```text
main.parse
  → _dispatch_public(command=="backtest")
      1) project_root = Path.cwd().resolve(strict=True)
      2) 从用户 --config 派生 config_relative: PurePosixPath
         （必须与 C0 R3「原路径逐 component lstat、无 symlink/reparse」兼容；
          禁止先 Path.resolve() 跟叶链接再 relative_to，以免绕过 C0 锚定）
      3) load_m3_config(<anchored config path>)  exact ×1
         （失败 → M3_CONFIG_INVALID 或沿用 readiness 等价的 exit 2 映射；见 §2.4）
      4) resolve_formal_backtest_cli_inputs(
            project_root=..., config=<同一对象>, config_relative=...,
            snapshot_id=args.snapshot_id, fold=args.fold, horizon=args.horizon,
         )  exact ×1
         · 此阶段零写（C0 合同）
         · FormalCliResolveError → CommandSummary（见 §2.4），不得 re-raise 到 _run_public
      5) run_formal_backtest_stage(
            stage_root=r.stage_root,
            target=r.target, plan=r.plan, release=r.release,
            experiment=r.experiment, config=r.config,
            fresh_context=r.fresh_context,
            artifact_roots=r.artifact_roots,
            resume=not args.no_resume,
         )  exact ×1
         · 仅 StageRunner 在已解析 stage_root 下做 no-clobber 发布/receipt
         · 禁止 C1 额外 mkdir/扫描/补生成上游 stage
      6) 组装成功 CommandSummary（§2.3）
```

**跨进程 / fresh**

- 每个 OS 进程必须完整执行 1–5；禁止缓存 `FormalBacktestCliResolution` / verified capability 到磁盘或 pickle。
- 禁止 CLI/`dispatcher=` 注入 caller-supplied resolution。
- 子进程/复跑 = 重新 resolve + 重新 stage（resume 语义由 StageRunner 决定，不是跳过 resolve）。

**零写边界**

| 阶段 | 允许写？ |
|---|---|
| parse / usage 失败 | 否 |
| load_m3_config / resolve 失败 | 否（resolver 本身零写；C1 不得预创建 stage_root） |
| resolve 成功、stage 前 | 否 |
| `run_formal_backtest_stage` | 仅 StageRunner 合同内 temp→final no-clobber + 外置 receipt |
| 其他 public 命令 | 仍 UNAVAILABLE；不得写 |

### 2.3 成功规范 JSON（exact schema）

进程 exit **0**；stdout 单行 canonical JSON：

```json
{
  "command": "backtest",
  "failures": [],
  "fold": "fold_001",
  "horizon": 5,
  "ok": true,
  "reused": false,
  "snapshot_id": "<64-hex>",
  "stop_stage": "backtest",
  "work_key": "<64-hex>"
}
```

字段冻结：

- `fold` / `horizon` / `snapshot_id`：来自 **已解析 CLI args**（与 resolution 闭包一致；不一致应在 resolve/stage 已 fail-closed）。
- `work_key`：`resolution.work_key`（必须 == target/plan manifest）。
- `reused`：`FormalBacktestStageResult.reused`（bool）。
- `stop_stage`：字面 `"backtest"`。
- **禁止** details 含：`final_root`、`receipt_path`、绝对路径、URI、token、receipt/manifest 原文 hash 列表、MLflow 字段、exception message。

### 2.4 失败规范 JSON / 退出码映射

统一形态（与现 CLI 合同一致）：

```json
{
  "command": "backtest",
  "failures": [
    {
      "error_code": "<STABLE_CODE>",
      "exit_code": <2-5>,
      "node_id": "backtest",
      "scope": "command"
    }
  ],
  "ok": false
}
```

| 来源 | error_code | exit | 备注 |
|---|---|---|---|
| argparse / usage | `M3_CLI_USAGE_INVALID` | 2 | dispatcher 未调用 |
| config load / project 边界（C1 层） | `M3_CONFIG_INVALID` | 2 | 对齐 readiness/snapshot |
| `FormalCliResolveError` | **原样** `exc.code` | **原样** `exc.exit_code` | 仅当 `type is FormalCliResolveError`；cause/context 已空 |
| `M3StageRunnerError` | **原样** `exc.code` | 5 | 含 `STAGE_ALREADY_COMPLETE` |
| 其他 Exception | `M3_COMMAND_FAILED` | 5 | 不得泄漏 message；不得信任 `.code` |
| 未实现的其他命令 | `M3_COMMAND_HANDLER_UNAVAILABLE` | 5 | **保持** |

多失败时仍全量列出、按 `(scope,node_id,error_code)` 排序、进程取最小非零码（C1 单命令通常单 failure）。

**必须继续 UNAVAILABLE（不得实现）**

`train`、`evaluate`、`run-all`、`verify-reproducibility`、`acceptance-audit`；以及任何 tracking/MLflow handler。C1 测试须回归断言这些命令仍为 UNAVAILABLE。

---

## 3. 文件白名单（未来实现包；本审计不改）

### 3.1 允许修改

| 路径 | 动作 |
|---|---|
| `src/quant/research/run_m3.py` | 仅：`backtest` 增加 `--no-resume`；`_dispatch_public` 增加 backtest 分支按 §2.2–2.4 |
| `tests/unit/test_m3_run_cli.py` | 扩展：UNAVAILABLE 回归仍含 train 等；可增 backtest usage/`--no-resume` 解析 |
| `tests/unit/test_m3_g8c_c1_backtest_cli.py` | **新增** focused unit（mock/patch 边界见 §4） |
| `tests/integration/test_m3_g8c_c1_backtest_cli.py` | **仅当** F0 诚实链主验后可复用；owned temp roots 上 actual resolve→stage；禁止伪 fixture |
| `docs/agent/M3_G8C_C1_R1_*任务单.md` / 交付 / 独立初验报告 | 由主 Agent 冻结任务后的外部闭环写入 |

### 3.2 明确禁止修改（C1）

- `formal_cli_resolve.py`（C0 已冻；C1 只调用）
- `backtest_stage.py`、`a_share_*.py`、G7 verifier/contracts
- `tracking.py` / `tracking_stage.py` / MLflow 相关
- `orchestration.py` StageRunner primitive（除非主验发现真实接线冲突并重开合同）
- `m3/__init__.py`（已惰性导出 resolver/stage；C1 不需扩 export，除非证明冷导入断裂）
- 正式 `data/` artifacts、configs 科学键、路线图 Gate 勾选
- C2 范围文档之外的 tracking CLI 设计落地

### 3.3 已有可只读复用

- `tests/support/m3_formal_public_chain/*`（F0；**主验 PASS 前不得假定可写 integration**）
- `tests/unit/test_m3_g8_r1_formal_backtest_stage.py`、golden（stage 行为 SSOT）
- `tests/unit/test_m3_g8c_c0_formal_cli_resolve.py`、integration（resolver 行为 SSOT）

---

## 4. 反例矩阵（实现与独立初验必须覆盖）

### 4.1 Hostile / 脱敏

- dispatcher/stage/resolver 抛带 `TOKEN=`、`Bearer`、`C:\...`、`/home/...`、`\\server\...` 的异常 → stdout 仅稳定 code；无 traceback。
- hostile Mapping 作为 details 注入尝试 → `M3_COMMAND_FAILED`。
- FormalCliResolveError 与递归 `__cause__` 不得进入 JSON（C0 已清空；C1 不得 `str(exc)` 入 details）。

### 4.2 Identity / 闭包

- 错误 snapshot_id / fold / horizon（parser 层与 resolve 层）。
- config_relative 叶/中间 symlink、junction、hardlink、same-bytes 换 inode（依赖 C0；C1 断言 **stage 未启动、零写**）。
- runtime/code/config 与 snapshot request 漂移 → resolve fail，exit 2/5 按 C0 code，零写。
- 跨 work 合法重签拼接 → fail-closed。

### 4.3 Cross-process / capability

- 断言 `FormalBacktestCliResolution` / `FormalBacktestStageResult` 不可 pickle。
- 无 CLI 入口接受预解析 resolution。
- 文档/测试声明：第二进程必须重新 resolve（可用两次独立 `main([...])` + 独立 monkeypatch 计数：`resolve`×2、`run_formal_backtest_stage`×2）。

### 4.4 Resume / no-clobber

- 首次：`reused=false`，stage 调用 1 次。
- completed + 默认 resume：`reused=true`（handler0 由 stage 合同保证；C1 测 `reused` 与 exit 0）。
- completed + `--no-resume`：`STAGE_ALREADY_COMPLETE/5`；不得覆盖 final。
- partial/orphan/conflict：映射既有 `STAGE_*`；不得留下 C1 自写半成品。
- **禁止**引入普通 rename fallback。

### 4.5 命令隔离

- `train`/`evaluate`/`run-all`/… 仍 `M3_COMMAND_HANDLER_UNAVAILABLE`。
- backtest 成功路径 **不** import/load MLflow；cold import `run_m3` 不加载 Qlib/LightGBM/MLflow（重依赖仅按现有懒加载边界）。
- 不得调用 `run_formal_tracking_stage`。

### 4.6 Unit vs Integration 边界

- Unit：允许对 `resolve_formal_backtest_cli_inputs` / `run_formal_backtest_stage` 做 **窄** monkeypatch 以测接线顺序与 JSON；禁止 patch production verifier 内部、禁止伪造 verified 写入正式根。
- Integration：仅 F0 诚实链；actual 调用真实 resolve+stage；Windows `m3chain312`；WSL1 capability=false 时在链写入前 exact skip。

---

## 5. 平台与验证拓扑

| 环境 | C1 角色 |
|---|---|
| **Windows** `D:\Miniforge3\envs\m3chain312\python.exe` | 诚实 formal 链 + backtest CLI integration 主反馈环（与 F0 一致） |
| **Windows** 普通 Miniforge（若任务书指定） | 定向 unit / Ruff / mypy 可补充，不得替代 m3chain312 actual |
| **WSL1 / DrvFS** `base` | `platform_supports_renameat2_noreplace()==false` → actual publish **窄 skip**；其余 unit/静态仍绿 |
| **未来 Linux ext4** | capability=true 时完整 actual golden/integration；**当前不得**用 WSL1 skip 关闭 Gate |

验证顺序（实现包，非本审计）：focused unit → 定向 Ruff/mypy →（条件满足时）单轮 Windows actual integration → WSL skip 断言；禁止机械全量与并发长链。

---

## 6. 停止条件（C1 实现/初验任一命中即停）

1. F0 R3 独立初验或主验未 PASS；或 C0 resolver 整体主验未 PASS。
2. 发现必须修改 C0 resolver 签名、G8 R1 stage 签名、StageRunner no-clobber、G7 verifier 或 receipt schema 才能接线。
3. 只能靠 fake verified / SimpleNamespace / 私有 helper / 扫描目录 / 补生成缺失上游 stage。
4. 需要真实网络、正式仓库 G1 数据、或生产 MLflow 才能做最小证明。
5. 为“方便”实现 train/evaluate/run-all/tracking（即滑入 C2）。
6. WSL1 上用非原子 rename 冒充 no-clobber PASS。
7. support 伪链膨胀或第五模块突破 F0 行数/模块冻结且无主 Agent 重开。

---

## 7. 与 F0 / C0 的依赖（硬门禁）

```text
G8C-C0-F0-R3 独立初验
  → F0 R3 主验 PASS（Windows 诚实 public chain support）
  → C0 formal_cli_resolve 整体主验 PASS
  → 主 Agent 冻结本设计为正式 C1 任务单
  → 外部实现 C1 → 另一外部独立初验 → 主验
  → 其后才可设计 C2 tracking CLI
```

当前状态（审计时点）：**F0 R3 交付已出、独立初验进行中；C1 仅可设计审计，不可实现、不可宣布合同 PASS。**

F0 对 C1 的具体供给：

- 诚实 G1→`backtest_plan` owned 链 + resolver happy-path；
- C1 integration 应在该链上 **多一步** `run_formal_backtest_stage`（仍 owned-only 清理）；
- C0 保证 resolution 字段可直接绑定 stage 签名；C1 不得改绑定形状。

---

## 8. 明确非目标（C1）

- C2：tracking 子命令、MLflow handler、journal CLI。
- `run-all` continuation、reproducibility、acceptance-audit。
- 修改科学配置、费用、或 backtest 算法。
- 宣布 G8/M3/Linux ext4/真实数据 Gate PASS。
- 用 development-example API 冒充 formal CLI。

---

## 9. 建议任务书标题（供主 Agent 在门禁满足后冻结）

`M3_G8C_C1_R1_Backtest命令接线任务单.md`  
正文应 verbatim 吸收本报告 §2–§7 的 API/JSON/退出码/顺序/白名单/反例/停止条件/F0 依赖；并写明实现与初验必须使用不同全新 `cursor-grok-4.5-high` 会话。

---

## 10. 本审计会话声明

- 模型：`cursor-grok-4.5-high`
- 模式：严格只读设计审计；**未实现 C1/C2**
- 唯一写入：本文件
- 未执行：长链 integration、联网、git add/commit
- 结论：**C1 最小 backtest 接线合同可冻结为任务设计；实现授权阻塞于 F0 R3→C0 主验链**
