# 飞书人工交易演练运行说明

本版本实现双向消息适配、固定格式回报、SQLite持久账本与独立后台接收程序。仅支持沪深主板股票演练，`auto_trade=false`，所有消息有“演练 · 不下真实单”前缀；不是已上线的实盘服务。计划资金10万元不等于真实账户余额。

## 离线验收与恢复

在项目根目录，设置 `PYTHONPATH=src`、`PYTHONUTF8=1`。以下示例使用 `D:\Miniforge3\python.exe` 对应的Python。

```powershell
python -m quant paper manual demo --output artifacts/manual/demo_new
python -m quant paper manual --database artifacts/manual/demo_new/session.sqlite status
python -m quant paper manual --database artifacts/manual/demo_new/session.sqlite export --output artifacts/manual/export_new
```

输出目录必须不存在，避免覆盖证据。演练不联网：两次部分成交累计1000股、确认费用5元，现金89489元；另一个建议明确未操作。重复回报不重复入账。数据库使用WAL和FULL同步；关机重开使用同一个 `--database`。备份运行中数据库应使用SQLite backup，不能只复制sqlite文件遗漏WAL。

`init --opening opening.json --sessions sessions.json --account galaxy_rehearsal --sender ou_xxx --chat oc_xxx` 初始化隔离账户。opening示例：`{"date":"2026-09-18","cash":100000,"holdings":{}}`；sessions为有序交易日期JSON数组，必须来自实际交易日历。不得据示例覆盖真实账户事实。

`propose --file orders.json` 接收建议数组，每项必填order_id、version、account_id、strategy_version、symbol、side、quantity、limit_price、signal_at、valid_from、valid_until。时间含+08:00时区，BUY为100股整数倍。替代建议另加supersedes_order_id，只能替代已确认未操作、已撤余单或未发即过期的建议。同一股票在途状态未明时阻止再提建议；买单预留现金，卖出未成交不能预支收入。

## 飞书绑定与启动

1. 创建飞书自建应用、启用机器人，配置发送消息及接收用户消息所需权限和可用范围，订阅 `im.message.receive_v1`，事件接收选择长连接，发布应用。群聊回报需让机器人实际收到文本事件。
2. 在运行进程环境配置 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`，不要写进Git或聊天。把实际open_id/chat_id写入 `configs/trading/manual_galaxy_100k.toml`，须与init绑定一致，设置enabled=true。
3. 安装声明的可选依赖 `python -m pip install -e ".[feishu]"`，启动：

```powershell
python -m quant paper manual --database artifacts/manual/galaxy_100k_rehearsal/session.sqlite serve --config configs/trading/manual_galaxy_100k.toml --send-rehearsal
```

这是常驻程序，可在独立终端运行，不依赖Codex。当前没有替你注册登录启动任务；配置为空时拒绝启动。仅发送演练消息，禁止把mode改成live。服务有操作系统单实例锁，每秒处理持久队列；`session.heartbeat.json`仅表明处理线程最近成功一轮，不代表WebSocket收信已验证。网络中断或机器关机期间不运行；飞书历史漏收不保证自动补齐，需结合券商核对后补报。

## 回报格式

```text
委托 O001 v1 券商单号=B123 数量=1000 限价=10.52 时间=09:31:05
成交 O001 v1 成交号=F456 本次数量=400 成交价=10.50 时间=09:31:18 费用=待核
撤单确认 O001 v1 券商单号=B123 已撤剩余=600 时间=09:34:00
未操作 O002 v1 确认未委托=是 原因=错过窗口
查单 O001 v1 券商单号=B123 状态=已委托未确认成交
费用确认 O001 v1 成交号=F456 费用=5.00
```

成交是本次增量，成交号按券商实际编号。时间属于建议对应交易日，支持日后补报该日实际成交。未回复视为未知，绝不推定未操作；窗口结束只提醒查单，不自动重发/追价。部分成交只记实际数量，费用待核显示临时账本。补报旧单会使替代建议暂停等待核对。矛盾回报保存原文并进入review，不修改原持仓，阻止新的操作建议；确认/错误提示仍可发送。

离线注入：`receive --file envelope.json`，文件包含message_id、sender_id、chat_id、text；再运行process。这仅供本机演练和恢复，不是对外HTTP接口。`resolve --message-id xxx --reason "已核对原因"`保留审计后忽略问题消息；加--retry重新处理原消息。真正更正应补一条正确回报，不能直接改数据库。已确认费用更改、外部交易及跨日委托不在本版自动处理范围。

发送前先持久标记sending；异常后uncertain，重启不盲目重发。服务返回message_id仅表示平台接受，不证明用户看到了。sending/uncertain须人工核对，不能清空数据库来重试。

## 收盘净值与待完成接入

export生成opening.json/events.json，可直接给现有 `python -m quant.execution.manual_nav --opening ... --events ... --to YYYY-MM-DD --output 新目录 --rehearsal` 估值，读取现有行情、交易日历及公司行动输入。必须逐交易日收盘，下一日使用上次收盘state和当日新增events；发生补报或费用修订时从原始opening重算受影响日期。不能把持仓现金快照当作净值收益。当前后台未自动调度收盘任务；券商独立对账、公司行动同步与账本回写尚需连接，因而summary明确cash_and_nav_final=false。

尚未完成真实飞书双向联调、实盘策略选择与2分钟延迟验证、行情/停牌/涨跌停/权限的订单前检查、真实券商期初及日终对账、自动接入冻结策略订单、收盘调度、开机常驻部署。不得仅凭本轮测试开启真实操作。ETF与科创/创业板尚未纳入本版建议规则。
