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

策略曲线下方可切换年度 / 月度指标与对比基准，查看策略简述、原回测资金，并下载 HTML 期间报告。超额为累计收益差（百分点），夏普按日收益年化；缺少可比基准时保留空值。新资金回放最多使用 10 万、100 万两档，不改变三档成本测试。

看板当前流水线提供“重启投研 / 从断点恢复”按钮，通过现有计划任务恢复；不会重复启动运行中的任务，也不会清空断点。

看板后台服务可通过 `scripts/register_research_dashboard.ps1` 注册为当前用户的登录启动任务 `QuantitativeTrading-ResearchDashboard`，只监听本机8768端口；启动器互斥和端口检查防止重复启动，异常退出每隔1分钟重试，最多3次。关机期间不运行，登录后恢复。日志位于 `artifacts/research/dashboard_service/`；`/api/health` 用于核对实际服务进程。

运行卡片区分实际运行、时间片结束、每日观察避让、其他写入任务占用、重试冷却及故障；显示最近进度保存时间、Windows 计划任务下次触发时间和重试条件。进程或调度读取失败时明确标为未知，计划触发不保证立即开工。

研究结果支持按策略标签搜索，并显示研究保留复核结论、原判定和风险原因。每日观察提示会区分数据维护、风险核对及流程错误，说明所需处理。

各因子／策略报告提供“1x成本：年度与月度结果”入口，列出收益、沪深300／中证500全收益超额、夏普和最大回撤；月表按年份拆分。结果登记时自动生成，也可运行 `python -m quant report periods` 从已保存净值补写历史报告；无完成净值的记录明确标为不适用，不重跑回测、不改变原准入结论。

研究结果默认折叠同源报告、公共对照及已验证三档成本逐日净值与资金记录相同的结果；可展开原始记录，或切换“全部原始记录”。分组不合并结论，不代表独立策略数量，缺少净值证据不折叠。

新建因子评估流水线在成本回放前核对全历史排序、缺失位置及方向，对同批次等价信号复用完成的回放，独立统计检验与准入结论保留。流水线报告记录复用数量与节省的版本×成本回放数，因子目录的 `reuse.json` 保留来源和文件校验。中断后从原目录恢复；旧批次沿用原执行方式。

已注册的一轮跨股票样本搜索见 `configs/research/gp_cross_stock_v1.toml`：当前未完成批次之后，调度只创建一个采用三组各300只股票的新批次，以最弱组IC评分；恢复时使用原样本及冻结目标。三组都用于训练，历史对照不冒充独立验证；正式准入仍走原电池与三档成本。
