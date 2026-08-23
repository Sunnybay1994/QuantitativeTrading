# M3 G8C-C0 F1 R1：Windows m3chain312 隔离环境独立复验报告

日期：2026-08-11  
角色：全新外部独立初验 Agent（未参与 F1 实现）  
模型：`cursor-grok-4.5-high`  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
结论：**PASS**（仅「Windows `m3chain312` 隔离环境工程前置」；**非**主验、**非** F0 链构造、**非** C0/C1、**非** Linux ext4、**非**任何 Gate）

依据：`AGENTS.md`、`.ai/README.md` / `.ai/review_checklist.md` / `.ai/workflows/multi_agent_delivery.md`；  
任务单 [`M3_G8C_C0_F1_R1_WindowsM3Chain312隔离环境任务单.md`](M3_G8C_C0_F1_R1_WindowsM3Chain312隔离环境任务单.md)；  
交付报告 [`M3_G8C_C0_F1_R1_WindowsM3Chain312隔离环境交付报告.md`](M3_G8C_C0_F1_R1_WindowsM3Chain312隔离环境交付报告.md)。

本会话对 production / tests / config / `pyproject.toml` / 任务单 / 交付报告 / `D:\Miniforge3\envs\m3chain312` **严格只读**；未安装、升级、卸载或修改该环境及其他 conda 环境；未写 `data/clean` 或 `artifacts/research/m3` 正式树；未 `git add` / `commit`。仓库内唯一写入：**本独立复验报告**。

## 1. 结论边界（诚实声明）

| 可声明 | 不可声明 |
|---|---|
| Windows `m3chain312` 隔离环境工程前置 **PASS**，可解锁主验 | F1 主验已通过 |
| C0 unit 在该解释器下可跑通（含既有 skip） | C0 / C1 Gate 通过 |
| public no-replace 在本机 Windows 上可用 | Linux ext4 Gate / WSL 发布终验通过 |
| integration 仍按 F0 stop **skip** | 诚实 public formal G1→chain 已构造（**F0 未闭合**） |

## 2. 任务单探针逐项映射

解释器：`D:\Miniforge3\envs\m3chain312\python.exe`；`PYTHONPATH=src`；cwd=当前 worktree。

| # | 任务要求 | 独立证据 | 结论 |
|---|---|---|---|
| 环境 | exact `m3chain312`，Python 3.12；不污染 base/py312/WSL | `conda env list` 含 `D:\Miniforge3\envs\m3chain312`；本解释器 `3.12.13`；Windows `base`=3.13.13 且 `qlib` 缺失；Windows `py312`=`3.12.13` 且 `qlib`/`lightgbm` 均缺失；路径与 `py312` 分离 | 满足 |
| 1 | import `quant/qlib/lightgbm/pyarrow/polars/pandera/pytest` | 全部 OK；`quant`→worktree `src\quant\__init__.py`；其余→`m3chain312\Lib\site-packages` | PASS |
| 1b | Qlib+LightGBM 同进程 | 同进程 import 成功；另 `lgb.Dataset(...).construct()` + `import qlib` 同进程 `num_data=3` | PASS |
| 2 | `importlib.metadata.version`：fire/loguru/numpy/pandas/pyarrow/pyqlib/tqdm | `0.7.1 / 0.7.3 / 2.5.2 / 2.3.3 / 25.0.1 / 0.9.7 / 4.70.0`（与交付一致） | PASS |
| 2b | 关键 wheel/元数据 | `pyqlib` WHEEL `Tag: cp312-cp312-win_amd64`，Classifier MIT；`lightgbm 4.7.0` `py3-none-win_amd64` MIT；`pyarrow 25.0.1` `cp312-cp312-win_amd64` Apache-2.0；`pip check` 无 broken | PASS |
| 3 | public `build_provider_runtime_fingerprint()` exact 包集合 | packages 恰为 `fire/loguru/numpy/pandas/pyarrow/pyqlib/python/tqdm`；`sha256=8f1148c7aa7ec73e46eb7bf897488ca81b547952f4299ff073a0a8b9835cc227` | PASS |
| 4 | `platform_supports_renameat2_noreplace()` | **True** | PASS |
| 4b | owned 临时目录 public no-replace；同名拒绝且不覆盖 | 首次 `commit_directory_noreplace` 成功；二次同名 → `G1_RELEASE_CONCURRENT_PUBLISH`；marker 文本与 sha256 不变；无额外文件渗入；owned 目录精确清理后不存在 | PASS |
| 5 | `compute_m3_runtime_identity(..., frozen_config_digests=...)` | `schema=m3-runtime-identity-v1`；`code_source=git`；`python_version=3.12.13`；`os_name=nt`；`sys_platform=win32` | PASS |
| 5b | cold 无网络 / 不启 MLflow 服务 | 新鲜进程：socket `connect`/`create_connection` 守卫 **0 hit**；`MLFLOW_TRACKING_URI` 未设置；fingerprint/runtime/platform 探针无拨号（见 §3 反例 ADV1） | PASS |
| 6 | C0 unit + 定向 Ruff/mypy；integration 按 F0 skip | 见 §4 | 终态明确 |

安装边界旁证（只读）：`quantstats`/`tushare`/`akshare`/`xtquant`/`miniqmt` 的 `find_spec` 均为 `None`；`mlflow==3.15.1` 作为 `pyqlib` 传递依赖存在，但 **不等于**安装了项目 `research` optional 整组。`pyproject.toml` 仍声明 `pyqlib>=0.9.7` / `lightgbm>=4.3`；本轮未改依赖声明。

