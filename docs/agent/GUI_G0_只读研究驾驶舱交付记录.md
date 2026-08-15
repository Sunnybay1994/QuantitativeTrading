# GUI G0 只读研究驾驶舱 — 交付记录

## 结果

- 状态：**源码、只读适配层与 optional 依赖声明已交付；真实 Streamlit UI 验收阻塞于安装环境确认**。
- 分支：`codex/gui-research-workbench`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\gui-research-workbench`
- 基线 / 当前 HEAD：`9fc08ba382e491cfcfeebb7b0c14ef06085bf013`
- 修改目的：新增 G0 只读研究运行 catalog、清单/输出完整性、受限 NAV 投影、薄 Streamlit 页面、本地回环
  启动器、聚焦测试和 GUI session 文档。
- 明确未修改：根工作树、既有 artifacts、`data/`、M2/M3 runner、因子、策略、回测、execution、Schema、
  配置、README、AGENTS、项目级路线图、技术调研及各层既有 `__init__.py`。`pyproject.toml` 仅有统筹批准
  的一行 optional group hunk。

## 修改文件及目的

| 文件 | 目的 |
| --- | --- |
| `src/quant/gui/research_runs.py` | 固定根 catalog、完整 V1 清单重建、canonical/run identity、跨平台 link/reparse 防护、精确输出树和 SHA-256、128 MiB 有界完整性、64 MiB/25 万行有界 NAV 投影 |
| `src/quant/gui/app.py` | summary-first 总览、少量筛选、运行详情、显式完整性动作和 1.0× NAV；持续显示只读/无 PAPER/LIVE 边界 |
| `src/quant/gui/launcher.py`、`__main__.py`、`__init__.py` | `python -m quant.gui` 本地回环入口；固定 app、无 shell 插值、关闭遥测/文件监听、缺依赖稳定退出 |
| `tests/unit/test_gui_research_runs.py` | 正常读链、缺根、非规范清单、目录身份漂移、输出篡改、额外文件、链接、非法 NAV 反例 |
| `tests/unit/test_gui_launcher.py` | 缺依赖无副作用、固定命令/环境、端口与非回环地址拒绝 |
| `tests/gui/test_streamlit_app.py` | Streamlit 可用时验证默认空态、详情完整性动作和 NAV 渲染路径 |
| `docs/roadmaps/GUI_投研工作台路线图.md` | 本 session 范围、所有权、阻塞、安全提交点、债项登记、验收和后续队列 |
| `docs/gui/*` | GUI 产品/技术设计、安装启动与运维边界、文档索引 |
| `docs/agent/GUI_G0_只读研究驾驶舱任务单.md` | 冻结目标、接口、失败码、白名单、反例和验证要求 |
| `pyproject.toml` | 新增唯一 optional group `gui = ["streamlit>=1.48,<2"]`；不进入核心/交易运行时 |

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
  审核面；optional group 保持核心/交易运行时隔离。官方仓库/包元数据许可证为 Apache-2.0，无 GPL 类传播
  要求；未来分发保留适用许可证/NOTICE，安装后再核对解析到的传递依赖许可证。

## 验证

| 命令或检查 | 结果 | 证据摘要 |
| --- | --- | --- |
| 定向 pytest（单进程，数值线程 `<=2`） | 通过 / 有明确阻塞 | `13 passed, 2 skipped in 1.36s`；skip 为未安装 Streamlit、Windows 当前账号无 symlink 权限 |
| 定向 Ruff | 通过 | `All checks passed!` |
| 定向 mypy | 通过 | `Success: no issues found in 8 source files` |
| `python -m quant.gui` 无依赖路径 | 通过 | Python 原生退出码 `2`，输出共享依赖锁说明；未启动 Streamlit 子进程 |
| 当前真实 artifacts catalog 探针 | 通过 | 30 个自洽运行、0 issue；22 `RESEARCH_ONLY`、8 `REJECTED`、0 `PAPER_CANDIDATE`；最大 `data_end=2026-08-13` |
| 最小真实 run 完整性/NAV 探针 | 通过 | run `36b3dd917281…`：4 个输出 `VERIFIED`；1.0× NAV `AVAILABLE`，242 行 |
| 根工作树 GUI 白名单路径状态 | 通过 | 无输出；GUI 源码/文档未写入根工作树 |
| worktree 身份 | 通过 | 分支 `codex/gui-research-workbench`，HEAD 为冻结基线 |
| 全量 pytest / WSL Gate | 未运行 | 本任务获批只做定向、单进程验证；不宣称项目 Gate 通过 |
| Streamlit AppTest / 浏览器 smoke | 阻塞 | optional group 已声明；当前环境无 Streamlit，解释器/安装命令待统筹确认 |

说明：第一次 pytest 收集解析到了根工作树的 editable 安装，随后定向命令以当前 worktree `src` 为
`PYTHONPATH`；共享 pytest 临时根还存在权限问题，因此每次测试使用全新的系统临时 `--basetemp`。这些是
环境承载修正，没有修改安装状态、共享依赖或项目代码合同。

## 清理与范围审查

- Ruff/mypy 已清除未使用导入和类型问题；无临时调试代码、自动安装逻辑、Plotly、数据库或任务抽象。
- Git 状态只包含统筹批准的 14 个独占新文件，以及 `pyproject.toml` 唯一获批 optional-group hunk；其他共享
  文件和既有产物无变化。
- 内部 subagent 仅用于互斥的只读项目/产品/在线框架调研，未模拟实现—独立初验；代码由主 Agent 串行实现
  并执行普通定向开发检查。
- Dashboard 构建规范影响：默认页 summary-first，指标定义/来源、空态、异常态和可信度层级均在界面附近
  可见；没有把目录 mtime、缓存或 UI session 当作运行事实。

## 已知限制、债项与下一步

- 当前不能把 GUI 表述为已安装或可运维启动；真实 AppTest、浏览器 overview/detail/chart smoke 待统筹确认
  解释器与安装窗口。
- Windows symlink 对抗性测试因账号权限跳过；实现按 `lstat` 与 reparse attribute fail-closed，仍需在允许创建
  symlink 的 WSL/Linux 定向环境执行该反例后才能形成跨平台证据。
- G0 同步完整性总量上限 128 MiB，NAV 输入上限 64 MiB/25 万行；超限明确 `BLOCKED`，以后交给外置
  verifier，不在 Web session 放宽。
- 公共 orchestration 边界未关闭前不得增加运行按钮；性能优化只有在真实规模可复现、已测量瓶颈后进入。
- 本次安全提交包含 `pyproject.toml` 唯一依赖 hunk及 G0 文件；提交后立即回报 SHA 并释放共享文件锁。下一
  队列是向统筹回报候选解释器/安装命令，获批后再安装、核对解析依赖许可证、运行 AppTest 与本地浏览器
  smoke 并更新本记录。远程共享、鉴权、任务 worker 和交易动作均需独立任务书。
