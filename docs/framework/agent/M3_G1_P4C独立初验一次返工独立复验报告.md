# M3 G1-P4C：独立初验一次返工独立复验报告

日期：2026-07-15  
角色：全新外部独立复验 Agent（非 fast `cursor-grok-4.5-high`；未参与 P4C 原实现、上轮初验或本轮返工）  
复验范围：仅 [`M3_G1_P4C独立初验一次返工任务单.md`](M3_G1_P4C独立初验一次返工任务单.md) **P0-1**，并确认未破坏原 P4C 合同面  
结论：**独立复验通过，可交主 Agent 终验**

本报告**不得**宣布 P4C / B4 / G1 / M3 / 任一 Gate 通过。  
交付报告 [`M3_G1_P4C独立初验一次返工交付报告.md`](M3_G1_P4C独立初验一次返工交付报告.md) **仅作交接索引，不作证据**。

## 1. 审查与方法

只读对照：

- `AGENTS.md`、`karpathy-guidelines.md`
- 返工任务单 P0-1 / §2–§3；原任务单 §8 第 1/8 款；原独立初验报告 P0-1
- `src/quant/data/m3_release.py`（`verify_g1_release`、`_snapshot_ancestor_identities`、`_assert_ancestor_identities_unchanged`）
- `tests/unit/test_m3_g1_release.py` 正式祖先对抗与既有矩阵

独立证据（非交付自述）：

1. 源码门禁位置与错误码映射；
2. 临时对抗 `_p4c_p0_1_reverify_tmp.py`（**验证后已删除**）：hook/时点与实现者正式测试不同；
3. 正式定向 / 全量 pytest / ruff / mypy（WSL Miniforge `base`）。

环境：`Linux 4.4.0-22621-Microsoft`（WSL1）；`/home/mabw/miniforge3/bin/conda run -n base`；`PYTHONPATH=src`。未用 `py312` / Windows Python；未联网；未读 token/TOML/`_old/`；未处理返工任务单 §4 非阻塞项；未改生产代码或正式测试。

## 2. 总判定

| 项 | 结果 |
|---|---|
| P0-1 入口祖先身份快照（文本绝对路径 + `(st_dev,st_ino)`，symlink/非目录/lstat 失败 fail-closed） | **通过**（源码 + 对抗） |
| 成功返回前与 root/entry 同一门禁复核祖先 | **通过**（源码顺序） |
| 中途祖先→symlink / 中途真实目录 inode 漂移 → 脱敏 `G1_RELEASE_VERIFY_FAILED` | **通过**（独立 hook 对抗） |
| 非仅检查 root/symlink；祖先层级 inode 漂移仍拒 | **通过**（grandparent 对抗） |
| 入口非法仍 `PATH_INVALID`；happy verify；publisher 复用；entry hardlink 别名仍拒 | **通过** |
| 生产路径无 `os.rename`/`os.replace`；WSL1 `renameat2` fail-closed | **通过** |
| 正式 29 项 + 全量 798 + ruff + mypy | **全绿** |

**独立复验通过，可交主 Agent 终验。**

## 3. 源码核对（P0-1）

`verify_g1_release`：

1. 入口：`_reject_ancestor_symlinks(root)` 后，读 artifact **前**调用  
   `_snapshot_ancestor_identities(root, code="G1_RELEASE_PATH_INVALID")`；
2. `_snapshot_ancestor_identities`：自 `path.parent` 文本到 FS 根，逐级 `os.path.abspath` + `os.lstat`，记录  
   `(abs_text, (st_dev, st_ino))`；symlink / 非目录 / `OSError` → 给定 `code`；**不**调用 `.resolve(`；
3. 成功构造 `VerifiedG1Release` **前**，与 `_dir_identity(root)`、entry inode 终验同一门槛调用  
   `_assert_ancestor_identities_unchanged(..., code="G1_RELEASE_VERIFY_FAILED")`；
