# M3 G5A R4 / G5B R3：输出根租约与事务发布返工交付报告

日期：2026-08-09  
角色：返工实现 Agent  
结论：实现与自测完成，等待全新 Agent 独立复验和主 Agent 最终验收

## 1. 完成内容

- 新增私有轻依赖 `quant.research.m3._artifact_publication`。调用在长时 fresh/train/predict 前取得
  独占 root lease；marker 不进入 manifest、receipt 或 artifact identity，也不从包根导出。
- POSIX 以 `O_DIRECTORY | O_NOFOLLOW` 打开 dir-fd，所有 final file 的 exclusive-create、读取、
  file identity 复核和回滚均相对该 fd。原路径被 rename/recreate 后，写入仍锚定原实体，提交前
  fresh root identity 对账失败，并从原实体精确回滚。
- Windows 以 `CreateFileW` 打开目录句柄，使用
  `FILE_LIST_DIRECTORY + FILE_FLAG_BACKUP_SEMANTICS + FILE_FLAG_OPEN_REPARSE_POINT`，共享模式只含
  READ/WRITE、不含 DELETE。最小实测确认 F:/NTFS 上 rename 被 OS 拒绝；句柄 file-index 与
  `lstat().st_ino` 双向对账，关闭前重验 root identity 与 reparse 状态。
- 使用进程内 active-root 注册表和磁盘 `O_EXCL` marker：正常第二 builder 在 train/predict 0 次时
  拒绝；marker 被删除时同进程第二 builder 仍不能进入，原调用以 rollback failure fail closed。
- 每个 final file 均由 `O_EXCL | O_BINARY` 等价流写入并 flush/fsync；记录 file identity。普通失败
  逆序删除本调用仍保持 exact identity 的文件；未知、竞争或被替换文件不删除。回滚或空目录证明
  失败分别暴露 `M3_MODEL_ROLLBACK_FAILED` / `M3_PREDICTION_ROLLBACK_FAILED`，公开异常链为空。
- G5A formal/development lease 覆盖 fresh/load/train/save 全长窗口。LightGBM `save_model` 只写系统
  `TemporaryDirectory` 唯一文件，验证普通非空 bytes 后再事务发布 `model.txt`、curve、metadata；
  不再直接向 output root 调用 LightGBM path writer。
- G5B formal/development lease 覆盖 fresh/inference/predict 全长窗口；两文件 writer 复用共享发布
  边界。Parquet 物理 hash 从锚定目录读取，R2 的 O_EXCL、精确回滚、copied-root pre-LightGBM、
  fresh whole-resign 与单次 predict 性质保留。

## 2. 关键对抗证据

- formal/development G5A、G5B 均在长操作回调中尝试 rename 原 root 并于原路径重建空目录：Windows
  阻止 rename 后正常发布；WSL/POSIX rename 成功，但 builder 稳定拒绝，dir-fd 将被移动的原实体
  回滚为空，替换目录保持为空。
- 第二 formal model/prediction builder 复入同 root：分别在 train/predict 0 次时拒绝；外层 builder
  仍精确完成一次训练/预测。
- 三个 G5A final writer 的 ValueError/RuntimeError、三处 final-file fsync、临时模型 save/empty/read/
  cleanup、post-write root 重验全部 fail closed；成功回滚目录为空。
- G5A/G5B rollback unlink failure 返回独立稳定码；owned file 被删除并以 competitor inode 重建时，
  verifier 不删除 competitor bytes，并把现场保留给人工调查。
- Windows junction/reparse 和 POSIX symlink root 均在创建 lease 前拒绝；删除 lease marker 后不接受
  第二 builder，原调用不谎报普通输入错误。

## 3. 修改文件

- `src/quant/research/m3/_artifact_publication.py`：私有跨平台 anchored lease 和事务发布实现。
- `src/quant/research/m3/model.py`：G5A 全窗口 lease、系统临时模型保存、三文件事务和 rollback 失败码。
- `src/quant/research/m3/predictions.py`：G5B 全窗口 lease、锚定 Parquet hash 和共享两文件事务。
- `tests/unit/test_m3_formal_model_artifact.py`：formal G5A、共享发布边界、Win32/POSIX、temp/fsync/
  rollback/reparse/identity 反例。
- `tests/unit/test_m3_model_artifact.py`：development G5A root replacement 反例。
- `tests/unit/test_m3_formal_prediction_artifact.py`：formal/development G5B root replacement、并发 lease，
  并将 R2 rollback hostile 注入对准跨平台 anchored unlink。
- G5A/G5B 原任务单与联合返工任务单：只补交付状态和报告链接。

## 4. 验证命令与实际结果

Windows 原生 Miniforge，`D:\Miniforge3\python.exe`，`PYTHONPATH=src`：

```text
pytest formal_model + formal_prediction + development_model + development_prediction
  61 passed, 1 skipped, 78299 warnings in 802.61s
最终增量：Win32 handle/deleted-marker 2 passed；junction/reparse 1 passed；
          owned-file identity/no-delete 1 passed
Ruff（3 个生产模块 + 3 个直接测试）：All checks passed!
mypy（3 个生产模块 + 2 个 formal 测试）：Success: no issues found in 5 source files
```

整组中的 1 skipped 是当时使用普通 Windows symlink API 时主机未授予 symlink 权限；随后测试改用
无需该权限的 junction，并实际 `1 passed`。warnings 为既有 Pandera/Polars 弃用警告和 worktree
`.pytest_cache` 权限警告，不改变断言结果。

WSL Miniforge `base`，同一 `/mnt/f` DrvFS worktree，`PYTHONPATH=src`：

```text
同四文件 pytest：62 passed, 78299 warnings in 466.23s
最终增量 owned-file identity/no-delete：1 passed
Ruff：All checks passed!
mypy：Success: no issues found in 5 source files
```

Windows 与 WSL 均执行了 fake LightGBM 的完整合同组和真实 native LightGBM smoke；包根延迟 import、
G5A fresh/copy-root/row-key/hostile verifier，以及 G5B copied-root 零 LightGBM、whole-resign、rank/key/
receipt 和 R2 writer 回归均包含在四文件组内。

## 5. 边界与剩余事项

- 本报告是实现者自测，不替代全新 Agent 独立复验或主 Agent 最终验收。
- WSL 路径为 `/mnt/f` DrvFS，不是 ext4；上述结果不是 Linux/ext4 Gate。
- 未运行正式全 folds/horizons work，未写正式 G1 artifact/journal，未访问网络、`data/legacy` 或真实数据。
- 本包通过独立复验与主验后，仅恢复 G5A/G5B 的工程前置；不关闭正式 G6-G9、真实性能、M3 或 ext4 Gate。
