# 运维

唯一环境：Windows，`D:\Miniforge3\python.exe`（Python 3.13）。项目根执行：

```powershell
$env:PYTHONPATH = "$PWD\src"
$env:POLARS_MAX_THREADS = '4'
$env:PYTHONUTF8 = '1'
python -m quant --help
python -m quant status
python -m quant gpu-check
```

## 日常命令

| 做什么 | 命令 |
|---|---|
| 日更只读检查 | `python -m quant research daily --check-only` |
| 日更 | `.\scripts\run_daily_observation.ps1` |
| 持续挖因子 | `.\scripts\run_continuous_mining.ps1` |
| 扫描论文/开源 | `python -m quant intel scan`（`--no-extract` 不花 LLM） |
| 发一条通知 | `python -m quant notify test` |
| 排行榜 | `python -m quant report leaderboard` |
| 本地投研看板 | `python -m quant report dashboard --port 8768`；已安装登录任务时自动恢复，不要重复启动 |
| 挖掘状态 | `.\scripts\show_factor_mining_status.ps1` |

计划任务安装：`.\scripts\install_daily_observation.ps1`、`.\scripts\register_continuous_mining.ps1`、`.\scripts\register_research_dashboard.ps1`。电脑须开机且用户登录；看板地址 `http://127.0.0.1:8768`。

## 凭据

全部 `*.local.toml` / 环境变量，不进 Git。

| 用途 | 位置 |
|---|---|
| Tushare | `configs/tushare.local.toml` |
| DeepSeek | `DEEPSEEK_API_KEY` 或 `configs/deepseek.local.toml` |
| SMTP | `SMTP_HOST` / `SMTP_FROM` / `SMTP_TO` / `SMTP_PASSWORD` |
| 企微 / 飞书 | `WECOM_WEBHOOK` / `FEISHU_WEBHOOK` |
| 微信 | `WXAUTO_GROUP`，需解锁桌面；可选依赖 `pip install -e ".[wechat]"` |

`configs/notify.toml` 的 `channels` 配好后，日更/挖掘失败会真发消息；未配则写入 `artifacts/notify/outbox.jsonl`。

## 证据位置

| 问题 | 看哪里 |
|---|---|
| 日更 | `artifacts/daily/sue_v2/`、`artifacts/daily/scheduler/` |
| Q10 前向 | `artifacts/paper/q10_sue_v2/` |
| 持续挖掘 | `artifacts/research/continuous/status.json`、各 `batch_*/digest.md` |
| 情报周报 | `artifacts/intel/<ISO周>/digest.md` |
| 实验数字 | `artifacts/registry/experiments.parquet`、[排行榜](research/排行榜.md) |

## 恢复

先确认 Python 进程已结束。持续挖掘自动从 GP 种群与 `N4/admission_progress.json` 恢复。不要删断点、不要改冻结配置冒充同一次 run。日更与挖掘互斥，工作日 17:20/21:20 挖掘让路。

## GPU

默认 CPU。要加速时：`$env:QUANT_DEVICE='auto'` 或改 `configs/runtime.toml`。`python -m quant gpu-check --refresh` 查看本机 OpenCL 是否可用。

## 研究反馈

`python -m quant research feedback` 只读取已保存电池并更新 `artifacts/research/feedback/feedback.json`，不回测、不调用 LLM。持续挖掘下一次进程启动后，每轮结束自动刷新；新周度候选请求读取最近三批反馈及 `configs/research/research_priorities.toml`。已有周度请求、运行批次和 GP 断点保持冻结，因此当前运行进程不会热加载这次代码修改。DeepSeek 原闲时窗口与周/月预算保持有效；反馈异常写入挖掘状态，不阻断已完成的本地研究。

`python -m quant research batch-diagnosis --run <已完成批次目录> --run <另一批次目录> --output <新目录>` 复算保存的训练/电池分数、统计失败与成本敏感性，不重新回测。第9批的最弱组目标与总体训练IC分别解释；已观察历史不是独立测试。

