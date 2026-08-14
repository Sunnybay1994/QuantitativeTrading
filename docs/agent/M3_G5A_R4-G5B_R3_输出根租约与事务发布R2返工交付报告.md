# M3 G5A R4 / G5B R3：输出根租约与事务发布 R2 返工交付报告

日期：2026-08-09  
角色：R2 最小返工实现 Agent  
结论：测试清理缺陷已修复，双平台自测通过；等待全新 Agent 独立复验

## 1. 失败闭环

- 现象：独立复验确认 publication 产品行为通过，但 WSL 的
  `test_r4_publication_rejects_link_root_without_creating_lease` 在产品断言成功后，对 POSIX
  directory symlink 调用 `Path.rmdir()`，触发 `NotADirectoryError`，四文件组终态为
  `1 failed, 62 passed`。
- 根因：创建阶段区分了 Windows junction 与 POSIX symlink，清理阶段却错误共用目录删除语义。
- 应遵循规则：Windows junction 使用 `rmdir()`；POSIX symlink 删除 link entry 必须使用
  `unlink()`。产品拒绝断言必须先完成，cleanup 置于其后，避免 cleanup 异常覆盖产品失败。

## 2. 最小修改

仅修改 `tests/unit/test_m3_formal_model_artifact.py`：

1. 保持 `ArtifactPublication(link)` 必须在 lease/output 创建前拒绝的产品断言不变；
2. 产品断言和 real target 空目录断言完成后，再按 `os.name` 分支清理；
3. Windows junction 使用 `link.rmdir()`；POSIX symlink 使用 `link.unlink()`；
4. cleanup 后使用 `os.path.lexists(link)` 证明 link entry 已删除，并再次证明 real target 仍是
   实体目录且为空。

本轮生产代码零修改；未改变 link/reparse/root lease、异常或 artifact 合同。

## 3. 验证结果

Windows 原生 Miniforge，`D:\Miniforge3\python.exe`，`PYTHONPATH=src`：

```text
隔离 junction 用例：1 passed
G5A/G5B formal+development 四文件组：63 passed, 78299 warnings in 816.47s
Ruff：All checks passed!
mypy --no-incremental：Success: no issues found in 5 source files
```

WSL Miniforge `base`，同一 `/mnt/f` DrvFS worktree，`PYTHONPATH=src`：

```text
隔离 POSIX symlink 用例：1 passed
G5A/G5B formal+development 四文件组：63 passed, 78299 warnings in 497.59s
Ruff：All checks passed!
mypy --no-incremental：Success: no issues found in 5 source files
```

曾并行运行两平台 mypy 时，WSL mypy 2.2.0 因共享增量缓存报告一次内部错误；确认并行进程结束后，
两平台分别以 `--no-incremental` 串行复跑并均通过。该工具缓存冲突不是代码或测试失败。

warnings 为既有 Pandera/Polars 弃用警告及 worktree `.pytest_cache` 权限警告。WSL 结果仍是
base + DrvFS 工程兼容证据，不是 ext4 Gate。

## 4. 边界

- 本报告是返工实现者自测，不能替代全新 Agent 独立复验或主 Agent 最终验收。
- 未访问网络、`data/legacy`、正式 G1 artifact/journal 或正式候选目录，未执行正式 full work。
- R2 通过独立复验后也只恢复 G5A/G5B publication 工程前置，不关闭 G6-G9、M3 或 Linux/ext4 Gate。
