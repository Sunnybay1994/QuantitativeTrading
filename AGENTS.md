# AGENTS.md

个人 A 股/ETF 量化项目。成功标准只有：每日可执行订单清单、模拟盘净值、最终真实资金的风险调整正收益。

当前会话的 Agent 就是唯一研究员+工程师。不申请运行 Python、读写数据、Tushare、联网、CPU/GPU、安装 `pyproject.toml` 已列依赖、DeepSeek 月≤US$30 的权限。需要用户确认的只有：真钱下单、覆盖 raw、付费新源、单次>US$50 API、改本文件安全不变量。

## 硬规则

1. 禁止新治理层、正式身份体系、预建通用平台、状态标签停工、双环境 Gate、独立审查仪式。
2. 禁止单因子微假设；因子进库走电池。禁止用 ≤3 年 Top-K 收益差判定。
3. LLM 不直接交易。主观判断必须变成可评估信号列。
4. 测量：持股期、收益指数基准、空仓压力窗口标不适用。
5. 实验结果不手写文档。换手 6–8× 且 2× 超额≥5pp 视为通过（路线图 §1.2），不得临时改其他门槛。
6. 单文件 >1500 行 / md >30KB 必须拆。连续一周只有重构没有研究产出视为失灵。

口诀：做完之后回测、数据、订单、模拟净值都没变，就不是现在该做的事。机器能做的写成流水线。

## 安全不变量

无前视；raw 不可覆盖；统一回测口径与三档成本；预注册；凭据不进 Git；`auto_trade=false`。

## 结构

`quant.core` → `data` → `factors` → `research`/`portfolio`/`backtest` → `execution` → `reporting`。新能力在 `llm`/`notify`/`intel`，统一入口 `python -m quant`。`research/m3` 冻结。死代码在 `legacy/`。

细节：[docs/START_HERE.md](docs/START_HERE.md)、[docs/RESEARCH_PROTOCOL.md](docs/RESEARCH_PROTOCOL.md)、[项目实施路线图.md](项目实施路线图.md)。

## 项目协作

本项目已取消 Concord 协作机制；不再调用其任务认领、消息或交接工具，也不启动 inbox 监听。任务依据当前用户指令与工作清单推进，保留其他会话的未提交改动。
