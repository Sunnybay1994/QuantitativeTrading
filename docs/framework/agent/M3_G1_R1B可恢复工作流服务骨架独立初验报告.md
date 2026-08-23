# M3 G1-R1B 可恢复工作流服务骨架独立初验报告

日期：2026-07-16  
初验模型：`cursor-grok-4.5-high`（非 fast；未使用 GPT/Terra）  
身份：外部独立初验 Agent（未参与 R1B 实现）  
结论：**不通过**（退回实现；**未关闭**任何 Gate；**未勾选**路线图；不宣称 M3/G1/B4 通过）

环境备注：项目 `.git` 为空目录，记为环境问题；未执行 `git init` / 删建 `.git`。

---

## 1. 初验范围与证据边界

| 项 | 处理 |
|---|---|
| 任务合同 SSOT | `docs/framework/agent/M3_G1_R1B可恢复工作流服务骨架外部闭环任务单.md` |
| 实现者自述 | `docs/framework/agent/M3_G1_R1B可恢复工作流服务骨架交付报告.md`（**不作证据**） |
| 只读核对 | `src/quant/research/m3/g1_workflow.py`、`src/quant/research/m3/__init__.py` 导出、`tests/unit/test_m3_g1_workflow.py` |
| 写入白名单 | **仅本报告** |
| 禁止 | 改生产代码 / 改实现者测试；读 `archive/legacy_pre_greenfield`；遍历 `data/`；通读历史报告 |

对抗验证使用一次性 `/tmp` 脚本，跑完后不保留为仓库测试文件；建议主验/返工把对应用例并入 `tests/unit/test_m3_g1_workflow.py`。

---

## 2. 质量命令复跑摘要（初验自跑为准）

| 命令 | 摘要 |
|---|---|
| `python -m pytest -q tests/unit/test_m3_g1_workflow.py` | **15 passed**，约 57m（3420.68s），大量 pandera DeprecationWarning |
| `python -m pytest -q`（全量） | **1 failed, 851 passed**，约 1h43m（6180.82s）；见 §2.1 |
| `python -m ruff check src tests` | **All checks passed**（exit 0） |
| `python -m mypy src` | **Success: no issues found in 82 source files**（exit 0） |

### 2.1 全量 pytest

- 初验复跑：`1 failed, 851 passed, 1797253 warnings in 6180.82s`
- 失败用例：`tests/unit/test_m3_journal_lock.py::test_child_process_hold_blocks_and_sigkill_recovers`（**非 R1B 白名单文件**；R1L journal lock）
- 定稿前对该单测孤立复跑：**1 passed / 3.36s** → 记为 **偶发 flake**，不作为 R1B 主退回因；主退回因仍为 §5 问题 #1（§9.1 operation 伪报）
- 交付报告曾写全量“进行中”；以上以本初验自跑为准

---

## 3. 任务书 §5–§11 逐条映射

### §5 冻结公共接口

| 要求 | 证据 | 判定 |
|---|---|---|
| `Stage`/`Operation`/`CauseCategory`/`G1WorkflowCountsV1`/`VerifiedG1WorkflowStateV1`/`M3G1WorkflowError` 与六公共函数签名 | `g1_workflow.py` L66–140、L286–554；connector 要求 `type(...) is TushareConnector/BaostockConnector` | 通过 |
| 包导出 | `__init__.py` 导出六函数 + counts/state/error；类型别名可从子模块取（实现者测试覆盖函数导出） | 通过 |
| `str(error)=="<op>:<code>"`，`repr` 无路径/token；边界 `from None` | `M3G1WorkflowError.__str__/__repr__`；实现者 `test_error_message_sanitized`；对抗中路径失败亦见稳定格式 | 通过（脱敏） |
| dataclass exact-type / 冻结 / completed 前缀 | `VerifiedG1WorkflowStateV1.__post_init__` | 通过 |

### §6 权威 source context

| 要求 | 证据 | 判定 |
|---|---|---|
| 固定相对布局，不接受第二套路径 | `_REL_*` + `_open_layout` | 通过 |
| SH/SZ calendar/instrument 验真、指纹前后一致、开闭市一致、warmup/tail | `_load_source_context` / `_validate_calendar_pair` / `_fingerprint_file` | 通过 |
| history 切片进 `G1BuildInputs`；history_symbols 精确切片 | `_make_build_inputs` | 通过 |
| 拒绝 symlink | `_reject_path_symlinks` / `_dir_identity` / journal preflight | 通过 |

