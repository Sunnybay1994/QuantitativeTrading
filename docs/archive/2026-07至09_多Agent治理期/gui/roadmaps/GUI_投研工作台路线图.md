# GUI 投研工作台路线图

## 文档边界

本文只管理 GUI session 的范围、所有权、阻塞、验收与下一队列，不定义或改写项目级里程碑状态。
项目 Gate、阶段与实施顺序以根目录
[`项目实施路线图.md`](../../../../../项目实施路线图.md) 为唯一事实来源；GUI 技术选型依据
[`A股港股通个人量化投研交易系统调研.md`]（历史路径 `../../../A股港股通个人量化投研交易系统调研.md`，当前仓库未收录）。

## 目标与范围

目标是把现有量化框架包装成研究员可直接使用、可审计、可恢复的投研工作台，使研究员把精力放在因子、
策略和证据判断上。GUI 只做薄控制面与不可变结果投影，领域计算仍由现有 `quant.data`、`quant.factors`、
`quant.strategies`、`quant.backtest`、`quant.execution` 和 `quant.reporting` 边界负责。

已交付 G0 范围：

- 只读发现 `artifacts/research/runs/<run_id>/run.json`；
- 展示运行数量、研究结论、策略、数据窗口、核心指标、时间语义、fold、caveat 与输出清单；
- 区分“清单自洽”与“输出完整性已验证”，完整性通过后才读取并展示 NAV；
- 提供受控本地启动器，依赖缺失时给出明确、无副作用的失败信息；
- 用聚焦单元测试覆盖路径逃逸、重解析点、清单篡改、输出篡改和空目录。

已交付 G1 范围：

- 从 G0 canonical catalog 中显式选择 2–4 个唯一运行；
- 只有数据窗口、universe 身份、时间语义、fold、成本倍数、选模指标、聚合指标名称和完整 input 证据逐项
  一致时才允许比较；
- 逐 run 重新验证 manifest identity、精确输出树、size/SHA-256；任一失败则整份比较证据 fail-closed；
- 全部验证后按选择顺序并排展示 manifest 原有 metrics、hypothesis、caveats、input/output；
- 只有每个运行的 NAV 都通过现有有界读取与 digest 复核时才叠加原始 1.0× 行；只增加显示标签。

已交付 G1-D1 范围：

- 严格比较精确返回 `COMPARISON_CONTRACT_MISMATCH` 时，增加只读比较口径关系诊断；
- diagnosis 与 verifier 直接共享现有 `_comparison_contract` 的唯一 14 字段机器定义，并在内部生成全量
  14 字段关系；
- UI 只渲染至少含一个 `DIFFERENT` 的字段行；用户选择第一项只作为 `REFERENCE`，其余项按选择顺序
  显示 `SAME` 或 `DIFFERENT`；
- 不显示合同字段原值、部分 metric/NAV、兼容子集、推荐、排名或准入，不改变既有 fail-closed 门禁与
  output-hash 前失败顺序。

已冻结 G1-D2 范围（实现、独立初验与 focused 验证已通过；等待安全提交/合流）：

- 在现有 canonical catalog 上增加唯一 `filter_research_runs` 纯筛选函数，保持输入运行原序和对象 identity；
- 结论与策略仍为 exact membership；运行检索只对 `run_id`、`hypothesis_id`、策略名/版本及其组合做
  `strip().casefold()` 后的 literal substring 匹配；
- 总览增加最多 128 字符的 `搜索运行` 与 `Caveat` 三态筛选（`ALL` / `PRESENT` / `ABSENT`），空选择和
  非法模式按冻结合同 fail-closed；
- 六张 KPI 卡继续统计完整 canonical catalog，表格显示筛选计数；筛选不触发 output verifier、NAV、hash、
  运行产物读取、排名、推荐、准入或任何运行编排能力。

## 明确非目标

