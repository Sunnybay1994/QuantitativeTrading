# M3 G5B R2：正式 PredictionArtifact 独立复验报告

日期：2026-08-09  
角色：未参与 R2 返工实现的全新独立初验 Agent  
结论：**FAIL，返回 R3 最小返工**

## 1. 独立性与范围

- 完整阅读根 `AGENTS.md`、`.ai` 通用规则、G5B R1/R2 任务合同、R1 独立复验、
  R2 交付报告、`predictions.py`、G5A `model.py` 及直接测试。
- 生产代码和实现者测试全程只读；仅新增本报告，未 `git add/commit`，未访问网络、
  `data/legacy`、正式 G1 journal 或正式候选目录。独立探针只使用系统临时目录。
- Windows 使用 `D:\Miniforge3\python.exe`；WSL 使用 Miniforge `base` 和同一 `/mnt/f`
  DrvFS worktree。WSL/DrvFS 证据不是 ext4/Linux Gate。

## 2. R1 三个 P1 的复验结果

### 已关闭：两文件失败回滚和 exclusive create

- formal/development 共用 `_write_prediction_bundle`；Parquet 与 manifest 均由
  `O_CREAT | O_EXCL | O_BINARY` 的已打开 binary stream 写入。
- 独立 `fsync` 注入：第 1 次（Parquet）和第 2 次（manifest）分别抛带私密 marker
  的 `RuntimeError`，两者均返回精确 `M3_PREDICTION_ARTIFACT_INVALID`，
  `cause/context=None`，marker 不泄漏，目录为空。正常路径观测到两次 `fsync`。
- 独立 late-open 竞争：在 `_open_owned_output` 紧邻 `os.open(O_EXCL)` 之前抢占
  Parquet 或 manifest，均返回 `M3_PREDICTION_ROLLBACK_FAILED`，不覆盖、不删除竞争者
  sentinel，异常链为空。
- 独立 rollback hostile 反例：manifest 失败后让 Parquet `unlink` 在嵌套异常中失败，
  同时增加未知竞争文件。结果精确为 `M3_PREDICTION_ROLLBACK_FAILED`、
  `cause/context=None`、marker 不泄漏，未知文件 bytes 保持不变。

### 已关闭：copied model root 的 pre-LightGBM 拒绝顺序

- G5A `verify_model_artifact` 现在先完成 receipt bytes 验真和 exact input/output/root 闭包，
  再调用 `_lightgbm()` / `Booster`。
- 独立使用 copied model 三文件 + 原 receipt 调用 G5B builder 和 verifier，两者均在
  `M3_PREDICTION_ARTIFACT_INVALID` 处稳定拒绝，`cause/context=None`，
  hostile `_lightgbm` counter 为 **0**，builder output 为空。

### 已关闭：fresh predict 与整包重签

- 将 score 取反并重算 rank，然后重写 Parquet，重算
  `predictions_sha256` / `prediction_keys_sha256`，canonical 重写 manifest，并重发布 receipt。
  fresh verifier 仍以 `M3_PREDICTION_ARTIFACT_INVALID` 拒绝，异常链为空。
- 让 `_read_predictions` 抛带私密 marker 的 `OSError`，对外仍仅有稳定错误码，
  `cause/context=None`，marker 不泄漏。

## 3. 新发现的 P1：caller-created output root 身份未绑定

### 现象

formal 和 development builder 均会接受下列竞争：

1. builder 在调用方创建的空目录 A 上通过 `_require_empty_directory`；
2. fresh verification / native predict 执行期间，竞争者将 A rename 到另一路径，并在原路径新建
   不同 inode/file-id 的空真实目录 B；
3. builder 成功返回，并把 `prediction_manifest.json` 和 `predictions.parquet` 写入 B；
4. 真正通过调用前空目录检查的 A 仍为空。

独立最小复现实测摘要：

