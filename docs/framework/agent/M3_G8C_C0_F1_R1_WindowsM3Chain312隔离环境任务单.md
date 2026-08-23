# M3 G8C-C0 F1 R1：Windows m3chain312 隔离环境任务单

日期：2026-08-11

状态：**工程主验 PASS；允许重冻 F0 真链任务；C0/C1 与 Linux ext4 Gate 仍未通过**

## 1. 目标与依据

为 C0 的诚实 public formal chain support 创建专用 Windows Miniforge 环境 `m3chain312`。当前 WSL1 即使在依赖
齐全的`py312`也不支持formal publisher要求的atomic directory no-replace；Windows支持发布原语，但base与既有
`py312`缺Qlib/fire/LightGBM/PyArrow。新环境只解决工程测试依赖与发布原语交集，不替代Linux ext4 Gate。

官方包证据：PyPI `pyqlib 0.9.7`提供`cp312-win_amd64` wheel，项目`pyproject.toml`已在`qlib` optional group
声明`pyqlib>=0.9.7`，研究组声明`lightgbm>=4.3`。不得修改项目依赖声明。

## 2. 环境与安装边界

- 新环境唯一名称：`m3chain312`，Python exact 3.12；不得修改/删除/clone-overwrite Windows `base`、Windows
  `py312`、WSL `base/py312`。
- 若同名环境已存在，先只读核对；完全符合才复用，否则停止，不原地修补未知环境。
- 从当前worktree执行：先创建全新环境，再仅安装项目`.[qlib,dev]`与`lightgbm>=4.3`。不得安装`research`整组，
  避免无关MLflow/quantstats；不得安装data/broker依赖。
- 使用标准PyPI/conda渠道与项目已声明版本范围；记录最终resolved版本、Python、平台、wheel来源与许可证摘要。
  不写token/凭据，不改pip/conda全局配置。
- 环境创建失败时保留精确诊断；不得污染其他环境。若需删除不完整新环境，先确认目标exact为
  `D:\Miniforge3\envs\m3chain312`，只删除该新环境并在报告说明。

## 3. 必须通过的探针

在`m3chain312`中、以当前worktree `PYTHONPATH=src`：

1. Python 3.12；import `quant`、`qlib`、`lightgbm`、`pyarrow`、`polars`、`pandera`、`pytest`；
2. `importlib.metadata.version`可读取`fire,loguru,numpy,pandas,pyarrow,pyqlib,tqdm`；
3. public `build_provider_runtime_fingerprint()`成功且含上述exact package集合；
4. public `platform_supports_renameat2_noreplace()`为true，并在workspace内新建owned临时目录做一次public
   no-replace探针；同名目标拒绝且不覆盖，之后精确清理owned目录；
5. `compute_m3_runtime_identity`对当前配置frozen digest成功；cold import不启动MLflow服务/网络；
6. 运行C0 unit（integration仍按F0状态skip）与定向Ruff/mypy，结果明确终态。

任何真实G1/stage全链构造仍属于F0后续，不在F1运行；不得写`data/clean`或`artifacts/research/m3`正式树。

## 4. 文件白名单与交付

- 本任务状态
- 唯一交付报告 `docs/framework/agent/M3_G8C_C0_F1_R1_WindowsM3Chain312隔离环境交付报告.md`
- 独立初验只写 `docs/framework/agent/M3_G8C_C0_F1_R1_WindowsM3Chain312隔离环境独立复验报告.md`

禁止修改任何production/tests/config/pyproject/lockfile/其他文档，禁止git add/commit。环境本身位于项目外。

## 5. 停止条件与声明

Windows wheel不可安装或import；需要源码编译器/系统级SDK；public no-replace为false；依赖解析要求修改
pyproject或污染既有环境；Qlib/LightGBM不能在同一Python 3.12进程共存；需要真实网络服务/MLflow；任一出现即停止。

F1仅可声明“Windows m3chain312隔离环境工程前置PASS”。F1主验PASS后，主Agent另重冻F0在该环境实际构造链；
不宣称C0/C1、Linux ext4或任何Gate通过。

## 6. 主 Agent 最终验收（2026-08-11）

结论：**PASS，仅限 Windows `m3chain312` 隔离环境工程前置**。

- 外部实现与未参与实现的全新外部初验均按白名单完成；独立初验结论 PASS。
- 主验复核 Python `3.12.13`、`pyqlib 0.9.7`、`lightgbm 4.7.0`、`pyarrow 25.0.1`，public provider fingerprint
  为 `8f1148c7aa7ec73e46eb7bf897488ca81b547952f4299ff073a0a8b9835cc227`，public no-replace capability 为 true。
- 主验在当前 worktree、`PYTHONPATH=src` 下复跑 C0 unit：`17 passed, 1 skipped`。
- 主验首次公共探针误用了已不存在的旧模块名 `quant.data.m3_g1_release`，该命令不计证据；修正为当前公共模块
  `quant.data.m3_release` 后明确通过。
- 定向 Ruff 的 4 个既有 `BLE001` 仍是 C0 代码卫生债；本环境任务禁止改 production，因此不阻断环境前置，
  但 F0/C0 后续交付不得把它宣称为静态全绿。

本结论只解锁新的 F0 任务冻结与外部实现，不解锁 C0/C1，也不替代 Linux ext4 发布终验。
