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

默认通道在 [configs/notify.toml](../configs/notify.toml) 设置，例如：

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
3. 在 [configs/trading/manual_galaxy_100k.toml](../configs/trading/manual_galaxy_100k.toml) 填接收人的`sender_id`（open_id）和`chat_id`，设置`enabled=true`；保留`mode="rehearsal"`、`live_notifications=false`、`auto_trade=false`。
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

查看命令输出的每个`channel/ok/detail`，并在目标端核实。统一webhook接口目前只检查HTTP状态，未校验平台响应体业务码；HTTP成功不保证平台接受或用户收到。所有通道失败时也会写入`outbox`并可能返回退出码0，不能仅凭退出码判定送达；部分通道成功时，不会为其余失败通道自动补发。飞书双向适配另外校验业务码和message_id，但平台接受仍不等于用户已读，发送结果不明时不会盲目重发。

## 本地保存 App ID / Secret（Windows）

在项目根目录运行 `.\scripts\configure_feishu.ps1`，按提示输入App ID和Secret；Secret隐藏输入。同一命令可更新，留空保留原值；更换App ID时必须同时输入Secret。查看是否已配置：`.\scripts\configure_feishu.ps1 -Status`，不会显示密钥。

凭据以Windows当前用户DPAPI加密保存在 `configs/feishu.local.dpapi`，位于项目内并由Git忽略。同一Windows用户重启后仍能读取；换电脑或换运行账户需重新配置。它不是防范同一用户恶意程序的隔离机制。

飞书后台服务已自动读取本地凭据，无需每次设置环境变量。完整的FEISHU_APP_ID/FEISHU_APP_SECRET环境变量仍优先；只设置其中一个会报错，避免混用新旧凭据。更新后重启飞书服务生效。脚本仅保存凭据，不启用服务、不发消息，sender_id/chat_id和演练账户仍按上文配置。
