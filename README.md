# A 股港股通个人量化投研交易系统

个人使用的 A 股与港股通量化系统:日频起步,研究与交易解耦,共享同一数据契约与
`target_weight` 接口。先轻量投研,纸面稳定后再逐步接入实盘。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/START_HERE.md](docs/START_HERE.md) | **新 Agent 从这里开始**：环境、入口、启动 prompt |
| [AGENTS.md](AGENTS.md) | 智能体行为准则（v2：单 Agent、业务优先、反过度工程化） |
| [项目实施路线图.md](项目实施路线图.md) | 当前阶段目标、本周任务、冻结清单、结果台账（v4） |
| [A股港股通个人量化投研交易系统调研.md](A股港股通个人量化投研交易系统调研.md) | 技术选型依据与模块设计("为什么") |
| [docs/research/研究流程精简版.md](docs/research/研究流程精简版.md) | 一个假设怎么从想法到结论 |
| [docs/项目审查与流程重构报告_20260908.md](docs/项目审查与流程重构报告_20260908.md) | 2026-09-08 流程诊断与重构决定 |
| [docs/archive/](docs/archive/2026-07至09_多Agent治理期/README.md) | 2026-07 至 09 多 Agent 治理期的全部历史文档，只读 |

## 目录结构

```text
quant/
├─ pyproject.toml            # 依赖:核心 / data(Tushare及校验源) / research / dev
├─ configs/
│  ├─ research/              # 股票池、因子、模型、成本(带版本与有效期)
│  └─ trading/               # 非秘密交易参数;实盘默认关闭
├─ src/quant/
│  ├─ domain/                # 数据契约(Pandera)与枚举 —— 全系统唯一真源
│  ├─ data/                  # 原始采集接口、raw/clean 分层、质量门禁
│  │  └─ connectors/         # 第三方数据源薄适配器（SDK 仅在这里导入）
│  ├─ factors/               # 因子定义与注册(M2/M3)
│  ├─ strategies/            # Strategy 接口:as_of 可知数据 → target_weight
│  ├─ research/              # 研究编排 CLI；不承载数据源或交易逻辑
│  ├─ portfolio/             # 组合约束与目标订单(M4)
│  ├─ backtest/              # 统一市场约束回测(M2/M4)
│  ├─ execution/             # 纸面账户、OMS、风控、券商 Gateway(M4/M5)
│  └─ reporting/             # 日报、归因、告警
├─ tests/                    # unit / integration / fixtures(黄金数据集)
├─ data/                     # raw / clean / features / qlib / legacy(不进 Git)
├─ artifacts/                # 回测、模型、报告及历史实验产物(不进 Git)
└─ docs/                     # START_HERE、研究流程与假设卡(research/)、历史归档(archive/)
```

## 架构铁律

1. 券商 API 只允许出现在 `execution` 的 Gateway 适配器内部。
2. 数据源 SDK 只允许出现在 `data/connectors` 内部;换源不改下游。
   只有 `quant.data` 的显式 repository/工具可读取项目 `data/`；其他层不得直接读取数据目录。
3. 策略只输出 `target_weight`,不做 IO、不碰订单。
4. 原始数据(raw 层)不可覆盖;clean 层必须通过 Pandera 质量门禁。
5. 财务数据用真实披露时间(PIT);信号可知时间与成交时间分离。
6. 实盘默认关闭；完成回测和模拟盘验证后，由用户确认小资金实盘。

## 快速开始

唯一运行环境：Windows 原生 Miniforge（`D:\Miniforge3\python.exe`，Python 3.13）。WSL / Linux Gate /
py312 环境已冻结，不再是任何任务的验收条件。

```powershell
cd F:\AI_Coding\QuantitativeTrading
$env:PYTHONPATH = "F:\AI_Coding\QuantitativeTrading\src"
D:\Miniforge3\python.exe -m pip install -e ".[dev,data,research]"   # 首次或依赖变化时
D:\Miniforge3\python.exe -m pytest tests/unit/test_lightweight_research_run.py -q   # 冒烟

# 每日数据刷新：17点前取上一开市日；重复执行为 no-op
D:\Miniforge3\python.exe -m quant.data.refresh --to today

# ETF 策略 walk-forward
D:\Miniforge3\python.exe -m quant.research.run_s1_walk_forward --config configs/research/m2_s2_volatility_target.toml
# 全市场因子评估
D:\Miniforge3\python.exe -m quant.research.run_classic_factors --config configs/research/m2_classic_daily_factors.toml --threads 8
```

数据刷新同时覆盖沪深股票日线、复权因子、daily_basic，以及 11 只 ETF 的成交行情和总回报价格。
股票增量保存在 `data/clean/tushare_incremental/`，可通过 `quant.data.refresh_stocks.read_stock_data`
与历史快照合并读取。详细配置见 `configs/data/refresh.toml`。

## S0 模拟盘

`D:\Miniforge3\python.exe -m quant.execution.paper_ledger --to today` 生成每日持仓、净值和订单参考；先运行数据刷新命令。前向首日 2026-10-08，详见 [运行说明](docs/research/模拟盘运行.md)。
