# M3 G5A R4 / G5B R3：输出根租约与事务发布独立复验报告

日期：2026-08-09  
角色：未参与本轮实现的全新独立复验 Agent  
结论：**FAIL，返回实现 Agent 做最小跨平台测试清理返工；不进入主 Agent 最终验收**

## 1. 独立性、范围与边界

- 完整核对了联合返工任务单、交付报告、G5A/G5B 原任务单、G5A R1/R2/R3 和
  G5B R1/R2 的失败/复验证据，并只读审查了 `_artifact_publication.py`、`model.py`、
  `predictions.py` 及四个直接测试文件。
- 生产代码与实现者测试全程只读；本报告是唯一仓库写入。未执行 `git add/commit`，
  未访问网络、`data/legacy`、正式 G1 artifact/journal 或正式候选目录。独立探针只使用
  Windows 或 DrvFS 系统临时目录。
- 本结论只针对 G5A/G5B publication 工程合同。WSL 使用 `/mnt/f` 工作树和 `/mnt/c`
  临时根，都是 DrvFS，不是 ext4；不宣称正式 full work、M3 或 Linux/ext4 Gate 通过。

## 2. 标准—证据—结论

| 冻结要求 | 独立证据 | 结果 |
| --- | --- | --- |
| exact caller-created output-root 在长时窗口受租约保护 | Windows 对 formal/development model 的 fresh/loader、train、temp-save、commit 共 8 个窗口，以及 formal/development prediction 的 fresh、predict、commit 共 6 个窗口尝试 rename+replacement；14 次 rename 均被目录句柄阻止，builder 只向原实体发布 exact bundle | PASS |
| POSIX rename 成功后仍锚定原实体并 fail closed | WSL base/DrvFS 对同样 14 个窗口攻击；rename 均成功，公开入口分别返回 `M3_MODEL_ARTIFACT_INVALID` / `M3_PREDICTION_ARTIFACT_INVALID`，cause/context 为 `None`，被移动的原实体和替换根均为空 | PASS |
| 同根并发、marker 删除、进程内 registry | Windows 与 WSL 独立低层探针均证明第二 lease 不能进入；marker 被删除后 registry 仍拒绝同进程复入，原调用不谎报成功 | PASS |
| Windows junction/reparse 与 POSIX symlink 拒绝 | Windows 独立 junction 探针和 WSL 独立 symlink 探针均在创建 lease 前拒绝，真实目录保持空 | PASS（产品行为） |
| lease handle/dir-fd 被关闭、owned file inode 替换 | 句柄/fd 失效均 fail closed；owned file 被竞争者用新 inode 重建后，rollback 不删除 competitor bytes，并返回 rollback failure | PASS |
| G5A 三文件事务和 G5B 两文件事务 | 独立注入 model 第 2/3 writer 的 `ValueError`/`RuntimeError`、三个 final-file fsync 时点；prediction 两个 writer 及两个 final-file fsync 时点，普通失败后目录均精确回滚为空 | PASS |
| rollback failure 独立稳定码和空异常链 | 独立注入 model/prediction unlink 失败和 Windows handle-close；精确返回 `M3_MODEL_ROLLBACK_FAILED` / `M3_PREDICTION_ROLLBACK_FAILED`，cause/context 为 `None`，保留无法证明安全删除的现场 | PASS |
| 原 G5A/G5B 合同不回归 | Windows 63-test 组通过，WSL 组除下述 cleanup 外其余 62 项通过；包含 copied G5A/G5B upstream root 在 LightGBM 前拒绝、native LightGBM train/save/load/predict、fresh whole-resign 拒绝、builder/verifier 各 predict 一次、late `O_EXCL` no-clobber 与不删竞争文件 | PASS（产品行为） |
| Windows 与 WSL base 冻结定向 pytest 必须绿色 | Windows `63 passed`；WSL `62 passed, 1 failed`，失败是 POSIX symlink 用例的平台错误 cleanup | **FAIL** |

## 3. 阻断问题：POSIX symlink 测试用错清理原语

