# M1 HK-INSTRUMENT-R3 官方资格类型解耦 ETF 行情 Gate 主 Agent 验证报告

日期：2026-07-18  
结论：**通过；available-history Gate 不再依赖待授权的 HKEX ETF Instrument 行**

## 1. 变更与理由

`ConnectEligibilitySnapshotSchema` 和 `ConnectEligibilityEventSchema` 已把交易所资格事实中的
`security_type` 固定为 `STOCK/ETF/OTHER`。本次让 available-history Gate 合并两条 Route 的已验证事实，
优先用非 `OTHER` 官方类型分类；只有官方类型为 `OTHER` 或缺失时才回退 HK Instrument。

- 官方 ETF 可在缺少 Instrument 行时合法排除；若 Instrument 存在但标为 STOCK，则引用冲突。
- 官方 STOCK 仍必须存在 Instrument 且类型为 STOCK，以保留 `list_date/delist_date` 的权威职责。
- 同一证券在任意 Route/快照/事件中出现 STOCK/ETF 冲突时 fail closed。
- 所有资格 Parquet 逐文件通过领域 Schema；引用缺失、类型冲突或不可信时稳定返回
  `BAR_WINDOW_REFERENCE_INVALID`。

该变更只解除“为了从行情 Gate 排除 ETF 而采集 HKEX 网页主表”的错误耦合，不宣称 31 个暂存 ETF
Instrument 的来源合规，也不关闭完整 HK Instrument/M1 Gate。

## 2. 对抗性验证

新增并通过以下反例：官方 ETF 且无 Instrument 行可排除；官方 ETF 与 Instrument STOCK 冲突失败；
跨 Route STOCK/ETF 冲突失败；官方 STOCK 缺 Instrument 失败；官方 OTHER 回退 Instrument ETF。
既有上市日、退市日、非开市日、结构性短历史和精确 session 测试保持通过。

## 3. 验证结果

WSL Miniforge `base` 与 Windows Miniforge `base`：

```text
pytest tests/unit/test_query_universe.py -q
14 passed
ruff check src/quant/data/query.py src/quant/data/query_universe.py tests/unit/test_query_universe.py
All checks passed
```

WSL 定向 mypy：`Success: no issues found in 2 source files`。仅有既存 Pandera/Polars deprecation warning。
随后在 WSL/Windows 各运行 `test_query.py + test_query_universe.py + test_tushare_connector.py` 扩展定向回归，
均为 `71 passed`。

真实 clean/reference 数据上，SH_CONNECT 与 SZ_CONNECT 均得到：

```text
eligible=644, required_stocks=613, excluded_etfs=31,
structurally_short=11, missing_session_total=36374,
unexpected_session_total=0, complete=false
```

两条 Route 按预期返回 `BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE`：当前阻塞是 60 日行情尚未回填，
不是 ETF Instrument 引用错误。`02983.HK` 仍按一日结构性短历史计算。

## 4. 剩余风险

- 31 个 ETF 的完整 Instrument 记录仍需有明确授权的数据源后才能支撑完整 HK Instrument/M1 Gate；既存
  HKEX 网页 raw/clean 只保留为历史证据，不得扩大使用。
- 港股 60 日 raw/clean 尚未完成；R3 没有降低行情完整性或精确 session Gate。
- 当前资格类型是全市场身份属性；未来若上游出现真实类型变更，现有冲突策略会 fail closed，需先审查
  领域契约而不是静默覆盖。
