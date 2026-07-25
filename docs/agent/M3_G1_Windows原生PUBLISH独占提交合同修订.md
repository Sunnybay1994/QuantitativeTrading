# M3 G1：Windows 原生 PUBLISH 独占提交合同修订

- 日期：2026-07-25
- 用户授权：**暂不考虑 WSL2/ext4，先在 Windows 原生环境推进**
- **不宣称** Linux Gate / Codex 终验 / ext4 不可变发布等价

## 背景

正式 `publish_g1_release` 最终提交依赖 Linux `renameat2(RENAME_NOREPLACE)`。  
Windows / WSL1 无该 syscall → `G1_RELEASE_PUBLISH_UNSUPPORTED`，阻塞后续 G2A。

## 修订

在 `os.name == "nt"` 时：

1. 最终目录提交使用 Win32 **`MoveFileExW(src, dst, flags=0)`**  
   - 目标不存在：移动成功  
   - 目标已存在：`ERROR_ALREADY_EXISTS (183)` → `G1_RELEASE_CONCURRENT_PUBLISH`
2. **目录 fsync**：NTFS 无可靠 directory-fd fsync；文件写入已在 `_exclusive_write_bytes` 中 `os.fsync`；Windows 上 `_fsync_directory` 仅校验路径为目录后返回  
3. **二进制写入**：`_exclusive_write_bytes` 必须带 `os.O_BINARY`（Windows 缺省文本模式会破坏 parquet/json 字节）  
4. **禁止** `os.rename` / `os.replace` 作为 Linux 回退；静态测试继续禁止二者

Linux / 支持 `renameat2` 的路径不变。

## 身份与宣称边界

- Windows 上验真得到的 `VerifiedG1Release` 仅用于 **Windows 原生推进轨**（G2A…）
- 不得写入「Linux ext4 Gate 通过」或降低既有 Linux 发布合同
- 日后 WSL2/ext4 就绪时，仍须在目标 FS 上重新正式 publish 并主验

## 验证

- 定向单测 `test_m3_g1_release.py`（含 MoveFileEx / 禁止 os.rename）
- 正式 CLI：`python -m quant.research.m3.run_g1 ... publish`
