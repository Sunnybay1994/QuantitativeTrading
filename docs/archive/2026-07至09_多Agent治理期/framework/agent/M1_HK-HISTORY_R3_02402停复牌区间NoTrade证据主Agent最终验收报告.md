# M1 HK-HISTORY R3：02402 停复牌区间 No-Trade 证据主 Agent 最终验收报告

日期：2026-08-15
结论：**PASS（Windows 工程合同）；允许物化 UA-M1-004 业务证据并建立新的不可变 HK60 v2 plan**

## 验收结论

- `UA-M1-001 / 01065.HK@2026-05-05` 的 canonical raw、metadata、evidence identity 与 plan 行为保持不变。
- 新增 `UA-M1-004` 只接受任务书冻结的 `02402.HK`、13 个 no-trade 日、selector、record、source、
  suspension/resumption UTC、两条 HKEX notice 及 Tushare retained-zero-row 观察；`2026-05-04` 与范围外
  symbol/date/record 均 fail closed。
- `HKNoTradeEvidence.__post_init__`、Pandera dataframe check 与 raw canonical verifier 的范围一致；未知
  record、非 canonical JSON、raw/metadata/hash 漂移及 hostile 异常均稳定拒绝。
- 修改只影响 expected-key 证据闭包，没有放宽 raw mapper、OHLC、plan/receipt、策略、账户、公司行动或订单语义。
- `src/quant/domain/schemas.py` 中并发存在的 `DailyBasic1dSchema` 属于策略会话；本验收只评价并提交
  `datetime as dt` 与 `HKNoTradeEvidenceSchema` 的 M1 hunks，不替策略会话提交其余内容。

## 外部职责分离证据

- 实现：全新 Cursor 会话，`cursor-grok-4.6-high`；focused `196 passed, 2 skipped`，Ruff/mypy PASS。
- 独立初验：另一全新 Cursor 会话，`cursor-grok-4.6-high`；三目标文件开始/结束 SHA256 一致，focused
  `129 passed, 2 skipped`，新增 21 个未落盘对抗探针全部 PASS，Ruff/mypy PASS。
- 独立报告：`M1_HK-HISTORY_R3_02402停复牌区间NoTrade证据独立复验报告.md`。

## 主 Agent Windows 验证

```text
D:\Miniforge3\python.exe -m pytest tests/unit/test_hk_history_backfill.py -q --tb=short --basetemp <project-local>
129 passed, 2 skipped

D:\Miniforge3\python.exe -m ruff check <M1 two production files + focused test>
All checks passed!

D:\Miniforge3\python.exe -m mypy <M1 two production files>
Success: no issues found in 2 source files
```

首次使用默认 `%TEMP%\pytest-of-mbw` 时，Codex 沙箱账户在 fixture 建立前被 Windows ACL 拒绝；第二次指定的
basetemp 父目录尚未创建，同样只产生 setup error。创建项目内唯一父目录后，上述真实测试取得明确绿色终态；
前两次不计产品失败或通过证据。

## 剩余工作

本报告只关闭代码合同。主 Agent仍须：用 canonical bytes 物化 retained raw/metadata 与 13 项 evidence；新建
不可变 v2 plan/journal；先执行零网络 recover；再按一小时限频补齐剩余请求；8/8 后按已冻结顺序发布并 fresh
加载 HK60 v3。按用户当前指示不执行 Linux Gate。
