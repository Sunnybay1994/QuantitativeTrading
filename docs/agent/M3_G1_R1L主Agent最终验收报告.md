# M3 G1-R1L 主 Agent 最终验收报告

日期：2026-07-15  
状态：**主 Agent 最终验收通过**

本结论只关闭 G1-R1L 崩溃安全 journal 写锁子包，不宣称 G1、M3 或任何 Gate 通过。

## 1. 外部闭环

- 首次实现会话连接中断，无报告、无证据资格；新外部实现会话接管并逐文件审计；
- 接管修正 `type(Path)` 对 `PosixPath` 恒假的根因，冻结代码后完成 257 项定向；
- R1A 合流 mypy 问题关闭后，独立报告收尾保留首次失败历史并进入初验；
- 全新外部独立初验通过四项未公开对抗：三进程竞争与 SIGKILL recovery、lock entry
  unlink/recreate 不误释新 inode、`O_CLOEXEC`、两 executor 从 intent/raw/candidate hard-crash 恢复。

独立证据见 [`M3_G1_R1L崩溃安全Journal写锁独立初验报告.md`](M3_G1_R1L崩溃安全Journal写锁独立初验报告.md)。

## 2. 主 Agent 终验

主 Agent 复核持久 `.writer.lock` + Linux advisory `flock`、不 unlink、主异常优先、release failure 可见及
两 executor 稳定错误映射；没有 PID/mtime lease、sleep 或旧 `O_EXCL` marker 语义。

在 WSL Miniforge `base`、同一持久协调锁下实跑：

| 验证 | 结果 |
|---|---|
| `test_m3_g1_planning.py` + `test_m3_journal_lock.py` | **37 passed**（11.44s） |
| Ruff：R1A/R1L 关键生产与测试文件 | **PASS** |
| mypy：R1A/R1L 四个关键生产文件 | **PASS** |
| 持久协调锁 | **STILL_PRESENT**，未 unlink |

外部独立初验另实跑四项 ADV、R1L 定向 **257 passed**、Ruff、mypy 81 files；合流最新全量证据为
**837 passed**。主验不重复约 50 分钟全量 pytest。

## 3. 结论与遗留

- R1L crash-safe writer exclusion、释放优先级、fd 边界和两 executor recovery 合同通过主验。
- R1L 可作为 R1B 的已满足前置。
- 本结论不证明真实长周期 G1 数据回补或正式发布；R1B/R1C 和正式 PUBLISH 仍未完成。

