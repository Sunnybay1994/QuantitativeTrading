# M3-G8F-R2E Windows Py312 Qlib Environment 交付报告

日期：2026-08-28<br>
task id：`M3-G8F-R2E-WINDOWS-PY312-QLIB-ENVIRONMENT`<br>
角色：唯一 Luna 审计 Worker<br>
资源：`STATIC_ONLY / CPU NONE`

- exact base / HEAD：`10af1582845fbffd8356fa987d0c5ce2d6783ed4`
- branch：`codex/m3-g8f-r2e-windows-py312-qlib-environment`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2e-windows-py312-qlib-environment`
- 唯一写入：`docs/framework/deliveries/M3_G8F_R2E_WindowsPy312QlibEnvironment交付报告.md`
- 交付结论：`ENVIRONMENT_INVENTORY_INCOMPLETE / A17 MISSING`

## 1. 结论

已按任务书对 exact Windows 环境路径与 tracked 锚点做只读复核。
`D:\Miniforge3\envs\py312\python.exe` 存在，其大小、SHA-256 与 conda Python record
共同闭合 Windows native Python `3.12.13` 候选解释器身份。

但是 exact `Lib\site-packages\qlib`、`pyqlib-0.9.7.dist-info`、`pyqlib.dist-info` 和 conda-meta
Qlib/pyqlib record 均不存在。本 HEAD 仅以 `pyqlib>=0.9.7` 宽泛声明 Qlib optional dependency，
也没有可用于 Windows cp312 安装的 exact wheel filename、source URL、byte size、SHA-256、许可证和完整依赖变更清单。

因此本包只证明“exact Windows Python 候选存在”，不证明“exact Windows Python + Qlib
运行环境完整”。A17 继续为 `MISSING`，终态不得超过
`ENVIRONMENT_INVENTORY_INCOMPLETE`，不得写 `READY`。

## 2. 现场与权威身份

### 2.1 Git 与任务边界

- 写入前 `HEAD` 为 `10af1582845fbffd8356fa987d0c5ce2d6783ed4`，branch 与任务书一致。
- 写入前 worktree 仅任务书 untracked，`cached=0`；无 production/tests/config/review 变更。
- 本 Worker 只新增本交付报告；没有修改任务书、review、production、tests、config、roadmap 或 governance。

### 2.2 exact Windows interpreter

| 字段 | 只读复核值 |
|---|---|
| path | `D:\Miniforge3\envs\py312\python.exe` |
| size | `105288` bytes |
| SHA-256 | `0d84b0acc6a5a3e7906d07c63a364e19b76410fa726c4412c74d3af7408b08d5` |
| conda record | `D:\Miniforge3\envs\py312\conda-meta\python-3.12.13-h63b1a2d_1.json` |
| record identity | name `python`; version `3.12.13`; build `h63b1a2d_1` |
| package SHA-256 | `11c2922dfc954be1a5b867b6891d6430596eed8895983b9c1620dfca4c220e6b` |
| license | `PSF-2.0` |

这些事实只闭合 interpreter candidate，没有执行 `python.exe`，也没有使用 PATH、
`sys.executable` 或 WSL 路径替代该身份。

### 2.3 Qlib 缺失证据

| exact 检查项 | 结果 |
|---|---|
| `D:\Miniforge3\envs\py312\Lib\site-packages\qlib` | 不存在 |
| `D:\Miniforge3\envs\py312\Lib\site-packages\pyqlib-0.9.7.dist-info` | 不存在 |
| `D:\Miniforge3\envs\py312\Lib\site-packages\pyqlib.dist-info` | 不存在 |
| `D:\Miniforge3\envs\py312\conda-meta` 中文件名匹配 `qlib` | `0` records |

这是 filesystem/package metadata 范围的 exact absence 证据。本包禁止启动 Python，因此没有尝试
import 或 metadata probe 来越过任务书。不将任何非 exact 目录、editable install、PATH 发现或
WSL package 当作 Windows Qlib 证据。

### 2.4 tracked 项目锚点

| 输入 | Git blob | working SHA-256 | 结论 |
|---|---|---|---|
| `pyproject.toml` | exact HEAD blob `8f7060757e9e5ac959c25a6e0441a95d42f52164` | `96047c6772bb08696f924ad9497d3a6c26b6cb08b2f5332fc600288355c8d3dd` | Python `>=3.10`；optional Qlib 仅 `pyqlib>=0.9.7`，不是 exact lock |
| `data/external/qlib/v0.9.7/dump_bin.py` | `cb8ed72dabbbd990edb7c5ec14d34356124b7580` | `b8f34c57ce1ef4b1772f3909735e66058f21b25bd7ab8a5f16318822401fe53f` | `21847` bytes；package-owned dump tool，不是 Qlib wheel |
| WSL py312 验收报告 | `7173ecc41245fd8d81a5140a81c1fd0459c667ca` | `3f603a9f35f6f2261532827fdf8a7d0a3792e5ebdb894f50ced16f6f9c7e2601` | 明确是 `/home/mabw/miniforge3/envs/py312`，不能代替 Windows executable/wheel |

tracked dump tool 身份闭合不能闭合 A17；WSL 报告中的 manylinux wheel 与 wheelhouse aggregate SHA
也不是 Windows cp312 wheel 的 filename/bytes/hash/license 证据。

REWORK1 保留身份纠正历史：首轮交付将
`a4e8af6112843e3703ec46505351dc22bf746469` 误标为 `pyproject.toml` 的 HEAD Git blob。该值实际是当时
working-tree `git hash-object -- pyproject.toml` 的输出，而 exact HEAD blob 是
`8f7060757e9e5ac959c25a6e0441a95d42f52164`。本次仅修正 Git 对象标签；working bytes SHA-256、
环境身份、Qlib 缺失事实和 `ENVIRONMENT_INVENTORY_INCOMPLETE / A17 MISSING` 结论均不变。

## 3. 安装输入与后续准入

未来目标只能是既有 `D:\Miniforge3\envs\py312`，目标解释器固定 Python `3.12.13`，
目标 distribution 固定 `pyqlib==0.9.7`。当前尚缺：

1. Windows cp312 兼容的 exact wheel filename 与 source URL；
2. wheel 的 byte size 与 SHA-256；
3. pyqlib 及所有将被新增、升级或降级依赖的许可证与 exact inventory；
4. 可证明 resolver 不会未授权地改写既有环境的安装计划。

因此后续唯一合法动作是由中央另行冻结 network/download/install/resource 租约，先在
no-clobber evidence root 下下载并审查 exact Windows artifacts，再单独决定是否安装。
本包不是该授权。安装开始后任何失败都不得推测性卸载或递归删除共享环境；
应保留证据并标记 `ENVIRONMENT_PARTIAL_LOCKED`，等待中央精确处置。

## 4. 对抗性核对

| 反例 | 结果 |
|---|---|
| exact Windows interpreter 存在 | 不能推导 Qlib 已安装；A17 仍 `MISSING`。 |
| WSL py312 + Qlib 0.9.7 已验收 | 不能替换 Windows path、wheel tag、bytes 或 hash。 |
| tracked dump tool SHA/size 闭合 | 它不是 Qlib distribution，不具有 import/runtime 语义。 |
| `pyproject.toml` 声明 `pyqlib>=0.9.7` | 宽泛约束不能替换本任务的 exact `==0.9.7` 安装身份。 |
| 为了继续需要启动 Python/conda/pip 或联网 | 保持 `CENTRAL_RESOURCE` 并 STOP，不自行探针。 |
| 安装需要改变未知已有包 | `INSTALL_INPUT_INCOMPLETE`；未获明确变更清单不得安装。 |

## 5. 实际执行与未运行边界

实际只读命令仅包括：`git status/rev-parse/hash-object`、`Get-Item`、`Get-FileHash`、
`Get-Content` 读取 exact JSON/Markdown，`Test-Path` 检查任务书列明的 exact package paths，
以及仅对 `D:\Miniforge3\envs\py312\conda-meta` 文件名的 `qlib` 过滤。

| 项 | 状态 |
|---|---|
| Python / pytest / Ruff / mypy / cold import | `UNRUN` |
| conda / pip / package metadata CLI | `UNRUN` |
| Qlib / Alpha158 / LGBModel / dump tool execution | `UNRUN` |
| network / download / install / upgrade / uninstall | `UNRUN` |
| environment 创建、删除或修改 | `0-write` |
| request / config / G1 release / controlled root / evidence root | `未创建 / 未读取` |
| WSL executable 替代 Windows 证据 | `未使用` |
| actual successor / real Qlib data / retained / network | `UNRUN` |
| stage / commit / merge / cleanup | `未执行` |

## 6. 交付终态与剩余风险

交付终态：

`ENVIRONMENT_INVENTORY_INCOMPLETE / A17 MISSING`

本报告没有证明 Qlib 可 import、依赖闭合、Windows wheel 兼容、dump tool 可执行，也没有关闭
actual successor、真实 Qlib、new root、retained 或 M3 Gate。下一步仅能是由未参与本 Worker 的
唯一独立 reviewer 静态复核本 inventory；review PASS 也只证明盘点诚实，不得升级为 A17 或 Gate 通过。