- 不遍历或修补 `data/`，不下载数据，不计算因子、策略、成交或准入结论；
- 不在 Streamlit session 内执行长任务，不建立任务队列、worker、账号或权限系统；
- 不修改任何不可变研究产物，不提供重试覆盖、任意路径、任意 SQL、shell 或动态 import；
- 不提供 PAPER/LIVE、下单、撤单、自动确认或自动晋级入口；
- 不计算跨 run 排名、差值、均值、胜负、收益/风险指标或准入结论，不解析其他报告补齐指标；
- 不在 G1-D1 展示合同字段原值、摘要、长度、digest 或差异内容，不计算相似度，不寻找或推荐兼容子集；
- 不 import 任一 M2 `run_*` 私有 helper，不复制策略、回测或准入逻辑；运行能力以后只通过另行冻结的
  公共应用服务接口接入；
- 不替换项目级路线图、Schema、枚举、配置或依赖 SSOT。

## 分支、worktree 与基线

- 唯一文档 owner：GUI session；当前 G1-D2 active topology 为 exact base
  `ac57ce9e40dc6731e1106b2fa2398f4013fa19da`、branch `codex/gui-g1-d2-run-search`、worktree
  `F:/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/gui-g1-d2-run-search`；exact7 active，包含 6 个
  实现路径与 1 个 manager-owned taskbook，任务书对实现 Agent 只读。
- G1-D1 历史冻结基线：`2a376100a50fb0ad5040048e4ba2aae8c974ace9`；source
  `9f42b3c81a3a5e4e70ec4a0c85e0c7695b9d1736` 已经 integration merge
  `8427c83ddad62690b1f75d391ed1178fd3f6f415` 吸收，并以
  `archive/gui-g1-d1-comparison-diagnostics-20260816` 留档。来源 branch 与 worktree 已 archive-first 退休。
- 历史 G0-C4 冻结父提交：`4fa5d21a9c99c125ba0dadb8c732cca2681b34ba`。
- 历史 G1 安全提交：`a5c63f7c8ca1d763b934c13330e793c65da27842`；已由统筹 no-ff 纳入后续
  integration 历史，并已包含在历史 G1-D1 基线中。
- G0 代码与 optional 依赖安全点：`6640b791cf0fab6f996aea014293a618d2e5a22e`。
- G0 smoke 环境失败记录安全点：`75b6419c3e0bcf5c1e1924ed02dd6fda87bd53b5`。
- 根工作树：只读，GUI session 不在其中写入或合流。

## 文件与文档所有权

历史 G1-D1 包的 exact 文件白名单为以下 7 个路径：

```text
src/quant/gui/research_runs.py
src/quant/gui/app.py
tests/unit/test_gui_research_runs.py
tests/gui/test_streamlit_app.py
docs/gui/GUI_产品与技术设计.md
docs/gui/roadmaps/GUI_投研工作台路线图.md
docs/gui/agent/GUI_G1_D1_严格比较口径诊断任务与交付记录.md
```

该白名单已随 G1-D1 安全提交、合流与来源线退出关闭；当前不授权继续写这些路径。后续 GUI 窄包必须由
统筹基于当时最新 integration 重新冻结 exact base、owner、白名单和资源窗口。

以下为历史 G0/G1 owner 集合，不构成当前写白名单：

```text
src/quant/gui/__init__.py
src/quant/gui/__main__.py
src/quant/gui/launcher.py
src/quant/gui/app.py
src/quant/gui/research_runs.py
tests/unit/test_gui_launcher.py
tests/unit/test_gui_research_runs.py
tests/gui/test_streamlit_app.py
docs/gui/roadmaps/GUI_投研工作台路线图.md
docs/gui/README.md
docs/gui/GUI_产品与技术设计.md
docs/gui/GUI_安装启动与运维手册.md
docs/gui/agent/GUI_G0_只读研究驾驶舱任务单.md
docs/gui/agent/GUI_G0_只读研究驾驶舱交付记录.md
```

