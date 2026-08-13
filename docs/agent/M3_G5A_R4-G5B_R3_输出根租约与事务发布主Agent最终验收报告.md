# M3 G5A R4 / G5B R3：输出根租约与事务发布主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS（G5A/G5B 正式工程合同）**

## 1. 验收范围

本次主验吸收 G5A/G5B 历轮实现、独立失败与返工证据，最终针对联合任务
`M3_G5A_R4-G5B_R3_输出根租约与事务发布返工任务单.md` 验收：caller-created output root 的全窗口实体
锚定、跨进程/同进程租约、formal/development 共用事务发布、精确 no-clobber/rollback、稳定脱敏异常，以及
Windows 与 POSIX 的 link/reparse 和目录原语边界。

R2 只修复独立复验中 POSIX symlink cleanup 错用 `rmdir()` 的测试缺陷；联合生产实现没有为该测试问题扩大
改动。生产文件不存在 R2 前加密哈希基线，因此验收证据如实采用任务白名单、mtime、当前 SHA256、Git 差异
和两平台回归，不声称不存在的 pre/post 哈希对照。

## 2. 主验结论

- `ArtifactPublication` 在进入 fresh/train/predict 长窗口前锚定 caller root：Windows 持有禁止 share-delete 的
  directory handle，POSIX 持有 `O_DIRECTORY|O_NOFOLLOW` dir-fd；
- 同进程 registry 与磁盘 exclusive lease 共同阻止第二 builder；lease 被删除、root/handle/fd 漂移或返回前
  exact-entry 不闭合均 fail closed；
- 所有最终文件通过 anchored root 独占创建、flush/fsync；仅按本调用记录的 inode/file-id 逆序回滚，不删除
  并发或预存文件；rollback 无法精确证明时返回独立稳定错误；
- G5A 先在系统临时文件保存 LightGBM model bytes，再进入三文件事务；G5B 在同一租约窗口内完成完整 fresh
  verify 和 predict。formal/development 均受同一根身份与事务规则约束；
- root 在 fresh/train/temp-save/predict/commit 窗口被 rename/replaced、copied model root、hostile writer/fsync/
  unlink/handle-close、第二 builder 等对抗路径均在计算或发布边界 fail closed；
- R2 跨平台 cleanup 现在在产品拒绝和 real target 断言之后执行：Windows junction 使用 `rmdir()`，POSIX
  symlink 使用 `unlink()`，cleanup 不再遮蔽真实产品错误。

据此，G5A 正式 LightGBM ModelArtifact 与 G5B 正式 PredictionArtifact 的工程合同完成，可解锁 G6A 正式
EvaluationArtifact 实现。

## 3. 验证证据

实现与独立复验：

- Windows 四文件组：`63 passed`；
- WSL base `/mnt/f` 四文件组：`63 passed`；
- 两平台 Ruff PASS，mypy 5 files PASS；
- 独立“假产品接受 link”探针在两平台证明产品断言先失败、cleanup 未运行且未遮蔽；
- `git diff --check` PASS。

主 Agent Windows 精选高风险回归：

- 10 项 publication/model/prediction 对抗：`10 passed`；
- Ruff：5 个生产/测试目标 PASS；
- mypy `--no-incremental`：3 个生产文件 PASS。

warning 为既有 Pandera/Polars deprecation 与 worktree `.pytest_cache` 权限提示，不影响测试结论。

## 4. 边界与剩余事项

- 当前 WSL 路径是 `/mnt/f` DrvFS，不是 ext4；以上 Linux 证据只关闭双平台开发合同，不关闭 M3 Linux/ext4
  Gate；
- 本报告不替代 G6A/G6B evaluation/research-summary、G7 target/backtest、G8 orchestration/tracking 或 G9
  最终质量验收；
- 正式 G1 Windows 发布已完成，但完整 M3 Gate 仍等待 G6–G9、真实数据/性能和最终跨平台 closure。
