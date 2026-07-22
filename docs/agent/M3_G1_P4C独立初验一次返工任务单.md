# M3 G1-P4C：独立初验一次返工任务单

日期：2026-07-15  
状态：主 Agent 已复核 P0-1；退回原外部实现会话返工  
原任务：[`M3_G1_P4C不可变发布外部闭环任务单.md`](M3_G1_P4C不可变发布外部闭环任务单.md)  
失败证据：[`M3_G1_P4C不可变发布独立初验报告.md`](M3_G1_P4C不可变发布独立初验报告.md)

## 1. 唯一阻塞项 P0-1

- **现象**：`verify_g1_release` 入口检查通过后，把 release 的祖先目录移动到另一位置，再在原路径放置指向它的
  symlink；验证仍成功返回。
- **根因**：入口只执行一次 `_reject_ancestor_symlinks(root)`，结束仅比较 release root 与 entry inode；没有保存并
  复核从 release root 父目录到文件系统根的祖先身份。
- **被破坏的不变量**：成功返回必须证明整条访问路径在验证前后均无 symlink，且祖先、release root、所有 entry
  的物理身份未漂移。下游不得拿到经过路径重绑定的“verified”对象。
- **应遵循规则**：原任务书 §8 第 1/8 款；总设计 §6.5；`AGENTS.md` 的 fail-closed 与文件身份规则。

## 2. 最小修复合同

只允许修改：

1. `src/quant/data/m3_release.py`；
2. `tests/unit/test_m3_g1_release.py`；
3. 新建 `docs/M3_G1_P4C独立初验一次返工交付报告.md`。

不得修改 P4A/P4B、domain Schema、包导出、配置、路线图、原交付/初验报告或其他测试。

实现必须：

1. 在 `verify_g1_release` 开始读取 artifact 前，对 `root` 的每一级真实祖先（至少从 `root.parent` 到文件系统根）按
   文本绝对路径记录 `(st_dev, st_ino)`；任何 symlink、非目录或 `lstat` 失败均 fail-closed；
2. 成功构造返回值前，再按相同路径逐级 `lstat`，要求仍是非 symlink 目录且身份 tuple 与入口快照逐项相等；祖先
   增删、替换、改为 symlink 或身份变化一律拒绝；
3. 祖先终验必须与现有 root/entry 终验处在同一成功前门禁内，不能只在 reader 某个分支或 publisher 中检查；
4. 中途祖先漂移统一映射为脱敏 `M3ReleaseError("G1_RELEASE_VERIFY_FAILED")`，无绝对路径、无 `__cause__`；入口即
   非法的现有路径失败语义不得被无关改变；
5. 不用 `resolve()` 跟随 symlink，不缓存字符串后跳过物理检查，不增加 `os.rename/os.replace` 或任何 fallback；
6. 保留 WSL1 `renameat2` 不支持时的既有 fail-closed 行为，不借本返工扩大发布实现。

仅在结束处再次调用 `_reject_ancestor_symlinks` **不充分**：它能发现 symlink，却不能证明祖先被替换成另一个真实目录
时的 inode 漂移。必须做入口/出口祖先身份快照比较。

## 3. 正式回归测试

把独立初验最小复现升级为正式测试，至少覆盖：

1. **中途改 symlink**：在 manifest 已开始解析后移动某一级祖先，并在原路径创建指向旧内容的 symlink；
   `verify_g1_release` 必须以 `G1_RELEASE_VERIFY_FAILED` 拒绝；
2. **中途换真实目录 / inode 漂移**：把祖先替换为新的真实目录，同时保持可继续读取或在适当 hook 后触发终验；
   即使没有 symlink也必须拒绝；
3. 两个错误对象的 `str(exc)` 只能是稳定 code，`__cause__ is None`，traceback/消息不得包含临时绝对路径；
4. 正常 verify、现有 entry/root TOCTOU、publisher 复用与 WSL1 unsupported 测试继续通过。

测试不得只直接调用新 helper；必须从公开 `verify_g1_release` 证明成功返回前门禁生效。允许用 monkeypatch 在确定的
解析/读取 hook 触发替换，测试结束必须清理自己创建的路径。

## 4. 本轮不扩张项

以下保留在原初验报告 §7，当前不阻塞且本返工不要求处理：

- `_O_NOFOLLOW` 常量缺失时的更细 fail-closed；
- 把独立的 post-rename root fsync/cleanup 对抗全部正式化；
- 在支持 `RENAME_NOREPLACE` 的 WSL2/Linux 上做真实 commit 成功路径验证。

## 5. 自测、报告与复验

原实现会话完成后运行：

```bash
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q tests/unit/test_m3_g1_release.py
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check src tests
/home/mabw/miniforge3/bin/conda run -n base python -m mypy src
```

交付报告逐项写明 P0-1 的“现象—根因—规则—复现—新增测试—结果”，状态只能是“待独立复验”。完成后必须交给
一个未参与实现和上轮初验的全新外部会话复验；复验至少重做两个祖先漂移反例，不能只复跑正式测试。复验报告为
`docs/M3_G1_P4C独立初验一次返工独立复验报告.md`。
