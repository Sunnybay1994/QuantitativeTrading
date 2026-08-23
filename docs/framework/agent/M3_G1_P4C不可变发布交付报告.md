# M3 G1-P4C：不可变发布交付报告

日期：2026-07-15  
角色：外部实现 Agent（第 2 步）  
状态：**待独立初验**（不得宣布 P4C/B4/G1/M3/Gate 通过）  
任务书：[`M3_G1_P4C不可变发布外部闭环任务单.md`](M3_G1_P4C不可变发布外部闭环任务单.md)

## 1. 修改文件

| 文件 | 动作 |
|---|---|
| `src/quant/data/m3_release.py` | 新增 |
| `src/quant/data/__init__.py` | 仅新增冻结导出 |
| `tests/unit/test_m3_g1_release.py` | 新增 |
| `docs/M3_G1_P4C不可变发布交付报告.md` | 本报告 |

未修改 P4A/P4B、domain Schema、配置、路线图或上游测试。

## 2. 实现摘要

1. **纯准备** `prepare_g1_release`：从 `G1ReleaseInputs` 重建 P4A candidate → verify → audit → sample/request 闭包 → `reconcile_cross_source` → release identity → 空 issues quality；零 IO/网络。
2. **Release identity**：`SHA256(canonical_json(m3-g1-release-identity-v1))`；quality hash 不进入 release ID。
3. **17 项 artifact + manifest**：唯一 `_ARTIFACT_REGISTRY`；Parquet 固定 zstd 参数；JSON 为 canonical bytes；manifest 最后写。
4. **Strict reader/verifier**：拒绝 BOM/duplicate key/类型漂移/非 canonical bytes；final 18 entry、`st_nlink==1`、无 symlink/inode 别名；从 final 重算 primary key（调用 P4A `_primary_candidate_key`）与 release ID。
5. **原子发布**：staging(0700) → stage-release 预验 → `libc.renameat2(..., RENAME_NOREPLACE)` → root fsync → 再验 → cleanup；已有 final 仅严格验真复用；无 `os.rename/os.replace` fallback。

## 3. 任务书验收矩阵映射

| # | 要求 | 证据 |
|---|---|---|
| 1 | inputs exact rebuild；prepare 零 IO/network | `test_inputs_exact_rebuild`；`test_prepare_zero_io_network` |
| 2 | identity 传播与稳定性 | `test_release_identity_stable_under_row_shuffle`；`test_release_identity_changes_on_calendar_cell`；`test_tolerance_change_changes_release_id` |
| 3 | 无自报 candidate/audit 入口；quality fail 零增量 | `test_no_caller_self_reported_candidate_entry`；`test_quality_fail_zero_delta`；`test_prepared_rejects_self_reported_quality` |
| 4 | strict JSON reader | `test_strict_json_readers`（BOM/duplicate/非 canonical/bool 冒充 int） |
| 5 | 17-entry registry；parquet 列/dtype | `test_artifact_registry_closure`；`test_parquet_extra_column_rejected`；`test_coercible_dtype_rejected` |
| 6 | primary 自洽篡改仍拒 | `test_primary_table_tamper_with_self_consistent_manifest_rejected` |
| 7 | （detail/summary 闭包由 verifier+bundle 构造覆盖） | happy `verify_g1_release` + identity 重算路径 |
| 8 | extra/hidden/FIFO/symlink/hardlink | `test_extra_hidden_and_fifo_rejected`；`test_symlink_and_hardlink_rejected` |
| 9 | 首次发布、零写复用、损坏/空 final | `test_publish_verify_happy_path`；`test_corrupt_final_not_overwritten`；`test_empty_final_concurrent_not_overwritten` |
| 10 | fsync/rename 故障；主异常优先 | `test_fsync_fault_and_primary_priority`；`test_renameat2_eexist_reuses_winner`；`test_renameat2_unsupported` |
| 11 | 真实 renameat2 / 不支持 fail-closed | `test_real_renameat2_noclobber`；`test_platform_probe_is_bool`；见 §5 环境限制 |
| 12 | 脱敏；包根导出；无 research/connector | `test_error_surfaces_no_path_leak`；`test_package_export_and_no_research_import`；`test_static_no_rename_fallback`；`test_quality_hash_not_in_release_id` |

## 4. 验证命令与结果

环境：`wsl.exe` → `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，`/home/mabw/miniforge3/bin/conda run -n base`。

| 命令 | 结果 |
|---|---|
| `PYTHONPATH=src python -m pytest -q tests/unit/test_m3_g1_release.py`（分两批合计） | **27 passed**（19 + 8） |
| `PYTHONPATH=src python -m pytest -q` | **796 passed**，916412 warnings，2648.91s |
| `python -m ruff check src tests` | **All checks passed** |
| `python -m mypy src` | **Success: no issues found in 79 source files** |

定向批次数：

```text
19 passed, 8 deselected ... in 1259.20s
8 passed, 19 deselected ... in 788.25s
```

全量：

```text
796 passed, 916412 warnings in 2648.91s (0:44:08)
```
## 5. 已知限制与环境事实（非合同放宽）

### 5.1 WSL1 与 `renameat2(RENAME_NOREPLACE)`

**现象**：本机内核 `4.4.0-*-Microsoft`（WSL1）上，`libc.renameat2(..., RENAME_NOREPLACE=1)` 对目录返回 `EINVAL`；`flags=0` 可成功。

**证据**：探测脚本对空目录 rename；`errno=22 EINVAL`。

**影响**：生产路径按合同 fail-closed，映射为 `G1_RELEASE_PUBLISH_UNSUPPORTED`（另含 `ENOSYS`/`ENOTSUP`）。本机**不能**完成真实 NOREPLACE 目录原子提交。

**测试策略**：`publish_capable` fixture 在 `platform_supports_renameat2_noreplace()==False` 时注入仅用于测试的 no-clobber `os.rename`（dst 已存在则 `CONCURRENT_PUBLISH`），以覆盖 prepare/write/verify/复用/故障语义；真实 `_renameat2_noreplace` 仍由 `test_real_renameat2_noclobber` 证明在本机返回 `PUBLISH_UNSUPPORTED` 或（在支持内核上）`CONCURRENT_PUBLISH`。

**建议**：主验/实盘发布应在支持 `RENAME_NOREPLACE` 的 WSL2/Linux 内核上复验真实 commit；不得回退 `os.rename/os.replace` 到生产路径。

### 5.2 其他

- 默认测试零网络、不读 token/TOML、不访问 `_old/`、不跑真实 connector。
- Pandera/Polars deprecation warnings 为既有噪声，不改变本包结论。
- 未宣称 B4/G1/M3/Gate 关闭；下一步为独立初验。

## 6. 合同矛盾记录

无需要主 Agent 改写 SSOT 的接口矛盾。P4A/P4B 公共接口按现行代码消费；唯一允许的私有依赖为 `_primary_candidate_key`。

环境能力缺口见 §5.1（实现已 fail-closed，未放宽合同）。
