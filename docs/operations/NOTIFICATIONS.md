# 消息通知：接入与使用


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

默认通道在 [configs/notify.toml](../../configs/notify.toml) 设置，例如：

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
3. 在 [configs/trading/manual_galaxy_100k.toml](../../configs/trading/manual_galaxy_100k.toml) 填接收人的`sender_id`（open_id）和`chat_id`，设置`enabled=true`；保留`mode="rehearsal"`、`live_notifications=false`、`auto_trade=false`。
4. 准备期初账户`opening.json`和交易日历数组`sessions.json`，初始化后启动：

```powershell
python -m quant paper manual init --opening opening.json --sessions sessions.json --account galaxy_rehearsal --sender ou_xxx --chat oc_xxx
python -m quant paper manual serve --send-rehearsal
# 另一个终端提交演练建议数组，后台发送并处理回复
python -m quant paper manual propose --file orders.json
python -m quant paper manual status
```

默认数据库为`artifacts/manual/galaxy_100k_rehearsal/session.sqlite`；重启沿用同一数据库，不重复init。如指定`--database`，放在init/serve等子命令之前。开户资金10万元只是计划值，期初文件必须表达当前演练账户事实。订单JSON字段及期初文件示例见[运行说明](MANUAL_EXECUTION_OPERATIONS.md)。

在绑定的飞书会话中回复，例如：

```text
委托 O001 v1 券商单号=B123 数量=1000 限价=10.52 时间=09:31:05
成交 O001 v1 成交号=F456 本次数量=400 成交价=10.50 时间=09:31:18 费用=待核
未操作 O002 v1 确认未委托=是 原因=错过窗口
费用确认 O001 v1 成交号=F456 费用=5.00
```

O001等必须是本账户已登记建议；成交数量为本次增量。漏回复保持待确认，不推定未操作。所有消息标注演练，不下真实单；真实飞书联调、策略订单自动接入和日终对账尚未完成，也未为此服务注册登录启动任务。完整撤单/查单格式、离线demo及恢复见[运行说明](MANUAL_EXECUTION_OPERATIONS.md)。

### 如何判断通知是否成功

查看命令输出的每个`channel/ok/detail`，并在目标端核实。统一webhook接口现在同时检查HTTP状态和平台业务码；平台接受仍不保证用户已读。所有通道失败时也会写入`outbox`并可能返回退出码0，不能仅凭退出码判定送达；部分通道成功时，不会为其余失败通道自动补发。飞书双向适配另外校验业务码和message_id，但平台接受仍不等于用户已读，发送结果不明时不会盲目重发。

## 交互式接入向导（Windows）

在项目根目录运行：

```powershell
.\scripts\configure_feishu.ps1
```

1. 输入App ID和Secret；Secret隐藏输入，已有同一应用可留空保留。
2. 向导验证应用身份。按提示在飞书后台配置长连接、订阅`im.message.receive_v1`、开启消息接收权限并发布应用，再按回车。
3. 等待显示“连接成功”和随机口令，再将口令发给机器人；群聊需 @机器人。
4. 向导自动读取sender_id/chat_id，核对后输入`y`保存。失败、超时或取消不覆盖原配置，可重新运行。

查看状态：`.\scripts\configure_feishu.ps1 -Status`。也可执行 `python -m quant.notify.feishu_setup`。配置状态不代表服务在线。

凭据和绑定一起以当前Windows用户DPAPI加密保存到项目内 `configs/feishu.local.dpapi`，Git忽略。同一用户重启后可读取，换电脑或账户需重新配置。启动向导前清除FEISHU_APP_ID/FEISHU_APP_SECRET临时变量，避免服务优先读取旧环境凭据。

向导不发送消息、不初始化假定余额、不启用交易。服务配置sender_id/chat_id都为空时，会自动读取加密绑定；显式配置仍优先，不能只填一个。初始化演练账户仍需将向导显示的两个ID传入init；已初始化账户不自动更换绑定。服务凭据必须与本地绑定属于同一应用，更新后重启服务。其他启动步骤见上文。

## 看板管理通道

打开看板 → 消息通知。邮件、企业微信、飞书群webhook、个人微信支持配置保存、启停自动通知及单独发送测试。敏感输入不回显，留空保留已有值。单向通道按需发送，不存在后台回复监听进程。

普通通道设置加密保存在`configs/notify.local.dpapi`，Git忽略，覆盖同名通道的文件配置；默认启用列表同步被覆盖。配置文件`notify.enabled=false`仍为总开关。SMTP_TO环境变量仍覆盖邮件收件人。未配置通道可折叠，不必全部填写。

飞书应用卡片支持验证保存凭据、5位口令绑定并确认、启动/停止消息监听。身份和凭据保存在原`configs/feishu.local.dpapi`，不会通过API返回Secret。绑定前先停止消息监听，避免多连接分流事件。配置和启停接口仅接受本机同源、页面令牌与有长度限制的JSON请求。

“发送交易演练测试”仅向已绑定会话发送明确标注“不要下真实单”的虚构订单。收到的消息和固定格式解析显示在页面，并自动回复接收确认；**这些回报未核对券商事实，不更新演练或实盘账户**。完整账户服务仍使用原`paper manual serve`，不要对同一个应用同时运行两个接收服务。

监听进程独立于网页，关闭页面不会停止；点“停止监听”停止进程。电脑重启后需要重新启动监听，本版尚未注册自动启动任务。进程状态与连接状态分别显示；失败会显示错误类型并尝试重连。消息和回执存放在`artifacts/notify/console/receipts.sqlite`，保留消息ID去重；发送结果不明不盲目重发。看板展示最近30条，其他记录留在数据库。旧版测试消息标为历史记录，不自动补发回执。
