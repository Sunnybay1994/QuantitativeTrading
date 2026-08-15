# GUI 安装启动与运维手册

## 当前可用性

G0/G1 只读工作台的 Windows functional smoke 已通过。`pyproject.toml` 声明
`gui = ["streamlit>=1.49,<2"]`；1.49 是官方支持 `st.dataframe(width="stretch")` 的最低版本，页面中的
12 处 dataframe 已统一使用该参数。G0-C4 短生命周期 venv 验证结束后已精确删除，因此仓库仍不会自动
安装或常驻启动 Streamlit：

- 可以运行纯 Python catalog、完整性、NAV 与启动器聚焦测试；
- `python -m quant.gui` 在缺少 Streamlit 时应以退出码 2 明确失败；
- 安装后只通过正式入口 `python -m quant.gui` 启动；`python -m quant.gui.launcher` 只加载定义，不会调用
  `main()`，不构成启动命令；
- 不得修改 Windows/WSL `base`，也不得在未获资源窗口时创建环境或启动常驻服务；
- Windows functional smoke 不等于独立依赖闭包、WSL Gate 或 strict zero-warning 验收。

Streamlit 只作为 optional `gui` 依赖，不进入核心/交易运行时。G0-C4 解析到的许可证元数据为 Streamlit
Apache-2.0、Altair BSD license text、pydeck Apache-2.0、toml MIT、watchdog Apache-2.0；未来分发仍需
保留适用许可证/NOTICE，并按实际解析版本复核。未安装时启动器不自动安装、不启动服务，catalog、完整性和
NAV 的纯 Python 测试仍可运行。

## 开发验证

在独立 GUI worktree 和项目已配置的开发环境中运行：

```powershell
python -m pytest tests/unit/test_gui_research_runs.py tests/unit/test_gui_launcher.py -q
python -m pytest tests/gui/test_streamlit_app.py -q -p no:cacheprovider
```

第二条命令在 Streamlit 未安装时会显式跳过；有 Streamlit 时应实际执行 3 个 AppTest。G0-C4 反馈环结果为
`3 passed, 3 warnings in 12.99s`，3 条 warning 来自 `importlib.metadata`，旧 `use_container_width`
告警为 0。

## 安装与启动

以下命令形态已在 G0-C4 Windows 反馈环验证，但不构成以后自行抢占资源或修改 base 的授权。实际环境应由
统筹分配唯一路径和资源窗口：

```powershell
D:\Miniforge3\python.exe -m venv --system-site-packages F:\AI_Coding\QuantitativeTrading\artifacts\dev_envs\gui-g0-c4-win-py313
F:\AI_Coding\QuantitativeTrading\artifacts\dev_envs\gui-g0-c4-win-py313\Scripts\python.exe -m pip install -e ".[gui]"
F:\AI_Coding\QuantitativeTrading\artifacts\dev_envs\gui-g0-c4-win-py313\Scripts\python.exe -m pip check
F:\AI_Coding\QuantitativeTrading\artifacts\dev_envs\gui-g0-c4-win-py313\Scripts\python.exe -m quant.gui --artifact-root F:\AI_Coding\QuantitativeTrading\artifacts --address 127.0.0.1 --port 18501 --headless
```

G0-C4 使用 .NET `System.Diagnostics.Process` carrier：`ArgumentList`、`UseShellExecute=false`、
`CreateNoWindow=true`、异步 stdout/stderr、真实退出码；每个 Python 子进程在取得 PID 后设置 BelowNormal、
affinity `0xF00` 和数值线程上限 2。解释器为 Python 3.13.13，实际 Streamlit 1.61.1，editable `[gui]`
安装成功，`pip check` 为 `No broken requirements found.`。`--system-site-packages` 会借用
`D:\Miniforge3` 中的依赖，因此这次 smoke 只能证明 Windows UI 反馈环，不能证明独立依赖闭包或 WSL Gate。

一次诊断命令误用了 `python -m quant.gui.launcher`；该模块只定义 `main()`，因此 exit 0 但没有监听端口或
残留进程。只读核对 `src/quant/gui/__main__.py` 后，最终使用上面的正确入口 `python -m quant.gui` 完成
真实 smoke。运维脚本和文档不得把定义模块写成启动入口。

默认监听 `127.0.0.1:8501`，仅本机可访问。可用参数：

```text
--artifact-root PATH   固定研究产物根；默认是当前目录下 artifacts
--address ADDRESS      Streamlit 监听地址；默认 127.0.0.1
--port PORT            1..65535；默认 8501
--headless             使用 headless 模式
--no-headless          允许自动打开本机浏览器；默认保持 headless
```

G0-C4 验证固定使用 `127.0.0.1:18501`，先确认端口空闲；默认值仍为 8501。不得绑定非回环地址。

## G0-C4 功能 smoke 结果

- overview：34 个可读 run、22 `RESEARCH_ONLY`、12 `REJECTED`、0 `PAPER_CANDIDATE`、0 issue，最大
  `data_end=2026-08-13`；表格使用 `width="stretch"` 正常显示。
- detail：固定 `36b3dd917281…` 在显式校验前锁定 NAV；校验后 4 个清单输出 `VERIFIED`，真实 NAV 曲线
  与表格可见。
- comparison：固定 `36b3dd917281…` 与 `03e6131b4617…` 在显式校验前锁定；校验后两个运行的口径和
  输出完整性 `VERIFIED`，既有 484 行原始 1.0× NAV 以 4 个 run+fold series 正常显示。
- 浏览器 console error 为 0；server 日志中 `use_container_width`、Traceback、Exception、Error 均为 0。
- 浏览器累计 18 条 warning，只有两类 Vega `Infinite extent`（`date`、`unit_nav`）。登记为
  `GUI-DEBT-VEGA-001`：functional smoke PASS，但 strict zero-warning 未关闭。只有 Streamlit/Altair 升级
  或出现空图、console error、曲线缺失时，才做显式输入形态实验；不得为了消警告连接 fold、重算 NAV 或
  改写证据。
- smoke 结束后已关闭浏览器，精确停止 18501 监听叶进程；carrier 因受控停止返回 `-1`，不是应用崩溃。
  目标 env、PID tree、端口、ignored basetemp/log/temp 和 browser tab 均为 0 残留，CPU8–11 已释放。

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
