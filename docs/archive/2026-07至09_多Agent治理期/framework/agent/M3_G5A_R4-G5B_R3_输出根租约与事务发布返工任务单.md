# M3 G5A R4 / G5B R3：输出根租约与事务发布返工任务单

日期：2026-08-09  
状态：实现与自测已交付，等待全新 Agent 独立复验和主 Agent 最终验收  
交付报告：[`M3_G5A_R4-G5B_R3_输出根租约与事务发布返工交付报告.md`](M3_G5A_R4-G5B_R3_输出根租约与事务发布返工交付报告.md)  
前置：G5A R3 的 fresh/model/predict 数学保留；G5B R2 除 output-root identity TOCTOU 外的返工项已通过独立复验

## 1. 失败闭环与不变量

G5B R2 独立复验在 formal/development builder 中均复现：调用方创建的空 `output_root`
通过预检后，在长时 fresh/predict 窗口被 rename，原路径再新建另一空实体目录。builder 把两文件
成功发布到替换目录。根因是预检时的目录实体身份未传递给 writer，writer 在长操作后重新信任了
当前路径。

主 Agent 同类审计证明 G5A 还有更宽的发布缺口：LightGBM `save_model(path)` 和 Polars
`write_parquet(path)` 直接按路径写入，既未证明还是原目录实体，也没有将三文件作为一个可回滚事务。
因此 G5A 数学/fresh 结论保留，但不可变发布子合同重新打开为 R4。

不变量：builder 成功时，产物必须位于调用方预先提供的那一个空目录实体，不是同一路径字符串
当下指向的任意目录。失败只回滚本次拥有的文件，不覆盖、不删除并发/既有文件，不留 partial bundle。

## 2. 共享私有发布边界

新增私有轻依赖模块 `quant.research.m3._artifact_publication`，仅服务 M3 builder，不从包根导出，
不是可持久 capability、数字签名、WORM 或通用文件框架。

1. 任何长时 fresh/train/predict 前，校验 root 是已存在、空、非 symlink/junction/reparse 的
   实体目录，随后取得本调用独占 lease。第二 builder 不得共享 lease，必须在 train/predict 0 次时拒绝。
2. POSIX 使用 `O_DIRECTORY | O_NOFOLLOW` 的已打开 dir-fd 锚定原目录实体；子文件 exclusive-create、
   身份校验、回滚与 lease 清理均通过该 dir-fd 完成。路径被 rename 时写入仍锚在原实体；成功前
   若原路径不再指向该实体，必须用 dir-fd 回滚并 fail closed。
3. Windows 持有原 root 的 Win32 directory handle；打开时使用
   `FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT`，共享模式不包含 `FILE_SHARE_DELETE`，
   使 rename/delete/replace 在 lease 存续期由 OS 拒绝。关闭前 fresh 重验 handle、当前路径身份与 reparse 状态。
   不得用一次 `Path.is_dir()` 或只打开子文件代替目录句柄。
4. lease marker/句柄只是进程内发布状态，不进 manifest/receipt/identity。成功后目录 exact set 仍只有
   任务冻结产物；任一失败后目录为空。
5. 产物使用 `O_EXCL | O_BINARY` 等价独占打开，从已打开流写入并 flush/fsync。打开后保留
   file identity，回滚前 fresh 比对，只删除本调用文件。
6. writer/flush/fsync/post-write/root 重验任一失败，逆序回滚本调用文件和 lease。普通失败仍使用
   阶段 `*_ARTIFACT_INVALID`；回滚本身或失败后空目录证明失败使用
   `M3_MODEL_ROLLBACK_FAILED` / `M3_PREDICTION_ROLLBACK_FAILED`。公开异常 cause/context 均为 `None`。

## 3. G5A R4 最小修复

1. formal/development model builder 在 fresh alignment、LightGBM import/train 前取得 lease，并在所有路径释放。
   现有 fresh verifier 顺序、exact formal capability、train/validation 数学、best iteration、curve/manifest/receipt/predict 不变。
2. `Booster.save_model` 不得直接写 `output_root/model.txt`。使用系统临时目录的唯一文件，校验非空并
   读取 bytes，再经 lease exclusive stream 发布。临时目录必须自动清理，不得位于 output-root、G1/journal 或 `data/`。
3. `model.txt`、`validation_curve.parquet`、`model.metadata.json` 是同一三文件事务；全部完成、
   内容和 root 重验通过后才成功。不保留 partial bundle 作为恢复协议。

## 4. G5B R3 最小修复

1. formal/development prediction builder 在现有空目录预检位置取得 lease，并将同一 lease 传递到两文件
   writer；不得在 predict 后丢弃预检身份并重新信任当前路径。
