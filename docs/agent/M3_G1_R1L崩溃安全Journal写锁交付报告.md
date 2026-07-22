# M3 G1-R1L 崩溃安全 Journal 写锁交付报告

日期：2026-07-15  
状态：**待独立初验**  
角色：外部实现接管 Agent（仅 R1L，不做初验）  
模型：`cursor-grok-4.5-high`（非 fast）

PARALLEL_BARRIER_READY: R1L

本包仅交付 R1L 崩溃安全 journal 写锁，**不宣称** R1L / G1 / Gate 最终通过。

## 0. 接管披露（不可采信声明）

首个 R1L 实现会话在生成交付报告前因 Cursor 连接中断被主 Agent 终止：无交付报告、无可采信测试结论、未到达屏障标记。白名单内既有文件视为**未验真的部分实现**；本会话逐文件审计并最小修正。

## 1. 白名单写入（本接管会话）

| 文件 | 说明 |
|---|---|
| `src/quant/data/_journal_lock.py` | 修正 `isinstance(Path)`；flock 持久 inode；释放错误优先级 |
| `src/quant/data/m3_backfill.py` | 审计确认：整阶段持锁 + 稳定码映射（无额外改动） |
| `src/quant/data/m3_reference.py` | 同上 |
| `tests/unit/test_m3_journal_lock.py` | 补齐 §7 反例 |
| `tests/unit/test_m3_backfill_requests.py` | 持久 `.writer.lock` 非业务 mutation 断言 |
| `tests/unit/test_m3_reference.py` | 审计确认（无额外改动） |
| 本报告 | 交付与屏障标记 |

未修改 R1A 文件。未写入独立初验报告。

## 2. 关键修正

- **根因**：`type(journal_root) is Path` 对 `PosixPath` 恒 False → `CONTROLLED_ROOT_INVALID`。
- **修复**：`isinstance(journal_root, Path)`。
- **合同**：持久 lock、不 unlink；仅 flock=active；主异常优先于 unlock/close。

## 3. 定向验证（屏障前；其后代码冻结）

| 命令 | 结果 |
|---|---|
| `pytest -q`（journal_lock + backfill_requests + reference） | **257 passed** |
| `ruff check`（本包六文件） | **PASS** |

## 4. 并行屏障后首次合流验证（历史保留；含 mypy 失败）

只读确认 R1A 报告含 `PARALLEL_BARRIER_READY: R1A`。在**未 unlink** 的 `/tmp/quant-m3-r1-validation.lock` 下串行执行：

| 命令 | 结果 |
|---|---|
| `pytest -q` | **832 passed**（3063.73s） |
| `ruff check src tests` | **PASS** |
| `mypy src` | **FAIL**：`src/quant/research/m3/g1_planning.py:199` assignment 类型不兼容（`G1DependencyVersionV1` vs `G1SourceDigestV1`）——**R1A 白名单文件**，本会话禁止修改 |
| 协调 lock 文件 | **仍存在**（`LOCK_STILL_PRESENT`） |
| R1L 三生产文件单独 mypy | **Success: no issues found in 3 source files** |

凭据/绝对路径扫描：helper 与本报告无 token/绝对路径泄露。

**当时结论（已保留，不得覆盖）**：R1L 生产代码与实现者测试已冻结、定向全绿；全量三项未全部通过（对端 R1A mypy），故当时状态为「待合流」，**不**宣称 R1L/G1/Gate 通过。

## 5. R1A 返工后的合流重验（证据合流）

R1A 外部返工 Agent 已完成 `g1_planning.py` 异构循环变量最小隔离，并在同一持久 flock 下刷新唯一一次合流验证。专项证据见：

- [`M3_G1_R1A合流mypy单点返工任务单.md`](M3_G1_R1A合流mypy单点返工任务单.md)
- [`M3_G1_R1A合流mypy单点返工交付报告.md`](M3_G1_R1A合流mypy单点返工交付报告.md)
- [`M3_G1_R1A运行身份与分阶段计划骨架交付报告.md`](M3_G1_R1A运行身份与分阶段计划骨架交付报告.md) §4

只读核对结果：

| 项 | 证据 |
|---|---|
| 最小改动 | 两循环变量改为 `source_digest` / `dependency`；未改公共接口/digest/错误码 |
| R1A 定向 | mypy 1 文件通过；`test_m3_g1_planning.py` **13 passed**；Ruff 通过 |
| 持久锁 | `/tmp/quant-m3-r1-validation.lock` 重验前 `LOCK_PRESENT`，结束后 `LOCK_STILL_PRESENT`（未 unlink） |
| 合流重验 | `pytest -q` **832 passed**（3112.23s）；Ruff `src tests` 通过；mypy **81 source files** 通过；进程 **exit_code 0** |
| R1L 未被动 | R1A 返工白名单与 R1L 白名单互斥；返工报告写明未改 R1L；mtime：R1L 六文件均 ≤17:17，`g1_planning.py` 返工为 18:25 |

本收尾会话**未**重复运行全量 pytest/Ruff/mypy（任务单明确复用刚完成合流证据，避免无价值重复耗时）。合流证据收尾细节见 [`M3_G1_R1L合流证据收尾交付报告.md`](M3_G1_R1L合流证据收尾交付报告.md)。

## 6. 结论

- R1L 生产代码与实现者测试仍按屏障后冻结；首次合流 mypy 失败历史完整保留。
- R1A 返工后合流三项全绿证据可追溯，状态改为**待独立初验**。
- **不**宣称 R1L / G1 / M3 / Gate 通过；独立初验由未参与实现的外部 Agent 执行。
