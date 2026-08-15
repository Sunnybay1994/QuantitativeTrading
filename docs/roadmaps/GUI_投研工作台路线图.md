# GUI 投研工作台路线图

## 文档边界

本文只管理 GUI session 的范围、所有权、阻塞、验收与下一队列，不定义或改写项目级里程碑状态。
项目 Gate、阶段与实施顺序以根目录
[`项目实施路线图.md`](../../项目实施路线图.md) 为唯一事实来源；GUI 技术选型依据
[`A股港股通个人量化投研交易系统调研.md`](../../A股港股通个人量化投研交易系统调研.md)。

## 目标与范围

目标是把现有量化框架包装成研究员可直接使用、可审计、可恢复的投研工作台，使研究员把精力放在因子、
策略和证据判断上。GUI 只做薄控制面与不可变结果投影，领域计算仍由现有 `quant.data`、`quant.factors`、
`quant.strategies`、`quant.backtest`、`quant.execution` 和 `quant.reporting` 边界负责。

当前 G0 范围：

- 只读发现 `artifacts/research/runs/<run_id>/run.json`；
- 展示运行数量、研究结论、策略、数据窗口、核心指标、时间语义、fold、caveat 与输出清单；
- 区分“清单自洽”与“输出完整性已验证”，完整性通过后才读取并展示 NAV；
- 提供受控本地启动器，依赖缺失时给出明确、无副作用的失败信息；
- 用聚焦单元测试覆盖路径逃逸、重解析点、清单篡改、输出篡改和空目录。

当前 G1 范围：

- 从 G0 canonical catalog 中显式选择 2–4 个唯一运行；
- 只有数据窗口、universe 身份、时间语义、fold、成本倍数、选模指标、聚合指标名称和完整 input 证据逐项
  一致时才允许比较；
- 逐 run 重新验证 manifest identity、精确输出树、size/SHA-256；任一失败则整份比较证据 fail-closed；
- 全部验证后按选择顺序并排展示 manifest 原有 metrics、hypothesis、caveats、input/output；
- 只有每个运行的 NAV 都通过现有有界读取与 digest 复核时才叠加原始 1.0× 行；只增加显示标签。

## 明确非目标

- 不遍历或修补 `data/`，不下载数据，不计算因子、策略、成交或准入结论；
- 不在 Streamlit session 内执行长任务，不建立任务队列、worker、账号或权限系统；
- 不修改任何不可变研究产物，不提供重试覆盖、任意路径、任意 SQL、shell 或动态 import；
- 不提供 PAPER/LIVE、下单、撤单、自动确认或自动晋级入口；
- 不计算跨 run 排名、差值、均值、胜负、收益/风险指标或准入结论，不解析其他报告补齐指标；
- 不 import 任一 M2 `run_*` 私有 helper，不复制策略、回测或准入逻辑；运行能力以后只通过另行冻结的
  公共应用服务接口接入；
- 不替换项目级路线图、Schema、枚举、配置或依赖 SSOT。

## 分支、worktree 与基线

