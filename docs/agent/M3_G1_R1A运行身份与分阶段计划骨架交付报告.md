# M3 G1-R1A 运行身份与分阶段计划骨架交付报告

日期：2026-07-15  
状态：**返工已交，待全新外部独立复验**  
角色：外部实现 Agent（仅 R1A，不做初验）  
模型：`cursor-grok-4.5-high`（非 fast）

PARALLEL_BARRIER_READY: R1A

本包仅交付 R1A 编排骨架合同，**不宣称** R1A/G1/B4/M3 或任何 Gate 最终通过。

## 1. 白名单写入

| 文件 | 说明 |
|---|---|
| `src/quant/research/m3/g1_planning.py` | runtime identity / static plan / derived history plan；含返回前 source 闭包重校验 |
| `src/quant/research/m3/__init__.py` | 仅追加本包公共导出（首次实现；后续返工未改） |
| `tests/unit/test_m3_g1_planning.py` | 实现者测试（含 TOCTOU 六项回归） |
| 本报告 | 交付与屏障/合流证据 |
| `docs/M3_G1_R1A合流mypy单点返工交付报告.md` | mypy 单点返工专项 |
| `docs/M3_G1_R1A返回前源码身份TOCTOU返工交付报告.md` | TOCTOU 返工专项 |

未修改：data 层既有合同、C0、配置示例、路线图、raw/clean/artifacts、依赖、R1L 白名单文件。  
未写入：独立初验报告（初验 Agent 专属）。

## 2. 合同实现摘要

- `compute_g1_runtime_identity`：受控根无 symlink/identity 漂移；只读 `pyproject.toml` + `src/quant/**/*.py`；依赖七元组经 `importlib.metadata.version`；规范 JSON digest。
- `build_g1_static_plan`：重建校验 LoadedM3Config 九 identity；内部调用 runtime；`plan_index_weight_requests`；七 endpoint policy；固定 mapper/schema/execution-fact 版本；`G1BuildSpec`/`G1CrossSourcePolicy` 自证。
- `derive_g1_history_plan`：重算 static 精确相等；index response multiset 闭包；PIT 成员 API；SH/SZ 日历一致；observation 历史并集；`resolve_history_window` + `plan_history_requests`；derived digest。
- `M3G1PlanningError`：`str==code`；无绝对路径/cause 敏感链。

## 3. 定向验证（屏障前；历史）

环境：WSL Miniforge `base`；无网络、无 token、无真实 data 写入。

| 命令/范围 | 结果 |
|---|---|
| `pytest -q tests/unit/test_m3_g1_planning.py` | **13 passed** |
| `pytest -q tests/unit/test_m3_g1_planning.py tests/unit/test_m3_config.py tests/unit/test_index_membership.py` | **113 passed** |
| `ruff check`（本包三文件） | **PASS** |
| 任务书含 `test_m3_backfill_requests.py` 的联合定向 | **不采信为本包失败**：失败指纹为 R1L 并行中途的 `CONTROLLED_ROOT_INVALID`（`hold_journal_writer_lock`），与 R1A 白名单无关 |

## 4. 合流 mypy 单点返工（2026-07-15）

### 4.1 现象—根因—规则—复现—改动

| 项 | 内容 |
|---|---|
| 现象 | R1L 首次合流 `mypy src` 失败于 `g1_planning.py:199`（`item` 先后承载 `G1SourceDigestV1` / `G1DependencyVersionV1`） |
| 根因 | 同一局部作用域复用异构循环变量名 |
| 应遵循规则 | 含义明确、类型单一的局部变量；禁止 `Any`/`cast`/`type: ignore`/放宽字段/删校验/改 mypy 配置 |
| 最小复现 | `mypy src/quant/research/m3/g1_planning.py` |
| 实际最小改动 | `source_digest` / `dependency` 分名；语义不变 |

测试：既有用例已同时构造并验证非空 `source_files` 与 `dependencies` 的 exact-type/重建/排序/唯一性，返工未改测试文件。专项见 [`M3_G1_R1A合流mypy单点返工交付报告.md`](M3_G1_R1A合流mypy单点返工交付报告.md)。

### 4.2 返工后定向验证

| 命令 | 结果 |
|---|---|
| `mypy src/quant/research/m3/g1_planning.py` | **Success: no issues found in 1 source file** |
| `pytest -q tests/unit/test_m3_g1_planning.py` | **13 passed** |
| `ruff check`（planning + 测试） | **All checks passed!** |

### 4.3 持久锁下唯一一次合流重验

锁 `/tmp/quant-m3-r1-validation.lock`：**未删除**；结束后仍存在（`LOCK_STILL_PRESENT`）。

| 命令 | 结果 |
|---|---|
| `pytest -q` | **832 passed**（3112.23s） |
| `ruff check src tests` | **All checks passed!** |
| `mypy src` | **Success: no issues found in 81 source files** |

## 5. 禁止项自检

- 无 Tushare/BaoStock 调用、无 token、无 CLI、无 journal/raw/release 写入。
- 未修改对端 R1L 文件；未宣布 Gate 通过。

## 6. 返回前源码身份 TOCTOU 返工（2026-07-15）

权威任务：[`M3_G1_R1A返回前源码身份TOCTOU返工任务单.md`](M3_G1_R1A返回前源码身份TOCTOU返工任务单.md)。  
专项交付：[`M3_G1_R1A返回前源码身份TOCTOU返工交付报告.md`](M3_G1_R1A返回前源码身份TOCTOU返工交付报告.md)。

| 项 | 内容 |
|---|---|
| 现象 | hash 完成后、`_read_dependencies` 窗口同大小同 inode 改写仍返回陈旧 digest（初验 ADV1） |
| 最小改动 | 返回前重收集完整有序 source digest tuple + 重 hash `pyproject.toml`，字节级比较；失败码 `G1_PLANNING_SOURCE_TREE_INVALID` |
| 新增回归 | 同 inode 改写 / 新 inode 替换 / 增删 `.py` / pyproject 同大小改写 / 成功算法不变 / 异常脱敏 |
| 定向 | `pytest` **18 passed**；ruff/mypy 本包 PASS |
| 合流 | 持久锁下唯一一次：`pytest` **837 passed**；ruff PASS；`mypy src` 81 files PASS；**LOCK_STILL_PRESENT** |
| 状态 | **返工已交，待全新外部独立复验**；不宣称 Gate |

未修改 R1L、独立初验报告、配置、路线图、依赖、数据产物。
