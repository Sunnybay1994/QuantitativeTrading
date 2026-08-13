# M3 G8C-C0 F2 R1：Windows Conda Python Executable 锚定独立复验报告

日期：2026-08-11  
角色：全新外部独立初验 Agent（未参与 F2 实现）  
模型：`cursor-grok-4.5-high`  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
解释器：`D:\Miniforge3\envs\m3chain312\python.exe`（独立实测 `st_nlink=2`）  
结论：**PASS**（仅「Windows current conda Python executable 锚定工程合同」；**非** F2 主验、**非** F0/C0/C1、**非** Linux Gate）

依据：`AGENTS.md`、`.ai/README.md` / `.ai/review_checklist.md` / `.ai/workflows/multi_agent_delivery.md`；  
任务单 [`M3_G8C_C0_F2_R1_WindowsCondaPythonExecutable锚定任务单.md`](M3_G8C_C0_F2_R1_WindowsCondaPythonExecutable锚定任务单.md)；  
交付报告 [`M3_G8C_C0_F2_R1_WindowsCondaPythonExecutable锚定交付报告.md`](M3_G8C_C0_F2_R1_WindowsCondaPythonExecutable锚定交付报告.md)。

本会话对 `provider.py` / 实现测试 / 环境 / 任务单 / 交付报告 **严格只读**；未改 production/tests/config/依赖/conda 环境；未联网；未 `git add` / `commit`。仓库内本角色唯一写入：**本独立复验报告**（对抗探针为只读会话临时 `.tmp-g8c-c0-f2-r1-*` 证据，不进入白名单交付）。

## 1. 结论边界

| 可声明 | 不可声明 |
|---|---|
| Windows current conda Python executable 锚定工程合同独立初验 **PASS** | F2 主验已通过 |
| 通用 `_read_regular` 仍强制 `st_nlink==1` | 已放宽 artifact/dump-tool 单链接 |
| `m3chain312` nlink=2 可完成 focused materialize | F0 R3 / C0 / C1 通过 |
| WSL base 既有 provider focused/静态兼容（nlink=1） | Linux ext4 Gate / 发布终验通过 |

## 2. 只读合同核对（源码）

| 不变量 | 证据 | 结论 |
|---|---|---|
| 通用 `_read_regular` 仍 `st_nlink != 1` → 拒绝 | `provider.py` L1067–1075；独立调用 `_read_regular(sys.executable)` → `ValueError("regular unlinked file required")` | 未放宽 |
| Windows 特例仅 exact current `sys.executable` | `_is_windows_current_python_executable` 要求 `os.name=="nt"` + 绝对路径 + `_require_current_python_executable`（`resolve` 路径相等 **且** `samefile`） | 满足 |
| hardlink 别名路径（同 inode、异 resolve）拒绝 | ADV3b：`samefile=True` 但路径不等 → `provider Python executable drift` / `DEVELOPMENT_PROVIDER_INPUT_INVALID` | 满足 |
| `CreateFileW` share **仅** `FILE_SHARE_READ(0x1)` | L934–957：无 `FILE_SHARE_WRITE/DELETE`；`OPEN_EXISTING\|FILE_FLAG_OPEN_REPARSE_POINT` | 满足 |
| handle 覆盖完整 materialize | `_materialize` 整体包在 `with _hold_python_executable(...)`（preflight→subprocess→inspect→manifest） | 满足 |
| 前后 identity/hash | open：volume/file-index/size/nlink/attrs + handle SHA-256；exit 成功路径 `_verify_windows_current_python_anchor` 再核 | 满足 |
| 全路径关闭 handle | open 失败 `except` 关闭；CM `finally` 关闭；ADV7/8/10 泄漏探针均可再 `os.link` | 满足 |
| 失败脱敏 | `@_boundary(... ) from None`；ADV6 注入含 path/handle 的 `OSError` → 对外仅稳定错误码 | 满足 |
| 非导出 | 私有 `_hold_*` / Win32 helpers；未进 `m3.__init__`；未复制 `_artifact_publication` | 满足 |
| 白名单 | dirty 仅 `provider.py` + `test_m3_provider_materialization.py` + 任务/交付文档 | 满足 |

## 3. 实现者未使用的对抗反例

临时探针：`.tmp-g8c-c0-f2-r1-indep-adversarial.py`（及 alias/junc 补充）；结果摘要 `.tmp-g8c-c0-f2-r1-indep-adv-win*.txt`。