- **现象**：WSL base/DrvFS 四文件定向 pytest 在
  `tests/unit/test_m3_formal_model_artifact.py:111` 失败。测试主体已成功证明
  `ArtifactPublication(link)` 拒绝 symlink，且真实目录为空；但 `finally` 对 POSIX
  symlink 调用 `link.rmdir()`，抛出 `NotADirectoryError: [Errno 20] Not a directory`。
- **根因**：测试创建阶段已区分 Windows junction 和 POSIX symlink，清理阶段却无条件共用
  directory removal。POSIX symlink 应删除 link entry，不应以 `rmdir` 当作实体目录删除。
- **违反的规则/不变量**：联合返工任务单要求 Windows 与 WSL base 定向 pytest 均通过；
  项目规则要求平台特有语义分别验证，且测试清理不能掩盖真正断言结果。当前 WSL Gate
  终态不是绿色，实现交付报告中的 `62 passed` 无法由当前工作树复现。
- **最小复现**：

  ```text
  WSL base /mnt/f DrvFS:
  python -m pytest tests/unit/test_m3_formal_model_artifact.py \
    tests/unit/test_m3_formal_prediction_artifact.py \
    tests/unit/test_m3_model_artifact.py \
    tests/unit/test_m3_prediction_artifact.py -q

  result: 1 failed, 62 passed
  failure: test_r4_publication_rejects_link_root_without_creating_lease
           link.rmdir() -> NotADirectoryError [Errno 20]
  ```

- **必须返工**：仅修复该测试的平台清理。POSIX symlink 使用 link unlink，Windows junction
  使用 junction directory removal；保持生产 publication 实现不变。应增加/收紧清理回归，
  证明 cleanup 既删除测试创建的 link/junction，也不用二次异常掩盖产品断言。
- **通过条件**：隔离的 POSIX symlink 用例通过；Windows 对应 junction 用例通过；四文件
  Windows/WSL base 定向 pytest 均绿色；Ruff/mypy 保持绿色；再由未参与返工的全新 Agent
  独立复验。

## 4. 验证记录

| 检查 | 实际结果 |
| --- | --- |
| Windows Miniforge 四文件 pytest | **63 passed**，78298 warnings，931.72s |
| WSL Miniforge base / DrvFS 四文件 pytest | **1 failed, 62 passed**，78298 warnings，614.83s |
| Windows 独立 root/lease/marker/inode/handle/junction 探针 | PASS，6 类 |
| Windows formal/development builder 全窗口 rename+replacement | PASS，14 个窗口均由 OS 阻止 |
| Windows 独立 writer/fsync/rollback/handle-close 故障注入 | PASS，model 9 类 + prediction 8 类 |
| WSL base/DrvFS 独立 root/symlink/marker/inode/closed-fd 探针 | PASS，6 类 |
| WSL base/DrvFS formal/development builder 全窗口 rename+replacement | PASS，14 个窗口 rename 成功后均拒绝并锚定回滚 |
| Windows Ruff | All checks passed |
| WSL base Ruff | All checks passed |
| Windows mypy | Success: no issues found in 5 source files |
| WSL base mypy | Success: no issues found in 5 source files |
| `git diff --check` | PASS |

warnings 为既有 Pandera/Polars deprecation，与本次阻断无关。失败用例的产品断言在
cleanup 前已成立，因此本报告不把它误写为 publication 生产语义缺陷；但也不能把失败的
WSL pytest Gate 包装为 PASS。

## 5. 最终判定与 Gate 边界

**FAIL，返回最小返工。** 当前独立证据支持输出根租约、锚定事务发布、精确回滚、
no-clobber 和原 G5A/G5B fresh/native/predict 不变量；但冻结的 WSL base 定向 pytest 因
POSIX symlink cleanup 缺陷不绿，不满足完成标准。返工不应扩大到生产算法。

即使上述 cleanup 返工通过全新独立复验，也只能恢复 G5A/G5B publication 工程前置；
不代表正式 full folds/horizons work、真实性能、G6-G9、M3 或 ext4 Gate 已通过。
