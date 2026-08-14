# M3 G8 R2：G7F Quality 与 Release Context 同步返工独立复验报告

日期：2026-08-11  
角色：未参与实现的全新外部独立初验 Agent（只读 production / 实现测试 / 任务书与交付报告）  
唯一写入：本报告  
结论：**FAIL**（不解锁主验；非 ext4 / 非 G8 Gate）

依据：`AGENTS.md` / `.ai/workflows/multi_agent_delivery.md`、[`M3_G8_R1任务单.md`](M3_G8_R1任务单.md) §12、G7F R4 主验合同、[`M3_G8_R2_G7FQuality与ReleaseContext同步返工交付报告.md`](M3_G8_R2_G7FQuality与ReleaseContext同步返工交付报告.md)

---

## 1. 总判

| §12 重点 | 结论 |
|---|---|
| 1) exact `BacktestArtifactFreshVerificationContext` + 21-input（manifest/quality/八表，拒 old/four-path/fake receipt/subclass/duck，零 property access） | **PASS** |
| 2) 每次 StageRunner closure actual `verify_backtest_build_output`；closure 顺序/次数沿 §9 | **PASS** |
| 3) copied-root；三窗 inode；`_EntityGuardedFormalBacktestStageRunner` 诚实覆盖 final→receipt、不改 primitive、不缓存 | **PASS（Windows 实触达）** |
| 4) WSL 首轮 2 fail 放宽是否仅为平台错误码差异且仍 fail-closed；当前 revision 重跑终态 | **FAIL** |
| 5) Windows 定向/邻接、Ruff/mypy/cold/diff；WSL golden 仅 capability false 窄 skip | 定向/静态 **PASS**；WSL combo 绿但后两窗测试诚实性被 §4 否决 |

---

## 2. 阻断项（FAIL）

### 现象

交付将后两窗（`after_temp_before_final` / `after_final_before_receipt`）允许码扩为
`{STAGE_RECOVERY_CONFLICT, STAGE_PUBLISH_FAILED}`，称 WSL/DrvFS「平台错误码差异」。  
当前 revision 独立对抗探针证明：在 WSL `platform_supports_renameat2_noreplace()==False` 时，两窗均在
**temp closure 之后、mutation/EntityGuarded 之前** 因 `commit_directory_noreplace` →
`G1_RELEASE_PUBLISH_UNSUPPORTED` 得到 `STAGE_PUBLISH_FAILED`：

| 窗 | pre 次数 | mut | entity_guard | commit_exc | code | receipt/tmp |
|---|---|---|---|---|---|---|
| after_temp_before_final | 1 | False | 0 | `G1_RELEASE_PUBLISH_UNSUPPORTED` | `STAGE_PUBLISH_FAILED` | 空 |
| after_final_before_receipt | 1 | False | 0 | 同上 | 同上 | 空 |

同探针 Windows（capability True）对照：

| 窗 | pre | mut | eg | code |
|---|---|---|---|---|
| after_temp_before_final | 2 | True | 0（final closure 检出） | `STAGE_RECOVERY_CONFLICT` |
| after_final_before_receipt | 2 | True | 1（进入 EntityGuarded，未进 base publish） | `STAGE_RECOVERY_CONFLICT` |

因此 WSL「绿」不是同一实体检出路径的码差，而是 **exclusive commit 不可达导致实体窗未执行**。

### 根因

DrvFS/WSL1 无 renameat2 noreplace；StageRunner 在 commit 失败且 final 未落成时映射 `STAGE_PUBLISH_FAILED`。  
测试断言放宽把该平台短路算作 §12.2.4 三窗 inode 反例通过。

### 应遵循规则

- 任务 §12.2.4：三窗同路径 quality/market inode 替换须在 receipt 前因实体/闭包合同 fail-closed。  
- §12.5 / §11：仅 **actual golden** 允许 capability false 窄 skip；不得用 `STAGE_PUBLISH_FAILED` 伪装未触达的实体窗。  
- `AGENTS.md` §11：独立初验不得只复述实现报告；反例须证明合同路径被执行。

### 最小复现

WSL base + `PYTHONPATH=src`，对当前 worktree 跑独立探针（系统临时目录，不改仓库）：  
capability False → 仅 `pre=1` → `commit_exc=G1_RELEASE_PUBLISH_UNSUPPORTED` → `STAGE_PUBLISH_FAILED`，`mut=False`，`eg=0`。

### 新增测试（返工必须）

1. `platform_supports_renameat2_noreplace() is False` 时：后两窗 **窄 skip**，reason 写明
   `exclusive commit unsupported; inode window unreachable`（或等价），**禁止**接受
   `STAGE_PUBLISH_FAILED` 作为实体反例通过。  
