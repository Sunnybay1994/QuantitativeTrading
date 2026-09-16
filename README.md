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

## 投研看板

在项目根目录启动本地只读看板：

```powershell
$env:PYTHONPATH = "$PWD\src"
D:\Miniforge3\python.exe -m quant report dashboard --port 8768
```

浏览器打开 [投研工作台](http://127.0.0.1:8768/)。服务仅监听本机；关闭服务或重启电脑后需重新启动。

- 查看实际研究进程、CPU 累计计算时间、显卡占用，以及挖掘阶段、断点进度和候选入库结果。
- 查看历史回测的成本后收益、夏普、回撤与报告证据，支持搜索、结论筛选和点击表头切换升降序。
- 绘制已有策略或模拟账户收益曲线，选择成本档、日期区间并叠加中证500、纳斯达克综合、恒生科技等基准；支持鼠标与逐日滑块查看数值。曲线按共同起止日归零，保留原币和价格/全收益口径，不补造缺失数据。基准使用已保存快照，实际覆盖日期在图例展示；页面刷新不会联网更新行情。
- 查看每日模拟观察、风险检查、账户权益、现金比例、持仓数与订单数。
- 每 20 秒自动刷新，也可点击“手动刷新”立即读取最新数据；刷新保留当前筛选和排序。

看板读取已有结果，不启动挖掘或下单。保存状态与实际进程分别展示；显卡占用是整张显卡的用量，不代表本项目用量。

## 目录

- `src/quant/` 运行时代码；`legacy/` 已迁出的死模块
- `configs/` 版本化规则，索引见 [configs/README.md](configs/README.md)
- `data/`、`artifacts/` 不进 Git
- `docs/` 长期文档；按日期命名的实验页在 `docs/research/experiments_2026-09/` 与 `docs/archive/`

`auto_trade=false`。真实资金下单只由用户确认。

研究反馈：`python -m quant research feedback` 汇总已完成电池的失败、家族、衰减与基准缺口；下一次持续调度自动更新，新周度候选使用该反馈。研究目标与准入门槛分开，详见 [研究协议](docs/RESEARCH_PROTOCOL.md)。
