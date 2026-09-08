# M3 G1-R1A 主 Agent 最终验收报告

日期：2026-07-15  
状态：**主 Agent 最终验收通过**

本结论只关闭 G1-R1A 运行身份与分阶段计划骨架子包，不宣称 G1、M3 或任何 Gate 通过。

## 1. 外部闭环

- 原实现完成 runtime identity、static plan 和 derived history plan；
- 首次合流 mypy 因异构循环变量复用失败，外部返工后关闭；
- 外部独立初验发现返回前 source identity TOCTOU：第一次 hash 后同 inode 改写仍返回陈旧 digest；
- 外部实现返工增加返回前完整 source tuple bytes 重收集及 pyproject bytes 重 hash；
- 未参与返工的全新外部复验通过原 ADV1，并通过 rename、等数量删增、恢复 mtime、第二次扫描窗口改写等
  9 项对抗。

失败历史保留在 [`M3_G1_R1A运行身份与分阶段计划骨架独立初验报告.md`](M3_G1_R1A运行身份与分阶段计划骨架独立初验报告.md)，
关闭证据见 [`M3_G1_R1A返回前源码身份TOCTOU独立复验报告.md`](M3_G1_R1A返回前源码身份TOCTOU独立复验报告.md)。

## 2. 主 Agent 终验

主 Agent 核对 `compute_g1_runtime_identity` 成功路径：候选 identity 构造后重新执行完整
`_collect_source_digests` 和 `_hash_regular_file(pyproject.toml)`，比较完整 digest，再执行祖先/root identity
复核；没有用 mtime-only、sleep、重试或缓存替代 bytes 闭包。

在 WSL Miniforge `base`、持久 `/tmp/quant-m3-r1-validation.lock` 下实跑：

| 验证 | 结果 |
|---|---|
| `test_m3_g1_planning.py` + `test_m3_journal_lock.py` | **37 passed**（11.44s） |
| Ruff：R1A/R1L 关键生产与测试文件 | **PASS** |
| mypy：R1A/R1L 四个关键生产文件 | **PASS** |
| 持久协调锁 | **STILL_PRESENT**，未 unlink |

返工实现另在同一持久锁下刷新全量 **837 passed**、Ruff 和 mypy 81 files；外部独立复验实跑定向
**240 passed**、Ruff、mypy 81 files。主验为节省无价值重复耗时，没有再次执行约 50 分钟的全量 pytest。

## 3. 结论与遗留

- R1A 冻结接口、身份闭包、历史成员 union、错误码和脱敏合同通过主验。
- R1A 可作为 R1B 的已满足前置。
- Pandera/Polars 仍产生大量弃用警告；本次短门禁为 326 条。它不影响业务正确性，作为 P2 性能/维护债记录，
  不阻塞 R1B。
- R1B、R1C、正式 `RENAME_NOREPLACE` PUBLISH、B4/G1 Gate 均未完成。