2. R2 已验收的 O_EXCL/O_BINARY、flush/fsync、file identity、精确回滚、late concurrent claim、
   copied-root 在 LightGBM 前拒绝、builder/verifier 各 predict 一次、fresh whole-resign 拒绝全部保留。
3. 输出 exact set 仍为 `predictions.parquet` 和 `prediction_manifest.json`，receipt/formal-development 隔离不变。

## 5. 必测反例

- formal/development G5A：在 fresh verifier 返回前、LightGBM train/save 前后尝试 rename 原 root 并以新空目录
  替换原路径。Windows 必须阻止成功替换；POSIX 若 rename 成功，必须在返回前拒绝并通过 dir-fd 将原实体回滚为空。
  替换目录始终 0 files。
- formal/development G5B：精确复现 R2 独立复验的 predict 窗口攻击，不得将两文件发布到替换目录。
- 第二 builder 使用已 lease 的同一 root，在 train/predict 0 次时拒绝；root/lease 被替换、删除、改为
  reparse/symlink 或身份漂移均 fail closed，错误/traceback 不泄露路径或 marker。
- G5A 三个 final writer 分别抛 ValueError/非 ValueError，flush/fsync 在第 1/2/3 文件失败，以及 post-write/root 重验失败；
  成功回滚后 root 为空，无 lease。
- G5A 模型临时保存失败、空 bytes、读取失败、清理失败；不得把临时文件当正式输出，不留 output partial。
- G5B R2 的 writer/fsync/late O_EXCL/unknown file/rollback failure 反例全部保持。回滚任一 final file 或 lease 失败时
  返回对应 rollback stable code，`cause/context is None`，不删除并发/既有/身份漂移文件。
- G5A R3 的 formal fresh/copy-root/row-key/hostile verifier/native LightGBM 和 G5B R2 的 copied-root 零 LightGBM、
  whole-resign fresh predict、rank/key/receipt 边界全部保持。包根 import 不加载 LightGBM/Qlib/MLflow。

## 6. 白名单、验证与边界

可写：

- 新增 `src/quant/research/m3/_artifact_publication.py`；
- `src/quant/research/m3/model.py`、`src/quant/research/m3/predictions.py`；
- `tests/unit/test_m3_formal_model_artifact.py`、`tests/unit/test_m3_formal_prediction_artifact.py`；
- 只为 development 共用发布边界必需的 `tests/unit/test_m3_model_artifact.py`、`tests/unit/test_m3_prediction_artifact.py`；
- 本任务交付/独立复验报告，以及 G5A/G5B 原任务单状态链接补充。

禁止修改 contracts、G1-G4C、G6+、artifact 格式、receipt 框架、正式 G1/artifacts/journal、
`data/legacy`、依赖和配置。禁止网络。不得把 path hash、marker 或 lease 表述为外部来源证明。

验证：Windows 先跑 formal/development root-lease/writer 反例，再跑 G5A/G5B 直接回归、native LightGBM、
Ruff/mypy；WSL base `/mnt/f` 跑同组定向并明确 DrvFS 非 ext4；最后 `git diff --check` 和白名单审查。

实现后必须由全新 Agent 独立复现 Windows/POSIX root replacement、并发 lease、中段 writer/rollback 及原 G5A/G5B fresh 反例。
独立复验 PASS 后再由主 Agent 验收。本包通过仅恢复 G5A/G5B 工程前置，不执行正式全 work，不关闭 M3 或 ext4 Gate。

## 7. R2：POSIX symlink 测试清理返工（2026-08-09）

独立复验报告：`M3_G5A_R4-G5B_R3_输出根租约与事务发布独立复验报告.md`。生产 publication 合同及
Windows/POSIX 独立探针均通过；唯一 Gate 阻断是
`test_r4_publication_rejects_link_root_without_creating_lease` 的测试清理在 POSIX symlink 上调用
`Path.rmdir()`，稳定触发 `NotADirectoryError`，导致 WSL 四文件组 `1 failed, 62 passed`。

最小返工规则：

- 生产代码零修改；
- Windows junction cleanup 继续使用目录删除语义；POSIX directory symlink 必须使用`unlink()`；
- cleanup放在不会掩盖产品断言的位置，若产品未按预期拒绝仍应显示产品失败，而不是清理异常；
- 增加/保持双平台分支证明 link本体被删除、real target未删除、root内未创建lease/输出；
- Windows四文件组、WSL base/DrvFS四文件组、Ruff、mypy、diff check全部通过。

R2只允许修改`tests/unit/test_m3_formal_model_artifact.py`与新增唯一R2交付报告/复验报告。返工后由全新
独立上下文复验；不得借此修改或放宽生产link/reparse/root lease逻辑。
