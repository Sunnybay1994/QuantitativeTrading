# 全市场分钟线补全

`python -m quant data minutes` 每次刷新沪深京当前上市股票、场内 ETF 名单，先增量导入 `D:/new_tdx/vipdoc` 的 1m/5m 文件，再抓取各近期接口返回的全部 1m 窗口。只接收最近已收盘交易日及之前的数据。这里的全市场指当前大陆股票及 ETF，不包括港美股、退市历史全集；港股原有 Yahoo 流程保留。

- 新浪：AKShare `stock_zh_a_minute(period='1', adjust='')`，请求 SDK 支持的 1970 根窗口，实际起止日期逐次记录。缺成交额保持 null。
- 东财：股票/ETF 各自的 AKShare 一分钟接口，请求近五个交易日全部可返回记录。部分端点可能拒绝连接，连续失败后退避五分钟，其他来源继续。
- TDX：只导入发生变化的本地文件。采集器不能替代通达信客户端下载；文件没更新会在覆盖检查中留下缺口。
- 每个来源单独保存，不用报价快照伪造 OHLC，不拼接来源冒充完整日。原始响应追加保存，clean 原子替换；未知停牌和缺失分开于“完整”状态，不以没有返回认定停牌。

检查最近十个交易日的逐标的覆盖；240 根规则分钟才计为 OHLCV 完整，成交额完整性另列。名单按上市日期限制；缺口报告中的 `missing_or_suspended_dates` 需要进一步日线/停牌证据解释，不能当作确定的下载失败或停牌。接口最大窗口边界之外仍可能缺失，任务 `checked` 表示本轮检查结束，不表示全市场无缺口。

状态：`artifacts/minute_refresh/status.json`；名单：`universe.json`；逐标的断点和覆盖：`date=YYYY-MM-DD/*.json`。同日成功取到最新交易日的来源避免重复请求；失败项下次重试，断点恢复优先未尝试标的。支持 `--limit N --skip-tdx --max-seconds N` 做小范围诊断。

## Futu 盘后实时订阅全市场 1 分钟（独立机制）

与盘中 `quant data realtime`（QUOTE 优先、小观察名单）和 `quant data minutes`（TDX/公开源）分开。收盘后只用 OpenD **K_1M 订阅 + get_cur_kline** 轮转扫全市场，**不消耗 History KL 额度**。

| 项 | 说明 |
|---|---|
| 入口 | `python -m quant data post-close-k1m` |
| 配置 | `configs/data/post_close_k1m.toml`（与 `realtime.toml` 隔离） |
| 产物 | clean：`data/clean/bar_intraday/freq=1m/source=futu_realtime/`；raw：`data/raw/futu/realtime/date=*/post_close_k1m/`；状态：`artifacts/post_close_k1m/` |
| 调度 | `scripts/install_post_close_k1m.ps1` → 工作日 15:10；`scripts/run_post_close_k1m.ps1` |
| 探针 | `--limit N --max-batches 1 --max-seconds 600`；非闭盘诊断加 `--force` |

OpenD 约 100 档、每轮 ≥65s，全市场约 1.5h。与盘中 RealtimeQuotes 互斥（脚本检测到 live realtime / GP 冻结会 deferred）。

## Futu 全市场历史 1 分钟

职责拆分：

| 通道 | 入口 | 用途 | 是否消耗 Futu 历史额度 |
|---|---|---|---|
| 近期分钟 | `quant data minutes`（任务 MinutesRecent） | 当日/近窗全市场 1m（TDX + 公开源） | 否 |
| 历史分钟 | `quant data minute-history`（任务 MinutesHistory） | 全市场缺失年份回填 | 是（约 100 标的 / 滚动约 7 天） |

额度策略（`configs/data/minute_history.toml`）：

