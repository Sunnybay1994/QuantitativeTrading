# M1-HKEX-02983-P0 Daily Quotations 任务单

日期：2026-08-02（Asia/Shanghai）

状态：**返工独立复验与主 Agent 最终验收 PASS；仅关闭 retained Daily Quotations 证据工程合同，不关闭正式 02983 bar、HK60 或 M1 Gate。**

## 目标与边界

对已留存的 HKEX Main Board `d260710e.htm` 建立独立、严格的 Daily Quotations
parser/verifier，只产出 `02983.HK@2026-07-10` 的 typed verified evidence。本包不写
formal raw/clean/journal，不接 HK history finalize，也不把 HKEX 记录改写成 Tushare。

## 冻结来源与记录

- source：`HKEX_DAILY_QUOTATIONS`
- URL：`https://www.hkex.com.hk/eng/stat/smstat/dayquot/d260710e.htm`
- raw size：`32,792,632`
- raw SHA-256：`67d1109fe358021543579a6cb5f26c2a31c47f8feae6543e451f8356efcec5b8`
- report/date：`QUOTATIONS` + `SALES RECORDS FOR ALL STOCKS`，`10 JUL 2026 (FRIDAY)`
- record：code `2983`，name `HESAI-W`，currency `HKD`，symbol `02983.HK`

parser 只接受目标记录实际出现的 flag 集 `{empty,D,U,X,Y}`；其他 prefix、无法解释的
字符或销售阶段骨架漂移一律 fail closed。允许的 HTML 非业务内容只有报告自身固定
分页 tag。

## 闭包规则

quotation 行提供 previous close/close/high/low/volume/turnover；open 只取按报告顺序的
sales records 首笔。全部 sales records 重算 record count、volume、turnover、min/max、
first/last price，并同 quotation 摘要闭合。

sales turnover 保留完整 Decimal；quotation `TURNOVER ($)` 为整 HKD，以显式版本
`hkex-turnover-whole-hkd-round-half-up-v1` 将逐笔合计 `ROUND_HALF_UP` 到整 HKD 后精确比较。
不使用浮点、容差或隐式猜测。

parse identity 绑定 raw SHA/size、source URL/record、date/symbol/code/name/currency、parser 和
turnover rounding 版本及全部重算摘要；verified evidence identity 再绑定 parse identity 与
关键来源身份。`ParsedHKEXDailyQuotation` 可承载自洽 fixture 以验证 parser；公开
`VerifiedHKEXDailyQuotation` 是不可直接构造且由 `__init_subclass__` 禁止任何子类的 final 结果类型，
正式 exact-type 实例只能由接收 retained raw
bytes 的公开 verifier 产生。verifier 必须在内部 fresh 计算 raw hash/size、严格 parse、执行全部
成交闭包，并强制官方 URL、`EXPECTED_RAW_SHA256` 与 `EXPECTED_RAW_SIZE`。Parsed 对象不是
任何公开 Verified 入口的输入。合成 Parsed 即使把官方 hash/size 填入并重算全部 identity，或再破坏
sales closure 并重算 identity，也不能成为官方 Verified evidence。任何消费者若未来接入，只能接受
公开 retained-byte verifier 返回的 exact final type，并 fresh 核对不变量；不得仅凭可变对象或子类的
`isinstance` 结果建立信任。

## 反例与验收

覆盖 date/code/name/currency/URL/raw SHA 漂移，未知 flag，缺 section，volume/turnover/
open/high/low/close 任一不闭合，`.5000` 半元边界、重算身份的伪造 Parsed，以及 hostile 子类覆盖
`__new__`/`__init__` 并写 `__dict__` 的构造绕过。Windows 与
WSL base 分别运行定向 Ruff、mypy、pytest；另对真实留存 raw 做一次只读内存验真。