## 3. 实现者未使用的安全/对抗反例

以下均在独立会话新建探针中执行（非复述交付报告）：

| ID | 反例 | 结果 |
|---|---|---|
| ADV1 | 故意设置 `MLFLOW_TRACKING_URI=http://127.0.0.1:9` 后跑 fingerprint + frozen runtime identity | socket 守卫仍 **0 hit**；指纹 sha 不变 |
| ADV2 | 目标已存在为**普通文件**时 `commit_directory_noreplace` | `G1_RELEASE_CONCURRENT_PUBLISH`；文件字节与 sha256 完整保留；staging 仍在 |
| ADV3 | 成功发布后第三次提交含 `evil.bin` 的同名目录 | 仍 `G1_RELEASE_CONCURRENT_PUBLISH`；published 保持 `V1`；无 `evil.bin` |
| ADV4 | 失败的 exclusive commit 后 staging 是否残留（防“半覆盖假成功”） | staging **仍存在**；dst 未变 |
| ADV5 | research/data/broker 相关包不得因本环境出现 | `quantstats/xtquant/tushare/akshare/miniqmt` 均缺失 |
| ADV6 | 正式树未被 F1 写入 | `data/clean/m3_g1/releases` **不存在**；`artifacts/research/m3` 仅既有 `.gitkeep`（无正式产物） |
| ADV7 | 非法 frozen digest（短 sha） | `M3SourceDigestV1` → `ValueError('invalid sha256')`；错误 path 集合 → `M3_RUNTIME_IDENTITY_INPUT_INVALID` |
| ADV8 | 隔离：base / py312 不得被本任务“补齐”为可用 Qlib 链环境 | base 无 `qlib`；py312 无 `qlib`/`lightgbm`；仅 `m3chain312` 同时具备 |
| ADV9 | 同进程 LightGBM Dataset 构造 + Qlib | `construct()` 后 `num_data==3`，`qlib` 仍可导入 |

未发现交付报告对关键探针结果的实质性谎报或环境串改迹象。

## 4. C0 测试与定向静态检查（独立复跑）

| 命令 | 终态 |
|---|---|
| `pytest -q tests/unit/test_m3_g8c_c0_formal_cli_resolve.py` | **17 passed, 1 skipped**（exit 0） |
| `pytest -q tests/integration/test_m3_g8c_c0_formal_cli_resolve.py` | **1 skipped**（F0/R3 stop：无诚实可复用 public formal G1→backtest_plan 链；exit 0） |
| `ruff check src/quant/research/m3/formal_cli_resolve.py tests/unit/test_m3_g8c_c0_formal_cli_resolve.py` | **exit 1**：生产文件 4×`BLE001`（L165/L876/L894/L902）；测试文件无报错。任务白名单禁止改 production，记为既有卫生债，**不**作为本环境安装失败 |
| `mypy src/quant/research/m3/formal_cli_resolve.py` | **Success: no issues found**（exit 0） |

pytest 出现 `.pytest_cache` WinError 5 警告，不影响收集与结果判定。

### Integration / F0 未闭合（强制诚实）

integration 用例 `test_r3_stop_no_honest_public_formal_chain_for_resolver` 仍 skip，理由不变：worktree 无诚实可复用 published formal G1→backtest_plan public 链；禁止用 G7F/G8 monkeypatch/`SimpleNamespace`/`object.__setattr__` 伪链充数。  
**F0 链构造、C0 formal CLI 端到端、C1 均未在本 F1 闭合。**

## 5. 与交付报告差异 / 旁证

| 项 | 说明 |
|---|---|
| 关键版本 / fingerprint sha | 独立复核与交付 **一致** |
| conda/pip 包计数 | 交付用 conda list 规模旁证；本轮 `pip list` 行数 base/py312/m3chain312≈308/17/211。工具不同，**不**作为指纹验收；隔离结论以 import 能力与路径为准 |
| `artifacts/research/m3` | 目录存在但仅 `.gitkeep`；非 F1 正式产物写入 |
| Ruff BLE001 | 与交付一致；非 F1 阻断项（白名单禁改 production） |

## 6. 最终判定与剩余 Gate

### 最终判定：**PASS**

通过含义仅限任务单允许声明：  
**Windows `m3chain312` 隔离环境工程前置 PASS**（可进入主 Agent 主验）。

### 剩余 Gate / 阻塞（主验前与之后）

1. **F1 主验**（主 Agent）：吸收本初验后做最终契约/文档一致性验收；主验 PASS 前 **F0/C0/C1 禁止继续**（任务单状态）。  
2. **F0**（主验 PASS 后另冻）：在本 `m3chain312` 上实际构造诚实 public formal chain；当前 integration 仍 skip，**未闭合**。  
3. **C0 / C1**：不得因本 PASS 宣称通过。  
4. **Linux ext4 / WSL Gate**：本环境不替代；Windows 绿测 ≠ Linux 发布终验。  
5. **定向 Ruff BLE001 债**：与环境无关的既有生产卫生项，后续若改 `formal_cli_resolve.py` 需另开任务。

### 初验角色声明

实现者自测不能代替本报告；本报告不能代替主验；未宣称任何 M3 Gate 关闭。
