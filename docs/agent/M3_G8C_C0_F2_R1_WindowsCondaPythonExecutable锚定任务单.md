# M3 G8C-C0 F2 R1：Windows Conda Python Executable 锚定任务单

日期：2026-08-11

状态：**工程主验 PASS；允许恢复 F0 R3；C0/C1 与 Linux ext4 Gate 仍未通过**

## 1. 现象与根因

F0 R2 已通过 public G1（18 文件）与 snapshot，随后真实 `materialize_qlib_provider` 在 preflight 稳定失败：
`D:\Miniforge3\envs\m3chain312\python.exe` 是 conda 合法 hardlink，`st_nlink=2`；production `provider._read_regular`
对所有文件一律要求 `st_nlink==1`，同时又要求传入路径 resolve 后 exact 等于 `sys.executable`，因此正常 conda 环境无合法路径。

本包只修正当前进程解释器的 Windows 锚定；不改变 provider identity、dump tool、snapshot、artifact 或 receipt 合同。

## 2. 安全不变量

1. 通用 `_read_regular` 完全保持 `st_nlink==1`；qlib dump script、snapshot/provider 文件、manifest/receipt 不得放宽。
2. 特例只允许 `os.name == "nt"` 且 caller `python_executable` 与 `Path(sys.executable)`：
   - exact `Path`/absolute/resolve/samefile；所有祖先与 leaf 无 symlink/junction/reparse；leaf 为 regular；
   - `st_nlink >= 1`，不得以 nlink 值代替实体校验；文件 size>0；
   - 在任何 provider 输出写入前用 Windows `CreateFileW` 打开真实 leaf，desired access 至少 read，share mode **仅允许 read**，
     禁止其他 handle 写入或删除，`OPEN_EXISTING | FILE_FLAG_OPEN_REPARSE_POINT`；
   - 用 `GetFileInformationByHandle` 将 volume/file-index/size/link-count/attributes 与 path lstat/当前 `sys.executable`
     绑定，拒绝 reparse、实体漂移；持有 handle 覆盖 preflight、`subprocess.run`、provider structure inspection 与 manifest 写入；
   - 结束前重新核对 handle/path/current executable 为同一实体且 metadata/bytes SHA-256 未漂移，然后关闭 handle；任何失败回滚
     到既有 provider 错误/输出边界，cause/context 脱敏。
3. 非 Windows 路径维持现有单链接行为；不得借本包改变 Linux/WSL Gate。
4. 解释器锚定不得成为 public capability/API，不导出 handle/key/identity，不复制 `_artifact_publication` 私有实现；只可在
   `provider.py` 内实现最小私有 context manager。
5. 不得通过复制 `python.exe`、修改 `sys.executable`、monkeypatch `_read_regular` 或跳过 subprocess 解决。

## 3. 必测反例

- Windows `m3chain312` actual `sys.executable`（nlink=2）通过 preflight 并能完成一个 focused provider materialization；
- 解释器另建第三 hardlink后，guard 内从其他 hardlink尝试写入、truncate、replace/delete current path均被系统阻止或在最终复核拒绝，
  且 provider输出不宣称成功；owned hostile link精确清理；
- 同 bytes copy、symlink/junction/reparse、different executable、relative/alias、caller path在 guard前后替换均拒绝；
- dump tool hardlink仍拒绝，证明通用 `_read_regular` 未放宽；
- hostile WinAPI/subprocess/identity异常稳定脱敏；timeout/failure/成功均关闭handle，无句柄泄漏；
- development/formal provider既有定向回归，Windows `m3chain312` 与 WSL base静态/邻接；WSL不要求nlink>1成功。

## 4. 白名单

- `src/quant/research/m3/provider.py`
- `tests/unit/test_m3_provider_materialization.py`
- 更新本任务状态
- 唯一交付报告 `docs/agent/M3_G8C_C0_F2_R1_WindowsCondaPythonExecutable锚定交付报告.md`
- 独立初验只写 `docs/agent/M3_G8C_C0_F2_R1_WindowsCondaPythonExecutable锚定独立复验报告.md`

禁止修改 F0 support/integration、其他 production/tests/config/docs、环境、依赖；禁止联网/add/commit。

## 5. 验证与停止条件

Windows `m3chain312`：focused provider materialization、Ruff、mypy、cold import；Windows base只作邻接反馈。WSL base：既有
provider focused/静态兼容，DrvFS非ext4。不得机械跑全量。

若 Windows no-share-write/delete handle 使子解释器无法正常启动；Python/conda hardlink实体无法用公开 Win32 identity稳定绑定；
需要放宽通用artifact单链接规则、修改public API/schema/receipt/config；或需要系统SDK/依赖变更，立即停止。

F2只可声明“Windows current conda Python executable锚定工程合同PASS”。F2主验PASS后，F0 R3复用现有support继续
provider→backtest_plan→resolver；不直接宣称F0/C0/C1或Linux Gate通过。

## 6. 主 Agent 最终验收（2026-08-11）

结论：**PASS，仅限 Windows current conda Python executable 锚定工程合同**。

- 外部实现与未参与实现的全新外部独立初验均 PASS；职责分离成立。
- 主验在 `m3chain312` 复跑 focused provider：`19 passed, 3 skipped`；Ruff、mypy、diff-check 全绿。
- `sys.executable` 实测 `st_nlink=2`；专用 Windows handle 覆盖 preflight、子进程、structure inspection、manifest
  写入及最终身份/hash复核。独立反例确认 hardlink 写/截断/删除被阻止或最终拒绝，句柄无泄漏。
- 通用 `_read_regular` 仍 exact 要求 `st_nlink==1`；dump tool、snapshot/provider、manifest/receipt 均未放宽。

本结论只解锁 F0 R3 复用既有 support 继续真实链；不解锁 C0/C1，也不替代 Linux ext4 Gate。
