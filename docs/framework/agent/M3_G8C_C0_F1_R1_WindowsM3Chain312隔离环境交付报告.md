# M3 G8C-C0 F1 R1：Windows m3chain312 隔离环境交付报告

日期：2026-08-11  
角色：外部实现 Agent（`cursor-grok-4.5-high`）  
状态：**Windows m3chain312 隔离环境工程前置 PASS（待独立初验 / 主验）**

任务单：[`M3_G8C_C0_F1_R1_WindowsM3Chain312隔离环境任务单.md`](M3_G8C_C0_F1_R1_WindowsM3Chain312隔离环境任务单.md)

## 1. 结论边界

仅可声明：**Windows `m3chain312` 隔离环境工程前置 PASS**。  
不宣称 C0/C1、Linux ext4、任何 Gate、F0 formal chain 构造通过。未写 `data/clean` 或 `artifacts/research/m3` 正式树；未 git add/commit；未改 production/tests/config/pyproject/lockfile/其他文档。

## 2. 环境创建与安装

创建前 `conda env list` 仅有 Windows `base`、`py312`；`D:\Miniforge3\envs\m3chain312` 不存在。执行：

```text
D:\Miniforge3\Scripts\conda.exe create -y -n m3chain312 python=3.12 pip
# cwd = 当前 m3-g4-formal worktree
D:\Miniforge3\envs\m3chain312\python.exe -m pip install --upgrade pip
D:\Miniforge3\envs\m3chain312\python.exe -m pip install ".[qlib,dev]" "lightgbm>=4.3"
```

| 项 | 值 |
|---|---|
| 环境路径 | `D:\Miniforge3\envs\m3chain312`（exact） |
| Python | `3.12.13`（Anaconda/Miniforge win-64） |
| 平台 | `Windows-11-10.0.22631-SP0` / `os.name=nt` |
| 安装范围 | 仅 `.[qlib,dev]` + `lightgbm>=4.3`；**未**装 `research` / `data` / broker |
| `pip check` | 无 broken requirements |
| 索引 | 既有 pip 配置指向 `pypi.tuna.tsinghua.edu.cn`；未改 pip/conda 全局配置 |

未修改/删除/覆盖 Windows `base`、Windows `py312`、WSL 环境。当前 conda list 规模快照（仅作隔离旁证，非指纹验收）：`base` n=413、`py312` n=33、`m3chain312` n=226。

### 2.1 关键 resolved 版本与 wheel

| 包 | 版本 | Wheel / Tag | 许可证摘要 |
|---|---|---|---|
| pyqlib | 0.9.7 | `cp312-cp312-win_amd64`（PyPI wheel，无源码编译） | Classifier: MIT |
| lightgbm | 4.7.0 | `py3-none-win_amd64` | MIT |
| pyarrow | 25.0.1 | `cp312-cp312-win_amd64` | Apache-2.0 |
| fire | 0.7.1 | — | Apache-2.0 |
| loguru | 0.7.3 | — | Classifier: MIT |
| numpy | 2.5.2 | — | — |
| pandas | 2.3.3 | — | — |
| tqdm | 4.70.0 | — | — |
| polars | 1.43.2 | — | — |
| pandera | 0.32.1 | — | — |
| pytest | 9.1.1 | — | — |
| ruff | 0.16.2 | — | — |
| mypy | 2.3.0 | — | — |
| quant | 0.1.0 | 由当前 worktree `pip install .` | 项目 |

传递依赖说明：`pyqlib` 拉入 `mlflow==3.15.1` 等研究栈传递包；**未**安装 `quantstats`（`find_spec` 为 `None`）。这不等于安装了项目 `research` optional group。

## 3. 必须探针（`PYTHONPATH=src`，解释器 `m3chain312`）

| # | 探针 | 结果 |
|---|---|---|
| 1 | Python 3.12；import `quant/qlib/lightgbm/pyarrow/polars/pandera/pytest` | PASS（`quant` 解析到 worktree `src`） |
| 2 | `importlib.metadata.version`：`fire,loguru,numpy,pandas,pyarrow,pyqlib,tqdm` | PASS（上表） |
| 3 | public `build_provider_runtime_fingerprint()` | PASS；packages 恰为 `fire/loguru/numpy/pandas/pyarrow/pyqlib/python/tqdm`；`sha256=8f1148c7aa7ec73e46eb7bf897488ca81b547952f4299ff073a0a8b9835cc227` |
| 4 | `platform_supports_renameat2_noreplace()` | **True** |
| 4b | workspace owned 临时目录 public `commit_directory_noreplace` | 首次提交成功；同名目标抛 `G1_RELEASE_CONCURRENT_PUBLISH` 且不覆盖 marker；owned 目录精确清理后不存在 |
| 5 | `compute_m3_runtime_identity(..., frozen_config_digests=...)` | PASS；`schema=m3-runtime-identity-v1`；`code_source=git`；`python_version=3.12.13`；`os_name=nt` |
| 5b | cold import / fingerprint / runtime 不拨号网络 | PASS（socket.connect 守卫无 hit）；`MLFLOW_TRACKING_URI` 环境变量未设置；未启动 MLflow 服务 |

未运行任何真实 G1/stage 全链构造。

## 4. C0 测试与定向静态检查

工作目录：当前 worktree；解释器：`D:\Miniforge3\envs\m3chain312\python.exe`；`PYTHONPATH=src`。

| 命令 | 终态 |
|---|---|
| `pytest -q tests/unit/test_m3_g8c_c0_formal_cli_resolve.py` | **17 passed, 1 skipped**（exit 0） |
| `pytest -q tests/integration/test_m3_g8c_c0_formal_cli_resolve.py` | **1 skipped**（F0/R3 stop skip 仍在；exit 0） |
| `ruff check src/quant/research/m3/formal_cli_resolve.py tests/unit/test_m3_g8c_c0_formal_cli_resolve.py` | **exit 1**：既有生产文件 4×`BLE001`（L165/L876/L894/L902）；测试文件无报错。本任务白名单禁止改 production，未修补 |
| `mypy src/quant/research/m3/formal_cli_resolve.py` | **Success: no issues found**（exit 0） |

pytest 出现 `.pytest_cache` WinError 5 警告，不影响收集/结果。

## 5. 仓库内变更文件

| 路径 | 动作 |
|---|---|
| `docs/framework/agent/M3_G8C_C0_F1_R1_WindowsM3Chain312隔离环境任务单.md` | 状态 → 外部实现已交付；待独立初验 |
| `docs/framework/agent/M3_G8C_C0_F1_R1_WindowsM3Chain312隔离环境交付报告.md` | 本报告（唯一交付） |

环境本体在项目外 `D:\Miniforge3\envs\m3chain312`。会话私有探针脚本已删除，未纳入交付。

## 6. 风险与下一步

- **风险**：定向 Ruff 对既有 `formal_cli_resolve.py` 报 BLE001；属代码卫生债，非本环境安装失败。`pyqlib` 传递安装 `mlflow`，cold 路径未启服务，但后续任务需继续禁止把 Windows 绿测表述为 Linux Gate。
- **下一步**：未参与实现的外部 Agent 只读写独立复验报告 `docs/framework/agent/M3_G8C_C0_F1_R1_WindowsM3Chain312隔离环境独立复验报告.md`；主验 PASS 后由主 Agent 另重冻 F0，在本环境实际构造诚实 public formal chain。F1 主验 PASS 前 F0/C0/C1 禁止继续。
