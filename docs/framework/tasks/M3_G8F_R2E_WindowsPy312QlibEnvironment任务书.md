# M3-G8F-R2E Windows Py312 Qlib Environment 任务书

日期：2026-08-28<br>
状态：`FROZEN / STATIC_ONLY / ENVIRONMENT_INVENTORY_INCOMPLETE`

## 1. 身份与目标

- task id：`M3-G8F-R2E-WINDOWS-PY312-QLIB-ENVIRONMENT`
- exact base / HEAD：`10af1582845fbffd8356fa987d0c5ce2d6783ed4`
- branch：`codex/m3-g8f-r2e-windows-py312-qlib-environment`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2e-windows-py312-qlib-environment`
- 目标：只读冻结 Windows native Python 3.12 / Qlib 0.9.7 候选环境、依赖约束、安装输入与未来验证合同；本包不创建或修改环境。

结论上限为 `ENVIRONMENT_INVENTORY_FROZEN`。当前 exact interpreter 已存在，但未发现 Qlib package 或
dist-info，因此 A17 仍为 `MISSING / ENVIRONMENT_INVENTORY_INCOMPLETE`，不得写 READY。

## 2. exact3 与角色

1. `docs/framework/tasks/M3_G8F_R2E_WindowsPy312QlibEnvironment任务书.md`（经理唯一写）
2. `docs/framework/deliveries/M3_G8F_R2E_WindowsPy312QlibEnvironment交付报告.md`（后续唯一 Worker 写）
3. `docs/framework/reviews/M3_G8F_R2E_WindowsPy312QlibEnvironment独立初验报告.md`（不同 reviewer 写）

当前只批准路径 1。中央复核前不得派 Worker/reviewer；不得写 delivery/review、production、tests、config、roadmap 或 governance。

## 3. 只读事实与权威锚点

| 输入 | 身份 / 结果 | 边界 |
|---|---|---|
| exact interpreter candidate | `D:\Miniforge3\envs\py312\python.exe`；size `105288`；SHA-256 `0d84b0acc6a5a3e7906d07c63a364e19b76410fa726c4412c74d3af7408b08d5` | 只读 filesystem identity；本轮未执行 |
| conda Python record | `python-3.12.13-h63b1a2d_1.json`；version `3.12.13`；package SHA-256 `11c2922dfc954be1a5b867b6891d6430596eed8895983b9c1620dfca4c220e6b`；license `PSF-2.0` | 证明 Windows cp312 interpreter，不证明 Qlib |
| Qlib presence | `Lib\site-packages\qlib`、`pyqlib-0.9.7.dist-info`、`pyqlib.dist-info` 均不存在；conda-meta 无 qlib/pyqlib record | `MISSING`；不得用 import 或 WSL 结果补证 |
| `pyproject.toml` | exact HEAD Git blob `8f7060757e9e5ac959c25a6e0441a95d42f52164`；working bytes SHA-256 `96047c6772bb08696f924ad9497d3a6c26b6cb08b2f5332fc600288355c8d3dd` | Python `>=3.10`；optional qlib `pyqlib>=0.9.7`，不是 exact lock |
| tracked dump tool | `data/external/qlib/v0.9.7/dump_bin.py`；blob `cb8ed72...`；size `21847`；SHA-256 `b8f34c57ce1ef4b1772f3909735e66058f21b25bd7ab8a5f16318822401fe53f` | package-owned tool；不是 Qlib wheel |
| WSL py312 report | blob `7173ecc...`；SHA-256 `3f603a9f35f6f2261532827fdf8a7d0a3792e5ebdb894f50ced16f6f9c7e2601` | 只证明 WSL `/home/mabw/.../py312`，禁止替代 Windows executable |

## 4. 冻结目标环境与安装输入

- 唯一候选环境路径：`D:\Miniforge3\envs\py312`；唯一候选解释器为其 `python.exe`。
- 目标 Python：exact `3.12.13`；目标 Qlib distribution：exact `pyqlib==0.9.7`。不得只满足宽泛 `>=0.9.7`。
- 后续安装前必须冻结 Windows `cp312` 兼容的 exact wheel filename、source URL、byte size、SHA-256、许可证及所有将新增/升级/降级的依赖清单；当前这些 wheel/hash 事实不存在，状态为 `MISSING`。
- 不允许从 WSL wheelhouse、manylinux wheel、conda cache名或文档中的聚合 SHA 推导 Windows wheel。
- 不允许在 `base` 安装；不创建第二个 `py312`，不改环境名，不改 project dependency declarations。

## 5. 后续变更授权合同（当前未授权）

若中央另行批准 network/install，必须采用单一短命 installer、exact环境、受控CPU与no-clobber evidence：

1. 安装前重新核 interpreter SHA、Python record、Qlib absence、环境 package inventory与无活跃进程；任一漂移零写STOP。
2. 先只下载 exact Windows wheel及其完整依赖到新 evidence/download root，逐文件记录来源、size、SHA、license；hash不符STOP，不安装。
3. 中央复核下载清单后才允许对该 existing env 安装；禁止 resolver 任意升级现有包，禁止修改 base。
4. 每阶段保留stdout/stderr/exit与安装前后inventory；网络、许可证、wheel兼容、dependency conflict任一失败立即STOP。
5. 不对共享环境做推测性自动卸载/回滚。若安装已开始后失败，环境标记 `ENVIRONMENT_PARTIAL_LOCKED` 并保留证据，等待中央精确处置；不得递归删除env。

## 6. 后续验证合同（当前不运行）

获得独立资源授权后，顺序仅为：exact interpreter identity → Python 3.12.13 → `pyqlib==0.9.7` metadata →
`pip check`等价依赖闭包 → Qlib/Alpha158/LGBModel最窄 cold import → package-owned dump tool spec/bytes闭包 →
fresh evidence/scope/process residue。不得运行真实Qlib数据、下载、actual successor、新root或network。

## 7. 对抗与失败语义

- Windows interpreter存在但Qlib缺失：不得标A17完成。
- WSL py312/Qlib已绿：不得替换Windows路径或wheel证据。
- 名为`qlib`的目录、非exact dist-info、版本漂移、editable install、PATH发现或`sys.executable`默认：全部拒绝。
- wheel没有exact hash/license/dependency清单、resolver需改变未知既有包：`INSTALL_INPUT_INCOMPLETE`。
- 环境或解释器身份漂移：`ENVIRONMENT_IDENTITY_DRIFT_STOP`。
- 需要实际执行Python/conda/pip/network才能继续：保持`CENTRAL_RESOURCE`并STOP，不自行探针。

## 8. 静态验收与边界

任务书阶段仅本文件dirty、cached0、`git diff --check` PASS、UTF-8无BOM、LF-only、TW0、single EOF LF。
本包不关闭A17、actual successor、真实Qlib运行、new root、retained或M3 Gate；Linux不在当前目标，但不能因此把WSL证据改标Windows。

## 9. REVIEW_FAIL1 Git identity修正

首轮独立初验确认环境结论成立，但发现taskbook/delivery把working-tree `git hash-object`结果
`a4e8af6112843e3703ec46505351dc22bf746469`误标为HEAD Git blob；exact HEAD blob应为
`8f7060757e9e5ac959c25a6e0441a95d42f52164`。本节永久保留该现象、根因与修正；raw SHA-256及环境盘点结论不变。
原Worker仅可同步delivery中的同一标签，随后由原独立reviewer复验；不得借此修改其他证据或扩大环境权限。