### §7 inspect 恢复规则

| 要求 | 证据 | 判定 |
|---|---|---|
| 重算 R1A static；tushare batch missing/partial/complete | `_recover_tushare_batch` / `_verify_tushare_complete` | 通过 |
| INDEX 完整后 derive history；再恢复 history | `_inspect` 分支 | 通过 |
| HISTORY 后 candidate build/verify/audit；audit 非 PASS → quality failed | `_inspect` | 通过 |
| reference 恢复 + reconcile；未发布时丢弃 transient prepared，completed 停 REFERENCE | `_inspect`：无 release 时不 append PREPARE | 通过 |
| 只验唯一 `release_id`；不扫描任选 | `release_dir = layout.release_root / transient.release_id` | 通过（实现者仅放了非法 decoy `0*64`+空 manifest，非“两合法 release”） |
| `completed_stages` 固定前缀 | `__post_init__` + 阶段 append 顺序 | 通过 |

### §8 各执行段停止点

| 段 | 证据 | 判定 |
|---|---|---|
| INDEX：已完成零网复用；执行后 re-inspect；不进 HISTORY | `run_g1_index_stage`；测试 `test_index_stage_then_idempotent_reuse` / five-stage | 通过 |
| HISTORY：需 INDEX；停 HISTORY | `run_g1_history_stage`；five-stage | 通过 |
| REFERENCE：需 HISTORY；30 req；停 REFERENCE，`prepared=None` | `run_g1_reference_stage`；five-stage | 通过 |
| PREPARE：零网；瞬时 completed 含 PREPARE；随后普通 inspect 无 PREPARE | `prepare_g1_workflow`；five-stage mid inspect | 通过 |
| PUBLISH：先 prepare；unsupported 零 staging；支持则 publish + re-inspect | `publish_g1_workflow`；monkeypatch renameat2 | 通过 |
| 生产路径无 `os.replace` | `g1_workflow.py` 无匹配；`test_no_os_replace_in_workflow_module`；`m3_release.py` 亦无 `os.replace` | 通过 |

### §9 重试分类 / 异常归类 / counts

| 要求 | 证据 | 判定 |
|---|---|---|
| `classify_error` allowlist，非法→PERMANENT→执行失败 | `_checked_classify`；`test_classify_illegal_maps_to_execution_failed` | 通过 |
| CauseCategory 映射表 | `_map_planning_error` / `_map_reference_error` / `_map_release_error` 与 raise 点 | 大体通过 |
| **operation 必须反映公开函数当前动作** | 见 **问题 #1** | **不通过** |
| counts = 计划总数非完成数 | `_counts`；fresh inspect index=2、history/ref=0；HISTORY 后 ref=30 | 通过 |

### §10 测试矩阵覆盖（实现者）

| # | 覆盖情况 |
|---|---|
| 1–2 五段停点 + 幂等 | 有（`test_five_stage_*`、idempotent） |
| 3 INDEX interrupt recovery | 有（intent/candidate 故障点） |
| 4 reference 30 | 有（嵌在 five-stage） |
| 5 额外文件/symlink | 有；hardlink / 跨 raw root 指向未见独立用例 |
| 6 calendar 不一致 / 窗外未来日 | 有 |
| 7 早期证券缺失 | 有 |
| 8 不任选 release | **弱**：仅非法 decoy，非两合法且字典序更靠前 |
| 9 unsupported / no-clobber / 禁 os.replace | 有 |
| 10 脱敏 | 有 |
| 11 import 隔离 | 有 |
| 12 全量/ruff/mypy | 初验自跑（见 §2） |

### §11 独立初验对抗（本会话新增）

见 §4。

---

## 4. 新增对抗反例（实现者未使用）

### 4.1 INDEX 完成后整体替换合法但 G1 hash 不同的 config（主反例）

一次性脚本：`/tmp/r1b_adv_config_swap.py`（不入库）。

步骤摘要：

1. 临时项目根 + fake Tushare，跑通 `run_g1_index_stage(config_A)`，`factor_ratio_rtol=0.001`。
2. 换成合法 `config_B`（仅 `factor_ratio_rtol=0.002` → `g1_config_sha256` 不同；日期/指数请求规格不变）。
3. `inspect_g1_workflow(config_B)`。

结果：

