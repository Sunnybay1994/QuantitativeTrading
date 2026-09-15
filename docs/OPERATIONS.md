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
| 挖掘状态 | `.\scripts\show_factor_mining_status.ps1` |

计划任务安装：`.\scripts\install_daily_observation.ps1`、`.\scripts\register_continuous_mining.ps1`。电脑须开机且用户登录。

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