```text
FORMAL_ROOT_RACE=ACCEPTED
NEW_FILES=prediction_manifest.json,predictions.parquet
ORIGINAL_FILES=
N=5

DEV_ROOT_RACE=ACCEPTED_N=5
NEW_FILES=prediction_manifest.json,predictions.parquet
ORIGINAL_FILES=
```

### 根因与违反规则

- formal/development 分别在 `predictions.py:316` / `predictions.py:224` 检查空真实目录，
  但不保留该时点的 root identity。
- `_write_prediction_bundle` 直到 `predictions.py:972` 才对当前路径 `os.lstat`，因此把替换后
  的 B 误当成权威 root；`predictions.py:984` 的成功路径也未与调用前 root identity
  对账。现有 identity 只用于写失败后 rollback，不保护成功发布。
- 这违反任务书 §6.1 的“output root 必须是调用方已创建的空实体目录”，
  也违反 R2 对 exact root/no-clobber 身份的意图。仅保护最终文件名的 `O_EXCL`
  不能防止父目录身份被替换。

### 必须返工与新增测试

1. 空目录预检必须产生并传递调用方 root 的权威 identity，不得在长时 fresh/predict
   之后重新以同路径当前对象作为新的信任起点。
2. 在首个输出创建前与两文件成功后，都必须 fresh 证明路径仍是该 exact root、
   非 link/reparse 且 tree 精确；中途身份变化不得返回成功 capability。
3. 修复必须同时考虑 Windows rename/reparse 和 POSIX rename/symlink 竞争；不能只增加
   另一次 `exists()` 而保留新的 check/use 窗口。若需要受信目录 handle/dir-fd 或平台等价
   原语，必须在 R3 任务书冻结，不由实现者自行放宽。
4. 必测反例：formal 和 development 分别在 predict 返回前替换 root；新路径目录不得
   获得任何输出，原 root 不得被误删，对外错误稳定脱敏且异常链为空。
5. 通过条件：上述反例双路径均拒绝；R2 的 ValueError/RuntimeError、flush/fsync、
   late `O_EXCL`、rollback hostile/unknown-file、copied-root pre-load 和整包重签回归保持绿色；
   再由未参与 R3 实现的全新 Agent 独立复验。

## 4. 验证记录

| 验证 | 实际结果 |
| --- | --- |
| Windows formal prediction + formal model + development prediction + topk | **45 passed**，50328 warnings，601.67s |
| Windows 定向 Ruff | PASS |
| Windows `predictions.py` + `model.py` mypy | PASS |
| WSL base `/mnt/f` 同组扩大回归 | **45 passed**，50328 warnings，270.74s |
| WSL base 定向 Ruff | PASS |
| WSL base `predictions.py` + `model.py` mypy | PASS |
| 独立 fsync 失败/成功调用计数 | PASS；失败后空目录，成功精确 2 次 fsync |
| 独立 late-open 竞争/no-clobber | PASS；sentinel 不覆盖不删除 |
| 独立 rollback hostile + 未知文件 | PASS；稳定 rollback code，无异常链/泄密 |
| copied-root G5B builder/verifier pre-LightGBM | PASS；counter=0，builder output 空 |
| score/Parquet/manifest/receipt 整包重签 | PASS；fresh predict 拒绝 |
| formal caller-root 身份替换 | **FAIL：替换目录被成功发布** |
| development caller-root 身份替换 | **FAIL：替换目录被成功发布** |

warnings 为已知 Pandera/Polars deprecation 与 worktree `.pytest_cache` 权限警告；
`--basetemp` 下测试完成，不影响上述结论。

## 5. 结论与 Gate 边界

**FAIL，返回 R3 最小返工。** R2 已关闭 R1 的三个原始 P1，但成功发布仍未将
output root 绑定到调用方通过预检的 exact 目录对象。在 R3 实现、新回归和全新
独立复验 PASS 之前，G5B 不进入主 Agent 最终验收，不解锁正式 G6。本轮即使其他
45 项合同回归双平台绿色，也不代表正式全 work、真实数据性能、M3 或 Linux/ext4 Gate
已通过。
