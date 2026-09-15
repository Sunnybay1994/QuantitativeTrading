# 个人 A 股 / ETF 量化投研系统

日频研究、自动挖因子、模拟账户、人工订单通知。实盘默认关闭。

## 从哪里开始

1. [AGENTS.md](AGENTS.md) — 工作准则
2. [docs/OPERATIONS.md](docs/OPERATIONS.md) — 怎么跑
3. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 结构
4. [docs/RESEARCH_PROTOCOL.md](docs/RESEARCH_PROTOCOL.md) — 怎么判定
5. [项目实施路线图.md](项目实施路线图.md) — 现在做什么
6. [docs/research/排行榜.md](docs/research/排行榜.md) — 数字

## 日常

```powershell
$env:PYTHONPATH = "$PWD\src"
$env:POLARS_MAX_THREADS = '4'
$env:PYTHONUTF8 = '1'
D:\Miniforge3\python.exe -m quant status
D:\Miniforge3\python.exe -m quant research daily --check-only
```

| 计划任务 | 时间 | 做什么 |
|---|---|---|
| DailyObservation | 工作日 17:30、21:30 | 数据/因子增量、冻结预测、观察账户、Q10 |
| ContinuousMining | 登录后每 10 分钟尝试接续 | GP + 评估 + 入库，每片最多 2 小时 |

电脑须开机并登录。失败通知见 `configs/notify.toml`（未配通道则写 `artifacts/notify/outbox.jsonl`）。

## 目录

- `src/quant/` 运行时代码；`legacy/` 已迁出的死模块
- `configs/` 版本化规则，索引见 [configs/README.md](configs/README.md)
- `data/`、`artifacts/` 不进 Git
- `docs/` 长期文档；按日期命名的实验页在 `docs/research/experiments_2026-09/` 与 `docs/archive/`

`auto_trade=false`。真实资金下单只由用户确认。