共享 SSOT 均保持锁定，包括 `AGENTS.md`、`README.md`、`项目实施路线图.md`、`docs/README.md`、
`docs/governance/用户待批示与参与事项.md`、`src/quant/domain/schemas.py`、各层已有
`__init__.py` 与技术调研文档。`docs/governance/roadmaps/README.md` 及项目结构治理路线图由统筹任务维护。
`pyproject.toml` 在 G0-C4 只临时释放唯一 hunk：把 optional group 的 Streamlit 下限从 1.48 提高到 1.49；
不得修改其他依赖、工具配置或锁文件，安全提交后重新锁定。

历史 G1 获准修改以下 6 个既有文件：

```text
src/quant/gui/research_runs.py
src/quant/gui/app.py
tests/unit/test_gui_research_runs.py
tests/gui/test_streamlit_app.py
docs/gui/roadmaps/GUI_投研工作台路线图.md
docs/gui/GUI_产品与技术设计.md
```

历史 G0-C4 安全提交严格限定为以下 6 个既有路径：

```text
pyproject.toml
src/quant/gui/app.py
tests/gui/test_streamlit_app.py
docs/gui/roadmaps/GUI_投研工作台路线图.md
docs/gui/GUI_安装启动与运维手册.md
docs/gui/agent/GUI_G0_只读研究驾驶舱交付记录.md
```

## 依赖、阻塞与资源边界

- G0 适配层只使用 Python 标准库、项目已有 Polars 与轻量研究清单合同。
- 依赖 SSOT 当前声明 `gui = ["streamlit>=1.49,<2"]`；1.49 是 `st.dataframe(width="stretch")` 的
  官方支持下限。Streamlit 仍只属于 optional GUI 反馈环，不进入核心/交易运行时依赖。