| ID | 反例（实现测试未覆盖或未组合） | 结果 |
|---|---|---|
| ADV0 | 直接 `_read_regular(m3chain312 python.exe)`（nlink=2） | **PASS** 仍拒绝 |
| ADV1 | guard 内第三 hardlink：写/truncate/delete current+other；`os.replace` 他链→current | 写/truncate/delete **系统阻止**；`replace` 偶发成功但最终复核拒绝且 **不宣称成功** → **PASS** |
| ADV2 | 同 bytes copy 作为 `python_executable` | **PASS** 拒绝且未跑 dump |
| ADV3 | leaf symlink alias | **SKIP**（WinError 1314 无建链特权）；由 ADV3b/ADV4/ADV4b 覆盖 alias/reparse |
| ADV3b | 同卷 hardlink 别名路径（samefile 但 resolve 不等） | **PASS** 拒绝 |
| ADV4 | junction 祖先 + 同卷 hardlink leaf | **PASS** 拒绝 |
| ADV4b | junction 使 `resolve()` **恰好等于** `sys.executable`（`_is_windows_current=True`） | **PASS**；`_require_no_reparse_chain` 仍拒；materialize 稳定码 |
| ADV5 | 不同 executable（`D:\Miniforge3\python.exe`） | **PASS** 拒绝 |
| ADV6 | WinAPI/`CreateFile` 异常消息含 path/handle | **PASS** 对外无路径/句柄泄漏 |
| ADV7 | `TimeoutExpired` 路径 | **PASS** `PROVIDER_DUMP_TIMEOUT` + handle 已释放 |
| ADV8 | 成功 dump 后 verify 强制 drift | **PASS** 不宣称成功 + handle 已释放 |
| ADV9 | 持 handle 时另开 GENERIC_WRITE / DELETE | **PASS** 均失败；handle nlink≥2 |
| ADV10 | 成功 CM 路径后泄漏探针 | **PASS** |
| ADV11 | dump-tool hardlink → `_read_regular` | **PASS** 仍 `regular unlinked file required` |

对抗后清理：`m3chain312` `st_nlink` 回到 **2**（过程中曾因残留探针链短暂为 3，已精确清理 owned links）。

## 4. 双平台 focused / static / cold（独立复跑）

### Windows `m3chain312`

| 检查 | 结果 |
|---|---|
| `pytest -q tests/unit/test_m3_provider_materialization.py` | **19 passed, 3 skipped**（exit 0） |
| `ruff check` provider + 该测试 | **All checks passed** |
| `mypy` 同上 | **Success: no issues found** |
| cold import（`PYTHONPATH=src`） | **PASS** |
| 实际 `st_nlink` | **2** |

### Windows base（邻接）

| 检查 | 结果 |
|---|---|
| 同 focused 文件 | **17 passed, 5 skipped**（nlink≥2 相关 skip；exit 0） |

### WSL Miniforge `base`

| 检查 | 结果 |
|---|---|
| focused provider 测试 | **19 passed, 3 skipped**（exit 0） |
| ruff / mypy | **PASS / PASS** |
| cold import | **PASS**；`nlink=1`（**不要求** nlink>1 成功） |
| 文件系统 | `findmnt` → **drvfs** `/mnt/f`（非 ext4） |

## 5. 与交付报告差异

| 项 | 说明 |
|---|---|
| focused/静态数字 | 与交付一致（Win m3chain312 19/3；base 邻接 17/5；WSL 19/3） |
| `_read_regular` 仍拒 nlink2 | 独立复现一致 |
| 对抗深度 | 本报告新增 junction resolve-to-exact、timeout 关句柄、WinAPI 脱敏、hardlink 别名路径等；**未发现**交付谎报 |
| 停止条件 | 子解释器在持 handle 下可跑（交付自测）；本轮 hostile 写删被拦，未见需放宽通用单链接或改 public API |

## 6. 最终判定与剩余 Gate

### 最终判定：**PASS**

通过含义仅限任务单允许声明：  
**Windows current conda Python executable 锚定工程合同**独立初验通过，可交主 Agent 做 F2 主验。

### 剩余 Gate / 阻塞

1. **F2 主验**（主 Agent）：契约/回归/文档一致性终验；**F2 主验 PASS 前禁止继续 F0 R3 / C0 / C1**。  
2. **F0 R3**：复用既有 support 继续 provider→backtest_plan→resolver（主验通过后另冻）。  
3. **C0 / C1**：不得因本 PASS 宣称通过。  
4. **Linux ext4 / WSL Gate**：本包明确不改变；Windows 绿测 ≠ Linux 发布终验；当前 WSL 工作树为 **drvfs**。  
5. 操作卫生：hostile hardlink 必须落在 owned 目录并精确清理，避免污染 conda `python.exe` 的 `st_nlink`（本轮已清理回 2）。

### 初验角色声明

实现者自测不能代替本报告；本报告不能代替主验；未宣称任何 M3 Gate 关闭；未 add/commit。
