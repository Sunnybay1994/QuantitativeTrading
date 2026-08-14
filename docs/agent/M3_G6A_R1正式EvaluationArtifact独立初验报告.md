# M3 G6A R1：正式 EvaluationArtifact 独立初验报告

日期：2026-08-09  
角色：未参与实现的独立初验 Agent  
结论：**FAIL；不得进入主 Agent 最终验收，不得据此运行正式全 folds/horizons G6A work 或进入 G6B**

## 1. 范围与边界

本轮完整核对了 `AGENTS.md`、G6A R1 任务单、G5A/G5B 主验、G6A 交付报告、
`contracts.py`、`evaluate.py`、`_artifact_publication.py`、包根导出和 formal evaluation tests。
生产代码与实现者测试保持只读；只写本报告。未联网，未读取或写入正式 G1 artifacts/journal，
未扫描 `data/legacy`，未 add/commit。

本轮证据只覆盖 Windows 原生与 WSL Miniforge base 在 `/mnt/f` DrvFS 上的定向工程合同。
它不是 ext4/Linux Gate、正式全 work、真实数据性能、acceptance threshold 或 M3 Gate 证据。

## 2. 阻断问题

### [P1] POSIX fresh/计算窗口替换 output root 后没有在首个最终文件写入前 fail closed

- **现象**：独立 WSL base/DrvFS 探针在 `verify_prediction_artifact` 中把已由
  `ArtifactPublication` 锚定的空 `output_root` rename 为另一名称，并在原路径创建新的空目录。
  formal builder 最终返回稳定错误 `M3_EVALUATION_ARTIFACT_INVALID`，且原目录和替换目录最终均为空，
  但观测到 `ArtifactPublication.write_bytes` 已被调用 **3 次**。因此它是在写完三个最终文件并于
  commit 阶段发现 root identity 漂移后回滚，而不是任务单第 7.1 节要求的“首个输出独占创建前
  fresh 重验，同一实体不成立则写入 0 bytes”。
- **Windows 对照**：同一探针在 Windows 上因为打开的目录句柄阻止 rename，fresh callback 直接失败，
  `write_bytes` 调用为 0。该平台差异不能覆盖 POSIX 合同缺口。
- **根因**：`evaluate.py:472-490` 在进入 publication 后完成全部 fresh/数学计算，随后
  `evaluate.py:491-493` 直接连续调用三次 `write_bytes`。`_artifact_publication.py:69-86` 的
  `write_stream` 在 `_open_output` 前没有调用 `_require_current_root`；POSIX 的 `_open_output`
  使用锚定 dir-fd，因此会向已被 rename 的原实体写入，直到 `commit`
  (`_artifact_publication.py:108-128`) 才复验当前路径实体并回滚。
- **被破坏的不变量**：caller-created output root 的实体身份必须贯穿 preflight→fresh→数学→首个
  exclusive-create；fresh/计算期间发生替换时，两个目录均必须从未出现本次最终输出 bytes。
  “事后回滚为空”不等价于“首字节前拒绝”。
- **最小复现**：在 WSL/DrvFS 创建空 root；进入 `build_evaluation_artifact` 后，于 fresh prediction
  verifier callback 中执行 `root.rename(old_root); root.mkdir()`；包装
  `ArtifactPublication.write_bytes` 计数。实际结果：`FRESH_CALLS=1`、`WRITE_CALLS=3`、稳定错误且
  两目录最终为空。
- **应新增测试**：在 POSIX/WSL 测试中覆盖至少两个替换点：fresh verifier 返回前、数学 helper 返回前；
  除稳定错误与最终双空目录外，必须断言 `_open_output`/`write_bytes` 调用为 0。Windows 保留 rename
  被目录句柄拒绝的对照。另覆盖首个 write 前的 current-root 复验与 commit 前替换回滚，区分两类语义。
- **最小修复方向**：在 publication 的首个输出 exclusive-create 前复验 current path 仍是锚定实体；
  最稳妥的是让 `write_stream` 在 `_open_output` 前执行 `_require_current_root`，同时保留 commit 的二次
  复验与既有精确 rollback。若该公共 helper 影响 G5A/G5B，必须回归其双平台 publication tests。
- **通过条件**：上述 POSIX fresh/数学窗口探针 `WRITE_CALLS == 0`；原目录与替换目录均为空；异常
  `cause/context is None`；G5A/G5B/G6A publication 定向测试、Ruff、mypy 在 Windows 与 WSL base
  均通过。

## 3. 其余契约映射