- 许可证核对：[Streamlit 官方仓库](https://github.com/streamlit/streamlit)和包元数据均标记 Apache-2.0；
  它是宽松许可证，无 GPL 类传播要求，未来分发仍需保留其许可证/NOTICE 等适用义务。安装后再核对解析
  到的传递依赖清单。
- G0-C4 使用唯一 Windows venv 和 `--system-site-packages` 完成功能 smoke 后已精确删除环境。借用
  system site packages 的反馈环不证明独立依赖闭包，也不能替代 WSL `base` Gate。
- 未安装时的降级语义不变：catalog、完整性、NAV 与启动器单测继续可用；`python -m quant.gui` 不自动
  安装、不启动子进程，以稳定退出码 2 说明缺少 optional group。
- 测试只运行定向目标、单进程、线程不超过 2；不运行全量 Gate，不启动外部 Agent，不占用项目长任务的
  专用资源。
- G1-D1 已在项目统一串行槽用 BelowNormal、CPU8–11（mask `0xF00`）、数值线程不超过 2 完成开发检查、
  AppTest 与两个真实 probe 的可用性核验。项目级 basetemp 位于当前 worktree 的 ignored `artifacts/` 下；
  验证后 venv、basetemp、目标 PID tree、`0xF00` 和 18501 listener 均已精确清理。本机只有 CPU0–11，未使用
  无效 mask，也未启动 browser 或外部 Agent。

## 已形成的历史 G0 安全证据

| 证据 | 结果 | 边界 |
| --- | --- | --- |
| 定向 pytest | `13 passed, 2 skipped in 1.36s` | skip 为 Streamlit 未安装与 Windows 当前账号无 symlink 权限；不是 UI 或 WSL Gate |
| 定向 Ruff | `All checks passed!` | 只覆盖 G0 获批源码/测试范围 |
| 定向 mypy | `Success: no issues found in 8 source files` | 只覆盖 G0 获批源码/测试范围 |
| 缺依赖启动器 | 稳定退出码 2、无子进程 | 证明降级语义，不证明真实 UI 可启动 |
| 真实 artifacts 只读探针 | 30 个自洽 run、0 issue；最小 run 输出 `VERIFIED`，NAV `AVAILABLE` | 当时快照，只读证据，不硬编码到 UI，不代表项目 Gate |
| Windows smoke 环境创建（历史） | 两次旧承载均以 `-1`、无环境/日志/残留终止 | 记录于 `75b6419`；后续 G0-C4 使用新冻结的 .NET carrier，不复用旧失败承载 |

## 历史 G1 定向验证证据

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

## 历史 G0-C4 Windows 功能 smoke 证据

G0-C4 在统筹独占释放 CPU8–11 后，用 .NET `System.Diagnostics.Process`、`ArgumentList`、异步
stdout/stderr、真实退出码、BelowNormal、affinity `0xF00` 和数值线程上限 2 串行执行。目标环境为
`artifacts/dev_envs/gui-g0-c4-win-py313`，验证结束后已删除。

| 证据 | 结果 | 边界 |
| --- | --- | --- |
| 依赖与解释器 | Python `3.13.13`、Streamlit `1.61.1`、pytest `9.1.1`；editable `[gui]` 安装成功；`pip check` 无 broken requirements | venv 借用 `D:\Miniforge3` system site packages；不是独立依赖闭包或 WSL Gate |
| AppTest | `3 passed, 3 warnings in 12.99s`；旧 `use_container_width` 告警 `0` | 3 条 warning 来自 `importlib.metadata`，不是 GUI API；只覆盖 Windows UI 反馈环 |
| 运行总览 | 34 个可读 run、22 `RESEARCH_ONLY`、12 `REJECTED`、0 `PAPER_CANDIDATE`、0 issue；最大 `data_end=2026-08-13` | 只读当时快照，不改变结论或准入 |
| 固定详情 | `36b3dd917281…` 在校验前锁定 NAV；校验后 4 个输出 `VERIFIED`，真实 NAV 曲线和表格可见 | 完整性动作有界，只读 |
| 固定比较 | `36b3dd917281…` + `03e6131b4617…` 在校验前锁定；校验后 2 run 口径/输出 `VERIFIED`，484 行、4 个 run+fold series 可见 | 只拼接原始 1.0× 行，不排名、不重算业务指标 |
| 浏览器控制台 | `0` error；18 条 warn、2 类唯一 Vega `Infinite extent` | 登记 `GUI-DEBT-VEGA-001`；functional smoke PASS，但 strict zero-warning 未关闭 |
| 服务日志 | 正确入口 `python -m quant.gui`；旧参数弃用告警 `0`，Traceback/Exception/Error `0` | 一次误用定义模块 `python -m quant.gui.launcher` 仅 exit 0、未绑定端口；随即改用正式入口 |
| 清理 | 目标 env、PID tree、18501 端口、ignored basetemp/log/temp、browser tab 均为 0 残留 | 服务叶进程精确停止后 carrier 的 `-1` 是预期停止终态，不是应用崩溃 |

## 可控基础设施债登记

当前以闭合只读业务路径为主。以下债项不放宽安全、PIT、fail-closed、统一回放、OMS/风控/对账或人工准入：

| 债项与 owner | 当前影响 | 延期理由 | 触发条件 | 通过标准 | 临时处置 |
| --- | --- | --- | --- | --- | --- |
| 公共 orchestration 应用服务边界；GUI session 提接缝需求，项目统筹裁决共享接口 | GUI 不得发起研究运行 | G0 只读闭环不需要任务执行；私有 runner helper 不是稳定公共接口 | 用户要求从 GUI 发起运行或进入对应项目 Gate | 类型化公共用例、幂等 JobSpec、持久化状态、资源/恢复/取消和失败语义由权威后端冻结并测试；GUI 只提交请求 | 不显示运行按钮，不 import `run_*`，只投影不可变结果 |
| `GUI-DEBT-VEGA-001`；GUI session | 功能页面与最终 484 行/4 series 曲线可见、console error 为 0，但初始化累计 18 条、2 类 `Infinite extent` warn；strict zero-warning 未关闭 | 消警告可能诱导连接 fold、重算或改变已验证证据；当前无空图或业务错误，不为 renderer 噪声扩大实现 | Streamlit/Altair 升级，或出现空图、console error、曲线缺失 | 用显式输入形态实验定位并消除 warn，同时保持原始行、fold 边界、digest 和曲线语义；AppTest/browser 回归通过 | 如实记录 warn；不把 functional PASS 写成 zero-warning PASS，不连接 fold、不重算 NAV |
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
| G1-D1 | `COMPARISON_CONTRACT_MISMATCH` 只读 14 字段关系诊断 | 已完成：source `9f42b3c` → merge `8427c83`，archive-first 退出 |
| G1-D2 | 运行总览 manifest-only literal 检索与 caveat presence 过滤 | 实现、独立初验与 focused 验证已通过；当前仅为 `READY_FOR_SAFE_COMMIT` 候选，等待安全提交/合流 |

G1-D2 当前证据边界（不替代项目 Gate 或合流结论）：实现已完成；独立 reviewer `01a03198...` 首轮
`FAIL`，返工后 `REVIEW_PASS`。combined focused pytest exit 0（35 passed、1 skipped），唯一 skip
是 Windows symlink-creation unit condition，不是 AppTest；等价 AppTest-only exit 0（9 passed、0 skipped）。
Ruff 四路径 exit 0；mypy 两个生产 GUI 文件 exit 0、2 files clean；exact7 `git diff --check`
exit 0、无 overflow；manager-owned taskbook 尾随空白 0、本地链接缺失 0。Python 3.13.13、
Streamlit 1.62.0、`pip check` exit 0，`quant.gui.__file__` 指向当前 worktree；`--system-site-packages`
不证明独立依赖闭包或 WSL Gate。目标环境、basetemp、PID tree 与 `0xF00` 均清理；未运行 browser、
cold、real artifacts 或 full pytest。

过程边界：首次 install carrier 仅发生 payload loss，未盲目重试；第二次 install exit 0。首次 combined
run 因 total skip 保守 `STOP`，root 接受 symlink 边界后完成 AppTest-only recovery；首次 mypy payload
loss 后仅做窄范围、可观测的 base recovery。G1-D2 当前仅是 `READY_FOR_SAFE_COMMIT` 候选，source
SHA、safe commit、merge、integration 与 retirement 尚未完成。

G0-C1 至 G0-C3、G1-C1 至 G1-C3、G0-C4 和 G1-D1 的既有提交与验证结果均作为历史证据保留；
`GUI-DEBT-VEGA-001` 仍开放，因此不得宣称 strict zero-warning C4 关闭。G1-D1 的 focused pytest、
Ruff、mypy、Streamlit AppTest 与真实 Probe A 已通过；Probe B 的 live fixture 因 29 个同口径候选 run 全部
`VERIFIED` 而继续记录为 `BLOCKED_BY_FIXTURE_AVAILABILITY`。统筹随后冻结的一次
`DERIVED_REAL_BYTES_OUTPUT_FAIL` 已用两个 fresh verified canonical run 的隔离逐文件副本通过：14 字段全部
`REFERENCE/SAME`，第二个副本 output 末字节篡改后严格返回 `COMPARISON_RUN_UNVERIFIED`，canonical 源
SHA 未变且临时资源已清理。因此等价验收及 exact 7 路径安全提交已经闭合；这里的状态不代表项目级里程碑、
browser 或 WSL Gate 完成，也不把派生反例称为既存坏 run。

## G1-D1 历史合流与 worktree 退出闭环

- **安全提交**：`9f42b3c81a3a5e4e70ec4a0c85e0c7695b9d1736`；定向 pytest、Ruff、mypy、
  AppTest、Probe A 与统筹冻结的 Probe B 等价派生反例均已形成证据。browser 未要求、未执行，不能写成通过。
- **合流**：integration merge `8427c83ddad62690b1f75d391ed1178fd3f6f415` 已吸收 source；没有从 GUI
  session 写根 writer checkout，也没有据此宣称项目 Gate 完成。
- **退出**：archive tag 已建立，来源 branch/worktree、ignored basetemp、短生命周期环境、派生临时 root、
  PID tree、端口与 CPU 占用均已清理。后续任务不得复用已退休 worktree 或旧 base。

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
- Windows Streamlit AppTest 与 overview/detail/comparison 浏览器 functional smoke 已按 G0-C4 证据通过；
  `GUI-DEBT-VEGA-001`、独立依赖闭包和 WSL Gate 仍未关闭，不得扩大表述。

## G1-D1 验收标准

- 诊断关系只在 issue code 精确为 `COMPARISON_CONTRACT_MISMATCH` 时可用；选择错误、输出上限、逐 run
  完整性或 NAV 问题不显示关系表；
- verifier 与 diagnose 直接复用同一 `_comparison_contract` 14 字段映射；diagnose 在内部覆盖全部 14 字段，
  不复制字段白名单；
- UI 只显示内部关系中至少含一个 `DIFFERENT` 的字段行；用户选择第一项在这些行仅显示 `REFERENCE`，
  其余项仅显示 exact `SAME` / `DIFFERENT`；REFERENCE 不含 baseline、winner、benchmark、推荐或准入
  语义；
- 页面不展示合同字段原值、摘要、长度、hash/digest、逐 run metric、部分 NAV、兼容子集或建议；
- mismatch 的错误码、entry、按字段名排序的 detail 集合及其早于 output size/hash 校验的失败顺序保持兼容；
  mismatch 时不得读取或哈希输出；
- 重新选择运行会清除旧诊断；严格比较的 2–4 唯一选择、128 MiB 输出上限、250,000 NAV 行上限和
  all-or-nothing 证据门禁均不改变；
- focused pytest、Ruff、mypy、AppTest 与真实 3-run mismatch Probe A 已通过；真实同口径 output-fail
  live fixture 因不存在而保留 `BLOCKED_BY_FIXTURE_AVAILABILITY`。统筹冻结的等价验收已由一次真实 canonical
  字节派生的隔离篡改反例通过：14 字段全 `REFERENCE/SAME`、output fail 精确闭合、无部分 evidence/NAV，
  canonical SHA 不变且临时资源清零；它不是既存坏 run。exact 7 安全提交、合流与来源线退出均已完成。

## G1-D2 验收标准

- `filter_research_runs` 只消费 canonical manifest 摘要，单次按输入顺序返回，保持对象 identity；空结论或
  策略选择返回空 tuple，非法 caveat 模式立即抛出 `ValueError`；
- query 只搜索 `run_id`、`hypothesis_id`、`strategy_name`、`strategy_version` 与
  `strategy_name strategy_version`，大小写不敏感但保持 literal substring 语义，不触碰 hypothesis 正文、
  caveat 文本、路径、digest、metric、input/output 或 NAV；
- `ALL`、`PRESENT`、`ABSENT` 只按 `manifest.caveats` 是否为空筛选；结论、策略、query、caveat 可组合，
  无匹配显示明确空态；
- overview 默认空 query/`ALL` 的行、列和 catalog 顺序与原行为一致；六张 KPI 卡仍统计全量 canonical
  runs，计数说明同时给出筛选结果与 catalog 总量；
- AppTest/单测用 fail-on-call 与 fail-on-file-access seam 证明筛选不触发 output verifier、comparison verifier、
  NAV projection 或文件访问；详情、比较和 G1-D1 关系诊断合同保持不变；
- 不新增依赖、缓存、索引、session state、路径输入、下载、执行能力或 M3/G2/orchestration 接缝；focused
  pytest、Ruff、mypy 与独立初验已通过，但不代表独立依赖闭包、WSL Gate、browser/cold/real artifacts
  或 full pytest 已完成。

## 后续队列

在 G0/G1 只读证据闭合并获得新的文件/依赖授权后，再依次评估：持久化 Job/Run repository、外置 worker、
数据质量中心、受控因子/策略注册表、报告中心、晋级只读视图、运维与审计。任何交易写操作都需要单独任务
书、权限模型、人工确认和既有执行服务接缝，不由本路线图预先授权。
