# UA-ENV-001：WSL 只读环境预检报告

日期：2026-08-12
性质：只读预检；未迁移、未转换、未新建发行版、未安装依赖

## 1. 结论

当前主机具备继续制定 WSL2 方案的基础条件，但现有 `Ubuntu` 仍是 **WSL1**，项目与 Linux home/root
均不在 ext4 上，因此不能关闭 Linux `RENAME_NOREPLACE`、正式不可变发布或 M3/M4 平台 Gate。

用户本轮只批准环境预检并明确“Linux 环境暂不实现”。本报告不构成迁移授权，也不执行任何环境变更。

## 2. Windows 侧只读证据

- `wsl.exe --status`：Default Distribution=`Ubuntu`，Default Version=`2`。
- `wsl.exe -l -v`：`Ubuntu` 状态为 Stopped，VERSION=`1`。
- `Win32_ComputerSystem.HypervisorPresent=True`。
- 物理内存约 68.6 GB。
- 盘符均为 NTFS；与后续方案最相关的可用空间：
  - `C:` 约 107.5 GB；
  - `D:` 约 110.1 GB；
  - `F:` 约 1.99 TB；
  - `G:` 约 1.46 TB。

这些事实只说明主机已启用 hypervisor 且 WSL 默认版本为 2；不能推出当前 Ubuntu 已迁移或 ext4 已可用。

## 3. 现有 Ubuntu 只读证据

- 内核：`4.4.0-22621-Microsoft`，符合现有 WSL1 运行形态。
- `/`：`wslfs`；`/home/mabw`：`wslfs`。
- `/mnt/f/AI_Coding/QuantitativeTrading`：挂载自 `F:\`，类型 `drvfs`。
- root/home 可用空间约 101 GB，使用率约 90%；`/mnt/f` 可用约 1.9 TB。
- WSL 可见内存约 67.0 GB、swap 约 124.9 GB。

因此，即便把项目复制到当前 Ubuntu 的 `/home`，仍只会落在 WSL1 `wslfs`，不能提供所需 ext4 语义。

## 4. 后续方案边界（未获执行授权）

若用户未来恢复 Linux 环境建设，需另行批准后再选择：

1. 转换现有 Ubuntu 到 WSL2；或
2. 新建专用 WSL2 发行版，并在其 ext4 VHDX 内建立验证副本与隔离测试根。

正式方案还应先解决：root/home 当前高使用率、VHDX 位置与备份、现有 Task Scheduler/路径迁移、
Windows 与 Linux 工作树合流方式、`RENAME_NOREPLACE`/dir-fd/O_NOFOLLOW 实机探针及回滚步骤。

本轮停止于只读结论，不调用 `wsl --set-version`、`wsl --import`、`wsl --install` 或任何等价命令。
