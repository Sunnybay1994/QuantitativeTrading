# M3 G8D-F1 R2：FINISHED 远端 Run 全标签复用闭包独立复验报告

日期：2026-08-10

角色：全新外部独立复验 Agent（未参与 R1/R2 实现）

模型：`cursor-grok-4.5-high`（实际）

工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`

结论：**PASS**（仅解锁主验；不得自行宣布 Gate / 正式 tracking / ext4 / 真实 MLflow 通过）

只声明工程合同 R2 复验通过。生产代码、实现者测试、任务单与历史报告全程只读；本会话唯一写入为本报告。

## 1. 范围与只读纪律

- 完整阅读根 `AGENTS.md`、`.ai`（README / review_checklist / multi_agent_delivery 等）、任务单 §13、R1 交付/独立初验、R2 交付报告，以及白名单 `tracking.py` / unit。
- 禁止联网 / 真实 MLflow / 安装依赖 / `git add|commit` / 正式 artifact / 修改任何非本报告文件。
- 临时对抗探针仅落系统临时目录，执行后已清理：`%TEMP%\g8d_f1_r2_indep_2e52ea5c\`。

HEAD：`eace7ebbd61a622a66f9b1cdb6402f42922aae73`

| 文件 | SHA256 | 相对 R1 | 相对 R2 交付 |
|---|---|---|---|
| `tracking.py` | `b7b63fafd90baeb2d689e499ea86ff9e212c374bef4d76994336131b44e5ad91` | 已改 | 一致 |
| unit | `849d9151fdc56371ca58af5767ea209fdf29716f7cef3b48b88435ef605f5846` | 已改 | 一致 |
| `tracking_stage.py` | `cf4ae7a8fea7b9c0ffefb8e0ec0732d9394448d95f95804512a3be7236160063` | 不变 | 一致 |
| `__init__.py` | `866b5a1f7abe4d90d37f6106cf6756a16ed0d38b173118f5e6e8a54bb5c86e11` | 不变 | 一致 |
| golden | `f83e82d747a69c187c5b3521fc657b9ff19323c9b9b69e964ba25b4e610af903` | 不变 | 一致 |

`git diff --check`（`tracking.py` + unit）通过。R2 白名单改动面与任务单 §13 一致：仅 `tracking.py` + G8D-F1 unit；`tracking_stage.py` / golden / `__init__.py` SHA 与 R1 初验一致。

关键修复点（只读核对）：`_register_remote_locked` 复用路径调用

`_validate_remote_run(run, {**dict(request.tags), **expected_tags})`

即 create 首写的 request tags ∪ 5 个 protected tags 全部参与子集逐键比较；额外普通远端标签不纳入 exact-set。

## 2. §13 合同逐项映射

| §13 要求 | 独立证据（实现者未用值优先） | 结论 |
|---|---|---|
| `formal_gate_eligible` 单独漂移拒绝 | 独立探针：`"TRUE"` / `"1"` / `" true"`（实现者用 `"false"`）；`create_calls==0` | 满足 |
| `release_kind` 单独漂移拒绝 | 独立探针：`"Formal"` / `""`（实现者用 `"development_example"`）；`create=0` | 满足 |
| 任一 request tag 缺失拒绝 | 分别缺失 + 两者皆缺；`create=0` | 满足 |
| 5 protected 全对但 request tags 漂移必须拒绝且 create=0 | `"yes"`+`"prod"` 双漂移；以及上述单键漂移 | 满足 |
| 全部 7 键一致且额外普通标签复用同 run id | `audit_channel`/`note` 额外标签 → `reuse-r2-indep`；`create=0` | 满足 |
| protected 漂移仍 fail-closed | `quant_work_key` 漂移（实现者用 `quant_request_sha256`） | 满足 |
| status 非 FINISHED 不退化 | `RUNNING`/`FAILED`/`KILLED` 均拒且 `create=0` | 满足 |
| 多匹配语义不退化 | 两 FINISHED 同 7 键 → `multiple remote tracking runs`；`create=0` | 满足 |
| hostile Mapping 稳定 | 独立 `Mapping` ABC，`.get` 抛含 SECRET/URI/PID；register 抛出且 `create=0` | 满足 |
| 递归异常脱敏 | stage `find_runs` 抛 `__cause__` 链；公开 `STAGE_BUILD_FAILED`，`cause/context` 空，无 TOKEN/URI/路径泄漏 | 满足 |
| stage 映射 remote 冲突 | request-tag 漂移 → `STAGE_BUILD_FAILED`，无 detail 泄漏，`create=0` | 满足 |
| 只改 tracking.py/unit；stage/golden/init SHA=R1 | 上表 | 满足 |
| Windows+WSL §11 定向/邻接 | 见 §3 | 满足 |
| Ruff/mypy/cold/diff | 见 §3 | 满足 |

## 3. 实现者测试动态复跑

### Windows Miniforge（`D:\Miniforge3\python.exe`，`PYTHONPATH=<worktree>/src`）

| 命令 | 结果 |
|---|---|
| Ruff 白名单 | All checks passed |
| mypy `tracking.py`/`tracking_stage.py` | Success |
| cold + capability | `WINDOWS_COLD_IMPORT_PASS True`；`WINDOWS_RENAMEAT2_NOREPLACE True` |
| G8D unit | **9 passed** in 182.92s（`.tmp-g8d-f1-r2-indep-unit-win.txt`） |
| G8D golden | **2 passed** in 190.28s；actual 未 skip（`.tmp-g8d-f1-r2-indep-golden-win.txt`） |
| journal + G8R1 unit/golden | **14 passed** in 1064.36s（`.tmp-g8d-f1-r2-indep-adj-win.txt`） |

### WSL Miniforge base / DrvFS（`/mnt/f/.../m3-g4-formal`）

| 命令 | 结果 |
|---|---|
| cold + capability | `WSL_COLD_IMPORT_PASS True`；`WSL_RENAMEAT2_NOREPLACE False`（**非 ext4**；仅窄 skip） |
| Ruff / mypy | 通过 |
| 组合一次：G8D unit+golden + journal + G8R1 unit | **23 passed, 1 skipped** in 341.63s（`.tmp-g8d-f1-r2-indep-combo-wsl.txt`） |
| 唯一 skip | `test_actual_publish_resume_noresume_orphan_and_remote_counts`（`platform_supports_renameat2_noreplace()==False`） |

warning 主要为 Pandera/Polars `concat(how='horizontal')` 弃用；另有 pytest cache Permission denied。无业务失败。

## 4. 独立对抗摘要（实现者未用）

系统临时探针（已清理）对 `register_remote_tracking_run` / `run_formal_tracking_stage` 的攻击结果：

`ALL_INDEP_ADVERSARIAL_PASS`

覆盖：eligible/release 非实现者错误值与空白、缺失组合、7 键+额外普通标签复用、protected 他键漂移、三态非 FINISHED、多匹配、hostile Mapping、stage BUILD 脱敏、递归异常图脱敏；全部冲突路径 `create_calls==0`。

## 5. 有效 / 无效命令

**有效**：Windows Ruff/mypy/cold/unit/golden/邻接；WSL cold/capability/Ruff/mypy/组合；独立对抗探针（系统临时目录）；SHA / `git diff --check`。

**无效 / 未执行（合同禁止）**：联网、真实 MLflow、pip/conda 安装、`git add`/`commit`、正式 artifact、生产/测试修改、Linux ext4 Gate。

**探针调试误判（非产品缺陷）**：首次将 `stage_root` 放在 artifact roots 外导致 `StageRunner`→`STAGE_INPUT_INVALID`；属探针构造错误，修正为 `default_stage_root` 同树后 stage 路径复验 PASS。

## 6. 残余边界

- 本 PASS 只解锁主验；不宣称真实 tracking / G8 / M3 / ext4 / 真实 MLflow Gate。
- WSL1/DrvFS 能力位 false 的 actual publish 窄 skip 仅为兼容证据，**不是** Linux ext4 Gate。
- 工作树另有无关既有改动，未纳入本包复验范围。
- 未运行全量 pytest / 真实网络。

## 7. 最终裁定

独立复验 **PASS**。R1 阻断项（FINISHED 复用未校验 request tags）已由 R2 最小修复闭合；实现者未用错误值/缺失/hostile Mapping/额外普通标签/status/多匹配/递归脱敏均通过；只读文件 SHA 与 R1 一致；双平台定向与邻接按 §11 通过。

可进入主 Agent 最终验收。主验发现问题须再回「外部实现 → 外部独立复验」循环，不得由主 Agent 直接改码跳过。
