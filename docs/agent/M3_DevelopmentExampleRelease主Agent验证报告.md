# M3 Development Example Release 主 Agent 验证报告

日期：2026-07-31
结论：**开发契约通过；正式 G1/G2/G8/G9/M3 Gate 均未据此关闭**
冻结边界：[`M3_DevelopmentExampleRelease开发并行轨任务单.md`](M3_DevelopmentExampleRelease开发并行轨任务单.md)

## 1. 验收范围

本轮只验收无网络 development example G1 包、development snapshot 和 G8 snapshot runner 的首次发布、
恢复与重复执行。未访问 Tushare/BaoStock，未扫描 `data/legacy/`，未修改、重启或控制正式 G1 进程，未把
开发结果转换为 `VerifiedG1Release`。

关键反例通过：artifact/hash/tree 漂移、移入未显式标记 development/example 的根目录、正式 snapshot
入口接收开发类型、formal identity key 用于开发 snapshot、正式 runner 接收 development node，均在写入前
或严格验证阶段失败关闭。

## 2. 验证证据

Windows 原生 `D:\Miniforge3\python.exe`：

- 定向 Ruff：通过；
- 本次 5 个生产源码文件 mypy：通过；
- `test_m3_development_example.py`、`test_m3_orchestration.py`、`test_m3_snapshot.py`：42 passed。

WSL Miniforge `base`（`/mnt/f/...` 隔离 worktree）：

- 对应定向 Ruff：通过；
- 对应 5 个生产源码文件 mypy：通过；
- 同一组定向测试：42 passed。

测试存在 Pandera/Polars 的既有 deprecation warnings，不影响本轮结果。G8 状态机测试为跨平台确定性使用
项目既有 test-only directory commit primitive；这不证明 WSL1 支持正式 no-replace publish，也不替代 Linux
发布 Gate。

## 3. 正式 G1 状态快照

2026-07-31 20:59:11 +08:00 只读检查：正式 G1 PID 34848 仍存活并响应，累计 CPU 8453.83 秒，工作集
4,147,515,392 bytes；命令仍为正式 `reference`。本轮没有读取或写入其 journal、candidate 或正式发布目录。

正式 `REFERENCE → PREPARE → Windows PUBLISH → 磁盘验收` 继续独立等待。正式 G2A 主验、真实数据覆盖/
性能、真实训练评估、正式发布与 Gate 关闭仍受它阻塞。
