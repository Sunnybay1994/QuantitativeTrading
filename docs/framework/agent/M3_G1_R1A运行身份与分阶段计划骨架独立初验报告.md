# M3 G1-R1A 运行身份与分阶段计划骨架独立初验报告

日期：2026-07-15  
状态：**不通过，返回外部实现返工**  
角色：外部独立初验 Agent（接管；未参与 R1A 实现 / mypy 返工；首次停滞会话无证据资格）  
模型：`cursor-grok-4.5-high`（非 fast）

本结论只针对 R1A 子包独立初验。**不宣称** R1A / G1 / M3 或任何 Gate 通过。

## 0. 边界与方法

| 项 | 内容 |
|---|---|
| 接管单 | [`M3_G1_R1A首次独立初验会话停滞接管任务单.md`](M3_G1_R1A首次独立初验会话停滞接管任务单.md) |
| 任务书 | [`M3_G1_R1A运行身份与分阶段计划骨架外部闭环任务单.md`](M3_G1_R1A运行身份与分阶段计划骨架外部闭环任务单.md) §4–§10 |
| 实现证据 | [`M3_G1_R1A运行身份与分阶段计划骨架交付报告.md`](M3_G1_R1A运行身份与分阶段计划骨架交付报告.md)；[`M3_G1_R1A合流mypy单点返工交付报告.md`](M3_G1_R1A合流mypy单点返工交付报告.md) |
| R1L 合流状态 | [`M3_G1_R1L崩溃安全Journal写锁独立初验报告.md`](M3_G1_R1L崩溃安全Journal写锁独立初验报告.md)（仅确认合流，不代替 R1A） |
| 只读 | 全部生产代码、实现者测试、配置、数据、交付报告 |
| 唯一写入 | 本独立初验报告 |
| 环境 | WSL Miniforge `base`；禁止 Windows Python |
| 协调锁 | `/tmp/quant-m3-r1-validation.lock` 持久 flock 串行；**未 unlink**（`LOCK_BEFORE=PRESENT` → `LOCK_AFTER=STILL_PRESENT`） |
| 首次停滞会话 | 无报告；过程/自测不具备证据资格；本会话从冻结任务书与已交付文件重新独立验证 |

临时对抗脚本仅置于 `/tmp/quant-m3-r1a-adv/`，验证后已删除；未进入 `src/` / `tests/`。

## 1. 结论总览

| 阶段 | 结果 |
|---|---|
| 交付结构 / 屏障 / 合流证据核对 | PASS（只读） |
| 冻结合同逐项映射（§4–§7） | **有缺口：§5.1 返回前源码身份窗口** |
| 五项未公开对抗（§9） | **4/5 PASS；ADV1 FAIL** |
| 持久 flock 重检查：定向 235 + Ruff 三文件 + mypy 81 | PASS（exit 0；锁仍在） |
| **初验结论** | **不通过；返回外部实现返工** |

## 2. 交付与合流证据核对（只读）

| 核对项 | 结果 |
|---|---|
| `PARALLEL_BARRIER_READY: R1A` | 是 |
| mypy 单点返工：`source_digest` / `dependency` 分名 | 源码与返工报告一致 |
| 合流重验报告：832 / Ruff / mypy 81 / 锁未 unlink | 报告可追溯；**本初验未重复全量 832**（按接管单） |
| 白名单生产+测试只读；本初验未改 `src/`/`tests/` | 是 |

## 3. 冻结合同逐项映射

| 契约面 | 证据 | 结论 |
|---|---|---|
| 公共 dataclass / 三入口 / 八稳定码 / `str==code` | `g1_planning.py`；实现者脱敏测试；ADV2/3/5 | PASS |
| 受控根无 symlink；只读 pyproject + `src/quant/**/*.py`；规范 source-tree JSON | `_open_project_root` / `_collect_source_digests`；实现者 symlink/escape 测试 | PASS（单文件读窗口） |
| **hash 完成后、返回前源码同大小同 inode 改写须 fail-closed** | ADV1；`compute_g1_runtime_identity` 仅 `_assert_root_unchanged`，不重校验 source digests | **FAIL** |
| 七依赖 `importlib.metadata.version`；fingerprint JSON；拒控制字符/别名 | `_read_dependencies`；ADV5 | PASS |
| 重建 LoadedM3Config 九 identity；内部 runtime；七 endpoint；固定版本闭包 | `_rebuild_loaded_config` / `build_g1_static_plan`；ADV2；实现者 forged identity 测试 | PASS |
| derive：重算 static 精确相等；response multiset；PIT API；SH/SZ 日历；observation 历史并集 | `derive_g1_history_plan`；ADV3/4；实现者 union/calendar 测试 | PASS |
| 零网络零写入 | 实现者 monkeypatch 测试 | PASS |
| 包导出 | `__init__.py`；实现者 export 测试 | PASS |

