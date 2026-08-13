# M3 G8D-F1 R1 正式 Tracking StageRunner 独立初验报告

日期：2026-08-10

角色：全新外部独立初验 Agent（未参与实现；上一 Ask 静态会话不计初验）

模型：`cursor-grok-4.5-high`

工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`

结论：**FAIL**（阻断主验；未修改任何生产/测试代码）

只声明工程合同初验失败；不宣称真实 tracking / G8 / M3 / ext4 / 真实 MLflow Gate 状态。

## 1. 范围与只读纪律

- 完整阅读根 `AGENTS.md`、`.ai` 规则、任务单、交付报告与白名单生产/测试。
- 唯一写入本报告；禁止联网 / 真实 MLflow / 安装 / `git add|commit` / 正式 artifact。
- 临时对抗探针仅落系统临时目录，执行后已清理脚本与临时构建树。

HEAD：`eace7ebbd61a622a66f9b1cdb6402f42922aae73`

白名单源码 SHA256（与交付报告一致）：

| 文件 | SHA256 |
|---|---|
| `tracking.py` | `a84292af055c1c9ea57e64824422822abd9e4687bd5a6ad1770f03645e04e9b3` |
| `tracking_stage.py` | `cf4ae7a8fea7b9c0ffefb8e0ec0732d9394448d95f95804512a3be7236160063` |
| `__init__.py` | `866b5a1f7abe4d90d37f6106cf6756a16ed0d38b173118f5e6e8a54bb5c86e11` |
| unit | `790f85c1b926192142a7ab5c72f077a7170067f780634095c351306046f71303` |
| golden | `f83e82d747a69c187c5b3521fc657b9ff19323c9b9b69e964ba25b4e610af903` |

`git diff --check`（白名单）通过。scoped status 仅白名单生产/测试与本任务文档（工作树另有无关既有改动，未纳入本包）。

## 2. 合同逐项映射（摘要）

| 合同项 | 证据 | 结论 |
|---|---|---|
| API：context/request/remote/stage | 源码 + unit/golden | 满足 |
| fresh eval/backtest 各 exact once | golden 计数；独立探针 `fresh_fail_before_remote` 在 remote 前停 | 满足 |
| 34 inputs / 11 uploads / 22 params / 2 tags | unit + 独立 `counts_34_11_22_2` | 满足 |
| request→remote→marker；外置 lock 不进 final | golden + `lock_outside_final` | 满足 |
| 显式 client；无隐式网络 | `client is None`→INPUT；cold import 无 mlflow | 满足 |
| 首次/resume/`resume=False`/orphan 次数 | Windows golden actual | 满足 |
| marker 前崩溃恢复同 run id | unit | 满足 |
| 自洽重签仍被 fresh closure 拒绝 | 独立 `self_consistent_resign_*` + `orphan_resign_fresh_reject` | 满足 |
| 混配 work/experiment/roots/receipt | unit + 独立 mix/missing/alias | 满足 |
| hostile Mapping/client/递归异常脱敏 | 独立 PASS（BUILD/INPUT 稳定、零泄漏） | 满足 |
| 上传相对层级 | 独立：真实 alias + `root/.../0p5x` 分层，无假 `evaluation`/`backtest` alias | 满足 |
| FINISHED 复用「全部 tag/hash 一致」 | 独立：`formal_gate_eligible` 漂移仍被复用 | **不满足（阻断）** |

## 3. 实现者测试动态复跑

### Windows Miniforge（`D:\Miniforge3\python.exe`）

| 命令 | 结果 |
|---|---|
| Ruff 白名单 | All checks passed |
| mypy `tracking.py`/`tracking_stage.py` | Success |
| cold import | `WINDOWS_COLD_IMPORT_PASS True`；`RENAMEAT2_NOREPLACE True` |
| unit+golden 一次 | **10 passed in 382.33s**（actual 未 skip） |
| 邻接 journal + G8R1 unit/golden | **14 passed in 1028.57s** |

### WSL Miniforge base / DrvFS（`/mnt/f/.../m3-g4-formal`）

| 命令 | 结果 |
|---|---|
| capability | `WSL_RENAMEAT2_NOREPLACE False`（非 ext4；仅窄 skip） |
| cold import | `WSL_COLD_IMPORT_PASS True` |
| Ruff / mypy | 通过 |
| 组合一次：G8D unit+golden + journal + G8R1 unit | **22 passed, 1 skipped in 346.32s** |
| 唯一 skip | `test_actual_publish_resume_noresume_orphan_and_remote_counts`（能力位 false） |

未跑真实 MLflow / 网络 / 安装依赖 / 正式 artifact。

## 4. 独立对抗（实现者未用）

临时探针（已清理）：`%TEMP%\g8d_f1_r1_indep_adversarial_probe*.py`

| 反例 | 结果 |
|---|---|
| 34/11/22/2 精确闭包 | PASS |
| artifact 上传相对层级 | PASS |
| FINISHED + protected `quant_request_sha256` 漂移 | PASS（content conflict） |
| FINISHED + request tag `formal_gate_eligible` 漂移 | **FAIL（仍复用）** |
| 额外未知 `quant_*` tag | OBSERVE（当前允许） |
| 同字节 request 换 inode | PASS |
| 自洽重签 vs fresh expected | PASS |
| fresh 失败且 remote=0 | PASS |
| 显式 client 必需 | PASS |
| experiment/receipt/alias 敌意 | PASS |
| hostile Mapping / 递归异常图脱敏 | PASS |
| 外置 lock ∉ final | PASS |
| temp closure 后、final 前换 marker identity | PASS → `STAGE_RECOVERY_CONFLICT` |
| orphan 自洽重签 + fresh 不同 | PASS → `STAGE_RECOVERY_CONFLICT` |
| 两 stage root 同 target/key | PASS（共享 fake remote 复用同 run；锁按 stage_root，跨 root 无互斥——边界说明） |

## 5. 阻断问题（返工合同）

### F1：FINISHED 复用未校验 request tags（`formal_gate_eligible` / `release_kind`）

- **现象**：远端已有 1 个 `FINISHED` run，5 个 protected identity tags/hash 与当前 request 一致，但 `formal_gate_eligible` 从 `"true"` 漂移为 `"false"`（`release_kind` 仍正确）时，`register_remote_tracking_run` 仍返回同 run id 并视为可复用。
- **根因**：`_validate_remote_run` 仅对 `expected_tags`（5 个 protected keys）做子集相等；create 时写入的 request tags（`formal_gate_eligible`/`release_kind`）不参与复用校验。
- **应遵循规则**：任务单 §6「1 个仅 FINISHED 且全部 tag/hash 一致可复用」；§5 tags exact `formal_gate_eligible="true"` 与 `release_kind="formal"`；独立反例要求覆盖 FINISHED tag 漂移 fail-closed。
- **最小复现**（系统临时目录，fake client，无网络）：
  1. `build_formal_tracking_request(...)` 得到 request（tags 含 `formal_gate_eligible=true`）；
  2. 构造 `RemoteTrackingRunV1(status="FINISHED", tags={**protected_ok, "formal_gate_eligible":"false", "release_kind":"formal"})`；
  3. 调用 `register_remote_tracking_run(..., client=fake)`；
  4. **当前**成功复用；**期望** raise / 映射为 formal `STAGE_BUILD_FAILED`。
- **新增测试**：unit 断言 FINISHED + request-tag 漂移 fail-closed；建议同时覆盖 `release_kind` 漂移与「protected 全对但 request tags 缺失」。
- **通过条件**：上述复用路径拒绝；create 首写的 request tags ∪ protected tags 在复用时全部一致；既有 protected 漂移 / 非 FINISHED / 多匹配回归仍绿；Windows+WSL 定向复跑通过。

## 6. 有效 / 无效命令

**有效**：Windows Ruff/mypy/cold/unit+golden/邻接；WSL capability/cold/Ruff/mypy/组合；独立对抗探针（系统临时目录）。

**无效 / 未执行（按合同禁止）**：联网、真实 MLflow、pip/conda 安装、`git add`/`commit`、正式 artifact 写入、生产代码修改、Linux ext4 Gate。

## 7. 最终裁定

独立初验 **FAIL**。实现者定向绿测与多数对抗通过，但不能解锁主验：FINISHED 复用未落实「全部 tag/hash 一致」，允许 `formal_gate_eligible` 漂移仍复用远端 run。

返工后须再次由未参与该轮实现的外部独立初验复验；主 Agent 不得在本轮自行改码跳过。
