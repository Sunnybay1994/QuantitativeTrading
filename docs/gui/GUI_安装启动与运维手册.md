# GUI 安装启动与运维手册

## 当前可用性

G0 当前处于“依赖已声明、批准环境创建阻塞”阶段。`pyproject.toml` 已声明
`gui = ["streamlit>=1.48,<2"]`，但唯一批准的 Windows smoke venv 两次创建承载均以 `-1`、无日志终止，
目标目录和解释器均未产生，因此：

- 可以运行纯 Python catalog、完整性、NAV 与启动器聚焦测试；
- `python -m quant.gui` 在缺少 Streamlit 时应以退出码 2 明确失败；
- 不得修改 WSL `base`，也不得在统筹确认解释器/命令前抢占项目在途任务资源；
- 真实 AppTest、本地浏览器 smoke 和常驻服务运维仍是待安装验收项。
- 不进行第三次盲试，不改用其他全局解释器；下一次环境操作必须由统筹重新冻结可观测创建机制或恢复条件。

Streamlit 的必要性是以纯 Python 提供统一只读审核界面，且只作为 optional `gui` 依赖，不进入核心/交易
运行时。官方仓库与包元数据标记 Apache-2.0；分发时需保留适用许可证/NOTICE。未安装时启动器稳定退出码
2，不自动安装、不启动服务，catalog/完整性/NAV 的纯 Python 测试仍可运行。

## 开发验证

在独立 GUI worktree 和项目已配置的开发环境中运行：

```powershell
python -m pytest tests/unit/test_gui_research_runs.py tests/unit/test_gui_launcher.py -q
python -m pytest tests/gui/test_streamlit_app.py -q
```

第二条命令在 Streamlit 未安装时会显式跳过。这是“真实 UI 未验证”的证据，不是成功替代。

## 依赖解锁后的安装与启动

已批准但尚未成功执行的 smoke 环境路径和候选命令如下；它们是失败留痕，不构成再次执行授权：

```powershell
D:\Miniforge3\python.exe -m venv --system-site-packages F:\AI_Coding\QuantitativeTrading\artifacts\dev_envs\gui-g0-win-py313
F:\AI_Coding\QuantitativeTrading\artifacts\dev_envs\gui-g0-win-py313\Scripts\python.exe -m pip install -e "F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\gui-research-workbench[gui]"
F:\AI_Coding\QuantitativeTrading\artifacts\dev_envs\gui-g0-win-py313\Scripts\python.exe -m quant.gui --artifact-root F:\AI_Coding\QuantitativeTrading\artifacts
```

2026-08-16 的实际尝试使用基础解释器 `D:\Miniforge3\python.exe`（Python 3.13.13）、Hidden
`Start-Process`、BelowNormal、affinity `0xF00` 和线程上限 2。两次承载会话均非零 `-1` 且没有 stdout/stderr；
终态审计确认 `artifacts/dev_envs`、目标 venv、`Scripts/python.exe`、`pyvenv.cfg`、匹配日志和 `0xF00`
Python 均不存在。上面第一条 venv 命令通过受限 wrapper 尝试两次；第二、三条命令从未执行。Windows/WSL
base 未修改，pip 安装、AppTest 和浏览器均未开始，CPU8–11 已释放。

默认监听 `127.0.0.1:8501`，仅本机可访问。可用参数：

```text
--artifact-root PATH   固定研究产物根；默认是当前目录下 artifacts
--address ADDRESS      Streamlit 监听地址；默认 127.0.0.1
--port PORT            1..65535；默认 8501
--headless             使用 headless 模式
--no-headless          允许自动打开本机浏览器；默认保持 headless
```

本手册在依赖声明真正合流和命令真实运行前只记录预期接口，不宣称上述安装/启动已通过。

## 运行边界

- 为避免把任意路径暴露给页面，artifact root 仅由受信任运维者在启动命令中设置，再通过子进程环境传给 UI。
- G0 只读；服务账号不需要且不应拥有产物写权限。
- 默认保持回环地址。若要绑定非回环地址，必须先完成鉴权、TLS、反向代理、网络边界和日志脱敏任务。
- 不把长回测、采集、训练或任务状态放在 Streamlit 进程；未来由持久化 worker 承担。
- 不用删除或修补坏产物来“恢复页面”；页面会按问题码隔离坏运行，产物处置走独立、获批流程。

## 页面使用

1. 在“运行总览”查看可读运行、结论分布、最大数据结束日和异常数量。
2. 用“结论”和“策略”筛选定位运行；空结果会保留筛选上下文而不是显示无说明空白。
3. 进入“运行详情”核对假设、时间语义、fold、成本、指标、caveat 和输出清单。
4. 需要看 NAV 时显式执行输出完整性校验。只有 `VERIFIED` 才会读取 `test_nav.parquet`。
   G0 同步校验总量上限为 128 MiB，超限运行需等待未来外置 verifier。
5. `BLOCKED` 时记录问题码和 run id；不要绕过校验直接打开同目录其他文件并据此晋级。

## 常见故障

| 现象 / 问题码 | 含义 | 处置 |
| --- | --- | --- |
| 启动退出码 2 | Streamlit 未安装或未纳入当前环境 | 等待依赖 SSOT 解锁并按项目 optional group 安装 |
| `RUNS_ROOT_MISSING` | 指定 artifact root 下没有固定 runs 根 | 核对受信任启动参数与产物挂载；GUI 不自动搜索其他路径 |
| `RUNS_ROOT_UNSAFE` | runs 根不是安全实目录或不可读取 | 停止服务，检查挂载、权限、link/reparse point；不要放宽校验 |
| `RUN_MANIFEST_*` | JSON、V1 合同、规范编码或身份不一致 | 隔离该运行并回到发布者/原始任务证据，不在 GUI 修改 |
| `RUN_TREE_MISMATCH` | 实际文件树与清单不一致 | 检查缺失、额外或临时文件，保持不可变产物原样留证 |
| `RUN_OUTPUT_DIGEST_MISMATCH` | size 或 SHA-256 漂移 | 视为篡改/损坏，拒绝 NAV；从可信源重新生成新 run |
| `NAV_SCHEMA_INVALID` | NAV 必要列、类型或值不满足只读投影合同 | 保留原 run，修复上游发布代码并产生新 run |

## 停止与恢复

G0 没有后台任务。停止 Streamlit 进程不会改变研究产物，重新启动后会从不可变清单重新构建投影。发生安全
问题时先停止进程并保留坏运行证据；不要清目录、改 `run.json` 或覆盖输出。任何删除、迁移、修复、依赖升级
和远程暴露都需单独授权。
