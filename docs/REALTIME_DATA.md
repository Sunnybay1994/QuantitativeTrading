# 盘中行情

`python -m quant data realtime run` 在沪深交易日 09:20—15:05 采集。日历复用已保存的交易所日历，缺覆盖时调用现有 Tushare 日历更新；不按星期猜交易日。午休保留连接并更新心跳，恢复后重新拉取当前 K 线。

首次运行依赖本机已登录的 Futu OpenD（127.0.0.1:11111）及对应行情权限。安装可选依赖 `pip install -e ".[realtime]"`。调度安装入口 `scripts/install_realtime_quotes.ps1`，工作日 09:20 和用户登录时触发；电脑须开机且用户登录。程序有独占文件锁，不与日更共享写入目标。

## 采集范围

`configs/data/realtime.toml` 明确账户根目录；当前采用 B20 主策略、Q10 的模拟持仓，以及执行日期为当天的候选订单。这里的持仓来自项目模拟账户，不代表用户券商真实持仓。新增分钟策略可将同格式的日期化 positions.csv / orders.csv 根目录加入该配置。

持仓、订单优先，剩余额度用于冻结的高流动性观察名单。名单按沪市主板、深市主板、创业板、科创板，以及流通市值分组选择，ETF 另列。完整范围、读取账户日期和被舍弃的补充标的保存在 `artifacts/realtime/futu/watchlist.json`。名单于进程启动时冻结；盘中变更需更新配置并重启。不能静默舍弃持仓或订单。

## 数据时效和消费

OpenD 订阅 QUOTE 和 K_1M 并持续接收供应商推送，采集器每 5 秒读取报价缓存、每个标的每 60 秒读取当前最多 1000 根一分钟 K 线，显式使用不复权。K 线请求错开执行，避免整池请求同时发出。它不是逐笔、盘口或毫秒级接收器。

首版保留供应商分钟标签及独立 09:30 开盘行，不强行转换为 TDX 的 240 根格式。为避免把正在变化的 K 线当成最终值，只有在标签时间之后至少 63 秒重新获取的记录才发布。考虑一分钟轮询，实际确认延迟约 63—123 秒，再加网络和处理耗时；策略必须按实际 available_at 决策，不能假设每到整分就有最终 K 线。后续降低延迟需要盘中验证标签与结束时刻语义。

原始响应追加到新的 `data/raw/futu/realtime/date=*/` 压缩文件；策略数据保存在 `data/realtime/futu/market.sqlite`。SQLite WAL 支持并发读取，每次修订保留新版本和 available_at，raw 不覆盖。断线后等待订阅释放窗口再重连、重订阅，通过当前 K 线接口恢复当天窗口，不请求历史 K 线，不改历史 Futu 或 TDX 分区。

使用 `python -m quant data realtime read --symbol 510300.SH --count 20`，或调用 `quant.data.realtime_store.read_for_strategy`。读取器要求交易时段、健康心跳、30 秒内供应商报价、非停牌、连续的已完成分钟，并只选读取时已可知的版本。失联、缺分钟、延迟报价、未来时间、午休或休市均拒绝提供可执行输入。早盘不足所需窗口时同样拒绝，不填零、不前向填充。它提供数据，不产生实盘订单，`auto_trade=false`。

## 检查和故障

- `python -m quant data realtime status`：本地状态、心跳年龄、逐标的请求异常及订阅额度。
- `python -m quant data realtime probe --max-seconds 90`：有限的连接、订阅、报价与当前 K 线读取探测，结果放在独立 probes 目录；不会让生产读取器变成 ready。
- 主状态 `artifacts/realtime/futu/status.json`；调度日志在其 scheduler 子目录。
- OpenD 不在线或未登录时重连并退避；不得把客户端登录窗口或订阅成功当成盘中低延迟验证。
- 一只股票两种订阅占两个实时额度；预留 10，最多 40 只。额度不足时先缩减补充观察名单；连持仓和订单都无法覆盖时报告错误，不抢占其他连接。账户快照早于上一交易日或缺少持仓文件时也会拒绝启动。

协议依据：[实时 K 线](https://openapi.futunn.com/futu-api-doc/quote/get-kl.html)、[订阅及默认推送复权](https://openapi.futunn.com/futu-api-doc/quote/sub.html)、[额度](https://openapi.futunn.com/futu-api-doc/intro/authority.html)。历史额度仅适用于历史 K 线接口，此采集器不调用该接口。
