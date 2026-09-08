# M3-G8F-R2E Windows Py312 Qlib Environment 独立初验报告

日期：2026-08-28<br>
task id：`M3-G8F-R2E-WINDOWS-PY312-QLIB-ENVIRONMENT`<br>
角色：未参与任务书或交付报告写入的独立 reviewer<br>
模式：`STATIC_ONLY / CPU NONE`

初验结论：`REVIEW_PASS / REWORK1`

## 1. 结论摘要

交付的主结论是正确且保守的：exact Windows Python 3.12.13 候选解释器存在，但该环境中
没有 Qlib package/dist-info/conda record，也没有 exact Windows cp312 wheel、hash、license 与依赖变更清单。
因此 A17 必须继续为 `MISSING / ENVIRONMENT_INVENTORY_INCOMPLETE`，WSL py312 证据不能代替
Windows executable/wheel 证据。

首轮独立初验曾发现，任务书和交付报告把 working-tree
`git hash-object -- pyproject.toml` 输出
`a4e8af6112843e3703ec46505351dc22bf746469` 误标成 exact HEAD Git blob。REWORK1 已由经理与原
审计 Worker 分别在 taskbook/delivery 中保留历史并修正：exact HEAD blob 为
`8f7060757e9e5ac959c25a6e0441a95d42f52164`，`a4e8af...` 只标记为当时的 working-tree
`git hash-object` 输出。该身份阻断已闭合，A17 结论与所有环境权限边界未改变。

## 2. 独立复核结果

### 2.1 exact Windows interpreter

| 项 | 独立观测 | 结论 |
|---|---|---|
| path | `D:\Miniforge3\envs\py312\python.exe` | 存在 |
| size | `105288` bytes | 与任务书/交付一致 |
| SHA-256 | `0d84b0acc6a5a3e7906d07c63a364e19b76410fa726c4412c74d3af7408b08d5` | 与任务书/交付一致 |
| conda record | `python-3.12.13-h63b1a2d_1.json` | name/version/build 一致 |
| package SHA-256 | `11c2922dfc954be1a5b867b6891d6430596eed8895983b9c1620dfca4c220e6b` | 一致 |
| license | `PSF-2.0` | 一致 |

本初验未执行该解释器；上表只是 filesystem/conda JSON 身份，不证明 Qlib runtime。

### 2.2 Qlib absence 反例

独立检查不仅重复了任务书列出的三个 exact path，还对
`D:\Miniforge3\envs\py312\Lib\site-packages` 和 `conda-meta` 中名称包含 `qlib`
的条目做了只读名称过滤。结果均为空：

- `Lib\site-packages\qlib` 不存在；
- `pyqlib-0.9.7.dist-info` 不存在；
- `pyqlib.dist-info` 不存在；
- 其他版本或其他命名的 `*qlib*` site-packages 候选为空；
- `conda-meta` 的 `*qlib*` record 为空。

因此“Windows interpreter 存在”不能推导“Qlib 已安装”，A17 继续 `MISSING`。

### 2.3 WSL 不可替代 Windows

tracked WSL 报告的 exact Git blob 为
`7173ecc41245fd8d81a5140a81c1fd0459c667ca`，working SHA-256 为
`3f603a9f35f6f2261532827fdf8a7d0a3792e5ebdb894f50ced16f6f9c7e2601`。报告明确指向
`/home/mabw/miniforge3/envs/py312`、cp312 manylinux wheel 与 WSL wheelhouse。这些事实不能替代
`D:\...\python.exe` 或 Windows cp312 wheel 的 filename/bytes/hash/license/dependency inventory。交付在该
边界上没有过度声明。

### 2.4 安装输入仍不完整

- `pyproject.toml` 工作文件内容只声明 `requires-python = ">=3.10"` 和
  `pyqlib>=0.9.7`，它不是 exact Windows lock。
- tracked dump tool 为 `21847` bytes，SHA-256
  `b8f34c57ce1ef4b1772f3909735e66058f21b25bd7ab8a5f16318822401fe53f`，但它不是 Qlib wheel。
- tracked 文件列表中未发现 pyqlib/Qlib Windows wheel 文件。
- exact Windows wheel filename/source URL/size/SHA-256/license 及完整依赖变更清单仍缺失。

因此未来任何 download/install 都必须重新申请中央授权；本包不具备安装准入。

## 3. 首轮阻断项与 REWORK1 闭合

### P1 - `pyproject.toml` Git blob 身份记录错误（已闭合）

独立命令结果：

- `git rev-parse HEAD:pyproject.toml` =
  `8f7060757e9e5ac959c25a6e0441a95d42f52164`；
- 首轮记录的 working-tree `git hash-object -- pyproject.toml` =
  `a4e8af6112843e3703ec46505351dc22bf746469`；
- working-file SHA-256 =
  `96047c6772bb08696f924ad9497d3a6c26b6cb08b2f5332fc600288355c8d3dd`。

exact base/HEAD 的 Git blob 是第一个值。首轮任务书§3 和交付报告§2.4 均把第二个值
标为 Git blob，与 exact HEAD 不符。REWORK1 后：

- taskbook SHA-256 = `48590a797c4fb57c6aeb64f567b56011e7edf2f26e4272e6198e51b9d4961bad`；
- delivery SHA-256 = `ad82675575e1b4967165ec86d36404f6158eb262b0ec31def886228ba8496479`；
- 两者均把 exact HEAD blob 写为 `8f7060757e9e5ac959c25a6e0441a95d42f52164`；
- `a4e8af6112843e3703ec46505351dc22bf746469` 均只作为首轮 working-tree
  `git hash-object` 输出的历史证据保留；
- working bytes SHA-256、Windows interpreter/Qlib absence 证据、A17 `MISSING` 与未授权边界均未改变。

首轮通过条件及 REWORK1 结果：

1. 经理只修正任务书中该 anchor，明确区分 HEAD Git blob 与历史 working-tree `git hash-object`：PASS；
2. 原审计 Worker 只修正交付报告中同一 anchor：PASS；
3. 不改变 A17 `MISSING`、Windows/WSL 边界或安装输入缺口；
4. 复验确认 task/delivery 与 exact HEAD 身份一致：PASS。

## 4. 范围、卫生与未运行边界

- exact HEAD/branch 与任务书一致；
- 初验写入前 actual dirty 只有 taskbook + delivery，cached `0`，`git diff --check` PASS；
- 本 reviewer 只写唯一 review 路径；
- 未执行 Python/conda/pip/Qlib/pytest/Ruff/mypy/cold import；
- 未联网、下载、安装、升降级、卸载或修改环境；
- 未创建 request/config/release/root/evidence，未读取 LOCKED/retained 现场；
- 未 stage/commit/merge/cleanup。

本 `REVIEW_PASS / REWORK1` 只证明 tracked anchor 标注与环境缺口盘点已静态闭合。它不是
Windows Qlib 环境完整证据，也不授权任何安装或运行；A17 仍为 `MISSING`。
