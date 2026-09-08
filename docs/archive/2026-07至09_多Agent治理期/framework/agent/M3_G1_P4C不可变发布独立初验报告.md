# M3 G1-P4C：不可变发布独立初验报告

日期：2026-07-15  
角色：外部独立初验 Agent（第 3 步；未参与实现）  
结论：**独立初验不通过**，退回外部实现 Agent 返工  
边界：本报告**不得**宣布 P4C / B4 / G1 / M3 / 任一 Gate 最终通过；亦未修改生产代码或正式测试

任务书：[`M3_G1_P4C不可变发布外部闭环任务单.md`](M3_G1_P4C不可变发布外部闭环任务单.md)  
交付声明（非证据）：[`M3_G1_P4C不可变发布交付报告.md`](M3_G1_P4C不可变发布交付报告.md)

## 1. 审查范围与方法

只读审查：

- `src/quant/data/m3_release.py`
- `src/quant/data/__init__.py` 冻结导出
- `tests/unit/test_m3_g1_release.py`
- 对照任务书 §3–§11、总设计 §2/§3/§6–§9、`M3实施与Agent交接.md` §4.10、P4A/P4B 主验报告与 domain Schema 契约

方法：

1. 任务书条款 → 源码路径 → 独立证据映射（不采信交付报告自述）；
2. 新增临时对抗脚本 `_p4c_adv_review_tmp.py`（验证后已删除），覆盖任务书 §11 八类反例及补充项；
3. 复跑实现者定向测试、全量 `pytest`、`ruff`、`mypy`（WSL Miniforge `base`）。

环境：`Linux 4.4.0-22621-Microsoft`（WSL1）；`/home/mabw/miniforge3/bin/conda run -n base`；禁止 Windows Python、联网、token、`_old/`、真实 connector。

## 2. 总判定

| 维度 | 结果 |
|---|---|
| 文件范围 / 无改 P4A·P4B / 无 research·connector 反向依赖 | 通过（静态） |
| 生产路径无 `os.rename` / `os.replace` / syscall-number fallback | 通过（静态 + 对抗） |
| WSL1 `renameat2(RENAME_NOREPLACE)` fail-closed | 通过（真实探测 `errno=22 EINVAL` + 对抗） |
| 实现者 27 项定向测试 | 27 passed |
| 全量 pytest / ruff / mypy | 全绿（见 §5） |
| 任务书 §11 独立对抗 | **1 项失败 → 初验不通过** |

**独立初验不通过。** 实现者自测与全量回归绿色不能掩盖 `verify_g1_release` 对祖先路径 TOCTOU 的合同缺口。返工后须由**未参与该轮实现**的全新会话复验。

## 3. 阻塞问题（须返工）

### P0-1：verify 期间祖先被替换为 symlink 后仍成功返回

- **现象**：在 `verify_g1_release` 执行过程中，将 release 的祖先目录替换为指向原内容的 symlink 后，验证**不抛错并成功返回** `VerifiedG1Release`。成功返回时，访问路径上已存在祖先 symlink，违反“root 与全部祖先无 symlink”与“验证期间祖先替换即失败”。
- **根因**：`verify_g1_release` 仅在入口调用一次 `_reject_ancestor_symlinks(root)`；结束时只复核 `root` 自身 `(st_dev,st_ino)` 与各 entry inode，**不再复核祖先 symlink/身份**。祖先被换成 symlink 后，release 目录 inode 可保持不变，故逃逸。
- **应遵循规则**：任务书 §8 第 1/8 款；总设计 §6.5 verifier 路径身份；“读取过程中对 directory/file identity 做前后快照；祖先、entry 或 inode 在验证期间替换即失败”。
- **最小复现**（独立对抗，已删临时文件）：
  1. 发布到 `…/mid/<release_id>`；
  2. monkeypatch `_parse_manifest_bytes`：解析后立刻 `shutil.move(mid, alt)` 并 `os.symlink(alt, mid)`；
  3. 继续 `verify_g1_release` → **未 raise**（期望 `G1_RELEASE_VERIFY_FAILED` 或 `G1_RELEASE_PATH_INVALID`）。
- **新增测试**：正式测试须包含“verify 中途祖先换 symlink / 祖先 inode 漂移”对抗；不得只测 entry symlink 或启动前祖先检查。
- **通过条件**：
  1. 上述复现必失败且错误码稳定脱敏；
  2. 成功返回前必须再次 `_reject_ancestor_symlinks`（或等价祖先身份前后快照比对）；
  3. 独立复验重跑该对抗通过；实现者原矩阵与全量回归仍绿。

代码锚点：

```951:964:src/quant/data/m3_release.py
def verify_g1_release(*, release: G1Release) -> VerifiedG1Release:
    """Strict final-directory verification; never mutates final."""
    try:
        rebuilt_release = G1Release(
            release_id=release.release_id,
            root=release.root,
            manifest_path=release.manifest_path,
            quality_path=release.quality_path,
        )
        root = rebuilt_release.root
        _reject_ancestor_symlinks(root)
        root_before = _dir_identity(root)
```

```1159:1164:src/quant/data/m3_release.py
        if _dir_identity(root) != root_before:
            raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
        for name, ident in file_idents.items():
            st = os.lstat(root / name)
            if (st.st_dev, st.st_ino) != ident:
                raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
```

## 4. 任务书 §11 对抗映射