| 冻结项 | 独立证据 | 结论 |
|---|---|---|
| builder/verifier 各自 fresh G1→G5B prediction，且独立 fresh label | 两个 formal 入口共同进入 `_fresh_formal_evaluation`；其中调用公开 `verify_prediction_artifact` 与 `verify_label_artifact`，随后 exact 比对 root/frame/manifest/receipt；hostile upstream 被稳定码脱敏 | PASS（不抵消阻断项） |
| 17 个物理 input 无 alias | receipt inputs 包含 G1 manifest+eligible、G4B 4 文件、G5B 3 文件、G3A 4 文件、fold 2 文件、experiment 2 文件；先 normalized path 唯一，再两两 `samefile`；显式 receipt 路径与 nested 链 exact 对齐 | PASS |
| 五层 key、四分母 | eligible/scorable/predicted/labeled/evaluated 分别从 fresh 物理输入重建；`predicted == scorable`、两个 subset 与 inner intersection 明确；daily 和 aggregate 均使用冻结分母 | PASS |
| label 缺失不得筛 prediction | 独立两日数学探针保持 scorable/predicted 各 3；第二日 labels 为 0 时 `n_predicted=3`、`prediction_coverage=1.0`、状态 `NO_LABELS`；额外 prediction key 被拒绝为 `predicted differs from scorable` | PASS |
| 八状态与优先级 | 实现顺序与冻结顺序一致；独立组合反例验证 `NO_LABELS` 优先于 `NO_PREDICTIONS`；实现者测试覆盖八状态、tie、N 边界及 ICIR | PASS |
| daily IC/ICIR | Pearson/Spearman 仅 COMPUTABLE 日计算；Spearman average rank；汇总等权 mean，sample std `ddof=1`，少于两日/零 std 为 null | PASS |
| whole-sale 三文件重签 | 独立探针同时重写合法 schema 的 daily、重算 metrics、重算 manifest hashes，并以目标 work 的合法 17/3 closure 重发 receipt；verifier 仍以 fresh 五层重算拒绝，稳定码且无异常链 | PASS |
| 三文件 publication/receipt | exclusive-create、owned identity、三文件 exact tree、writer/readback/commit 和 rollback 边界存在；writer hostile tests 通过；但 fresh/数学窗口首字节前身份复验缺口导致本轮总 FAIL | **FAIL** |
| formal/development exact 隔离 | formal exact type gate 覆盖所有 capability/spec/path/config；包根分别导出 formal 与 development 类型/入口；formal 不调用 development verifier | PASS |
| 异常脱敏 | 独立 hostile `_read_evaluation_daily` 抛含私有 sentinel 的异常，公开边界仅返回 `M3_EVALUATION_ARTIFACT_INVALID`，`cause/context is None`，sentinel 不外泄 | PASS |
| 轻依赖 | Windows 导入 `quant.research.m3` 与 `evaluate` 后，`sys.modules` 中无 Qlib/LightGBM/MLflow | PASS |

## 4. 验证结果

### Windows 原生 Miniforge

- 任务单四文件 pytest：`49 passed, 39546 warnings in 550.56s`；
- Ruff：`All checks passed!`；
- mypy `evaluate.py --no-incremental`：`Success: no issues found in 1 source file`；
- whole-sale 三文件重签：拒绝，稳定码与空异常链 PASS；
- label/prediction coverage、五层交叉漂移、status priority：PASS；
- hostile reader 脱敏：PASS；
- Windows root replacement 对照：rename 被打开的目录句柄拒绝，`WRITE_CALLS=0`。

### WSL Miniforge base，`/mnt/f` DrvFS

- 对应四文件 pytest：`49 passed, 39546 warnings in 237.47s`；
- Ruff：`All checks passed!`；
- mypy：`Success: no issues found in 1 source file`；
- POSIX root replacement 独立探针：稳定错误、最终双空目录，但
  `FRESH_CALLS=1, WRITE_CALLS=3`，故冻结合同 **FAIL**。

warning 为既有 Pandera/Polars deprecation 与工作树 `.pytest_cache` 无写权限；pytest 使用独立
`--basetemp`，不影响结果。定向 `git diff --check` 对 G6A 白名单无空白错误；未发现重依赖 import。

## 5. 最终判定

G6A 的 fresh 链、数学、exact receipt、wholesale 防伪、formal/dev 隔离和脱敏主体实现均有充分正向证据，
但 output-root 实体身份在 POSIX fresh/计算窗口只于 commit 阶段复验，违反任务单明确的首字节前 fail-closed
条件。这是不可变发布边界的阻断缺陷，因此本轮独立初验判定 **FAIL**。

返工应保持 G6A 数学与 receipt 代码不变，仅修复公共 publication 首写前 current-root 复验并增加上述
POSIX 对抗测试；返工完成后必须由未参与返工的全新独立 Agent 复验。正式 G6A、G6B、ext4/Linux Gate、
真实全 work 与 M3 Gate 仍全部未关闭。
