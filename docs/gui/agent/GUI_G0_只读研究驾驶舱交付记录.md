# GUI G0 只读研究驾驶舱 — 交付记录

## 结果

- 状态：**G0/G1 只读功能 smoke PASS；Streamlit API 弃用修复已验证，`GUI-DEBT-VEGA-001` 仍开放，
  strict zero-warning 未关闭**。
- 当前分支：`codex/gui-g0-c4-smoke`
- 当前 worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\gui-g0-c4-smoke`
- G0-C4 冻结父提交：`4fa5d21a9c99c125ba0dadb8c732cca2681b34ba`
- 修改目的：在既有 G0/G1 只读研究驾驶舱上把 Streamlit 下限提高到 1.49，将 12 处 dataframe 迁移到
  `width="stretch"`，完成 AppTest 与 overview/detail/comparison 真实浏览器 functional smoke，并固化诚实
  的 renderer 债和环境边界。
- 明确未修改：根工作树、既有 artifacts、`data/`、M2/M3 runner、因子、策略、回测、execution、Schema、
  配置、README、AGENTS、项目级路线图、技术调研及各层既有 `__init__.py`。`pyproject.toml` 仅有统筹批准
  的一行 optional group hunk。

## 修改文件及目的

| 文件 | 目的 |
| --- | --- |
| `src/quant/gui/research_runs.py` | 固定根 catalog、完整 V1 清单重建、canonical/run identity、跨平台 link/reparse 防护、精确输出树和 SHA-256、128 MiB 有界完整性、64 MiB/25 万行有界 NAV 投影 |
| `src/quant/gui/app.py` | summary-first 总览、运行详情/比较、显式完整性动作和 1.0× NAV；12 处 `st.dataframe` 使用 `width="stretch"`，持续显示只读/无 PAPER/LIVE 边界 |
| `src/quant/gui/launcher.py`、`__main__.py`、`__init__.py` | `python -m quant.gui` 本地回环入口；固定 app、无 shell 插值、关闭遥测/文件监听、缺依赖稳定退出 |
| `tests/unit/test_gui_research_runs.py` | 正常读链、缺根、非规范清单、目录身份漂移、输出篡改、额外文件、链接、非法 NAV 反例 |
| `tests/unit/test_gui_launcher.py` | 缺依赖无副作用、固定命令/环境、端口与非回环地址拒绝 |
| `tests/gui/test_streamlit_app.py` | 3 个 AppTest 覆盖默认空态、详情完整性和比较路径；首个测试同时锁定旧参数为 0、新参数为 12 处 |
| `docs/gui/roadmaps/GUI_投研工作台路线图.md` | 本 session 范围、所有权、阻塞、安全提交点、债项登记、验收和后续队列 |
| `docs/gui/*` | GUI 产品/技术设计、安装启动与运维边界、文档索引 |
| `docs/gui/agent/GUI_G0_只读研究驾驶舱任务单.md` | 冻结目标、接口、失败码、白名单、反例和验证要求 |
| `pyproject.toml` | optional group 最小调整为 `gui = ["streamlit>=1.49,<2"]`；不进入核心/交易运行时 |

## 设计与合同证据

- GUI 只 import 稳定 lightweight manifest 合同与 canonical encoder；未 import 任一 M2 `run_*` 私有 helper，
  未复制策略、回测或准入逻辑。
- 运行发现只访问受信任 `<artifact_root>/research/runs` 的直接 64 位十六进制子目录；一个坏条目只产生
  结构化 issue，不拖垮其他清单。
- catalog 只有在严格 UTF-8/canonical JSON、精确 V1 字段、原 dataclass 合同、内容身份和目录身份都一致时
  才产出摘要。
- 输出校验拒绝 symlink/junction/reparse/特殊文件，要求目录和文件集合精确一致，再流式核对 size/SHA-256。
- NAV 在完整性 `VERIFIED` 后重新读取同一精确字节并复核 digest；只接受必要列、类型、非空、有限正值、
  合法 fold、数据窗口、唯一键和 1.0× 成本路径，不重算研究指标或改变结论。
- 同步校验和 NAV 都有界；无数据库、队列、缓存权威、权限框架或运行编排抽象。
- 启动器只接受 loopback，页面不接受 arbitrary artifact path；缺 Streamlit 不安装、不写文件、不启动子进程。
- 依赖必要性：项目已满足“需要统一审核界面”的技术触发条件，Streamlit 以最低前端认知成本提供纯 Python
  审核面；optional group 保持核心/交易运行时隔离。实际解析元数据为 Streamlit Apache-2.0、Altair BSD
  license text、pydeck Apache-2.0、toml MIT、watchdog Apache-2.0；未来分发保留适用许可证/NOTICE，并按
  实际版本复核。

## 验证

| 命令或检查 | 结果 | 证据摘要 |
| --- | --- | --- |
| 依赖安装与版本 | 通过 | 唯一 Windows venv；Python `3.13.13`、Streamlit `1.61.1`、pytest `9.1.1`；editable `[gui]` exit 0，`quant` 从当前 worktree 导入 |
| `pip check` | 通过 | `No broken requirements found.` |
| AppTest | 通过 | `3 passed, 3 warnings in 12.99s`；stderr 0；旧 `use_container_width` 告警 0；3 条 warning 为 `importlib.metadata` |
| overview 真实路径 | functional PASS | 34 个可读 run、22 `RESEARCH_ONLY`、12 `REJECTED`、0 `PAPER_CANDIDATE`、0 issue；最大 `data_end=2026-08-13` |
| detail 真实路径 | functional PASS | 固定 `36b3dd917281…`：校验前 NAV 锁定；校验后 4 outputs `VERIFIED`，真实曲线/表可见 |
| comparison 真实路径 | functional PASS | 固定 `36b3dd917281…` + `03e6131b4617…`：校验前锁定；校验后 2 runs 口径/输出 `VERIFIED`，484 行、4 个 run+fold series 可见 |
| 浏览器 console | 部分通过 | 0 error；18 warn、2 个唯一 Vega `Infinite extent`（`date`、`unit_nav`）；登记 `GUI-DEBT-VEGA-001`，strict zero-warning 未关闭 |
| 服务日志 | 通过 | 正确入口 `python -m quant.gui`；`use_container_width`、Traceback、Exception、Error 均为 0 |
| 环境与资源清理 | 通过 | env、PID tree、18501 端口、ignored basetemp/log/temp、browser tab 均为 0 残留；CPU8–11 已释放 |
| 全量 pytest / WSL Gate | 未运行 | G0-C4 是 Windows UI 反馈环；不得表述为项目 Gate 或 Linux 文件系统语义通过 |

全部 G0-C4 子进程由 .NET `System.Diagnostics.Process` carrier 用 `ArgumentList`、
`UseShellExecute=false`、`CreateNoWindow=true`、异步 stdout/stderr 和真实退出码串行承载；取得 PID 后设置
BelowNormal、affinity `0xF00`，数值线程不超过 2。venv 采用 `--system-site-packages`，借用了
`D:\Miniforge3` 依赖，因此 `pip check` 和 functional smoke 不证明独立依赖闭包，也不能替代 WSL `base` Gate。

一次启动诊断误用了定义模块 `python -m quant.gui.launcher`，其 exit 0 但没有监听端口或残留进程；只读确认
`src/quant/gui/__main__.py` 后，改用正式入口 `python -m quant.gui` 完成全链。旧 G0 阶段两次
Hidden `Start-Process` 创建失败仍由安全点 `75b6419c3e0bcf5c1e1924ed02dd6fda87bd53b5` 保留；本轮使用新冻结
的可观测 .NET carrier，不把旧失败记录抹去或冒充成功。

## 清理与范围审查

- G0/G1 已有 Ruff/mypy 证据保持有效；G0-C4 只改 Streamlit 参数、依赖下限、现有 AppTest 断言和三份文档，
  无自动安装逻辑、Plotly、数据库、队列、权限或运行编排抽象。
- G0-C4 提交前 Git cached 范围必须精确为 6 个获批路径；`pyproject.toml` 只有 Streamlit 下限 1.48→1.49
  的 hunk，`app.py` 只有 12 处 `use_container_width=True`→`width="stretch"`，不修改 `line_chart`。
- 内部 subagent 仅用于互斥的只读项目/产品/在线框架调研，未模拟实现—独立初验；代码由主 Agent 串行实现
  并执行普通定向开发检查。
- Dashboard 构建规范影响：默认页 summary-first，指标定义/来源、空态、异常态和可信度层级均在界面附近
  可见；没有把目录 mtime、缓存或 UI session 当作运行事实。

## 已知限制、债项与下一步

- Windows functional smoke 已通过，但短生命周期环境已按合同删除；没有常驻 GUI 服务或可复用的独立依赖
  闭包。下次反馈环仍需新的资源窗口，不能修改 Windows/WSL base。
- `GUI-DEBT-VEGA-001` 仍开放：最终 484 行、4 series 曲线可见且 console error 为 0，但累计 18 条、两类
  Vega `Infinite extent` warn。只有 Streamlit/Altair 升级或出现空图、console error、曲线缺失时才触发显式
  输入形态实验；不连接 fold、不重算 NAV、不改写不可变证据。不得宣称 strict zero-warning C4 通过。
- Windows symlink 对抗性测试因账号权限跳过；实现按 `lstat` 与 reparse attribute fail-closed，仍需在允许创建
  symlink 的 WSL/Linux 定向环境执行该反例后才能形成跨平台证据。
- G0 同步完整性总量上限 128 MiB，NAV 输入上限 64 MiB/25 万行；超限明确 `BLOCKED`，以后交给外置
  verifier，不在 Web session 放宽。
- 公共 orchestration 边界未关闭前不得增加运行按钮；性能优化只有在真实规模可复现、已测量瓶颈后进入。
- 既有 G0 安全提交为 `6640b791cf0fab6f996aea014293a618d2e5a22e`，G1 安全提交为
  `a5c63f7c8ca1d763b934c13330e793c65da27842`。本文所在 G0-C4 最多 6 路径提交只关闭 functional smoke 与
  Streamlit API 弃用问题；renderer 债、独立依赖闭包和 WSL Gate 保持开放。远程共享、鉴权、任务 worker、
  GUI 发起运行和任何交易动作均需独立任务书及公共 orchestration 边界。
