# M1 HK-INSTRUMENT-R2A HKEX ETP 权威补全主 Agent 验证报告

日期：2026-07-18  
结论：**已撤回**；技术验证通过不能替代数据许可，31 个目标 ETF 的生产来源仍待合规闭环

> 2026-07-18 后续审计发现 HKEX 公共网站现行条款禁止未经书面许可的程序化/脚本化访问、系统性抓取
> 和建库。下述内容只保留为历史技术证据，不再构成 Gate 通过结论；网页 connector 已改为
> `HKEX_ETP_LICENSE_REQUIRED` fail closed。纠正报告：
> [`M1_HK-INSTRUMENT-R2A-CORR_HKEX网页采集合规撤回主Agent验证报告.md`](M1_HK-INSTRUMENT-R2A-CORR_HKEX网页采集合规撤回主Agent验证报告.md)。

## 1. 实现

- 新增窄 `HkexEtpConnector`，每次从 HKEX 官方 ETP 页面动态解析当前 token，再调用官方 JSONP
  数据端点；HTTP 错误归一为不含 URL/token 的稳定错误。
- JSONP 完整匹配 callback，JSON 拒绝重复 key 和非有限数，响应失败或结构漂移 fail closed。
- connector 只保留显式目标的原始行；mapper 按 UTC epoch 毫秒解析日期，对每个目标选择
  `trade_date <= as_of` 的最新记录并拒绝同日身份冲突。
- 只接受 HKD `ETFs` 和严格正整数 board lot；输出通过 `InstrumentSchema`。
- 专用 pipeline 在 mapper/Schema 之前先写不可变 raw，metadata 绑定 as-of、完整目标集合和
  `latest_trade_date_lte_as_of_v1`，不含 token。
- `update_instruments` 增加 `--source hkex-etp --as-of --symbols`；既有 Tushare/BaoStock 路径不变，
  携带 HKEX 专属参数时 fail-fast。

## 2. 自动验证

Windows Miniforge 与 WSL Miniforge `base` 均执行：

```text
pytest tests/unit/test_hkex_etp_connector.py \
       tests/unit/test_hkex_etp_instruments.py \
       tests/unit/test_update_instruments.py -q
24 passed
```

同一白名单 Ruff 通过；WSL 定向 mypy 通过。对抗性覆盖动态 token 中被注释的样例返回、缺/多 token、
callback 不符、尾随垃圾、重复 JSON key、`NaN`、失败响应、future-only、缺失目标、同日身份冲突、
错误币种/类别、零或浮点 lot、UTC 日期、mapper 失败后 raw 已留存且 clean 字节不变，以及成功 upsert
不覆盖既有股票。

## 3. 真实发布证据

生产命令精确绑定 `as_of=2026-07-10` 与 31 个目标，只执行一次：

- snapshot id：`120813.813763Z-d550bd13c064`
- raw：`data/raw/hkex/instrument_etp/date=2026-07-18/120813.813763Z-d550bd13c064.parquet`
- raw 行数：1900；目标代码数：31
- raw SHA-256：`47403b87db139f89a4f4b5e2f3874e7929a1dd07641dbf1df148f2c9bc3f94bd`
- metadata 所载 SHA-256 与文件实算值一致；metadata 不含 `token`
- 本次 clean 输入：31 行；发布后 HK Instrument：3281 行，其中 ETF 31 行
- clean SHA-256：`cef830f83ba6d2c6d51f9dee127518325948713b56cbda327092986258641d56`
- 发布后 HK 全表通过 `InstrumentSchema`

真实探针与发布数据均证明 31/31 个目标在 2026-07-10 有唯一无冲突的最新行，币种均为 HKD、类别均
为 `ETFs`。

## 4. Gate 与剩余风险

重新运行双 Route `--require-available-history`：

```text
SH_CONNECT -> BAR_WINDOW_REFERENCE_INVALID
SZ_CONNECT -> BAR_WINDOW_REFERENCE_INVALID
```

这符合冻结边界：ETF 引用已全部补齐，但 `02983.HK` 临时股票柜台仍没有 Instrument。下一步必须按
HKEX 交易安排和最终生效公告投影其 `2026-07-10` 至 `2026-08-13` 生命周期，不能用 `02525.HK`
替代，也不能把 2026-08-17/24 的证书或 CCASS 截止日误作最后交易日。

本报告不宣布 HK60 available-history Gate 或 M1 里程碑通过。