4. 中途漂移统一 `G1_RELEASE_VERIFY_FAILED` 且 `from None`；入口祖先非法保持 `PATH_INVALID`。

正式测试从公开 `verify_g1_release` 覆盖 symlink 与真实目录 inode 漂移，并断言 `str(exc)==code`、`__cause__ is None`、无临时绝对路径。

## 4. 独立对抗（实现者未使用的 hook/时点）

实现者正式测试 hook：`_parse_manifest_bytes`。独立临时脚本改用：

| 对抗 | hook / 手法 | 期望 | 结果 |
|---|---|---|---|
| a 中途祖先→symlink | `_parse_quality_bytes` 后 `move(mid→alt)` + `symlink` | `G1_RELEASE_VERIFY_FAILED`，脱敏、无 cause | **拒（通过）** |
| b 中途真实目录 inode 漂移 | `_release_id_from_parts` 后换新 `mid`（无 symlink） | 同上 | **拒（通过）** |
| c grandparent inode 漂移 | `_parse_summary_bytes` 后替换 `grand` | 同上（非仅 mid/root） | **拒（通过）** |
| d 入口祖先已是 symlink | verify 前放置 | `G1_RELEASE_PATH_INVALID` | **通过** |
| e entry hardlink 别名 | quality→manifest hardlink | `VERIFY_FAILED` | **通过** |
| f 静态：快照自 parent→根；终验与 root/entry 同门槛；无 `.resolve(` | `inspect` + 源码 | 顺序成立 | **通过** |
| g 生产无 `os.rename`/`os.replace` | 读 `m3_release.py` | 无 | **通过** |
| h happy verify + publisher 零写复用 | 公开 API | 成功 | **通过** |
| i `renameat2` unsupported 无 fallback | monkeypatch → `PUBLISH_UNSUPPORTED` | 无 final | **通过** |

```text
9 passed, 439080 warnings in 1155.62s (0:19:15)
```

临时文件已删除，未保留生产/正式测试改动。

## 5. 正式回归与静态检查

均经 `wsl.exe` → `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，`/home/mabw/miniforge3/bin/conda run -n base`。

| 命令 | 结果 |
|---|---|
| 独立对抗 `_p4c_p0_1_reverify_tmp.py` | **9 passed**，1155.62s |
| `pytest -q` 两条正式 P0-1 | **2 passed**，239.49s |
| `pytest -q tests/unit/test_m3_g1_release.py` | **29 passed**，2090.04s |
| `pytest -q` | **798 passed**，987118 warnings，2901.14s |
| `ruff check src tests` | **All checks passed!** |
| `mypy src` | **Success: no issues found in 79 source files** |

真实 `renameat2(RENAME_NOREPLACE)` 探测：`rc=-1 errno=22 EINVAL`（WSL1）。

## 6. 原 P4C 合同面（本轮抽查，未宣称 Gate）

在 P0-1 修复前提下，未观察到下列合同被破坏：

- 成功返回前祖先 + root + entry 身份同门槛；
- 入口路径非法与中途 verify 漂移错误码分离；
- publisher 复用 / 空损坏 final 不覆盖（正式矩阵仍绿）；
- 生产无 `os.rename`/`os.replace` fallback；WSL1 unsupported fail-closed。

未扩张处理返工任务单 §4 / 原初验 §7 非阻塞项。

## 7. 限制（必须保留）

本宿主为 **WSL1**：真实目录 `RENAME_NOREPLACE` 返回 `EINVAL`。本复验确认 fail-closed 与无 fallback，**未**在支持内核上验证真实原子 commit 成功路径。主验仍应在支持 `renameat2(RENAME_NOREPLACE)` 的 WSL2/Linux 上复核真实 commit。测试夹具 `publish_capable` 的注入 no-clobber **不得**误读为生产已验证真实 NOREPLACE 成功。

## 8. 处置

**独立复验通过，可交主 Agent 终验。**  
不宣称 P4C / B4 / G1 / M3 / Gate 通过；不得据此关闭 Gate 或启动 G2A。
