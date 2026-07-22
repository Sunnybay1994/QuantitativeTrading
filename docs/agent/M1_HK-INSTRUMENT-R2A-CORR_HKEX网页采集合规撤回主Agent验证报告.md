# M1 HK-INSTRUMENT-R2A-CORR HKEX 网页采集合规撤回主 Agent 验证报告

日期：2026-07-18  
结论：**撤回 R2A 通过结论；公共网页 connector 已 fail closed**

## 1. 现象与根因

R2A 最初通过 HKEX ETP 页面动态 token 调用其前端 JSONP 端点，技术上完成了 31 个 ETF 的 raw/clean
闭包。后续核验 HKEX 现行 Terms of Use（最后更新 2025-08-19）发现，第 5 节明确禁止未经书面许可的
programmatic/scripted/mechanical access、systematic retrieval、web scraping，以及由网站信息创建数据库。

根因是任务冻结时只核对了接口真实性、字段和安全边界，没有在生产采集前核对数据许可与允许的程序化
交付渠道。被破坏的不变量是：**技术上可访问不等于被授权作为生产数据源采集和持久化。**

## 2. 应遵循规则与修正

- HKEX 公共页面可用于人工核验单项事实，但不得由本项目连接器脚本化抓取或系统性建库。
- HKEX 官方 FAQ 说明，允许程序化下载的是已订阅 Historical Data 产品后的正式 API。
- `HkexEtpConnector.fetch_etp_instruments` 现固定返回 `HKEX_ETP_LICENSE_REQUIRED`，在报错前不会访问
  网络或写 raw/clean。
- 保留既有 raw 与报告作为不可变历史证据，不继续扩大使用、不删除或伪装来源；当前 clean 中 31 个 ETF
  的引用覆盖只能视为待替换的暂存状态，不能支撑 R2A 或 M1 Gate 通过。
- 后续只能接入留有许可证据的 HKEX licensed adapter，或改用已授权且明确允许本项目用途的数据供应商。

## 3. 最小复现与通过条件

最小复现：向默认 `HkexEtpConnector` 注入会记录请求的 mock client，再调用单一目标；期望稳定抛出
`HKEX_ETP_LICENSE_REQUIRED` 且请求计数为零。

通过条件：

1. 默认 connector 零网络、零写入 fail closed；
2. CLI 文档明确许可前置条件，不再描述网页 token/JSONP 为可用生产路径；
3. R2A 任务和原验证报告显式标记撤回，保留现象—根因—规则—测试—通过条件链；
4. 31 个 ETF 的合规来源重新闭环前，Instrument/M1 Gate 不得宣布通过。

后续 R3 已让 available-history Gate 优先使用官方资格事实中的 `security_type` 排除 ETF，因此该特定行情
Gate 不再依赖这些暂存 Instrument 行；本条仍适用于完整 HK Instrument/M1 Gate，不能误读为恢复 R2A。

## 4. 验证结果

WSL Miniforge `base` 与 Windows Miniforge `base` 均运行：

```text
pytest tests/unit/test_hkex_etp_connector.py \
       tests/unit/test_hkex_etp_instruments.py \
       tests/unit/test_update_instruments.py -q
21 passed
```

两端 Ruff 通过；WSL 对 connector 与 CLI 的定向 mypy 通过。mock 对抗测试确认默认 connector 抛出
`HKEX_ETP_LICENSE_REQUIRED` 且网络请求计数为零。仅有既存 Pandera/Polars deprecation warning。

权威依据：HKEX `Terms of Use` §5 与 `Getting Market Data` FAQ 中关于订阅历史产品及正式 Programmatic
Data Download API 的说明。
