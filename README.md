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

浏览器打开 [投研工作台](http://127.0.0.1:8768/)。服务仅监听本机；已注册下述登录任务时，登录后自动恢复，否则需手动启动。

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

曲线下的期间报告展示冻结配置中的训练设置、评估范围及实际保存净值覆盖，下载 HTML 保留相同说明和证据路径。未保存的训练首末日显示未知；逐年历史回放不自动视为独立测试，模拟净值的前向独立性须结合候选冻结记录核验。

运行卡片区分实际运行、时间片结束、每日观察避让、其他写入任务占用、重试冷却及故障；显示最近进度保存时间、Windows 计划任务下次触发时间和重试条件。进程或调度读取失败时明确标为未知，计划触发不保证立即开工。

研究结果支持按策略标签搜索，并显示研究保留复核结论、原判定和风险原因。每日观察提示会区分数据维护、风险核对及流程错误，说明所需处理。

各因子／策略报告提供“1x成本：年度与月度结果”入口，列出收益、沪深300／中证500全收益超额、夏普和最大回撤；月表按年份拆分。结果登记时自动生成，也可运行 `python -m quant report periods` 从已保存净值补写历史报告；无完成净值的记录明确标为不适用，不重跑回测、不改变原准入结论。

研究结果默认折叠同源报告、公共对照及已验证三档成本逐日净值与资金记录相同的结果；可展开原始记录，或切换“全部原始记录”。分组不合并结论，不代表独立策略数量，缺少净值证据不折叠。

新建因子评估流水线在成本回放前核对全历史排序、缺失位置及方向，对同批次等价信号复用完成的回放，独立统计检验与准入结论保留。流水线报告记录复用数量与节省的版本×成本回放数，因子目录的 `reuse.json` 保留来源和文件校验。中断后从原目录恢复；旧批次沿用原执行方式。

已注册的一轮跨股票样本搜索见 `configs/research/gp_cross_stock_v1.toml`：当前未完成批次之后，调度只创建一个采用三组各300只股票的新批次，以最弱组IC评分；恢复时使用原样本及冻结目标。三组都用于训练，历史对照不冒充独立验证；正式准入仍走原电池与三档成本。

研究结果中的“报告 · 年/月表现”直接打开完整 HTML：保留原报告结论，并展示该变体 1× 成本的策略说明、年度与月度收益、夏普和回撤；默认对照中证500全收益指数，与曲线面板默认口径一致。无净值的结果继续链接原报告。R8 容量回放曲线按实际保存资金档显示，历史大资金敏感性结果不代表10万元账户。

飞书人工交易演练：`python -m quant paper manual demo --output artifacts/manual/demo_new`。支持固定格式回报、部分成交、费用确认、重复去重和重启恢复；真实飞书需绑定后联调，当前不是实盘服务。详见[运行说明](docs/MANUAL_EXECUTION_OPERATIONS.md)。

## 消息通知：接入与使用

当前实现如下；“已实现”表示代码支持，不表示本机已经配置或完成真实送达联调。当前 `configs/notify.toml` 的 `channels=[]`，统一通知默认只写本地文件。

|接口|配置/入口|已实现范围|
|---|---|---|
|邮件 SMTP|`email`|发送纯文本邮件，STARTTLS，可选账号认证；不接收邮件回报|
|企业微信群机器人|`wecom`|HTTPS webhook 单向文本通知；不接收群内回复|
|飞书群自定义机器人|`feishu`|HTTPS webhook 单向文本通知；不接收成交回复|
|个人微信 Windows 客户端|`wxauto`|精确选择指定群并发送文本；另有读取当前可见群消息的命令，未接入自动成交记账|
|飞书自建应用机器人|`paper manual`|长连接接收固定格式回复、发送演练建议/确认、持久账本、部分成交/费用确认/去重/恢复；目前仅演练|
|本地 outbox|自动回退|追加 `artifacts/notify/outbox.jsonl`，不代表对外送达，也不会自动补发|

### 单向通知的统一入口

在项目根目录执行，以下 `python` 指项目环境（本机 `D:\Miniforge3\python.exe`）：

```powershell
$env:PYTHONPATH = "$PWD\src"
$env:PYTHONUTF8 = '1'
# 只落本地文件，不发消息
python -m quant notify test --dry-run
# 配好通道后真实发送；--channel 可重复指定
python -m quant notify test --channel feishu
python -m quant notify send --channel feishu --channel email --title "投研状态" --body "日更已完成，请查看报告。"
```

默认通道在 [configs/notify.toml](configs/notify.toml) 设置，例如：

```toml
[notify]
enabled = true
channels = ["feishu"]
```

保留该文件其他配置段。`--channel`覆盖默认通道列表；`enabled=false`、空通道或`--dry-run`均写outbox。已有日更/挖掘脚本的通知调用会读取此配置；这不表示每个事件都会主动通知。Python调用为 `from quant.notify import send; send("标题", "正文", channels=["feishu"])`，可传 `config_path=Path(...)` 使用另一个配置文件。

### 各通道接入

**邮件**：配置SMTP服务与收发地址，密码使用邮箱的SMTP授权码或服务要求的凭据。

```powershell
$env:SMTP_HOST = 'smtp.example.com'
$env:SMTP_FROM = 'sender@example.com'
$env:SMTP_TO = 'recipient@example.com' # 多人用英文逗号分隔
$env:SMTP_USERNAME = 'sender@example.com'
$env:SMTP_PASSWORD = '<SMTP授权码>'
python -m quant notify test --channel email
```

当前使用STARTTLS，默认端口587，不支持直接以SSL方式连接465。端口由配置文件 `[email].smtp_port` 优先决定（现值587）；更换端口须修改该项，配置未提供端口时才读取 `SMTP_PORT`。host/from/username同样由非空配置值优先，`SMTP_TO`则覆盖配置收件人。

**企业微信 / 飞书群webhook**：在目标群添加对应机器人，取得HTTPS webhook，再设置其中一个环境变量并测试。

```powershell
$env:WECOM_WEBHOOK = '<企业微信群机器人HTTPS地址>'
python -m quant notify test --channel wecom
$env:FEISHU_WEBHOOK = '<飞书群机器人HTTPS地址>'
python -m quant notify test --channel feishu
```

当前仅发送文本载荷，不实现机器人签名计算；需签名的配置不能直接使用此接口。关键词等平台规则须由消息满足。标题加正文截到2000字符。此飞书webhook与下方自建应用机器人是两个独立入口。

**个人微信**：Windows Python 3.13安装可选依赖，微信登录并保持桌面解锁；群名须精确匹配。

```powershell
python -m pip install -e ".[wechat]"
$env:WXAUTO_GROUP = '量化通知测试群'
python -m quant notify test --channel wxauto
# 读取当前可见群消息，非完整历史库；不会自动解析为成交
python -m quant.reporting.wechat --group '量化通知测试群' --select read --contains '测试编号'
```

也可在配置 `[wxauto].group` 指定群名，非空时优先于环境变量。底层文件发送命令 `python -m quant.reporting.wechat --group '量化通知测试群' --select send --text-file message.txt` 默认预览；加`--execute`才真实发送。

上述 `$env:...` 只对当前PowerShell及其子进程有效。后台计划任务不会自动继承另一个终端临时设置的变量；需在实际任务运行账户/启动环境中配置并重新启动对应任务。不要把webhook、密码或App Secret提交到Git。

### 飞书双向人工交易演练

1. 创建飞书自建应用、启用机器人，配置发送消息与接收用户消息的权限及可用范围，订阅`im.message.receive_v1`并使用长连接，发布应用。无需公网回调地址；服务电脑须开机联网。
2. 安装 `python -m pip install -e ".[feishu]"`，在服务环境设置`FEISHU_APP_ID`、`FEISHU_APP_SECRET`。
3. 在 [configs/trading/manual_galaxy_100k.toml](configs/trading/manual_galaxy_100k.toml) 填接收人的`sender_id`（open_id）和`chat_id`，设置`enabled=true`；保留`mode="rehearsal"`、`live_notifications=false`、`auto_trade=false`。
4. 准备期初账户`opening.json`和交易日历数组`sessions.json`，初始化后启动：

```powershell
python -m quant paper manual init --opening opening.json --sessions sessions.json --account galaxy_rehearsal --sender ou_xxx --chat oc_xxx
python -m quant paper manual serve --send-rehearsal
# 另一个终端提交演练建议数组，后台发送并处理回复
python -m quant paper manual propose --file orders.json
python -m quant paper manual status
```

默认数据库为`artifacts/manual/galaxy_100k_rehearsal/session.sqlite`；重启沿用同一数据库，不重复init。如指定`--database`，放在init/serve等子命令之前。开户资金10万元只是计划值，期初文件必须表达当前演练账户事实。订单JSON字段及期初文件示例见[运行说明](docs/MANUAL_EXECUTION_OPERATIONS.md)。

在绑定的飞书会话中回复，例如：

```text
委托 O001 v1 券商单号=B123 数量=1000 限价=10.52 时间=09:31:05
成交 O001 v1 成交号=F456 本次数量=400 成交价=10.50 时间=09:31:18 费用=待核
未操作 O002 v1 确认未委托=是 原因=错过窗口
费用确认 O001 v1 成交号=F456 费用=5.00
```

O001等必须是本账户已登记建议；成交数量为本次增量。漏回复保持待确认，不推定未操作。所有消息标注演练，不下真实单；真实飞书联调、策略订单自动接入和日终对账尚未完成，也未为此服务注册登录启动任务。完整撤单/查单格式、离线demo及恢复见[运行说明](docs/MANUAL_EXECUTION_OPERATIONS.md)。

### 如何判断通知是否成功

查看命令输出的每个`channel/ok/detail`，并在目标端核实。统一webhook接口目前只检查HTTP状态，未校验平台响应体业务码；HTTP成功不保证平台接受或用户收到。所有通道失败时也会写入`outbox`并可能返回退出码0，不能仅凭退出码判定送达；部分通道成功时，不会为其余失败通道自动补发。飞书双向适配另外校验业务码和message_id，但平台接受仍不等于用户已读，发送结果不明时不会盲目重发。