| §11 要求 | 独立证据 | 结果 |
|---|---|---|
| primary table+manifest wholesale 自洽替换 | `test_adv_primary_wholesale_identity_rebind_still_rejected`（伪造 primary/release/quality/entry） | 通过（拒） |
| summary/detail/receipt 同时重绑 | `test_adv_summary_detail_receipt_simultaneous_rebind_rejected` | 通过（拒） |
| coercible dtype | 实现者已有；独立未重复 | 采信实现者覆盖 |
| 同 inode / 不同 path | `test_adv_inode_alias_via_hardlink_same_dev_rejected` | 通过（拒） |
| 并发方先创建空 final | 实现者 `test_empty_final_concurrent_not_overwritten` | 采信 |
| rename 成功后 output-root fsync 或 cleanup 失败 | `test_adv_post_rename_root_fsync_failure_not_success`；`test_adv_post_rename_cleanup_failure_not_success` | 通过（不伪成功） |
| strict JSON duplicate/BOM/非 canonical | 实现者已有；独立补 trailing newline + NaN | 通过（拒） |
| **ancestor 在 verify 中途替换** | `test_adv_ancestor_replaced_mid_verify` | **失败（未拒）→ P0-1** |
| `renameat2` 不可用且不得 fallback | 真实 `EINVAL`；`test_adv_renameat2_real_path_no_os_rename_fallback_on_einval`；源码无 `os.rename/replace/syscall` | 通过 |

补充独立项（均通过）：physical SHA 与 logical content SHA 分裂篡改；`price_limit_required_keys_sha256` 漂移；错误面无绝对路径 / `__cause__`；ctypes `renameat2` 静态无 syscall-number。

对抗汇总：**11 passed, 1 failed**（`test_adv_ancestor_replaced_mid_verify`），约 1256s。

## 5. 验证命令与真实结果

均经 `wsl.exe` → `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，`PYTHONPATH=src`，`/home/mabw/miniforge3/bin/conda run -n base`。

| 命令 | 结果 |
|---|---|
| 临时对抗 `_p4c_adv_review_tmp.py` | **1 failed, 11 passed**（见 §3/§4） |
| `python -m pytest -q tests/unit/test_m3_g1_release.py` | **27 passed**，721287 warnings，1995.49s |
| `python -m pytest -q` | **796 passed**，916412 warnings，2631.41s |
| `python -m ruff check src tests` | **All checks passed!** |
| `python -m mypy src` | **Success: no issues found in 79 source files** |

平台探测：`renameat2(..., RENAME_NOREPLACE=1)` 对空目录 → `rc=-1 errno=22 EINVAL`。本机**不能**完成真实 NOREPLACE 目录原子提交；生产路径映射 `G1_RELEASE_PUBLISH_UNSUPPORTED`，对抗确认**无** `os.rename/os.replace` fallback。测试夹具 `publish_capable` 在探测失败时注入仅测试用 no-clobber，**不得**被误读为生产已验证真实原子 commit。

## 6. 已核对通过的合同面（摘要）

以下不构成“初验通过”，仅记录未被本轮对抗打穿的面：

- 公开 API / 值对象形状与任务书 §3 一致；包根导出齐全；
- `prepare_g1_release` 从原输入重建 P4A/P4B；无自报 candidate/audit 入口；`G1PreparedRelease` 重算 identity/quality；
- release ID envelope 与 quality hash 不进入 release ID；
- strict JSON reader：BOM/duplicate/非 canonical/bool-as-int；canonical bytes 比对；
- 17 artifact registry；Parquet exact dtype（含 coercible 拒绝）；primary identity 经 `_primary_candidate_key` + required keys 重算；
- final 18 entry、`st_nlink`、hardlink/inode 别名、FIFO/hidden；
- 空/损坏 final 不覆盖；post-rename fsync/cleanup 失败不伪成功；
- 错误码稳定字符串，观察面无绝对路径泄露；
- 文件范围未越权修改 domain / P4A / P4B。

## 7. P2 观察（不单独阻塞，返工时可顺带）

- 实现者 `test_fsync_fault_and_primary_priority` 从写入起即失败 fsync，未覆盖“rename 成功后的 root fsync”；独立对抗已补，建议正式化。
- `_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)` 在标志缺失时静默退化为无 nofollow；Linux/WSL 现有标志，但建议缺失时 fail-closed。
- 交付报告将 detail/summary 闭包主要归因于 happy path；独立已补对抗，返工后正式测试应保留。

## 8. 处置

**退回外部实现 Agent。** 最小修复范围：

1. 修复 P0-1：`verify_g1_release`（及依赖它的 publish 预验/复用路径）在成功返回前强制祖先无 symlink / 祖先身份未漂移；
2. 将 §3 最小复现升级为 `tests/unit/test_m3_g1_release.py` 正式对抗；
3. 自测定向 + 全量 pytest / ruff / mypy；更新交付报告，状态仍为“待独立复验”，不得宣称 Gate 通过。

主 Agent 终验不得在本报告结论下启动。P4C / B4 / G1 / M3 / Gate 均保持未关闭；不得启动 G2A。

## 9. 环境限制声明

本宿主为 WSL1：真实目录 `RENAME_NOREPLACE` 返回 `EINVAL`。本初验验证了 fail-closed 与无 fallback，**未**在支持内核上验证真实原子 commit 成功路径。即使 P0-1 修复后复验通过，主验仍应在支持 `renameat2(RENAME_NOREPLACE)` 的 WSL2/Linux 上复核真实 commit。