- **100 额度全部用于历史缺年**；`quota_reserve=0`，用到 remaining=0 为止；`max_new_symbols=100`。
- **`same_day_topup=false`**：不用 Futu 做当日续更，避免 7 天滚动后旧标的反复占额；近期靠 MinutesRecent。
- 每轮优先续下窗口内**已扣额度**的未完成标的，再开新标的；时间预算 `max_seconds=10800`。

时间范围（尽量早）：

- 配置 `start=1990-01-01`，与上市日取较晚者作为探测请求起点。
- `earliest_available=true`：向 Futu 拉首页，以**实际返回的第一条分钟**为该标的最早日（官方约最近八年，供应商能给多早就取多早；边界写入 `artifacts/minute_history/earliest_bounds.json`）。
- 缺失年份**从早到晚**下载，先保住即将滚出窗口的旧数据。
- `end_policy=latest_completed_session`：结束日随最近已收盘交易日滚动，不冻结在固定日历日。

产物与规则：clean 在 `data/clean/futu_minute/all_market/symbol=*/year=*/data.parquet`；已有年份分区不重下；北交所跳过；空年/下载错误分别延后七天、边界探测错误延后一天。进度：`artifacts/minute_history/status.json`、`progress.json`。`--check-only` 只排队列不请求。

部署：`scripts/install_minute_refresh.ps1` 安装两个独立 Windows 任务。近期补数工作日 16:10、21:10；历史队列工作日 22:10。相同任务忽略重入，程序另有文件锁，机器须开机且用户登录；Futu 历史需要 OpenD 登录。任务与订单/净值日更分开运行，以免全市场网络抓取阻塞现有日更。

相关入口：`scripts/run_minute_refresh.ps1`（历史加 `-History`）；日志位于 `artifacts/minute_refresh/scheduler/`。所有入口维持 `auto_trade=false`。本流程是数据积累，不自动改变现有因子选源或策略准入。

**与 GP 冻结互斥（2026-10-14）：** 采集会改写 clean `bar_intraday` 字节。若检测到持续挖掘 / nightly / GP 进程，调度脚本写 `deferred` 状态后退出 0，不抢写；挖掘侧若撞上过期冻结则归档 `N2/stale_context_recovery` 后重钉。

## 全市场 BaoStock 5 分钟（2026-09-23）

数据名单与研究池分离：`market_universe.py` 合并最新全市场股票/ETF、历史日线中的已退市标的，以及 BaoStock 基础资料中的历史股票；研究 Top800 不再限制采集。沪深队列按上市日期请求，北交所继续由已有近期源/TDX 覆盖；不把供应商不支持的市场称为已完成。

`python -m quant data baostock-history` 独立补采。每轮先扩大全市场当前年度覆盖，再逐年向前请求至上市日期或 1990-12-19；具体可取起点由供应商实际返回决定，空响应不证明此前无历史。已有日线确认的完整交易日复用，不重抓；有数据但缺少日线验证的年度记为 unverified，缺根记为 partial，空响应记为 empty。错误十分钟后可重试，缺口/空返回七天后再试。原始响应追加保留，clean 按标的写锁合并，兼容日更与历史补采同时运行。`run_baostock_history.ps1` 在挖掘/GP 持有冻结 bar 时同样 `deferred` 退出，避免打穿 checksum。

`QuantitativeTrading-BaostockHistory` 每天每小时 25 分触发，每轮默认 3000 秒，运行中忽略重复触发；机器须开机且用户登录。年度请求结束后保存断点，暂停或关机后下次续跑。`scripts/install_baostock_history.ps1` 注册，`run_baostock_history.ps1` 执行。每日目标随完成交易日滚动，不固定在研究截止日。

名单、状态、逐标的年度断点、错误与缺口位于 `artifacts/baostock_history/`，看板数据模块可查看进度并手动启动。日更的 BaoStock 名单也使用此全市场数据名单；研究配置及准入规则不变。部署和运行中不等于全历史无缺口，真实增加行数与失败记录见 status.json；测试见 tests.xml。
