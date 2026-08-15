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

## 明确非目标

- 不遍历或修补 `data/`，不下载数据，不计算因子、策略、成交或准入结论；
- 不在 Streamlit session 内执行长任务，不建立任务队列、worker、账号或权限系统；
- 不修改任何不可变研究产物，不提供重试覆盖、任意路径、任意 SQL、shell 或动态 import；
- 不提供 PAPER/LIVE、下单、撤单、自动确认或自动晋级入口；
- 不 import 任一 M2 `run_*` 私有 helper，不复制策略、回测或准入逻辑；运行能力以后只通过另行冻结的
  公共应用服务接口接入；
- 不替换项目级路线图、Schema、枚举、配置或依赖 SSOT。

## 分支、worktree 与基线

- 分支：`codex/gui-research-workbench`
- 独立 worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\gui-research-workbench`
- 冻结基线：`9fc08ba382e491cfcfeebb7b0c14ef06085bf013`
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

## 依赖、阻塞与资源边界

- G0 适配层只使用 Python 标准库、项目已有 Polars 与轻量研究清单合同。
- 已获统筹批准在依赖 SSOT 声明 `gui = ["streamlit>=1.48,<2"]`；必要性是提供项目技术调研触发条件下的
  统一 Python 只读审核界面，同时保持 Streamlit 不进入核心/交易运行时依赖。依赖尚未安装，解释器和安装
  命令仍待统筹确认，不启动 GUI 服务。
- 许可证核对：[Streamlit 官方仓库](https://github.com/streamlit/streamlit)和包元数据均标记 Apache-2.0；
  它是宽松许可证，无 GPL 类传播要求，未来分发仍需保留其许可证/NOTICE 等适用义务。安装后再核对解析
  到的传递依赖清单。
- 未安装时的降级语义：catalog、完整性、NAV 与启动器单测继续可用；`python -m quant.gui` 不自动安装、
  不启动子进程，以稳定退出码 2 说明缺少 optional group。
- UI 测试在 Streamlit 缺失时显式跳过；这不代表真实 UI 已验收。
- 测试只运行定向目标、单进程、线程不超过 2；不运行全量 Gate，不启动外部 Agent，不占用项目长任务的
  专用资源。

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

当前 G0-C1 至 G0-C3 已形成安全提交；G0-C4 已完成依赖声明，但批准环境的创建承载失败，阻塞于新的恢复
裁决。这里的状态只描述本 session 的工作队列，
不代表项目级里程碑完成。

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

## 后续队列

在 G0 证据闭合并获得新的文件/依赖授权后，再依次评估：持久化 Job/Run repository、外置 worker、数据质量
中心、受控因子/策略注册表、运行比较、报告中心、晋级只读视图、运维与审计。任何交易写操作都需要单独任务
书、权限模型、人工确认和既有执行服务接缝，不由本路线图预先授权。
