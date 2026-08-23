# M3 G1-P4C：独立初验一次返工交付报告

日期：2026-07-15  
角色：原外部实现 Agent（第 2 步返工）  
状态：**待独立复验**（不得宣布 P4C/B4/G1/M3/Gate 通过）  
返工任务书：[`M3_G1_P4C独立初验一次返工任务单.md`](M3_G1_P4C独立初验一次返工任务单.md)  
失败证据：[`M3_G1_P4C不可变发布独立初验报告.md`](M3_G1_P4C不可变发布独立初验报告.md)

## 1. 修改文件（白名单）

| 文件 | 动作 |
|---|---|
| `src/quant/data/m3_release.py` | 修复 P0-1：祖先身份入口快照 + 成功前终验 |
| `tests/unit/test_m3_g1_release.py` | 新增两个从公开 `verify_g1_release` 进入的对抗 |
| `docs/M3_G1_P4C独立初验一次返工交付报告.md` | 本报告 |

未修改 P4A/P4B、domain Schema、包导出、配置、路线图、原交付/初验报告；未处理初验报告 §7 非阻塞观察。

## 2. P0-1：现象—根因—规则—复现—新增测试—结果

| 项 | 内容 |
|---|---|
| **现象** | `verify_g1_release` 入口通过后，中途把祖先换成指向原内容的 symlink（或换成新真实目录），仍成功返回。 |
| **根因** | 入口只调一次 `_reject_ancestor_symlinks`；结束只比 release root / entry inode，未保存并复核祖先物理身份。 |
| **应遵循规则** | 返工任务书 §2；原任务书 §8 第 1/8 款；总设计 §6.5；成功返回前祖先、root、entry 身份均不得漂移。 |
| **最小复现** | 发布到 `…/mid/<release_id>`；monkeypatch `_parse_manifest_bytes` 后 `move(mid→alt)` + `symlink(alt→mid)`，或换新真实 `mid` 并移回 release；期望拒。 |
| **修复** | 读 artifact 前 `_snapshot_ancestor_identities(root)`（`root.parent`→FS 根，文本绝对路径 + `lstat`，记录 `(st_dev,st_ino)`）；成功返回前与 root/entry 终验同门槛调用 `_assert_ancestor_identities_unchanged`。中途漂移 → 脱敏 `G1_RELEASE_VERIFY_FAILED`；入口非法仍 `G1_RELEASE_PATH_INVALID`。不用 `resolve()`，不增 rename fallback。 |
| **新增测试** | `test_verify_mid_ancestor_replaced_with_symlink_rejected`；`test_verify_mid_ancestor_real_dir_inode_drift_rejected`（均从公开 verify 进入，并断言 `str(exc)==code`、`__cause__ is None`、无临时绝对路径）。 |
| **结果** | 两对抗均拒绝；定向/全量/ruff/mypy 见 §3。 |

## 3. 验证命令与结果

环境：`wsl.exe` → `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，`/home/mabw/miniforge3/bin/conda run -n base`。

| 命令 | 结果 |
|---|---|
| `python -m pytest -q tests/unit/test_m3_g1_release.py::test_verify_mid_ancestor_replaced_with_symlink_rejected tests/unit/test_m3_g1_release.py::test_verify_mid_ancestor_real_dir_inode_drift_rejected` | **2 passed**，240.05s |
| `python -m pytest -q tests/unit/test_m3_g1_release.py` | **29 passed**，2062.02s |
| `python -m pytest -q` | **798 passed**，987118 warnings，2882.95s |
| `python -m ruff check src tests` | **All checks passed!** |
| `python -m mypy src` | **Success: no issues found in 79 source files** |

定向：

```text
29 passed, 791993 warnings in 2062.02s (0:34:22)
```

全量：

```text
798 passed, 987118 warnings in 2882.95s (0:48:02)
```

## 4. 明确未做

- 初验报告 §7：`_O_NOFOLLOW` 细化、post-rename fsync/cleanup 对抗正式化、支持内核上真实 commit 成功路径。
- 扩大发布实现、`os.rename/os.replace` fallback、修改非白名单文件。
- 未创建复验报告；未宣称 Gate / P4C / B4 / G1 / M3 通过。

## 5. 交接

请未参与本轮实现与上轮初验的全新外部会话撰写
`docs/M3_G1_P4C独立初验一次返工独立复验报告.md`；复验至少重做两个祖先漂移反例，不能只复跑正式测试。
