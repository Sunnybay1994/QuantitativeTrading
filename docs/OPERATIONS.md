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

看板策略曲线下提供年/月指标、基准选择、资金标注、策略说明和 HTML 报告下载。下载使用当前策略、日期筛选、成本档与表格所选基准。自动生成的模型报告链接到 `periods/`，月度明细按年拆分；空仓初始化期排除，不把部分年/月当完整期间。资金回放入口拒绝 10 万、100 万以外或重复档位；修改后的 R8 配置必须使用新输出目录，不能接续旧多资金档运行。

看板“当前流水线 → 重启投研 / 从断点恢复”触发现有 Windows ContinuousMining 计划任务，运行中不重复启动，不强杀进程、不清空断点、不重置失败计数。仍遵守日更避让与写入互斥；“已请求”不等于已运行，须看实际进程和批次状态。控制接口仅接受本地同源、带页面令牌的 POST。

每日观察的 `complete` 表示流程执行完成，影子滑点 `partial` 则表示报价窗口仍有缺口；看板会显示具体数量与处理事项。影子价格不是实际成交，缺失数据不能按零滑点处理，也不是下单通知。

日更 `forward_tracking.tdx_recovery_root` 启用本地ETF量额恢复：仅处理已完成交易日的保存订单，校验完整分钟、量额隐含价及至少192根跨源分钟收盘价，失败保留缺口。通过后原始快照保存在当次 `forward_tracking/raw_tdx/`，逐日来源和失败原因见 `minute_recovery.json`，不改共享分钟库、不联网、不覆盖历史报告。影子价格仍不是实际成交。