`python -m quant research reversal-readiness --output <新目录>` 按 `configs/research/pressure_reversal_v1.toml` 抽查量价反转输入，保存实际刷新配置、行业源哈希与机器报告。只检查输入，不读未来收益、不入队、不回放账户；抽样月份与表达式文本去重不能替代完整历史覆盖和信号等价检查，量价代理不能证明没有消息影响。

看板策略曲线下提供年/月指标、基准选择、资金标注、策略说明和 HTML 报告下载。下载使用当前策略、日期筛选、成本档与表格所选基准。自动生成的模型报告链接到 `periods/`，月度明细按年拆分；空仓初始化期排除，不把部分年/月当完整期间。资金回放入口拒绝 10 万、100 万以外或重复档位；修改后的 R8 配置必须使用新输出目录，不能接续旧多资金档运行。

看板“当前流水线 → 重启投研 / 从断点恢复”触发现有 Windows ContinuousMining 计划任务，运行中不重复启动，不强杀进程、不清空断点、不重置失败计数。仍遵守日更避让与写入互斥；“已请求”不等于已运行，须看实际进程和批次状态。控制接口仅接受本地同源、带页面令牌的 POST。

每日观察的 `complete` 表示流程执行完成，影子滑点 `partial` 则表示报价窗口仍有缺口；看板会显示具体数量与处理事项。影子价格不是实际成交，缺失数据不能按零滑点处理，也不是下单通知。

日更 `forward_tracking.tdx_recovery_root` 启用本地ETF量额恢复：仅处理已完成交易日的保存订单，按开盘5/15/30分钟分别校验连续分钟、量额隐含价及至少80%的跨源分钟收盘价；仅采用从最短窗口起连续通过的范围，失败保留缺口。全天质量另行记录，不将窗口通过视为整天合格。通过后原始快照保存在当次 `forward_tracking/raw_tdx/`，逐日来源和失败原因见 `minute_recovery.json`，不改共享分钟库、不联网、不覆盖历史报告。影子价格仍不是实际成交。

恢复证据可用 `python -m quant research recovery-audit --file-baseline <恢复前文件哈希清单.json> --output <新报告.json>` 比对。输出分别记录文件内容、修改时间及读取中变化；文件相同不能单独证明自动续跑或排除相同内容重写，需另查新进程与同批次后续产物。不带 `--file-baseline` 时保留历史调度与净值日期核查。

09-19自动化优化：新冻结配置启用 `prepare_month_inputs=true`，N3首次建批时复用月度输入补齐；恢复旧批次不会重新冻结执行快照。N5按当前调度日期检查到期月份，保留旧跳过记录；准入只能采用同截止日的完整月度参考表。若旧批次已达失败上限，新到期月份只有一次恢复机会，仍失败则继续保留上限，不无限重试。

新冻结配置的 `slice_checkpoint_seconds=180` 在硬截止前预留收尾时间。GP代际、年度/成本档账户及N4候选边界可主动让出时间片，退出码75记录为可恢复，不累加失败；已有冻结批次保留原时间片规则。单个计算单元超过预留时间时仍由原硬截止保护，不保证任意位置零重算。

日更 `model/refresh_progress.json` 原子记录输入子步骤、时间和分钟请求计数；失败次数与完成请求数分别展示，更新时间不证明进程存活。看板并发处理请求，状态刷新合并并发请求，缓存时间和刷新失败可见。

新电池的 `pipeline_config.json` 记录 `benchmark_reuse=true`；跨批基准缓存按目标、会话日期、执行数据内容、费用和回放代码校验，仅复用完整三档成本结果。缓存索引在电池集合的 `benchmark_cache/`，每批 `benchmarks/benchmark_reuse.json` 记录来源及节省数量；损坏/不匹配缓存不命中，旧冻结流水线不切换模式。代码改动或输入变更可能导致保守失效，不能把测试复用数当作生产节省量。

`configs/research/gp_predictive_priority_v2.toml` 仅登记预测能力优先的搜索方案，尚未接入调度或入队；实施前必须冻结具体机制终端及完整输入覆盖。一次批次上限、未来验证与原准入门槛保持有效。
