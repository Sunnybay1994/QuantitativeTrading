# 30万元同形观察账户：输入准备

账户仍为30万元、Top15股票40%及512890/511010各30%，股票月末1%预挂最多3日、ETF季度再平衡；`shadow=true`、`auto_trade=false`。首正式信号11-30，不接券商。本文只说明输入生产，不改变准入、权重或下单规则。

## 准备与消费分开

`QuantitativeTrading-Account30wInputs` 在工作日21:05准备两只ETF的日线、前收参考与公司行动，早于现有21:30日更。账户启动前也准备数据，不创建账户状态、订单或通知清单。任务以当前用户最低权限运行，最多10分钟，忽略重叠实例；错过21:05不迟到补跑，避免与晚间账户作业争同一输入。

它只请求两只ETF各一份近10日`fund_daily`及一份完整`fund_div`，不做股票全市场回补、模型拟合或因子研究。日历只读已有沪深日历；缺日历或指定非开市日则失败，不额外探测/下载日历。沿用原21点后消费窗口，不把未完成当日行情当作完成。

项目根目录使用项目Python执行：

```powershell
python -m quant data account-30w-inputs --output artifacts/data/account_30w_prepare/<新目录>
# 只可指定已完成的开市日，保存真实本次接收时间
python -m quant data account-30w-inputs --to YYYY-MM-DD --output artifacts/data/account_30w_prepare/<新目录>
```

不传日期时，21点前以上一日为上界，按已存日历选最近开市日；21点后可选当天。显式未来日、未到窗口的当天或休市日不被默默改成另一天。

## 文件与时刻

- 原始响应只追加到`data/raw/tushare/fund_daily`和`fund_div`。
- 报价快照在`data/clean/account_30w_top15_inputs/date=<交易日>/capture_*`，包含真实接收时刻与文件SHA；已有完整同日快照核对后复用。
- 公司行动使用已有主表发布到`data/clean/etf_corporate_actions/account_30w_capture_*`；公告原文、份额乘数及现金腿仍由原主表规则校验，丢失已知实施分红时拒绝发布。
- 准备回执`summary.json`的`available_at`不早于报价和公司行动版本的实际观测时刻。旧日期的手工准备不是当时PIT到达证据，也不算自然验收。

同日报价及每个行动版本分别持发布锁，防止任务与账户入口同时采集或发布。首次实时发布后使用发布后的实际时刻读取新版本；显式提供历史截止时刻的读取仍拒绝更晚的版本。

现有日更继续消费完整同日输入。回填未让路时，冻结降级只读已经保存且通过SHA/时间校验的快照；没有同日ETF缓存则记不可用，不用昨日行情生成新委托。错过准备任务且没有输入时，不把不买决定包装成订单就绪。

## 安装与核对

`scripts/install_account_30w_inputs.ps1` 导出可检查的XML；加`-Install`注册未来任务，已有同名任务时拒绝替换，不立即启动。执行脚本为`scripts/run_account_30w_inputs.ps1`，日志在`artifacts/data/account_30w_prepare/scheduler/`。故障沿用原项目自动化告警。

注册与手工准备分别核对，不把`Ready`或未运行状态当成自然成功。机器证据见[本轮输入核验](../../artifacts/maintenance/review_20261115/account_inputs/verification.json)；月末仍需11-30订单、12-01成交与通知等实际证据。

12-01盘前 `python -m quant paper account-30w-top15 --notify-due` 只发送冻结11-30模拟清单供人工演练，不下真钱；正式入口仍是 `python -m quant paper account-30w-top15 --to YYYY-MM-DD`。
