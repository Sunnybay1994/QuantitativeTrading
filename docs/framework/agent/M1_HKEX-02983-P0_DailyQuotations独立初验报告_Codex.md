# M1-HKEX-02983-P0 Daily Quotations 独立初验报告

日期：2026-08-02（Asia/Shanghai）

角色：未参与实现的独立只读初验
结论：**FAIL，必须返工后复验**

## 阻塞问题：公开 Verified 构造可绕过 raw 来源与成交闭包

### 现象

`VerifiedHKEXDailyQuotation(...)` 是公开 dataclass 构造。独立探针从一个自洽的合成 raw
取得 `ParsedHKEXDailyQuotation`，把其中 `raw_sha256/raw_size` 换成冻结的官方常量并按公开字段
重算确定性 identity 后，公开构造成功产出 `VerifiedHKEXDailyQuotation`。该合成 raw 与真实 retained
raw 内容无关。

同一探针再把 `sales_volume` 从 680 改为 681、保持 quotation volume 为 680 并重算 parse identity，
公开构造仍成功；相同对象经 `verify_hkex_daily_quotation` 会正确返回
`HKEX_DAILY_QUOTATIONS_NOT_CLOSED`。因此 public verifier 与 public constructor 的 Verified 语义不一致。

### 根因

`VerifiedHKEXDailyQuotation.__post_init__` 仅 fresh 重建 Parsed、检查官方 URL/hash/size 常量和
`evidence_id`。它既不持有或重新解析 raw bytes，也没有执行 verifier 中的 volume、OHLC、last price、
turnover 闭包。SHA-256 是调用者可填写的普通字段；确定性 content identity 只能证明字段自洽，不能证明
这些字段来自对应 raw。

### 应遵循规则

任务单要求：合成 raw 即使 digest 自洽也只能 parse；任何公开 Verified 构造和 verifier 都必须 fresh
强制官方 URL/hash/size，结构篡改必须失败。`VerifiedHKEXDailyQuotation` 的所有公开产生路径还必须具有
同一 sales-to-quotation 闭包语义。

### 最小复现

1. 解析测试 `_raw()` 获得自洽 Parsed。
2. 复制全部字段，将 raw hash/size 替换为官方常量。
3. 按模块冻结的 canonical payload 算法重算 `parsed_id` 和 `evidence_id`。
4. 调用 `VerifiedHKEXDailyQuotation(evidence_id=..., evidence=...)`；当前被接受。
5. 将 `sales_volume` 改成与 `volume` 不同并再次重算 identity；当前仍被公开构造接受。

### 必须新增的测试

- 自洽合成 raw 的 Parsed 即使填入官方 hash/size 并重算全部 identity，也不得经任何公开构造成为 Verified。
- identity 自洽但 volume、open、high、low、close、last price 或 turnover 任一不闭合时，所有公开 Verified
  产生路径必须拒绝。
- 测试不得依赖“攻击者忘记重算 parsed_id/evidence_id”才失败。

### 通过条件

公开 API 只能通过对调用者提供的 raw bytes 重新计算 size/hash、严格 parse 并完成成交闭包来产生 Verified；
或公开类型没有可绕过 verifier 的普通构造入口。返工后上述两类探针均稳定失败，再由新的独立会话复验。

## 通过的核对项

- quotation 与 sales section 中 `02983` 目标行缺失或重复均 fail closed。
- 错误 URL/hash 输入被拒绝；真实 retained raw 的 size/hash 与冻结常量一致。
- `7060.4999 -> 7060`、`7060.5000 -> 7061`、`7060.5001 -> 7061`，ROUND_HALF_UP 边界正确。
- Windows 与 WSL base 对真实 raw 均只读验真：944 笔、volume 2,640,331、sales turnover
  43,420,387.430、evidence ID `c46f614dcea919b7beb4aaddd7a03e4b801dcb937e40d3262124d019b264f4da`。
- 模块未发现网络、Tushare、RawStore/CleanStore 或目录发现依赖。

## 验证摘要

- Windows Miniforge：定向 Ruff PASS；mypy PASS；pytest `18 passed`。
- WSL Miniforge base：定向 Ruff PASS；mypy PASS；pytest `18 passed`。
- Windows 与 WSL 均完成真实 retained raw 的只读内存验真；未发起网络请求。

本结论只针对 M1-HKEX-02983-P0 初验，不表示 HK history、HK60、M1 或其他 formal Gate 状态。