## 4. 未公开对抗（§9）

| ID | 场景 | 结果 |
|---|---|---|
| ADV1 | source 在 `_collect_source_digests` 完成后、返回前被同大小同 inode 改写（patch `_read_dependencies` 窗口） | **FAIL**：静默返回陈旧 `source_files` digest（旧 `AAAA` hash，现场已是 `ZZZZ`） |
| ADV2 | 九 identity 填同一自洽 hex，但不等于 C0 对 document 重算值 | PASS → `G1_PLANNING_CONFIG_INVALID` |
| ADV3 | 整集替换为另一 signal 窗口下 request/receipt/frame 自洽 responses | PASS → `G1_PLANNING_IDENTITY_MISMATCH` |
| ADV4 | Jan 含早期成员 `000001.SZ`/`000777.SZ`，Feb 结束日截面已调出；history union 保留 | PASS（union_len=302） |
| ADV5 | 依赖 `Numpy` 大小写别名、`NUL`、ZWSP（`numpy\u200b`）碰撞 | PASS → `G1_PLANNING_DEPENDENCY_INVALID` |

## 5. 返工项（六项格式）

### R1A-ADV1：返回前同大小同 inode 源码改写未 fail-closed

| 项 | 内容 |
|---|---|
| 现象 | `compute_g1_runtime_identity` 在源码 digest 集合已算完后，于依赖读取窗口对某 `.py` 做同大小、同 inode 内容改写；函数仍成功返回，且 `source_files` 中该路径 sha256 等于改写前 bytes，不等于返回时磁盘内容。 |
| 根因 | 单文件 TOCTOU 只覆盖 `_digest_source_file` 读窗口；返回前仅 `_assert_root_unchanged`（根/祖先 identity），不重校验已收集 source digests 与现场 bytes/mtime/inode。 |
| 应遵循规则 | 任务书 §5.1 / §9-ADV1：运行身份须反映受控源码在身份生成过程中的真实内容；hash 完成后、返回前的同大小 inode 级替换必须 fail-closed（`G1_PLANNING_SOURCE_TREE_INVALID` 或等价身份码），不得交付陈旧 digest。 |
| 最小复现 | 最小临时项目写入 `a.py=b"AAAA"`；patch `quant.research.m3.g1_planning._read_dependencies`，在调用真实实现前同 inode 覆写为 `b"ZZZZ"`；调用 `compute_g1_runtime_identity`；观察成功返回且 digest 仍为 `sha256(b"AAAA")`。 |
| 新增测试 | 实现者测试须覆盖：hash 完成后、返回前同大小同 inode 改写 → 抛稳定码且不返回陈旧 identity；可选覆盖同大小新 inode 替换。 |
| 通过条件 | 上述对抗改为抛稳定规划错误；无陈旧 `source_tree_sha256`/`code_version` 成功返回；定向 pytest/Ruff/mypy 在持久锁下 exit 0；再经独立初验复验 ADV1。 |

## 6. 持久 flock 重检查（本会话实跑）

| 命令 | 结果 |
|---|---|
| `pytest -q`（g1_planning + config + backfill_requests + index_membership） | **235 passed**（18.12s） |
| `ruff check`（planning + `__init__` + 实现者测试） | **All checks passed!** |
| `mypy src` | **Success: no issues found in 81 source files** |
| `/tmp/quant-m3-r1-validation.lock` | **STILL_PRESENT**（未 unlink） |
| 进程退出 | **EXIT=0** |

### 证据区分

| 类别 | 内容 |
|---|---|
| 本会话实跑 | 五项 ADV；上表定向 pytest / Ruff / mypy；锁存在性 |
| 复用外部实现合流证据（未本会话重跑） | 全量 `832 passed`；全量 Ruff `src tests`；合流 mypy 81 |

## 7. 下一步

- **不通过**；交回外部实现 Agent 按 §5 六项返工（最小改 `g1_planning.py` + 实现者测试）。
- 返工交付后须由**未参与该轮实现**的全新外部独立初验复验（至少 ADV1 + 合同映射 + 锁下定向/静态）。
- **不得**据此进入主验、勾选路线图或宣称 G1/M3/Gate 通过。
