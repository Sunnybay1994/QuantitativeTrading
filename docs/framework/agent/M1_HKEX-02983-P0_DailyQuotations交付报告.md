# M1-HKEX-02983-P0 Daily Quotations 交付报告

日期：2026-08-02（Asia/Shanghai）

## 交付

新增独立 `quant.data.hkex_daily_quotations`，严格识别 HKEX 报告日期、QUOTATIONS、
SALES RECORDS FOR ALL STOCKS、目标 code/name/currency 与销售阶段标记。本模块无网络、
无路径发现、无 Tushare 依赖，只消费调用者显式传入的 retained bytes。

两阶段合同分为可公开构造的 `ParsedHKEXDailyQuotation` 和不可公开构造的
`VerifiedHKEXDailyQuotation` final 结果类型；其公开 constructor 失败，`__init_subclass__` 无条件拒绝
所有子类。正式 exact-type Verified 只由模块内工厂在 retained-byte verifier 完成全部重验后产生：入口内部
fresh 计算 raw hash/size、严格 parse，再闭合 volume、OHLC、last price 和版本化整 HKD
`ROUND_HALF_UP` turnover，并强制冻结的官方 URL/raw SHA/raw size。公开 verifier 不再接受 Parsed。
返工后，即使合成 Parsed 填入官方 SHA/size 并重算 parsed/evidence identity，或破坏 sales volume 后
再次重算所有 identity，也不能通过公开构造或 verifier 获得 Verified。二次返工还覆盖 hostile 子类覆盖
`__new__` 为 `object.__new__`、在 `__init__` 写 `__dict__` 的两类（闭合/不闭合）payload；类定义阶段即
fail closed，不能产生任何 `isinstance` capability。全项目搜索未发现模块外 public consumer；未来消费者
必须接受 exact final type 并 fresh 核对，不得把普通子类/可变对象的 `isinstance` 当作来源证明。

## 真实 raw 只读证据

对 `artifacts/hkex_probe/d260710e.htm` 实算并验真成功：

```text
raw_size=32792632
raw_sha256=67d1109fe358021543579a6cb5f26c2a31c47f8feae6543e451f8356efcec5b8
source=HKEX_DAILY_QUOTATIONS
source_record_id=HKEX_DAILY_QUOTATIONS:2026-07-10:2983
previous_close=16.10 open=16.53 high=17.17 low=15.64 close=16.57
quotation_volume=2640331 quotation_turnover_whole_hkd=43420387
sales_record_count=944 sales_volume=2640331 sales_turnover=43420387.430
flag_counts={empty:764,D:4,U:4,X:17,Y:155}
turnover_rounding_version=hkex-turnover-whole-hkd-round-half-up-v1
evidence_id=c46f614dcea919b7beb4aaddd7a03e4b801dcb937e40d3262124d019b264f4da
```

`X` 17 笔在完整 raw 中实算合计 10,080 股，本 parser 不丢弃任何 X 记录。本证据的
source 始终为 HKEX，没有伪装为 Tushare。

## 验证和状态边界

开发 fixture 覆盖严格成功与 fail-closed 反例。

- Windows Miniforge：Ruff 通过，mypy `Success: no issues found in 2 source files`；新模块加
  既有 HK history/CLI 回归 `42 passed, 1 skipped`（新模块 `23 passed`；已知 Windows symlink
  权限用例跳过）。
- WSL Miniforge base：Ruff 通过，mypy `Success: no issues found in 2 source files`；同组
  `43 passed`（新模块 `23 passed`）。
- 真实 raw 在 Windows 与 WSL base 分别只读验真，产生相同 evidence ID
  `c46f614dcea919b7beb4aaddd7a03e4b801dcb937e40d3262124d019b264f4da`。

本包没有写 formal raw/clean/journal，没有调用网络，没有接入
HK history finalize。因此它只关闭 `02983.HK@2026-07-10` 的官方日线来源解析/
evidence 工程首包，不代表 HK60、M1 或任何 formal Gate 已关闭。