2. capability True（Windows / 未来 ext4）：后两窗 **只允许** 实体检出对应码
   （当前实据为 `STAGE_RECOVERY_CONFLICT`），并断言 mutation 发生且
   final→receipt 窗进入 `_EntityGuardedFormalBacktestStageRunner._publish_static_receipt`。  
3. 保留「无 receipt / 无 temp 残留 / cause·context 为空」。

### 通过条件

- Windows：三窗 + EntityGuarded 实触达绿（与本轮对照一致）。  
- WSL：unit+golden 终态诚实（后两窗 skip 或在 capability true 宿主实跑）；golden 仍仅 §11 窄 skip。  
- 交付不得再声称「仅错误码差异」。  
- 全新独立复验再过一次后才可进主验。

---

## 3. 其余合同映射（非阻断摘要）

### 3.1 exact context / 21-input / 零 property access — PASS

- `make_formal_backtest_run_plan` / `run_formal_backtest_stage`：`type(fresh_context) is BacktestArtifactFreshVerificationContext`。  
- 21-input 唯一经 `backtest_artifact_input_paths`：`manifest.json` + `quality.json` + 八表；无 `receipt.json`。  
- 实现测试拒 four-path 构造、SimpleNamespace duck、subclass、缺 `release` 旧对象。  
- **独立对抗（实现者未用）**：`@property` 一触即 `AssertionError` 的 PropDuck → `STAGE_INPUT_INVALID`，
  cause/context 空，**未触发任何 property**（证明靠 `type is`，非 duck/getattr）。

### 3.2 closure 实际重验与 §9 顺序 — PASS

- `closure` 每次调用模块内 `verify_backtest_build_output`（经 G7F `_formal_bundle` →
  `_validate_formal_input_identity` → `_validate_formal_release_context_binding` 重捕 snapshot）。  
- Windows actual golden：首发 `build, pre, pre, final`；resume / resume=False / orphan 顺序断言仍在。  
- EntityGuarded **不缓存** snapshot：每次 `_publish_static_receipt` 重入 `backtest_artifact_input_paths`。

### 3.3 EntityGuarded 诚实性 — PASS（Windows）

- 子类位于 `backtest_stage.py`，仅覆盖 `_publish_static_receipt`；`StageRunner` primitive 仍属
  `orchestration.py`（`EG_OVERRIDES` / `BASE_OWN_PUBLISH` 均为 True）。  
- final→receipt：独立探针 `entity_guard_enter=1`，`base_publish=0`，码 `STAGE_RECOVERY_CONFLICT`，无 receipt/tmp。  
- copied-root outer release：plan/run 均 `STAGE_INPUT_INVALID`（实现测试 + 类型/字段相等合同）。

### 3.4 验证终态（本轮独立执行）

| 平台 | 项 | 结果 |
|---|---|---|
| Windows | G8 unit | **12 passed**，760.40s |
| Windows | G8 golden | **1 passed**，1000.55s（capability True） |
| Windows | 邻接 G7F unit + StageRunner/编排/nested | **87 passed**，935.91s |
| Windows | Ruff / mypy / cold | All passed / Success / `cold-ok True` |
| WSL base | G8 unit+golden | **12 passed, 1 skipped**，529.80s |
| WSL | golden skip reason | `host lacks atomic directory no-replace publication`（§11 窄 skip） |
| WSL | Ruff / mypy / cold | All passed / Success / `cold-ok False` |
| 双方 | 未联网、未 add/commit；本 Agent 仅新增本报告 |

`backtest_stage.py` git blob：`e7dcd9827098709c94d85b41a5c4214740b8441d`（与交付报告一致；标注 SHA256 实为 blob id）。

---

## 4. 独立对抗清单（实现者未用）

1. PropDuck 零 property access（上）。  
2. WSL vs Windows 同脚本三窗触达追踪（mut/eg/commit_exc）——暴露放宽假绿。  
3. EntityGuarded 进入计数 vs base `_publish_static_receipt`（证明子类拦截且不改 primitive）。  
4. 21-input 尾段名精确为 quality+八表、无 G1 receipt（运行时再确认）。

---

## 5. 边界声明

- 本报告 **FAIL**：只阻止进入主验；不评价 ext4、不关闭 G8/M3 Gate。  
- WSL DrvFS 绿测 ≠ Linux ext4 Gate。  
- production / 实现测试本轮只读；未改 G7F/G1/StageRunner primitive/tracking/CLI。

下一步：主 Agent 按 §2 冻结返工任务 → 外部实现收紧后两窗 capability 门控 → **另一**全新独立复验。