- 唯一 owner：GUI session（本任务）；其他 session 不在本 worktree 写入或提交。
- 分支：`codex/gui-research-workbench`
- 独立 worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\gui-research-workbench`
- 冻结基线：`9fc08ba382e491cfcfeebb7b0c14ef06085bf013`
- G1 父提交 HEAD：`75b6419c3e0bcf5c1e1924ed02dd6fda87bd53b5`；G1 已完成定向验证并形成本文所在的安全提交，完整 SHA 以 Git 记录为准。
- G0 代码与 optional 依赖安全点：`6640b791cf0fab6f996aea014293a618d2e5a22e`。
- G0 smoke 环境失败记录安全点：`75b6419c3e0bcf5c1e1924ed02dd6fda87bd53b5`。
- 根工作树：只读，GUI session 不在其中写入或合流。

## 文件与文档所有权

本 session 仅拥有以下独占新文件：

```text
src/quant/gui/__init__.py
src/quant/gui/__main__.py
src/quant/gui/launcher.py
src/quant/gui/app.py
src/quant/gui/research_runs.py
tests/unit/test_gui_launcher.py
tests/unit/test_gui_research_runs.py
tests/gui/test_streamlit_app.py
docs/roadmaps/GUI_投研工作台路线图.md
docs/gui/README.md
docs/gui/GUI_产品与技术设计.md
docs/gui/GUI_安装启动与运维手册.md
docs/agent/GUI_G0_只读研究驾驶舱任务单.md
docs/agent/GUI_G0_只读研究驾驶舱交付记录.md
```

共享 SSOT 均保持锁定，包括 `AGENTS.md`、`README.md`、`项目实施路线图.md`、`docs/README.md`、
`docs/用户待批示与参与事项.md`、`pyproject.toml`、`src/quant/domain/schemas.py`、各层已有
`__init__.py` 与技术调研文档。`docs/roadmaps/README.md` 及项目结构治理路线图由统筹任务维护。
其中 `pyproject.toml` 的唯一批准 hunk 已随 G0 提交；当前状态是**重新锁定且不得继续修改**，不是尚未声明。

G1 获准只修改上述已有文件中的以下 6 个，不新增文件：

```text
src/quant/gui/research_runs.py
src/quant/gui/app.py
tests/unit/test_gui_research_runs.py
tests/gui/test_streamlit_app.py
docs/roadmaps/GUI_投研工作台路线图.md
docs/gui/GUI_产品与技术设计.md
```

## 依赖、阻塞与资源边界

- G0 适配层只使用 Python 标准库、项目已有 Polars 与轻量研究清单合同。
- 已获统筹批准在依赖 SSOT 声明 `gui = ["streamlit>=1.48,<2"]`；必要性是提供项目技术调研触发条件下的
  统一 Python 只读审核界面，同时保持 Streamlit 不进入核心/交易运行时依赖。该声明已经提交在
  `6640b791`，随后共享依赖 SSOT 重新锁定；依赖仍未安装，不启动 GUI 服务。
- 许可证核对：[Streamlit 官方仓库](https://github.com/streamlit/streamlit)和包元数据均标记 Apache-2.0；
  它是宽松许可证，无 GPL 类传播要求，未来分发仍需保留其许可证/NOTICE 等适用义务。安装后再核对解析
  到的传递依赖清单。
- 未安装时的降级语义：catalog、完整性、NAV 与启动器单测继续可用；`python -m quant.gui` 不自动安装、
  不启动子进程，以稳定退出码 2 说明缺少 optional group。
- UI 测试在 Streamlit 缺失时显式跳过；这不代表真实 UI 已验收。
- 测试只运行定向目标、单进程、线程不超过 2；不运行全量 Gate，不启动外部 Agent，不占用项目长任务的
  专用资源。
- G1 编码与验证分离：编码可在独立 worktree 进行；pytest/Ruff/mypy 与真实 artifacts 探针等待项目统一串行
  资源队列，轮到时仅用 BelowNormal、CPU8–11（mask `0xF00`）、数值线程不超过 2。项目级 basetemp 必须
  位于本 worktree 的 ignored `artifacts/` 下并在完成后精确清理；本机只有 CPU0–11，不使用无效 mask。

## 已形成的 G0 安全证据

| 证据 | 结果 | 边界 |
| --- | --- | --- |
| 定向 pytest | `13 passed, 2 skipped in 1.36s` | skip 为 Streamlit 未安装与 Windows 当前账号无 symlink 权限；不是 UI 或 WSL Gate |
| 定向 Ruff | `All checks passed!` | 只覆盖 G0 获批源码/测试范围 |
| 定向 mypy | `Success: no issues found in 8 source files` | 只覆盖 G0 获批源码/测试范围 |
| 缺依赖启动器 | 稳定退出码 2、无子进程 | 证明降级语义，不证明真实 UI 可启动 |
| 真实 artifacts 只读探针 | 30 个自洽 run、0 issue；最小 run 输出 `VERIFIED`，NAV `AVAILABLE` | 当时快照，只读证据，不硬编码到 UI，不代表项目 Gate |
| Windows smoke 环境创建 | 两次受控承载均以 `-1`、无环境/日志/残留终止 | 记录于 `75b6419`；pip/AppTest/browser 未运行，禁止第三次重试 |

## G1 定向验证证据

全部检查均在统筹正式释放 CPU8–11 后串行执行，carrier 为 BelowNormal、affinity `0xF00`，数值线程不超过 2；
没有创建或安装 Streamlit 环境。

| 证据 | 结果 | 边界 |
| --- | --- | --- |
| 定向 pytest | `23 passed, 2 skipped in 1.76s` | skip 仍为 Streamlit 未安装与 Windows symlink 权限；不是 AppTest/browser 或 WSL Gate |
| 定向 Ruff | `All checks passed!` | 只覆盖 GUI 包与对应定向测试 |
| 定向 mypy | `Success: no issues found in 8 source files` | 只覆盖 GUI 包与对应定向测试 |
| 真实 immutable runs 只读比较 | catalog 32 runs / 0 issue；两个固定 run 的 4/5 个输出均验证，comparison `VERIFIED` | 当时只读快照；未写或修改 artifact，不形成排名或准入判断 |
| 已验证 NAV 拼接 | `AVAILABLE`，484 行，selection order `[1, 2]` | 只拼接已有 1.0× 行与显示标签，不重算业务指标 |
| 项目级 basetemp | pytest 结束后不存在 | 精确目标为 ignored `artifacts/test_tmp/gui-g1-basetemp` |

## 可控基础设施债登记

当前以闭合只读业务路径为主。以下债项不放宽安全、PIT、fail-closed、统一回放、OMS/风控/对账或人工准入：

| 债项与 owner | 当前影响 | 延期理由 | 触发条件 | 通过标准 | 临时处置 |
| --- | --- | --- | --- | --- | --- |
| 公共 orchestration 应用服务边界；GUI session 提接缝需求，项目统筹裁决共享接口 | GUI 不得发起研究运行 | G0 只读闭环不需要任务执行；私有 runner helper 不是稳定公共接口 | 用户要求从 GUI 发起运行或进入对应项目 Gate | 类型化公共用例、幂等 JobSpec、持久化状态、资源/恢复/取消和失败语义由权威后端冻结并测试；GUI 只提交请求 | 不显示运行按钮，不 import `run_*`，只投影不可变结果 |
| Streamlit 安装与真实 AppTest；GUI session + 环境资源 owner | optional group 已声明；批准的 Windows venv 创建承载两次以 `-1`、无日志终止，目标环境未产生，真实 UI 仍不可启动 | 已按停止条件结束尝试并释放 CPU8–11；根因尚无证据，禁止第三次盲试；不得改变任何 base | 统筹冻结新的可观测创建机制或确认承载层根因与恢复条件 | 唯一批准环境创建成功，解析后许可证清单核对，`pip check`、AppTest 及本地浏览器 overview/detail/chart 路径通过，且无残留进程 | 启动器缺依赖稳定退出；UI 测试显式 skip/blocked；安全代码提交保持 clean |
| 大规模 manifest 性能；GUI session | 未来运行数量或输出哈希量增长时可能变慢 | 目前没有真实可复现瓶颈，提前缓存/索引会增加第二事实来源风险 | 真实 manifest 规模下出现可重现延迟或内存超标，并有基准数据 | 先记录数据量、延迟、内存与热点，再做保持身份/失败语义的最小优化和回归基准 | 直接、有界、无缓存权威地扫描固定 runs 根；同步校验上限 128 MiB |
| 远程共享、认证与 RBAC；未来独立安全任务 owner | G0 仅本机使用，不能安全开放给多人 | 本机只读闭环不需要网络暴露，提前建设权限框架超出当前业务目标 | 明确多人/远程访问需求 | 鉴权、RBAC、TLS/反代、审计、秘密处理和威胁模型通过独立安全验收 | 启动器强制 loopback；无远程部署说明或绕过开关 |

性能工作遵循“先测量、再实施”：不得因推测添加 catalog 数据库、缓存索引、并行扫描或后台队列。

## 安全提交点与当前队列

| 安全提交点 | 内容 | 进入条件 |
| --- | --- | --- |
| G0-C1 | 路线图、任务书、产品/技术设计、运维说明 | 范围、失败语义、文件白名单冻结 |
| G0-C2 | 只读 catalog、清单校验、输出完整性与 NAV 投影 | 聚焦单元测试和静态检查通过 |
| G0-C3 | Streamlit 薄 UI 与启动器 | 无依赖路径可测；UI 源码不产生副作用 |
| G0-C4 | 真实 Streamlit AppTest 与本地浏览器 smoke | 共享依赖锁释放并完成依赖声明/安装 |
| G1-C1 | 2–4 run 严格比较、整体完整性与 NAV fail-closed 纯逻辑 | G1 6 文件白名单与合同冻结 |
| G1-C2 | “运行比较”薄页面、纯逻辑/条件 AppTest 与文档同步 | G1-C1 完成且不增加任何执行能力 |
| G1-C3 | 定向 pytest/Ruff/mypy 与真实 immutable artifacts 只读探针 | 项目统一串行资源队列轮到 GUI |

当前 G0-C1 至 G0-C3 已形成安全提交；G0-C4 已完成依赖声明，但批准环境的创建承载失败，阻塞于新的恢复
裁决。G1-C1 至 G1-C3 已在获批的 6 个已有文件内完成并取得上述定向证据，本文所在 G1 安全提交等待统筹合流。这里的状态只描述
本 session 的工作队列，
不代表项目级里程碑完成。

## G1 安全提交、合流与 worktree 退出条件

- **安全提交**：只有统一资源队列轮到 GUI，定向 pytest、Ruff、mypy、真实 immutable artifacts 只读探针
  实际完成，ignored basetemp 精确清理，且 cached diff 仍严格为获批 6 文件时，才形成 G1 提交。Streamlit
  AppTest/browser 未验必须继续写在提交交付口径中，不能因纯逻辑绿测被抹去。
- **合流**：GUI session 只回报 G1 commit SHA、父提交、exact file list、验证结果和残余风险；由项目统筹在
  独立 integration 分支执行冲突审计与合流。不得从本 session 直接写根 writer checkout、修改中央 SSOT
  或自行宣称项目 Gate 完成。
- **worktree 删除**：仅当 G0/G1 提交均已被统筹确认纳入目标集成历史、分支无未提交改动、ignored
  basetemp/GUI 进程/批准但失败的 smoke venv 均无残留、G0 真实 UI smoke 债项已在后续 owner/路线图中保留，
  且统筹明确批准退出后，才可删除本 worktree。未满足任一条件时继续保留，不做目录移动或根级清理。

## G0 验收标准

- 默认页在不交互时回答：有多少可读运行、各结论分布、哪些条目异常、数据覆盖到何时；
- 只接受直接位于固定 runs 根目录下的 64 位小写十六进制运行目录；缺失、损坏或危险条目作为结构化问题
  展示，不静默吞掉；
- `run.json` 必须是 UTF-8 规范 JSON、与目录/内容身份一致，并通过轻量研究 V1 合同重建；
- 输出树必须无链接/重解析点、无额外或缺失文件，且 size/SHA-256 全部匹配后才能读取 NAV；
- G0 同步完整性校验总量上限为 128 MiB；超限明确阻塞，未来交给外置 verifier，不在 Web session
  执行无界哈希；
- NAV 只做 schema 与有限值校验，不重算研究指标，不改变结论；
- 缺少 Streamlit 时 `python -m quant.gui` 以稳定非零码退出并给出依赖声明阻塞说明；
- Git diff 只包含本页列出的独占新文件。

## G1 验收标准

- 仅接受 2–4 个唯一、已由 catalog 验证的运行；保持用户选择顺序，数量或重复错误以结构化状态阻塞；
- 可比较字段必须逐项一致，完整 inputs 与 aggregate metric 名称也属于口径；策略/版本、假设、seed、
  config/code identity、结论、指标值、caveat 和输出清单只作逐 run 实验维度；
- 所选运行声明输出合计不超过 128 MiB；任一 identity、输出树、size 或 digest 不闭合时不显示部分比较证据；
- 指标只展示 manifest 原值，不排序、不排名、不求差值/均值，也不从 NAV 或 `report.json` 重算；
- NAV 仅在所有运行输出验证后逐一重新复核，合并上限 250,000 行；任一缺失、非法、漂移或超限时整图
  `BLOCKED`，不退化为部分曲线；
- pytest、Ruff、mypy 和真实 artifacts 探针只有在统一资源队列轮到 GUI 后运行；Streamlit AppTest/browser
  因批准环境未创建继续明确未验证，不得用源码测试表述为真实 UI smoke 通过。

## 后续队列

在 G0 证据闭合并获得新的文件/依赖授权后，再依次评估：持久化 Job/Run repository、外置 worker、数据质量
中心、受控因子/策略注册表、运行比较、报告中心、晋级只读视图、运维与审计。任何交易写操作都需要单独任务
书、权限模型、人工确认和既有执行服务接缝，不由本路线图预先授权。
