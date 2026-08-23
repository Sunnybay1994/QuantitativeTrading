# M3 G1-R1A 合流 mypy 单点返工交付报告

日期：2026-07-15  
状态：**待独立初验**  
角色：外部实现 Agent（R1A 返工；不做初验）  
模型：`cursor-grok-4.5-high`（非 fast）

本报告只覆盖合流 mypy 单点返工。**不宣称** R1A / G1 / M3 / 任何 Gate 通过。

## 1. 现象—根因—规则—复现—改动

| 项 | 内容 |
|---|---|
| 现象 | 首次合流 `mypy src` 失败于 `g1_planning.py:199`：`G1DependencyVersionV1` 与先前 `G1SourceDigestV1` 赋值不兼容 |
| 根因 | `G1RuntimeIdentityV1.__post_init__` 同一局部作用域复用循环变量 `item` 遍历两类无继承关系的 dataclass |
| 应遵循规则 | 异构领域对象使用含义明确、类型单一的局部变量；禁止 `Any`/`cast`/`type: ignore`/放宽字段/删校验/改 mypy 配置 |
| 最小复现 | WSL Miniforge `base`：`python -m mypy src/quant/research/m3/g1_planning.py`（修复前失败，修复后通过） |
| 实际最小改动 | 两循环分别改为 `source_digest` / `dependency`；保留 exact-type、嵌套重建、排序、唯一性与失败码 |

## 2. 白名单写入

| 文件 | 说明 |
|---|---|
| `src/quant/research/m3/g1_planning.py` | 仅改 `__post_init__` 两处循环变量名 |
| `tests/unit/test_m3_g1_planning.py` | **未改**：既有 `test_runtime_identity_stable_and_source_changes` 与 `test_runtime_dataclass_rejects_list_bool_order_forged_digest` 已同时构造并校验非空 `source_files` 与 `dependencies` |
| `docs/M3_G1_R1A运行身份与分阶段计划骨架交付报告.md` | 同步返工与合流证据 |
| 本报告 | 返工交付 |

未修改 R1L 任何文件。未写独立初验报告。

## 3. 定向验证

环境：WSL Miniforge `base`；无网络、无 token、无 raw/clean/release 写入。

| 命令 | 结果 |
|---|---|
| `mypy src/quant/research/m3/g1_planning.py` | **Success: no issues found in 1 source file** |
| `pytest -q tests/unit/test_m3_g1_planning.py` | **13 passed** |
| `ruff check`（上述两文件） | **All checks passed!** |

## 4. 持久锁下唯一一次合流重验

锁文件 `/tmp/quant-m3-r1-validation.lock`：**未 unlink**；重验前 `LOCK_PRESENT`，结束后 `LOCK_STILL_PRESENT`。

| 命令 | 结果 |
|---|---|
| `pytest -q` | **832 passed**（3112.23s） |
| `ruff check src tests` | **All checks passed!** |
| `mypy src` | **Success: no issues found in 81 source files** |
| 进程退出 | **exit_code 0** |

## 5. 禁止项自检

- 未改公共接口、digest、规范 JSON、错误码或 R1A 冻结语义。
- 未修改 R1L；未读取 token；未联网；未写 raw/clean/release。
- 未宣称 Gate / R1A / G1 / M3 通过；状态仅为**待独立初验**。