- `completed_stages==("INDEX",)`，**request_id 与 A 完全相同**，**零额外网络调用** → raw/journal 按 request identity 复用。
- `g1_config_sha256` / `factor_ratio_rtol` / `derived_plan.static_plan_sha256` / `derived_plan_sha256` **均改变** → static/derived identity 必须变。
- 另换 **signal 日期改变 request specs** 的 config_C：`completed_stages==()`，旧 receipt **不能**冒充新 INDEX。

→ 本条 **对抗通过**（证明实现符合 §11 第一项意图）。

### 4.2 同源 PATH 失败的 operation 归属（触发不通过）

一次性脚本：`/tmp/r1b_adv_op_bug.py`。

在 INDEX 完成后，于 `run_g1_history_stage` 入口 `_inspect(operation=HISTORY)` 过程中，使项目根 exit identity 校验失败。

现象：抛出 `M3G1WorkflowError`，`code=G1_WORKFLOW_PROJECT_ROOT_INVALID`，但 **`operation=INSPECT`**，`str=="INSPECT:G1_WORKFLOW_PROJECT_ROOT_INVALID"`（期望 `HISTORY:...`）。

根因：`_assert_root_unchanged`（及同类 `_assert_calendar_slice`）写死 `operation="INSPECT"`，忽略 `_inspect` 传入的公开动作。

→ 违反任务书 **§9.1**。

---

## 5. 不通过问题清单（标准格式）

### 问题 #1：执行段入口 inspect 的 PATH/日历切片失败伪报 `INSPECT`

- **现象**：`run_g1_history_stage`（及同样经 `_inspect(operation=INDEX|REFERENCE|PREPARE|PUBLISH)` 的路径）在项目根/祖先 exit 校验失败时，公开异常 `operation` 为 `INSPECT` 而非当前公开函数动作；`str(error)` 亦为 `INSPECT:G1_WORKFLOW_PROJECT_ROOT_INVALID`。
- **根因**：`g1_workflow.py` 中 `_assert_root_unchanged` 全路径硬编码 `operation="INSPECT"`；`_assert_calendar_slice` 同样硬编码 `INSPECT`（在 HISTORY 已完整后的切片校验路径上会同类误报）。
- **应遵循规则**：任务书 §9.1 —「同一上游异常若发生在不同 operation，`operation` 必须反映公开函数当前动作；inspect 前置失败使用 `INSPECT`，不得伪报 INDEX」（同理不得把 HISTORY/PREPARE/PUBLISH 入口失败伪报为 INSPECT）。
- **最小复现**：INDEX 完成后调用 `run_g1_history_stage`；在 `_inspect` 末尾使 root `(st_dev,st_ino)` 与入口快照不一致（初验用 patch `_dir_identity` 二次返回异 inode；真实场景为运行中替换项目根祖先/目录 identity）。见 `/tmp/r1b_adv_op_bug.py` 逻辑。
- **新增测试（建议返工写入实现者测试文件）**：
  1. `test_history_entry_root_identity_failure_reports_history_operation`：HISTORY 入口 PATH 失败 → `operation=="HISTORY"` 且 `str` 前缀 `HISTORY:`。
  2. （可选）`test_calendar_slice_failure_preserves_caller_operation`：在能到达 `_assert_calendar_slice` 的调用方上断言 operation 透传。
- **通过条件**：
  1. `_assert_root_unchanged(layout, *, operation: Operation)`（及 `_assert_calendar_slice(..., operation=...)`）使用调用方传入的 `operation`，不再写死 `INSPECT`。
  2. 上述新测通过；定向 `tests/unit/test_m3_g1_workflow.py`、ruff、mypy 仍绿。
  3. 普通 `inspect_g1_workflow` 失败仍报告 `INSPECT`。

### 建议补强（不单独构成今日不通过主因，但 §11/§10 覆盖不足）

- 两份**合法** release、非目标字典序更靠前时 inspect 只验目标（实现者目前仅非法 decoy）。
- REFERENCE 后替换 primary raw + 伪造局部 receipt 的全闭包失败。
- publish rename 前替换项目根祖先的 PATH 边界（与问题 #1 同路径，修好 operation 后应一并测）。

---

## 6. 结论

**不通过**。核心合同面（五段状态机、恢复、counts、脱敏、无 `os.replace`、质量工具）大体到位，且 §11 config-swap 对抗已证明 request identity 复用与 G1 identity 分离；但 **§9.1 operation 归属**在 PATH（及日历切片）失败路径上明确违约，须返工后再次独立初验。

本初验 **未关闭** Gate，**未勾选** `项目实施路线图.md`，**不宣称** M3/G1/B4 通过。
