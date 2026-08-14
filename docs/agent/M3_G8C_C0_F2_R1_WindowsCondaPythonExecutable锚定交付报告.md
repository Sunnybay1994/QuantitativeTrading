# M3 G8C-C0 F2 R1：Windows Conda Python Executable 锚定交付报告

日期：2026-08-11  
角色：外部实现 Agent（`cursor-grok-4.5-high`，全新会话）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
解释器：`D:\Miniforge3\envs\m3chain312\python.exe`（actual `st_nlink=2`）  
任务单：[`M3_G8C_C0_F2_R1_WindowsCondaPythonExecutable锚定任务单.md`](M3_G8C_C0_F2_R1_WindowsCondaPythonExecutable锚定任务单.md)  
结论：**Windows current conda Python executable 锚定工程合同自测 PASS；不宣称 F0/C0/C1 或 Linux Gate PASS；待独立初验**

## 1. 白名单与实际改动

| 路径 | 处置 |
|---|---|
| `src/quant/research/m3/provider.py` | 新增私有 `_hold_python_executable` / Win32 no-share-write/delete handle 锚定；通用 `_read_regular` 仍 `st_nlink==1` |
| `tests/unit/test_m3_provider_materialization.py` | focused nlink=2 materialize、hostile third hardlink、dump-tool hardlink、same-bytes/relative/symlink、handle close |
| 本交付报告 | 新增 |
| 任务单状态 | 更新为待独立初验 |

未改 F0 support/integration、其他 production/tests/config/docs、依赖或环境；未 add/commit；未联网。

## 2. 冻结实现要点

1. 特例仅 `os.name == "nt"` 且 caller 为绝对路径，且 `resolve`+`samefile` 等于 `Path(sys.executable)`。
2. 祖先/leaf 无 symlink/junction/reparse；leaf regular；`st_nlink >= 1`；size>0。
3. `CreateFileW(GENERIC_READ, FILE_SHARE_READ only, OPEN_EXISTING|FILE_FLAG_OPEN_REPARSE_POINT)`，持有覆盖 preflight→subprocess→inspect→manifest；`GetFileInformationByHandle` 绑定 volume/file-index/size/nlink/attributes 与 path lstat；handle 内 SHA-256 首尾复核；失败/成功均关闭 handle。
4. 非 Windows / 非 current exe 仍走 `_read_regular`；dump tool / artifact 单链接合同未放宽。
5. 相对路径、同字节 copy、symlink、不同 executable、dump-tool hardlink 均拒绝。

## 3. 停止条件探针（未触发停止）

| 条件 | 结果 |
|---|---|
| no-share-write/delete handle 阻断子解释器 | **未触发**：持 handle 下 `subprocess.run([sys.executable, ...])` rc=0 |
| Win32 identity 无法稳定绑定 | **未触发**：`st_ino`==file-index；size/nlink 一致；`st_dev&0xFFFFFFFF`==volume_serial |
| 需放宽通用 artifact 单链接 / 改 public API/schema/receipt/config | **未触发** |
| 需系统 SDK/依赖变更 | **未触发**（仅 stdlib `ctypes`） |

## 4. 验证证据

| 检查 | 结果 |
|---|---|
| Windows `m3chain312` focused `test_m3_provider_materialization.py` | **19 passed, 3 skipped**（含 nlink=2 materialize + hostile） |
| Windows `m3chain312` Ruff / mypy / cold import | PASS / PASS / PASS（`PYTHONPATH=src`） |
| Windows base 邻接同文件 | **17 passed, 5 skipped**（nlink≥2 用例 skip） |
| WSL base focused + Ruff / mypy / cold import | **19 passed, 3 skipped**；静态 PASS；`nlink=1`，不要求 nlink>1 成功 |
| `_read_regular(sys.executable)` on m3chain312 | 仍 `ValueError("regular unlinked file required")` |

命令摘要（Windows m3chain312）：

```text
$env:PYTHONPATH="<worktree>\src"
D:\Miniforge3\envs\m3chain312\python.exe -m pytest -q tests/unit/test_m3_provider_materialization.py
D:\Miniforge3\envs\m3chain312\python.exe -m ruff check src/quant/research/m3/provider.py tests/unit/test_m3_provider_materialization.py
D:\Miniforge3\envs\m3chain312\python.exe -m mypy src/quant/research/m3/provider.py tests/unit/test_m3_provider_materialization.py
```

## 5. 禁止项自检

| 项 | 本轮 |
|---|---|
| 放宽通用 `_read_regular` / artifact 单链接 | 未做 |
| 复制 `_artifact_publication` 私有实现 / 导出 handle API | 未做（provider 内最小私有 CM） |
| 复制 python.exe / 改 `sys.executable` / monkeypatch `_read_regular` | 未做 |
| 修改 F0 support/integration / 其他代码/配置/依赖 | 未做 |
| add/commit / 联网 | 未做 |
| 宣称 F0/C0/C1/Gate PASS | **未宣称** |

## 6. 给独立初验

1. 只读核对白名单 diff 与 `_read_regular` 仍 `st_nlink==1`。
2. 在 `m3chain312` 复跑 focused provider 测试与静态检查（需 `PYTHONPATH=src` 或等价 editable）。
3. 追加实现者未用的对抗性反例（例如 guard 中途替换 path 实体、junction 祖先、WinAPI 异常脱敏）。
4. 唯一报告：`docs/agent/M3_G8C_C0_F2_R1_WindowsCondaPythonExecutable锚定独立复验报告.md`。
