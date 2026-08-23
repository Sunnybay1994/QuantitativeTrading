# M3 G5A R4 / G5B R3：输出根租约与事务发布 R2 独立复验报告

日期：2026-08-09  
角色：未参与 R1 实现或 R2 返工的全新独立复验 Agent  
结论：**PASS，可进入主 Agent 最终验收**

## 1. 范围、独立性与边界

- 完整读取了项目 `AGENTS.md`、联合返工任务单（含 §7 R2）、R1 独立复验 FAIL 报告和
  R2 返工交付报告；生产代码与实现者测试全程只读，本报告是唯一仓库写入。
- 未执行 `git add/commit`，未访问网络、`data/legacy`、正式 G1 artifact/journal 或正式候选目录。
  pytest 使用独立系统临时 `basetemp`；额外探针也只使用系统临时目录。
- 本结论只关闭 R2 的跨平台测试清理返工，并恢复 G5A/G5B publication **工程合同**前置。
  WSL 证据来自 `base` + `/mnt/f` DrvFS，不是 ext4，不代表正式 full work、G6-G9、M3 或
  Linux/ext4 Gate 通过。

## 2. R2 差异与生产代码零变化核对

R2 的可见变更严格位于
`tests/unit/test_m3_formal_model_artifact.py::test_r4_publication_rejects_link_root_without_creating_lease`：

1. 产品拒绝断言和 real target 空目录断言先完成；
2. Windows junction 使用 `rmdir()`，POSIX directory symlink 使用 `unlink()`；
3. cleanup 后以 `os.path.lexists(link)` 证明 link entry 已删除，并再次证明 real target 仍存在且为空。

三份生产文件的当前 SHA-256 快照如下；其文件修改时间分别为 02:49、02:14、01:59，均早于
03:41 生成的 R1 独立复验报告及 03:44 的 R2 测试修改时间。R2 交付白名单、当前状态和内容审查均未显示
生产文件在 R2 被再次写入：

| 文件 | SHA-256 |
| --- | --- |
| `src/quant/research/m3/_artifact_publication.py` | `4229EE2649AB46D1329290ED66BC2A0F6763339663E8465D198D94574A87901D` |
| `src/quant/research/m3/model.py` | `894D8C2434CD17AD83E6F033D9D33DE329363D391F77B2A0329EEFDE3E5BA752` |
| `src/quant/research/m3/predictions.py` | `E36955E932E6D8C943F3A214177199C3114B3C3632205CC3419FD19BB2F99901` |

R1 报告和 R2 开始前均未冻结这三份文件的加密哈希基线，因此上表是当前快照，**不是伪装成 pre/post
加密对照**。可复核的证据是 R2 冻结白名单仅允许一份测试和报告、生产文件 mtime 早于 R1 复验、当前
`git diff`/内容仍对应 R1 已审 publication 实现，以及本轮唯一测试文件写入时间。按本轮可观测证据，R2
没有放宽或修改 publication、link/reparse、root lease、rollback 或 artifact 生产语义。

## 3. 标准—独立证据—结论

| 冻结要求 | 独立证据 | 结果 |
| --- | --- | --- |
| POSIX symlink 使用 `unlink()` | 源码定向审查；WSL 隔离用例包含在四文件组中并通过；cleanup 后 link 本体消失、real target 保留 | PASS |
| Windows junction 使用目录删除语义 | 源码定向审查；Windows 对应用例通过，未因普通 symlink 权限而跳过 | PASS |
| 产品拒绝断言位于 cleanup 前 | 断言顺序为 publication 拒绝 → target 为空 → cleanup；不存在 `finally` 抢先清理 | PASS |
| cleanup 不遮蔽产品错误 | 额外对抗探针把发布器替换为错误接受 link 的假实现；Windows/WSL 均直接暴露 `link root entered`，且此时 link 仍存在、target 仍为空，证明 cleanup 未覆盖原错误 | PASS |
| 四文件 Windows 回归绿色 | formal/development model + prediction 四文件组 `63 passed` | PASS |
| 四文件 WSL base/DrvFS 回归绿色 | 同组 `63 passed`，R1 的 `NotADirectoryError` 不再出现 | PASS |
| 定向 Ruff/mypy 双平台绿色 | 两平台 Ruff 全通过；mypy `--no-incremental` 均为 5 source files 无问题 | PASS |

## 4. 独立验证记录

Windows 原生 Miniforge（`D:\Miniforge3\python.exe`，`PYTHONPATH=src`）：

```text
python -m pytest \
  tests/unit/test_m3_formal_model_artifact.py \
  tests/unit/test_m3_formal_prediction_artifact.py \
  tests/unit/test_m3_model_artifact.py \
  tests/unit/test_m3_prediction_artifact.py -q --basetemp=<system-temp>
=> 63 passed, 78299 warnings in 962.03s

Ruff（3 个生产模块 + 4 个直接测试）
=> All checks passed!

mypy --no-incremental（3 个生产模块 + 2 个 formal 测试）
=> Success: no issues found in 5 source files

cleanup 不遮蔽产品错误对抗探针
=> R2_CLEANUP_DOES_NOT_MASK_PRODUCT_FAILURE_PASS
```

WSL Miniforge `base`（同一 `/mnt/f` DrvFS worktree，`PYTHONPATH=src`）：

```text
同四文件 pytest
=> 63 passed, 78299 warnings in 484.11s

同范围 Ruff
=> All checks passed!

同范围 mypy --no-incremental
=> Success: no issues found in 5 source files

cleanup 不遮蔽产品错误对抗探针
=> R2_CLEANUP_DOES_NOT_MASK_PRODUCT_FAILURE_PASS
```

warnings 是既有 Pandera/Polars deprecation 及 worktree `.pytest_cache` 权限警告，不改变测试终态。
Windows 初次后台命令因父进程未传入目标 worktree `PYTHONPATH` 而发生 4 个 collection error；确认没有执行
测试主体后，以正确 `PYTHONPATH` 和新的隔离 `basetemp` 重跑，得到上述最终绿色结果。该启动配置错误未被
计入产品结论，也未覆盖在报告之外。最终 `git diff --check` 为 PASS；仅出现既有 LF/CRLF 提示，没有
whitespace error。

## 5. 最终判定

**PASS。** R1 唯一阻断的 POSIX symlink cleanup 已按平台原语最小修复；Windows junction 与 POSIX
symlink 均正确清理，real target 不被删除，且产品拒绝失败优先暴露、不被 cleanup 异常遮蔽。生产 publication
逻辑在 R2 保持不变，双平台四文件回归和定向静态检查全部绿色。

本报告只允许任务进入主 Agent 最终验收。即使主验通过，也仅恢复 G5A R4 / G5B R3 publication 工程前置；
正式 full folds/horizons、真实性能、G6-G9、M3 总 Gate 与 ext4 Gate 仍保持开放。
